#!/usr/bin/env python3
"""Geodaten für das Beiratsgebiet Büchenbach — deterministisch, ohne Fremd-Key.

Erzeugt drei Dateien in geo/:

  beiraete.geojson   Die Gebiete aller Orts- und Stadtteilbeiräte. Das eigene
                     ist markiert; die Nachbarn geben Orientierung, wo das
                     Gebiet endet und wer nebenan zuständig ist.
  strassen.json      Alle Straßen im Beiratsgebiet, mit statistischem Bezirk —
                     die Übersicht „welche Straßen gehören eigentlich dazu?".
  strassen.geojson   Geometrie dieser Straßen. Damit zeigt das Portal eine
                     Straße sofort auf der Karte, ohne bei jedem Klick einen
                     Geokodierdienst zu fragen.

Quellen, beide öffentlich:

  * Stadt Erlangen, Statistik und Stadtforschung (Open Data, dl-de/by-2.0):
    „Statistische Bezirke nach Straßenabschnitten" (amtliches
    Straßenverzeichnis) und die Vektorgeometrie der Beiratsgebiete.
  * OpenStreetMap über die Overpass-API (ODbL): Geometrie der Straßen.

Die Zuordnung Straße → Beirat läuft über die Straßengeometrie, nicht über den
statistischen Bezirk: drei Bezirke im Stadtgebiet liegen quer über
Beiratsgrenzen. Das Verfahren stammt aus dem Schwesterprojekt UVPA, wo es
gegen zwei unabhängige Quellen geprüft wurde (siehe dortiges geo/README.md).

Aufruf:  python tools/fetch_geodata.py [--out geo] [--beirat "…Büchenbach"]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

import amtliche_geometrie as geom

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

AMT_URL = ("https://erlangen.de/uwao-api/faila/files/bypath/Dokumente/Statistik/"
           "Statistik%20Open%20Data/bezirke_strassenabschnitte_2025.10.xlsx")
BEIRAT_URL = ("https://erlangen.de/uwao-api/faila/files/bypath/Dokumente/Statistik/"
              "Statistik%20Open%20Data/Elangen_2015_Vektorgeometrie_"
              "Stadtteilbeiratsgebiete.zip")

UA = ("SBR-Buechenbach/1.0 (ehrenamtliches Infoportal; "
      "+https://erlangen-kommunal.github.io/SBR-Buechenbach/)")

# Die Geometriedatei ist von 2015 und trägt Arbeitsnamen — die Stadtteilbeiräte
# wurden erst am 27.07.2016 beschlossen. Die Übersetzung auf die heutigen Namen
# ist durch die Nummerierung belegt: der Plan, der seit 01.05.2026 Bestandteil
# der Satzung ist, führt dieselben Nummern (08/09/10/11/13).
#
# Anger und Bruck sind seit 01.05.2026 getrennte Beiräte, die Stadt
# veröffentlicht dafür aber keine getrennte Geometrie — deshalb steht das
# gemeinsame Gebiet für beide.
BEIRAT_NAMEN = {
    "SB Zentrum/Nord": "Stadtteilbeirat Innenstadt",
    "SB Regnitz": "Stadtteilbeirat Alterlangen",
    "SB Ost": "Stadtteilbeirat Ost",
    "SB Süd-Ost": "Stadtteilbeirat Süd",
    "SB Südost": "Stadtteilbeirat Süd",
    "SB Tal/Anger/Bruck": "Stadtteilbeirat Anger / Bruck",
    "SB West": "Stadtteilbeirat Büchenbach",
    "OB Eltersdorf": "Ortsbeirat Eltersdorf",
    "OB Frauenaurach": "Ortsbeirat Frauenaurach",
    "OB Dechsendorf": "Ortsbeirat Dechsendorf",
    "OB Hüttendorf": "Ortsbeirat Hüttendorf",
    "OB Kriegenbrunn": "Ortsbeirat Kriegenbrunn",
    "OB Tennenlohe": "Ortsbeirat Tennenlohe",
    "OB Kosbach/Häusling/Steudach": "Ortsbeirat Kosbach/Häusling/Steudach",
}

EIGENES_GEBIET = "Stadtteilbeirat Büchenbach"

# Ab diesem Anteil gilt eine Straße als zum Gebiet gehörend. Straßen auf der
# Gebietsgrenze gehören beiden Seiten — für den Beirat sind sie relevant.
MIN_ANTEIL = 0.15
PRECISION = 5
XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

NAMED_ROADS_QUERY = """
[out:json][timeout:180][bbox:49.52,10.90,49.65,11.05];
way["highway"]["name"];
out geom;
"""

# ── OSM-Themenkategorien für den Karten-Tab ──────────────────────────────────
# Für jede Kategorie eine Overpass-Auswahl (im gemeinsamen Union-Query) und ein
# Python-Prädikat, das ein Objekt anhand seiner Tags derselben Kategorie
# zuordnet. Reihenfolge = Priorität: das erste passende Prädikat gewinnt, damit
# ein Objekt mit mehreren Tags (etwa eine historische Kirche) genau einmal
# erscheint. `farbe`/`icon` steuern die Darstellung im Frontend.
POI_KATEGORIEN = [
    ("spielplatz", "Spielplätze", "🛝", "#2f9e44",
     lambda t: t.get("leisure") == "playground"),
    ("schule_kita", "Schulen & Kitas", "🏫", "#e8590c",
     lambda t: t.get("amenity") in {"school", "kindergarten"}),
    ("gesundheit", "Gesundheit", "🩺", "#e64980",
     lambda t: t.get("amenity") in {"pharmacy", "doctors", "dentist", "clinic"}
     or "healthcare" in t),
    ("nahversorgung", "Nahversorgung", "🛒", "#1971c2",
     lambda t: t.get("shop") in {"supermarket", "bakery", "convenience",
                                 "butcher", "greengrocer"}),
    ("gastro", "Gastronomie", "🍽️", "#b8860b",
     lambda t: t.get("amenity") in {"restaurant", "cafe", "fast_food", "pub",
                                    "bar", "biergarten", "ice_cream"}),
    ("gemeinschaft", "Kirche & Gemeinschaft", "⛪", "#7048e8",
     lambda t: t.get("amenity") in {"place_of_worship", "community_centre",
                                    "social_facility"}),
    ("historisch", "Historisch & Denkmal", "🏛️", "#846358",
     lambda t: "historic" in t),
    ("sport", "Sportanlagen", "⚽", "#0c8599",
     lambda t: t.get("leisure") in {"pitch", "sports_centre", "fitness_station",
                                    "fitness_centre", "swimming_pool"}),
    ("haltestelle", "Bushaltestellen", "🚌", "#1c7ed6",
     lambda t: t.get("highway") == "bus_stop"
     or (t.get("public_transport") == "platform" and t.get("bus") == "yes")),
    ("querung", "Querungen", "🚸", "#f08c00",
     lambda t: t.get("highway") == "crossing" or "crossing" in t),
    ("abfall", "Abfall & Recycling", "🗑️", "#5c940d",
     lambda t: t.get("amenity") in {"waste_basket", "recycling"}),
    ("bank", "Sitzbänke", "🪑", "#868e96",
     lambda t: t.get("amenity") == "bench"),
]

LINIEN_KATEGORIEN = [
    ("radweg", "Radweg-Infrastruktur", "🚲", "#087f5b",
     lambda t: t.get("highway") == "cycleway"
     or t.get("cycleway") in {"lane", "track", "opposite", "opposite_lane",
                              "opposite_track"}
     or any(k.startswith("cycleway:") and v in {"lane", "track"}
            for k, v in t.items())),
    ("tempo", "Tempo-Beschränkung", "🚦", "#e03131",
     lambda t: "maxspeed" in t and t.get("highway") is not None),
]

# Punkt-Objekte aller Kategorien in einem Rutsch (mit Zentroid für Flächen).
POI_QUERY = """
[out:json][timeout:180][bbox:{bbox}];
(
  nwr[leisure=playground];
  nwr[amenity~"^(school|kindergarten)$"];
  nwr[amenity~"^(pharmacy|doctors|dentist|clinic)$"];
  nwr[healthcare];
  nwr[shop~"^(supermarket|bakery|convenience|butcher|greengrocer)$"];
  nwr[amenity~"^(restaurant|cafe|fast_food|pub|bar|biergarten|ice_cream)$"];
  nwr[amenity~"^(place_of_worship|community_centre|social_facility)$"];
  nwr[historic];
  nwr[leisure~"^(pitch|sports_centre|fitness_station|fitness_centre|swimming_pool)$"];
  node[highway=bus_stop];
  node[public_transport=platform][bus=yes];
  node[highway=crossing];
  node[crossing];
  nwr[amenity~"^(waste_basket|recycling)$"];
  node[amenity=bench];
);
out center tags;
"""

# Linien-Objekte (Radinfrastruktur, tempolimitierte Straßen) mit Geometrie.
LINIEN_QUERY = """
[out:json][timeout:180][bbox:{bbox}];
(
  way[highway=cycleway];
  way[highway][cycleway];
  way[highway]["cycleway:both"];
  way[highway]["cycleway:left"];
  way[highway]["cycleway:right"];
  way[highway][maxspeed];
);
out geom tags;
"""

# Rohwert eines definierenden Tags → deutsches Label für den Popup-Untertitel.
SUBTYP_DE = {
    "restaurant": "Restaurant", "cafe": "Café", "fast_food": "Imbiss",
    "pub": "Kneipe", "bar": "Bar", "biergarten": "Biergarten",
    "ice_cream": "Eisdiele", "supermarket": "Supermarkt", "bakery": "Bäckerei",
    "convenience": "Kiosk", "butcher": "Metzgerei", "greengrocer": "Obst & Gemüse",
    "pharmacy": "Apotheke", "doctors": "Arztpraxis", "dentist": "Zahnarztpraxis",
    "clinic": "Klinik", "school": "Schule", "kindergarten": "Kindergarten",
    "playground": "Spielplatz", "place_of_worship": "Kirche/Gebetsstätte",
    "community_centre": "Gemeinschaftshaus", "social_facility": "Soziale Einrichtung",
    "pitch": "Sportplatz", "sports_centre": "Sportzentrum",
    "fitness_station": "Fitnessstation", "fitness_centre": "Fitnessstudio",
    "swimming_pool": "Schwimmbad", "bus_stop": "Bushaltestelle",
    "crossing": "Fußgängerquerung", "waste_basket": "Abfalleimer",
    "recycling": "Recycling", "bench": "Sitzbank", "memorial": "Denkmal",
    "monument": "Denkmal", "wayside_cross": "Feldkreuz", "wayside_shrine": "Bildstock",
    "building": "Historisches Gebäude", "yes": "",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def http_get(url: str, timeout: int = 240) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def overpass(query: str) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last = None
    for mirror in OVERPASS_MIRRORS:
        for attempt in (1, 2):
            try:
                req = urllib.request.Request(
                    mirror, data=body,
                    headers={"User-Agent": UA,
                             "Content-Type": "application/x-www-form-urlencoded"})
                with urllib.request.urlopen(req, timeout=300) as r:
                    return json.loads(r.read().decode("utf-8"))
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                last = e
                code = getattr(e, "code", None)
                log(f"  {mirror} → {code or e} (Versuch {attempt})")
                if code in (429, 504) and attempt == 1:
                    time.sleep(20)
                else:
                    break
    raise RuntimeError(f"Kein Overpass-Spiegel erreichbar: {last}")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


def vergleichsform(s: str) -> str:
    """Schreibweisen-toleranter Schlüssel für den Abgleich mit dem Verzeichnis.

    OpenStreetMap und das amtliche Verzeichnis setzen Bindestriche und
    Leerzeichen unterschiedlich („Adenauerring" gegen „Adenauer-Ring").
    """
    return re.sub(r"[\s\-]+", "", norm(s).lower())


# ── Amtliches Straßenverzeichnis ─────────────────────────────────────────────

def parse_amt(blob: bytes) -> tuple[str, dict[str, list[str]]]:
    """→ (Stand, {Straßenname: ['76 Büchenbach Dorf', …]})."""
    z = zipfile.ZipFile(BytesIO(blob))
    shared = ["".join(t.text or "" for t in si.iter(XLSX_NS + "t"))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(XLSX_NS + "si")]
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    target = next(rels[s.get(rel_ns + "id")] for s in wb.iter(XLSX_NS + "sheet")
                  if s.get("name") == "Nach Straßen")

    stand, strassen = "", {}
    for row in ET.fromstring(z.read("xl/" + target.lstrip("/").removeprefix("xl/"))).iter(XLSX_NS + "row"):
        cells = {}
        for c in row.findall(XLSX_NS + "c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            v = c.find(XLSX_NS + "v")
            cells[col] = (shared[int(v.text)] if c.get("t") == "s" and v is not None
                          else (v.text if v is not None else "")) or ""
        if not stand and (m := re.search(r"Stand:\s*(\d+)\.(\d+)\.(\d+)", cells.get("A", ""))):
            stand = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        key, name, bez = cells.get("A", "").strip(), cells.get("B", "").strip(), cells.get("K", "").strip()
        if not key.isdigit() or not name:
            continue
        eintrag = strassen.setdefault(norm(name), [])
        if bez and norm(bez) not in eintrag:
            eintrag.append(norm(bez))
    return stand, strassen


# ── OSM-Themenobjekte für den Karten-Tab ─────────────────────────────────────

def _subtyp(tags: dict) -> str:
    for k in ("amenity", "shop", "leisure", "historic", "healthcare", "highway"):
        v = tags.get(k)
        if v:
            return SUBTYP_DE.get(v, v.replace("_", " "))
    return ""


def klassifiziere(tags: dict, kats) -> str | None:
    for key, _label, _icon, _farbe, pred in kats:
        if pred(tags):
            return key
    return None


def extract_osm_kategorien(out: Path, finde, beirat: str,
                           eigen_bbox: tuple[float, float, float, float]) -> None:
    """OSM-Themenobjekte (Punkte + Linien) aus Overpass holen, präzise auf das
    Beiratspolygon clippen und drei Dateien schreiben: osm_poi.geojson,
    osm_linien.geojson, osm_kategorien.json."""
    lon0, lat0, lon1, lat1 = eigen_bbox
    bbox = f"{lat0},{lon0},{lat1},{lon1}"       # Overpass erwartet S,W,N,O

    log("OpenStreetMap: Themenobjekte (Punkte) …")
    data = overpass(POI_QUERY.format(bbox=bbox))
    punkte, zaehl_p = [], {k: 0 for k, *_ in POI_KATEGORIEN}
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if el["type"] == "node":
            lon, lat = el.get("lon"), el.get("lat")
        else:                                    # Weg/Relation: Zentroid
            c = el.get("center") or {}
            lon, lat = c.get("lon"), c.get("lat")
        if lon is None or lat is None or finde(lon, lat) != beirat:
            continue                             # nur echt im Polygon
        kat = klassifiziere(tags, POI_KATEGORIEN)
        if not kat:
            continue
        label = next(l for k, l, *_ in POI_KATEGORIEN if k == kat)
        props = {"kat": kat,
                 "name": norm(tags.get("name") or tags.get("ref") or label),
                 "sub": _subtyp(tags)}
        if tags.get("wheelchair") in {"yes", "limited"}:
            props["bf"] = True
        punkte.append({"type": "Feature", "properties": props,
                       "geometry": {"type": "Point",
                                    "coordinates": [round(lon, PRECISION),
                                                    round(lat, PRECISION)]}})
        zaehl_p[kat] += 1
    write_json(out / "osm_poi.geojson",
               {"type": "FeatureCollection", "features": punkte}, compact=True)

    log("OpenStreetMap: Themenobjekte (Linien) …")
    data = overpass(LINIEN_QUERY.format(bbox=bbox))
    linien, zaehl_l = [], {k: 0 for k, *_ in LINIEN_KATEGORIEN}
    for el in data.get("elements", []):
        g = el.get("geometry")
        tags = el.get("tags", {})
        if not g:
            continue
        kat = klassifiziere(tags, LINIEN_KATEGORIEN)
        if not kat:
            continue
        probe = g[:: max(1, len(g) // 6)]
        if not any(finde(p["lon"], p["lat"]) == beirat for p in probe):
            continue                             # mindestens ein Stützpunkt im Gebiet
        props = {"kat": kat, "name": norm(tags.get("name", ""))}
        if kat == "tempo":
            props["tempo"] = tags.get("maxspeed", "")
        linien.append({"type": "Feature", "properties": props,
                       "geometry": {"type": "LineString",
                                    "coordinates": [[round(p["lon"], PRECISION),
                                                     round(p["lat"], PRECISION)]
                                                    for p in g]}})
        zaehl_l[kat] += 1
    write_json(out / "osm_linien.geojson",
               {"type": "FeatureCollection", "features": linien}, compact=True)

    write_json(out / "osm_kategorien.json", {
        "stand": time.strftime("%Y-%m-%d"),
        "quelle": "© OpenStreetMap-Mitwirkende (ODbL)",
        "punkt": [{"key": k, "label": l, "icon": i, "farbe": f, "count": zaehl_p[k]}
                  for k, l, i, f, _ in POI_KATEGORIEN],
        "linie": [{"key": k, "label": l, "icon": i, "farbe": f, "count": zaehl_l[k]}
                  for k, l, i, f, _ in LINIEN_KATEGORIEN],
    }, compact=False)
    log(f"  {len(punkte)} Punkte, {len(linien)} Linien im Gebiet „{beirat}“")


# ── Hauptlauf ────────────────────────────────────────────────────────────────

def write_json(path: Path, data, compact: bool) -> None:
    text = json.dumps(data, ensure_ascii=False,
                      separators=(",", ":") if compact else None,
                      indent=None if compact else 2)
    path.write_text(text + ("" if compact else "\n"), encoding="utf-8")
    log(f"  → {path} ({path.stat().st_size / 1024:.0f} KB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="geo")
    ap.add_argument("--beirat", default=EIGENES_GEBIET,
                    help="Eigenes Beiratsgebiet (Vorgabe: %(default)s)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    log("Stadt Erlangen: Gebiete der Orts- und Stadtteilbeiräte …")
    shapes, attrs = geom.load_zip(http_get(BEIRAT_URL))
    gebiete, features = [], []
    for rings_gk, attr in zip(shapes, attrs):
        roh = norm(attr.get("NAME", ""))
        name = BEIRAT_NAMEN.get(roh, roh)
        if roh not in BEIRAT_NAMEN:
            log(f"  Warnung: unbekanntes Gebiet „{roh}“")
        rings = [[[round(v, PRECISION) for v in geom.gk4_to_wgs84(x, y)]
                  for x, y in ring] for ring in rings_gk]
        gebiete.append((name, rings, geom.bbox(rings)))
        features.append({
            "type": "Feature",
            "properties": {"name": name, "eigen": name == args.beirat,
                           "nummer": attr.get("NUMMER", "")},
            "geometry": {"type": "Polygon", "coordinates": rings},
        })
    if not any(f["properties"]["eigen"] for f in features):
        log(f"  FEHLER: „{args.beirat}“ kommt in den Gebietsdaten nicht vor.")
        return 1
    write_json(out / "beiraete.geojson",
               {"type": "FeatureCollection", "features": features}, compact=True)

    def finde(lon: float, lat: float) -> str | None:
        for name, rings, (x0, y0, x1, y1) in gebiete:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and geom.contains(rings, lon, lat):
                return name
        return None

    log("Stadt Erlangen: amtliches Straßenverzeichnis …")
    stand, amt = parse_amt(http_get(AMT_URL))
    log(f"  {len(amt)} Straßen (Stand {stand})")

    log("OpenStreetMap: Straßengeometrie …")
    roads = overpass(NAMED_ROADS_QUERY)
    treffer: dict[str, dict[str, int]] = {}
    linien: dict[str, list] = {}
    for el in roads.get("elements", []):
        name = norm(el.get("tags", {}).get("name", ""))
        line = el.get("geometry")
        if not name or not line:
            continue
        step = max(1, len(line) // 8)
        counts = treffer.setdefault(name, {})
        for p in line[::step]:
            if (b := finde(p["lon"], p["lat"])):
                counts[b] = counts.get(b, 0) + 1
        linien.setdefault(name, []).append(
            [[round(p["lon"], PRECISION), round(p["lat"], PRECISION)] for p in line])

    # Straßen des eigenen Gebiets bestimmen
    amt_nach_form = {vergleichsform(n): (n, b) for n, b in amt.items()}
    eigene, grenzlage = [], 0
    for name, counts in treffer.items():
        total = sum(counts.values())
        if not total or counts.get(args.beirat, 0) / total < MIN_ANTEIL:
            continue
        anteil = counts[args.beirat] / total
        nachbarn = sorted((b for b, n in counts.items()
                           if b != args.beirat and n / total >= MIN_ANTEIL))
        if nachbarn:
            grenzlage += 1
        amtlicher_name, bezirke = amt_nach_form.get(vergleichsform(name), (None, []))
        eintrag = {
            "name": name,
            "bezirke": bezirke,
            "anteil": round(anteil, 3),
            "auch_in": nachbarn,
            # ohne amtlichen Eintrag: OSM kennt die Straße, das Verzeichnis
            # nicht — es führt nur Straßen mit Hausnummern
            "amtlich": amtlicher_name is not None,
        }
        if amtlicher_name and amtlicher_name != name:
            eintrag["amtliche_schreibweise"] = amtlicher_name
        eigene.append(eintrag)
    eigene.sort(key=lambda s: s["name"].lower())

    write_json(out / "strassen.json", {
        "beirat": args.beirat,
        "stand_verzeichnis": stand,
        "stand_geometrie": "2015 (Beiratsgebiete), OpenStreetMap tagesaktuell",
        "quellen": {
            "strassenverzeichnis": AMT_URL,
            "beiratsgebiete": BEIRAT_URL,
            "lizenz_stadt": "Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2.0)",
            "lizenz_osm": "ODbL, © OpenStreetMap-Mitwirkende",
        },
        "anzahl": len(eigene),
        "strassen": eigene,
        # Alle amtlichen Straßennamen der Stadt — Grundlage der Straßenerkennung
        # im Protokolltext. Protokolle nennen auch Straßen außerhalb des
        # Beiratsgebiets, deshalb die vollständige Liste und nicht nur die 128.
        "alle_namen": sorted(amt, key=str.lower),
    }, compact=False)

    namen = {s["name"] for s in eigene}
    write_json(out / "strassen.geojson", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {"name": n},
                      "geometry": {"type": "MultiLineString", "coordinates": linien[n]}}
                     for n in sorted(namen) if n in linien],
    }, compact=True)

    ohne = sum(1 for s in eigene if not s["amtlich"])
    log(f"  {len(eigene)} Straßen im Gebiet „{args.beirat}“ "
        f"({grenzlage} auf der Grenze, {ohne} nicht im amtlichen Verzeichnis)")

    # OSM-Themenobjekte für den Karten-Tab. Nicht kritisch — schlägt Overpass
    # hier fehl, bleiben die Straßendaten oben trotzdem erhalten.
    eigen_bbox = next(bb for name, _r, bb in gebiete if name == args.beirat)
    try:
        extract_osm_kategorien(out, finde, args.beirat, eigen_bbox)
    except Exception as e:
        log(f"  OSM-Kategorien übersprungen: {e}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
