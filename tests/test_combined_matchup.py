"""team_week's combined-matchup block (lotg_support.matchup).

One game's two teams taken together: the value sits in the WINNER's row, the
loser's row reads "winner" (linked to it in the workbook). Sums add the two
teams; efficiency and boom/bust % average each team's own value; bench points
are combined Max PF − combined PF. PF keeps the +5 semifinal bonus.

Run: python tests/test_combined_matchup.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

from lotg_support import matchup as M  # noqa: E402
from lotg_support import digest as D  # noqa: E402


def _game(**over):
    a = {"Team": "A", "Opponent": "B", "Year": 2025, "Week": 3, "Win?": True,
         "PF": 150.0, "Max PF": 170.0, "Efficiency": 150 / 170,
         "Points from QBs": 40.0, "Donuts (starters)": 1, "% of starters boom": 20.0,
         "Starter turnover from previous week": 2}
    b = {"Team": "B", "Opponent": "A", "Year": 2025, "Week": 3, "Win?": False,
         "PF": 120.0, "Max PF": 160.0, "Efficiency": 120 / 160,
         "Points from QBs": 30.0, "Donuts (starters)": 0, "% of starters boom": 10.0,
         "Starter turnover from previous week": 1}
    a.update(over.get("a", {}))
    b.update(over.get("b", {}))
    return pd.DataFrame([b, a])   # loser first: order must not matter


def test_value_in_winner_row_and_winner_text_in_loser_row():
    out = M.add_combined_columns(_game()).set_index("Team")
    assert out.at["A", "Combined points"] == 270.0
    assert out.at["B", "Combined points"] == M.WINNER_TEXT
    assert out.at["A", "Combined Max PF"] == 330.0
    assert out.at["A", "Combined bench points"] == 60.0            # 330 - 270
    assert out.at["A", "Combined points from QBs"] == 70.0
    assert out.at["A", "Combined donuts (starters)"] == 1
    assert isinstance(out.at["A", "Combined donuts (starters)"], int)  # a count renders "1"
    for c in M.COMBINED_NAMES:
        if c in ("Combined points", "Combined Max PF", "Combined efficiency", "Combined bench points",
                 "Combined points from QBs", "Combined donuts (starters)", "Combined % of starters boom",
                 "Combined starter turnover from previous week"):
            assert out.at["B", c] == M.WINNER_TEXT, c


def test_efficiency_and_boom_average_each_teams_own_value():
    out = M.add_combined_columns(_game()).set_index("Team")
    # Average of 0.8824 and 0.75, NOT 270/330 = 0.8182.
    assert abs(out.at["A", "Combined efficiency"] - round((150 / 170 + 120 / 160) / 2, 4)) < 1e-9
    assert out.at["A", "Combined % of starters boom"] == 15.0


def test_winner_follows_win_flag_not_pf():
    # 2026+ two-week final: a team can trail in one leg yet win the round.
    g = _game(a={"Win?": False, "PF": 150.0}, b={"Win?": True, "PF": 120.0})
    out = M.add_combined_columns(g).set_index("Team")
    assert out.at["B", "Combined points"] == 270.0
    assert out.at["A", "Combined points"] == M.WINNER_TEXT


def test_tie_puts_value_in_both_rows():
    g = _game(a={"Win?": False, "PF": 130.0}, b={"Win?": False, "PF": 130.0})
    out = M.add_combined_columns(g).set_index("Team")
    assert out.at["A", "Combined points"] == 260.0 == out.at["B", "Combined points"]


def test_missing_base_blanks_both_rows():
    g = _game(b={"Starter turnover from previous week": None})
    out = M.add_combined_columns(g).set_index("Team")
    c = "Combined starter turnover from previous week"
    assert out.at["A", c] is None and out.at["B", c] is None


def test_no_opponent_row_is_blank_and_frame_untouched():
    g = _game().iloc[[1]]                      # the winner alone
    out = M.add_combined_columns(g)
    assert out["Combined points"].isna().all()
    assert "Combined points" not in g.columns


def test_workbook_topic_and_formats_follow_the_base():
    import lotg
    assert {lotg._col_topic(c) for c in M.COMBINED_NAMES} == {"Combined"}
    assert "Combined" in lotg._TOPIC_FILL
    for c, base, _how in M.COMBINED_COLUMNS:
        assert lotg._col_number_format(c) == lotg._col_number_format(base), c
    assert lotg._col_number_format("Combined efficiency") == "0.00%"


def test_plan_and_formulas_carry_the_block_last():
    import formulas
    from lotg_support.plan import load_plan_catalog
    cat = load_plan_catalog(_ROOT / "plan" / "LOTG Plan - Sheet1.csv")
    assert cat["team-week"][-len(M.COMBINED_NAMES):] == list(M.COMBINED_NAMES)
    assert formulas.undocumented_columns(cat) == []


def test_email_names_both_teams_on_a_combined_stat():
    tw = pd.DataFrame({"Team": ["shmuel256", "LWebs53"], "Year": [2026, 2022], "Week": [4, 2],
                       "Opponent": ["LWebs53", "stevenb123"]})
    col = "Combined points"
    hl = [D.WeeklyHighlight("teams", "shmuel256", col, "high", 1, 380.5, week=4)]
    ev = [D.EventCrossing("team_week", "shmuel256 2026 week 4", col, "high", 1, 380.5,
                          passed=("LWebs53 2022 week 2",))]
    out, _rest = D.fold_week_boards(hl, ev, {"team_week": tw}, [(2026, 4)])
    line = out[0].line()
    assert "380.5 vs LWebs53" in line, line
    assert "LWebs53 2022 week 2 (vs stevenb123)" in line, line


def test_committed_exports_one_value_per_game():
    """On the committed team_week (built columns if present, else the helper over
    it): completed seasons have exactly one number and one "winner" per game, and
    Combined points = PF + Points against on the winner's row."""
    p = _ROOT / "exports" / "team_week.csv"
    if not p.exists():
        print("SKIP: exports/team_week.csv absent")
        return
    tw = pd.read_csv(p, low_memory=False)
    if "Combined points" not in tw.columns:
        tw = M.add_combined_columns(tw)
    yrs = pd.to_numeric(tw["Year"], errors="coerce")
    done = tw[yrs < yrs.max()]
    cp = done["Combined points"].astype(str).str.strip()
    assert (cp == M.WINNER_TEXT).sum() * 2 == len(done), "one winner cell per game"
    num = pd.to_numeric(done["Combined points"], errors="coerce")
    w = done[num.notna()]
    assert len(w) * 2 == len(done)
    diff = (pd.to_numeric(w["Combined points"]) - (w["PF"] + w["Points against"])).abs()
    assert diff.max() < 0.011, diff.max()
    assert w["Win?"].astype(str).str.lower().eq("true").all()


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
