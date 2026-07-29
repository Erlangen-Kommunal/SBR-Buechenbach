"""Tagesordnungspunkte benachbarter Gremien holen.

Warum keine Dokumente ins Repo wandern: Der Bauausschuss allein brächte grob
4.500 PDFs und würde das Repo etwa verdoppeln. Gespeichert werden deshalb nur
Metadaten — Titel, TOP-Nummer, Datum, Gremium, Beschlusstext, Vorlagennummer
(`kvonr`) und ein Deeplink.

Gelesen wird trotzdem mehr: Ein Titel wie „Einrichtung neuer Tempo-30-Anordnungen
für mehr Verkehrssicherheit" verrät nicht, dass es darin um Frankenwaldallee,
Odenwaldallee und Münaustraße geht, und „Maßnahmen zur Kosteneinsparung im ÖPNV"
nennt die Linie 298 erst in Anlage 1. Die Tiefenprüfung liest deshalb den
Vorlagentext (HTML), die Anlagen (PDF) und die Niederschrift (PDF, je Sitzung
eine). Gesucht wird nach Straßen des Beiratsgebiets und nach Buslinien, die hier
halten (geo/buslinien.json). Ins Repo kommt davon nur der Beleg: die gefundenen
Straßen, Linien und ein kurzer Schnipsel als `fundstellen`. Einladungen sind
bewusst keine Quelle — sie enthalten nur die Tagesordnung, die ohnehin schon
erfasst ist.

Die Anlagen sind zusammen rund 3,6 GB. Deshalb liest der Lauf sie nur für
Vorlagen ab --anlagen-ab (Vorgabe 2026) und je Lauf höchstens --anlagen-budget
Stück, neueste zuerst; Bilddateien und alles über 3 MB bleiben außen vor.

Routine-Tagesordnungspunkte („Anfragen", „Mitteilungen zur Kenntnis" …) werden
nicht weggeworfen, sondern als `routine: true` markiert — wegwerfen hieße, eine
Vollständigkeit zu behaupten, die die Daten nicht hergeben. Das Frontend blendet
sie standardmäßig aus.

Der Lauf ist inkrementell: erfasste Sitzungen und schon gelesene Dokumente
werden übersprungen (`geprueft` auf oberster Ebene), solange nicht --force
gesetzt ist.
Vergangene Sitzungen ändern sich nicht mehr; Niederschriften erscheinen aber
später als die Sitzung, deshalb wird eine Sitzung ohne Niederschrift bei jedem
Lauf erneut nachgesehen.

Standardbibliothek plus optional PyMuPDF oder pypdf für die Niederschriften
(beide stehen in .github/workflows/sync.yml). Fehlen beide, laufen die übrigen
Quellen unverändert weiter.

Aufruf:
    python tools/fetch_gremien_tops.py
    python tools/fetch_gremien_tops.py --force
    python tools/fetch_gremien_tops.py --ohne-tiefenpruefung
    python tools/fetch_gremien_tops.py --anlagen-ab 2024-01-01 --anlagen-budget 300
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

# PyMuPDF zuerst: pypdf schiebt in den Niederschriften Leerzeichen in Wörter
# („Verband sversammlung"), was die Straßensuche zerreißt. Beide sind optional.
try:
    import fitz
except ImportError:
    fitz = None
try:
    import pypdf
except ImportError:
    pypdf = None

REPO = Path(__file__).resolve().parent.parent
OUT_JSON = REPO / "gremien_tops.json"

BASE = "https://ratsinfo.erlangen.de"
UA = "SBR-Infoportal/1.0 (ehrenamtlich; Kontakt ueber github.com/Erlangen-Kommunal)"

# ── Projektspezifisch: welche Nachbargremien interessieren ───────────────────
# Der Stadtteilbeirat ist örtlich zuständig, nicht fachlich. Interessant ist
# daher, was andernorts über Büchenbach entschieden wird: der Stadtrat als
# beschließendes Gremium, der Umwelt-, Verkehrs- und Planungsausschuss (Straßen,
# Bebauungspläne, ÖPNV — der Löwenanteil der ortsbezogenen Beschlüsse) sowie
# Sport- und Jugendhilfeausschuss, deren Einrichtungen (Sportanlagen, Kitas,
# Jugendtreffs) im Stadtteil liegen.
GREMIEN = {
    1: "Stadtrat",
    15: "Umwelt-, Verkehrs- und Planungsausschuss",
    11: "Sportausschuss",
    19: "Jugendhilfeausschuss",
}

# Wahlperioden: je Eintrag (Startjahr, Startmonat, Anzahl_Monate).
# Neue Amtszeit ab Mai 2026 (Kommunalwahl Bayern 2026). 84 Monate = 7 Jahre Puffer;
# das Skript holt nur Sitzungen, die das RIS tatsächlich kennt.
PERIODEN = [
    (2020, 5, 72),   # 2020-05 – 2026-04 (1. Wahlperiode)
    (2026, 5, 84),   # 2026-05 – 2033-04 (2. Wahlperiode, Puffer)
]

# Wiederkehrende Formalpunkte ohne eigenen Sachgehalt. Anker auf Zeilenanfang,
# damit „Anfragen zur Verkehrssituation …" nicht mitgefangen wird.
ROUTINE = [
    re.compile(p, re.I) for p in (
        r"^Anfragen\b",
        r"^Mitteilung(en)? zur Kenntnis\b",
        r"^Bericht aus (der )?nicht ?öffentlicher? Sitzung",
        r"^Bearbeitungsstand (der )?Fraktionsanträge",
        r"^Genehmigung der Niederschrift",
        r"^Niederschrift(en)? (der|über)",
        r"^Verschiedenes$",
        r"^Bekanntgaben?$",
        r"^Einwohnerfrage(n|stunde)",
        r"^Beschlussüberwachung",
        r"^Strategisches Management",
        # Personalien der Beiräte: nennen den Ortsnamen und werden dadurch als
        # ortsbezogen erkannt, haben aber keinen Sachgehalt für die Stadtteilarbeit.
        r"^Änderung(en)? (im|in den|in dem) (Stadtteil|Orts)",
        r"^Änderung(en)? in den (Stadtteil|Orts)beiräten",
    )
]

# ── Ortsbezug ────────────────────────────────────────────────────────────────
# Das amtliche Straßenverzeichnis ist die Namensautorität (geo/strassen.json).
# Verglichen wird über Wort-n-Gramme, NICHT über Teilzeichenketten: sonst gilt
# „Schallershofer Straße" als Treffer für „Hofer Straße". Normalisiert werden
# Umlaute, Bindestriche und Leerzeichen, damit die OSM-Schreibweise
# („Adenauerring") auf die amtliche („Adenauer-Ring") trifft.
MAX_STRASSEN_WORTE = 4  # längster amtlicher Name: „An der Weißen Marter"


def norm_strasse(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("-", ""), (" ", ""), (".", "")):
        s = s.replace(a, b)
    return s


def lade_strassen() -> dict[str, str]:
    p = REPO / "geo" / "strassen.json"
    if not p.exists():
        print("Hinweis: geo/strassen.json fehlt — kein Straßenbezug.")
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    namen = [s["name"] if isinstance(s, dict) else s for s in d.get("strassen", [])]
    namen += [s.get("amtliche_schreibweise") for s in d.get("strassen", [])
              if isinstance(s, dict) and s.get("amtliche_schreibweise")]
    namen += d.get("alle_namen", [])
    return {norm_strasse(n): n for n in namen if n and len(n) > 4}


def lade_gebiet() -> tuple[set[str], str]:
    """Normalisierte Namen der Straßen im Beiratsgebiet + Name des Beirats.

    Getrennt vom stadtweiten Verzeichnis, weil der Stadtteilbeirat örtlich
    zuständig ist: Ein Tagesordnungspunkt zur Henkestraße ist für Büchenbach
    ohne Belang, einer zum Adenauer-Ring nicht.
    """
    p = REPO / "geo" / "strassen.json"
    if not p.exists():
        return set(), ""
    d = json.loads(p.read_text(encoding="utf-8"))
    namen: set[str] = set()
    for s in d.get("strassen", []):
        if isinstance(s, dict):
            namen.add(norm_strasse(s["name"]))
            if s.get("amtliche_schreibweise"):
                namen.add(norm_strasse(s["amtliche_schreibweise"]))
        else:
            namen.add(norm_strasse(s))
    namen.discard("")
    return namen, d.get("beirat", "")


def lade_linien() -> set[str]:
    """Nummern der Linien, die im Beiratsgebiet halten (geo/buslinien.json).

    Ein Beschluss wie „Kein Weiterbetrieb der Linie 298" nennt weder Büchenbach
    noch eine Straße und streicht dem Stadtteil trotzdem eine Verbindung.
    """
    p = REPO / "geo" / "buslinien.json"
    if not p.exists():
        return set()
    d = json.loads(p.read_text(encoding="utf-8"))
    return {str(l["ref"]).strip() for l in d.get("linien", []) if l.get("ref")}


# Nummern zählen nur mit Linien-Kontext davor: „298" allein ist in einem
# Haushaltsplan eine Zahl unter vielen. Der Kontext deckt Zusammensetzungen ab
# („Nachtlinie", „Buslinie", „Stadtbus") und Aufzählungen („Linien 293, 296 und
# 298"), aber ausdrücklich nicht die Richtlinie — davon handelt jeder dritte
# Beschluss, und ihre Nummern sind keine Fahrpläne.
LINIEN_KONTEXT_RE = re.compile(
    r"(?i)\b(?:(?:stadt-?)?bus(?:linien?)?|\w*?(?<!richt)linien?)\b[\s:]*"
    r"((?:[A-Z]?\d{1,3}[A-Z]?)(?:\s*(?:,|/|und|bis|\+|&)\s*[A-Z]?\d{1,3}[A-Z]?)*)")
LINIEN_NUMMER_RE = re.compile(r"[A-Z]?\d{1,3}[A-Z]?")


def linien_in(text_: str, refs: set[str]) -> list[str]:
    if not refs:
        return []
    out = set()
    for m in LINIEN_KONTEXT_RE.finditer(text_):
        for nummer in LINIEN_NUMMER_RE.findall(m.group(1)):
            if nummer in refs:
                out.add(nummer)
    return sorted(out, key=lambda r: (len(r), r))


def strassen_in(titel: str, nmap: dict[str, str]) -> list[str]:
    woerter = re.findall(r"[A-Za-zÄÖÜäöüß.\-]+", titel)
    out = set()
    for i in range(len(woerter)):
        for k in range(1, MAX_STRASSEN_WORTE + 1):
            if i + k > len(woerter):
                break
            treffer = nmap.get(norm_strasse("".join(woerter[i:i + k])))
            if treffer:
                out.add(treffer)
    return sorted(out)


TOP_ROW_RE = re.compile(r'(?is)<tr[^>]*class="smc-t-r-l"[^>]*>(.*?)</tr>')
NUM_RE = re.compile(r'(?is)class="tofnum".*?<span[^>]*>(.*?)</span>')
# Das RIS liefert zwei Zeilen-Layouts. Welches kommt, hängt an der einzelnen
# Sitzung, NICHT an der Wahlperiode: Kartenlayout gibt es schon 2025, und noch
# im Mai 2026 tagte der Stadtrat im alten Layout. Deshalb immer beides probieren.
# Listen-Layout: TOP hat einen to0050-Link mit smc_datatype_to-Klasse.
TITLE_RE = re.compile(r'(?is)href="to0050\.asp\?__ktonr=(\d+)"[^>]*class="[^"]*smc_datatype_to[^"]*"[^>]*>(.*?)</a>')
# Kartenlayout: kein to0050-Link, der Titel steht in einem Div — es gibt für
# diese TOPs keine Detailseite, die ktonr wird deshalb synthetisiert (top_url).
TITLE_NEW_RE = re.compile(r'(?is)class="[^"]*smc-card-header-title(?:-simple)?[^"]*"[^>]*>(.*?)</(?:div|a|span)>')
VORLAGE_RE = re.compile(r'(?is)href="vo0050\.asp\?__kvonr=(\d+)"')
BESCHLUSS_RE = re.compile(r'(?is)smc_field_smcdv0_box\d+_beschluss[^>]*>(.*?)</p>')


def text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def top_url(t: dict) -> str:
    """Bester belastbarer Link zum TOP.

    Nur echte (numerische) ktonr haben eine Detailseite; mit einer
    synthetischen ktonr antwortet `to0050.asp` mit der SessionNet-Fehlerseite
    (HTTP 200, geprüft). Dann führt die Vorlage am nächsten ans Thema heran,
    sonst die Sitzungsseite, auf der der TOP steht.
    """
    if t["ktonr"].isdigit():
        return f"{BASE}/to0050.asp?__ktonr={t['ktonr']}"
    if t.get("kvonr"):
        return f"{BASE}/vo0050.asp?__kvonr={t['kvonr']}"
    return f"{BASE}/si0057.asp?__ksinr={t['ksinr']}"


def hole(url: str, versuche: int = 3) -> str:
    letzter = None
    for n in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            letzter = e
            time.sleep(1.5 * (n + 1))
    raise RuntimeError(f"{url}: {letzter}")


def sitzungen(kgrnr: int) -> list[tuple[str, str]]:
    """(ksinr, ISO-Datum) aller Sitzungen des Gremiums über alle Wahlperioden."""
    out = []
    for wp_jahr, wp_monat, wp_monate in PERIODEN:
        url = (f"{BASE}/si0046.asp?__cjahr={wp_jahr}&__cmonat={wp_monat}"
               f"&__canz={wp_monate}&smccont=85&__osidat=d&__kgsgrnr={kgrnr}&__cselect=65536")
        seite = hole(url)
        for row in TOP_ROW_RE.findall(seite):
            m = re.search(r"si0057\.asp\?__ksinr=(\d+)", row)
            d = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", row)
            if m and d:
                out.append((m.group(1), f"{d.group(3)}-{d.group(2)}-{d.group(1)}"))
    return list(dict.fromkeys(out))


def tops(ksinr: str) -> list[dict]:
    seite = hole(f"{BASE}/si0057.asp?__ksinr={ksinr}")
    out = []
    for row in TOP_ROW_RE.findall(seite):
        t = TITLE_RE.search(row)
        if t:
            # Altes Format: ktonr aus to0050-Link
            titel = text(t.group(2))
            if len(titel) < 4:
                continue
            nummer = NUM_RE.search(row)
            vorlage = VORLAGE_RE.search(row)
            beschluss = BESCHLUSS_RE.search(row)
            out.append({
                "ktonr": t.group(1),
                "top": text(nummer.group(1)) if nummer else "",
                "titel": titel,
                "kvonr": vorlage.group(1) if vorlage else "",
                "beschluss": text(beschluss.group(1)).removeprefix("Beschluss:").strip() if beschluss else "",
                "routine": any(r.search(titel) for r in ROUTINE),
            })
        else:
            # Neues Format (ab WP 2026): kein to0050-Link; Titel im smc-card-header-title-Div.
            t2 = TITLE_NEW_RE.search(row)
            if not t2:
                continue
            titel = text(t2.group(1))
            if len(titel) < 4:
                continue
            # Abschnittsüberschriften ("Werkausschuss EB77:", "Empfehlungen:") überspringen.
            if titel.endswith(":") and len(titel) < 60:
                continue
            nummer = NUM_RE.search(row)
            top_num = text(nummer.group(1)) if nummer else ""
            vorlage = VORLAGE_RE.search(row)
            beschluss = BESCHLUSS_RE.search(row)
            # Synthetische ktonr: ksinr_TOPNUM (eindeutig je Sitzung).
            syn_ktonr = f"{ksinr}_{top_num.replace(' ', '_') or str(len(out))}"
            out.append({
                "ktonr": syn_ktonr,
                "top": top_num,
                "titel": titel,
                "kvonr": vorlage.group(1) if vorlage else "",
                "beschluss": text(beschluss.group(1)).removeprefix("Beschluss:").strip() if beschluss else "",
                "routine": any(r.search(titel) for r in ROUTINE),
            })
    # Ein TOP kann in der Tabelle mehrfach auftauchen (Unterpunkte je Vorlage).
    return list({t["ktonr"]: t for t in out}.values())


# ── Tiefenprüfung: Vorlagentext, Anlagen und Niederschrift ──────────────────
# Der Titel eines TOP nennt den Ortsbezug oft nicht — er steht im Sachverhalt
# der Vorlage, in ihren Anlagen oder in dem, was in der Sitzung gesagt wurde.
# Beispiel: „Maßnahmen zur Kosteneinsparung im ÖPNV" (Stadtrat 30.07.2026)
# nennt Büchenbach nirgends; erst Anlage 1 führt „Kein Weiterbetrieb der Linie
# 298" auf — eine Linie, die im Beiratsgebiet hält. Gelesen wird deshalb alles
# drei, gespeichert nur der Beleg: gefundene Straßen, Linien und ein Schnipsel.

SCHNIPSEL_ZEICHEN = 110      # Kontext je Seite eines Treffers
MAX_FUNDSTELLEN = 4          # je TOP; mehr hilft beim Lesen nicht
MAX_PDF_BYTES = 25 * 1024 * 1024
# Anlagen sind zusammen rund 3,6 GB. Deshalb Grenzen: große Dateien sind fast
# immer Pläne und Fotos (kein extrahierbarer Text), und je Lauf wird nur ein
# Kontingent geholt — der Rückstand wird über mehrere Läufe abgetragen,
# neueste Vorlagen zuerst.
MAX_ANLAGE_BYTES = 3 * 1024 * 1024
MAX_ANLAGEN_JE_VORLAGE = 8
ANLAGEN_BUDGET = 600
# Standardmäßig nur die laufende Wahlperiode ab dem Wechsel im Mai 2026: Was
# jetzt beraten wird, ist noch zu beeinflussen — ältere Anlagen sind Archiv und
# werden bei Bedarf mit --anlagen-ab nachgeholt.
ANLAGEN_AB = "2026-01-01"
# Nach Bezeichnung aussortieren, was erfahrungsgemäß nur Bildmaterial ist.
ANLAGE_UEBERSPRINGEN = re.compile(
    r"(?i)(lageplan|übersichtsplan|uebersichtsplan|grundriss|schnitt\b|ansicht|luftbild|"
    r"foto|bildmaterial|präsentation|praesentation|siegerentwurf|wettbewerb|plakat)")

DOK_LINK = r'href="getfile\.asp\?id=(\d+)&(?:amp;)?type=do"[^>]*>\s*'
NIEDERSCHRIFT_RE = re.compile(f"(?is){DOK_LINK}Niederschrift")
# Dokumentliste einer Vorlage: nur die Download-Buttons, sonst steht jedes
# Dokument doppelt (Symbol-Link + Button).
VORLAGE_DOK_RE = re.compile(
    r'(?is)href="getfile\.asp\?id=(\d+)&(?:amp;)?type=do"[^>]*aria-label="Dokument Download[^>]*>\s*([^<]{2,80})')
# In der Niederschrift beginnt jeder Punkt mit „TOP 11" am Zeilenanfang; die
# Nummer ist der Schlüssel zurück auf unsere TOPs („Ö 11" → „11").
TOP_MARKER_RE = re.compile(r"(?m)^[ \t]*TOP[ \t]+(\d+(?:\.\d+)*)\b")
TOP_NUMMER_RE = re.compile(r"\d+(?:\.\d+)*")


def sichtbarer_text(seite: str) -> str:
    ohne = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", seite)
    return text(ohne)


def pdf_text(daten: bytes) -> str:
    if fitz is not None:
        with fitz.open(stream=daten, filetype="pdf") as doc:
            return "\n".join(s.get_text() for s in doc)
    if pypdf is not None:
        leser = pypdf.PdfReader(io.BytesIO(daten))
        return "\n".join(s.extract_text() or "" for s in leser.pages)
    return ""


def hole_roh(url: str, versuche: int = 3) -> bytes:
    letzter = None
    for n in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read(MAX_PDF_BYTES + 1)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            letzter = e
            time.sleep(1.5 * (n + 1))
    raise RuntimeError(f"{url}: {letzter}")


GRUNDWORT_RE = re.compile(r"(stra(?:ß|ss)e|str\.?|weg|allee|ring|platz|gasse|anlage|steig|damm)$", re.I)


def suchmuster(strasse: str) -> list[str]:
    """Muster, über die die Fundstelle im Text wiederzufinden ist.

    Der n-Gramm-Abgleich trifft „Adenauer-Ring" auch in „Adenauerring" und
    „Münaustraße" in „Münau-Straße" — die Belegsuche braucht dieselbe Freiheit.
    Zuerst der ganze Name mit beliebigen Trennzeichen (bei „Hintere Gasse" ist
    nur die Wortfolge kennzeichnend, nicht „Hintere"), ersatzweise der längste
    Namensteil ohne Grundwort: „Am Europakanal" → „Europakanal", „Zambellistraße"
    → „Zambelli".
    """
    teile = [p for p in re.split(r"[\s\-]+", strasse) if p]
    if not teile:
        return []
    muster = [r"[\s\-]*".join(re.escape(p) for p in teile)]
    stamm = GRUNDWORT_RE.sub("", max(teile, key=len))
    if len(stamm) >= 4:
        muster.append(re.escape(stamm))
    return muster


# Aufzählungszeichen aus PDFs kommen als Symbolschrift (Wingdings) im
# Unicode-Privatbereich an; im Browser stehen dort leere Kästchen. Codepunkte
# über chr() statt als Escape-Folge, damit in dieser Datei kein Zeichen steht,
# das ein Editor oder eine Kodierung unterwegs verschlucken kann.
PRIVATBEREICH = (chr(0xE000), chr(0xF8FF))
UNLESBAR = {chr(c) for c in range(32)} - {chr(9), chr(10), chr(13)} | {chr(0xFFFD)}


def lesbar(s: str) -> str:
    return "".join(" " if c in UNLESBAR or PRIVATBEREICH[0] <= c <= PRIVATBEREICH[1] else c
                   for c in s)


def ausschnitt(quelle: str, m: re.Match) -> str:
    aus = quelle[max(0, m.start() - SCHNIPSEL_ZEICHEN):m.end() + SCHNIPSEL_ZEICHEN]
    return f"… {re.sub(r'\s+', ' ', lesbar(aus)).strip()} …"


def schnipsel(quelle: str, strasse: str) -> str:
    """Kurzer Beleg rund um die erste Nennung der Straße."""
    for m in (re.search(p, quelle, re.I) for p in suchmuster(strasse)):
        if m:
            return ausschnitt(quelle, m)
    return ""


def linien_schnipsel(quelle: str, nummer: str) -> str:
    """Beleg zur Linie — die Fundstelle mit Linien-Kontext, nicht irgendeine Zahl."""
    for m in LINIEN_KONTEXT_RE.finditer(quelle):
        if nummer in LINIEN_NUMMER_RE.findall(m.group(1)):
            return ausschnitt(quelle, m)
    return ""


def fundstelle(quelle_text: str, herkunft: str, nmap: dict[str, str], gebiet: set[str],
               refs: set[str]) -> dict | None:
    """Ortsbezug in einem Dokumenttext: Straßen des Gebiets, Linien mit Halt hier."""
    if not quelle_text:
        return None
    im_gebiet = [s for s in strassen_in(quelle_text, nmap) if norm_strasse(s) in gebiet]
    linien = linien_in(quelle_text, refs)
    if not im_gebiet and not linien:
        return None
    eintrag = {"quelle": herkunft, "strassen": im_gebiet,
               "beleg": schnipsel(quelle_text, im_gebiet[0]) if im_gebiet
               else linien_schnipsel(quelle_text, linien[0])}
    if linien:
        eintrag["linien"] = linien
    return eintrag


def top_abschnitte(niederschrift: str) -> dict[str, str]:
    """Niederschrift in Abschnitte je TOP-Nummer zerlegen.

    Ohne diese Zuordnung müsste ein Treffer der ganzen Sitzung angehängt werden
    — dann behauptet jeder ihrer TOPs einen Ortsbezug, den nur einer hat.
    """
    marker = list(TOP_MARKER_RE.finditer(niederschrift))
    out: dict[str, str] = {}
    for i, m in enumerate(marker):
        ende = marker[i + 1].start() if i + 1 < len(marker) else len(niederschrift)
        out[m.group(1)] = out.get(m.group(1), "") + niederschrift[m.start():ende]
    return out


def top_nummer(t: dict) -> str:
    """„Ö 30.1" → „30.1"; das Ö/N unterscheidet öffentlich von nichtöffentlich."""
    m = TOP_NUMMER_RE.search(t.get("top") or "")
    return m.group(0) if m else ""


# Anzeigereihenfolge der Belege: erst was beschlossen werden soll, dann was in
# der Sitzung dazu gesagt wurde. Feste Ordnung, damit der Diff nicht wandert.
QUELLEN_ORDNUNG = {"vorlage": 0, "anlage": 1, "niederschrift": 2}


def vorlagen_stand(geprueft: dict) -> dict[str, dict]:
    """Buchführung der Vorlagen im aktuellen Format.

    Ältere Läufe legten je Vorlage nur die Fundstelle ab (oder `{}` für „gelesen,
    nichts gefunden"). Seit die Anlagen dazukommen, braucht es zwei Angaben —
    der Text kann geprüft sein, die Anlagen noch nicht.
    """
    alt = geprueft.get("vorlagen", {})
    neu: dict[str, dict] = {}
    for kvonr, wert in alt.items():
        if isinstance(wert, dict) and ("fund" in wert or "anlagen" in wert):
            neu[kvonr] = wert
        else:                                   # Format vor den Anlagen
            neu[kvonr] = {"fund": wert or None, "anlagen": False}
    geprueft["vorlagen"] = neu
    return neu


def tiefenpruefung(alle: list[dict], nmap: dict[str, str], gebiet: set[str], refs: set[str],
                   workers: int, geprueft: dict, anlagen_budget: int, anlagen_ab: str) -> None:
    """Vorlagen samt Anlagen und Niederschriften lesen, Belege an die TOPs hängen.

    `geprueft` ist die Buchführung über gelesene Dokumente und steht im
    Ergebnis auf oberster Ebene, nicht am einzelnen TOP: Eine Vorlage berät oft
    mehrere Gremien (398 von 2.816), und ein Beleg gehört zum Dokument, nicht zu
    dem TOP, bei dem er zufällig zuerst auffiel. Das spart Abrufe und hält die
    Datei klein — 4.100 TOPs ohne Fund bräuchten sonst je einen leeren Block.
    """
    vorlagen = vorlagen_stand(geprueft)
    sitzungen_geprueft = geprueft.setdefault("sitzungen", {})

    # Neueste zuerst: Wer das Kontingent für die Anlagen aufbraucht, soll es für
    # die Vorlagen tun, über die gerade entschieden wird.
    juengste: dict[str, str] = {}
    for t in alle:
        if t["kvonr"]:
            juengste[t["kvonr"]] = max(juengste.get(t["kvonr"], ""), t["datum"])
    nach_datum = sorted(juengste, key=lambda k: juengste[k], reverse=True)

    # 1) Vorlagentexte — je Vorlagennummer ein Abruf, Ergebnis für alle TOPs damit.
    offen = [k for k in nach_datum if k not in vorlagen]
    if offen:
        print(f"Tiefenprüfung: {len(offen)} Vorlagen lesen …", flush=True)

        def vorlage(kvonr: str) -> str:
            try:
                return sichtbarer_text(hole(f"{BASE}/vo0050.asp?__kvonr={kvonr}"))
            except RuntimeError as e:
                print(f"  Vorlage {kvonr}: {e}", flush=True)
                return ""

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for kvonr, txt in zip(offen, pool.map(vorlage, offen)):
                if not txt:
                    continue  # nicht vermerken, dann holt sie der nächste Lauf
                vorlagen[kvonr] = {"fund": fundstelle(txt, "vorlage", nmap, gebiet, refs),
                                   "anlagen": False}

    # 1b) Anlagen — dort stehen die Details, die der Vorlagentext zusammenfasst.
    rueckstand = [k for k in nach_datum
                  if k in vorlagen and not vorlagen[k].get("anlagen") and juengste[k] >= anlagen_ab]
    if rueckstand and anlagen_budget > 0:
        lies_anlagen(rueckstand[:anlagen_budget], vorlagen, nmap, gebiet, refs, workers)
        rest = len(rueckstand) - min(len(rueckstand), anlagen_budget)
        aelter = sum(1 for k in nach_datum
                     if k in vorlagen and not vorlagen[k].get("anlagen") and juengste[k] < anlagen_ab)
        if rest:
            print(f"  {rest} Vorlagen mit ungelesenen Anlagen — der nächste Lauf macht weiter.")
        if aelter:
            print(f"  {aelter} ältere Vorlagen (vor {anlagen_ab}) bleiben ungelesen "
                  f"— mit --anlagen-ab nachholbar.")

    # 2) Niederschriften — je Sitzung eine, aufgeteilt auf ihre TOPs. Sitzungen
    #    ohne Niederschrift bleiben unvermerkt: sie erscheint erst Wochen später.
    if fitz is None and pypdf is None:
        print("Hinweis: weder PyMuPDF noch pypdf vorhanden — Niederschriften übersprungen.")
    else:
        offene_sitzungen: dict[str, list[dict]] = {}
        for t in alle:
            if t["ksinr"] not in sitzungen_geprueft:
                offene_sitzungen.setdefault(t["ksinr"], []).append(t)
        if offene_sitzungen:
            print(f"Tiefenprüfung: {len(offene_sitzungen)} Sitzungen auf Niederschriften prüfen …", flush=True)
            lies_niederschriften(offene_sitzungen, nmap, gebiet, workers, sitzungen_geprueft)

    # 3) Belege je TOP zusammensetzen: Vorlage aus der Buchführung, Niederschrift
    #    aus diesem Lauf (`_neu`) oder aus dem Bestand, wenn sie früher gelesen
    #    wurde. Ein leeres `_neu` heißt „gelesen, nichts gefunden" — dann darf
    #    der alte Beleg nicht wieder auftauchen.
    for t in alle:
        t.pop("geprueft", None)  # frühere Fassung führte die Marken am TOP
        vorher = {f["quelle"]: f for f in t.get("fundstellen", [])}
        aus_vorlage = vorlagen.get(t["kvonr"], {}).get("fund") if t["kvonr"] else None
        aus_anlage = vorlagen.get(t["kvonr"], {}).get("anlage") if t["kvonr"] else None
        aus_niederschrift = t.pop("_neu", None) if "_neu" in t else vorher.get("niederschrift")
        neu = [f for f in (aus_vorlage, aus_anlage, aus_niederschrift) if f]
        if neu:
            t["fundstellen"] = sorted(neu, key=lambda f: QUELLEN_ORDNUNG.get(f["quelle"], 9))[:MAX_FUNDSTELLEN]
        else:
            t.pop("fundstellen", None)


def lies_anlagen(kvonrs: list[str], vorlagen: dict[str, dict], nmap: dict[str, str],
                 gebiet: set[str], refs: set[str], workers: int) -> None:
    """Anlagen der Vorlagen lesen und den besten Fund je Vorlage vermerken.

    Der Vorlagentext fasst zusammen, die Anlage führt aus: Straßenlisten,
    Linienbündel, Maßnahmenpläne. Ohne sie fehlt genau das, was den Stadtteil
    betrifft. Ergebnis je Vorlage ist eine Fundstelle der Quelle „anlage".
    """
    print(f"Tiefenprüfung: Anlagen von {len(kvonrs)} Vorlagen lesen …", flush=True)
    gelesen = uebersprungen = 0

    def anlagen(kvonr: str) -> tuple[dict | None, dict | None, int, int]:
        try:
            seite = hole(f"{BASE}/vo0050.asp?__kvonr={kvonr}")
        except RuntimeError as e:
            print(f"  Vorlage {kvonr}: {e}", flush=True)
            return None, None, 0, 0
        # Den Vorlagentext gleich mitbewerten: Die Seite ist ohnehin geholt, und
        # ein früher Lauf kann sie nach engeren Kriterien geprüft haben.
        text_fund = fundstelle(sichtbarer_text(seite), "vorlage", nmap, gebiet, refs)
        docs = list(dict.fromkeys(VORLAGE_DOK_RE.findall(seite)))[:MAX_ANLAGEN_JE_VORLAGE]
        fund, n, weg = None, 0, 0
        for did, label in docs:
            label = html.unescape(label).strip()
            if ANLAGE_UEBERSPRINGEN.search(label):
                weg += 1
                continue
            try:
                daten = hole_roh(f"{BASE}/getfile.asp?id={did}&type=do")
                if len(daten) > MAX_ANLAGE_BYTES:
                    weg += 1
                    continue
                txt = pdf_text(daten)
            except Exception:  # noqa: BLE001 — eine kaputte Anlage stoppt nichts
                weg += 1
                continue
            n += 1
            treffer = fundstelle(txt, "anlage", nmap, gebiet, refs)
            # Die aussagekräftigste Anlage gewinnt: die mit den meisten Bezügen.
            if treffer and (fund is None or
                            len(treffer["strassen"]) + len(treffer.get("linien", []))
                            > len(fund["strassen"]) + len(fund.get("linien", []))):
                treffer["dokument"] = label[:80]
                fund = treffer
        return fund, text_fund, n, weg

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for kvonr, (fund, text_fund, n, weg) in zip(kvonrs, pool.map(anlagen, kvonrs)):
            eintrag = vorlagen.setdefault(kvonr, {"fund": None, "anlagen": False})
            eintrag["anlagen"] = True
            eintrag["fund"] = text_fund
            if fund:
                eintrag["anlage"] = fund
            else:
                eintrag.pop("anlage", None)
            gelesen += n
            uebersprungen += weg
    mit_fund = sum(1 for k in kvonrs if vorlagen.get(k, {}).get("anlage"))
    print(f"  {gelesen} Anlagen gelesen, {uebersprungen} übersprungen (Bild/zu groß), "
          f"{mit_fund} Vorlagen mit Fund in der Anlage.")


def lies_niederschriften(offene: dict[str, list[dict]], nmap: dict[str, str], gebiet: set[str],
                         workers: int, vermerk: dict) -> None:
    def niederschrift(ksinr: str) -> tuple[str, str]:
        """(Dokument-ID, Text) — leer, wenn (noch) keine veröffentlicht ist."""
        try:
            m = NIEDERSCHRIFT_RE.search(hole(f"{BASE}/si0057.asp?__ksinr={ksinr}"))
            if not m:
                return "", ""
            daten = hole_roh(f"{BASE}/getfile.asp?id={m.group(1)}&type=do")
            if len(daten) > MAX_PDF_BYTES:
                print(f"  Sitzung {ksinr}: Niederschrift über {MAX_PDF_BYTES // 1024 // 1024} MB, übersprungen")
                return "", ""
            return m.group(1), pdf_text(daten)
        except Exception as e:  # noqa: BLE001 — kaputtes PDF darf den Lauf nicht reißen
            print(f"  Sitzung {ksinr}: {e}", flush=True)
            return "", ""

    ohne_abschnitt = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ksinr, (docid, txt) in zip(offene, pool.map(niederschrift, list(offene))):
            if not docid or not txt:
                continue
            abschnitte = top_abschnitte(txt)
            if not abschnitte:
                ohne_abschnitt += 1
            for t in offene[ksinr]:
                t["_neu"] = fundstelle(abschnitte.get(top_nummer(t), ""), "niederschrift", nmap, gebiet) or {}
            vermerk[ksinr] = docid
    if ohne_abschnitt:
        print(f"  {ohne_abschnitt} Niederschriften ohne TOP-Gliederung — Format prüfen.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="auch bereits erfasste Sitzungen neu holen")
    ap.add_argument("--ohne-tiefenpruefung", action="store_true",
                    help="nur Titel auswerten, keine Vorlagen, Anlagen und Niederschriften lesen")
    ap.add_argument("--anlagen-budget", type=int, default=ANLAGEN_BUDGET,
                    help="Vorlagen, deren Anlagen je Lauf gelesen werden (0 = keine; "
                         "Vorgabe: %(default)s, neueste zuerst)")
    ap.add_argument("--anlagen-ab", default=ANLAGEN_AB,
                    help="nur Anlagen von Vorlagen ab diesem Datum lesen "
                         "(ISO, Vorgabe: %(default)s; leer = ohne Grenze)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    bestand = {}
    geprueft: dict = {}
    if OUT_JSON.exists() and not args.force:
        alt = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        geprueft = alt.get("geprueft", {})
        for t in alt.get("tops", []):
            bestand.setdefault(t["ksinr"], []).append(t)

    alle: list[dict] = []
    for kgrnr, name in GREMIEN.items():
        sitz = sitzungen(kgrnr)
        offen = [s for s in sitz if s[0] not in bestand]
        print(f"{name}: {len(sitz)} Sitzungen, {len(offen)} neu abzurufen", flush=True)

        for ksinr, _ in sitz:
            if ksinr in bestand:
                alle.extend(bestand[ksinr])

        if offen:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for (ksinr, datum), ts in zip(offen, pool.map(lambda s: tops(s[0]), offen)):
                    for t in ts:
                        alle.append({
                            "gremium": name, "kgrnr": kgrnr, "datum": datum, "ksinr": ksinr, **t,
                        })

    # Ortsbezug nachtragen (auch für Einträge aus dem Bestand, damit ein
    # aufgefrischtes Straßenverzeichnis überall durchschlägt).
    nmap = lade_strassen()
    gebiet, beiratsname = lade_gebiet()
    refs = lade_linien()
    # „Büchenbach" aus „Stadtteilbeirat Büchenbach" — der Ortsname im Titel ist
    # neben dem Straßenbezug das zweite belastbare Relevanzsignal.
    ort = norm_strasse(beiratsname.split()[-1]) if beiratsname else ""
    for t in alle:
        # Link ebenfalls für alle neu bestimmen, damit eine korrigierte
        # Link-Regel auch die schon erfassten Einträge repariert.
        t["url"] = top_url(t)
        t["strassen"] = strassen_in(t["titel"], nmap) if nmap else []
        t["strassen_im_titel"] = [s for s in t["strassen"] if norm_strasse(s) in gebiet]
        t["linien_im_titel"] = linien_in(t["titel"], refs)
        t["nennt_ort"] = bool(ort) and ort in norm_strasse(t["titel"])

    if nmap and not args.ohne_tiefenpruefung:
        tiefenpruefung(alle, nmap, gebiet, refs, args.workers, geprueft,
                       args.anlagen_budget, args.anlagen_ab)

    for t in alle:
        # Ortsbezug aus allen Quellen zusammenführen: Titel plus das, was die
        # Tiefenprüfung in Vorlage, Anlagen und Niederschrift gefunden hat.
        belege = t.get("fundstellen", [])
        t["strassen_im_gebiet"] = sorted(set(t["strassen_im_titel"]) |
                                         {s for f in belege for s in f["strassen"]})
        t["linien"] = sorted(set(t["linien_im_titel"]) |
                             {l for f in belege for l in f.get("linien", [])},
                             key=lambda r: (len(r), r))
        im_titel = t["strassen_im_titel"] or t["linien_im_titel"] or t["nennt_ort"]
        t["quellen"] = (["titel"] if im_titel else []) + [f["quelle"] for f in belege]
        # Relevanz bleibt eng definiert: örtlicher Bezug, nicht thematische
        # Ähnlichkeit. Was das verfehlt, findet die Volltextsuche.
        t["relevant"] = bool(t["strassen_im_gebiet"] or t["linien"] or t["nennt_ort"]) and not t["routine"]

    alle.sort(key=lambda t: (t["datum"], t["gremium"], t["top"]), reverse=True)
    OUT_JSON.write_text(json.dumps({
        "stand": date.today().isoformat(),
        "wahlperioden": [
            {"label": "2020 – 2026", "von": "2020-05-01", "bis": "2026-04-30"},
            {"label": "2026 – 2032", "von": "2026-05-01", "bis": "2032-04-30"},
        ],
        "quelle": "Ratsinformationssystem der Stadt Erlangen (SessionNet)",
        "gremien": {str(k): v for k, v in GREMIEN.items()},
        "tops": alle,
        # Buchführung der Tiefenprüfung: welche Vorlage mit welchem Ergebnis und
        # welche Sitzung mit welcher Niederschrift gelesen wurde. Nur dadurch
        # bleibt der wöchentliche Lauf bei ein paar Dutzend Abrufen statt 3.000.
        "geprueft": {
            "vorlagen": dict(sorted(geprueft.get("vorlagen", {}).items())),
            "sitzungen": dict(sorted(geprueft.get("sitzungen", {}).items())),
        },
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    routine = sum(1 for t in alle if t["routine"])
    relevant = [t for t in alle if t.get("relevant")]
    ueber_strasse = sum(1 for t in relevant if t["strassen_im_gebiet"])
    ueber_linie = sum(1 for t in relevant if t["linien"])
    ueber_ort = sum(1 for t in relevant if t["nennt_ort"])
    nur_dokument = sum(1 for t in relevant if "titel" not in t["quellen"])
    je_quelle = {q: sum(1 for t in relevant if q in t["quellen"])
                 for q in ("vorlage", "anlage", "niederschrift")}
    print(f"\n{OUT_JSON.name}: {len(alle)} Tagesordnungspunkte "
          f"({routine} Routine, {len(alle) - routine} inhaltlich).")
    print(f"  mit Bezug zum Beiratsgebiet: {len(relevant)} ({ueber_strasse} über eine Straße, "
          f"{ueber_linie} über eine Linie, {ueber_ort} über den Ortsnamen)")
    print(f"  Tiefenprüfung: {je_quelle['vorlage']} Treffer in Vorlagentexten, "
          f"{je_quelle['anlage']} in Anlagen, {je_quelle['niederschrift']} in Niederschriften "
          f"— davon {nur_dokument} allein daraus (im Titel nicht erkennbar).")


if __name__ == "__main__":
    main()
