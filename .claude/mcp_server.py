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

mcp = MCPServer("fancy_memory")

# Resolved from this file, not the cwd. As a relative path it silently returned
# "No memory context yet" whenever the server was launched from anywhere else,
# which reads as empty memory rather than as a misconfiguration.
MEMORY_DIR = Path(__file__).resolve().parent / "memory"


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
        "preferences": 6_000,     # tracks PREFS_CAP = 40 in semantic.py
        # 11_000 = ANTIPATTERNS_CAP (40) x the measured ~262b/entry. Keep these
        # two in step: a budget below its own entry cap truncates a full list,
        # which is the unit mismatch this file's antipatterns warn about.
        "antipatterns": 11_000,
        # no skill_tree entry: lookup-only, never injected, so it needs no cap
        # 20_000 so tier1 injects WHOLE even at its 15K compression threshold:
        # pass 1 gives tier1 10_000 and tier2 5_000, then pass 2 hands tier1
        # the remaining 5_000 for a full 15_000, leaving tier2 a 5_000 tail -
        # the right shape, since beyond tier2 the history is ignorable. At
        # 19_000 tier1 peaked at 14_250/15_000; at 12_000 it got 9_000/14_240
        # and tier2 3_000/3_993, so both truncated on every injection.
        "digests": 20_000,        # tier1 + tier2, shared
        "recent": 3_000,          # tier0, role-filtered
    }

    # tier0 is the raw transcript, where Claude's prose outweighs the user's by
    # ~19x and restates what tier1 already holds as tagged bullets. Keep the
    # user's words whole and clip each reply to its opening claim, which is
    # where the verdict sits. A full tier0 tail cost 10,000 chars and carried
    # about two replies; this carries a whole session in under 2,000.
    REPLY_HEAD = 180
    # Anchored to line start, NOT to a preceding blank line. The blank line is
    # not guaranteed: half-split compression cuts at a line midpoint and can
    # leave a marker with a single newline before it, and two markers in the
    # live tier0 were preceded by one newline. Requiring two silently dropped
    # them - and dropping a user message is the worst failure this filter has.
    # The cost is that a reply quoting a marker at column 0 splits a turn in
    # two, which is visible and harmless next to losing the user's words.
    # Subagent(<type>) is a third role. It has to be a boundary here, not just
    # a recognised name: without it a delegated report is swallowed into the
    # preceding Claude turn's body and clipped away with it.
    ROLE = r"User|Claude|Subagent\([^)]*\)"
    TURN_RE = re.compile(
        r"^\*\*\[(\d{2}:\d{2}:\d{2})\] (" + ROLE + r"):\*\*[ \t]*\n"
        r"(.*?)(?=^\*\*\[\d{2}:\d{2}:\d{2}\] (?:" + ROLE + r"):\*\*|\Z)",
        re.S | re.M,
    )

    def read_file(path, max_chars=None):
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8").strip()
        if max_chars and len(content) > max_chars:
            return content[:max_chars] + "\n\n[...truncated...]"
        return content

    def recent_exchange(budget):
        """Newest tier0 turns: user verbatim, replies clipped to their head."""
        raw = read_file(EPISODIC_DIR / "tier0.md")
        if not raw:
            return ""
        turns = TURN_RE.findall(raw)
        kept, used = [], 0
        for ts, role, body in reversed(turns):
            body = body.strip()
            if role != "User" and len(body) > REPLY_HEAD:
                body = body[:REPLY_HEAD].rstrip() + " [...]"
            entry = f"**[{ts}] {role}:** {body}"
            if used + len(entry) > budget:
                if kept:
                    break
                entry = entry[:budget]      # one oversized turn: keep its head
            kept.append(entry)
            used += len(entry)
        return "\n\n".join(reversed(kept))

    def cascade_digests(budget):
        """tier1..tier2, newest first.

        No tier may claim more than half of what is left, so an oversized tier1
        cannot starve the tiers beneath it - the old shared budget let tier0 do
        exactly that and tier1+ never appeared at all. A second pass hands any
        unspent budget back to the newest truncated tier.
        """
        tiers = []
        # tier1..tier2 only. Beyond tier2 the history is old enough to ignore
        # at injection time; tier3+ stays on disk, reachable via search_memory().
        # Walking to tier9 also let each new tier claim a share of a fixed
        # budget, shrinking tier1 as the archive grew.
        for n in range(1, 3):
            p = EPISODIC_DIR / f"tier{n}.md"
            if not p.exists():
                break
            content = read_file(p)
            if content:
                tiers.append([n, content, 0])

        remaining = budget
        for t in tiers:
            if remaining <= 0:
                break
            t[2] = min(len(t[1]), max(remaining // 2, 0))
            remaining -= t[2]

        for t in tiers:
            if remaining <= 0:
                break
            extra = min(len(t[1]) - t[2], remaining)
            t[2] += extra
            remaining -= extra

        out = []
        for n, content, take in tiers:
            if take <= 0:
                continue
            body = content if take >= len(content) else \
                "[...earlier content...]\n\n" + content[-take:]
            out.append(f"### tier{n}\n{body}")
        return "\n\n".join(out)

    # Order follows 20-80-20: what steers behaviour goes in the opening slot,
    # bulk reference takes the weak middle, and the live thread sits in the
    # closing slot where it is most likely to be referenced next.
    sections = []

    prefs = read_file(SEMANTIC_DIR / "preferences.md", LIMITS["preferences"])
    if prefs:
        sections.append(f"## Preferences\n{prefs}")

    anti = read_file(SEMANTIC_DIR / "antipatterns.md", LIMITS["antipatterns"])
    if anti:
        sections.append(f"## Antipatterns\n{anti}")

    # A pointer, not content. These files are the recall half of the system:
    # knowing they exist is what makes a lookup happen, the way a person knows
    # they have been burned by something before without holding the detail.
    lookup = [n for n in ("topics.md", "skillTree.md")
              if (SEMANTIC_DIR / n).exists()]
    if lookup:
        sections.append(
            "## On Demand\n"
            "*Not injected: "
            + ", ".join(f"`memory/semantic/{n}`" for n in lookup)
            + ". `topics.md` holds per-topic do's and don'ts, in more detail "
            "than the injected files carry. Reach for `search_memory()` for a "
            "hit map, or an Explore agent over `memory/` when the wording is "
            "uncertain.*"
        )

    digests = cascade_digests(LIMITS["digests"])
    if digests:
        sections.append(f"## History (compressed)\n{digests}")

    recent = recent_exchange(LIMITS["recent"])
    if recent:
        sections.append(
            "## Recent Exchange\n"
            "*User messages verbatim; replies clipped to their opening claim. "
            "Use search_memory() for the full text.*\n\n" + recent
        )

    if not sections:
        return "No memory context yet. Start working and it will accumulate."

    total = sum(len(s) for s in sections)
    # ~3.5 chars/token for markdown carrying code, paths and tables. The old
    # //4 understated this payload by roughly 15%.
    return f"# Memory Context (~{round(total / 3.5)} tokens)\n\n" + "\n\n---\n\n".join(sections)


@mcp.tool()
def search_memory(query: str) -> str:
    """
    Locate where a topic appears across memory. Returns a hit map, not content.

    Per file: how many lines matched, and which line numbers. Read the lines you
    want afterward, or hand an Explore agent the memory folder when the question
    is open-ended and you do not know the right keyword yet.

    Use when the user refers to past events, decisions or history, or to check
    whether the project has covered some ground before.

    Args:
        query: Search terms, space-separated. Terms are OR'd; with more than one
               term the map also reports which lines matched ALL of them.

    Returns a per-file hit map, densest file first.
    """
    if not MEMORY_DIR.exists():
        return "No memory directory found."

    keywords = [w.lower() for w in re.findall(r"\w+", query) if len(w) >= 3]
    if not keywords:
        return "No valid search terms. Use words with 3+ characters."

    # A map stays small however many hits there are, so there is no result cap -
    # the old 10-hit cap plus alphabetical file order meant a common term filled
    # every slot from episodic/tier0 and narrative/ was never reached at all.
    MAX_LINES_SHOWN = 24

    rows, seen_dirs, hit_dirs, scanned = [], set(), set(), 0
    for md_file in sorted(MEMORY_DIR.rglob("*.md")):
        try:
            lines = md_file.read_text(encoding="utf-8", errors="replace").split("\n")
        except Exception:
            continue
        scanned += 1

        hits, all_hits = [], []
        for i, line in enumerate(lines, start=1):
            low = line.lower()
            matched = [kw for kw in keywords if kw in low]
            if matched:
                hits.append(i)
                if len(matched) == len(keywords) > 1:
                    all_hits.append(i)

        rel = md_file.relative_to(MEMORY_DIR).as_posix()
        top = rel.split("/")[0] if "/" in rel else "."
        seen_dirs.add(top)
        if hits:
            rows.append((len(hits), rel, hits, all_hits))
            hit_dirs.add(top)

    if not rows:
        return (f"No matches for: {', '.join(keywords)}  ({scanned} files scanned)\n"
                "Try fewer or broader terms, or delegate an Explore agent over "
                "memory/ if the wording is uncertain.")

    rows.sort(key=lambda r: (-r[0], r[1]))
    width = max(len(r[1]) for r in rows)

    out = [f"Hit map for: {', '.join(keywords)}   "
           f"({len(rows)} of {scanned} files matched)", ""]
    for count, rel, hits, all_hits in rows:
        shown = ", ".join(str(n) for n in hits[:MAX_LINES_SHOWN])
        if len(hits) > MAX_LINES_SHOWN:
            shown += f", +{len(hits) - MAX_LINES_SHOWN} more"
        label = "hits  lines" if count != 1 else "hit   line "
        line = f"  {rel:<{width}}  {count:>4} {label} {shown}"
        if all_hits:
            line += f"\n  {'':<{width}}         all terms on line{'s' if len(all_hits) > 1 else ''} " \
                    + ", ".join(str(n) for n in all_hits[:8])
        out.append(line)

    silent = sorted(d for d in seen_dirs - hit_dirs if d != ".")
    if silent:
        out += ["", "  nothing in: " + ", ".join(f"{d}/" for d in silent)]
    out += ["", "  Read the lines you need, or delegate an Explore agent over "
            "memory/ for open-ended recall."]
    return "\n".join(out)


if __name__ == "__main__":
    mcp.run(transport="stdio")
