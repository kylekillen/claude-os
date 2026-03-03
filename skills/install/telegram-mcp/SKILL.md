---
name: install-telegram-mcp
description: Install Telegram MCP server for remote communication with Kyle
version: 1.0.0
installs:
  - telegram-mcp-server
requires:
  bins: ["npm"]
  env: ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
---

# Install: Telegram Communication

## What This Installs

- Telegram MCP server (`mcptelegram`) for sending/receiving messages
- Remote communication capability for when Kyle is away from desktop

## Steps

### 1. Install Binary

```bash
npm install -g mcptelegram
```

Binary installs to `/opt/homebrew/bin/mcptelegram`.

### 2. Add MCP Server

Add to `~/.claude/settings.json` under `mcpServers`:

```json
"telegram": {
  "command": "mcptelegram",
  "env": {
    "TELEGRAM_BOT_TOKEN": "<bot-token>",
    "TELEGRAM_CHAT_ID": "<chat-id>"
  }
}
```

### 3. Test Connection

Send a test message using the MCP Telegram tool to verify connectivity.

### 4. Verify

Confirm Kyle receives the test message in Telegram.

## Usage

Use MCP Telegram tools to send messages, receive commands, and communicate remotely.
