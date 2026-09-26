"""
Minimal MCP Server - Memory Injection

Single tool: inject_memory() - loads context from previous sessions
Hooks handle: logging, compression, skill extraction (automatic)
"""

from mcp.server.mcpserver import MCPServer
from pathlib import Path

mcp = MCPServer("workspace")

MEMORY_DIR = Path(".claude/memory")


@mcp.tool()
def inject_memory() -> str:
    """
    Load memory context from previous sessions. Call this at session start.

    Returns episodic history + semantic knowledge (preferences, antipatterns, skills).
    Skills are referenced in skillTree - read them on-demand when relevant.
    """
    EPISODIC_DIR = MEMORY_DIR / "episodic"
    SEMANTIC_DIR = MEMORY_DIR / "semantic"

    LIMITS = {
        # Episodic - cascade until budget
        "episodic_budget": 10_000,
        # Semantic - core files + skill tree (skills are on-demand)
        "preferences": 3_000,
        "antipatterns": 2_000,
        "skill_tree": 2_000,
    }

    def read_file(path, max_chars=None):
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8").strip()
        if max_chars and len(content) > max_chars:
            return content[:max_chars] + "\n\n[...truncated...]"
        return content

    def cascade_episodic(budget):
        """Read episodic tiers until budget reached, newest first."""
        result = []
        remaining = budget

        # Start with tier0 (most recent), then tier1, tier2...
        for n in range(10):  # Safety limit
            tier_path = EPISODIC_DIR / f"tier{n}.md"
            if not tier_path.exists():
                break

            content = read_file(tier_path)
            if not content:
                continue

            if len(content) <= remaining:
                result.append(content)
                remaining -= len(content)
            else:
                # Take tail of this tier to fill remaining budget
                result.append(content[-remaining:])
                break

        return "\n\n---\n\n".join(result) if result else ""

    sections = []

    # === EPISODIC (cascaded) ===
    episodic = cascade_episodic(LIMITS["episodic_budget"])
    if episodic:
        sections.append(f"## Recent Events\n{episodic}")

    # === SEMANTIC ===

    # Core preferences (always inject)
    prefs = read_file(SEMANTIC_DIR / "preferences.md", LIMITS["preferences"])
    if prefs:
        sections.append(f"## Preferences\n{prefs}")

    # Core antipatterns (always inject)
    anti = read_file(SEMANTIC_DIR / "antipatterns.md", LIMITS["antipatterns"])
    if anti:
        sections.append(f"## Antipatterns\n{anti}")

    # Skill tree (index only - read skill files on-demand when relevant)
    skill_tree = read_file(SEMANTIC_DIR / "skillTree.md", LIMITS["skill_tree"])
    if skill_tree:
        sections.append(f"## Skill Tree\n{skill_tree}\n\n*Skills listed above can be read from `{SEMANTIC_DIR}/skills/<name>.md` when relevant.*")

    if not sections:
        return "No memory context yet. Start working and it will accumulate."

    total = sum(len(s) for s in sections)
    return f"# Memory Context (~{total//4} tokens)\n\n" + "\n\n---\n\n".join(sections)


if __name__ == "__main__":
    mcp.run(transport="stdio")
