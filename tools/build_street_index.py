#!/usr/bin/env python3
"""
tools/build_street_index.py
Erzeugt content/strassen_docs.json aus graph.db und geo/strassen.json.
Ermöglicht dem Frontend auf Mobilgeräten das sofortige Laden der Straßen-
Protokoll-Zuordnung ohne sekundenlange synchrone Volltext-Scans im Browser.
"""

import json
import re
from pathlib import Path
import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "graph.db"
GEO_STRASSEN = REPO_ROOT / "geo" / "strassen.json"
OUT_JSON = REPO_ROOT / "content" / "strassen_docs.json"

TOKEN_RE = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9.\-]*")
ADDR_TAIL_RE = re.compile(r"^[\s,]*\d{1,3}\s*[a-zA-Z]?[\s,]*9\d{4}\b")
MAX_WORTE = 4

def norm_street(s: str) -> str:
    s = s.lower().replace("strasse", "straße")
    return re.sub(r"[\s\-]+", "", s)

def detect_streets(text: str, namen: dict[str, str], max_found: int = 12) -> list[str]:
    found = {}
    tokens = list(TOKEN_RE.finditer(text))
    for i in range(len(tokens)):
        if len(found) >= max_found:
            break
        phrase_parts = []
        for n in range(MAX_WORTE):
            if i + n >= len(tokens):
                break
            tok = tokens[i + n]
            phrase_parts.append(tok.group(0))
            phrase = " ".join(phrase_parts)
            key = norm_street(phrase)
            amtlich = namen.get(key)
            if not amtlich or key in found:
                continue
            ende = tok.end()
            tail = text[ende : ende + 16]
            if ADDR_TAIL_RE.match(tail):
                continue
            found[key] = amtlich
    return list(found.values())

def main():
    if not DB_PATH.exists():
        print(f"Fehler: {DB_PATH} existiert nicht.")
        return 1
    if not GEO_STRASSEN.exists():
        print(f"Fehler: {GEO_STRASSEN} existiert nicht.")
        return 1

    geo_data = json.loads(GEO_STRASSEN.read_text(encoding="utf-8"))
    alle_namen = geo_data.get("alle_namen", [])
    if not alle_namen and "strassen" in geo_data:
        alle_namen = [s["name"] for s in geo_data["strassen"]]

    namen = {norm_street(n): n for n in alle_namen}
    print(f"{len(namen)} Straßennamen aus {GEO_STRASSEN.name} geladen.")

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    rows = conn.execute("""
        SELECT id, strftime(date, '%Y-%m-%d') AS date, category, title, text
        FROM documents
        WHERE text IS NOT NULL
        ORDER BY date DESC, title
    """).fetchall()
    conn.close()

    print(f"{len(rows)} Dokumente mit Volltext aus {DB_PATH.name} geladen.")

    index: dict[str, list[dict]] = {}
    total_refs = 0

    for doc_id, doc_date, category, title, text in rows:
        detected = detect_streets(text, namen, max_found=999)
        for name in detected:
            key = norm_street(name)
            if key not in index:
                index[key] = []
            index[key].append({
                "id": doc_id,
                "date": doc_date,
                "category": category,
                "title": title
            })
            total_refs += 1

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT_JSON.stat().st_size / 1024.0
    print(f"{OUT_JSON.name} geschrieben ({size_kb:.1f} KB, {len(index)} Straßen mit {total_refs} Erwähnungen).")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
