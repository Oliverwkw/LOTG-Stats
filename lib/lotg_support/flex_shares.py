"""Who fills the flex slots: the positional split of FLX and SFLX starts.

`% of FLX WR` = of the starts a team (or the league) made in the regular flex
slots (FLX1, and FLX2 from 2024), the share that went to a WR; likewise RB and
TE. `% of SFLX QB / WR / RB / TE` is the same for the superflex slot. Shares are
pooled over the period (every flex start in the season, or all-time), not an
average of weekly shares, so a season with two flex slots weighs twice a season
with one — the same pooling as the `% of starters <tier>` columns.

Only FILLED slots count: an empty slot has no player_week row, so it is in
neither numerator nor denominator (it is counted in `Empty slots`). A dead start
(ruled out, scored 0) still names who the manager put in the slot, so it counts.
Position is player_week's `Position` (Sleeper's current dictionary), the same
position every other sheet shows for that player.

A period with no flex starts gets no row, so the caller's left merge leaves it
N/A rather than 0.
"""
from __future__ import annotations

import re
from typing import Sequence

import pandas as pd

SLOT_COL = "Position started in (if starter)"

FLX_POSITIONS = ("WR", "RB", "TE")
SFLX_POSITIONS = ("WR", "RB", "TE", "QB")

COLUMNS = ([f"% of FLX {p}" for p in FLX_POSITIONS]
           + [f"% of SFLX {p}" for p in SFLX_POSITIONS])

_FLX_RE = re.compile(r"^FLX\d*$")


def slot_kind(label) -> str | None:
    """'FLX' for a regular flex slot label (FLX1, FLX2, ...), 'SFLX' for the
    superflex, None for every other slot."""
    s = str(label or "").strip().upper()
    if s == "SFLX":
        return "SFLX"
    if _FLX_RE.match(s):
        return "FLX"
    return None


def flex_starts(pw: pd.DataFrame) -> pd.DataFrame:
    """player_week's starts in a flex or superflex slot, with a `_kind` column."""
    need = {"Starter/Bench", SLOT_COL, "Position"}
    if pw is None or pw.empty or not need.issubset(pw.columns):
        return pd.DataFrame(columns=list(pw.columns if pw is not None else []) + ["_kind"])
    st = pw[pw["Starter/Bench"].astype(str) == "Starter"]
    kind = st[SLOT_COL].map(slot_kind)
    return st.assign(_kind=kind)[kind.notna()]


def flex_shares(pw: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """One row per `keys` group (keys=[] → one row for everything) with the
    seven COLUMNS, each 0-100 rounded to 1 place. A group with starts in only
    one kind of slot gets the other kind's columns as None."""
    keys = list(keys)
    fs = flex_starts(pw)
    if not fs.empty and keys:
        fs = fs.dropna(subset=keys)
    if fs.empty:
        return pd.DataFrame(columns=keys + COLUMNS)
    grp = fs.assign(_k=1)
    gkeys = keys or ["_k"]
    out = None
    for kind, positions in (("FLX", FLX_POSITIONS), ("SFLX", SFLX_POSITIONS)):
        part = grp[grp["_kind"] == kind]
        tot = part.groupby(gkeys).size()
        cols = {}
        for p in positions:
            n = part[part["Position"].astype(str) == p].groupby(gkeys).size().reindex(tot.index).fillna(0)
            cols[f"% of {kind} {p}"] = (n / tot * 100).round(1)
        frame = pd.DataFrame(cols, index=tot.index)
        out = frame if out is None else out.join(frame, how="outer")
    out = out.reset_index()
    if not keys:
        out = out.drop(columns="_k")
    out = out.astype(object).where(out.notna(), None)
    return out[keys + COLUMNS]
