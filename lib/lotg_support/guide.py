"""The league strategy guide, printed next to the data it applies to.

The guide lives in project memory (one Markdown file per subject, indexed by
MEMORY.md's "Strategy guide" line), not in the repo, because every session
updates it as lessons come up. `scripts/advise.py` and `scripts/trade.py`
print the files that fit the question at the end of their output, read live
from memory each run, so the guide is used on every advice answer without a
second tool call — and a lesson added to a file shows up on the next run.

    from lotg_support import guide
    print(guide.render("waivers"))

Memory is found at $LOTG_MEMORY_DIR, else the first `*/memory/**/MEMORY.md`
under /tmp/claude* that has a "Strategy guide" line. No memory (a run on
GitHub Actions, a subagent without it) prints one line saying so, so the
answer can say no guide rule was applied.
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

# Always first: the 8-team caveat applies to every call.
COMMON = ["league-size-caveat"]

# Which files answer which question. Order = reading order (hub first).
TOPICS: Dict[str, List[str]] = {
    "startsit": ["weekly-lineup-strategy", "start-sit-edges", "player-evaluation"],
    "waivers": ["waivers-streaming", "player-evaluation", "league-settings"],
    "strategy": ["dynasty-strategy", "season-arc", "league-2026-windows", "rookie-picks",
                 "dynasty-age-curves"],
    "roster": ["dynasty-strategy", "dynasty-age-curves", "player-evaluation"],
    "trade": ["dynasty-strategy", "trade-strategy", "manager-profiles", "negotiation-styles",
              "league-2026-windows", "dynasty-age-curves", "ktc-caveats"],
}

_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


def memory_dir() -> Optional[Path]:
    env = os.environ.get("LOTG_MEMORY_DIR")
    if env and (Path(env) / "MEMORY.md").exists():
        return Path(env)
    for p in sorted(glob.glob("/tmp/claude*/memory/**/MEMORY.md", recursive=True)):
        try:
            if "Strategy guide" in Path(p).read_text(errors="replace"):
                return Path(p).parent
        except OSError:
            continue
    return None


def indexed(mem: Path) -> List[str]:
    """Every file MEMORY.md links on its strategy-guide and partner lines."""
    out: List[str] = []
    for line in (mem / "MEMORY.md").read_text(errors="replace").splitlines():
        if "Strategy guide" in line or "manager-profiles" in line:
            out += [m for m in re.findall(r"\]\(([\w.-]+)\.md\)", line) if m not in out]
    return out


def render(topic: Union[str, Sequence[str]], mem: Optional[Path] = None) -> str:
    """The guide files for one topic, or for several (each file once)."""
    topics = [topic] if isinstance(topic, str) else list(topic)
    topic = " + ".join(topics)
    mem = memory_dir() if mem is None else mem
    if mem is None or not (mem / "MEMORY.md").exists():
        return ("# STRATEGY GUIDE: project memory not found here — say no guide rule was applied "
                "(set LOTG_MEMORY_DIR to point at it)")
    names = list(COMMON)
    for t in topics:
        names += [n for n in TOPICS.get(t, []) if n not in names]
    parts = [f"# STRATEGY GUIDE ({topic}) — read live from {mem}. Apply it, cite the rule you used; "
             "add or correct a line in the file when this answer teaches something new."]
    missing = []
    for n in names:
        f = mem / f"{n}.md"
        if not f.exists():
            missing.append(n)
            continue
        parts.append(f"\n## {n}.md\n" + _FRONTMATTER.sub("", f.read_text(errors="replace")).strip())
    others = [n for n in indexed(mem) if n not in names and (mem / f"{n}.md").exists()]
    if missing:
        parts.append(f"\n# not found in memory: {', '.join(missing)} (renamed? check MEMORY.md)")
    if others:
        parts.append(f"\n# other guide files (read if the question reaches them): {', '.join(others)}")
    return "\n".join(parts)
