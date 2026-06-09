"""Phase 12 #43: data-quality sanity ranges over the built CSVs.

Asserts there are no ERROR findings from `lotg_support.sanity` (win% in [0,1],
non-negative counts, no inf). WARN findings (implausible age, N/A-vs-0 blanks)
are printed but don't fail. SKIPS cleanly when no build is present.

Run: python tests/test_sanity_ranges.py [exports_dir]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support.sanity import collect_findings, summarize  # noqa: E402


def _exports_dir() -> Path:
    # Test-time exports dir: $LOTG_EXPORTS or the default. Deliberately does NOT
    # read sys.argv — under pytest sys.argv holds pytest's own args ("tests/",
    # "-v"), which made this guard silently SKIP ("no built exports") in CI. The
    # CLI path below handles an explicit dir argument.
    return Path(os.environ.get("LOTG_EXPORTS", _ROOT / "exports"))


def test_sanity_ranges():
    d = _exports_dir()
    if not (d / "team_year.csv").exists():
        import pytest  # type: ignore
        pytest.skip("no built exports present")
    findings = collect_findings(d)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert not errors, "sanity ERRORs:\n  " + "\n  ".join(
        f"{f.sheet}.{f.column}: {f.detail}" for f in errors
    )


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else _exports_dir()
    if not (d / "team_year.csv").exists():
        print("No built exports found; skipping.")
        sys.exit(0)
    fs = collect_findings(d)
    print(summarize(fs))
    for f in fs:
        print(f"  {f.severity:5} {f.sheet}.{f.column}: {f.detail}")
    sys.exit(1 if any(f.severity == "ERROR" for f in fs) else 0)
