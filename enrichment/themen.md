# Themen-Taxonomie Stadtteilbeirat Büchenbach (kuratiert)

Grundlage für den Themen-Filter der Protokollsuche. Ein Dokument kann mehrere
Themen haben. Die Schlüsselwörter sind **Hinweise** für die Zuordnung durch den
KI-Agenten beim Anreichern (`enrichment/docs/<pfad>.md`), keine harten Regeln.
Intern werden Themen mit `|` getrennt gespeichert (Namen können Kommas enthalten),
im Frontmatter stehen sie als JSON-Array.

Ausschließlich Themen aus dieser Liste verwenden — sonst wächst der Filter
unkontrolliert.

## Sachthemen

| Thema | Schlüsselwörter (Hinweise) |
|-------|----------------------------|
| Verkehr & Mobilität | Verkehr, Straße, Kreuzung, Ampel, Tempo, Verkehrsberuhigung |
| Rad- & Fußverkehr | Radweg, Fahrrad, Gehweg, Fußgänger, Querung, Zebrastreifen |
| ÖPNV & Stadt-Umland-Bahn | Bus, ÖPNV, Haltestelle, Nahverkehr, StUB, Stadt-Umland-Bahn |
| Parken | Parkplatz, Stellplatz, Bewohnerparken, Parkraum |
| Verkehrssicherheit | Schulweg, Tempo 30, Unfall, Sicherheit im Verkehr, Beleuchtung |
| Wohnen & Stadtentwicklung | Wohnbau, Bebauungsplan, Quartier, Baugebiet, Stadtentwicklung, Nachverdichtung |
| Soziales & Nachbarschaft | Soziales, Wohnen im Alter, Diakonie, Nachbarschaft, Sozialstruktur, Integration |
| Kinder, Jugend & Familie | Kinder, Jugend, Jugendarbeit, Familie, Spielplatz, Jugendtreff |
| Senioren & Inklusion | Senioren, Barrierefreiheit, Inklusion, Pflege, Rikscha |
| Bildung (Schulen & Kitas) | Schule, Kita, Kindergarten, Hort, Bildung |
| Grün, Natur & Spielplätze | Grünanlage, Baum, Spielplatz, Park, Umwelt, Natur, Begrünung |
| Sport & Freizeit | Sport, Sportanlage, Freizeit, Verein, Bolzplatz, Sportentwicklung |
| Sicherheit & Ordnung | Sicherheit, Ordnung, Feuerwehr, Rettung, Defibrillator, Sauberkeit |
| Infrastruktur & Versorgung | Stromnetz, ESTW, EB77, Abfall, Straßenreinigung, Breitband, Versorgung |
| Bürgerbeteiligung & Gremien | Beteiligung, Bürgerversammlung, Antrag, Beirat, Satzung, Wahl |
| Vereine & Ehrenamt | Verein, Ehrenamt, Kirchengemeinde, Initiative, Bürgertreff |

## Format-Hinweis

Zusammenfassungen werden **je Sitzung** an der Niederschrift verankert
(`enrichment/docs/SBR/<niederschrift>.pdf.md`) und im Portal als Sitzungs-Überblick
gezeigt. 3–6 Sätze auf Deutsch: worum ging es, was wurde vorgestellt/beschlossen,
welche Themen und Orte in Büchenbach sind betroffen. Keine Floskeln.
