---
name: install-supabase-mcp
description: Install Supabase MCP server for direct database access
version: 1.0.0
installs:
  - supabase-mcp-server
requires:
  bins: ["npx"]
  env: ["SUPABASE_ACCESS_TOKEN"]
---

# Install: Supabase MCP Server

## What This Installs

- Direct Supabase access via MCP tools — queries, inserts, schema inspection
- Replaces inline Python for contacts, health_vitals, workouts, pos_divisions, pos_state

## Steps

### 1. Get Access Token

Generate a Supabase access token at https://supabase.com/dashboard/account/tokens

### 2. Add MCP Server

Add to `~/.claude/settings.json` under `mcpServers`:
```json
"supabase": {
  "command": "npx",
  "args": ["@supabase/mcp-server-supabase", "--access-token", "<token>"]
}
```

### 3. Verify

Test querying a known table (e.g., `contacts`, `health_vitals`).

## Tables in Use

| Table | Purpose |
|-------|---------|
| `contacts` | Contact directory with context fields |
| `health_vitals` | Fitbit sync data |
| `health_workouts` | Tonal workout logs |
| `pos_divisions` | Personal-OS division registry |
| `pos_state` | State storage (writers-room weights, etc.) |
| `pos_sessions` | Session records |
| `articles` | News articles for scoring |
| `interests` | Interest weights for news scoring |
