# SU Member Verifier

Discord membership verification for Swansea University societies.

Verifies Discord server members against the Students' Union membership list
and automatically assigns the "Member" role to verified users.

─────────────────────────────────────────────────────────

## Quick Start (Windows)

**Double-click `setup.bat`** — it installs everything automatically.

Then fill in your details and run:

```
.venv\Scripts\su-verify status    Check everything works
.venv\Scripts\su-verify scrape    Get the SU member list (opens browser)
.venv\Scripts\su-verify run       Verify members + assign Discord roles
```

## Quick Start (macOS / Linux)

```bash
bash setup.sh                     Install everything
.venv/bin/su-verify status        Check everything works
.venv/bin/su-verify scrape        Get the SU member list (opens browser)
.venv/bin/su-verify run           Verify members + assign Discord roles
```

─────────────────────────────────────────────────────────

## What You Need (10-minute setup, one-time)

### 1. Discord Bot

Go to https://discord.com/developers/applications:

1. **New Application** → name it "SU Verifier" → Create
2. **Bot** (left sidebar) → Reset Token → **copy the token**
3. Under **Privileged Gateway Intents** → enable **Server Members Intent** → Save
4. **OAuth2** → URL Generator → check **bot** → check **Manage Roles**
5. Open the generated URL → invite the bot to your server
6. In Discord: Settings → Advanced → **enable Developer Mode**
7. Right-click your server icon → **Copy ID** → this is your GUILD_ID
8. Right-click the "Member" role → **Copy ID** → this is your VERIFIED_ROLE_ID
9. Server Settings → Roles → drag "SU Verifier" **above** the Member role

### 2. Google Form

Create a form at https://forms.google.com with these fields:

| Question | Type |
|----------|------|
| Discord Username | Short answer |
| Student Email | Short answer |

Link it to a Google Sheet (Responses tab → Create Spreadsheet).

### 3. Configure .env

Open `.env` in Notepad and fill in:

```
DISCORD_BOT_TOKEN=paste_your_token_here
DISCORD_GUILD_ID=paste_your_guild_id_here
DISCORD_VERIFIED_ROLE_ID=paste_your_role_id_here
SU_SOCIETY_SLUG=your-society-name
```

─────────────────────────────────────────────────────────

## Weekly Workflow (2 minutes)

The committee member who runs this does these steps once a week:

### Step 1: Get the member list (30 seconds)

```bash
.venv\Scripts\su-verify scrape
```

A browser opens. Log into swansea-union.co.uk with your university account.
The script captures your session and saves the member list automatically.

### Step 2: Export form responses (15 seconds)

1. Open your Google Form → Responses tab
2. Click the green Sheets icon → opens the linked spreadsheet
3. File → Download → Comma Separated Values (.csv)
4. Save as `responses.csv` in the project folder

### Step 3: Verify and assign roles (30 seconds)

```bash
.venv\Scripts\su-verify run
```

This does three things:
- Reads all pending form submissions from `responses.csv`
- Cross-references each against the SU member list (by student email → ID)
- Assigns the Discord role to matched members

That's it. The terminal shows you exactly who was verified and who wasn't.

### Rest of the week

New submissions arrive throughout the week. You don't need to re-log into the SU
every time — the session cookie lasts about 24 hours:

```bash
.venv\Scripts\su-verify resume    Re-scrape without login
.venv\Scripts\su-verify run       Process new submissions
```

─────────────────────────────────────────────────────────

## How Verification Works

The tool matches form submissions against the SU member list:

| Priority | Method | How it works |
|----------|--------|--------------|
| 1 | Student ID | Extracts the number from `student_id@swansea.ac.uk` emails and matches against SU card numbers |
| 2 | Email | Direct email address match |
| 3 | Name | Last-resort fuzzy name match (low confidence, needs manual review) |

The most common case: a student submits `2447997@swansea.ac.uk` → the tool
extracts `2447997` → matches it against Chris Chobanov's SU card number →
assigns the Discord role. No names needed.

─────────────────────────────────────────────────────────

## Commands

| Command | What it does |
|---------|-------------|
| `su-verify status` | Check bot permissions and configuration |
| `su-verify scrape` | Open browser, log into SU, scrape member list |
| `su-verify verify` | Cross-reference CSV against member list (no roles) |
| `su-verify run` | Full pipeline: verify + assign Discord roles |
| `su-verify resume` | Re-scrape with saved cookies (skip login) |

Add `--dry-run` to preview without making changes:
```bash
.venv\Scripts\su-verify run --dry-run
```

─────────────────────────────────────────────────────────

## Troubleshooting

**"Bot is not in the server"**
→ Use the OAuth2 URL Generator in Discord Developer Portal to invite the bot.

**"Bot lacks permissions"**
→ The bot needs "Manage Roles" permission AND must be above the Member role
in Server Settings → Roles.

**"User not found" when assigning roles**
→ The Discord username must match exactly what's in the server. Ask the
member to check: click their name in Discord → Copy Username.

**"CSV missing required columns"**
→ Your Google Form question titles must be exactly "Discord Username" and
"Student Email". Edit the form questions to match these names.

**The scraper finds 0 members**
→ Run `su-verify scrape` again from scratch (not resume). Make sure you
complete the full login flow before closing the browser.

**The browser opens to a login page after scrape**
→ Your cookies expired. Run `su-verify scrape` (not resume) to re-login.

─────────────────────────────────────────────────────────

## Security

- No credentials are stored — the SU login is always manual via the browser
- Session cookies are saved locally in `su_cookies.json` (gitignored)
- The `.env` file contains your Discord bot token (gitignored)
- No data is sent to any third-party service
- The tool runs entirely on one committee member's computer

─────────────────────────────────────────────────────────

## Requirements

The setup script installs everything automatically. You just need:

- **Windows 10/11**, macOS, or Linux
- **Python 3.10+** (setup.bat will tell you if it's missing)
- **Discord server admin access** (to invite the bot)
- **SU committee membership** (to access the member list)

No Google Cloud billing. No server. No monthly fees.

─────────────────────────────────────────────────────────

## License

MIT
