"""
Hook handler - logs conversation to the memory system.

Episodic: memory/episodic/tier0.md (user prompts + assistant replies)
Narrative: memory/narrative/draft.md (user prompts + assistant replies)

Only the assistant's visible text is recorded.
Auto-compression spawned when thresholds exceeded.
"""

import sys
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
EPISODIC_DIR = BASE_DIR / "memory" / "episodic"
NARRATIVE_DIR = BASE_DIR / "memory" / "narrative"
DEBUG_LOG = Path(__file__).parent / "events.log"
COMPRESS_SCRIPT = Path(__file__).parent / "compress.py"

# No threshold constants here on purpose: over_threshold() imports the table
# from compress.py, which owns it. A second copy drifted once already - draft
# stayed at 25_000 after compress.py moved to 50_000.


def ensure_dirs():
    """Create memory directories if needed."""
    EPISODIC_DIR.mkdir(parents=True, exist_ok=True)
    NARRATIVE_DIR.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "memory" / "semantic" / "skills").mkdir(parents=True, exist_ok=True)


def log_episodic(role: str, content: str):
    """Append to episodic/tier0.md (no thinking)."""
    ensure_dirs()
    tier0 = EPISODIC_DIR / "tier0.md"
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"\n**[{timestamp}] {role}:**\n{content}\n"

    with open(tier0, "a", encoding="utf-8") as f:
        f.write(entry)


def log_narrative(role: str, content: str):
    """Append to narrative/draft.md."""
    ensure_dirs()
    draft = NARRATIVE_DIR / "draft.md"
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"\n**[{timestamp}] {role}:**\n{content}\n"

    with open(draft, "a", encoding="utf-8") as f:
        f.write(entry)


# Debug capture only. NOTHING in the memory system reads events.log -
# inject_memory() and compression never open it. It exists purely so a human
# can inspect what the hooks received.
#
# It had reached 95MB in 27 hours, and 98% of that was PreToolUse/PostToolUse
# carrying entire tool payloads (~9KB each, pretty-printed over ~31 lines) that
# feed neither episodic nor narrative memory. Only Stop and UserPromptSubmit
# drive the memory system, so only those are kept, one compact line each.
DEBUG_EVENTS = {"Stop", "UserPromptSubmit", "SubagentStop"}
DEBUG_MAX_BYTES = 10_000_000      # rotate past this; set to 0 to log nothing
DEBUG_MAX_PAYLOAD = 4_000         # truncate any single payload past this


def log_debug(event: str, data: dict):
    """Append one compact line per kept event, with rotation."""
    if not DEBUG_MAX_BYTES or event not in DEBUG_EVENTS:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload_str = json.dumps(data, default=str)
    if len(payload_str) > DEBUG_MAX_PAYLOAD:
        payload_str = (payload_str[:DEBUG_MAX_PAYLOAD]
                       + f"... [truncated from {len(payload_str)} bytes]")
    entry = f"[{timestamp}] {event} {payload_str}\n"

    try:
        if DEBUG_LOG.exists() and DEBUG_LOG.stat().st_size + len(entry) > DEBUG_MAX_BYTES:
            DEBUG_LOG.replace(DEBUG_LOG.with_suffix(".1.log"))
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass    # debug logging must never break a hook


def over_threshold() -> list:
    """Every tier/level currently above its own threshold.

    Checking only tier0 and draft meant a backlog anywhere else (tier1+,
    chapter, book) never triggered a run of its own - it was picked up only
    when tier0 or draft happened to trip at the same time. compress.py owns
    the threshold table, so import it instead of keeping a second copy here.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from compress import (
            episodic_path, episodic_threshold,
            narrative_path, NARRATIVE_LEVELS, NARRATIVE_THRESHOLDS,
        )
    except Exception as e:
        print(f"[HOOK] threshold check unavailable: {e}", file=sys.stderr)
        return []

    over = []
    for n in range(100):  # safety limit
        p = episodic_path(n)
        if n > 0 and not p.exists():
            break
        if p.exists() and p.stat().st_size > episodic_threshold(n):
            over.append("episodic/tier%d" % n)

    for level in NARRATIVE_LEVELS[:-1]:  # collection never compresses
        p = narrative_path(level)
        if p.exists() and p.stat().st_size > NARRATIVE_THRESHOLDS[level]:
            over.append("narrative/" + level)

    return over


def maybe_compress():
    """Spawn compression if any tier or narrative level exceeds its threshold.

    A .compression-paused flag in memory/ suspends compression only, without
    touching the thresholds, so a maintenance pass can rewrite memory files
    without a trigger firing into them mid-edit. Logging continues. Delete the
    file to resume. (The heavier switch is hooks/.paused, which stops logging
    too - see __main__ below.)
    """
    if (BASE_DIR / "memory" / ".compression-paused").exists():
        print("[HOOK] compression paused (.compression-paused present)", file=sys.stderr)
        return

    over = over_threshold()

    if over:
        print("[HOOK] over threshold: " + ", ".join(over), file=sys.stderr)
        subprocess.Popen(
            ["python", str(COMPRESS_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )


# A delegated run can return a very long report, and a heavy session delegates
# ~100 times. 2_000 bytes keeps the task and its outcome while capping what one
# agent can add to a 20_000-byte tier.
SUBAGENT_REPORT_CAP = 2_000


def clip(text: str, cap: int) -> str:
    """Trim to cap, marking what was dropped so a short report is never ambiguous."""
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n[...report clipped from {len(text)} bytes]"


def subagent_report(data: dict) -> tuple:
    """(label, report) from a SubagentStop payload; ("", "") when unusable.

    The payload schema is not documented, so take the inline message if it is
    there and fall back to the subagent's own transcript. SubagentStop is in
    DEBUG_EVENTS, so events.log keeps the real keys for refining this later.
    """
    # Observed across 37 real payloads: agent_type is always present but is an
    # empty string for 14 of them (unnamed/default agents), hence the fallback
    # to a generic label. "description" was in the guessed chain and is dropped
    # here - it only ever appears nested inside background_tasks, never at the
    # top level, so it could not have matched.
    label = (data.get("agent_type") or data.get("subagent_type")
             or data.get("agent_name") or "subagent")
    text = data.get("last_assistant_message") or ""
    if not text:
        # agent_transcript_path, NOT transcript_path. The payload carries both:
        # transcript_path is the MAIN session's, so using it would log the main
        # thread's last message as this subagent's report - a wrong footprint,
        # which is worse than a thin one.
        path = data.get("agent_transcript_path")
        if path:
            text = extract_last_assistant(path).get("text") or ""
    return str(label).strip() or "subagent", text


def extract_last_assistant(transcript_path: str) -> dict:
    """Return the last assistant message's visible text from the transcript JSONL."""
    result = {"text": None}

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in reversed(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "assistant":
                continue

            for item in obj.get("message", {}).get("content", []):
                if isinstance(item, dict) and item.get("type") == "text":
                    result["text"] = item.get("text", "")
                    break

            if result["text"]:
                break

    except Exception as e:
        print(f"[HOOK] Error reading transcript: {e}", file=sys.stderr)

    return result


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        event = data.get("hook_event_name", "UNKNOWN")

        log_debug(event, data)
        print(f"[HOOK] {event}", file=sys.stderr)

        if event == "UserPromptSubmit":
            prompt = data.get("prompt", "")
            if prompt:
                # Log to both systems
                log_episodic("User", prompt)
                log_narrative("User", prompt)

        elif event == "Stop":
            transcript_path = data.get("transcript_path")
            if transcript_path:
                assistant = extract_last_assistant(transcript_path)

                if assistant["text"]:
                    # Episodic: just the response
                    log_episodic("Claude", assistant["text"])

                    # Narrative: the visible reply
                    log_narrative('Claude', assistant['text'])

            maybe_compress()

        elif event == "SubagentStop":
            label, report = subagent_report(data)
            if report:
                entry = clip(report, SUBAGENT_REPORT_CAP)
                log_episodic(f"Subagent({label})", entry)
                log_narrative(f"Subagent({label})", entry)

            # Not deferred to the next main Stop: a long delegated stretch can
            # add 100+ capped reports before one arrives.
            maybe_compress()

    except Exception as e:
        print(f"[HOOK ERROR] {e}", file=sys.stderr)


# Set by compress.py and semantic.py on the `claude -p` subprocesses they
# spawn. Those subprocesses run inside this project, so without this guard
# their UserPromptSubmit carries the whole compression prompt and their Stop
# carries the summary - both logged back into the files being compressed.
HOOK_GUARD_ENV = "MEMORY_HOOKS_DISABLED"


if __name__ == "__main__":
    # Drop a file named .paused beside this script to disable logging.
    paused = (Path(__file__).parent / ".paused").exists()

    if os.environ.get(HOOK_GUARD_ENV):
        print("[HOOK] skipped: compression subprocess", file=sys.stderr)
    elif not paused:
        main()
