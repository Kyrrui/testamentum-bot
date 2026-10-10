# Testamentum Bot

A Discord bot for the Marcionite Testamentum — 24 books, 4,300+ verses. Look up verses, search scripture, take quizzes, and more.

**Add it to your server:** open the bot's profile in any server it's in → **Add App** → **Add to Server**. To run your own copy, see [docs/SETUP.md](docs/SETUP.md).

## Features

### Verse Lookup
- `/verse Evang 1:1` — look up a single verse or range (`Rom 7:11-13`)
- `/chapter Evangelicon 1` — read a full chapter with section headings and pagination
- `/context Evang 1:5` — see a verse with surrounding context
- `/search grace` — fuzzy search across all books, paginated with highlighted matches
- `/random` — random verse, optionally filtered by book
- `/image Evang 1:1` — generate a shareable styled verse image

### Study Tools
- `/sections Evangelicon` — list all section headings in a book or chapter
- `/bookinfo Romans` — chapter count, verse count, sections, source URL
- **Inline expansion** — type a reference in any message (e.g. "check out Evang 1:1") and the bot auto-replies with the verse
- **Related Passages** — `/verse` and `/random` include a button to find thematically similar verses

### Bookmarks & Collections
- `/bookmark Evang 1:1` — save a verse to your personal bookmarks
- `/bookmarks` — view all your saved verses
- `/unbookmark Evang 1:1` — remove a bookmark
- `/collection create "Favorites"` — create a named verse collection
- `/collection add "Favorites" Evang 1:1` — add verses to a collection
- `/collection view "Favorites"` — see all verses in a collection
- `/collection list` — list your collections
- React with :bookmark: on any verse embed to bookmark it

### Verse of the Day
- AI-selected daily passage (chosen by a GitHub Action, with history to avoid repeats)
- Styled verse image with parchment aesthetic
- Posted to configured channels as soon as the day's pick lands (GitHub's scheduler runs it late, often midday)
- `/verseoftheday` — view today's pick anytime

### Daily Quiz
- Multiplayer scripture quiz posted daily at 6:05 AM US Eastern
- Every server plays the same verse; each server sees only its own players on today's board
- Yesterday's quiz closes and reveals its answer when the new one posts
- Three rounds: guess the **book** → **chapter** → **verse**
- Verse shown as a styled image (no reference visible)
- Everyone answers independently with private responses
- Live leaderboard updates on the quiz embed
- Per-server all-time leaderboard with medals
- `/quiz` — personal quiz anytime (supports book/chapter filters)
- `/leaderboard` — view your server's all-time scores

### Reactions
- :bookmark: — bookmark the verse (saves persistently + DMs you)
- :arrow_right: — expand to show the next few verses
- :speech_balloon: — create a discussion thread for the passage

### Didascalicon & News
- A random Didascalicon (catechism) Q&A is posted daily at 6:10 AM US Eastern
- New articles on the Marcionite Church website are announced with an @everyone ping
- **Theology auto-answer** — questions in an enabled channel are matched to a Didascalicon answer via OpenRouter. It's the one feature that costs money per message, so only the bot owner can turn it on.

### Bot Replies
Turned on per server by the bot owner (`/setup bot-replies enabled:true`):
In a server with this on, any message that @mentions the bot or says "bot", "clanker" or "testamentum bot" is treated as being about this bot ("Testamentum" alone means the scripture).
- **"good bot"** and similar → the "I'm doing my part!" GIF (or "Doing my part 😇" where the bot can't attach files). **"bot is broken" / "clanker needs fixing"** → an apology that **pings the bot owner** for breakage reports (at most once per 10 minutes; insults like "bad bot" get the apology without a ping). Short messages are free phrase matches; "if the bot breaks…" isn't a report.
- **Anything else about the bot** → one OpenRouter call that recognises longer praise/complaints, points people to the right command, church website page, or Didascalicon Q&A (posted in full under the reply), or confirms how the bot works. A bare passing mention ("lol the bot") gets a one-line `/help` pointer, at most once per channel per 10 minutes. It never quotes scripture from memory, only links to church website pages, and doesn't hold conversations. If OpenRouter is unavailable, breakage reports still get the apology and ping.
- Limits: AI replies (bot replies and theology auto-answers together) are capped at 100 per person per day and 2,000 per server per day, resetting at midnight US Eastern; counts are kept in `llm_usage.json` so restarts don't reset them. Someone who hits a limit is told (always for an @mention, once a day otherwise). The bot owner has no personal limit. Every decision is logged as `[bot-replies] …` in the bot's logs.
- Models (OpenRouter): bot replies use `anthropic/claude-haiku-5.5` (`OPENROUTER_GUIDE_MODEL`). In a side-by-side on the bot's real prompts it matched Sonnet at about 1/20 the cost. Theology matching and the daily Verse of the Day pick use `anthropic/claude-sonnet-5.5` (`OPENROUTER_MODEL`), where Haiku missed clear matches.

### Using it in DMs
- Anyone who shares a server with the bot can DM it from its profile and use its slash commands there (and type references like `Evang 1:1`); nothing to install.
- To use its slash commands in DMs with other people, group chats, or servers it isn't in, add it to your personal apps: its profile → **Add App** → **Add to My Apps**. Only slash commands work there.

### Multi-Server Support
Members with **Manage Server** (and the bot owner) configure channels with `/setup` (server-only; not available in DMs or user installs). Discord shows `/setup` and the owner commands to anyone with Manage Messages, so a bot owner who is a moderator can see them; who may run them is checked when they're used.
- `/setup quiz #daily-quiz` — set the daily quiz channel
- `/setup votd #verse-of-the-day` — set the Verse of the Day channel
- `/setup didascalicon #channel` — daily Didascalicon Q&A
- `/setup announcements #channel` — website news with @everyone
- `/setup status` — view current config (and whether storage is persistent)
- `/setup disable quiz` — disable a feature

Bot-owner only (the Discord application's owner or team, plus any `OWNER_IDS`): `/setup theology`, `/setup theology-all`, `/setup bot-replies`, and the commands that act on every server at once — `/postquiz`, `/postdidascalicon`, `/checknews`, `/resetnews`, `/asktheology`. `/testannounce` posts only in the server it's run from.

## Books

**Evangelicon** — Unified Gospel (24 chapters, 1,188 verses)

**Apostolicon** — Galatians, 1 & 2 Corinthians, Romans, 1 & 2 Thessalonians, Laodiceans, Colossians, Philemon, Philippians

**Antilegicon** — Titus, 1 & 2 Timothy, Alexandrians

**Psalmicon** — 40 Psalms

**Homileticon** — Diognetus

**Synaxicon** — Ephesians, Magnesians, Trallians, Romans, Philadelphians, Smyrnaeans, Metrodorus (Ignatius)

### Book Abbreviations
`Evang`, `Gal`, `1Cor`, `2Cor`, `Rom`, `1Thess`, `2Thess`, `Laod`, `Col`, `Phm`, `Phil`, `Tit`, `1Tim`, `2Tim`, `Alex`, `Psalm`, `Diog`, `Mag`, `Tral`, `Smyrn`, `Metro`

## Self-Hosting

**[docs/SETUP.md](docs/SETUP.md)** is the full guide to running your own copy, written so anyone can take over the bot: the Discord application, Railway hosting, the GitHub jobs, OpenRouter, server setup, troubleshooting and every environment variable.

In short: fork the repo and enable its two scheduled Actions, create a Discord application (with the Message Content intent), deploy the fork on Railway with a volume at `/data`, set `DISCORD_TOKEN`, `DATA_DIR`, `OPENROUTER_API_KEY`, `VOTD_REPO` and `BOT_MAINTAINER`, and add `OPENROUTER_API_KEY` as a GitHub Actions secret.

## Architecture

```
testamentum-bot/
├── bot.py                 # Discord bot (slash commands, reactions, scheduled tasks)
├── scraper.py             # Web scraper for marcionitechurchofchrist.org
├── verse_image.py         # Verse image generator (Pillow)
├── verse_of_the_day.py    # VOTD script (OpenRouter pick + webhook post)
├── announcements.py       # Church website news feed reader
├── scrape_didascalicon.py # Didascalicon (catechism) scraper
├── data/
│   ├── testamentum.json   # Scraped verse database (committed)
│   ├── didascalicon.json  # Scraped catechism Q&As (committed)
│   └── votd*.json         # Verse of the Day + history (written by the Action)
├── assets/
│   ├── EBGaramond.ttf     # Serif font for verse images
│   └── EBGaramond-Italic.ttf
├── .github/workflows/
│   ├── scrape.yml         # Daily scraper
│   └── verse-of-the-day.yml  # Daily VOTD generation
├── requirements.txt
├── Procfile
└── railway.toml
```

Runtime data (persistent volume):
- `server_config.json` — per-server channel config
- `quiz_leaderboard.json` — per-server all-time scores
- `daily_quiz.json` — current quiz state
- `votd.json` — cached VOTD
- `users/<id>.json` — per-user bookmarks and collections
- `didascalicon_history.json`, `theology_cache.json`, `theology_replies.json` — Didascalicon rotation, LLM match cache, reply cooldowns
- `llm_usage.json` — today's AI-reply counts per person and per server
- `announcements_seen.json` — news articles already announced

## License

Verse data from [Marcionite Church of Christ](https://marcionitechurchofchrist.org/). Fonts are [EB Garamond](https://github.com/georgd/EB-Garamond) (SIL Open Font License).
