"""Regression guard for the PR E in-season freshness fixes (A, B, C).

These confirm the pipeline behaves correctly during a LIVE season — the case
that can't be exercised by the current (offseason) build, where the real data
makes A/B/C no-ops. Simulates week 1 of 2026 with synthetic Sleeper data.

Covers:
  * Fix A  time-gate: a week isn't "complete" until Tuesday 08:00 UTC after its
    Monday Night game (so a mid-game build drops the in-progress week).
  * Fix C  season gate: the in-progress season isn't "complete".
  * Fix B  injury tracker: capture -> CSV -> load roundtrip (incl. bye via the
    fixed schedule and traded-player NFL team), and the shared overlay decision
    resolve_injury_flags() (the SAME function the build uses).

Run directly (`python tests/test_in_season_freshness.py`) or via pytest.
Also a useful harness for Phase 14 (weekly in-season digest).
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "lib", _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import lotg  # noqa: E402
from lotg_support import injury_tracker as it  # noqa: E402

UTC = timezone.utc


# --------------------------------------------------------------------------
# Fix A — trailing-week time gate
# --------------------------------------------------------------------------
def test_kickoff_thursday_2026():
    # Labor Day 2026 = Mon Sep 7 -> NFL kickoff Thursday Sep 10.
    assert lotg._nfl_kickoff_thursday(2026) == date(2026, 9, 10)


def test_week1_cutoff_is_tuesday_0800_utc():
    assert lotg._week_complete_cutoff(2026, 1) == datetime(2026, 9, 15, 8, 0, tzinfo=UTC)


def test_week_in_progress_not_complete():
    # Sunday games on, and Monday 11pm ET (Tue 03:00 UTC) — week 1 still live.
    assert not lotg._week_is_complete(2026, 1, datetime(2026, 9, 13, 20, 0, tzinfo=UTC))
    assert not lotg._week_is_complete(2026, 1, datetime(2026, 9, 15, 3, 0, tzinfo=UTC))


def test_week_complete_after_cutoff():
    assert lotg._week_is_complete(2026, 1, datetime(2026, 9, 15, 8, 0, tzinfo=UTC))


def test_completed_seasons_always_complete():
    now = datetime(2026, 6, 7, tzinfo=UTC)
    assert lotg._week_is_complete(2015, 9, now)  # ancient -> always done


# --------------------------------------------------------------------------
# Fix C — provisional-season gate
# --------------------------------------------------------------------------
def test_season_complete_gate():
    assert lotg._season_is_complete(2025, datetime(2026, 6, 7, tzinfo=UTC))
    assert not lotg._season_is_complete(2026, datetime(2026, 10, 1, tzinfo=UTC))


# --------------------------------------------------------------------------
# Fix B — injury tracker capture / load
# --------------------------------------------------------------------------
_PLAYERS = {
    "P_HEALTHY": {"full_name": "Healthy QB", "position": "QB", "team": "KC", "injury_status": "", "status": "Active"},
    "P_OUT":     {"full_name": "Out RB", "position": "RB", "team": "DAL", "injury_status": "Out", "status": "Inactive"},
    "P_SUS":     {"full_name": "Sus WR", "position": "WR", "team": "MIA", "injury_status": "Sus", "status": "Inactive"},
    "P_BYE":     {"full_name": "Bye WR", "position": "WR", "team": "BUF", "injury_status": "", "status": "Active"},
    "P_TRADED":  {"full_name": "Traded TE", "position": "TE", "team": "BUF", "injury_status": "", "status": "Active"},
    "P_Q":       {"full_name": "Quest RB", "position": "RB", "team": "SF", "injury_status": "Questionable", "status": "Active"},
}


class _MockSC:
    def players_nfl(self):
        return _PLAYERS

    def rosters(self):
        return [{"players": list(_PLAYERS.keys()), "taxi": [], "reserve": [], "starters": []}]

    def get(self, path):
        return {"season": "2026", "week": 1} if "state" in str(path) else None


def _capture_to_index(tmp: Path, monkeypatch_teams_playing=None):
    if monkeypatch_teams_playing is not None:
        it.teams_playing = monkeypatch_teams_playing
    sc = _MockSC()
    season, week = it.current_state(sc)
    rows = it.capture_rows(sc, season, week)
    (tmp / "data").mkdir(exist_ok=True)
    (tmp / "data" / "injury_tracker.csv").write_text(",".join(it.TRACKER_COLUMNS) + "\n")
    it.merge_into_csv(tmp, rows)
    it.merge_into_csv(tmp, rows)  # re-run same week must NOT duplicate
    return rows, it.load_status_index(tmp)


# BUF is on bye in week 1 of this synthetic season; everyone else plays.
_PLAYING = lambda season, week, timeout=30: {"KC", "DAL", "MIA", "SF", "PHI", "NYG"}


def test_capture_state_and_count():
    sc = _MockSC()
    assert it.current_state(sc) == (2026, 1)
    rows = it.capture_rows(sc, 2026, 1)
    assert len(rows) == len(_PLAYERS)


def test_capture_bye_and_traded_team():
    with tempfile.TemporaryDirectory() as d:
        rows, _ = _capture_to_index(Path(d), _PLAYING)
        by = {r["player_id"]: r for r in rows}
        assert by["P_BYE"]["on_bye"] == "true"
        # Traded player is logged on his CURRENT team (BUF) and gets BUF's bye.
        assert by["P_TRADED"]["nfl_team"] == "BUF" and by["P_TRADED"]["on_bye"] == "true"
        assert by["P_OUT"]["on_bye"] == "false" and by["P_OUT"]["injury_status"] == "Out"
        assert by["P_HEALTHY"]["on_bye"] == "false"


def test_merge_dedup_on_rerun():
    with tempfile.TemporaryDirectory() as d:
        _, idx = _capture_to_index(Path(d), _PLAYING)
        assert len(idx) == len(_PLAYERS)  # second merge replaced, not duplicated


# --------------------------------------------------------------------------
# Fix B — overlay decision (the real shared function the build calls)
# --------------------------------------------------------------------------
def test_overlay_resolution():
    with tempfile.TemporaryDirectory() as d:
        _, idx = _capture_to_index(Path(d), _PLAYING)

    def resolve(pid, pts):
        e = idx[(pid, 2026, 1)]
        return it.resolve_injury_flags(e["status"], e["bye"], pts)

    # (injury, suspension, bye) override, or None for "no override"
    assert resolve("P_HEALTHY", 20.0) is None              # played, healthy
    assert resolve("P_OUT", 0.0) == (True, False, False)    # missed, Out -> injury
    assert resolve("P_SUS", 0.0) == (False, True, False)    # missed, Sus -> suspension
    assert resolve("P_BYE", 0.0) == (False, False, True)    # bye wins
    assert resolve("P_TRADED", 0.0) == (False, False, True)  # bye via new team
    assert resolve("P_Q", 12.0) is None                     # questionable but played
    assert resolve("P_OUT", 8.0) is None                    # played through injury -> no override


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
