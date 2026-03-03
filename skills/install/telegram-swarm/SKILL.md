---
name: install-telegram-swarm
description: Install multi-bot Telegram swarm for distinct agent personalities
version: 1.0.0
installs:
  - telegram-swarm-bots
requires:
  installed: ["telegram-mcp"]
---

# Install: Telegram Swarm

## What This Installs

- Pool of 3-5 additional Telegram bots that appear as distinct named agents in a group chat
- Each subagent (researcher, evaluator, writer) sends messages as its own bot identity
- Round-robin assignment with bot name customization

## Steps

### 1. Create Additional Bots

Via BotFather in Telegram, create 3-5 additional bots:
- `@YourResearchBot` — for research agent outputs
- `@YourWriterBot` — for writing drafts and content
- `@YourTraderBot` — for trading signals and position updates

### 2. Configure Bot Pool

Store tokens in `~/.config/personal-os/telegram-swarm.json`:
```json
{
  "bots": [
    {"name": "Researcher", "token": "..."},
    {"name": "Writer", "token": "..."},
    {"name": "Trader", "token": "..."}
  ],
  "group_chat_id": "<group-id>"
}
```

### 3. Create Dispatch Script

Write `~/.claude/scripts/telegram-swarm.py` that routes messages to the appropriate bot based on context.

### 4. Verify

Send a test message from each bot to the group chat.

## Usage

When dispatching background agents (research, writing, trading), route their output through the appropriate swarm bot so Kyle sees distinct identities in the Telegram group.
