"""Trade checks: `lotg_support.trade` wraps the forecast without changing it.

- With no trade and no overrides, the patched forecast is the plain forecast
  (same seed, same calibration, same odds to the decimal).
- The swap touches only the roster week: the seasons the model calibrates on
  keep their real rosters.
- A swap moves exactly the named players, both ways.

Run: python tests/test_trade.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import forecast as F, inquiry as Q, trade as T  # noqa: E402

_HAVE = (_ROOT / "exports" / "player_week.csv").exists() and \
    (_ROOT / "exports" / "snapshot" / "sleeper_players_nfl.json").exists()


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _sample_trade():
    """Two real players on two different rosters of the newest season."""
    year = max(Q.export_seasons())
    week = F.roster_week(year)
    rosters = T._rosters(year, week)
    (a, pa), (b, pb) = list(rosters.items())[:2]
    players = Q.players()
    return T.resolve(a, [players.name(pa[0])], [players.name(pb[0])], year)


def test_no_trade_is_the_plain_forecast():
    if not _HAVE and _skip("no exports/snapshot"):
        return
    tr = _sample_trade()
    calib = T._calibration()
    plain = F.forecast(tr.year, sims=400, calibration=calib, seed=7)
    with T._patched(T.Trade(tr.year, tr.week, tr.team, tr.partner, {}, {}), {}, ()):
        wrapped = F.forecast(tr.year, sims=400, calibration=calib, seed=7)
    assert [(o.team, o.champion, round(o.projection, 6)) for o in plain.odds] == \
        [(o.team, o.champion, round(o.projection, 6)) for o in wrapped.odds]


def test_swap_touches_only_the_roster_week():
    if not _HAVE and _skip("no exports/snapshot"):
        return
    tr = _sample_trade()
    rid = {v: k for k, v in Q.teams(tr.year).items()}
    before_past = F.startable_pool(tr.year - 1, 1)
    with T._patched(tr, {}, ()):
        assert F.startable_pool(tr.year - 1, 1) == before_past
        now = F.startable_pool(tr.year, tr.week)
    a, b = now[rid[tr.team]], now[rid[tr.partner]]
    assert set(tr.get) <= set(a) and not set(tr.give) & set(a)
    assert set(tr.give) <= set(b) and not set(tr.get) & set(b)
    # restored afterwards
    assert set(tr.give) <= set(F.startable_pool(tr.year, tr.week)[rid[tr.team]])


def test_resolve_refuses_the_wrong_side():
    if not _HAVE and _skip("no exports/snapshot"):
        return
    tr = _sample_trade()
    try:
        T.resolve(tr.team, list(tr.get.values()), list(tr.give.values()), tr.year)
    except LookupError:
        return
    raise AssertionError("resolve accepted players from the wrong roster")


def test_depth_rate_matches_player_table():
    """The depth tables and the players table show the same forecast rate
    (the in-season blend once the forecast blends), so the caveats agree."""
    if not _HAVE and _skip("no exports/snapshot"):
        return
    tr = _sample_trade()
    table = T.player_table(tr, None).set_index("Player")["fcst rate"]
    for team in (tr.team, tr.partner):
        d = T.depth(tr, team, True, top=50)
        d = d[d["Player"].str.endswith(" *")]
        for _, r in d.iterrows():
            name = r["Player"][:-2]
            assert name in table.index, name
            a, b = r["fcst"], table[name]
            assert (a != a and b != b) or abs(a - b) < 1e-9, (name, a, b)


TESTS = [test_no_trade_is_the_plain_forecast, test_swap_touches_only_the_roster_week,
         test_resolve_refuses_the_wrong_side, test_depth_rate_matches_player_table]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall trade checks passed")
