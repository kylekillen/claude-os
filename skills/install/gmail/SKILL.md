---
name: install-gmail
description: Install Gmail integration via MCP tools and google_api.py
version: 1.0.0
installs:
  - google-mcp-gmail
  - google-api-script
requires:
  bins: ["python3"]
  credentials:
    - ~/.config/personal-os/token.json
    - ~/.config/personal-os/credentials.json
---

# Install: Gmail Integration

## What This Installs

- Google MCP server with Gmail tools (list, read, search)
- `google_api.py` fallback for send, attachments, download

## Steps

### 1. Configure Google MCP Server

The Google MCP server provides Gmail tools. Add to `~/.claude/settings.json`:

```json
"google": {
  "command": "...",
  "env": { ... }
}
```

### 2. Set Up OAuth Credentials

Place Google OAuth credentials at:
- `~/.config/personal-os/credentials.json` — OAuth client config
- `~/.config/personal-os/token.json` — Refresh token

### 3. Verify MCP Tools

Test these MCP tools work:
- `mcp__google__gmail_messages_list` — List emails with query
- `mcp__google__gmail_message_get` — Read specific email by ID
- `mcp__google__gmail_messages_list_all_accounts` — Cross-account search

### 4. Verify Script Fallback

```bash
SCRIPT="~/.claude/scripts/google_api.py"
python3 "$SCRIPT" gmail search "newer_than:1d"
```

## MCP Tools Reference

```
mcp__google__gmail_messages_list     — List/search emails
mcp__google__gmail_message_get       — Read email by message_id
mcp__google__gmail_messages_list_all_accounts — Search all accounts
```

## Script Commands

```bash
SCRIPT="~/.claude/scripts/google_api.py"
python3 "$SCRIPT" gmail search "query"
python3 "$SCRIPT" gmail get <message_id>
python3 "$SCRIPT" gmail send "to@example.com" "Subject" "Body"
python3 "$SCRIPT" gmail attachments "has:attachment from:someone"
python3 "$SCRIPT" gmail download <msg_id> <attachment_id> /tmp/file.pdf
```

## Common Search Queries

| Looking For | Query |
|-------------|-------|
| From specific sender | `from:someone@example.com` |
| With subject keyword | `subject:keyword` |
| Recent attachments | `has:attachment newer_than:30d` |
| Date range | `after:2025/01/01 before:2025/02/01` |

## Rules

1. Use MCP tools for reading; use script for sending
2. Large attachments → download then use `/large-file-processing`
3. Confirm recipient and subject before sending
