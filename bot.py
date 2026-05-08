"""
Testamentum Discord Bot
Serves verses from the Marcionite Testamentum via slash commands.
"""

import datetime
import json
import os
import random
import re
from difflib import SequenceMatcher

import discord
import requests as http_requests
from discord import app_commands, ui
from discord.ext import tasks
from dotenv import load_dotenv
from verse_image import render_verse

load_dotenv()

# Static data (bundled with repo)
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "testamentum.json")

# Runtime data (persistent volume on Railway, or local data/ for dev)
RUNTIME_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
os.makedirs(RUNTIME_DIR, exist_ok=True)

VOTD_PATH = os.path.join(RUNTIME_DIR, "votd.json")
QUIZ_PATH = os.path.join(RUNTIME_DIR, "daily_quiz.json")
ALLTIME_LB_PATH = os.path.join(RUNTIME_DIR, "quiz_leaderboard.json")
SERVER_CONFIG_PATH = os.path.join(RUNTIME_DIR, "server_config.json")
USERDATA_DIR = os.path.join(RUNTIME_DIR, "users")
os.makedirs(USERDATA_DIR, exist_ok=True)

EMBED_COLOR = 0x8B4513  # brown/parchment
QUIZ_CHANNEL_ID = os.getenv("QUIZ_CHANNEL_ID")  # legacy fallback
VOTD_GITHUB_URL = "https://raw.githubusercontent.com/Kyrrui/testamentum-bot/main/data/votd.json"


# --- User data (bookmarks, collections) ---


def _load_user_data(user_id: str) -> dict:
    path = os.path.join(USERDATA_DIR, f"{user_id}.json")
    if not os.path.exists(path):
        return {"bookmarks": [], "collections": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_user_data(user_id: str, data: dict):
    path = os.path.join(USERDATA_DIR, f"{user_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# --- Server config (multi-server support) ---


def _load_server_config() -> dict:
    """Load per-server config. {guild_id: {quiz_channel, votd_channel}}"""
    if not os.path.exists(SERVER_CONFIG_PATH):
        return {}
    with open(SERVER_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_server_config(config: dict):
    with open(SERVER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _get_quiz_channels() -> list[int]:
    """Get all configured quiz channel IDs across all servers."""
    config = _load_server_config()
    channels = [int(c["quiz_channel"]) for c in config.values() if c.get("quiz_channel")]
    # Legacy fallback
    if QUIZ_CHANNEL_ID and int(QUIZ_CHANNEL_ID) not in channels:
        channels.append(int(QUIZ_CHANNEL_ID))
    return channels


def _get_votd_channels() -> list[int]:
    """Get all configured VOTD channel IDs across all servers."""
    config = _load_server_config()
    return [int(c["votd_channel"]) for c in config.values() if c.get("votd_channel")]

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


# --- Related verses (keyword-based) ---

# Common words to skip when finding related verses
STOP_WORDS = {
    "the", "and", "of", "to", "in", "a", "is", "that", "it", "for", "was",
    "on", "are", "as", "with", "his", "they", "be", "at", "one", "have",
    "this", "from", "or", "had", "by", "not", "but", "what", "all", "were",
    "we", "when", "your", "can", "said", "there", "an", "which", "their",
    "if", "will", "do", "shall", "he", "she", "him", "her", "them", "who",
    "has", "been", "my", "i", "me", "no", "so", "up", "out", "about", "into",
    "than", "its", "you", "then", "did", "also", "am", "ye", "unto", "upon",
    "thou", "thee", "thy", "hath", "doth", "would", "may", "let", "us",
    "those", "these", "even", "own", "how", "nor", "neither", "yet", "now",
}


def extract_keywords(text: str, max_words: int = 6) -> set[str]:
    """Extract meaningful keywords from verse text."""
    words = re.findall(r"[a-z]+", text.lower())
    keywords = [w for w in words if w not in STOP_WORDS and len(w) > 2]
    return set(keywords[:max_words])


def find_related(book: str, chapter: int, verse: int, max_results: int = 5) -> list[tuple[str, str, str, str]]:
    """Find verses related by keyword overlap. Returns (book, ch, v, text)."""
    # Get the source verse text
    source_text = DB["books"].get(book, {}).get("chapters", {}).get(
        str(chapter), {}
    ).get("verses", {}).get(str(verse), "")
    if not source_text:
        return []

    keywords = extract_keywords(source_text)
    if not keywords:
        return []

    scored = []
    for bname, bdata in DB["books"].items():
        for ch_num, ch_data in bdata["chapters"].items():
            for v_num, v_text in ch_data["verses"].items():
                # Skip the source verse itself
                if bname == book and ch_num == str(chapter) and v_num == str(verse):
                    continue
                v_keywords = extract_keywords(v_text)
                overlap = len(keywords & v_keywords)
                if overlap >= 2:
                    scored.append((overlap, bname, ch_num, v_num, v_text))

    scored.sort(key=lambda x: -x[0])
    return [(b, c, v, t) for _, b, c, v, t in scored[:max_results]]


# --- Embed title parsing ---

# Parse embed titles like "Evangelicon 1:1", "Romans 3:21-25", "Evangelicon 1:1 (in context)"
EMBED_TITLE_RE = re.compile(r"^(.+?)\s+(\d+):(\d+)(?:\s*-\s*(\d+))?")


def parse_embed_title(title: str) -> tuple[str, int, int, int | None] | None:
    """Parse a verse reference from an embed title."""
    m = EMBED_TITLE_RE.match(title)
    if not m:
        return None
    book, ch, v_start, v_end = m.groups()
    if book not in DB["books"]:
        return None
    return book, int(ch), int(v_start), int(v_end) if v_end else None


# --- Bot setup ---

intents = discord.Intents.default()
intents.message_content = True  # needed for inline verse expansion
intents.reactions = True  # needed for reaction features
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Allow commands to work in DMs, group chats, and servers (user-installable)
ALLOWED_CONTEXTS = app_commands.AppCommandContext(
    guild=True, dm_channel=True, private_channel=True
)
ALLOWED_INSTALLS = app_commands.AppInstallationType(guild=True, user=True)
tree.allowed_contexts = ALLOWED_CONTEXTS
tree.allowed_installs = ALLOWED_INSTALLS


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


class TimeoutView(ui.View):
    """Base view that disables all buttons when it times out."""

    message: discord.Message | None = None

    async def on_timeout(self):
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass


class SearchPaginator(TimeoutView):
    """Paginated search results with Previous/Next buttons."""

    PER_PAGE = 5

    def __init__(self, results: list[tuple[str, str, str, str, float]], query: str, book_filter: str | None):
        super().__init__(timeout=900)
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


class ChapterPaginator(TimeoutView):
    """Paginated chapter display."""

    VERSES_PER_PAGE = 15

    def __init__(self, book: str, chapter: int):
        super().__init__(timeout=900)
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


class RelatedView(TimeoutView):
    """Button to show related passages for a verse."""

    def __init__(self, book: str, chapter: int, verse: int):
        super().__init__(timeout=900)
        self.book = book
        self.chapter = chapter
        self.verse = verse

    @ui.button(label="Related Passages", style=discord.ButtonStyle.primary, emoji="\U0001f517")
    async def related_btn(self, interaction: discord.Interaction, button: ui.Button):
        related = find_related(self.book, self.chapter, self.verse)
        if not related:
            await interaction.response.send_message(
                "No related passages found.", ephemeral=True
            )
            return

        desc_lines = []
        for bname, ch, v, txt in related:
            display = txt if len(txt) <= 150 else txt[:147] + "..."
            desc_lines.append(f"**{bname} {ch}:{v}**\n{display}\n")

        embed = discord.Embed(
            title=f"Related to {self.book} {self.chapter}:{self.verse}",
            description="\n".join(desc_lines),
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


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
    view = RelatedView(book, chapter, v_start)
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()


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
    view.message = await interaction.original_response()


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
    view = RelatedView(bname, int(ch), int(v))
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()


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
    view.message = await interaction.original_response()


@tree.command(name="verseoftheday", description="See today's Verse of the Day")
async def votd_command(interaction: discord.Interaction):
    votd = _fetch_votd()
    if not votd:
        embed = discord.Embed(
            title="Not Available Yet",
            description="The Verse of the Day hasn't been set yet. Check back later!",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    ref = f"{votd['book']} {votd['chapter']}:{votd['verse_start']}"
    if votd["verse_start"] != votd["verse_end"]:
        ref += f"-{votd['verse_end']}"

    # Generate verse image
    verse_tuples = [(int(v["verse"]), v["text"]) for v in votd["verses"]]
    buf = render_verse(ref, verse_tuples)
    file = discord.File(buf, filename="votd.png")

    embed = discord.Embed(
        title=f"Verse of the Day — {votd.get('date', 'Today')}",
        description=f"*{votd['blurb']}*",
        color=EMBED_COLOR,
    )
    embed.set_image(url="attachment://votd.png")
    embed.set_footer(text="Verse selection and summary generated by AI")
    await interaction.response.send_message(embed=embed, file=file)


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


@tree.command(name="image", description="Generate a shareable verse image")
@app_commands.describe(reference="Verse reference, e.g. 'Evang 1:1' or 'Rom 7:11-13'")
@app_commands.autocomplete(reference=verse_autocomplete)
async def image_command(interaction: discord.Interaction, reference: str):
    parsed = parse_reference(reference)
    if not parsed:
        embed = discord.Embed(
            title="Invalid Reference",
            description=(
                f"Could not parse: `{reference}`\n\n"
                "**Format:** `Book Chapter:Verse` or `Book Chapter:Start-End`\n"
                "**Examples:** `Evang 1:1`, `Rom 7:11-13`"
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

    # Get section heading from first verse
    section = results[0][2]

    # Build verse list for image
    verse_tuples = [(vnum, text) for vnum, text, _ in results]

    await interaction.response.defer()
    buf = render_verse(ref_str, verse_tuples, section=section)
    file = discord.File(buf, filename="verse.png")
    embed = discord.Embed(title=ref_str, color=EMBED_COLOR)
    embed.set_image(url="attachment://verse.png")
    await interaction.followup.send(embed=embed, file=file)


class QuizView(TimeoutView):
    """Scripture quiz — three rounds: book → chapter → verse."""

    STAGE_BOOK = 0
    STAGE_CHAPTER = 1
    STAGE_VERSE = 2

    def __init__(self, book: str, chapter: str, verse: str, text: str,
                 start_stage: int = 0):
        super().__init__(timeout=900)
        self.book = book
        self.chapter = chapter
        self.verse = verse
        self.text = text
        self.start_stage = start_stage
        self.stage = start_stage
        self.score = 0
        self.total_stages = 3 - start_stage
        self.answered = False

        if start_stage == self.STAGE_BOOK:
            self._setup_book_buttons()
        elif start_stage == self.STAGE_CHAPTER:
            self._setup_chapter_buttons()
        elif start_stage == self.STAGE_VERSE:
            self._setup_verse_buttons()

    def _clear_buttons(self):
        self.clear_items()

    def _setup_book_buttons(self):
        self._clear_buttons()
        all_books = list(DB["books"].keys())
        wrong = [b for b in all_books if b != self.book]
        random.shuffle(wrong)
        choices = wrong[:3] + [self.book]
        random.shuffle(choices)

        for choice in choices:
            btn = ui.Button(
                label=choice,
                style=discord.ButtonStyle.secondary,
            )
            btn.callback = self._make_book_callback(choice)
            self.add_item(btn)

    def _setup_chapter_buttons(self):
        self._clear_buttons()
        ch_count = len(DB["books"][self.book]["chapters"])
        all_chapters = list(range(1, ch_count + 1))
        correct_ch = int(self.chapter)
        wrong = [c for c in all_chapters if c != correct_ch]
        random.shuffle(wrong)
        choices = wrong[:3] + [correct_ch]
        random.shuffle(choices)

        for choice in choices:
            btn = ui.Button(
                label=f"Chapter {choice}",
                style=discord.ButtonStyle.secondary,
            )
            btn.callback = self._make_chapter_callback(choice)
            self.add_item(btn)

    def _setup_verse_buttons(self):
        self._clear_buttons()
        ch_data = DB["books"][self.book]["chapters"][self.chapter]
        all_verses = [int(v) for v in ch_data["verses"].keys()]
        correct_v = int(self.verse)
        wrong = [v for v in all_verses if v != correct_v]
        random.shuffle(wrong)
        choices = wrong[:3] + [correct_v]
        random.shuffle(choices)

        for choice in choices:
            btn = ui.Button(
                label=f"Verse {choice}",
                style=discord.ButtonStyle.secondary,
            )
            btn.callback = self._make_verse_callback(choice)
            self.add_item(btn)

    def _make_book_callback(self, choice: str):
        async def callback(interaction: discord.Interaction):
            if self.answered:
                await interaction.response.send_message("Already answered!", ephemeral=True)
                return

            correct = choice == self.book
            embed = interaction.message.embeds[0]
            ref = f"{self.book} {self.chapter}:{self.verse}"

            if correct:
                self.score += 1
                self.stage = self.STAGE_CHAPTER
                self._setup_chapter_buttons()
                status = self._build_status()
                embed.description = (
                    f"*Guess the reference!*\n\n>>> {self.text}\n\n"
                    f"{status}\n"
                    f"*Now guess the chapter!*"
                )
                embed.color = EMBED_COLOR
                embed.set_footer(text=f"Score: {self.score}/{self.total_stages} — answered by {interaction.user.display_name}")
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                self.answered = True
                self._clear_buttons()
                embed.color = 0xFF0000
                embed.description = (
                    f"*Which book is this verse from?*\n\n>>> {self.text}\n\n"
                    f"Wrong! The answer is **{ref}**"
                )
                embed.set_footer(text=f"Score: {self.score}/{self.total_stages} — answered by {interaction.user.display_name}")
                await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _build_status(self) -> str:
        """Build the status lines showing known/guessed info."""
        lines = []
        if self.start_stage <= self.STAGE_BOOK:
            if self.stage > self.STAGE_BOOK:
                lines.append(f"Book: **{self.book}** \u2705")
            # else: still guessing book, don't show
        else:
            lines.append(f"Book: **{self.book}**")

        if self.start_stage <= self.STAGE_CHAPTER:
            if self.stage > self.STAGE_CHAPTER:
                lines.append(f"Chapter: **{self.chapter}** \u2705")
        else:
            lines.append(f"Chapter: **{self.chapter}**")

        return "\n".join(lines)

    def _make_chapter_callback(self, choice: int):
        async def callback(interaction: discord.Interaction):
            if self.answered:
                await interaction.response.send_message("Already answered!", ephemeral=True)
                return

            correct = choice == int(self.chapter)
            embed = interaction.message.embeds[0]
            ref = f"{self.book} {self.chapter}:{self.verse}"

            if correct:
                self.score += 1
                self.stage = self.STAGE_VERSE
                self._setup_verse_buttons()
                status = self._build_status()
                embed.description = (
                    f"*Guess the reference!*\n\n>>> {self.text}\n\n"
                    f"{status}\n"
                    f"*Now guess the verse!*"
                )
                embed.color = EMBED_COLOR
                embed.set_footer(text=f"Score: {self.score}/{self.total_stages} — answered by {interaction.user.display_name}")
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                self.answered = True
                self._clear_buttons()
                status = self._build_status()
                embed.color = 0xFF0000
                embed.description = (
                    f"*Guess the reference!*\n\n>>> {self.text}\n\n"
                    f"{status}\n"
                    f"Wrong chapter! The answer is **{ref}**"
                )
                embed.set_footer(text=f"Score: {self.score}/{self.total_stages} — answered by {interaction.user.display_name}")
                await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _make_verse_callback(self, choice: int):
        async def callback(interaction: discord.Interaction):
            if self.answered:
                await interaction.response.send_message("Already answered!", ephemeral=True)
                return

            self.answered = True
            self.stage = self.STAGE_VERSE + 1  # past final stage for _build_status
            correct = choice == int(self.verse)
            embed = interaction.message.embeds[0]
            ref = f"{self.book} {self.chapter}:{self.verse}"
            status = self._build_status()

            if correct:
                self.score += 1
                self._clear_buttons()
                embed.color = 0x00FF00
                embed.description = (
                    f"*Guess the reference!*\n\n>>> {self.text}\n\n"
                    f"{status}\n"
                    f"Verse: **{self.verse}** \u2705\n\n"
                    f"**Perfect score!**"
                )
                embed.set_footer(text=f"Score: {self.score}/{self.total_stages} — answered by {interaction.user.display_name}")
            else:
                self._clear_buttons()
                embed.color = 0xFFAA00
                embed.description = (
                    f"*Guess the reference!*\n\n>>> {self.text}\n\n"
                    f"{status}\n"
                    f"Verse: **{self.verse}** \u274c (you guessed {choice})\n\n"
                    f"**Close! The answer is {ref}**"
                )
                embed.set_footer(text=f"Score: {self.score}/{self.total_stages} — answered by {interaction.user.display_name}")

            await interaction.response.edit_message(embed=embed, view=self)

        return callback


@tree.command(name="quiz", description="Scripture quiz — guess the reference of a verse")
@app_commands.describe(
    book="Provide to skip the book round (optional)",
    chapter="Provide to skip the chapter round too (optional, requires book)",
)
@app_commands.autocomplete(book=book_autocomplete)
async def quiz_command(interaction: discord.Interaction, book: str | None = None, chapter: int | None = None):
    resolved = None
    start_stage = QuizView.STAGE_BOOK

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
        start_stage = QuizView.STAGE_CHAPTER

        if chapter is not None:
            if str(chapter) not in DB["books"][resolved]["chapters"]:
                ch_count = len(DB["books"][resolved]["chapters"])
                embed = discord.Embed(
                    title="Invalid Chapter",
                    description=f"**{resolved}** has {ch_count} chapters (1-{ch_count}).",
                    color=0xFF0000,
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            start_stage = QuizView.STAGE_VERSE

    # Build verse pool based on provided filters
    pool = DB["books"]
    if resolved:
        pool = {resolved: DB["books"][resolved]}

    all_verses = []
    for bname, bdata in pool.items():
        for ch_num, ch_data in bdata["chapters"].items():
            if chapter is not None and resolved and int(ch_num) != chapter:
                continue
            for v_num, v_text in ch_data["verses"].items():
                all_verses.append((bname, ch_num, v_num, v_text))

    if not all_verses:
        await interaction.response.send_message("No verses found.", ephemeral=True)
        return

    bname, ch, v, txt = random.choice(all_verses)

    # Build initial prompt based on starting stage
    if start_stage == QuizView.STAGE_BOOK:
        prompt = "*Which book is this verse from?*"
        hint = "Pick the correct book!"
    elif start_stage == QuizView.STAGE_CHAPTER:
        prompt = f"*Which chapter of **{resolved}** is this from?*"
        hint = "Pick the correct chapter!"
    else:
        prompt = f"*Which verse in **{resolved}** chapter **{chapter}** is this?*"
        hint = "Pick the correct verse!"

    # Generate verse image without reference
    quiz_img = render_verse("", [(1, txt)], hide_reference=True)
    file = discord.File(quiz_img, filename="quiz.png")

    embed = discord.Embed(
        title="Scripture Quiz",
        description=prompt,
        color=EMBED_COLOR,
    )
    embed.set_image(url="attachment://quiz.png")
    embed.set_footer(text=hint)

    view = QuizView(bname, ch, v, txt, start_stage=start_stage)
    await interaction.response.send_message(embed=embed, view=view, file=file)
    view.message = await interaction.original_response()


def _generate_quiz_data() -> dict:
    """Generate a new daily quiz (pick verse, generate choices)."""
    # Load quiz history
    history_path = os.path.join(RUNTIME_DIR, "quiz_history.json")
    history = []
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)

    # Pick a verse not in history
    all_verses = []
    for bname, bdata in DB["books"].items():
        for ch_num, ch_data in bdata["chapters"].items():
            for v_num, v_text in ch_data["verses"].items():
                ref = f"{bname} {ch_num}:{v_num}"
                if ref not in history:
                    all_verses.append((bname, ch_num, v_num, v_text))

    if not all_verses:
        history.clear()
        for bname, bdata in DB["books"].items():
            for ch_num, ch_data in bdata["chapters"].items():
                for v_num, v_text in ch_data["verses"].items():
                    all_verses.append((bname, ch_num, v_num, v_text))

    book, chapter, verse, text = random.choice(all_verses)

    # Generate 4 choices for each stage
    all_books = list(DB["books"].keys())
    wrong_books = [b for b in all_books if b != book]
    random.shuffle(wrong_books)
    book_choices = wrong_books[:3] + [book]
    random.shuffle(book_choices)

    all_chapters = list(range(1, len(DB["books"][book]["chapters"]) + 1))
    correct_ch = int(chapter)
    wrong_chapters = [c for c in all_chapters if c != correct_ch]
    random.shuffle(wrong_chapters)
    chapter_choices = wrong_chapters[:3] + [correct_ch]
    random.shuffle(chapter_choices)

    ch_data = DB["books"][book]["chapters"][chapter]
    all_v = [int(v) for v in ch_data["verses"].keys()]
    correct_v = int(verse)
    wrong_v = [v for v in all_v if v != correct_v]
    random.shuffle(wrong_v)
    verse_choices = wrong_v[:3] + [correct_v]
    random.shuffle(verse_choices)

    # Update history
    history.append(f"{book} {chapter}:{verse}")
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    return {
        "book": book,
        "chapter": chapter,
        "verse": verse,
        "text": text,
        "book_choices": book_choices,
        "chapter_choices": chapter_choices,
        "verse_choices": verse_choices,
        "leaderboard": {},
    }


setup_group = app_commands.Group(
    name="setup",
    description="Configure Testamentum Bot for this server (admin only)",
    default_permissions=discord.Permissions(administrator=True),
)
tree.add_command(setup_group)


@setup_group.command(name="quiz", description="Set the daily quiz channel")
@app_commands.describe(channel="Channel for the daily quiz")
async def setup_quiz(interaction: discord.Interaction, channel: discord.TextChannel):
    config = _load_server_config()
    guild_id = str(interaction.guild_id)
    config.setdefault(guild_id, {})
    config[guild_id]["quiz_channel"] = str(channel.id)
    _save_server_config(config)
    await interaction.response.send_message(
        f"Daily quiz will be posted to {channel.mention}.", ephemeral=True
    )


@setup_group.command(name="votd", description="Set the Verse of the Day channel")
@app_commands.describe(channel="Channel for the Verse of the Day")
async def setup_votd(interaction: discord.Interaction, channel: discord.TextChannel):
    config = _load_server_config()
    guild_id = str(interaction.guild_id)
    config.setdefault(guild_id, {})
    config[guild_id]["votd_channel"] = str(channel.id)
    _save_server_config(config)
    await interaction.response.send_message(
        f"Verse of the Day will be posted to {channel.mention}.", ephemeral=True
    )


@setup_group.command(name="disable", description="Disable a daily feature")
@app_commands.describe(feature="Feature to disable")
@app_commands.choices(feature=[
    app_commands.Choice(name="quiz", value="quiz_channel"),
    app_commands.Choice(name="votd", value="votd_channel"),
])
async def setup_disable(interaction: discord.Interaction, feature: app_commands.Choice[str]):
    config = _load_server_config()
    guild_id = str(interaction.guild_id)
    if guild_id in config and feature.value in config[guild_id]:
        del config[guild_id][feature.value]
        _save_server_config(config)
        await interaction.response.send_message(
            f"Disabled **{feature.name}** for this server.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"**{feature.name}** is not configured for this server.", ephemeral=True
        )


@setup_group.command(name="status", description="Show current configuration")
async def setup_status(interaction: discord.Interaction):
    config = _load_server_config()
    guild_id = str(interaction.guild_id)
    guild_config = config.get(guild_id, {})

    lines = []
    quiz_ch = guild_config.get("quiz_channel")
    votd_ch = guild_config.get("votd_channel")
    lines.append(f"**Daily Quiz:** {f'<#{quiz_ch}>' if quiz_ch else 'Not configured'}")
    lines.append(f"**Verse of the Day:** {f'<#{votd_ch}>' if votd_ch else 'Not configured'}")

    embed = discord.Embed(
        title="Server Configuration",
        description="\n".join(lines),
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="postquiz", description="Manually trigger the daily quiz (admin only)")
@app_commands.default_permissions(administrator=True)
async def postquiz_command(interaction: discord.Interaction):
    await interaction.response.defer()
    await _auto_post_quiz()
    await interaction.followup.send("Daily quiz posted!", ephemeral=True)


@tree.command(name="clearleaderboard", description="Reset this server's quiz leaderboard (admin only)")
@app_commands.default_permissions(administrator=True)
async def clearleaderboard_command(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id)
    lb = _load_alltime_lb()
    if guild_id in lb:
        del lb[guild_id]
        _save_alltime_lb(lb)
    await interaction.response.send_message("This server's leaderboard has been reset.", ephemeral=True)


@tree.command(name="leaderboard", description="View this server's all-time quiz leaderboard")
async def leaderboard_command(interaction: discord.Interaction):
    guild_id = str(interaction.guild_id) if interaction.guild_id else None
    lb_text = _build_alltime_leaderboard(guild_id, 15)
    embed = discord.Embed(
        title="All-Time Quiz Leaderboard",
        description=lb_text,
        color=EMBED_COLOR,
    )
    all_lb = _load_alltime_lb()
    guild_lb = all_lb.get(guild_id, {}) if guild_id else {}
    total_games = sum(e["games_played"] for e in guild_lb.values()) if guild_lb else 0
    total_perfect = sum(e["perfect"] for e in guild_lb.values()) if guild_lb else 0
    embed.set_footer(text=f"{len(guild_lb)} players | {total_games} games played | {total_perfect} perfect scores")
    await interaction.response.send_message(embed=embed)


@tree.command(name="bookmark", description="Save a verse to your bookmarks")
@app_commands.describe(reference="Verse reference, e.g. 'Evang 1:1' or 'Rom 7:11-13'")
@app_commands.autocomplete(reference=verse_autocomplete)
async def bookmark_command(interaction: discord.Interaction, reference: str):
    parsed = parse_reference(reference)
    if not parsed:
        embed = discord.Embed(
            title="Invalid Reference",
            description=f"Could not parse: `{reference}`",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    book, chapter, v_start, v_end = parsed
    ref_str = f"{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "")

    # Verify the verse exists
    results = get_verses(book, chapter, v_start, v_end)
    if not results:
        embed = discord.Embed(
            title="Not Found",
            description=f"No verses found for **{ref_str}**",
            color=0xFF0000,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)

    # Check for duplicate
    if ref_str in data["bookmarks"]:
        await interaction.response.send_message(
            f"**{ref_str}** is already in your bookmarks.", ephemeral=True
        )
        return

    data["bookmarks"].append(ref_str)
    _save_user_data(user_id, data)
    await interaction.response.send_message(
        f"\U0001f516 Bookmarked **{ref_str}** ({len(data['bookmarks'])} total)",
        ephemeral=True,
    )


@tree.command(name="bookmarks", description="View your saved bookmarks")
async def bookmarks_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)
    bookmarks = data.get("bookmarks", [])

    if not bookmarks:
        embed = discord.Embed(
            title="Your Bookmarks",
            description="No bookmarks yet. Use `/bookmark Evang 1:1` or react with \U0001f516 on any verse.",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Show bookmarks with verse text previews
    lines = []
    for ref in bookmarks[-20:]:  # show last 20
        parsed = parse_reference(ref)
        if parsed:
            book, ch, vs, ve = parsed
            results = get_verses(book, ch, vs, ve)
            if results:
                preview = results[0][1]
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(f"**{ref}** — {preview}")
            else:
                lines.append(f"**{ref}**")
        else:
            lines.append(f"**{ref}**")

    embed = discord.Embed(
        title=f"Your Bookmarks ({len(bookmarks)})",
        description="\n".join(lines),
        color=EMBED_COLOR,
    )
    if len(bookmarks) > 20:
        embed.set_footer(text=f"Showing latest 20 of {len(bookmarks)}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="unbookmark", description="Remove a verse from your bookmarks")
@app_commands.describe(reference="Verse reference to remove")
@app_commands.autocomplete(reference=verse_autocomplete)
async def unbookmark_command(interaction: discord.Interaction, reference: str):
    parsed = parse_reference(reference)
    if not parsed:
        await interaction.response.send_message(
            f"Could not parse: `{reference}`", ephemeral=True
        )
        return

    book, chapter, v_start, v_end = parsed
    ref_str = f"{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "")

    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)

    if ref_str in data["bookmarks"]:
        data["bookmarks"].remove(ref_str)
        _save_user_data(user_id, data)
        await interaction.response.send_message(
            f"Removed **{ref_str}** from your bookmarks.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"**{ref_str}** is not in your bookmarks.", ephemeral=True
        )


# --- Collections ---

collection_group = app_commands.Group(
    name="collection",
    description="Manage your personal verse collections",
)
tree.add_command(collection_group)


@collection_group.command(name="create", description="Create a new collection")
@app_commands.describe(name="Name for the collection")
async def collection_create(interaction: discord.Interaction, name: str):
    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)
    collections = data.setdefault("collections", {})

    if name in collections:
        await interaction.response.send_message(
            f"Collection **{name}** already exists.", ephemeral=True
        )
        return

    if len(collections) >= 20:
        await interaction.response.send_message(
            "You can have up to 20 collections.", ephemeral=True
        )
        return

    collections[name] = []
    _save_user_data(user_id, data)
    await interaction.response.send_message(
        f"Created collection **{name}**.", ephemeral=True
    )


@collection_group.command(name="add", description="Add a verse to a collection")
@app_commands.describe(
    name="Collection name",
    reference="Verse reference, e.g. 'Evang 1:1'",
)
@app_commands.autocomplete(reference=verse_autocomplete)
async def collection_add(interaction: discord.Interaction, name: str, reference: str):
    parsed = parse_reference(reference)
    if not parsed:
        await interaction.response.send_message(
            f"Could not parse: `{reference}`", ephemeral=True
        )
        return

    book, chapter, v_start, v_end = parsed
    ref_str = f"{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "")

    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)
    collections = data.get("collections", {})

    if name not in collections:
        await interaction.response.send_message(
            f"Collection **{name}** doesn't exist. Create it first with `/collection create {name}`.",
            ephemeral=True,
        )
        return

    if ref_str in collections[name]:
        await interaction.response.send_message(
            f"**{ref_str}** is already in **{name}**.", ephemeral=True
        )
        return

    collections[name].append(ref_str)
    _save_user_data(user_id, data)
    await interaction.response.send_message(
        f"Added **{ref_str}** to **{name}** ({len(collections[name])} verses)",
        ephemeral=True,
    )


@collection_group.command(name="remove", description="Remove a verse from a collection")
@app_commands.describe(
    name="Collection name",
    reference="Verse reference to remove",
)
@app_commands.autocomplete(reference=verse_autocomplete)
async def collection_remove(interaction: discord.Interaction, name: str, reference: str):
    parsed = parse_reference(reference)
    if not parsed:
        await interaction.response.send_message(
            f"Could not parse: `{reference}`", ephemeral=True
        )
        return

    book, chapter, v_start, v_end = parsed
    ref_str = f"{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "")

    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)
    collections = data.get("collections", {})

    if name not in collections:
        await interaction.response.send_message(
            f"Collection **{name}** doesn't exist.", ephemeral=True
        )
        return

    if ref_str in collections[name]:
        collections[name].remove(ref_str)
        _save_user_data(user_id, data)
        await interaction.response.send_message(
            f"Removed **{ref_str}** from **{name}**.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"**{ref_str}** is not in **{name}**.", ephemeral=True
        )


@collection_group.command(name="view", description="View a collection's verses")
@app_commands.describe(name="Collection name")
async def collection_view(interaction: discord.Interaction, name: str):
    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)
    collections = data.get("collections", {})

    if name not in collections:
        await interaction.response.send_message(
            f"Collection **{name}** doesn't exist.", ephemeral=True
        )
        return

    verses = collections[name]
    if not verses:
        embed = discord.Embed(
            title=f"Collection: {name}",
            description="This collection is empty. Use `/collection add` to add verses.",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    lines = []
    for ref in verses:
        parsed = parse_reference(ref)
        if parsed:
            book, ch, vs, ve = parsed
            results = get_verses(book, ch, vs, ve)
            if results:
                preview = results[0][1]
                if len(preview) > 80:
                    preview = preview[:77] + "..."
                lines.append(f"**{ref}** — {preview}")
            else:
                lines.append(f"**{ref}**")
        else:
            lines.append(f"**{ref}**")

    embed = discord.Embed(
        title=f"Collection: {name} ({len(verses)} verses)",
        description="\n".join(lines),
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@collection_group.command(name="list", description="List all your collections")
async def collection_list(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)
    collections = data.get("collections", {})

    if not collections:
        embed = discord.Embed(
            title="Your Collections",
            description="No collections yet. Use `/collection create \"Favorites\"` to start.",
            color=EMBED_COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    lines = []
    for name, verses in collections.items():
        lines.append(f"**{name}** — {len(verses)} verses")

    embed = discord.Embed(
        title=f"Your Collections ({len(collections)})",
        description="\n".join(lines),
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@collection_group.command(name="delete", description="Delete a collection")
@app_commands.describe(name="Collection name to delete")
async def collection_delete(interaction: discord.Interaction, name: str):
    user_id = str(interaction.user.id)
    data = _load_user_data(user_id)
    collections = data.get("collections", {})

    if name not in collections:
        await interaction.response.send_message(
            f"Collection **{name}** doesn't exist.", ephemeral=True
        )
        return

    count = len(collections[name])
    del collections[name]
    _save_user_data(user_id, data)
    await interaction.response.send_message(
        f"Deleted collection **{name}** ({count} verses).", ephemeral=True
    )


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
        name="/image <reference>",
        value=(
            "Generate a shareable verse image\n"
            "`/image Evang 1:1` `/image Rom 3:23-25`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/quiz [book]",
        value=(
            "Scripture quiz — guess which book a verse is from\n"
            "`/quiz` `/quiz Evangelicon`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/leaderboard",
        value="View the all-time daily quiz leaderboard",
        inline=False,
    )
    embed.add_field(
        name="Reactions",
        value=(
            "\U0001f516 Bookmark — react on a verse to get it DM'd to you\n"
            "\u27a1\ufe0f Expand — react to see the next few verses\n"
            "\U0001f4ac Thread — react to create a discussion thread"
        ),
        inline=False,
    )
    embed.add_field(
        name="Inline Expansion",
        value="Type a verse reference in any message (e.g. \"check out Evang 1:1\") and the bot will auto-reply with the verse.",
        inline=False,
    )
    embed.add_field(
        name="Bookmarks & Collections",
        value=(
            "`/bookmark <reference>` — save a verse\n"
            "`/bookmarks` — view your saved verses\n"
            "`/unbookmark <reference>` — remove a bookmark\n"
            "`/collection create/add/remove/view/list/delete`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Server Setup (admin)",
        value=(
            "`/setup quiz #channel` — set daily quiz channel\n"
            "`/setup votd #channel` — set Verse of the Day channel\n"
            "`/setup disable` — disable a feature\n"
            "`/setup status` — show current config"
        ),
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


# --- Daily Quiz (persistent view) ---


def _fetch_votd() -> dict | None:
    """Fetch the latest VOTD from GitHub, falling back to local file."""
    try:
        resp = http_requests.get(VOTD_GITHUB_URL, timeout=10)
        resp.raise_for_status()
        votd = resp.json()
        # Cache locally
        with open(VOTD_PATH, "w", encoding="utf-8") as f:
            json.dump(votd, f, indent=2, ensure_ascii=False)
        return votd
    except Exception as e:
        print(f"Failed to fetch VOTD from GitHub: {e}")
        # Fall back to local file
        if os.path.exists(VOTD_PATH):
            with open(VOTD_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return None


def _load_daily_quiz() -> dict | None:
    if not os.path.exists(QUIZ_PATH):
        return None
    with open(QUIZ_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_daily_quiz(quiz: dict):
    with open(QUIZ_PATH, "w", encoding="utf-8") as f:
        json.dump(quiz, f, indent=2, ensure_ascii=False)


def _load_alltime_lb() -> dict:
    """Load all-time leaderboard. {guild_id: {user_id: {name, total_score, games_played, perfect}}}"""
    if not os.path.exists(ALLTIME_LB_PATH):
        return {}
    with open(ALLTIME_LB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_alltime_lb(lb: dict):
    with open(ALLTIME_LB_PATH, "w", encoding="utf-8") as f:
        json.dump(lb, f, indent=2, ensure_ascii=False)


def _update_alltime_score(guild_id: str, user_id: str, user_name: str, score: int):
    """Add a completed quiz score to a server's all-time leaderboard."""
    lb = _load_alltime_lb()
    guild_lb = lb.setdefault(guild_id, {})
    if user_id not in guild_lb:
        guild_lb[user_id] = {"name": user_name, "total_score": 0, "games_played": 0, "perfect": 0}
    guild_lb[user_id]["name"] = user_name
    guild_lb[user_id]["total_score"] += score
    guild_lb[user_id]["games_played"] += 1
    if score == 3:
        guild_lb[user_id]["perfect"] += 1
    _save_alltime_lb(lb)


def _build_today_leaderboard(quiz: dict) -> str:
    """Build today's leaderboard string."""
    lb = quiz.get("leaderboard", {})
    if not lb:
        return "*No answers yet*"

    entries = sorted(lb.values(), key=lambda e: -e["score"])
    lines = []
    for i, entry in enumerate(entries[:15]):
        medal = ["\U0001f947", "\U0001f948", "\U0001f949"][i] if i < 3 else f"**{i+1}.**"
        stage_label = f"{entry['score']}/3"
        if entry.get("done"):
            lines.append(f"{medal} {entry['name']} — {stage_label}")
        else:
            lines.append(f"{medal} {entry['name']} — {stage_label} *(in progress)*")

    return "\n".join(lines)


def _build_alltime_leaderboard(guild_id: str | None = None, max_entries: int = 10) -> str:
    """Build all-time leaderboard string for a specific server."""
    all_lb = _load_alltime_lb()
    if not all_lb or not guild_id:
        return "*No scores yet*"

    lb = all_lb.get(guild_id, {})
    if not lb:
        return "*No scores yet*"

    entries = sorted(lb.values(), key=lambda e: (-e["total_score"], -e["perfect"]))
    lines = []
    for i, entry in enumerate(entries[:max_entries]):
        medal = ["\U0001f947", "\U0001f948", "\U0001f949"][i] if i < 3 else f"**{i+1}.**"
        avg = entry["total_score"] / entry["games_played"] if entry["games_played"] else 0
        lines.append(
            f"{medal} {entry['name']} — **{entry['total_score']}** pts "
            f"({entry['games_played']} games, {entry['perfect']} perfect, "
            f"avg {avg:.1f})"
        )

    return "\n".join(lines)


async def _update_quiz_embed(quiz: dict):
    """Update quiz embeds in all servers with both leaderboards."""
    today_lb = _build_today_leaderboard(quiz)

    # Get all message locations
    messages = quiz.get("messages", {})
    # Legacy fallback
    if not messages and quiz.get("channel_id") and quiz.get("message_id"):
        messages = {quiz["channel_id"]: quiz["message_id"]}

    for ch_id, msg_id in messages.items():
        channel = client.get_channel(int(ch_id))
        if not channel:
            continue
        try:
            message = await channel.fetch_message(int(msg_id))
        except discord.NotFound:
            continue

        guild_id = str(channel.guild.id) if channel.guild else None
        alltime_lb = _build_alltime_leaderboard(guild_id, 5)

        embed = message.embeds[0]
        embed.clear_fields()
        embed.add_field(name="Today's Scores", value=today_lb, inline=False)
        embed.add_field(name="All-Time Leaderboard", value=alltime_lb, inline=False)

        try:
            await message.edit(embed=embed)
        except discord.Forbidden:
            pass


async def _handle_daily_quiz(interaction: discord.Interaction, custom_id: str):
    """Handle all daily quiz button interactions (book, chapter, verse)."""
    quiz = _load_daily_quiz()
    if not quiz:
        await interaction.response.send_message(
            "No daily quiz is active right now.", ephemeral=True
        )
        return

    user_id = str(interaction.user.id)
    guild_id = str(interaction.guild_id) if interaction.guild_id else "dm"
    user_name = interaction.user.display_name
    lb = quiz.setdefault("leaderboard", {})

    # Parse: dq_book_0, dq_chapter_2, dq_verse_1
    parts = custom_id.split("_")
    stage = parts[1]
    choice_idx = int(parts[2])

    if user_id not in lb:
        lb[user_id] = {"name": user_name, "score": 0, "stage": "book", "done": False}

    user_entry = lb[user_id]

    if user_entry["done"]:
        ref = f"{quiz['book']} {quiz['chapter']}:{quiz['verse']}"
        await interaction.response.send_message(
            f"You already completed today's quiz! (Score: {user_entry['score']}/3)\n"
            f"The answer was **{ref}**",
            ephemeral=True,
        )
        return

    if user_entry["stage"] != stage:
        # User is on a later stage but clicked an earlier button.
        # Resend the buttons for their current stage so they can continue.
        current = user_entry["stage"]
        if current == "chapter":
            view = ui.View(timeout=None)
            for j, ch in enumerate(quiz["chapter_choices"]):
                btn = ui.Button(label=f"Chapter {ch}", style=discord.ButtonStyle.secondary)
                btn.callback = _make_ephemeral_handler(f"dq_chapter_{j}")
                view.add_item(btn)
            await interaction.response.send_message(
                f"You already got the book right (**{quiz['book']}**).\n\n*Now guess the chapter:*",
                view=view, ephemeral=True,
            )
        elif current == "verse":
            view = ui.View(timeout=None)
            for j, v in enumerate(quiz["verse_choices"]):
                btn = ui.Button(label=f"Verse {v}", style=discord.ButtonStyle.secondary)
                btn.callback = _make_ephemeral_handler(f"dq_verse_{j}")
                view.add_item(btn)
            await interaction.response.send_message(
                f"You already got **{quiz['book']} Chapter {quiz['chapter']}** right.\n\n*Now guess the verse:*",
                view=view, ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"You're on the **{current}** round! Use the buttons from your current stage.",
                ephemeral=True,
            )
        return

    ref = f"{quiz['book']} {quiz['chapter']}:{quiz['verse']}"

    if stage == "book":
        choice = quiz["book_choices"][choice_idx]
        correct = choice == quiz["book"]
        if correct:
            user_entry["score"] += 1
            user_entry["stage"] = "chapter"
            _save_daily_quiz(quiz)

            ch_view = ui.View(timeout=None)
            for j, ch in enumerate(quiz["chapter_choices"]):
                btn = ui.Button(label=f"Chapter {ch}", style=discord.ButtonStyle.secondary)
                btn.callback = _make_ephemeral_handler(f"dq_chapter_{j}")
                ch_view.add_item(btn)

            await interaction.response.send_message(
                f"✅ Correct! The book is **{quiz['book']}**.\n\n*Now guess the chapter:*",
                view=ch_view, ephemeral=True,
            )
            client.loop.create_task(_update_quiz_embed(quiz))
        else:
            user_entry["done"] = True
            _update_alltime_score(guild_id, user_id, user_name, user_entry["score"])
            _save_daily_quiz(quiz)
            await interaction.response.send_message(
                f"❌ Wrong! The answer is **{ref}**.\nYour score: **{user_entry['score']}/3**",
                ephemeral=True,
            )
            client.loop.create_task(_update_quiz_embed(quiz))

    elif stage == "chapter":
        choice = quiz["chapter_choices"][choice_idx]
        correct = choice == int(quiz["chapter"])
        if correct:
            user_entry["score"] += 1
            user_entry["stage"] = "verse"
            _save_daily_quiz(quiz)

            v_view = ui.View(timeout=None)
            for j, v in enumerate(quiz["verse_choices"]):
                btn = ui.Button(label=f"Verse {v}", style=discord.ButtonStyle.secondary)
                btn.callback = _make_ephemeral_handler(f"dq_verse_{j}")
                v_view.add_item(btn)

            await interaction.response.send_message(
                f"✅ Correct! It's **{quiz['book']} Chapter {quiz['chapter']}**.\n\n*Now guess the verse:*",
                view=v_view, ephemeral=True,
            )
            client.loop.create_task(_update_quiz_embed(quiz))
        else:
            user_entry["done"] = True
            _update_alltime_score(guild_id, user_id, user_name, user_entry["score"])
            _save_daily_quiz(quiz)
            await interaction.response.send_message(
                f"❌ Wrong chapter! The answer is **{ref}**.\nYour score: **{user_entry['score']}/3**",
                ephemeral=True,
            )
            client.loop.create_task(_update_quiz_embed(quiz))

    elif stage == "verse":
        choice = quiz["verse_choices"][choice_idx]
        correct = choice == int(quiz["verse"])
        user_entry["done"] = True
        if correct:
            user_entry["score"] += 1
        _update_alltime_score(guild_id, user_id, user_name, user_entry["score"])
        _save_daily_quiz(quiz)
        if correct:
            await interaction.response.send_message(
                f"✅ **Perfect score!** The answer is **{ref}**.\nYour score: **{user_entry['score']}/3**",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ Close! The answer is **{ref}** (you guessed verse {choice}).\nYour score: **{user_entry['score']}/3**",
                ephemeral=True,
            )
        client.loop.create_task(_update_quiz_embed(quiz))


def _make_ephemeral_handler(custom_id: str):
    """Create a callback for ephemeral chapter/verse buttons."""
    async def callback(interaction: discord.Interaction):
        await _handle_daily_quiz(interaction, custom_id)
    return callback


class DailyQuizPersistentView(ui.View):
    """Persistent view registered at startup for the book-stage buttons."""

    def __init__(self):
        super().__init__(timeout=None)
        for i in range(4):
            btn = ui.Button(
                label="\u200b",  # invisible placeholder
                style=discord.ButtonStyle.secondary,
                custom_id=f"dq_book_{i}",
            )
            self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("dq_"):
            await _handle_daily_quiz(interaction, custom_id)
            return False  # we handled it
        return True


async def _auto_post_quiz():
    """Auto-post a daily quiz to all configured quiz channels."""
    channels = _get_quiz_channels()
    if not channels:
        print("No quiz channels configured.")
        return

    quiz_data = _generate_quiz_data()

    # Track message IDs per channel for leaderboard updates
    quiz_data["messages"] = {}

    for ch_id in channels:
        channel = client.get_channel(ch_id)
        if not channel:
            print(f"  Quiz channel {ch_id} not found, skipping.")
            continue

        guild_id = str(channel.guild.id) if channel.guild else None
        alltime_text = _build_alltime_leaderboard(guild_id, 5)

        # Generate fresh image and file for each channel
        img_buf = render_verse("", [(1, quiz_data["text"])], hide_reference=True)
        file = discord.File(img_buf, filename="quiz.png")

        embed = discord.Embed(
            title="Daily Scripture Quiz",
            description=(
                "*Which book is this verse from?*\n\n"
                "Everyone can play! Your answers are private."
            ),
            color=EMBED_COLOR,
        )
        embed.set_image(url="attachment://quiz.png")
        embed.add_field(name="Today's Scores", value="*No answers yet*", inline=False)
        embed.add_field(name="All-Time Leaderboard", value=alltime_text, inline=False)
        embed.set_footer(text="Round 1 of 3 — Pick the correct book!")

        view = DailyQuizPersistentView()
        for i, item in enumerate(view.children):
            if isinstance(item, ui.Button) and i < len(quiz_data["book_choices"]):
                item.label = quiz_data["book_choices"][i]

        try:
            msg = await channel.send(embed=embed, view=view, file=file)
            quiz_data["messages"][str(ch_id)] = str(msg.id)
            print(f"  Posted quiz to #{channel.name} ({ch_id})")
        except discord.Forbidden:
            print(f"  No permission to post in {ch_id}, skipping.")

    # Legacy single-channel fields for backward compat
    if quiz_data["messages"]:
        first_ch = list(quiz_data["messages"].keys())[0]
        quiz_data["channel_id"] = first_ch
        quiz_data["message_id"] = quiz_data["messages"][first_ch]

    _save_daily_quiz(quiz_data)
    print(f"Daily quiz posted: {quiz_data['book']} {quiz_data['chapter']}:{quiz_data['verse']}")


@tasks.loop(time=datetime.time(hour=10, minute=5))  # 10:05 UTC = 6:05 AM EST
async def daily_quiz_task():
    await _auto_post_quiz()


@tasks.loop(time=datetime.time(hour=10, minute=0))  # 10:00 UTC = 6:00 AM EST
async def votd_repost_task():
    """Post the VOTD to all configured VOTD channels."""
    channels = _get_votd_channels()
    if not channels:
        return

    votd = _fetch_votd()
    if not votd:
        print("No VOTD available.")
        return

    # Only post if it's today's VOTD
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    if votd.get("date") != today:
        print(f"VOTD is from {votd.get('date')}, not today ({today}). Skipping repost.")
        return

    ref = f"{votd['book']} {votd['chapter']}:{votd['verse_start']}"
    if votd["verse_start"] != votd["verse_end"]:
        ref += f"-{votd['verse_end']}"

    verse_tuples = [(int(v["verse"]), v["text"]) for v in votd["verses"]]
    buf = render_verse(ref, verse_tuples)

    for ch_id in channels:
        channel = client.get_channel(ch_id)
        if not channel:
            continue
        try:
            file = discord.File(buf, filename="votd.png")
            buf.seek(0)  # reset for next channel
            embed = discord.Embed(
                title=f"Verse of the Day — {votd.get('date', 'Today')}",
                description=f"*{votd['blurb']}*",
                color=EMBED_COLOR,
            )
            embed.set_image(url="attachment://votd.png")
            embed.set_footer(text="Verse selection and summary generated by AI")
            await channel.send(embed=embed, file=file)
            print(f"  Posted VOTD to #{channel.name} ({ch_id})")
        except discord.Forbidden:
            print(f"  No permission to post VOTD in {ch_id}")


@client.event
async def on_ready():
    client.add_view(DailyQuizPersistentView())
    if not daily_quiz_task.is_running():
        daily_quiz_task.start()
        print("Daily quiz task scheduled.")
    if not votd_repost_task.is_running():
        votd_repost_task.start()
        print("VOTD repost task scheduled.")
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


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # Ignore bot reactions
    if payload.user_id == client.user.id:
        return

    emoji = str(payload.emoji)
    if emoji not in ("\U0001f516", "\u27a1\ufe0f", "\U0001f4ac"):
        return

    channel = client.get_channel(payload.channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    # Only react to embeds from our bot or our webhook
    is_bot = message.author.id == client.user.id
    is_webhook = message.webhook_id is not None and message.embeds
    if not (is_bot or is_webhook) or not message.embeds:
        return

    embed = message.embeds[0]
    if not embed.title:
        return

    # Try to parse verse reference from embed title
    parsed = parse_embed_title(embed.title)

    # If it's a VOTD embed, load the reference from votd.json
    if not parsed and "Verse of the Day" in embed.title:
        votd = _fetch_votd()
        if votd:
            parsed = (
                votd["book"],
                int(votd["chapter"]),
                int(votd["verse_start"]),
                int(votd["verse_end"]),
            )

    # If it's a quiz embed, load the reference from daily_quiz.json
    if not parsed and "Quiz" in (embed.title or ""):
        quiz = _load_daily_quiz()
        if quiz:
            parsed = (
                quiz["book"],
                int(quiz["chapter"]),
                int(quiz["verse"]),
                None,
            )

    if not parsed:
        return

    book, chapter, v_start, v_end = parsed
    user = client.get_user(payload.user_id)
    if not user:
        try:
            user = await client.fetch_user(payload.user_id)
        except discord.NotFound:
            return

    # 🔖 Bookmark — save persistently and DM the verse
    if emoji == "\U0001f516":
        results = get_verses(book, chapter, v_start, v_end)
        if not results:
            return

        ref_str = f"{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "")

        # Save to persistent bookmarks
        uid = str(payload.user_id)
        user_data = _load_user_data(uid)
        if ref_str not in user_data["bookmarks"]:
            user_data["bookmarks"].append(ref_str)
            _save_user_data(uid, user_data)

        desc_lines = []
        for vnum, text, section in results:
            desc_lines.append(f"**{vnum}** {text}")

        dm_embed = discord.Embed(
            title=f"\U0001f516 {ref_str}",
            description="\n".join(desc_lines),
            color=EMBED_COLOR,
        )
        dm_embed.set_footer(text=f"Bookmarked! You have {len(user_data['bookmarks'])} bookmarks. Use /bookmarks to view.")
        try:
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # user has DMs disabled

    # ➡️ Expand — show next verses
    elif emoji == "\u27a1\ufe0f":
        last_verse = v_end if v_end else v_start
        next_start = last_verse + 1
        next_end = last_verse + 5
        results = get_verses(book, chapter, next_start, next_end)
        if not results:
            # Try next chapter
            next_ch = chapter + 1
            if str(next_ch) in DB["books"].get(book, {}).get("chapters", {}):
                results = get_verses(book, next_ch, 1, 5)
                if results:
                    chapter = next_ch
                    next_start = 1
                    next_end = results[-1][0]

        if not results:
            return

        ref_str = f"{book} {chapter}:{results[0][0]}-{results[-1][0]}"
        desc_lines = []
        last_section = None
        for vnum, text, section in results:
            if section and section != last_section:
                desc_lines.append(f"\n__**{section}**__")
                last_section = section
            desc_lines.append(f"**{vnum}** {text}")

        expand_embed = discord.Embed(
            title=ref_str,
            description="\n".join(desc_lines),
            color=EMBED_COLOR,
        )
        expand_embed.set_footer(text="Continued reading")
        view = RelatedView(book, chapter, results[0][0])
        await channel.send(embed=expand_embed, view=view)

    # 💬 Thread — create discussion thread
    elif emoji == "\U0001f4ac":
        ref_str = f"{book} {chapter}:{v_start}" + (f"-{v_end}" if v_end else "")
        # Check if message already has a thread
        if message.flags.has_thread:
            return
        try:
            thread = await message.create_thread(
                name=f"Discussion: {ref_str}",
                auto_archive_duration=1440,  # 24 hours
            )
            results = get_verses(book, chapter, v_start, v_end)
            verse_text = ""
            if results:
                verse_text = "\n".join(f"**{vn}** {t}" for vn, t, _ in results)
            await thread.send(
                f"**{ref_str}**\n\n{verse_text}\n\n"
                f"*Thread started by {user.display_name} — discuss this passage below!*"
            )
        except discord.Forbidden:
            pass  # missing permissions


def main():
    import time
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set. Create a .env file with your token.")
        return
    try:
        client.run(token)
    except (discord.HTTPException, discord.LoginFailure, discord.DiscordServerError) as e:
        status = getattr(e, "status", None)
        # 429 = token-level rate limit, 5xx = Discord overloaded.
        # Either way, retrying immediately makes things worse — sleep before exit.
        if status == 429 or (status and status >= 500):
            print(f"Discord login failed with status {status}. Sleeping 10 minutes before exit to avoid restart-loop.")
            time.sleep(600)
        raise


if __name__ == "__main__":
    main()
