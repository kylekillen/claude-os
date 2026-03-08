# Claude OS v3

Markdown-first memory, 70+ skills, and autonomous operation for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Zero API cost — memory comes from indexing your own markdown files.

## How It Works

```
You write markdown docs ──→ Indexed (FTS5 + semantic embeddings) ──→ Stored in SQLite
                                                                          │
Every prompt ──→ Hybrid search (keyword 40% + semantic 60%) ──→ Top 15 chunks injected
                 + domain boosting + feedback loop + access tracking
                                                                          │
Session ends ──→ Narratives extracted from transcript ──→ Index rebuilt
Session starts ──→ Previous narrative + daily logs loaded ──→ Continuity
```

**Memory cost:** $0. No LLM extraction. No API calls. Just your markdown files indexed locally with sentence-transformers.

## Install

### Prerequisites

- **Claude Code** — [Install guide](https://docs.anthropic.com/en/docs/claude-code/getting-started)
- **Python 3.10+** — `brew install python@3.13` or [python.org](https://python.org)

### One Command

```bash
git clone https://github.com/kylekillen/claude-os.git
cd claude-os
./install.sh
```

The installer will:
1. Ask you to name your AI assistant
2. Check prerequisites
3. Optionally set up AgentMail (your assistant's own email)
4. Install hooks, scripts, and 70+ skills
5. Create a Python venv with sentence-transformers
6. Initialize the markdown index database
7. Start the hooks server (macOS launchd or manual)
8. Verify everything works

## What Gets Installed

```
~/.claude/
├── hooks/                  # Hook server (persistent HTTP on port 9090)
│   ├── http-server/        # server.py — handles all lifecycle events
│   └── session-start-*.sh  # SessionStart → HTTP bridge
├── scripts/                # Search engine, narrative extraction, compound loop
├── skills/                 # 70+ skills (pdf, docx, research, design, etc.)
│   └── install/            # Additional capabilities to install on-demand
├── agents/                 # Agent team configurations
├── CLAUDE.md               # Your assistant's personality and instructions
└── settings.local.json     # Hook configuration

~/.claude-mem/
├── markdown-index.db       # SQLite: chunks + FTS5 + embeddings + search_log
├── venv/                   # Python environment (sentence-transformers)
├── decisions.md            # Persistent decisions (loaded every SessionStart)
├── last-session.md         # Previous session narrative
├── session-narratives/     # Archive of session summaries
└── logs/                   # Server logs

~/mojo-daemon/              # Autonomous task daemon
├── src/                    # Heartbeat scripts
├── logs/                   # Daemon logs
└── state/                  # Task state
```

## Memory System (v3)

### Markdown-First — No LLM Extraction

v3 eliminated all LLM-based memory extraction. Instead:

1. **You write markdown files** — notes, decisions, status docs, MEMORY.md
2. **markdown-search.py indexes them** — chunks at `## ` headers, embeds with all-MiniLM-L6-v2
3. **server.py searches on every prompt** — FTS5 + cosine similarity, top 15 injected as context

That's it. Write things down → they become searchable memory. Zero API cost.

### Three Scoring Layers

| Layer | What | How |
|-------|------|-----|
| **Domain boost** | Chunks tagged by file path (trading, financial, health...). Query keywords detect domain. Matching chunks: 1.4x | Automatic |
| **Feedback boost** | Search history analysis. Domain-specific chunks boosted, noisy ones penalized | Self-improving (needs 30+ searches) |
| **Access boost** | Previously-returned chunks get mild boost | Automatic |

### Session Lifecycle

| Event | What Happens |
|-------|-------------|
| **SessionStart** | Load: previous session narrative, persistent decisions, recent errors, daily logs, pending webhook events |
| **UserPromptSubmit** | Detect domain → search markdown index → inject top 15 chunks |
| **PreCompact** | Backup transcript, flush key decisions to daily log |
| **Stop** | Extract narratives → run compound loop → rebuild markdown index |

### Key Scripts

| Script | Role |
|--------|------|
| `markdown-search.py` | Indexer + search engine. Chunks .md files, embeds, searches |
| `extract-narratives.py` | Pulls compaction summaries from .jsonl transcripts |
| `compound-loop.py` | Extracts failure patterns, generates preventive rules |
| `query-context.py` | Standalone search fallback (CLI) |

### Performance

| Metric | Value |
|--------|-------|
| Search latency | ~50-100ms (model cached in server process) |
| Model memory | ~400MB (all-MiniLM-L6-v2, CPU) |
| Index size | ~15MB |
| Context per prompt | ~3-4K tokens (15 chunks) |
| Reindex (incremental) | ~5-30s |

## Skills (70+)

### Document Skills
`pdf` · `docx` · `pptx` · `xlsx`

### Research & Thinking
`research` · `first-principles` · `algorithm`

### Design & Development
`frontend-design` · `canvas-design` · `brand-guidelines` · `theme-factory` · `mcp-builder` · `web-artifacts-builder`

### Content & Marketing
`copywriting` · `content-strategy` · `seo-audit` · `email-sequence` · `social-content` · `ad-creative`

### Install-on-Demand
Available in `~/.claude/skills/install/`:
`voice-transcription` · `markitdown` · `supabase-mcp` · `sqlite-mcp` · `context7` · `google-calendar` · `google-drive` · `telegram-swarm` · `ntfy`

## AgentMail

Your assistant can have its own email address (e.g., `assistant@agentmail.to`). Set up during install or add later via [agentmail.to](https://agentmail.to).

## Server Management

```bash
~/.claude/hooks/http-server/manage.sh status    # Check
~/.claude/hooks/http-server/manage.sh restart   # Restart
tail -f ~/.claude-mem/logs/http-hooks-stderr.log # Logs
```

## Uninstall

```bash
cd claude-os && ./uninstall.sh
```

## Architecture

Single persistent HTTP server (stdlib only) on port 9090 handles all six Claude Code hook events in 1-5ms. Memory search runs inline on every UserPromptSubmit — no subprocess spawning. The embedding model (all-MiniLM-L6-v2, 384-dim) is loaded once and cached in server memory (~400MB).

The markdown index uses SQLite with FTS5 for keyword search and pre-computed embeddings for semantic search. Files are chunked at `## ` headers. A search_log table tracks every query for feedback-based scoring.

Session continuity comes from extracted narrative summaries (pulled from transcript compaction points) and append-only daily logs (OpenClaw pattern).

## License

MIT
