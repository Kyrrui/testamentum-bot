"""
Verse of the Day — picks a random consecutive verse range from the
Testamentum and posts the rendered image to a Discord channel via webhook.

Avoids repeating any passage already in votd_history.json.

Requires environment variables:
  DISCORD_WEBHOOK_URL — Discord webhook URL for the target channel
"""

import json
import os
import random
import sys
from datetime import datetime, timezone

import requests

from verse_image import render_verse

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "testamentum.json")
VOTD_PATH = os.path.join(os.path.dirname(__file__), "data", "votd.json")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "votd_history.json")
EMBED_COLOR = 0x8B4513

MIN_RANGE = 2
MAX_RANGE = 6
MAX_PICK_ATTEMPTS = 200


def load_db() -> dict:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history: list[dict]):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def _ranges_overlap(a_book: str, a_ch: int, a_start: int, a_end: int,
                    b_book: str, b_ch: int, b_start: int, b_end: int) -> bool:
    if a_book != b_book or a_ch != b_ch:
        return False
    return not (a_end < b_start or b_end < a_start)


def _is_used(book: str, chapter: int, v_start: int, v_end: int, history: list[dict]) -> bool:
    for h in history:
        try:
            h_ch = int(h["chapter"])
            h_start = int(h["verse_start"])
            h_end = int(h["verse_end"])
        except (KeyError, ValueError, TypeError):
            continue
        if _ranges_overlap(book, chapter, v_start, v_end,
                           h["book"], h_ch, h_start, h_end):
            return True
    return False


def pick_random_verse(db: dict, history: list[dict]) -> dict:
    """Pick a random 2-6 verse range that hasn't been used before."""
    books = list(db["books"].keys())
    for _ in range(MAX_PICK_ATTEMPTS):
        book = random.choice(books)
        chapters = list(db["books"][book]["chapters"].keys())
        chapter = random.choice(chapters)
        ch_data = db["books"][book]["chapters"][chapter]
        verse_nums = sorted(int(v) for v in ch_data["verses"].keys())
        if not verse_nums:
            continue

        range_size = random.randint(MIN_RANGE, MAX_RANGE)
        # Pick a starting verse such that we have at least range_size verses available
        max_start_idx = max(0, len(verse_nums) - range_size)
        start_idx = random.randint(0, max_start_idx)
        v_start = verse_nums[start_idx]
        # Build a consecutive run from this start
        v_list = [v_start]
        for nxt in verse_nums[start_idx + 1:]:
            if nxt == v_list[-1] + 1 and len(v_list) < range_size:
                v_list.append(nxt)
            else:
                break
        # Ensure we got at least MIN_RANGE consecutive verses
        if len(v_list) < MIN_RANGE:
            continue
        v_end = v_list[-1]

        if _is_used(book, int(chapter), v_start, v_end, history):
            continue

        verses = [{"verse": str(v), "text": ch_data["verses"][str(v)]} for v in v_list]
        return {
            "book": book,
            "chapter": chapter,
            "verse_start": str(v_start),
            "verse_end": str(v_end),
            "verses": verses,
        }

    raise RuntimeError(f"Could not find an unused verse range after {MAX_PICK_ATTEMPTS} attempts.")


def post_to_discord(verse: dict):
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

    ref = f"{verse['book']} {verse['chapter']}:{verse['verse_start']}"
    if verse["verse_start"] != verse["verse_end"]:
        ref += f"-{verse['verse_end']}"

    verse_tuples = [(int(v["verse"]), v["text"]) for v in verse["verses"]]
    img_buf = render_verse(ref, verse_tuples)

    embed = {
        "title": f"Verse of the Day — {today}",
        "image": {"url": "attachment://votd.png"},
        "color": EMBED_COLOR,
    }

    payload = {"embeds": [embed]}

    resp = requests.post(
        DISCORD_WEBHOOK_URL,
        data={"payload_json": json.dumps(payload)},
        files={"file": ("votd.png", img_buf.getvalue(), "image/png")},
        timeout=30,
    )
    resp.raise_for_status()
    print("Posted to Discord successfully.")


def main():
    if not DISCORD_WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL not set.")
        sys.exit(1)

    print("Loading verses and history...")
    db = load_db()
    history = load_history()
    print(f"Loaded {len(db['books'])} books, {len(history)} past picks.")

    print("Picking a random verse range...")
    verse = pick_random_verse(db, history)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    verse["date"] = today
    ref = f"{verse['book']} {verse['chapter']}:{verse['verse_start']}"
    if verse["verse_start"] != verse["verse_end"]:
        ref += f"-{verse['verse_end']}"
    print(f"Selected: {ref}")

    print(f"Saving to {VOTD_PATH}...")
    with open(VOTD_PATH, "w", encoding="utf-8") as f:
        json.dump(verse, f, indent=2, ensure_ascii=False)

    history.append({
        "date": today,
        "book": verse["book"],
        "chapter": verse["chapter"],
        "verse_start": verse["verse_start"],
        "verse_end": verse["verse_end"],
    })
    save_history(history)
    print(f"History updated ({len(history)} entries).")

    print("Posting to Discord...")
    post_to_discord(verse)


if __name__ == "__main__":
    main()
