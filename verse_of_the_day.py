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

from verse_image import render_verse

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


def _call_anthropic(system: list, messages: list, tools: list | None = None) -> dict:
    """Make a single Anthropic API call and return the response JSON."""
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "system": system,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools

    import time
    for attempt in range(5):
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "content-type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            json=body,
            timeout=120,
        )
        if resp.status_code == 429:
            wait = min(2 ** attempt * 10, 60)
            print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/5)...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # raise on final failure


def _do_web_search(query: str) -> str:
    """Perform a web search using DuckDuckGo and return text results."""
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=8)
        formatted = []
        for r in results:
            formatted.append(f"{r['title']}\n{r['body']}")
        return "\n\n".join(formatted) if formatted else "No results found."
    except Exception as e:
        return f"Search failed: {e}"


def _do_news_search(query: str) -> str:
    """Search recent news using DuckDuckGo and return headlines."""
    try:
        from ddgs import DDGS
        results = DDGS().news(query, max_results=8)
        formatted = []
        for r in results:
            formatted.append(f"{r['title']}\n{r['body']}")
        return "\n\n".join(formatted) if formatted else "No news results found."
    except Exception as e:
        return f"News search failed: {e}"


def pick_verse(verses_json: str) -> dict:
    """Ask Claude to pick a verse range of the day.

    Claude has access to web search so it can look up today's news,
    holidays, and events before choosing a passage.

    Returns {book, chapter, verse_start, verse_end, verses: [{verse, text}], blurb}.
    """
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

    system = [
        {
            "type": "text",
            "text": (
                "You are a thoughtful scholar of the Marcionite Testamentum. "
                "Your role is to select a meaningful passage (verse range) for the Verse of the Day.\n\n"
                "You have access to web_search and news_search tools. Use them to understand what's happening today.\n\n"
                "IMPORTANT — what counts as relevant context:\n"
                "- MAJOR holidays only: Christmas, Easter, Thanksgiving, New Year's, etc. "
                "Ignore made-up novelty days like 'National Pancake Day' or 'National Librarian Day' — nobody cares about those.\n"
                "- Significant world news: wars, disasters, major political events, historic moments.\n"
                "- The season, time of year, or day of the week can be relevant but keep it natural.\n"
                "- If nothing notable is happening today, that's fine — just pick a great passage "
                "and write a thoughtful reflection without forcing a connection to some obscure holiday.\n\n"
                "Guidelines for picking a passage:\n"
                "- Pick a range of 2-6 consecutive verses that form a complete thought.\n"
                "- Vary selections across all books — don't favor any single book.\n"
                "- Pick passages that are thought-provoking, comforting, challenging, or spiritually rich.\n"
                "- Your blurb should feel like a thoughtful pastor wrote it — warm, genuine, specific. "
                "If there's a real major event or holiday, connect to it. If not, just reflect on the passage itself "
                "and why it matters. Don't shoehorn in irrelevant connections.\n"
                "- Do NOT fabricate or assume any holidays, events, or news — only reference what you confirmed via search."
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"Here is the complete Testamentum:\n\n{verses_json}",
            "cache_control": {"type": "ephemeral"},
        },
    ]

    tools = [
        {
            "name": "web_search",
            "description": "Search the web for general information — holidays, observances, historical events for today's date, etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    }
                },
                "required": ["query"],
            },
        },
        {
            "name": "news_search",
            "description": "Search recent news headlines and current events. Use this to find out what's happening in the world today.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The news search query",
                    }
                },
                "required": ["query"],
            },
        },
    ]

    messages = [
        {
            "role": "user",
            "content": (
                f"Today is {today}. "
                "First, search the web to find out what's happening today — holidays, observances, "
                "major news headlines, current events. Do multiple searches.\n\n"
                "Then, pick a Verse of the Day passage from the Testamentum that connects to what you found.\n\n"
                "After your searches, respond with ONLY this JSON format:\n"
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
                "Reference specific holidays, news, or events you found. "
                'Be specific and grounded."\n'
                "}"
            ),
        },
    ]

    # Agentic loop: let Claude search as much as it wants, then respond
    max_turns = 10
    for turn in range(max_turns):
        data = _call_anthropic(system, messages, tools)

        # Log usage
        usage = data.get("usage", {})
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)
        input_tokens = usage.get("input_tokens", 0)
        print(f"  Turn {turn + 1} — input: {input_tokens}, cache_read: {cache_read}, cache_create: {cache_create}")

        # Check if Claude wants to use tools
        if data["stop_reason"] == "tool_use":
            # Process all tool calls
            tool_results = []
            for block in data["content"]:
                if block["type"] == "tool_use":
                    query = block["input"]["query"]
                    if block["name"] == "news_search":
                        print(f"  News search: {query}")
                        result = _do_news_search(query)
                    else:
                        print(f"  Web search: {query}")
                        result = _do_web_search(query)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": result,
                    })

            # Add assistant message and tool results to conversation
            messages.append({"role": "assistant", "content": data["content"]})
            messages.append({"role": "user", "content": tool_results})
            continue

        # Claude is done searching — extract the final JSON response
        text_content = ""
        for block in data["content"]:
            if block["type"] == "text":
                text_content += block["text"]

        content = text_content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        # Find JSON in the response (Claude might include preamble text)
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            content = content[json_start:json_end]

        return json.loads(content)

    raise RuntimeError("Claude did not produce a final answer within the turn limit.")


def post_to_discord(verse: dict):
    """Post the verse of the day to Discord via webhook with generated image."""
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

    ref = f"{verse['book']} {verse['chapter']}:{verse['verse_start']}"
    if verse["verse_start"] != verse["verse_end"]:
        ref += f"-{verse['verse_end']}"

    # Generate verse image
    verse_tuples = [(int(v["verse"]), v["text"]) for v in verse["verses"]]
    img_buf = render_verse(ref, verse_tuples)

    # Embed with the image attached and blurb below
    embed = {
        "title": f"Verse of the Day — {today}",
        "description": f"*{verse['blurb']}*",
        "image": {"url": "attachment://votd.png"},
        "color": EMBED_COLOR,
        "footer": {"text": "Verse selection and summary generated by AI"},
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
