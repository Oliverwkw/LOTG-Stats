"""The strategy guide printed by advise.py / trade.py: the right files per
topic, each once, frontmatter stripped, read live, and a clear line when
memory is absent.

Run: python tests/test_guide.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import guide  # noqa: E402


def _mem(tmp: Path) -> Path:
    (tmp / "MEMORY.md").write_text(
        "- Strategy guide: [dynasty-strategy](dynasty-strategy.md) hub; [new-file](new-file.md)\n"
        "- [manager-profiles](manager-profiles.md): opponents\n")
    for name in set(guide.COMMON + [n for v in guide.TOPICS.values() for n in v] + ["new-file"]):
        (tmp / f"{name}.md").write_text(f"---\nname: {name}\ndescription: x\n---\n\nRULE FROM {name}\n")
    return tmp


def test_topics_print_their_files_once_without_frontmatter():
    with tempfile.TemporaryDirectory() as d:
        mem = _mem(Path(d))
        out = guide.render(["waivers", "startsit"], mem)
        for n in guide.COMMON + guide.TOPICS["waivers"] + guide.TOPICS["startsit"]:
            assert out.count(f"## {n}.md") == 1, n
            assert f"RULE FROM {n}" in out
        assert "description: x" not in out
        assert "new-file" in out.split("other guide files")[1]      # new index entries are surfaced


def test_edits_show_up_on_the_next_render():
    with tempfile.TemporaryDirectory() as d:
        mem = _mem(Path(d))
        (mem / "trade-strategy.md").write_text("---\nname: t\n---\nA NEW LESSON\n")
        assert "A NEW LESSON" in guide.render("trade", mem)


def test_missing_memory_says_so():
    with tempfile.TemporaryDirectory() as d:
        out = guide.render("trade", mem=Path(d))
    assert "project memory not found" in out and "no guide rule was applied" in out


TESTS = [test_topics_print_their_files_once_without_frontmatter, test_edits_show_up_on_the_next_render,
         test_missing_memory_says_so]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall guide checks passed")
