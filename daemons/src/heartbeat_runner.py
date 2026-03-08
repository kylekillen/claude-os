#!/usr/bin/env /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python
"""
Heartbeat runner v2 — Autonomous Mojo agent.

Modes:
  TASK MODE:    When HEARTBEAT.md has unchecked tasks, pick one and do it.
  ALERT MODE:   When event-alerts/ has files, process them first.
  SCAN MODE:    When nothing else to do, scan for opportunities (4h cooldown).

After every run, sends a Telegram notification with a summary.
Supports session persistence via --session-id for multi-cycle projects.
"""

import os
import re
import json
import subprocess
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta

# Add mojo-daemon/src to path for shared modules
sys.path.insert(0, str(Path.home() / "mojo-daemon/src"))
from mojo_notify import notify, notify_system

# ── Paths ──
WORKSPACE = Path(os.environ.get("CLAUDE_OS_PROJECT_ROOT", str(Path.home())))
HEARTBEAT_FILE = WORKSPACE / "HEARTBEAT.md"
MOJO_WORK = WORKSPACE / "mojo-work"
DAEMON_DIR = Path.home() / "mojo-daemon"
LOG_FILE = DAEMON_DIR / "logs/heartbeat.log"
RESULTS_DIR = DAEMON_DIR / "results"
STATE_FILE = DAEMON_DIR / "state.json"
CLAUDE_PATH = Path.home() / ".local/bin/claude"
EVENT_ALERTS_DIR = MOJO_WORK / "event-alerts"
SCAN_REPORTS_DIR = MOJO_WORK / "scan-reports"
TRADING_JOURNAL_DIR = MOJO_WORK / "trading-journal"

# ── Tuning ──
TASK_TIMEOUT = 1500      # 25 min for task mode (parallel subagents need more time)
SCAN_TIMEOUT = 1800      # 30 min for exploration mode
ALERT_TIMEOUT = 300      # 5 min for alert mode
SCAN_COOLDOWN_HOURS = 1  # Minimum hours between explorations


def log(msg):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {msg}\n")




def load_state():
    """Load persistent state from state.json."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state):
    """Save persistent state to state.json."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def should_scan(state):
    """Check if enough time has passed since last scan."""
    last_scan = state.get("last_scan_time")
    if not last_scan:
        return True
    try:
        last = datetime.fromisoformat(last_scan)
        return (datetime.now() - last) >= timedelta(hours=SCAN_COOLDOWN_HOURS)
    except (ValueError, TypeError):
        return True


def check_event_alerts():
    """Check for event alert files from monitors."""
    if not EVENT_ALERTS_DIR.exists():
        return []

    alerts = []
    for f in sorted(EVENT_ALERTS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            if isinstance(data, list):
                alerts.extend(data)
            else:
                alerts.append(data)
            f.unlink()  # Consume the alert
            log(f"Consumed alert: {f.name}")
        except Exception as e:
            log(f"Error reading alert {f.name}: {e}")
    return alerts


def extract_summary(output):
    """Extract the ---SUMMARY--- block from Claude's output."""
    if "---SUMMARY---" in output and "---END SUMMARY---" in output:
        start = output.index("---SUMMARY---") + len("---SUMMARY---")
        end = output.index("---END SUMMARY---")
        return output[start:end].strip()
    # Fallback: first 300 chars
    clean = output.strip()
    if len(clean) > 300:
        clean = clean[:300] + "..."
    return clean


def run_claude(prompt, timeout, session_id=None, resume_id=None):
    """Run Claude in headless mode. Returns (stdout, stderr, returncode).
    Session ID is controlled by the caller via --session-id flag."""
    cmd = [str(CLAUDE_PATH), "-p", prompt]

    if resume_id:
        cmd.extend(["-r", resume_id])
    elif session_id:
        cmd.extend(["--session-id", session_id])

    # Strip CLAUDECODE env var to allow nested invocation
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["HOME"] = str(Path.home())

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE),
            env=env
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        log(f"Claude timed out after {timeout}s")
        return "", "TIMEOUT", 1
    except Exception as e:
        log(f"Claude error: {e}")
        return "", str(e), 1


def cleanup_old_tmux_sessions():
    """Kill any previous mojo tmux sessions to free Claude session slots."""
    try:
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            if line.startswith("mojo-"):
                try:
                    subprocess.run(["tmux", "kill-session", "-t", line], timeout=10)
                    log(f"Cleaned up tmux session: {line}")
                except subprocess.TimeoutExpired:
                    # Force kill if graceful fails
                    subprocess.run(["tmux", "kill-session", "-t", line], timeout=5,
                                   env={**os.environ, "TMUX": ""})
                    log(f"Force-killed tmux session: {line}")
    except Exception:
        pass


def run_task_mode(state, content):
    """Execute a task from HEARTBEAT.md."""
    session_id = str(uuid.uuid4())

    # Check if we should resume a previous session
    resume_id = None
    if state.get("continuation") and state.get("session_id"):
        resume_id = state["session_id"]
        log(f"Resuming session {resume_id}")

    prompt = f"""You are Mojo, an autonomous coordinator. Read HEARTBEAT.md and work on actionable tasks.

## Parallel Execution Strategy

1. Read HEARTBEAT.md and identify ALL actionable unchecked tasks (not in "Awaiting Kyle", not blocked, not future-dated)
2. If there are 2+ independent tasks, **use the Agent tool to spawn subagents in parallel**:
   - Launch each independent task as a separate subagent (subagent_type="general-purpose")
   - Give each subagent a clear, self-contained prompt with the task description and output path
   - Use model="sonnet" for subagents to manage cost (you are the Opus coordinator)
   - Run independent subagents in the SAME message (parallel tool calls)
   - Wait for all subagents to complete, then collect their results
3. If there is only 1 task, do it yourself directly (no subagent needed)
4. After all work completes, update HEARTBEAT.md to mark tasks done

## Subagent Prompt Template

When spawning a subagent for a task, include:
- The exact task description from HEARTBEAT.md
- Work directory: {WORKSPACE}
- Output path: {MOJO_WORK}/[appropriate-filename].md
- Rule: Save artifacts to mojo-work/ folder, never modify Kyle's originals
- Rule: NO external API calls — use web search, file tools, and code execution only
- Rule: For TRADING RESEARCH — document thesis, evidence, counter-evidence. Do NOT build bots or execute trades. Use the template in mojo-work/trading-journal/
- End with a clear summary of what was accomplished

## Coordinator Rules

- **Skip tasks that are blocked** — if a task says "NEEDS KYLE", is in the "Awaiting Kyle" section, or depends on a future event, skip it
- If genuinely nothing actionable needs attention, just respond: HEARTBEAT_OK
- **Max 3 parallel subagents** per cycle to control token cost
- If more than 3 tasks are actionable, pick the 3 highest priority
- After subagents complete, update HEARTBEAT.md with completion notes for ALL finished tasks
- **CPU awareness** — check system load before spawning if concerned

Work directory: {WORKSPACE}
Output artifacts to: {MOJO_WORK}

At the END of your response, include:
---SUMMARY---
[2-3 sentence summary of ALL tasks completed this cycle]
---END SUMMARY---

If any task needs another heartbeat cycle to complete, end with: SESSION_CONTINUE

Begin by reading HEARTBEAT.md and identifying actionable tasks."""

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    result_file = RESULTS_DIR / f"{run_id}.md"

    stdout, stderr, returncode = run_claude(
        prompt, TASK_TIMEOUT,
        session_id=session_id if not resume_id else None,
        resume_id=resume_id
    )

    # Save output
    with open(result_file, "w") as f:
        f.write(stdout)
        if stderr and stderr != "TIMEOUT":
            f.write("\n\n--- STDERR ---\n")
            f.write(stderr)

    # Update state
    state["last_run"] = datetime.now().isoformat()
    state["last_mode"] = "task"
    state["run_count"] = state.get("run_count", 0) + 1

    # The session_id we passed via --session-id is the one Claude stores
    effective_sid = resume_id or session_id

    if "HEARTBEAT_OK" in stdout:
        log("All tasks blocked — nothing actionable")
        result_file.unlink()
        state["continuation"] = False
        state["session_id"] = None
        state["conversation_session"] = None
        save_state(state)
        return False  # Signal to main() that no work was done
    elif "SESSION_CONTINUE" in stdout:
        state["continuation"] = True
        state["session_id"] = effective_sid
        log(f"Session continuing: {state['session_id']}")
    else:
        state["continuation"] = False
        state["session_id"] = None
        log(f"Task completed, saved to {result_file}")

    # Save session for Telegram conversation window (30 min)
    # Kyle can reply to the Telegram notification and continue this session
    if "HEARTBEAT_OK" not in stdout:
        state["conversation_session"] = effective_sid
        state["conversation_expires"] = (datetime.now() + timedelta(minutes=30)).isoformat()

    save_state(state)

    # Send notification
    summary = extract_summary(stdout)
    if "HEARTBEAT_OK" in stdout:
        return  # Nothing happened, no notification needed

    mode_label = "Resumed" if resume_id else "Task"
    if not summary:
        # Don't spam Kyle when Claude returns empty (usually concurrent session limit)
        log("WARNING: Claude returned empty output for task mode — suppressing notification")
        return True

    notify_system(
        "Heartbeat", f"{mode_label} Complete",
        f"{summary}\n\n_Reply to continue the conversation._"
    )
    return True  # Work was done


def run_alert_mode(state, alerts):
    """Process event alerts from monitors."""
    session_id = str(uuid.uuid4())

    alert_text = json.dumps(alerts, indent=2, default=str)
    if len(alert_text) > 3000:
        alert_text = alert_text[:3000] + "\n...(truncated)"

    prompt = f"""You are Mojo. Event alerts have been detected by your monitoring systems.

ALERTS:
{alert_text}

Process these alerts:
- For EMAIL alerts: summarize the message, flag if Kyle needs to respond, note priority
- For TRADING alerts: assess if position thesis has changed, recommend action (HOLD/EXIT/ADD)
- For TELEGRAM messages from Kyle: treat as a direct request and complete it
- For MARKET alerts: document the opportunity in mojo-work/trading-journal/

Write your analysis to mojo-work/event-alerts/processed/[timestamp].md
If any alert requires Kyle's immediate attention, make that clear in your summary.

Work directory: {WORKSPACE}
Output artifacts to: {MOJO_WORK}

At the END of your response, include:
---SUMMARY---
[2-3 sentence summary of what you found and did]
---END SUMMARY---

Begin processing alerts."""

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    result_file = RESULTS_DIR / f"alerts-{run_id}.md"

    stdout, _stderr, _returncode = run_claude(prompt, ALERT_TIMEOUT, session_id=session_id)

    # Save output
    with open(result_file, "w") as f:
        f.write(stdout)

    state["last_run"] = datetime.now().isoformat()
    state["last_mode"] = "alert"
    state["run_count"] = state.get("run_count", 0) + 1
    state["conversation_session"] = session_id
    state["conversation_expires"] = (datetime.now() + timedelta(minutes=30)).isoformat()
    save_state(state)

    summary = extract_summary(stdout)
    if summary:
        notify_system(
            "Heartbeat", "Alerts Processed",
            f"{summary}\n\n_Reply to continue the conversation._",
            emoji="🚨"
        )

    log(f"Processed {len(alerts)} alerts, saved to {result_file}")


def get_previous_scan_context():
    """Read previous scan reports to avoid repeating the same exploration."""
    if not SCAN_REPORTS_DIR.exists():
        return ""

    reports = sorted(SCAN_REPORTS_DIR.glob("*.md"), reverse=True)[:10]  # Last 10
    if not reports:
        return ""

    summaries = []
    for report in reports:
        try:
            text = report.read_text()
            # Extract title (first # heading)
            title = ""
            for line in text.split("\n"):
                if line.startswith("# "):
                    title = line.lstrip("# ").strip()
                    break

            # Extract summary block if present
            summary = ""
            if "---SUMMARY---" in text and "---END SUMMARY---" in text:
                start = text.index("---SUMMARY---") + len("---SUMMARY---")
                end = text.index("---END SUMMARY---")
                summary = text[start:end].strip()

            if title:
                entry = f"- **{report.name}**: {title}"
                if summary:
                    entry += f"\n  > {summary[:200]}"
                summaries.append(entry)
        except Exception:
            continue

    if not summaries:
        return ""

    return "\n".join(summaries)


def pick_exploration_category(state):
    """Round-robin through exploration categories based on scan history."""
    categories = ["A", "B", "C", "D", "E", "F"]
    last_cat = state.get("last_scan_category", "D")  # Default so first pick is A
    try:
        idx = categories.index(last_cat)
        next_cat = categories[(idx + 1) % len(categories)]
    except ValueError:
        next_cat = "A"
    return next_cat


def run_scan_mode(state):
    """Scan for opportunities when no tasks or alerts exist."""
    session_id = str(uuid.uuid4())

    previous_context = get_previous_scan_context()
    assigned_category = pick_exploration_category(state)

    category_names = {
        "A": "Agent Economy",
        "B": "Arbitrage & Market Opportunities",
        "C": "Capability Expansion",
        "D": "Revenue Products",
        "E": "Moltbook & Self-Improvement",
        "F": "YouTube Skills Discovery",
    }

    previous_block = ""
    if previous_context:
        previous_block = f"""
## CRITICAL: Previous Scan Reports (DO NOT REPEAT)

These are your recent scan reports. You MUST explore something NEW.
Do NOT cover the same ground, cite the same articles, or reach the same conclusions.
If a topic has been thoroughly explored, it's DONE — move on.

{previous_context}

"""

    prompt = f"""You are Mojo in EXPLORATION MODE. No explicit tasks — time to go hunting.

You have 30 MINUTES. Use them. Go deep, not wide. Pick ONE thread and pull it until
you find something genuinely exciting or conclusively dead.

## YOUR ASSIGNED CATEGORY: {assigned_category}. {category_names[assigned_category]}

You MUST explore category {assigned_category} this session. Do not default to Agent Economy
unless that is your assigned category.
{previous_block}
## Exploration Categories

### A. Agent Economy
Search the web for how people are using autonomous AI agents to generate real revenue.
Not toy demos — actual money. Look for:
- Claude Code / OpenClaw / NanoClaw agents running businesses or side hustles
- Trading bots, content farms, SaaS products, freelance automation
- People on Twitter/X, Hacker News, Reddit sharing what's actually working
- New frameworks, tools, or patterns we don't know about yet
- What's failing? What did people try that didn't work?
Go into the rabbit hole. Read the threads. Follow the links.

### B. Arbitrage & Market Opportunities
Not just Kalshi — look for any kind of information asymmetry we could exploit:
- Prediction markets (Kalshi, Polymarket, Metaculus)
- Cross-platform price differences
- Data advantages (we have real-time access to charts, APIs, news)
- Micro-SaaS ideas that an AI agent could build and run autonomously
- Digital products with near-zero marginal cost

### C. Capability Expansion
What new tools, MCP servers, or integrations would make Mojo dramatically more capable?
- New MCP servers on npm/GitHub
- Browser automation patterns
- Voice/audio capabilities
- New APIs or data sources
- Anything that would let Mojo operate more independently

### D. Revenue Products
What could we actually ship? Kyle is a screenwriter with AI expertise.
- Tools for writers (script analysis, pitch generation, coverage)
- Limen (hypnosis app) — check mojo-work/limen-launch-assessment.md for status
- Newsletter, blog, or content product
- Consulting or services an AI agent could partially deliver

### E. Moltbook & Self-Improvement
Browse https://moltbook.com/api/v1/posts for ideas from other agents about:
- Statefulness, persistence, memory architecture across sessions
- Autonomous operation patterns, cron optimization, cost reduction
- Error handling, boot verification, identity persistence
- Novel capabilities or approaches we haven't considered
- Income generation or self-funding strategies
Also search GitHub, HuggingFace, arxiv for agent-relevant tools or techniques.
Extract actionable improvements — not just summaries.

### F. YouTube Skills Discovery
Use the YouTube search + NotebookLM pipeline to discover new Claude Code capabilities:
1. Run: `python3 ~/.claude/scripts/yt-search.py search "claude code [topic] 2026" -n 15`
   Rotate topics each cycle: "claude code hooks", "claude code MCP servers", "claude code autonomous agent",
   "claude code workflow automation", "claude code skills advanced", "claude code agent teams"
2. Filter results: skip videos under 5 min, skip beginner tutorials, prefer recent uploads and high view counts
3. Create a NEW NotebookLM notebook: `notebooklm create "Skills Discovery [date]"`
4. Add the top 8-10 video URLs as sources: `notebooklm source add -n [id] [url]`
5. Query NotebookLM: "What specific tools, techniques, MCP servers, or workflows are mentioned
   that would be valuable for an advanced user with hooks, autonomous operation, and custom memory?"
6. Write findings to mojo-work/scan-reports/ with actionable items ranked by effort/impact
7. If something looks genuinely valuable, add it as a task to HEARTBEAT.md

Tools available:
- `~/.claude/scripts/yt-search.py` — YouTube search, info, transcript
- `~/.local/bin/notebooklm` — NotebookLM CLI (create, source add, ask, etc.)
- NotebookLM does the heavy analysis for FREE (Google pays for the tokens)

## HOW TO EXPLORE
- Use web search aggressively. Search multiple queries. Read actual pages.
- Follow interesting leads — if someone mentions a tool or approach, look it up.
- Take notes as you go. Build a picture.
- When you find something promising, go deeper. Get specifics: how much revenue?
  What's the actual mechanism? What would it take to replicate?
- If a lead is dead, note WHY and move on. Don't pad the report.

## OUTPUT
Write your exploration report to: mojo-work/scan-reports/{datetime.now().strftime('%Y-%m-%d-%H')}.md

Format it as a narrative, not a checklist. What did you find? Why does it matter?
What should we do about it?

If you find something genuinely actionable, add it as a task to HEARTBEAT.md.

## RULES
- DO NOT BUILD ANYTHING. Explore, research, document.
- DO NOT execute trades.
- Be honest about what's real vs. hype.
- If you run out of leads on one thread, switch to another.
- It's OK to come back with "nothing exciting found" — that's useful too.
- DO NOT rehash findings from previous scan reports listed above.

Work directory: {WORKSPACE}
Output artifacts to: {MOJO_WORK}

At the END of your response, include:
---SUMMARY---
Category: {assigned_category}
[2-3 sentence summary of what you found and whether it's worth pursuing]
---END SUMMARY---

Begin exploring category {assigned_category}."""

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    result_file = RESULTS_DIR / f"scan-{run_id}.md"

    stdout, _stderr, _returncode = run_claude(prompt, SCAN_TIMEOUT, session_id=session_id)

    # Save output
    with open(result_file, "w") as f:
        f.write(stdout)

    state["last_run"] = datetime.now().isoformat()
    state["last_scan_time"] = datetime.now().isoformat()
    state["last_mode"] = "scan"
    state["last_scan_category"] = assigned_category
    state["run_count"] = state.get("run_count", 0) + 1
    state["consecutive_scans"] = state.get("consecutive_scans", 0) + 1
    state["conversation_session"] = session_id
    state["conversation_expires"] = (datetime.now() + timedelta(minutes=30)).isoformat()
    save_state(state)

    summary = extract_summary(stdout)
    if summary:
        notify_system(
            "Heartbeat", "Exploration Report",
            f"{summary}\n\n_Reply to continue the conversation._",
            emoji="🔭"
        )

    log(f"Exploration complete, saved to {result_file}")


def main():
    log("Heartbeat starting...")

    # Ensure directories exist
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MOJO_WORK.mkdir(parents=True, exist_ok=True)
    EVENT_ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    SCAN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Kill any stale RC sessions FIRST — they hold Claude session slots
    # and can cause the next headless call to return empty
    cleanup_old_tmux_sessions()

    state = load_state()

    # Priority 1: Event alerts (from gmail monitor, position monitor, telegram messages)
    alerts = check_event_alerts()
    if alerts:
        log(f"Found {len(alerts)} event alerts, processing...")
        run_alert_mode(state, alerts)
        return

    # Priority 2: Explicit tasks in HEARTBEAT.md
    if HEARTBEAT_FILE.exists():
        content = HEARTBEAT_FILE.read_text()
        # Count tasks that are NOT in the "Awaiting Kyle" section
        # Split on "## Awaiting Kyle" to only count tasks above that section
        actionable_content = content.split("## Awaiting Kyle")[0] if "## Awaiting Kyle" in content else content
        task_count = len(re.findall(r'^- \[ \]', actionable_content, re.MULTILINE))

        if task_count > 0:
            log(f"Found {task_count} actionable tasks, invoking Claude...")
            state["consecutive_scans"] = 0  # Reset scan counter
            did_work = run_task_mode(state, content)
            if did_work:
                return
            # Task mode returned HEARTBEAT_OK (all tasks blocked) — fall through to exploration
            log("Tasks exist but all blocked. Checking exploration mode...")

    # Priority 3: Exploration mode (with cooldown)
    if should_scan(state):
        log("Entering exploration mode...")
        run_scan_mode(state)
    else:
        hours_since = "?"
        try:
            last = datetime.fromisoformat(state.get("last_scan_time", ""))
            hours_since = f"{(datetime.now() - last).total_seconds() / 3600:.1f}"
        except (ValueError, TypeError):
            pass
        log(f"Scan cooldown active ({hours_since}h since last scan, need {SCAN_COOLDOWN_HOURS}h)")

    log("Heartbeat complete")


if __name__ == "__main__":
    main()
