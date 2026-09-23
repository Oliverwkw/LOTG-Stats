"""nflverse re-scoring follows the league's own rules for that year.

`_league_score` turns an nflverse stat line into league points: for games the
league never rostered (the start/sit window, full-season points, pre-pickup PPG).
Checked against Sleeper's own stat lines for 2021-26 it matched 97.07% of rostered
player-weeks; 99.94% after these rules:

* 'fum' is EVERY fumble (nflverse's totals): a botched snap or a return fumble
  counts, and the sack/rush/receiving split missed them.
* fumble return yards count on an opponent's fumble only.
* nothing scores on defensive stats: Sleeper's int/sack/ff/fum_rec are
  team-defense keys, and this league scores no individual (idp_*) defense —
  so a receiver's recovered muff and a two-way player's cornerback snaps
  score nothing.
* 2020 (ESPN) scores by the ESPN league's own settings, where any fumble is -2;
  the years before the league use 2020's.

Run: PYTHONPATH=src:lib python tests/test_league_scoring.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("lotg", _ROOT / "src" / "lotg.py")
lotg = importlib.util.module_from_spec(_spec)
sys.modules["lotg"] = lotg          # dataclasses resolve types via sys.modules
_spec.loader.exec_module(lotg)
import espn_2020  # noqa: E402

# The league's 2021+ Sleeper table, the parts these checks touch.
_SLEEPER = {"pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0, "rush_yd": 0.1, "rec": 1.0,
            "rec_yd": 0.1, "fum": -1.0, "fum_lost": -1.0, "fum_rec": 2.0, "fum_ret_yd": 0.1, "def_td": 6.0, "safe": 2.0,
            "ff": 1.0, "sack": 1.0, "int": 2.0}


def _ok(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def check_fumbles_are_the_totals():
    # Andy Dalton 2024 week 5: 136 pass yds, 1 INT, 3 rush yds, two fumbles on
    # non-play snaps, both recovered by his own team. Sleeper: 1.74.
    line = {"passing_yards": 136, "passing_interceptions": 1, "rushing_yards": 3,
            "sack_fumbles": 0, "rushing_fumbles": 0, "fumbles_total": 2,
            "fumbles_lost_total": 0, "fumble_recovery_yards_own": 0}
    got = lotg._league_score(line, _SLEEPER, "QB")
    ok = _ok("a fumble off a snap is still a fumble (Dalton 2024 wk5 = Sleeper's 1.74)", got == 1.74, got)
    lost = lotg._league_score({"fumbles_total": 1, "fumbles_lost_total": 1}, _SLEEPER, "WR")
    ok &= _ok("a lost one is fum + fum_lost (-2)", lost == -2.0, lost)
    return ok


def check_own_recovery_is_not_a_return():
    own = lotg._league_score({"fumble_recovery_yards_own": 28}, _SLEEPER, "RB")
    opp = lotg._league_score({"fumble_recovery_yards_opp": 20}, _SLEEPER, "RB")
    ok = _ok("yards after recovering your own fumble score nothing", own == 0.0, own)
    ok &= _ok("an opponent's still does", opp == 2.0, opp)
    return ok


def check_offense_is_not_scored_on_defense():
    # Sleeper's int/sack/ff/fum_rec are TEAM-defense keys; a player's own
    # defensive stats would be idp_*, which this league does not score.
    line = {"def_fumbles_forced": 1, "fumble_recovery_opp": 1, "def_sacks": 1,
            "def_interceptions": 1, "def_tds": 1, "def_safeties": 1, "receptions": 3}
    wr = lotg._league_score(line, _SLEEPER, "WR")
    ok = _ok("a receiver's forced fumble / recovery / sack / INT score nothing", wr == 3.0, wr)
    # Travis Hunter: CB to nflverse, DB to Sleeper; his receptions score, his
    # cornerback snaps do not.
    two_way = lotg._league_score(line, _SLEEPER, "DB")
    ok &= _ok("nor does a two-way player's defense, whatever his label", two_way == 3.0, two_way)
    return ok


def check_2020_uses_the_espn_leagues_rules():
    raw = json.load(open(_ROOT / "data/espn_2020_raw/view_mSettings.json"))["settings"]
    sc = espn_2020.scoring_settings(raw)
    ok = _ok("PPR, 0.04 per passing yard, -2 per INT",
             (sc.get("rec"), sc.get("pass_yd"), sc.get("pass_int")) == (1.0, 0.04, -2.0),
             {k: sc.get(k) for k in ("rec", "pass_yd", "pass_int")})
    ok &= _ok("ANY fumble is -2 (ESPN stat 68), nothing extra for losing it",
              sc.get("fum") == -2.0 and not sc.get("fum_lost"), {k: sc.get(k) for k in ("fum", "fum_lost")})
    ok &= _ok("return TDs score 6", sc.get("st_td") == 6.0, sc.get("st_td"))
    # A synthetic running back's line with one fumble his team recovered.
    line = {"rushing_yards": 66, "rushing_tds": 1, "receptions": 4, "receiving_yards": 30,
            "fumbles_total": 1, "fumbles_lost_total": 0}
    got = lotg._league_score(line, sc, "RB")
    ok &= _ok("a fumble costs 2 whether or not it was lost", got == 6.6 + 6 + 4 + 3.0 - 2, got)
    league = espn_2020.emit_sleeper_2020(espn_2020.load_espn_2020(str(_ROOT / "data/espn_2020_raw")))
    ok &= _ok("and the synthetic 2020 league carries them", league["league"]["scoring_settings"] == sc
              if "league" in league else False, sorted(league)[:6])
    return ok


def run_all():
    ok = True
    for fn in (check_fumbles_are_the_totals, check_own_recovery_is_not_a_return,
               check_offense_is_not_scored_on_defense, check_2020_uses_the_espn_leagues_rules):
        print(f"\n{fn.__name__}:")
        ok &= fn()
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return ok


def test_league_scoring():
    assert run_all()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
