# Aans FootBot ⚽

Discord bot that brings FotMob live scores, fixtures and goal alerts to your server.

**Features**
- Slash commands (`/follow_team`, `/follow_league`, `/setchannel`, `/live`, `/fixtures`, `/list`, ...)
- Follow teams **and** leagues/competitions
- Dedicated notification channel
- Background poller (~15s default) for near real-time score/goal updates (typically 10-30s off real life)
- Simple JSON storage per guild

> **Disclaimer**: Uses FotMob’s unofficial internal API. It can break without notice. Not affiliated with FotMob. Use responsibly and respect rate limits.

## Setup

1. Create a Discord Application + Bot at https://discord.com/developers/applications
2. Enable **Server Members Intent** if you want (not strictly required). Copy the Bot Token.
3. Invite the bot with scopes: `bot` + `applications.commands`. Permissions: Send Messages, Embed Links, View Channels, Use Slash Commands.
4. Clone this repo, create `.env` from `.env.example`, put your token.
5. ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   python bot.py
