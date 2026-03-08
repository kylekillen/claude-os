#!/usr/bin/env python3
"""
Consolidated HTTP Hooks Server for Claude Code

Replaces 14+ individual shell hook scripts with a single persistent HTTP server.
Performance: ~1-5ms per hook (HTTP POST) vs ~100-500ms per hook (Python process spawn).

Endpoints:
  POST /hooks/SessionStart
  POST /hooks/UserPromptSubmit
  POST /hooks/PreToolUse
  POST /hooks/PostToolUse
  POST /hooks/PreCompact
  POST /hooks/Stop

  Inbound Webhook / Event Queue:
  POST   /webhook/<source>   — receive and queue an event from external source
  GET    /events/pending     — list all unprocessed events
  GET    /events/summary     — one-line summary of pending events
  POST   /events/<id>/ack    — mark event as processed
  DELETE /events/<id>/ack    — mark event as processed (alternative)

All hook endpoints receive the same JSON payload Claude Code sends to shell hooks.
Response format follows Claude Code HTTP hook spec.
Webhook endpoints accept arbitrary JSON payloads from external sources.

Zero external dependencies — stdlib only.
"""

import json
import os
import sys
import sqlite3
import subprocess
import shutil
import time
import threading
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from datetime import datetime, timezone
from pathlib import Path

# Force PyTorch/sentence-transformers to CPU only — prevent Metal GPU crashes
# when multiple processes contend for the GPU (MLX local-extract, hybrid-search, etc.)
os.environ["PYTORCH_MPS_DISABLE"] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
# urllib imports removed — no more direct API calls
# from urllib.request import Request, urlopen
# from urllib.error import HTTPError

# Semantic search (available when running under venv Python with sentence-transformers)
try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# ── Cached Sentence Transformer Model ──
# Loaded once at first use, persists for server lifetime (~400MB in RAM).
# Eliminates 7-12s model reload per subprocess call.
_search_model = None
_search_model_attempted = False
_search_model_lock = threading.Lock()

# ── Config ──
PORT = 9090
HOST = "127.0.0.1"

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
EVENT_QUEUE_DB = os.path.expanduser("~/.claude/hooks/http-server/event-queue.db")
LOG_DIR = Path.home() / ".claude-mem/logs"
LOG_FILE = LOG_DIR / "http-hooks-server.log"
VENV_PYTHON = str(Path.home() / ".claude-mem/venv/bin/python")
# MEM0_SCRIPT removed — observation recording disabled in v3

# Ensure bun and homebrew are in PATH (launchd gives minimal PATH)
_EXTRA_PATHS = [
    str(Path.home() / ".bun/bin"),
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    str(Path.home() / ".local/bin"),
]
_current = os.environ.get("PATH", "")
for p in _EXTRA_PATHS:
    if p not in _current:
        _current = p + ":" + _current
os.environ["PATH"] = _current

# Pre-compact backup dir (configurable via env)
_PROJECT_ROOT = Path(os.environ.get("CLAUDE_OS_PROJECT_ROOT", str(Path.home())))
BACKUP_DIR = _PROJECT_ROOT / "sessions/pre-compact-backups"

# Daily log directory (OpenClaw-style append-only daily context)
DAILY_LOG_DIR = _PROJECT_ROOT / "memory/daily"

# Memory v3: Scripts that run on Stop
# Extract narratives from transcripts, then reindex markdown for search
STOP_SCRIPTS = [
    {"cmd": ["python3", str(Path.home() / ".claude/scripts/extract-narratives.py")], "timeout": 60},
    {"cmd": ["python3", str(Path.home() / ".claude/scripts/compound-loop.py")], "timeout": 30},
    {"cmd": [VENV_PYTHON, str(Path.home() / ".claude/scripts/markdown-search.py"), "--index"], "timeout": 300},
]

# Session consolidation scripts (optional — set CLAUDE_OS_PROJECT_ROOT to enable)
SESSION_SCRIPTS = []
_consolidate = _PROJECT_ROOT / "system/scripts/consolidate_session.py"
_logger = _PROJECT_ROOT / "system/scripts/session_logger.py"
if _consolidate.exists():
    SESSION_SCRIPTS.append({"cmd": ["python3", str(_consolidate), "--hook"], "timeout": 60})
if _logger.exists():
    SESSION_SCRIPTS.append({"cmd": ["python3", str(_logger), "--hook"], "timeout": 60})

# Worker service commands
WORKER_CMD_BASE = [str(Path.home() / ".bun/bin/bun"), str(Path.home() / ".claude/plugins/claude-mem/plugin/scripts/worker-service.cjs")]

# (Memory v3: Haiku API config and API_KEY_PATHS removed — no direct API calls)

# (Memory v3: observation filtering constants removed — PostToolUse is now a no-op)

# File size limits (from check-file-size.py)
HARD_LIMIT = 50 * 1024 * 1024  # 50MB
NATIVE_EXTENSIONS = {'.pdf', '.ipynb'}
BINARY_EXTENSIONS = {'.zip', '.tar', '.gz', '.bz2', '.7z', '.dmg', '.iso', '.bin'}

# Bash cat limit (from check-bash-cat.py)
CAT_SIZE_LIMIT = 500 * 1024  # 500KB

# (Memory v3: TYPE_WEIGHT removed — observation scoring disabled)


LOG_MAX_SIZE = 5 * 1024 * 1024  # 5MB per log file
LOG_KEEP_ROTATED = 3  # keep 3 rotated copies

# Persistent files loaded at SessionStart
DECISIONS_PATH = os.path.expanduser("~/.claude-mem/decisions.md")
ERROR_LOG_PATH = os.path.expanduser("~/.claude-mem/errors.log")


def log_error(source, error, context=""):
    """Append structured error to persistent error log. Programmatic — no LLM needed."""
    try:
        os.makedirs(os.path.dirname(ERROR_LOG_PATH), exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {source}: {error}"
        if context:
            entry += f" | context: {context[:200]}"
        with open(ERROR_LOG_PATH, "a") as f:
            f.write(entry + "\n")
        # Rotate if > 100KB
        if os.path.getsize(ERROR_LOG_PATH) > 100 * 1024:
            lines = open(ERROR_LOG_PATH).readlines()
            with open(ERROR_LOG_PATH, "w") as f:
                f.writelines(lines[-200:])  # Keep last 200 entries
    except Exception:
        pass

# (Memory v3: turn counter and nudge system removed — no longer needed)

def _get_search_model():
    """Lazy-load and cache the sentence transformer model. Thread-safe."""
    global _search_model, _search_model_attempted
    if _search_model_attempted:
        return _search_model
    with _search_model_lock:
        if _search_model_attempted:
            return _search_model
        _search_model_attempted = True
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.environ.get("QUERY_CONTEXT_MODEL", "all-MiniLM-L6-v2")
            # Suppress progress bars that leak to stdout
            old_fd = os.dup(1)
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 1)
            os.close(devnull)
            try:
                _search_model = SentenceTransformer(model_name, device="cpu")
            finally:
                os.dup2(old_fd, 1)
                os.close(old_fd)
        except Exception as e:
            print(f"[WARN] Sentence transformer load failed: {e}", file=sys.stderr)
            _search_model = None
        return _search_model


# ── Inline Query-Context Search ──
# ── Memory v3: Markdown-first query context ──
# Searches markdown index (built by markdown-search.py) instead of SQLite observations/memories.
# Uses cached sentence-transformer model for semantic search.

MD_DB_PATH = os.path.expanduser("~/.claude-mem/markdown-index.db")

_QC_MAX_RESULTS = 15
_QC_MIN_QUERY_LENGTH = 15
_QC_FTS_WEIGHT = 0.4
_QC_SEMANTIC_WEIGHT = 0.6
_QC_SCORE_THRESHOLD = 0.10
_QC_EMBEDDING_DIM = 384
_QC_DOMAIN_BOOST = 1.4  # Boost results from matching domain

# Domain classification from file paths
_QC_DOMAIN_RULES = [
    ("Trading/", "trading"),
    ("Financial/", "financial"),
    ("Screenwriting/", "screenwriting"),
    ("Health/", "health"),
    ("Code/", "code"),
    ("Contacts/", "contacts"),
    ("mojo-work/", "system"),
    ("memory/", "system"),
    ("sessions/", "system"),
    ("drafts/", "system"),
    ("HEARTBEAT", "system"),
    ("CLAUDE.md", "system"),
]

# Query keywords that signal a domain
_QC_DOMAIN_KEYWORDS = {
    "trading": ["trading", "kalshi", "polymarket", "arbitrage", "arb", "bot", "position",
                "market", "spread", "maker", "taker", "alpaca", "momentum", "backtest"],
    "financial": ["financial", "investment", "schwab", "tax", "401k", "ira", "roth",
                  "portfolio", "net worth", "fpl", "dew wealth", "blackstone"],
    "screenwriting": ["screenplay", "pitch", "imposter", "magic", "myst", "script",
                      "outline", "producer", "notes", "halo", "man on fire", "pilot",
                      "episode", "beat sheet", "red deck"],
    "health": ["health", "fitbit", "labs", "workout", "tonal", "sleep", "heart rate",
               "blood", "cholesterol", "weight"],
    "code": ["code", "spotify", "limen", "laten", "github", "deploy", "vercel",
             "nextjs", "react", "python", "typescript", "mcp", "api"],
    "system": ["memory", "heartbeat", "daemon", "hook", "session", "claude",
               "narrative", "compaction", "mojo"],
}

_QC_STOPWORDS = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
                 'of', 'to', 'in', 'for', 'on', 'at', 'by', 'with', 'from',
                 'it', 'its', 'that', 'this', 'do', 'did', 'does', 'what',
                 'how', 'when', 'where', 'why', 'who', 'which', 'can', 'we',
                 'i', 'my', 'our', 'you', 'your', 'me', 'us', 'and', 'or', 'not'}

_QC_SKIP_PATTERNS = [
    'good morning', 'morning routine', 'start the day',
    'yes', 'no', 'ok', 'sure', 'thanks', 'thank you',
    'continue', 'go ahead', 'proceed', 'do it',
    '/commit', '/help', '/clear',
]

# Display path prefixes for relative path display (auto-detected)
_QC_PERSONAL_OS = os.environ.get("CLAUDE_OS_PROJECT_ROOT", os.path.expanduser("~"))
if not _QC_PERSONAL_OS.endswith("/"):
    _QC_PERSONAL_OS += "/"
_QC_AUTO_MEMORY = ""
# Auto-detect auto-memory path from project config
for d in Path.home().glob(".claude/projects/*/memory"):
    _QC_AUTO_MEMORY = str(d) + "/"
    break


def _qc_detect_domain(prompt):
    """Detect which domain a query is about based on keywords."""
    lower = prompt.lower()
    scores = {}
    for domain, keywords in _QC_DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[domain] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


def _qc_should_search(prompt):
    if not prompt or len(prompt.strip()) < _QC_MIN_QUERY_LENGTH:
        return False
    lower = prompt.strip().lower()
    for pat in _QC_SKIP_PATTERNS:
        if lower == pat or (lower.startswith(pat + ' ') and len(lower) < 30):
            return False
    return True


def _qc_search_fts(db, query, limit=60):
    terms = [t for t in query.split() if len(t) > 1 and t.lower() not in _QC_STOPWORDS]
    if not terms:
        return {}
    safe_query = " OR ".join(f'"{t}"' for t in terms[:10])
    try:
        rows = db.execute("""
            SELECT CAST(fts.chunk_id AS INTEGER), fts.rank
            FROM chunks_fts fts
            WHERE chunks_fts MATCH ?
            ORDER BY fts.rank LIMIT ?
        """, (safe_query, limit)).fetchall()
    except Exception:
        return {}
    if not rows:
        return {}
    ranks = [abs(r[1]) for r in rows]
    max_rank = max(ranks) if ranks else 1
    return {r[0]: 1.0 - (abs(r[1]) / max_rank) if max_rank > 0 else 0 for r in rows}


def _qc_search_semantic(db, model, query, limit=60):
    if model is None or not _HAS_NUMPY:
        return {}
    query_emb = model.encode([query], normalize_embeddings=True)[0]
    rows = db.execute("SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL").fetchall()
    scores = []
    for cid, emb_blob in rows:
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        if len(emb) == _QC_EMBEDDING_DIM:
            sim = float(np.dot(query_emb, emb))
            scores.append((cid, sim))
    scores.sort(key=lambda x: -x[1])
    top = scores[:limit]
    if not top:
        return {}
    max_sim = top[0][1]
    min_sim = top[-1][1] if len(top) > 1 else 0
    spread = max_sim - min_sim if max_sim != min_sim else 1
    return {cid: (sim - min_sim) / spread for cid, sim in top}


def _qc_hybrid_search(db, model, query, limit=15, query_domain=None):
    import math
    fts_scores = _qc_search_fts(db, query, limit=limit * 3)
    sem_scores = _qc_search_semantic(db, model, query, limit=limit * 3)
    all_ids = set(fts_scores.keys()) | set(sem_scores.keys())

    # Pre-fetch domain, access_count, and feedback_boost
    chunk_meta = {}
    if all_ids:
        placeholders = ",".join("?" * len(all_ids))
        for row in db.execute(
            f"SELECT id, COALESCE(access_count, 0), COALESCE(domain, 'general'), COALESCE(feedback_boost, 1.0) FROM chunks WHERE id IN ({placeholders})",
            list(all_ids)
        ).fetchall():
            chunk_meta[row[0]] = {"access_count": row[1], "domain": row[2], "feedback_boost": row[3]}

    combined = []
    for cid in all_ids:
        fts = fts_scores.get(cid, 0)
        sem = sem_scores.get(cid, 0)
        score = _QC_FTS_WEIGHT * fts + _QC_SEMANTIC_WEIGHT * sem

        meta = chunk_meta.get(cid, {})

        # Domain boost: prefer results from the same domain as the query
        if query_domain and meta.get("domain") == query_domain:
            score *= _QC_DOMAIN_BOOST

        # Feedback boost: learned from search history (domain specificity vs noise)
        score *= meta.get("feedback_boost", 1.0)

        # Mild access boost: chunks returned before and presumably useful get a nudge
        ac = meta.get("access_count", 0)
        if ac > 0:
            score *= (1.0 + 0.1 * math.log(ac + 1))  # +10% per log(access), gentle

        if score >= _QC_SCORE_THRESHOLD:
            combined.append((cid, score))
    combined.sort(key=lambda x: -x[1])
    return combined[:limit]


def _qc_format_results(db, results):
    if not results:
        return ""
    ids = [r[0] for r in results]
    placeholders = ",".join("?" * len(ids))
    rows = db.execute(f"""
        SELECT id, file_path, section_header, chunk_text
        FROM chunks WHERE id IN ({placeholders})
    """, ids).fetchall()
    chunk_map = {r[0]: r for r in rows}
    lines = ["# Relevant Context (markdown search)\n"]
    for cid, score in results:
        chunk = chunk_map.get(cid)
        if not chunk:
            continue
        _, fpath, header, text = chunk
        rel_path = fpath
        for prefix in [_QC_PERSONAL_OS, _QC_AUTO_MEMORY]:
            if fpath.startswith(prefix):
                rel_path = fpath[len(prefix):]
                break
        display_text = text[:500]
        if len(text) > 500:
            display_text += "..."
        lines.append(f"**[{rel_path}] {header}** (score: {score:.2f})")
        lines.append(f"{display_text}\n")
    return "\n".join(lines)


def _inline_query_context(data):
    """Memory v3: search markdown index for relevant context.
    Uses cached sentence-transformer model. Returns context string or ""."""
    prompt = data.get('prompt', '')
    if not _qc_should_search(prompt):
        return ""
    if not os.path.exists(MD_DB_PATH):
        return ""

    t0 = time.time()
    model = _get_search_model()
    query_domain = _qc_detect_domain(prompt)

    db = sqlite3.connect(MD_DB_PATH, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")

    try:
        results = _qc_hybrid_search(db, model, prompt, limit=_QC_MAX_RESULTS, query_domain=query_domain)
        elapsed = time.time() - t0

        if not results:
            log(f"QUERY_CONTEXT: No results for: {prompt[:80]} ({elapsed:.1f}s)")
            return ""

        # Log search for feedback tracking
        try:
            result_ids = ",".join(str(r[0]) for r in results)
            db.execute("""
                INSERT OR IGNORE INTO search_log (query, query_domain, result_ids, result_count)
                VALUES (?, ?, ?, ?)
            """, (prompt[:500], query_domain, result_ids, len(results)))
            db.commit()
        except Exception:
            pass  # search_log table may not exist yet (created by next --index run)

        domain_info = f", domain={query_domain}" if query_domain else ""
        context = _qc_format_results(db, results)
        log(f"QUERY_CONTEXT: {len(results)} chunks for: {prompt[:60]} ({elapsed:.2f}s{domain_info})")
        return context
    except Exception as e:
        log(f"QUERY_CONTEXT error: {e}")
        return ""
    finally:
        db.close()


def _rotate_log_if_needed():
    """Rotate http-hooks-server.log when it exceeds LOG_MAX_SIZE."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_SIZE:
            for i in range(LOG_KEEP_ROTATED, 0, -1):
                src = LOG_FILE.with_suffix(f".log.{i-1}") if i > 1 else LOG_FILE
                dst = LOG_FILE.with_suffix(f".log.{i}")
                if src.exists():
                    shutil.move(str(src), str(dst))
    except Exception:
        pass

def log(msg):
    ts = datetime.now().isoformat()
    line = f"{ts} {msg}"
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_log_if_needed()
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    # Also log to stderr so launchd captures it
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass


# get_api_key() and call_haiku() REMOVED — no direct API calls allowed.
# Memory extraction relies on subscription-based haiku subagents via memory nudge.


def run_script(cmd, timeout=30, input_data=None):
    """Run a script with optional stdin data."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            input=json.dumps(input_data) if input_data else None
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        log(f"Timeout: {' '.join(cmd[:3])}")
        return False, "", "timeout"
    except Exception as e:
        log(f"Script error {cmd[0]}: {e}")
        return False, "", str(e)


# ════════════════════════════════════════════════
# Hook Handlers
# ════════════════════════════════════════════════

NARRATIVE_PATH = os.path.expanduser("~/.claude-mem/last-session.md")

def handle_session_start(data):
    """SessionStart: load last session narrative for episodic continuity.
    NOTE: worker-service start/context/session-init are handled by the
    claude-mem plugin's own hooks (plugin/hooks/hooks.json). Do NOT
    duplicate those calls here — killing the worker-service daemon
    breaks ALL running Claude Code sessions.
    """
    session_id = data.get("session_id", "unknown")
    log(f"SessionStart: session={session_id[:12]}...")

    # Load last session narrative for episodic memory
    narrative = ""
    try:
        if os.path.exists(NARRATIVE_PATH):
            with open(NARRATIVE_PATH, "r") as f:
                narrative = f.read().strip()
            if narrative:
                narrative = f"<previous-session>\n{narrative}\n</previous-session>"
                log(f"SessionStart: loaded narrative ({len(narrative)} chars)")
    except Exception as e:
        log(f"SessionStart: narrative load error: {e}")

    # Load persistent decisions
    decisions = ""
    try:
        if os.path.exists(DECISIONS_PATH):
            with open(DECISIONS_PATH, "r") as f:
                content = f.read().strip()
            if content:
                decisions = f"\n<persistent-decisions>\n{content}\n</persistent-decisions>"
                log(f"SessionStart: loaded decisions ({len(content)} chars)")
    except Exception as e:
        log(f"SessionStart: decisions load error: {e}")

    # Load recent errors (last 20 lines)
    errors = ""
    try:
        if os.path.exists(ERROR_LOG_PATH):
            with open(ERROR_LOG_PATH, "r") as f:
                lines = f.readlines()
            recent = lines[-20:] if len(lines) > 20 else lines
            if recent:
                errors = f"\n<recent-errors>\n{''.join(recent).strip()}\n</recent-errors>"
                log(f"SessionStart: loaded {len(recent)} recent errors")
    except Exception as e:
        log(f"SessionStart: error log load error: {e}")

    # Load today's + yesterday's daily logs (OpenClaw bootstrap pattern)
    daily_context = ""
    try:
        from datetime import timedelta
        today = datetime.now()
        for days_ago in [1, 0]:  # Yesterday first, then today
            day = today - timedelta(days=days_ago)
            day_str = day.strftime("%Y-%m-%d")
            daily_path = DAILY_LOG_DIR / f"{day_str}.md"
            if daily_path.exists():
                content = daily_path.read_text().strip()
                if content and len(content) > 50:
                    # Truncate to keep context reasonable
                    if len(content) > 3000:
                        content = content[-3000:]  # Keep most recent entries
                    label = "today" if days_ago == 0 else "yesterday"
                    daily_context += f"\n<daily-log date=\"{day_str}\" rel=\"{label}\">\n{content}\n</daily-log>"
                    log(f"SessionStart: loaded daily log {label} ({len(content)} chars)")
    except Exception as e:
        log(f"SessionStart: daily log load error: {e}")

    # Check for pending inbound events (webhook queue)
    pending_events = _get_pending_events_context()

    context = (narrative + decisions + errors + daily_context + pending_events).strip()
    if context:
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    return {}


def handle_user_prompt_submit(data):
    """UserPromptSubmit: Memory v3 markdown context injection.
    Searches markdown index for relevant content and injects as context.
    No more per-turn local extraction — narratives are written at Stop.
    """
    # Query context (inline — uses cached model, no subprocess)
    context = _inline_query_context(data)

    if context:
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}
    return {}



# (Memory v3: _run_local_extraction, _build_memory_nudge, _extract_recent_context,
#  _run_per_turn_memory all removed — extraction now happens via markdown narratives at Stop)


def handle_pre_tool_use(data):
    """PreToolUse: safety guards + tool guards."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name == "Read":
        result = _check_file_size(tool_input)
        if result.get("continue") is False:
            return result
    elif tool_name == "Bash":
        result = _check_bash_cat(tool_input)
        if result.get("continue") is False:
            return result
        result = _guard_paper_mode(tool_input)
        if result.get("continue") is False:
            return result
        result = _guard_moltbook(tool_input)
        if result.get("continue") is False:
            return result
        result = _guard_sentence_transformers_cpu(tool_input)
        if result.get("continue") is False:
            return result
    elif tool_name == "Edit":
        result = _guard_mojo_file_edit(tool_input)
        if result.get("continue") is False:
            return result

    return {}


# ── Tool Guards ──────────────────────────────────────────────────────

# Vault root for file guard (auto-configured from CLAUDE_OS_PROJECT_ROOT)
_VAULT_ROOT = os.environ.get("CLAUDE_OS_PROJECT_ROOT", str(Path.home()))

# Paths within vault that any instance (including heartbeat) may edit
_EDIT_ALLOWED_PATHS = [
    "mojo-work/",
    "mojo-drafts/",
    "sessions/",
    "memory/",
    "HEARTBEAT.md",
    "Trading/kalshi-monitor/",
    "Health/data/",
    "drafts/jot-file-ingested.md",
    "sessions/daily-summaries.md",
]

# System files outside the vault that heartbeat must not touch
_SYSTEM_PROTECTED_PATHS = [
    os.path.expanduser("~/.claude/settings.json"),
    os.path.expanduser("~/.claude/settings.local.json"),
    os.path.expanduser("~/.claude/CLAUDE.md"),
    os.path.expanduser("~/.claude/hooks/"),
]


def _guard_mojo_file_edit(tool_input):
    """Block edits to Kyle's original files in the vault.
    Allows: mojo-work/, mojo-drafts/, sessions/, memory/, HEARTBEAT.md,
    Trading/kalshi-monitor/, Health/data/, -mojo suffix files.
    Also blocks edits to ~/.claude/settings*, ~/.claude/hooks/, ~/.claude/CLAUDE.md
    UNLESS the file path contains the override marker.
    """
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return {}

    # Check system-protected paths
    for protected in _SYSTEM_PROTECTED_PATHS:
        if protected.endswith("/"):
            if file_path.startswith(protected):
                return {
                    "continue": False,
                    "stopReason": (
                        f"BLOCKED: Cannot edit system file {file_path}. "
                        "If Kyle explicitly asked for this change, have him confirm "
                        "and re-run with '# KYLE-APPROVED' comment in the edit context."
                    )
                }
        else:
            if file_path == protected:
                return {
                    "continue": False,
                    "stopReason": (
                        f"BLOCKED: Cannot edit system file {file_path}. "
                        "If Kyle explicitly asked for this change, have him confirm "
                        "and re-run with '# KYLE-APPROVED' comment in the edit context."
                    )
                }

    # Check vault files
    if not file_path.startswith(_VAULT_ROOT):
        return {}  # Not in vault — allow (other projects, home dir, etc.)

    rel_path = file_path[len(_VAULT_ROOT):].lstrip("/")

    # Allow mojo-suffixed files anywhere
    basename = os.path.basename(rel_path)
    name_no_ext = os.path.splitext(basename)[0]
    if name_no_ext.endswith("-mojo"):
        return {}

    # Allow explicitly permitted paths
    for allowed in _EDIT_ALLOWED_PATHS:
        if allowed.endswith("/"):
            if rel_path.startswith(allowed):
                return {}
        else:
            if rel_path == allowed:
                return {}

    # Block everything else in vault
    return {
        "continue": False,
        "stopReason": (
            f"BLOCKED: Editing vault file '{rel_path}' directly. "
            "Work in mojo-work/ or use -mojo suffix files. "
            "If Kyle explicitly asked for this edit, tell him about this guard "
            "and ask him to confirm — then add the file to _EDIT_ALLOWED_PATHS in server.py."
        )
    }


def _guard_paper_mode(tool_input):
    """Block attempts to switch trading from paper to live mode.
    Override: include '# LIVE-APPROVED' in the command."""
    command = tool_input.get("command", "")
    if not command:
        return {}

    # Allow if Kyle explicitly approved
    if "# LIVE-APPROVED" in command:
        return {}

    # Patterns that indicate switching to live trading
    live_patterns = [
        r'ALPACA_PAPER_TRADE\s*=\s*["\']?[Ff]alse',
        r'paper\s*=\s*[Ff]alse',
        r'is_paper\s*=\s*[Ff]alse',
        r'--live\b',
        r'PAPER_MODE\s*=\s*[Ff]alse',
        r'paper_mode\s*=\s*[Ff]alse',
    ]
    for pattern in live_patterns:
        if re.search(pattern, command):
            return {
                "continue": False,
                "stopReason": (
                    "BLOCKED: Detected attempt to switch to live trading. "
                    "All trading must stay in paper mode until Kyle explicitly approves. "
                    "If Kyle has approved live trading, re-run the command with "
                    "'# LIVE-APPROVED' appended as a comment."
                )
            }
    return {}


def _guard_moltbook(tool_input):
    """Block installing skills or packages from Moltbook content."""
    command = tool_input.get("command", "")
    if not command:
        return {}

    if "Moltbook" not in command and "moltbook" not in command:
        return {}

    install_patterns = [
        r'\b(pip|npm|npx|brew|cargo)\s+install\b',
        r'\bskill\b',
        r'\bplugin\s+install\b',
    ]
    for pattern in install_patterns:
        if re.search(pattern, command):
            return {
                "continue": False,
                "stopReason": (
                    "BLOCKED: Moltbook content is untrusted. "
                    "Never install skills, plugins, or packages from Moltbook."
                )
            }
    return {}


def _guard_sentence_transformers_cpu(tool_input):
    """Warn if running sentence-transformers without CPU enforcement."""
    command = tool_input.get("command", "")
    if not command:
        return {}

    if "SentenceTransformer" not in command and "sentence-transformers" not in command:
        return {}

    # Check for CPU enforcement
    if 'device="cpu"' in command or "device='cpu'" in command:
        return {}
    if "PYTORCH_MPS_DISABLE=1" in command:
        return {}
    if "CUDA_VISIBLE_DEVICES=" in command:
        return {}

    return {
        "continue": False,
        "stopReason": (
            "BLOCKED: sentence-transformers must run on CPU to avoid Metal GPU crashes. "
            "Add device='cpu' to SentenceTransformer() or set PYTORCH_MPS_DISABLE=1."
        )
    }


# (Memory v3: _pre_action_memory_lookup removed — was searching old SQLite DB.
#  Context injection now happens at UserPromptSubmit via markdown search.)


def _check_file_size(tool_input):
    """Block reads of huge binary files."""
    file_path = tool_input.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return {}

    size_bytes = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()

    if ext in NATIVE_EXTENSIONS:
        return {}

    if ext in BINARY_EXTENSIONS and size_bytes > HARD_LIMIT:
        size_mb = size_bytes / (1024 * 1024)
        return {
            "continue": False,
            "stopReason": f"BLOCKED: Binary file is {size_mb:.0f}MB. Extract or convert first."
        }
    return {}


def _check_bash_cat(tool_input):
    """Block cat/head/tail on large files."""
    command = tool_input.get("command", "")
    cat_patterns = [
        r'\bcat\s+["\']?([^|;&\n"\']+)["\']?',
        r'\bhead\s+(?:-\d+\s+)?["\']?([^|;&\n"\']+)["\']?',
        r'\btail\s+(?:-\d+\s+)?["\']?([^|;&\n"\']+)["\']?',
    ]
    for pattern in cat_patterns:
        match = re.search(pattern, command)
        if match:
            file_path = match.group(1).strip()
            if file_path.startswith('~'):
                file_path = os.path.expanduser(file_path)
            if not os.path.exists(file_path) or os.path.isdir(file_path):
                return {}
            if os.path.getsize(file_path) > CAT_SIZE_LIMIT:
                size_kb = os.path.getsize(file_path) / 1024
                return {
                    "continue": False,
                    "stopReason": f"BLOCKED: cat/head/tail on {size_kb:.0f}KB file (limit: 500KB). Use `large-file-processing` skill instead."
                }
    return {}


# (Memory v3: _ensure_memory_session_id removed — no longer writing to old SQLite DB)


def handle_post_tool_use(data):
    """PostToolUse: no-op in Memory v3 (observation recording disabled).
    Old SQLite observations DB is no longer searched by query-context."""
    return {}


def _flush_daily_log(transcript_path, session_id):
    """Extract key context from transcript and append to today's daily log.
    This is the OpenClaw 'pre-compaction flush' pattern: save important info
    before compaction destroys it. Runs programmatically (no LLM needed)."""
    if not transcript_path or not Path(transcript_path).exists():
        return

    try:
        DAILY_LOG_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        daily_path = DAILY_LOG_DIR / f"{today}.md"

        # Parse transcript for key signals: decisions, file changes, user requests
        decisions = []
        files_changed = []
        topics = []

        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                role = entry.get("role", "")
                content = entry.get("message", entry.get("content", ""))

                # Extract from compaction summaries (richest context source)
                if entry.get("type") == "summary":
                    summary_text = content if isinstance(content, str) else str(content)
                    if summary_text and len(summary_text) > 50:
                        topics.append(summary_text[:500])

                # Extract user messages (capture intent/decisions)
                if role == "user" and isinstance(content, str) and len(content) > 20:
                    lower = content.lower()
                    # Capture decision-like statements
                    if any(kw in lower for kw in ["let's", "go with", "use ", "switch to",
                                                   "remember", "always", "never", "prefer",
                                                   "decision", "agreed", "confirmed"]):
                        decisions.append(content[:200])

                # Track file writes/edits
                if role == "assistant":
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tool = block.get("name", "")
                                inp = block.get("input", {})
                                if tool in ("Write", "Edit") and "file_path" in inp:
                                    files_changed.append(inp["file_path"])

        # Build the flush entry
        if not decisions and not files_changed and not topics:
            return

        ts = datetime.now().strftime("%H:%M")
        entry_lines = [f"\n### Session {session_id[:8]} — {ts} (pre-compaction flush)\n"]

        if topics:
            entry_lines.append("**Context:**")
            for t in topics[-3:]:  # Last 3 compaction summaries
                entry_lines.append(f"- {t[:300]}")
            entry_lines.append("")

        if decisions:
            entry_lines.append("**Decisions/Intent:**")
            for d in decisions[-10:]:  # Last 10 decision-like statements
                entry_lines.append(f"- {d}")
            entry_lines.append("")

        if files_changed:
            unique_files = list(dict.fromkeys(files_changed))[-15:]
            entry_lines.append("**Files changed:**")
            for fp in unique_files:
                entry_lines.append(f"- {fp}")
            entry_lines.append("")

        # Append to daily log (create if needed)
        flush_text = "\n".join(entry_lines)
        if not daily_path.exists():
            daily_path.write_text(f"# Daily Log — {today}\n{flush_text}")
        else:
            with open(daily_path, "a") as f:
                f.write(flush_text)

        log(f"Daily log flush: {len(decisions)} decisions, {len(files_changed)} files, {len(topics)} topics")

    except Exception as e:
        log(f"Daily log flush error: {e}")
        log_error("PreCompact/daily-flush", str(e), f"session={session_id}")


def handle_pre_compact(data):
    """PreCompact: backup transcript + flush key context to daily log before compaction."""
    session_id = data.get("session_id", "unknown")
    transcript_path = data.get("transcript_path", "")
    trigger = data.get("trigger", "unknown")

    log(f"PreCompact: {trigger}, session: {session_id}")

    if transcript_path and Path(transcript_path).exists():
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            backup_name = f"{timestamp}-{session_id}-{trigger}.jsonl"
            backup_path = BACKUP_DIR / backup_name
            shutil.copy2(transcript_path, backup_path)
            size_kb = backup_path.stat().st_size / 1024
            log(f"Backed up {size_kb:.1f}KB to {backup_name}")

            # Update index
            index_path = BACKUP_DIR / "session-index.json"
            try:
                index = json.loads(index_path.read_text()) if index_path.exists() else {}
                index[session_id] = {"backup_file": backup_name, "timestamp": timestamp, "trigger": trigger}
                index_path.write_text(json.dumps(index, indent=2))
            except Exception:
                pass
        except Exception as e:
            log(f"Backup error: {e}")
            log_error("PreCompact/backup", str(e), f"session={session_id}")

    # Memory v3.1: Flush key context to daily log before compaction destroys it.
    # This is the OpenClaw 'write-ahead log' pattern.
    _flush_daily_log(transcript_path, session_id)

    return {}


def _run_stop_pipeline(data):
    """Background worker: Memory v3 stop pipeline.
    1. Session consolidation scripts
    2. Extract narratives from transcripts
    3. Reindex markdown files for search

    Note: Doc updates happen in-session (CLAUDE.md convention) and via
    heartbeat daemon cleanup tasks — not at Stop, to avoid API costs.
    """
    session_id = data.get("session_id", "unknown")

    # Session consolidation scripts
    for script in SESSION_SCRIPTS:
        run_script(script["cmd"], timeout=script["timeout"], input_data=data)

    # Memory v3 pipeline: extract narratives + reindex markdown
    for script in STOP_SCRIPTS:
        run_script(script["cmd"], timeout=script["timeout"])

    log(f"Stop pipeline complete: session={session_id}")


def handle_stop(data):
    """Stop: launch memory pipeline in background thread so we return immediately."""
    session_id = data.get("session_id", "unknown")
    log(f"Stop: session={session_id} (launching background pipeline)")
    t = threading.Thread(target=_run_stop_pipeline, args=(data,), daemon=True)
    t.start()
    return {}


# (Memory v3: observation helpers removed — _should_observe, _classify_type, _classify_validity,
#  _generate_title, _generate_facts, _extract_files all deleted. PostToolUse is now a no-op.)


# ════════════════════════════════════════════════
# Inbound Webhook / Event Queue
# ════════════════════════════════════════════════

def _init_event_queue_db():
    """Create the event queue SQLite database and table if they don't exist."""
    db = sqlite3.connect(EVENT_QUEUE_DB, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'message',
            payload TEXT NOT NULL DEFAULT '{}',
            timestamp TEXT NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_events_processed ON events(processed)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_events_source ON events(source)")
    db.commit()
    db.close()
    log("Event queue DB initialized")


def _get_event_db():
    """Get a connection to the event queue database."""
    db = sqlite3.connect(EVENT_QUEUE_DB, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.row_factory = sqlite3.Row
    return db


def handle_webhook_receive(source, body):
    """POST /webhook/<source> — receive and queue an inbound event.

    Accepts JSON body with optional fields:
      - type: event type string (default: 'message')
      - payload: arbitrary JSON data (default: entire body)
      - Or any raw JSON which becomes the payload
    """
    try:
        data = json.loads(body) if isinstance(body, (str, bytes)) else body
    except (json.JSONDecodeError, TypeError):
        data = {"raw": body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)}

    event_type = data.pop("type", "message") if isinstance(data, dict) else "message"
    # If caller provided an explicit 'payload' key, use it; otherwise the whole body is the payload
    if isinstance(data, dict) and "payload" in data:
        payload = data["payload"]
    else:
        payload = data

    timestamp = datetime.now(timezone.utc).isoformat()

    db = _get_event_db()
    try:
        cursor = db.execute(
            "INSERT INTO events (source, type, payload, timestamp, processed) VALUES (?, ?, ?, ?, 0)",
            (source, event_type, json.dumps(payload), timestamp)
        )
        event_id = cursor.lastrowid
        db.commit()
        log(f"WEBHOOK: queued event #{event_id} from {source} (type={event_type})")
        return {"status": "queued", "event_id": event_id, "source": source, "type": event_type}
    except Exception as e:
        log(f"WEBHOOK error: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def handle_events_pending():
    """GET /events/pending — list all unprocessed events."""
    db = _get_event_db()
    try:
        rows = db.execute(
            "SELECT id, source, type, payload, timestamp, processed FROM events WHERE processed = 0 ORDER BY id ASC"
        ).fetchall()
        events = []
        for row in rows:
            events.append({
                "id": row["id"],
                "source": row["source"],
                "type": row["type"],
                "payload": json.loads(row["payload"]),
                "timestamp": row["timestamp"],
                "processed": bool(row["processed"]),
            })
        return {"count": len(events), "events": events}
    except Exception as e:
        log(f"EVENTS pending error: {e}")
        return {"count": 0, "events": [], "error": str(e)}
    finally:
        db.close()


def handle_event_ack(event_id):
    """POST /events/<id>/ack — mark a single event as processed."""
    db = _get_event_db()
    try:
        cursor = db.execute("UPDATE events SET processed = 1 WHERE id = ? AND processed = 0", (event_id,))
        db.commit()
        if cursor.rowcount > 0:
            log(f"EVENT ack: #{event_id} marked processed")
            return {"status": "acknowledged", "event_id": event_id}
        else:
            return {"status": "not_found_or_already_processed", "event_id": event_id}
    except Exception as e:
        log(f"EVENT ack error: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def handle_events_summary():
    """GET /events/summary — one-line summary of pending events for SessionStart injection."""
    db = _get_event_db()
    try:
        rows = db.execute("""
            SELECT source, type, COUNT(*) as cnt
            FROM events
            WHERE processed = 0
            GROUP BY source, type
            ORDER BY cnt DESC
        """).fetchall()
        if not rows:
            return {"summary": "", "total": 0}

        total = sum(r["cnt"] for r in rows)
        parts = []
        for row in rows:
            parts.append(f"{row['cnt']} {row['source']}/{row['type']}")
        summary = f"Pending events ({total}): " + ", ".join(parts)

        # Also fetch the most recent 5 for detail
        recent = db.execute("""
            SELECT id, source, type, payload, timestamp
            FROM events WHERE processed = 0
            ORDER BY id DESC LIMIT 5
        """).fetchall()
        recent_list = []
        for r in recent:
            try:
                payload_preview = json.loads(r["payload"])
                # Try to get a text preview from common payload shapes
                preview = ""
                if isinstance(payload_preview, dict):
                    preview = payload_preview.get("text", payload_preview.get("message", payload_preview.get("subject", "")))
                if isinstance(preview, str) and len(preview) > 100:
                    preview = preview[:100] + "..."
                recent_list.append(f"  #{r['id']} [{r['source']}/{r['type']}] {preview or '(structured data)'}")
            except Exception:
                recent_list.append(f"  #{r['id']} [{r['source']}/{r['type']}]")

        detail = "\n".join(recent_list)
        return {"summary": summary, "detail": detail, "total": total}
    except Exception as e:
        log(f"EVENTS summary error: {e}")
        return {"summary": "", "total": 0, "error": str(e)}
    finally:
        db.close()


def _get_pending_events_context():
    """Build context string for SessionStart injection from pending events."""
    try:
        if not os.path.exists(EVENT_QUEUE_DB):
            return ""
        result = handle_events_summary()
        if result["total"] == 0:
            return ""
        lines = [
            f"\n<pending-events>\n{result['summary']}",
        ]
        if result.get("detail"):
            lines.append(f"Recent:\n{result['detail']}")
        lines.append("Use GET /events/pending on localhost:9090 to see full payloads.")
        lines.append("Use POST /events/<id>/ack to acknowledge processed events.")
        lines.append("</pending-events>")
        return "\n".join(lines)
    except Exception:
        return ""


# ════════════════════════════════════════════════
# HTTP Server
# ════════════════════════════════════════════════

HANDLERS = {
    "SessionStart": handle_session_start,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PreToolUse": handle_pre_tool_use,
    "PostToolUse": handle_post_tool_use,
    "PreCompact": handle_pre_compact,
    "Stop": handle_stop,
}


def _handle_health():
    """Health check endpoint: GET /health"""
    result = {"status": "ok", "pid": os.getpid(), "timestamp": datetime.now(timezone.utc).isoformat()}
    try:
        if not os.path.exists(DB_PATH):
            result["status"] = "error"
            result["error"] = "DB not found"
            return result

        db = sqlite3.connect(DB_PATH, timeout=5)
        db.execute("PRAGMA journal_mode=WAL")

        cursor = db.execute("SELECT COUNT(*) FROM observations")
        result["observation_count"] = cursor.fetchone()[0]

        cursor = db.execute("SELECT MAX(created_at) FROM observations")
        row = cursor.fetchone()
        result["last_observation_time"] = row[0] if row and row[0] else None

        cursor = db.execute("SELECT COUNT(*) FROM sdk_sessions")
        result["session_count"] = cursor.fetchone()[0]

        cursor = db.execute("SELECT COUNT(*) FROM sdk_sessions WHERE memory_session_id IS NULL")
        result["sessions_missing_memory_id"] = cursor.fetchone()[0]

        cursor = db.execute("SELECT COUNT(*) FROM memories WHERE is_active = 1")
        result["active_memories"] = cursor.fetchone()[0]

        # Check DB writability
        db.execute("PRAGMA integrity_check")
        result["db_writable"] = True

        db.close()
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


class HookHandler(BaseHTTPRequestHandler):

    def _send_json(self, status_code, result):
        """Helper to send a JSON response."""
        response_body = json.dumps(result, indent=2).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def do_GET(self):
        path = self.path.strip("/")
        if path == "health":
            self._send_json(200, _handle_health())
        elif path == "events/pending":
            self._send_json(200, handle_events_pending())
        elif path == "events/summary":
            self._send_json(200, handle_events_summary())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        # Parse URL path
        path = self.path.strip("/")
        parts = path.split("/")

        # Read request body (shared by all POST handlers)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        # Route: POST /hooks/<event_type>
        if len(parts) == 2 and parts[0] == "hooks":
            event_type = parts[1]
            handler = HANDLERS.get(event_type)
            if not handler:
                log(f"POST 404: unknown event_type={event_type}")
                self.send_response(404)
                self.end_headers()
                return

            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                log(f"{event_type}: invalid JSON body")
                data = {}

            try:
                t0 = time.time()
                result = handler(data)
                elapsed = (time.time() - t0) * 1000
                sid = data.get("session_id", "?")[:12] if isinstance(data, dict) else "?"
                log(f"{event_type}: {elapsed:.0f}ms (session={sid})")
            except Exception as e:
                log(f"{event_type} ERROR: {e}")
                result = {}

            response_body = json.dumps(result).encode() if result else b""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            if response_body:
                self.wfile.write(response_body)
            return

        # Route: POST /webhook/<source>
        if len(parts) == 2 and parts[0] == "webhook":
            source = parts[1]
            if not source or not re.match(r'^[a-zA-Z0-9_-]+$', source):
                self._send_json(400, {"status": "error", "error": "Invalid source name. Use alphanumeric, hyphens, underscores."})
                return
            result = handle_webhook_receive(source, body)
            status_code = 201 if result.get("status") == "queued" else 500
            self._send_json(status_code, result)
            return

        # Route: POST /events/<id>/ack
        if len(parts) == 3 and parts[0] == "events" and parts[2] == "ack":
            try:
                event_id = int(parts[1])
            except ValueError:
                self._send_json(400, {"status": "error", "error": "Event ID must be an integer."})
                return
            self._send_json(200, handle_event_ack(event_id))
            return

        log(f"POST 404: unmatched path={self.path}")
        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        """Support DELETE /events/<id>/ack as an alternative to POST."""
        path = self.path.strip("/")
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "events" and parts[2] == "ack":
            try:
                event_id = int(parts[1])
            except ValueError:
                self._send_json(400, {"status": "error", "error": "Event ID must be an integer."})
                return
            self._send_json(200, handle_event_ack(event_id))
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress default HTTP log noise
        pass


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Starting HTTP hooks server on {HOST}:{PORT}")

    # Initialize event queue database
    _init_event_queue_db()

    # Write PID file for management
    pid_file = Path.home() / ".claude/hooks/http-server/server.pid"
    pid_file.write_text(str(os.getpid()))

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = ThreadedHTTPServer((HOST, PORT), HookHandler)
    try:
        log("Server running")
        server.serve_forever()
    except KeyboardInterrupt:
        log("Server stopped")
        server.server_close()
    finally:
        pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
