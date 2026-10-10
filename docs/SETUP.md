# Running Testamentum Bot yourself

This guide is for anyone taking over Testamentum Bot. If the original maintainer (Kyrrui) can't run it anymore, you can follow it from scratch and end up with a fully working copy of the bot. You don't need to know the code. Budget about an hour.

## How the bot is put together

Four pieces work together. You'll set each one up below.

| Piece | What it does | Cost |
|---|---|---|
| **Discord application** | The bot's identity: its name, avatar and login token, and who counts as its owner. | Free |
| **Railway** (hosting) | Runs `bot.py` around the clock and keeps its settings on a disk (a "volume"). Redeploys automatically whenever the GitHub repo changes. | Hobby plan, about $5/month |
| **GitHub repo + Actions** | Holds the code and the scripture data. Two scheduled jobs run there daily. One re-scrapes the Testamentum and Didascalicon from the church website. The other picks the Verse of the Day. Both commit their results back to the repo. | Free |
| **OpenRouter** (AI) | The AI model behind the Verse of the Day pick, the theology auto-answer, and the bot's replies when someone mentions it. Everything else works without it. | Pay as you go, usually cents a day |

Everything the bot posts as scripture or catechism comes word for word from its data files. The AI only chooses and points; it never writes verse text.

## Step 0: Take over, or start fresh?

If the previous maintainer can still hand things over, take over. It's the easiest path, and the bot keeps its name, its servers, and every server's settings, bookmarks and leaderboards. Do all five of these:

1. **Discord application.** Discord can't give an app to a person, only to a Developer Team. The old maintainer:
   - creates a team (Developer Portal → **Teams** → New Team) and invites you as an **Admin**,
   - moves the app into it (the app's General Information → **Transfer App to Team**),
   - then makes you the team's **owner**.

   The last part matters. When someone says the bot is broken, it pings the team owner. Its replies also name the team owner as the maintainer, whatever `BOT_MAINTAINER` says. Afterwards, reset the bot's token (Bot → **Reset Token**), since the old maintainer has seen the current one.
2. **GitHub.** They transfer the repository to you (repo Settings → General → Danger Zone → **Transfer ownership**), and you accept from GitHub's email. If you already have a repo or fork named `testamentum-bot`, delete or rename it first, or GitHub refuses the transfer. Secrets and settings move with the repo. Then, in the **Actions** tab, open **Daily Scrape**, click **⋯** → **Disable workflow**, and then click **Enable workflow**. Do the same for **Verse of the Day**. This moves GitHub's failure emails from them to you.
3. **Railway.** Being invited to the project gives you access, but the bill stays on their account, and the bot stops when their plan does. Have them transfer the project to your own Railway account or workspace. The volume, which holds every server's settings, moves with it. Then reconnect the service to the moved repo: service → **Settings** → **Source** → `your-github-name/testamentum-bot`. Let Railway's GitHub app access your account when it asks.
4. **OpenRouter.** The AI key stored in GitHub and Railway is theirs and spends their credit. Make your own key (Step 3), replace `OPENROUTER_API_KEY` in both places (Step 4.1, and the Railway service's Variables tab), and ask them to delete the old key.
5. **Railway variables.** In the service's **Variables** tab, set these:
   - `DISCORD_TOKEN`: the new token from item 1
   - `OPENROUTER_API_KEY`: your key
   - `VOTD_REPO`: `your-github-name/testamentum-bot`
   - `BOT_MAINTAINER`: your Discord username

   Deploy, and check the startup log as in [Step 5.4](#step-5-deploy-on-railway). Then continue at [Step 6](#step-6-configure-it-in-your-server).

If you're starting fresh, follow every step from Step 1. The bot will be a new Discord application, so it has to be re-added to servers, and their `/setup` settings, bookmarks and quiz leaderboards start empty. If you can get copies of the old files, see [Moving data from the old bot](#moving-data-from-the-old-bot).

## Step 1: Copy the code

1. Sign in to GitHub and **fork** the repository (the Fork button at the top right of the repo page). Keep it **public**, keep the name `testamentum-bot`, and keep the branch named `main`. The bot downloads the Verse of the Day from `raw.githubusercontent.com/<your fork>/main/data/votd.json` without logging in. That only works if the repo is public and the branch is `main`.
2. In your fork, open the **Actions** tab and click **I understand my workflows, go ahead and enable them**.
3. GitHub also keeps scheduled jobs switched off in forks. Click **Daily Scrape** in the left sidebar. If it says scheduled workflows are disabled, click **Enable workflow**. Do the same for **Verse of the Day**. Until both are enabled, the daily jobs don't run and Step 4's **Run workflow** button doesn't appear.

Your copy's address is `your-github-name/testamentum-bot`. You'll need it in Step 5.

## Step 2: Create the Discord application

Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**. Name it, then:

1. **General Information:** set the description, and copy the **Application ID** for the invite link below.
2. **Bot tab:**
   - Set the **Username** and **Icon**. They're the name and avatar people see in chat.
   - Click **Reset Token**, copy the token and keep it secret. This is `DISCORD_TOKEN`.
   - Under **Privileged Gateway Intents**, turn on **Message Content Intent** and save. The bot asks Discord for this when it logs in, so if it's off the bot can't connect at all. It stays offline, and the log says `Message Content Intent is off`.
   - Turn on **Public Bot** so other servers can add it. To keep the bot private, leave this off and set Install Link to **None** in the next step, because Discord won't save a Discord Provided Link for a private app. You then add the bot to servers with the invite link below.
3. **Installation tab:**
   - Under Installation Contexts, tick both **User Install** and **Guild Install**.
   - Set Install Link to **Discord Provided Link**, or to **None** for a private bot.
   - Under Default Install Settings → **Guild Install**, add the scopes `applications.commands` and `bot`. Add these permissions: View Channels, Send Messages, Send Messages in Threads, Create Public Threads, Embed Links, Attach Files, Read Message History, Add Reactions, and Mention Everyone (needed for the website news @everyone pings).
   - Save.

An unverified bot can join at most 100 servers. Discord lets you apply for verification once the bot is in 75, and a verified bot needs Discord's separate approval to keep Message Content Intent.

The account that creates the application is the bot's **owner**. Only the owner can run the commands that cost money or affect every server, such as turning on AI replies and theology auto-answer, `/postquiz` and `/checknews`. If the app belongs to a Developer Team, the team's admins and developers count as owners too. You can add other people as owners with `OWNER_IDS` (see the [variable reference](#environment-variables)). To find someone's user ID, turn on Discord Settings → Advanced → **Developer Mode**, then right-click their name → **Copy User ID**.

To add the bot to a server, use this link (replace `YOUR_APP_ID`), or open the bot's profile → **Add App** → **Add to Server**:

```
https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&permissions=309237894208&integration_type=0&scope=bot+applications.commands
```

## Step 3: Get an OpenRouter key

1. Create an account at [openrouter.ai](https://openrouter.ai) and add some credit. $5 lasts a long time at this bot's usage. Credit is prepaid and the AI features stop when it runs out, so turn on auto top-up (Credits page) or check the balance now and then.
2. Create an API key (Keys page). **Set a credit limit on the key**, so a bug or a busy day can't run up a large bill.
3. Keep the key handy. It goes in two places: GitHub (Step 4, for the Verse of the Day) and Railway (Step 5, for theology and bot replies). You can make a separate key for each place, with its own limit, if you'd like to be able to revoke one without the other.

The bot works without a key: lookups, quizzes, daily posts and canned replies all run. Only the AI features switch off, and the Verse of the Day is then picked at random.

## Step 4: Set up the GitHub jobs

In your fork:

1. **Settings → Secrets and variables → Actions → New repository secret:** name `OPENROUTER_API_KEY`, value your key.
2. **Actions tab:** open **Daily Scrape** and click **Run workflow**, then do the same for **Verse of the Day**. Both should finish green within a minute or two. Verse of the Day leaves a commit called "chore: update verse of the day". Daily Scrape only commits when the website has changed.

After that, the jobs run every day:

- **Daily Scrape** (cron 06:00 UTC) re-scrapes the Testamentum and Didascalicon from marcionitechurchofchrist.org. It checks the result first: all books present, no gaps in chapters, enough verses. If anything looks broken it refuses to commit, so a website outage can't wipe the data.
- **Verse of the Day** (cron 10:00 UTC) has the AI pick a passage and commits `data/votd.json`. The bot reads that file from GitHub and posts it.

GitHub often starts scheduled jobs hours late; the Verse of the Day usually lands around midday US Eastern. That's normal. On very busy days GitHub can skip a scheduled run entirely. If the Verse of the Day hasn't appeared by evening, run it by hand (Actions → Verse of the Day → **Run workflow**). GitHub also switches off scheduled jobs in a repo that has had no activity for 60 days. If the daily posts stop, check the Actions tab and re-enable them.

## Step 5: Deploy on Railway

1. Sign in at [railway.com](https://railway.com) with GitHub. Create a **New Project → Deploy from GitHub repo** and choose your fork. If your fork isn't listed, click **Configure GitHub App** and give Railway access to it. Railway reads `railway.toml` and runs `python bot.py`. The first start crashes because there's no token yet; that's expected.
2. **Add a volume:** right-click the project canvas (or press Ctrl/Cmd+K) → **Volume**, attach it to the bot's service, and set the mount path to `/data`. This is where server settings, bookmarks, quiz scores and usage counts live. Without it they're wiped on every redeploy, and redeploys happen at least once a day: every commit to `main` triggers one, including the daily jobs' commits.
3. In the service's **Variables** tab, add:

   | Variable | Value |
   |---|---|
   | `DISCORD_TOKEN` | the bot token from Step 2 |
   | `DATA_DIR` | `/data` |
   | `OPENROUTER_API_KEY` | your key from Step 3 |
   | `VOTD_REPO` | `your-github-name/testamentum-bot` (your fork) |
   | `BOT_MAINTAINER` | your Discord username, without the @ |

   The [full list](#environment-variables) has optional extras.
4. Railway holds the volume and variable changes until you apply them. Click **Deploy** on the banner at the top of the canvas that lists them. If the service still shows Crashed, use Deployments → **⋮** → **Redeploy**. Then open the deployment's logs. A healthy start looks like this:

   ```
   Bot is ready! Logged in as YourBot#1234
   Storage: `/data` (persistent volume)
   OpenRouter: configured
   Installs: Public Bot on; server installs on; user installs on
   ```

   - If `Storage:` starts with ⚠️, the volume isn't mounted at `DATA_DIR`. Fix that before going further.
   - If the `Installs:` line shows `OFF` on a bot you meant to be public, the Step 2 settings weren't saved. The bot only reads them at login, so fix them and then restart the deployment (Deployments → **⋮** → **Restart**). On a bot you deliberately kept private, `Public Bot OFF; server installs OFF` is expected.

## Step 6: Configure it in your server

Invite the bot (Step 2's link), then in your server run:

| Command | What it sets |
|---|---|
| `/setup quiz #channel` | the daily scripture quiz (6:05 AM US Eastern) |
| `/setup votd #channel` | the Verse of the Day (posted when the day's pick lands) |
| `/setup didascalicon #channel` | the daily Didascalicon Q&A (6:10 AM US Eastern) |
| `/setup announcements #channel` | website news with an @everyone ping (the bot needs Mention Everyone there) |
| `/setup bot-replies enabled:true` | **Owner only.** AI replies when people mention the bot, plus the "good bot" / "bot is broken" replies |
| `/setup theology #channel` or `/setup theology-all enabled:true` | **Owner only.** Theology questions answered from the Didascalicon |
| `/setup status` | shows all of the above, plus whether storage is persistent |

Anyone with Manage Messages can see `/setup`, but only members with Manage Server and the bot's owner can use it. If you don't see it, reload Discord: Ctrl+R, or Cmd+R on a Mac; on a phone, close and reopen the app. The owner-only commands refuse everyone else, so other servers can use the bot without running up AI costs. Those servers can still switch the features off with `/setup disable`.

## Step 7: Check it works

- [ ] `/verse Evang 1:1` replies with the verse.
- [ ] Typing `Evang 1:1` in a message gets an automatic reply. If not, the bot can't post in that channel. It needs View Channels, Send Messages, Embed Links and Read Message History there.
- [ ] `/setup status` lists your channels and says storage is persistent.
- [ ] New bot only: `/postquiz` (owner) posts a quiz in your quiz channel. On a bot you took over, skip this. It re-rolls today's quiz for **every** server and closes the one people are playing.
- [ ] With bot replies on, `good bot` gets "Doing my part 😇", and `@YourBot any verses about forgiveness?` gets verses. The bot offers verses when a message asks for a verse, scripture, a passage, a psalm or the bible, or asks what scripture says or teaches about something.
- [ ] The next day, the quiz and Didascalicon post in the morning and the Verse of the Day around midday US Eastern.

## Day to day

**Updating the bot.** Every push to `main` redeploys it on Railway. The daily jobs commit to `main` every day, so run `git pull --rebase` before you push. Test changes locally first (see [Running it on your computer](#running-it-on-your-computer)).

**Logs.** Railway's deployment logs show what the bot is doing. Useful prefixes:

| Prefix | Meaning |
|---|---|
| `[bot-replies]` | each decision about a message that mentioned the bot |
| `[theology]` | theology auto-answer matching |
| `[llm]` | AI usage limits being hit, or a reply cut short |
| `[announcements]` | the website news feed |

**Costs and limits.** AI replies (mentions plus theology answers) are capped at 100 per person and 2,000 per server per day. The caps reset at midnight US Eastern, and the owner has no personal cap. Mention replies run on Claude Haiku 5.5 and cost about 0.1¢ each. Theology matching and the Verse of the Day use Claude Sonnet 5.5 at about 1¢ each, and a repeated theology question is answered from cache for free. To change the caps, edit `LLM_CALLS_PER_USER_PER_DAY` and `LLM_CALLS_PER_SERVER_PER_DAY` near the top of `bot.py`.

**Changing models.** On Railway, set `OPENROUTER_GUIDE_MODEL` for mention replies or `OPENROUTER_MODEL` for theology. The Verse of the Day reads a separate GitHub Actions *variable*, also called `OPENROUTER_MODEL` (Settings → Secrets and variables → Actions → **Variables** tab). If OpenRouter retires a model, change it in both places.

**Library updates.** Last known working (October 2026): Python 3.12 and discord.py 2.7.1. `requirements.txt` doesn't pin exact versions, so each Railway build installs the newest releases. If a deploy breaks right after a library release, pin the last working version in `requirements.txt` (for example `discord.py==2.7.1`).

**The website changed.** If the church site restructures, the Daily Scrape job fails its checks and keeps the last good data, so the bot keeps working. The job's log says what failed. The parsing lives in `scraper.py` and `scrape_didascalicon.py`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bot is offline | Check the Railway logs. `DISCORD_TOKEN not set`: add the variable. `Message Content Intent is off`: turn it on (Step 2). A login error: reset the token in the Developer Portal and update the variable. Railway stops restarting after 3 crashes, so after fixing the cause use Deployments → **⋮** → **Redeploy**. |
| Slash commands work, typed references don't | Either the bot isn't in this server, or it lacks permissions in that channel. Commands added with **Add to My Apps** work anywhere, but typed references only work where the bot itself was added. The channel needs View Channels, Send Messages, Embed Links and Read Message History for the bot; the log says `Inline expansion failed in ...`. |
| `/setup` missing | You need Manage Messages to see it. Also try reloading Discord. |
| Settings forgotten after a deploy | No volume at `DATA_DIR`. `/setup status` and the startup log show this. |
| No Verse of the Day | One of: the Verse of the Day job isn't running (check the Actions tab); `VOTD_REPO` points somewhere else; the repo isn't public or its branch isn't `main` (log: `Failed to fetch VOTD from GitHub`); or `/setup votd` isn't set. |
| Bot replies or theology never answer | One of: the owner hasn't run `/setup bot-replies` / `/setup theology`; the startup log says `OpenRouter: OPENROUTER_API_KEY NOT SET`; or the key is out of credit. |
| AI replies stopped, and logs show `Guide LLM call failed` or `Theology match LLM call failed` with a 404 or 400 | The OpenRouter model was retired or renamed. Pick a current one at [openrouter.ai/models](https://openrouter.ai/models) and set it (see Changing models). A 402 means the key is out of credit. |
| "Only the bot owner can use this command" | You aren't the Discord application's owner. Use the account that created it, add your user ID to `OWNER_IDS`, or join the app's Developer Team as an Admin or Developer. |
| The bot pings or names the old maintainer | The app's team is still owned by them. Have them make you the team owner (Step 0). |
| A daily job's push is rejected (403) | A branch protection rule or ruleset on `main` blocks direct pushes (Settings → Branches / Rules). Let GitHub Actions bypass it, or remove it. |
| Railway build fails and mentions the builder | Railway is replacing Nixpacks. Change `builder = "NIXPACKS"` in `railway.toml` to `"RAILPACK"`. |

## Moving data from the old bot

The bot's state is a handful of JSON files in its volume (`DATA_DIR`):

| File | Holds |
|---|---|
| `server_config.json` | each server's `/setup` channels and switches |
| `users/<id>.json` | each person's bookmarks and collections |
| `quiz_leaderboard.json` | all-time quiz scores per server |
| `daily_quiz.json`, `quiz_history.json` | today's quiz and past quiz verses |
| `didascalicon_history.json` | which Q&As were already posted |
| `theology_cache.json`, `theology_replies.json` | theology match cache and reply cooldowns |
| `announcements_seen.json` | news articles already announced |
| `llm_usage.json` | today's AI usage counts |
| `votd.json` | cached Verse of the Day |

In a handover, transferring the Railway project moves these files with it (Step 0). Otherwise, copy them by hand through the Railway CLI:

1. Install the [Railway CLI](https://docs.railway.com/guides/cli), run `railway login`, then run `railway link` in the repo folder and pick the project.
2. Run `railway ssh` to get a shell inside the running bot. The files are under `/data`.
3. To save a file, `cat` it and copy the text out. To restore one, run `cat > /data/<name>.json`, paste the text, and press Ctrl+D.
4. Restart the deployment afterwards.

Never commit these files to GitHub: the repo is public and they hold people's data. Channel IDs in `server_config.json` only matter for servers your new bot is in. Without the files, just run `/setup` again in each server.

## Running it on your computer

You need Python 3.10 or newer (the bot and the GitHub jobs are tested on 3.12). Then:

```bash
pip install -r requirements.txt
```

Use a separate test bot, not the live one. Give it its own Step 2 setup, including Message Content Intent. Create a `.env` file in the repo folder with its token and your fork:

```
DISCORD_TOKEN=your-test-bot-token
VOTD_REPO=your-github-name/testamentum-bot
```

Then run:

```bash
python bot.py
```

Without `DATA_DIR`, runtime files go in `data/`. They're all git-ignored except `data/votd.json`, which the bot overwrites with the copy from `VOTD_REPO`. Before you commit, undo that with:

```bash
git checkout data/votd.json
```

## Environment variables

| Variable | Needed | Purpose |
|---|---|---|
| `DISCORD_TOKEN` | yes | the bot's login token |
| `DATA_DIR` | yes on Railway | where runtime files live; point it at the volume (`/data`) |
| `OPENROUTER_API_KEY` | for AI features | theology auto-answer and bot replies (and, as a GitHub secret, the Verse of the Day pick) |
| `VOTD_REPO` | yes, unless it's the original repo | `owner/repo` whose `data/votd.json` the bot posts; defaults to `Kyrrui/testamentum-bot` |
| `BOT_MAINTAINER` | recommended | your Discord username, as the AI writes it in replies (the bot turns it into a mention of the app's owner, or its team's owner); defaults to `kyrrui` |
| `OWNER_IDS` | optional | extra Discord user IDs (comma-separated, digits only) treated as bot owners |
| `OPENROUTER_GUIDE_MODEL` | optional | model for mention replies; default `anthropic/claude-haiku-5.5` |
| `OPENROUTER_MODEL` | optional | model for theology; default `anthropic/claude-sonnet-5.5`. The Verse of the Day reads a GitHub Actions variable of the same name. |
| `QUIZ_CHANNEL_ID` | legacy | an extra quiz channel; prefer `/setup quiz` |
| `DISCORD_WEBHOOK_URL` | not used | `verse_of_the_day.py` only: also post the card to a webhook. The workflow doesn't set it; the bot posts the verse itself. |
