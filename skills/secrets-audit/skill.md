---
name: secrets-audit
description: Audit all projects for secrets backup compliance. Run at end of day or when checking system health.
---

# Secrets Audit

Verify all local `.env` / `.env.local` files are backed up to Drive.

## Quick Check (End of Day)

Run this to check for drift between local and Drive:

```bash
DRIVE="/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS"

echo "=== Secrets Sync Check ==="

# Type B projects
echo ""
echo "Audio Player (.env.local):"
diff -q ~/audio-player/.env.local "$DRIVE/Audio Player/config/.env.local" 2>/dev/null && echo "  ✓ In sync" || echo "  ✗ OUT OF SYNC or missing"

echo ""
echo "Grocery (.env):"
diff -q ~/grocery-optimizer/.env "$DRIVE/Grocery/config/.env" 2>/dev/null && echo "  ✓ In sync" || echo "  ✗ OUT OF SYNC or missing"

# Type C projects (Code/)
echo ""
echo "Code/ projects:"
for project in family-gifts kalshi-bot spotify-edge; do
  if [ -f ~/$project/.env ]; then
    diff -q ~/$project/.env "$DRIVE/Code/$project/secrets/.env" 2>/dev/null && echo "  $project: ✓ In sync" || echo "  $project: ✗ OUT OF SYNC"
  fi
done

echo ""
echo "=== Done ==="
```

## If Out of Sync

Back up the local file to Drive:

```bash
# For Type B (division projects):
cp ~/audio-player/.env.local "$DRIVE/Audio Player/config/.env.local"
cp ~/grocery-optimizer/.env "$DRIVE/Grocery/config/.env"

# For Type C (Code/ projects):
cp ~/project/.env "$DRIVE/Code/project/secrets/.env"
```

## Full Structural Audit (Monthly)

For a comprehensive check of all projects against new-project conventions:

1. Read `system/decisions/project-audit-2026-01-22.md` for the template
2. Check each division has:
   - _index.md with Personal OS Integration section
   - Correct project type annotation
   - For Type B: symlinks intact
   - For Type C: secrets backed up, GitHub URL in Code/_index.md

## Projects to Check

### Type B (Symlinks + Secrets in Division)
| Project | Local | Secrets Location |
|---------|-------|------------------|
| Audio Player | ~/audio-player | Audio Player/config/.env.local |
| Grocery | ~/grocery-optimizer | Grocery/config/.env |
| Trading | ~/claude-hedge-fund | Uses Code/kalshi-bot secrets |

### Type C (GitHub + Secrets in Code/)
| Project | Local | Secrets Location |
|---------|-------|------------------|
| family-gifts | ~/family-gifts | Code/family-gifts/secrets/.env |
| kalshi-bot | ~/kalshi-bot | Code/kalshi-bot/secrets/.env |
| spotify-edge | ~/spotify-edge | Code/spotify-edge/secrets/.env |
| slc-flight-tracker | ~/slc-flight-tracker | (no secrets) |
| volleyball-pipeline | ~/volleyball-pipeline | (no secrets) |

## When This Audit Was Created

January 22, 2026 - Found 4 projects with unbackup .env files during manual audit.
