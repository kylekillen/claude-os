---
name: install-mem0-memory
description: Install Mem0-style memory pipeline with FTS5+semantic search, attention decay, and entity extraction
version: 1.0.0
installs:
  - mem0-processor
  - query-context-hook
  - hybrid-search
  - attention-decay
  - memory-consolidation
  - entity-extraction
requires:
  bins: ["python3"]
  env: ["ANTHROPIC_API_KEY"]
  packages: ["numpy", "sentence-transformers"]
---

# Install: Mem0 Memory System

## What This Installs

A two-pass LLM-powered memory pipeline that extracts semantic knowledge from conversations and stores it in a dedicated `memories` table (separate from raw `observations`).

**Components:**
- `mem0-processor.py` — CRUD for memories table, FTS5+semantic search, CLI
- `query-context.py` — UserPromptSubmit hook that searches memories+observations and injects context
- `hybrid-search.py` — FTS5 keyword + MiniLM 384-dim semantic vector search
- `attention-decay.py` — Exponential decay on observation scores with type-based half-lives
- `memory-consolidate.py` — Merges low-score session clusters
- `extract-entities.py` — Entity relationship extraction
- `extract-patterns.py` — Pattern extraction from sessions
- `sync-memories-to-md.py` — Writes memories table to MEMORY.md
- `observe-tool-use.py` — PostToolUse hook, writes observations to SQLite
- `per-turn-memory.py` — Per-turn memory capture hook

## Steps

### 1. Create Python venv

```bash
python3.13 -m venv ~/.claude-mem/venv
~/.claude-mem/venv/bin/pip install numpy sentence-transformers
```

Required because system Python 3.14 lacks numpy/sentence-transformers.

### 2. Create Database

```bash
python3 ~/.claude/scripts/mem0-processor.py --stats
```

This initializes `~/.claude-mem/claude-mem.db` with tables:
- `observations` — raw tool events (PostToolUse hook)
- `memories` — clean knowledge facts (Mem0 pipeline)
- `entities`, `entity_relationships` — knowledge graph
- FTS5 virtual tables for keyword search
- `embedding` BLOB column for semantic vectors

### 3. Install Scripts

All scripts go in `~/.claude/scripts/`:
- `mem0-processor.py` — `--list`, `--stats`, `--search "query"`, `--embed-all`
- `query-context.py` — Hook script, searches memories first then observations
- `hybrid-search.py` — `--query "text" --top 15 --mode hybrid|keyword|semantic`
- `attention-decay.py` — Run on Stop hook
- `memory-consolidate.py` — `--execute` to merge clusters
- `extract-entities.py`, `extract-patterns.py` — Entity/pattern extraction
- `sync-memories-to-md.py` — Regenerates MEMORY.md from memories table

### 4. Install Hooks

All hooks go in `~/.claude/hooks/`:
- `observe-tool-use.py` — PostToolUse, matcher `""` (empty string, NOT `*`)
- `per-turn-memory.py` — UserPromptSubmit, 60s timeout

### 5. Configure settings.local.json

Add hooks to `~/.claude/settings.local.json`:

**UserPromptSubmit:**
- `query-context.py` (5s timeout) — injects relevant context
- `per-turn-memory.py` (60s timeout) — captures memories

**PostToolUse:**
- `observe-tool-use.py` (10s timeout, matcher `""`)

**Stop pipeline (in order):**
1. `memory-update.py`
2. `attention-decay.py`
3. `memory-consolidate.py --execute`
4. `extract-entities.py`
5. `extract-patterns.py`
6. `hybrid-search.py --embed-new` (via venv python)
7. `mem0-processor.py --embed-all` (via venv python)
8. `sync-memories-to-md.py`

### 6. Embed Existing Observations

```bash
~/.claude-mem/venv/bin/python ~/.claude/scripts/hybrid-search.py --embed-new
~/.claude-mem/venv/bin/python ~/.claude/scripts/mem0-processor.py --embed-all
```

### 7. Verify

```bash
python3 ~/.claude/scripts/mem0-processor.py --stats
python3 ~/.claude/scripts/mem0-processor.py --list
python3 ~/.claude/scripts/hybrid-search.py --query "test" --top 3
```

## Key Architecture Notes

- **DO NOT dispatch background subagents for memory processing** — caused zombie processes
- Memory storage is fully automated by Stop hook calling Anthropic Haiku API
- PostToolUse matcher MUST be `""` (empty string), NOT `"*"` — `*` is invalid regex
- The plugin at `~/.claude/plugins/claude-mem/plugin/hooks/hooks.json` may re-enable old hooks on update — check after plugin updates
- DB epochs are MILLISECONDS (not seconds)

## Usage

```bash
# List all memories
python3 ~/.claude/scripts/mem0-processor.py --list

# Search memories
python3 ~/.claude/scripts/mem0-processor.py --search "kalshi trading"

# Stats
python3 ~/.claude/scripts/mem0-processor.py --stats

# Hybrid search observations
python3 ~/.claude/scripts/hybrid-search.py --query "your query" --top 15
```
