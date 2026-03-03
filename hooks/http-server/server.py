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

All endpoints receive the same JSON payload Claude Code sends to shell hooks.
Response format follows Claude Code HTTP hook spec.

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
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ── Config ──
PORT = 9090
HOST = "127.0.0.1"

DB_PATH = os.path.expanduser("~/.claude-mem/claude-mem.db")
LOG_DIR = Path.home() / ".claude-mem/logs"
LOG_FILE = LOG_DIR / "http-hooks-server.log"
VENV_PYTHON = str(Path.home() / ".claude-mem/venv/bin/python")
MEM0_SCRIPT = str(Path.home() / ".claude/scripts/mem0-processor.py")

# Ensure common tool paths are available (launchd gives minimal PATH)
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

# Pre-compact backup dir
BACKUP_DIR = Path.home() / ".claude-mem/backups"

# Scripts that run on Stop
STOP_SCRIPTS = [
    {"cmd": ["python3", str(Path.home() / ".claude/scripts/memory-update.py")], "timeout": 30},
    {"cmd": ["python3", str(Path.home() / ".claude/scripts/attention-decay.py")], "timeout": 30},
    {"cmd": ["python3", str(Path.home() / ".claude/scripts/memory-consolidate.py"), "--execute"], "timeout": 30},
    {"cmd": ["python3", str(Path.home() / ".claude/scripts/extract-entities.py")], "timeout": 30},
    {"cmd": ["python3", str(Path.home() / ".claude/scripts/extract-patterns.py")], "timeout": 30},
    {"cmd": [VENV_PYTHON, str(Path.home() / ".claude/scripts/hybrid-search.py"), "--embed-new"], "timeout": 60},
    {"cmd": [VENV_PYTHON, str(Path.home() / ".claude/scripts/mem0-processor.py"), "--embed-all"], "timeout": 30},
    {"cmd": ["python3", str(Path.home() / ".claude/scripts/sync-memories-to-md.py")], "timeout": 15},
]

# Session consolidation scripts (add your own project-specific scripts here)
SESSION_SCRIPTS = []

# Haiku API config
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# ── Observation filtering ──
ALWAYS_OBSERVE = {'Write', 'Edit', 'NotebookEdit'}
SOMETIMES_OBSERVE = {'Bash', 'WebSearch', 'WebFetch', 'Task'}
NEVER_OBSERVE = {
    'Glob', 'Grep', 'Read',
    'TaskList', 'TaskGet', 'TaskUpdate', 'TaskCreate', 'TaskStop', 'TaskOutput',
    'AskUserQuestion', 'EnterPlanMode', 'ExitPlanMode', 'Skill',
}
TRIVIAL_BASH = ['ls', 'pwd', 'echo', 'which', 'cat', 'head', 'tail', 'wc', 'sleep', 'true', 'false']

# File size limits
HARD_LIMIT = 50 * 1024 * 1024  # 50MB
NATIVE_EXTENSIONS = {'.pdf', '.ipynb'}
BINARY_EXTENSIONS = {'.zip', '.tar', '.gz', '.bz2', '.7z', '.dmg', '.iso', '.bin'}

# Bash cat limit
CAT_SIZE_LIMIT = 500 * 1024  # 500KB

# Type weights for attention scoring
TYPE_WEIGHT = {
    'decision': 2.0, 'bugfix': 1.8, 'feature': 1.5,
    'refactor': 1.2, 'discovery': 1.0, 'change': 0.8,
}


def log(msg):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except Exception:
        pass


def get_api_key():
    """Get Anthropic API key from environment variable."""
    return os.environ.get("ANTHROPIC_API_KEY")


def call_haiku(api_key, prompt, timeout=30):
    """Call Haiku API. Returns parsed JSON or None."""
    body = json.dumps({
        "model": HAIKU_MODEL,
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST"
    )

    try:
        with urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
            text = result.get("content", [{}])[0].get("text", "")
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
            return json.loads(text)
    except Exception as e:
        log(f"Haiku API error: {e}")
        return None


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

def handle_session_start(data):
    """SessionStart: no-op (context generation handled elsewhere)."""
    return {}


def handle_user_prompt_submit(data):
    """UserPromptSubmit: context injection + memory retrieval."""
    session_id = data.get("session_id", "")
    transcript_path = data.get("transcript_path", "")

    # Query context (the main context injection)
    ok, stdout, _ = run_script(
        [VENV_PYTHON, str(Path.home() / ".claude/scripts/query-context.py")],
        timeout=15, input_data=data
    )
    context = stdout.strip() if ok and stdout.strip() else ""

    # Fork memory extraction to background (don't block the prompt)
    threading.Thread(
        target=_run_per_turn_memory, args=(session_id, transcript_path),
        daemon=True
    ).start()

    if context:
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}
    return {}


def _run_per_turn_memory(session_id, transcript_path):
    """Background: per-turn Mem0 memory extraction."""
    try:
        run_script(
            [sys.executable, str(Path.home() / ".claude/hooks/per-turn-memory.py")],
            timeout=60,
            input_data={"session_id": session_id, "transcript_path": transcript_path}
        )
    except Exception as e:
        log(f"Per-turn memory error: {e}")


def handle_pre_tool_use(data):
    """PreToolUse: file size check (Read) and bash cat check (Bash)."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name == "Read":
        return _check_file_size(tool_input)
    elif tool_name == "Bash":
        return _check_bash_cat(tool_input)
    return {}


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
                    "stopReason": f"BLOCKED: cat/head/tail on {size_kb:.0f}KB file (limit: 500KB). Use Read tool with offset/limit instead."
                }
    return {}


def handle_post_tool_use(data):
    """PostToolUse: observe tool use -> write to sqlite."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", "")
    session_id = data.get("session_id", "")

    if not tool_name or not _should_observe(tool_name, tool_input):
        return {}

    if not session_id:
        return {}

    try:
        if not os.path.exists(DB_PATH):
            return {}

        db = sqlite3.connect(DB_PATH, timeout=5)
        db.execute("PRAGMA journal_mode=WAL")

        cursor = db.execute(
            "SELECT memory_session_id, project FROM sdk_sessions WHERE content_session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            db.close()
            return {}

        memory_session_id, project = row[0], row[1] or 'default'

        cursor = db.execute(
            "SELECT COUNT(*) FROM observations WHERE memory_session_id = ?",
            (memory_session_id,)
        )
        prompt_num = cursor.fetchone()[0] + 1

        now = datetime.now(timezone.utc)
        obs_type = _classify_type(tool_name, tool_input, tool_response)
        title = _generate_title(tool_name, tool_input, tool_response)
        facts = _generate_facts(tool_name, tool_input, tool_response)
        files_read, files_modified = _extract_files(tool_name, tool_input)

        facts_text = ' '.join(facts)
        discovery_tokens = max(len(facts_text) // 4, 50)
        initial_score = TYPE_WEIGHT.get(obs_type, 1.0)

        validity_class, valid_for_hours = _classify_validity(tool_name, tool_input, obs_type)
        now_ms = int(now.timestamp() * 1000)
        valid_until = (now_ms + valid_for_hours * 3600000) if valid_for_hours else None

        db.execute("""
            INSERT INTO observations
            (memory_session_id, project, type, title, subtitle, facts, narrative, concepts,
             files_read, files_modified, prompt_number, created_at, created_at_epoch,
             discovery_tokens, attention_score, access_count, validity_class, valid_until_epoch)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (
            memory_session_id, project, obs_type, title, '',
            json.dumps(facts), '', json.dumps([]),
            json.dumps(files_read), json.dumps(files_modified),
            prompt_num, now.isoformat(), now_ms,
            discovery_tokens, initial_score, validity_class, valid_until,
        ))

        db.commit()
        db.close()
        log(f"OBS: [{obs_type}] {title[:60]}")

    except Exception as e:
        log(f"PostToolUse DB error: {e}")

    return {}


def handle_pre_compact(data):
    """PreCompact: backup transcript before compaction."""
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

    # Run memory extraction in background
    threading.Thread(
        target=_run_pre_compact_memories, args=(data,),
        daemon=True
    ).start()

    return {}


def _run_pre_compact_memories(data):
    """Background: pre-compact memory extraction."""
    try:
        run_script(
            [sys.executable, str(Path.home() / ".claude/hooks/pre-compact-memories.py")],
            timeout=60, input_data=data
        )
    except Exception as e:
        log(f"PreCompact memories error: {e}")


def _run_stop_pipeline(data):
    """Background worker: run full memory pipeline."""
    session_id = data.get("session_id", "unknown")

    # Session consolidation scripts (if any configured)
    for script in SESSION_SCRIPTS:
        run_script(script["cmd"], timeout=script["timeout"], input_data=data)

    # Pre-compact memories (full conversation extraction)
    run_script(
        [sys.executable, str(Path.home() / ".claude/hooks/pre-compact-memories.py")],
        timeout=60, input_data=data
    )

    # Memory pipeline scripts (sequential — each depends on previous)
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


# ════════════════════════════════════════════════
# Observation helpers
# ════════════════════════════════════════════════

def _should_observe(tool_name, tool_input):
    if tool_name in NEVER_OBSERVE:
        return False
    if tool_name in ALWAYS_OBSERVE:
        return True
    if tool_name in SOMETIMES_OBSERVE:
        if tool_name == 'Bash':
            cmd = tool_input.get('command', '').strip()
            first_word = cmd.split()[0] if cmd else ''
            first_word = os.path.basename(first_word)
            if first_word in TRIVIAL_BASH:
                return False
            if len(cmd) < 15 and first_word in ('echo', 'date', 'whoami'):
                return False
            return True
        return True
    if tool_name.startswith('mcp__'):
        return True
    return False


def _classify_type(tool_name, tool_input, tool_response):
    if tool_name in ('Write', 'Edit', 'NotebookEdit'):
        return 'change'
    if tool_name == 'Bash':
        cmd = tool_input.get('command', '')
        if 'git commit' in cmd:
            return 'change'
        if any(x in cmd for x in ['pip install', 'npm install', 'brew install', 'apt install']):
            return 'change'
        if 'test' in cmd.lower() or 'pytest' in cmd:
            return 'discovery'
        return 'discovery'
    if tool_name in ('WebSearch', 'WebFetch'):
        return 'discovery'
    if tool_name == 'Task':
        return 'feature'
    return 'discovery'


def _classify_validity(tool_name, tool_input, obs_type):
    if tool_name in ('Write', 'Edit', 'NotebookEdit'):
        return 'permanent', None
    if obs_type == 'decision':
        return 'permanent', None
    if tool_name == 'Bash':
        cmd = tool_input.get('command', '')
        if any(x in cmd for x in ['install', 'git commit', 'git push', 'ALTER TABLE', 'CREATE TABLE']):
            return 'permanent', None
        if any(x in cmd.lower() for x in ['balance', 'price', 'status', 'position', 'portfolio']):
            return 'snapshot', 24
        if any(x in cmd.lower() for x in ['test', 'pytest', 'debug', 'curl']):
            return 'ephemeral', 4
        return 'snapshot', 48
    if tool_name in ('WebSearch', 'WebFetch'):
        return 'snapshot', 72
    if tool_name == 'Task':
        return 'snapshot', 168
    return 'snapshot', 48


def _generate_title(tool_name, tool_input, tool_response):
    if tool_name == 'Write':
        return f"Created {os.path.basename(tool_input.get('file_path', 'unknown'))}"
    if tool_name == 'Edit':
        return f"Edited {os.path.basename(tool_input.get('file_path', 'unknown'))}"
    if tool_name == 'NotebookEdit':
        mode = tool_input.get('edit_mode', 'replace')
        return f"Notebook {mode}: {os.path.basename(tool_input.get('notebook_path', 'unknown'))}"
    if tool_name == 'Bash':
        desc = tool_input.get('description', '')
        if desc:
            return desc[:80]
        cmd = tool_input.get('command', '')
        return f"Ran: {cmd[:77]}..." if len(cmd) > 80 else f"Ran: {cmd}"
    if tool_name == 'WebSearch':
        return f"Searched: {tool_input.get('query', '')[:70]}"
    if tool_name == 'WebFetch':
        url = tool_input.get('url', '')
        return f"Fetched: {url[:67]}..." if len(url) > 70 else f"Fetched: {url}"
    if tool_name == 'Task':
        return f"Agent ({tool_input.get('subagent_type', '')}): {tool_input.get('description', '')[:60]}"
    if tool_name.startswith('mcp__'):
        return f"MCP {tool_name.split('__')[-1]}"
    return f"{tool_name} operation"


def _generate_facts(tool_name, tool_input, tool_response):
    facts = []
    resp_str = str(tool_response) if tool_response else ''
    if tool_name in ('Write', 'Edit', 'NotebookEdit'):
        fp = tool_input.get('file_path', tool_input.get('notebook_path', ''))
        facts.append(f"File: {fp}")
        if tool_name == 'Edit':
            old = tool_input.get('old_string', '')
            new = tool_input.get('new_string', '')
            if old:
                facts.append(f"Replaced {len(old)} chars with {len(new)} chars")
            if tool_input.get('replace_all'):
                facts.append("Replace all occurrences")
    elif tool_name == 'Bash':
        cmd = tool_input.get('command', '')
        facts.append(f"Command: {cmd[:300]}")
        if resp_str and len(resp_str) > 5:
            if 'error' in resp_str.lower() or 'failed' in resp_str.lower():
                facts.append(f"Error in output: {resp_str[:200]}")
            else:
                facts.append(f"Output: {resp_str[:200]}")
    elif tool_name == 'WebSearch':
        facts.append(f"Query: {tool_input.get('query', '')}")
    elif tool_name == 'WebFetch':
        facts.append(f"URL: {tool_input.get('url', '')}")
        facts.append(f"Prompt: {tool_input.get('prompt', '')[:100]}")
    elif tool_name == 'Task':
        facts.append(f"Agent type: {tool_input.get('subagent_type', 'unknown')}")
        facts.append(f"Description: {tool_input.get('description', '')}")
        prompt = tool_input.get('prompt', '')
        if prompt:
            facts.append(f"Task prompt: {prompt[:200]}")
    return facts


def _extract_files(tool_name, tool_input):
    files_read, files_modified = [], []
    if tool_name == 'Read':
        fp = tool_input.get('file_path', '')
        if fp:
            files_read.append(fp)
    elif tool_name in ('Write', 'Edit'):
        fp = tool_input.get('file_path', '')
        if fp:
            files_modified.append(fp)
    elif tool_name == 'NotebookEdit':
        fp = tool_input.get('notebook_path', '')
        if fp:
            files_modified.append(fp)
    return files_read, files_modified


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


class HookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = self.path.strip("/")
        parts = path.split("/")
        if len(parts) != 2 or parts[0] != "hooks":
            self.send_response(404)
            self.end_headers()
            return

        event_type = parts[1]
        handler = HANDLERS.get(event_type)
        if not handler:
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        try:
            t0 = time.time()
            result = handler(data)
            elapsed = (time.time() - t0) * 1000
            log(f"{event_type}: {elapsed:.0f}ms")
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

    def log_message(self, format, *args):
        pass


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Starting HTTP hooks server on {HOST}:{PORT}")

    pid_file = Path.home() / ".claude/hooks/http-server/server.pid"
    pid_file.write_text(str(os.getpid()))

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

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
