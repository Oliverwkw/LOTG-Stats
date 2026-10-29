"""Stable player keys on every export sheet that names a player.

Names are not keys: Sleeper re-spells them (34 players gained Jr./Sr./II on
2026-10-22) and `full_name` is not unique (Josh Allen QB/G, Lamar Jackson
QB/CB, ...). The build already tracks each player by his Sleeper `player_id`;
this module puts that id beside every player name on the way out, so a reader
(or `fast.py` / `inquire.py`) can join by id instead of by name.

Every id is the one the build itself used for that row — nothing is re-derived
from a name here. Columns, all TEXT (an id is a label, never a number):

  * `Player ID` — player_week / player_year / player_all_time / player_additions.
  * `Reference player ID` — player_week, beside `Reference player name`; blank
    when the reference is an empty slot ("Empty slot", Sleeper id "0").
  * `Player Added ID` / `Player Dropped ID` — add_drops.
  * `Player Picked ID` — both pick sheets.
  * `Player IDs received` / `Player IDs sent` — trades: the player ids on each
    side, "; "-joined in the order the players are listed in `Assets received`
    / `Assets sent` (picks and FAAB carry no id, so they are not in the list).
  * `GSIS ID` — player_all_time: the nflverse gsis_id the build matched the
    player to (Sleeper -> DynastyProcess -> nflverse, with the last-name
    correction), blank when there is none.

2020 rows come from the ESPN backfill, whose players the build already keys by
Sleeper id (DynastyProcess `espn_id` bridge in `espn_2020`).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd

PLAYER_ID = "Player ID"
REFERENCE_ID = "Reference player ID"
ADDED_ID = "Player Added ID"
DROPPED_ID = "Player Dropped ID"
PICKED_ID = "Player Picked ID"
RECEIVED_IDS = "Player IDs received"
SENT_IDS = "Player IDs sent"
GSIS_ID = "GSIS ID"

ID_COLUMNS = (PLAYER_ID, REFERENCE_ID, ADDED_ID, DROPPED_ID, PICKED_ID,
              RECEIVED_IDS, SENT_IDS, GSIS_ID)

# Sleeper's id for an empty lineup slot.
EMPTY_SLOT_ID = "0"

_PLAYER_SHEETS = {"Player-Week", "Player-year", "Player-all-time", "player_additions"}
_PICK_SHEETS = {"non_rookie_picks", "rookie_picks"}


def clean_id(v: Any) -> Optional[str]:
    """An id as a bare string ('7564', never '7564.0'); None when missing."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if s.lower() in ("", "nan", "none", "n/a", "<na>"):
        return None
    return s


def join_ids(ids: Any) -> Optional[str]:
    """A list of ids -> '; '-joined text (None for an empty or missing list)."""
    if ids is None or isinstance(ids, float):
        return None
    if isinstance(ids, str):
        ids = [ids]
    out = [c for c in (clean_id(i) for i in ids) if c]
    return "; ".join(out) if out else None


def split_ids(cell: Any) -> List[str]:
    """Inverse of join_ids for a read-back CSV cell."""
    s = clean_id(cell)
    return [t.strip() for t in s.split(";") if t.strip()] if s else []


def _col(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in frame.columns:
        return frame[name]
    return pd.Series([None] * len(frame), index=frame.index, dtype=object)


def add_export_ids(plan_key: str, frame: pd.DataFrame,
                   gsis_of: Optional[Callable[[str], Optional[str]]] = None) -> pd.DataFrame:
    """Return `frame` with the id columns for its sheet filled from the build's
    internal id columns. Existing columns are left untouched."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame
    out = frame.copy()
    if plan_key in _PLAYER_SHEETS and PLAYER_ID in out.columns:
        out[PLAYER_ID] = out[PLAYER_ID].map(clean_id).astype(object)
    if plan_key == "Player-Week":
        ref = _col(out, REFERENCE_ID).map(clean_id)
        out[REFERENCE_ID] = ref.where(ref.ne(EMPTY_SLOT_ID), None).astype(object)
    if plan_key == "Player-all-time" and gsis_of is not None and PLAYER_ID in out.columns:
        out[GSIS_ID] = out[PLAYER_ID].map(lambda p: clean_id(gsis_of(p)) if p else None).astype(object)
    if plan_key == "add_drops":
        out[ADDED_ID] = _col(out, "_added_pid").map(clean_id).astype(object)
        out[DROPPED_ID] = _col(out, "_dropped_pid").map(clean_id).astype(object)
    if plan_key in _PICK_SHEETS:
        out[PICKED_ID] = _col(out, "_player_id").map(clean_id).astype(object)
    if plan_key == "trades":
        out[RECEIVED_IDS] = _col(out, "_recv_player_ids").map(join_ids).astype(object)
        out[SENT_IDS] = _col(out, "_drop_player_ids").map(join_ids).astype(object)
    return out


# (sheet file stem, name column, id column, joined?) — every name/id pair.
PAIRS = (
    ("player_week", "Player", PLAYER_ID, False),
    ("player_week", "Reference player name", REFERENCE_ID, False),
    ("player_year", "Player", PLAYER_ID, False),
    ("player_all_time", "Player", PLAYER_ID, False),
    ("player_additions", "Player", PLAYER_ID, False),
    ("add_drops", "Player Added", ADDED_ID, False),
    ("add_drops", "Player Dropped", DROPPED_ID, False),
    ("non_rookie_picks", "Player Picked", PICKED_ID, False),
    ("rookie_picks", "Player Picked", PICKED_ID, False),
    ("trades", "Assets received", RECEIVED_IDS, True),
    ("trades", "Assets sent", SENT_IDS, True),
)


def _is_named(v: Any) -> bool:
    s = clean_id(v)
    return bool(s) and s != "Empty slot"


def unmapped_rows(sheets: Dict[str, pd.DataFrame],
                  is_player: Callable[[str], bool] = lambda s: True) -> pd.DataFrame:
    """Every row that names a player but carries no id for him (and the reverse:
    an id with no name). `sheets` maps file stem -> frame as read from the CSV.
    For trades, a cell's player names are its assets that `is_player` accepts
    (picks / FAAB are not players); the id list must be the same length."""
    rows: List[Dict[str, Any]] = []
    for stem, name_col, id_col, joined in PAIRS:
        df = sheets.get(stem)
        if df is None or name_col not in df.columns:
            continue
        ids = _col(df, id_col)
        for i, (nm, pid) in enumerate(zip(df[name_col], ids)):
            if joined:
                names = [a.strip() for a in str(nm).split(";")] if _is_named(nm) else []
                names = [a for a in names if a and is_player(a)]
                n_ids = len(split_ids(pid))
                if len(names) != n_ids:
                    rows.append({"Sheet": stem, "Column": name_col, "Row": i + 2,
                                 "Name": nm, "ID": pid,
                                 "Problem": f"{len(names)} player name(s), {n_ids} id(s)"})
                continue
            has_n, has_i = _is_named(nm), bool(clean_id(pid))
            if has_n != has_i:
                rows.append({"Sheet": stem, "Column": name_col, "Row": i + 2,
                             "Name": nm, "ID": pid,
                             "Problem": "name without id" if has_n else "id without name"})
    return pd.DataFrame(rows, columns=["Sheet", "Column", "Row", "Name", "ID", "Problem"])


def name_map(frames: Iterable[pd.DataFrame], name_col: str = "Player",
             id_col: str = PLAYER_ID) -> Dict[str, str]:
    """id -> the name the exports print for it (last seen wins)."""
    out: Dict[str, str] = {}
    for df in frames:
        if df is None or name_col not in df.columns or id_col not in df.columns:
            continue
        for nm, pid in zip(df[name_col], df[id_col]):
            p = clean_id(pid)
            if p and _is_named(nm):
                out[p] = str(nm)
    return out
