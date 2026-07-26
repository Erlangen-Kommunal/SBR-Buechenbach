#!/usr/bin/env python3
"""Änderungsreport für den Wochen-Sync — Markdown mit inhaltlichem Kontext.

Läuft in der CI NACH den Sync-Schritten (uvp_agent --sync, fetch_geodata,
fetch_gremien_tops) und VOR dem Commit: verglichen wird der Arbeitsstand mit
HEAD (= main). Der Report wird PR-Beschreibung und E-Mail an den Admin — er
soll die Frage „Was kommt da eigentlich rein?" beantworten, ohne dass man
jede Datei öffnen muss:

- neue Sitzungsdokumente mit Datum/Kategorie/Titel aus SBR/index.json,
- neue Tagesordnungspunkte anderer Gremien (Büchenbach-Bezug hervorgehoben),
- Geodaten als Objektzahl-Vergleich statt GeoJSON-Diff,
- alles Übrige als schlichte Dateiliste.

Nur Standardbibliothek. Jede Sektion fängt ihre Fehler selbst — ein kaputtes
JSON darf den Report nicht verhindern, sonst gäbe es gar keine Information.

Aufruf:  python tools/sync_report.py --out-dir <dir>
         → schreibt <dir>/report.md und <dir>/title.txt
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def head_json(path: str):
    """Datei-Inhalt aus HEAD als JSON; None, wenn dort (noch) nicht vorhanden."""
    try:
        return json.loads(git("show", f"HEAD:{path}"))
    except (RuntimeError, json.JSONDecodeError):
        return None


def work_json(path: str):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def changed_files() -> dict[str, str]:
    """Pfad → Status (A neu, M geändert, D gelöscht). Untracked zählt als A."""
    out: dict[str, str] = {}
    for line in git("status", "--porcelain").splitlines():
        st, path = line[:2], line[3:]
        if path.startswith('"') and path.endswith('"'):
            # git quotet Nicht-ASCII-Pfade C-artig; für die Anzeige reicht das Roh-Unquoting
            path = path[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
            path = path.encode("latin-1", "replace").decode("utf-8", "replace")
        if st == "??":
            out[path] = "A"
        elif "D" in st:
            out[path] = "D"
        elif "A" in st:
            out[path] = "A"
        else:
            out[path] = "M"
    return out


def fmt_date(iso: str) -> str:
    try:
        return dt.date.fromisoformat(iso[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return iso


def fmt_size(path: str) -> str:
    try:
        return f"{(ROOT / path).stat().st_size / 1048576:.1f} MB"
    except OSError:
        return "?"


def kurz(text: str, max_len: int = 280) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


# ── Sektionen ────────────────────────────────────────────────────────────────

def sektion_dokumente(files: dict[str, str]) -> tuple[list[str], int]:
    """Neue PDFs unter SBR/ mit Metadaten aus dem frisch gesyncten index.json."""
    neue = sorted(p for p, st in files.items()
                  if st == "A" and p.startswith("SBR/") and p.lower().endswith(".pdf"))
    if not neue:
        return [], 0
    index = {d.get("filename"): d for d in (work_json("SBR/index.json") or [])}
    zeilen = [f"## 📄 Neue Sitzungsdokumente ({len(neue)})", ""]
    for p in neue:
        meta = index.get(Path(p).name)
        if meta:
            zeilen.append(f"- **{fmt_date(meta.get('date', '?'))} · {meta.get('category', '?')}** — "
                          f"{meta.get('title', Path(p).name)} (`{p}`, {fmt_size(p)})")
        else:
            zeilen.append(f"- `{p}` ({fmt_size(p)}) — *nicht im Dokumentindex; bitte prüfen*")
    zeilen.append("")
    return zeilen, len(neue)


def sektion_tops(files: dict[str, str]) -> tuple[list[str], int]:
    """Neue Tagesordnungspunkte aus gremien_tops.json, Bezug hervorgehoben."""
    if "gremien_tops.json" not in files:
        return [], 0
    alt, neu = head_json("gremien_tops.json"), work_json("gremien_tops.json")
    if not neu:
        return ["## 🏛️ Tagesordnungen anderer Gremien", "",
                "- Datei geändert, aber nicht lesbar — bitte den Diff prüfen.", ""], 0

    def key(t: dict):  # ktonr ist die TOP-Nummer des Ratsinfosystems, stabil je Punkt
        return t.get("ktonr") or (t.get("gremium"), t.get("datum"), t.get("top"), t.get("titel"))

    alte_keys = {key(t) for t in (alt or {}).get("tops", [])}
    dazu = [t for t in neu.get("tops", []) if key(t) not in alte_keys]
    if not dazu:
        return ["## 🏛️ Tagesordnungen anderer Gremien", "",
                "- Keine neuen Punkte (nur Metadaten wie `stand` aktualisiert).", ""], 0

    relevant = [t for t in dazu if t.get("relevant") and not t.get("routine")]
    rest = [t for t in dazu if t not in relevant]
    zeilen = [f"## 🏛️ Neue Tagesordnungspunkte anderer Gremien "
              f"({len(dazu)}, davon {len(relevant)} mit Büchenbach-Bezug)", ""]
    for t in sorted(relevant, key=lambda t: t.get("datum") or "", reverse=True):
        marker = ", ".join(filter(None, [
            ", ".join(t.get("strassen_im_gebiet") or []),
            "nennt Büchenbach" if t.get("nennt_ort") else "",
        ]))
        zeilen.append(f"- **{fmt_date(t.get('datum', '?'))} · {t.get('gremium', '?')}"
                      f"{' · TOP ' + t['top'] if t.get('top') else ''}** — {t.get('titel', '?')}")
        if marker:
            zeilen.append(f"  - Bezug: {marker}")
        if t.get("beschluss"):
            zeilen.append(f"  - Beschluss: {kurz(t['beschluss'])}")
        if t.get("url"):
            zeilen.append(f"  - {t['url']}")
    if rest:
        je_gremium: dict[str, int] = {}
        for t in rest:
            je_gremium[t.get("gremium", "?")] = je_gremium.get(t.get("gremium", "?"), 0) + 1
        zeilen.append("")
        zeilen.append("Ohne erkannten Bezug (im Portal ausgeblendet bzw. Routine): "
                      + " · ".join(f"{g}: {n}" for g, n in sorted(je_gremium.items())))
    zeilen.append("")
    return zeilen, len(dazu)


def sektion_geo(files: dict[str, str]) -> list[str]:
    """Geodaten: Objektzahlen alt → neu statt eines unlesbaren GeoJSON-Diffs."""
    geo = sorted(p for p in files if p.startswith("geo/") and p.endswith((".json", ".geojson")))
    if not geo:
        return []
    zeilen = ["## 🗺️ Geodaten", ""]
    for p in geo:
        alt, neu = head_json(p), work_json(p)
        if p.endswith(".geojson"):
            a = len((alt or {}).get("features", [])) if alt else "—"
            n = len((neu or {}).get("features", [])) if neu else "—"
            zeilen.append(f"- `{p}`: {a} → {n} Objekte")
        elif p.endswith("strassen.json"):
            a_namen = {s.get("name") for s in (alt or {}).get("strassen", [])}
            n_namen = {s.get("name") for s in (neu or {}).get("strassen", [])}
            zeile = f"- `{p}`: {len(a_namen) if alt else '—'} → {len(n_namen)} Straßen"
            if plus := sorted(n_namen - a_namen):
                zeile += f" · neu: {', '.join(plus)}"
            if minus := sorted(a_namen - n_namen):
                zeile += f" · entfallen: {', '.join(minus)}"
            zeilen.append(zeile)
        elif p.endswith("osm_kategorien.json"):
            def counts(d):
                return {k["key"]: k.get("count", 0)
                        for k in (d or {}).get("punkt", []) + (d or {}).get("linie", [])}
            ca, cn = counts(alt), counts(neu)
            diffs = [f"{k}: {ca.get(k, 0)} → {v}" for k, v in cn.items() if ca.get(k, 0) != v]
            zeilen.append(f"- `{p}`: " + ("; ".join(diffs) if diffs else "Zählwerte unverändert"))
        else:
            zeilen.append(f"- `{p}` geändert")
    zeilen.append("")
    return zeilen


def sektion_rest(files: dict[str, str], schon_berichtet: set[str]) -> list[str]:
    uebrig = {p: st for p, st in sorted(files.items()) if p not in schon_berichtet}
    if not uebrig:
        return []
    label = {"A": "neu", "M": "geändert", "D": "gelöscht"}
    zeilen = ["## 🔧 Übrige Änderungen", ""]
    for p, st in uebrig.items():
        hinweis = ""
        if st == "M" and p.lower().endswith(".pdf"):
            hinweis = " — vorhandenes PDF neu geschrieben (vermutlich Kompression); bitte prüfen"
        zeilen.append(f"- {label[st]}: `{p}`{hinweis}")
    zeilen.append("")
    return zeilen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    files = changed_files()
    heute = dt.date.today().isoformat()

    if not files:
        (out / "report.md").write_text("Keine Änderungen.\n", encoding="utf-8")
        (out / "title.txt").write_text(f"Wochen-Sync Ratsinfo ({heute}): keine Änderungen",
                                       encoding="utf-8")
        print("Keine Änderungen.")
        return

    teile: list[str] = [f"# Wochen-Sync Ratsinfo — Änderungsreport ({heute})", ""]
    berichtet: set[str] = set()
    n_docs = n_tops = 0

    for name, fn in [("Dokumente", sektion_dokumente), ("Tagesordnungen", sektion_tops)]:
        try:
            zeilen, n = fn(files)
            teile += zeilen
            if name == "Dokumente":
                n_docs = n
                berichtet |= {p for p in files if p.startswith("SBR/") and p.lower().endswith(".pdf")
                              and files[p] == "A"}
                berichtet |= {p for p in files if p == "SBR/index.json"}
            else:
                n_tops = n
                berichtet.add("gremien_tops.json")
        except Exception as e:  # Sektion kaputt → vermerken, Report geht weiter
            teile += [f"## ⚠️ Sektion {name} fehlgeschlagen", "", f"- {e}", ""]

    try:
        geo_zeilen = sektion_geo(files)
        teile += geo_zeilen
        berichtet |= {p for p in files if p.startswith("geo/")}
    except Exception as e:
        teile += ["## ⚠️ Sektion Geodaten fehlgeschlagen", "", f"- {e}", ""]

    teile += sektion_rest(files, berichtet)
    teile += [
        "---",
        "",
        "**Prüfhinweise:** Sind alle Dokumente plausibel benannt und stammen die",
        "Links aus `ratsinfo.erlangen.de`? Wirken die Geodaten-Zählwerte glaubhaft",
        "(OSM ist von jedermann editierbar)? Erst der **Merge** dieses PRs",
        "veröffentlicht die Daten — der Deploy läuft danach automatisch.",
        "",
    ]

    stichworte = []
    if n_docs:
        stichworte.append("1 neues Dokument" if n_docs == 1 else f"{n_docs} neue Dokumente")
    if n_tops:
        stichworte.append("1 neuer TOP" if n_tops == 1 else f"{n_tops} neue TOPs")
    if not stichworte:
        stichworte.append("Daten aktualisiert")
    titel = f"Wochen-Sync Ratsinfo ({heute}): " + ", ".join(stichworte)

    (out / "report.md").write_text("\n".join(teile), encoding="utf-8")
    (out / "title.txt").write_text(titel, encoding="utf-8")
    print(titel)


if __name__ == "__main__":
    sys.exit(main())
