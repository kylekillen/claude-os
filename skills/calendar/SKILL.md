---
name: calendar
description: Use this skill when the user asks to "check calendar", "what's on my calendar", "create event", "schedule meeting", "upcoming events", or mentions calendar operations.
---

# Calendar Operations

View and create events on Kyle's Google Calendar.

## MCP Tools

```
mcp__google__calendar_list - List all calendars
mcp__google__calendar_events_list - List events from a calendar
mcp__google__calendar_event_create - Create new event
mcp__google__calendar_events_list_all_accounts - Events across all accounts
```

## List Today's Events

```
mcp__google__calendar_events_list
  calendar_id: "primary"
  time_min: "[TODAY]T00:00:00Z"
  time_max: "[TODAY]T23:59:59Z"
```

Replace [TODAY] with the current date in YYYY-MM-DD format.

## Create an Event

```
mcp__google__calendar_event_create
  calendar_id: "primary"
  summary: "Event title"
  start_time: "YYYY-MM-DDTHH:MM:SS-07:00"
  end_time: "YYYY-MM-DDTHH:MM:SS-07:00"
```

Kyle is in Mountain Time (UTC-7 or UTC-6 depending on DST).

## Rules

1. Times must be in RFC3339 format
2. Default calendar is "primary"
3. When creating events, confirm details with Kyle before executing
4. Report calendar info in plain English, not raw JSON
