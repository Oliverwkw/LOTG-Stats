"""Sleeper's live player status must not rewrite completed seasons.

`pid_meta` comes from Sleeper's /players/nfl feed — the player's status TODAY,
with no per-week history. The player_week loop uses it as a fallback: scored 0,
not on bye, and Sleeper says OUT / IR / PUP / INACTIVE / DOUBTFUL -> the week was
missed. That is reasonable for the in-progress season and wrong for every other
one, because it makes history a function of the calendar day the build ran.

It is also what the 2026-07-29 dataset-health email was reporting. Reproduced by
building twice off the committed caches with a single input changed — Jaylin
Noel's live injury_status, None -> "Out" (one of a batch of late-July
training-camp PUP designations):

    player_year   2 rows   (Noel, plus Cooper Kupp via a league-relative
                            percentile that tipped when Noel's numbers moved)
    team_year     1 row    plehv79
    league_year   1 row    2025
    player_week  17 rows   Noel, every week of 2025 — the terminal streak
                           encoding skips non-played weeks, so flipping four of
                           them re-encodes every run boundary in his season
    team_week     6 rows   plehv79 weeks 2/13/15/16 (donut, under-10 and injury
                           counts) plus weeks 1 and 3, where the Most-injured
                           streak run spanning 1-3 re-encoded
    league_week   4 rows   2025 weeks 2, 13, 15, 16
    trades        1 row    the plehv79 <-> LWebs53 deal that received Noel

— an exact match for the seven sheets and every row in that email.

Run: PYTHONPATH=src:lib python tests/test_live_status_scope.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "lib"))

from lotg import live_status_applies  # noqa: E402


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond or not detail else f" — {detail}"))
    return bool(cond)


def check_completed_seasons_are_frozen():
    ok = True
    for season in (2020, 2021, 2022, 2023, 2024, 2025):
        ok &= _ok(f"{season} ignores live status while 2026 is in progress",
                  live_status_applies(season, 2026) is False)
    return ok


def check_in_progress_season_still_uses_it():
    ok = _ok("the in-progress season uses live status", live_status_applies(2026, 2026))
    ok &= _ok("a future season does too", live_status_applies(2027, 2026))
    return ok


def check_unknown_current_season_keeps_old_behaviour():
    """No league chain -> we can't tell which season is live. Falling back to
    'apply it' keeps the pre-fix behaviour rather than silently dropping every
    injury flag."""
    ok = _ok("None current season -> applies", live_status_applies(2022, None))
    ok &= _ok("unparseable season -> applies", live_status_applies("n/a", 2026))
    ok &= _ok("unparseable current -> applies", live_status_applies(2022, "n/a"))
    return ok


def check_the_call_site_is_gated():
    """Keep the guard wired to the one place it matters. The fallback reads
    pid_meta['status'] / ['injury_status'], and those lookups must sit behind
    live_status_applies()."""
    src = (_ROOT / "src" / "lotg.py").read_text()
    ok = _ok("player_week loop calls the gate",
             "live_status_applies(season, _current_lotg_season)" in src)
    # The injury-signal tokens should appear exactly once — inside the gated
    # fallback. A second, ungated copy would reopen the hole.
    ok &= _ok("injury-signal list appears once",
              src.count('"pup", "doubtful"') == 1,
              f"count={src.count(chr(34) + 'pup' + chr(34) + ', ' + chr(34) + 'doubtful' + chr(34))}")
    gate = src.index("live_status_applies(season, _current_lotg_season)")
    tokens = src.index('"pup", "doubtful"')
    ok &= _ok("the gate is evaluated before the live-status lookup", gate < tokens)
    return ok


def run_all() -> bool:
    all_ok = True
    for t in (check_completed_seasons_are_frozen,
              check_in_progress_season_still_uses_it,
              check_unknown_current_season_keeps_old_behaviour,
              check_the_call_site_is_gated):
        print(f"\n{t.__name__}:")
        all_ok &= bool(t())
    print("\n" + ("ALL PASS" if all_ok else "SOME FAILED"))
    return all_ok


def test_live_status_scope():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
