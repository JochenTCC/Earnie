"""OeMAG-/RefMarkt-Referenzkurven und Katalog-Seed-Skalierung (Wartung)."""
from __future__ import annotations

from data.feed_in_prices import validate_fixed_monthly_feed_in_rates

MIN_OEMAG_MONTHS = 12
# Backwards-compatible alias (tests / callers may still import the old name).
MIN_REFMARKT_MONTHS = 12


def load_oemag_monthly_reference_rates(
    tariffs_doc: dict,
) -> tuple[tuple[int, int, float], ...]:
    """Lädt und validiert die OeMAG-Referenzkurve (mindestens 12 Monate)."""
    raw = tariffs_doc.get("oemag_monthly_feed_in_rates")
    if raw is None:
        raise ValueError(
            "oemag_monthly_feed_in_rates fehlt in tariffs.json "
            "(Wartungs-Referenzkurve für Monats-Einspeisetarif-Seeds)."
        )
    rates = validate_fixed_monthly_feed_in_rates(raw)
    if len(rates) < MIN_OEMAG_MONTHS:
        raise ValueError(
            f"oemag_monthly_feed_in_rates muss mindestens {MIN_OEMAG_MONTHS} Einträge "
            f"haben, nicht {len(rates)}."
        )
    return rates


def load_econtrol_referenzmarktwert_pv_monthly(
    tariffs_doc: dict,
) -> tuple[tuple[int, int, float], ...]:
    """Lädt E-Control Referenzmarktwert PV (§13 EAG), mindestens 12 Monate."""
    raw = tariffs_doc.get("econtrol_referenzmarktwert_pv_monthly")
    if raw is None:
        raise ValueError(
            "econtrol_referenzmarktwert_pv_monthly fehlt in tariffs.json "
            "(Wartungs-Referenzkurve, z. B. für VKW PV-Flex)."
        )
    rates = validate_fixed_monthly_feed_in_rates(raw)
    if len(rates) < MIN_REFMARKT_MONTHS:
        raise ValueError(
            f"econtrol_referenzmarktwert_pv_monthly muss mindestens "
            f"{MIN_REFMARKT_MONTHS} Einträge haben, nicht {len(rates)}."
        )
    return rates


def load_monthly_float_reference_cent(tariffs_doc: dict) -> float:
    raw = tariffs_doc.get("monthly_float_reference_cent_kwh")
    if raw is None:
        raise ValueError(
            "monthly_float_reference_cent_kwh fehlt in tariffs.json "
            "(historischer Nenner für OeMAG-proportionale Katalog-Seeds)."
        )
    reference = float(raw)
    if reference <= 0.0:
        raise ValueError("monthly_float_reference_cent_kwh muss > 0 sein.")
    return reference


def build_monthly_float_lookup(
    oemag_rates: tuple[tuple[int, int, float], ...],
    reference_cent_kwh: float,
    tariff: dict,
) -> tuple[tuple[int, int, float], ...]:
    """
    Skaliert OeMAG-Monatspreise proportional zu arbeitspreis_kwh_cent.
    Abzug: settlement_fee_cent_kwh (min. 0 ct/kWh).

    Nur noch Katalog-Wartung / Seeds — Runtime nutzt owned ``monthly_rates``.
    """
    if "arbeitspreis_kwh_cent" not in tariff:
        raise ValueError(
            "OeMAG-Skalierung erfordert arbeitspreis_kwh_cent am Seed-Tarif."
        )
    work_price = float(tariff["arbeitspreis_kwh_cent"])
    if work_price <= 0.0:
        raise ValueError("arbeitspreis_kwh_cent muss > 0 sein.")
    reference = float(reference_cent_kwh)
    if reference <= 0.0:
        raise ValueError("monthly_float_reference_cent_kwh muss > 0 sein.")
    settlement = float(tariff.get("settlement_fee_cent_kwh", 0.0) or 0.0)
    factor = work_price / reference
    scaled: list[tuple[int, int, float]] = []
    for year, month, oemag_cent in oemag_rates:
        cent = max(0.0, oemag_cent * factor - settlement)
        scaled.append((year, month, round(cent, 4)))
    return tuple(scaled)


def build_refmarkt_minus_fee_lookup(
    refmarkt_rates: tuple[tuple[int, int, float], ...],
    settlement_fee_cent_kwh: float,
) -> tuple[tuple[int, int, float], ...]:
    """Seed: RefMarkt PV − Abschlag (min. 0), z. B. VKW PV-Flex."""
    fee = float(settlement_fee_cent_kwh)
    return tuple(
        (year, month, round(max(0.0, cent - fee), 4))
        for year, month, cent in refmarkt_rates
    )


SEED_CURVE_OEMAG = "oemag"
SEED_CURVE_REFMARKT_PV = "econtrol_refmarkt_pv"

# monthly_seed.curve → Shared-Kurve in tariffs.json
SEED_CURVE_KEYS = {
    SEED_CURVE_OEMAG: "oemag_monthly_feed_in_rates",
    SEED_CURVE_REFMARKT_PV: "econtrol_referenzmarktwert_pv_monthly",
}


def monthly_seed_curve(tariff: dict) -> str | None:
    """Kurvenname aus ``monthly_seed`` oder None (Tarif wird nicht geseedet)."""
    seed = tariff.get("monthly_seed")
    if seed is None:
        return None
    if not isinstance(seed, dict):
        raise ValueError(f"Tarif '{tariff.get('id')}': monthly_seed muss ein Objekt sein.")
    curve = str(seed.get("curve", "")).strip()
    if curve not in SEED_CURVE_KEYS:
        raise ValueError(
            f"Tarif '{tariff.get('id')}': monthly_seed.curve muss "
            f"{' oder '.join(sorted(SEED_CURVE_KEYS))} sein, nicht {curve!r}."
        )
    return curve


def build_seeded_monthly_rates(
    tariffs_doc: dict,
    tariff: dict,
) -> tuple[tuple[int, int, float], ...]:
    """
    Monatswerte eines Katalog-Tarifs aus seinem ``monthly_seed`` (Wartung).

    - ``oemag``: OeMAG × arbeitspreis_kwh_cent / monthly_float_reference_cent_kwh − settlement_fee
    - ``econtrol_refmarkt_pv``: RefMarkt PV − settlement_fee

    Werte ≤ 0 bleiben 0.0 im Ergebnis; ``monthly_rates`` erlaubt nur > 0, der
    Aufrufer entscheidet über Sonderbehandlung.
    """
    curve = monthly_seed_curve(tariff)
    if curve is None:
        raise ValueError(f"Tarif '{tariff.get('id')}' hat kein monthly_seed.")
    settlement = float(tariff.get("settlement_fee_cent_kwh", 0.0) or 0.0)
    if curve == SEED_CURVE_OEMAG:
        seed = tariff["monthly_seed"]
        if "arbeitspreis_kwh_cent" not in seed:
            raise ValueError(
                f"Tarif '{tariff.get('id')}': monthly_seed.arbeitspreis_kwh_cent fehlt "
                "(Pflicht für curve 'oemag')."
            )
        return build_monthly_float_lookup(
            load_oemag_monthly_reference_rates(tariffs_doc),
            load_monthly_float_reference_cent(tariffs_doc),
            {
                "arbeitspreis_kwh_cent": seed["arbeitspreis_kwh_cent"],
                "settlement_fee_cent_kwh": settlement,
            },
        )
    return build_refmarkt_minus_fee_lookup(
        load_econtrol_referenzmarktwert_pv_monthly(tariffs_doc),
        settlement,
    )
