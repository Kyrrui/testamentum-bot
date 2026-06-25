"""
Verse of the Day — uses an LLM (via OpenRouter) to pick a meaningful verse
range from the Testamentum, then posts the rendered image to Discord.

The LLM only picks the reference; it does NOT write a blurb. If the LLM
call fails or returns an invalid pick, falls back to random selection.

Requires environment variables:
  OPENROUTER_API_KEY  — API key for OpenRouter (optional; falls back to random)
  OPENROUTER_MODEL    — model slug, defaults to anthropic/claude-sonnet-4
  DISCORD_WEBHOOK_URL — Discord webhook URL for the target channel
"""

import json
import os
import random
import sys
import time
from datetime import datetime, timezone

import requests

from verse_image import render_verse

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "testamentum.json")
VOTD_PATH = os.path.join(os.path.dirname(__file__), "data", "votd.json")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "votd_history.json")
EMBED_COLOR = 0x8B4513

MIN_RANGE = 2
MAX_RANGE = 6
MAX_PICK_ATTEMPTS = 200


# --- Data loading ---


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


# --- Reference validation ---


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


def lookup_section(db: dict, book: str, chapter: str, v_start: int) -> str | None:
    """Find the section heading that covers verse `v_start` in this chapter."""
    ch_data = db["books"].get(book, {}).get("chapters", {}).get(str(chapter))
    if not ch_data:
        return None
    sections = ch_data.get("sections") or {}
    # `sections` maps verse-num -> name; either it's keyed per-verse (every
    # verse covered) or only at section starts. Try exact match first, then
    # fall back to the nearest start at or below v_start.
    if str(v_start) in sections:
        return sections[str(v_start)] or None
    starts = sorted((int(k) for k in sections.keys()))
    candidate = None
    for s in starts:
        if s <= v_start:
            candidate = sections[str(s)]
        else:
            break
    return candidate or None


def lookup_verses(db: dict, book: str, chapter: str, v_start: int, v_end: int) -> list[dict] | None:
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


# --- LLM selection ---


def build_structure_summary(db: dict) -> str:
    """Compact summary of books, chapters, and section headings (~4k tokens)."""
    lines = []
    for bname, bdata in db["books"].items():
        lines.append(f"=== {bname} ===")
        for ch_num in sorted(bdata["chapters"].keys(), key=int):
            ch_data = bdata["chapters"][ch_num]
            verse_count = len(ch_data["verses"])
            sections = ch_data.get("sections", {})
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


def _call_llm(system_text: str, user_text: str) -> str:
    body = {
        "model": OPENROUTER_MODEL,
        "max_tokens": 256,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
    }
    for attempt in range(3):
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Kyrrui/testamentum-bot",
                "X-Title": "Testamentum Bot",
            },
            json=body,
            timeout=120,
        )
        if resp.status_code == 429:
            wait = min(2 ** attempt * 20, 90)
            print(f"  Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        if not resp.ok:
            print(f"  Error {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage", {})
        print(f"  Tokens — prompt: {usage.get('prompt_tokens', '?')}, completion: {usage.get('completion_tokens', '?')}")
        return data["choices"][0]["message"]["content"] or ""
    resp.raise_for_status()


def pick_llm_verse(db: dict, history: list[dict]) -> dict | None:
    """Ask the LLM to pick a meaningful passage. Returns None on any failure."""
    if not OPENROUTER_API_KEY:
        return None

    try:
        structure = build_structure_summary(db)
        past_refs = []
        for h in history:
            past_refs.append(f"{h['book']} {h['chapter']}:{h['verse_start']}-{h['verse_end']}")
        history_str = "\n".join(past_refs) if past_refs else "(none)"

        system_text = (
            "You are selecting a passage from the Marcionite Testamentum for the Verse of the Day. "
            "Pick a meaningful, coherent passage of 2-6 consecutive verses that forms a complete thought "
            "or a self-contained reflection.\n\n"
            "Use the section headings in the structure summary as guides — passages within a single section "
            "tend to be coherent. Avoid splitting mid-sentence or mid-narrative.\n\n"
            "Vary selections across all 24 books. Don't favor the famous opening verses. "
            "NEVER pick a passage that overlaps with anything in the history.\n\n"
            "Respond with ONLY this JSON, no preamble, no markdown, no commentary:\n"
            '{"book": "Book Name", "chapter": "N", "verse_start": "N", "verse_end": "N"}'
        )

        user_text = (
            f"Testamentum structure:\n\n{structure}\n\n"
            f"Previously used passages (DO NOT pick anything overlapping):\n{history_str}\n\n"
            "Pick a Verse of the Day passage now."
        )

        raw = _call_llm(system_text, user_text)
        content = raw.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start < 0 or json_end <= json_start:
            print(f"  LLM response had no JSON: {content[:200]!r}")
            return None
        result = json.loads(content[json_start:json_end])

        book = result["book"]
        chapter = str(result["chapter"])
        v_start = int(result["verse_start"])
        v_end = int(result["verse_end"])

        if v_end < v_start:
            print(f"  LLM returned end < start ({v_start}-{v_end}), rejecting.")
            return None

        verses = lookup_verses(db, book, chapter, v_start, v_end)
        if not verses:
            print(f"  LLM picked invalid reference: {book} {chapter}:{v_start}-{v_end}")
            return None

        if _is_used(book, int(chapter), v_start, v_end, history):
            print(f"  LLM picked already-used passage: {book} {chapter}:{v_start}-{v_end}")
            return None

        return {
            "book": book,
            "chapter": chapter,
            "verse_start": str(v_start),
            "verse_end": str(v_end),
            "verses": verses,
            "section": lookup_section(db, book, chapter, v_start) or "",
        }
    except Exception as e:
        print(f"  LLM selection failed: {e}")
        return None


# --- Random fallback ---


def pick_random_verse(db: dict, history: list[dict]) -> dict:
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
        max_start_idx = max(0, len(verse_nums) - range_size)
        start_idx = random.randint(0, max_start_idx)
        v_start = verse_nums[start_idx]
        v_list = [v_start]
        for nxt in verse_nums[start_idx + 1:]:
            if nxt == v_list[-1] + 1 and len(v_list) < range_size:
                v_list.append(nxt)
            else:
                break
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
            "section": lookup_section(db, book, chapter, v_start) or "",
        }

    raise RuntimeError(f"Could not find an unused verse range after {MAX_PICK_ATTEMPTS} attempts.")


# --- Discord posting ---


def post_to_discord(verse: dict):
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    ref = f"{verse['book']} {verse['chapter']}:{verse['verse_start']}"
    if verse["verse_start"] != verse["verse_end"]:
        ref += f"-{verse['verse_end']}"

    verse_tuples = [(int(v["verse"]), v["text"]) for v in verse["verses"]]
    section = verse.get("section") or None
    img_buf = render_verse(ref, verse_tuples, section=section)

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


# --- Main ---


def main():
    if not DISCORD_WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL not set.")
        sys.exit(1)

    print("Loading verses and history...")
    db = load_db()
    history = load_history()
    print(f"Loaded {len(db['books'])} books, {len(history)} past picks.")

    verse = None
    if OPENROUTER_API_KEY:
        print(f"Asking LLM to pick a passage (model: {OPENROUTER_MODEL})...")
        verse = pick_llm_verse(db, history)
        if verse:
            print("LLM selection succeeded.")
        else:
            print("LLM selection failed, falling back to random.")
    else:
        print("No OPENROUTER_API_KEY set, using random selection.")

    if not verse:
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
