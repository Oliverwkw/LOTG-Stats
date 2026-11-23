"""player_week `Injury status` (Healthy / Out / IR) beside `Injury?`.

`lotg_support.injury_status` labels the build's `Injury?` at write time:
  * Out or IR <=> Injury? True, Healthy <=> False, row for row;
  * IR = the injured weeks nflverse's weekly rosters list as status RES (by
    sleeper_id, else gsis), Out every other injured week;
  * Injury? itself is untouched: its per-season True counts for completed seasons
    are pinned here (a move is a stat change and needs the user's approval).

Data checks run on the committed exports and return early when absent; on
exports from before the column they label a frame locally first, so the same
assertions hold before and after the first build that writes it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import injury_status as S  # noqa: E402

_PW = _ROOT / "exports" / "player_week.csv"
_PAT = _ROOT / "exports" / "player_all_time.csv"

# Injury? = True player-weeks per completed season (exports of 2026-11-23).
_INJURED_BY_SEASON = {2020: 368, 2021: 634, 2022: 497, 2023: 485, 2024: 633, 2025: 695}


# ---------------------------------------------------------------- unit

def test_flag_on_reads_bools_and_csv_text():
    for v in (True, "True", "TRUE", "1", 1, 1.0, "yes"):
        assert S.flag_on(v), v
    for v in (False, "False", "0", 0, 0.0, "", None, float("nan"), "N/A", "<NA>"):
        assert not S.flag_on(v), v
    # CI reads CSVs under pandas 3 (str dtype)
    s = pd.Series(["True", "False", None], dtype="string")
    assert s.map(S.flag_on).tolist() == [True, False, False]


def test_reserve_keys_and_status_column():
    wr = pd.DataFrame({"season": [2024, 2024, 2024], "week": [3, 3, 4],
                       "status": ["RES", "ACT", "RES"],
                       "sleeper_id": ["100", "200", None], "gsis_id": ["00-1", "00-2", "00-3"]})
    sid, gs = S.reserve_keys(wr)
    assert sid == {("100", 2024, 3)}
    assert gs == {("00-1", 2024, 3), ("00-3", 2024, 4)}
    pw = pd.DataFrame({"Player ID": ["100", "200", "300", "100", "300"],
                       "Year": [2024] * 5, "Week": [3, 3, 4, 4, 5],
                       "Injury?": [True, True, True, False, True]})
    st = S.status_column(pw, sid, gs, gsis_of={"300": "00-3"}.get)
    # 100 wk3 RES by sleeper id; 200 ACT -> Out; 300 wk4 RES by gsis only;
    # 100 wk4 not injured -> Healthy; 300 wk5 not on reserve -> Out
    assert st.tolist() == ["IR", "Out", "IR", "Healthy", "Out"]
    pw["Injury status"] = st
    assert S.disagreements(pw).empty
    pw.loc[3, "Injury status"] = "Out"            # Out on a False row
    pw.loc[0, "Injury status"] = "Hurt"           # not a label
    assert sorted(S.disagreements(pw).index) == [0, 3]


def test_sanity_flags_a_disagreement(tmp_path=None):
    import tempfile
    from lotg_support.sanity import collect_findings
    d = Path(tmp_path or tempfile.mkdtemp())
    pd.DataFrame({"Player": ["A", "B"], "Year": ["2024", "2024"], "Week": ["1", "1"],
                  "Injury?": ["True", "False"], "Injury status": ["IR", "Out"]}
                 ).to_csv(d / "player_week.csv", index=False)
    f = [x for x in collect_findings(d) if x.column == "Injury status"]
    assert len(f) == 1 and f[0].severity == "ERROR" and "1 rows" in f[0].detail, f


def test_build_adds_the_column_and_keeps_injury_flag_boolean():
    src = (_ROOT / "src" / "lotg.py").read_text()
    assert 'if fname == "player_week.csv" and isinstance(frame, pd.DataFrame)' in src
    assert src.count("_add_injury_status(frame)") == 1
    import importlib.util
    spec = importlib.util.spec_from_file_location("lotg_kind_probe", _ROOT / "src" / "lotg.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["lotg_kind_probe"] = m
    spec.loader.exec_module(m)
    assert m._column_kind("Injury status") == "text"
    assert m._column_kind("Injury?") == "boolean"
    assert m._col_topic("Injury status") == m._col_topic("Injury?")
    plan = pd.read_csv(_ROOT / "plan" / "LOTG Plan - Sheet1.csv", dtype=str)["Player-Week"].dropna().tolist()
    assert plan.index("Injury status") == plan.index("Injury?") + 1


# ---------------------------------------------------------------- data

def _reserve():
    sid, gs = set(), set()
    for f in sorted((_ROOT / ".cache").glob("nflverse_weekly_rosters_*.csv")):
        a, b = S.reserve_keys(pd.read_csv(f, dtype=str, low_memory=False))
        sid |= a
        gs |= b
    return sid, gs


def _gsis_of():
    if not _PAT.exists():
        return {}
    pat = pd.read_csv(_PAT, dtype=str, usecols=["Player ID", "GSIS ID"])
    return dict(zip(pat["Player ID"], pat["GSIS ID"]))


def _pw():
    """(committed player_week with Injury status, did the build write it)."""
    if not _PW.exists():
        print("  exports/player_week.csv absent")
        return None, False
    pw = pd.read_csv(_PW, low_memory=False, dtype=str, keep_default_na=False)
    if S.COLUMN in pw.columns:
        return pw, True
    print("  exports predate Injury status: checked on a locally labelled frame")
    sid, gs = _reserve()
    pw[S.COLUMN] = S.status_column(pw, sid, gs, gsis_of=_gsis_of().get)
    return pw, False


def test_injury_status_agrees_with_injury_flag():
    pw, _ = _pw()
    if pw is None:
        return
    bad = S.disagreements(pw)
    assert bad.empty, f"{len(bad)} rows disagree: {bad[['Player', 'Year', 'Week', 'Injury?', S.COLUMN]].head(10).values.tolist()}"
    # Injury? itself unchanged: values still True / False, completed-season counts pinned
    assert set(pw["Injury?"].str.strip()) <= {"True", "False"}, set(pw["Injury?"])
    got = pw[pw["Injury?"] == "True"].groupby(pd.to_numeric(pw["Year"])).size().to_dict()
    for yr, n in _INJURED_BY_SEASON.items():
        assert got.get(yr) == n, f"{yr}: {got.get(yr)} Injury? weeks, pinned {n}"


def test_ir_is_exactly_the_reserve_weeks():
    pw, _ = _pw()
    if pw is None:
        return
    sid, gs = _reserve()
    if not sid:
        print("  .cache weekly rosters absent")
        return
    gsis = _gsis_of()
    yr = pd.to_numeric(pw["Year"]).astype(int)
    wk = pd.to_numeric(pw["Week"]).astype(int)
    # completed seasons only: the live season's committed rosters can trail the build's
    done = yr <= max(_INJURED_BY_SEASON)
    wrong = []
    for p, y, w, lab in zip(pw["Player ID"][done], yr[done], wk[done], pw[S.COLUMN][done]):
        if lab == S.HEALTHY:
            continue
        p = S._clean_id(p)
        res = (p, y, w) in sid or (S._clean_id(gsis.get(p)), y, w) in gs
        if (lab == S.IR) != res:
            wrong.append((p, y, w, lab))
    assert not wrong, f"{len(wrong)} Out/IR rows disagree with the rosters: {wrong[:10]}"
    n_ir = int((pw[S.COLUMN][done] == S.IR).sum())
    assert n_ir > 1500, n_ir      # ~1,750 IR weeks 2020-25; near zero = the id join broke


def test_spot_checks():
    pw, _ = _pw()
    if pw is None:
        return
    for name, y, w, want in [("Deebo Samuel", "2020", "1", "IR"), ("Brandon Aiyuk", "2020", "1", "Out")]:
        r = pw[pw.Player.str.startswith(name) & (pw.Year == y) & (pw.Week == w)]
        assert r[S.COLUMN].tolist() == [want], (name, r[S.COLUMN].tolist())


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
