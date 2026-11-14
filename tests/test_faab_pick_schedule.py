"""The fixed FAAB pick schedule (lotg_support.faab_pick_schedule): one standard price per slot and week to the class's
NFL draft, the same in every year, read from committed CSVs only (KTC is design-time)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import faab_pick_schedule as PS  # noqa: E402


def test_same_point_of_cycle_same_price_every_year():
    S = PS.load()
    for slot in ("1.01", "1.05", "2.03", "3.08", "4.08"):
        for w in (-120, -60, -20, 0, 8):
            p = [S.base[slot] * __import__("math").exp(S.shape(PS.overall(slot), w)) for _ in range(2)]
            t21 = S.table(2021, PS.nfl_draft(2021) + pd.Timedelta(weeks=w))[slot]
            t26 = S.table(2026, PS.nfl_draft(2026) + pd.Timedelta(weeks=w))[slot]
            assert abs(t21 - t26) < 1e-9 and abs(t21 - p[0]) < 1e-9


def test_anchor_is_todays_slot_price_at_league_draft_week():
    S = PS.load()
    t = S.table(2027, PS.nfl_draft(2027) + pd.Timedelta(weeks=PS.LEAGUE_DRAFT_WEEK))
    for slot, p in S.base.items():
        assert abs(t[slot] - p) < 1e-6 * max(p, 1)


def test_further_out_never_dearer_before_the_nfl_draft():
    S = PS.load()
    for ov in (1, 8, 13, 24, 32):
        v = [S.shape(ov, w) for w in range(-200, 1)]
        assert all(a <= b + 1e-12 for a, b in zip(v, v[1:]))


def test_runtime_reads_no_ktc():
    src = (ROOT / "lib" / "lotg_support" / "faab_pick_schedule.py").read_text()
    head = src[:src.index("# ---------------------------------------------------------------------------------------------")]
    assert "ktc" not in head.split('"""', 2)[2].lower()      # outside the docstring, the run-time half never touches KTC


def test_nfl_draft_rule_matches_known_drafts():
    for y, d in PS.NFL_DRAFT.items():
        x = pd.Timestamp(f"{y}-04-23"); x = x + pd.Timedelta(days=(3 - x.dayofweek) % 7)
        assert x == pd.Timestamp(d), y


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
