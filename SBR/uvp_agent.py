#!/usr/bin/env python3
"""
UVP Document Agent — Claude AI agent for the Umwelt-, Verkehrs- und Planungsausschuss
(Werkausschuss EB77) of the City of Erlangen.

Scrapes, indexes, and analyzes official committee documents from the
Erlangen Ratsinformationssystem (ratsinfo.erlangen.de).

Usage:
    python uvp_agent.py [--refresh]

Environment:
    ANTHROPIC_API_KEY  required

Optional dependencies:
    pip install pypdf   enables PDF text extraction
"""

import argparse
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import anthropic
import requests

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = "https://ratsinfo.erlangen.de"
COMMITTEE_NUM = 15  # Umwelt-, Verkehrs- und Planungsausschuss / Werkausschuss EB77
COMMITTEE_NAME = "Umwelt-, Verkehrs- und Planungsausschuss"
DOWNLOAD_DIR = Path("uvp_docs")
INDEX_FILE = DOWNLOAD_DIR / "index.json"
SCRAPE_YEARS = range(2020, 2027)
MODEL = "claude-opus-4-8"
MAX_TOKENS = 4096

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

SYSTEM_PROMPT = """\
You are a helpful assistant for the Umwelt-, Verkehrs- und Planungsausschuss
(Environment, Traffic and Planning Committee / Werkausschuss EB77) of the City of
Erlangen, Germany.

You can access official committee documents from the city's Ratsinformationssystem:
- Einladung: Invitations / agendas sent ahead of each meeting
- Niederschrift: Official minutes recording discussions and decisions
- Anhang: Appendices and supporting documents

Use your tools to search, download, and read documents when answering questions.
Respond in the same language the user uses (German or English).\
"""

# ── HTML Scraping ─────────────────────────────────────────────────────────────

class _RowParser(HTMLParser):
    """Extracts table rows from Ratsinformationsystem listing pages."""

    def __init__(self):
        super().__init__()
        self.rows: list = []
        self._row: list = []
        self._cell: list = []
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in_cell, self._cell = True, []
        elif tag == "a" and self._in_cell:
            href = dict(attrs).get("href", "")
            if href:
                self._cell.append(("link_start", href))

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(("text", data))

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._in_cell = False
            self._row.append(self._cell)
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
        elif tag == "a" and self._in_cell:
            self._cell.append(("link_end", ""))


def _sanitize(name: str) -> str:
    for src, dst in [
        ("ä", "ae"), ("ö", "oe"), ("ü", "ue"),
        ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss"),
    ]:
        name = name.replace(src, dst)
    name = re.sub(r"[^\w\s\-_]", "", name)
    return re.sub(r"[\s_]+", "_", name).strip("_")


def _iso_date(text: str) -> str:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else "unknown"


def _scrape_year(http: requests.Session, year: int) -> list[dict]:
    url = (
        f"{BASE_URL}/si0046.asp?__cjahr={year}&__cmonat=1&__canz=12"
        f"&smccont=85&__osidat=d&__kgsgrnr={COMMITTEE_NUM}&__cselect=65536"
    )
    try:
        r = http.get(url, headers=HTTP_HEADERS, timeout=30)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    r.encoding = "iso-8859-1"

    parser = _RowParser()
    parser.feed(r.text)

    docs = []
    for row in parser.rows:
        if not any(
            kind == "link_start" and "si0057.asp" in val
            for cell in row
            for kind, val in cell
        ):
            continue
        if len(row) < 3:
            continue

        date_text = "".join(val for kind, val in row[0] if kind == "text")
        date = _iso_date(date_text)

        seen: dict[str, dict] = {}
        curr_href = curr_text = ""
        in_link = False

        for kind, val in row[2]:
            if kind == "link_start":
                curr_href, curr_text, in_link = val, "", True
            elif kind == "link_end":
                in_link = False
                m = re.search(r"id=(\d+)", curr_href)
                if m:
                    did = m.group(1)
                    text = curr_text.strip()
                    if did not in seen:
                        seen[did] = {"href": curr_href, "text": text}
                    elif text and not seen[did]["text"]:
                        seen[did]["text"] = text
            elif kind == "text" and in_link:
                curr_text += val

        for did, info in seen.items():
            tl = info["text"].lower()
            if "einladung" in tl:
                category = "Einladung"
            elif any(w in tl for w in ("niederschrift", "protokoll")):
                category = "Niederschrift"
            else:
                category = "Anhang"

            safe = _sanitize(info["text"]) or f"doc_{did}"
            docs.append({
                "doc_id": did,
                "date": date,
                "category": category,
                "title": info["text"],
                "filename": f"{date}_{category}_{safe}.pdf",
                "href": info["href"],
            })

    return docs


# ── Index Management ──────────────────────────────────────────────────────────

def _build_index(http: requests.Session) -> list[dict]:
    http.get(f"{BASE_URL}/info.asp", headers=HTTP_HEADERS)
    docs = []
    for year in SCRAPE_YEARS:
        year_docs = _scrape_year(http, year)
        docs.extend(year_docs)
        print(f"  {year}: {len(year_docs)} documents")
    return docs


def load_index(http: requests.Session, force: bool = False) -> list[dict]:
    """Return the document index, loading from cache or scraping as needed."""
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    if not force and INDEX_FILE.exists():
        with open(INDEX_FILE, encoding="utf-8") as f:
            docs = json.load(f)
    else:
        print(f"Scraping document index for {COMMITTEE_NAME}...")
        docs = _build_index(http)
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)

    for d in docs:
        d["downloaded"] = (DOWNLOAD_DIR / d["filename"]).exists()
    return docs


# ── Tool Implementations ──────────────────────────────────────────────────────

def _tl_list_sessions(year: int, index: list[dict]) -> str:
    by_date: dict[str, list] = {}
    for d in index:
        if year and not d["date"].startswith(str(year)):
            continue
        by_date.setdefault(d["date"], []).append(d)

    if not by_date:
        return f"No sessions found{f' for {year}' if year else ''}."

    lines = ["Sessions (newest first):"]
    for date in sorted(by_date.keys(), reverse=True):
        docs = by_date[date]
        cats = ", ".join(sorted({d["category"] for d in docs}))
        n_dl = sum(1 for d in docs if d.get("downloaded"))
        lines.append(
            f"  {date} — {len(docs)} docs ({cats}) [{n_dl}/{len(docs)} downloaded]"
        )
    return "\n".join(lines)


def _tl_search_documents(
    query: str, year: int, category: str, index: list[dict]
) -> str:
    hits = [
        d for d in index
        if (not year or d["date"].startswith(str(year)))
        and (not category or d["category"] == category)
        and (not query or query.lower() in d["title"].lower())
    ]
    if not hits:
        return "No documents match the given criteria."

    hits.sort(key=lambda d: d["date"], reverse=True)
    shown = hits[:30]
    lines = [
        f"Found {len(hits)} document(s)"
        + (" (showing first 30):" if len(hits) > 30 else ":"),
        "",
    ]
    for d in shown:
        status = "✓" if d.get("downloaded") else "○"
        lines.append(
            f"  {status} [ID:{d['doc_id']}] {d['date']} | {d['category']} | {d['title']}"
        )
    return "\n".join(lines)


def _tl_download(doc_id: str, index: list[dict], http: requests.Session) -> str:
    doc = next((d for d in index if d["doc_id"] == doc_id), None)
    if not doc:
        return f"No document with ID '{doc_id}' found."

    path = DOWNLOAD_DIR / doc["filename"]
    if path.exists():
        return f"Already downloaded: {path.name}"

    url = f"{BASE_URL}/{doc['href']}"
    try:
        r = http.get(url, headers=HTTP_HEADERS, stream=True, timeout=60)
        if r.status_code == 200:
            with open(path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            doc["downloaded"] = True
            return f"Downloaded: {path.name} ({path.stat().st_size:,} bytes)"
        return f"Download failed: HTTP {r.status_code}"
    except Exception as exc:
        return f"Download error: {exc}"


def _tl_read(doc_id: str, index: list[dict]) -> str:
    doc = next((d for d in index if d["doc_id"] == doc_id), None)
    if not doc:
        return f"No document with ID '{doc_id}' found."

    path = DOWNLOAD_DIR / doc["filename"]
    if not path.exists():
        return (
            f"'{doc['filename']}' is not downloaded. "
            f"Run download_document with doc_id='{doc_id}' first."
        )

    try:
        import pypdf
    except ImportError:
        return (
            "PDF text extraction requires pypdf.\n"
            "Install it with:  pip install pypdf\n"
            f"File is at: {path}"
        )

    try:
        reader = pypdf.PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(t for t in pages if t.strip())
        if not text.strip():
            return (
                f"No text extracted from '{doc['filename']}' "
                "(may be a scanned/image-only PDF)."
            )
        words = text.split()
        if len(words) > 4000:
            text = " ".join(words[:4000]) + f"\n\n[Truncated — {len(words):,} words total]"
        header = f"=== {doc['date']} | {doc['category']} | {doc['title']} ==="
        return f"{header}\n\n{text}"
    except Exception as exc:
        return f"Error reading PDF: {exc}"


def _tl_refresh(http: requests.Session) -> tuple[str, list[dict]]:
    docs = load_index(http, force=True)
    return f"Index refreshed: {len(docs)} documents.", docs


# ── Tool Schema ───────────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "list_sessions",
        "description": (
            f"List {COMMITTEE_NAME} sessions with their dates, "
            "document counts, and download status. Useful for an overview."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "Filter by year, e.g. 2024. Omit or pass 0 for all years.",
                }
            },
        },
    },
    {
        "name": "search_documents",
        "description": (
            "Search documents by keyword, year, or category. "
            "Returns doc IDs, dates, and titles. "
            "Use the doc_id with download_document or read_document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to match in document titles (case-insensitive).",
                },
                "year": {
                    "type": "integer",
                    "description": "Filter by year, e.g. 2024. Omit or pass 0 for all years.",
                },
                "category": {
                    "type": "string",
                    "description": "Limit to one document type.",
                    "enum": ["Einladung", "Niederschrift", "Anhang"],
                },
            },
        },
    },
    {
        "name": "download_document",
        "description": "Download a document by its ID and save it as a PDF.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "Document ID from search_documents.",
                }
            },
            "required": ["doc_id"],
        },
    },
    {
        "name": "read_document",
        "description": (
            "Extract and return text from a downloaded PDF. "
            "Use download_document first if not yet downloaded. "
            "Returns up to ~4 000 words."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_id": {
                    "type": "string",
                    "description": "Document ID to read.",
                }
            },
            "required": ["doc_id"],
        },
    },
    {
        "name": "refresh_index",
        "description": (
            "Re-scrape the Ratsinformationsystem to update the document index "
            "with the latest sessions and files."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _call_tool(
    name: str, inputs: dict, index: list[dict], http: requests.Session
) -> tuple[str, list[dict]]:
    """Dispatch a tool call and return (result_text, updated_index)."""
    if name == "list_sessions":
        return _tl_list_sessions(inputs.get("year", 0), index), index
    if name == "search_documents":
        return (
            _tl_search_documents(
                inputs.get("query", ""),
                inputs.get("year", 0),
                inputs.get("category", ""),
                index,
            ),
            index,
        )
    if name == "download_document":
        return _tl_download(inputs["doc_id"], index, http), index
    if name == "read_document":
        return _tl_read(inputs["doc_id"], index), index
    if name == "refresh_index":
        return _tl_refresh(http)
    return f"Unknown tool: {name}", index


# ── Agent Loop ────────────────────────────────────────────────────────────────

def run(force_refresh: bool = False) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY environment variable is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    http = requests.Session()

    print(f"UVP Document Agent — {COMMITTEE_NAME}, Erlangen")
    print("=" * 60)
    index = load_index(http, force=force_refresh)
    downloaded = sum(1 for d in index if d.get("downloaded"))
    print(f"Ready — {len(index)} documents indexed, {downloaded} downloaded locally.")
    print('Type "exit" to quit.\n')

    messages: list[dict] = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAuf Wiedersehen!")
            return

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q", "bye", "tschüss"}:
            print("Auf Wiedersehen!")
            return

        messages.append({"role": "user", "content": user_input})

        # Agentic inner loop — handles tool calls for this user turn
        while True:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Print text blocks
            text = "\n".join(b.text for b in response.content if b.type == "text")
            if text:
                print(f"Assistant: {text}")

            # Add full assistant message (including any tool_use blocks) to history
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            # Execute each tool call
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                arg_str = ", ".join(
                    f"{k}={v!r}" for k, v in block.input.items() if v not in (None, "", 0)
                )
                print(f"  → {block.name}({arg_str})")
                result, index = _call_tool(block.name, block.input, index, http)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        print()  # Blank line between turns


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Claude AI agent for {COMMITTEE_NAME} document retrieval"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-scrape the document index from ratsinfo.erlangen.de",
    )
    args = parser.parse_args()
    run(force_refresh=args.refresh)


if __name__ == "__main__":
    main()
