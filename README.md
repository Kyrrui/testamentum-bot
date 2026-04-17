# Testamentum Bot

A Discord bot for the Marcionite Testamentum — 24 books, 4,300+ verses. Look up verses, search scripture, take quizzes, and more.

[Invite to your server](https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&permissions=277025467456&scope=bot+applications.commands)

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
- AI-selected daily passage with a contextual reflection
- Searches the web for today's holidays and news to connect the passage to current events
- Styled verse image with parchment aesthetic
- Posts automatically to configured channels at 6:00 AM EST
- `/verseoftheday` — view today's pick anytime

### Daily Quiz
- Multiplayer scripture quiz posted daily at 6:05 AM EST
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

### Multi-Server Support
Admins configure channels with `/setup`:
- `/setup quiz #daily-quiz` — set the daily quiz channel
- `/setup votd #verse-of-the-day` — set the Verse of the Day channel
- `/setup status` — view current config
- `/setup disable quiz` — disable a feature

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

### Requirements
- Python 3.12+
- Discord bot token
- Railway account (or any hosting platform)
- Anthropic API key (for Verse of the Day)

### Setup

1. Clone the repo
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create `.env`:
   ```
   DISCORD_TOKEN=your_bot_token
   ```
4. Scrape the verse database:
   ```
   python scraper.py
   ```
5. Run the bot:
   ```
   python bot.py
   ```

### Railway Deployment

1. Connect the GitHub repo to Railway
2. Set environment variables:
   - `DISCORD_TOKEN` — your bot token
   - `DATA_DIR` — `/data` (with a persistent volume mounted there)
3. Add a persistent volume mounted at `/data`
4. Deploy

### GitHub Actions (Verse of the Day)

Add these as GitHub repository secrets:
- `ANTHROPIC_API_KEY` — for AI verse selection
- `DISCORD_WEBHOOK_URL` — webhook for your VOTD channel

The VOTD runs daily at 6:00 AM EST via GitHub Actions. The bot fetches the result from GitHub and reposts to all configured servers.

### Daily Scraper

A GitHub Action runs daily to re-scrape the Testamentum website. It validates the data before overwriting to prevent corruption if the site is down.

## Architecture

```
testamentum-bot/
├── bot.py                 # Discord bot (slash commands, reactions, scheduled tasks)
├── scraper.py             # Web scraper for marcionitechurchofchrist.org
├── verse_image.py         # Verse image generator (Pillow)
├── verse_of_the_day.py    # VOTD script (Claude API + web search)
├── daily_quiz.py          # Quiz generator (legacy, now handled by bot)
├── data/
│   └── testamentum.json   # Scraped verse database (committed)
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

## License

Verse data from [Marcionite Church of Christ](https://marcionitechurchofchrist.org/). Fonts are [EB Garamond](https://github.com/georgd/EB-Garamond) (SIL Open Font License).
