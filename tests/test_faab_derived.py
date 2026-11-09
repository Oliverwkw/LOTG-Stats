"""The FAAB versions of the KTC-derived columns (lotg_support.faab_derived, the build's side output).

Static tests use synthetic frames; the data test reads exports/raw/faab_derived/ (written by the build; artifact only)
and skips when it is absent. Run directly (`python tests/test_faab_derived.py`) or via pytest.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))
sys.path.insert(0, str(_ROOT / "src"))

from lotg_support import faab_derived as D  # noqa: E402


def test_transform():
    t = D.Transform()
    assert t.identity and t(250.0) == 250.0 and t(None) is None
    t = D.Transform(scale=2.0, power=0.5)
    assert abs(t(100.0) - 20.0) < 1e-12 and t(0.0) == 0.0 and t(-5.0) == 0.0


def test_asset_parsing():
    drafted = {(2024, "4.04"): "111", (2025, "2.09"): "222"}
    days = {2024: date(2024, 7, 13), 2025: date(2025, 7, 20)}
    a = D.Assets("Khalil Herbert; 2024 4.04(M. Lloyd); $15 FAAB; 2028 3(shmuel256); 2025 2.09", "9001",
                 drafted, days, date(2023, 5, 1))
    assert a.players == ["9001"] and a.faab == 15.0 and a.n == 5
    labels = [l for l, _ in a.picks]
    # before the season that sets the order a pick is valued at its round average (the KTC pass's rule)
    assert labels == ["2024 4.??", "2028 3.??", "2025 2.??"], labels
    assert a.picks[0][1] == ("111", date(2024, 7, 13)) and a.picks[1][1] is None
    b = D.Assets("2025 2.09(J. Doe); 2025 3.01", "", drafted, days, date(2025, 3, 2))
    # in the order-setting season a pick keeps its slot, unless the text shows no "(player)": the build then has no
    # slot for it either and uses the round average
    assert [l for l, _ in b.picks] == ["2025 2.09", "2025 3.??"] and b.players == []


def test_pick_specs_override_the_text():
    tr = pd.DataFrame({"Team": ["A"], "Date": ["2025-07-20 18:16:38"], "Assets received": ["2025 2.09"]})
    side = tr.assign(_fd_pk_recv='[["2025 2.??", ["333", "2025-07-20"]]]', _fd_pk_sent="[]")
    sides = [(D.Assets("2025 2.09", "", {}, {}, date(2025, 7, 20)), D.Assets("", "", {}, {}, date(2025, 7, 20)))]
    assert D.use_pick_specs(sides, tr, side) == 1
    assert sides[0][0].picks == [("2025 2.??", ("333", date(2025, 7, 20)))] and sides[0][1].picks == []


def test_oscore_rules():
    s = [pd.Series([0.0, 0.0, 5.0, 10.0]), pd.Series([1.0, 2.0, 3.0, None])]
    o = D.oscore(s, droppable=(1,))
    # an exact 0 sits at the bottom of its tie (min rank), the rest average; a droppable gap is skipped
    assert list(o) == [29.2, 45.8, 87.5, 100.0], list(o)
    assert pd.isna(D.oscore(s)[3])                                   # required component missing -> N/A


def test_pick_adjust_window():
    rp = pd.DataFrame({"Number": ["1.01", "1.02", "1.03", "1.01", "1.02", "1.03"], "x": [10, 8, 6, 12, 6, 4]})
    out = D.pick_adjust_rookie(rp, "x")
    # 1.01 (the first pick): {1.01, 1.02}; 1.03 (the last): {1.01, 1.02, 1.03}
    assert abs(out[0] - (10 - (10 + 8 + 12 + 6) / 4)) < 1e-4
    assert abs(out[2] - (6 - 46 / 6)) < 1e-4


def test_side_output_reproduces_the_build():
    """every O-Score, Trade impact score and skill, KTC and FAAB, recomputed from the side output's components"""
    side = D.load_side()
    if not side or "picks" not in side:
        print("skip: no exports/raw/faab_derived (written by the CI build)")
        return
    res = D.reproduce(side)
    for kind, r in res.items():
        for k, n in r.items():
            assert n == 0, (kind, k, n)


def test_search_without_a_transform_reproduces_the_side_output():
    """the transform search recomputes every FAAB version from the history; with no transform it must land on the
    build's own numbers, or a transform's score would mix in the search's own drift"""
    side = D.load_side()
    if not side or "_fd_pk_recv" not in side.get("trades", pd.DataFrame()):
        print("skip: no exports/raw/faab_derived with pick specs (written by the CI build)")
        return
    s = D.Search(D.EXPORTS, D.OUT, date.today())
    res = s.run(D.Transform())
    for sh, df in res.items():
        for c in df.columns:
            fc = c + D.SUFFIX
            if fc not in s.side[sh]:
                continue
            a, b = D._num(s.side[sh][fc]), D._num(df[c])
            bad = int((((a - b).abs() > 0.051) | (a.isna() != b.isna())).sum())
            assert bad == 0, (sh, c, bad)


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
            print("ok", _n)
