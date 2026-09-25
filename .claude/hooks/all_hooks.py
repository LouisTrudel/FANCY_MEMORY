"""
Hook handler - logs conversation to memory system

Episodic: memory/episodic/tier0.md (User + Claude responses)
Narrative: memory/narrative/draft.md (User + Claude responses + thinking)

Auto-compression spawned when thresholds exceeded.
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
EPISODIC_DIR = BASE_DIR / "memory" / "episodic"
NARRATIVE_DIR = BASE_DIR / "memory" / "narrative"
DEBUG_LOG = Path(__file__).parent / "events.log"
COMPRESS_SCRIPT = Path(__file__).parent / "compress.py"

# Thresholds (must match compress.py)
EPISODIC_TIER0_THRESHOLD = 20_000
NARRATIVE_DRAFT_THRESHOLD = 25_000


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


def log_narrative(role: str, content: str, thinking: str = None):
    """Append to narrative/draft.md (with thinking)."""
    ensure_dirs()
    draft = NARRATIVE_DIR / "draft.md"
    timestamp = datetime.now().strftime("%H:%M:%S")

    entry = f"\n**[{timestamp}] {role}:**\n"
    if thinking:
        entry += f"<thinking>\n{thinking}\n</thinking>\n\n"
    entry += f"{content}\n"

    with open(draft, "a", encoding="utf-8") as f:
        f.write(entry)


def log_debug(event: str, data: dict):
    """Append raw event to debug log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload_str = json.dumps(data, indent=2, default=str)
    entry = f"\n{'='*60}\n[{timestamp}] {event}\n{'='*60}\n{payload_str}\n"

    with open(DEBUG_LOG, "a", encoding="utf-8") as f:
        f.write(entry)


def maybe_compress():
    """Spawn compression if any threshold exceeded."""
    episodic_tier0 = EPISODIC_DIR / "tier0.md"
    narrative_draft = NARRATIVE_DIR / "draft.md"

    needs_compression = False

    if episodic_tier0.exists() and episodic_tier0.stat().st_size > EPISODIC_TIER0_THRESHOLD:
        needs_compression = True
        print(f"[HOOK] episodic/tier0 exceeds threshold", file=sys.stderr)

    if narrative_draft.exists() and narrative_draft.stat().st_size > NARRATIVE_DRAFT_THRESHOLD:
        needs_compression = True
        print(f"[HOOK] narrative/draft exceeds threshold", file=sys.stderr)

    if needs_compression:
        subprocess.Popen(
            ["python", str(COMPRESS_SCRIPT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )


def extract_last_assistant(transcript_path: str) -> dict:
    """Extract last assistant message from transcript JSONL."""
    result = {"thinking": None, "text": None}

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in reversed(lines):
            try:
                obj = json.loads(line)
                if obj.get("type") != "assistant":
                    continue

                msg = obj.get("message", {})
                content = msg.get("content", [])

                for item in content:
                    if not isinstance(item, dict):
                        continue

                    if item.get("type") == "thinking" and not result["thinking"]:
                        result["thinking"] = item.get("thinking", "")

                    if item.get("type") == "text" and not result["text"]:
                        result["text"] = item.get("text", "")

                if result["thinking"] and result["text"]:
                    break

            except json.JSONDecodeError:
                continue

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

                    # Narrative: response + thinking
                    log_narrative("Claude", assistant["text"], assistant["thinking"])

            maybe_compress()

    except Exception as e:
        print(f"[HOOK ERROR] {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
