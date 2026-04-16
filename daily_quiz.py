"""
Daily Quiz — picks a random verse and posts a multi-stage quiz to Discord.

The quiz embed uses persistent custom_ids so the bot can handle
button clicks indefinitely (no 15-minute timeout).

Requires environment variables:
  DISCORD_QUIZ_WEBHOOK_URL — Discord webhook URL for the quiz channel
"""

import json
import os
import random
import sys

import requests

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "testamentum.json")
QUIZ_PATH = os.path.join(os.path.dirname(__file__), "data", "daily_quiz.json")
QUIZ_HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "quiz_history.json")
ALLTIME_LB_PATH = os.path.join(os.path.dirname(__file__), "data", "quiz_leaderboard.json")
EMBED_COLOR = 0x8B4513

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
QUIZ_CHANNEL_ID = os.environ.get("QUIZ_CHANNEL_ID")


def load_db() -> dict:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_quiz_history() -> list[str]:
    """Load list of previously used verse refs to avoid repeats."""
    if not os.path.exists(QUIZ_HISTORY_PATH):
        return []
    with open(QUIZ_HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_quiz_history(history: list[str]):
    with open(QUIZ_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def pick_quiz_verse(db: dict, history: list[str]) -> tuple[str, str, str, str]:
    """Pick a random verse not in history. Returns (book, chapter, verse, text)."""
    all_verses = []
    for bname, bdata in db["books"].items():
        for ch_num, ch_data in bdata["chapters"].items():
            for v_num, v_text in ch_data["verses"].items():
                ref = f"{bname} {ch_num}:{v_num}"
                if ref not in history:
                    all_verses.append((bname, ch_num, v_num, v_text))

    if not all_verses:
        # Reset history if we've used everything
        all_verses = []
        for bname, bdata in db["books"].items():
            for ch_num, ch_data in bdata["chapters"].items():
                for v_num, v_text in ch_data["verses"].items():
                    all_verses.append((bname, ch_num, v_num, v_text))
        history.clear()

    return random.choice(all_verses)


def generate_choices(db: dict, book: str, chapter: str, verse: str) -> dict:
    """Generate the 4 choices for each stage."""
    # Book choices
    all_books = list(db["books"].keys())
    wrong_books = [b for b in all_books if b != book]
    random.shuffle(wrong_books)
    book_choices = wrong_books[:3] + [book]
    random.shuffle(book_choices)

    # Chapter choices
    ch_count = len(db["books"][book]["chapters"])
    all_chapters = list(range(1, ch_count + 1))
    correct_ch = int(chapter)
    wrong_chapters = [c for c in all_chapters if c != correct_ch]
    random.shuffle(wrong_chapters)
    chapter_choices = wrong_chapters[:3] + [correct_ch]
    random.shuffle(chapter_choices)

    # Verse choices
    ch_data = db["books"][book]["chapters"][chapter]
    all_verses = [int(v) for v in ch_data["verses"].keys()]
    correct_v = int(verse)
    wrong_verses = [v for v in all_verses if v != correct_v]
    random.shuffle(wrong_verses)
    verse_choices = wrong_verses[:3] + [correct_v]
    random.shuffle(verse_choices)

    return {
        "book_choices": book_choices,
        "chapter_choices": chapter_choices,
        "verse_choices": verse_choices,
    }


def post_quiz(quiz_data: dict):
    """Post the quiz embed with persistent buttons to Discord."""
    text = quiz_data["text"]
    book_choices = quiz_data["book_choices"]

    # Build book stage buttons
    components = [
        {
            "type": 1,  # action row
            "components": [
                {
                    "type": 2,  # button
                    "style": 2,  # secondary
                    "label": choice,
                    "custom_id": f"dq_book_{i}",
                }
                for i, choice in enumerate(book_choices)
            ],
        }
    ]

    # Load all-time leaderboard for display
    alltime_text = "*No scores yet*"
    if os.path.exists(ALLTIME_LB_PATH):
        with open(ALLTIME_LB_PATH, "r", encoding="utf-8") as f:
            alltime_lb = json.load(f)
        if alltime_lb:
            entries = sorted(alltime_lb.values(), key=lambda e: (-e["total_score"], -e["perfect"]))
            lines = []
            medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
            for i, entry in enumerate(entries[:5]):
                medal = medals[i] if i < 3 else f"**{i+1}.**"
                avg = entry["total_score"] / entry["games_played"] if entry["games_played"] else 0
                lines.append(
                    f"{medal} {entry['name']} — **{entry['total_score']}** pts "
                    f"({entry['games_played']} games, {entry['perfect']} perfect)"
                )
            alltime_text = "\n".join(lines)

    embed = {
        "title": "Daily Scripture Quiz",
        "description": (
            "*Which book is this verse from?*\n\n"
            f">>> {text}\n\n"
            "Everyone can play! Your answers are private."
        ),
        "color": EMBED_COLOR,
        "fields": [
            {"name": "Today's Scores", "value": "*No answers yet*", "inline": False},
            {"name": "All-Time Leaderboard", "value": alltime_text, "inline": False},
        ],
        "footer": {"text": "Round 1 of 3 — Pick the correct book!"},
    }

    payload = {
        "embeds": [embed],
        "components": components,
    }

    resp = requests.post(
        f"https://discord.com/api/v10/channels/{QUIZ_CHANNEL_ID}/messages",
        headers={
            "Authorization": f"Bot {DISCORD_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    msg_data = resp.json()
    return msg_data["id"], msg_data["channel_id"]


def main():
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set.")
        sys.exit(1)
    if not QUIZ_CHANNEL_ID:
        print("ERROR: QUIZ_CHANNEL_ID not set.")
        sys.exit(1)

    print("Loading data...")
    db = load_db()
    history = load_quiz_history()
    print(f"Loaded {len(history)} past quiz verses.")

    print("Picking a verse...")
    book, chapter, verse, text = pick_quiz_verse(db, history)
    ref = f"{book} {chapter}:{verse}"
    print(f"Selected: {ref}")

    choices = generate_choices(db, book, chapter, verse)

    print("Posting quiz...")
    message_id, channel_id = post_quiz({
        "text": text,
        **choices,
    })
    print(f"Posted quiz message {message_id} in channel {channel_id}")

    # Save quiz data for the bot to use
    quiz_data = {
        "book": book,
        "chapter": chapter,
        "verse": verse,
        "text": text,
        "message_id": message_id,
        "channel_id": channel_id,
        "leaderboard": {},  # user_id -> {name, score, stage}
        **choices,
    }
    with open(QUIZ_PATH, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=2, ensure_ascii=False)
    print(f"Saved quiz data to {QUIZ_PATH}")

    # Update history
    history.append(ref)
    save_quiz_history(history)
    print(f"History updated ({len(history)} entries).")


if __name__ == "__main__":
    main()
