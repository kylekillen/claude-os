---
name: install-topic-monitor
description: Install background topic monitoring with proactive alerts
version: 1.0.0
installs:
  - topic-monitor-script
  - alert-integration
requires:
  bins: ["python3"]
---

# Install: Topic Monitor

## What This Installs

- Background monitoring script that watches for developments on specified topics
- Integrates with ntfy for push alerts when something important happens
- Topics: Kalshi market events, screenplay industry news, AI/Claude updates, prediction market developments

## Steps

### 1. Create Monitor Script

Write `~/.claude/scripts/topic-monitor.py` that:
- Accepts a list of topics/keywords to watch
- Periodically searches web for new developments
- Scores relevance against interest weights
- Sends ntfy alerts for high-scoring matches
- Stores seen articles to avoid duplicates

### 2. Configure Topics

Create `~/.config/personal-os/monitor-topics.yaml`:
```yaml
topics:
  - name: "Kalshi prediction markets"
    keywords: ["kalshi", "prediction market regulation", "CFTC prediction"]
    weight: 1.5
  - name: "Claude Code updates"
    keywords: ["claude code", "anthropic release", "claude update"]
    weight: 1.3
  - name: "Screenplay market"
    keywords: ["spec script sale", "screenplay market", "WGA"]
    weight: 1.0
```

### 3. Add to Heartbeat

Add topic-monitor as a heartbeat task that runs every 4 hours.

### 4. Verify

```bash
python3 ~/.claude/scripts/topic-monitor.py --once --verbose
```

## Usage

Runs automatically via heartbeat daemon. Sends alerts to ntfy when important developments are detected.
