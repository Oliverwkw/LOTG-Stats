"""Pick swaps and protections (lotg_support.pick_conditions, data/pick_conditions.csv).

The value system is checked on toy slot prices (exact expectations), the ledger is checked for shape, and —
once a build carries the column — the trades sheet is checked for the Dobbins / trade-#68 restatement and the
two 2027 4th-round swaps.
"""
from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from lotg_support import pick_conditions as PC  # noqa: E402

EXPORTS = ROOT / "exports"


def _c(**kw):
    base = dict(cid="X", kind="swap", year=2027, rnd=4, orig="A", other="B", slots=frozenset(), after="",
                frm="B", to="A", ts="2024-01-01 00:00:00", deal="", notes="", rollover=None)
    base.update(kw)
    return PC.Condition(**base)


def _price(table):
    """slot -> value (same for every owner and year)"""
    return lambda o, s, y: float(table[s])


EARLY_MID = {s: (100.0 if s <= 4 else 60.0) for s in range(1, 9)}       # KTC's two quarters a round spans
LINEAR = {s: 100.0 - 10 * s for s in range(1, 9)}


def test_ledger_loads_and_validates():
    conds = PC.load()
    ids = {c.cid for c in conds}
    assert {"DOBBINS-2025-2ND", "DOBBINS-2025-2ND-UNPROTECT", "SWAP-EKELER", "SWAP-LUKE-9",
            "KAMARA-2029-4TH"} <= ids, ids
    d = {c.cid: c for c in conds}
    assert d["DOBBINS-2025-2ND"].slots == frozenset({1, 2, 3, 4}) and d["DOBBINS-2025-2ND"].rollover == 2026
    assert d["SWAP-LUKE-9"].after == "SWAP-EKELER"
    for c in conds:
        lab = PC.label(c)
        if c.has_asset:
            # never a leading year: every pick-label parser keys on '^YYYY'
            assert lab and not re.match(r"^\d{4}\b", lab) and PC.is_label(lab), lab
            assert PC.from_label(lab, conds) is c
        else:
            assert lab is None


def test_protection_parts_sum_to_the_whole_pick():
    for table in (EARLY_MID, LINEAR):
        for roll in (None, 2026):
            prot = _c(kind="protected_pick", orig="S", other="", slots=frozenset({1, 2, 3, 4}), rollover=roll)
            rem = _c(kind="protection_removal", orig="S", other="", slots=frozenset({1, 2, 3, 4}), rollover=roll)
            rollv = (sum(table.values()) / 8) if roll else 0.0
            pv = lambda o, s, y: float(table[s]) if y == 2027 else (rollv if roll else 0.0)
            vp, vr = PC.value(prot, [prot], pv), PC.value(rem, [rem], pv)
            whole = sum(table.values()) / 8
            assert abs(vp + vr - whole) < 1e-9, (vp, vr, whole)
            top = sum(table[s] for s in range(1, 5)) / 8
            assert abs(vr - (top - 0.5 * rollv)) < 1e-9


def test_protection_resolves_once_drafted():
    rem = _c(kind="protection_removal", orig="S", other="", slots=frozenset({1, 2, 3, 4}), rollover=2026)
    prot = _c(kind="protected_pick", orig="S", other="", slots=frozenset({1, 2, 3, 4}), rollover=2026)
    pv = _price(LINEAR)
    landed_8 = lambda o, y: 8 if y == 2027 else None
    assert PC.value(rem, [rem], pv, landed_8) == 0.0                  # never triggered (2.08)
    assert PC.value(prot, [prot], pv, landed_8) == LINEAR[8]          # the pick itself
    landed_2 = lambda o, y: 2 if y == 2027 else None
    assert abs(PC.value(rem, [rem], pv, landed_2) - (LINEAR[2] - sum(LINEAR.values()) / 8)) < 1e-9


def test_two_pick_swap_is_two_sevenths_of_the_quarter_gap():
    sw = _c()
    v = PC.value(sw, [sw], _price(EARLY_MID))
    assert abs(v - (2 / 7) * (100 - 60)) < 1e-9, v
    assert PC.value(sw, [sw], _price(EARLY_MID), lambda o, y: {"A": 3, "B": 6}[o]) == 0.0   # already the better
    assert PC.value(sw, [sw], _price(EARLY_MID), lambda o, y: {"A": 6, "B": 3}[o]) == 40.0


def test_chained_swap_matches_brute_force():
    first = _c(cid="J", orig="J", other="L", frm="O", to="J")
    second = _c(cid="K", orig="O", other="", after="J", frm="O", to="K")
    conds = [first, second]
    got = PC.value(second, conds, _price(LINEAR))
    tot = n = 0
    for sj, sl, so in itertools.permutations(range(1, 9), 3):
        keep = max(sj, sl)                     # Oliver keeps the worse of J's / L's after the first swap
        better = min(so, keep)
        tot += LINEAR[better] - LINEAR[so]
        n += 1
    assert abs(got - tot / n) < 1e-9, (got, tot / n)
    assert got > 0


def test_better_of_two_picks():
    b = _c(kind="better_of", orig="S", other="L", frm="S", to="M")
    v = PC.value(b, [b], _price(EARLY_MID))
    # E[max] over distinct slot pairs: both late 12/56 -> 60, otherwise 100
    assert abs(v - (44 * 100 + 12 * 60) / 56) < 1e-9, v
    assert PC.value(b, [b], _price(LINEAR), lambda o, y: {"S": 7, "L": 2}[o]) == LINEAR[2]
    assert PC.label(b).startswith("Pick better of: ") and PC.is_label(PC.label(b))


def test_slot_curve_keeps_the_round_average():
    for rnd in (1, 2, 3, 4):
        shares = [PC.slot_share(rnd, s) for s in range(1, 9)]
        assert abs(sum(shares) / 8 - 1.0) < 1e-9 and shares == sorted(shares, reverse=True), (rnd, shares)
    pv = PC.unit_pick_value(4, lambda o, y: 100.0, lambda o, s, y: 7.0, lambda o, y: 3 if o == "A" else None)
    assert pv("A", 3, 2027) == 7.0                                    # settled: priced exactly
    assert abs(pv("B", 1, 2027) - 100.0 * PC.slot_share(4, 1)) < 1e-9
    conds = PC.load()
    flat = PC.unit_pick_value(4, lambda o, y: 100.0, lambda o, s, y: None, lambda o, y: None)
    for cid in ("SWAP-EKELER", "SWAP-LUKE-9"):
        c = next(x for x in conds if x.cid == cid)
        assert 0.05 < PC.portion(c, conds, flat) < 0.5, cid           # a real price, not KTC's flat quarters
    txt = PC.describe(conds[0], 0.5, ktc=1234.4, faab=56.78)
    assert "1,234 KTC" in txt and "$56.8 FAAB" in txt


def test_faab_value_goes_through_faab_history_pick_value():
    from lotg_support import faab_history as FH
    conds = PC.load()
    PC.set_faab_context(None, conds, {}, lambda y: __import__("datetime").date(int(y), 9, 8))
    try:
        sw = next(c for c in conds if c.cid == "SWAP-EKELER")
        price = lambda lbl, dk, d: 80.0          # the round-average FAAB price
        v = PC.faab_value(PC.spec_label(sw), "2025-01-01", price=price)
        w = [80.0 * PC.slot_share(4, s) for s in range(1, 9)]
        want = sum(max(w[a], w[b]) - w[a] for a in range(8) for b in range(8) if a != b) / 56
        assert abs(v - want) < 1e-9, (v, want)
        assert FH.pick_value(None, "2027 cond:NOPE", None, "2025-01-01") is None
    finally:
        PC._FAAB_CTX.clear()


def test_every_condition_names_a_completed_trade_with_both_teams():
    """matched by completion time like the commissioner overlay (tests/test_commissioner_overlay_match.py)"""
    import glob
    import json
    if not glob.glob(str(ROOT / "exports/snapshot/season_2021")):
        print("SKIP: no Sleeper snapshot")
        return
    sys.path.insert(0, str(ROOT / "tests"))
    from test_commissioner_overlay_match import _completions
    done = _completions()
    missing = [c.cid for c in PC.load() if c.ts not in done]
    assert not missing, f"pick conditions matching no trade completion: {missing}"


# ------------------------------------------------------------------------------------------- the build's output

def _trades():
    p = EXPORTS / "trades.csv"
    if not p.exists():
        return None
    import pandas as pd
    t = pd.read_csv(p, dtype=str)
    return t if "Pick swaps and protections" in t.columns else None


def test_dobbins_and_trade_68_restated():
    t = _trades()
    if t is None:
        print("SKIP: exports predate 'Pick swaps and protections'")
        return
    dob = t[t.Date.str.startswith("2022-06-08") & (t.Team == "shmuel256")]
    assert len(dob) == 1 and "2025 2.08" in dob["Assets received"].iloc[0], dob["Assets received"].tolist()
    assert "top-4 protected" in dob["Pick swaps and protections"].iloc[0]
    for txt in t["Pick swaps and protections"].dropna():
        assert re.search(r"[\d,]+ KTC", txt) and re.search(r"\$[\d,.]+ FAAB", txt), txt   # both prices, every one
    t68 = t[t.Date.str.startswith("2023-01-14 02:11:02")]
    sam = t68[t68.Team == "shmuel256"].iloc[0]
    steve = t68[t68.Team == "stevenb123"].iloc[0]
    assert "2025 2.08" not in str(sam["Assets received"]), sam["Assets received"]
    assert str(sam["Assets received"]).startswith("Pick protection removed: 2025 2nd(stevenb123)")
    assert "2025 4.04" in str(steve["Assets received"])
    assert "Removes the top-4 protection" in str(sam["Pick swaps and protections"])
    # the 2nd's chain now starts in the Dobbins trade
    rp = __import__("pandas").read_csv(EXPORTS / "rookie_picks.csv", dtype=str)
    dart = rp[(rp.Year.str.startswith("2025")) & (rp.Number == "2.08")].iloc[0]
    assert dart["Original Team"] == "stevenb123" and dart["Number of trades"] == "3"


def test_fourth_round_swaps_on_their_trades():
    t = _trades()
    if t is None:
        print("SKIP: exports predate 'Pick swaps and protections'")
        return
    ek = t[t.Date.str.startswith("2024-07-13 18:02:35")]
    assert any("Pick swap: 2027 4ths, JacobRosenzweig gets the better" in str(x)
               for x in ek[ek.Team == "JacobRosenzweig"]["Assets received"])
    assert any("Pick swap: 2027 4ths" in str(x) for x in ek[ek.Team == "Oliverwkw"]["Assets sent"])
    km = t[t.Date.str.startswith("2025-11-02 11:37:36") & (t.Team == "shmuel256")]
    assert any("Pick better of: 2029 4th(stevenb123) or 2029 4th(LWebs53)" in str(x) for x in km["Assets received"])
    lk = t[t.Date.str.startswith("2026-10-22") & (t.Team == "LWebs53")]
    assert any("Pick swap: 2027 4ths, LWebs53 gets the better" in str(x) for x in lk["Assets received"])


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("ok", _n)
