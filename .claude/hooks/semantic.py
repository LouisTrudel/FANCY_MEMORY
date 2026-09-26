"""
Semantic Memory - Three-Tier Skill Emergence System

Level 0: preferences.md + antipatterns.md (raw accumulation)
Level 1: skillTree.md (candidates - grouped patterns)
Level 2: skills/*.md (emerged skills - proven patterns)

Flow:
  narrative draft → extract → prefs/antipatterns (append)
                           ↓ threshold
                    compact → skillTree (append candidates)
                           ↓ threshold
                    cluster → skills/*.md (create skill files)
"""

import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
MEMORY_DIR = BASE_DIR / "memory"
SEMANTIC_DIR = MEMORY_DIR / "semantic"
NARRATIVE_DIR = MEMORY_DIR / "narrative"
SKILLS_DIR = SEMANTIC_DIR / "skills"
LOG_FILE = Path(__file__).parent / "semantic.log"

# Thresholds
PREFS_ANTI_THRESHOLD = 8_000    # Combined size to trigger Level 1 compact
SKILL_TREE_THRESHOLD = 10_000   # Size to trigger Level 2 compact
MIN_SKILL_ENTRIES = 5           # Minimum entries to form a skill

# File caps (lines)
PREFS_CAP = 40
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


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def call_claude(prompt: str, model: str = "haiku") -> str | None:
    """Call Claude. Runs from temp dir to avoid triggering hooks."""
    try:
        result = subprocess.run(
            ["claude", "--model", model, "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
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


# ============ LEVEL 0: RAW ACCUMULATION ============

def extract_preferences():
    """Extract user preferences from narrative draft. Appends to preferences.md."""
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
- ADD new entries for new preferences found
- REMOVE entries that are explicitly contradicted
- KEEP entries not mentioned (no change = keep)

FORMAT:
# Preferences

- [{today}] Preference statement here.
- [{today}] Another preference.

RULES:
- One line per preference
- Date in brackets at start
- Be concise but specific
- Merge similar entries (don't duplicate)
- Max {PREFS_CAP} entries (drop oldest if exceeded)
- If nothing new found, output existing file unchanged

Output the complete file:"""

    result = call_claude(prompt)
    if not result:
        log("No preferences result")
        return

    if not result.strip().startswith("#"):
        result = "# Preferences\n\n" + result

    write_file(prefs_path, result)
    log(f"Updated preferences.md ({len(result)} bytes)")


def extract_antipatterns():
    """Extract antipatterns from narrative draft. Appends to antipatterns.md."""
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
- REMOVE if explicitly resolved/outdated
- KEEP entries not mentioned (no change = keep)

FORMAT:
# Antipatterns

- [{today}] DON'T do X. Instead do Y. (reason)
- [{today}] AVOID approach because consequence.

RULES:
- One line per antipattern
- Date in brackets at start
- Start with DON'T, AVOID, NEVER, or similar
- Include the correct alternative when known
- Be specific (include function/file names when relevant)
- Max {ANTIPATTERNS_CAP} entries (drop oldest if exceeded)
- If nothing new found, output existing file unchanged

Output the complete file:"""

    result = call_claude(prompt)
    if not result:
        log("No antipatterns result")
        return

    if not result.strip().startswith("#"):
        result = "# Antipatterns\n\n" + result

    write_file(antipatterns_path, result)
    log(f"Updated antipatterns.md ({len(result)} bytes)")


# ============ LEVEL 1: COMPACT TO SKILL TREE ============

def compact_to_skill_tree():
    """Compact prefs+antipatterns, extract skill candidates to skillTree.md."""
    prefs_path = SEMANTIC_DIR / "preferences.md"
    anti_path = SEMANTIC_DIR / "antipatterns.md"
    tree_path = SEMANTIC_DIR / "skillTree.md"

    prefs = read_file(prefs_path)
    anti = read_file(anti_path)
    existing_tree = read_file(tree_path)

    combined_size = len(prefs) + len(anti)
    if combined_size < PREFS_ANTI_THRESHOLD:
        log(f"Prefs+Anti ({combined_size}b) below threshold ({PREFS_ANTI_THRESHOLD}b)")
        return

    log(f"Level 1 compact triggered: {combined_size}b")
    today = datetime.now().strftime("%Y-%m-%d")

    # Get existing skills for context
    existing_skills = []
    if SKILLS_DIR.exists():
        existing_skills = [f.stem for f in SKILLS_DIR.glob("*.md")]

    prompt = f"""You are organizing preferences and antipatterns into a skill tree.

PREFERENCES:
{prefs}

ANTIPATTERNS:
{anti}

EXISTING SKILL TREE:
{existing_tree if existing_tree else "(empty)"}

EXISTING SKILL FILES: {existing_skills if existing_skills else "(none)"}

TASK:
1. DEDUPLICATE and MERGE similar entries in prefs and antipatterns
2. IDENTIFY domain-specific entries (UI, data, animation, etc.)
3. KEEP general entries in prefs/antipatterns (not domain-specific)
4. EXTRACT domain-specific entries as CANDIDATES in skillTree.md

OUTPUT FORMAT (use exact delimiters):

===PREFERENCES===
# Preferences

- [date] General preference (not domain-specific)
- [date] Another general preference

===ANTIPATTERNS===
# Antipatterns

- [date] General antipattern (not domain-specific)

===SKILLTREE===
# Skill Tree

## Active Skills
(List existing skill files with descriptions)

## Candidates

### [UI]
- [date] UI-specific preference or antipattern
- [date] Another UI entry

### [Data]
- [date] Data/sync specific entry

### [Animation]
- [date] Animation/tween specific entry

RULES:
- Candidate groups need a clear domain name in [brackets]
- Move domain-specific entries from prefs/anti → candidates
- Keep entries that apply broadly in prefs/anti
- Preserve dates on all entries
- Merge duplicates (keep most recent date)
- If a candidate group has {MIN_SKILL_ENTRIES}+ entries, note it's ready for skill promotion
- Maintain any existing Active Skills section

Output all three sections:"""

    result = call_claude(prompt, model="sonnet")  # Use sonnet for complex reasoning
    if not result:
        log("Level 1 compact failed")
        return

    # Parse the three sections
    try:
        sections = {}
        current_section = None
        current_content = []

        for line in result.split("\n"):
            if line.strip() == "===PREFERENCES===":
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = "preferences"
                current_content = []
            elif line.strip() == "===ANTIPATTERNS===":
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = "antipatterns"
                current_content = []
            elif line.strip() == "===SKILLTREE===":
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = "skilltree"
                current_content = []
            else:
                current_content.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        # Write updated files
        if "preferences" in sections and sections["preferences"]:
            write_file(prefs_path, sections["preferences"])
            log(f"Compacted preferences.md")

        if "antipatterns" in sections and sections["antipatterns"]:
            write_file(anti_path, sections["antipatterns"])
            log(f"Compacted antipatterns.md")

        if "skilltree" in sections and sections["skilltree"]:
            write_file(tree_path, sections["skilltree"])
            log(f"Updated skillTree.md")

    except Exception as e:
        log(f"Parse error in Level 1 compact: {e}")


# ============ LEVEL 2: COMPACT SKILL TREE → CREATE SKILLS ============

def compact_skill_tree():
    """Compact skillTree.md, create skill files for strong clusters."""
    tree_path = SEMANTIC_DIR / "skillTree.md"
    tree = read_file(tree_path)

    if len(tree) < SKILL_TREE_THRESHOLD:
        log(f"SkillTree ({len(tree)}b) below threshold ({SKILL_TREE_THRESHOLD}b)")
        return

    log(f"Level 2 compact triggered: {len(tree)}b")

    # Get existing skills
    existing_skills = {}
    if SKILLS_DIR.exists():
        for skill_file in SKILLS_DIR.glob("*.md"):
            existing_skills[skill_file.stem] = read_file(skill_file)

    prompt = f"""You are promoting skill candidates to full skills.

SKILL TREE:
{tree}

EXISTING SKILLS:
{existing_skills if existing_skills else "(none)"}

TASK:
1. Find candidate groups with {MIN_SKILL_ENTRIES}+ entries
2. Promote them to full skill files
3. Update skillTree.md to reference new skills
4. Merge new entries into existing skills if they match

OUTPUT FORMAT (use exact delimiters):

===SKILLTREE===
# Skill Tree

## Active Skills
Load these when context matches:

### skill-name
**Use when:** One line description
**Keywords:** comma, separated, keywords
**File:** skills/skill-name.md

## Candidates
(Remaining groups not yet promoted)

### [GroupName]
- [date] Entry not yet promoted

===SKILL:skill-name===
# Skill: Skill Name

## When to Use
Brief description of when this skill applies.

## Keywords
keyword1, keyword2, keyword3

## Preferences
- [date] Preference entry
- [date] Another preference

## Antipatterns
- [date] DON'T do X
- [date] AVOID Y

RULES:
- Skill names: lowercase-hyphenated (build-ui, data-handling)
- Minimum {MIN_SKILL_ENTRIES} entries to form a skill
- Keywords should match common terms that trigger this skill
- Each skill needs: When to Use, Keywords, Preferences, Antipatterns
- Merge into existing skills rather than creating duplicates
- Keep candidates that aren't ready for promotion
- Preserve all dates

Output skillTree first, then each skill:"""

    result = call_claude(prompt, model="sonnet")
    if not result:
        log("Level 2 compact failed")
        return

    try:
        # Parse skillTree and skill files
        current_section = None
        current_name = None
        current_content = []
        outputs = {}

        for line in result.split("\n"):
            if line.strip() == "===SKILLTREE===":
                if current_section and current_name:
                    outputs[current_name] = "\n".join(current_content).strip()
                current_section = "skilltree"
                current_name = "skillTree"
                current_content = []
            elif line.strip().startswith("===SKILL:"):
                if current_section and current_name:
                    outputs[current_name] = "\n".join(current_content).strip()
                current_section = "skill"
                current_name = line.strip().replace("===SKILL:", "").replace("===", "").strip()
                current_content = []
            else:
                current_content.append(line)

        if current_section and current_name:
            outputs[current_name] = "\n".join(current_content).strip()

        # Write outputs
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)

        for name, content in outputs.items():
            if not content:
                continue
            if name == "skillTree":
                write_file(tree_path, content)
                log(f"Updated skillTree.md")
            else:
                skill_path = SKILLS_DIR / f"{name}.md"
                write_file(skill_path, content)
                log(f"Created/updated skill: {name}.md")

    except Exception as e:
        log(f"Parse error in Level 2 compact: {e}")


# ============ ENTRY POINTS ============

def on_draft_compress():
    """Called when draft→chapter compression happens."""
    log("=== Level 0: Extracting from narrative ===")
    extract_preferences()
    extract_antipatterns()
    log("=== Level 0 complete ===")

    # Check if Level 1 needed
    prefs = read_file(SEMANTIC_DIR / "preferences.md")
    anti = read_file(SEMANTIC_DIR / "antipatterns.md")
    if len(prefs) + len(anti) > PREFS_ANTI_THRESHOLD:
        log("=== Level 1: Compacting to skill tree ===")
        compact_to_skill_tree()
        log("=== Level 1 complete ===")

        # Check if Level 2 needed
        tree = read_file(SEMANTIC_DIR / "skillTree.md")
        if len(tree) > SKILL_TREE_THRESHOLD:
            log("=== Level 2: Creating skills ===")
            compact_skill_tree()
            log("=== Level 2 complete ===")


def manual_compact():
    """Force run all compaction levels."""
    log("=== Manual compact: Level 1 ===")
    compact_to_skill_tree()
    log("=== Manual compact: Level 2 ===")
    compact_skill_tree()
    log("=== Manual compact complete ===")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--compact":
        manual_compact()
    else:
        on_draft_compress()
