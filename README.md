# FANCY_MEMORY

Persistent memory system for Claude Code. Context survives across sessions.

## Quick Start

```bash
git clone https://github.com/LouisTrudel/FANCY_MEMORY.git my-project
cd my-project
claude
```

Memory accumulates automatically as you work.

## How It Works

```
You work → Hooks log & compress → Memory tiers fill
New session → inject_memory() → Context restored
```

**Three memory layers:**
| Layer | What it captures | Compression |
|-------|------------------|-------------|
| Episodic | Events, actions, discoveries | tier0 → tier1 → tier2 |
| Narrative | Story of work sessions | draft → chapter → book |
| Semantic | Facts, preferences, project state | Extracted from chapters |

## Structure

```
├── .claude/
│   ├── settings.json       # Hooks config
│   ├── mcp_server.py       # inject_memory() tool
│   ├── hooks/              # Auto-log, compress, extract
│   └── memory/             # Accumulates as you work
│       ├── episodic/
│       ├── narrative/
│       └── semantic/
├── .mcp.json               # MCP server reference
└── CLAUDE.md               # Behavior guidance
```

## What Gets Tracked

- **Tracked (template):** hooks, configs, CLAUDE.md
- **Ignored (per-project):** memory data, whitepaper.md, roadmap.md, logs

## CLAUDE.md Behavior

Built-in guidance for:
- Memory injection at session start
- Delegation (simple → execute, complex → explore/plan)
- Documentation (whitepaper + roadmap when appropriate)
- Efficiency (minimal reads, concise responses)

## License

MIT
