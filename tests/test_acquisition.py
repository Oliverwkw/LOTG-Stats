"""Guards for `lotg_support.acquisition` — player_additions' "Price paid (FAAB)"
and "Points above expectation (total / rate)".

Synthetic fixtures pin the arithmetic: the channel rules, the depth-taxed trade
split, a better price never predicting less, a tenure with no rostered week, and
rate = total / weeks rostered. Data checks tie the exported columns to numbers
the build already publishes (add_drops' winning bid, the tenure length) and skip
when the exports predate the columns; they assert only on completed seasons.

Run: python tests/test_acquisition.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import acquisition as ACQ  # noqa: E402

_PA = _ROOT / "exports" / "player_additions.csv"


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def _additions():
    """The exported player_additions on completed seasons, or None."""
    if not _PA.exists():
        return None
    pa = pd.read_csv(_PA, low_memory=False)
    if not set(ACQ.COLUMNS).issubset(pa.columns):
        return None
    seasons = pd.to_numeric(pa["Season"], errors="coerce")
    return pa[seasons < seasons.max()].copy()


# --- synthetic -----------------------------------------------------------
def test_channel_rules():
    assert ACQ.channel("Commissioner", 0) is None
    assert ACQ.channel("Free agency", 0) == "free"
    assert ACQ.channel("Waiver", 0) == "free"          # a $0 claim cost nothing
    assert ACQ.channel("Waiver", 7) == "waiver"
    assert ACQ.channel("Trade") == "trade"
    assert ACQ.channel("Draft", draft_kind="rookie") == "rookie"
    assert ACQ.channel("Draft", draft_kind="startup") == "startup"
    assert ACQ.channel("Draft", draft_kind="vet") == "startup"   # continues the startup board


def test_value_shares():
    assert ACQ.value_shares([5000.0]) == [1.0]
    s = ACQ.value_shares([1000.0, 4000.0, 2000.0])
    assert abs(sum(s) - 1.0) < 1e-12
    assert abs(s[1] - 4000 / 7000) < 1e-12 and abs(s[0] - 1000 / 7000) < 1e-12   # no depth tax
    assert ACQ.value_shares([3000.0, None]) is None     # one unpriced asset: no guessed split
    assert ACQ.value_shares([0.0, 0.0]) == [0.5, 0.5]
    # the allocated prices add back up to the sent side's price
    assert abs(sum(9000 * x for x in s) - 9000) < 1e-9


def test_slot_price_curve_never_rises_with_the_pick_number():
    # the 2020 startup's top: 1.04 drafted below 1.01-1.03 must not cost more
    picks = [(1, 9999.0), (2, 9983.0), (3, 8850.0), (4, 8043.0), (5, 9999.0), (6, 9999.0), (9, 8350.0)]
    c = ACQ.slot_price_curve(picks)
    vals = [c[s] for s in sorted(c)]
    assert all(a >= b for a, b in zip(vals, vals[1:])), c
    assert c[1] >= c[4] and c[6] > c[7] > c[8] > c[9]       # the gap is interpolated
    assert ACQ.slot_price(c, 20) == c[9] and ACQ.slot_price(c, 0) == c[1]
    # several classes per slot: the mean per slot, weighted
    c2 = ACQ.slot_price_curve([(1, 7000.0), (1, 5000.0), (2, 4000.0)])
    assert c2 == {1: 6000.0, 2: 4000.0}
    assert ACQ.slot_price_curve([]) == {}


def test_money_curve_anchors():
    """Option B (user 2026-10-03): KTC places an asset on the rookie board; a
    mid first costs $1,000; below the 4.08 it is KTC / 100; dollars only rise
    with value, steeply at the top."""
    board = ACQ.slot_price_curve([(1, 7220.0), (2, 6010.0), (3, 5980.0), (4, 5600.0), (5, 5500.0),
                                  (6, 4860.0), (9, 4790.0), (17, 3380.0), (32, 2080.0)])
    m = ACQ.MoneyCurve(board, 32)
    k_mid = (board[4] + board[5]) / 2
    assert abs(m.faab(k_mid) - ACQ.MID_FIRST_FAAB) < 1.0
    assert m.faab(1000.0) == 10.0 and abs(m.faab(2080.0) - 20.8) < 1e-9   # the locked 100 KTC per $
    ks = [500, 1500, 2080, 2500, 3380, 4790, 5600, 6010, 7220, 9000, 9999]
    dollars = [m.faab(k) for k in ks]
    assert all(a < b for a, b in zip(dollars, dollars[1:])), dollars
    # top guys are not in the same hemisphere as a margin guy
    assert m.faab(9999.0) > 100 * m.faab(1000.0)
    # above the 1.01 the board continues at its 1.01 -> 1.02 step
    assert abs(m.slot_of(7220.0 + 1210.0) - 0.0) < 1e-9
    assert m.faab(None) is None


def test_pick_year_discount_is_the_league_fit():
    """Fitted from the league's pick-for-pick trades (2026-10-03); fixed so a
    price stays what it was at the move."""
    assert ACQ.PICK_YEAR_DISCOUNT == 0.80


def test_trade_price_feature_is_in_dollars():
    assert ACQ.price_feature("trade", trade_faab=0.0) == 0.0
    assert abs(ACQ.price_feature("trade", trade_faab=99.0) - math.log(100.0)) < 1e-12
    assert ACQ.price_feature("trade", trade_faab=None) is None


def test_depth_value_matches_the_trade_margin_rule():
    assert ACQ.depth_value([3000.0]) == 3000.0
    assert abs(ACQ.depth_value([1000.0, 3000.0]) - (3000 + 600)) < 1e-9


def _waiver_pool(n_per_bid=12, weeks=20):
    """Waiver adds at bids 1..40: a bigger bid scores more every week, held
    `weeks` weeks, never cut."""
    out = []
    for bid in (1, 5, 10, 20, 40):
        for j in range(n_per_bid):
            rate = 2.0 + 0.25 * bid + (j % 3)
            cf = [rate] * weeks
            out.append(ACQ.Addition(key=(bid, j), ch="waiver", p=ACQ.price_feature("waiver", faab=bid),
                                    pos="WR", held=[(k + 1, rate) for k in range(weeks)],
                                    cf=cf, noff=[k // 17 for k in range(weeks)]))
    return out


def test_better_price_never_expects_less():
    pool = _waiver_pool()
    probe = [ACQ.Addition(key=("probe", b), ch="waiver", p=ACQ.price_feature("waiver", faab=b), pos="WR",
                          held=[(k + 1, 10.0) for k in range(10)], cf=[10.0] * 20,
                          noff=[0] * 17 + [1] * 3) for b in (1, 5, 10, 20, 40)]
    out = ACQ.points_above_expectation(pool + probe)
    totals = [out[("probe", b)][ACQ.TOTAL_COLUMN] for b in (1, 5, 10, 20, 40)]
    # same production, higher bid -> higher expectation -> lower points above it
    assert all(a >= b - 1e-6 for a, b in zip(totals, totals[1:])), totals


def test_rate_is_total_over_weeks_rostered_and_empty_tenures():
    pool = _waiver_pool()
    never = ACQ.Addition(key="never", ch="waiver", p=ACQ.price_feature("waiver", faab=10), pos="RB",
                         held=[], cf=[3.0] * 20, noff=[0] * 20)
    unpriced = ACQ.Addition(key="unpriced", ch="trade", p=None, pos="RB",
                            held=[(1, 9.0)], cf=[9.0], noff=[0])
    comm = ACQ.Addition(key="comm", ch=None, p=None, pos="QB", held=[(1, 9.0)], cf=[9.0], noff=[0])
    out = ACQ.points_above_expectation(pool + [never, unpriced, comm])
    assert out["never"] == {ACQ.RATE_COLUMN: 0.0, ACQ.TOTAL_COLUMN: 0.0}
    assert out["unpriced"] == {ACQ.RATE_COLUMN: None, ACQ.TOTAL_COLUMN: None}
    assert out["comm"] == {ACQ.RATE_COLUMN: None, ACQ.TOTAL_COLUMN: None}
    for a in pool:
        r = out[a.key]
        assert abs(r[ACQ.RATE_COLUMN] - r[ACQ.TOTAL_COLUMN] / len(a.held)) < 0.01


def test_expectation_counts_peers_after_they_left():
    """Y is what peers SCORED in each week since acquisition, held or not: a
    pool whose players were all cut after week 2 but kept scoring 6 a week
    elsewhere expects ~6 in week 10, not 0."""
    pool = [ACQ.Addition(key=j, ch="free", p=0.0, pos="WR",
                         held=[(1, 6.0), (2, 6.0)], cf=[6.0] * 12, noff=[0] * 12) for j in range(40)]
    late = ACQ.Addition(key="late", ch="free", p=0.0, pos="WR",
                        held=[(10, 6.0)], cf=[6.0] * 12, noff=[0] * 12)
    out = ACQ.points_above_expectation(pool + [late])
    assert abs(out["late"][ACQ.TOTAL_COLUMN]) < 0.5, out["late"]


def test_season_scale_and_calendar():
    sc = ACQ.season_scale({2020: 10.0, 2021: 12.0, 2026: 12.0}, {2020: 2020, 2021: 2021, 2026: 2021})
    assert abs(sc[2020] - 1.1) < 1e-9 and abs(sc[2021] - 11 / 12) < 1e-9
    cal = ACQ.elapsed_calendar([(2021, 2), (2020, 16), (2021, 1), (2021, 1)])
    assert cal == [(2020, 16), (2021, 1), (2021, 2)]
    ends = {(2020, 16): "2020-12-28", (2021, 1): "2021-09-13", (2021, 2): "2021-09-20"}
    assert ACQ.first_elapsed_index(cal, ends, "2021-09-13") == 1      # the week ending that day counts
    assert ACQ.first_elapsed_index(cal, ends, "2021-09-14") == 2
    assert ACQ.first_elapsed_index(cal, ends, "2022-01-01") == 3      # nothing played since


# --- against the exports ---------------------------------------------------
def test_export_prices_follow_the_channel_rules():
    pa = _additions()
    if pa is None:
        return _skip("exports predate the points-above-expectation columns")
    price = pd.to_numeric(pa[ACQ.PRICE_COLUMN], errors="coerce")
    kind = pa["Addition type"].astype(str)
    assert price[kind == "Commissioner"].isna().all()
    assert (price[kind == "Free agency"] == 0).all()
    ad = pd.read_csv(_ROOT / "exports" / "add_drops.csv", low_memory=False)
    w = pa[kind == "Waiver"]
    rows = w["Link to addition"].astype(str).str.lstrip("#").astype(int) - 1
    bids = pd.to_numeric(ad.loc[rows.values, "Faab"], errors="coerce").fillna(0).values
    assert (abs(pd.to_numeric(w[ACQ.PRICE_COLUMN], errors="coerce").values - bids) < 1e-6).all()
    # every priced draft and trade row has a price, and none is negative
    assert (price.dropna() >= 0).all()
    assert price[kind == "Draft"].notna().mean() > 0.95


def _draft_order(number: object):
    try:
        r, s = str(number).split(".")
        return int(r), int(s)
    except ValueError:
        return None


def test_export_no_pick_costs_more_than_the_pick_before_it():
    """Within every draft (each rookie class, the 2020 startup, the 2021 vet
    draft), in draft order, Price paid never rises — the 2020 startup once
    priced 1.04 (Cook) above 1.01 (CMC)."""
    pa = _additions()
    if pa is None:
        return _skip("exports predate the points-above-expectation columns")
    d = pa[pa["Addition type"] == "Draft"][["Player", "Team", "Season", ACQ.PRICE_COLUMN]]
    checked = 0
    for sheet in ("rookie_picks", "non_rookie_picks"):
        pk = pd.read_csv(_ROOT / "exports" / f"{sheet}.csv", low_memory=False)
        pk = pk[pk["Player Picked"].notna()].copy()
        pk["order"] = pk["Number"].map(_draft_order)
        pk = pk[pk["order"].notna()]
        pk["Season"] = pk["Year"].astype(str).str[:4].replace({"star": "2020"}).astype(int)
        m = pk.merge(d, left_on=["Player Picked", "Team", "Season"], right_on=["Player", "Team", "Season"])
        if sheet == "rookie_picks":
            # a rookie-draft 5.0X is a FAAB buy, locked (user rule 2026-10-03)
            r5 = m["order"].map(lambda o: o[0] == 5)
            assert (m.loc[r5, ACQ.PRICE_COLUMN].astype(float) == ACQ.ROUND5_PICK_FAAB).all()
        for year, g in m.groupby("Year"):
            prices = g.sort_values("order")[ACQ.PRICE_COLUMN].astype(float).tolist()
            bumps = [(a, b) for a, b in zip(prices, prices[1:]) if b > a + 1e-9]
            assert not bumps, (sheet, year, bumps[:3])
            checked += 1
    assert checked >= 5, checked


def test_ktc_per_faab_is_the_locked_rate():
    """$1 FAAB = 100 KTC is a league rule the trades sheet and Price paid share."""
    sys.path.insert(0, str(_ROOT / "src"))
    import lotg  # noqa: E402
    assert lotg.KTC_PER_FAAB == 100.0


def test_export_player_bought_for_faab_alone_costs_the_dollars():
    """A trade sending only FAAB for one player prices him at exactly those
    dollars — the 100 KTC per $ in and out of KTC cancels only if both sides use
    the locked rate (Mason Taylor for $5, D'Onta Foreman for $3)."""
    pa = _additions()
    if pa is None:
        return _skip("exports predate the points-above-expectation columns")
    import re
    tr = pd.read_csv(_ROOT / "exports" / "trades.csv", low_memory=False)
    faab_only = tr["Assets sent"].astype(str).str.fullmatch(r"\$\d+ FAAB")
    one = ~tr["Assets received"].astype(str).str.contains(";")
    rows = tr[faab_only & one]
    checked = 0
    for i, r in rows.iterrows():
        dollars = float(re.sub(r"[^0-9.]", "", r["Assets sent"]))
        hit = pa[(pa["Link to addition"] == f"T#{i + 1}") & (pa["Player"] == r["Assets received"])]
        if hit.empty:
            continue
        assert abs(float(hit[ACQ.PRICE_COLUMN].iloc[0]) - dollars) < 0.051, (r["Assets received"], dollars)
        checked += 1
    assert checked >= 5, checked


def test_export_rate_is_total_over_tenure():
    pa = _additions()
    if pa is None:
        return _skip("exports predate the points-above-expectation columns")
    tot = pd.to_numeric(pa[ACQ.TOTAL_COLUMN], errors="coerce")
    rate = pd.to_numeric(pa[ACQ.RATE_COLUMN], errors="coerce")
    weeks = pd.to_numeric(pa["Tenure (NFL weeks)"], errors="coerce").fillna(0)
    none = weeks == 0
    priced = pd.to_numeric(pa[ACQ.PRICE_COLUMN], errors="coerce").notna() | (pa["Addition type"] == "Free agency")
    assert (tot[none & tot.notna()] == 0).all() and (rate[none & tot.notna()] == 0).all()
    assert (tot[none & priced].notna()).all()
    m = (weeks > 0) & tot.notna()
    assert ((rate[m] - tot[m] / weeks[m]).abs() <= 0.011).all()
    assert tot[pa["Addition type"] == "Commissioner"].isna().all()


def test_export_never_cut_expectation_is_centred_on_short_holds():
    """Holds of four weeks or fewer are near the expectation on average (the
    model is fitted on every week, held or not); the reward for long holds is
    the design, so only the short end is pinned."""
    pa = _additions()
    if pa is None:
        return _skip("exports predate the points-above-expectation columns")
    tot = pd.to_numeric(pa[ACQ.TOTAL_COLUMN], errors="coerce")
    weeks = pd.to_numeric(pa["Tenure (NFL weeks)"], errors="coerce")
    short = tot[(weeks > 0) & (weeks <= 4)].dropna()
    assert len(short) > 100 and abs(short.mean()) < 10, short.describe()


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            print(_n)
            _f()
    print("ok")
