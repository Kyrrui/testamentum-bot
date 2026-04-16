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
    "1 cor": "1 Corinthians",
    "2 cor": "2 Corinthians",
    "1 thess": "1 Thessalonians",
    "2 thess": "2 Thessalonians",
    "1 tim": "1 Timothy",
    "2 tim": "2 Timothy",
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


# --- Inline reference detection ---

# Matches references in natural text: "Evang 1:1", "1 Cor 3:5-7", "Rom 7:11"
# Uses word boundary and known book names/aliases to avoid false positives
INLINE_REF_RE = re.compile(
    r"(?<!\w)("
    + "|".join(re.escape(a) for a in sorted(BOOK_ALIASES.keys(), key=len, reverse=True))
    + r")\s+(\d+):(\d+)(?:\s*-\s*(\d+))?(?!\w)",
    re.IGNORECASE,
)


# --- Bot setup ---

intents = discord.Intents.default()
intents.message_content = True  # needed for inline verse expansion
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


@tree.command(name="sections", description="List section headings in a book or chapter")
@app_commands.describe(
    book="Book name",
    chapter="Chapter number (optional — omit to see all chapters)",
)
@app_commands.autocomplete(book=book_autocomplete)
async def sections_command(interaction: discord.Interaction, book: str, chapter: int | None = None):
    resolved = resolve_book(book)
    if not resolved:
        embed = discord.Embed(
            title="Unknown Book",
            description=f"Unknown book: `{book}`",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    book_data = DB["books"][resolved]

    if chapter is not None:
        ch_data = book_data["chapters"].get(str(chapter))
        if not ch_data:
            ch_count = len(book_data["chapters"])
            embed = discord.Embed(
                title="Invalid Chapter",
                description=f"**{resolved}** has {ch_count} chapters (1-{ch_count}).",
                color=0xFF0000,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # List sections in this chapter
        sections = ch_data.get("sections", {})
        seen = []
        for v_num in sorted(sections.keys(), key=int):
            name = sections[v_num]
            if not seen or seen[-1][0] != name:
                seen.append((name, v_num))

        if not seen:
            embed = discord.Embed(
                title=f"{resolved} — Chapter {chapter}",
                description="No section headings in this chapter.",
                color=EMBED_COLOR,
            )
        else:
            desc_lines = []
            for name, start_v in seen:
                desc_lines.append(f"**v{start_v}** — {name}")
            embed = discord.Embed(
                title=f"{resolved} — Chapter {chapter} Sections",
                description="\n".join(desc_lines),
                color=EMBED_COLOR,
            )
        await interaction.response.send_message(embed=embed)
        return

    # All chapters — list sections across the whole book
    desc_lines = []
    for ch_num in sorted(book_data["chapters"].keys(), key=int):
        ch_data = book_data["chapters"][ch_num]
        sections = ch_data.get("sections", {})
        seen = []
        for v_num in sorted(sections.keys(), key=int):
            name = sections[v_num]
            if not seen or seen[-1] != name:
                seen.append(name)
        if seen:
            sec_list = ", ".join(seen)
            desc_lines.append(f"**Chapter {ch_num}:** {sec_list}")
        else:
            desc_lines.append(f"**Chapter {ch_num}**")

    embed = discord.Embed(
        title=f"{resolved} — All Sections",
        description="\n".join(desc_lines),
        color=EMBED_COLOR,
    )
    # Truncate if too long for embed
    if len(embed.description) > 4096:
        embed.description = embed.description[:4093] + "..."
    await interaction.response.send_message(embed=embed)


@tree.command(name="context", description="Show a verse with surrounding context")
@app_commands.describe(
    reference="Verse reference, e.g. 'Evang 1:5' or 'Rom 3:23'",
    radius="Number of verses before and after to show (default 3)",
)
@app_commands.autocomplete(reference=verse_autocomplete)
async def context_command(interaction: discord.Interaction, reference: str, radius: int = 3):
    parsed = parse_reference(reference)
    if not parsed:
        embed = discord.Embed(
            title="Invalid Reference",
            description=(
                f"Could not parse: `{reference}`\n\n"
                "**Format:** `Book Chapter:Verse`\n"
                "**Examples:** `Evang 1:5`, `Rom 3:23`"
            ),
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    book, chapter, v_target, _ = parsed
    radius = max(1, min(radius, 10))  # clamp 1-10

    ch_data = DB["books"].get(book, {}).get("chapters", {}).get(str(chapter))
    if not ch_data:
        embed = discord.Embed(
            title="Not Found",
            description=f"Chapter {chapter} not found in **{book}**",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    v_start = max(1, v_target - radius)
    verse_nums = sorted(int(v) for v in ch_data["verses"].keys())
    v_end = min(verse_nums[-1] if verse_nums else v_target, v_target + radius)

    desc_lines = []
    last_section = None
    for v in range(v_start, v_end + 1):
        text = ch_data["verses"].get(str(v))
        if not text:
            continue
        section = ch_data["sections"].get(str(v))
        if section and section != last_section:
            desc_lines.append(f"\n__**{section}**__")
            last_section = section
        if v == v_target:
            desc_lines.append(f">>> **{v}** {text}")
        else:
            desc_lines.append(f"**{v}** {text}")

    embed = discord.Embed(
        title=f"{book} {chapter}:{v_target} (in context)",
        description="\n".join(desc_lines),
        color=EMBED_COLOR,
    )
    embed.set_footer(text=f"Showing verses {v_start}-{v_end}")
    await interaction.response.send_message(embed=embed)


@tree.command(name="bookinfo", description="Show information about a book")
@app_commands.describe(book="Book name")
@app_commands.autocomplete(book=book_autocomplete)
async def bookinfo_command(interaction: discord.Interaction, book: str):
    resolved = resolve_book(book)
    if not resolved:
        embed = discord.Embed(
            title="Unknown Book",
            description=f"Unknown book: `{book}`",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    book_data = DB["books"][resolved]
    chapters = book_data["chapters"]
    ch_count = len(chapters)
    total_verses = sum(len(ch["verses"]) for ch in chapters.values())

    # Find all unique sections
    all_sections = []
    for ch_num in sorted(chapters.keys(), key=int):
        sections = chapters[ch_num].get("sections", {})
        for v_num in sorted(sections.keys(), key=int):
            name = sections[v_num]
            if not all_sections or all_sections[-1] != name:
                all_sections.append(name)

    # Chapter breakdown
    ch_lines = []
    for ch_num in sorted(chapters.keys(), key=int):
        v_count = len(chapters[ch_num]["verses"])
        ch_lines.append(f"Ch {ch_num}: {v_count} verses")

    embed = discord.Embed(
        title=resolved,
        color=EMBED_COLOR,
    )
    embed.add_field(name="Chapters", value=str(ch_count), inline=True)
    embed.add_field(name="Total Verses", value=str(total_verses), inline=True)
    embed.add_field(
        name="Chapter Breakdown",
        value="\n".join(ch_lines) if len("\n".join(ch_lines)) <= 1024 else ", ".join(ch_lines),
        inline=False,
    )
    if all_sections:
        sec_text = "\n".join(f"- {s}" for s in all_sections[:30])
        if len(all_sections) > 30:
            sec_text += f"\n*...and {len(all_sections) - 30} more*"
        embed.add_field(name=f"Sections ({len(all_sections)})", value=sec_text, inline=False)
    embed.add_field(name="Source", value=book_data.get("url", "N/A"), inline=False)
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
        name="/context <reference> [radius]",
        value=(
            "Show a verse with surrounding context\n"
            "`/context Evang 1:5` `/context Rom 3:23 5`"
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
        name="/sections <book> [chapter]",
        value=(
            "List section headings in a book or chapter\n"
            "`/sections Evangelicon` `/sections Evangelicon 2`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/bookinfo <book>",
        value=(
            "Show info about a book (chapters, verses, sections)\n"
            "`/bookinfo Evangelicon` `/bookinfo Romans`"
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
        name="Inline Expansion",
        value="Type a verse reference in any message (e.g. \"check out Evang 1:1\") and the bot will auto-reply with the verse.",
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


@client.event
async def on_message(message: discord.Message):
    # Ignore bot messages
    if message.author.bot:
        return

    # Find all verse references in the message
    matches = list(INLINE_REF_RE.finditer(message.content))
    if not matches:
        return

    # Limit to 3 expansions per message to avoid spam
    embeds = []
    for match in matches[:3]:
        book_input, ch, v_start, v_end = match.groups()
        book = resolve_book(book_input)
        if not book:
            continue

        v_end_int = int(v_end) if v_end else None
        results = get_verses(book, int(ch), int(v_start), v_end_int)
        if not results:
            continue

        ref_str = f"{book} {ch}:{v_start}"
        if v_end:
            ref_str += f"-{v_end}"

        desc_lines = []
        for vnum, text, section in results:
            desc_lines.append(f"**{vnum}** {text}")

        embed = discord.Embed(
            title=ref_str,
            description="\n".join(desc_lines),
            color=EMBED_COLOR,
        )
        embeds.append(embed)

    if embeds:
        await message.reply(embeds=embeds, mention_author=False)


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set. Create a .env file with your token.")
        return
    client.run(token)


if __name__ == "__main__":
    main()
