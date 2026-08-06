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
    # Test-time exports dir: $LOTG_EXPORTS or the default. Deliberately does NOT
    # read sys.argv — under pytest sys.argv holds pytest's own args ("tests/",
    # "-v"), which made this guard silently SKIP in CI. The CLI path below
    # handles an explicit dir argument.
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
        # Sum the destination by key too (don't set_index): the league has
        # distinct NFL players who share a name (two "Tyler Johnson", two "Justin
        # Jefferson"), so player_all/team_all can hold multiple rows per name.
        # Indexing by name would compare a per-name year-sum against ONE of the
        # colliding rows; summing both sides by name keeps the all-time = Σ-years
        # invariant well-defined under collisions.
        b = dst.groupby(dstkey)[col].apply(lambda s: _num(s).sum())
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

    # Positional starter-scoring split. Every startable slot in this league is a
    # QB/WR/RB/TE, so the four "Points from <pos>" columns must reconstruct PF
    # exactly, and the four shares must sum to 1 on every scoring row. Rolls up
    # week -> year -> all-time like any other counting stat. Guarded on presence
    # so the check skips against a build predating the columns.
    _pos_pts = ["Points from QBs", "Points from WRs", "Points from TEs", "Points from RBs"]
    _pos_pct = ["% of points from QBs", "% of points from WRs", "% of points from TEs",
                "% of points from RBs"]
    if all(c in tw.columns for c in _pos_pts + _pos_pct):
        # The one legitimate gap is the league's +5 semifinal home-field bonus,
        # which lives in PF but belongs to no player, so it can't be attributed
        # to a position. It goes only to the higher seed, so a semifinal row is
        # allowed a gap of 0 OR 5; every other row must match PF to the cent.
        split = sum(_num(tw[c]).fillna(0) for c in _pos_pts)
        gap = (_num(tw["PF"]).fillna(0) - split).abs()
        is_semi = tw["Week Name"].astype(str).str.strip().eq("Semifinal")
        d = gap.where(~is_semi, pd.concat([gap, (gap - 5.0).abs()], axis=1).min(axis=1))
        out.append(("team_week Σ positional starter points = PF (± semifinal bonus)",
                    bool(d.max() <= 0.05), f"max Δ {d.max():.3f}", False))

        # Shares sum to 1 wherever the week actually scored (a 0-point lineup
        # renders all four as N/A, which drops out of _num).
        shares = sum(_num(tw[c]) for c in _pos_pct)
        shares = shares.dropna()
        d = (shares - 1.0).abs()
        out.append(("team_week positional shares sum to 1",
                    bool(shares.empty or d.max() <= 0.001), f"max Δ {d.max():.4f}", False))

        for col in _pos_pts:
            g = tw.groupby(["Team", "Year"])[col].apply(lambda s: _num(s).sum()).reset_index()
            m = ty.merge(g, on=["Team", "Year"], suffixes=("_y", "_w"))
            d = (_num(m[f"{col}_y"]) - _num(m[f"{col}_w"])).abs()
            out.append((f"team_year {col} = Σ team_week", bool(d.max() <= 0.05),
                        f"max Δ {d.max():.3f}", False))
            cmp_group(ty, "Team", col, ta, "Team", 0.05, f"team_all {col} = Σ team_year")

    # player_all #tx = Σ player_year. Phase 12 finding #1 (now FIXED): player_year
    # is padded with a row for every (player, season) that has real transaction
    # activity but no weekly appearance — offseason-only moves (bucketed under the
    # prior fantasy year) and initial-roster vets dropped with no recorded 'add'.
    cmp_group(py, "Player", "Number of transactions", pa, "Player", 0.5,
              "player_all #tx = Σ player_year", known=False)
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
    _cli_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else _exports_dir()
    frames = _load(_cli_dir)
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
