# Infoportal Stadtteilbeirat Büchenbach

Alles zur Arbeit des **Stadtteilbeirats Büchenbach** (Stadt Erlangen) an einem
Ort: die öffentlichen Sitzungsprotokolle seit 2020 mit Volltextsuche, die
Satzung und weiteres Stadtrecht, Statistik zum Stadtteil, Zuständigkeiten der
Ämter, verwandte Gremien, Links und eine Karte des Beiratsgebiets.

**→ https://erlangen-kommunal.github.io/SBR-Buechenbach/**

Ehrenamtlich erstellt. Es werden ausschließlich öffentlich zugängliche Daten
verwendet. Diese Anwendung steht in keiner Verbindung zur Stadt Erlangen.

Schwesterprojekt: [UVPA-Dokumentensuche](https://github.com/Erlangen-Kommunal/UVPA).

---

## Was drin ist

- **Öffentliche Sitzungsprotokolle** seit 2020 (Einladungen, Niederschriften,
  Anhänge), im Volltext durchsuchbar, mit einer Zusammenfassung je Sitzung
- **Satzung & Recht** — Rechtsgrundlage der Orts- und Stadtteilbeiräte,
  weiteres Stadtrecht
- **Statistik** — Bevölkerung, Sozialstruktur, Prognosen
- **Ämter** — welches Amt für welches Anliegen zuständig ist
- **Fachbeiräte** — Beiräte und Ausschüsse der Stadt, jeweils mit der letzten
  Sitzung der Wahlperiode 2020–2026
- **Karte** — Grenzen des Beiratsgebiets, auf Wunsch mit amtlichem Luftbild und
  Flurstücken
- **Straßen** — alle Straßen im Beiratsgebiet und die Protokolle dazu

## Aufbau

```
SBR/                  Sitzungs-PDFs (flach) + index.json
uvp_agent.py          Scraper: Index + PDFs aus dem Ratsinformationssystem
tools/                Geodaten, Passwort-Hash, link-content.ps1
enrichment/           Zusammenfassungen je Sitzung + Themen-Taxonomie
content/              statische Abschnitte (Ämter, Fachbeiräte, Links, Karte)
recht/ statistik/     kuratierte Register
geo/                  Beiratsgrenzen, Straßenverzeichnis
GraphBuilder/         C#/.NET — baut graph.db (DuckDB)
web/                  statisches Frontend (DuckDB-Wasm, Leaflet)
```

`graph.db` wird in der CI gebaut und ist **nicht** im Repo.

### `content/` ist kanonisch — `web/content/` nur eine Verknüpfung

Das Frontend lädt `content/<name>.json` relativ zur Seite. Im Deploy landet das
Verzeichnis per `cp -r content _site/content` neben der `index.html`, beim
lokalen Entwickeln wird `web/` ausgeliefert und braucht es dort ebenfalls.

`web/content` ist deshalb eine **Junction auf `content/`** und in `.gitignore`.
Nach einem frischen Clone einmal anlegen:

```powershell
pwsh -File tools/link-content.ps1
```

Früher lag dort eine echte Kopie. Die ist unbemerkt auseinandergelaufen — weil
`web/content/` ignoriert wird, blieben Änderungen daran lokal, während die
ausgelieferte Datei monatelang veraltet war. Deshalb die Junction: **niemals
wieder zwei Stände.**

## Selbst bauen

```bash
python uvp_agent.py --sync                 # Index + neue PDFs (kein API-Key nötig)
python tools/fetch_geodata.py              # Geodaten auffrischen
dotnet run --project GraphBuilder -- .     # graph.db bauen
cd web && python -m http.server            # lokal ansehen
```

Lokal fehlt `auth.json`, dann entfällt das Passwort-Gate.

## Automatik

- `.github/workflows/sync.yml` — donnerstags 04:00 Europe/Berlin, deterministisch, ohne LLM
- `.github/workflows/deploy.yml` — bei jedem Push auf `main` nach GitHub Pages

Zusammenfassungen entstehen **nicht** in der CI, sondern werden lokal von einem
KI-Agenten geschrieben; siehe [enrichment/README.md](enrichment/README.md).
Themen ausschließlich aus [enrichment/themen.md](enrichment/themen.md) —
intern mit `|` getrennt, weil Themennamen Kommas enthalten können.

## Hinweise für Mitarbeitende

- Pre-Commit-Hook blockt Dateien ab 12 MB: `git config core.hooksPath .githooks`
- Passwort-Gate ist eine Nutzungshürde, **kein Datenschutz**. Passwort in `.secrets` (gitignored).
- Bei Frontend-Änderungen `APP_VERSION`, `CONTENT_VERSION` (bustet `content/*.json`)
  und die `?v=`-Parameter in `index.html` **gemeinsam** hochzählen.
- Offene Punkte und Fallstricke: [OFFENE_PUNKTE.md im UVPA-Repo](https://github.com/Erlangen-Kommunal/UVPA/blob/main/OFFENE_PUNKTE.md)

## Daten und Lizenzen

Protokolle: Stadt Erlangen, Ratsinformationssystem (amtlich öffentlich).
Karten: [basemap.de](https://basemap.de) (BKG), OpenStreetMap-Mitwirkende (ODbL),
Luftbild und Flurstücke der Bayerischen Vermessungsverwaltung (CC BY 4.0).
Beiratsgebiete: Stadt Erlangen, Statistik und Stadtforschung (dl-de/by-2.0),
Geometrie im Stand von 2015 — Näheres in [geo/README.md](geo/README.md).
