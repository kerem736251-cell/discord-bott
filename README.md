# Quantix Discord Bot

A production-ready Discord bot starter for the Quantix community.

## Features
- Slash commands
- Ticket panel with buttons
- Welcome messages
- Moderation: clear, kick, ban, timeout
- Announcements
- Giveaways
- User/server info
- Customer verification (local demo codes + optional website API hook)
- Automatic roles after successful verification
- SQLite database for settings, verification codes, tickets and giveaways
- Docker/Railway-ready 24/7 deployment

## Local setup
1. Install Python 3.12+.
2. Create a Discord application and bot in the Discord Developer Portal.
3. Enable Server Members Intent.
4. Copy `.env.example` to `.env`.
5. Put your bot token in `.env`.
6. Run:
   ```bash
   pip install -r requirements.txt
   python bot.py
   ```

## Invite permissions/scopes
Use OAuth2 scopes `bot` and `applications.commands`. Give the bot permissions needed for moderation, role management, channels, messages and embeds. Keep the bot role above the customer/moderation roles it needs to manage.

## First commands
- `/setup` — saves important server IDs
- `/ticketpanel` — posts the ticket button panel
- `/createcode` — creates a one-use verification code
- `/verify` — customer enters a code and receives the configured role
- `/announce` — professional announcement embed
- `/giveaway` — start a giveaway

## 24/7 Railway deployment
1. Push this folder to a GitHub repo.
2. Create a Railway project from the repo.
3. Add `DISCORD_TOKEN` as an environment variable.
4. Deploy one replica with sleeping disabled.

The bot does not need a public web domain; it connects outbound to Discord.
