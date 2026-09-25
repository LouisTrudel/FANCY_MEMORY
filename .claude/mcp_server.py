"""
Minimal MCP Server - Memory Injection

Single tool: inject_memory() - loads context from previous sessions
Hooks handle: logging, compression (automatic)
"""

from mcp.server.mcpserver import MCPServer
from pathlib import Path

mcp = MCPServer("workspace")

MEMORY_DIR = Path(".claude/memory")


@mcp.tool()
def inject_memory() -> str:
    """
    Load memory context from previous sessions. Call this at session start.

    Returns episodic history (what happened) + narrative context (the story).
    """
    EPISODIC_DIR = MEMORY_DIR / "episodic"
    NARRATIVE_DIR = MEMORY_DIR / "narrative"
    SEMANTIC_DIR = MEMORY_DIR / "semantic"

    LIMITS = {
        "tier0_tail": 5_000,
        "tier1_full": 15_000,
        "draft_tail": 5_000,
        "chapter_full": 20_000,
        "semantic": 3_000,
    }

    def read_file(path, max_chars=None):
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8").strip()
        if max_chars and len(content) > max_chars:
            return content[:max_chars] + "\n\n[...truncated...]"
        return content

    def read_tail(path, max_chars):
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8").strip()
        if len(content) <= max_chars:
            return content
        return "[...earlier content...]\n\n" + content[-max_chars:]

    sections = []

    # Episodic
    tier0 = read_tail(EPISODIC_DIR / "tier0.md", LIMITS["tier0_tail"])
    if tier0:
        sections.append(f"## Recent Events\n{tier0}")

    tier1 = read_file(EPISODIC_DIR / "tier1.md", LIMITS["tier1_full"])
    if tier1:
        sections.append(f"## Event History\n{tier1}")

    # Narrative
    draft = read_tail(NARRATIVE_DIR / "draft.md", LIMITS["draft_tail"])
    if draft:
        sections.append(f"## Current Session\n{draft}")

    chapter = read_file(NARRATIVE_DIR / "chapter.md", LIMITS["chapter_full"])
    if chapter:
        sections.append(f"## Story So Far\n{chapter}")

    # Semantic
    if SEMANTIC_DIR.exists():
        for md_file in SEMANTIC_DIR.glob("*.md"):
            content = read_file(md_file, LIMITS["semantic"])
            if content:
                sections.append(f"## {md_file.stem.title()}\n{content}")

    if not sections:
        return "No memory context yet. Start working and it will accumulate."

    total = sum(len(s) for s in sections)
    return f"# Memory Context (~{total//4} tokens)\n\n" + "\n\n---\n\n".join(sections)


if __name__ == "__main__":
    mcp.run(transport="stdio")
