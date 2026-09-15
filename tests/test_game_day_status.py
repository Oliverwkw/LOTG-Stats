"""data/game_day_status.csv: who dressed and never played, 2020-2025.

After the snap-count union (test_injury_gap_fill.py), the `Injury?` weeks still
left on ACTIVE-roster players with 0 snaps were looked up one by one in team
inactive lists and game reports. 208 of 215 dressed and sat — backup
quarterbacks, depth backs and receivers — and are not injuries; 7 were genuinely
out (inactive, reserve list, or Rome Odunze 2025 wk15, active but ruled out in
pregame warmups). See lotg_support/game_day_status.py for the statuses.

The same PR bridges snap counts through DynastyProcess's pfr_id when the weekly
rosters leave it blank, which recovers 31 weeks of players who did take the
field (Trey McBride 2022 wks 2-9, Khalil Shakir 2022, Jalen Tolbert 2022...).

Run: PYTHONPATH=src:lib python tests/test_game_day_status.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT / "lib", _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lotg_support import game_day_status as gds  # noqa: E402

_FILE = _ROOT / "data" / "game_day_status.csv"
_EXPORTS = _ROOT / "exports"
# The INFO line the build logs once it has read the file — how a data test knows
# the committed exports were built with it.
_MARKER = "game_day_status season="


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


def test_the_file_is_well_formed():
    rows = gds.read_rows(_FILE)
    assert rows, "data/game_day_status.csv is missing or empty"
    problems = gds.validate(rows)
    assert not problems, "\n".join(problems[:20])


def test_validate_catches_what_it_should():
    good = {"player_name": "A", "gsis_id": "00-0012345", "season": "2025", "week": "3",
            "nfl_team": "IND", "status": "active", "detail": "QB2",
            "source": "https://example.com/x"}
    assert gds.validate([good]) == []
    for bad, needle in (
        (dict(good, season="2026"), "belongs to the tracker"),
        (dict(good, status="questionable"), "unknown status"),
        (dict(good, source=""), "no source"),
        (dict(good, gsis_id="AAA123456"), "not a gsis id"),
        (dict(good, week="19"), "regular-season week"),
    ):
        got = gds.validate([bad])
        assert any(needle in p for p in got), (bad, got)
    assert any("duplicate" in p for p in gds.validate([good, dict(good)]))


def test_only_active_rows_veto_and_never_in_a_tracker_season():
    import csv
    rows = [
        ("Leonard", "00-0040206", 2025, 9, "active"),
        ("Odunze", "00-0039919", 2025, 15, "ruled_out_pregame"),
        ("Rypien", "00-0035992", 2025, 15, "emergency_qb3"),
        ("Stray", "00-0099999", 2026, 1, "active"),
    ]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "g.csv"
        with p.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(gds.GAME_DAY_STATUS_COLUMNS)
            for name, g, s, wk, st in rows:
                w.writerow([name, g, s, wk, "X", st, "d", "https://x"])
        assert gds.dressed_by_week(p, 2025) == {9: {"00-0040206"}}
        assert gds.dressed_by_week(p, 2026) == {}, "the tracker owns 2026"
        assert gds.dressed_by_week(p, 2024) == {}
        assert gds.dressed_by_week(Path(d) / "absent.csv", 2025) == {}


def test_the_build_wires_it():
    """Asserted on the source: the veto lives inside build_all()."""
    src = (_ROOT / "src" / "lotg.py").read_text()
    assert '"game_day_status.csv"' in src, "the build does not read the file"
    assert "(not dressed)" in src, "the injury default no longer honours a dressed week"
    assert _MARKER in src, "the build no longer logs the read"
    assert 'dp_ids[["pfr_id", "gsis_id"]]' in src, \
        "the DynastyProcess pfr_id fallback for the snap bridge is gone"


def test_the_exports_honour_every_row():
    """active -> Injury? False; any other status -> Injury? True. Every row must
    match a player_week row, or the file has drifted from the sheets."""
    try:
        import pandas as pd
    except ImportError:
        return _skip("pandas not installed")
    pw_path = _EXPORTS / "player_week.csv"
    if not pw_path.exists():
        return _skip("no exports/player_week.csv")
    try:
        built_with = _MARKER in (_EXPORTS / "raw" / "build_debug.log").read_text(errors="replace")
    except Exception:
        built_with = False
    if not built_with:
        return _skip(f"the committed exports predate the file (no {_MARKER!r} in "
                     "exports/raw/build_debug.log); asserts from the first post-merge build")

    pw = pd.read_csv(pw_path, low_memory=False, usecols=["Player", "Year", "Week", "Injury?"])
    pw["Injury?"] = pw["Injury?"].astype(str).str.lower().eq("true")
    by_key = pw.groupby(["Player", "Year", "Week"])["Injury?"].agg(list)
    unmatched, wrong = [], []
    for r in gds.read_rows(_FILE):
        key = (r["player_name"], int(r["season"]), int(r["week"]))
        if key not in by_key.index:
            unmatched.append(key)
            continue
        want = not gds.GAME_DAY_STATUSES[r["status"]]
        if any(v != want for v in by_key.loc[key]):
            wrong.append((*key, r["status"], by_key.loc[key]))
    assert not unmatched, f"{len(unmatched)} row(s) match no player_week row: {unmatched[:10]}"
    assert not wrong, (f"{len(wrong)} player-week(s) disagree with their researched "
                       f"game-day status: {wrong[:10]}")


def _run_all():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
