"""What NFLverse changed underneath us between two builds.

NFLverse back-corrects completed seasons. A 2025 own-fumble recovery yard was
revised in July 2026 and moved a player's full-season points by 0.1; a routine
week brings a few hundred such touch-ups across first downs, fumble yardage and
position labels. Those are upstream data corrections, not our build failing to
reproduce — so the weekly health email must not report them as dataset
breakages. It should say what NFLverse changed and move on.

This module answers that by diffing the NFLverse cache files themselves: the
committed `.cache/nflverse_*.csv` (snapshotted before the audit build) against
the freshly downloaded ones (the audit build sets LOTG_REFRESH_EXTERNAL=1, so
every season re-downloads). The result carries both a human summary — "NFLverse
made N changes" — and the (player, season, week) coordinates of the revisions,
which `audit_weekly` uses to attribute its own Part 1 diffs.

Significance. Ordinary stat touch-ups are noise and stay informational. A
change is escalated to a real flag when it is STRUCTURAL (rows or columns
appearing / disappearing, a file that vanished) or when it moved more of our
own exports than `MAX_ATTRIBUTED_ROWS` — at which point "upstream corrected
some data" is no longer an adequate description of what happened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

# Candidate primary keys, most specific first. NFLverse files disagree on
# whether the player column is player_id (stats) or gsis_id (injuries), and
# whether rows are per-week or per-season.
_KEYS = (
    ("player_id", "season", "week"),
    ("gsis_id", "season", "week"),
    ("player_id", "season"),
    ("gsis_id", "season"),
    ("player_id",),
    ("gsis_id",),
)
# Where a file keeps the player's display name, best first.
_NAME_COLS = ("player_display_name", "full_name", "player_name", "display_name")
# Churn that is cosmetic rather than a data revision.
_IGNORE_COLS = frozenset({"headshot_url"})

# Above this many of OUR export rows attributed to upstream, the drift stops
# being routine housekeeping and gets flagged for a look.
MAX_ATTRIBUTED_ROWS = 500


@dataclass
class FileDrift:
    name: str
    changed_cells: int = 0
    changed_rows: int = 0
    added_rows: int = 0
    removed_rows: int = 0
    columns_added: List[str] = field(default_factory=list)
    columns_removed: List[str] = field(default_factory=list)
    top_columns: List[Tuple[str, int]] = field(default_factory=list)
    unkeyed: bool = False           # no usable primary key; counted coarsely

    @property
    def structural(self) -> bool:
        return bool(self.added_rows or self.removed_rows or self.columns_removed)


@dataclass
class Drift:
    files: List[FileDrift] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    new_files: List[str] = field(default_factory=list)
    # Coordinates of the revised rows, for attributing our own diffs.
    player_weeks: Set[Tuple[str, int, int]] = field(default_factory=set)
    player_seasons: Set[Tuple[str, int]] = field(default_factory=set)
    compared: bool = False          # False when there was nothing to diff

    @property
    def changed_cells(self) -> int:
        return sum(f.changed_cells for f in self.files)

    @property
    def changed_rows(self) -> int:
        return sum(f.changed_rows for f in self.files)

    @property
    def structural(self) -> bool:
        return bool(self.missing_files) or any(f.structural for f in self.files)

    @property
    def any_change(self) -> bool:
        return bool(self.changed_cells or self.structural or self.new_files)

    def summary(self) -> str:
        """The one-liner the email leads the NFLverse section with."""
        if not self.compared:
            return "No NFLverse snapshot to compare — upstream drift not measured this run."
        if not self.any_change:
            return "NFLverse made no changes to the data this build reads."
        bits = []
        if self.changed_cells:
            bits.append(f"{self.changed_cells} value(s) across {self.changed_rows} row(s)")
        added = sum(f.added_rows for f in self.files)
        removed = sum(f.removed_rows for f in self.files)
        if added:
            bits.append(f"{added} new row(s)")
        if removed:
            bits.append(f"{removed} row(s) withdrawn")
        cols_a = sum(len(f.columns_added) for f in self.files)
        cols_r = sum(len(f.columns_removed) for f in self.files)
        if cols_a:
            bits.append(f"{cols_a} new column(s)")
        if cols_r:
            bits.append(f"{cols_r} column(s) dropped")
        if self.new_files:
            bits.append(f"{len(self.new_files)} new file(s)")
        if self.missing_files:
            bits.append(f"{len(self.missing_files)} file(s) gone")
        n_files = len([f for f in self.files if f.changed_cells or f.structural])
        return (f"NFLverse made {', '.join(bits)}"
                + (f" across {n_files} file(s)." if n_files else "."))

    def detail_lines(self, limit: int = 8) -> List[str]:
        rows = sorted((f for f in self.files if f.changed_cells or f.structural),
                      key=lambda f: -(f.changed_cells + f.added_rows + f.removed_rows))
        out = []
        for f in rows[:limit]:
            bits = []
            if f.changed_cells:
                cols = ", ".join(f"{c} ({n})" for c, n in f.top_columns[:4])
                bits.append(f"{f.changed_cells} value(s) in {f.changed_rows} row(s)"
                            + (f" — {cols}" if cols else ""))
            if f.added_rows:
                bits.append(f"+{f.added_rows} row(s)")
            if f.removed_rows:
                bits.append(f"-{f.removed_rows} row(s)")
            if f.columns_added:
                bits.append(f"+{len(f.columns_added)} column(s)")
            if f.columns_removed:
                bits.append(f"dropped {', '.join(f.columns_removed[:4])}")
            out.append(f"{f.name}: {'; '.join(bits)}")
        if len(rows) > limit:
            out.append(f"… and {len(rows) - limit} more file(s)")
        for n in self.missing_files[:limit]:
            out.append(f"{n}: file is gone from the fresh build")
        return out

    def is_significant(self, attributed_rows: int) -> Optional[str]:
        """Why this drift deserves a flag, or None if it's routine."""
        if not self.compared:
            return None      # nothing was measured; there is nothing to escalate
        if self.missing_files:
            return (f"{len(self.missing_files)} NFLverse file(s) disappeared: "
                    f"{', '.join(self.missing_files[:4])}")
        dropped = [c for f in self.files for c in f.columns_removed]
        if dropped:
            return (f"NFLverse dropped {len(dropped)} column(s) the build may read: "
                    f"{', '.join(dropped[:6])}")
        moved = sum(f.added_rows + f.removed_rows for f in self.files)
        if moved:
            return f"NFLverse added / withdrew {moved} row(s) — games appearing or disappearing"
        if attributed_rows > MAX_ATTRIBUTED_ROWS:
            return (f"upstream revisions moved {attributed_rows} of our export rows "
                    f"(over the {MAX_ATTRIBUTED_ROWS} threshold)")
        return None


def _pick_key(a: pd.DataFrame, b: pd.DataFrame) -> Optional[List[str]]:
    for cand in _KEYS:
        if all(c in a.columns and c in b.columns for c in cand):
            return list(cand)
    return None


def _name_col(df: pd.DataFrame) -> Optional[str]:
    for c in _NAME_COLS:
        if c in df.columns:
            return c
    return None


def _diff_one(name: str, before: pd.DataFrame, after: pd.DataFrame,
              drift: Drift) -> FileDrift:
    fd = FileDrift(name=name)
    fd.columns_added = [c for c in after.columns if c not in before.columns]
    fd.columns_removed = [c for c in before.columns if c not in after.columns]
    shared = [c for c in before.columns if c in after.columns and c not in _IGNORE_COLS]

    key = _pick_key(before, after)
    if not key:
        # No key to align on — all we can honestly say is whether the row count
        # moved. Reporting a cell count here would be fiction.
        fd.unkeyed = True
        fd.added_rows = max(0, len(after) - len(before))
        fd.removed_rows = max(0, len(before) - len(after))
        return fd

    b = before.drop_duplicates(key).set_index(key).sort_index()
    a = after.drop_duplicates(key).set_index(key).sort_index()
    fd.added_rows = len(a.index.difference(b.index))
    fd.removed_rows = len(b.index.difference(a.index))
    common = b.index.intersection(a.index)
    if len(common) == 0:
        return fd
    b, a = b.loc[common], a.loc[common]

    name_col = _name_col(after)
    per_col: Dict[str, int] = {}
    changed_mask = pd.Series(False, index=common)
    for c in [c for c in shared if c not in key]:
        bs, as_ = b[c], a[c]
        neq = ~((bs.astype(str) == as_.astype(str)) | (bs.isna() & as_.isna()))
        n = int(neq.sum())
        if n:
            per_col[c] = n
            fd.changed_cells += n
            changed_mask = changed_mask | neq
    fd.changed_rows = int(changed_mask.sum())
    fd.top_columns = sorted(per_col.items(), key=lambda kv: -kv[1])

    if fd.changed_rows and name_col:
        touched = a.loc[changed_mask]
        names = touched[name_col].astype(str)
        seasons = pd.to_numeric(touched["season"], errors="coerce") \
            if "season" in touched.columns else None
        if seasons is None and "season" in key:
            seasons = pd.Series([i[key.index("season")] for i in touched.index],
                                index=touched.index)
        weeks = pd.to_numeric(touched["week"], errors="coerce") \
            if "week" in touched.columns else None
        if weeks is None and "week" in key:
            weeks = pd.Series([i[key.index("week")] for i in touched.index],
                              index=touched.index)
        for i in touched.index:
            nm = names.loc[i]
            if not nm or nm == "nan":
                continue
            yr = seasons.loc[i] if seasons is not None else None
            if yr is None or pd.isna(yr):
                continue
            yr = int(yr)
            drift.player_seasons.add((nm, yr))
            wk = weeks.loc[i] if weeks is not None else None
            if wk is not None and not pd.isna(wk):
                drift.player_weeks.add((nm, yr, int(wk)))
    return fd


def diff_nflverse_cache(before_dir: Optional[Path], after_dir: Optional[Path],
                        pattern: str = "nflverse_*.csv") -> Drift:
    """Diff two snapshots of the NFLverse cache directory."""
    drift = Drift()
    if not before_dir or not after_dir:
        return drift
    before_dir, after_dir = Path(before_dir), Path(after_dir)
    if not before_dir.is_dir() or not after_dir.is_dir():
        return drift
    before = {p.name: p for p in sorted(before_dir.glob(pattern))}
    after = {p.name: p for p in sorted(after_dir.glob(pattern))}
    if not before and not after:
        return drift
    drift.compared = True
    drift.missing_files = [n for n in before if n not in after]
    drift.new_files = [n for n in after if n not in before]
    for name in sorted(set(before) & set(after)):
        try:
            b = pd.read_csv(before[name], low_memory=False)
            a = pd.read_csv(after[name], low_memory=False)
        except Exception:
            continue
        drift.files.append(_diff_one(name, b, a, drift))
    return drift
