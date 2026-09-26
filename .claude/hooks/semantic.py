"""
Semantic Memory Extraction - Preferences & Antipatterns

Two files, both extracted from narrative (draft.md):
- preferences.md  ← What user wants (style, workflow, choices)
- antipatterns.md ← What NOT to do (mistakes learned, corrections)

Triggered when draft→chapter compression happens.
Uses UPDATE-in-place approach (outputs complete file, not append).
"""

import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
MEMORY_DIR = BASE_DIR / "memory"
SEMANTIC_DIR = MEMORY_DIR / "semantic"
NARRATIVE_DIR = MEMORY_DIR / "narrative"
LOG_FILE = Path(__file__).parent / "semantic.log"

# Line caps for each file
PREFS_CAP = 50
ANTIPATTERNS_CAP = 30


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")


def read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def call_claude(prompt: str) -> str | None:
    """Call Claude for extraction. Runs from temp dir to avoid triggering hooks."""
    try:
        result = subprocess.run(
            ["claude", "--model", "haiku", "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=90,
            encoding="utf-8",
            shell=True,
            cwd=tempfile.gettempdir()
        )
        if result.returncode != 0:
            log(f"Claude failed: {result.stderr[:200]}")
            return None
        return result.stdout.strip()
    except Exception as e:
        log(f"Error: {e}")
        return None


def write_with_cap(path: Path, content: str, cap: int):
    """Write file, keeping only the last `cap` entries."""
    SEMANTIC_DIR.mkdir(parents=True, exist_ok=True)

    lines = content.strip().split("\n")

    # Find header (lines before first "- [")
    header_end = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("- ["):
            header_end = i
            break

    header = lines[:header_end]
    entries = lines[header_end:]

    # Keep only last `cap` entries
    if len(entries) > cap:
        entries = entries[-cap:]

    final = "\n".join(header + entries)
    path.write_text(final, encoding="utf-8")


# ============ PREFERENCES EXTRACTION ============

def extract_preferences():
    """Extract user preferences from narrative draft."""
    draft_path = NARRATIVE_DIR / "draft.md"
    prefs_path = SEMANTIC_DIR / "preferences.md"

    draft = read_file(draft_path)
    if len(draft) < 1000:
        log("Draft too small for preference extraction")
        return

    existing = read_file(prefs_path)
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""Extract USER PREFERENCES from this narrative session log.

SIGNALS TO LOOK FOR:
- "user prefers", "user wants", "user likes"
- "always use", "never use", "from now on"
- "I prefer", "let's go with", "we agreed"
- Style choices, workflow patterns, conventions

EXISTING PREFERENCES:
{existing if existing else "(none yet)"}

NARRATIVE LOG:
{draft[-20000:]}

TASK:
Output the COMPLETE UPDATED preferences.md file.
- UPDATE existing entries if new info refines them
- ADD new entries for new preferences
- REMOVE entries explicitly contradicted
- KEEP entries not mentioned (unchanged)

FORMAT:
# User Preferences

- [{today}] Preference statement here.
- [{today}] Another preference.

RULES:
- One line per preference
- Date in brackets
- Be concise but specific
- Merge similar entries (don't duplicate)
- If nothing new, output the existing file unchanged

Output the complete file:"""

    result = call_claude(prompt)
    if not result:
        log("No preferences result")
        return

    # Basic validation
    if not result.strip().startswith("#"):
        result = "# User Preferences\n\n" + result

    write_with_cap(prefs_path, result, PREFS_CAP)
    log(f"Updated preferences.md")


# ============ ANTIPATTERNS EXTRACTION ============

def extract_antipatterns():
    """Extract mistakes/antipatterns from narrative draft."""
    draft_path = NARRATIVE_DIR / "draft.md"
    antipatterns_path = SEMANTIC_DIR / "antipatterns.md"

    draft = read_file(draft_path)
    if len(draft) < 1000:
        log("Draft too small for antipattern extraction")
        return

    existing = read_file(antipatterns_path)
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""Extract ANTIPATTERNS (mistakes to avoid) from this narrative session log.

SIGNALS TO LOOK FOR:
- "user corrected", "actually no", "that's wrong"
- "doesn't work", "broke", "failed because"
- "don't use X, use Y instead"
- Corrections, bugs found, approaches that failed

EXISTING ANTIPATTERNS:
{existing if existing else "(none yet)"}

NARRATIVE LOG:
{draft[-20000:]}

TASK:
Output the COMPLETE UPDATED antipatterns.md file.
- UPDATE existing entries if more context found
- ADD new antipatterns discovered
- REMOVE if something was wrong but now resolved
- KEEP entries not mentioned (unchanged)

FORMAT:
# Antipatterns

- [{today}] DON'T do X. Instead do Y. (reason)
- [{today}] AVOID approach because consequence.

RULES:
- One line per antipattern
- Date in brackets
- Start with DON'T, AVOID, NEVER, or similar
- Include the correct alternative when known
- Be specific (include function/file names)
- If nothing new, output the existing file unchanged

Output the complete file:"""

    result = call_claude(prompt)
    if not result:
        log("No antipatterns result")
        return

    # Basic validation
    if not result.strip().startswith("#"):
        result = "# Antipatterns\n\n" + result

    write_with_cap(antipatterns_path, result, ANTIPATTERNS_CAP)
    log(f"Updated antipatterns.md")


# ============ ENTRY POINT ============

def on_draft_compress():
    """Called before draft→chapter compression. Extract from draft while it's available."""
    log("=== Semantic extraction triggered ===")
    extract_preferences()
    extract_antipatterns()
    log("=== Semantic extraction complete ===")


if __name__ == "__main__":
    # Manual run
    on_draft_compress()
