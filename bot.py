"""
Testamentum Discord Bot
Serves verses from the Marcionite Testamentum via slash commands.
"""

import json
import os
import random
import re

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "testamentum.json")

# --- Load Data ---

def load_db() -> dict:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

DB = load_db()

# --- Book name resolution ---

# Build aliases: lowercase name -> canonical name
BOOK_ALIASES: dict[str, str] = {}
for name in DB["books"]:
    lower = name.lower()
    BOOK_ALIASES[lower] = name
    # Short aliases
    if lower == "evangelicon":
        BOOK_ALIASES["evang"] = name
        BOOK_ALIASES["ev"] = name
    elif lower == "psalmicon":
        BOOK_ALIASES["psalm"] = name
        BOOK_ALIASES["ps"] = name
    elif lower.startswith("1 "):
        BOOK_ALIASES["1" + lower[2:]] = name
        BOOK_ALIASES["i " + lower[2:]] = name
    elif lower.startswith("2 "):
        BOOK_ALIASES["2" + lower[2:]] = name
        BOOK_ALIASES["ii " + lower[2:]] = name
    # First 3 chars
    if len(lower) > 3:
        short = lower[:3]
        if short not in BOOK_ALIASES:
            BOOK_ALIASES[short] = name

# Additional common short forms
BOOK_ALIASES.update({
    "gal": "Galatians",
    "rom": "Romans",
    "col": "Colossians",
    "phil": "Philippians",
    "phm": "Philemon",
    "tit": "Titus",
    "laod": "Laodiceans",
    "alex": "Alexandrians",
    "diog": "Diognetus",
    "mag": "Magnesians",
    "tral": "Trallians",
    "trall": "Trallians",
    "smyrn": "Smyrnaeans",
    "metro": "Metrodorus",
    "1cor": "1 Corinthians",
    "2cor": "2 Corinthians",
    "1thess": "1 Thessalonians",
    "2thess": "2 Thessalonians",
    "1tim": "1 Timothy",
    "2tim": "2 Timothy",
})


def resolve_book(name: str) -> str | None:
    """Resolve a user-typed book name to the canonical name."""
    key = name.lower().strip()
    if key in BOOK_ALIASES:
        return BOOK_ALIASES[key]
    # Fuzzy: check if any alias starts with the input
    for alias, canonical in BOOK_ALIASES.items():
        if alias.startswith(key):
            return canonical
    return None


def book_choices() -> list[str]:
    """Return list of all book names for autocomplete."""
    return list(DB["books"].keys())


# --- Reference parsing ---

# Matches: "Evang 1:1", "Rom 7:11-13", "1 Cor 3:5", "Psalm 5:2-4"
REF_RE = re.compile(
    r"^(.+?)\s+(\d+):(\d+)(?:\s*-\s*(\d+))?\s*$"
)


def parse_reference(ref: str) -> tuple[str, int, int, int | None] | None:
    """Parse a verse reference like 'Evang 1:1' or 'Rom 7:11-13'."""
    m = REF_RE.match(ref.strip())
    if not m:
        return None
    book_input, chapter, verse_start, verse_end = m.groups()
    book = resolve_book(book_input)
    if not book:
        return None
    return book, int(chapter), int(verse_start), int(verse_end) if verse_end else None


def get_verses(book: str, chapter: int, verse_start: int, verse_end: int | None = None) -> list[tuple[int, str]] | None:
    """Fetch one or more verses. Returns list of (verse_num, text) or None."""
    book_data = DB["books"].get(book)
    if not book_data:
        return None

    ch = book_data["chapters"].get(str(chapter))
    if not ch:
        return None

    if verse_end is None:
        verse_end = verse_start

    results = []
    for v in range(verse_start, verse_end + 1):
        text = ch.get(str(v))
        if text:
            results.append((v, text))

    return results if results else None


# --- Bot setup ---

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


async def book_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    choices = []
    for name in DB["books"]:
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))
        if len(choices) >= 25:
            break
    return choices


@tree.command(name="verse", description="Look up a verse by reference (e.g. Evang 1:1 or Rom 7:11-13)")
@app_commands.describe(reference="Verse reference, e.g. 'Evang 1:1' or 'Rom 7:11-13'")
async def verse_command(interaction: discord.Interaction, reference: str):
    parsed = parse_reference(reference)
    if not parsed:
        await interaction.response.send_message(
            f"Could not parse reference: `{reference}`\n"
            "Format: `Book Chapter:Verse` or `Book Chapter:Start-End`\n"
            "Examples: `Evang 1:1`, `Rom 7:11-13`, `Psalm 5:2-4`",
            ephemeral=True,
        )
        return

    book, chapter, v_start, v_end = parsed
    results = get_verses(book, chapter, v_start, v_end)

    if not results:
        await interaction.response.send_message(
            f"No verses found for **{book} {chapter}:{v_start}"
            + (f"-{v_end}" if v_end else "") + "**",
            ephemeral=True,
        )
        return

    # Format output
    header = f"**{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "") + "**"
    lines = [header, ""]
    for vnum, text in results:
        lines.append(f"**{vnum}** {text}")

    msg = "\n".join(lines)
    if len(msg) > 2000:
        msg = msg[:1997] + "..."
    await interaction.response.send_message(msg)


@tree.command(name="search", description="Search verses by text")
@app_commands.describe(
    text="Text to search for",
    book="Limit search to a specific book (optional)",
)
@app_commands.autocomplete(book=book_autocomplete)
async def search_command(interaction: discord.Interaction, text: str, book: str | None = None):
    query = text.lower()
    results = []

    books_to_search = DB["books"]
    if book:
        resolved = resolve_book(book)
        if not resolved:
            await interaction.response.send_message(
                f"Unknown book: `{book}`", ephemeral=True
            )
            return
        books_to_search = {resolved: DB["books"][resolved]}

    for bname, bdata in books_to_search.items():
        for ch_num, ch_verses in bdata["chapters"].items():
            for v_num, v_text in ch_verses.items():
                if query in v_text.lower():
                    results.append((bname, ch_num, v_num, v_text))
                    if len(results) >= 10:
                        break
            if len(results) >= 10:
                break
        if len(results) >= 10:
            break

    if not results:
        await interaction.response.send_message(
            f'No results for "{text}"'
            + (f" in **{resolve_book(book) or book}**" if book else ""),
            ephemeral=True,
        )
        return

    lines = [f'**Search results for "{text}"**', ""]
    for bname, ch, v, txt in results:
        # Truncate long verses
        display = txt if len(txt) <= 150 else txt[:147] + "..."
        lines.append(f"**{bname} {ch}:{v}** — {display}")

    msg = "\n".join(lines)
    if len(msg) > 2000:
        msg = msg[:1997] + "..."
    await interaction.response.send_message(msg)


@tree.command(name="random", description="Get a random verse")
@app_commands.describe(book="Limit to a specific book (optional)")
@app_commands.autocomplete(book=book_autocomplete)
async def random_command(interaction: discord.Interaction, book: str | None = None):
    if book:
        resolved = resolve_book(book)
        if not resolved:
            await interaction.response.send_message(
                f"Unknown book: `{book}`", ephemeral=True
            )
            return
        pool = {resolved: DB["books"][resolved]}
    else:
        pool = DB["books"]

    # Build flat list of all verses
    all_verses = []
    for bname, bdata in pool.items():
        for ch_num, ch_verses in bdata["chapters"].items():
            for v_num, v_text in ch_verses.items():
                all_verses.append((bname, ch_num, v_num, v_text))

    if not all_verses:
        await interaction.response.send_message("No verses found.", ephemeral=True)
        return

    bname, ch, v, txt = random.choice(all_verses)
    await interaction.response.send_message(
        f"**{bname} {ch}:{v}**\n\n{txt}"
    )


@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot is ready! Logged in as {client.user}")
    total = sum(
        len(v)
        for b in DB["books"].values()
        for v in b["chapters"].values()
    )
    print(f"Loaded {len(DB['books'])} books, {total} verses")


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set. Create a .env file with your token.")
        return
    client.run(token)


if __name__ == "__main__":
    main()
