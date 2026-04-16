"""
Verse of the Day — uses Claude to pick a meaningful verse from the Testamentum,
then posts it to a Discord channel via webhook.

Requires environment variables:
  ANTHROPIC_API_KEY — API key for Claude
  DISCORD_WEBHOOK_URL — Discord webhook URL for the target channel
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "testamentum.json")
VOTD_PATH = os.path.join(os.path.dirname(__file__), "data", "votd.json")
EMBED_COLOR = 0x8B4513


def load_stripped_verses() -> str:
    """Load the JSON and strip it to just book -> chapter -> verse -> text."""
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    stripped = {}
    for bname, bdata in db["books"].items():
        stripped[bname] = {}
        for ch_num, ch_data in bdata["chapters"].items():
            stripped[bname][ch_num] = ch_data["verses"]

    return json.dumps(stripped, ensure_ascii=False)


def pick_verse(verses_json: str) -> dict:
    """Ask Claude to pick a verse range of the day.

    Returns {book, chapter, verse_start, verse_end, verses: [{verse, text}], blurb}.
    """
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 2048,
            "system": [
                {
                    "type": "text",
                    "text": (
                        "You are a thoughtful scholar of the Marcionite Testamentum. "
                        "Your role is to select a meaningful passage (verse range) for the Verse of the Day.\n\n"
                        "Guidelines:\n"
                        "- Pick a range of 2-6 consecutive verses that form a complete thought or passage.\n"
                        "- Consider what day it is — holidays (Easter, Christmas, Thanksgiving, etc.), "
                        "days of remembrance, seasonal themes, or what's happening in the world.\n"
                        "- Vary your selections across all books — don't favor any single book.\n"
                        "- Pick passages that are thought-provoking, comforting, challenging, or spiritually rich.\n"
                        "- Your blurb should connect the passage to today — mention the date, any holidays, "
                        "current events, seasonal themes, or why this particular passage speaks to the present moment. "
                        "Be specific and grounded, not generic."
                    ),
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": f"Here is the complete Testamentum:\n\n{verses_json}",
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Today is {today}. "
                        "Pick a Verse of the Day passage from the Testamentum. "
                        "Respond in EXACTLY this JSON format, nothing else:\n"
                        "{\n"
                        '  "book": "Book Name",\n'
                        '  "chapter": "1",\n'
                        '  "verse_start": "1",\n'
                        '  "verse_end": "4",\n'
                        '  "verses": [\n'
                        '    {"verse": "1", "text": "full verse text"},\n'
                        '    {"verse": "2", "text": "full verse text"}\n'
                        "  ],\n"
                        '  "blurb": "A 2-4 sentence reflection connecting this passage to today. '
                        "Mention the date, any holidays or observances, current events, or seasonal themes. "
                        'Explain why this passage is meaningful right now."\n'
                        "}"
                    ),
                },
            ],
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    content = data["content"][0]["text"].strip()
    # Parse the JSON response — handle potential markdown wrapping
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    result = json.loads(content)

    # Log cache performance
    usage = data.get("usage", {})
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)
    input_tokens = usage.get("input_tokens", 0)
    print(f"Tokens — input: {input_tokens}, cache_read: {cache_read}, cache_create: {cache_create}")

    return result


def post_to_discord(verse: dict):
    """Post the verse of the day to Discord via webhook."""
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

    ref = f"{verse['book']} {verse['chapter']}:{verse['verse_start']}"
    if verse["verse_start"] != verse["verse_end"]:
        ref += f"-{verse['verse_end']}"

    # Format the verses
    verse_lines = []
    for v in verse["verses"]:
        verse_lines.append(f"**{v['verse']}** {v['text']}")
    verse_text = "\n".join(verse_lines)

    embed = {
        "title": f"Verse of the Day — {today}",
        "description": (
            f"**{ref}**\n\n"
            f"{verse_text}\n\n"
            f"---\n"
            f"*{verse['blurb']}*"
        ),
        "color": EMBED_COLOR,
        "footer": {"text": "Testamentum Bot"},
    }

    resp = requests.post(
        DISCORD_WEBHOOK_URL,
        json={"embeds": [embed]},
        timeout=30,
    )
    resp.raise_for_status()
    print("Posted to Discord successfully.")


def main():
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)
    if not DISCORD_WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL not set.")
        sys.exit(1)

    print("Loading verses...")
    verses_json = load_stripped_verses()
    print(f"Loaded {len(verses_json):,} chars of verse data.")

    print("Asking Claude to pick a passage...")
    verse = pick_verse(verses_json)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    verse["date"] = today
    ref = f"{verse['book']} {verse['chapter']}:{verse['verse_start']}"
    if verse["verse_start"] != verse["verse_end"]:
        ref += f"-{verse['verse_end']}"
    print(f"Selected: {ref}")
    print(f"Blurb: {verse['blurb']}")

    # Save VOTD to file so the bot can serve /verseoftheday
    print(f"Saving to {VOTD_PATH}...")
    with open(VOTD_PATH, "w", encoding="utf-8") as f:
        json.dump(verse, f, indent=2, ensure_ascii=False)

    print("Posting to Discord...")
    post_to_discord(verse)


if __name__ == "__main__":
    main()
