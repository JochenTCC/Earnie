"""
persist_paths.py – Pfade für persistente Laufzeitdateien (unter earnie_env/).
"""
from __future__ import annotations

import os

from runtime_store.env_vars import read_env
from runtime_store.persist_paths_base import (  # noqa: F401  (re-exported)
    _DEFAULT_ENV_ROOT,
    _LEGACY_CONFIG_DIR,
    _LEGACY_DOTENV,
    _LEGACY_DOTENV_IN_CONFIG,
    _LEGACY_RUNTIME_DIR,
    _config_dir_from_config_path_env,
    _effective_config_path_env,
    _env_path_explicit,
    _is_legacy_config_file_path,
    _path_is_under,
    _preferred_config_dir,
    _preferred_dotenv,
    _preferred_or_legacy_file,
    _preferred_runtime_dir,
    config_dir,
    config_path,
    cons_data_pending_file,
    consumer_state_file,
    consumption_profiles_file,
    daemon_stdio_log_file,
    default_config_dir,
    env_root,
    flexible_consumer_profiles_file,
    log_file,
    power_interval_sampler_state_file,
    pv_counter_state_file,
    resolve_backtesting_log_dir,
    resolve_config_prefixed_path,
    resolve_runtime_prefixed_path,
    resolve_uploads_dir,
    runtime_dir,
    runtime_path,
    total_consumption_profiles_file,
    usage_ping_state_file,
    feature_reviews_state_file,
)
from runtime_store.persist_paths_base import (  # noqa: F401  (re-exported)
    _config_directory_from_env,
)





























































CONS_DATA_CSV = "cons_data.csv"
CONS_DATA_CSV_LEGACY = "cons_data_hourly.csv"


def default_cons_data_file() -> str:
    """Canonical cons_data path; fall back to legacy ``*_hourly`` name if present."""
    preferred = runtime_path(CONS_DATA_CSV)
    if os.path.exists(preferred):
        return preferred
    legacy = runtime_path(CONS_DATA_CSV_LEGACY)
    if os.path.exists(legacy):
        return legacy
    return preferred


def resolve_cons_data_path(configured_path: str) -> str:
    """Prefer existing file; if ``cons_data.csv`` is missing, try ``cons_data_hourly.csv``."""
    if os.path.exists(configured_path):
        return configured_path
    norm = configured_path.replace("\\", "/")
    if norm.endswith("/" + CONS_DATA_CSV) or norm.endswith(CONS_DATA_CSV):
        legacy = configured_path[: -len(CONS_DATA_CSV)] + CONS_DATA_CSV_LEGACY
        if os.path.exists(legacy):
            return legacy
    return configured_path


def bundled_config_dir() -> str:
    """Im Image gebündelte Config-Vorlagen (nicht vom NAS-Volume überschrieben)."""
    return os.path.join("share", "config")


def bundled_grid_fees_file() -> str:
    """Published Netzentgelt catalog under share/config/grid_fees.json (seed template)."""
    return os.path.join(bundled_config_dir(), "grid_fees.json")


def resolve_grid_fees_catalog_template_path() -> str:
    """Full public catalog for seeding site grid_fees.json (prefer share/config)."""
    preferred = _preferred_or_legacy_file("grid_fees.json")
    bundled = bundled_grid_fees_file()
    if os.path.isfile(bundled):
        return bundled
    if os.path.isfile(preferred):
        return preferred
    return bundled


def resolve_grid_fees_json_path() -> str:
    """Pfad zu grid_fees.json: ENV > neben config.json > earnie_env/config."""
    return _resolve_sidecar_json_path(
        env_suffix="GRID_FEES_PATH",
        filename="grid_fees.json",
        default_path=os.path.join(_preferred_config_dir(), "grid_fees.json"),
    )


USER_GRID_FEES_JSON = "user_grid_fees.json"


def user_grid_fees_path_for(grid_fees_path: str) -> str:
    """Edibert user grid areas (``user_grid_fees.json``) next to the given ``grid_fees.json``."""
    return os.path.join(os.path.dirname(grid_fees_path), USER_GRID_FEES_JSON)


def resolve_user_grid_fees_json_path() -> str:
    """Pfad zu user_grid_fees.json: immer neben grid_fees.json (kein eigener ENV-Override)."""
    return user_grid_fees_path_for(resolve_grid_fees_json_path())


def bundled_config_example_file() -> str:
    return os.path.join(bundled_config_dir(), "config.example.json")


def bundled_config_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "config.minimal.json")


def bundled_config_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "config.schema.json")


def resolve_config_template_path() -> str:
    """Vorlage für config.example.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = _preferred_or_legacy_file("config.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "config.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_config_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_config_minimal_template_path() -> str:
    """Vorlage für neue config.json (Greenfield-Bootstrap, ohne Hausdaten)."""
    preferred = _preferred_or_legacy_file("config.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_config_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def config_schema_file() -> str:
    """Pfad zum JSON-Schema im Persistenz-Ordner."""
    preferred = _preferred_or_legacy_file("config.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "config.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_config_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_config_schema_template_path() -> str:
    """Schema-Vorlage: Mount, Legacy oder gebündelte Image-Kopie."""
    return config_schema_file()


def resolve_config_json_path() -> str:
    """Pfad zu config.json: cloud session > CONFIG_PATH-Dir > ENV_PATH/config > legacy."""
    from runtime_store.cloud_demo import get_session_env_root

    session = get_session_env_root()
    if session:
        return os.path.join(session, "config", "config.json")
    env = _effective_config_path_env()
    if env:
        if _is_legacy_config_file_path(env):
            return env
        return os.path.join(env, "config.json")
    preferred = os.path.join(_preferred_config_dir(), "config.json")
    if os.path.isfile(preferred):
        return preferred
    legacy_dir = os.path.join(_LEGACY_CONFIG_DIR, "config.json")
    if os.path.isfile(legacy_dir):
        return legacy_dir
    legacy = "config.json"
    if os.path.isfile(legacy):
        return legacy
    return preferred




# Process-wide memo for sidecar path resolution (skips repeated isfile on bind mounts).
_sidecar_path_cache: dict[tuple, str] = {}


def clear_sidecar_path_cache() -> None:
    """Reset sidecar path memo (tests / env changes)."""
    _sidecar_path_cache.clear()


def _sidecar_path_cache_key(
    *,
    env_suffix: str,
    filename: str,
    default_path: str,
    legacy_basename: str | None,
    session_root: str | None,
    sidecar_env: str,
    install_context: str,
    config_path_env: str,
) -> tuple:
    return (
        env_suffix,
        filename,
        default_path,
        legacy_basename,
        session_root,
        sidecar_env,
        install_context,
        config_path_env,
    )


def _resolve_sidecar_json_path_uncached(
    *,
    env_suffix: str,
    filename: str,
    default_path: str,
    legacy_basename: str | None,
    session_root: str | None,
    sidecar_env: str,
    install_context: str,
) -> str:
    if session_root:
        return os.path.join(config_dir(), filename)
    if sidecar_env:
        return sidecar_env
    config_directory = _config_directory_from_env()
    if config_directory and install_context.strip().lower() == "homeassistant_addon":
        return os.path.join(config_directory, filename)
    if config_directory:
        co_located = os.path.join(config_directory, filename)
        if os.path.isfile(co_located):
            return co_located
    if os.path.isfile(default_path):
        return default_path
    legacy_in_config = os.path.join(_LEGACY_CONFIG_DIR, filename)
    if os.path.isfile(legacy_in_config):
        return legacy_in_config
    if legacy_basename and os.path.isfile(legacy_basename):
        return legacy_basename
    if config_directory:
        return os.path.join(config_directory, filename)
    return default_path


def _resolve_sidecar_json_path(
    *,
    env_suffix: str,
    filename: str,
    default_path: str,
    legacy_basename: str | None = None,
) -> str:
    """
    Sidecar-JSON im Config-Verzeichnis, wenn CONFIG_PATH per ENV gesetzt ist.

    Reihenfolge: cloud session > explizite Sidecar-ENV > vorhandene Datei im Config-Dir >
    vorhandener Default/Legacy > (bei CONFIG_PATH) Zielpfad im Config-Dir >
    Default-Pfad.

    Home Assistant add-on: always keep sidecars under ``EARNIE_CONFIG_PATH``
    (``/config`` / addon_config). Never fall back to a leftover copy under
    ``EARNIE_ENV_PATH/config`` (stale catalog after addon_config migration).
    """
    from runtime_store.cloud_demo import get_session_env_root

    session_root = get_session_env_root()
    sidecar_env = read_env(env_suffix)
    install_context = read_env("INSTALL_CONTEXT")
    config_path_env = _effective_config_path_env()
    key = _sidecar_path_cache_key(
        env_suffix=env_suffix,
        filename=filename,
        default_path=default_path,
        legacy_basename=legacy_basename,
        session_root=session_root,
        sidecar_env=sidecar_env,
        install_context=install_context,
        config_path_env=config_path_env,
    )
    cached = _sidecar_path_cache.get(key)
    if cached is not None:
        return cached
    resolved = _resolve_sidecar_json_path_uncached(
        env_suffix=env_suffix,
        filename=filename,
        default_path=default_path,
        legacy_basename=legacy_basename,
        session_root=session_root,
        sidecar_env=sidecar_env,
        install_context=install_context,
    )
    _sidecar_path_cache[key] = resolved
    return resolved


def local_settings_file() -> str:
    return runtime_path("local_settings.json")


def local_settings_example_file() -> str:
    return runtime_path("local_settings.example.json")


def resolve_local_settings_template_path() -> str:
    """Vorlage für local_settings.json: Runtime-Mount oder gebündelte Image-Kopie."""
    preferred = local_settings_example_file()
    if os.path.isfile(preferred):
        return preferred
    legacy = os.path.join(_LEGACY_RUNTIME_DIR, "local_settings.example.json")
    if os.path.isfile(legacy):
        return legacy
    bundled = os.path.join(bundled_config_dir(), "local_settings.example.json")
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_local_settings_json_path() -> str:
    """Maschinenspezifische Einstellungen: cloud session / runtime > ENV > runtime/local_settings.json."""
    from runtime_store.cloud_demo import get_session_env_root

    if get_session_env_root():
        return local_settings_file()
    env = read_env("LOCAL_SETTINGS_PATH")
    if env:
        return env
    return local_settings_file()


def bundled_backtesting_scenarios_example_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.example.json")


def bundled_backtesting_scenarios_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.minimal.json")


def bundled_backtesting_scenarios_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "backtesting_scenarios.schema.json")


def resolve_backtesting_scenarios_template_path() -> str:
    """Vorlage für backtesting_scenarios.example.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = _preferred_or_legacy_file("backtesting_scenarios.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "backtesting_scenarios.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_backtesting_scenarios_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_minimal_template_path() -> str:
    """Vorlage für neue backtesting_scenarios.json (leere Szenarien)."""
    preferred = _preferred_or_legacy_file("backtesting_scenarios.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_backtesting_scenarios_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_schema_template_path() -> str:
    """Schema-Vorlage für backtesting_scenarios.json."""
    preferred = _preferred_or_legacy_file("backtesting_scenarios.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "backtesting_scenarios.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_backtesting_scenarios_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_backtesting_scenarios_json_path() -> str:
    """Pfad zu backtesting_scenarios.json: ENV > neben config.json > earnie_env/config > Legacy."""
    return _resolve_sidecar_json_path(
        env_suffix="BACKTESTING_SCENARIOS_PATH",
        filename="backtesting_scenarios.json",
        default_path=os.path.join(_preferred_config_dir(), "backtesting_scenarios.json"),
        legacy_basename="backtesting_scenarios.json",
    )


def bundled_tariffs_example_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.example.json")


def bundled_tariffs_catalog_file() -> str:
    """Published full tariff catalog under share/config/tariffs.json."""
    return os.path.join(bundled_config_dir(), "tariffs.json")


def bundled_tariffs_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.minimal.json")


def bundled_tariffs_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "tariffs.schema.json")


def resolve_tariffs_template_path() -> str:
    preferred = _preferred_or_legacy_file("tariffs.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_catalog_template_path() -> str:
    """Full public catalog for seeding site tariffs.json (prefer share/config)."""
    preferred = _preferred_or_legacy_file("tariffs.json")
    # Preferred path is the live site file — only use it as a *template* if we are
    # not about to bootstrap that same path. Callers should prefer bundled catalog.
    bundled = bundled_tariffs_catalog_file()
    if os.path.isfile(bundled):
        return bundled
    if os.path.isfile(preferred):
        return preferred
    return bundled


def resolve_tariffs_minimal_template_path() -> str:
    """Vorlage für neue tariffs.json (leere Tarif-Kataloge)."""
    preferred = _preferred_or_legacy_file("tariffs.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_schema_template_path() -> str:
    preferred = _preferred_or_legacy_file("tariffs.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_tariffs_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_tariffs_json_path() -> str:
    """Pfad zu tariffs.json: ENV > neben config.json > earnie_env/config."""
    return _resolve_sidecar_json_path(
        env_suffix="TARIFFS_PATH",
        filename="tariffs.json",
        default_path=os.path.join(_preferred_config_dir(), "tariffs.json"),
    )


USER_TARIFFS_JSON = "user_tariffs.json"


def user_tariffs_path_for(tariffs_path: str) -> str:
    """Edibert user file (``user_tariffs.json``) next to the given ``tariffs.json``."""
    return os.path.join(os.path.dirname(tariffs_path), USER_TARIFFS_JSON)


def resolve_user_tariffs_json_path() -> str:
    """Pfad zu user_tariffs.json: immer neben tariffs.json (kein eigener ENV-Override)."""
    return user_tariffs_path_for(resolve_tariffs_json_path())


def bundled_house_profiles_example_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.example.json")


def bundled_house_profiles_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.minimal.json")


def bundled_house_profiles_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "house_profiles.schema.json")


def resolve_house_profiles_template_path() -> str:
    preferred = _preferred_or_legacy_file("house_profiles.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_minimal_template_path() -> str:
    """Vorlage für neue house_profiles.json (leere Profile)."""
    preferred = _preferred_or_legacy_file("house_profiles.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_schema_template_path() -> str:
    preferred = _preferred_or_legacy_file("house_profiles.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_house_profiles_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_house_profiles_json_path() -> str:
    """Pfad zu house_profiles.json: ENV > neben config.json > earnie_env/config."""
    return _resolve_sidecar_json_path(
        env_suffix="HOUSE_PROFILES_PATH",
        filename="house_profiles.json",
        default_path=os.path.join(_preferred_config_dir(), "house_profiles.json"),
    )


def bundled_components_example_file() -> str:
    return os.path.join(bundled_config_dir(), "components.example.json")


def bundled_components_minimal_file() -> str:
    return os.path.join(bundled_config_dir(), "components.minimal.json")


def bundled_components_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "components.schema.json")


def resolve_components_template_path() -> str:
    preferred = _preferred_or_legacy_file("components.example.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_minimal_template_path() -> str:
    """Vorlage für neue components.json (leere Kataloge)."""
    preferred = _preferred_or_legacy_file("components.minimal.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_minimal_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_schema_template_path() -> str:
    preferred = _preferred_or_legacy_file("components.schema.json")
    if os.path.isfile(preferred):
        return preferred
    bundled = bundled_components_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_components_json_path() -> str:
    """Pfad zu components.json: ENV > neben config.json > earnie_env/config."""
    return _resolve_sidecar_json_path(
        env_suffix="COMPONENTS_PATH",
        filename="components.json",
        default_path=os.path.join(_preferred_config_dir(), "components.json"),
    )


def bundled_deviation_rules_example_file() -> str:
    return os.path.join(bundled_config_dir(), "deviation_rules.example.json")


def bundled_deviation_rules_schema_file() -> str:
    return os.path.join(bundled_config_dir(), "deviation_rules.schema.json")


def resolve_deviation_rules_template_path() -> str:
    """Vorlage für deviation_rules.json: Mount, Legacy oder gebündelte Image-Kopie."""
    preferred = _preferred_or_legacy_file("deviation_rules.example.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "deviation_rules.example.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_deviation_rules_example_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_deviation_rules_schema_template_path() -> str:
    """Schema-Vorlage für deviation_rules.json."""
    preferred = _preferred_or_legacy_file("deviation_rules.schema.json")
    if os.path.isfile(preferred):
        return preferred
    legacy = "deviation_rules.schema.json"
    if os.path.isfile(legacy):
        return legacy
    bundled = bundled_deviation_rules_schema_file()
    if os.path.isfile(bundled):
        return bundled
    return preferred


def resolve_deviation_rules_json_path() -> str:
    """Pfad zu deviation_rules.json: ENV > neben config.json > earnie_env/config > Legacy > Vorlage."""
    return _resolve_sidecar_json_path(
        env_suffix="DEVIATION_RULES_PATH",
        filename="deviation_rules.json",
        default_path=os.path.join(_preferred_config_dir(), "deviation_rules.json"),
        legacy_basename="deviation_rules.json",
    )


def bundled_dotenv_example_file() -> str:
    return os.path.join(bundled_config_dir(), ".env.example")


def resolve_dotenv_path() -> str:
    """Pfad zur .env: cloud session > ENV > Config-Dir > ENV_PATH/config/.env > legacy."""
    from runtime_store.cloud_demo import get_session_env_root

    if get_session_env_root():
        return os.path.join(config_dir(), ".env")
    env = read_env("DOTENV_PATH")
    if env:
        return env
    preferred_dotenv = _preferred_dotenv()
    # Explicit ENV_PATH (launch.json / greenfield): stay inside that tree.
    # Do not fall back to legacy config/.env (often still points at NAS).
    if _env_path_explicit():
        if os.path.isfile(preferred_dotenv):
            return preferred_dotenv
        if os.path.isfile(_LEGACY_DOTENV):
            return _LEGACY_DOTENV
        return preferred_dotenv
    config_directory = _config_directory_from_env()
    if config_directory:
        co_located = os.path.join(config_directory, ".env")
        if os.path.isfile(co_located):
            return co_located
        # Prefer co-located path for new bootstraps when CONFIG_PATH is set.
        if not os.path.isfile(preferred_dotenv) and not os.path.isfile(
            _LEGACY_DOTENV_IN_CONFIG
        ):
            return co_located
    if os.path.isfile(preferred_dotenv):
        return preferred_dotenv
    # Prefer repo-root .env over legacy config/.env when preferred is missing.
    if os.path.isfile(_LEGACY_DOTENV):
        return _LEGACY_DOTENV
    if os.path.isfile(_LEGACY_DOTENV_IN_CONFIG):
        return _LEGACY_DOTENV_IN_CONFIG
    if config_directory:
        return os.path.join(config_directory, ".env")
    return preferred_dotenv


def resolve_dotenv_template_path() -> str:
    """Vorlage für .env: Repo-.env.example oder gebündelte Image-Kopie."""
    if os.path.isfile(".env.example"):
        return ".env.example"
    bundled = bundled_dotenv_example_file()
    if os.path.isfile(bundled):
        return bundled
    return bundled
