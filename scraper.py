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
    "Ephesians (Ignatius)": "https://marcionitechurchofchrist.org/ephesians/",
    "Magnesians": "https://marcionitechurchofchrist.org/magnesians/",
    "Trallians": "https://marcionitechurchofchrist.org/trallians/",
    "Romans (Ignatius)": "https://marcionitechurchofchrist.org/mromans/",
    "Philadelphians": "https://marcionitechurchofchrist.org/philadelphians/",
    "Smyrnaeans": "https://marcionitechurchofchrist.org/symrnaeans/",
    "Metrodorus": "https://marcionitechurchofchrist.org/metrodorus/",
}

# Map written numbers to digits
WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "twenty-one": 21, "twenty-two": 22,
    "twenty-three": 23, "twenty-four": 24, "twenty-five": 25,
    "twenty-six": 26, "twenty-seven": 27, "twenty-eight": 28,
    "twenty-nine": 29, "thirty": 30, "thirty-one": 31, "thirty-two": 32,
    "thirty-three": 33, "thirty-four": 34, "thirty-five": 35,
    "thirty-six": 36, "thirty-seven": 37, "thirty-eight": 38,
    "thirty-nine": 39, "forty": 40, "forty-one": 41, "forty-two": 42,
}

# Regex for chapter/psalm headings like "CHAPTER ONE" or "PSALM FORTY"
CHAPTER_RE = re.compile(
    r"^(?:CHAPTER|PSALM)\s+([A-Z]+(?:-[A-Z]+)?)\s*$", re.IGNORECASE
)

# Regex for verse numbers at start of text: "1 In the beginning..."
VERSE_RE = re.compile(r"^(\d+)\s+(.+)")


def word_to_number(word: str) -> int | None:
    return WORD_TO_NUM.get(word.lower().strip())


def fetch_page(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


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
        # Check for bold-only elements (chapter/psalm headings)
        strongs = el.find_all("strong")
        if strongs:
            # Process each piece: bold text might be heading or verse number
            parts = []
            for child in el.children:
                if hasattr(child, "name") and child.name == "strong":
                    text = child.get_text(strip=True)
                    if text:
                        parts.append(("bold", text))
                else:
                    text = child.get_text() if hasattr(child, "get_text") else str(child)
                    text = text.strip()
                    if text:
                        parts.append(("text", text))

            # Case 1: Entire element is a single bold block -> possible heading
            if len(parts) == 1 and parts[0][0] == "bold":
                blocks.append(("heading", parts[0][1]))
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
        if block[0] == "heading":
            heading_text = block[1]
            match = CHAPTER_RE.match(heading_text)
            if match:
                word = match.group(1)
                num = word_to_number(word)
                if num is not None:
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
            if current_chapter == 0:
                current_chapter = 1
                chapters["1"] = {"sections": {}, "verses": {}}
            ch = chapters.setdefault(str(current_chapter), {"sections": {}, "verses": {}})
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
