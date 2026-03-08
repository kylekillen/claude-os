---
name: install-discord
description: Install Discord as an additional communication channel
version: 1.0.0
installs:
  - discord-channel
requires:
  bins: ["npm"]
  env: ["DISCORD_BOT_TOKEN"]
---

# Install: Discord Channel

## What This Installs

- Discord bot for sending/receiving messages
- Additional communication channel alongside Telegram
- Main channels respond to all messages; others require @mentions

## Steps

### 1. Create Discord Bot

1. Go to Discord Developer Portal (discord.com/developers)
2. Create new application → Bot
3. Enable "Message Content Intent" under Privileged Gateway Intents
4. Generate bot token
5. Invite to your server with message read/write permissions

### 2. Add MCP Server or Script

Add to `~/.claude/settings.json` under `mcpServers`:
```json
"discord": {
  "command": "npx",
  "args": ["discord-mcp-server"],
  "env": { "DISCORD_BOT_TOKEN": "<token>" }
}
```

### 3. Verify

Send a test message to the configured Discord channel.
