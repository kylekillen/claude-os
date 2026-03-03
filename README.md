# Claude OS

Persistent memory and context injection for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Claude OS gives Claude long-term memory that persists across sessions, so it remembers your preferences, past decisions, project context, and anything else worth keeping.

## How It Works

```
You talk to Claude ──→ Facts extracted by Haiku ──→ Stored in SQLite
                                                          │
Next session starts ──→ Relevant memories retrieved ──→ Injected as context
```

**Cost:** ~$0.01 per session (Haiku API calls for memory extraction).

## What Gets Installed

```
~/.claude/
├── hooks/                  # Hook scripts (HTTP server + memory extraction)
│   ├── http-server/        # Persistent server handling all hook events
│   ├── per-turn-memory.py  # Mem0-style two-pass fact extraction
│   └── pre-compact-*.py    # Pre-compaction memory capture
├── scripts/                # Memory pipeline (search, embeddings, decay)
├── skills/                 # 22+ portable skills (pdf, docx, research, etc.)
├── CLAUDE.md               # Your assistant's personality and instructions
└── settings.local.json     # Hook configuration

~/.claude-mem/
├── claude-mem.db           # SQLite database (FTS5 + vector embeddings)
├── venv/                   # Python environment (sentence-transformers)
├── logs/                   # Pipeline logs
└── backups/                # Transcript backups
```

## Install

### Prerequisites

- **Claude Code** — [Install guide](https://docs.anthropic.com/en/docs/claude-code/getting-started)
- **Python 3.10+** — `brew install python@3.13` or [python.org](https://python.org)
- **Anthropic API key** — [Get one here](https://console.anthropic.com/settings/keys)

### One Command

```bash
git clone https://github.com/YOUR_USERNAME/claude-os.git
cd claude-os
./install.sh
```

The installer will:
1. Ask you to name your AI assistant
2. Check prerequisites
3. Set up hooks, scripts, and skills
4. Create a Python venv with sentence-transformers
5. Initialize the memory database
6. Start the hooks server as a launchd daemon (macOS)
7. Verify everything works

## Memory System

### Mem0-Style Two-Pass Pipeline

Every conversation turn:
1. **Extract** — Haiku reads the exchange and extracts knowledge facts
2. **Search** — Each fact is compared against existing memories via FTS5
3. **Decide** — Haiku determines: ADD new / UPDATE existing / DELETE wrong / NONE
4. **Execute** — Decisions are applied to the memories table

This prevents duplicate memories and keeps the knowledge base clean.

### What Gets Remembered

- Decisions and preferences you express
- Technical discoveries and constraints
- Project status and milestones
- Corrections to wrong assumptions
- Workflow patterns

### Managing Memories

```bash
# List all memories
~/.claude-mem/venv/bin/python ~/.claude/scripts/mem0-processor.py --list

# Search memories
~/.claude-mem/venv/bin/python ~/.claude/scripts/mem0-processor.py --search "project name"

# Statistics
~/.claude-mem/venv/bin/python ~/.claude/scripts/mem0-processor.py --stats
```

## Skills

22+ portable skills are included. Use them by name in conversation:

| Skill | What It Does |
|-------|-------------|
| `pdf` | Read, merge, split, create PDFs |
| `docx` | Read, edit, create Word documents |
| `pptx` | Create/edit PowerPoint presentations |
| `xlsx` | Read, edit, create Excel files |
| `research` | Structured web research with source verification |
| `first-principles` | Systematic problem decomposition |
| `frontend-design` | Production-grade UI design |
| `canvas-design` | Visual art and poster design |
| `algorithmic-art` | Generative art with p5.js |
| `doc-coauthoring` | Collaborative document writing workflow |

### Install Skills

Additional capabilities can be installed from `~/.claude/skills/install/`:

```
voice-transcription  — Local Whisper speech-to-text
markitdown           — Universal file → Markdown converter
supabase-mcp         — Supabase database tools
sqlite-mcp           — SQLite database tools
context7             — Live API documentation
```

## Server Management

```bash
# Check status
~/.claude/hooks/http-server/manage.sh status

# Restart
~/.claude/hooks/http-server/manage.sh restart

# View logs
tail -f ~/.claude-mem/logs/http-hooks-server.log
tail -f ~/.claude-mem/logs/per-turn-memory.log
```

## Customization

### Adding MCP Servers

Edit `~/.claude/settings.local.json` and add to the `mcpServers` key:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "my-mcp-server"],
      "env": { "API_KEY": "..." }
    }
  }
}
```

### Adding Custom Skills

Create a directory in `~/.claude/skills/my-skill/` with a `SKILL.md` file:

```markdown
---
name: my-skill
description: What this skill does
---

Instructions for Claude when this skill is invoked...
```

### Modifying the Assistant

Edit `~/.claude/CLAUDE.md` to change personality, instructions, and behavior.

## Uninstall

```bash
cd claude-os
./uninstall.sh
```

This removes all Claude OS files but preserves Claude Code itself.

## Architecture

The system uses a single persistent HTTP server (stdlib only, zero dependencies) that handles all six Claude Code hook events in 1-5ms per call. This replaces what would otherwise be 14+ Python process spawns per hook event.

The memory database uses SQLite with FTS5 full-text search and 384-dimensional sentence-transformer embeddings for hybrid retrieval. Observations are scored with exponential attention decay, and low-value entries are automatically consolidated.

## License

MIT
