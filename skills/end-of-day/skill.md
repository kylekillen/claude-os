---
name: end-of-day
description: Use this skill when Kyle says "end of day", "wrap up", "let's close out", "EOD", or similar end-of-day phrases.
---

# End of Day Routine

Daily wrap-up. Requires: fitbit, gmail, google-drive (see `~/.claude/state.yaml`).

## Step 1: Check for Workout Photo

```bash
ls "Personal-OS-v2/" | grep -iE "(screenshot|\.(jpg|jpeg|png|heic)$)"
```

If photo exists → use `/workout-log`. If not → move on.

## Step 2: Fitbit

Sync Fitbit data (see `install/fitbit` for commands). Report: steps, active minutes, resting HR.

## Step 3: Review Morning Summary

Read today's entry from `sessions/daily-summaries.md`. What got done? What didn't? What rolls?

## Step 4: Update Summary

Edit today's entry: mark completed, note rollovers, add context for tomorrow.

## Step 5: Jot File

```bash
python3 "Personal-OS-v2/system/scripts/google_api.py" drive export 1HRm1ysZmOCCy5xPXiH8YTjzon7ga2nSrZHeQRUnLcPU /tmp/jot-file.md
```

Add new items to `drafts/jot-file-ingested.md`. Remind Kyle to clear the Google Doc.

## Step 6: Secrets Backup Check

```bash
DRIVE="Personal-OS-v2"
echo "=== Secrets Sync Check ==="
for p in family-gifts kalshi-bot spotify-edge; do
  [ -f ~/$p/.env ] && (diff -q ~/$p/.env "$DRIVE/Code/$p/secrets/.env" 2>/dev/null && echo "$p: ✓" || echo "$p: ✗ NEEDS BACKUP")
done
echo "OAuth tokens:"
diff -q ~/.config/personal-os/token.json "$DRIVE/system/secrets/oauth-tokens/token.json" 2>/dev/null && echo "  Google: ✓" || echo "  Google: ✗ NEEDS BACKUP"
```

If anything needs backup → do it now.

## Step 7: Tomorrow Preview

```bash
python3 "Personal-OS-v2/system/scripts/google_api.py" tasks list NnRqU2tCdUh4cWR6N2Y4Tw
```

Ask: "Anything to discuss about tomorrow?"

## Step 8: Final Summary

Brief: "Today: [done]. Tomorrow: [top priority]." End clean.
