"""Startup-Prüfungen nach Bootstrap (z. B. Loxone-Smoke-Test, Tarif-Plausibilität)."""
from __future__ import annotations

import logging
import sys

from house_config.tariff_plausibility import (
    collect_tariff_plausibility_errors,
    format_tariff_plausibility_errors,
)
from integrations.loxone_connectivity import loxone_env_configured, verify_loxone_setup
from runtime_store.env_vars import read_env
from runtime_store.persist_paths import (
    resolve_backtesting_scenarios_json_path,
    resolve_tariffs_json_path,
    resolve_tariffs_schema_template_path,
)

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_flag(suffix: str, *, default: bool = False) -> bool:
    raw = read_env(suffix)
    if not raw:
        return default
    return raw.lower() in _TRUTHY


def run_loxone_verify_on_startup() -> None:
    """
    Liest alle konfigurierten Loxone-IOs (ohne FTP/Roundtrip).

    Standard: einmal pro Worker-Start nach Deploy/Neustart.
    Fehler werden geloggt; der Betrieb läuft weiter.

    EARNIE_SKIP_LOXONE_VERIFY=1 → überspringen
    EARNIE_VERIFY_LOXONE_ON_START=0 → überspringen
    EARNIE_STRICT_LOXONE_VERIFY=1 → bei Fehler mit Exit-Code 1 abbrechen
    """
    if _env_flag("SKIP_LOXONE_VERIFY"):
        logger.info(
            "Loxone-Startup-Prüfung übersprungen (EARNIE_SKIP_LOXONE_VERIFY)."
        )
        return
    if not _env_flag("VERIFY_LOXONE_ON_START", default=True):
        logger.info(
            "Loxone-Startup-Prüfung übersprungen "
            "(EARNIE_VERIFY_LOXONE_ON_START=0)."
        )
        return
    if not loxone_env_configured():
        logger.info(
            "Loxone-Startup-Prüfung übersprungen (LOXONE_* in .env nicht vollständig)."
        )
        return

    try:
        ok, results = verify_loxone_setup()
    except (FileNotFoundError, ValueError, KeyError) as exc:
        logger.error("Loxone-Startup-Prüfung: ungültige Konfiguration: %s", exc)
        if _env_flag("STRICT_LOXONE_VERIFY"):
            raise SystemExit(1) from exc
        return

    failed = 0
    for item in results:
        target = f" ({item.io_name})" if item.io_name else ""
        if item.passed:
            logger.info("[loxone-verify] OK %s%s: %s", item.label, target, item.detail)
        elif item.severity == "warning":
            logger.warning(
                "[loxone-verify] WARNUNG %s%s: %s", item.label, target, item.detail
            )
        else:
            failed += 1
            logger.error(
                "[loxone-verify] FEHLER %s%s: %s", item.label, target, item.detail
            )

    if ok:
        logger.info(
            "Loxone-Startup-Prüfung: alle %s Prüfungen erfolgreich.", len(results)
        )
        return

    message = (
        f"Loxone-Startup-Prüfung: {failed} von {len(results)} Prüfungen fehlgeschlagen."
    )
    if _env_flag("STRICT_LOXONE_VERIFY"):
        logger.error("%s Abbruch (EARNIE_STRICT_LOXONE_VERIFY).", message)
        raise SystemExit(1)
    logger.error("%s Optimierung startet trotzdem.", message)


def run_tariff_plausibility_on_startup() -> None:
    """
    Validiert tariffs.json und Szenario-Referenzen beim Worker-Start.

    EARNIE_SKIP_TARIFF_VALIDATE=1 → überspringen
    EARNIE_STRICT_TARIFF_VALIDATE=1 → bei Fehler mit Exit-Code 1 abbrechen
    """
    if _env_flag("SKIP_TARIFF_VALIDATE"):
        logger.info(
            "Tarif-Startup-Prüfung übersprungen (EARNIE_SKIP_TARIFF_VALIDATE)."
        )
        return

    errors = collect_tariff_plausibility_errors(
        tariffs_path=resolve_tariffs_json_path(),
        scenarios_path=resolve_backtesting_scenarios_json_path(),
        schema_path=resolve_tariffs_schema_template_path(),
    )
    if not errors:
        logger.info("Tarif-Startup-Prüfung: tariffs.json plausibel.")
        return

    message = format_tariff_plausibility_errors(errors)
    if _env_flag("STRICT_TARIFF_VALIDATE"):
        logger.error(
            "%s Abbruch (EARNIE_STRICT_TARIFF_VALIDATE).", message
        )
        raise SystemExit(1)
    logger.error("%s Optimierung startet trotzdem.", message)


def main() -> int:
    """CLI-Einstieg (gleiche Logik wie beim Worker-Start)."""
    import config as cfg
    import logger_config
    from runtime_store.persist_paths import log_file

    cfg.reinit_config()
    logger_config.setup_logging(log_file=log_file(), level=logging.INFO)
    run_tariff_plausibility_on_startup()
    run_loxone_verify_on_startup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
