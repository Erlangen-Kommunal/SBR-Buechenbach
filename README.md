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
- **Anträge & Stellungnahmen des Beirats** — die Schreiben an Oberbürgermeister,
  Fraktionen und Stadtrat, im selben Bereich wie die Protokolle
- **Satzung & Recht** — Rechtsgrundlage der Orts- und Stadtteilbeiräte,
  weiteres Stadtrecht
- **Statistik** — Bevölkerung, Sozialstruktur, Prognosen
- **Ämter** — welches Amt für welches Anliegen zuständig ist
- **Fachbeiräte** — Beiräte und Ausschüsse der Stadt, jeweils mit der letzten
  bekannten Sitzung; gezählt wird seit Mai 2020 über beide Wahlperioden hinweg
- **Büchenbach anderswo** — Tagesordnungspunkte von Stadtrat, Umwelt-, Verkehrs-
  und Planungs-, Sport- und Jugendhilfeausschuss mit Bezug zum Stadtteil, samt
  Belegstelle (siehe unten)
- **Straße & Karte** — Beiratsgrenze, Straßensuche mit Protokollbezug und
  einblendbare OSM-Themen (Spielplätze, Haltestellen, Nahversorgung, Denkmäler,
  Tempo-Beschränkungen …)

## Aufbau

```
SBR/                  Sitzungs-PDFs (flach) + index.json
SBR/Anträge_Übersicht/  Anträge des Beirats + antraege.json, ANTRAEGE.md
uvp_agent.py          Scraper: Index + PDFs aus dem Ratsinformationssystem
tools/                Geodaten, Tagesordnungen der Nachbargremien, Passwort-Hash
enrichment/           Zusammenfassungen je Sitzung + Themen-Taxonomie
content/              statische Abschnitte (Ämter, Fachbeiräte, Links, Karte)
recht/ statistik/     kuratierte Register
geo/                  Beiratsgrenzen, Straßenverzeichnis, Buslinien
gremien_tops.json     Tagesordnungen der Nachbargremien + Belege zum Ortsbezug
GraphBuilder/         C#/.NET — baut graph.db (DuckDB)
web/                  statisches Frontend (DuckDB-Wasm, Leaflet)
```

`graph.db` wird in der CI gebaut und ist **nicht** im Repo.

### Anträge: eigenes Register neben `index.json`

Die Anträge, Stellungnahmen und Briefe des Beirats stehen nicht im
Ratsinformationssystem — sie kommen vom Beirat selbst. `SBR/index.json` schreibt
der Wochen-Sync bei jedem Lauf neu, dort eingetragen wären sie beim nächsten Lauf
verschwunden. Sie liegen deshalb in `SBR/antraege.json`, das von Hand gepflegt
wird und Zusammenfassung und Themen gleich mitbringt (wie `recht/` und
`statistik/`, nicht wie `enrichment/`). GraphBuilder schreibt beide Quellen in
dieselbe `documents`-Tabelle; unterschieden werden sie über die Kategorie
`Antrag` bzw. `Anlage`. Im Portal erscheinen sie unter „Protokolle & Anträge" in
einem eigenen Abschnitt, in der Volltextsuche und im Straßenbezug gleichrangig
mit den Sitzungsdokumenten.

Ein neuer Antrag braucht also: die PDF nach `SBR/Anträge_Übersicht/`, einen
Eintrag in `SBR/antraege.json` und eine Zeile in `SBR/ANTRAEGE.md`.

### „Büchenbach anderswo": wie der Ortsbezug gefunden wird

`tools/fetch_gremien_tops.py` erfasst die Tagesordnungen von Stadtrat, Umwelt-,
Verkehrs- und Planungs-, Sport- und Jugendhilfeausschuss. **Ins Repo kommen nur
Metadaten und kurze Belegschnipsel, keine Dokumente** — der Bauausschuss allein
brächte grob 4.500 PDFs.

Gelesen wird trotzdem mehr, denn der Titel verrät den Ortsbezug oft nicht:

| Quelle | Warum sie nötig ist |
|---|---|
| **Titel** | reicht für den offensichtlichen Fall |
| **Vorlagentext** (HTML von `vo0050.asp`) | „Einrichtung neuer Tempo-30-Anordnungen" nennt Frankenwaldallee, Odenwaldallee und Mönaustraße erst im Sachverhalt. Kein PDF nötig, die Seite trägt den Text |
| **Anlagen der Vorlage** (PDF) | „Maßnahmen zur Kosteneinsparung im ÖPNV" nennt die Linie 298 erst in Anlage 1 — die Beschlussvorlage selbst enthält keine einzige Liniennummer |
| **Niederschrift der Sitzung** (PDF) | was tatsächlich gesagt wurde; an den `TOP <nr>`-Marken in Abschnitte zerlegt, sonst behauptet jeder TOP einer Sitzung den Bezug, den nur einer hat |

**Einladungen sind bewusst keine Quelle.** Sie enthalten nur die Tagesordnung
(2–4 KB), die ohnehin aus der Sitzungsseite geparst wird.

Zwei Signale zählen als Bezug: eine **Straße des Beiratsgebiets** (amtliches
Verzeichnis als Namensautorität, siehe `geo/README.md`) und eine **Buslinie, die
im Gebiet hält** (`geo/buslinien.json`). Eine Liniennummer zählt nur mit
Linien-Kontext davor — „Linie 298", „Buslinie 287T", „Stadtbus 286" —, nie als
nackte Zahl, sonst wäre jeder Haushaltsplan ein Treffer. Ausgenommen ist die
*Richt*linie.

Gespeichert wird davon nur der Beleg: gefundene Straßen, Linien und ein
Schnipsel mit Quellenangabe (`fundstellen`). Das Portal zeigt ihn aufklappbar
unter „Fundstelle" — ohne ihn sieht ein Eintrag, dessen Bezug erst in Anlage 3
steht, wie ein Fehlgriff aus.

**Kontingente.** Alle Anlagen zusammen sind rund 3,6 GB. Der Lauf liest sie
deshalb nur für Vorlagen ab `--anlagen-ab` (Vorgabe 2026) und höchstens
`--anlagen-budget` Stück je Lauf (Vorgabe 600), neueste zuerst; Bilddateien
(Lageplan, Grundriss, Präsentation …) und alles über 3 MB bleiben außen vor.
Ältere Jahrgänge holt man mit `--anlagen-ab 2024-01-01` nach.

**Buchführung.** Welche Vorlage mit welchem Ergebnis und welche Sitzung mit
welcher Niederschrift gelesen wurde, steht in `gremien_tops.json` unter
`geprueft` — auf **Dokumentebene**, nicht am einzelnen TOP. 398 Vorlagen werden
in mehreren Gremien beraten; am TOP geführt würden sie mehrfach geholt, und
4.100 TOPs ohne Fund trügen je einen leeren Block. Dadurch bleibt der
Wochen-Sync bei ein paar Dutzend Abrufen statt 3.000. Eine Sitzung ohne
Niederschrift wird bei jedem Lauf erneut nachgesehen — sie erscheint erst
Wochen später.

**Was das Verfahren nicht findet:** TOPs ohne Vorlage (Anfragen,
Fraktionsanträge — rund ein Viertel) haben nur ihren Titel; Anlagen vor 2026
sind ungelesen; Niederschriften fehlen für die jüngsten Sitzungen. Und es findet
zu viel, wo Namen doppelt belegt sind: „Sanierung Bachgraben" meint das
Gewässer, nicht die gleichnamige Straße, „Realschule am Europakanal" nur den
Schulnamen. Grob jeder achte Dokumenttreffer ist so einer — der sichtbare Beleg
soll das entscheidbar machen, statt es zu verstecken.

### Fallstricke des Ratsinformationssystems

Teuer erkaufte Erfahrungen, damit sie niemand zweimal macht:

- **Zwei Zeilen-Layouts.** Sitzungsseiten liefern entweder eine Liste mit
  `to0050`-Detaillinks je TOP oder ein Kartenlayout ganz ohne. Welches kommt,
  hängt an der **einzelnen Sitzung, nicht an der Wahlperiode**: Kartenlayout gibt
  es schon 2025, und noch im Mai 2026 tagte der Stadtrat im alten Layout. Der
  Parser probiert immer beides.
- **Synthetische `ktonr` sind keine URLs.** Im Kartenlayout hat ein TOP keine
  Detailseite; die Nummer wird gebildet (`<ksinr>_<TOP>`). `to0050.asp` antwortet
  darauf mit einer Fehlerseite — und zwar mit **HTTP 200**, ein Statuscode-Check
  fängt das nicht. Verlinkt wird deshalb die Vorlage (`vo0050`), ersatzweise die
  Sitzung (`si0057`).
- **PyMuPDF statt pypdf.** pypdf schiebt in diesen PDFs Leerzeichen in Wörter
  („Verband sversammlung"), was jede Namenssuche zerreißt. Beide stehen in
  `sync.yml`, PyMuPDF wird bevorzugt.
- **Aufzählungszeichen sind Symbolschrift.** Sie kommen als Zeichen aus dem
  Unicode-Privatbereich an und stehen im Browser als leere Kästchen. Werden vor
  dem Speichern herausgefiltert.
- **Wahlperioden einzeln abfragen.** Die Sitzungsliste (`si0046.asp`) will
  Startmonat und Monatszahl; eine Periode ist ein Aufruf. Seit Mai 2026 sind es
  zwei — `PERIODEN` im Skript.

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
python tools/fetch_geodata.py              # Geodaten + Buslinien auffrischen
python tools/fetch_gremien_tops.py         # Tagesordnungen der Nachbargremien
dotnet run --project GraphBuilder -- .     # graph.db bauen
cd web && python -m http.server            # lokal ansehen
```

Lokal fehlt `auth.json`, dann entfällt das Passwort-Gate. `gremien_tops.json`
liegt im Repo-Wurzelverzeichnis; wer `web/` ausliefert, sieht „Büchenbach
anderswo" leer — dann stattdessen das Wurzelverzeichnis servieren und
`/web/` aufrufen, so greift der Rückfallpfad `../gremien_tops.json`.

## Automatik

- `.github/workflows/sync.yml` — donnerstags 04:00 Europe/Berlin, deterministisch, ohne LLM
- `.github/workflows/deploy.yml` — bei jedem Push auf `main` nach GitHub Pages

Zusammenfassungen entstehen **nicht** in der CI, sondern werden lokal von einem
KI-Agenten geschrieben; siehe [enrichment/README.md](enrichment/README.md).
Themen ausschließlich aus [enrichment/themen.md](enrichment/themen.md) —
intern mit `|` getrennt, weil Themennamen Kommas enthalten können.

**Offen: gemeinsamer Lauf mit dem UVPA-Repo.** Beide Projekte ziehen aus
demselben Ratsinformationssystem, und die Dokumente des Umwelt-, Verkehrs- und
Planungsausschusses lädt `uvp_agent.py` dort ohnehin herunter — die
Tiefenprüfung hier holt sie ein zweites Mal. Naheliegend wäre zuerst ein
gemeinsamer Dokument-Cache (Schlüssel: `getfile`-ID, Inhalt: extrahierter Text
statt PDF), danach ein gemeinsames Modul für Abruf und PDF-Text, das heute
dreifach existiert.

## Hinweise für Mitarbeitende

- Pre-Commit-Hook blockt Dateien ab 12 MB: `git config core.hooksPath .githooks`
- Passwort-Gate ist eine Nutzungshürde, **kein Datenschutz**. Passwort in `.secrets` (gitignored).
- Bei Frontend-Änderungen `APP_VERSION`, `CONTENT_VERSION` (bustet `content/*.json`)
  und die `?v=`-Parameter in `index.html` **gemeinsam** hochzählen.
- Offene Punkte und Fallstricke: [OFFENE_PUNKTE.md im UVPA-Repo](https://github.com/Erlangen-Kommunal/UVPA/blob/main/OFFENE_PUNKTE.md)

## Daten und Lizenzen

Protokolle: Stadt Erlangen, Ratsinformationssystem (amtlich öffentlich).
Karten: [basemap.de](https://basemap.de) (BKG) und OpenStreetMap-Mitwirkende
(ODbL); aus OSM stammen auch die Themenobjekte und die Buslinien im Gebiet.
Beiratsgebiete: Stadt Erlangen, Statistik und Stadtforschung (dl-de/by-2.0),
Geometrie im Stand von 2015 — Näheres in [geo/README.md](geo/README.md).
