"""Read-only access + search layer for ad-hoc league inquiries.

Nothing here is part of the build. `python -m lotg` never imports this module,
no workflow calls it, and every function is pure-read: it opens committed files
under `exports/` and returns values. It exists so that a question about the
league ("who ...", "when ...", "what if ...") can be answered from primitives
that are already correct, instead of re-deriving them in a throwaway script.

Three layers, smallest first:

  1. **Sheets** — the twelve committed export CSVs, loaded once and cached, plus
     `find_columns()` to answer "which sheet holds this concept?" across all
     ~1,300 columns without grepping headers by hand, and a tiny predicate
     filter (`Year=2025`, `Points>200`) that reads the same in code and on a
     command line.

  2. **Season metadata** — playoff structure and the starting-lineup template
     read from each season's `league.json`, so nothing has to hardcode "8-team
     superflex, two flex" (true in 2024+, false in 2021-23) or "playoffs start
     week 16" (false in 2026).

  3. **Snapshot** — the raw Sleeper capture: players, rosters, weekly matchups,
     transactions, drafts. This is where counterfactual work starts, and it is
     the layer that is most tedious to re-open by hand.

Gotchas that live here as code so no future inquiry has to rediscover them:

  * `exports/*.csv` covers 2020-, the snapshot only 2021-. 2020 came from the
    ESPN dump (`data/espn_2020_raw`), so snapshot-based tooling must skip it —
    `season_meta(2020).has_snapshot` is False.
  * A team's `PF` in `team_week.csv` is NOT always Sleeper's raw `points`: the
    league's +5 home-field bonus for the higher seed in each semifinal is added
    by the build, and only there (see `SEMIFINAL_HOME_BONUS`). Eight rows across
    2021-2025 differ for exactly this reason.
  * Sleeper writes `"0"` into `starters` for a start slot left empty, and puts
    offseason trades in `week_01` of the season they precede.

Usage:
    import sys; sys.path.insert(0, "lib")
    from lotg_support import inquiry as Q

    Q.load_sheet("team_week")                     # DataFrame
    Q.find_columns("efficien")                    # every sheet/column that matches
    Q.rows("player_year", "Year=2025", "Points>250")
    Q.top("player_all_time", "Points", n=10)
    Q.trades(player="Justin Herbert")             # both sides, named, with picks
"""
from __future__ import annotations

import difflib
import functools
import json
import operator
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

# Single source of truth for cell -> number parsing (handles "", "-", "75%",
# "1,234" and the build's blank sentinels). Shared with the digest so an
# inquiry and the weekly email never disagree about what a cell means.
from lotg_support.digest import _to_float as to_number  # noqa: F401


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ROOT_OVERRIDE: Optional[Path] = None


def repo_root() -> Path:
    """Repository root: $LOTG_ROOT, an explicit set_root(), or this file's repo."""
    if _ROOT_OVERRIDE is not None:
        return _ROOT_OVERRIDE
    env = os.environ.get("LOTG_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


def set_root(path: Optional[os.PathLike]) -> None:
    """Point the whole module at another checkout (used by tests). Clears caches."""
    global _ROOT_OVERRIDE
    _ROOT_OVERRIDE = Path(path).resolve() if path is not None else None
    clear_caches()


def exports_dir() -> Path:
    return repo_root() / "exports"


def snapshot_dir() -> Path:
    return repo_root() / "exports" / "snapshot"


# ---------------------------------------------------------------------------
# Layer 1: the committed export sheets
# ---------------------------------------------------------------------------
SHEETS: Tuple[str, ...] = (
    "player_week",
    "player_year",
    "player_all_time",
    "team_week",
    "team_year",
    "team_all_time",
    "league_week",
    "league_year",
    "league_all_time",
    "transactions",
    "trades",
    "picks",
    "formulas",
)

# What identifies a row, per sheet — used by top()/describe() for labelling and
# by find_columns() to keep keys out of "value" columns.
ENTITY_COL: Dict[str, str] = {
    "player_week": "Player",
    "player_year": "Player",
    "player_all_time": "Player",
    "team_week": "Team",
    "team_year": "Team",
    "team_all_time": "Team",
    "league_week": "Week Name",
    "league_year": "Year",
    "league_all_time": "",
    "transactions": "Player Added",
    "trades": "Team",
    "picks": "Player Picked",
    "formulas": "Stat",
}

_ALIASES = {
    "pw": "player_week", "py": "player_year", "pa": "player_all_time",
    "pat": "player_all_time", "tw": "team_week", "ty": "team_year",
    "ta": "team_all_time", "tat": "team_all_time", "lw": "league_week",
    "ly": "league_year", "la": "league_all_time", "lat": "league_all_time",
    "txn": "transactions", "trans": "transactions", "trade": "trades",
    "pick": "picks", "draft": "picks",
}


def sheet_name(name: str) -> str:
    """Canonical sheet name from an alias / loose spelling ('Player-Week' -> player_week)."""
    key = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    key = _ALIASES.get(key, key)
    if key not in SHEETS:
        raise KeyError(f"unknown sheet {name!r}; known: {', '.join(SHEETS)}")
    return key


@functools.lru_cache(maxsize=None)
def _load_sheet_cached(name: str, root: str) -> pd.DataFrame:
    path = Path(root) / "exports" / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run the build, or check LOTG_ROOT")
    # Read as text: the build writes mixed cells ("34-20", "75%", "TRUE") and
    # pandas' inference would silently retype them differently per column. Use
    # numeric()/to_number() when a column needs to be a number.
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load_sheet(name: str) -> pd.DataFrame:
    """One export sheet as an all-text DataFrame (cached; do not mutate in place)."""
    return _load_sheet_cached(sheet_name(name), str(repo_root()))


def all_sheets() -> Dict[str, pd.DataFrame]:
    """Every export sheet that exists, keyed by canonical name."""
    out: Dict[str, pd.DataFrame] = {}
    for name in SHEETS:
        try:
            out[name] = load_sheet(name)
        except FileNotFoundError:
            continue
    return out


def numeric(df: pd.DataFrame, column: str) -> pd.Series:
    """One column parsed to float (unparseable -> NaN), index preserved."""
    return pd.Series([to_number(v) for v in df[column]], index=df.index, dtype="float64")


def clear_caches() -> None:
    """Drop every cached read (call after the exports/snapshot change on disk)."""
    _load_sheet_cached.cache_clear()
    _load_json_cached.cache_clear()
    _players_cached.cache_clear()
    _season_meta_cached.cache_clear()
    _formula_index.cache_clear()
    _export_team_names.cache_clear()
    _season_eligibility_cached.cache_clear()
    _ever_rostered_cached.cache_clear()
    _unavailable_cached.cache_clear()


# ---------------------------------------------------------------------------
# Column search: "which sheet holds this concept?"
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnHit:
    sheet: str
    column: str
    formula: str = ""
    notes: str = ""

    def __str__(self) -> str:  # pragma: no cover - display only
        tail = f"  — {self.notes}" if self.notes else ""
        return f"{self.sheet}.{self.column}{tail}"


@functools.lru_cache(maxsize=1)
def _formula_index(root: str) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """{(sheet, Stat): (formula, notes)} from formulas.csv, sheet-canonicalised."""
    try:
        df = _load_sheet_cached("formulas", root)
    except FileNotFoundError:
        return {}
    out: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for _, r in df.iterrows():
        try:
            key = (sheet_name(r.get("Sheet", "")), str(r.get("Stat", "")))
        except KeyError:
            continue
        out[key] = (str(r.get("Formula", "")), str(r.get("Notes", "")))
    return out


def find_columns(pattern: str, sheets: Optional[Sequence[str]] = None,
                 search_notes: bool = True) -> List[ColumnHit]:
    """Every (sheet, column) whose name — or documented formula/notes — matches.

    `pattern` is a case-insensitive regex. This is the fast way in to a cold
    question: the twelve sheets carry ~1,300 columns between them, and the one
    that answers a question is rarely in the sheet you would guess.
    """
    rx = re.compile(pattern, re.IGNORECASE)
    names = [sheet_name(s) for s in sheets] if sheets else [s for s in SHEETS if s != "formulas"]
    formulas = _formula_index(str(repo_root()))
    hits: List[ColumnHit] = []
    for name in names:
        try:
            df = load_sheet(name)
        except FileNotFoundError:
            continue
        for col in df.columns:
            formula, notes = formulas.get((name, col), ("", ""))
            if rx.search(col) or (search_notes and (rx.search(formula) or rx.search(notes))):
                hits.append(ColumnHit(name, col, formula, notes))
    return hits


def column_catalog() -> Dict[str, List[str]]:
    """{sheet: [columns]} for every sheet — a grep-able inventory."""
    return {name: list(df.columns) for name, df in all_sheets().items()}


def describe_column(sheet: str, column: str) -> Dict[str, Any]:
    """Shape of one column: fill rate, range, extremes, and its documented formula."""
    name = sheet_name(sheet)
    df = load_sheet(name)
    if column not in df.columns:
        raise KeyError(f"{name} has no column {column!r}" + _suggest(column, df.columns))
    vals = numeric(df, column)
    entity = ENTITY_COL.get(name) or (df.columns[0] if len(df.columns) else "")
    formula, notes = _formula_index(str(repo_root())).get((name, column), ("", ""))
    out: Dict[str, Any] = {
        "sheet": name, "column": column, "rows": int(len(df)),
        "numeric_values": int(vals.notna().sum()),
        "blank_or_text": int(len(df) - vals.notna().sum()),
        "formula": formula, "notes": notes,
    }
    if vals.notna().any():
        out.update(min=float(vals.min()), max=float(vals.max()), mean=float(vals.mean()))
        if entity in df.columns:
            out["argmax"] = str(df.loc[vals.idxmax(), entity])
            out["argmin"] = str(df.loc[vals.idxmin(), entity])
    else:
        sample = [v for v in df[column] if str(v).strip()][:5]
        out["sample_values"] = sample
    return out


# ---------------------------------------------------------------------------
# Predicate filtering: "Year=2025", "Points>200", "Player~mahomes"
# ---------------------------------------------------------------------------
def _suggest(wanted: str, columns: Iterable[str]) -> str:
    """'; did you mean [...]?' — substring matches first, then close spellings."""
    cols = list(columns)
    near = [c for c in cols if str(wanted).lower() in c.lower()]
    near += [c for c in difflib.get_close_matches(str(wanted), cols, n=5, cutoff=0.6)
             if c not in near]
    return f"; did you mean {near[:5]}?" if near else ""


_OPS: Tuple[Tuple[str, Callable[[Any, Any], bool]], ...] = (
    (">=", operator.ge), ("<=", operator.le), ("!=", operator.ne),
    ("==", operator.eq), ("~", None), (">", operator.gt), ("<", operator.lt),
    ("=", operator.eq),
)


@dataclass(frozen=True)
class Predicate:
    column: str
    op: str
    value: str

    def matches(self, cell: Any) -> bool:
        text = "" if cell is None else str(cell).strip()
        if self.op == "~":
            return re.search(self.value, text, re.IGNORECASE) is not None
        want_num, got_num = to_number(self.value), to_number(text)
        fn = dict(_OPS)[self.op]
        if want_num is not None and got_num is not None:
            return bool(fn(got_num, want_num))
        if self.op in (">", ">=", "<", "<="):
            return False  # ordering a non-number against a number is never true
        # Equality on text: case-insensitive, and TRUE/True/1 all read as true.
        a, b = text.lower(), self.value.strip().lower()
        if a in ("true", "false") or b in ("true", "false"):
            a = {"1": "true", "0": "false"}.get(a, a)
            b = {"1": "true", "0": "false"}.get(b, b)
        return bool(fn(a, b))


def parse_predicate(expr: str) -> Predicate:
    """'Avg points >= 12.5' -> Predicate. Operators: = == != > >= < <= ~ (regex)."""
    for token, _ in _OPS:
        idx = expr.find(token)
        if idx > 0:
            return Predicate(expr[:idx].strip(), token, expr[idx + len(token):].strip())
    raise ValueError(f"cannot parse filter {expr!r} (expected e.g. \"Year=2025\")")


def filter_rows(df: pd.DataFrame, *filters: str) -> pd.DataFrame:
    """Rows matching every filter. Unknown column -> KeyError with near-misses."""
    out = df
    for expr in filters:
        if not expr:
            continue
        pred = parse_predicate(expr)
        if pred.column not in out.columns:
            raise KeyError(f"no column {pred.column!r}" + _suggest(pred.column, out.columns))
        out = out[[pred.matches(v) for v in out[pred.column]]]
    return out


def rows(sheet: str, *filters: str) -> pd.DataFrame:
    """Filtered rows of one sheet: rows('player_year', 'Year=2025', 'Points>250')."""
    return filter_rows(load_sheet(sheet), *filters)


def top(sheet: str, column: str, *filters: str, n: int = 10,
        ascending: bool = False, columns: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Leaderboard for one column, blanks dropped, with the row's identifying keys."""
    name = sheet_name(sheet)
    df = filter_rows(load_sheet(name), *filters)
    if column not in df.columns:
        raise KeyError(f"{name} has no column {column!r}")
    vals = numeric(df, column)
    df = df.assign(**{"_value": vals}).dropna(subset=["_value"])
    df = df.sort_values("_value", ascending=ascending)
    keys = [c for c in (ENTITY_COL.get(name), "Year", "Week Name", "Week", "Team", "Season")
            if c and c in df.columns]
    keep = list(dict.fromkeys(list(columns) if columns else keys + [column]))
    return df.head(n)[keep].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Layer 2: season metadata (playoff shape + starting-lineup template)
# ---------------------------------------------------------------------------
# The league's home-field rule: the higher seed in each semifinal gets +5 points,
# in the playoff-start week only. src/lotg.py bakes this into team_week's PF, so
# any replay that wants to match the build must add it too.
SEMIFINAL_HOME_BONUS = 5.0

# Sleeper's sentinel for a starting slot left unfilled.
EMPTY_SLOT = "0"

_FLEX_POOL: Dict[str, Tuple[str, ...]] = {
    "QB": ("QB",), "RB": ("RB",), "WR": ("WR",), "TE": ("TE",), "K": ("K",),
    "DEF": ("DEF",), "FLEX": ("RB", "WR", "TE"), "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"), "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}


@dataclass(frozen=True)
class SeasonMeta:
    """Everything about a season's shape, read from its own league.json."""
    year: int
    has_snapshot: bool
    playoff_teams: int = 4
    playoff_week_start: int = 16
    starting_slots: Tuple[Tuple[str, ...], ...] = ()
    roster_positions: Tuple[str, ...] = ()
    status: str = ""

    @property
    def regular_season_weeks(self) -> int:
        return self.playoff_week_start - 1

    @property
    def playoff_weeks(self) -> Tuple[int, ...]:
        """Playoff weeks with data in the snapshot (2026+ finals run two weeks)."""
        return tuple(range(self.playoff_week_start, self.last_week + 1))

    @property
    def last_week(self) -> int:
        # 2021-2025: semis (16) + final (17). 2026 moved the start to 15 and made
        # the final a two-week round, which still ends at 17.
        return 17

    @property
    def is_complete(self) -> bool:
        """True once the season is over (Sleeper's own league status).

        Guards and regression tests only assert against completed seasons: a
        season still being played has weeks in the snapshot that the build has
        not written to `exports/` yet, and comparing the two mid-week would
        compare a partial week against nothing.
        """
        return str(self.status).lower() in ("complete", "post_season")

    @property
    def semifinal_week(self) -> int:
        """The playoff-start week: semifinals, and the only week the +5 lands in."""
        return self.playoff_week_start

    @property
    def finals_weeks(self) -> Tuple[int, ...]:
        """Weeks the final is played over — one before 2026, two from 2026 on."""
        return tuple(range(self.playoff_week_start + 1, self.last_week + 1))

    @property
    def lineup_size(self) -> int:
        return len(self.starting_slots)


@functools.lru_cache(maxsize=None)
def _season_meta_cached(year: int, root: str) -> SeasonMeta:
    path = Path(root) / "exports" / "snapshot" / f"season_{year}" / "league.json"
    if not path.exists():
        # 2020 and earlier: exports exist (ESPN backfill) but no Sleeper snapshot.
        return SeasonMeta(year=year, has_snapshot=False, playoff_week_start=15 if year <= 2020 else 16)
    blob = json.loads(path.read_text())
    settings = blob.get("settings") or {}
    positions = tuple(blob.get("roster_positions") or ())
    slots = tuple(_FLEX_POOL.get(p, (p,)) for p in positions if p not in ("BN", "IR", "TAXI"))
    return SeasonMeta(
        year=year,
        has_snapshot=True,
        playoff_teams=int(settings.get("playoff_teams") or 4),
        playoff_week_start=int(settings.get("playoff_week_start") or 16),
        starting_slots=slots,
        roster_positions=positions,
        status=str(blob.get("status") or ""),
    )


def season_meta(year: int) -> SeasonMeta:
    """Playoff structure + starting-lineup template for one season."""
    return _season_meta_cached(int(year), str(repo_root()))


def completed_seasons() -> List[int]:
    """Snapshot seasons that have finished — what the guards assert against."""
    return [y for y in snapshot_seasons() if season_meta(y).is_complete]


def snapshot_seasons() -> List[int]:
    """Seasons with a Sleeper snapshot (i.e. replayable). 2020 is not one of them."""
    base = snapshot_dir()
    if not base.exists():
        return []
    out = []
    for child in base.glob("season_*"):
        if (child / "league.json").exists():
            try:
                out.append(int(child.name.split("_")[1]))
            except (IndexError, ValueError):
                continue
    return sorted(out)


def export_seasons() -> List[int]:
    """Seasons present in the built exports (includes 2020's ESPN backfill)."""
    df = load_sheet("team_week")
    return sorted({int(v) for v in numeric(df, "Year").dropna()})


# ---------------------------------------------------------------------------
# Layer 3: the Sleeper snapshot
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def _load_json_cached(rel: str, root: str) -> Any:
    path = Path(root) / rel
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    return json.loads(path.read_text())


def _snap(rel: str) -> Any:
    return _load_json_cached(str(Path("exports") / "snapshot" / rel), str(repo_root()))


@dataclass(frozen=True)
class PlayerMeta:
    player_id: str
    name: str
    position: str
    nfl_team: str = ""


def _normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", text.lower())


class AmbiguousPlayer(KeyError):
    """Raised when a name matches several players — the candidates are listed."""


_STARTABLE = ("QB", "RB", "WR", "TE", "K", "DEF")


@functools.lru_cache(maxsize=1)
def _ever_rostered_cached(root: str) -> frozenset:
    out: Set[str] = set()
    for year in snapshot_seasons():
        try:
            for roster in _snap(f"season_{year}/rosters.json"):
                out.update(str(p) for p in (roster.get("players") or ()))
        except FileNotFoundError:
            continue
    return frozenset(out)


def ever_rostered() -> frozenset:
    """Every player id on any roster in any snapshot season."""
    return _ever_rostered_cached(str(repo_root()))


class Players:
    """The Sleeper player dictionary, indexed for lookup by id or by name."""

    def __init__(self, blob: Dict[str, dict]):
        self._by_id: Dict[str, PlayerMeta] = {}
        self._by_norm: Dict[str, List[str]] = {}
        for pid, rec in blob.items():
            rec = rec or {}
            name = rec.get("full_name") or " ".join(
                x for x in (rec.get("first_name"), rec.get("last_name")) if x) or str(pid)
            meta = PlayerMeta(str(pid), name, (rec.get("position") or "").upper(),
                              rec.get("team") or "")
            self._by_id[str(pid)] = meta
            self._by_norm.setdefault(_normalize(name), []).append(str(pid))

    def meta(self, player_id: str) -> PlayerMeta:
        return self._by_id.get(str(player_id), PlayerMeta(str(player_id), str(player_id), ""))

    def name(self, player_id: str) -> str:
        return self.meta(player_id).name

    def position(self, player_id: str) -> str:
        return self.meta(player_id).position

    def positions(self) -> Dict[str, str]:
        """{player_id: position} for the whole dictionary (what lineup code wants)."""
        return {pid: m.position for pid, m in self._by_id.items()}

    def names(self) -> Dict[str, str]:
        return {pid: m.name for pid, m in self._by_id.items()}

    def resolve(self, who: str) -> str:
        """Player id from an id, an exact name, or an unambiguous partial name.

        Raises AmbiguousPlayer listing the candidates rather than guessing —
        picking silently is how a counterfactual ends up replaying the wrong
        player for seventeen weeks.
        """
        key = str(who).strip()
        if key in self._by_id:
            return key
        needle = _normalize(key)
        exact = self._by_norm.get(needle, [])
        partial = [] if exact else [
            pid for norm, ids in self._by_norm.items() if needle and needle in norm for pid in ids]
        candidates = exact or partial
        if not candidates:
            raise KeyError(f"no player matches {who!r}")
        # Narrow by relevance before giving up: a startable position first
        # ("Lamar Jackson" is also a cornerback), then whoever was actually on a
        # roster in this league. Only a tie that survives both is ambiguous.
        for narrower in (lambda p: self.meta(p).position in _STARTABLE,
                         lambda p: p in ever_rostered()):
            if len(candidates) > 1:
                narrowed = [p for p in candidates if narrower(p)]
                if narrowed:
                    candidates = narrowed
        if len(candidates) == 1:
            return candidates[0]
        raise AmbiguousPlayer(
            f"{who!r} matches {len(candidates)} players: "
            + ", ".join(f"{self.meta(p).name} [{p}] {self.meta(p).position}"
                        for p in sorted(candidates)[:12])
            + " — pass the id instead")


@functools.lru_cache(maxsize=None)
def _players_cached(root: str) -> Players:
    return Players(_load_json_cached("exports/snapshot/sleeper_players_nfl.json", root))


def players() -> Players:
    """The (cached) player dictionary."""
    return _players_cached(str(repo_root()))


@functools.lru_cache(maxsize=1)
def _export_team_names(root: str) -> Tuple[str, ...]:
    try:
        df = _load_sheet_cached("team_week", root)
    except FileNotFoundError:
        return ()
    return tuple(sorted({str(t) for t in df["Team"] if str(t).strip()}))


def canonical_team(name: str) -> str:
    """A team name spelled the way the exports spell it.

    Sleeper's display name and the built sheets can disagree on case
    ("Shmuel256" vs "shmuel256"), which silently breaks a join between a
    snapshot-derived result and `team_week.csv`. Unknown names pass through.
    """
    for known in _export_team_names(str(repo_root())):
        if known.lower() == str(name).strip().lower():
            return known
    return str(name)


def teams(year: int) -> Dict[int, str]:
    """{roster_id: team name}, spelled as the exports spell it (see canonical_team)."""
    users = {u["user_id"]: (u.get("display_name") or u.get("username") or u["user_id"])
             for u in _snap(f"season_{int(year)}/users.json")}
    return {r["roster_id"]: canonical_team(users.get(r.get("owner_id"), f"Roster {r['roster_id']}"))
            for r in _snap(f"season_{int(year)}/rosters.json")}


def roster_id(year: int, team: str) -> int:
    """Roster id for a team name (case-insensitive; accepts a numeric id as-is)."""
    if str(team).isdigit():
        return int(team)
    table = teams(year)
    for rid, name in table.items():
        if str(name).lower() == str(team).strip().lower():
            return rid
    near = [n for n in table.values() if str(team).lower() in str(n).lower()]
    if len(near) == 1:
        return roster_id(year, near[0])
    raise KeyError(f"no {year} team named {team!r}; have {sorted(table.values())}")


@dataclass(frozen=True)
class WeekRow:
    """One roster's week, straight from Sleeper (points are RAW — see module docstring)."""
    roster_id: int
    matchup_id: Optional[int]
    points: float
    starters: Tuple[str, ...]
    players: Tuple[str, ...]
    players_points: Dict[str, float] = field(default_factory=dict)

    @property
    def bench(self) -> Tuple[str, ...]:
        started = set(self.starters)
        return tuple(p for p in self.players if p not in started)


def week(year: int, wk: int) -> Dict[int, WeekRow]:
    """{roster_id: WeekRow} for one week of one season."""
    raw = _snap(f"season_{int(year)}/weeks/week_{int(wk):02d}/matchups.json")
    out: Dict[int, WeekRow] = {}
    for row in raw:
        out[row["roster_id"]] = WeekRow(
            roster_id=row["roster_id"],
            matchup_id=row.get("matchup_id"),
            points=float(row.get("points") or 0.0),
            starters=tuple(str(p) for p in (row.get("starters") or ())),
            players=tuple(str(p) for p in (row.get("players") or ())),
            players_points={str(k): float(v or 0.0)
                            for k, v in (row.get("players_points") or {}).items()},
        )
    return out


def played_weeks(year: int) -> List[int]:
    """Weeks of a season that actually have scores (an unplayed week is all zeros)."""
    meta = season_meta(year)
    if not meta.has_snapshot:
        return []
    out = []
    for wk in range(1, meta.last_week + 1):
        try:
            rows = week(year, wk)
        except FileNotFoundError:
            continue
        if any(r.points for r in rows.values()):
            out.append(wk)
    return out


def player_points(year: int, wk: int) -> Dict[str, float]:
    """{player_id: points} for everyone rostered that week (starters and bench)."""
    out: Dict[str, float] = {}
    for row in week(year, wk).values():
        for pid, val in row.players_points.items():
            out[pid] = float(val or 0.0)
    return out


def pairings(year: int, wk: int) -> List[Tuple[int, int]]:
    """[(roster_id, roster_id)] head-to-heads for a week, from Sleeper matchup ids."""
    groups: Dict[Any, List[int]] = {}
    for rid, row in week(year, wk).items():
        groups.setdefault(row.matchup_id, []).append(rid)
    return [tuple(sorted(sides)) for sides in groups.values() if len(sides) == 2]


@functools.lru_cache(maxsize=None)
def _season_eligibility_cached(year: int, root: str) -> Dict[str, frozenset]:
    meta = season_meta(year)
    learned: Dict[str, Set[str]] = {}
    for wk in played_weeks(year):
        for row in week(year, wk).values():
            for idx, pid in enumerate(row.starters):
                if pid == EMPTY_SLOT or idx >= len(meta.starting_slots):
                    continue
                slot = meta.starting_slots[idx]
                if len(slot) == 1:  # a strict slot proves eligibility; a flex proves nothing
                    learned.setdefault(pid, set()).add(slot[0])
    out: Dict[str, frozenset] = {}
    for pid, pos in players().positions().items():
        elig = set(learned.pop(pid, set()))
        if pos:
            elig.add(pos)
        if elig:
            out[pid] = frozenset(elig)
    for pid, elig in learned.items():  # rostered but absent from the dictionary
        out[pid] = frozenset(elig)
    return out


def season_eligibility(year: int) -> Dict[str, frozenset]:
    """{player_id: positions he could start at} for one season.

    The Sleeper player dictionary holds only a player's *current* position, so
    it drifts: Cordarrelle Patterson is listed RB today but filled a strict WR
    slot in 2021, which makes three of that season's real lineups look illegal.
    Eligibility is therefore the current position PLUS every strict slot the
    player was actually fielded in that season — observed, not guessed. Flex
    slots teach nothing and are ignored.

    Note this is for *legality*. `Max PF` in the exports is computed by the
    build from current positions, so `lineup.compute_optimal_lineup` is left
    alone and keeps matching the built column exactly.
    """
    return _season_eligibility_cached(int(year), str(repo_root()))


@functools.lru_cache(maxsize=None)
def _unavailable_cached(year: int, root: str) -> frozenset:
    return frozenset(_unavailable(year))


def unavailable(year: int) -> Set[Tuple[str, int]]:
    """{(player_id, week)} the build flags as on bye / injured / suspended.

    Read from `player_week.csv` (the build's own judgement) and mapped back to
    player ids by name, so a counterfactual lineup never starts someone who was
    never going to take the field.
    """
    return set(_unavailable_cached(int(year), str(repo_root())))


def _unavailable(year: int) -> Set[Tuple[str, int]]:
    weeks_by_name: Dict[str, Set[int]] = {}
    df = load_sheet("player_week")
    year_s, week_s = numeric(df, "Year"), numeric(df, "Week")
    flags = [c for c in ("Bye?", "Injury?", "Suspension?") if c in df.columns]
    for idx, name in enumerate(df["Player"]):
        if year_s.iloc[idx] != year:
            continue
        if any(str(df[c].iloc[idx]).strip().lower() in ("true", "1", "yes") for c in flags):
            wk = week_s.iloc[idx]
            if pd.notna(wk):
                weeks_by_name.setdefault(str(name), set()).add(int(wk))
    if not weeks_by_name:
        return set()
    pl = players()
    return {(pid, wk) for pid, name in pl.names().items() for wk in weeks_by_name.get(name, ())}


# ---------------------------------------------------------------------------
# Transactions and trades
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Trade:
    """A completed trade with both sides already resolved to names."""
    season: int
    date: str
    transaction_id: str
    roster_ids: Tuple[int, ...]
    received: Dict[int, Tuple[str, ...]]          # roster_id -> player ids gained
    faab: Dict[int, float] = field(default_factory=dict)   # roster_id -> net FAAB
    picks: Tuple[dict, ...] = ()

    def team(self, rid: int, year: Optional[int] = None) -> str:
        return teams(year or self.season).get(rid, f"Roster {rid}")

    def describe(self) -> str:
        pl = players()
        parts = []
        for rid in self.roster_ids:
            got = ", ".join(pl.name(p) for p in self.received.get(rid, ())) or "—"
            cash = self.faab.get(rid, 0.0)
            if cash:
                got += f", ${cash:+.0f} FAAB"
            picks = [f"{p.get('season')} r{p.get('round')}" for p in self.picks
                     if p.get("owner_id") == rid]
            if picks:
                got += ", " + ", ".join(picks)
            parts.append(f"{self.team(rid)} gets {got}")
        return f"[{self.date}] " + "; ".join(parts)


def raw_transactions(year: int, wk: Optional[int] = None) -> List[dict]:
    """Raw Sleeper transaction records. Offseason deals live in week_01."""
    meta = season_meta(year)
    weeks = [wk] if wk else range(1, meta.last_week + 1)
    out: List[dict] = []
    for w in weeks:
        try:
            out.extend(_snap(f"season_{int(year)}/weeks/week_{int(w):02d}/transactions.json"))
        except FileNotFoundError:
            continue
    return out


def _txn_date(txn: dict) -> str:
    stamp = txn.get("status_updated") or txn.get("created")
    if not stamp:
        return ""
    return datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc).date().isoformat()


def trades(season: Optional[int] = None, player: Optional[str] = None,
           date: Optional[str] = None) -> List[Trade]:
    """Completed trades, optionally narrowed to a season / a player / a date.

    `player` accepts an id or a name (resolved through Players.resolve, so a
    partial name is fine as long as it is unambiguous).
    """
    pid = players().resolve(player) if player else None
    seasons = [int(season)] if season else snapshot_seasons()
    out: List[Trade] = []
    for yr in seasons:
        for txn in raw_transactions(yr):
            if txn.get("type") != "trade" or txn.get("status") != "complete":
                continue
            adds = {str(k): int(v) for k, v in (txn.get("adds") or {}).items()}
            if pid and pid not in adds and pid not in {str(k) for k in (txn.get("drops") or {})}:
                continue
            when = _txn_date(txn)
            if date and when != date:
                continue
            received: Dict[int, List[str]] = {}
            for player_id, rid in adds.items():
                received.setdefault(int(rid), []).append(player_id)
            cash: Dict[int, float] = {}
            for move in (txn.get("waiver_budget") or ()):
                cash[int(move["receiver"])] = cash.get(int(move["receiver"]), 0.0) + float(move["amount"])
                cash[int(move["sender"])] = cash.get(int(move["sender"]), 0.0) - float(move["amount"])
            out.append(Trade(
                season=yr, date=when, transaction_id=str(txn.get("transaction_id") or ""),
                roster_ids=tuple(int(r) for r in (txn.get("roster_ids") or ())),
                received={k: tuple(v) for k, v in received.items()},
                faab=cash, picks=tuple(txn.get("draft_picks") or ()),
            ))
    out.sort(key=lambda t: (t.season, t.date))
    return out


def transactions_for(player: str, season: Optional[int] = None) -> List[dict]:
    """Every completed transaction (add/drop/waiver/trade) touching one player."""
    pid = players().resolve(player)
    seasons = [int(season)] if season else snapshot_seasons()
    out: List[dict] = []
    for yr in seasons:
        for txn in raw_transactions(yr):
            if txn.get("status") != "complete":
                continue
            touched = {str(k) for k in (txn.get("adds") or {})} | {str(k) for k in (txn.get("drops") or {})}
            if pid in touched:
                out.append({**txn, "_season": yr, "_date": _txn_date(txn)})
    out.sort(key=lambda t: (t["_season"], t["_date"]))
    return out


def drafts(year: int) -> List[dict]:
    """Draft picks for a season, from the committed raw capture."""
    path = Path("exports") / "raw" / f"drafts_{int(year)}.json"
    return _load_json_cached(str(path), str(repo_root()))


# ---------------------------------------------------------------------------
# Convenience dossiers — the shape most inquiries start from
# ---------------------------------------------------------------------------
def player_dossier(name: str) -> Dict[str, Any]:
    """Everything the exports know about one player, in one call."""
    label = name
    try:
        label = players().name(players().resolve(name))
    except (KeyError, FileNotFoundError):
        pass
    matcher = f"^{re.escape(label)}$"
    return {
        "player": label,
        "all_time": rows("player_all_time", f"Player~{matcher}"),
        "by_year": rows("player_year", f"Player~{matcher}"),
        "by_week": rows("player_week", f"Player~{matcher}"),
        "added": rows("transactions", f"Player Added~{matcher}"),
        "dropped": rows("transactions", f"Player Dropped~{matcher}"),
        "drafted": rows("picks", f"Player Picked~{matcher}"),
    }


def team_dossier(team: str) -> Dict[str, Any]:
    """Everything the exports know about one team."""
    matcher = f"^{re.escape(team)}$"
    return {
        "team": team,
        "all_time": rows("team_all_time", f"Team~{matcher}"),
        "by_year": rows("team_year", f"Team~{matcher}"),
        "by_week": rows("team_week", f"Team~{matcher}"),
        "trades": rows("trades", f"Team~{matcher}"),
        "transactions": rows("transactions", f"Team~{matcher}"),
    }


def season_dossier(year: int) -> Dict[str, Any]:
    """One season: league row, team-year table, and the playoff bracket as built."""
    return {
        "year": int(year),
        "league": rows("league_year", f"Year={year}"),
        "teams": rows("team_year", f"Year={year}"),
        "weeks": rows("league_week", f"Year={year}"),
        "bracket": rows("team_week", f"Year={year}", "Week Name~final|semi|place|toilet"),
        "meta": season_meta(year),
    }
