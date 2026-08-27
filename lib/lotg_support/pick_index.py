"""`PH#N` -> pick-sheet row: the map that survives the picks split.

The picks frame is built as ONE table and written as TWO sheets
(`non_rookie_picks` + `rookie_picks`, see `src/pick_history.py`). Every `PH#N`
cross-sheet reference is that frame's positional index + 1, and the two sheets
interleave in the frame — the vet draft, then the rookie drafts, then the
startup, then late-added picks — so `N` indexes NEITHER sheet on its own and the
order cannot be recovered from the two CSVs alone.

The build already computes the mapping for the xlsx hyperlink resolver. This
module persists it next to the other build dumps as `exports/raw/pick_ref_index.csv`
and reads it back, so everything downstream of the export — the weekly health
audit's link check, the pick-chain guard, an inquiry that spans both drafts —
can still follow a `PH#N` to the row it names, and can still reconstruct the
frame in build order.

Readers must tolerate its absence: an `exports/` written before this map existed
returns None rather than a wrong answer.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

RAW_SUBDIR = "raw"
FILE_NAME = "pick_ref_index.csv"

# The two sheets the frame is written as, in sheet order.
SHEETS: Tuple[str, ...] = ("non_rookie_picks", "rookie_picks")

_FIELDS = ("ref", "sheet", "row")


def index_path(exports_dir) -> Path:
    """Where the map lives under an exports tree."""
    return Path(exports_dir) / RAW_SUBDIR / FILE_NAME


def write_index(exports_dir, ref_target: Mapping[int, Tuple[str, int]]) -> Optional[Path]:
    """Persist `{PH ref -> (sheet, xlsx row)}`. Returns the path, or None.

    `ref_target` is the map the writer already builds for the hyperlink
    resolver, where the row is an XLSX row (the CSV data row + 1 for the header
    + 1 for 1-basing). It is converted to a 0-based CSV row on the way out, so a
    reader can index a DataFrame or a `csv.DictReader` list directly.
    """
    if not ref_target:
        return None
    path = index_path(exports_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_FIELDS)
        for ref in sorted(ref_target):
            sheet, xlsx_row = ref_target[ref]
            writer.writerow([int(ref), str(sheet), int(xlsx_row) - 2])
    return path


def load_index(exports_dir) -> Optional[List[Tuple[str, int]]]:
    """`[(sheet, 0-based row)]` in `PH#` order — element `i` is `PH#{i+1}`.

    None when the file is absent (an `exports/` from before the split), or when
    the refs it holds are not the complete run `1..len` — a gapped map cannot be
    indexed positionally, and guessing at the gaps is how a link check starts
    silently comparing the wrong rows.
    """
    path = index_path(exports_dir)
    if not path.exists():
        return None
    rows: Dict[int, Tuple[str, int]] = {}
    try:
        with path.open() as fh:
            for rec in csv.DictReader(fh):
                rows[int(rec["ref"])] = (str(rec["sheet"]).strip(), int(rec["row"]))
    except (OSError, TypeError, ValueError, KeyError):
        return None
    if not rows or sorted(rows) != list(range(1, len(rows) + 1)):
        return None
    return [rows[i] for i in range(1, len(rows) + 1)]


def order_rows(exports_dir, sheet_rows: Mapping[str, Sequence]) -> Optional[list]:
    """The picks frame in BUILD order, from each sheet's rows in sheet order.

    `sheet_rows` maps sheet name -> that sheet's rows (anything indexable — a
    `csv.DictReader` list, a list of dicts). Returns None when the map is
    missing or does not fit the sheets it is being applied to, which is the
    caller's cue to report rather than to improvise.
    """
    index = load_index(exports_dir)
    if index is None:
        return None
    out = []
    for sheet, row in index:
        rows = sheet_rows.get(sheet)
        if rows is None or not (0 <= row < len(rows)):
            return None
        out.append(rows[row])
    return out


def order_frame(exports_dir, frames: Mapping[str, object]):
    """pandas variant of `order_rows`: one frame in build order.

    Carries a `_sheet` column so a caller that followed a `PH#N` here can still
    say which sheet the row actually lives on. Returns None on the same terms as
    `order_rows`.
    """
    import pandas as pd

    index = load_index(exports_dir)
    if index is None:
        return None
    positions: Dict[str, List[int]] = {}
    slots: Dict[str, List[int]] = {}
    for slot, (sheet, row) in enumerate(index):
        positions.setdefault(sheet, []).append(row)
        slots.setdefault(sheet, []).append(slot)
    parts = []
    for sheet, rows in positions.items():
        df = frames.get(sheet)
        if df is None or getattr(df, "empty", True):
            return None
        if min(rows) < 0 or max(rows) >= len(df):
            return None
        take = df.iloc[rows].copy()
        take["_sheet"] = sheet
        take.index = slots[sheet]
        parts.append(take)
    if not parts:
        return None
    return pd.concat(parts).sort_index().reset_index(drop=True)
