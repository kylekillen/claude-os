---
name: move-to-future-projects
description: Use this skill when Kyle says "move to future projects", "send to future projects", "make that a future project", or wants to promote a jot file item to a project file.
---

# Move to Future Projects

Takes an item from the jot file and creates a dedicated markdown file in the future projects folder.

## Steps

1. **Identify the item** — Get the item number(s) and content from the jot file

2. **Create the markdown file** in:
   ```
   /Users/kylekillen/Library/CloudStorage/GoogleDrive-kyle.killen@gmail.com/My Drive/Personal-OS-v2/drafts/future-projects/
   ```

   Filename: kebab-case version of the project name (e.g., `grocery-list-optimizer.md`)

3. **Use this template:**
   ```markdown
   # [Project Name]

   **From jot file:** [Date]

   ## Original Idea
   [Content from jot file]

   ## To Research
   - [needs spec]
   ```

4. **Remove the item** from `drafts/jot-file-ingested.md`

5. **Confirm** — Tell Kyle the file was created and where

## Notes

- The project file is a stub until Kyle specs it out
- When ready for research, Kyle moves it to `drafts/research-queue/`
- Multiple items can be moved at once
