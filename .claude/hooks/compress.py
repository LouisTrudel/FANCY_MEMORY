"""
Background compression - handles both Episodic and Narrative memory systems.

EPISODIC (tier0 → tier1 → tier2 → ... → tierN):
  - Infinite tiers with formula-based thresholds
  - Bullet-point format, timestamped events

NARRATIVE (draft → chapter → book → collection):
  - Fixed 4-level hierarchy
  - Prose format; preserves the narrative arc of the visible exchange

HALF-COMPRESSION STRATEGY:
  - Only compress the OLDER half of content
  - Keep the NEWER half in the source tier
  - Ensures every tier always has some content
  - Prevents empty files and data gaps

Rate limiting: 60s cooldown, 10/hour max
"""

import subprocess
import sys
import os
import json
import re
import tempfile
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
    # Half-split means the input per call is HALF the threshold. Prose needs a
    # wide window to carry an arc; a chapter entry built from ~12 turns is a
    # fragment. 50K gives a 25K input (~25 turns) and costs nothing at
    # injection time, because draft is never injected. Measured draft->chapter
    # is ~36%, so expect a ~9KB chapter entry per call.
    "draft": 50_000,
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


# ============ CONTENT SPLITTING ============
#
# FILE ORDER: Oldest content at TOP, newest at BOTTOM (append adds to bottom)
# SPLIT: First half = OLDER (compress this), Second half = NEWER (keep this)
# APPEND: Add compressed output to END of next tier (preserves chronology)
#

def split_content(content: str) -> tuple[str, str]:
    """
    Simple line-based split at midpoint.
    Returns (older_half, newer_half).

    - older_half = first half of lines (TOP of file = oldest)
    - newer_half = second half of lines (BOTTOM of file = newest)

    Works for both raw content (tier0/draft) and sectioned content (tier1+/chapter+).
    Section markers naturally fall into correct halves.
    """
    lines = content.split('\n')

    if len(lines) < 6:
        # Too small to split meaningfully, compress all
        return content, ""

    mid = len(lines) // 2

    older = '\n'.join(lines[:mid]).strip()
    newer = '\n'.join(lines[mid:]).strip()

    return older, newer


# ============ RATE LIMITING ============

COOLDOWN_SECONDS = 60     # gate on STARTING a run, not between files in one
MAX_PER_HOUR = 20         # safety valve against runaway spend
MAX_PER_RUN = 4           # drain a backlog in one pass (tier0+tier1+tier2+draft)


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


def hourly_allowed() -> tuple[bool, str]:
    """Hourly cap only, with no cooldown. Used between files inside one run."""
    state = load_state()
    now = datetime.now().timestamp()

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


def can_compress() -> tuple[bool, str]:
    """Cooldown + hourly cap. Gates whether a run may START (see main())."""
    state = load_state()
    now = datetime.now().timestamp()

    last = state.get("last_compression")
    if last and (now - last) < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - last))
        return False, f"cooldown ({remaining}s)"

    return hourly_allowed()


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

TAG each event using:

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
- Verbose deliberation (keep the conclusion only)
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
- Turning points: Key realizations and why they mattered
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
- Lessons : The deep lessons
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
- Include the stated rationale behind each breakthrough, as given in the replies
- Name specific things (files, concepts, decisions)
- Keep the human element (struggles, realizations, satisfaction)

Draw on the session's visible exchanges: what was asked, what was decided,
and what the tools returned. Favor realizations and turning points over
mechanical step-by-step recaps. The gold is in why choices were made.

INPUT:
{content}

Write the {ctx["role"]}:"""


# ============ OUTPUT VALIDATION ============
#
# A compression run DELETES its source, so anything that is not clearly a
# summary has to be rejected. On 2026-10-15 a 1.19M-char narrative half was
# replaced by 452 chars of refusal text that the model had echoed back from
# the tail of its own input. These checks are the gate that stops that.
#

MIN_SUMMARY_CHARS = 200
# Measured in compress.log, NOT the 8-12% an earlier version of this comment
# claimed: tier0->tier1 21-33%, tier1->tier2 18-69%, draft->chapter 22-45%,
# chapter->book 74-88%, book->collection 30%.
#
# Ratios RISE with the level, and that is the design working, not a fault. Each
# file holds the previous level's output, so a later stage is summarizing text
# that is already dense - there is little left to remove, and squeezing harder
# would cost detail rather than bytes. Half-split exists for the same reason:
# compressing a whole file on threshold used to leave empty files behind. So
# tier3+ and collection.md are meant to be small and very dense, not small and
# shrinking further. Do not "fix" a high-level ratio by tightening a prompt.
#
# The floor stays far below every observed value on purpose: it guards against
# garbage output, not loose compression. The 2026-10-15 incident was 0.04%.
MIN_RATIO = 0.005

EPISODIC_TAG_RE = re.compile(
    r"\[(BUILT|FIXED|CHANGED|DECIDED|TRIED|ABANDONED|DISCOVERED"
    r"|BLOCKED|RESOLVED|REQUESTED|CLARIFIED)\]"
)

REFUSAL_PATTERNS = [
    "i won't", "i will not", "i can't help", "i cannot help",
    "i can't assist", "i cannot assist", "i can't provide",
    "i cannot provide", "i'm unable", "i am unable", "i'm not able",
    "i am not able", "i apologize, but", "i don't feel comfortable",
    "withheld content", "tripped the classifier", "as an ai",
    "tell me which you want", "let me know which",
]


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def validate_summary(summary: str, source: str, kind: str, label: str) -> tuple[bool, str]:
    """
    Gate between the LLM and the memory files. Returns (ok, reason).

    Rejects empty output, output too short to hold the material, refusals,
    verbatim echoes of the input, and output missing the structure its
    prompt asked for.
    """
    if not summary:
        return False, "empty output"

    if len(summary) < MIN_SUMMARY_CHARS:
        return False, f"too short ({len(summary)} < {MIN_SUMMARY_CHARS} chars)"

    ratio = len(summary) / max(len(source), 1)
    if ratio < MIN_RATIO:
        return False, (
            f"ratio {ratio:.5f} below floor {MIN_RATIO} "
            f"({len(summary)} chars from {len(source)})"
        )

    low = _normalize(summary)

    for pattern in REFUSAL_PATTERNS:
        if pattern in low:
            return False, f"refusal pattern: {pattern!r}"

    # Echo check: the model returning part of its own input instead of a
    # summary is exactly what happened in the 2026-10-15 incident.
    probe = low[:400]
    if len(probe) >= 200 and probe in _normalize(source):
        return False, "echoes source verbatim"

    if kind == "episodic" and not EPISODIC_TAG_RE.search(summary):
        return False, "no [TAG] bullets in episodic output"

    if kind == "narrative":
        breaks = summary.count("\n")
        if breaks < 4:
            return False, f"narrative output has {breaks} line breaks, expected prose sections"

    return True, "ok"


def pending_path(path: Path) -> Path:
    """Sidecar holding the half about to be deleted, until the summary validates."""
    return path.with_name(f"{path.stem}.pending.md")


# ============ COMPRESSION LOGIC ============

def compress_with_claude(content: str, prompt: str) -> str | None:
    """Call Claude CLI to compress content. Uses Sonnet for nuanced compression."""
    try:
        # Use stdin for prompt to avoid shell escaping issues
        result = subprocess.run(
            ["claude", "--model", "sonnet", "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            encoding="utf-8",
            shell=True,
            # Mark this process so the logging hooks skip it. Without the
            # mark, `claude -p` fires UserPromptSubmit/Stop in this project
            # and writes the prompt and the summary straight back into the
            # files being compressed.
            env={**os.environ, "MEMORY_HOOKS_DISABLED": "1"},
            # Run from a temp dir so the subprocess does not load THIS project's
            # CLAUDE.md and .mcp.json. Inheriting the project cwd handed every
            # summarizer the instructions "FIRST ACTION: inject_memory()" and
            # "Never assume intent - ask if unclear", so a run could spend its
            # first step loading memory, or return a clarifying question instead
            # of a summary. semantic.py already did this; compress.py did not.
            cwd=tempfile.gettempdir(),
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
    """Compress OLDER HALF of episodic tier N → tier N+1, keep newer half."""
    path = episodic_path(n)
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    size = len(content)
    threshold = episodic_threshold(n)

    if size <= threshold:
        return False

    log(f"Compressing episodic/tier{n}: {size} > {threshold}")

    # Split: compress older half (TOP of file), keep newer half (BOTTOM of file)
    older, newer = split_content(content)

    if not older:
        log(f"Nothing to compress in tier{n}")
        return False

    log(f"Split: {len(older)} chars to compress, {len(newer)} chars to keep")

    # Park the half we are about to delete. Nothing is lost if the
    # response fails validation below.
    pending = pending_path(path)
    pending.write_text(older, encoding="utf-8")

    prompt = episodic_prompt(older, n)
    summary = compress_with_claude(older, prompt)

    ok, reason = validate_summary(summary or "", older, "episodic", f"tier{n}")
    if not ok:
        log(f"REJECTED tier{n} summary: {reason}")
        log(f"Source half kept in {pending.name}; tier{n} left intact")
        return False

    log(f"Got summary: {len(summary)} chars ({len(summary)/len(older)*100:.1f}% of older half)")

    # Append to END of next tier (existing + new = chronological order)
    # Older compressions stay at top, newer compressions added to bottom
    next_path = episodic_path(n + 1)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n{'='*60}\n## [{timestamp}] From tier{n}\n{'='*60}\n\n{summary}\n"

    existing = next_path.read_text(encoding="utf-8") if next_path.exists() else ""
    next_path.write_text(existing + entry, encoding="utf-8")

    # Keep newer half (BOTTOM of original) in current tier
    path.write_text(newer, encoding="utf-8")
    pending.unlink(missing_ok=True)   # validated and written: safe to drop
    log(f"Kept {len(newer)} chars in tier{n}, appended {len(summary)} chars to tier{n+1}")

    # ROBLOX install: semantic extraction runs off the narrative draft only
    # (see compress_narrative_level); there is no tier1 extraction here.

    return True


def trigger_semantic():
    """Run semantic extraction (preferences + antipatterns from narrative draft)."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from semantic import on_draft_compress
        on_draft_compress()
    except Exception as e:
        log(f"Semantic extraction failed: {e}")


def compress_narrative_level(level: str) -> bool:
    """Compress OLDER HALF of narrative level → next level, keep newer half."""
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

    # Split: compress older half (TOP of file), keep newer half (BOTTOM of file)
    older, newer = split_content(content)

    if not older:
        log(f"Nothing to compress in {level}")
        return False

    log(f"Split: {len(older)} chars to compress, {len(newer)} chars to keep")

    # Park the half we are about to delete. Nothing is lost if the
    # response fails validation below.
    pending = pending_path(path)
    pending.write_text(older, encoding="utf-8")

    prompt = narrative_prompt(older, level)
    summary = compress_with_claude(older, prompt)

    ok, reason = validate_summary(summary or "", older, "narrative", level)
    if not ok:
        log(f"REJECTED {level} summary: {reason}")
        log(f"Source half kept in {pending.name}; {level} left intact")
        return False

    log(f"Got summary: {len(summary)} chars ({len(summary)/len(older)*100:.1f}% of older half)")

    # Append to END of next level (existing + new = chronological order)
    # Older compressions stay at top, newer compressions added to bottom
    next_level = NARRATIVE_LEVELS[level_idx + 1]
    next_path = narrative_path(next_level)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n{'='*60}\n## [{timestamp}] From {level}\n{'='*60}\n\n{summary}\n"

    existing = next_path.read_text(encoding="utf-8") if next_path.exists() else ""
    next_path.write_text(existing + entry, encoding="utf-8")

    # semantic.py reads draft.md off disk, so it has to see exactly the half we
    # just archived: not the half we keep, and not both (that double-extracts).
    # Expose `older` for the extraction, then restore `newer` in a finally, so a
    # failure inside semantic.py cannot strand the half we are retaining.
    if level == "draft":
        try:
            path.write_text(older, encoding="utf-8")
            trigger_semantic()
        finally:
            path.write_text(newer, encoding="utf-8")
    else:
        path.write_text(newer, encoding="utf-8")

    pending.unlink(missing_ok=True)   # validated and written: safe to drop
    log(f"Kept {len(newer)} chars in {level}, appended {len(summary)} chars to {next_level}")

    return True


def cascade_compress():
    """Check all tiers/levels and compress as needed.

    The cooldown gates whether a run may start (main()); inside a run we
    compress up to MAX_PER_RUN files back to back. Re-checking the cooldown
    between files meant a run could only ever handle ONE file, so whatever
    came first in cascade order starved everything downstream - and tier0,
    which refills fastest, is always first. Under continuous use (an agent
    running unattended for hours) tier0 took every slot and tier1+ never
    drained.
    """
    compressed_count = 0

    def may_continue() -> tuple[bool, str]:
        if compressed_count >= MAX_PER_RUN:
            return False, f"per-run limit ({MAX_PER_RUN}/run)"
        return hourly_allowed()

    # Episodic: check tier0, tier1, ... until one doesn't exist
    for n in range(100):  # safety limit
        path = episodic_path(n)
        if n > 0 and not path.exists():
            break

        if file_size(path) > episodic_threshold(n):
            allowed, reason = may_continue()
            if not allowed:
                log(f"Stopping run: {reason}; backlog resumes next run")
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
            allowed, reason = may_continue()
            if not allowed:
                log(f"Stopping run: {reason}; backlog resumes next run")
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
