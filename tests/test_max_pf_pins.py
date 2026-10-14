"""Max PF position pins: the build's ceiling agrees with Sleeper's own.

Sleeper keeps a season max-points total per roster (`rosters[].settings.ppts`),
computed week by week with the position each player carried THAT week. The
build computes `team_week."Max PF"` with one position per player, Sleeper's
current label, so a player Sleeper has since relabelled moves the ceiling.
`position_pins.MAX_PF_POSITION_PINS` records the relabels that mattered
(Taysom Hill, Cordarrelle Patterson); with them, the regular-season Max PF of
every completed team-season matches `ppts` to the cent except one, whose gap is
a stat correction rather than a position (see KNOWN_GAPS).

The data test asserts against the snapshot only — Sleeper's numbers and the
build's own routine — so it holds before and after CI regenerates exports/.
`test_replay.test_ceiling_model_reproduces_the_built_max_pf` and
`test_draft_capital` tie the same routine to the shipped column.

Run: python tests/test_max_pf_pins.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import inquiry as Q  # noqa: E402
from lotg_support.lineup import compute_optimal_lineup  # noqa: E402
from lotg_support.position_pins import max_pf_position  # noqa: E402

_HAVE_DATA = (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists()

HILL, PATTERSON = "4381", "1535"

# Team-seasons whose regular-season Max PF is NOT expected to match Sleeper's
# `ppts`, with the exact gap (build minus Sleeper). stevenb123 2024: Sleeper's
# `fpts` for the team and the opponent's `fpts_against` are off by the same
# 1.00 — a stat correction to a starter (week 6 or 13, the two meetings with
# Shmuel256) that landed after Sleeper froze its season totals. Not a position,
# so no pin can or should close it.
KNOWN_GAPS = {(2024, "stevenb123"): 1.00}


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_pin_lookup_week_beats_season_and_misses_elsewhere():
    assert max_pf_position(HILL, 2021, 5) == "QB"            # season-wide
    assert max_pf_position(HILL, 2023, 9) == "QB"            # one week
    assert max_pf_position(HILL, 2023, 8) is None            # the week beside it
    assert max_pf_position(HILL, 2022, 9) is None            # another season
    assert max_pf_position(PATTERSON, "2021", "3") == "WR"   # string inputs
    assert max_pf_position("no-such-player", 2021, 1) is None
    assert max_pf_position(HILL, 2021, None) is None         # no week, no pin


def test_pin_applies_only_when_a_week_is_passed():
    # As a TE Hill takes the TE slot and the real TE drops to FLEX; as a QB he
    # takes the superflex instead and the backup QB sits.
    pts = {HILL: 20.0, "qb": 30.0, "qb2": 10.0, "te": 5.0}
    pos = {HILL: "TE", "qb": "QB", "qb2": "QB", "te": "TE"}
    as_te = compute_optimal_lineup(pts, pos, 2021)
    as_qb = compute_optimal_lineup(pts, pos, 2021, week=13)
    assert as_te == 30.0 + 20.0 + 5.0 + 10.0    # QB, TE=Hill, FLEX=te, SF=qb2
    assert as_qb == 30.0 + 5.0 + 20.0           # QB, TE=te, SF=Hill; qb2 benched
    # Unpinned weeks and seasons keep the current label.
    assert compute_optimal_lineup(pts, pos, 2022, week=13) == as_te


# ---------------------------------------------------------------------------
# Against the committed snapshot
# ---------------------------------------------------------------------------
def test_regular_season_max_pf_matches_sleeper_ppts():
    if not _HAVE_DATA:
        return _skip("no committed snapshot")
    positions = Q.players().positions()
    problems, checked = [], 0
    for season in Q.completed_seasons():
        meta = Q.season_meta(season)
        rosters_path = Q.snapshot_dir() / f"season_{season}" / "rosters.json"
        if not meta.has_snapshot or not rosters_path.exists():
            continue
        teams = Q.teams(season)
        built = {}
        for wk in Q.played_weeks(season):
            if wk >= meta.playoff_week_start:
                continue
            for rid, row in Q.week(season, wk).items():
                built[rid] = built.get(rid, 0.0) + compute_optimal_lineup(
                    {p: row.players_points.get(p, 0.0) for p in row.players},
                    positions, season, week=wk)
        for r in json.loads(rosters_path.read_text()):
            s = r.get("settings") or {}
            sleeper = float(s.get("ppts", 0)) + float(s.get("ppts_decimal", 0)) / 100
            rid = int(r["roster_id"])
            gap = round(built.get(rid, 0.0) - sleeper, 2)
            want = KNOWN_GAPS.get((season, teams.get(rid, "")), 0.0)
            checked += 1
            if abs(gap - want) > 0.005:
                problems.append(f"{season} {teams.get(rid, rid)}: build - Sleeper = {gap:+.2f}"
                                f" (expected {want:+.2f})")
    if not checked:
        return _skip("no completed season with a snapshot")
    assert not problems, problems


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  [FAIL] {name} — {exc}")
    sys.exit(1 if fails else 0)
