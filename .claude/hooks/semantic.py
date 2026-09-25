"""
Semantic Memory Extraction - Simple, focused approach.

Two extractions at natural trigger points:
- prefs.md    ← from tier1 (after tier0→tier1 compression)
- project.md  ← from chapter (after draft→chapter compression)

No grep, no complex dedup - tier1/chapter already compressed and deduplicated.
Just translate events → stable facts.
"""

import subprocess
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
MEMORY_DIR = BASE_DIR / "memory"
SEMANTIC_DIR = MEMORY_DIR / "semantic"
LOG_FILE = Path(__file__).parent / "semantic.log"

# Caps (lines, not bytes - easier to manage)
PREFS_CAP = 50      # ~50 preferences max
PROJECT_CAP = 100   # ~100 project facts max


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")


def read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def write_semantic(name: str, content: str, cap: int):
    """Write semantic file, enforcing line cap (keep newest)."""
    SEMANTIC_DIR.mkdir(parents=True, exist_ok=True)
    path = SEMANTIC_DIR / f"{name}.md"

    lines = content.strip().split("\n")
    if len(lines) > cap:
        # Keep header + newest entries
        lines = lines[:3] + lines[-(cap-3):]

    path.write_text("\n".join(lines), encoding="utf-8")


def call_claude(prompt: str) -> str | None:
    """Single LLM call for extraction."""
    try:
        result = subprocess.run(
            ["claude", "--model", "haiku", "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            shell=True
        )
        if result.returncode != 0:
            log(f"Claude failed: {result.stderr[:200]}")
            return None
        return result.stdout.strip()
    except Exception as e:
        log(f"Error: {e}")
        return None


# ============ PREFS EXTRACTION (from tier1) ============

def extract_prefs():
    """Extract user preferences from tier1 episodic events."""
    tier1_path = MEMORY_DIR / "episodic" / "tier1.md"
    prefs_path = SEMANTIC_DIR / "prefs.md"

    tier1 = read_file(tier1_path)
    if len(tier1) < 500:
        log("tier1 too small for prefs extraction")
        return

    existing = read_file(prefs_path)
    existing_facts = ""
    if existing:
        # Extract just the bullet points for dedup reference
        lines = [l for l in existing.split("\n") if l.startswith("- ")]
        existing_facts = "\n".join(lines[-20:])  # Last 20 for context

    prompt = f"""Extract USER PREFERENCES from these episodic events.

Look for [DECIDED] and [CHANGED] tags - these indicate choices/preferences.

EXISTING PREFS:
{existing_facts or "(none yet)"}

EVENTS:
{tier1[-15000:]}

OUTPUT FORMAT:
1. First, list any OUTDATED existing prefs that are contradicted by newer events:
   REMOVE: <quote the outdated pref>

2. Then list NEW or UPDATED preferences:
   - <preference statement>

RULES:
- If a newer event contradicts an older pref, mark old for REMOVE and add the new one
- Skip if already covered and still accurate
- Be concise

If nothing changed, output: (no changes)"""

    result = call_claude(prompt)
    if not result or "no changes" in result.lower():
        log("No pref changes")
        return

    # Parse REMOVE entries
    removes = []
    for line in result.split("\n"):
        if line.strip().startswith("REMOVE:"):
            remove_text = line.replace("REMOVE:", "").strip()
            removes.append(remove_text)

    # Parse new entries
    new_entries = [l.strip() for l in result.split("\n") if l.strip().startswith("- ")]

    if not new_entries and not removes:
        log("No valid pref changes")
        return

    # Remove outdated entries from existing
    if removes and existing:
        lines = existing.split("\n")
        filtered = []
        for line in lines:
            should_remove = False
            for r in removes:
                # Fuzzy match - if remove text is substring of line
                if r.lower()[:50] in line.lower():
                    should_remove = True
                    break
            if not should_remove:
                filtered.append(line)
        existing = "\n".join(filtered)
        log(f"Removed {len(removes)} outdated prefs")

    # Append new entries
    if new_entries:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_section = f"\n## [{timestamp}]\n" + "\n".join(new_entries)

        if existing:
            updated = existing + new_section
        else:
            updated = f"# User Preferences\n{new_section}"

        write_semantic("prefs", updated, PREFS_CAP)
        log(f"Added {len(new_entries)} prefs")
    elif removes:
        write_semantic("prefs", existing, PREFS_CAP)
        log("Updated prefs (removals only)")


# ============ PROJECT EXTRACTION (from chapter) ============

def extract_project():
    """Extract project state from narrative chapters."""
    chapter_path = MEMORY_DIR / "narrative" / "chapter.md"
    project_path = SEMANTIC_DIR / "project.md"

    chapter = read_file(chapter_path)
    if len(chapter) < 500:
        log("chapter too small for project extraction")
        return

    existing = read_file(project_path)
    existing_facts = ""
    if existing:
        lines = [l for l in existing.split("\n") if l.startswith("- ")]
        existing_facts = "\n".join(lines[-30:])

    prompt = f"""Extract PROJECT FACTS from these narrative chapters.

Look for:
- What we're building (goals from "Opening" sections)
- What exists now (architecture from "Resolution" sections)
- Why things are this way (key decisions from "Turning Points")

EXISTING FACTS:
{existing_facts or "(none yet)"}

CHAPTERS:
{chapter[-20000:]}

OUTPUT FORMAT:
1. First, list any OUTDATED existing facts contradicted by newer info:
   REMOVE: <quote the outdated fact>

2. Then list NEW or UPDATED facts:
   - <fact statement>

RULES:
- If newer info contradicts an older fact, mark old for REMOVE and add the new one
- Skip if already covered and still accurate
- Be concise

If nothing changed, output: (no changes)"""

    result = call_claude(prompt)
    if not result or "no changes" in result.lower():
        log("No project changes")
        return

    # Parse REMOVE entries
    removes = []
    for line in result.split("\n"):
        if line.strip().startswith("REMOVE:"):
            remove_text = line.replace("REMOVE:", "").strip()
            removes.append(remove_text)

    # Parse new entries
    new_entries = [l.strip() for l in result.split("\n") if l.strip().startswith("- ")]

    if not new_entries and not removes:
        log("No valid project changes")
        return

    # Remove outdated entries from existing
    if removes and existing:
        lines = existing.split("\n")
        filtered = []
        for line in lines:
            should_remove = False
            for r in removes:
                if r.lower()[:50] in line.lower():
                    should_remove = True
                    break
            if not should_remove:
                filtered.append(line)
        existing = "\n".join(filtered)
        log(f"Removed {len(removes)} outdated project facts")

    # Append new entries
    if new_entries:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_section = f"\n## [{timestamp}]\n" + "\n".join(new_entries)

        if existing:
            updated = existing + new_section
        else:
            updated = f"# Project State\n{new_section}"

        write_semantic("project", updated, PROJECT_CAP)
        log(f"Added {len(new_entries)} project facts")
    elif removes:
        write_semantic("project", existing, PROJECT_CAP)
        log("Updated project (removals only)")


# ============ ENTRY POINTS ============

def on_tier1_compress():
    """Called after tier0→tier1 compression."""
    log("Extracting prefs from tier1")
    extract_prefs()


def on_chapter_compress():
    """Called after draft→chapter compression."""
    log("Extracting project from chapter")
    extract_project()


if __name__ == "__main__":
    # Manual run: extract both
    extract_prefs()
    extract_project()
