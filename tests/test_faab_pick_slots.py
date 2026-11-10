"""A traded pick's slot as knowable on the trade date (lotg_support.faab_pick_slots, Oliver 2026-11-10).

Static tests use a synthetic league; the data tests read the committed exports and skip when they are absent.
Run directly (`python tests/test_faab_pick_slots.py`) or via pytest.
"""
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import faab_pick_slots as PS  # noqa: E402

TEAMS = [f"T{i}" for i in range(1, 9)]
SLOTS = {f"1.{s:02d}": 2000.0 - 150 * (s - 1) for s in range(1, 9)}        # 1.01 $2,000 ... 1.08 $950
RAVG = {1: sum(SLOTS.values()) / 8}


def _league(weeks=15, season=2025):
    """T1 loses every game, T8 wins every game, the rest in between; one regular season + semis + final"""
    rows = []
    for w in range(1, weeks + 1):
        for i, t in enumerate(TEAMS):
            rows.append((t, season, w, f"Week {w}", i >= 4 if w % 2 else i >= 3, 100.0 + 10 * i, 120.0 + 10 * i))
    for i, t in enumerate(TEAMS[4:]):
        rows.append((t, season, 16, "Semifinal", i >= 2, 150.0, 160.0))
    rows.append(("T8", season, 17, "Final", True, 150.0, 160.0))
    tw = pd.DataFrame(rows, columns=["Team", "Year", "Week", "Week Name", "Win?", "PF", "Max PF"])
    rp = pd.DataFrame([(season + 1, f"1.{i + 1:02d}", t) for i, t in enumerate(TEAMS)], columns=["Year", "Number", "Original Team"])
    # roster strength says the opposite of the results (T1 strongest), so the fade from roster to record shows
    pa = pd.DataFrame([(t, "2025-01-01", None, f"p{i}") for i, t in enumerate(TEAMS)], columns=["Team", "Date", "Date dropped/traded", "sid"])
    val = {f"p{i}": 1000.0 - 100 * i for i in range(8)}
    return PS.SlotOdds(tw=tw, rp=rp, pa=pa, value=lambda sid, d: val.get(sid))


def test_state_by_date():
    S = _league()
    assert S.state(2027, "2025-10-01")[0] == "far"           # deciding season 2026 not next up in 2025
    assert S.state(2026, "2025-08-01") == ("pre", 0)          # kickoff 2025-09-04
    assert S.state(2026, "2025-09-09") == ("season", 1)       # week 1 ends Monday 2025-09-08
    assert S.state(2026, "2025-12-17")[0] == "post"           # week 15 done, final not played
    assert S.state(2026, "2025-12-30")[0] == "set"            # week 17 ends 2025-12-29


def test_label_original_team():
    S = _league()
    assert S.original_team("2026 1.03(A. Player)") == "T3"
    assert S.original_team("2027 2(T5)") == "T5"
    assert S.original_team("2027 2") is None


def test_price_fades_from_roster_to_record():
    S = _league()
    pre = S.price("2026 1.01(X)", "2025-08-01", SLOTS, RAVG)          # T1: strongest roster -> projected late pick
    late = S.price("2026 1.01(X)", "2025-11-25", SLOTS, RAVG)         # T1: worst record by week 12 -> early pick
    assert pre < RAVG[1] < late, (pre, RAVG[1], late)
    assert abs(pre - RAVG[1]) < abs(late - RAVG[1])                   # preseason odds are wide (sigma 2.75)
    assert S.price("2026 1.01(X)", "2025-12-30", SLOTS, RAVG) is None  # order set: the caller's exact slot
    assert S.price("2027 1(T1)", "2025-10-01", SLOTS, RAVG) is None    # two drafts out: round average


def test_post_season_brackets():
    S = _league()
    o = S.odds(2026, "2025-12-24")                                    # semifinals played (week 16 ends 12-22)
    assert all(abs(sum(p) - 1) < 1e-9 for p in o.values())
    assert sum(o["T8"][6:]) > 0.999 and sum(o["T5"][4:6]) > 0.999     # winners 7-8, losers 5-6


def test_switch_off_keeps_old_rule():
    S = _league()
    PS.FADE_IN = False
    try:
        assert S.price("2026 1.01(X)", "2025-11-25", SLOTS, RAVG) is None
    finally:
        PS.FADE_IN = True


def test_committed_picks_never_read_the_landed_slot():
    """before its order is set, a pick prices off its original team's odds only: the landed slot in its label
    ("2026 2.03(...)") prices the same as the bare future label of that team ("2026 2(team)")"""
    if not (_ROOT / "exports" / "team_week.csv").exists():
        print("skip: no exports")
        return
    S = PS.SlotOdds(value=None)
    rp = pd.read_csv(_ROOT / "exports" / "rookie_picks.csv")
    sp = {f"2.{s:02d}": 500.0 - 40 * s for s in range(1, 10)}
    n = 0
    for r in rp[(rp.Year == 2026) & rp.Number.astype(str).str.fullmatch(r"2\.0[1-8]")].itertuples():
        a = S.price(f"2026 {r.Number}(X. Player)", "2025-12-01", sp, {2: 300.0})
        b = S.price(f"2026 2({r._5})", "2025-12-01", sp, {2: 300.0})
        assert a is not None and a == b, (r.Number, a, b)
        n += 1
    assert n == 8, n


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("ok", _n)
