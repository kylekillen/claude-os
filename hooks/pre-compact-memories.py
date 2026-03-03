#!/usr/bin/env python3
"""
Pre-Compaction / Stop Memory Extraction Hook (Mem0-style two-pass pipeline)

Fires on PreCompact (before context window compression) and Stop (session end).
Reads the full transcript, runs the Mem0 pipeline:

  Pass 1: Haiku extracts up to 10 facts from the full conversation
  Search: For each fact, FTS search for similar existing memories
  Pass 2: Haiku compares new facts against existing memories →
           decides ADD / UPDATE <id> / DELETE <id> / NONE
  Execute: Apply each decision to the memories table

Input (stdin): {"session_id": "...", "transcript_path": "...", "trigger": "..."}
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

LOG_FILE = Path.home() / ".claude-mem/logs/pre-compact-memories.log"
MEM0_SCRIPT = Path.home() / ".claude/scripts/mem0-processor.py"
VENV_PYTHON = str(Path.home() / ".claude-mem/venv/bin/python")

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TRANSCRIPT_CHARS = 80000


def log(msg):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} - {msg}\n")
    except Exception:
        pass


def get_api_key():
    return os.environ.get("ANTHROPIC_API_KEY")


def call_haiku(api_key, prompt, timeout=30):
    """Generic Haiku API call. Returns parsed JSON or None."""
    body = json.dumps({
        "model": HAIKU_MODEL,
        "max_tokens": 3000,
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        log(f"API error {e.code}: {body_text}")
        return None
    except json.JSONDecodeError:
        log("Failed to parse Haiku JSON")
        return None
    except Exception as e:
        log(f"API call failed: {e}")
        return None


DB_PATH = Path.home() / ".claude-mem/claude-mem.db"


def extract_conversation(transcript_path):
    """Extract user/assistant messages AND tool results from the JSONL transcript."""
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
                            parts = []
                            for item in content:
                                if isinstance(item, dict):
                                    if item.get("type") == "text":
                                        parts.append(item.get("text", ""))
                                    elif item.get("type") == "tool_result":
                                        # Include tool results — this is where Agent summaries live
                                        result_content = item.get("content", "")
                                        if isinstance(result_content, list):
                                            for rc in result_content:
                                                if isinstance(rc, dict) and rc.get("type") == "text":
                                                    parts.append(f"[TOOL RESULT]: {rc.get('text', '')[:3000]}")
                                        elif isinstance(result_content, str) and len(result_content) > 20:
                                            parts.append(f"[TOOL RESULT]: {result_content[:3000]}")
                                elif isinstance(item, str):
                                    parts.append(item)
                            content = "\n".join(parts)
                        if content and len(content.strip()) > 5:
                            messages.append(f"USER: {content.strip()[:4000]}")

                    elif msg_type == "assistant":
                        content = msg.get("message", {}).get("content", [])
                        if isinstance(content, list):
                            parts = []
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    parts.append(item.get("text", ""))
                            text = "\n".join(parts)
                        elif isinstance(content, str):
                            text = content
                        else:
                            text = ""
                        if text and len(text.strip()) > 10:
                            messages.append(f"ASSISTANT: {text.strip()[:2000]}")

                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception as e:
        log(f"Error reading transcript: {e}")

    return messages


def extract_session_observations(session_id):
    """Pull structured observations from the DB for this session's time window.

    Observations capture ALL work including subagent activity, so this
    provides coverage of the 88% of session content that raw transcript
    text messages miss (tool results, Agent outputs, file changes).
    """
    try:
        import sqlite3
        db = sqlite3.connect(str(DB_PATH), timeout=5)

        # Get observations from the last 6 hours (covers any active session)
        from datetime import timezone
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        six_hours_ago = now_ms - (6 * 60 * 60 * 1000)

        rows = db.execute("""
            SELECT title, subtitle, facts, type
            FROM observations
            WHERE created_at_epoch > ?
            ORDER BY created_at_epoch ASC
        """, (six_hours_ago,)).fetchall()
        db.close()

        if not rows:
            return ""

        # Build a compact digest — title + key facts for each observation
        lines = []
        for title, subtitle, facts_json, obs_type in rows:
            entry = f"- [{obs_type or '?'}] {title or '(untitled)'}"
            if subtitle:
                entry += f" — {subtitle[:120]}"
            # Include structured facts if available
            if facts_json:
                try:
                    facts = json.loads(facts_json) if isinstance(facts_json, str) else facts_json
                    if isinstance(facts, list):
                        for fact in facts[:3]:  # Top 3 facts per observation
                            entry += f"\n    * {str(fact)[:200]}"
                except (json.JSONDecodeError, TypeError):
                    pass
            lines.append(entry)

        digest = "\n".join(lines)
        log(f"Observation digest: {len(rows)} observations, {len(digest)} chars")
        return digest

    except Exception as e:
        log(f"Observation extraction failed: {e}")
        return ""


def search_similar(fact_text, limit=5):
    """FTS search for memories similar to this fact."""
    try:
        result = subprocess.run(
            [VENV_PYTHON, str(MEM0_SCRIPT), "--search", fact_text,
             "--fts-only", "--limit", str(limit)],
            capture_output=True, text=True, timeout=5
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
        reason = decision.get("reason", "")
        log(f"NONE: {reason[:60]} — {fact[:40]}")
        return False

    if action == "ADD":
        if not fact or len(fact) < 10:
            return False
        try:
            result = subprocess.run(
                [VENV_PYTHON, str(MEM0_SCRIPT), "--add", fact,
                 "--category", category, "--session", session_id or "unknown",
                 "--no-embed"],
                capture_output=True, text=True, timeout=10
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
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
                capture_output=True, text=True, timeout=10
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


def main():
    t0 = time.time()

    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        log("No valid input")
        sys.exit(0)

    session_id = input_data.get("session_id", "unknown")
    transcript_path = input_data.get("transcript_path", "")

    log(f"Memory extraction: session={session_id}")

    # Find transcript
    if not transcript_path or not Path(transcript_path).exists():
        claude_dir = Path.home() / ".claude" / "projects"
        if session_id and session_id != "unknown":
            # Try exact match
            for jsonl in claude_dir.rglob(f"{session_id}.jsonl"):
                transcript_path = str(jsonl)
                break
            # Try prefix match (hook may receive truncated session ID)
            if not transcript_path or not Path(transcript_path).exists():
                for jsonl in claude_dir.rglob(f"{session_id}*.jsonl"):
                    transcript_path = str(jsonl)
                    break
            # Fallback: most recently modified .jsonl
            if not transcript_path or not Path(transcript_path).exists():
                jsonls = sorted(claude_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
                if jsonls:
                    transcript_path = str(jsonls[0])

    if not transcript_path or not Path(transcript_path).exists():
        log(f"No transcript found (path={transcript_path}, session={session_id})")
        sys.exit(0)

    api_key = get_api_key()
    if not api_key:
        log("No API key found")
        sys.exit(0)

    # Extract conversation text (user/assistant messages + tool results)
    messages = extract_conversation(transcript_path)

    # Extract structured observations from DB (captures subagent work)
    obs_digest = extract_session_observations(session_id)

    if not messages and not obs_digest:
        log("No messages or observations found")
        sys.exit(0)

    # Build combined input: conversation text + observation digest
    conversation_text = "\n\n".join(messages) if messages else ""

    # Budget: 50K for conversation, 30K for observations
    if len(conversation_text) > 50000:
        conversation_text = conversation_text[-50000:]
        log(f"Truncated conversation to last 50000 chars")
    if len(obs_digest) > 30000:
        obs_digest = obs_digest[-30000:]
        log(f"Truncated observations to last 30000 chars")

    total_chars = len(conversation_text) + len(obs_digest)
    log(f"Extracted {len(messages)} messages ({len(conversation_text)} chars) + {len(obs_digest)} chars observations = {total_chars} total")

    # Build the input sections
    input_sections = []
    if conversation_text:
        input_sections.append(f"CONVERSATION:\n{conversation_text}")
    if obs_digest:
        input_sections.append(f"WORK LOG (structured observations of all tool use, including subagent/background work):\n{obs_digest}")

    combined_input = "\n\n---\n\n".join(input_sections)

    # ── Pass 1: Extract facts ──
    extract_prompt = f"""Extract the most important knowledge facts from this session. You have TWO sources:
1. CONVERSATION — the direct user/assistant dialogue including tool results
2. WORK LOG — structured observations of every significant action, including work done by background agents

Focus on:
- Decisions Kyle made or preferences he expressed
- Technical discoveries, bugs found, or constraints identified
- Corrections to previous wrong assumptions
- Project status changes or milestones reached
- Key files created or architectural choices made
- Financial outcomes or lessons learned
- Workflow patterns

Return ONLY a JSON object: {{"facts": [{{"fact": "...", "category": "..."}}]}}
Categories: preference, technical, workflow, project, person, financial

Be selective — only extract facts worth remembering across sessions.
Skip trivial observations and implementation details.
Maximum 10 facts.

{combined_input}"""

    result = call_haiku(api_key, extract_prompt, timeout=30)
    if not result or "facts" not in result:
        log(f"Pass 1 failed: {result}")
        sys.exit(0)

    facts = result["facts"]
    if not facts:
        log("Pass 1: nothing worth remembering")
        sys.exit(0)

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
        log("No valid facts after filtering")
        sys.exit(0)

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

    decisions_result = call_haiku(api_key, compare_prompt, timeout=30)
    if not decisions_result or "decisions" not in decisions_result:
        log(f"Pass 2 failed: {decisions_result} — falling back to simple ADD")
        # Fallback: ADD everything without comparison
        stored = 0
        for item in facts_with_matches:
            if execute_decision({
                "action": "ADD", "fact": item["fact"],
                "category": item["category"]
            }, session_id):
                stored += 1
        elapsed = time.time() - t0
        log(f"Done (fallback): {stored} ADDs in {elapsed:.1f}s")
        sys.exit(0)

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
    sys.exit(0)


if __name__ == "__main__":
    main()
