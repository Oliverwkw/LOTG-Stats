"""Phase 14: year-round digest build (offseason no longer gated).

The digest now runs the identical diff pipeline in-season and off — the offseason
is not skipped. A build with no prior snapshot baselines silently; a re-build
against that snapshot with unchanged data produces an EMPTY digest (the
"No leaderboard changes this week." marker → send_digest --skip-empty suppresses
it, so a quiet week sends no email); and when the snapshot shows movement, the
digest is non-empty and carries the same section structure as in-season.

Runs against the real committed exports (offseason: season 2026, 0 weeks) and
SKIPs cleanly if they're absent.

Run: PYTHONPATH=src:lib python tests/test_build_digest.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "lib"))

import build_digest as B  # noqa: E402

_EMPTY = "No leaderboard changes this week."


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def check_year_round_build():
    exports = _ROOT / "exports"
    if not (exports / "team_year.csv").exists():
        print("  [SKIP] no real exports present")
        return True
    with tempfile.TemporaryDirectory() as d:
        snap = Path(d) / "snap.json"
        h0, h1 = Path(d) / "d0.html", Path(d) / "d1.html"

        # 1) Offseason baseline: builds (not skipped), writes a snapshot, empty digest.
        rc0 = B.main(["--exports", str(exports), "--snapshot", str(snap), "--out", str(h0)])
        ok = _ok("offseason build returns 0 (not skipped)", rc0 == 0)
        ok &= _ok("snapshot written in the offseason", snap.exists())
        meta = json.loads(snap.read_text())["meta"]
        ok &= _ok("offseason meta (0 weeks) confirmed", int(meta["weeks_completed"]) == 0, f"meta={meta}")
        ok &= _ok("baseline digest is empty (would be suppressed)", _EMPTY in h0.read_text())

        # 2) Re-build against that snapshot, unchanged data → still empty (no movement).
        rc1 = B.main(["--exports", str(exports), "--snapshot", str(snap), "--out", str(h1)])
        ok &= _ok("no-movement rebuild returns 0", rc1 == 0)
        ok &= _ok("no-movement digest empty → send suppressed", _EMPTY in h1.read_text())
        return ok


def check_movement_makes_nonempty():
    """Drop an event key from the snapshot so that event re-fires as 'new' — proves
    movement yields a non-empty digest (the same mechanism as a real weekly diff)."""
    exports = _ROOT / "exports"
    if not (exports / "transactions.csv").exists():
        print("  [SKIP] no real exports present")
        return True
    with tempfile.TemporaryDirectory() as d:
        snap = Path(d) / "snap.json"
        h = Path(d) / "d.html"
        B.main(["--exports", str(exports), "--snapshot", str(snap), "--out", str(h)])
        data = json.loads(snap.read_text())
        if not data.get("event_keys"):
            print("  [SKIP] no event keys in snapshot to perturb")
            return True
        data["event_keys"] = data["event_keys"][:-3]   # forget 3 events → they re-fire
        snap.write_text(json.dumps(data))
        B.main(["--exports", str(exports), "--snapshot", str(snap), "--out", str(h)])
        html = h.read_text()
        return _ok("movement → non-empty digest with in-season structure",
                   _EMPTY not in html and "Notable" in html, f"empty_marker={_EMPTY in html}")


def run_all() -> bool:
    all_ok = True
    for t in (check_year_round_build, check_movement_makes_nonempty):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_build_digest():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
