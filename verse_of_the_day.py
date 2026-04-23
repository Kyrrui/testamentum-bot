"""
Verse of the Day — uses an LLM (via OpenRouter) to pick a meaningful verse
from the Testamentum, then posts it to a Discord channel via webhook.

Requires environment variables:
  OPENROUTER_API_KEY — API key for OpenRouter
  DISCORD_WEBHOOK_URL — Discord webhook URL for the target channel
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

from verse_image import render_verse

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "moonshotai/kimi-k2")
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


def load_db() -> dict:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_structure_summary(db: dict) -> str:
    """Build a compact summary of the Testamentum structure with section headings.

    Much smaller than the full text — lets the LLM pick a reference without
    having to include 127k tokens of verses in the prompt.
    """
    lines = []
    for bname, bdata in db["books"].items():
        lines.append(f"=== {bname} ===")
        for ch_num in sorted(bdata["chapters"].keys(), key=int):
            ch_data = bdata["chapters"][ch_num]
            verse_count = len(ch_data["verses"])
            sections = ch_data.get("sections", {})
            # List unique section headings in order
            seen = []
            for v_num in sorted(sections.keys(), key=int):
                name = sections[v_num]
                if not seen or seen[-1][0] != name:
                    seen.append((name, v_num))
            if seen:
                sec_strs = [f"{name} (v{v})" for name, v in seen]
                lines.append(f"Ch {ch_num} ({verse_count}v): {' | '.join(sec_strs)}")
            else:
                lines.append(f"Ch {ch_num} ({verse_count}v)")
        lines.append("")
    return "\n".join(lines)


def lookup_verses(db: dict, book: str, chapter: str, v_start: int, v_end: int) -> list[dict] | None:
    """Look up verse text from the local database."""
    book_data = db["books"].get(book)
    if not book_data:
        return None
    ch_data = book_data["chapters"].get(str(chapter))
    if not ch_data:
        return None

    verses = []
    for v in range(v_start, v_end + 1):
        text = ch_data["verses"].get(str(v))
        if text:
            verses.append({"verse": str(v), "text": text})
    return verses if verses else None


def _call_llm(system_text: str, user_text: str) -> str:
    """Call the LLM via OpenRouter and return the text response."""
    import time
    body = {
        "model": OPENROUTER_MODEL,
        "max_tokens": 1024,
        "provider": {"order": ["moonshotai", "groq", "together"], "allow_fallbacks": True},
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
    }

    for attempt in range(5):
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Kyrrui/testamentum-bot",
                "X-Title": "Testamentum Bot",
            },
            json=body,
            timeout=180,
        )
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            wait = int(retry_after) if retry_after else min(2 ** attempt * 30, 120)
            print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/5)...")
            print(f"  Response: {resp.text[:200]}")
            time.sleep(wait)
            continue
        if not resp.ok:
            print(f"  Error {resp.status_code}: {resp.text[:1000]}")
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        print(f"  Tokens — prompt: {usage.get('prompt_tokens', '?')}, completion: {usage.get('completion_tokens', '?')}")
        choice = data["choices"][0]
        finish = choice.get("finish_reason")
        content = choice["message"]["content"] or ""
        print(f"  Finish reason: {finish}")
        print(f"  Response preview: {content[:300]!r}")
        return content
    resp.raise_for_status()


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


def pick_verse(db: dict, history: list[dict]) -> dict:
    """Pick a verse of the day in two steps:

    1. LLM picks a passage reference based on structure + context
    2. We look up the verse text locally and the LLM writes the blurb

    Returns {book, chapter, verse_start, verse_end, verses, blurb}.
    """
    context = _gather_context()
    structure = build_structure_summary(db)

    # History string
    if history:
        past_refs = [f"{h['book']} {h['chapter']}:{h['verse_start']}-{h['verse_end']}" for h in history]
        history_str = "Previously used passages (DO NOT repeat any of these):\n" + "\n".join(past_refs)

        recent_with_blurbs = [h for h in history[-7:] if h.get("blurb")]
        if recent_with_blurbs:
            blurb_lines = [f"- {h['date']}: {h['blurb']}" for h in recent_with_blurbs]
            history_str += (
                "\n\nRecent blurbs (DO NOT repeat the same news events or themes):\n"
                + "\n".join(blurb_lines)
            )
    else:
        history_str = ""

    system_text = (
        "You are a thoughtful scholar of the Marcionite Testamentum. "
        "Your role is to select a meaningful passage (verse range) for the Verse of the Day.\n\n"
        "IMPORTANT — what counts as relevant context:\n"
        "- MAJOR holidays only: Christmas, Easter, Thanksgiving, New Year's, etc. "
        "Ignore made-up novelty days like 'National Pancake Day' — nobody cares about those.\n"
        "- Significant BREAKING news from TODAY only, not ongoing events from days ago.\n"
        "- DEFAULT TO NOT MENTIONING NEWS. Most days should just be a thoughtful reflection on "
        "the passage itself.\n\n"
        "Guidelines:\n"
        "- Pick a range of 2-6 consecutive verses.\n"
        "- Vary selections across all books — don't favor any single book.\n"
        "- NEVER repeat a previously used passage.\n"
        "- Don't default to famous verses (e.g. Evangelicon 1:1). Dig deep.\n"
        "- Your blurb should feel like a thoughtful pastor wrote it — warm, genuine, specific.\n"
        "- Do NOT fabricate any holidays, events, or news."
    )

    user_text = (
        "Testamentum structure (book, chapters, section headings):\n\n"
        f"{structure}\n\n"
        f"Today's context:\n\n{context}\n\n"
        + (f"{history_str}\n\n" if history_str else "")
        + "Pick a Verse of the Day passage. "
        "Use the section headings as hints about the passage's theme.\n\n"
        "Respond with ONLY this JSON, no preamble or markdown fences:\n"
        "{\n"
        '  "book": "Book Name",\n'
        '  "chapter": "1",\n'
        '  "verse_start": "1",\n'
        '  "verse_end": "4",\n'
        '  "blurb": "A 2-4 sentence reflection. Warm, genuine, specific."\n'
        "}"
    )

    raw = _call_llm(system_text, user_text)

    content = raw.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    json_start = content.find("{")
    json_end = content.rfind("}") + 1
    if json_start >= 0 and json_end > json_start:
        content = content[json_start:json_end]

    result = json.loads(content)

    # Look up the actual verse text from our local db
    v_start = int(result["verse_start"])
    v_end = int(result["verse_end"])
    verses = lookup_verses(db, result["book"], result["chapter"], v_start, v_end)
    if not verses:
        raise RuntimeError(f"LLM picked invalid reference: {result['book']} {result['chapter']}:{v_start}-{v_end}")
    result["verses"] = verses
    return result


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
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set.")
        sys.exit(1)
    if not DISCORD_WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL not set.")
        sys.exit(1)
    print(f"Using model: {OPENROUTER_MODEL}")

    print("Loading verses and history...")
    db = load_db()
    history = load_history()
    structure = build_structure_summary(db)
    print(f"Structure summary: {len(structure):,} chars, {len(history)} past picks.")

    print("Asking LLM to pick a passage...")
    verse = pick_verse(db, history)
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
