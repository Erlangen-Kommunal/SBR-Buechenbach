# Geodaten

Grundlage für die Karte mit den Beiratsgrenzen und für die Sektion „Straßen im
Beiratsgebiet". Erzeugt von `tools/fetch_geodata.py` (nur Python-Standard­
bibliothek, keine pip-Abhängigkeit); der Wochen-Sync ruft das Skript mit auf.

```bash
python tools/fetch_geodata.py
```

| Datei | Inhalt |
|---|---|
| `beiraete.geojson` | Gebiete aller 13 Orts- und Stadtteilbeiräte; das eigene ist mit `"eigen": true` markiert |
| `strassen.json` | Die 128 Straßen im Beiratsgebiet mit statistischem Bezirk, dazu alle 914 amtlichen Straßennamen der Stadt |
| `strassen.geojson` | Geometrie dieser Straßen — damit zeigt das Portal eine Straße ohne Geokodierdienst |

## Quellen und Lizenzen

**Stadt Erlangen, Statistik und Stadtforschung** ([Open
Data](https://erlangen.de/aktuelles/opendata)) — amtliches Straßenverzeichnis
(„Statistische Bezirke nach Straßenabschnitten") und Vektorgeometrie der
Beiratsgebiete. Lizenz **dl-de/by-2.0**.

**OpenStreetMap** über die Overpass-API — Geometrie der Straßen.
Lizenz **ODbL**, © OpenStreetMap-Mitwirkende.

Beide Namensnennungen stehen in der Oberfläche (Kartenlegende und Fußzeile der
Straßen-Sektion).

## Wie die Zuordnung entsteht

Eine Straße gehört zum Gebiet, wenn ihre **Geometrie** darin liegt — nicht,
weil ihr statistischer Bezirk dazugehört. Der Umweg über den Bezirk wäre
falsch: Drei Bezirke im Stadtgebiet liegen quer über Beiratsgrenzen. Das
Verfahren stammt aus dem Schwesterprojekt UVPA, wo es gegen zwei unabhängige
Quellen geprüft wurde (dort `geo/README.md`); die Kurzfassung:

- Umgerechnete Bezirksgrenzen gegen das amtliche Straßenverzeichnis: 87,5 %
  exakt derselbe Bezirk, Abweichungen nur bei Straßen auf der Grenze.
- Der Verschnitt trifft bei allen sieben eindeutig benannten Ortsbeiräten zu
  100 % — das prüft das Verfahren, bevor es auf die Stadtteilbeiräte
  angewandt wird.

**8 Straßen liegen auf der Gebietsgrenze** und gehören damit auch zu einem
Nachbargebiet (Büchenbacher Steg, Kosbacher Damm, Steudacher Straße …). Sie
sind in der Liste mit ↔ markiert; ab 15 % Anteil zählt eine Straße zum Gebiet.

**5 Straßen kennt OpenStreetMap, das amtliche Verzeichnis nicht** — es führt
nur Straßen mit Hausnummern. Betroffen sind Dämme und Wirtschaftswege.

## Vorbehalt zur Geometrie

Die Satzung über Orts- und Stadtteilbeiräte nennt in § 1 die Namen; seit der
Fassung **ab 01.05.2026** verweist sie zusätzlich auf einen Plan als
Satzungsbestandteil (liegt unter `recht/` im Repository). Dieser Plan ist eine
Rasterkarte — als **Geodatei** veröffentlicht die Stadt die Beiratsgebiete
weiterhin nur im Stand **von 2015**. Die Zuordnung der damaligen Arbeitsnamen
auf die heutigen ist durch die Nummerierung belegt: der Plan von 2026 führt
dieselben Nummern.

Für Büchenbach ändert sich dadurch nichts. Betroffen ist nur **Anger/Bruck**:
seit 01.05.2026 zwei getrennte Beiräte, für die es keine getrennte Geometrie
gibt — sie erscheinen auf der Karte als ein Gebiet.

## Offen

- Getrennte Geometrie für Anger und Bruck sowie eine Bestätigung, dass die
  übrigen Gebiete seit 2015 unverändert sind — anzufragen bei Statistik und
  Stadtforschung.
