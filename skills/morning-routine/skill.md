---
name: morning-routine
description: Use this skill when Kyle says "good morning", "morning routine", "start the day", "what's on today", or similar morning check-in phrases.
---

# Morning Routine

Daily startup. Requires: fitbit, gmail, google-calendar, google-drive (see `~/.claude/state.yaml`).

## Step 1: Fitbit

Sync Fitbit data (see `install/fitbit` for commands). Report sleep briefly (duration, quality).

## Step 2: Calendar

Use MCP calendar tools or `google_api.py calendar today`. Summarize what's scheduled.

## Step 3: Email

Use MCP Gmail tools. Priority tiers:
- **Show details:** `IMPORTANT` label
- **Summarize:** `CATEGORY_PERSONAL` without `IMPORTANT`
- **Count only:** Updates, Social, Promotions, Forums
- **Red flags:** Dates in next 3 days, attachments from known contacts, "urgent/deadline/notes/review"

## Step 4: Jot File

```bash
python3 "Personal-OS-v2/system/scripts/google_api.py" drive export 1HRm1ysZmOCCy5xPXiH8YTjzon7ga2nSrZHeQRUnLcPU /tmp/jot-file.md
```

Add new items to `drafts/jot-file-ingested.md` with timestamp. Ask: "Any urgent for today, or defer?"

## Step 5: Tasks

```bash
SCRIPT="Personal-OS-v2/system/scripts/google_api.py"
echo "=== HIGHEST IMPACT ===" && python3 "$SCRIPT" tasks list NnRqU2tCdUh4cWR6N2Y4Tw
echo "=== TODAY ===" && python3 "$SCRIPT" tasks list MTc4MzgzMTg5MTU0NDQ2NDYwMTM6MDow
```

## Step 6: Set the Day

Summarize calendar + tasks. Ask: "Anything to add or adjust?"
Archive summary to `sessions/daily-summaries.md`. Kyle is Mountain Time.
