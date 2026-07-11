"""IANA-Zeitzone aus Breiten-/Längengrad (offline, timezonefinder)."""
from __future__ import annotations

_finder = None


def lookup_timezone_name(latitude: float, longitude: float) -> str:
    """Liefert IANA-Zeitzone für geographische Koordinaten."""
    global _finder
    if _finder is None:
        from timezonefinder import TimezoneFinder

        _finder = TimezoneFinder()
    tz = _finder.timezone_at(lat=float(latitude), lng=float(longitude))
    if not tz:
        raise ValueError(
            f"Keine Zeitzone für Koordinaten {latitude:.4f}, {longitude:.4f} gefunden "
            "(z. B. Meer oder ungültiger Punkt)."
        )
    return str(tz)
