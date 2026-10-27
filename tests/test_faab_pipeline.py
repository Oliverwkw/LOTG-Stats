"""FAAB value pipeline pieces (`lotg_support.faab_pipeline` / `faab_inputs` / `faab_votes` vote dates).

- the replacement line by season (184 / 208 / 200 roster spots league-wide);
- the excused-absence fallback lifts an exempt player to his preseason value and never lowers anyone;
- votes map to the grid date of the board they were shown on (never a later one), and a vote on an unknown
  player or a date before the grid is skipped, not misplaced;
- trades.csv parses into two-team sides, players resolved to their player_additions row;
- a pick's price falls with each further draft out and a late slot never prices above an early one.

None of these need scikit-learn (the models import it lazily), so they run in the build's CI. No network. Run: python tests/test_faab_pipeline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import faab_inputs as I  # noqa: E402
from lotg_support import faab_pipeline as P  # noqa: E402


def test_replacement_line_by_season():
    assert list(P.line_n(pd.to_datetime(["2023-10-01", "2024-02-01", "2024-10-01", "2025-03-01", "2026-10-24"]))) == [184, 184, 208, 200, 200]


def test_excused_fallback_lifts_to_preseason_only():
    R = pd.DataFrame({"sid": ["a", "a", "b", "b"], "date": pd.to_datetime(["2025-08-20", "2025-10-21", "2025-08-20", "2025-10-21"]),
                      "V_raw": np.array([900, 100, 300, 500], "float32"), "e_x_cur_exempt": [0, 3, 0, 3]})
    out = P.excused_fallback(R.copy()).V_raw.values
    assert out[1] == 900 and out[3] == 500 and out[0] == 900 and out[2] == 300


def test_votes_map_to_their_own_board_date():
    R = pd.DataFrame({"sid": ["1", "2", "1", "2"], "date": pd.to_datetime(["2026-10-20", "2026-10-20", "2026-10-27", "2026-10-27"])})
    csv = ("timestamp,team,question_id,kind,board_date,player_a,player_b\n"
           "10/25/2026 10:00:00,Oliverwkw,q1,pair,2026-10-24,1,2\n"
           "10/25/2026 10:00:00,Oliverwkw,q2,pair,2020-01-01,1,2\n"
           "10/25/2026 10:00:00,Oliverwkw,q3,pair,2026-10-24,1,999\n")
    idx, vd = P.vote_rows(R, csv)
    assert vd == {"2026-10-24": "2026-10-20"}                         # the board shown on the 24th = the 20th's rows
    assert sorted(R.iloc[idx].index.tolist()) == [0, 1]              # unknown player 999 and the pre-grid vote skipped


def test_trades_parse_into_two_sides():
    if not (_ROOT / "exports" / "trades.csv").exists():
        print("  [SKIP] exports absent"); return
    pa = I.player_additions_sid()
    TR = I.trades(pa)
    assert len(TR) >= 200
    two = [s for s in TR.values() if len(s) == 2]
    assert len(two) / len(TR) > 0.95
    kinds = {k for s in TR.values() for side in s.values() for k, _, _ in side}
    assert kinds <= {"faab", "pick", "player", "startup", "unknown"}
    pl = [(x, a) for s in TR.values() for side in s.values() for k, x, a in side if k == "player"]
    assert all(pa.loc[x, "Player"] == a for x, a in pl[:300])


def test_pick_prices_fall_with_distance_and_slot():
    if not (_ROOT / "exports" / "rookie_picks.csv").exists():
        print("  [SKIP] exports absent"); return
    pk = I.Picks(I.player_additions_sid())
    d = pd.Timestamp("2026-03-01")
    assert pk.value("2026 1", d) > pk.value("2027 1", d) > pk.value("2028 1", d)
    assert pk.value("2026 1", d) > pk.value("2026 2", d) > pk.value("2026 3", d)
    assert pk.value("2026 5", d) == 20.0


TESTS = [test_replacement_line_by_season, test_excused_fallback_lifts_to_preseason_only, test_votes_map_to_their_own_board_date,
         test_trades_parse_into_two_sides, test_pick_prices_fall_with_distance_and_slot]

if __name__ == "__main__":
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall faab pipeline checks passed")
