#!/usr/bin/env python3
"""Fachbeiräte und Ausschüsse aus dem Ratsinformationssystem (SessionNet) parallel aktualisieren.

Liest content/fachbeiraete.json, fragt für jedes Gremium die Sitzungstermine seit Mai 2020 ab,
aktualisiert die Sitzungsanzahl und das Datum der letzten Sitzung und setzt den aktuellen Stand.
"""
from __future__ import annotations

import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FACH_JSON = REPO / "content" / "fachbeiraete.json"
BASE = "https://ratsinfo.erlangen.de"
UA = "SBR-Infoportal/1.0 (ehrenamtlich; Kontakt ueber github.com/Erlangen-Kommunal)"

PERIODEN = [
    (2020, 5, 72),   # 2020-05 bis 2026-04 (1. Wahlperiode)
    (2026, 5, 84),   # 2026-05 bis 2033-04 (2. Wahlperiode)
]

TOP_ROW_RE = re.compile(r'(?is)<tr[^>]*class="smc-t-r-l"[^>]*>(.*?)</tr>')


def hole_sitzungen(kgrnr: int) -> tuple[int, str | None]:
    out = []
    for wp_jahr, wp_monat, wp_monate in PERIODEN:
        url = (f"{BASE}/si0046.asp?__cjahr={wp_jahr}&__cmonat={wp_monat}"
               f"&__canz={wp_monate}&smccont=85&__osidat=d&__kgsgrnr={kgrnr}&__cselect=65536")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                seite = resp.read().decode("utf-8", errors="replace")
                for row in TOP_ROW_RE.findall(seite):
                    m = re.search(r"si0057\.asp\?__ksinr=(\d+)", row)
                    d = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", row)
                    if m and d:
                        out.append((m.group(1), f"{d.group(3)}-{d.group(2)}-{d.group(1)}"))
        except Exception as e:
            print(f"  [Fehler bei kgrnr={kgrnr}]: {e}", flush=True)
    
    unique = list(dict.fromkeys(out))
    # Nur vergangene oder heutige Sitzungen für 'letzte_sitzung' berücksichtigen
    heute = date.today().isoformat()
    past_dates = [d for _, d in unique if d <= heute]
    past_dates.sort()
    
    cnt = len(unique)
    last_d = past_dates[-1] if past_dates else (unique[-1][1] if unique else None)
    return cnt, last_d


def main():
    if not FACH_JSON.exists():
        print(f"Fehler: {FACH_JSON} existiert nicht.", flush=True)
        return

    data = json.loads(FACH_JSON.read_text(encoding="utf-8"))
    eintraege = data.get("eintraege", [])
    print(f"Aktualisiere {len(eintraege)} Fachbeiräte und Ausschüsse parallel aus SessionNet...", flush=True)

    def verarbeite_eintrag(e):
        url = e.get("url", "")
        m = re.search(r"__kgrnr=(\d+)", url)
        if not m:
            return e, None
        kgrnr = int(m.group(1))
        name = e.get("name", f"Gremium {kgrnr}")
        cnt, last_d = hole_sitzungen(kgrnr)
        
        alt_cnt = e.get("sitzungen")
        alt_d = e.get("letzte_sitzung")
        
        diff = []
        if cnt == 0 and alt_cnt:
            # Nicht-öffentliche Gremien (z. B. Ältestenrat) ohne Treffer im öffentlichen Kalender
            pass
        elif alt_cnt != cnt:
            diff.append(f"Sitzungen: {alt_cnt} -> {cnt}")
            e["sitzungen"] = cnt
        if last_d is not None and alt_d != last_d:
            diff.append(f"letzte Sitzung: {alt_d} -> {last_d}")
            e["letzte_sitzung"] = last_d
            
        if diff:
            return e, f"  * {name}: {', '.join(diff)}"
        else:
            return e, f"  = {name}: unverändert ({cnt} Sitzungen, letzt: {last_d})"

    with ThreadPoolExecutor(max_workers=8) as ex:
        ergebnisse = list(ex.map(verarbeite_eintrag, eintraege))

    aenderungen = 0
    for _, log in ergebnisse:
        if log:
            print(log, flush=True)
            if "*" in log:
                aenderungen += 1

    data["stand"] = date.today().isoformat()
    FACH_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nFertig: {aenderungen} Gremien aktualisiert. Neuer Stand: {data['stand']}.", flush=True)


if __name__ == "__main__":
    main()
