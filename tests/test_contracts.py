"""Contract layer: scoring reconciliation, signing selection, matching.

The load-bearing guard ties this module to a number the build published
independently: the league points it re-scores from nflverse weekly stats must
reproduce `player_year["Points (full season)"]`. That one needs the committed
`.cache/` and `exports/`, and skips cleanly without them.

The rest pin behaviour a wrong answer would rest on, using synthetic fixtures so
they run with no data and no network at all: a rookie deal is not a signing,
"big" is ranked inside a position-year, a season a player never played is a real
zero for points but not for a rate, a control outside the caliper is dropped
rather than stretched to fit, and the reported p-value is deterministic.

Run: python tests/test_contracts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import contracts as C  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "player_year.csv").exists()
_HAVE_STATS = bool(list((_ROOT / ".cache").glob("nflverse_stats_player_week_*.csv")))


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


# ---------------------------------------------------------------------------
# Fixtures: a tiny league of made-up players, so the logic tests need no data
# ---------------------------------------------------------------------------
def _panel() -> pd.DataFrame:
    """Four positions, three seasons, ten players a position-season."""
    rows = []
    for season in (2019, 2020, 2021):
        for position in C.POSITIONS:
            for i in range(10):
                rows.append({"player_id": f"{position}{i}", "season": season,
                             "player": f"{position} {i}", "position": position,
                             "games": 16, "points": 300.0 - 20.0 * i,
                             "ppg": (300.0 - 20.0 * i) / 16})
    panel = pd.DataFrame(rows)
    panel["pos_rank"] = panel.groupby(["season", "position"])["points"].rank(
        ascending=False, method="min")
    panel["startable"] = [float(r <= C.STARTABLE_CUTOFF[p])
                          for r, p in zip(panel["pos_rank"], panel["position"])]
    return panel


def _contracts() -> pd.DataFrame:
    """Three WR deals in 2020, one of them a rookie contract."""
    return pd.DataFrame([
        {"player": "WR 1", "gsis_id": "WR1", "position": "WR", "team": "A",
         "year_signed": 2020, "years": 4.0, "apy": 20.0, "apy_cap_pct": 0.10,
         "guaranteed": 40.0, "draft_year": 2016.0},
        {"player": "WR 2", "gsis_id": "WR2", "position": "WR", "team": "B",
         "year_signed": 2020, "years": 3.0, "apy": 15.0, "apy_cap_pct": 0.08,
         "guaranteed": 20.0, "draft_year": 2015.0},
        {"player": "WR 3", "gsis_id": "WR3", "position": "WR", "team": "C",
         "year_signed": 2020, "years": 4.0, "apy": 30.0, "apy_cap_pct": 0.15,
         "guaranteed": 60.0, "draft_year": 2020.0},   # rookie deal — not a signing
    ])


# ---------------------------------------------------------------------------
# Scoring: the guard that ties this module to the build
# ---------------------------------------------------------------------------
def test_scoring_reconciles_with_the_build():
    if not (_HAVE_EXPORTS and _HAVE_STATS):
        return _skip("needs committed exports/ and .cache/ nflverse stats")
    seasons = [y for y in Q.completed_seasons() if y >= 2020
               and (_ROOT / ".cache" / f"nflverse_stats_player_week_{y}.csv").exists()]
    if not seasons:
        return _skip("no completed season has cached weekly stats")
    problems = C.check_scoring_reconciles(seasons=seasons)
    assert not problems, problems
    print(f"  re-scored points reproduce the build's own totals for {seasons}")


def test_lotg_points_charge_the_fumbles_a_player_got_back():
    """League scoring is PPR minus fumbles recovered by the player's own team."""
    weekly = pd.DataFrame([
        {"fantasy_points_ppr": 20.0, "rushing_fumbles": 2.0, "rushing_fumbles_lost": 1.0},
        {"fantasy_points_ppr": 12.5, "rushing_fumbles": 0.0, "rushing_fumbles_lost": 0.0},
    ])
    got = C.lotg_points(weekly).tolist()
    assert got == [19.0, 12.5], got
    print("  one unlost fumble costs exactly 1 point; a clean week is untouched")


# ---------------------------------------------------------------------------
# Signings
# ---------------------------------------------------------------------------
def test_rookie_deals_are_not_signings():
    vets = C.signings(first_year=2019, last_year=2021, contracts=_contracts())
    assert set(vets["player"]) == {"WR 1", "WR 2"}, sorted(vets["player"])
    withrookies = C.signings(first_year=2019, last_year=2021, veterans_only=False,
                             contracts=_contracts())
    assert len(withrookies) == 3
    print("  a deal signed in the player's draft year is slotted, not a signing")


def test_big_is_ranked_within_position_and_year():
    vets = C.signings(first_year=2019, last_year=2021, contracts=_contracts())
    ranks = dict(zip(vets["player"], vets["rank_in_position_year"]))
    assert ranks == {"WR 1": 1.0, "WR 2": 2.0}, ranks
    print("  rank runs on apy_cap_pct inside the position-year, not on raw dollars")


# ---------------------------------------------------------------------------
# The before/after window
# ---------------------------------------------------------------------------
def test_a_season_never_played_is_zero_points_but_no_rate():
    panel = _panel()
    rows = pd.DataFrame([{"gsis_id": "WR0", "position": "WR", "year": 2021}])
    window = C.event_frame(rows, panel, "gsis_id", "year").iloc[0]
    assert window["y0_points"] == 300.0                 # 2021 exists
    assert window["y1_points"] == 0.0                   # 2022 does not
    assert window["y1_games"] == 0.0
    assert pd.isna(window["y1_ppg"])                    # no rate from no game
    assert window["two_year_points"] == 300.0
    print("  a missing season scores 0 for a roster and contributes no ppg")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _study_on_fixture(panel: pd.DataFrame = None, contracts: pd.DataFrame = None,
                      **kwargs) -> C.ContractStudy:
    """The fixture's players sit 20 points apart, so it runs a wider caliper."""
    panel = _panel() if panel is None else panel
    signings = C.signings(first_year=2020, last_year=2020,
                          contracts=_contracts() if contracts is None else contracts)
    kwargs.setdefault("caliper_sd", 0.5)
    return C.study(first_year=2020, last_year=2020, panel=panel,
                   all_signings=signings, age_caliper=None,
                   permutations=200, **kwargs)


def test_controls_come_from_the_same_position_and_season():
    result = _study_on_fixture()
    assert len(result.matched) == 2, result.matched
    assert set(result.matched["position"]) == {"WR"}
    assert (result.matched["n_controls"] > 0).all()
    print("  every signer matched inside his own position-season")


def test_a_signer_with_nobody_close_is_dropped_not_stretched():
    """The caliper is a bar, not a preference: unmatched is reported, not filled."""
    panel = _panel()
    # A signer 400 points clear of everyone in his position-season.
    lonely = panel[(panel["player_id"] == "WR0")].copy()
    lonely["points"] = 900.0
    lonely["ppg"] = 900.0 / 16
    panel = pd.concat([panel[panel["player_id"] != "WR0"], lonely], ignore_index=True)
    contracts = _contracts().assign(gsis_id=["WR0", "WR2", "WR3"],
                                    player=["WR 0", "WR 2", "WR 3"])
    result = _study_on_fixture(panel=panel, contracts=contracts)
    assert "WR 0" not in set(result.matched["player"]), result.matched["player"].tolist()
    assert "WR 2" in set(result.matched["player"])      # the ordinary signer still matches
    assert "WR 0" in set(result.unmatched["player"])
    assert any("unmatched" in w for w in result.warnings), result.warnings
    print("  the outlier signer is dropped and surfaced, never matched to whoever "
          "happened to be nearest")


def test_control_pool_excludes_the_other_notable_signings():
    panel = _panel()
    signings = C.signings(first_year=2020, last_year=2020, contracts=_contracts())
    pool = C.control_pool(panel, signings, exclude_top_n=2, min_baseline_games=1)
    entering_2020 = pool[pool["year"] == 2020]
    assert "WR1" not in set(entering_2020["gsis_id"])
    assert "WR2" not in set(entering_2020["gsis_id"])
    assert "WR4" in set(entering_2020["gsis_id"])
    print("  a player who signed his own notable deal cannot stand in as untouched")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def test_summary_reports_fdr_q_values_over_the_whole_family():
    result = _study_on_fixture()
    summary = result.summary
    assert "q" in summary.columns
    assert (summary["q"] >= summary["p"] - 1e-9).all(), summary
    print(f"  {len(summary)} tests reported with a q-value, never a bare p")


def test_the_permutation_p_is_deterministic_and_two_sided():
    gaps = [3.0, 5.0, -1.0, 4.0, 2.0, 6.0, -2.0, 3.5]
    first = C._sign_permutation_p(gaps, permutations=2000, seed=0)
    again = C._sign_permutation_p(gaps, permutations=2000, seed=0)
    mirrored = C._sign_permutation_p([-g for g in gaps], permutations=2000, seed=0)
    assert first == again == mirrored, (first, again, mirrored)
    assert 0.0 < first < 1.0
    print(f"  paired sign-flip test is reproducible (p={first:.4f}) and symmetric")


# ---------------------------------------------------------------------------
# Guards that need the downloaded contracts file
# ---------------------------------------------------------------------------
def test_big_signings_join_to_real_seasons():
    if not (_HAVE_EXPORTS and C.have_contracts()):
        return _skip("needs the cached nflverse contracts file")
    problems = C.check_contract_join()
    assert not problems, problems
    print("  the top-5 signings all join to a player-season")


def test_matched_cohorts_start_level():
    if not (_HAVE_EXPORTS and C.have_contracts()):
        return _skip("needs the cached nflverse contracts file")
    problems = C.check_controls_are_balanced()
    assert not problems, problems
    print("  signers and their controls enter the season within 5 points of each other")


def test_the_contracts_file_is_the_maintained_one():
    if not C.have_contracts():
        return _skip("needs the cached nflverse contracts file")
    newest = int(C.load_contracts()["year_signed"].max())
    assert newest >= C.MIN_EXPECTED_YEAR, newest
    print(f"  contracts run through {newest} (the csv asset stops at 2022)")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    print("\nOK")
