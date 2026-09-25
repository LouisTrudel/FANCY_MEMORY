"""
Background compression - handles both Episodic and Narrative memory systems.

EPISODIC (tier0 → tier1 → tier2 → ... → tierN):
  - Infinite tiers with formula-based thresholds
  - tier0: 50KB, tierN (N>=1): 10KB + (N × 5KB)
  - Bullet-point format, timestamped events

NARRATIVE (draft → chapter → book → collection):
  - Fixed 4-level hierarchy
  - Prose format, includes reasoning/thinking
  - Tells the story of what happened and why

Rate limiting: 60s cooldown, 10/hour max
"""

import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
MEMORY_DIR = BASE_DIR / "memory"
EPISODIC_DIR = MEMORY_DIR / "episodic"
NARRATIVE_DIR = MEMORY_DIR / "narrative"
LOCK_FILE = MEMORY_DIR / ".compress.lock"
STATE_FILE = MEMORY_DIR / ".compress_state.json"
LOG_FILE = Path(__file__).parent / "compress.log"

# Narrative level order
NARRATIVE_LEVELS = ["draft", "chapter", "book", "collection"]
NARRATIVE_THRESHOLDS = {
    "draft": 25_000,       # Raw logs → ~6KB chapter entry (inject tail)
    "chapter": 20_000,     # Injectable fully (~5K tokens)
    "book": 50_000,        # Search/on-demand only
    "collection": 100_000, # Archive (rarely compresses)
}


def log(msg: str):
    """Log to compress.log"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {msg}\n")
    print(f"[COMPRESS] {msg}", file=sys.stderr)


# ============ THRESHOLDS ============

def episodic_threshold(n: int) -> int:
    """
    Thresholds aligned with injection strategy:
    - tier0: 20KB (raw, inject tail 5KB)
    - tier1: 15KB (compressed, inject FULL)
    - tier2+: 20KB+ (archive, search only)

    tier0: 20KB → compresses to ~5KB → tier1
    tier1: 15KB → inject fully, then compress
    tierN (N>=2): 15KB + (N × 5KB)
    """
    if n == 0:
        return 20_000   # Compress sooner for fresh tier1
    if n == 1:
        return 15_000   # Keep injectable
    return 15_000 + (n * 5_000)  # tier2: 25KB, tier3: 30KB, etc.


def episodic_path(n: int) -> Path:
    return EPISODIC_DIR / f"tier{n}.md"


def narrative_path(level: str) -> Path:
    return NARRATIVE_DIR / f"{level}.md"


def file_size(path: Path) -> int:
    if path.exists():
        return len(path.read_text(encoding="utf-8"))
    return 0


# ============ RATE LIMITING ============

COOLDOWN_SECONDS = 60
MAX_PER_HOUR = 10


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {"last_compression": None, "hour_start": None, "count_this_hour": 0}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def can_compress() -> tuple[bool, str]:
    state = load_state()
    now = datetime.now().timestamp()

    last = state.get("last_compression")
    if last and (now - last) < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last))
        return False, f"cooldown ({remaining}s)"

    hour_start = state.get("hour_start")
    count = state.get("count_this_hour", 0)

    if hour_start and (now - hour_start) < 3600:
        if count >= MAX_PER_HOUR:
            return False, f"hourly limit ({MAX_PER_HOUR}/hour)"
    else:
        state["hour_start"] = now
        state["count_this_hour"] = 0
        save_state(state)

    return True, "ok"


def record_compression():
    state = load_state()
    now = datetime.now().timestamp()

    state["last_compression"] = now
    state["count_this_hour"] = state.get("count_this_hour", 0) + 1

    hour_start = state.get("hour_start")
    if not hour_start or (now - hour_start) >= 3600:
        state["hour_start"] = now
        state["count_this_hour"] = 1

    save_state(state)
    log(f"Compression #{state['count_this_hour']} this hour")


# ============ LOCK ============

def acquire_lock() -> bool:
    if LOCK_FILE.exists():
        age = datetime.now().timestamp() - LOCK_FILE.stat().st_mtime
        if age < 300:
            return False
        LOCK_FILE.unlink()
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.touch()
    return True


def release_lock():
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()


# ============ COMPRESSION PROMPTS ============

def episodic_prompt(content: str, tier: int) -> str:
    """Prompt for episodic compression (events → tagged bullets)."""

    # Higher tiers = more aggressive merging
    tier_guidance = {
        0: """Group by LOGICAL TASK, not by time. One bullet per outcome.
Example: 10 messages about implementing hooks = one [BUILT] bullet.
Use timestamp of completion. Range like [10:00-10:30] for long tasks.""",

        1: """Merge related outcomes into themes.
Example: [BUILT] hooks + [BUILT] compression = [BUILT] memory system.
Keep only pivotal timestamps.""",

        2: """Major milestones only. What would you tell someone
who asks 'what did you accomplish this week?'""",
    }
    guidance = tier_guidance.get(tier, "Core outcomes only. What survives a year from now?")

    return f"""Compress this work log into tagged event bullets.

INPUT FORMAT: **[HH:MM:SS] Role:** content

EXTRACT using these tags:

OUTPUTS (what was produced):
- [BUILT] Created something new
- [FIXED] Solved a problem
- [CHANGED] Modified existing thing

PROCESS (how work happened):
- [DECIDED] Made a choice (include why)
- [TRIED] Attempted something
- [ABANDONED] Gave up an approach (include why - important lesson)
- [DISCOVERED] Insight, realization, learning

STATUS (where things stand):
- [BLOCKED] Stuck, waiting, can't proceed
- [RESOLVED] Previously blocked, now cleared

CONTEXT (important inputs):
- [REQUESTED] User asked for something
- [CLARIFIED] Misunderstanding was corrected

DISCARD:
- Greetings, confirmations ("ok", "got it", "sounds good")
- Verbose explanations (keep conclusion only)
- Code blocks and file contents (they exist in files)
- Thinking/reasoning (that goes in narrative, not episodic)

TIER {tier} GUIDANCE: {guidance}

OUTPUT FORMAT:
- [HH:MM] [TAG] <what> (why/context if important)
- [BLOCKED] <issue> (no timestamp for ongoing blockers)

INPUT:
{content}

OUTPUT:"""


def narrative_prompt(content: str, level: str) -> str:
    """Prompt for narrative compression."""

    level_context = {
        "draft": {
            "role": "CHAPTER",
            "scope": "one work session",
            "structure": """- Opening: What we set out to do
- Complications: What made it challenging
- Turning points: Key realizations (use <thinking> content here)
- Resolution: What we accomplished
- Open threads: What's still unresolved""",
        },
        "chapter": {
            "role": "BOOK",
            "scope": "a project phase (multiple sessions)",
            "structure": """- The Goal: What we were building and why
- The Journey: Major challenges and how we overcame them
- Pivotal Moments: Decisions that shaped the outcome
- Lessons: What we learned
- Cliffhanger: Where this leads next""",
        },
        "book": {
            "role": "COLLECTION ENTRY",
            "scope": "an entire project",
            "structure": """- What It Is: The project in one paragraph
- Why It Exists: The problem it solves
- How It Evolved: Key phases of development
- Core Insights: The deep lessons
- Current State: Where it stands now""",
        },
    }

    ctx = level_context.get(level, level_context["book"])

    return f"""You are compressing raw notes into a {ctx["role"]}.

SCOPE: {ctx["scope"]}

STRUCTURE:
{ctx["structure"]}

WRITING STYLE:
- Prose paragraphs, conversational but clear
- Show cause → effect ("We tried X, but Y, so we Z")
- Include reasoning that led to breakthroughs
- Name specific things (files, concepts, decisions)
- Keep the human element (struggles, realizations, satisfaction)

HANDLING <thinking> BLOCKS:
These contain internal reasoning. Extract insights and "aha moments"
but not the mechanical step-by-step. The gold is in realizations.

INPUT:
{content}

Write the {ctx["role"]}:"""


# ============ COMPRESSION LOGIC ============

def compress_with_claude(content: str, prompt: str) -> str | None:
    """Call Claude CLI to compress content. Uses Sonnet for nuanced compression."""
    try:
        # Use stdin for prompt to avoid shell escaping issues
        # --no-hooks prevents compression prompts/responses from being logged back to memory
        result = subprocess.run(
            ["claude", "--model", "sonnet", "-p", "-", "--no-hooks"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            encoding="utf-8",
            shell=True
        )

        if result.returncode != 0:
            log(f"Claude CLI failed: {result.stderr}")
            return None

        summary = result.stdout.strip()
        if not summary:
            log("Claude returned empty response")
            return None

        return summary

    except subprocess.TimeoutExpired:
        log("Claude CLI timed out")
        return None
    except FileNotFoundError:
        log("Claude CLI not found")
        return None
    except Exception as e:
        log(f"Compression error: {e}")
        return None


def compress_episodic_tier(n: int) -> bool:
    """Compress episodic tier N → tier N+1."""
    path = episodic_path(n)
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    size = len(content)
    threshold = episodic_threshold(n)

    if size <= threshold:
        return False

    log(f"Compressing episodic/tier{n}: {size} > {threshold}")

    prompt = episodic_prompt(content, n)
    summary = compress_with_claude(content, prompt)

    if not summary:
        return False

    log(f"Got summary: {len(summary)} chars ({len(summary)/size*100:.1f}%)")

    # Append to next tier
    next_path = episodic_path(n + 1)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n{'='*60}\n## [{timestamp}] From tier{n}\n{'='*60}\n\n{summary}\n"

    existing = next_path.read_text(encoding="utf-8") if next_path.exists() else ""
    next_path.write_text(existing + entry, encoding="utf-8")

    # Clear current tier
    path.write_text("", encoding="utf-8")
    log(f"Cleared episodic/tier{n}, appended to tier{n+1}")

    # Trigger semantic extraction after tier0→tier1 compression
    if n == 0:
        trigger_semantic("prefs")

    return True


def trigger_semantic(extraction_type: str):
    """Run semantic extraction inline (fast with haiku)."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from semantic import on_tier1_compress, on_chapter_compress
        if extraction_type == "prefs":
            on_tier1_compress()
        elif extraction_type == "project":
            on_chapter_compress()
    except Exception as e:
        log(f"Semantic extraction failed: {e}")


def compress_narrative_level(level: str) -> bool:
    """Compress narrative level → next level."""
    level_idx = NARRATIVE_LEVELS.index(level)
    if level_idx >= len(NARRATIVE_LEVELS) - 1:
        return False  # collection doesn't compress further

    path = narrative_path(level)
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    size = len(content)
    threshold = NARRATIVE_THRESHOLDS[level]

    if size <= threshold:
        return False

    log(f"Compressing narrative/{level}: {size} > {threshold}")

    prompt = narrative_prompt(content, level)
    summary = compress_with_claude(content, prompt)

    if not summary:
        return False

    log(f"Got summary: {len(summary)} chars ({len(summary)/size*100:.1f}%)")

    # Append to next level
    next_level = NARRATIVE_LEVELS[level_idx + 1]
    next_path = narrative_path(next_level)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n{'='*60}\n## [{timestamp}] From {level}\n{'='*60}\n\n{summary}\n"

    existing = next_path.read_text(encoding="utf-8") if next_path.exists() else ""
    next_path.write_text(existing + entry, encoding="utf-8")

    # Clear current level
    path.write_text("", encoding="utf-8")
    log(f"Cleared narrative/{level}, appended to {next_level}")

    # Trigger semantic extraction after draft→chapter compression
    if level == "draft":
        trigger_semantic("project")

    return True


def cascade_compress():
    """Check all tiers/levels and compress as needed."""
    compressed_count = 0

    # Episodic: check tier0, tier1, ... until one doesn't exist
    for n in range(100):  # safety limit
        path = episodic_path(n)
        if n > 0 and not path.exists():
            break

        if file_size(path) > episodic_threshold(n):
            allowed, reason = can_compress()
            if not allowed:
                log(f"Rate limited: {reason}")
                return compressed_count

            if compress_episodic_tier(n):
                record_compression()
                compressed_count += 1

    # Narrative: check draft, chapter, book (not collection)
    for level in NARRATIVE_LEVELS[:-1]:  # exclude collection
        path = narrative_path(level)
        if not path.exists():
            continue

        if file_size(path) > NARRATIVE_THRESHOLDS[level]:
            allowed, reason = can_compress()
            if not allowed:
                log(f"Rate limited: {reason}")
                return compressed_count

            if compress_narrative_level(level):
                record_compression()
                compressed_count += 1

    return compressed_count


def main():
    log("Compress script started")

    if not acquire_lock():
        log("Another compression in progress")
        return

    try:
        allowed, reason = can_compress()
        if not allowed:
            log(f"Rate limited on start: {reason}")
            return

        count = cascade_compress()
        log(f"Compressed {count} file(s)")

    finally:
        release_lock()

    log("Compress script finished")


if __name__ == "__main__":
    main()
