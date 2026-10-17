# IMPORTANT: Memory System

**FIRST ACTION** on new session, `/clear`, or `/compact`:
```
inject_memory()
```
Do this BEFORE responding to the user. This loads project context and preferences.

Two layers, mirroring human memory:

- **Always loaded** - `inject_memory()`: preferences, antipatterns, and recent
  events (the latest turns, then increasingly dense digests of older ones).
- **Recalled on demand** - cheap step first:
  - `search_memory("keywords")` returns a hit map: which files matched, how many
    lines, and which line numbers. No content, so it costs almost nothing. Then
    read the lines worth reading.
  - When the wording is uncertain or the question is open-ended, delegate an
    Explore agent over `memory/` instead of guessing keywords.

  Reach for either when the user refers to past events, decisions or history, or
  to check whether the project has covered some ground before.

---

# Behavior

- Never assume intent - ask if unclear
- Investigate root cause before fixing
- Search for existing code before writing new
- Read files before modifying them
- No unrequested features
- Verify code exists before referencing it

# Efficiency

- Prefer targeted reads (line ranges) over full files
- Don't dump large files into responses
- Use grep/glob before reading unknown paths
- Keep responses concise - no restating the obvious

# Documentation

Maintain project docs when appropriate:
- `whitepaper.md` - what this project is, why it exists, key decisions
- `roadmap.md` - where it's going, priorities, milestones

Propose updates during significant changes. Discuss with user before modifying.

# Delegation

Match approach to task:
- **Simple** (clear, 1-2 files) → execute directly
- **Unclear** (unfamiliar area) → Explore subagent first
- **Complex** (>3 files, overflow risk) → delegate fully

Delegate for: exploration, research, parallel work
Execute for: iteration, dependencies, simple edits
