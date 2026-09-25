"""
Memory injection - generates context for session start.

Outputs markdown that can be injected into system prompt or first message.

Usage:
    python inject.py              # Full injection (episodic + narrative)
    python inject.py episodic     # Episodic only
    python inject.py narrative    # Narrative only
    python inject.py minimal      # Just tier1 + semantic
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
EPISODIC_DIR = BASE_DIR / "memory" / "episodic"
NARRATIVE_DIR = BASE_DIR / "memory" / "narrative"
SEMANTIC_DIR = BASE_DIR / "memory" / "semantic"

# Injection limits (characters)
LIMITS = {
    "tier0_tail": 5_000,      # Recent raw events
    "tier1_full": 15_000,     # Full compressed history
    "draft_tail": 5_000,      # Recent raw narrative
    "chapter_full": 20_000,   # Full chapter
    "semantic": 3_000,        # Core facts
}


def read_file(path: Path, max_chars: int = None) -> str:
    """Read file, optionally truncated."""
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if max_chars and len(content) > max_chars:
        return content[:max_chars] + "\n\n[...truncated...]"
    return content


def read_tail(path: Path, max_chars: int) -> str:
    """Read last N characters of file."""
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if len(content) <= max_chars:
        return content
    return "[...earlier content...]\n\n" + content[-max_chars:]


def get_episodic_context() -> str:
    """Get episodic memory context for injection."""
    sections = []

    # tier0 tail (recent uncompressed)
    tier0 = read_tail(EPISODIC_DIR / "tier0.md", LIMITS["tier0_tail"])
    if tier0:
        sections.append(f"### Recent Events (uncompressed)\n{tier0}")

    # tier1 full (compressed history)
    tier1 = read_file(EPISODIC_DIR / "tier1.md", LIMITS["tier1_full"])
    if tier1:
        sections.append(f"### Event History (compressed)\n{tier1}")

    if not sections:
        return ""

    return "## Episodic Memory\n\n" + "\n\n".join(sections)


def get_narrative_context() -> str:
    """Get narrative memory context for injection."""
    sections = []

    # draft tail (recent story)
    draft = read_tail(NARRATIVE_DIR / "draft.md", LIMITS["draft_tail"])
    if draft:
        sections.append(f"### Current Session Notes\n{draft}")

    # chapter full (story so far)
    chapter = read_file(NARRATIVE_DIR / "chapter.md", LIMITS["chapter_full"])
    if chapter:
        sections.append(f"### Story So Far\n{chapter}")

    if not sections:
        return ""

    return "## Narrative Memory\n\n" + "\n\n".join(sections)


def get_semantic_context() -> str:
    """Get semantic memory (facts, skills) for injection."""
    sections = []

    # Check for any .md files in semantic dir
    if SEMANTIC_DIR.exists():
        for md_file in SEMANTIC_DIR.glob("*.md"):
            content = read_file(md_file, LIMITS["semantic"])
            if content:
                name = md_file.stem.replace("_", " ").title()
                sections.append(f"### {name}\n{content}")

        # Also check skills subfolder
        skills_dir = SEMANTIC_DIR / "skills"
        if skills_dir.exists():
            for md_file in skills_dir.glob("*.md"):
                content = read_file(md_file, 1000)  # Smaller limit for skills
                if content:
                    name = md_file.stem.replace("_", " ").title()
                    sections.append(f"### Skill: {name}\n{content}")

    if not sections:
        return ""

    return "## Semantic Memory\n\n" + "\n\n".join(sections)


def get_minimal_context() -> str:
    """Minimal injection - just tier1 + semantic."""
    sections = []

    tier1 = read_file(EPISODIC_DIR / "tier1.md", LIMITS["tier1_full"])
    if tier1:
        sections.append(f"## Recent History\n{tier1}")

    semantic = get_semantic_context()
    if semantic:
        sections.append(semantic)

    return "\n\n".join(sections)


def get_full_context() -> str:
    """Full injection - everything."""
    sections = []

    episodic = get_episodic_context()
    if episodic:
        sections.append(episodic)

    narrative = get_narrative_context()
    if narrative:
        sections.append(narrative)

    semantic = get_semantic_context()
    if semantic:
        sections.append(semantic)

    if not sections:
        return "# Memory\n\nNo memory context available yet."

    header = "# Memory Context\n\n"
    return header + "\n\n---\n\n".join(sections)


def main():
    # Fix Windows encoding
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    if mode == "episodic":
        output = get_episodic_context()
    elif mode == "narrative":
        output = get_narrative_context()
    elif mode == "semantic":
        output = get_semantic_context()
    elif mode == "minimal":
        output = get_minimal_context()
    else:
        output = get_full_context()

    if output:
        print(output)
    else:
        print("# Memory\n\nNo memory context available yet.")

    # Print stats to stderr
    total_chars = len(output)
    est_tokens = total_chars // 4
    print(f"\n[Injection: {total_chars} chars, ~{est_tokens} tokens]", file=sys.stderr)


if __name__ == "__main__":
    main()
