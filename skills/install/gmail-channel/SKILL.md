---
name: install-gmail-channel
description: Install Gmail as an event trigger channel (email → Claude action)
version: 1.0.0
installs:
  - gmail-polling-daemon
  - email-trigger-routing
requires:
  installed: ["gmail"]
---

# Install: Gmail as Trigger Channel

## What This Installs

- Email-as-event-source: incoming emails can trigger Claude actions automatically
- Polling loop watches for emails matching filters (label, sender, subject prefix)
- SQLite state tracking prevents re-processing
- Separate from tool-mode Gmail (which is already installed)

## Steps

### 1. Create Polling Script

Write `~/.claude/scripts/gmail-channel.py` that:
1. Polls Gmail every 5 minutes for new messages matching filters
2. Tracks processed message IDs in SQLite
3. Routes matching emails to appropriate handlers:
   - `from:*@dewwealth.com` → Financial alert
   - `subject:Notes` → Notes review workflow
   - `subject:Urgent` → ntfy push notification
4. Logs actions to `~/.claude-mem/logs/gmail-channel.log`

### 2. Configure Filters

Create `~/.config/personal-os/gmail-filters.yaml`:
```yaml
filters:
  - name: "Financial advisor"
    query: "from:carter@dewwealth.com"
    action: "notify"
    priority: "high"
  - name: "Producer notes"
    query: "subject:notes from:known-producers"
    action: "flag-for-review"
  - name: "Urgent"
    query: "label:IMPORTANT newer_than:1h"
    action: "notify"
```

### 3. Add to Heartbeat or launchd

Run as periodic task (every 5 minutes via launchd or every heartbeat cycle).

### 4. Verify

```bash
python3 ~/.claude/scripts/gmail-channel.py --once --verbose
```

## Usage

Runs automatically. When a matching email arrives, it triggers the configured action (notification, flag for review, or direct processing).
