"""The FAAB Value twins of the KTC columns (lotg_support.faab_history + src/lotg.py).

Static tests use a synthetic history; the data tests read the committed data/faab_value/ files and skip when
they are absent. Run directly (`python tests/test_faab_history.py`) or via pytest.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

from lotg_support import faab_history as FH  # noqa: E402


def _index():
    rows = []
    # weekly Tuesdays in June 2025, daily from Sept 1 2025
    for d in ["2025-06-03", "2025-06-10", "2025-06-17", "2025-09-01", "2025-09-02", "2025-09-03"]:
        rows.append(("1", d, 1000.0))
        if d >= "2025-06-10":
            rows.append(("2", d, 300.0))
    rows = [r for r in rows if not (r[0] == "1" and r[1] == "2025-09-03")]      # player 1 off the board on 09-03
    picks = pd.DataFrame([("2024-07-01", "1.01", 2000.0), ("2024-07-01", "1.05", 1050.0), ("2024-07-01", "2.01", 400.0),
                          ("2025-07-12", "1.01", 2200.0), ("2025-07-12", "1.05", 1000.0), ("2025-07-12", "2.01", 380.0)],
                         columns=["draft_day", "slot", "price"])
    return FH.FaabIndex(pd.DataFrame(rows, columns=["sid", "date", "value"]), picks)


def test_player_lookup_rules():
    f = _index()
    assert f.player("1", "2025-05-30") is None                       # before the history
    assert f.player("1", "2025-06-03") == 1000.0
    assert f.player("1", "2025-06-09") == 1000.0                     # last grid date on or before
    assert f.player("2", "2025-06-05") is None                       # not valued yet
    assert f.player("1", "2025-07-15") is None                       # more than MAX_GAP days after a grid date
    assert f.player("1", "2025-09-03") == 0.0                        # valued before, off the board that day
    assert f.player("2", "2025-09-10") == 300.0                      # trailing edge carried (CARRY days)
    assert f.player("2", "2025-10-01") is None                       # past the carry window
    assert f.player("99", "2025-09-02") is None                      # never valued
    assert f.player("1.0", "2025-06-03") == 1000.0                   # float-ish ids from a CSV
    # a draftee joins the board on the next grid date: the draft-day columns take that first value
    assert f.player_entering("2", "2025-06-05") == 300.0             # first value 5 days later
    assert f.player_entering("2", "2025-05-30") is None              # more than MAX_GAP days before it
    assert f.player_entering("1", "2025-07-15") is None              # valued before: a gap stays a gap
    assert f.player_entering("1", "2025-09-03") == 0.0               # valued before, off the board: as player()


def test_pick_price_rules():
    f = _index()
    assert f.pick("2026 1.05", "2026-03-01") == 1000.0               # same-year slot before September
    assert f.pick("2026 1.??", "2026-03-01") == (2200 + 1000) / 2    # unknown slot: round average
    assert abs(f.pick("2027 2.01", "2026-03-01") - 380.0 * 0.95) < 1e-9   # one draft further out
    assert f.pick("2026 5.01", "2026-03-01") == 20.0
    assert f.pick("2025 1.05", "2025-08-01") is None                 # its draft was held: value the player
    # before the first league draft: that draft's slot prices (Oliver, 2026-11-10)
    assert f.pick("2024 1.05", "2024-06-01") == 1050.0
    assert f.pick("2024 1.??", "2024-06-01") == (2000 + 1050) / 2
    assert abs(f.pick("2025 1.??", "2024-06-01") - (2000 + 1050) / 2 * 0.95) < 1e-9


def test_trade_diff_twins_the_ktc_rules():
    f = _index()
    today = date(2025, 9, 2)
    # depth tax: the best asset in full, the 2nd x0.6; FAAB counts $1 = $1
    assert FH.trade_diff(f, "2025-06-17", today, ["1"], ["2"], [], [], 0, 50) == round(1000 - (300 + 50 * 0.6), 1)
    assert FH.trade_diff(f, "2025-06-17", today, ["1"], [], [], [], 0, 0) == 1000.0         # empty side = 0
    assert FH.trade_diff(f, "2025-06-05", today, ["2"], ["1"], [], [], 0, 0) is None        # a side with no value
    assert FH.trade_diff(f, "2025-10-01", today, ["1"], ["2"], [], [], 0, 0) is None        # future checkpoint
    assert FH.trade_diff(f, "2025-06-17", today, [], [], [], [], 0, 0) is None              # nothing traded


def test_drafted_pick_becomes_the_player():
    f = _index()
    drafted = ("2", date(2025, 9, 2))
    assert FH.pick_value(f, "2025 1.05", drafted, "2025-07-01") == 1050.0      # before its draft: the price from earlier drafts
    assert FH.pick_value(f, "2025 1.05", drafted, "2025-09-02") == 300.0       # after: the drafted player
    assert FH.pick_value(f, "2025 1.05", None, "2025-09-02") is None
    assert FH.net(None, None) is None and FH.net(5.0, None) == 5.0 and FH.net(None, 2.0) == -2.0


def test_twin_names_and_column_rules():
    import lotg
    import formula_equations as FE
    for sheet, cols in (("add_drops", ["KTC value of player added at deal time", "Net KTC value 1 year later"]),
                        ("trades", ["Pick value received", "Change in pick value at draft time",
                                    "KTC value difference at end of season"]),
                        ("picks", ["KTC on draft day", "Pick-adjusted Difference in KTC 2 years after draft day"]),
                        ("player_additions", ["KTC at pickup", "KTC change 3 years after pickup"])):
        for c in cols:
            t = FE.faab_twin(c)
            assert t and "FAAB Value" in t, c
            assert lotg._faab_twin_base(t) == c.lower(), (t, lotg._faab_twin_base(t))
            assert lotg._column_kind(t) == lotg._column_kind(c), c
            assert lotg._preserve_na(t) == lotg._preserve_na(c), c
            assert lotg._col_topic(t) == lotg._col_topic(c), c
    assert lotg._faab_twin_base("Price paid (FAAB)") == "price paid (faab)"


def test_every_ktc_unit_column_has_its_twin_beside_it():
    from lotg_support.plan import load_plan_catalog
    import formula_equations as FE
    plan = load_plan_catalog(_ROOT / "plan" / "LOTG Plan - Sheet1.csv")
    n = 0
    for (stat, sheet) in FE.KTC_UNIT_STATS:
        for sh in sheet.split(" / "):
            cols = plan[sh]
            assert stat in cols and FE.faab_twin(stat) in cols, (sh, stat)
            i, j = cols.index(stat), cols.index(FE.faab_twin(stat))
            assert 0 < j - i <= 3, (sh, stat, i, j)          # right after it (picks: after its pick-adjusted pair)
            n += 1
    assert n == 46          # 34 Formulas rows, the pick rows on both pick sheets; multi-column rows make it 53
    twins = [c for sh in ("add_drops", "trades", "rookie_picks", "non_rookie_picks", "player_additions")
             for c in plan[sh] if "FAAB Value" in c]
    assert len(twins) == 53, len(twins)


def test_committed_pick_table_matches_faab_inputs():
    """the exported slot table reproduces faab_inputs.Picks.value (the fit's own pick prices)"""
    if not (_ROOT / "exports" / "player_additions.csv").exists():
        print("skip: no exports")
        return
    from lotg_support import faab_inputs as I
    picks = I.Picks(I.player_additions_sid())
    # the same history on both sides: before its order is set a pick's price reads roster strength from it
    # (faab_pick_slots); faab_inputs.Picks reads the committed history too
    H = pd.read_csv(FH.HISTORY, dtype={"sid": str, "date": str}) if FH.HISTORY.exists() else pd.DataFrame(columns=["sid", "date", "value"])
    f = FH.FaabIndex(H, FH.pick_price_table(picks))
    n = 0
    for d in ["2021-03-01", "2021-08-01", "2022-03-01", "2023-01-15", "2023-08-01", "2024-02-10", "2025-05-05", "2025-11-20", "2026-06-30"]:
        t = pd.Timestamp(d)
        for lab in [f"{t.year} 1.01", f"{t.year} 2.07", f"{t.year} 3.??", f"{t.year + 1} 1.??", f"{t.year + 2} 2.??",
                    f"{t.year + 1} 4.03"]:
            a, b = picks.value(lab, t), f.pick(lab, t.date())
            if b is None:
                continue                     # consumed: faab_history defers to the drafted player
            assert abs(a - b) < 1e-6, (lab, d, a, b)
            n += 1
    assert n >= 25, n


def test_rookies_have_a_draft_day_faab_value():
    """a draftee joins the FAAB board 1-3 days after the league draft; the draft-day twin takes that first value"""
    p = _ROOT / "exports" / "rookie_picks.csv"
    if not p.exists() or not FH.HISTORY.exists():
        print("skip: no exports / history")
        return
    rp = pd.read_csv(p)
    if "FAAB Value on draft day" not in rp.columns:
        print("skip: exports predate the FAAB Value twins")
        return
    y = pd.to_numeric(rp.Year, errors="coerce")
    done = rp[(y >= 2021) & (y <= 2025) & rp["Player Picked ID"].notna()]
    filled = pd.to_numeric(done["FAAB Value on draft day"], errors="coerce").notna().mean()
    assert filled >= 0.9, filled


def test_committed_history_matches_the_inputs():
    """the history's rows equal the committed inputs' values (same rules, same params) on shared (sid, date) rows"""
    if not FH.HISTORY.exists():
        print("skip: no committed history.csv")
        return
    from lotg_support import faab_value as V
    R = V.load_inputs()
    v = V.with_links(R, V.load_params())
    a = pd.DataFrame(dict(sid=R.sid.astype(str), date=pd.to_datetime(R.date).dt.strftime("%Y-%m-%d"), v=v))
    h = pd.read_csv(FH.HISTORY, dtype={"sid": str, "date": str})
    m = a.merge(h, on=["sid", "date"])
    assert len(m) > 0.5 * len(a), (len(m), len(a))
    bad = m[(m.v.round(1) - m.value).abs() > 0.15]
    assert len(bad) <= 0.01 * len(m), bad.head(10)


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("ok", _n)
