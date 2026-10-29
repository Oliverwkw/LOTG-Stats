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
import re
import shutil
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from . import number_format as NF

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "exports"
DIGEST_HTML = ROOT / "data" / "digest" / "last_digest.html"
SHELL = ROOT / "site"

# Every file the generator reads. Anything else is off limits.
INPUTS = (
    "exports/*.csv",                 # every sheet, served whole on the Data page (+ CSV downloads)
    "data/digest/last_digest.html",
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
    "add_drops": None,          # labels picked at load time (see _labels)
    "player_additions": ("Player", "Team", "Addition type", "Date"),
    "rookie_picks": ("Player Picked", "Team", "Year", "Number"),
}
RECORD_DEPTH = 10               # rows per end; ties at the cut are kept up to RECORD_CAP
RECORD_CAP = 25

# Never ranked: identifiers, links, and columns whose number is a label.
_NOT_A_STAT = re.compile(r"^(Year|Week|Season|Number|Date.*|Link .*|Player ID|.*\bID)$")

SEASON_COLUMNS = [
    "Year", "Result", "Record", "Regular season record", "Win %", "All-play win %",
    "Points", "Avg points", "Points against", "Max PF", "Efficiency", "Points left on bench",
    "Differential", "Lineup Boldness", "Drafting skill", "Trading skill", "Add/Drop skill",
    "Draft Value", "Times Highest score?", "Week of playoff elimination",
]
TEAM_SUMMARY_COLUMNS = [
    "All time record", "All time win %", "Regular season record", "Playoff record",
    "Championships", "Number of championship appearances", "Number of playoff appearances",
    "Number of last place finishes", "Points", "Avg points", "Points against", "Efficiency",
    "All-play win %", "Avg yearly luck", "Drafting skill", "Trading skill", "Add/Drop skill",
    "Times Highest score?", "Times Lowest score?",
]
PLAYER_SUMMARY_COLUMNS = [
    "Top team", "Last team", "Points", "Total points as starter", "PPG starter",
    "PPG starter adjusted by position", "Weeks rostered", "Weeks as starter", "% of starts",
    "Number of teams", "Number of trades", "Number of Add/Drops", "Starter PAR",
    "Championships rostered by", "Championships started by", "Times as Player of the week?",
    "Win % as starter",
]
PLAYER_SEASON_COLUMNS = [
    "Year", "Top Team", "Last team", "Age", "Points", "Total points as starter", "PPG starter",
    "Weeks as starter", "Weeks rostered", "Starter PAR", "Rostered by champion?",
    "Started in championship game?",
]
STINT_COLUMNS = [
    "Team", "Addition type", "Date", "Season", "Date dropped/traded", "Tenure (NFL weeks)",
    "Games played on team", "Total weeks as team starter (all stints)", "Avg PPG on team",
    "Points added", "Price paid (FAAB)", "Player addition value", "KTC at pickup",
    "KTC change 1 year after pickup",
]
TRADE_SIDE_COLUMNS = [
    "Pick value received", "Trade impact score", "Wins added", "Net points", "Avg net points",
    "Trade addition value", "O-Score", "Asset difference in average age", "Tanking",
    "KTC value difference at deal time", "KTC value difference at end of season",
    "KTC value difference 1 year later", "KTC value difference 2 years later",
]
KTC_TIMELINE = [
    ("Deal", "KTC value difference at deal time"),
    ("Season end", "KTC value difference at end of season"),
    ("+1 yr", "KTC value difference 1 year later"),
    ("+2 yr", "KTC value difference 2 years later"),
]
DRAFT_COLUMNS = [
    "Year", "Number", "Player Picked", "Team", "Original Team", "Age when drafted",
    "KTC on draft day", "KTC at end of rookie year", "KTC 1 year after draft day",
    "KTC 2 years after draft day", "KTC 3 years after draft day",
    "Pick-adjusted Difference in KTC on draft day",
    "Pick-adjusted Difference in KTC 1 year after draft day",
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
            if not text.lower().startswith("rate the board"):
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

def forecast_odds(year: int, sims: int = 20000) -> Optional[Dict[str, object]]:
    """Title / finals / playoff odds from lotg_support.forecast, or None if the
    forecast cannot run (the site still builds without it)."""
    try:
        import warnings
        from . import forecast as F
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fc = F.forecast(year, sims=sims)
    except Exception as exc:                            # pragma: no cover - depends on snapshot
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}
    rows = [{"team": o.team, "champion": round(o.champion, 1), "finals": round(o.finals, 1),
             "playoffs": round(o.playoffs, 1), "wins": round(o.expected_wins, 2),
             "pf": round(o.expected_pf, 2),
             "next": None if o.next_week is None else round(o.next_week, 2)}
            for o in fc.by_champion()]
    return {"year": year, "sims": fc.sims, "played": list(fc.played_weeks), "odds": rows}


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
    return out


def sheet_chunks(sheet: str, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """The sheet whole ("all"), or split by season when its CSV is large."""
    path = EXPORTS / f"{sheet}.csv"
    key = _season_key(df)
    if key is None or not path.exists() or path.stat().st_size <= CHUNK_BYTES:
        return {"all": df}
    vals = df[key].astype(str).str.replace(r"\.0$", "", regex=True)
    return {v: df[vals == v] for v in sorted(vals.unique())}


# ---------------------------------------------------------------- builders

class Site:
    def __init__(self):
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
                "seasons": sorted(int(y) for y in self.tw["Year"].dropna().unique())}

    # -- home
    def standings(self) -> List[dict]:
        cur = self.tw[(self.tw.Year == self.season)
                      & self.tw["Week Name"].astype(str).str.startswith("Week ")].copy()
        cur["PF"] = pd.to_numeric(cur["PF"], errors="coerce")
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
        df = _read(sheet)
        if df.empty:
            return {"sheet": sheet, "columns": []}
        labels = RECORD_SHEETS.get(sheet)
        if labels is None:
            labels = tuple(c for c in ("Team", "Player added", "Player dropped", "Date", "Season")
                           if c in df.columns) or tuple(df.columns[:3])
        labels = tuple(c for c in labels if c in df.columns)
        year = pd.to_numeric(df["Year"] if "Year" in df else df.get("Season"), errors="coerce") \
            if ("Year" in df or "Season" in df) else None
        live = (year == self.season) if year is not None else pd.Series(False, index=df.index)
        cols = []
        for c in df.columns:
            if c in labels or _NOT_A_STAT.match(str(c)):
                continue
            v = _numeric(df, c)
            ok = v.notna()
            if ok.sum() < 3 or v[ok].nunique() < 2:
                continue
            places = NF.decimals(NF.col_number_format(c))
            entry = {"col": c, "label": _display(c, sheet), "fmt": column_format(c), "n": int(ok.sum())}
            for end, asc in (("hi", False), ("lo", True)):
                s = v[ok].sort_values(ascending=asc, kind="mergesort")
                cut = s.iloc[min(RECORD_DEPTH, len(s)) - 1]
                keep = s[(s >= cut) if not asc else (s <= cut)].head(RECORD_CAP)
                tied = int(((s >= cut) if not asc else (s <= cut)).sum()) - len(keep)
                rows = []
                for idx, val in keep.items():
                    rows.append([_clean(val, places), [_clean(df.at[idx, lab]) for lab in labels],
                                 bool(live.get(idx, False))])
                entry[end] = rows
                if tied > 0:
                    entry[end + "_more"] = tied
            cols.append(entry)
        return {"sheet": sheet, "labels": list(labels), "live_season": self.season, "columns": cols}

    # -- head to head
    def games(self) -> pd.DataFrame:
        g = self.tw[["Team", "Opponent", "Year", "Week", "Week Name", "Win?", "PF", "Points against"]].copy()
        g = g.dropna(subset=["Opponent"])
        g["PF"] = pd.to_numeric(g.PF, errors="coerce")
        g["Points against"] = pd.to_numeric(g["Points against"], errors="coerce")
        g["W"] = g["Win?"].astype(str).str.lower().eq("true")
        g["Playoff"] = ~g["Week Name"].astype(str).str.startswith("Week ")
        return g

    def h2h(self) -> Dict[str, object]:
        g = self.games()
        cells = {}
        for (a, b), x in g.groupby(["Team", "Opponent"]):
            reg, po = x[~x.Playoff], x[x.Playoff]
            last = x.sort_values(["Year", "Week"]).iloc[-1]
            cells[f"{a}|{b}"] = {
                "w": int(x.W.sum()), "l": int((~x.W).sum()),
                "rw": int(reg.W.sum()), "rl": int((~reg.W).sum()),
                "pw": int(po.W.sum()), "pl": int((~po.W).sum()),
                "pf": round(float(x.PF.sum()), 2), "pa": round(float(x["Points against"].sum()), 2),
                "last": f"{int(last.Year)} {last['Week Name']}: {'W' if last.W else 'L'} "
                        f"{last.PF:.2f}-{last['Points against']:.2f}"}
        return {"teams": self.teams, "cells": cells,
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
                    "kept": _split_assets(r.get("Assets retained now"))}
            for c in TRADE_SIDE_COLUMNS:
                if c in t.columns:
                    side[c] = _clean(pd.to_numeric(r[c], errors="coerce"),
                                     NF.decimals(NF.col_number_format(c)))
            grp["sides"].append(side)
        out = sorted(groups.values(), key=lambda g: g["time"], reverse=True)
        for n, g in enumerate(out):
            g["id"] = len(out) - n
            del g["time"]
            # the deal's grade: the winning side by trade impact, KTC trend for each side
            g["sides"].sort(key=lambda s: -(s.get("Trade impact score") or 0))
        return out

    def trade_meta(self) -> Dict[str, object]:
        return {"fmt": {c: column_format(c) for c in TRADE_SIDE_COLUMNS},
                "labels": {c: _display(c, "trades") for c in TRADE_SIDE_COLUMNS},
                "ktc": KTC_TIMELINE}

    # -- draft
    def draft(self) -> Dict[str, object]:
        r = self.rookie.copy()
        out = {"rookie": _table(r, DRAFT_COLUMNS, "rookie_picks")}
        if not self.startup.empty:
            out["startup"] = _table(self.startup, DRAFT_COLUMNS, "non_rookie_picks")
        return out

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
            h2h.append({"opp": opp, "w": int(x.W.sum()), "l": int((~x.W).sum()),
                        "pw": int(x[x.Playoff].W.sum()), "pl": int((~x[x.Playoff].W).sum()),
                        "pf": round(float(x.PF.mean()), 2), "pa": round(float(x["Points against"].mean()), 2)})
        week_cols = ["Year", "Week Name", "Opponent", "Win?", "PF", "Points against", "Margin",
                     "Max PF", "Efficiency"]
        this = self.tw[(self.tw.Team == team) & (self.tw.Year == self.season)]
        roster = self.current_roster()
        roster = roster[roster.Team == team].copy()
        roster["slug"] = roster.Player.map(self.slugs)
        pos_order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}
        roster["_o"] = roster.Position.map(pos_order).fillna(9)
        roster = roster.sort_values(["Starter/Bench", "_o", "Points"], ascending=[False, True, False])
        picks = self.rookie[self.rookie.Team == team]
        return {
            "team": team, "summary": summary,
            "summary_labels": {c: _display(c, "team_all_time") for c in summary},
            "summary_fmt": {c: column_format(c) for c in summary},
            "seasons": _table(seasons, SEASON_COLUMNS, "team_year"),
            "h2h": sorted(h2h, key=lambda r: -(r["w"] - r["l"])),
            "weeks": _table(this.sort_values("Week"), week_cols, "team_week"),
            "roster": _table(roster, ["Player", "slug", "Position", "NFL team", "Age", "Starter/Bench",
                                      "Points", "Acquired via"], "player_week"),
            "ages": ages.get(team, {}), "league_ages": ages,
            "trades": [x["id"] for x in trades if any(s["team"] == team for s in x["sides"])],
            "draft": _table(picks.iloc[::-1], DRAFT_COLUMNS, "rookie_picks"),
        }

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
                "seasons": _table(py.get_group(name).sort_values("Year", ascending=False)
                                  if name in py.groups else self.py.iloc[0:0],
                                  PLAYER_SEASON_COLUMNS, "player_year"),
                "stints": _table(adds.get_group(name).sort_values("Date")
                                 if name in adds.groups else self.adds.iloc[0:0],
                                 STINT_COLUMNS, "player_additions"),
                "trades": sorted(set(trade_hits.get(name, [])), reverse=True),
                "draft": None if d is None else {
                    "year": _clean(d.Year), "pick": _clean(d.Number), "team": d.Team,
                    "ktc": _clean(pd.to_numeric(d["KTC on draft day"], errors="coerce"), 2)},
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
        timings["forecast"] = round(time.time() - t, 1)
        put("home.json", self.home(odds))
        t = time.time()
        for sheet in RECORD_SHEETS:
            put(f"records/{sheet}.json", self.records(sheet))
        timings["records"] = round(time.time() - t, 1)
        put("h2h.json", self.h2h())
        self._trades = self.trade_list()
        put("trades.json", {"meta": self.trade_meta(), "trades": self._trades})
        put("draft.json", self.draft())
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


def copy_shell(out: Path, shell: Path = SHELL) -> None:
    for f in shell.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)


def build(out_dir, forecast: bool = True, sims: int = 20000) -> Dict[str, object]:
    out = Path(out_dir)
    if (out / "data").exists():
        shutil.rmtree(out / "data")
    out.mkdir(parents=True, exist_ok=True)
    report = Site().build(out, forecast=forecast, sims=sims)
    copy_shell(out)
    dl = out / "downloads"
    dl.mkdir(exist_ok=True)
    for sheet in export_sheets():
        shutil.copy2(EXPORTS / f"{sheet}.csv", dl / f"{sheet}.csv")
    report["site_bytes"] = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    return report
