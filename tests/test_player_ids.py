"""Sleeper ids beside every player name (lotg_support.player_ids).

Unit tests run anywhere. The data tests read the committed exports and skip
cleanly while they predate the id columns (or are absent): every name has an
id, every id a name, one id never names two players in one week, and a trade
cell's id list matches its player names.

Run directly (`python tests/test_player_ids.py`) or via pytest.
"""
import re
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "lib"), str(_ROOT / "src")]

from lotg_support import player_ids as P  # noqa: E402

_EXPORTS = _ROOT / "exports"
_PICK = re.compile(r"^\d{4} ")


def _skip(msg):
    try:
        import pytest
        pytest.skip(msg)
    except ImportError:
        print("SKIP", msg)
        raise SystemExit(0)


def _sheet(stem):
    p = _EXPORTS / f"{stem}.csv"
    return pd.read_csv(p, dtype=str, keep_default_na=False) if p.exists() else None


def _sheets_with_ids():
    sheets = {stem: _sheet(stem) for stem in {s for s, *_ in P.PAIRS}}
    pw = sheets.get("player_week")
    if pw is None:
        _skip("exports/ absent")
    if P.PLAYER_ID not in pw.columns:
        _skip("exports predate the id columns")
    return sheets


def _is_player_asset(a):
    return not _PICK.match(a) and "faab" not in a.lower()


# --------------------------------------------------------------------- unit
def test_clean_id_is_a_bare_string():
    assert P.clean_id(7564) == "7564"
    assert P.clean_id(7564.0) == "7564"
    assert P.clean_id("7564.0") == "7564"
    assert P.clean_id(" 4034 ") == "4034"
    assert P.clean_id("DAL") == "DAL"
    for blank in (None, float("nan"), "", "nan", "None", "N/A", pd.NA):
        assert P.clean_id(blank) is None


def test_join_and_split_round_trip():
    assert P.join_ids(["4034", 6794.0, None]) == "4034; 6794"
    assert P.join_ids([]) is None and P.join_ids(None) is None
    assert P.split_ids("4034; 6794") == ["4034", "6794"]
    assert P.split_ids("") == []


def test_add_export_ids_per_sheet():
    pw = pd.DataFrame({"Player": ["A", "B"], "Player ID": ["1", 2.0],
                       "Reference player name": ["Empty slot", "A"],
                       "Reference player ID": ["0", "1"]})
    out = P.add_export_ids("Player-Week", pw)
    assert out["Player ID"].tolist() == ["1", "2"]
    assert out["Reference player ID"].tolist() == [None, "1"]
    assert pw["Player ID"].tolist() == ["1", 2.0], "input frame must not change"

    pat = P.add_export_ids("Player-all-time", pd.DataFrame({"Player": ["A"], "Player ID": ["1"]}),
                           gsis_of=lambda p: {"1": "00-0031234"}.get(p))
    assert pat["GSIS ID"].tolist() == ["00-0031234"]

    ad = P.add_export_ids("add_drops", pd.DataFrame({"_added_pid": ["5", None], "_dropped_pid": [None, "6"]}))
    assert ad["Player Added ID"].tolist() == ["5", None]
    assert ad["Player Dropped ID"].tolist() == [None, "6"]

    ph = P.add_export_ids("rookie_picks", pd.DataFrame({"_player_id": ["9", None]}))
    assert ph["Player Picked ID"].tolist() == ["9", None]

    tr = P.add_export_ids("trades", pd.DataFrame({"_recv_player_ids": [["1", "2"], []],
                                                  "_drop_player_ids": [[], ["3"]]}))
    assert tr["Player IDs received"].tolist() == ["1; 2", None]
    assert tr["Player IDs sent"].tolist() == [None, "3"]


def test_unmapped_rows_flags_both_directions():
    sheets = {
        "player_week": pd.DataFrame({"Player": ["A", "B", ""], "Player ID": ["1", "", "3"],
                                     "Reference player name": ["Empty slot", "", ""],
                                     "Reference player ID": ["", "", ""]}),
        "trades": pd.DataFrame({"Assets received": ["A; 2025 1.05(B); $5 FAAB", "A; B"],
                                "Player IDs received": ["1", "1"],
                                "Assets sent": ["", ""], "Player IDs sent": ["", ""]}),
    }
    bad = P.unmapped_rows(sheets, _is_player_asset)
    got = sorted(zip(bad["Sheet"], bad["Row"], bad["Problem"]))
    assert got == [("player_week", 3, "name without id"), ("player_week", 4, "id without name"),
                   ("trades", 3, "2 player name(s), 1 id(s)")], got


# --------------------------------------------------------------------- data
def test_every_named_player_has_an_id():
    sheets = _sheets_with_ids()
    bad = P.unmapped_rows(sheets, _is_player_asset)
    assert bad.empty, f"{len(bad)} row(s) without a matching id:\n{bad.head(20).to_string()}"


def test_ids_are_bare_strings():
    sheets = _sheets_with_ids()
    for stem, _name, id_col, joined in P.PAIRS:
        df = sheets.get(stem)
        if df is None or id_col not in df.columns:
            continue
        vals = [v for c in df[id_col] for v in (P.split_ids(c) if joined else [c]) if v]
        odd = [v for v in vals if v.endswith(".0") or not re.fullmatch(r"[0-9A-Z]+", v)]
        assert not odd, f"{stem}.{id_col}: {odd[:5]}"


def test_one_id_one_player_per_week():
    pw = _sheets_with_ids()["player_week"]
    two_rows = pw[pw.duplicated(["Player ID", "Year", "Week"], keep=False)]
    assert two_rows.empty, two_rows[["Player", "Player ID", "Team", "Year", "Week"]].head(10).to_string()
    names = pw.groupby(["Player ID"])["Player"].nunique()
    assert (names == 1).all(), f"an id printed under two names: {names[names > 1].head(10).to_dict()}"


def test_trade_ids_are_the_listed_players():
    sheets = _sheets_with_ids()
    tr, pat = sheets["trades"], sheets["player_all_time"]
    name_of = dict(zip(pat["Player ID"], pat["Player"]))
    wrong = []
    for side, ids_col in (("Assets received", P.RECEIVED_IDS), ("Assets sent", P.SENT_IDS)):
        for i, (cell, ids) in enumerate(zip(tr[side], tr[ids_col])):
            names = [a.strip() for a in cell.split(";") if a.strip() and _is_player_asset(a.strip())]
            got = [name_of.get(p) for p in P.split_ids(ids)]
            # A traded player who never played a LOTG week has no player_all_time row.
            if any(g is not None and g != n for g, n in zip(got, names)):
                wrong.append((i + 2, side, names, got))
    assert not wrong, wrong[:10]


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("ok", _n)
