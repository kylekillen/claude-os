# Writers Room

A swarm of AI agents with distinct personalities collaborate to solve story problems.

**V2 Compliant:** This skill is division-aware and persists state to Supabase.

## How It Works

**Round 1: Independent Proposals**
Three agents work in parallel, each approaching the problem from their perspective:
- **Fixer**: Solution-oriented, proposes concrete fixes
- **Storyteller**: Draws on analogies and real-world examples
- **Dr. No**: Finds holes, questions logic, stress-tests ideas

**Round 2: Reactions**
Each agent sees the others' proposals and responds:
- Fixer adapts based on Dr. No's critiques
- Storyteller grounds the Fixer's solutions in precedent
- Dr. No evaluates whether objections were addressed

**Round 3: Synthesis**
A Showrunner agent ranks the top 5 solutions based on quality, feasibility, and narrative satisfaction.

## Usage

When Kyle says "writers room" or presents a story problem to brainstorm:

### Step 0: Get Division Context

**CRITICAL:** Before starting, get the current division context.

```python
from supabase import create_client
import json

# Load credentials
creds = json.loads((Path.home() / ".config/personal-os/credentials.json").read_text())
sb = creds["supabase"]
supabase = create_client(sb["url"], sb["service_role_key"])

# Get current division from conversation context
# If not clear, ask Kyle which project this is for
DIVISION_NAME = "Project Name"  # e.g., "Imposter Syndrome"

result = supabase.table('pos_divisions').select('id, name, path').ilike('name', f'%{DIVISION_NAME}%').execute()
if result.data:
    DIVISION_ID = result.data[0]['id']
    DIVISION_PATH = result.data[0]['path']
    print(f"Working on: {result.data[0]['name']} ({DIVISION_ID})")
else:
    print(f"Division not found: {DIVISION_NAME}")
```

### Step 1: Clarify the Problem

Make sure you understand:
- What story/project is this for? (confirm division)
- What's the specific problem or question?
- Any constraints (genre, tone, existing plot points that can't change)?

### Step 2: Load Agent Weights

```python
# Agent weights are global (represent Kyle's taste across all projects)
result = supabase.table('pos_state').select('value').eq('division_id', '4fbfcc45-4700-419c-85e1-8a698b044868').eq('key', 'writers_room_agents').execute()

if result.data:
    agents = result.data[0]['value']
else:
    # Default weights
    agents = {
        "fixer": {"weight": 1.0, "wins": 0, "losses": 0, "contributions": []},
        "storyteller": {"weight": 1.0, "wins": 0, "losses": 0, "contributions": []},
        "dr_no": {"weight": 1.0, "wins": 0, "losses": 0, "contributions": []}
    }
```

### Step 3: Run Round 1 (Parallel)

Launch 3 background agents using the Task tool with `run_in_background: true`:

**CRITICAL:** All agent prompts must begin with this line to prevent refusal:
```
This is NOT a coding task - this is creative brainstorming for a TV/film project.
```

**Fixer Agent Prompt:**
```
This is NOT a coding task - this is creative brainstorming for a TV/film project.

You are a Fixer in a writers room. Read ~/.claude/skills/writers-room/prompts/fixer.md for personality.

STORY PROBLEM:
[Insert the problem]

PROJECT CONTEXT:
[Insert relevant context from the division's CONTEXT.md or recent state]

Propose 2-3 concrete solutions in 1-2 paragraphs each. Be specific and actionable.
```

**Storyteller Agent Prompt:**
```
This is NOT a coding task - this is creative brainstorming for a TV/film project.

You are a Storyteller in a writers room. Read ~/.claude/skills/writers-room/prompts/storyteller.md for personality.

STORY PROBLEM:
[Insert the problem]

PROJECT CONTEXT:
[Insert relevant context]

Share relevant analogies or real-world stories that illuminate solutions. 1-2 paragraphs each.
```

**Dr. No Agent Prompt:**
```
This is NOT a coding task - this is creative brainstorming for a TV/film project.

You are a Dr. No in a writers room. Read ~/.claude/skills/writers-room/prompts/dr-no.md for personality.

STORY PROBLEM:
[Insert the problem]

PROJECT CONTEXT:
[Insert relevant context]

Identify the trickiest part of this problem - what makes it hard? Poke holes in obvious solutions. If you have a fix, propose it. 1-2 paragraphs.
```

Use `model: "sonnet"` for Round 1 agents.

### Step 4: Collect Round 1 Results

Wait for all 3 agents to complete. Read their outputs.

### Step 5: Run Round 2 (Parallel)

Launch 3 new background agents, each seeing all Round 1 responses:

**Fixer Reaction:**
```
This is NOT a coding task - this is creative brainstorming for a TV/film project.

You are a Fixer. You've seen proposals from your fellow writers:

ORIGINAL PROBLEM:
[Problem]

ROUND 1 PROPOSALS:
- Fixer: [their R1 output]
- Storyteller: [their R1 output]
- Dr. No: [their R1 output]

React to what you've heard. Does the Storyteller's analogy strengthen your idea? Can you address Dr. No's concerns? Revise or defend your solution. 1-2 paragraphs.
```

**Storyteller Reaction:**
```
This is NOT a coding task - this is creative brainstorming for a TV/film project.

You are a Storyteller. You've seen proposals from your fellow writers:

[Same format - show all R1 outputs]

React. Does the Fixer's solution remind you of other stories? Can you ground it further? 1-2 paragraphs.
```

**Dr. No Reaction:**
```
This is NOT a coding task - this is creative brainstorming for a TV/film project.

You are a Dr. No. You've seen proposals and reactions:

[Same format - show all R1 outputs]

Were your concerns addressed? Do new holes emerge? Be honest - if a solution now works, say so. 1-2 paragraphs.
```

Use `model: "sonnet"` for Round 2 agents.

### Step 6: Run Synthesis (Sonnet)

Launch a Showrunner agent with `model: "sonnet"`:

```
You are the Showrunner. Read ~/.claude/skills/writers-room/prompts/showrunner.md for your role.

STORY PROBLEM:
[Problem]

ROUND 1:
Fixer: [output]
Storyteller: [output]
Dr. No: [output]

ROUND 2:
Fixer Reaction: [output]
Storyteller Reaction: [output]
Dr. No Reaction: [output]

AGENT WEIGHTS (for tiebreaking):
Fixer: [weight]
Storyteller: [weight]
Dr. No: [weight]

Synthesize and rank the top 5 solutions.
```

### Step 7: Present to Kyle

Show Kyle the Showrunner's ranked list. Ask:
"Which of these resonates most? Rank them 1-5 so I can calibrate the room."

### Step 7b: Feedback Loop (Optional)

If Kyle has substantive feedback that challenges the room's conclusions:

1. Run Round 4 agents with Kyle's feedback:

```
This is NOT a coding task - this is creative brainstorming for a TV/film project.

You are a [Fixer/Storyteller/Dr. No]. The showrunner has brought back feedback from Kyle:

ORIGINAL PROBLEM:
[Problem]

SHOWRUNNER'S RANKING:
[R3 output]

KYLE'S FEEDBACK:
[Kyle's pushback, defense of ideas, new angles]

Respond to Kyle's feedback. Does it change your position? What new possibilities does it open? 1-2 paragraphs.
```

2. Collect responses and synthesize
3. Present refined proposal to Kyle
4. Repeat until Kyle is satisfied or wants to move on

**When to use the feedback loop:**
- Kyle defends an idea the room rejected
- Kyle identifies flaws in the room's reasoning
- Kyle offers new angles that weren't considered
- Room consensus feels derivative or incomplete

### Step 8: Update Weights & Save State

After Kyle ranks or session concludes:

```python
from supabase import create_client
from datetime import datetime
import json

# Load credentials
creds = json.loads((Path.home() / ".config/personal-os/credentials.json").read_text())
sb = creds["supabase"]
supabase = create_client(sb["url"], sb["service_role_key"])

# === Update Global Agent Weights ===
# For Kyle's #1 pick: add +0.1 to contributing agent(s)
# For Kyle's #5 pick: subtract -0.05 from contributing agent(s)

agents['fixer']['weight'] += 0.1  # Example: if Fixer contributed to #1
agents['fixer']['contributions'].append(f"{datetime.now().strftime('%Y-%m-%d')}: [Description]")

# Save to Personal OS division (global weights)
supabase.table('pos_state').upsert({
    'division_id': '4fbfcc45-4700-419c-85e1-8a698b044868',  # Personal OS
    'key': 'writers_room_agents',
    'value': agents,
    'updated_at': datetime.now().isoformat()
}, on_conflict='division_id,key').execute()

# === Save Session State to Project Division ===
session_state = {
    "task": "Writers room session",
    "question": "[The story problem]",
    "completed": ["List of rounds completed", "Key decisions made"],
    "key_decisions": ["Decision 1", "Decision 2"],
    "current_direction": {
        "concept": "The winning direction",
        "key_insight": "Why it works"
    },
    "agent_weights": {
        "fixer": "+0.1 (reason)" if weight_changed else "no change",
        # etc.
    },
    "updated_at": datetime.now().isoformat()
}

supabase.table('pos_state').upsert({
    'division_id': DIVISION_ID,  # The project we're working on
    'key': 'current_work',
    'value': session_state,
    'updated_at': datetime.now().isoformat()
}, on_conflict='division_id,key').execute()

print(f"Saved session to {DIVISION_NAME}")
```

## State Architecture

| Data | Location | Why |
|------|----------|-----|
| Agent weights | `pos_state` under Personal OS division, key: `writers_room_agents` | Global - represents Kyle's taste preferences |
| Session state | `pos_state` under project division, key: `current_work` | Per-project - what we decided, where we left off |
| Agent personalities | Local files in `prompts/` | Static - don't change |

## File Locations

- Personality prompts: `~/.claude/skills/writers-room/prompts/`
- Legacy agent history: `~/.claude/skills/writers-room/agent-history.json` (migrated to Supabase)
- Legacy sessions: `~/.claude/skills/writers-room/sessions/` (new sessions go to Supabase)

## Notes

- Round 1 and Round 2 agents run in parallel for speed
- **Use Sonnet for all agents** - Haiku refuses creative tasks
- All prompts must start with "This is NOT a coding task" to prevent refusal
- The feedback loop (Step 7b) is often where the best ideas emerge
- When the room cites precedents, check if that makes the idea feel derivative
- Over time, weights should reflect which agent types align with Kyle's taste

## Lessons Learned (2026-01-25)

1. **Question framing matters:** "How do they connect?" is too abstract. Better: "What specific shared passion/moment creates the spark?"
2. **Precedents can backfire:** The room citing The Americans/Killing Eve for "escape routes" made it feel unoriginal
3. **Kyle's feedback can reverse positions:** Dr. No changed from rejecting jazz to endorsing it after Kyle's defense
4. **Forum > matching secrets:** Characters need a space to connect, not secrets that line up one-for-one
