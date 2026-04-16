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
    """Ask Claude to pick a verse of the day. Returns {book, chapter, verse, text, reflection}."""
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
            "max_tokens": 1024,
            "system": [
                {
                    "type": "text",
                    "text": (
                        "You are a thoughtful scholar of the Marcionite Testamentum. "
                        "Your role is to select a meaningful Verse of the Day. "
                        "Consider the day of the week, time of year, and the depth and beauty of the text. "
                        "Vary your selections across all books — don't favor any single book. "
                        "Pick verses that are thought-provoking, comforting, or spiritually rich."
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
                        "Pick a Verse of the Day from the Testamentum. "
                        "Respond in EXACTLY this JSON format, nothing else:\n"
                        '{"book": "Book Name", "chapter": "1", "verse": "1", '
                        '"text": "the full verse text", '
                        '"reflection": "A 1-2 sentence reflection on why this verse is meaningful today."}'
                    ),
                },
            ],
        },
        timeout=60,
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

    embed = {
        "title": f"Verse of the Day — {today}",
        "description": (
            f"**{verse['book']} {verse['chapter']}:{verse['verse']}**\n\n"
            f"{verse['text']}\n\n"
            f"*{verse['reflection']}*"
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

    print("Asking Claude to pick a verse...")
    verse = pick_verse(verses_json)
    print(f"Selected: {verse['book']} {verse['chapter']}:{verse['verse']}")
    print(f"Reflection: {verse['reflection']}")

    print("Posting to Discord...")
    post_to_discord(verse)


if __name__ == "__main__":
    main()
