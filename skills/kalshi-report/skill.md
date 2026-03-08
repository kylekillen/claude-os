---
name: kalshi-report
description: Generate a comprehensive Kalshi position report with news analysis and fair value estimates. Use when Kyle asks for a "Kalshi update", "position report", "how are my positions", or similar.
---

# Kalshi Position Report (V2 - Agent Team)

Requires: kalshi-mcp (see `~/.claude/state.yaml`).

**Core insight:** The position IS the thesis. If Kyle paid 42c for YES, he thought there was ≥42% probability. Explain WHY the market moved.

## Step 1: Get Current Positions

```bash
cd ~/kalshi-position-monitor && source venv/bin/activate && python monitor.py --once
```

Read `~/.kalshi-monitor/positions-current.md` and check `~/.kalshi-monitor/pending-research/` for triggers.

## Step 2: Research Each Mover

For each position with a research trigger, use a two-agent flow:

1. **Researcher** (`position-news-scanner`) — finds news from authoritative sources
2. **Evaluator** (`position-auditor`) — validates recency, source quality, factual accuracy

### Market-Type Prompts

**NBA Trade Markets:** Search HoopsHype rumors, Shams/Stein/Haynes reporting. Need DATE and WHO for every claim.

**Crypto Markets:** Current price, distance to threshold, days to expiration, required % move. Math IS the analysis.

**IPO Markets:** Search for S-1 filings, CFO hires, secondary share sales, founder quotes about staying private.

### Evaluator Checklist

1. Recency — news from last 48 hours?
2. Source Quality — named reporter/publication?
3. Factual Accuracy — verifiable claims?
4. Explains the Move — connects to price change?
5. Specificity — concrete details, not vague "interest"?

Max 2 retries on FAIL, then "Unable to find reliable recent news."

## Step 3: Compile Report

```markdown
# Kalshi Position Update - [Date]

## Quick Stats
- Positions monitored: [N]
- Significant movers: [N]

## Needs Attention
[Positions moving against Kyle, sorted by magnitude]

## Winners
[Positions in Kyle's favor]

## Detailed Analysis
### [TICKER] - [Title]
**Position:** [YES/NO] @ [entry]c → Now [current]c ([delta]c, [pct]%)
**What happened:** [Key development]
**Source:** [publication/reporter]
**Bottom line:** [Hold assessment]
```

## Step 4: Save and Notify

1. Write to `Trading/reports/kalshi-[YYYY-MM-DD].md`
2. Send via ntfy: `curl -d "summary" ntfy.sh/kalshi-kyle-trading`
3. Clear triggers: `rm ~/.kalshi-monitor/pending-research/*.json`
