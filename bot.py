"""
Testamentum Discord Bot
Serves verses from the Marcionite Testamentum via slash commands.
"""

import json
import os
import random
import re
from difflib import SequenceMatcher

import discord
from discord import app_commands, ui
from dotenv import load_dotenv

load_dotenv()

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "testamentum.json")
VOTD_PATH = os.path.join(os.path.dirname(__file__), "data", "votd.json")

EMBED_COLOR = 0x8B4513  # brown/parchment

# --- Load Data ---


def load_db() -> dict:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


DB = load_db()

# --- Helpers ---


def verse_count() -> int:
    return sum(
        len(ch["verses"])
        for b in DB["books"].values()
        for ch in b["chapters"].values()
    )


# --- Book name resolution ---

BOOK_ALIASES: dict[str, str] = {}
for _name in DB["books"]:
    _lower = _name.lower()
    BOOK_ALIASES[_lower] = _name
    if _lower == "evangelicon":
        BOOK_ALIASES["evang"] = _name
        BOOK_ALIASES["ev"] = _name
    elif _lower == "psalmicon":
        BOOK_ALIASES["psalm"] = _name
        BOOK_ALIASES["ps"] = _name
    elif _lower.startswith("1 "):
        BOOK_ALIASES["1" + _lower[2:]] = _name
        BOOK_ALIASES["i " + _lower[2:]] = _name
    elif _lower.startswith("2 "):
        BOOK_ALIASES["2" + _lower[2:]] = _name
        BOOK_ALIASES["ii " + _lower[2:]] = _name
    if len(_lower) > 3:
        _short = _lower[:3]
        if _short not in BOOK_ALIASES:
            BOOK_ALIASES[_short] = _name

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
    key = name.lower().strip()
    if key in BOOK_ALIASES:
        return BOOK_ALIASES[key]
    for alias, canonical in BOOK_ALIASES.items():
        if alias.startswith(key):
            return canonical
    return None


# --- Reference parsing ---

REF_RE = re.compile(r"^(.+?)\s+(\d+):(\d+)(?:\s*-\s*(\d+))?\s*$")


def parse_reference(ref: str) -> tuple[str, int, int, int | None] | None:
    m = REF_RE.match(ref.strip())
    if not m:
        return None
    book_input, chapter, verse_start, verse_end = m.groups()
    book = resolve_book(book_input)
    if not book:
        return None
    return book, int(chapter), int(verse_start), int(verse_end) if verse_end else None


def get_verses(book: str, chapter: int, verse_start: int, verse_end: int | None = None) -> list[tuple[int, str, str | None]] | None:
    """Returns list of (verse_num, text, section_heading_or_None)."""
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
        text = ch["verses"].get(str(v))
        if text:
            section = ch["sections"].get(str(v))
            results.append((v, text, section))
    return results if results else None


# --- Fuzzy search ---


def fuzzy_search(query: str, book_filter: str | None = None, max_results: int = 50) -> list[tuple[str, str, str, str, float]]:
    """Search verses. Returns list of (book, chapter, verse, text, score).

    Exact substring matches score 1.0, fuzzy matches score lower.
    """
    query_lower = query.lower()
    query_words = query_lower.split()
    results = []

    books_to_search = DB["books"]
    if book_filter:
        resolved = resolve_book(book_filter)
        if resolved:
            books_to_search = {resolved: DB["books"][resolved]}

    for bname, bdata in books_to_search.items():
        for ch_num, ch_data in bdata["chapters"].items():
            for v_num, v_text in ch_data["verses"].items():
                v_lower = v_text.lower()

                # Exact substring match
                if query_lower in v_lower:
                    results.append((bname, ch_num, v_num, v_text, 1.0))
                    continue

                # Word-level fuzzy: check if all query words appear (possibly fuzzy)
                if len(query_words) > 1:
                    verse_words = v_lower.split()
                    matched_words = 0
                    for qw in query_words:
                        for vw in verse_words:
                            if qw in vw or SequenceMatcher(None, qw, vw).ratio() > 0.75:
                                matched_words += 1
                                break
                    if matched_words == len(query_words):
                        score = matched_words / len(query_words) * 0.8
                        results.append((bname, ch_num, v_num, v_text, score))
                        continue

                # Single-word fuzzy: check if any word in the verse is close
                if len(query_words) == 1:
                    verse_words = v_lower.split()
                    best = 0.0
                    for vw in verse_words:
                        # Strip punctuation for matching
                        vw_clean = re.sub(r"[^\w]", "", vw)
                        ratio = SequenceMatcher(None, query_lower, vw_clean).ratio()
                        if ratio > best:
                            best = ratio
                    if best > 0.75:
                        results.append((bname, ch_num, v_num, v_text, best * 0.8))

    # Sort by score descending, then by book order
    results.sort(key=lambda r: -r[4])
    return results[:max_results]


# --- Bot setup ---

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# --- Autocomplete ---


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


async def verse_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for verse references: suggest books, then chapters, then verses."""
    current = current.strip()
    choices = []

    if not current:
        # Show book names
        for name in list(DB["books"].keys())[:25]:
            choices.append(app_commands.Choice(name=name, value=name + " "))
        return choices

    # Try to parse partial input
    # Check if it matches "Book Chapter:" pattern
    ch_match = re.match(r"^(.+?)\s+(\d+):?$", current)
    if ch_match:
        book_input, ch_num = ch_match.groups()
        book = resolve_book(book_input)
        if book:
            ch_data = DB["books"][book]["chapters"].get(ch_num)
            if ch_data:
                verse_nums = sorted(int(v) for v in ch_data["verses"].keys())
                for v in verse_nums[:25]:
                    ref = f"{book} {ch_num}:{v}"
                    choices.append(app_commands.Choice(name=ref, value=ref))
            return choices

    # Check if it matches "Book" pattern — suggest chapters
    book = resolve_book(current)
    if book:
        chapter_nums = sorted(int(c) for c in DB["books"][book]["chapters"].keys())
        for c in chapter_nums[:25]:
            ref = f"{book} {c}:"
            choices.append(app_commands.Choice(name=ref, value=ref))
        return choices

    # Partial book name — suggest matching books
    for name in DB["books"]:
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name + " "))
        if len(choices) >= 25:
            break
    return choices


# --- Pagination views ---


class SearchPaginator(ui.View):
    """Paginated search results with Previous/Next buttons."""

    PER_PAGE = 5

    def __init__(self, results: list[tuple[str, str, str, str, float]], query: str, book_filter: str | None):
        super().__init__(timeout=300)
        self.results = results
        self.query = query
        self.book_filter = book_filter
        self.page = 0
        self.max_page = max(0, (len(results) - 1) // self.PER_PAGE)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.max_page

    def make_embed(self) -> discord.Embed:
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        page_results = self.results[start:end]

        title = f'Search: "{self.query}"'
        if self.book_filter:
            resolved = resolve_book(self.book_filter)
            title += f" in {resolved or self.book_filter}"

        embed = discord.Embed(
            title=title,
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=f"Page {self.page + 1}/{self.max_page + 1} | {len(self.results)} results"
        )

        desc_lines = []
        for bname, ch, v, txt, score in page_results:
            display = txt if len(txt) <= 200 else txt[:197] + "..."
            # Highlight matched text
            highlighted = re.sub(
                re.escape(self.query),
                lambda m: f"**__{m.group()}__**",
                display,
                flags=re.IGNORECASE,
            )
            fuzzy_tag = "" if score >= 1.0 else " *(fuzzy)*"
            desc_lines.append(f"**{bname} {ch}:{v}**{fuzzy_tag}\n{highlighted}\n")

        embed.description = "\n".join(desc_lines)
        return embed

    @ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.page = min(self.max_page, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)


class ChapterPaginator(ui.View):
    """Paginated chapter display."""

    VERSES_PER_PAGE = 15

    def __init__(self, book: str, chapter: int):
        super().__init__(timeout=300)
        self.book = book
        self.chapter = chapter
        ch_data = DB["books"][book]["chapters"][str(chapter)]
        self.verses = ch_data["verses"]
        self.sections = ch_data.get("sections", {})
        self.verse_nums = sorted(int(v) for v in self.verses.keys())
        self.page = 0
        self.max_page = max(0, (len(self.verse_nums) - 1) // self.VERSES_PER_PAGE)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.max_page

    def make_embed(self) -> discord.Embed:
        start = self.page * self.VERSES_PER_PAGE
        end = start + self.VERSES_PER_PAGE
        page_verses = self.verse_nums[start:end]

        embed = discord.Embed(
            title=f"{self.book} — Chapter {self.chapter}",
            color=EMBED_COLOR,
        )
        embed.set_footer(
            text=f"Page {self.page + 1}/{self.max_page + 1} | "
                 f"{len(self.verse_nums)} verses"
        )

        desc_lines = []
        last_section = None
        for vnum in page_verses:
            section = self.sections.get(str(vnum))
            if section and section != last_section:
                desc_lines.append(f"\n__**{section}**__")
                last_section = section
            text = self.verses[str(vnum)]
            desc_lines.append(f"**{vnum}** {text}")

        embed.description = "\n".join(desc_lines)
        return embed

    @ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: ui.Button):
        self.page = min(self.max_page, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)


# --- Commands ---


@tree.command(name="verse", description="Look up a verse by reference (e.g. Evang 1:1 or Rom 7:11-13)")
@app_commands.describe(reference="Verse reference, e.g. 'Evang 1:1' or 'Rom 7:11-13'")
@app_commands.autocomplete(reference=verse_autocomplete)
async def verse_command(interaction: discord.Interaction, reference: str):
    parsed = parse_reference(reference)
    if not parsed:
        embed = discord.Embed(
            title="Invalid Reference",
            description=(
                f"Could not parse: `{reference}`\n\n"
                "**Format:** `Book Chapter:Verse` or `Book Chapter:Start-End`\n"
                "**Examples:** `Evang 1:1`, `Rom 7:11-13`, `Psalm 5:2-4`"
            ),
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    book, chapter, v_start, v_end = parsed
    results = get_verses(book, chapter, v_start, v_end)

    if not results:
        ref_str = f"{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "")
        embed = discord.Embed(
            title="Not Found",
            description=f"No verses found for **{ref_str}**",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    ref_str = f"{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "")
    embed = discord.Embed(title=ref_str, color=EMBED_COLOR)

    desc_lines = []
    last_section = None
    for vnum, text, section in results:
        if section and section != last_section:
            desc_lines.append(f"\n__**{section}**__")
            last_section = section
        desc_lines.append(f"**{vnum}** {text}")

    embed.description = "\n".join(desc_lines)
    await interaction.response.send_message(embed=embed)


@tree.command(name="search", description="Search verses by text (supports fuzzy matching)")
@app_commands.describe(
    text="Text to search for",
    book="Limit search to a specific book (optional)",
)
@app_commands.autocomplete(book=book_autocomplete)
async def search_command(interaction: discord.Interaction, text: str, book: str | None = None):
    results = fuzzy_search(text, book)

    if not results:
        resolved = resolve_book(book) if book else None
        embed = discord.Embed(
            title="No Results",
            description=f'No results for "{text}"'
            + (f" in **{resolved or book}**" if book else ""),
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = SearchPaginator(results, text, book)
    await interaction.response.send_message(embed=view.make_embed(), view=view)


@tree.command(name="random", description="Get a random verse")
@app_commands.describe(book="Limit to a specific book (optional)")
@app_commands.autocomplete(book=book_autocomplete)
async def random_command(interaction: discord.Interaction, book: str | None = None):
    if book:
        resolved = resolve_book(book)
        if not resolved:
            embed = discord.Embed(
                title="Unknown Book",
                description=f"Unknown book: `{book}`",
                color=0xFF0000,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        pool = {resolved: DB["books"][resolved]}
    else:
        pool = DB["books"]

    all_verses = []
    for bname, bdata in pool.items():
        for ch_num, ch_data in bdata["chapters"].items():
            for v_num, v_text in ch_data["verses"].items():
                section = ch_data["sections"].get(v_num)
                all_verses.append((bname, ch_num, v_num, v_text, section))

    if not all_verses:
        await interaction.response.send_message("No verses found.", ephemeral=True)
        return

    bname, ch, v, txt, section = random.choice(all_verses)
    embed = discord.Embed(
        title=f"{bname} {ch}:{v}",
        description=txt,
        color=EMBED_COLOR,
    )
    if section:
        embed.set_footer(text=section)
    await interaction.response.send_message(embed=embed)


@tree.command(name="chapter", description="Read a full chapter")
@app_commands.describe(
    book="Book name",
    chapter="Chapter number",
)
@app_commands.autocomplete(book=book_autocomplete)
async def chapter_command(interaction: discord.Interaction, book: str, chapter: int):
    resolved = resolve_book(book)
    if not resolved:
        embed = discord.Embed(
            title="Unknown Book",
            description=f"Unknown book: `{book}`",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if str(chapter) not in DB["books"][resolved]["chapters"]:
        ch_count = len(DB["books"][resolved]["chapters"])
        embed = discord.Embed(
            title="Invalid Chapter",
            description=f"**{resolved}** has {ch_count} chapters (1-{ch_count}).",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    view = ChapterPaginator(resolved, chapter)
    await interaction.response.send_message(embed=view.make_embed(), view=view)


@tree.command(name="verseoftheday", description="See today's Verse of the Day")
async def votd_command(interaction: discord.Interaction):
    if not os.path.exists(VOTD_PATH):
        embed = discord.Embed(
            title="Not Available Yet",
            description="The Verse of the Day hasn't been set yet. Check back later!",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    with open(VOTD_PATH, "r", encoding="utf-8") as f:
        votd = json.load(f)

    ref = f"{votd['book']} {votd['chapter']}:{votd['verse_start']}"
    if votd["verse_start"] != votd["verse_end"]:
        ref += f"-{votd['verse_end']}"

    verse_lines = []
    for v in votd["verses"]:
        verse_lines.append(f"**{v['verse']}** {v['text']}")
    verse_text = "\n".join(verse_lines)

    embed = discord.Embed(
        title=f"Verse of the Day — {votd.get('date', 'Today')}",
        description=(
            f"**{ref}**\n\n"
            f"{verse_text}\n\n"
            f"---\n"
            f"*{votd['blurb']}*"
        ),
        color=EMBED_COLOR,
    )
    embed.set_footer(text="Verse selection and summary generated by AI")
    await interaction.response.send_message(embed=embed)


@tree.command(name="help", description="Show available commands and how to use them")
async def help_command(interaction: discord.Interaction):
    total_books = len(DB["books"])
    total = verse_count()
    book_list = ", ".join(DB["books"].keys())

    embed = discord.Embed(
        title="Testamentum Bot",
        description=f"*{total_books} books, {total} verses from the Marcionite Testamentum*",
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="/verse <reference>",
        value=(
            "Look up a verse or range\n"
            "`/verse Evang 1:1` `/verse Rom 7:11-13`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/chapter <book> <chapter>",
        value=(
            "Read a full chapter with section headings\n"
            "`/chapter Evangelicon 1` `/chapter Romans 7`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/search <text> [book]",
        value=(
            "Search verses with fuzzy matching\n"
            "`/search grace` `/search spirit Romans`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/random [book]",
        value=(
            "Get a random verse\n"
            "`/random` `/random Psalmicon`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/verseoftheday",
        value="See today's curated Verse of the Day with reflection",
        inline=False,
    )
    embed.add_field(
        name="Book Abbreviations",
        value=(
            "Evang, Gal, 1Cor, 2Cor, Rom, 1Thess, 2Thess, Laod, Col, "
            "Phm, Phil, Tit, 1Tim, 2Tim, Alex, Psalm, Diog, Mag, Tral, "
            "Smyrn, Metro"
        ),
        inline=False,
    )
    embed.add_field(
        name="Available Books",
        value=book_list,
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.event
async def on_ready():
    await tree.sync()
    print(f"Bot is ready! Logged in as {client.user}")
    print(f"Loaded {len(DB['books'])} books, {verse_count()} verses")


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set. Create a .env file with your token.")
        return
    client.run(token)


if __name__ == "__main__":
    main()
