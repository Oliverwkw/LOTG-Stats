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
        if not data.get("event_board"):
            print("  [SKIP] no event board in snapshot to perturb")
            return True
        board = data["event_board"]
        ok = _ok("board covers seasons before the in-progress one",
                 any(" 2024 " in d["label"] or "2024" in d["label"] for d in board),
                 f"{len(board)} places on the board")
        # Model a real overtake: say last week's board had the top two places the
        # other way round, so this week's holder of 1st passes the one recorded
        # there. (Dropping places instead would make an event "pass itself",
        # which is precisely what the diff declines to report.)
        first = next((i for i, d in enumerate(board) if d["rank"] == 1
                      and any(o["sheet"] == d["sheet"] and o["column"] == d["column"]
                              and o["end"] == d["end"] and o["rank"] == 2 for o in board)),
                     None)
        if first is None:
            print("  [SKIP] no board column with a 1st and a 2nd to swap")
            return ok
        a = board[first]
        b = next(o for o in board if o["sheet"] == a["sheet"] and o["column"] == a["column"]
                 and o["end"] == a["end"] and o["rank"] == 2)
        a["key"], b["key"] = b["key"], a["key"]
        a["label"], b["label"] = b["label"], a["label"]
        snap.write_text(json.dumps(data))
        B.main(["--exports", str(exports), "--snapshot", str(snap), "--out", str(h)])
        html = h.read_text()
        ok &= _ok("an overtake → non-empty digest with the event sections",
                  _EMPTY not in html and "All-time leaderboard moves —" in html,
                  f"empty_marker={_EMPTY in html}")
        ok &= _ok("the line reads as a crossing, not a 'no longer' note",
                  " passes " in html and "no longer" not in html)
        return ok


def check_legacy_snapshot_rebaselines():
    """A snapshot written before the all-seasons board carried `event_keys` (the
    current season only). The first run after the change must re-baseline in
    silence — not mail the league every place on a ~1000-entry board."""
    exports = _ROOT / "exports"
    if not (exports / "transactions.csv").exists():
        print("  [SKIP] no real exports present")
        return True
    with tempfile.TemporaryDirectory() as d:
        snap, h = Path(d) / "snap.json", Path(d) / "d.html"
        B.main(["--exports", str(exports), "--snapshot", str(snap), "--out", str(h)])
        data = json.loads(snap.read_text())
        data.pop("event_board", None)
        data["event_keys"] = ["trades|someone's 2020-01-01 trade|O-Score|high:1"]
        snap.write_text(json.dumps(data))
        B.main(["--exports", str(exports), "--snapshot", str(snap), "--out", str(h)])
        return _ok("legacy snapshot re-baselines (empty digest, no mass email)",
                   _EMPTY in h.read_text())


def check_manual_run_addresses_the_maintainer():
    """A hand-triggered run sends the REAL digest, but only to the maintainer.

    Run 462 was a workflow_dispatch and mailed a provisional digest — 65 lines of
    churn from a KTC correction — to all eight league members."""
    import send_digest as S
    cfg = {"recipients": ["a@x.com", "b@x.com", "c@x.com"],
           "test_recipients": ["okeimweiss@gmail.com"]}
    league = S._recipients_for(cfg, False)
    manual = S._recipients_for(cfg, True)
    ok = _ok("the weekly cron still reaches the league", len(league) == 3, league)
    ok &= _ok("a manual run reaches the maintainer only",
              manual == ["okeimweiss@gmail.com"], manual)
    ok &= _ok("--manual is a real flag", "--manual" in open(
        _ROOT / "scripts" / "send_digest.py").read())
    wf = (_ROOT / ".github" / "workflows" / "build.yml").read_text()
    ok &= _ok("the workflow passes it on workflow_dispatch",
              "--skip-empty --manual" in wf and 'github.event_name }}" = "workflow_dispatch"' in wf)
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_year_round_build, check_movement_makes_nonempty,
              check_legacy_snapshot_rebaselines,
              check_manual_run_addresses_the_maintainer):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_build_digest():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
