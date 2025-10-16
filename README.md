
# Discord Guard Bot

Watchlist users or bots. If a listed account joins again, the bot removes any admin roles it can, then kicks them, and logs the action. It also detects when someone grants admin after join and enforces the same way. Prefix is per guild and saved to disk.

## Features
- Per guild changeable prefix, `!setprefix ?` for example
- Watchlist add, remove, list
- Toggle guard enable or disable
- Optional log channel for actions
- Admin gain detection on member update
- JSON persistence, no database needed
- Safety checks for role hierarchy and permissions

## Commands
Use your current prefix.
- `guard` shows current settings
- `guard enable` or `guard disable`
- `guard setlog #channel` set the log channel, run `guard setlog` with no channel to clear
- `guard add <mention or id>`
- `guard remove <mention or id>`
- `guard list`
- `setprefix <newprefix>`
- `status`
- `testkick @user` simulate enforcement for testing

You need Manage Server permission or be listed in `owner_ids` in `config.json`.

## Local run
1. `python -m venv .venv`
2. Activate the venv
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`, paste your token
5. `python bot.py`

## Notes
- Invite the bot with Manage Roles, Kick Members, Read Messages.
- The bot highest role must be above roles it should remove.
- Server owners cannot be kicked, and the bot will not try to act on itself.
