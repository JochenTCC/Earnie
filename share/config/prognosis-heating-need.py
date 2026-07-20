"""Standalone-Prototyp — produktive Logik: data.heating_need."""
import json
import math
import urllib.request

# =====================================================================
# EINGABEPARAMETER
# =====================================================================
eingabe_wohnflaeche = 120.0        # in m²
eingabe_gebaeude_klasse = 2       # 1 = Passivhaus, 2 = Neubau, 3 = Bestand, 4 = Altbau
eingabe_wp_typ = "erde"           # "luft" oder "erde"
eingabe_latitude = 47             # Breitengrad
eingabe_longitude = 10            # Längengrad
eingabe_wunsch_temp = 21.5        # Gewünschte Raumtemperatur in °C
eingabe_heizgrenze = 15.0         # Heizgrenztemperatur in °C
eingabe_personen = 2              # Anzahl der Personen im Haushalt

# NEUE PHYSIKALISCHE SOLAR-PARAMETER
eingabe_solar_flaeche = 0.0      # Kollektorfläche in m²
eingabe_solar_tilt = 18.0         # Neigung: 0° = flach, 90° = Fassade
eingabe_solar_azimuth = 0.0       # Ausrichtung: 0° = Süd, -90° = Ost, 90° = West

# =====================================================================
# CORE-LOGIK / STATISCHE PARAMETER
# =====================================================================

def get_spezifischer_bedarf(gebaeude_klasse: int) -> float:
    """Liefert den spezifischen Heizwärmebedarf in kWh/(m²·a)."""
    klassen_defaults = {1: 15.0, 2: 45.0, 3: 80.0, 4: 130.0}
    return klassen_defaults.get(gebaeude_klasse, 80.0)


def get_jahresarbeitszahl(wp_typ: str) -> float:
    """Liefert die typische JAZ basierend auf der Technologie."""
    typ_cleaned = str(wp_typ).lower().strip()
    return {"luft": 3.5, "erde": 4.3}.get(typ_cleaned, 3.5)


def berechne_warmwasser_bedarf_woche(personen: int) -> float:
    """Berechnet den thermischen Warmwasserbedarf pro Woche (2 kWh pro Person/Tag)."""
    if personen <= 0:
        return 0.0
    return personen * 2.0 * 7.0

# =====================================================================
# ASTRONOMISCHE & TRANSITIONS-LOGIK
# =====================================================================

def get_daily_transposition_factor(lat: float, day_of_year: int, tilt: float, azimuth: float) -> float:
    """Berechnet den geometrischen Umrechnungsfaktor von horizontaler zu geneigter Fläche."""
    lat_rad, tilt_rad, az_rad = map(math.radians, [lat, tilt, azimuth])
    
    # Deklination der Sonne am jeweiligen Tag des Jahres
    decl = math.radians(23.45 * math.sin(math.radians(360 / 365 * (284 + day_of_year))))
    
    # Einfallswinkel auf horizontaler Fläche im Solarnadit (Zenith)
    cos_zenith = math.cos(lat_rad - decl)
    cos_zenith = max(0.1, cos_zenith) # Absicherung gegen Division durch Null im tiefen Winter
        
    # Einfallswinkel auf der geneigten Kollektorfläche im Solar-Noon (Stundenwinkel = 0)
    cos_theta = (math.cos(lat_rad - decl) * math.cos(tilt_rad) + 
                 math.sin(lat_rad - decl) * math.sin(tilt_rad) * math.cos(az_rad))
    cos_theta = max(0.0, cos_theta)
    
    # Isotropes Mischmodell: 50% gerichtete Direktstrahlung, 50% diffuser Himmel
    return 0.5 * (cos_theta / cos_zenith) + 0.5 * ((1.0 + math.cos(tilt_rad)) / 2.0)

# =====================================================================
# DYNAMISCHE KLIMADATEN-LOGIK (Open-Meteo API)
# =====================================================================

def fetch_historical_climate(lat: float, lon: float, jahr: int = 2025) -> dict:
    """Holt Tages-Mitteltemperaturen und Globalstrahlung von Open-Meteo."""
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
           f"&start_date={jahr}-01-01&end_date={jahr}-12-31"
           f"&daily=temperature_2m_mean,shortwave_radiation_sum&timezone=auto")
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f" [Meldung] Klima-Daten-Download fehlgeschlagen ({e}).")
    return {}


def berechne_wochenfaktoren_aus_temps(temps: list, wunsch_temp: float, heizgrenze: float) -> list:
    """Berechnet aus 365 Tageswerten die relative Heizlastverteilung für 52 Wochen."""
    if not temps or len(temps) < 364:
        return [1.0 / 52] * 52
        
    hdd_pro_tag = [max(0.0, wunsch_temp - t) if t < heizgrenze else 0.0 for t in temps]
    wochen_hdd = [sum(hdd_pro_tag[i*7:(i+1)*7]) for i in range(52)]
    
    summe_hdd = sum(wochen_hdd)
    if summe_hdd == 0:
        return [1.0 / 52] * 52
        
    return [h / summe_hdd for h in wochen_hdd]


def berechne_solar_ertrag_woche(radiation_mj_year: list, kw_idx: int, flaeche: float, 
                                   lat: float, tilt: float, azimuth: float) -> float:
    """Berechnet den thermischen Solarertrag einer Woche taggenau mit Tilt & Azimuth."""
    if not radiation_mj_year or flaeche <= 0.0:
        return 0.0
        
    wochen_ertrag = 0.0
    for d in range(7):
        tag_des_jahres = (kw_idx * 7) + d + 1
        if tag_des_jahres > len(radiation_mj_year):
            break
            
        # Strahlung von Megajoule in kWh umrechnen (1 MJ = 1/3.6 kWh)
        strahlung_kwh_horizontal = radiation_mj_year[tag_des_jahres - 1] / 3.6
        r_factor = get_daily_transposition_factor(lat, tag_des_jahres, tilt, azimuth)
        
        # Ertrag berechnen (40% mittlerer Wirkungsgrad solarthermischer Kollektoren)
        wochen_ertrag += (strahlung_kwh_horizontal * r_factor) * flaeche * 0.40
        
    return wochen_ertrag

# =====================================================================
# RECHEN-CORE & AUSGABE
# =====================================================================

def berechne_netto_strom_woche(heiz_bedarf_jahr: float, wochen_faktor: float, 
                               ww_bedarf_woche: float, solar_ertrag_woche: float, jaz: float) -> tuple[float, float]:
    """Berechnet den finalen elektrischen Strombedarf nach Solar-Abzug."""
    gesamter_waermebedarf = (heiz_bedarf_jahr * wochen_faktor) + ww_bedarf_woche
    netto_waermebedarf = max(0.0, gesamter_waermebedarf - solar_ertrag_woche)
    return (netto_waermebedarf / jaz), gesamter_waermebedarf


def loop_ueber_wochen(climate_data: dict, params: dict) -> float:
    """Schleife über alle 52 Wochen zur Berechnung und Anzeige der Verbräuche."""
    temps = climate_data.get("daily", {}).get("temperature_2m_mean", [])
    rads = climate_data.get("daily", {}).get("shortwave_radiation_sum", [])
    
    wochen_faktoren = berechne_wochenfaktoren_aus_temps(temps, params["wunsch_temp"], params["heizgrenze"])
    ww_woche = berechne_warmwasser_bedarf_woche(params["personen"])
    
    gesamter_strom_jahr = 0.0
    for kw_idx in range(52):
        solar_woche = berechne_solar_ertrag_woche(rads, kw_idx, params["solar_flaeche"], params["lat"], params["solar_tilt"], params["solar_azimuth"])
        strom_kw, waerme_kw = berechne_netto_strom_woche(params["heiz_jahr"], wochen_faktoren[kw_idx], ww_woche, solar_woche, params["jaz"])
        gesamter_strom_jahr += strom_kw
        
        if waerme_kw > 0.1:
            print(f"KW {kw_idx+1:02d}: Bedarf: {waerme_kw:6.1f} kWh_th | Solar-Deckung: {solar_woche:5.1f} kWh_th | WP-Strom: {strom_kw:5.1f} kWh_el")
            
    return gesamter_strom_jahr


def generiere_jahres_hochrechnung():
    """Koordiniert den gesamten Programmablauf."""
    climate_data = fetch_historical_climate(eingabe_latitude, eingabe_longitude)
    
    heiz_bedarf_jahr = eingabe_wohnflaeche * get_spezifischer_bedarf(eingabe_gebaeude_klasse)
    params = {
        "heiz_jahr": heiz_bedarf_jahr, "wunsch_temp": eingabe_wunsch_temp, "heizgrenze": eingabe_heizgrenze,
        "personen": eingabe_personen, "solar_flaeche": eingabe_solar_flaeche, 
        "solar_tilt": eingabe_solar_tilt, "solar_azimuth": eingabe_solar_azimuth,
        "jaz": get_jahresarbeitszahl(eingabe_wp_typ), "lat": eingabe_latitude
    }
    
    print(f"\n--- HOCHRECHNUNG FÜR KOORDINATEN: {eingabe_latitude}°, {eingabe_longitude}° ---")
    print(f"Gebäude: {eingabe_wohnflaeche}m² | {eingabe_personen} Personen | Solar: {eingabe_solar_flaeche}m² (Tilt: {eingabe_solar_tilt}°, Azimuth: {eingabe_solar_azimuth}°)")
    print("-" * 95)
    
    gesamtstrom = loop_ueber_wochen(climate_data, params)
    
    print("-" * 95)
    print(f"Gesamtstrombedarf WP (Heizen + WW) am Standort: {gesamtstrom:.2f} kWh/Jahr\n")


if __name__ == "__main__":
    generiere_jahres_hochrechnung()