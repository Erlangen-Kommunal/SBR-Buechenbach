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
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
