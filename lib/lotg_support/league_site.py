"""The league website: precomputed JSON for a static, server-less site.

`build(out_dir)` reads the committed exports (plus the last digest email and,
optionally, the championship forecast) and writes `out_dir/data/*.json`; the
page shell in `site/` (index.html, app.js, style.css) is copied next to it and
renders everything client-side with hash routing. GitHub Pages serves the
result as an Actions artifact (`.github/workflows/site.yml`), so nothing
generated is ever committed.

Read-only over the build: it changes no export, no data file and no workflow
output. Inputs are an allow-list (`INPUTS`) of files that are already public in
this repository; nothing under `plan/`, no memory file, no chat export and no
credential is read (tests/test_league_site.py checks the output for them).

Numbers are shipped raw, rounded to the workbook's decimal places, with one
format spec per column (`number_format.col_number_format`) so the page prints a
stat exactly as the spreadsheet does (memory: digest-numbers-workbook-decimals).
Column names shown to people go through the digest's `display_column`.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import shutil
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import number_format as NF
from . import workbook_comments as WC

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "exports"
DIGEST_HTML = ROOT / "data" / "digest" / "last_digest.html"
SHELL = ROOT / "site"

# Every file the generator reads. Anything else is off limits.
INPUTS = (
    "exports/*.csv",                 # every sheet, served whole on the Data page (+ CSV downloads)
    "data/digest/last_digest.html",
    "LOTG_Stats.xlsx from the build's LOTG_outputs artifact (asset-history comments, optional)",
    "exports/snapshot/season_<current>/{users,rosters,traded_picks}.json",   # future pick owners
    # docs/rate/board.json (FAAB values) is not read here: it ships with docs/ and the page
    # fetches it, so the FAAB page is always the board the rating page shows.
    # the forecast reads exports/ and exports/snapshot/ through lotg_support.inquiry
)

# Sheets the record book ranks on, with the columns that label a row.
RECORD_SHEETS = {
    "team_week": ("Team", "Year", "Week Name", "Opponent"),
    "team_year": ("Team", "Year"),
    "team_all_time": ("Team",),
    "player_week": ("Player", "Team", "Year", "Week Name", "Starter/Bench"),
    "player_year": ("Player", "Year", "Top Team"),
    "player_all_time": ("Player", "Top team"),
    "league_week": ("Year", "Week Name"),
    "league_year": ("Year",),
    "trades": ("Team", "Team's traded with 1", "Date", "Assets received"),
    "add_drops": ("Team", "Player Added", "Player Dropped", "Date"),
    "player_additions": ("Player", "Team", "Addition type", "Date"),
    # the pick leads: "2025 3.08 · AceMatthew → Jalen Milroe"
    "rookie_picks": ("Year", "Number", "Team", "Player Picked"),
    "non_rookie_picks": ("Year", "Number", "Team", "Player Picked"),
}
# The digest's board: top / bottom 5, and a tie shows only when all of it fits in
# the 5 (memory digest-line-rules-0922, `_tie_fits`): no 2-way tie for 5th.
RECORD_DEPTH = 5

# Week types, as the build's team records split them (team_all_time "Playoff
# record" / "Third place game record" / "Toilet bowl record" / "Toilet losers
# game record"; tests reconcile each). The 3rd-place game is NOT playoffs (user,
# 2026-11-02), and the toilet losers game is not the toilet bowl.
WEEK_KINDS = {"reg": "Regular season", "playoffs": "Playoffs", "third": "3rd place game",
              "toilet": "Toilet bowl", "trash": "Toilet losers game"}
# Views on top of the five week types (they overlap them, so they never enter a
# sum that must add up to the whole): the final alone, a subset of the playoffs.
EXTRA_VIEWS = {"final": "Final"}


def in_view(view: str, week_name) -> bool:
    return view == "final" and str(week_name) == "Final"


KIND_RECORD = {"playoffs": "Playoff record", "third": "Third place game record",
               "toilet": "Toilet bowl record", "trash": "Toilet losers game record"}


def week_kind(name) -> str:
    """"reg" for a regular-season week ("Week 7"); "playoffs" for Semifinal and
    Final; "third" for the 3rd-place game; "toilet" for Toilet Semis and Toilet
    Final; "trash" for the toilet losers game (Toilet Trash)."""
    n = str(name)
    if n.startswith("Week "):
        return "reg"
    low = n.lower()
    if "3rd" in low or "third" in low:
        return "third"
    if low.startswith("toilet"):
        return "trash" if ("trash" in low or "loser" in low) else "toilet"
    return "playoffs"


# "Still counting" is decided per CELL (`Counting`). Each column of a move sheet
# runs on its own clock, read from its definition in formulas.csv:
#   fixed       set when the move is made (the digest's LOCKED_AT_MOVE, a used
#               pick's trade count, cuff flags)
#   held        while the player / received assets are still on that team
#               (stint, tenure, "Assets retained now")
#   first_start weeks before his first start: while held and not started yet
#   team_now    "(all stints)" totals: while he is on that team now
#   sent        a trade's sent side "over the same time": while the received
#               side is held (4 years when no player came back)
#   draft       a trade's "Change in pick value at draft time": until every
#               received pick has been drafted
#   career      a pick's career PPG (every team): while he is active in the NFL
#   next17      the dropped player's next 17 played games: a year from the drop
#   checkpoint  "at end of season / N years later": until that date
#   always      keeps moving: wins added ("from the move to today"), impact
#               score, O-Score and pick-adjusted differences (re-ranked against
#               other rows / slot averages), % of all-time team points (the
#               denominator grows), points above expectation (a refit model)
# Season rows count while the season is in progress; a career row while he is
# rostered. Week rows are final. Team and league all-time totals move every week,
# so the board's note says so instead of tagging every row.
STILL_COUNTING = {"team_year": "season in progress", "player_year": "season in progress",
                  "league_year": "season in progress", "trades": "still counting",
                  "add_drops": "still counting", "player_additions": "still counting",
                  "rookie_picks": "still counting", "non_rookie_picks": "still counting",
                  "player_all_time": "still counting"}
_LOCKED_EXTRA = {"rookie_picks": {"Number of trades", "Commissioner moved?", "Cuff when drafted?"},
                 "non_rookie_picks": {"Number of trades", "Commissioner moved?", "Cuff when drafted?"},
                 "player_additions": {"Cuff at pickup?", "Number of times added by this team"},
                 "add_drops": {"Cuff at time of pickup?"},
                 "trades": {"Asset difference in average age"}}
_CHECKPOINT_YEARS = re.compile(r"(\d) years? (?:later|after)")
_CHECKPOINT_SEASON_END = re.compile(r"end of (?:rookie year|season)")
# (sheet, regex on the column) -> clock; first match wins, anything else is "held"
_CLOCKS = [
    ("*", r"^(Wins added|Wins added per season|Trade impact score|O-Score)$", "always"),
    ("*", r"^Pick-adjusted ", "always"),
    ("*", r"^% of all time team points", "always"),
    ("*", r"^Points above expectation", "always"),
    ("add_drops", r"^Number of times (picked up|dropped) by this team$", "always"),
    ("player_additions", r"^Number of times dropped by this team$", "always"),
    ("*", r"\(all stints\)$", "team_now"),
    ("*", r"^Weeks (between pickup and start|before first start)$", "first_start"),
    ("trades", r"^Avg PPG of sent players over same time", "sent"),
    ("trades", r"^Change in pick value at draft time$", "draft"),
    ("add_drops", r"^Dropped ", "next17"),
    ("rookie_picks", r"^Avg career PPG", "career"),
    ("non_rookie_picks", r"^Avg career PPG", "career"),
]
_START_COLS = ("Number of starts before next drop", "Number of starts before next transaction")
_PLAYER_ID_COL = {"player_additions": "Player ID", "add_drops": "Player Added ID",
                  "rookie_picks": "Player Picked ID", "non_rookie_picks": "Player Picked ID",
                  "player_all_time": "Player ID"}
_FUTURE_PICK = re.compile(r"^(\d{4}) \d")
_DRAFT_DAY = (8, 28)          # the rookie draft, ≈ Aug 28 (formulas.csv)
_SEASON_END = (2, 15)         # KTC "end of season" checkpoints, the February after


def _locked_columns(sheet: str) -> set:
    try:
        from .digest import LOCKED_AT_MOVE
        locked = set(LOCKED_AT_MOVE.get(sheet, ()))
    except Exception:                                  # pragma: no cover
        locked = {"Tanking"}
    return locked | _LOCKED_EXTRA.get(sheet, set())


def column_clock(sheet: str, col: str) -> str:
    """The clock a column of `sheet` runs on (see the table above)."""
    if col in _locked_columns(sheet):
        return "fixed"
    if _CHECKPOINT_YEARS.search(col) or _CHECKPOINT_SEASON_END.search(col):
        return "checkpoint"
    for where, rx, clock in _CLOCKS:
        if where in ("*", sheet) and re.search(rx, col):
            return clock
    return "held"


def _rookie_day(year: int) -> pd.Timestamp:
    """When a pick "becomes a rookie" for KTC: the day after Labor Day (the
    first Monday of September) of its draft year."""
    d = pd.Timestamp(year, 9, 1)
    return d + pd.Timedelta(days=(7 - d.weekday()) % 7 + 1)


class Counting:
    """Which cells of a sheet can still change: `counting(idx, col)`."""

    def __init__(self, sheet: str, df: pd.DataFrame, season: int, rostered: set,
                 today: Optional[pd.Timestamp] = None, team_of: Optional[Dict[str, str]] = None,
                 active: Optional[set] = None):
        self.sheet, self.df, self.season = sheet, df, season
        self.today = today or pd.Timestamp.now().normalize()
        self.team_of = team_of or {}          # Sleeper id -> team he is on now
        self.active = active or set()         # Sleeper ids active in the NFL
        self.open = self._open_rows(rostered)
        self.when = self._move_dates()

    def _year(self) -> pd.Series:
        col = "Year" if "Year" in self.df else ("Season" if "Season" in self.df else None)
        if col is None:
            return pd.Series(np.nan, index=self.df.index)
        y = self.df[col].astype(str).str.extract(r"(\d{4})")[0]
        out = pd.to_numeric(y, errors="coerce")
        if self.sheet == "non_rookie_picks":            # "startup" = the 2020 startup draft
            out = out.fillna(2020)
        return out

    def _move_dates(self) -> pd.Series:
        """When the row's move happened: its date, or draft day for a pick."""
        if self.sheet in ("rookie_picks", "non_rookie_picks"):
            return pd.to_datetime([f"{int(y)}-{_DRAFT_DAY[0]:02d}-{_DRAFT_DAY[1]:02d}" if pd.notna(y) else None
                                   for y in self._year()], errors="coerce").to_series(index=self.df.index)
        if "Date" in self.df:
            return pd.to_datetime(self.df["Date"].astype(str).str[:10], errors="coerce")
        return pd.Series(pd.NaT, index=self.df.index)

    def _empty(self, c: str) -> pd.Series:
        df = self.df
        if c not in df:
            return pd.Series(True, index=df.index)
        return df[c].isna() | df[c].astype(str).str.strip().isin(["", "nan", "N/A"])

    def _open_rows(self, rostered: set) -> pd.Series:
        df, idx = self.df, self.df.index
        if self.sheet in ("team_year", "player_year", "league_year"):
            return self._year() == self.season
        if self.sheet == "player_all_time":
            key = df["Player ID"].astype(str).str.split(".").str[0] if "Player ID" in df else df["Player"].astype(str)
            return key.isin(rostered)
        if self.sheet in ("player_additions", "add_drops"):
            return self._empty("Date dropped/traded")
        if self.sheet in ("rookie_picks", "non_rookie_picks"):
            # the drafted player is still with the drafting team (no first move after the draft yet)
            return self._empty("Link to next transaction")
        if self.sheet == "trades":
            return ~self._empty("Assets retained now")
        return pd.Series(False, index=idx)

    def _checkpoint_date(self, idx, col: str) -> Optional[pd.Timestamp]:
        m = _CHECKPOINT_YEARS.search(col)
        when = self.when.get(idx)
        if m and pd.notna(when):
            return when + pd.DateOffset(years=int(m.group(1)))
        if _CHECKPOINT_SEASON_END.search(col):
            y = self._year().get(idx)
            if pd.notna(y):
                return pd.Timestamp(int(y) + 1, *_SEASON_END)
        return None

    def _pid(self, idx) -> Optional[str]:
        col = _PLAYER_ID_COL.get(self.sheet)
        if col and col in self.df.columns and pd.notna(self.df.at[idx, col]):
            return str(self.df.at[idx, col]).split(".")[0]
        return None

    def counting(self, idx, col: str) -> bool:
        if self.sheet in ("rookie_picks", "non_rookie_picks"):
            undrafted = str(self.df.at[idx, "Player Picked"]).strip().lower() in ("", "nan", "unknown")
            if undrafted:                       # a pick not used yet can still be traded, nothing else
                return col == "Number of trades"
        if self.sheet in ("team_year", "player_year", "league_year", "player_all_time"):
            return bool(self.open.get(idx, False))
        clock = column_clock(self.sheet, col)
        held = bool(self.open.get(idx, False))
        if clock == "fixed":
            return False
        if clock == "always":
            return True
        if clock == "checkpoint":
            due = self._checkpoint_date(idx, col)
            return bool(due is not None and self.today < due)
        if clock == "first_start":
            starts = next((self.df.at[idx, c] for c in _START_COLS if c in self.df.columns), None)
            return held and not (pd.notna(starts) and float(starts) > 0)
        if clock == "team_now":
            pid = self._pid(idx)
            return bool(pid and self.team_of.get(pid) == str(self.df.at[idx, "Team"]))
        if clock == "sent":
            if held:
                return True
            no_players = self._empty("Player IDs received").get(idx, True)
            when = self.when.get(idx)
            return bool(no_players and pd.notna(when) and self.today < when + pd.DateOffset(years=4))
        if clock == "draft":
            years = [int(m.group(1)) for a in _split_assets(self.df.at[idx, "Assets received"])
                     if (m := _FUTURE_PICK.match(a))]
            return any(self.today < _rookie_day(y) for y in years)
        if clock == "career":
            pid = self._pid(idx)
            return bool(pid and pid in self.active)
        if clock == "next17":
            when = self.when.get(idx)
            return bool(pd.notna(when) and self.today < when + pd.DateOffset(years=1))
        return held


def board(values: pd.Series, ascending: bool, depth: int = RECORD_DEPTH) -> List[tuple]:
    """[(index, value, rank)] for the top `depth` by the digest's rule: rank is
    1 + the number strictly better; a tie is kept only if every holder fits."""
    s = values.dropna().sort_values(ascending=ascending, kind="mergesort")
    out = []
    for val, grp in s.groupby(s, sort=False):
        rank = len(out) + 1
        if rank + len(grp) - 1 > depth:
            break
        out.extend((idx, val, rank) for idx in grp.index)
    return out

# Never ranked: identifiers, links, and columns whose number is a label.
_NOT_A_STAT = re.compile(r"^(Year|Week|Season|Number|Date.*|Link .*|Player ID|.*\bID)$")

SEASON_COLUMNS = [
    "Year", "Result", "Record", "Regular season record", "Win %", "All-play win %",
    "Points", "Avg points", "Points against", "Max PF", "Efficiency", "Points left on bench",
    "Differential", "Lineup Boldness", "Drafting skill", "Trading skill", "Add/Drop skill",
    "Draft Value", "Times Highest score?", "Week of playoff elimination",
    # lotg_support.usage: the lineup's expected points vs what it scored
    "Starters' xFP", "Avg starters' xFP", "Starters' points minus xFP",
]
TEAM_SUMMARY_COLUMNS = [
    "All time record", "All time win %", "Regular season record", "Playoff record",
    "Third place game record", "Toilet bowl record", "Toilet losers game record",
    "Championships", "Number of championship appearances", "Number of playoff appearances",
    "Number of last place finishes", "Points", "Avg points", "Points against", "Efficiency",
    "All-play win %", "Avg yearly luck", "Drafting skill", "Trading skill", "Add/Drop skill",
    "Times Highest score?", "Times Lowest score?",
    "Avg weekly score", "Weekly score swing %", "Boom week %", "Bust week %", "Avg lineup riskiness",
]
# Scoring level vs swing (lotg_support.team_variance; AceMatthew's league-chat charts)
SWING_COLUMNS = [
    "Year", "Avg weekly score", "Weekly score swing", "Weekly score swing %", "Scoring style",
    "Avg weekly score (first 6 weeks)", "Weekly score swing % (first 6 weeks)",
    "Avg weekly score (to this point)", "Weekly score swing % (to this point)", "Scoring style (to this point)",
    "Avg weekly score percentile (to this point)", "Weekly score swing % percentile (to this point)",
    "Boom week %", "Bust week %",
]
RISK_COLUMNS = [
    "Year", "Avg lineup riskiness", "Avg lineup riskiness as underdog", "Avg lineup riskiness as favorite",
    "Underdog win % (risky lineup)", "Underdog win % (safe lineup)", "Avg lineup swing vs league",
    "QB-receiver stacks", "Avg swing added by stacking", "Starter pairs in the same NFL game",
    "Pairs sharing an NFL game with opponent",
]
PLAYER_SUMMARY_COLUMNS = [
    "Top team", "Last team", "Points", "Total points as starter", "PPG starter",
    "PPG starter adjusted by position", "Weeks rostered", "Weeks as starter", "% of starts",
    "Number of teams", "Number of trades", "Number of Add/Drops", "Starter PAR",
    "Championships rostered by", "Championships started by", "Times as Player of the week?",
    "Win % as starter", "xFP", "Points minus xFP",
]
PLAYER_SEASON_COLUMNS = [
    "Year", "Top Team", "Last team", "Age", "Points (full season)", "Avg points (full season)",
    "Points", "Total points as starter", "PPG starter",
    "Weeks as starter", "Weeks rostered", "Starter PAR", "Rostered by champion?",
    "Started in championship game?",
]
# Usage / opportunity per season (lotg_support.usage; rostered weeks, 2020 on).
PLAYER_USAGE_COLUMNS = [
    "Year", "Weeks with usage data", "Avg snap %", "Targets", "Carries", "Avg target share",
    "Air yards", "Red-zone opportunities", "xFP", "Avg xFP", "Points minus xFP",
    "Avg points minus xFP",
]
STINT_COLUMNS = [
    "Team", "Addition type", "Date", "Season", "Date dropped/traded", "Tenure (NFL weeks)",
    "Games played on team", "Total weeks as team starter (all stints)", "Avg PPG on team",
    "Points added", "Price paid (FAAB)", "Player addition value", "KTC at pickup",
    "KTC change 1 year after pickup", "FAAB Value at pickup", "FAAB Value change 1 year after pickup",
]
TRADE_SIDE_COLUMNS = [
    "Pick value received", "Trade impact score", "Wins added", "Net points", "Avg net points",
    "Trade addition value", "O-Score", "Asset difference in average age", "Tanking",
    "KTC value difference at deal time", "KTC value difference at end of season",
    "KTC value difference 1 year later", "KTC value difference 2 years later",
    "Pick FAAB Value received",
    "FAAB Value difference at deal time", "FAAB Value difference at end of season",
    "FAAB Value difference 1 year later", "FAAB Value difference 2 years later",
]
KTC_TIMELINE = [
    ("Deal", "KTC value difference at deal time"),
    ("Season end", "KTC value difference at end of season"),
    ("+1 yr", "KTC value difference 1 year later"),
    ("+2 yr", "KTC value difference 2 years later"),
]
# The same timeline in the league's FAAB dollars (the FAAB value system: lotg_support.faab_history).
FAAB_TIMELINE = [(lab, c.replace("KTC value difference", "FAAB Value difference")) for lab, c in KTC_TIMELINE]
DRAFT_COLUMNS = [
    "Year", "Number", "Player Picked", "Team", "Original Team", "Age when drafted",
    "KTC on draft day", "KTC at end of rookie year", "KTC 1 year after draft day",
    "KTC 2 years after draft day", "KTC 3 years after draft day",
    "Pick-adjusted Difference in KTC on draft day",
    "Pick-adjusted Difference in KTC 1 year after draft day",
    "FAAB Value on draft day", "FAAB Value at end of rookie year", "FAAB Value 1 year after draft day",
    "FAAB Value 2 years after draft day", "FAAB Value 3 years after draft day",
    "Pick-adjusted Difference in FAAB Value on draft day",
    "Pick-adjusted Difference in FAAB Value 1 year after draft day",
    "Avg PPG on team", "Points added", "Player addition value",
    "Pick-adjusted Difference in Player addition value", "O-Score",
    "% of starts made while rostered by drafting team", "Number of trades",
]


# ---------------------------------------------------------------- helpers

def _display(column: str, sheet: str = "") -> str:
    try:
        from .digest import display_column
        return display_column(column, sheet)
    except Exception:                                  # pragma: no cover - digest import is heavy
        return column[:-1] if column.endswith("?") else column


def column_format(column: str) -> Dict[str, object]:
    """How the workbook shows `column`: decimal places, and whether a percent
    is a 0-1 fraction shown x100 ("x") or a 0-100 number with a % sign ("%")."""
    fmt = NF.col_number_format(column)
    places = NF.decimals(fmt)
    spec: Dict[str, object] = {}
    if places is not None:
        spec["d"] = places
    if fmt and fmt.endswith('"%"'):
        spec["p"] = "%"
    elif fmt and fmt.endswith("%"):
        spec["p"] = "x"
    return spec


def _clean(v, places: Optional[int] = None):
    """A JSON-safe cell: NaN -> None, numpy -> python, floats rounded one place
    past the workbook's (so sorting stays exact but files stay small)."""
    if v is None:
        return None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        if math.isnan(v) or math.isinf(v):
            return None
        v = float(v)
        if places is not None:
            v = round(v, places + 3)
        return int(v) if v.is_integer() and abs(v) < 2**53 else v
    if isinstance(v, str):
        return v if v not in ("", "nan", "N/A") else None
    return v


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s or "x"


def _read(sheet: str) -> pd.DataFrame:
    path = EXPORTS / f"{sheet}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _numeric(df: pd.DataFrame, col: str) -> pd.Series:
    s = df[col]
    if pd.api.types.is_bool_dtype(s):
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(s, errors="coerce")


def _records(df: pd.DataFrame, columns: Iterable[str]) -> List[list]:
    cols = [c for c in columns if c in df.columns]
    places = {c: NF.decimals(NF.col_number_format(c)) for c in cols}
    return [[_clean(v, places[c]) for c, v in zip(cols, row)] for row in df[cols].values]


def _table(df: pd.DataFrame, columns: Iterable[str], sheet: str = "") -> Dict[str, object]:
    """A compact table: column names once, then rows as lists."""
    cols = [c for c in columns if c in df.columns]
    return {"cols": cols, "labels": [_display(c, sheet) for c in cols],
            "fmt": {c: column_format(c) for c in cols}, "rows": _records(df, cols)}


def _dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def _split_assets(text) -> List[str]:
    if not isinstance(text, str):
        return []
    return [a.strip() for a in text.split(";") if a.strip()]


# ---------------------------------------------------------------- digest

class _DigestParser(HTMLParser):
    """The emailed digest -> title, lede and sections of plain-text items."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.lede = ""
        self.sections: List[dict] = []
        self._tag: List[str] = []
        self._buf: List[str] = []
        self._grab: Optional[str] = None
        self._li_depth = 0
        self._edits = False

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3"):
            self._flush()
            self._grab, self._buf = tag, []
        elif tag == "li":
            if self._li_depth == 0:
                self._flush()
                self._grab, self._buf = "li", []
            else:
                self._buf.append(" · ")
            self._li_depth += 1
        elif tag == "p" and self._grab is None and not self.lede and self.title:
            self._grab, self._buf = "p", []

    def handle_endtag(self, tag):
        if tag == "li":
            self._li_depth = max(0, self._li_depth - 1)
            if self._li_depth == 0:
                self._flush()
        elif tag in ("h1", "h2", "h3", "p") and self._grab == tag:
            self._flush()

    def handle_data(self, data):
        if self._grab:
            self._buf.append(data)

    def _flush(self):
        if not self._grab:
            return
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip(" ·")
        kind, self._grab, self._buf = self._grab, None, []
        if not text:
            return
        if kind == "h1":
            self.title = text
        elif kind == "p":
            if not text.lower().startswith(("rate the board", "league site")):
                self.lede = text
        elif kind == "h2":
            self._edits = self._edits or text.lower().startswith("changes from edits")
            self.sections.append({"group": text, "title": text, "items": [], "edits": self._edits})
        elif kind == "h3":
            group = self.sections[-1]["group"] if self.sections else ""
            self.sections.append({"group": group, "title": text, "items": [], "edits": self._edits})
        elif kind == "li" and self.sections:
            self.sections[-1]["items"].append(text)


def digest_items(path: Path = DIGEST_HTML) -> Dict[str, object]:
    if not path.exists():
        return {"title": "", "lede": "", "sections": []}
    p = _DigestParser()
    p.feed(path.read_text(encoding="utf-8"))
    p._flush()
    sections = [s for s in p.sections if s["items"]]
    return {"title": html.unescape(p.title), "lede": p.lede, "sections": sections}


# ---------------------------------------------------------------- forecast

def replay_sims(sims: "np.ndarray", weeks: Sequence[int], rids: Sequence[int], names: Sequence[str],
                obs: Dict[int, List[int]], pairs: Dict[int, List[Tuple[int, int]]], regular_weeks: int,
                playoff_teams: int, semifinal_week: int, final_weeks: Sequence[int],
                bonus: int) -> Dict[str, Dict[str, float]]:
    """Playoff / final / title / 1st-seed counts and total wins from simulated
    seasons, in integer hundredths of a point so it is exact — site/app.js
    `replaySims` is this line for line, which is what makes the predictions
    page's baseline the home page's odds to the decimal.

    sims    sims x len(weeks) x len(rids), raw points in hundredths (no +5)
    obs     {played week: [hundredths per rid]}; pairs {week: [(i, j)]} as rid
            indexes; the table is wins + ½ ties, then PF, then the team's name
            (lotg_support.replay._standings), the bracket 1v4 / 2v3 with +bonus to
            the higher seed (ties to him), the final over `final_weeks` (ties to
            the 1v4 side) — replay._bracket."""
    n = len(rids)
    col = {w: j for j, w in enumerate(weeks)}
    order_name = sorted(range(n), key=lambda k: names[k])
    rank_name = {k: i for i, k in enumerate(order_name)}
    out = {nm: {"playoffs": 0, "final": 0, "title": 0, "seed1": 0, "wins": 0.0} for nm in names}
    rows = sims.tolist() if hasattr(sims, "tolist") else sims
    for sim in rows:
        def pts(w, k, sim=sim):
            return sim[col[w]][k] if w in col else (obs.get(w) or [0] * n)[k]
        half = [0] * n
        pf = [0] * n
        for w in range(1, regular_weeks + 1):
            if w not in col and w not in obs:
                continue
            for a, b in pairs.get(w, ()):
                x, y = pts(w, a), pts(w, b)
                pf[a] += x
                pf[b] += y
                if x > y:
                    half[a] += 2
                elif y > x:
                    half[b] += 2
                else:
                    half[a] += 1
                    half[b] += 1
        table = sorted(range(n), key=lambda k: (-half[k], -pf[k], rank_name[k]))
        for k in range(n):
            out[names[k]]["wins"] += half[k] / 2
        for k in table[:playoff_teams]:
            out[names[k]]["playoffs"] += 1
        out[names[table[0]]]["seed1"] += 1
        if playoff_teams < 4 or (semifinal_week not in col and semifinal_week not in obs):
            continue
        sd = table[:4]
        win = [hi if pts(semifinal_week, hi) + bonus >= pts(semifinal_week, lo) else lo
               for hi, lo in ((sd[0], sd[3]), (sd[1], sd[2]))]
        for k in win:
            out[names[k]]["final"] += 1
        fw = [w for w in final_weeks if w in col or w in obs]
        if not fw:
            continue
        a, b = win
        champ = a if sum(pts(w, a) for w in fw) >= sum(pts(w, b) for w in fw) else b
        out[names[champ]]["title"] += 1
    return out


def forecast_odds(year: int, sims: int = 20000) -> Optional[Dict[str, object]]:
    """Title / finals / playoff odds from lotg_support.forecast, or None if the
    forecast cannot run (the site still builds without it).

    The simulated seasons themselves go to the site too (key "_sims", written by
    `Site.build` as data/forecast_sims.bin: int16 tenths of a point, sims x
    weeks x teams): the predictions page replays exactly these seasons, so its
    no-changes odds are these odds. The odds here are counted from those same
    rounded scores (`replay_sims`), so both pages agree to the decimal."""
    try:
        import warnings
        from . import forecast as F
        from . import inquiry as Q
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fc = F.forecast(year, sims=sims, keep_scores=True)
    except Exception as exc:                            # pragma: no cover - depends on snapshot
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}
    meta = Q.season_meta(year)
    teams = Q.teams(year)
    rids = list(fc.sim_rids)
    names = [teams[r] for r in rids]
    idx = {r: k for k, r in enumerate(rids)}
    tenths = np.clip(np.rint(fc.sim_scores * 10), -32768, 32767).astype("<i2")
    obs_raw = {w: s for w, s in F._observed_scores(year).items() if w in fc.played_weeks}
    obs = {w: [int(round(float(s.get(r, 0.0)) * 100)) for r in rids] for w, s in obs_raw.items()}
    pairs = {w: [(idx[a], idx[b]) for a, b in Q.pairings(year, w) if a in idx and b in idx]
             for w in range(1, meta.regular_season_weeks + 1)}
    bonus = int(round(Q.SEMIFINAL_HOME_BONUS * 100))
    counts = replay_sims(tenths.astype(np.int64) * 10, fc.sim_weeks, rids, names, obs, pairs,
                         meta.regular_season_weeks, meta.playoff_teams, meta.semifinal_week,
                         list(meta.finals_weeks), bonus)
    n = max(fc.sims, 1)
    by = {o.team: o for o in fc.odds}
    rows = [{"team": t, "champion": round(100 * c["title"] / n, 1), "finals": round(100 * c["final"] / n, 1),
             "playoffs": round(100 * c["playoffs"] / n, 1), "wins": round(c["wins"] / n, 2),
             "pf": round(by[t].expected_pf, 2),
             "next": None if by[t].next_week is None else round(by[t].next_week, 2)}
            for t, c in counts.items()]
    rows.sort(key=lambda r: (-r["champion"], -r["finals"], -r["playoffs"], r["team"]))
    # P(he plays) in each remaining week, per Sleeper id, from the forecast's injury
    # model — what the predictions page draws its lineups from (site/app.js predict)
    avail = {pid: [round(float(x), 3) for x in v] for pid, v in fc.player_availability.items()}
    # what ESPN's daily injury capture (lotg_support.espn_injuries) did to each
    # rostered player: "ESPN: out for season (acl tear)" / "ESPN: est. back wk 13"
    from . import espn_injuries as ESPN
    at = ESPN.captured_at(year) if fc.injury_basis else None
    return {"year": year, "sims": fc.sims, "played": list(fc.played_weeks), "odds": rows,
            "avail": avail, "avail_from": fc.availability_from_week,
            "espn": dict(sorted(fc.espn_timelines.items())),
            # every hurt / tagged / ESPN-listed player: [ESPN timeline, what the odds assume]
            "injuries": {k: list(v) for k, v in sorted(fc.injury_basis.items())},
            "espn_at": at.isoformat(timespec="minutes") if at else None,
            # how the predictions page replays the same seasons (site/app.js predict)
            "sim": {"file": "forecast_sims.bin", "weeks": list(fc.sim_weeks), "teams": names,
                    "obs": {str(w): v for w, v in obs.items()},
                    "pairs": {str(w): [list(p) for p in v] for w, v in pairs.items()},
                    "regular_weeks": meta.regular_season_weeks, "playoff_teams": meta.playoff_teams,
                    "semifinal_week": meta.semifinal_week, "final_weeks": list(meta.finals_weeks),
                    "bonus": bonus,
                    # a roster move shifts a team's simulated weeks by slope x the
                    # change in its fielded lineup — the calibration that turns a
                    # projection gap into a points gap (forecast.Calibration.slope)
                    "slope": round(float(fc.calibration.slope), 4),
                    "rates": {k: round(v, 2) for k, v in sorted(fc.player_rates.items())}},
            "_sims": tenths}


def _kind_records(x: pd.DataFrame) -> Dict[str, int]:
    """Wins and losses per week type: {"regw": .., "regl": .., "playoffsw": ..}."""
    out = {}
    for k in WEEK_KINDS:
        y = x[x.Kind == k]
        out[k + "w"], out[k + "l"] = int(y.W.sum()), int((~y.W).sum())
    for k in EXTRA_VIEWS:
        y = x[x["Week Name"].map(lambda n, k=k: in_view(k, n))]
        out[k + "w"], out[k + "l"] = int(y.W.sum()), int((~y.W).sum())
    return out


def _zero_sum(values: pd.Series, deal: pd.Series) -> bool:
    """True when, trade by trade, the sides' values cancel (a KTC difference, net
    points): then the bottom of the board is only the top's other sides."""
    both = pd.DataFrame({"v": values, "k": deal}).dropna()
    if both.empty:
        return False
    sums = both.groupby("k")["v"].agg(["sum", "count", lambda x: x.abs().max()])
    sums.columns = ["sum", "count", "mag"]
    two = sums[(sums["count"] >= 2) & (sums["mag"] > 0)]
    return len(two) >= 10 and float(((two["sum"].abs() <= 0.01 * two["mag"] + 1e-6)).mean()) >= 0.95


# ---------------------------------------------------------------- data explorer

CHUNK_BYTES = 1_500_000          # a sheet bigger than this as CSV is split by season
GLOSSARY_SHEET = "formulas"      # exports/formulas.csv: every column's definition


def export_sheets() -> List[str]:
    """Every sheet in exports/ (the 14 tables and the formulas glossary)."""
    return sorted(p.stem for p in EXPORTS.glob("*.csv"))


def _season_key(df: pd.DataFrame) -> Optional[str]:
    for c in ("Year", "Season"):
        if c in df.columns:
            return c
    return None


# formulas.csv defines a few identity columns once for every sheet, in one sheet's
# words ("Team: the team that actually MADE the selection" is the pick sheets').
# The site says what they mean on each sheet.
_IDENTITY_DEFS = {
    "Team": {"*": "The fantasy team (manager) this row is about.",
             "rookie_picks": None, "non_rookie_picks": None,       # their own definition is right
             "trades": "The team on this side of the trade (the trades sheet has one row per team).",
             "add_drops": "The team that made the add/drop.",
             "player_week": "The fantasy team that rostered the player that week."},
    "Opponent": {"*": "The team played that week."},
    "Year": {"*": "Season."}, "Week": {"*": "Week of the season (1-based)."},
    "Week Name": {"*": "The week as the league names it: Week N in the regular season, or the playoff / consolation game."},
    "Player": {"*": "The player this row is about."},
}


def _defs_by_sheet() -> Dict[str, Dict[str, str]]:
    """formulas.csv -> {sheet: {column: definition}}; a row whose Sheet lists
    several sheets ("team_year / team_all_time") defines the column on each."""
    f = _read(GLOSSARY_SHEET)
    out: Dict[str, Dict[str, str]] = {}
    if f.empty:
        return out
    for _, r in f.iterrows():
        text = " ".join(str(x) for x in (r.get("Formula"), r.get("Notes")) if isinstance(x, str) and x.strip())
        for sheet in str(r.get("Sheet", "")).split("/"):
            out.setdefault(sheet.strip(), {})[str(r["Stat"])] = text
    for col, per in _IDENTITY_DEFS.items():
        for sheet in list(out):
            text = per.get(sheet, per["*"]) if sheet in per or "*" in per else None
            if text:
                out[sheet][col] = text
    return out


def sheet_chunks(sheet: str, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """The sheet whole ("all"), or split by season when its CSV is large."""
    path = EXPORTS / f"{sheet}.csv"
    key = _season_key(df)
    if key is None or not path.exists() or path.stat().st_size <= CHUNK_BYTES:
        return {"all": df}
    vals = df[key].astype(str).str.replace(r"\.0$", "", regex=True)
    return {v: df[vals == v] for v in sorted(vals.unique())}


# ---------------------------------------------------------------- future picks

PICK_HORIZON = 5                 # drafts ahead, as the build's Future draft capital (_FCAP_HORIZON)
PICK_ROUNDS = 4
FUTURE_PICK_WEIGHTS = {1: 0.25, 2: 0.09, 3: 0.03, 4: 0.01}   # src/lotg.py _FUTURE_PICK_WEIGHTS
_PICK_LABEL = re.compile(r"^(\d{4}) (\d)(?:\.\d\d)?\((.+)\)$")   # "2028 3(AceMatthew)", "2027 1.05(x)"


def _sleeper_pick_owners(season: int, canon: Dict[str, str]) -> Dict[tuple, str]:
    """(year, round, original team) -> current owner, from the committed
    snapshot's traded_picks.json (only picks that moved are listed)."""
    base = EXPORTS / "snapshot" / f"season_{int(season)}"
    try:
        users = {u["user_id"]: u["display_name"] for u in json.loads((base / "users.json").read_text())}
        rosters = {r["roster_id"]: users.get(r["owner_id"], "")
                   for r in json.loads((base / "rosters.json").read_text())}
        traded = json.loads((base / "traded_picks.json").read_text())
    except (OSError, ValueError):
        return {}
    name = lambda rid: canon.get(str(rosters.get(rid, "")).lower())
    return {(int(p["season"]), int(p["round"]), name(p["roster_id"])): name(p["owner_id"])
            for p in traded if name(p["roster_id"]) and name(p["owner_id"])}


def _league_id(season: int) -> Optional[str]:
    try:
        return str(json.loads((EXPORTS / "snapshot" / f"season_{int(season)}" / "league.json").read_text())["league_id"])
    except (OSError, ValueError, KeyError):
        return None


def nfl_players(extra_ids: Iterable[str] = (), ages: Optional[Dict[str, float]] = None) -> Dict[str, list]:
    """Sleeper id -> [name, position, NFL team, age] for every active QB/RB/WR/TE
    plus anyone rostered: the live roster layer gets ids only from Sleeper. Age is
    player_year's for the current season (the build's), where the build has one."""
    ages = ages or {}
    path = EXPORTS / "snapshot" / "sleeper_players_nfl.json"
    if not path.exists():
        return {}
    players = json.loads(path.read_text())
    keep = set(map(str, extra_ids))
    out = {}
    for pid, v in players.items():
        if (v.get("position") in ("QB", "RB", "WR", "TE") and v.get("active")) or pid in keep:
            name = v.get("full_name") or f"{v.get('first_name', '')} {v.get('last_name', '')}".strip()
            out[pid] = [name, v.get("position"), v.get("team"), ages.get(pid), v.get("injury_status"),
                        v.get("depth_chart_order"), v.get("depth_chart_position")]
    return out


# The weekly award flags shown on a matchup (team_week / player_week "...?" columns).
TEAM_AWARDS = ["Highest score?", "Lowest score?", "Largest blowout?", "Narrowest victory?",
               "Most efficient?", "Least efficient?", "Podium?", "Top half of league?", "One-man army?",
               "Most bench points?", "Most injured?", "Boom week?", "Bust week?",
               "Loss from hardship?", "Win from bye?", "Loss from bye?"]
PLAYER_AWARDS = ["Player of the week?", "QB of the week?", "RB of the week?", "WR of the week?",
                 "TE of the week?", "Benchwarmer of the week?", "Bench QB of the week?",
                 "Bench RB of the week?", "Bench WR of the week?", "Bench TE of the week?",
                 "Dud of the week?", "Roster dud of the week?",
                 "Highest starter on team?", "Lowest starter on team?", "Captain?"]


def _award_name(col: str) -> str:
    return col[:-1] if col.endswith("?") else col


# ---------------------------------------------------------------- builders

_TRADE_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}): (?:pick )?traded to (.+?) \(")
_PICK_HEAD = re.compile(r"^(\d{4}) (\d+\.\d+)")
SLOT_ORDER = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "FLX": 4, "FLEX": 4, "WRT": 4, "SFLX": 5, "SUPER_FLEX": 5}


class Site:
    def __init__(self, workbook=None):
        self.tw = _read("team_week")
        self.ty = _read("team_year")
        self.ta = _read("team_all_time")
        self.pw = _read("player_week")
        self.py = _read("player_year")
        self.pa = _read("player_all_time")
        self.adds = _read("player_additions")
        self.trades = _read("trades")
        self.rookie = _read("rookie_picks")
        self.startup = _read("non_rookie_picks")
        for df in (self.tw, self.ty, self.pw, self.py):
            if "Year" in df:
                df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        self.teams = sorted(self.ta["Team"].dropna().astype(str).unique()) if len(self.ta) else []
        self.season = int(self.tw["Year"].max())
        cur = self.tw[self.tw["Year"] == self.season]
        self.week = int(pd.to_numeric(cur["Week"], errors="coerce").max())
        self._player_slugs()
        self.workbook = workbook
        self._trades: List[dict] = []
        self._trade_ids: Dict[tuple, int] = {}
        self._histories = WC.histories(workbook) if workbook else None

    # -- identity
    def _player_slugs(self):
        """Player page keys: the Player ID column once it lands in the exports
        (a sibling PR adds it), else a name slug — namesakes get -2, -3."""
        names = pd.concat([self.pa.get("Player", pd.Series(dtype=str)),
                           self.pw.get("Player", pd.Series(dtype=str))]).dropna().astype(str)
        ids: Dict[str, str] = {}
        if "Player ID" in self.pa.columns:
            for n, pid in zip(self.pa["Player"], self.pa["Player ID"]):
                if pd.notna(pid):
                    ids[str(n)] = str(pid).split(".")[0]
        self.slugs: Dict[str, str] = {}
        used: set = set()
        for n in sorted(set(names)):
            key = ids.get(n) or slug(n)
            base, i = key, 2
            while key in used:
                key, i = f"{base}-{i}", i + 1
            used.add(key)
            self.slugs[n] = key

    def _positions(self) -> Dict[str, str]:
        pw = self.pw.dropna(subset=["Position"])
        return pw.groupby("Player")["Position"].last().astype(str).to_dict()

    def meta(self) -> Dict[str, object]:
        return {"season": self.season, "week": self.week,
                "week_name": str(self.tw[(self.tw.Year == self.season)
                                         & (pd.to_numeric(self.tw.Week, errors="coerce") == self.week)]
                                 ["Week Name"].iloc[0]),
                "teams": self.teams, "built": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
                "seasons": sorted(int(y) for y in self.tw["Year"].dropna().unique()),
                # the live layer: the page reads this league's rosters and traded picks
                # straight from Sleeper on open (lotg_support.league_site docs)
                "league_id": _league_id(self.season),
                # which main build the stats came from (site.yml passes it)
                "build_run": os.environ.get("LOTG_BUILD_RUN") or None,
                "build_time": os.environ.get("LOTG_BUILD_TIME") or None}

    # -- home
    def standings(self) -> List[dict]:
        cur = self.tw[(self.tw.Year == self.season)
                      & self.tw["Week Name"].astype(str).str.startswith("Week ")].copy()
        cur["PF"] = pd.to_numeric(cur["PF"], errors="coerce")
        cur["Max PF"] = pd.to_numeric(cur.get("Max PF"), errors="coerce")
        cur["Points against"] = pd.to_numeric(cur["Points against"], errors="coerce")
        cur["W"] = cur["Win?"].astype(str).str.lower().eq("true")
        # all-play: beat how many of the week's other scores
        cur["AP"] = cur.groupby("Week")["PF"].rank(method="min") - 1
        cur["APN"] = cur.groupby("Week")["PF"].transform("count") - 1
        out = []
        for team, g in cur.groupby("Team"):
            g = g.sort_values("Week")
            w = int(g.W.sum())
            streak = ""
            if len(g):
                last = g.W.iloc[-1]
                n = 0
                for x in reversed(g.W.tolist()):
                    if x != last:
                        break
                    n += 1
                streak = f"{'W' if last else 'L'}{n}"
            out.append({"team": team, "w": w, "l": int(len(g) - w),
                        "pf": round(float(g.PF.sum()), 2), "pa": round(float(g["Points against"].sum()), 2),
                        # the most the team could have scored with its best lineup each week
                        "max_pf": round(float(g["Max PF"].sum()), 2) if g["Max PF"].notna().any() else None,
                        "ap": f"{int(g.AP.sum())}-{int((g.APN - g.AP).sum())}",
                        "streak": streak,
                        "form": "".join("W" if x else "L" for x in g.W.tail(5))})
        out.sort(key=lambda r: (-r["w"], -r["pf"]))
        for i, r in enumerate(out, 1):
            r["rank"] = i
        return out

    def latest_results(self) -> List[dict]:
        wk = self.tw[(self.tw.Year == self.season)
                     & (pd.to_numeric(self.tw.Week, errors="coerce") == self.week)]
        seen, games = set(), []
        for _, r in wk.iterrows():
            pair = tuple(sorted((str(r.Team), str(r.Opponent))))
            if pair in seen or pd.isna(r.Opponent):
                continue
            seen.add(pair)
            o = wk[wk.Team == r.Opponent]
            games.append({"a": r.Team, "b": r.Opponent, "pa": _clean(pd.to_numeric(r.PF, errors="coerce"), 2),
                          "pb": _clean(pd.to_numeric(o.PF.iloc[0], errors="coerce"), 2) if len(o) else None,
                          "win": str(r["Win?"]).lower() == "true"})
        return games

    def home(self, odds) -> Dict[str, object]:
        return {"standings": self.standings(), "results": self.latest_results(),
                "forecast": odds, "digest": digest_items()}

    # -- records
    def records(self, sheet: str) -> Dict[str, object]:
        """Every numeric column's top and bottom 5 (digest tie rule). Week
        sheets also get a board per week type; trades rank one row per trade,
        and a zero-sum trade column (one side's gain is the other's loss) shows
        only its top, since its bottom is the same trades seen from the
        other side."""
        df = _read(sheet)
        if df.empty:
            return {"sheet": sheet, "columns": []}
        labels = tuple(c for c in RECORD_SHEETS.get(sheet, ()) if c in df.columns) or tuple(df.columns[:3])
        flag_text = STILL_COUNTING.get(sheet)
        counting = Counting(sheet, df, self.season, self.rostered_now(), team_of=self.roster_team(),
                            active=self.active_ids()) if flag_text else None
        scopes = {"all": df.index}
        if "Week Name" in df.columns:
            kinds = df["Week Name"].map(week_kind)
            scopes.update({k: df.index[kinds == k] for k in WEEK_KINDS})
            scopes.update({k: df.index[df["Week Name"].map(lambda n, k=k: in_view(k, n))] for k in EXTRA_VIEWS})
        deal = None
        if sheet == "trades":
            partners = [c for c in df.columns if c.startswith("Team's traded with")]
            deal = pd.Series([(str(d), frozenset([str(t)] + [str(r[c]) for c in partners if pd.notna(r[c])]))
                              for d, t, (_, r) in zip(df["Date"], df["Team"], df.iterrows())], index=df.index)
        cols = []
        for c in df.columns:
            if c in labels or _NOT_A_STAT.match(str(c)):
                continue
            v = _numeric(df, c)
            ok = v.notna()
            if ok.sum() < 3 or v[ok].nunique() < 2:
                continue
            places = NF.decimals(NF.col_number_format(c))
            entry = {"col": c, "label": _display(c, sheet), "fmt": column_format(c), "n": int(ok.sum()),
                     "scopes": {}}
            mirror = deal is not None and _zero_sum(v, deal)
            if mirror:
                entry["mirror"] = True
            for scope, index in scopes.items():
                vals = v.loc[index]
                if vals.notna().sum() < 1:
                    continue
                out = {}
                for end, asc in (("hi", False), ("lo", True)):
                    if mirror and end == "lo":
                        continue
                    if deal is not None:        # one row per trade: its best side for this end
                        order = vals.dropna().sort_values(ascending=asc, kind="mergesort")
                        vals_end = order[~deal.loc[order.index].duplicated()]
                    else:
                        vals_end = vals
                    out[end] = [[_clean(val, places), [_clean(df.at[idx, lab]) for lab in labels],
                                 bool(counting and counting.counting(idx, c)), rank,
                                 self.row_link(sheet, df, idx, deal)]
                                for idx, val, rank in board(vals_end, asc)]
                entry["scopes"][scope] = out
            cols.append(entry)
        return {"sheet": sheet, "labels": list(labels), "flag": flag_text, "live_season": self.season,
                "scopes": [k for k in scopes], "scope_names": {"all": "All weeks", **WEEK_KINDS, **EXTRA_VIEWS},
                "depth": RECORD_DEPTH, "columns": cols}

    def roster_team(self) -> Dict[str, str]:
        """Sleeper id -> the team he is on in the latest built week."""
        cur = self.current_roster()
        if "Player ID" not in cur:
            return {}
        return {str(p).split(".")[0]: str(t) for p, t in zip(cur["Player ID"], cur["Team"]) if pd.notna(p)}

    def active_ids(self) -> set:
        """Sleeper ids the player dictionary marks active (any position)."""
        if not hasattr(self, "_active"):
            path = EXPORTS / "snapshot" / "sleeper_players_nfl.json"
            self._active = ({pid for pid, v in json.loads(path.read_text()).items() if v.get("active")}
                            if path.exists() else set())
        return self._active

    def rostered_now(self) -> set:
        """Sleeper ids (and names) on a roster in the latest built week."""
        if not hasattr(self, "_rostered"):
            cur = self.current_roster()
            ids = set(cur["Player ID"].astype(str).str.split(".").str[0]) if "Player ID" in cur else set()
            self._rostered = ids | set(cur["Player"].astype(str))
        return self._rostered

    # -- where a row's details live
    def row_link(self, sheet: str, df: pd.DataFrame, idx, deal: Optional[pd.Series] = None) -> Optional[str]:
        """The site route that shows a row of `sheet` in full: the trade, the
        matchup, the player, the pick, the team or the week."""
        r = df.loc[idx]
        get = lambda c: r[c] if c in df.columns and pd.notna(r[c]) else None
        if sheet == "trades" and deal is not None:
            tid = self._trade_ids.get(deal.loc[idx])
            return f"trades/{tid}" if tid else None
        if sheet == "team_week":
            y, w, t = get("Year"), get("Week"), get("Team")
            return f"game/{int(float(y))}/{int(float(w))}/{slug(t)}" if y is not None and w is not None and t else None
        if sheet == "league_week":
            y, w = get("Year"), get("Week")
            return f"week/{int(float(y))}/{int(float(w))}" if y is not None and w is not None else None
        if sheet in ("rookie_picks", "non_rookie_picks"):
            return f"pick/{sheet}/{int(df.index.get_loc(idx))}"
        name = get("Player") or get("Player Added") or get("Player Dropped") or get("Player Picked")
        if name and str(name) in self.slugs:
            return f"player/{self.slugs[str(name)]}"
        team = get("Team")
        if team and str(team) in self.teams:
            return f"team/{slug(team)}"
        return None

    # -- one week: every matchup with both lineups
    def weeks(self, put) -> int:
        pw = self.pw.copy()
        pw["Points"] = pd.to_numeric(pw.Points, errors="coerce")
        pw["Wk"] = pd.to_numeric(pw.Week, errors="coerce")
        tw = self.tw.copy()
        tw["Wk"] = pd.to_numeric(tw.Week, errors="coerce")
        n = 0
        for (y, w), g in tw.groupby(["Year", "Wk"]):
            players = pw[(pw.Year == y) & (pw.Wk == w)]
            teams = {}
            for _, r in g.iterrows():
                mine = players[players.Team == r.Team].copy()
                mine["st"] = mine["Starter/Bench"].astype(str) == "Starter"
                raw = mine["Position started in (if starter)"].astype(str)
                slot = raw.str.replace(r"\d+$", "", regex=True)
                num = pd.to_numeric(raw.str.extract(r"(\d+)$")[0], errors="coerce").fillna(0)
                mine["o"] = [SLOT_ORDER.get(x, 6) if st else 9 for x, st in zip(slot, mine.st)]
                mine["n"] = num.values
                mine = mine.sort_values(["o", "n", "Points"], ascending=[True, True, False])
                teams[str(r.Team)] = {
                    "awards": [_award_name(c) for c in TEAM_AWARDS
                               if c in r.index and str(r[c]).lower() == "true"],
                    "opp": _clean(r.Opponent), "pf": _clean(pd.to_numeric(r.PF, errors="coerce"), 2),
                    "pa": _clean(pd.to_numeric(r["Points against"], errors="coerce"), 2),
                    "win": str(r["Win?"]).lower() == "true",
                    "max": _clean(pd.to_numeric(r.get("Max PF"), errors="coerce"), 2),
                    "players": [[p.Player, self.slugs.get(str(p.Player)), _clean(p.Position),
                                 _clean(p["Position started in (if starter)"]) if p.st else None,
                                 _clean(p.Points, 2), bool(p.st), _clean(p.get("NFL team")),
                                 [_award_name(c) for c in PLAYER_AWARDS
                                  if c in p.index and str(p[c]).lower() == "true"]]
                                for _, p in mine.iterrows()]}
            put(f"week/{int(y)}-{int(w)}.json", {"year": int(y), "week": int(w),
                                                  "week_name": str(g["Week Name"].iloc[0]), "teams": teams})
            n += 1
        return n

    # -- asset histories (the workbook's hover comments)
    def _history_lines(self, text: str) -> List[list]:
        """Each line of a history, with the trade it names linked when found."""
        out = []
        by_day: Dict[tuple, int] = {}
        for (date, teams), tid in self._trade_ids.items():
            for t in teams:
                by_day.setdefault((date[:10], t), tid)
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = _TRADE_LINE.match(line)
            out.append([line, f"trades/{by_day[(m.group(1), m.group(2))]}"
                        if m and (m.group(1), m.group(2)) in by_day else None])
        return out

    def player_histories(self) -> Dict[str, List[list]]:
        h = (self._histories or {}).get("player_all_time") or []
        names = list(self.pa["Player"].astype(str)) if "Player" in self.pa else []
        out = {}
        for row, col_a, text in h:
            # trust a comment only where column A still names the same player
            if row < len(names) and names[row] == str(col_a):
                out[str(col_a)] = self._history_lines(text)
        return out

    def pick_histories(self) -> Dict[str, Dict[int, List[list]]]:
        out: Dict[str, Dict[int, List[list]]] = {}
        for sheet, df in (("rookie_picks", self.rookie), ("non_rookie_picks", self.startup)):
            rows = {}
            for row, col_a, text in (self._histories or {}).get(sheet) or []:
                if row >= len(df) or str(df.iloc[row]["Year"]) != str(col_a):
                    continue
                rows[row] = self._history_lines(text)
            out[sheet] = rows
        return out

    # -- the All-time standings page: every team_all_time column but head to head
    def all_time_standings(self) -> Dict[str, object]:
        """team_all_time minus its per-opponent columns ("Record vs X", "Win % vs
        X", best / worst team record against): those live on Head to head."""
        opp = re.compile(r"^(Record|Win %) vs (" + "|".join(map(re.escape, self.teams)) + r")$")
        h2h_cols = {"Highest Win % vs a team", "Team for highest Win %", "Lowest Win % vs a team",
                    "Team for lowest Win %"}
        cols = [c for c in self.ta.columns if not opp.match(str(c)) and c not in h2h_cols]
        return _table(self.ta, cols, "team_all_time")

    # -- the home page's live record watch: where this week's numbers would rank
    def record_watch(self) -> Dict[str, object]:
        """Every all-time value of the stats a live week can set, sorted, plus
        each board's top 5 with who holds it. The page reads this week's scores
        from Sleeper and ranks them against these. Team PF here includes the
        semifinal +5 (live Sleeper points do not; noted on the page)."""
        tw = self.tw.copy()
        for c in ("PF", "Points against", "Margin"):
            tw[c] = pd.to_numeric(tw[c], errors="coerce")
        win = tw["Win?"].astype(str).str.lower().eq("true")
        lab = lambda d: [[str(r.Team), int(r.Year), str(r["Week Name"]), _clean(r.Opponent)] for _, r in d.iterrows()]

        def board_of(series: pd.Series, frame: pd.DataFrame, high: bool = True) -> dict:
            s = series.dropna().sort_values(ascending=not high, kind="mergesort")
            top = frame.loc[s.index[:5]]
            return {"values": [round(float(v), 2) for v in s], "top": [[round(float(v), 2), *l]
                                                                        for v, l in zip(s[:5], lab(top))]}
        games = tw[tw.Team < tw.Opponent.astype(str)]          # one row per game
        pw = self.pw.copy()
        pw["Points"] = pd.to_numeric(pw.Points, errors="coerce")
        st = pw[pw["Starter/Bench"].astype(str) == "Starter"].dropna(subset=["Points"])
        st = st.sort_values("Points", ascending=False, kind="mergesort")
        return {
            "team": {
                "Most points in a week": board_of(tw.PF, tw),
                "Fewest points in a week": board_of(tw.PF, tw, high=False),
                "Most points in a loss": board_of(tw.PF[~win], tw),
                "Fewest points in a win": board_of(tw.PF[win], tw, high=False),
                "Biggest margin of victory": board_of(tw.Margin[win], tw),
                "Most combined points in a game": board_of((games.PF + games["Points against"]), games),
            },
            "player": {"Most points by a starter": {
                "values": [round(float(v), 2) for v in st.Points.head(400)], "count": int(len(st)),
                "top": [[round(float(r.Points), 2), str(r.Player), str(r.Team), int(r.Year), str(r["Week Name"])]
                        for _, r in st.head(5).iterrows()]}},
        }

    # -- the broader record watch: every weekly stat a live week can set, with its history
    # Team-week stats the page can recompute from Sleeper's live player points
    # (id, team_week column, directions). Each matches its column on every
    # finished week (tests/test_league_site.py); PF on the semifinal adds +5.
    WATCH_TEAM_STATS = (
        [("pf", "PF", "hl"), ("pa", "Points against", "hl"), ("margin", "Margin", "hl"),
         ("maxpf", "Max PF", "hl"), ("eff", "Efficiency", "hl"), ("bench", "Bench points", "hl"),
         ("left", "Points left on bench", "hl"), ("inc", "Increase in points from previous week", "hl"),
         ("spread", "Difference between highest and lowest starters", "hl"),
         ("hist", "Highest starter score", "hl"), ("lost", "Lowest starter score", "hl")]
        + [(f"from_{p}", f"Points from {p}s", "hl") for p in ("QB", "RB", "WR", "TE")]
        + [(f"pct_{p}", f"% of points from {p}s", "hl") for p in ("QB", "RB", "WR", "TE")]
        + [(f"{a}_{w}", f"{c} ({w2})", "h") for a, c in (("don", "Donuts"), ("u10", "Players under 10 pts"),
                                                           ("o20", "Players over 20 pts"), ("o30", "Players over 30 pts"),
                                                           ("o40", "Players over 40 pts"), ("o50", "Players over 50 pts"))
           for w, w2 in (("st", "starters"), ("ro", "roster"))]
        + [(f"n{w}_{p}", f"Number of {p} {w2}", "hl") for p in ("QB", "RB", "WR", "TE")
           for w, w2 in (("st", "started"), ("ro", "rostered"))]
        + [("same_nfl", "Most number of players started from same NFL team", "h"),
           ("nfl_teams", "Number of NFL teams among starting players", "hl"),
           ("rk_st", "Number of rookies started", "h"), ("rk_ro", "Number of rookies rostered", "h")])
    # one row per game (the winner's row carries the Combined columns)
    WATCH_GAME_STATS = (
        [("c_pf", "Combined points", "hl"), ("c_maxpf", "Combined Max PF", "hl"), ("c_eff", "Combined efficiency", "hl"),
         ("c_bench", "Combined bench points", "h"), ("c_left", "Combined points left on bench", "h"),
         ("c_don", "Combined donuts (starters)", "h"), ("c_u10", "Combined players under 10 pts (starters)", "h"),
         ("c_rk", "Combined rookies started", "h")]
        + [(f"c_from_{p}", f"Combined points from {p}s", "h") for p in ("QB", "RB", "WR", "TE")]
        + [(f"c_o{n}", f"Combined players over {n} pts (starters)", "h") for n in (20, 30, 40, 50)])
    # More team-week stats, each with what it waits on (`dep`): own = the team's
    # own games; both = both teams' (a result, the opponent); league = every
    # team's (a week award); proj = a Sleeper-projection stat, which moves until
    # kickoff and locks once every game it depends on has kicked off [per user,
    # 2026-11-17]. Sleeper-projection versions only: the Claude / Enhanced
    # projections exist only inside the weekly build, for finished weeks.
    WATCH_EXTRA_TEAM_STATS = (
        [("sl_proj", "Sleeper Projection", "hl", "proj_own"),
         ("sl_above", "Points above Sleeper Projection", "hl", "own"),
         ("sl_diff", "Difference in Sleeper Projection from opponent", "hl", "proj_both"),
         ("sl_bold", "Sleeper Lineup Boldness", "hl", "proj_own"),
         ("sl_pre", f"Pre-week Win % (Sleeper Projection)", "hl", "proj_both"),
         ("sl_prediff", f"Difference in pre-week Win % (Sleeper Projection)", "hl", "proj_both"),
         ("sl_preover", f"Pre-week Win % overcome (Sleeper Projection)", "h", "both"),
         ("sl_largest", f"Largest Win % overcome (Sleeper Projection)", "h", "both"),
         ("sl_cb", f"Comeback size (Sleeper Projection)", "h", "both"), ("sl_ch", f"Choke size (Sleeper Projection)", "h", "both")]
        + [(f"sl_wo_{i}", f"Win % overcome entering {s} (Sleeper Projection)", "h", "both") for i, s in enumerate(("SNF", "Monday", "last game"))]
        + [(f"sl_cb_{i}", f"Comeback size entering {s} (Sleeper Projection)", "h", "both") for i, s in enumerate(("SNF", "Monday", "last game"))]
        + [(f"sl_ch_{i}", f"Choke size entering {s} (Sleeper Projection)", "h", "both") for i, s in enumerate(("SNF", "Monday", "last game"))]
        # comebacks per stage (lotg_support.gametime)
        + [c for i, s in enumerate(("SNF", "Monday", "last game")) for c in (
            (f"cb_m_{i}", f"Margin entering {s}", "hl", "both"),
            (f"cb_mo_{i}", f"Margin overcome (entering {s})", "h", "both"),
            (f"cb_po_{i}", f"Points overcome (entering {s})", "h", "both"),
            (f"cb_own_{i}", "% of own points scored in last game" if s == "last game" else f"% of own points scored {s} or later", "hl", "both"),
            (f"cb_pof_{i}", f"% of opponent's final points overcome (entering {s})", "h", "both"),
            (f"cb_ppl_{i}", f"Points overcome per player left (entering {s})", "h", "both"),
            (f"cb_mpl_{i}", f"Margin overcome per player left (entering {s})", "h", "both"),
            (f"cb_pos_{i}", f"% of opponent's score overcome ({'last game' if s == 'last game' else s + ' or later'})", "h", "both"))])
    # Streaks carried from last week (`streaks` in live_watch.json): this week adds
    # one if it keeps going, else it ends. TERMINAL-ENCODED on the sheet, so a
    # board holds the finished runs and each team's current one.
    WATCH_TEAM_STREAKS = (
        ("Win streak", "both"), ("Loss streak", "both"), ("Win streak counting previous season", "both"),
        ("Loss streak counting previous season", "both"), ("Highest score streak", "league"),
        ("Lowest score streak", "league"), ("Narrowest victory streak", "league"),
        ("Largest blowout streak", "league"), ("Most efficient streak", "league"),
        ("Least efficient streak", "league"), ("Top half streak", "league"), ("Bottom half streak", "league"),
        ("Podium streak", "league"), ("One-man army streak", "league"), ("Most bench points streak", "league"),
        ("150+ PF streak", "own"))
    WATCH_PLAYER_STREAKS = (
        ("Player of the week streak", "league"), ("QB of the week streak", "league"),
        ("RB of the week streak", "league"), ("WR of the week streak", "league"), ("TE of the week streak", "league"),
        ("Benchwarmer of the week streak", "league"), ("Bench QB of the week streak", "league"),
        ("Bench RB of the week streak", "league"), ("Bench WR of the week streak", "league"),
        ("Bench TE of the week streak", "league"), ("Dud of the week streak", "league"),
        ("Roster dud of the week streak", "league"), ("Highest starter on team streak", "own"),
        ("Lowest starter on team streak", "own"), ("Captain streak", "league"),
        ("10+ point streak", "self"), ("20+ point streak", "self"), ("30+ point streak", "self"),
        ("40+ point streak", "self"), ("50+ point streak", "self"))
    WATCH_GAME_EXTRA = (("c_slproj", "Combined Sleeper Projection", "hl", "proj_both"),
                        ("c_slabove", "Combined Points above Sleeper Projection", "hl", "both"))
    WATCH_MIN_ROWS = 10        # a board with fewer rows makes any top 5 trivial

    def live_watch(self) -> Dict[str, object]:
        """What the home page's record watch needs to estimate, while a week is
        played, which weekly records (and filtered versions of them) are possible
        or likely:
          stats     every weekly stat it recomputes live: team-week stats, game
                    (combined) stats and player points (by role and position);
          boards    "stat|dir|scope" -> [rows on the board, top-5 values, top-5
                    row ids]; scopes: all, win, loss, and for players also rookie
                    (user, 2026-11-17: no regular-season / this-season / franchise /
                    career versions); boards with under 10 rows are left out;
          rows_t / rows_p  the board rows' labels;
          prev      each team's points last week (the increase stat);
          streaks   each team's / player's streak counts through his latest week
                    (team: [year, week, count]; non-zero only);
          rates     each rostered player's projected points for a week: the
                    forecast's preseason rate blended with this season's PPG
                    (4 games of prior weight);
          rookies   this season's rookies; kickoffs this season's NFL kickoffs (ET)
                    per week and team, so the page knows how much of each game is left."""
        tw = self.tw.copy()
        win = tw["Win?"].astype(str).str.lower().eq("true")
        pw = self.pw.copy()
        pw["Points"] = pd.to_numeric(pw.Points, errors="coerce")
        st_mask = pw["Starter/Bench"].astype(str) == "Starter"
        key = ["Team", "Year", "Week"]
        g = pw[st_mask].groupby(key).Points
        tw = tw.join(g.max().rename("Highest starter score"), on=key).join(g.min().rename("Lowest starter score"), on=key)
        rows_t, rows_p, rid_t, rid_p = [], [], {}, {}

        def row_t(i):
            if i not in rid_t:
                r = tw.loc[i]
                rid_t[i] = len(rows_t)
                rows_t.append([str(r.Team), int(r.Year), str(r["Week Name"]), _clean(r.Opponent)])
            return rid_t[i]

        def row_p(i):
            if i not in rid_p:
                r = pw.loc[i]
                rid_p[i] = len(rows_p)
                rows_p.append([str(r["Player ID"]).split(".")[0], str(r.Player), str(r.Team), int(r.Year), str(r["Week Name"])])
            return rid_p[i]

        boards: Dict[str, list] = {}

        def add(k, values, rid):
            v = values.dropna()
            if len(v) < self.WATCH_MIN_ROWS:
                return
            for d in k[1]:
                s = v.sort_values(ascending=d == "l", kind="mergesort").head(5)
                boards[f"{k[0]}|{d}|{k[2]}"] = [int(len(v)), [round(float(x), 4) for x in s], [rid(i) for i in s.index]]

        team_scopes = [("all", slice(None)), ("win", win), ("loss", ~win & tw["Win?"].astype(str).str.lower().eq("false"))]
        stats = []
        for sid, col, dirs in self.WATCH_TEAM_STATS:
            if col not in tw.columns:
                continue
            stats.append({"id": sid, "kind": "team", "label": _display(col, "team_week"), "col": col,
                          "dirs": dirs, "fmt": column_format(col)})
            v = pd.to_numeric(tw[col], errors="coerce")
            for sc, m in team_scopes:
                add((sid, dirs, sc), v[m], row_t)
        for sid, col, dirs, dep in self.WATCH_EXTRA_TEAM_STATS:
            if col not in tw.columns:
                continue
            stats.append({"id": sid, "kind": "team", "label": _display(col, "team_week"), "col": col,
                          "dirs": dirs, "dep": dep, "fmt": column_format(col)})
            v = pd.to_numeric(tw[col], errors="coerce")
            for sc, m in team_scopes:
                add((sid, dirs, sc), v[m], row_t)
        streaks: Dict[str, Dict[str, object]] = {"team": {}, "player": {}}
        last_t = tw[tw.Year == tw.Year.max()].sort_values("Week").groupby("Team").tail(1)
        for j, (col, dep) in enumerate(self.WATCH_TEAM_STREAKS):
            if col not in tw.columns:
                continue
            sid = f"stk_{j}"
            stats.append({"id": sid, "kind": "team", "label": _display(col, "team_week"), "col": col,
                          "dirs": "h", "dep": dep, "streak": col, "fmt": {"d": 0}})
            add((sid, "h", "all"), pd.to_numeric(tw[col], errors="coerce"), row_t)
            for _, r in last_t.iterrows():
                v = pd.to_numeric(r[col], errors="coerce")
                if pd.notna(v) and v:
                    streaks["team"].setdefault(str(r.Team), {})[sid] = [int(r.Year), int(r.Week), int(v)]
        game = win                                       # the winner's row carries the game
        for sid, col, dirs in self.WATCH_GAME_STATS:
            if col not in tw.columns:
                continue
            stats.append({"id": sid, "kind": "game", "label": _display(col, "team_week"), "col": col,
                          "dirs": dirs, "fmt": column_format(col)})
            v = pd.to_numeric(tw[col], errors="coerce")
            add((sid, dirs, "all"), v[game], row_t)
        for sid, col, dirs, dep in self.WATCH_GAME_EXTRA:
            if col not in tw.columns:
                continue
            stats.append({"id": sid, "kind": "game", "label": _display(col, "team_week"), "col": col,
                          "dirs": dirs, "dep": dep, "fmt": column_format(col)})
            add((sid, dirs, "all"), pd.to_numeric(tw[col], errors="coerce")[game], row_t)
        # player points: role (st starter / bn bench / ro anyone rostered) x position
        pwin = pw["Win?"].astype(str).str.lower()
        rookie = pw["Rookie?"].astype(str).str.lower().eq("true")
        pts_fmt = column_format("Points")
        for role, rmask, rname in (("st", st_mask, "a starter"), ("bn", ~st_mask, "a benched player"),
                                   ("ro", pd.Series(True, index=pw.index), "a rostered player")):
            for pos in ("ALL", "QB", "RB", "WR", "TE"):
                m0 = rmask & (pw.Position.astype(str) == pos if pos != "ALL" else True)
                dirs = "hl" if role == "st" else "h"
                sid = f"p_{role}_{pos}"
                who = rname if pos == "ALL" else rname.replace("player", pos).replace("starter", f"{pos} starter")
                stats.append({"id": sid, "kind": "player", "role": role, "pos": pos, "dirs": dirs,
                              "label": f"Points by {who}", "fmt": pts_fmt})
                sc = [("all", m0), ("win", m0 & pwin.eq("true")), ("loss", m0 & pwin.eq("false")), ("rookie", m0 & rookie)]
                for s_, m in sc:
                    add((sid, dirs, s_), pw.Points[m], row_p)
        share = "% of points (if starter)"
        if share in pw.columns:
            stats.append({"id": "p_share", "kind": "player", "role": "st", "pos": "ALL", "dirs": "h",
                          "label": _display(share, "player_week"), "fmt": column_format(share)})
            v = pd.to_numeric(pw[share], errors="coerce")
            add(("p_share", "h", "all"), v[st_mask], row_p)
        # player streaks: each player's count on his latest row this season
        cur_p = pw[pw.Year == self.season].sort_values("Week")
        last_p = cur_p.drop_duplicates("Player ID", keep="last") if "Player ID" in cur_p.columns else cur_p.iloc[0:0]
        for j, (col, dep) in enumerate(self.WATCH_PLAYER_STREAKS):
            if col not in pw.columns:
                continue
            sid = f"pstk_{j}"
            stats.append({"id": sid, "kind": "player", "role": "ro", "pos": "ALL", "label": _display(col, "player_week"),
                          "col": col, "dirs": "h", "dep": dep, "streak": col, "fmt": {"d": 0}})
            add((sid, "h", "all"), pd.to_numeric(pw[col], errors="coerce"), row_p)
            for pid, y, w, v in zip(last_p["Player ID"], last_p.Year, last_p.Week, pd.to_numeric(last_p[col], errors="coerce")):
                if pd.notna(pid) and pd.notna(v) and v:
                    streaks["player"].setdefault(str(pid).split(".")[0], {})[sid] = [int(y), int(w), int(v)]
        cur = tw[tw.Year == self.season].sort_values(["Week"])
        prev = {str(t): [int(r.Week), _clean(pd.to_numeric(r.PF, errors="coerce"))] for t, r in
                cur.groupby("Team").tail(1).set_index("Team").iterrows()}
        return {"stats": stats, "boards": boards, "rows_t": rows_t, "rows_p": rows_p, "prev": prev,
                "streaks": streaks, "rates": self._weekly_rates(), "rookies": self._rookie_ids(),
                "kickoffs": self._kickoffs(), "season": self.season,
                "roster_positions": self._roster_positions(), "playoff": self._playoff_shape()}

    def _playoff_shape(self) -> Dict[str, object]:
        """The season's calendar for the predictions page (inquiry.SeasonMeta):
        regular weeks, the semifinal week (+5 to the higher seed) and the final's
        weeks (two from 2026, summed)."""
        try:
            from . import inquiry as Q
            m = Q.season_meta(self.season)
            start, teams = int(m.playoff_week_start), int(m.playoff_teams)
        except Exception:                                # pragma: no cover
            start, teams = 15, 4
        return {"teams": teams, "regular_weeks": start - 1, "semifinal_week": start,
                "final_weeks": list(range(start + 1, 18)), "semifinal_bonus": 5}

    def _weekly_rates(self) -> Dict[str, float]:
        """Sleeper id -> projected points for a week: the forecast's preseason
        rate (by name) blended with this season's points per game played."""
        prior: Dict[str, float] = {}
        try:
            import warnings
            from . import forecast as F
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                prior = F.player_rates(self.season)
        except Exception:                                # pragma: no cover - needs the snapshot
            prior = {}
        cur = self.pw[self.pw.Year == self.season].copy()
        cur["Points"] = pd.to_numeric(cur.Points, errors="coerce")
        played = cur[~cur.get("Bye?", pd.Series(False, index=cur.index)).astype(str).str.lower().eq("true")
                     & ~cur.get("Injury?", pd.Series(False, index=cur.index)).astype(str).str.lower().eq("true")]
        out = {}
        if "Player ID" not in cur.columns:
            return out
        names = cur.groupby("Player ID").Player.last()
        g = played.groupby("Player ID").Points.agg(["sum", "count"])
        for pid, name in names.items():
            p = prior.get(str(name))
            s, n = (g.loc[pid, "sum"], g.loc[pid, "count"]) if pid in g.index else (0.0, 0)
            rate = ((p if p is not None else 3.0) * 4 + s) / (4 + n)
            out[str(pid).split(".")[0]] = round(float(rate), 2)
        return out

    SEASON_PLAYER_COLUMNS = ["Points", "Avg points", "PPG starter", "Weeks rostered", "Weeks as starter",
                             "Avg snap %", "Avg target share", "Avg xFP"]

    def season_players(self) -> Dict[str, object]:
        """This season's player_year line for every rostered player, by Sleeper id
        (the NFL team pages' stats)."""
        cur = self.py[self.py.Year == self.season]
        cols = [c for c in self.SEASON_PLAYER_COLUMNS if c in cur.columns]
        rows = {}
        if "Player ID" in cur.columns:
            for _, r in cur.iterrows():
                if pd.notna(r["Player ID"]):
                    rows[str(r["Player ID"]).split(".")[0]] = [_clean(pd.to_numeric(r[c], errors="coerce"),
                                                                      NF.decimals(NF.col_number_format(c))) for c in cols]
        return {"season": self.season, "cols": cols, "labels": [_display(c, "player_year") for c in cols],
                "fmt": {c: column_format(c) for c in cols}, "rows": rows}

    def _rookie_ids(self) -> List[str]:
        cur = self.pw[self.pw.Year == self.season]
        if "Player ID" not in cur.columns or "Rookie?" not in cur.columns:
            return []
        r = cur[cur["Rookie?"].astype(str).str.lower().eq("true")]["Player ID"].dropna()
        return sorted({str(x).split(".")[0] for x in r})

    def _kickoffs(self) -> Dict[str, Dict[str, str]]:
        """{week: {NFL team (Sleeper's code): kickoff 'YYYY-MM-DDTHH:MM' ET}}."""
        try:
            from .gametime import norm_team
            g = pd.read_csv(ROOT / ".cache" / "nfldata_games.csv", low_memory=False)
        except Exception:
            return {}
        g = g[(g.season == self.season) & g.gametime.notna()]
        to_sleeper = {"LA": "LAR"}           # nflverse's codes -> Sleeper's (the player list's)
        out: Dict[str, Dict[str, str]] = {}
        for _, r in g.iterrows():
            ko = f"{r.gameday}T{str(r.gametime)[:5]}"
            for t in (r.home_team, r.away_team):
                code = norm_team(t)
                out.setdefault(str(int(r.week)), {})[to_sleeper.get(code, code)] = ko
        return out

    def _roster_positions(self) -> List[str]:
        try:
            lg = json.loads((EXPORTS / "snapshot" / f"season_{self.season}" / "league.json").read_text())
            return [p for p in lg.get("roster_positions", []) if p not in ("BN", "TAXI", "IR")]
        except (OSError, ValueError):
            return ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX"]

    # -- head to head
    def games(self) -> pd.DataFrame:
        g = self.tw[["Team", "Opponent", "Year", "Week", "Week Name", "Win?", "PF", "Points against"]].copy()
        g = g.dropna(subset=["Opponent"])
        g["PF"] = pd.to_numeric(g.PF, errors="coerce")
        g["Points against"] = pd.to_numeric(g["Points against"], errors="coerce")
        g["W"] = g["Win?"].astype(str).str.lower().eq("true")
        g["Kind"] = g["Week Name"].map(week_kind)
        return g

    def h2h(self) -> Dict[str, object]:
        g = self.games()
        cells = {}
        for (a, b), x in g.groupby(["Team", "Opponent"]):
            last = x.sort_values(["Year", "Week"]).iloc[-1]
            cells[f"{a}|{b}"] = {
                "w": int(x.W.sum()), "l": int((~x.W).sum()), **_kind_records(x),
                "pf": round(float(x.PF.sum()), 2), "pa": round(float(x["Points against"].sum()), 2),
                "games": [[int(r.Year), int(float(r.Week)), str(r["Week Name"]), _clean(r.PF, 2),
                           _clean(r["Points against"], 2), bool(r.W)]
                          for _, r in x.sort_values(["Year", "Week"], ascending=False).iterrows()],
                "last": f"{int(last.Year)} {last['Week Name']}: {'W' if last.W else 'L'} "
                        f"{last.PF:.2f}-{last['Points against']:.2f}"}
        return {"teams": self.teams, "cells": cells, "kinds": {**WEEK_KINDS, **EXTRA_VIEWS},
                "note": "PF includes the semifinal +5 bonus (team PF does; player points do not)."}

    # -- trades
    def trade_list(self) -> List[dict]:
        t = self.trades
        if t.empty:
            return []
        partner_cols = [c for c in t.columns if c.startswith("Team's traded with")]
        groups: Dict[tuple, dict] = {}
        for i, r in t.iterrows():
            teams = frozenset([str(r.Team)] + [str(r[c]) for c in partner_cols if pd.notna(r[c])])
            key = (str(r.Date), teams)
            grp = groups.setdefault(key, {"date": str(r.Date)[:10], "time": str(r.Date),
                                          "season": _clean(r.Season), "sides": []})
            side = {"team": r.Team, "got": _split_assets(r["Assets received"]),
                    "sent": _split_assets(r["Assets sent"]),
                    "kept": _split_assets(r.get("Assets retained now")),
                    # a pick swap / protection this side moved (lotg_support.pick_conditions)
                    "conds": [x for x in str(r.get("Pick swaps and protections") or "").split("; ")
                              if x and x.lower() != "nan"]}
            for c in TRADE_SIDE_COLUMNS:
                if c in t.columns:
                    side[c] = _clean(pd.to_numeric(r[c], errors="coerce"),
                                     NF.decimals(NF.col_number_format(c)))
            # every column of the trades sheet, for the trade's own page and for sorting
            side["all"] = {c: _clean(r[c], NF.decimals(NF.col_number_format(c))) for c in self._trade_all_cols()}
            grp["sides"].append(side)
        out = sorted(groups.values(), key=lambda g: g["time"], reverse=True)
        keys = {id(g): k for k, g in groups.items()}
        for n, g in enumerate(out):
            g["id"] = len(out) - n
            self._trade_ids[keys[id(g)]] = g["id"]
            del g["time"]
            # the deal's grade: the winning side by trade impact, KTC trend for each side
            g["sides"].sort(key=lambda s: -(s.get("Trade impact score") or 0))
        return out

    def _trade_all_cols(self) -> List[str]:
        """The trades sheet's columns minus ids, links and the row's own identity."""
        skip = re.compile(r"(ID|IDs)( |$)|^Link |^Team's traded with|^(Team|Date|Season)$")
        return [c for c in self.trades.columns if not skip.search(str(c))]

    def trade_meta(self) -> Dict[str, object]:
        allc = self._trade_all_cols()
        numeric = [c for c in allc if pd.to_numeric(self.trades[c], errors="coerce").notna().sum() >= 3
                   and not pd.api.types.is_bool_dtype(self.trades[c])]
        cols = list(dict.fromkeys(TRADE_SIDE_COLUMNS + allc))
        return {"fmt": {c: column_format(c) for c in cols},
                "labels": {c: _display(c, "trades") for c in cols},
                "all_cols": allc, "sortable": numeric,
                "ktc": KTC_TIMELINE, "faab": FAAB_TIMELINE}

    # -- draft
    def draft(self) -> Dict[str, object]:
        """Both pick sheets, every column (ids and link refs aside), the pick's
        number / player / team first; "_row" is each pick's row in its sheet
        (its page key). Ordered by year, round, slot, so 2.09 (the toilet-bowl
        reward pick, made after round 4) sits after 2.08."""
        out = {}
        for key, sheet, df in (("rookie", "rookie_picks", self.rookie), ("startup", "non_rookie_picks", self.startup)):
            if df.empty:
                continue
            d = df.assign(_row=range(len(df)))
            num = d["Number"].astype(str)
            d["_y"] = pd.to_numeric(d["Year"].astype(str).str.extract(r"(\d{4})")[0], errors="coerce").fillna(2020)
            d["_r"] = pd.to_numeric(num.str.split(".").str[0], errors="coerce")
            d["_s"] = pd.to_numeric(num.str.split(".").str[1], errors="coerce")
            d = d.sort_values(["_y", "_r", "_s"], kind="mergesort")
            lead = ["Number", "Player Picked", "Team", "Year"]
            rest = [c for c in df.columns if c not in lead and not re.search(r"(ID|IDs)( |$)|^Link ", str(c))]
            out[key] = _table(d, lead + rest + ["_row"], sheet)
        return out

    # -- future picks held
    def held_picks(self, horizon: int = PICK_HORIZON) -> Dict[str, object]:
        """Who holds each future rookie pick (the next `horizon` drafts, rounds
        1-4), the build's way (`_future_picks_owned` in src/lotg.py): every pick
        starts with its original team; the trades sheet's pick legs, replayed in
        date order, move it (they already carry the commissioner overlay's legs,
        data/commissioner_pick_trades.csv); a pick no trade moved but Sleeper's
        traded_picks shows elsewhere is with that owner. Reconciled in the tests
        against team_year's "Future draft capital" for the current season."""
        canon = {t.lower(): t for t in self.teams}
        years = list(range(self.season + 1, self.season + 1 + horizon))
        rounds = range(1, PICK_ROUNDS + 1)
        owner = {(y, r, o): o for y in years for r in rounds for o in self.teams}
        moved = set()
        t = self.trades.sort_values("Date", kind="mergesort")
        for team, got in zip(t["Team"], t["Assets received"]):
            for a in _split_assets(got):
                m = _PICK_LABEL.match(a)
                if not m or int(m.group(1)) not in years:
                    continue
                key = (int(m.group(1)), int(m.group(2)), canon.get(m.group(3).lower(), m.group(3)))
                if key in owner:
                    owner[key] = team
                    moved.add(key)
        for key, cur in _sleeper_pick_owners(self.season, canon).items():
            if key in owner and key not in moved:
                owner[key] = cur
        held: Dict[str, list] = {t: [] for t in self.teams}
        for (y, r, orig), team in sorted(owner.items()):
            held.setdefault(team, []).append([y, r, orig])
        snap = [[y, r, o, cur] for (y, r, o), cur in _sleeper_pick_owners(self.season, canon).items()
                if y in years]
        # each pick's FAAB value today, by the FAAB system's own rule (faab_history.FaabIndex.pick): the next
        # draft's picks by the original team's projected slot odds (roster strength + this season's record,
        # faab_pick_slots), later drafts at the round average, on the fixed weekly schedule (faab_pick_schedule)
        values: Dict[str, float] = {}
        try:
            from . import faab_history as FH
            fidx = FH.FaabIndex.load()
            today = pd.Timestamp.now().normalize()
            if fidx is not None:
                for (y, r, o) in owner:
                    v = fidx.pick(f"{y} {r}({o})", today)
                    if v is not None:
                        values[f"{y}|{r}|{o}"] = round(float(v), 2)
        except Exception:                               # pragma: no cover - the FAAB data may be absent
            values = {}
        # pick swaps / protections still open on these drafts (data/pick_conditions.csv): who gets the better
        # pick, valued only on the trades sheet; listed so the team pages can show them beside the picks
        conds = []
        try:
            from . import pick_conditions as PC
            for c in PC.load():
                if c.year in years:
                    conds.append({"id": c.cid, "kind": c.kind, "year": c.year, "round": c.rnd,
                                  "to": canon.get(c.to.lower(), c.to), "from": canon.get(c.frm.lower(), c.frm),
                                  "picks": [canon.get(o.lower(), o) for o in PC.picks_of(c, PC.load())],
                                  "text": PC.describe(c, None)})
        except Exception:                               # pragma: no cover - a malformed ledger fails the build tests
            conds = []
        return {"season": self.season, "years": years, "rounds": PICK_ROUNDS, "held": held, "values": values,
                "conditions": conds,
                "sleeper_at_build": snap,
                "weights": FUTURE_PICK_WEIGHTS}

    # -- rosters
    def current_roster(self) -> pd.DataFrame:
        pw = self.pw[self.pw.Year == self.season]
        wk = pd.to_numeric(pw.Week, errors="coerce")
        cur = pw[wk == wk.max()].copy()
        ages = self.py[self.py.Year == self.season].set_index("Player")["Age"]
        ages = pd.to_numeric(ages[~ages.index.duplicated()], errors="coerce")
        cur["Age"] = cur.Player.map(ages)
        return cur

    def roster_ages(self) -> Dict[str, dict]:
        cur = self.current_roster()
        out = {}
        for team, g in cur.groupby("Team"):
            st = g[g["Starter/Bench"].astype(str) == "Starter"]
            out[team] = {"avg": _clean(g.Age.mean(), 2), "starters": _clean(st.Age.mean(), 2),
                         "by_pos": {p: _clean(x.Age.mean(), 2) for p, x in g.groupby("Position")}}
        return out

    # -- team pages
    def team(self, team: str, trades: List[dict], ages: Dict[str, dict]) -> Dict[str, object]:
        ta = self.ta[self.ta.Team == team]
        summary = {}
        if len(ta):
            row = ta.iloc[0]
            for c in TEAM_SUMMARY_COLUMNS:
                if c in ta.columns:
                    summary[c] = _clean(row[c], NF.decimals(NF.col_number_format(c)))
        seasons = self.ty[self.ty.Team == team].sort_values("Year", ascending=False)
        g = self.games()
        mine = g[g.Team == team]
        h2h = []
        for opp, x in mine.groupby("Opponent"):
            h2h.append({"opp": opp, "w": int(x.W.sum()), "l": int((~x.W).sum()), **_kind_records(x),
                        "pf": round(float(x.PF.mean()), 2), "pa": round(float(x["Points against"].mean()), 2)})
        week_cols = ["Year", "Week", "Week Name", "Opponent", "Win?", "PF", "Points against", "Margin",
                     "Max PF", "Efficiency", "Starters' xFP", "Starters' points minus xFP"]
        this = self.tw[(self.tw.Team == team) & (self.tw.Year == self.season)]
        roster = self.current_roster()
        roster = roster[roster.Team == team].copy()
        roster["slug"] = roster.Player.map(self.slugs)
        pos_order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}
        roster["_o"] = roster.Position.map(pos_order).fillna(9)
        roster = roster.sort_values(["Starter/Bench", "_o", "Points"], ascending=[False, True, False])
        picks = self.rookie.assign(_row=range(len(self.rookie)))
        picks = picks[picks.Team == team]
        return {
            "team": team, "summary": summary,
            "summary_labels": {c: _display(c, "team_all_time") for c in summary},
            "summary_fmt": {c: column_format(c) for c in summary},
            "seasons": _table(seasons, SEASON_COLUMNS, "team_year"),
            "swing": _table(seasons, SWING_COLUMNS, "team_year"),
            "risk": _table(seasons, RISK_COLUMNS, "team_year"),
            "h2h": sorted(h2h, key=lambda r: -(r["w"] - r["l"])),
            "weeks": _table(this.sort_values("Week"), week_cols, "team_week"),
            "roster": _table(roster, ["Player", "slug", "Position", "NFL team", "Age", "Starter/Bench",
                                      "Points", "Acquired via"], "player_week"),
            "ages": ages.get(team, {}), "league_ages": ages,
            "trades": [x["id"] for x in trades if any(s["team"] == team for s in x["sides"])],
            "draft": _table(picks.iloc[::-1], DRAFT_COLUMNS + ["_row"], "rookie_picks"),
        }

    @staticmethod
    def _usage_seasons(g: pd.DataFrame) -> pd.DataFrame:
        """A player's seasons that have usage data, newest first (none before
        2020, none on exports that predate the columns)."""
        if "Weeks with usage data" not in g.columns:
            return g.iloc[0:0]
        n = pd.to_numeric(g["Weeks with usage data"], errors="coerce").fillna(0)
        return g[n > 0].sort_values("Year", ascending=False)

    # -- every NFL game since 2020 in league scoring, for the game logs and full-season rows
    NFL_LOG_FROM = 2020
    LOG_COLS = ["Year", "Week", "Week Name", "Team", "Starter/Bench", "Position started in (if starter)",
                "Points", "Snap %", "Targets", "Carries", "xFP"]

    def nfl_points(self) -> Dict[str, Dict[Tuple[int, int], float]]:
        """League-scored nflverse points by Sleeper id and (season, week): the build's own
        scorer (wins_added.nflverse_points_from_cache). The site workflow has no build
        cache, so missing seasons are downloaded first. Any failure: {} (game logs then
        show rostered weeks only)."""
        if getattr(self, "_nfl_pts", None) is not None:
            return self._nfl_pts
        self._nfl_pts = {}
        try:
            from . import external as X
            from . import wins_added as WA
            cache = ROOT / ".cache"
            cache.mkdir(exist_ok=True)
            cfg = X.ExternalConfig(cache_dir=cache)
            seasons = list(range(self.NFL_LOG_FROM, int(self.season) + 1))
            for y in seasons:
                f = cache / f"nflverse_stats_player_week_{y}.csv"
                if not f.exists() or (y == int(self.season) and time.time() - f.stat().st_mtime > 6 * 3600):
                    X.load_nflverse_stats_player_week(cfg, y, force_refresh=f.exists())
            self._nfl_pts = WA.nflverse_points_from_cache(seasons) or {}
        except Exception as e:      # network, bridge or format trouble: rostered weeks only
            print(f"league_site: nflverse game logs unavailable ({type(e).__name__}: {e})")
            self._nfl_pts = {}
        return self._nfl_pts

    def game_log(self, name: str, sid: Optional[str], g: Optional[pd.DataFrame], res: Dict) -> Dict[str, object]:
        """Every game: his rostered weeks (team, role, slot, points, the team's opponent and
        result, usage) plus every other NFL game since 2020 he played, newest first."""
        nfl = self.nfl_points().get(str(sid), {}) if sid else {}
        rows = {}
        if g is not None:
            for yr, wk, wn, team, role, slot, pts, snap, tg, ca, xfp in g[self.LOG_COLS].values:
                if pd.isna(yr) or pd.isna(wk):
                    continue
                y, w = int(yr), int(wk)
                rr = res.get((str(team), y, w), (None, None))
                rows[(y, w)] = [y, w, str(wn), str(team), str(role),
                                (None if pd.isna(slot) else str(slot)), _clean(pd.to_numeric(pts, errors="coerce"), 2),
                                rr[0], rr[1], _clean(nfl.get((y, w)), 2),
                                _clean(pd.to_numeric(snap, errors="coerce"), 4), _clean(pd.to_numeric(tg, errors="coerce"), 0),
                                _clean(pd.to_numeric(ca, errors="coerce"), 0), _clean(pd.to_numeric(xfp, errors="coerce"), 2)]
        for (y, w), pts in nfl.items():
            if (y, w) not in rows:
                # a week the exports don't reach yet isn't "not rostered": it's after the build
                after = y == int(self.season) and w > int(self.week)
                # an NFL week after the league's last week that season (week 18; 2020's week 17)
                done = y != int(self.season) and w > self._last_league_week().get(y, 99)
                role = "Since the last build" if after else "After the league season" if done else "Not rostered"
                rows[(y, w)] = [y, w, f"Week {w}", None, role, None, _clean(pts, 2),
                                None, None, _clean(pts, 2), None, None, None, None]
        cols = ["Year", "Week", "Week Name", "Team", "Role", "Slot", "Points", "Opponent", "Win?",
                "NFL points", "Snap %", "Targets", "Carries", "xFP"]
        return {"cols": cols, "rows": [rows[k] for k in sorted(rows, reverse=True)],
                "fmt": {"Points": {"d": 2}, "NFL points": {"d": 2}, "Snap %": {"d": 1, "p": "x"},
                        "Targets": {"d": 0}, "Carries": {"d": 0}, "xFP": {"d": 2}}}

    def _last_league_week(self) -> Dict[int, int]:
        if getattr(self, "_llw", None) is None:
            y = pd.to_numeric(self.tw["Year"], errors="coerce"); w = pd.to_numeric(self.tw["Week"], errors="coerce")
            self._llw = {int(k): int(v) for k, v in w.groupby(y).max().items() if pd.notna(k) and pd.notna(v)}
        return self._llw

    def full_seasons(self, sid: Optional[str], have: set) -> pd.DataFrame:
        """Season rows since 2020 for seasons he wasn't on a league roster: the whole NFL
        season's league-scored points (Points (full season) / Avg points (full season))."""
        nfl = self.nfl_points().get(str(sid), {}) if sid else {}
        by: Dict[int, List[float]] = {}
        for (y, w), pts in nfl.items():
            if y not in have and pts is not None:
                by.setdefault(y, []).append(float(pts))
        return pd.DataFrame([{"Year": y, "Top Team": "Not rostered", "Points (full season)": round(sum(v), 2),
                              "Avg points (full season)": round(sum(v) / len(v), 2)} for y, v in sorted(by.items())])

    # -- player pages
    def players(self) -> Dict[str, dict]:
        pos = self._positions()
        pw = self.pw.copy()
        pw["Points"] = pd.to_numeric(pw.Points, errors="coerce")
        pw["St"] = pw["Starter/Bench"].astype(str) == "Starter"
        by_team = {}
        for (player, team), g in pw.groupby(["Player", "Team"], sort=False):
            st = g[g.St]
            first, last = g.iloc[0], g.iloc[-1]
            by_team.setdefault(player, []).append({
                "team": team, "from": f"{int(first.Year)} {first['Week Name']}",
                "to": f"{int(last.Year)} {last['Week Name']}", "weeks": int(len(g)),
                "starts": int(len(st)), "pts": round(float(st.Points.sum()), 2),
                "ppg": round(float(st.Points.mean()), 2) if len(st) else None,
                "best": round(float(g.Points.max()), 2) if g.Points.notna().any() else None})
        latest = pw.sort_values(["Year", "Week"]).groupby("Player").tail(1).set_index("Player")
        cur_names = set(pw[(pw.Year == self.season)
                           & (pd.to_numeric(pw.Week, errors="coerce") == self.week)].Player)
        adds = self.adds.groupby("Player")
        py = self.py.groupby("Player")
        pa = self.pa.set_index("Player")
        pa = pa[~pa.index.duplicated()]
        trade_hits: Dict[str, List[int]] = {}
        for t in self._trades:
            for s in t["sides"]:
                for a in s["got"] + s["sent"]:
                    trade_hits.setdefault(a, []).append(t["id"])
        drafted = {str(r["Player Picked"]): r for _, r in self.rookie.iterrows()}
        hist = self.player_histories()
        log = pw.copy()
        for c in self.LOG_COLS:
            if c not in log.columns:
                log[c] = None
        logs = log.groupby("Player")
        sid_of = {}
        if "Player ID" in pw.columns:
            for nm, v in pw.dropna(subset=["Player ID"]).groupby("Player")["Player ID"].last().items():
                sid_of[nm] = str(v).split(".")[0]
        # each team-week's opponent and result, for the log
        res = {}
        for team, yr, wk, opp, won in self.tw[["Team", "Year", "Week", "Opponent", "Win?"]].values:
            y, w = pd.to_numeric(yr, errors="coerce"), pd.to_numeric(wk, errors="coerce")
            if pd.notna(y) and pd.notna(w):
                res[(str(team), int(y), int(w))] = (None if pd.isna(opp) else str(opp),
                                                    None if pd.isna(won) else str(won).strip().lower() in ("true", "1", "yes"))
        out = {}
        for name, key in self.slugs.items():
            summary = {}
            if name in pa.index:
                row = pa.loc[name]
                for c in PLAYER_SUMMARY_COLUMNS:
                    if c in pa.columns:
                        summary[c] = _clean(row[c], NF.decimals(NF.col_number_format(c)))
            lt = latest.loc[name] if name in latest.index else None
            d = drafted.get(name)
            out[key] = {
                "name": name, "pos": pos.get(name),
                "team": (str(lt.Team) if lt is not None and name in cur_names else None),
                "nfl": (str(lt["NFL team"]) if lt is not None and pd.notna(lt["NFL team"]) else None),
                "summary": summary,
                "summary_labels": {c: _display(c, "player_all_time") for c in summary},
                "summary_fmt": {c: column_format(c) for c in summary},
                "teams": by_team.get(name, []),
                "seasons": _table(pd.concat([py.get_group(name) if name in py.groups else self.py.iloc[0:0],
                                             self.full_seasons(sid_of.get(name), set(pd.to_numeric(py.get_group(name).Year, errors="coerce").dropna().astype(int)) if name in py.groups else set())],
                                            ignore_index=True).sort_values("Year", ascending=False),
                                  PLAYER_SEASON_COLUMNS, "player_year"),
                "games": self.game_log(name, sid_of.get(name), logs.get_group(name) if name in logs.groups else None, res),
                "usage": _table(self._usage_seasons(py.get_group(name)) if name in py.groups
                                else self.py.iloc[0:0], PLAYER_USAGE_COLUMNS, "player_year"),
                "stints": _table(adds.get_group(name).sort_values("Date")
                                 if name in adds.groups else self.adds.iloc[0:0],
                                 STINT_COLUMNS, "player_additions"),
                "trades": sorted(set(trade_hits.get(name, [])), reverse=True),
                "history": hist.get(name),
                "draft": None if d is None else {
                    "year": _clean(d.Year), "pick": _clean(d.Number), "team": d.Team,
                    "ktc": _clean(pd.to_numeric(d["KTC on draft day"], errors="coerce"), 2),
                    "faab": (_clean(pd.to_numeric(d["FAAB Value on draft day"], errors="coerce"), 1)
                             if "FAAB Value on draft day" in d else None)},
            }
        return out

    # -- every export sheet, whole
    def sheets(self, put) -> Dict[str, object]:
        defs = _defs_by_sheet()
        index = []
        for sheet in export_sheets():
            df = _read(sheet)
            cols = [str(c) for c in df.columns]
            chunks = sheet_chunks(sheet, df)
            for name, part in chunks.items():
                put(f"sheets/{sheet}/{slug(name)}.json", {"rows": _records(part, cols)})
            index.append({
                "sheet": sheet, "rows": int(len(df)), "cols": cols,
                "labels": [_display(c, sheet) for c in cols],
                "fmt": {c: column_format(c) for c in cols if sheet != GLOSSARY_SHEET},
                "chunks": [[name, slug(name), int(len(part))] for name, part in chunks.items()],
                "season_col": _season_key(df) if len(chunks) > 1 else None,
                "csv": f"downloads/{sheet}.csv",
                "csv_bytes": (EXPORTS / f"{sheet}.csv").stat().st_size,
                "defs": {c: defs.get(sheet, {}).get(c) for c in cols if defs.get(sheet, {}).get(c)},
            })
        return {"sheets": index}

    # -- search
    def search_index(self, players: Dict[str, dict]) -> List[list]:
        idx = [["t", t, t, "Team"] for t in self.teams]
        for key, p in players.items():
            weeks = sum(x["weeks"] for x in p["teams"])
            idx.append(["p", key, p["name"], " ".join(x for x in (p["pos"], p["team"] or "", p["nfl"] or "") if x),
                        weeks])
        idx.sort(key=lambda r: (r[0] != "t", -(r[4] if len(r) > 4 else 0)))
        return idx

    # -- everything
    def build(self, out: Path, forecast: bool = True, sims: int = 20000) -> Dict[str, object]:
        timings, sizes = {}, {}
        data = out / "data"
        t0 = time.time()

        def put(rel, obj):
            sizes[rel] = _dump(data / rel, obj)

        put("meta.json", self.meta())
        t = time.time()
        odds = forecast_odds(self.season, sims=sims) if forecast else None
        if odds and "_sims" in odds:
            arr = odds.pop("_sims")
            (data).mkdir(parents=True, exist_ok=True)
            (data / "forecast_sims.bin").write_bytes(arr.tobytes())
            sizes["forecast_sims.bin"] = arr.nbytes
        timings["forecast"] = round(time.time() - t, 1)
        put("home.json", self.home(odds))
        self._trades = self.trade_list()
        t = time.time()
        for sheet in RECORD_SHEETS:
            put(f"records/{sheet}.json", self.records(sheet))
        timings["records"] = round(time.time() - t, 1)
        put("h2h.json", self.h2h())
        put("all_time.json", self.all_time_standings())
        put("watch.json", self.record_watch())
        put("live_watch.json", self.live_watch())
        # the full sheet columns go in their own file: only the trades pages need them
        full = {t["id"]: [side.pop("all", {}) for side in t["sides"]] for t in self._trades}
        put("trades.json", {"meta": self.trade_meta(), "trades": self._trades})
        put("trades_full.json", full)
        put("draft.json", self.draft())
        put("picks.json", self.held_picks())
        # today's KTC (dynasty-daddy's directory) for the trade calculator; the browser can't
        # read dynasty-daddy itself (no CORS), and a build without network just leaves it out
        k = ktc_snapshot()
        if k:
            put("ktc.json", k)
        rostered = []
        for r in json.loads((EXPORTS / "snapshot" / f"season_{self.season}" / "rosters.json").read_text()) \
                if (EXPORTS / "snapshot" / f"season_{self.season}" / "rosters.json").exists() else []:
            rostered += r.get("players") or []
        ages = {}
        if "Player ID" in self.py.columns:
            cur = self.py[self.py.Year == self.season]
            for pid, age in zip(cur["Player ID"], pd.to_numeric(cur["Age"], errors="coerce")):
                if pd.notna(pid) and pd.notna(age):
                    ages[str(pid).split(".")[0]] = round(float(age), 2)
        put("nfl_players.json", nfl_players(rostered, ages))
        put("season_players.json", self.season_players())
        put("pick_history.json", {"has_workbook": self._histories is not None, **self.pick_histories()})
        t = time.time()
        self.weeks(put)
        timings["weeks"] = round(time.time() - t, 1)
        ages = self.roster_ages()
        for team in self.teams:
            put(f"team/{slug(team)}.json", self.team(team, self._trades, ages))
        t = time.time()
        players = self.players()
        for key, p in players.items():
            put(f"player/{key}.json", p)
        timings["players"] = round(time.time() - t, 1)
        put("search.json", self.search_index(players))
        t = time.time()
        put("sheets/index.json", self.sheets(put))
        timings["sheets"] = round(time.time() - t, 1)
        timings["total"] = round(time.time() - t0, 1)
        return {"timings": timings, "bytes": sum(sizes.values()), "files": len(sizes),
                "largest": sorted(sizes.items(), key=lambda kv: -kv[1])[:5]}


def ktc_snapshot_from(rows: Iterable[dict]) -> Optional[Dict[str, object]]:
    """dynasty-daddy's directory rows -> the trade calculator's KTC file: superflex value,
    the value a month ago and the superflex position rank, by Sleeper id; picks by their
    dynasty-daddy name ('2027 Early 1st'). Only QB/RB/WR/TE and generic picks."""
    players, picks, as_of = {}, {}, ""
    for r in rows or []:
        sf = r.get("sf_trade_value")
        if not isinstance(sf, (int, float)):
            continue
        as_of = max(as_of, str(r.get("date") or "")[:10])
        ago = r.get("last_month_value_sf")
        ago = ago if isinstance(ago, (int, float)) else None
        if r.get("position") == "PI":
            name = str(r.get("full_name") or "")
            if re.fullmatch(r"\d{4} (Early|Mid|Late) (1st|2nd|3rd|4th)", name):
                picks[name] = [sf, ago]
        elif r.get("position") in ("QB", "RB", "WR", "TE") and r.get("sleeper_id"):
            players[str(r["sleeper_id"])] = [sf, ago, r.get("sf_position_rank")]
    if not players:
        return None
    return {"as_of": as_of, "source": "KeepTradeCut superflex values, via dynasty-daddy", "players": players, "picks": picks}


def ktc_snapshot() -> Optional[Dict[str, object]]:
    try:
        from . import ktc
        return ktc_snapshot_from(ktc.load_directory(ROOT))
    except Exception:
        return None


def copy_shell(out: Path, shell: Path = SHELL, stamp: Optional[str] = None) -> None:
    """Copy the page shell; index.html asks for app.js / style.css with a hash of
    their contents (`app.js?v=…`), so a deploy is never hidden behind the copy a
    browser cached (GitHub Pages lets browsers keep files for 10 minutes). It also
    carries this build's stamp (window.SITE_BUILD), which the page adds to every
    data request, so the code never runs against another build's cached data."""
    import hashlib
    stamp = stamp or time.strftime("%Y%m%d%H%M%S", time.gmtime())
    for f in shell.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    index = out / "index.html"
    if index.exists():
        html_text = index.read_text(encoding="utf-8")
        for name in ("app.js", "style.css"):
            if (shell / name).exists():
                v = hashlib.sha1((shell / name).read_bytes()).hexdigest()[:10]
                html_text = re.sub(rf'(["\']){re.escape(name)}(["\'])', rf"\g<1>{name}?v={v}\g<2>", html_text)
        html_text = html_text.replace('<script src="app.js', f'<script>window.SITE_BUILD="{stamp}"</script>\n<script src="app.js', 1)
        index.write_text(html_text, encoding="utf-8")


def build(out_dir, forecast: bool = True, sims: int = 20000, workbook=None) -> Dict[str, object]:
    """`workbook`: the build's LOTG_Stats.xlsx (its asset-history comments go on
    the player and pick pages); without it those sections are left out."""
    out = Path(out_dir)
    if (out / "data").exists():
        shutil.rmtree(out / "data")
    out.mkdir(parents=True, exist_ok=True)
    report = Site(workbook=workbook).build(out, forecast=forecast, sims=sims)
    copy_shell(out)
    dl = out / "downloads"
    dl.mkdir(exist_ok=True)
    for sheet in export_sheets():
        shutil.copy2(EXPORTS / f"{sheet}.csv", dl / f"{sheet}.csv")
    report["site_bytes"] = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    return report
