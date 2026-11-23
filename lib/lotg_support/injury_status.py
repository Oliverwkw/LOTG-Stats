"""player_week `Injury status`: Healthy / Out / IR, beside `Injury?`.

`Injury?` (True / False) is unchanged and is still what every stat reads. The
build adds `Injury status` when player_week is written, from that same flag:

    Injury? False                                        -> "Healthy"
    Injury? True, nflverse weekly roster status RES      -> "IR"   (IR / PUP / NFI that week)
    Injury? True, anything else                          -> "Out"

So Out or IR <=> Injury? True, row for row (`disagreements()` is the guard:
lotg_support.sanity logs it at build time, tests/test_sanity_ranges.py fails on it).

The reserve join is by id, never by name: nflverse's `sleeper_id` first, then its
`gsis_id` through the build's own Sleeper -> gsis bridge.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional, Set, Tuple

import pandas as pd

HEALTHY, OUT, IR = "Healthy", "Out", "IR"
LABELS = (HEALTHY, OUT, IR)
FLAG = "Injury?"
COLUMN = "Injury status"

_TRUE = frozenset({"true", "t", "yes", "y", "1", "1.0"})


def flag_on(v: Any) -> bool:
    """`Injury?` truthiness for bools or their CSV text; NaN / blank / N/A = False."""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return False if pd.isna(v) else bool(v)
    return str(v).strip().lower() in _TRUE


def _clean_id(v: Any) -> str:
    s = str(v).strip() if v is not None else ""
    if not s or s.lower() in ("nan", "none", "<na>"):
        return ""
    return s[:-2] if s.endswith(".0") else s


def reserve_keys(rosters: pd.DataFrame, season: Optional[int] = None) -> Tuple[Set[Tuple[str, int, int]],
                                                                              Set[Tuple[str, int, int]]]:
    """({(sleeper_id, season, week)}, {(gsis_id, season, week)}) for every row of an
    nflverse weekly-rosters frame with status RES."""
    by_sid: Set[Tuple[str, int, int]] = set()
    by_gsis: Set[Tuple[str, int, int]] = set()
    if rosters is None or rosters.empty or "status" not in rosters.columns or "week" not in rosters.columns:
        return by_sid, by_gsis
    d = rosters[rosters["status"].astype(str).str.strip().str.upper() == "RES"]
    seasons = (pd.to_numeric(d["season"], errors="coerce") if "season" in d.columns
               else pd.Series(season, index=d.index, dtype="float"))
    weeks = pd.to_numeric(d["week"], errors="coerce")
    sids = d["sleeper_id"] if "sleeper_id" in d.columns else pd.Series("", index=d.index)
    gsis = d["gsis_id"] if "gsis_id" in d.columns else pd.Series("", index=d.index)
    for sid, gs, y, w in zip(sids, gsis, seasons, weeks):
        if pd.isna(y) or pd.isna(w):
            continue
        y, w = int(y), int(w)
        if (s := _clean_id(sid)):
            by_sid.add((s, y, w))
        if (g := _clean_id(gs)):
            by_gsis.add((g, y, w))
    return by_sid, by_gsis


def status_column(pw: pd.DataFrame, by_sid: Iterable[Tuple[str, int, int]] = (),
                  by_gsis: Iterable[Tuple[str, int, int]] = (),
                  gsis_of: Optional[Callable[[str], Optional[str]]] = None,
                  id_col: str = "Player ID") -> pd.Series:
    """Healthy / Out / IR per row of `pw`, from its `Injury?` and the reserve keys."""
    by_sid, by_gsis = set(by_sid), set(by_gsis)
    inj = pw[FLAG].map(flag_on)
    yr = pd.to_numeric(pw.get("Year"), errors="coerce")
    wk = pd.to_numeric(pw.get("Week"), errors="coerce")
    ids = pw[id_col] if id_col in pw.columns else pd.Series("", index=pw.index)
    out = []
    for is_inj, pid, y, w in zip(inj, ids, yr, wk):
        if not is_inj:
            out.append(HEALTHY)
            continue
        on_res = False
        if pd.notna(y) and pd.notna(w):
            p = _clean_id(pid)
            key = (int(y), int(w))
            if p and (p, *key) in by_sid:
                on_res = True
            elif p and gsis_of is not None:
                g = _clean_id(gsis_of(p))
                on_res = bool(g) and (g, *key) in by_gsis
        out.append(IR if on_res else OUT)
    return pd.Series(out, index=pw.index, dtype=object)


def disagreements(pw: pd.DataFrame) -> pd.DataFrame:
    """Rows where `Injury status` does not match `Injury?` (Out/IR <=> True, Healthy
    <=> False), or holds anything but the three labels. Empty = they agree."""
    if pw is None or pw.empty or COLUMN not in pw.columns or FLAG not in pw.columns:
        return pw.iloc[0:0] if isinstance(pw, pd.DataFrame) else pd.DataFrame()
    st = pw[COLUMN].astype(str).str.strip()
    inj = pw[FLAG].map(flag_on)
    bad = ~st.isin(LABELS) | (st.isin((OUT, IR)) != inj)
    return pw[bad]
