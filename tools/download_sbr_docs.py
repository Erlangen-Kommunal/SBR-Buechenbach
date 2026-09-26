import os
import re
import urllib.parse
import requests
from html.parser import HTMLParser

# Base URL of the Ratsinformationsystem
BASE_URL = "https://ratsinfo.erlangen.de"
COMMITTEE_NUM = 51 # Stadtteilbeirat Büchenbach
TARGET_DIR = "."

class RowParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current_row = []
        self.in_cell = False
        self.cell_content = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.current_row = []
        elif tag in ("td", "th"):
            self.in_cell = True
            self.cell_content = []
        elif tag == "a" and self.in_cell:
            attrs_dict = dict(attrs)
            if "href" in attrs_dict:
                self.cell_content.append(("link_start", attrs_dict["href"]))

    def handle_data(self, data):
        if self.in_cell:
            self.cell_content.append(("text", data))

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.in_cell = False
            self.current_row.append(self.cell_content)
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
        elif tag == "a" and self.in_cell:
            self.cell_content.append(("link_end", ""))

def sanitize_filename(name):
    # Map German umlauts and special characters
    umlaut_map = {
        'ä': 'ae', 'ö': 'oe', 'ü': 'ue',
        'Ä': 'Ae', 'Ö': 'Oe', 'Ü': 'Ue',
        'ß': 'ss'
    }
    for char, replacement in umlaut_map.items():
        name = name.replace(char, replacement)
    
    # Remove any character that is not a letter, digit, space, hyphen, or underscore
    name = re.sub(r'[^\w\s\-_]', '', name)
    # Replace spaces and multiple underscores with a single underscore
    name = re.sub(r'[\s_]+', '_', name)
    # Trim leading/trailing underscores
    return name.strip('_')

def parse_date(date_str):
    # Extract date format DD.MM.YYYY from string like "Di 20.10.2020" or "Mi 22.01.2020"
    m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return "unknown_date"

def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    session = requests.Session()
    # Establish session
    print("Initiating session with Ratsinformationsystem...")
    session.get(f"{BASE_URL}/info.asp", headers=headers)

    all_downloads = []

    print("Scanning sessions for the years 2020 to 2025...")
    for year in range(2020, 2026):
        url = f"{BASE_URL}/si0046.asp?__cjahr={year}&__cmonat=1&__canz=12&smccont=85&__osidat=d&__kgsgrnr={COMMITTEE_NUM}&__cselect=65536"
        r = session.get(url, headers=headers)
        if r.status_code != 200:
            print(f"Error fetching year {year}: HTTP {r.status_code}")
            continue

        # Force correct decoding for German characters
        r.encoding = 'iso-8859-1'

        parser = RowParser()
        parser.feed(r.text)

        sessions_found = 0
        for row in parser.rows:
            # Check if this row is a session row
            has_session = False
            for cell in row:
                for item_type, val in cell:
                    if item_type == "link_start" and "si0057.asp" in val:
                        has_session = True
                        break
            if not has_session:
                continue

            sessions_found += 1

            # Extract date
            date_text = ""
            for item_type, val in row[0]:
                if item_type == "text":
                    date_text += val
            date_iso = parse_date(date_text)

            # Reconstruct document links inside the third cell
            docs_cell = row[2]
            curr_href = ""
            curr_text = ""
            in_link = False
            
            row_docs = {}
            for item_type, val in docs_cell:
                if item_type == "link_start":
                    curr_href = val
                    curr_text = ""
                    in_link = True
                elif item_type == "link_end":
                    in_link = False
                    # Extract document ID
                    m = re.search(r'id=(\d+)', curr_href)
                    if m:
                        doc_id = m.group(1)
                        text_clean = curr_text.strip()
                        if doc_id not in row_docs:
                            row_docs[doc_id] = {"href": curr_href, "text": text_clean}
                        else:
                            # If we get a link with text, use that text instead of empty text
                            if text_clean and not row_docs[doc_id]["text"]:
                                row_docs[doc_id]["text"] = text_clean
                elif item_type == "text":
                    if in_link:
                        curr_text += val

            # Queue documents for download
            for doc_id, doc_info in row_docs.items():
                title = doc_info["text"]
                # Determine document category
                title_lower = title.lower()
                if "einladung" in title_lower:
                    category = "Einladung"
                elif "niederschrift" in title_lower or "protokoll" in title_lower:
                    category = "Niederschrift"
                else:
                    category = "Anhang"

                all_downloads.append({
                    "date": date_iso,
                    "doc_id": doc_id,
                    "category": category,
                    "original_title": title,
                    "href": doc_info["href"]
                })

        print(f"Year {year}: Scanned {sessions_found} sessions. Total downloads queued so far: {len(all_downloads)}")

    print(f"\nFound {len(all_downloads)} unique files to download.")
    downloaded_count = 0
    failed_count = 0

    for idx, item in enumerate(all_downloads, 1):
        date_str = item["date"]
        doc_id = item["doc_id"]
        category = item["category"]
        orig_title = item["original_title"]
        
        # Build sanitized title for filename
        sanitized_title = sanitize_filename(orig_title)
        if not sanitized_title:
            sanitized_title = f"document_{doc_id}"
            
        filename = f"{date_str}_{category}_{sanitized_title}.pdf"
        filepath = os.path.join(TARGET_DIR, filename)

        print(f"[{idx}/{len(all_downloads)}] Downloading {filename} (ID: {doc_id})...")
        download_url = f"{BASE_URL}/{item['href']}"
        
        try:
            res = session.get(download_url, headers=headers, stream=True)
            if res.status_code == 200:
                with open(filepath, "wb") as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        f.write(chunk)
                downloaded_count += 1
                print(f"    Saved successfully. ({os.path.getsize(filepath)} bytes)")
            else:
                print(f"    Failed: HTTP {res.status_code}")
                failed_count += 1
        except Exception as e:
            print(f"    Failed with exception: {e}")
            failed_count += 1

    print("\n" + "="*40)
    print("Download process finished.")
    print(f"Successfully downloaded: {downloaded_count} files.")
    print(f"Failed to download:      {failed_count} files.")
    print("="*40)

if __name__ == "__main__":
    main()
