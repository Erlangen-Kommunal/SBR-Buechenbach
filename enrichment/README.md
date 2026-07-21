# Sitzungs-Zusammenfassungen (KI, manuell)

Dieser Ordner enthält je Sitzung eine kurze deutsche Zusammenfassung der
**Niederschrift** unter `docs/<pfad-der-pdf>.md` (z. B.
`docs/SBR/2025-10-15_Niederschrift_Niederschrift_3_Sitzung_Buechenbach.pdf.md`).
`GraphBuilder` liest diese `.md`, hängt Text und Themen an das Dokument in
`graph.db` und zeigt sie im Portal als Sitzungs-Überblick (und im Volltext-Index).

## Bewusste Trennung von der Automatik

- **Automatisch & deterministisch** (GitHub Actions): Der Wochen-Sync
  (`.github/workflows/sync.yml` → `SBR/uvp_agent.py --sync`) lädt neue Dokumente
  aus dem Ratsinfosystem. `deploy.yml` baut `graph.db` und veröffentlicht die
  Seite. **Kein LLM, kein API-Key in der CI.**
- **Manuell & lokal** (dieser Ordner): Die Zusammenfassungen schreibt der in der
  IDE integrierte KI-Agent von Hand — kein fremder API-Key nötig.

## Ablauf: neue Sitzung anreichern

1. **Was fehlt?** Zu jeder Sitzung gibt es eine Niederschrift in `SBR/index.json`.
   Fehlt dazu eine gleichnamige `.md` unter `docs/SBR/`, ist die Sitzung noch
   nicht angereichert (typisch nach einem Sync).
2. **Agent beauftragen:** „Reichere die noch nicht angereicherten Sitzungen an."
   Der Agent liest den Niederschrift-Text und schreibt die `.md` im Format unten.
3. **Committen.** Der Push löst `deploy.yml` aus; `graph.db` enthält dann die
   neue Zusammenfassung.

## Dateiformat (`docs/SBR/<niederschrift>.pdf.md`)

```markdown
---
themen: ["ÖPNV & Stadt-Umland-Bahn", "Verkehrssicherheit"]
modell: <name des verwendeten modells>
erstellt: JJJJ-MM-TT
---

<3–6 Sätze auf Deutsch: worum ging es in der Sitzung, was wurde vorgestellt,
beantragt oder beschlossen, welche Orte/Projekte in Büchenbach sind betroffen.
Keine Floskeln.>
```

- **`themen`**: 0–4 Einträge, ausschließlich aus der Taxonomie in
  [`themen.md`](themen.md). Intern mit `|` getrennt gespeichert (Namen können
  Kommas enthalten), im Frontmatter als JSON-Array.
- Der **Body** ist die Zusammenfassung — sie fließt in Suche und Portal.

Der Erst-Backfill (15 Sitzungen 2020–2025) liegt vollständig unter `docs/SBR/`.
