"""
Hook to log conversation turns to tier0.

Captures:
- UserPromptSubmit → user message
- Stop → claude response (if available in payload)

Logs raw payload to debug.json for inspection.
"""

import sys
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
TIER0_FILE = BASE_DIR / "memory" / "tier0.md"
DEBUG_FILE = BASE_DIR / "hooks" / "debug.json"

def log_entry(role: str, content: str):
    """Append entry to tier0."""
    TIER0_FILE.parent.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%H:%M:%S")

    if len(content) > 3000:
        content = content[:3000] + "...[truncated]"

    entry = f"\n**[{timestamp}] {role}:**\n{content}\n"

    with open(TIER0_FILE, "a", encoding="utf-8") as f:
        f.write(entry)

def log_debug(event: str, data: dict):
    """Log raw event data for debugging."""
    DEBUG_FILE.parent.mkdir(exist_ok=True)

    debug_entry = {
        "timestamp": datetime.now().isoformat(),
        "event": event,
        "payload": data
    }

    # Append to debug log
    existing = []
    if DEBUG_FILE.exists():
        try:
            existing = json.loads(DEBUG_FILE.read_text())
        except:
            existing = []

    existing.append(debug_entry)
    # Keep last 20 entries
    existing = existing[-20:]
    DEBUG_FILE.write_text(json.dumps(existing, indent=2))

def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw else {}

        event = data.get("hook_event_name", "unknown")

        # Always log for debugging
        log_debug(event, data)

        if event == "UserPromptSubmit":
            prompt = data.get("prompt", "")
            if prompt:
                log_entry("User", prompt)

        elif event == "Stop":
            # Check if response is in payload
            response = data.get("response") or data.get("message") or data.get("content") or data.get("text")
            if response:
                log_entry("Claude", response)
            else:
                # Log that we got Stop but no response text
                log_entry("Claude", f"[Stop event - keys: {list(data.keys())}]")

    except Exception as e:
        print(f"Hook error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
