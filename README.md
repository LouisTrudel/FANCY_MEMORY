# FANCY_MEMORY

Persistent memory system for Claude Code. Context survives across sessions.

Hooks capture each turn, compress it in tiers as it ages, and an MCP tool injects the
result at the start of the next session.

## Requirements

- Python 3.10+ (the code uses `tuple[bool, str]` / `str | None` annotations)
- Claude Code CLI
- The `mcp` package:

```bash
pip install mcp
```

Without `mcp` the server does not start and Claude Code shows **no error** — the tool
is simply absent. See Troubleshooting.

OS- and terminal-agnostic: Windows, macOS and Linux, any terminal. Nothing is tied to
an editor.

## Quick Start

```bash
git clone https://github.com/LouisTrudel/FANCY_MEMORY.git my-project
cd my-project
pip install mcp
claude
```

Memory accumulates automatically as you work. `CLAUDE.md` instructs Claude to call
`inject_memory()` as its first action in a new session, and after `/clear` or
`/compact`.

## How It Works

```
You work  ->  hooks log every turn  ->  thresholds trip  ->  compression cascades
New session  ->  inject_memory()  ->  context restored
```

**Three layers:**

| Layer | What it captures | Cascade |
|-------|------------------|---------|
| Episodic | Tagged events: `[BUILT]`, `[FIXED]`, `[DECIDED]`, `[DISCOVERED]`, … | `tier0 → tier1 → tier2 → …` |
| Narrative | Prose story of work sessions | `draft → chapter → book → collection` |
| Semantic | Preferences, antipatterns, emergent skills | extracted on `draft → chapter` |

**Compression keeps the newer half.** When a file trips its threshold, only the older
half is summarised into the next level; the newer half stays put. No level is ever left
empty, and recent detail survives longer.

**Semantic extraction runs in three levels**, triggered when the draft compresses:

```
Level 0  preferences.md + antipatterns.md     (raw accumulation)
Level 1  skillTree.md                         (when prefs+anti > 8,000 bytes)
Level 2  skills/*.md                          (when skillTree > 10,000 bytes)
```

## Structure

```
├── .claude/
│   ├── settings.json       # Hook registrations (5 events)
│   ├── mcp_server.py       # inject_memory(), search_memory(query)
│   ├── hooks/
│   │   ├── all_hooks.py    # Capture every turn, trigger compression
│   │   ├── compress.py     # Tier/level cascade, thresholds, validation
│   │   ├── semantic.py     # Preference / antipattern / skill extraction
│   │   └── inject.py       # Assemble the context to inject
│   └── memory/             # Accumulates as you work (gitignored)
│       ├── episodic/       # tier0.md, tier1.md, …
│       ├── narrative/      # draft.md, chapter.md, book.md, collection.md
│       └── semantic/       # preferences.md, antipatterns.md, skillTree.md, skills/
├── .mcp.json               # MCP server registration
└── CLAUDE.md               # Behaviour guidance
```

## Tuning

Everything below is a constant at the top of its file.

**Compression thresholds** (`hooks/compress.py`)

| File | Trips at |
|---|---|
`tier0` | 20,000 bytes |
`tier1` | 15,000 |
`tierN` (N≥2) | 15,000 + N×5,000 |
`draft` | 25,000 |
`chapter` | 20,000 |
`book` | 50,000 |
`collection` | 100,000 (effectively archive) |

**Compression rate** (`hooks/compress.py`) — each compression is one `claude -p` call,
so these are cost controls:

```python
COOLDOWN_SECONDS = 60     # gate on STARTING a run, not between files in one
MAX_PER_HOUR = 20         # safety valve against runaway spend
MAX_PER_RUN = 4           # drain a backlog in one pass
```

**Semantic** (`hooks/semantic.py`)

```python
PREFS_ANTI_THRESHOLD = 8_000    # trigger Level 1
SKILL_TREE_THRESHOLD = 10_000   # trigger Level 2
MIN_SKILL_ENTRIES = 5           # entries needed before a skill file is created
PREFS_CAP = 40
ANTIPATTERNS_CAP = 30
```

**Injection** (`hooks/inject.py`) — `LIMITS` are **per-file** caps, not a total budget:

```python
LIMITS = {"tier0_tail": 5_000, "tier1_full": 15_000,
          "draft_tail": 5_000, "chapter_full": 20_000, "semantic": 3_000}

SEMANTIC_EXCLUDE = {"skillTree"}   # stems kept out of injection
INJECT_SKILLS = False              # skill files are NOT injected
```

Auto-generated skill files are deliberately not injected. Their count is unbounded, and
each one used to add up to 1KB to *every* session start. They stay on disk, readable on
demand and through `search_memory()`.

**Debug capture** (`hooks/all_hooks.py`)

```python
DEBUG_EVENTS = {"Stop", "UserPromptSubmit"}   # the only events that drive memory
DEBUG_MAX_BYTES = 10_000_000                  # rotate past this; 0 disables entirely
DEBUG_MAX_PAYLOAD = 4_000                     # truncate any single payload
```

`hooks/events.log` is a human debugging aid. Nothing in the memory system reads it, so
it is safe to delete at any time.

## Manual Use

```bash
python .claude/hooks/inject.py            # full context (default)
python .claude/hooks/inject.py minimal    # tier1 + semantic only
python .claude/hooks/inject.py episodic   # one layer: episodic|narrative|semantic
python .claude/hooks/compress.py          # force a cascade check now
```

Drop a file named `.paused` in `.claude/hooks/` to disable capture without unregistering
the hooks. Delete it to resume.

## What Gets Tracked

- **Tracked:** hooks, `mcp_server.py`, configs, `CLAUDE.md`, `README.md`
- **Ignored:** all memory data, logs, compression state, `whitepaper.md`, `roadmap.md`,
  `PLAN_memory_improvements.md`, `requirements.txt`, `.reference/`, backups

A clone therefore starts with an empty memory and accumulates its own.

## CLAUDE.md Behaviour

Built-in guidance for:

- Memory injection at session start, and after `/clear` or `/compact`
- Delegation (simple → execute, unclear → explore, complex → delegate)
- Documentation (whitepaper + roadmap when appropriate)
- Efficiency (targeted reads, concise responses)

## Troubleshooting

**The memory tool doesn't exist in my session.** Two silent causes:

1. `mcp` isn't installed — `pip install mcp`.
2. The server name in `.mcp.json` collides with a name Claude Code reserves. It ships as
   `fancy_memory`. **Do not rename it to `workspace`** — that name is reserved, and the
   server is skipped with no error. If you rename it, update all three places: the key in
   `.mcp.json`, the `MCPServer(...)` call in `mcp_server.py`, and any
   `mcp__<name>__inject_memory` entries in `.claude/settings.local.json`.

Check with `claude mcp list`.

**A file is way over its threshold and never compresses.** It is probably queued rather
than stuck: a run compresses at most `MAX_PER_RUN` files, then stops. Check
`hooks/compress.log`. Half-split also only halves a file per pass, so something far over
threshold needs several passes.

**Compression keeps failing.** Look for `Claude CLI failed` or `REJECTED` in
`hooks/compress.log`. Rejected summaries leave the source intact and park the input in a
`.pending.md` sidecar, so nothing is lost. A file enormously over threshold (10×+) may be
too large for one CLI call — rotate it aside manually and let the system start fresh.

**`events.log` is huge.** Expected if you widened `DEBUG_EVENTS`. Tool-call events carry
entire payloads. Delete the file; nothing depends on it.

## License

MIT
