# Session Management Template

Include this in skills that involve deep work spanning multiple sessions.

---

## Session Management

This skill involves deep work that may span multiple sessions. Track state so any instance can resume.

### On Launch

1. Get timestamp: `date`
2. Update `Personal-OS-v2/sessions/current-state.md`:

```markdown
## Active Task: [Project Name] — [Skill Name]

**Skill:** [skill-name]
**Project:** [project name]
**Started:** [timestamp from date command]
**Task type:** [category - notes review, writing, research, etc.]

### Working Files
- [list files being used]

### Context
[Brief description of what we're doing]

### Status
- [ ] [checklist of steps if applicable]
```

### On Pause

1. Get timestamp: `date`
2. Update state file:
   - Add `**Paused:** [timestamp] ([reason])`
   - Do NOT update progress yet (we're coming back)

### On Close (End of Session)

1. Get timestamp: `date`
2. Update state file:
   - Add `**Ended:** [timestamp]`
   - Calculate and add `**Duration:** [time minus any pauses]`
   - Add progress summary under `### Progress`
   - Add `### Resume Point` with specific next steps

3. Archive if switching to different work:
   - Copy to `Personal-OS-v2/sessions/archive/[date]-[project]-[task].md`
   - Clear current-state.md or start new task

### On Resume

When user says "resume work on [project]" or "check state file":

1. Read `Personal-OS-v2/sessions/current-state.md`
2. Find the `**Skill:**` field
3. Read that skill's instructions from `~/.claude/skills/[skill-name]/skill.md`
4. Reopen all files listed under `### Working Files`
5. Read the `### Resume Point` or `### Context` section
6. Get timestamp: `date`
7. Update state file: change `**Paused:**` to `**Resumed:** [timestamp]`
8. Brief the user: "Resuming [project]. We were [context]. Ready to continue?"

---

## Usage

To add session management to a skill, add this line near the top:

```markdown
**Session Management:** See `~/.claude/skills/_templates/session-management.md`
```

Then follow the template's on-launch instructions when the skill is triggered.
