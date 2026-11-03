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
  * `Player IDs retained now` / `… traded away` / `… dropped to FA` /
    `… in return from trades` / `… in additional assets traded away` /
    `… in full return chain` — trades: the same for each chain-of-custody
    cell, in the order (and with the de-duplication) that cell uses.
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

# trades' chain-of-custody cells -> (the build's internal key, the id column).
CHAIN_IDS = {
    "Assets retained now": ("retained", "Player IDs retained now"),
    "Assets traded away": ("traded", "Player IDs traded away"),
    "Assets dropped to FA": ("fa", "Player IDs dropped to FA"),
    "Return from trades": ("return", "Player IDs in return from trades"),
    "Additional assets traded away in those deals":
        ("additional", "Player IDs in additional assets traded away"),
    "Return from trades of trades...of trades. Keep going until present day":
        ("full", "Player IDs in full return chain"),
}
CHAIN_ID_COLUMNS = tuple(c for _k, c in CHAIN_IDS.values())

ID_COLUMNS = (PLAYER_ID, REFERENCE_ID, ADDED_ID, DROPPED_ID, PICKED_ID,
              RECEIVED_IDS, SENT_IDS, GSIS_ID) + CHAIN_ID_COLUMNS

# Sleeper's id for an empty lineup slot.
EMPTY_SLOT_ID = "0"

_PLAYER_SHEETS = {"Player-Week", "Player-year", "Player-all-time", "player_additions"}
_PICK_SHEETS = {"non_rookie_picks", "rookie_picks"}


def chain_player_ids(pairs: Iterable[Any], dedup: bool) -> List[str]:
    """(display, asset key) pairs of one chain cell -> its players' ids, in
    cell order. A key is ("player", pid) or ("pick", meta). `dedup` mirrors a
    cell written with dict.fromkeys(displays): a repeated display is skipped."""
    seen, out = set(), []
    for disp, key in pairs:
        if dedup:
            if disp in seen:
                continue
            seen.add(disp)
        if key and key[0] == "player" and clean_id(key[1]):
            out.append(clean_id(key[1]))
    return out


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


def _obj(frame: pd.DataFrame, values: Iterable[Any]) -> pd.Series:
    """An object column holding real None for a blank. (Series.map(...).astype(
    object) leaves NaN under pandas 3's string dtype, which CI runs.)"""
    return pd.Series(list(values), index=frame.index, dtype=object)


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
        out[PLAYER_ID] = _obj(out, map(clean_id, out[PLAYER_ID]))
    if plan_key == "Player-Week":
        out[REFERENCE_ID] = _obj(out, (None if r == EMPTY_SLOT_ID else r
                                       for r in map(clean_id, _col(out, REFERENCE_ID))))
    if plan_key == "Player-all-time" and gsis_of is not None and PLAYER_ID in out.columns:
        out[GSIS_ID] = _obj(out, (clean_id(gsis_of(p)) if p else None for p in out[PLAYER_ID]))
    if plan_key == "add_drops":
        out[ADDED_ID] = _obj(out, map(clean_id, _col(out, "_added_pid")))
        out[DROPPED_ID] = _obj(out, map(clean_id, _col(out, "_dropped_pid")))
    if plan_key in _PICK_SHEETS:
        out[PICKED_ID] = _obj(out, map(clean_id, _col(out, "_player_id")))
    if plan_key == "trades":
        out[RECEIVED_IDS] = _obj(out, map(join_ids, _col(out, "_recv_player_ids")))
        out[SENT_IDS] = _obj(out, map(join_ids, _col(out, "_drop_player_ids")))
        for _cell, (key, id_col) in CHAIN_IDS.items():
            out[id_col] = _obj(out, map(join_ids, _col(out, f"_chain_ids_{key}")))
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
    *(("trades", cell, id_col, True) for cell, (_k, id_col) in CHAIN_IDS.items()),
)


# Cells that name no player: an empty lineup slot, an unmade (future) pick.
_NOT_A_PLAYER = {"empty slot", "unknown"}


def _is_named(v: Any) -> bool:
    s = clean_id(v)
    return bool(s) and s.lower() not in _NOT_A_PLAYER


def unmapped_rows(sheets: Dict[str, pd.DataFrame],
                  is_player: Callable[[str], bool] = lambda s: True) -> pd.DataFrame:
    """Every row that names a player but carries no id for him (and the reverse:
    an id with no name). `sheets` maps file stem -> frame as read from the CSV.
    For trades, a cell's player names are its assets that `is_player` accepts
    (picks / FAAB are not players); the id list must be the same length."""
    rows: List[Dict[str, Any]] = []
    for stem, name_col, id_col, joined in PAIRS:
        df = sheets.get(stem)
        # A sheet written before that id column existed has nothing to check.
        if df is None or name_col not in df.columns or id_col not in df.columns:
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
