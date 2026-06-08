"""Phase 12 Part 1: cross-sheet reconciliation guard.

Rollups must agree across weekly -> year -> all-time and player <-> team. Reads
the built CSVs from a directory (default: <repo>/exports, or $LOTG_EXPORTS, or
argv[1]); SKIPS cleanly when no build is present, so it's safe in any checkout.

Run: python tests/test_cross_sheet_reconciliation.py [exports_dir]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent


def _exports_dir() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    return Path(os.environ.get("LOTG_EXPORTS", _ROOT / "exports"))


def _num(s):
    return pd.to_numeric(s.replace({"N/A": None, "In Progress": None, "": None}), errors="coerce")


def _load(d: Path):
    need = ["player_week", "player_year", "player_all_time", "team_week", "team_year", "team_all_time"]
    if not all((d / f"{n}.csv").exists() for n in need):
        return None
    return {n: pd.read_csv(d / f"{n}.csv", low_memory=False) for n in need}


def reconcile(frames) -> list:
    """Return a list of (name, ok, detail). KNOWN-OPEN findings are flagged."""
    pw, py, pa = frames["player_week"], frames["player_year"], frames["player_all_time"]
    tw, ty, ta = frames["team_week"], frames["team_year"], frames["team_all_time"]
    out = []

    def cmp_group(src, key, col, dst, dstkey, tol, name, known=False):
        a = src.groupby(key)[col].apply(lambda s: _num(s).sum())
        b = dst.set_index(dstkey)[col].pipe(_num)
        j = a.align(b, join="inner")
        d = (j[0] - j[1]).abs()
        out.append((name, bool(d.max() <= tol), f"max Δ {d.max():.3f}, {(d > tol).sum()} off", known))

    cmp_group(py, "Player", "Points", pa, "Player", 0.05, "player_all Points = Σ player_year")
    cmp_group(ty, "Team", "Points", ta, "Team", 0.05, "team_all Points = Σ team_year")
    cmp_group(py, "Player", "Times as Player of the week?", pa, "Player", 0.5, "player_all Times PotW = Σ player_year")
    cmp_group(ty, "Team", "Number of transactions", ta, "Team", 0.5, "team_all #tx = Σ team_year")

    # player_year Points = Σ player_week Points
    g = pw.groupby(["Player", "Year"])["Points"].apply(lambda s: _num(s).sum()).reset_index()
    m = py.merge(g, on=["Player", "Year"], suffixes=("_y", "_w"))
    d = (_num(m["Points_y"]) - _num(m["Points_w"])).abs()
    out.append(("player_year Points = Σ player_week", bool(d.max() <= 0.05), f"max Δ {d.max():.3f}", False))

    # team_year Points = Σ team_week PF
    g = tw.groupby(["Team", "Year"])["PF"].apply(lambda s: _num(s).sum()).reset_index()
    m = ty.merge(g, on=["Team", "Year"])
    d = (_num(m["Points"]) - _num(m["PF"])).abs()
    out.append(("team_year Points = Σ team_week PF", bool(d.max() <= 0.5), f"max Δ {d.max():.2f}", False))

    # Times Highest score? = Σ weekly
    g = tw.groupby(["Team", "Year"])["Highest score?"].apply(lambda s: _num(s).fillna(0).sum()).reset_index()
    m = ty.merge(g, on=["Team", "Year"])
    d = (_num(m["Times Highest score?"]) - _num(m["Highest score?"])).abs()
    out.append(("Times Highest score? = Σ weekly", bool(d.max() <= 0.5), f"max Δ {d.max():.0f}", False))

    # KNOWN-OPEN: player_all #tx = Σ player_year — fails for players whose only
    # activity in a not-yet-played season is off-season transactions (no
    # player_year row). Phase 12 finding #1; flip `known` to False once fixed.
    cmp_group(py, "Player", "Number of transactions", pa, "Player", 0.5,
              "player_all #tx = Σ player_year", known=True)
    return out


def test_cross_sheet_reconciliation():
    frames = _load(_exports_dir())
    if frames is None:
        import pytest  # type: ignore
        pytest.skip("no built exports present")
    results = reconcile(frames)
    hard_fail = [name for (name, ok, _d, known) in results if not ok and not known]
    assert not hard_fail, "reconciliation broken: " + "; ".join(hard_fail)


if __name__ == "__main__":
    frames = _load(_exports_dir())
    if frames is None:
        print("No built exports found; skipping.")
        sys.exit(0)
    bad = 0
    for name, ok, detail, known in reconcile(frames):
        tag = "PASS" if ok else ("KNOWN-OPEN" if known else "FAIL")
        if not ok and not known:
            bad += 1
        print(f"  {tag:11} {name}  ({detail})")
    sys.exit(1 if bad else 0)
