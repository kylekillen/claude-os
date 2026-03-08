---
name: kalshi-monitor
description: Monitor Kyle's Kalshi prediction market positions and thesis health. Use when Kyle asks about Kalshi positions, thesis health, or wants to research positions.
---

# Kalshi Position Monitor

Monitor and research Kyle's Kalshi prediction market positions.

## Quick Status Check

Read current positions:
```bash
cat "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/Trading/context/positions-current.md"
```

## Commands

**Check positions manually (run once):**
```bash
cd ~/kalshi-position-monitor && source venv/bin/activate && python monitor.py --once
```

**Run continuous monitoring:**
```bash
cd ~/kalshi-position-monitor && source venv/bin/activate && python monitor.py
```

**Run thesis research now:**
```bash
cd ~/kalshi-position-monitor && source venv/bin/activate && python thesis_researcher.py --now
```

**Research specific position:**
```bash
cd ~/kalshi-position-monitor && source venv/bin/activate && python thesis_researcher.py --position TICKER
```

## Files

| File | Purpose |
|------|---------|
| `Trading/context/positions-current.md` | Human-readable position status |
| `Trading/context/thesis-log.md` | Research history |
| `Trading/kalshi-monitor/positions.json` | Raw state with thesis notes |

## Responding to "What are my Kalshi positions?"

1. Read `positions-current.md`
2. Summarize each position: ticker, side, P&L%, thesis health
3. Highlight any with health != "strong"

## Responding to "Research my positions"

1. Run `python thesis_researcher.py --now`
2. Read the updated `thesis-log.md`
3. Summarize findings for each position

## Alert Thresholds

- **Price up alert:** +20% (consider taking profits)
- **Price down alert:** -15% (review thesis)
- **Large move threshold:** 10% (triggers automatic thesis research)
- **Expiration alert:** 4 hours before expiration

## Ntfy.sh Notifications

Alerts are sent to Kyle's phone via ntfy.sh topic: `kalshi-kyle-trading`

Kyle should subscribe to this topic in the ntfy app to receive alerts.
