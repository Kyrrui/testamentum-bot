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
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "votd_history.json")
EMBED_COLOR = 0x8B4513


def load_history() -> list[dict]:
    """Load VOTD history. Each entry has date, book, chapter, verse_start, verse_end."""
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history: list[dict]):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


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
            # Check retry-after header, otherwise use exponential backoff
            retry_after = resp.headers.get("retry-after")
            wait = int(retry_after) if retry_after else min(2 ** attempt * 30, 120)
            print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/5)...")
            print(f"  Response: {resp.text[:200]}")
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


def _gather_context() -> str:
    """Use Haiku to do web searches and gather today's context. Cheap and fast."""
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")

    print("  Gathering today's context...")

    # Do the searches ourselves — no need for an agentic loop
    web_results = _do_web_search(f"{today} major holidays observances")
    print(f"  Web search done ({len(web_results)} chars)")

    news_results = _do_news_search("today major world news headlines")
    print(f"  News search done ({len(news_results)} chars)")

    context = (
        f"Today is {today}.\n\n"
        f"=== Holidays and observances ===\n{web_results}\n\n"
        f"=== Today's news headlines ===\n{news_results}"
    )
    return context


def pick_verse(verses_json: str, history: list[dict]) -> dict:
    """Pick a verse of the day in two phases:

    1. Gather today's context via web/news search (no LLM needed)
    2. Send context + full Testamentum + history to Claude Sonnet

    Returns {book, chapter, verse_start, verse_end, verses: [{verse, text}], blurb}.
    """
    # Phase 1: gather context
    context = _gather_context()

    # Build history string so Claude knows what's been used
    if history:
        past_refs = [f"{h['book']} {h['chapter']}:{h['verse_start']}-{h['verse_end']}" for h in history]
        history_str = "Previously used passages (DO NOT repeat any of these):\n" + "\n".join(past_refs)

        # Include recent blurbs so Claude can avoid repeating topics
        recent_with_blurbs = [h for h in history[-7:] if h.get("blurb")]
        if recent_with_blurbs:
            blurb_lines = [f"- {h['date']}: {h['blurb']}" for h in recent_with_blurbs]
            history_str += (
                "\n\nRecent blurbs (DO NOT repeat the same news events or themes):\n"
                + "\n".join(blurb_lines)
            )
    else:
        history_str = ""

    # Phase 2: single Claude call with context + verses
    system = [
        {
            "type": "text",
            "text": (
                "You are a thoughtful scholar of the Marcionite Testamentum. "
                "Your role is to select a meaningful passage (verse range) for the Verse of the Day.\n\n"
                "You will be given today's date, holidays, and news headlines as context.\n\n"
                "IMPORTANT — what counts as relevant context:\n"
                "- MAJOR holidays only: Christmas, Easter, Thanksgiving, New Year's, etc. "
                "Ignore made-up novelty days like 'National Pancake Day' or 'National Librarian Day' — nobody cares about those.\n"
                "- Significant BREAKING news from TODAY: news that actually broke in the last 24 hours. "
                "Do NOT reference ongoing events that broke days ago (e.g. an earthquake from last week). "
                "News goes stale fast — if it's not urgent and top-of-mind today, don't mention it.\n"
                "- The season, time of year, or day of the week can be relevant but keep it natural.\n"
                "- DEFAULT TO NOT MENTIONING NEWS. Most days should just be a thoughtful reflection on "
                "the passage itself. Only tie to current events when there's something genuinely major "
                "happening that a reasonable person would expect pastoral reflection on.\n"
                "- Look at the history of recent blurbs — if you've mentioned the same event more than "
                "once already, DO NOT mention it again. Move on.\n\n"
                "Guidelines for picking a passage:\n"
                "- Pick a range of 2-6 consecutive verses that form a complete thought.\n"
                "- Vary selections across all books — don't favor any single book.\n"
                "- NEVER repeat a previously used passage (you'll be given the history).\n"
                "- Do NOT default to famous or opening verses (e.g. Evangelicon 1:1). "
                "Dig deep — find hidden gems, lesser-known passages, surprising verses. "
                "The Testamentum has 4,300+ verses across 24 books. Explore all of it.\n"
                "- Pick passages that are thought-provoking, comforting, challenging, or spiritually rich.\n"
                "- Your blurb should feel like a thoughtful pastor wrote it — warm, genuine, specific. "
                "If there's a real major event or holiday, connect to it. If not, just reflect on the passage itself "
                "and why it matters. Don't shoehorn in irrelevant connections.\n"
                "- Do NOT fabricate or assume any holidays, events, or news — only reference what was provided in the context."
            ),
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"Here is the complete Testamentum:\n\n{verses_json}",
            "cache_control": {"type": "ephemeral"},
        },
    ]

    messages = [
        {
            "role": "user",
            "content": (
                f"Here is today's context:\n\n{context}\n\n"
                + (f"{history_str}\n\n" if history_str else "")
                + "Based on the above, pick a Verse of the Day passage from the Testamentum.\n\n"
                "Respond with ONLY this JSON format:\n"
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
                "If there's a major holiday or significant news event, connect to it naturally. "
                "Otherwise just reflect on the passage and why it matters. "
                'Be warm, genuine, and specific — not generic."\n'
                "}"
            ),
        },
    ]

    data = _call_anthropic(system, messages)

    # Log usage
    usage = data.get("usage", {})
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)
    input_tokens = usage.get("input_tokens", 0)
    print(f"  Tokens — input: {input_tokens}, cache_read: {cache_read}, cache_create: {cache_create}")

    # Extract the JSON response
    text_content = ""
    for block in data["content"]:
        if block["type"] == "text":
            text_content += block["text"]

    content = text_content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    json_start = content.find("{")
    json_end = content.rfind("}") + 1
    if json_start >= 0 and json_end > json_start:
        content = content[json_start:json_end]

    return json.loads(content)


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

    print("Loading verses and history...")
    verses_json = load_stripped_verses()
    history = load_history()
    print(f"Loaded {len(verses_json):,} chars of verse data, {len(history)} past picks.")

    print("Asking Claude to pick a passage...")
    verse = pick_verse(verses_json, history)
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

    # Append to history (include blurb so we can avoid repeating topics)
    history.append({
        "date": today,
        "book": verse["book"],
        "chapter": verse["chapter"],
        "verse_start": verse["verse_start"],
        "verse_end": verse["verse_end"],
        "blurb": verse.get("blurb", ""),
    })
    save_history(history)
    print(f"History updated ({len(history)} entries).")

    print("Posting to Discord...")
    post_to_discord(verse)


if __name__ == "__main__":
    main()
