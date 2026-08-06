# SU Member Verifier — Swansea Esports

One command per week. Double-click to run.

---

## Install

**Download `su-verify`** from the [Releases page](https://github.com/KRUZZZZY/su-member-verifier/releases).

Double-click it. It installs everything automatically on first run.

---

## One-time setup (30 seconds)

The first run creates a `.env` file. Open it in Notepad and fill in **one thing**:

```
DISCORD_BOT_TOKEN=paste_your_token_here
```

Everything else is pre-filled:
- Google Sheets access (key-protected)
- Guild ID and role ID (Swansea Esports)
- SU member list path
- Form column names

You're done. Never touch the config again.

---

## Weekly workflow

```
su-verify run
```

That's it. One command. It:

1. Opens a browser → you log into swansea-union.co.uk
2. Scrapes the member list
3. Auto-fetches form responses
4. Matches students by ID
5. Assigns Discord roles
6. Deletes all data from your computer

---

## Commands

| Command | Does |
|---------|------|
| `su-verify run` | Everything: scrape + verify + assign + cleanup |
| `su-verify run --dry-run` | Preview without assigning roles |
| `su-verify status` | Check everything's working |

---

## Troubleshooting

**"User not found"** — Discord username doesn't match the form. Case-sensitive.

**Browser opens to login page** — complete the full login. It waits for you.

**Nothing happens** — you might need a bot token. Check your `.env` file.

---

No server. No fees. No data stored. Everything runs on your computer.
