"""
Minimal MCP Server - Memory Injection & Search

Tools:
- inject_memory() - loads context from previous sessions
- search_memory() - search through memory history

Hooks handle: logging, compression, skill extraction (automatic)
"""

import re
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
        "episodic_budget": 10_000,
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
        result = []
        remaining = budget
        for n in range(10):
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
                result.append(content[-remaining:])
                break
        return "\n\n---\n\n".join(result) if result else ""

    sections = []

    episodic = cascade_episodic(LIMITS["episodic_budget"])
    if episodic:
        sections.append(f"## Recent Events\n{episodic}")

    prefs = read_file(SEMANTIC_DIR / "preferences.md", LIMITS["preferences"])
    if prefs:
        sections.append(f"## Preferences\n{prefs}")

    anti = read_file(SEMANTIC_DIR / "antipatterns.md", LIMITS["antipatterns"])
    if anti:
        sections.append(f"## Antipatterns\n{anti}")

    skill_tree = read_file(SEMANTIC_DIR / "skillTree.md", LIMITS["skill_tree"])
    if skill_tree:
        sections.append(f"## Skill Tree\n{skill_tree}\n\n*Read skills from `{SEMANTIC_DIR}/skills/<name>.md` when relevant.*")

    if not sections:
        return "No memory context yet. Start working and it will accumulate."

    total = sum(len(s) for s in sections)
    return f"# Memory Context (~{total//4} tokens)\n\n" + "\n\n---\n\n".join(sections)


@mcp.tool()
def search_memory(query: str) -> str:
    """
    Search through all memory files for keywords.

    Use when user asks about past events, decisions, or project history.
    Examples: "what happened yesterday", "why did we use X", "when did we fix Y"

    Args:
        query: Search terms (space-separated keywords)

    Returns matching sections with file context.
    """
    if not MEMORY_DIR.exists():
        return "No memory directory found."

    # Extract keywords (words with 3+ chars, lowercased)
    keywords = [w.lower() for w in re.findall(r'\w+', query) if len(w) >= 3]
    if not keywords:
        return "No valid search terms. Use words with 3+ characters."

    results = []
    max_results = 10
    context_lines = 3

    # Search all .md files under memory/
    for md_file in sorted(MEMORY_DIR.rglob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            # Find lines matching any keyword
            for i, line in enumerate(lines):
                line_lower = line.lower()
                matched_keywords = [kw for kw in keywords if kw in line_lower]

                if matched_keywords:
                    # Get context (surrounding lines)
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    context = "\n".join(lines[start:end])

                    # Relative path for cleaner output
                    rel_path = md_file.relative_to(MEMORY_DIR)

                    results.append(f"### {rel_path} (line {i+1})\nMatched: {', '.join(matched_keywords)}\n```\n{context}\n```")

                    if len(results) >= max_results:
                        break

            if len(results) >= max_results:
                break

        except Exception:
            continue

    if not results:
        return f"No matches found for: {', '.join(keywords)}"

    header = f"Found {len(results)} matches for: {', '.join(keywords)}\n\n"
    return header + "\n\n".join(results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
