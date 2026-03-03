---
name: install-google-calendar
description: Install Google Calendar integration via MCP tools and google_api.py
version: 1.0.0
installs:
  - google-mcp-calendar
  - google-api-calendar
requires:
  bins: ["python3"]
  credentials:
    - ~/.config/personal-os/token.json
    - ~/.config/personal-os/credentials.json
---

# Install: Google Calendar Integration

## What This Installs

- Google MCP server with Calendar tools (list, create events)
- `google_api.py` fallback for calendar operations

## Steps

### 1. Configure Google MCP Server

The Google MCP server provides Calendar tools. Should already be configured from Gmail install.

### 2. Verify MCP Tools

Test these work:
- `mcp__google__calendar_list` — List calendars
- `mcp__google__calendar_events_list` — List events (supports timeMin/timeMax)
- `mcp__google__calendar_event_create` — Create events
- `mcp__google__calendar_events_list_all_accounts` — Cross-account events

### 3. Verify Script Fallback

```bash
SCRIPT="~/.claude/scripts/google_api.py"
python3 "$SCRIPT" calendar today
```

## MCP Tools Reference

```
mcp__google__calendar_list                    — List available calendars
mcp__google__calendar_events_list             — List events with date filtering
mcp__google__calendar_event_create            — Create a new event
mcp__google__calendar_events_list_all_accounts — Events across all accounts
```

## Script Commands

```bash
SCRIPT="~/.claude/scripts/google_api.py"
python3 "$SCRIPT" calendar today       # Today's events
python3 "$SCRIPT" calendar tomorrow    # Tomorrow's events
```

## Notes

- MCP tools are preferred over script for calendar operations
- Timezone handling depends on user's system settings
