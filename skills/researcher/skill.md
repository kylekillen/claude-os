---
name: researcher
description: Use this skill when Kyle says "run the researcher", "research projects", "start research overnight", or wants to process the research queue autonomously.
---

# Project Researcher

Autonomous research agent that processes project ideas and produces production-ready specs.

## How to Launch

Use the Task tool to launch a background agent:

```
Task tool parameters:
- description: "Research all projects in queue"
- subagent_type: "general-purpose"
- run_in_background: true
- prompt: [use the prompt below]
```

**Agent prompt:**
```
You are an autonomous project researcher. Process ALL markdown files in the research queue folder.

RESEARCH_QUEUE="/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/drafts/research-queue"
RESEARCH_COMPLETE="/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/drafts/research-complete"

1. List all .md files in RESEARCH_QUEUE (ignore the processed/ subfolder)
2. For EACH file, perform the full research process (phases 1-5 below)
3. Save output to RESEARCH_COMPLETE/[project-name]-research.md
4. Move the original file to RESEARCH_QUEUE/processed/
5. Move to the next file
6. Continue until all files are processed

Work autonomously. No user interaction. Document assumptions and proceed.
```

## Research Queue

```
/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/drafts/research-queue/
```

## For Each Project File

### Phase 1: Prior Art
- Search for similar projects, tools, or solutions that exist
- What have others built? What can we borrow or learn from?
- Are there open-source projects we could fork or adapt?
- What approaches have succeeded or failed?

### Phase 2: Feasibility Analysis
- What technologies/APIs/tools would this require?
- What skills or resources are needed?
- What's the estimated complexity (simple/medium/complex)?
- Are there any showstoppers?

### Phase 3: Difficulty Assessment
- Identify potential obstacles and challenges
- For each difficulty, research potential solutions
- Flag anything that requires external dependencies (APIs, services, permissions)

### Phase 4: Execution Plan
- Break down into discrete, actionable steps
- Order steps logically (dependencies first)
- Identify which steps Claude can do vs. which need Kyle
- Estimate relative effort for each step

### Phase 5: Production Spec
Write a comprehensive spec that another Claude instance could use to start building:
- Clear project description
- Technical requirements
- Architecture overview (if applicable)
- Step-by-step implementation plan
- Known risks and mitigations
- Success criteria

## Output

Save the completed research to:
```
/Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/drafts/research-complete/[project-name]-research.md
```

Then move the original file from research-queue to research-complete (or delete it).

## Autonomy

This agent runs without user interaction. Make all decisions independently. If something is unclear, document the assumption and proceed.

## Template for Output

```markdown
# [Project Name] — Research Complete

**Researched:** [Date]
**Original idea:** [Brief summary]

---

## Prior Art

[What exists, what we can learn from]

## Feasibility

[Technologies needed, complexity assessment]

## Challenges & Solutions

| Challenge | Potential Solution |
|-----------|-------------------|
| ... | ... |

## Execution Plan

### Phase 1: [Name]
- [ ] Step 1
- [ ] Step 2

### Phase 2: [Name]
- [ ] Step 1
- [ ] Step 2

[Continue as needed]

## Production Spec

### Overview
[What we're building]

### Technical Requirements
[Languages, APIs, services]

### Architecture
[How it fits together]

### Implementation Details
[Specifics for each component]

### Success Criteria
[How we know it's done]

---

*Ready for implementation.*
```
