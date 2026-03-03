#!/usr/bin/env python3
"""
Per-Turn Memory Extraction Hook (Mem0-style two-pass pipeline)

Runs on UserPromptSubmit. Forks to background immediately (zero blocking),
then runs the full Mem0 pipeline on the PREVIOUS exchange:

  Pass 1: Haiku extracts facts from the exchange
  Search: For each fact, FTS search for similar existing memories
  Pass 2: Haiku compares new facts against existing memories →
           decides ADD / UPDATE <id> / DELETE <id> / NONE
  Execute: Apply each decision to the memories table

Input (stdin): {"prompt": "...", "session_id": "...", "transcript_path": "..."}
"""

import sys
import json
import os
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".claude-mem/logs/per-turn-memory.log"
MEM0_SCRIPT = Path.home() / ".claude/scripts/mem0-processor.py"
VENV_PYTHON = str(Path.home() / ".claude-mem/venv/bin/python")

HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_TIMEOUT = 20

MIN_EXCHANGE_LENGTH = 100
MAX_EXCHANGE_CHARS = 8000


def log(msg):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} - {msg}\n")
    except Exception:
        pass


def get_api_key():
    return os.environ.get("ANTHROPIC_API_KEY")


def call_haiku(api_key, prompt):
    """Generic Haiku API call. Returns parsed JSON or None."""
    body = json.dumps({
        "model": HAIKU_MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
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
        with urllib.request.urlopen(req, timeout=HAIKU_TIMEOUT) as resp:
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
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode()[:200]
        except Exception:
            pass
        log(f"Haiku API error {e.code}: {body_text}")
        return None
    except json.JSONDecodeError:
        log("Failed to parse Haiku JSON response")
        return None
    except Exception as e:
        log(f"Haiku call failed: {e}")
        return None


def get_previous_exchange(transcript_path):
    """Extract the last complete user→assistant exchange from transcript."""
    if not transcript_path or not Path(transcript_path).exists():
        return None

    messages = []
    try:
        with open(transcript_path) as f:
            for line in f:
                try:
                    msg = json.loads(line.strip())
                    msg_type = msg.get("type")

                    if msg_type == "user":
                        content = msg.get("message", {}).get("content", "")
                        if isinstance(content, list):
                            parts = [
                                item.get("text", "") if isinstance(item, dict) and item.get("type") == "text"
                                else (item if isinstance(item, str) else "")
                                for item in content
                            ]
                            content = "\n".join(parts)
                        if content and len(content.strip()) > 5:
                            messages.append(("user", content.strip()))

                    elif msg_type == "assistant":
                        content = msg.get("message", {}).get("content", [])
                        if isinstance(content, list):
                            text = "\n".join(
                                item.get("text", "")
                                for item in content
                                if isinstance(item, dict) and item.get("type") == "text"
                            )
                        elif isinstance(content, str):
                            text = content
                        else:
                            text = ""
                        if text and len(text.strip()) > 10:
                            messages.append(("assistant", text.strip()))

                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception as e:
        log(f"Error reading transcript: {e}")
        return None

    if len(messages) < 3:
        return None

    last_assistant = None
    last_user = None
    for i in range(len(messages) - 2, -1, -1):
        if messages[i][0] == "assistant" and last_assistant is None:
            last_assistant = messages[i][1]
        elif messages[i][0] == "user" and last_assistant is not None and last_user is None:
            last_user = messages[i][1]
            break

    if not last_user or not last_assistant:
        return None

    exchange = f"USER: {last_user[:3000]}\n\nASSISTANT: {last_assistant[:5000]}"
    if len(exchange) < MIN_EXCHANGE_LENGTH:
        return None
    return exchange[:MAX_EXCHANGE_CHARS]


def search_similar(fact_text, limit=5):
    """FTS search for memories similar to this fact. Returns list of dicts."""
    try:
        result = subprocess.run(
            [VENV_PYTHON, str(MEM0_SCRIPT), "--search", fact_text,
             "--fts-only", "--limit", str(limit)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception as e:
        log(f"Search failed: {e}")
    return []


def execute_decision(decision, session_id):
    """Execute a single ADD/UPDATE/DELETE/NONE decision."""
    action = decision.get("action", "NONE").upper()
    fact = decision.get("fact", "").strip()
    category = decision.get("category", "technical").strip()
    target_id = decision.get("target_id")

    if action == "NONE":
        log(f"NONE: {fact[:60]}")
        return False

    if action == "ADD":
        if not fact or len(fact) < 10:
            return False
        try:
            result = subprocess.run(
                [VENV_PYTHON, str(MEM0_SCRIPT), "--add", fact,
                 "--category", category, "--session", session_id or "unknown",
                 "--no-embed"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                log(f"ADD [{category}]: {fact[:80]}")
                return True
            else:
                log(f"ADD failed: {result.stderr[:100]}")
        except Exception as e:
            log(f"ADD error: {e}")
        return False

    if action == "UPDATE" and target_id is not None:
        if not fact or len(fact) < 10:
            return False
        try:
            cmd = [VENV_PYTHON, str(MEM0_SCRIPT), "--update", str(target_id),
                   "--fact", fact, "--no-embed"]
            if category:
                cmd.extend(["--category", category])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                log(f"UPDATE #{target_id}: {fact[:80]}")
                return True
            else:
                log(f"UPDATE failed: {result.stderr[:100]}")
        except Exception as e:
            log(f"UPDATE error: {e}")
        return False

    if action == "DELETE" and target_id is not None:
        try:
            result = subprocess.run(
                [VENV_PYTHON, str(MEM0_SCRIPT), "--delete", str(target_id)],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                log(f"DELETE #{target_id}")
                return True
            else:
                log(f"DELETE failed: {result.stderr[:100]}")
        except Exception as e:
            log(f"DELETE error: {e}")
        return False

    return False


def do_extraction(session_id, transcript_path):
    """Full Mem0 two-pass pipeline. Runs in background."""
    t0 = time.time()

    api_key = get_api_key()
    if not api_key:
        log("No API key found")
        return

    exchange = get_previous_exchange(transcript_path)
    if not exchange:
        log("No previous exchange (session start or too short)")
        return

    log(f"Processing exchange ({len(exchange)} chars)")

    # ── Pass 1: Extract facts ──
    extract_prompt = f"""Extract the most important knowledge facts from this conversation exchange. Focus on:
- Decisions or preferences expressed by the user
- Technical discoveries, bugs found, or constraints identified
- Corrections to previous wrong assumptions
- Project status changes
- Financial outcomes or lessons learned
- Workflow patterns or tools used

Return ONLY a JSON object: {{"facts": [{{"fact": "...", "category": "..."}}]}}
Categories: preference, technical, workflow, project, person, financial

Be very selective — only extract facts worth remembering across sessions.
Skip trivial observations, implementation details, and intermediate steps.
Maximum 5 facts. If nothing is worth remembering, return {{"facts": []}}

EXCHANGE:
{exchange}"""

    result = call_haiku(api_key, extract_prompt)
    if not result or "facts" not in result:
        log(f"Pass 1 failed: {result}")
        return

    facts = result["facts"]
    if not facts:
        log("Pass 1: nothing worth remembering")
        return

    log(f"Pass 1: extracted {len(facts)} facts")

    # ── Search: Find similar existing memories for each fact ──
    facts_with_matches = []
    for item in facts:
        fact_text = item.get("fact", "").strip()
        category = item.get("category", "technical").strip()
        if not fact_text or len(fact_text) < 10:
            continue

        similar = search_similar(fact_text, limit=3)
        facts_with_matches.append({
            "fact": fact_text,
            "category": category,
            "similar_memories": similar
        })

    if not facts_with_matches:
        log("No valid facts to process")
        return

    # ── Pass 2: Compare and decide ──
    comparison_blocks = []
    for i, item in enumerate(facts_with_matches):
        block = f"NEW FACT {i+1}: \"{item['fact']}\" [category: {item['category']}]"
        if item["similar_memories"]:
            block += "\nSIMILAR EXISTING MEMORIES:"
            for mem in item["similar_memories"]:
                block += f"\n  - Memory #{mem['id']} (score {mem.get('score', 0):.2f}): \"{mem['fact']}\""
        else:
            block += "\nSIMILAR EXISTING MEMORIES: None found"
        comparison_blocks.append(block)

    compare_prompt = f"""You are a memory manager. For each new fact, compare it against similar existing memories and decide what to do.

Actions:
- ADD: New information not covered by any existing memory. Include the fact text and category.
- UPDATE <id>: The new fact is about the same topic as an existing memory but has newer, more complete, or corrected information. Include the updated fact text (merge old + new if appropriate) and the target memory ID.
- DELETE <id>: An existing memory is now provably wrong or completely obsolete based on the new fact. Include the target memory ID. Only delete if the new fact directly contradicts it.
- NONE: The new fact is already fully covered by existing memories. No action needed.

IMPORTANT:
- Prefer UPDATE over ADD+DELETE when a fact evolves (e.g., "FOK doesn't work" → "FOK does work now")
- Only ADD if the fact covers genuinely new ground
- Only DELETE if you're certain the existing memory is wrong, not just incomplete
- NONE if an existing memory already says essentially the same thing

{chr(10).join(comparison_blocks)}

Return ONLY a JSON object:
{{"decisions": [{{"action": "ADD|UPDATE|DELETE|NONE", "fact": "...", "category": "...", "target_id": null|<memory_id>, "reason": "brief reason"}}]}}

One decision per new fact, in order."""

    decisions_result = call_haiku(api_key, compare_prompt)
    if not decisions_result or "decisions" not in decisions_result:
        log(f"Pass 2 failed: {decisions_result}")
        # Fallback: just ADD everything (no comparison)
        for item in facts_with_matches:
            execute_decision({
                "action": "ADD", "fact": item["fact"],
                "category": item["category"]
            }, session_id)
        elapsed = time.time() - t0
        log(f"Done (fallback ADD): {len(facts_with_matches)} facts in {elapsed:.1f}s")
        return

    decisions = decisions_result["decisions"]
    log(f"Pass 2: {len(decisions)} decisions")

    # ── Execute decisions ──
    actions_taken = 0
    for decision in decisions:
        action = decision.get("action", "NONE").upper()
        reason = decision.get("reason", "")
        log(f"  Decision: {action} — {reason[:80]}")
        if execute_decision(decision, session_id):
            actions_taken += 1

    elapsed = time.time() - t0
    log(f"Done: {actions_taken} actions from {len(decisions)} decisions in {elapsed:.1f}s")


def find_transcript(session_id):
    claude_dir = Path.home() / ".claude" / "projects"
    if session_id and session_id != "unknown":
        # Try exact match first
        for jsonl in claude_dir.rglob(f"{session_id}.jsonl"):
            return str(jsonl)
        # Try prefix match (hook may receive truncated session ID)
        for jsonl in claude_dir.rglob(f"{session_id}*.jsonl"):
            return str(jsonl)
        # Fallback: most recently modified .jsonl in the project dir
        jsonls = sorted(claude_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if jsonls:
            return str(jsonls[0])
    return None


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    session_id = input_data.get("session_id", "unknown")
    transcript_path = input_data.get("transcript_path", "")

    if not transcript_path or not Path(transcript_path).exists():
        transcript_path = find_transcript(session_id)

    if not transcript_path:
        log(f"No transcript for session {session_id}")
        sys.exit(0)

    # Fork to background — parent returns instantly
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    os.setsid()
    sys.stdin.close()

    try:
        do_extraction(session_id, transcript_path)
    except Exception as e:
        log(f"Unhandled error: {e}")

    os._exit(0)


if __name__ == "__main__":
    main()
