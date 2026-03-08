#!/bin/bash
# Mojo Heartbeat Daemon
# Invokes Claude to work on tasks from HEARTBEAT.md
# Supports --resume for context continuity across cycles

set -e

WORKSPACE="${CLAUDE_OS_PROJECT_ROOT:-$HOME}"
LOGFILE="$HOME/mojo-daemon/logs/heartbeat.log"
RESULTS_DIR="$HOME/mojo-daemon/results"
MOJO_WORK="$WORKSPACE/mojo-work"
SESSION_FILE="$HOME/mojo-daemon/session-id.txt"
SESSION_MAX_AGE=604800  # 7 days in seconds

# Ensure directories exist
mkdir -p "$RESULTS_DIR" "$MOJO_WORK"

# Timestamp
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
RUN_ID=$(date '+%Y%m%d-%H%M%S')

echo "[$TIMESTAMP] Heartbeat starting..." >> "$LOGFILE"

# Check if HEARTBEAT.md exists
if [ ! -f "$WORKSPACE/HEARTBEAT.md" ]; then
    echo "[$TIMESTAMP] No HEARTBEAT.md found, skipping" >> "$LOGFILE"
    exit 0
fi

# Check if HEARTBEAT.md has actual tasks (not just headers)
TASK_COUNT=$(grep -c "^\- \[ \]" "$WORKSPACE/HEARTBEAT.md" 2>/dev/null || echo "0")
if [ "$TASK_COUNT" -eq 0 ]; then
    echo "[$TIMESTAMP] No unchecked tasks in HEARTBEAT.md, skipping" >> "$LOGFILE"
    exit 0
fi

echo "[$TIMESTAMP] Found $TASK_COUNT tasks, invoking Claude..." >> "$LOGFILE"

# Session resume logic
RESUME_FLAG=""
if [ -f "$SESSION_FILE" ]; then
    SESSION_ID=$(cat "$SESSION_FILE")
    SESSION_MTIME=$(stat -f %m "$SESSION_FILE" 2>/dev/null || echo "0")
    NOW=$(date +%s)
    SESSION_AGE=$((NOW - SESSION_MTIME))

    if [ "$SESSION_AGE" -lt "$SESSION_MAX_AGE" ] && [ -n "$SESSION_ID" ]; then
        RESUME_FLAG="--resume $SESSION_ID"
        echo "[$TIMESTAMP] Resuming session $SESSION_ID (age: ${SESSION_AGE}s)" >> "$LOGFILE"
    else
        echo "[$TIMESTAMP] Session expired (age: ${SESSION_AGE}s), starting fresh" >> "$LOGFILE"
        rm -f "$SESSION_FILE"
    fi
fi

# The heartbeat prompt
PROMPT="You are Mojo, an autonomous coordinator. Read HEARTBEAT.md and work on actionable tasks.

## Parallel Execution Strategy

1. Read HEARTBEAT.md and identify ALL actionable unchecked tasks (not in \"Awaiting Kyle\", not blocked, not future-dated)
2. If there are 2+ independent tasks, **use the Agent tool to spawn subagents in parallel**:
   - Launch each independent task as a separate subagent (subagent_type=\"general-purpose\")
   - Give each subagent a clear, self-contained prompt with the task description and output path
   - Use model=\"sonnet\" for subagents to manage cost (you are the Opus coordinator)
   - Run independent subagents in the SAME message (parallel tool calls)
   - Wait for all subagents to complete, then collect their results
3. If there is only 1 task, do it yourself directly (no subagent needed)
4. After all work completes, update HEARTBEAT.md to mark tasks done

## Subagent Prompt Template

When spawning a subagent for a task, include:
- The exact task description from HEARTBEAT.md
- Work directory: $WORKSPACE
- Output path: $WORKSPACE/mojo-work/[appropriate-filename].md
- Rule: Save artifacts to mojo-work/ folder, never modify Kyle's originals
- Rule: NO external API calls — use web search, file tools, and code execution only
- Rule: For TRADING RESEARCH — document thesis, evidence, counter-evidence. Do NOT build bots or execute trades. Use the template in mojo-work/trading-journal/
- End with a clear summary of what was accomplished

## Coordinator Rules

- **Skip tasks that are blocked** — if a task says \"NEEDS KYLE\", is in the \"Awaiting Kyle\" section, or depends on a future event, skip it
- If genuinely nothing actionable needs attention, just respond: HEARTBEAT_OK
- **Max 3 parallel subagents** per cycle to control token cost
- If more than 3 tasks are actionable, pick the 3 highest priority
- After subagents complete, update HEARTBEAT.md with completion notes for ALL finished tasks
- **CPU awareness** — check system load before spawning if concerned

Work directory: $WORKSPACE
Output artifacts to: $MOJO_WORK

At the END of your response, include:
---SUMMARY---
[2-3 sentence summary of ALL tasks completed this cycle]
---END SUMMARY---

If any task needs another heartbeat cycle to complete, end with: SESSION_CONTINUE

Begin by reading HEARTBEAT.md and identifying actionable tasks."

# Invoke Claude and capture output
RESULT_FILE="$RESULTS_DIR/$RUN_ID.md"

cd "$WORKSPACE"

# Run Claude with timeout (macOS compatible)
# Use --output-format json to capture session_id, pipe text to result file
JSON_FILE="$RESULTS_DIR/$RUN_ID.json"

if [ -n "$RESUME_FLAG" ]; then
    claude $RESUME_FLAG -p "$PROMPT" --output-format json > "$JSON_FILE" 2>&1 &
else
    claude -p "$PROMPT" --output-format json > "$JSON_FILE" 2>&1 &
fi
CLAUDE_PID=$!

# Wait up to 15 minutes
WAIT_TIME=0
MAX_WAIT=900
while kill -0 $CLAUDE_PID 2>/dev/null; do
    sleep 5
    WAIT_TIME=$((WAIT_TIME + 5))
    if [ $WAIT_TIME -ge $MAX_WAIT ]; then
        kill -9 $CLAUDE_PID 2>/dev/null
        echo "[$TIMESTAMP] Claude timed out after ${MAX_WAIT}s" >> "$LOGFILE"
        exit 1
    fi
done

# Check exit status
wait $CLAUDE_PID
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "[$TIMESTAMP] Claude exited with code $EXIT_CODE" >> "$LOGFILE"
    echo "[$TIMESTAMP] Error output:" >> "$LOGFILE"
    head -20 "$JSON_FILE" >> "$LOGFILE"
    # Still try to extract session_id on failure for next resume
    if [ -f "$JSON_FILE" ]; then
        NEW_SESSION_ID=$(python3 -c "import json,sys; d=json.load(open('$JSON_FILE')); print(d.get('session_id',''))" 2>/dev/null || true)
        if [ -n "$NEW_SESSION_ID" ]; then
            echo "$NEW_SESSION_ID" > "$SESSION_FILE"
        fi
    fi
    exit 1
fi

# Extract session_id and result text from JSON output
if [ -f "$JSON_FILE" ]; then
    NEW_SESSION_ID=$(python3 -c "import json,sys; d=json.load(open('$JSON_FILE')); print(d.get('session_id',''))" 2>/dev/null || true)
    if [ -n "$NEW_SESSION_ID" ]; then
        echo "$NEW_SESSION_ID" > "$SESSION_FILE"
        echo "[$TIMESTAMP] Saved session ID: $NEW_SESSION_ID" >> "$LOGFILE"
    fi

    # Extract text result for the .md file
    python3 -c "import json,sys; d=json.load(open('$JSON_FILE')); print(d.get('result',''))" > "$RESULT_FILE" 2>/dev/null || cp "$JSON_FILE" "$RESULT_FILE"
    rm -f "$JSON_FILE"
fi

# Check for HEARTBEAT_OK response
if grep -q "HEARTBEAT_OK" "$RESULT_FILE"; then
    echo "[$TIMESTAMP] Heartbeat OK - no action needed" >> "$LOGFILE"
    rm "$RESULT_FILE"  # Clean up empty runs
else
    echo "[$TIMESTAMP] Work completed, saved to $RESULT_FILE" >> "$LOGFILE"
fi

echo "[$TIMESTAMP] Heartbeat complete" >> "$LOGFILE"
