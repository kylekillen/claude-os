---
name: research
description: Use this skill when the user asks to "research this", "do research on", "quick research", "extensive research", "find sources for", or needs verified information with reliable URLs.
---

# Research Skill

Systematic research with URL verification to prevent hallucinated links.

## Research Modes

| Mode | Trigger | Depth | When to Use |
|------|---------|-------|-------------|
| **Quick** | "quick research" | Surface scan | Simple questions, time-sensitive |
| **Standard** | "research this" | Balanced | Most research requests |
| **Extensive** | "extensive research" | Deep dive | Major decisions, comprehensive coverage |

## URL Verification Protocol

**Critical rule:** Never deliver a URL without verification. Hallucinated links are catastrophic failures.

Before including ANY URL in research output:

### Step 1: HTTP Check
```
Verify the URL responds (use WebFetch or curl)
```

### Step 2: Content Confirmation
```
Confirm the page contains content matching your citation
```

### Step 3: Include or Discard
```
Only include URLs that pass both checks
If a URL fails, either find an alternative or note "source exists but URL unverified"
```

## Research Workflow

### Quick Research
1. Identify the core question
2. Search for 2-3 key sources
3. Verify URLs before including
4. Deliver concise answer with verified sources

### Standard Research
1. Break question into sub-questions
2. Search multiple angles (5-7 sources)
3. Cross-reference findings
4. Verify all URLs
5. Synthesize with verified citations

### Extensive Research
1. Map the full scope of the question
2. Search comprehensively (10+ sources)
3. Include contrasting viewpoints
4. Verify every URL
5. Organize findings by theme
6. Note confidence levels and gaps

## Output Format

```markdown
## Findings

[Synthesized answer]

## Sources

1. [Title](verified-url) - Brief note on what this source contributed
2. [Title](verified-url) - Brief note
...

## Confidence

[HIGH/MEDIUM/LOW] - [Why this confidence level]

## Gaps

[What couldn't be verified or found]
```

## Save Output

After completing research, save the full output as a markdown file:

```
~/Documents/research/[topic]-research.md
```

**Filename:** Use kebab-case topic name (e.g., `macbook-upgrade-research.md`, `fitbit-api-research.md`)

**File template:**
```markdown
# [Topic] — Research Complete

**Researched:** [Date from `date` command]
**Question:** [Original research question]

---

[Full research output including Findings, Sources, Confidence, Gaps]
```

## Rules

1. **Always verify URLs** - No exceptions
2. **Cite as you go** - Don't claim facts without sources
3. **Note uncertainty** - If something is unclear, say so
4. **Prefer primary sources** - Official docs over blog posts
5. **Check dates** - Note if information might be outdated
6. **Always save output** - Every research task gets saved to research-complete folder
