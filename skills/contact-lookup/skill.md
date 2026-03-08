---
name: contact-lookup
description: Look up contact information before a meeting or call. Use when Kyle asks "who is [person]", "what do I know about [person]", "look up [person]", "tell me about [person]", or before meetings with external people.
---

# Contact Lookup

Look up a person in the contacts database to prepare for a meeting or refresh Kyle's memory.

## Trigger Phrases

- "Who is [person]?"
- "What do I know about [person]?"
- "Look up [person]"
- "Tell me about [person]"
- "Before my meeting with [person]"
- "Remind me who [person] is"

## How to Execute

Run the contacts CLI lookup:

```bash
cd "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts"
python3 contacts_cli.py lookup "[person's name or email]"
```

## Output Format

Present the information conversationally:

**If contact found with context:**
> "[Name] is at [Company]. [Context from last meeting]. You last spoke on [date] - you've had [N] interactions."

**If contact found but needs interview:**
> "I found [Name] ([email]) but don't have any context yet. They're from your calendar - you've met [N] times. Would you like to tell me about them?"

**If not found:**
> "I don't have anyone matching '[query]' in your contacts. Should I add them?"

## Interview Flow

If the contact needs context (`needs_interview = TRUE`), offer to capture it:

1. Ask: "What do they do? How do you know them?"
2. Store the response:

```bash
cd "/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/system/scripts"
python3 << 'EOF'
from supabase import create_client
from pathlib import Path
import json

creds = json.loads((Path.home() / ".config/personal-os/credentials.json").read_text())
sb = creds["supabase"]
client = create_client(sb["url"], sb["service_role_key"])

# Update contact with context
client.table("contacts").update({
    "context": "CONTEXT_FROM_KYLE",
    "needs_interview": False
}).eq("email", "EMAIL_ADDRESS").execute()

print("Updated contact")
EOF
```

## Pre-Meeting Prep

When Kyle has an upcoming meeting, proactively look up the attendees:

1. Get today's calendar events
2. For each external attendee, look them up
3. Present a brief: "Your 2pm is with [Name] - [context from last meeting]"
