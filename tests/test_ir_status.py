"""Injured reserve in the forecast: the NFL minimum, the IR return curve, and the
research file's id key, expiry and "out through week".

Why these exist (2026-11-15):

  * the forecast had one return curve for every absence, so a player just put
    on IR was back 36% of the time a week later, when the NFL makes him miss 4
    games (3 in 2021). 0 of 35 in-season placements in 2026's injury tracker
    came back early; rewound 2021-25, the IR rule cuts the Brier score on IR
    players' remaining weeks from 0.230 to 0.192;
  * the research file was keyed by name ("Michael Penix" moved nobody) and its
    August rows applied all season (Kittle held to 70% with 8 of 9 games played).

Pure-logic tests need no data; the rest SKIP cleanly without exports/ or the
committed IR history (plan/notes/ir_spells.csv).

Run: python tests/test_ir_status.py
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import forecast as F  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402
from lotg_support import ir_status as IR  # noqa: E402

_HAVE_DATA = ((_ROOT / "exports" / "team_week.csv").exists()
              and (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists())
_HAVE_HISTORY = IR.history_path(_ROOT).exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _flat_injury_model() -> F.InjuryModel:
    return F.InjuryModel(recovery=(0.5,) * 8, tail=0.5, mean_duration=3.0, spells=1, seasons=())


def _ir_model() -> IR.IRReturnModel:
    return IR.IRReturnModel(recovery=(0.5, 0.5), tail=0.5, runs=1, returned=1, seasons=())


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------
def test_the_minimum_is_three_games_in_2021_and_four_after():
    assert IR.ir_min_games(2020) == 3 and IR.ir_min_games(2021) == 3
    assert IR.ir_min_games(2022) == 4 and IR.ir_min_games(2026) == 4


def test_an_ir_player_cannot_play_before_the_minimum():
    """One game already missed on IR in 2026: three more out in every draw, then
    the IR curve (not the general one) brings him back."""
    paths = F._injury_paths(np.random.default_rng(1), 2000, 6, np.array([0.9, 0.9]),
                            np.zeros(2, dtype=bool), np.array([1, 1]), _flat_injury_model(),
                            ir_games=np.array([1, -1]), ir_model=_ir_model(), year=2026)
    ir_player, plain = paths[:, :, 0], paths[:, :, 1]
    assert not ir_player[:, :3].any(), "back before the 4-game minimum"
    assert abs(ir_player[:, 3].mean() - 0.5) < 0.04, ir_player[:, 3].mean()
    assert plain[:, 0].mean() > 0.4, "a player not on IR returns on the general curve"


def test_a_lock_and_a_one_week_tag_do_what_they_say():
    paths = F._injury_paths(np.random.default_rng(2), 2000, 4, np.array([1.0, 1.0, 1.0]),
                            np.array([True, False, False]), np.array([-1, -1, -1]),
                            _flat_injury_model(), lock=np.array([2, 0, 0]),
                            first_week_p=np.array([1.0, 0.0, 0.85]))
    assert not paths[:, :2, 0].any() and paths[:, 2:, 0].all(), "flat player locked 2 weeks"
    assert not paths[:, 0, 1].any() and paths[:, 1, 1].mean() > 0.95, "Doubtful = one week out"
    assert abs(paths[:, 0, 2].mean() - 0.85) < 0.03


def test_the_old_call_is_unchanged():
    """Without the new arguments the paths are exactly what they were."""
    args = (np.random.default_rng(3), 300, 5, np.array([0.8, 0.9]), np.zeros(2, dtype=bool),
            np.array([2, -1]), _flat_injury_model())
    a = F._injury_paths(*args)
    b = F._injury_paths(np.random.default_rng(3), *args[1:], ir_games=np.array([-1, -1]),
                        ir_model=_ir_model(), year=2026)
    assert np.array_equal(a, b)


def test_a_research_note_expires():
    n = F.ResearchNote("X", 0.7, 1.0, "why", "http://x", "2026-08-07")
    assert n.applies(0) and not n.applies(1), "a preseason note stops once a week is known"
    out = dataclasses.replace(n, availability=None, out_through_week=17)
    assert out.applies(9) and out.applies(17) and not out.applies(18)
    assert dataclasses.replace(n, valid_through_week=6).applies(6)


def test_runs_are_read_from_weekly_rosters():
    """A bye inside an IR run does not end it; the next active row is the return."""
    import pandas as pd
    rows = []
    for wk, abbr, st in [(3, "A01", "ACT"), (4, "R01", "RES"), (5, "R01", "RES"), (7, "R01", "RES"),
                         (8, "R01", "RES"), (9, "A01", "ACT")]:
        rows.append({"season": 2023, "game_type": "REG", "position": "WR", "gsis_id": "g1",
                     "sleeper_id": "77", "full_name": "A B", "team": "T", "week": wk,
                     "status_description_abbr": abbr, "status": st})
    r = IR._runs_from_rosters(pd.DataFrame(rows))
    assert len(r) == 1
    run = r.iloc[0]
    assert (run.start_week, run.games_on_ir, run.outcome, run.return_week) == (4, 4, "returned", 9)


# ---------------------------------------------------------------------------
# Against the league's data
# ---------------------------------------------------------------------------
def test_the_history_obeys_the_minimum():
    if not _HAVE_HISTORY:
        return _skip("no plan/notes/ir_spells.csv")
    assert not IR.check_history(), IR.check_history()


def test_the_ir_curve_is_fitted_and_leaves_the_season_out():
    if not (_HAVE_HISTORY and _HAVE_DATA):
        return _skip("no IR history / exports")
    m = IR.ir_return_model(tracker=False)
    assert m.runs > 150 and m.returned > 50, (m.runs, m.returned)
    assert 0.1 < m.recovery[0] < 0.4, m.recovery
    assert m.recovery[0] > m.tail, "returns get rarer the longer he stays on IR"
    assert 2024 not in IR.ir_return_model(exclude_from_fits=2024, tracker=False).seasons
    curve = m.return_curve(0, 8, 2025)
    assert np.all(curve[:4] == 0) and curve[4] > 0


def test_the_ir_rule_predicts_ir_players_better():
    """Rewind the last completed season to weeks 4 and 8: the IR players' predicted
    availability must sit closer to what happened, with a better Brier score."""
    if not (_HAVE_HISTORY and _HAVE_DATA):
        return _skip("no IR history / exports")
    year = max(y for y in Q.completed_seasons() if y <= 2025)
    model = F.injury_model(exclude_from_fits=year)
    irm = IR.ir_return_model(exclude_from_fits=year)
    avail, base = F.availability_rates(year)
    pw = F._player_week()
    last = Q.season_meta(year).last_week
    old_b, new_b, real_all, old_all, new_all = [], [], [], [], []
    for k in (4, 8):
        missed, on_ir = F.weeks_missed(year, k), IR.on_ir(year, k)
        rows = pw[(pw["Year"] == year) & ~pw["Bye?"] & (pw["Week"] <= last)]
        p, start, irg, actual, weeks = [], [], [], [], []
        for (name, pid), g in rows.groupby(["Player", "Player ID"]):
            pid = str(pid).split(".")[0]
            fut = g[g["Week"] > k]
            if pid not in on_ir or fut.empty or not (g["Week"] <= k).any():
                continue
            p.append(avail.get(name, base.get(g["Position"].iloc[0], 0.83)))
            start.append(max(missed.get(name, 0), 0))
            irg.append(on_ir[pid][1])
            actual.append((~fut["Hurt"].to_numpy(bool)).astype(float))
            weeks.append(fut["Week"].to_numpy(int) - k - 1)
        assert p, f"nobody on IR at week {k} of {year}"
        args = (last - k, np.array(p), np.zeros(len(p), dtype=bool), np.array(start), model)
        old = F._injury_paths(np.random.default_rng(7), 600, *args).mean(axis=0)
        new = F._injury_paths(np.random.default_rng(7), 600, *args, ir_games=np.array(irg),
                              ir_model=irm, year=year).mean(axis=0)
        for i in range(len(p)):
            real = actual[i]
            o, n = old[weeks[i], i], new[weeks[i], i]
            old_b.extend((o - real) ** 2)
            new_b.extend((n - real) ** 2)
            real_all.extend(real)
            old_all.extend(o)
            new_all.extend(n)
    assert np.mean(new_b) < np.mean(old_b), (np.mean(new_b), np.mean(old_b))
    assert abs(np.mean(new_all) - np.mean(real_all)) < abs(np.mean(old_all) - np.mean(real_all))
    print(f"  {year}: IR players available {np.mean(real_all):.3f}; predicted "
          f"{np.mean(old_all):.3f} -> {np.mean(new_all):.3f}, Brier "
          f"{np.mean(old_b):.3f} -> {np.mean(new_b):.3f} (n={len(real_all)})")


def test_the_research_file_is_keyed_by_id():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    live = [y for y in Q.snapshot_seasons() if not Q.season_meta(y).is_complete]
    if not live or not F.research_path(max(live)).exists():
        return _skip("no live season with a research file")
    year = max(live)
    notes = F.research_overrides(year)
    players = Q.players()
    for pid, note in notes.items():
        assert note.player_id == pid, f"{note.player}: write the id into the file"
        assert Q._normalize(note.player) in Q._normalize(players.name(pid)), (note.player, pid)
    assert not F.check_research_file(year), F.check_research_file(year)


def test_a_live_forecast_reports_who_it_holds_out():
    if not _HAVE_DATA:
        return _skip("no exports/snapshot")
    live = [y for y in Q.snapshot_seasons() if not Q.season_meta(y).is_complete]
    if not live or not Q.played_weeks(max(live)):
        return _skip("no live season under way")
    year = max(live)
    fc = F.forecast(year, sims=300, availability=dataclasses.replace(F.AvailabilityModel(), draws=150))
    assert fc.player_availability and fc.availability_from_week == max(fc.played_weeks) + 1
    for pid, (placed, missed) in IR.on_ir(year, max(fc.played_weeks)).items():
        v = fc.player_availability.get(pid)
        if v is None:
            continue                          # not on a roster, or on a taxi squad
        early = max(IR.ir_min_games(year) - missed, 0)
        assert all(x == 0 for x in v[:early]), (pid, placed, missed, v[:early])


def test_the_build_does_not_import_ir_status():
    hits = []
    for folder in ("src", ".github/workflows"):
        for path in (_ROOT / folder).rglob("*"):
            if path.is_file() and "ir_status" in path.read_text(errors="ignore"):
                hits.append(str(path.relative_to(_ROOT)))
    assert not hits, hits


TESTS = [
    test_the_minimum_is_three_games_in_2021_and_four_after,
    test_an_ir_player_cannot_play_before_the_minimum,
    test_a_lock_and_a_one_week_tag_do_what_they_say,
    test_the_old_call_is_unchanged,
    test_a_research_note_expires,
    test_runs_are_read_from_weekly_rosters,
    test_the_history_obeys_the_minimum,
    test_the_ir_curve_is_fitted_and_leaves_the_season_out,
    test_the_ir_rule_predicts_ir_players_better,
    test_the_research_file_is_keyed_by_id,
    test_a_live_forecast_reports_who_it_holds_out,
    test_the_build_does_not_import_ir_status,
]


if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall IR checks passed")
