---
name: contact-log-meeting
description: Log meeting notes after a call or meeting. Use when Kyle says "just got off a call with [person]", "meeting notes for [person]", "log that I talked to [person]", or recaps a conversation.
---

# Log Meeting Notes

Capture what was discussed in a meeting so it's available for future reference.

## Trigger Phrases

- "Just got off a call with [person]"
- "Had a meeting with [person]"
- "Log meeting notes for [person]"
- "I talked to [person] about..."
- "Note that [person] and I discussed..."
- Any conversation recap that mentions a person

## How to Execute

When Kyle shares meeting details, extract:
1. **Who** - The person(s) involved
2. **What** - Summary of what was discussed
3. **Subject** (optional) - Meeting title if mentioned

Then log it:

```bash
cd "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts"
python3 contacts_cli.py log-meeting --email="person@email.com" --summary="Summary of discussion" --subject="Meeting title"
```

If you only have a name, find the email first:

```bash
python3 contacts_cli.py lookup "Person Name"
# Get their email from the output, then log
```

## What Gets Stored

1. **Interaction record** - Timestamped entry with the summary
2. **Updated context** - Summary prepended to contact's context field
3. **Interaction count** - Incremented
4. **Last interaction date** - Updated

## Example Flow

**Kyle says:** "Just got off a call with Sarah Chen. We discussed the pilot script timeline. She wants a draft by end of February and wants to schedule a notes call for next week."

**You do:**
1. Look up Sarah Chen to get her email
2. Log the meeting:
```bash
python3 contacts_cli.py log-meeting \
  --email="sarah.chen@studio.com" \
  --summary="Discussed pilot script timeline. She wants draft by end of Feb. Scheduling notes call for next week." \
  --subject="Pilot timeline call"
```

**You respond:** "Logged your call with Sarah Chen. I've noted she wants the pilot draft by end of February and you're scheduling a notes call for next week."

## Multiple Attendees

If the meeting had multiple people, log for each:

```bash
python3 contacts_cli.py log-meeting --email="person1@email.com" --summary="..." --subject="..."
python3 contacts_cli.py log-meeting --email="person2@email.com" --summary="..." --subject="..."
```

## Creating New Contacts

If the person isn't in the system yet:

```bash
python3 contacts_cli.py add --email="new@email.com" --name="New Person" --context="Met in [context]"
python3 contacts_cli.py log-meeting --email="new@email.com" --summary="..."
```
