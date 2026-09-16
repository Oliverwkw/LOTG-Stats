"""Guard: no already-compressed build output may be committed.

`exports/LOTG_Exports.zip` (dropped in PR #420) and `exports/LOTG_Stats.xlsx`
(PR #428) were both written to `exports/` by every build and both committed
back by the refresh step. An .xlsx IS a zip, so for both files git could
neither zlib nor delta the content: every rebuild stored a fresh full blob of
~9.4 MB and ~6.8 MB respectively. Between them they reached 618 MB — 71% of
every blob byte in the repo — for data the repo already had in the CSVs
sitting beside them.

That cost is UNRECLAIMABLE. Committed history cannot be pruned without a
`filter-repo` rewrite that changes every SHA and breaks every clone, so by the
time the symptom is visible (slow clones, slow CI checkouts) the bytes are
permanent. The damage is done by accumulation, not by any single commit, which
is why this has to be a guard and not a code review: nobody notices 7 MB.

Both fixes live only as `.gitignore` entries. Three things silently undo them:

  * `git add -f exports/LOTG_Stats.xlsx` — `-f` overrides .gitignore.
  * A NEW build output in a compressed format (a second workbook, a .parquet,
    a .tar.gz of the snapshot). The .gitignore entries name two exact paths;
    they cannot cover a file nobody has thought of yet.
  * A `.gitignore` edit that drops or mis-scopes an entry.

So this guard asserts the CLASS, not the two paths. It sniffs magic bytes
rather than trusting extensions, because a compressed container is just as
undeltifiable when it is called `snapshot.dat`.

There is deliberately NO allowlist. At the time of writing all 1507 tracked
files are text — the repo commits no binaries at all — so the honest invariant
is simply "everything committed here is text", with no exemption list to rot.
If a genuinely necessary binary ever has to be committed, add it explicitly
below with a comment saying why it is worth permanent history.

Note this checks TRACKED files only. The build still writes the workbook and
the zip into `exports/` on every run and still ships them in the LOTG_outputs
artifact; .gitignore keeps them out of the index, and `git ls-files` therefore
never sees them. A CI build having those files on disk is correct and must not
trip this test.

Run: python tests/test_no_binary_blobs_committed.py
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Leading bytes of the container formats git cannot delta. zip covers .xlsx,
# .docx, .pptx, .jar and .whl — they are all zips with a different extension.
_COMPRESSED_MAGIC = {
    b"PK\x03\x04": "zip (or xlsx/docx/pptx/jar/whl, which are zips)",
    b"PK\x05\x06": "zip (empty archive)",
    b"PK\x07\x08": "zip (spanned archive)",
    b"\x1f\x8b": "gzip",
    b"BZh": "bzip2",
    b"\xfd7zXZ\x00": "xz",
    b"7z\xbc\xaf\x27\x1c": "7-zip",
    b"Rar!\x1a\x07": "rar",
    b"\x28\xb5\x2f\xfd": "zstd",
    b"\x04\x22\x4d\x18": "lz4",
    b"PAR1": "parquet",
}

# Nothing is exempt today. See the module docstring before adding anything.
_ALLOWED: set[str] = set()

# A tripwire for a pathologically large file, well clear of the largest
# legitimate one (exports/snapshot/sleeper_players_nfl.json, ~18 MB) and well
# under the 100 MB blob that GitHub refuses outright. Text this big still
# deltas, so this is a smoke alarm, not the main guard — if it ever trips,
# work out what the file is before bumping it.
_MAX_TRACKED_MB = 50


def _tracked_files() -> list[str] | None:
    """Paths git has in the index, or None when this is not a git checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT), "ls-files", "-z"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.split("\0") if p]


def _classify(path: Path) -> str | None:
    """Name the disqualifying property of `path`, or None if it is fine."""
    try:
        head = path.open("rb").read(8192)
    except OSError:
        return None  # tracked but not on disk; nothing to judge
    for magic, label in _COMPRESSED_MAGIC.items():
        if head.startswith(magic):
            return f"already-compressed: {label}"
    if b"\x00" in head:
        return "binary (NUL byte in first 8KB)"
    return None


def test_no_compressed_or_binary_file_is_committed():
    tracked = _tracked_files()
    if tracked is None:
        import pytest
        pytest.skip("not a git checkout")

    offenders = []
    for rel in tracked:
        if rel in _ALLOWED:
            continue
        why = _classify(_ROOT / rel)
        if why:
            offenders.append(f"  {rel} — {why}")

    assert not offenders, (
        f"{len(offenders)} committed file(s) git cannot delta:\n"
        + "\n".join(sorted(offenders))
        + "\n\nEvery rebuild of one of these stores a fresh full copy, and that "
          "history can never be reclaimed. This is what PRs #420 and #428 "
          "removed. If the file is a build output, add it to .gitignore and "
          "ship it in the LOTG_outputs artifact instead; if it genuinely must "
          "be committed, add it to _ALLOWED with a reason."
    )


def test_no_tracked_file_is_pathologically_large():
    tracked = _tracked_files()
    if tracked is None:
        import pytest
        pytest.skip("not a git checkout")

    too_big = []
    for rel in tracked:
        p = _ROOT / rel
        try:
            mb = p.stat().st_size / 1048576
        except OSError:
            continue
        if mb > _MAX_TRACKED_MB:
            too_big.append(f"  {rel} — {mb:.1f} MB")

    assert not too_big, (
        f"{len(too_big)} tracked file(s) over {_MAX_TRACKED_MB} MB:\n"
        + "\n".join(sorted(too_big))
        + "\n\nWork out what the file is before raising the ceiling."
    )


if __name__ == "__main__":
    test_no_compressed_or_binary_file_is_committed()
    test_no_tracked_file_is_pathologically_large()
    print("ok: every tracked file is text and under "
          f"{_MAX_TRACKED_MB} MB")
