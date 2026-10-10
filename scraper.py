"""
Scraper for the Marcionite Church of Christ Testamentum.
Fetches all books and outputs a structured JSON database.
"""

import json
import re
import sys

import requests
from bs4 import BeautifulSoup

BOOKS = {
    # Evangelicon
    "Evangelicon": "https://marcionitechurchofchrist.org/evangelicon/",
    # Apostolicon
    "Galatians": "https://marcionitechurchofchrist.org/galatians/",
    "1 Corinthians": "https://marcionitechurchofchrist.org/1-corinthians/",
    "2 Corinthians": "https://marcionitechurchofchrist.org/2-corinthians/",
    "Romans": "https://marcionitechurchofchrist.org/romans/",
    "1 Thessalonians": "https://marcionitechurchofchrist.org/1-thessalonians/",
    "2 Thessalonians": "https://marcionitechurchofchrist.org/2-thessalonians/",
    "Laodiceans": "https://marcionitechurchofchrist.org/laodiceans/",
    "Colossians": "https://marcionitechurchofchrist.org/colossians/",
    "Philemon": "https://marcionitechurchofchrist.org/philemon/",
    "Philippians": "https://marcionitechurchofchrist.org/philippians/",
    # Antilegicon
    "Titus": "https://marcionitechurchofchrist.org/titus/",
    "1 Timothy": "https://marcionitechurchofchrist.org/1-timothy/",
    "2 Timothy": "https://marcionitechurchofchrist.org/2-timothy/",
    "Alexandrians": "https://marcionitechurchofchrist.org/alexandrians/",
    # Psalmicon
    "Psalmicon": "https://marcionitechurchofchrist.org/psalmicon/",
    # Homileticon
    "Diognetus": "https://marcionitechurchofchrist.org/diognetus/",
    # Synaxicon (Ignatius)
    "Ephesians": "https://marcionitechurchofchrist.org/ephesians/",
    "Magnesians": "https://marcionitechurchofchrist.org/magnesians/",
    "Trallians": "https://marcionitechurchofchrist.org/trallians/",
    "mRomans": "https://marcionitechurchofchrist.org/mromans/",
    "Philadelphians": "https://marcionitechurchofchrist.org/philadelphians/",
    "Smyrnaeans": "https://marcionitechurchofchrist.org/smyrnaeans/",
    "Metrodorus": "https://marcionitechurchofchrist.org/metrodorus/",
}

# Map written numbers to digits ("one" .. "ninety-nine")
_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
          "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
WORD_TO_NUM = {w: i for i, w in enumerate(_ONES + _TEENS, start=1)}
for _t, _tens in enumerate(_TENS, start=2):
    WORD_TO_NUM[_tens] = _t * 10
    for _o, _one in enumerate(_ONES, start=1):
        WORD_TO_NUM[f"{_tens}-{_one}"] = _t * 10 + _o

# Regex for chapter/psalm headings like "CHAPTER ONE" or "PSALM FORTY"
CHAPTER_RE = re.compile(
    r"^(?:CHAPTER|PSALM)\s+([A-Z]+(?:-[A-Z]+)?)\s*$", re.IGNORECASE
)

# Regex for verse numbers at start of text: "1 In the beginning..."
VERSE_RE = re.compile(r"^(\d+)\s+(.+)")


def word_to_number(word: str) -> int | None:
    return WORD_TO_NUM.get(word.lower().strip())


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def fetch_page(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def _flatten_parts(el) -> list[tuple[str, str]]:
    """Split an element into ("bold", text) / ("text", text) pieces.

    Recurses into wrapper tags (e.g. <span> pasted in from Bible sites) so a
    bold verse number nested inside one is still seen as bold.
    """
    parts = []
    for child in el.children:
        name = getattr(child, "name", None)
        if name in ("strong", "b"):
            text = child.get_text(strip=True)
            if text:
                parts.append(("bold", text))
        elif name and child.find(["strong", "b"]):
            parts.extend(_flatten_parts(child))
        else:
            text = child.get_text() if name else str(child)
            text = text.strip()
            if text:
                parts.append(("text", text))
    return parts


def extract_text_blocks(soup: BeautifulSoup) -> list[str]:
    """Extract meaningful text blocks from the page content area."""
    # Find the main content area - usually .entry-content in WordPress
    content = soup.select_one(".entry-content")
    if not content:
        content = soup.select_one("article")
    if not content:
        content = soup.select_one("#content")
    if not content:
        content = soup.body

    blocks = []
    for el in content.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
        # Check for bold-only elements (chapter/psalm headings). The site
        # mixes <strong> and <b> for verse numbers, so treat them the same.
        strongs = el.find_all(["strong", "b"])
        if strongs:
            # Process each piece: bold text might be heading or verse number
            parts = _flatten_parts(el)

            # Case 1: Entire element is a single bold block -> possible heading
            if len(parts) == 1 and parts[0][0] == "bold":
                blocks.append(("heading", parts[0][1]))
            # Case 1b: a chapter heading split across bold tags, e.g.
            # "<strong>CHAPTER</strong> <strong>TWELVE</strong>" (2 Corinthians)
            elif all(kind == "bold" for kind, _ in parts) and CHAPTER_RE.match(" ".join(t for _, t in parts)):
                blocks.append(("heading", " ".join(t for _, t in parts)))
            # Case 2: Starts with bold number followed by text -> verse(s)
            elif parts:
                # Reconstruct verses from bold-number + text pairs
                current_verse_num = None
                current_text_parts = []

                for kind, text in parts:
                    if kind == "bold":
                        # Check if this is a verse number
                        if text.isdigit():
                            # Save previous verse if any
                            if current_verse_num is not None and current_text_parts:
                                full_text = " ".join(current_text_parts).strip()
                                if full_text:
                                    blocks.append(("verse", current_verse_num, full_text))
                            current_verse_num = int(text)
                            current_text_parts = []
                        elif current_verse_num is not None and not CHAPTER_RE.match(text):
                            # Emphasized words inside a verse (e.g. the Lord's
                            # Prayer is bolded) - part of the verse, not a heading
                            current_text_parts.append(text)
                        else:
                            # Bold text that's not a number - could be a heading
                            # Save any pending verse first
                            if current_verse_num is not None and current_text_parts:
                                full_text = " ".join(current_text_parts).strip()
                                if full_text:
                                    blocks.append(("verse", current_verse_num, full_text))
                                current_verse_num = None
                                current_text_parts = []
                            # Check if it's a chapter/psalm heading
                            match = CHAPTER_RE.match(text)
                            if match:
                                blocks.append(("heading", text))
                            else:
                                # Sub-heading or other bold text, treat as heading
                                blocks.append(("heading", text))
                    else:
                        if current_verse_num is not None:
                            current_text_parts.append(text)
                        # else: text before any verse number, skip

                # Don't forget the last verse
                if current_verse_num is not None and current_text_parts:
                    full_text = " ".join(current_text_parts).strip()
                    if full_text:
                        blocks.append(("verse", current_verse_num, full_text))
        else:
            # Plain text paragraph - check if it starts with a number
            text = el.get_text(strip=True)
            if text:
                blocks.append(("text", text))

    return blocks


def parse_book(book_name: str, url: str) -> dict:
    """Parse a single book page into structured chapter:verse data."""
    print(f"  Scraping {book_name}...")
    soup = fetch_page(url)
    blocks = extract_text_blocks(soup)

    chapters = {}
    current_chapter = 0
    current_section = None

    for block in blocks:
        # A verse whose number the site forgot to bold, e.g. "6 In whose...".
        # Only accepted as the next verse in sequence, so stray numbered
        # prose isn't mistaken for scripture.
        if block[0] == "text" and current_chapter:
            match = VERSE_RE.match(block[1])
            verses = chapters[str(current_chapter)]["verses"]
            if match and int(match.group(1)) == max(map(int, verses), default=0) + 1:
                block = ("verse", int(match.group(1)), match.group(2))

        if block[0] == "heading":
            heading_text = block[1]
            match = CHAPTER_RE.match(heading_text)
            if match:
                word = match.group(1)
                num = word_to_number(word)
                if num is None:
                    # Ignoring it would pour the chapter's verses into the previous one.
                    raise ValueError(f"unrecognised chapter heading {heading_text!r}")
                current_chapter = num
                current_section = None
                chapters[str(current_chapter)] = {"sections": {}, "verses": {}}
            else:
                # Section heading within a chapter
                current_section = heading_text
        elif block[0] == "verse":
            verse_num = block[1]
            verse_text = block[2]
            # Clean up the text
            verse_text = re.sub(r"\s+", " ", verse_text).strip()
            verse_text = re.sub(r"\s+([.,;:!?])", r"\1", verse_text)
            if current_chapter == 0:
                current_chapter = 1
                chapters["1"] = {"sections": {}, "verses": {}}
            ch = chapters.setdefault(str(current_chapter), {"sections": {}, "verses": {}})
            if str(verse_num) in ch["verses"]:
                # A repeated verse number means a chapter heading was missed.
                raise ValueError(
                    f"chapter {current_chapter} has verse {verse_num} twice "
                    "(missed chapter heading?)"
                )
            ch["verses"][str(verse_num)] = verse_text
            if current_section:
                ch["sections"][str(verse_num)] = current_section

    return {
        "name": book_name,
        "url": url,
        "chapters": chapters,
    }


def scrape_all() -> dict:
    """Scrape all books and return the full database."""
    db = {"books": {}}
    errors = []

    for book_name, url in BOOKS.items():
        try:
            book_data = parse_book(book_name, url)
            verse_count = sum(len(ch["verses"]) for ch in book_data["chapters"].values())
            chapter_count = len(book_data["chapters"])
            print(f"    -> {chapter_count} chapters, {verse_count} verses")
            if verse_count == 0:
                errors.append(f"{book_name}: 0 verses parsed (HTML may have changed)")
            db["books"][book_name] = book_data
        except Exception as e:
            errors.append(f"{book_name}: {e}")
            print(f"    ERROR scraping {book_name}: {e}")

    return db, errors


def validate_scrape(db: dict, errors: list[str]) -> bool:
    """Check that the scrape looks reasonable before overwriting the JSON."""
    total_books = len(db["books"])
    total_verses = sum(
        len(ch["verses"])
        for book in db["books"].values()
        for ch in book["chapters"].values()
    )

    # Must have all books
    if total_books < len(BOOKS):
        missing = set(BOOKS.keys()) - set(db["books"].keys())
        errors.append(f"Missing {len(missing)} books: {', '.join(missing)}")

    # Sanity check: we know there are ~4300 verses; flag if count drops drastically
    MIN_EXPECTED_VERSES = 3000
    if total_verses < MIN_EXPECTED_VERSES:
        errors.append(
            f"Only {total_verses} verses scraped (expected >{MIN_EXPECTED_VERSES}). "
            "Site HTML may have changed."
        )

    # Chapters must run 1..N with no gaps (a gap means a heading wasn't recognised)
    for book_name, book in db["books"].items():
        nums = sorted(int(c) for c in book["chapters"])
        if nums and nums != list(range(1, nums[-1] + 1)):
            missing = sorted(set(range(1, nums[-1] + 1)) - set(nums))
            errors.append(f"{book_name}: missing chapter(s) {missing}")

    # Check a few key verses exist as a canary
    canaries = [
        ("Evangelicon", "1", "1"),
        ("Romans", "1", "1"),
        ("Psalmicon", "1", "1"),
    ]
    for book, ch, v in canaries:
        if book not in db["books"]:
            continue
        text = db["books"][book]["chapters"].get(ch, {}).get("verses", {}).get(v, "")
        if len(text) < 10:
            errors.append(f"Canary verse {book} {ch}:{v} is missing or too short")

    if errors:
        print("\nValidation FAILED:")
        for err in errors:
            print(f"  - {err}")
        return False

    print(f"\nValidation passed: {total_books} books, {total_verses} verses")
    return True


def main():
    import os

    print("Scraping Testamentum...")
    db, errors = scrape_all()

    total_books = len(db["books"])
    total_verses = sum(
        len(ch["verses"])
        for book in db["books"].values()
        for ch in book["chapters"].values()
    )
    print(f"\nScraped {total_books} books, {total_verses} total verses.")

    output_path = "data/testamentum.json"

    if not validate_scrape(db, errors):
        print("\nAborting: existing data/testamentum.json will NOT be overwritten.")
        sys.exit(1)

    os.makedirs("data", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    print(f"Saved to {output_path}")


if __name__ == "__main__":
    main()
