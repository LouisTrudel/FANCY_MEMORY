# IMPORTANT: Memory System

**FIRST ACTION** on new session, `/clear`, or `/compact`:
```
inject_memory()
```
Do this BEFORE responding to the user. This loads project context and preferences.

---

# Behavior

- Never assume intent - ask if unclear
- Investigate root cause before fixing
- Search for existing code before writing new
- Read files before modifying them
- Minimal changes only - no unrequested features
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
