"""Player usage / opportunity and expected fantasy points (xFP).

Every other stat in the exports is an OUTCOME. These columns say how much work
a player got, so a hot streak can be told apart from a role change:

  player_week   Snap %, Targets, Carries, Target share, Air yards,
                Red-zone opportunities, xFP, Points minus xFP
  player_year / player_all_time
                the same summed over his ROSTERED weeks (player_week rows),
                with averages per week of usage data
  team_week     Starters' xFP, Starters' points minus xFP
  team_year     the same summed, plus per-team-week averages

Sources (all free, all keyed by the GSIS id — never by name):
  * nflverse `stats_player_week`  targets, carries, target share, air yards
                                  (already cached by the build)
  * nflverse `snap_counts`        offense snap %; keyed by PFR id, bridged to
                                  GSIS through the weekly rosters, then the
                                  DynastyProcess id table (as the build's
                                  appearance check does)
  * ffverse `ffopportunity`       expected stats per player-game: receptions,
                                  yards, TDs, 2-pt conversions, first downs and
                                  interceptions, each the expectation of a
                                  nflfastR-trained model given the plays he was
                                  part of (`ep_weekly_{season}.csv`)
  * nflverse play-by-play         red-zone targets + carries (yardline_100 <= 20)

xFP IN THIS LEAGUE'S SCORING. ffopportunity's own `total_fantasy_points_exp`
is full PPR with 4-pt passing TDs, −2 INTs and no fumble term. Rather than
rescale that total, xFP here is rebuilt from the expected COMPONENTS with each
season's own scoring table (the same tables `_league_score` uses): Σ over the
league's scoring keys of mult × that key's expected stat, plus the TE premium
on expected receptions when a season has one. With today's settings (PPR, 4-pt
passing TD, −2 INT, 6-pt rush/rec TD, 2-pt 2) that reproduces ffopportunity's
own total within about half a point (max 0.51; it rounds the components it publishes; the
mean gap is ~0), which `tests/test_usage.py` checks; a future change to
the league's scoring (first downs, TE premium, per-carry points) flows through
on its own.

What xFP cannot see — so Points minus xFP absorbs it:
  * fumbles (ffopportunity models none; the league scores −1 per fumble, −1
    more when lost),
  * return / fumble-recovery TDs and fumble-return yards,
  * yardage bonuses (the league has none today; scored if added).
A player's xFP is blank, not 0, on a week nflverse shows he did not play
(no snaps, no stat line, no ffopportunity row) — bye, injury, inactive, the
not-yet-played live week. A week he played with no expected-points row (snaps
only) has xFP 0.

Caching: the ffopportunity files are stored gzipped (~0.8 MB a season instead
of ~5 MB) and the 20 MB play-by-play files are NEVER kept — only the derived
red-zone table (a few KB). A completed season is re-fetched after
`HISTORICAL_MAX_AGE_DAYS` (upstream rarely touches them), the in-progress one
on the build's normal horizon.
"""
from __future__ import annotations

import gzip
import io
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import external as X
from .injury_tracker import looks_like_gsis

# --------------------------------------------------------------------------
# Column names
# --------------------------------------------------------------------------
SNAP = "Snap %"
TARGETS = "Targets"
CARRIES = "Carries"
TSHARE = "Target share"
AIR = "Air yards"
RZ = "Red-zone opportunities"
XFP = "xFP"
DIFF = "Points minus xFP"
WEEK_COLUMNS = (SNAP, TARGETS, CARRIES, TSHARE, AIR, RZ, XFP, DIFF)

WEEKS = "Weeks with usage data"
AVG_SNAP = "Avg snap %"
AVG_TSHARE = "Avg target share"
AVG_XFP = "Avg xFP"
AVG_DIFF = "Avg points minus xFP"
PLAYER_PERIOD_COLUMNS = (WEEKS, AVG_SNAP, TARGETS, CARRIES, AVG_TSHARE, AIR, RZ,
                         XFP, AVG_XFP, DIFF, AVG_DIFF)

ST_XFP = "Starters' xFP"
ST_DIFF = "Starters' points minus xFP"
TEAM_WEEK_COLUMNS = (ST_XFP, ST_DIFF)
AVG_ST_XFP = "Avg starters' xFP"
AVG_ST_DIFF = "Avg starters' points minus xFP"
TEAM_PERIOD_COLUMNS = (ST_XFP, AVG_ST_XFP, ST_DIFF, AVG_ST_DIFF)

ALL_COLUMNS = tuple(dict.fromkeys(WEEK_COLUMNS + PLAYER_PERIOD_COLUMNS
                                  + TEAM_WEEK_COLUMNS + TEAM_PERIOD_COLUMNS))
# Whole-number columns (lotg_support.number_format / the export's Int64 pass).
COUNT_COLUMNS = (TARGETS, CARRIES, AIR, RZ, WEEKS)
# Stored 0-1, shown as percents.
FRACTION_COLUMNS = (SNAP, TSHARE, AVG_SNAP, AVG_TSHARE)

FIRST_SEASON = 2020          # nflverse snap counts / ffopportunity coverage here
HISTORICAL_MAX_AGE_DAYS = 28.0

# league scoring key -> the ffopportunity EXPECTED column it multiplies.
# (pass_att / rush_att are opportunities, not outcomes: their "expectation" is
# the attempt itself.)
XFP_SCORE_MAP: Dict[str, str] = {
    "pass_yd": "pass_yards_gained_exp",
    "pass_td": "pass_touchdown_exp",
    "pass_int": "pass_interception_exp",
    "pass_2pt": "pass_two_point_conv_exp",
    "pass_fd": "pass_first_down_exp",
    "pass_cmp": "pass_completions_exp",
    "pass_att": "pass_attempt",
    "rush_yd": "rush_yards_gained_exp",
    "rush_td": "rush_touchdown_exp",
    "rush_2pt": "rush_two_point_conv_exp",
    "rush_fd": "rush_first_down_exp",
    "rush_att": "rush_attempt",
    "rec": "receptions_exp",
    "rec_yd": "rec_yards_gained_exp",
    "rec_td": "rec_touchdown_exp",
    "rec_2pt": "rec_two_point_conv_exp",
    "rec_fd": "rec_first_down_exp",
}
# The same keys on ffopportunity's ACTUAL columns — the reconciliation the
# tests run (actual-component points vs the league's Points).
ACTUAL_SCORE_MAP: Dict[str, str] = {k: v[:-4] if v.endswith("_exp") else v
                                    for k, v in XFP_SCORE_MAP.items()}
# Scoring keys xFP has no expectation for (documented above; Points carries them).
NOT_MODELLED = ("fum", "fum_lost", "fum_rec_td", "fum_ret_yd", "st_td",
                "bonus_pass_yd_300", "bonus_pass_yd_400", "bonus_rush_yd_100",
                "bonus_rush_yd_200", "bonus_rec_yd_100", "bonus_rec_yd_200")

_FFO_URLS = (
    "https://github.com/ffverse/ffopportunity/releases/download/latest-data/ep_weekly_{season}.csv",
    "https://github.com/ffverse/ffopportunity/releases/download/v1.0.0-data/ep_weekly_{season}.csv",
)
_PBP_URLS = (
    "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet",
)
_PBP_COLS = ["season_type", "week", "yardline_100", "play_type", "two_point_attempt",
             "rush_attempt", "pass_attempt", "sack", "rusher_player_id", "receiver_player_id"]


# --------------------------------------------------------------------------
# Loaders (cached)
# --------------------------------------------------------------------------
def _max_age(season: int, current_season: Optional[int]) -> Optional[float]:
    cur = current_season or date.today().year
    return None if int(season) >= int(cur) else max(HISTORICAL_MAX_AGE_DAYS, X.cache_max_age_days())


def _fetch_bytes(urls: Sequence[str], timeout: int) -> bytes:
    import requests
    last: Optional[Exception] = None
    for url in urls:
        for trust_env in (False, True):
            try:
                s = requests.Session()
                s.trust_env = trust_env
                kw: Dict[str, Any] = {"timeout": timeout}
                if not trust_env:
                    kw["proxies"] = {"http": None, "https": None}
                r = s.get(url, **kw)
                r.raise_for_status()
                return r.content
            except Exception as e:  # pragma: no cover - network
                last = e
    raise last or RuntimeError("no url")


def _write_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    try:
        tmp.write_bytes(body)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _refresh(cfg: "X.ExternalConfig", path: Path, make, season: int,
             current_season: Optional[int], force_refresh: bool) -> None:
    """`external._ensure` semantics (a failed refresh keeps the copy on disk and
    leaves it stale) with a longer horizon for completed seasons."""
    have = path.exists() and path.stat().st_size > 0
    if not (force_refresh or X.cache_is_stale(path, _max_age(season, current_season))):
        return
    try:
        _write_atomic(path, make())
    except Exception:
        if not have:
            raise
        return
    X.record_fetch(path)


def ffo_path(cache_dir: Path, season: int) -> Path:
    return Path(cache_dir) / f"ffopportunity_ep_weekly_{int(season)}.csv.gz"


def red_zone_path(cache_dir: Path, season: int) -> Path:
    return Path(cache_dir) / f"nflverse_red_zone_{int(season)}.csv"


def load_ff_opportunity(cfg: "X.ExternalConfig", season: int, current_season: Optional[int] = None,
                        force_refresh: bool = False) -> pd.DataFrame:
    """ffopportunity's weekly expected-points file for `season`, cached gzipped
    (the body byte for byte, compressed)."""
    path = ffo_path(cfg.cache_dir, season)

    def make() -> bytes:
        body = _fetch_bytes([u.format(season=season) for u in _FFO_URLS], cfg.timeout_seconds)
        if body[:2] != b"\x1f\x8b":
            body = gzip.compress(body, mtime=0)
        return body

    _refresh(cfg, path, make, season, current_season, force_refresh)
    return pd.read_csv(path, compression="gzip", low_memory=False)


def red_zone_from_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    """Per (gsis_id, week): red-zone targets and carries in REGULAR-season
    plays. A target is a pass attempt with a listed receiver (sacks have none);
    a carry is a rush attempt (scrambles included, as nflverse's `carries`);
    two-point tries and plays wiped by penalty (`no_play`) are not counted."""
    cols = ["gsis_id", "week", "rz_targets", "rz_carries"]
    if pbp is None or pbp.empty:
        return pd.DataFrame(columns=cols)
    p = pbp
    if "season_type" in p.columns:
        p = p[p["season_type"].astype(str).str.upper() == "REG"]
    yl = pd.to_numeric(p["yardline_100"], errors="coerce")
    p = p[(yl <= 20) & p["play_type"].astype(str).isin(["pass", "run"])]
    if "two_point_attempt" in p.columns:
        p = p[pd.to_numeric(p["two_point_attempt"], errors="coerce").fillna(0) == 0]
    tgt = p[(pd.to_numeric(p["pass_attempt"], errors="coerce").fillna(0) == 1)
            & p["receiver_player_id"].notna()]
    car = p[(pd.to_numeric(p["rush_attempt"], errors="coerce").fillna(0) == 1)
            & p["rusher_player_id"].notna()]
    t = tgt.groupby(["receiver_player_id", "week"]).size().rename("rz_targets")
    t.index.names = ["gsis_id", "week"]
    c = car.groupby(["rusher_player_id", "week"]).size().rename("rz_carries")
    c.index.names = ["gsis_id", "week"]
    out = pd.concat([t, c], axis=1).fillna(0).astype(int).reset_index()
    out["week"] = out["week"].astype(int)
    return out[cols].sort_values(["week", "gsis_id"]).reset_index(drop=True)


def load_red_zone(cfg: "X.ExternalConfig", season: int, current_season: Optional[int] = None,
                  force_refresh: bool = False) -> pd.DataFrame:
    """Red-zone opportunities per (gsis_id, week). Downloads the season's
    play-by-play parquet in memory, keeps only the derived table."""
    path = red_zone_path(cfg.cache_dir, season)

    def make() -> bytes:
        body = _fetch_bytes([u.format(season=season) for u in _PBP_URLS], cfg.timeout_seconds * 3)
        pbp = pd.read_parquet(io.BytesIO(body), columns=_PBP_COLS)
        return red_zone_from_pbp(pbp).to_csv(index=False).encode()

    _refresh(cfg, path, make, season, current_season, force_refresh)
    return pd.read_csv(path, dtype={"gsis_id": str})


# --------------------------------------------------------------------------
# xFP
# --------------------------------------------------------------------------
def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def component_points(ffo: pd.DataFrame, scoring: Mapping[str, Any],
                     score_map: Mapping[str, str] = XFP_SCORE_MAP) -> pd.Series:
    """Σ mult × column over the league's scoring keys (no TE premium — that is
    position-dependent and added per player-week by `attach`)."""
    total = pd.Series(0.0, index=ffo.index)
    for key, col in score_map.items():
        mult = scoring.get(key)
        if mult:
            total = total + float(mult) * _num(ffo, col)
    return total


def _ffo_weekly(ffo: pd.DataFrame, scoring: Mapping[str, Any]) -> pd.DataFrame:
    cols = ["gsis_id", "week", "_xfp_base", "_rec_exp"]
    if ffo is None or ffo.empty or "player_id" not in ffo.columns:
        return pd.DataFrame(columns=cols)
    f = ffo[ffo["player_id"].notna()].copy()
    f["gsis_id"] = f["player_id"].astype(str).str.strip()
    f["week"] = pd.to_numeric(f["week"], errors="coerce")
    f = f.dropna(subset=["week"])
    f["_xfp_base"] = component_points(f, scoring)
    f["_rec_exp"] = _num(f, "receptions_exp")
    f["week"] = f["week"].astype(int)
    return f.groupby(["gsis_id", "week"], as_index=False)[["_xfp_base", "_rec_exp"]].sum()[cols]


def pfr_to_gsis_bridge(rosters: Iterable[pd.DataFrame], dp_ids: Optional[pd.DataFrame]) -> Dict[str, str]:
    """PFR id -> GSIS id: weekly rosters first, DynastyProcess fills gaps —
    the build's appearance-check bridge; placeholder GSIS tokens refused."""
    out: Dict[str, str] = {}
    frames = list(rosters) + ([dp_ids] if dp_ids is not None else [])
    for wr in frames:
        if wr is None or wr.empty or not {"pfr_id", "gsis_id"} <= set(wr.columns):
            continue
        for pf, gs in wr[["pfr_id", "gsis_id"]].dropna().itertuples(index=False):
            pf, gs = str(pf).strip(), str(gs).strip()
            if pf and pf.lower() != "nan" and looks_like_gsis(gs):
                out.setdefault(pf, gs)
    return out


def season_usage(season: int, stats: pd.DataFrame, snaps: pd.DataFrame, ffo: pd.DataFrame,
                 red_zone: pd.DataFrame, pfr_bridge: Mapping[str, str],
                 scoring: Mapping[str, Any]) -> pd.DataFrame:
    """One row per (gsis_id, week) nflverse shows the player PLAYING in a
    regular-season game of `season`, with the week columns (xFP before the TE
    premium in `_xfp_base`; `_rec_exp` carries the expected receptions it
    multiplies)."""
    parts: List[pd.DataFrame] = []
    if stats is not None and not stats.empty and "player_id" in stats.columns:
        s = stats
        if "season_type" in s.columns:
            s = s[s["season_type"].astype(str).str.upper() == "REG"]
        s = s[s["player_id"].notna()].copy()
        s["gsis_id"] = s["player_id"].astype(str).str.strip()
        s["week"] = pd.to_numeric(s["week"], errors="coerce")
        s = s.dropna(subset=["week"])
        s["week"] = s["week"].astype(int)
        st = pd.DataFrame({"gsis_id": s["gsis_id"], "week": s["week"],
                           TARGETS: _num(s, "targets"), CARRIES: _num(s, "carries"),
                           AIR: _num(s, "receiving_air_yards"),
                           TSHARE: pd.to_numeric(s.get("target_share"), errors="coerce")})
        st = st.groupby(["gsis_id", "week"], as_index=False).agg(
            {TARGETS: "sum", CARRIES: "sum", AIR: "sum", TSHARE: "max"})
        parts.append(st)
    if snaps is not None and not snaps.empty and {"pfr_player_id", "week"} <= set(snaps.columns):
        n = snaps
        if "game_type" in n.columns:
            n = n[n["game_type"].astype(str).str.upper() == "REG"]
        n = n.copy()
        tot = sum(_num(n, c) for c in ("offense_snaps", "defense_snaps", "st_snaps"))
        n = n[tot > 0]
        n["gsis_id"] = n["pfr_player_id"].astype(str).str.strip().map(pfr_bridge)
        n = n.dropna(subset=["gsis_id"])
        n["week"] = pd.to_numeric(n["week"], errors="coerce")
        n = n.dropna(subset=["week"])
        n["week"] = n["week"].astype(int)
        n[SNAP] = _num(n, "offense_pct")
        parts.append(n.groupby(["gsis_id", "week"], as_index=False)[SNAP].max())
    fw = _ffo_weekly(ffo, scoring)
    # ffopportunity carries the postseason too (weeks past the regular season);
    # keep the regular-season weeks the stat / snap files list.
    reg_weeks = set().union(*[set(p["week"]) for p in parts]) if parts else set()
    if reg_weeks and not fw.empty:
        fw = fw[fw["week"].isin(reg_weeks)]
    if not fw.empty:
        parts.append(fw)
    key = ["gsis_id", "week"]
    if not parts:
        return pd.DataFrame(columns=key + ["Year", SNAP, TARGETS, CARRIES, TSHARE, AIR, RZ,
                                           "_xfp_base", "_rec_exp"])
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on=key, how="outer")
    if red_zone is not None and not red_zone.empty:
        rz = red_zone.copy()
        rz["gsis_id"] = rz["gsis_id"].astype(str)
        rz["week"] = pd.to_numeric(rz["week"], errors="coerce").astype(int)
        rz[RZ] = _num(rz, "rz_targets") + _num(rz, "rz_carries")
        out = out.merge(rz[key + [RZ]], on=key, how="left")
    for c in (SNAP, TARGETS, CARRIES, AIR, RZ, "_xfp_base", "_rec_exp"):
        if c not in out.columns:
            out[c] = 0.0
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    if TSHARE not in out.columns:
        out[TSHARE] = None
    # A played week with no target-share row (no targets) is a 0 share.
    out[TSHARE] = pd.to_numeric(out[TSHARE], errors="coerce").fillna(0.0)
    out["Year"] = int(season)
    return out


# --------------------------------------------------------------------------
# Attaching to the sheets
# --------------------------------------------------------------------------
def attach(pw: pd.DataFrame, usage: pd.DataFrame, pid_to_gsis: Mapping[str, Optional[str]],
           scoring_by_season: Mapping[int, Mapping[str, Any]]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """player_week with the week columns filled, plus a per-row match report
    (Player ID, Player, Year, Week, gsis_id, status) for every row from
    FIRST_SEASON on: status is "matched", "did not play" (bridged, no nflverse
    game that week) or "no gsis" (the player id has no GSIS bridge)."""
    pw = pw.copy()
    for c in WEEK_COLUMNS:
        pw[c] = None
    if pw.empty or "Player ID" not in pw.columns:
        return pw, pd.DataFrame()
    yr = pd.to_numeric(pw["Year"], errors="coerce")
    wk = pd.to_numeric(pw["Week"], errors="coerce")
    gsis = pw["Player ID"].map(lambda p: pid_to_gsis.get(str(p)) if pd.notna(p) else None)
    in_scope = yr >= FIRST_SEASON
    u = usage.set_index(["gsis_id", "Year", "week"]) if not usage.empty else None
    rows = []
    vals = {c: [None] * len(pw) for c in WEEK_COLUMNS}
    pos = pw["Position"].astype(str).str.upper() if "Position" in pw.columns else pd.Series("", index=pw.index)
    pts = pd.to_numeric(pw.get("Points"), errors="coerce")
    for i, (g, y, w, ok) in enumerate(zip(gsis, yr, wk, in_scope)):
        if not ok or pd.isna(y) or pd.isna(w):
            continue
        status = "no gsis"
        if g:
            status = "did not play"
            if u is not None:
                k = (str(g), int(y), int(w))
                if k in u.index:
                    r = u.loc[k]
                    if isinstance(r, pd.DataFrame):
                        r = r.iloc[0]
                    status = "matched"
                    sc = scoring_by_season.get(int(y)) or {}
                    xfp = float(r["_xfp_base"])
                    if pos.iat[i] == "TE" and sc.get("bonus_rec_te"):
                        xfp += float(sc["bonus_rec_te"]) * float(r["_rec_exp"])
                    vals[SNAP][i] = round(float(r[SNAP]), 4)
                    vals[TARGETS][i] = int(round(float(r[TARGETS])))
                    vals[CARRIES][i] = int(round(float(r[CARRIES])))
                    vals[TSHARE][i] = round(float(r[TSHARE]), 4)
                    vals[AIR][i] = int(round(float(r[AIR])))
                    vals[RZ][i] = int(round(float(r[RZ])))
                    vals[XFP][i] = round(xfp, 2)
                    p = pts.iat[i]
                    vals[DIFF][i] = round(float(p) - xfp, 2) if pd.notna(p) else None
        rows.append((pw["Player ID"].iat[i], pw["Player"].iat[i] if "Player" in pw.columns else None,
                     int(y), int(w), g, status))
    for c in WEEK_COLUMNS:
        pw[c] = vals[c]
    report = pd.DataFrame(rows, columns=["Player ID", "Player", "Year", "Week", "gsis_id", "status"])
    return pw, report


def match_summary(report: pd.DataFrame, pw: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Per season: player-weeks in scope, matched, did-not-play, no-gsis, and
    the match rate among bridged rows that played (points > 0 or snaps)."""
    if report is None or report.empty:
        return pd.DataFrame()
    g = report.groupby(["Year", "status"]).size().unstack(fill_value=0)
    for c in ("matched", "did not play", "no gsis"):
        if c not in g.columns:
            g[c] = 0
    g["rows"] = g[["matched", "did not play", "no gsis"]].sum(axis=1)
    g["bridged %"] = ((g["rows"] - g["no gsis"]) / g["rows"]).round(4)
    return g.reset_index()


def unmatched_players(report: pd.DataFrame) -> pd.DataFrame:
    """Every rostered player with at least one in-scope row and no GSIS bridge,
    with how many player-weeks he has — the over-inclusive list."""
    if report is None or report.empty:
        return pd.DataFrame(columns=["Player ID", "Player", "Years", "Player-weeks"])
    r = report[report["status"] == "no gsis"]
    if r.empty:
        return pd.DataFrame(columns=["Player ID", "Player", "Years", "Player-weeks"])
    return (r.groupby(["Player ID", "Player"])
             .agg(Years=("Year", lambda s: ",".join(str(x) for x in sorted(set(s)))),
                  **{"Player-weeks": ("Week", "size")})
             .reset_index().sort_values("Player-weeks", ascending=False).reset_index(drop=True))


def _period(g: pd.DataFrame) -> Dict[str, Any]:
    x = pd.to_numeric(g[XFP], errors="coerce")
    has = x.notna()
    n = int(has.sum())
    if n == 0:
        return {c: None for c in PLAYER_PERIOD_COLUMNS} | {WEEKS: 0}

    def s(col, nd=2):
        return round(float(pd.to_numeric(g.loc[has, col], errors="coerce").fillna(0).sum()), nd)

    def a(col):
        return round(float(pd.to_numeric(g.loc[has, col], errors="coerce").mean()), 4)
    xs, ds = s(XFP), s(DIFF)
    return {WEEKS: n, AVG_SNAP: a(SNAP), TARGETS: int(s(TARGETS, 0)), CARRIES: int(s(CARRIES, 0)),
            AVG_TSHARE: a(TSHARE), AIR: int(s(AIR, 0)), RZ: int(s(RZ, 0)),
            XFP: xs, AVG_XFP: round(xs / n, 2), DIFF: ds, AVG_DIFF: round(ds / n, 2)}


def player_rollup(pw: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """The player period columns over player_week rows grouped by `keys`
    (["Player ID", "Year"] / ["Player ID"]). Averages are per week of usage
    data (a week nflverse shows him playing while rostered), not per rostered
    week; a player with none reads blank, Weeks with usage data 0."""
    keys = list(keys)
    if pw is None or pw.empty or not set(keys + [XFP]) <= set(pw.columns):
        return pd.DataFrame(columns=keys + list(PLAYER_PERIOD_COLUMNS))
    f = pw[pw["Player ID"].notna()].copy()
    if "Year" in keys:
        f["Year"] = pd.to_numeric(f["Year"], errors="coerce").astype("Int64")
    f["Player ID"] = f["Player ID"].astype(str)
    rows = []
    for k, g in f.groupby(keys):
        k = k if isinstance(k, tuple) else (k,)
        rows.append(dict(zip(keys, k)) | _period(g))
    out = pd.DataFrame(rows, columns=keys + list(PLAYER_PERIOD_COLUMNS))
    if "Year" in keys:
        out["Year"] = out["Year"].astype(int)
    return out


def team_week_rollup(pw: pd.DataFrame) -> pd.DataFrame:
    """(Team, Year, Week) -> Starters' xFP and Starters' points minus xFP:
    sums over the week's starters who have an xFP (a starter who did not play
    contributes nothing to either; an unbridged starter is left out of both,
    so the difference never charges his points against no expectation).
    Blank when no starter has an xFP (2020 weeks outside coverage, the live
    week before kickoff)."""
    keys = ["Team", "Year", "Week"]
    if pw is None or pw.empty or not set(keys + [XFP, DIFF, "Starter/Bench"]) <= set(pw.columns):
        return pd.DataFrame(columns=keys + list(TEAM_WEEK_COLUMNS))
    f = pw[pw["Starter/Bench"] == "Starter"][keys + [XFP, DIFF]].copy()
    f["Year"] = pd.to_numeric(f["Year"], errors="coerce")
    f["Week"] = pd.to_numeric(f["Week"], errors="coerce")
    f["Team"] = f["Team"].astype(str)
    f[XFP] = pd.to_numeric(f[XFP], errors="coerce")
    f[DIFF] = pd.to_numeric(f[DIFF], errors="coerce")
    f = f.dropna(subset=["Year", "Week"])
    g = f.groupby(keys).agg(**{ST_XFP: (XFP, lambda s: s.sum(min_count=1)),
                               ST_DIFF: (DIFF, lambda s: s.sum(min_count=1))}).reset_index()
    g[ST_XFP] = g[ST_XFP].round(2)
    g[ST_DIFF] = g[ST_DIFF].round(2)
    g["Year"] = g["Year"].astype(int)
    g["Week"] = g["Week"].astype(int)
    return g


def team_rollup(tw: pd.DataFrame, keys: Sequence[str]) -> pd.DataFrame:
    """team_week's two columns summed over `keys`, with per-team-week averages
    over the weeks that have a value."""
    keys = list(keys)
    if tw is None or tw.empty or not set(keys + list(TEAM_WEEK_COLUMNS)) <= set(tw.columns):
        return pd.DataFrame(columns=keys + list(TEAM_PERIOD_COLUMNS))
    f = tw[keys].copy()
    for k in keys:
        if k in ("Year", "Week"):
            f[k] = pd.to_numeric(f[k], errors="coerce")
    for c in TEAM_WEEK_COLUMNS:
        f[c] = pd.to_numeric(tw[c], errors="coerce")
    rows = []
    for k, g in f.groupby(keys):
        k = k if isinstance(k, tuple) else (k,)
        row = {kk: (int(v) if kk in ("Year", "Week") else v) for kk, v in zip(keys, k)}
        for c, avg in ((ST_XFP, AVG_ST_XFP), (ST_DIFF, AVG_ST_DIFF)):
            s = g[c].dropna()
            row[c] = round(float(s.sum()), 2) if not s.empty else None
            row[avg] = round(float(s.mean()), 2) if not s.empty else None
        rows.append(row)
    return pd.DataFrame(rows, columns=keys + list(TEAM_PERIOD_COLUMNS))


# --------------------------------------------------------------------------
# Build entry point
# --------------------------------------------------------------------------
def build_usage(cfg: "X.ExternalConfig", seasons: Iterable[int],
                scoring_by_season: Mapping[int, Mapping[str, Any]],
                current_season: Optional[int] = None,
                force_refresh_seasons: Iterable[int] = (),
                log=None) -> pd.DataFrame:
    """Every season's `season_usage`, concatenated. A season whose sources fail
    is skipped (its rows stay blank) and logged — usage never fails a build."""
    force = {int(s) for s in force_refresh_seasons}
    try:
        dp_ids = X.load_dynastyprocess_playerids(cfg)
    except Exception:
        dp_ids = None
    frames = []
    for season in sorted({int(s) for s in seasons if int(s) >= FIRST_SEASON}):
        fr = season in force
        try:
            stats = X.load_nflverse_stats_player_week(cfg, season, force_refresh=fr)
        except Exception as e:
            stats = None
            log and log(f"usage {season}: stats_player_week unavailable ({e})")
        try:
            snaps = X.load_nflverse_snap_counts(cfg, season, force_refresh=fr)
            rosters = X.load_nflverse_weekly_rosters(cfg, season, force_refresh=fr)
        except Exception as e:
            snaps, rosters = None, None
            log and log(f"usage {season}: snap counts unavailable ({e})")
        try:
            ffo = load_ff_opportunity(cfg, season, current_season, force_refresh=fr)
        except Exception as e:
            ffo = None
            log and log(f"usage {season}: ffopportunity unavailable ({e})")
        try:
            rz = load_red_zone(cfg, season, current_season, force_refresh=fr)
        except Exception as e:
            rz = None
            log and log(f"usage {season}: red-zone (pbp) unavailable ({e})")
        bridge = pfr_to_gsis_bridge([rosters] if rosters is not None else [], dp_ids)
        frames.append(season_usage(season, stats, snaps, ffo, rz, bridge,
                                   scoring_by_season.get(season) or {}))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# --------------------------------------------------------------------------
# Inquiry tools (advise.py / trade.py): usage straight from the nflverse cache
# --------------------------------------------------------------------------
TOOL_COLUMNS = ("G", "Snap%", "Snap% L{n}", "Tgt/G", "Car/G", "RZ/G", "xFP/G", "xFP L{n}",
                "Pts-xFP/G", "Pts-xFP L{n}")


def sleeper_to_gsis(players: Mapping[str, Mapping[str, Any]],
                    dp_ids: Optional[pd.DataFrame] = None) -> Dict[str, str]:
    """Sleeper player id -> GSIS id: Sleeper's own gsis_id, else DynastyProcess."""
    out: Dict[str, str] = {}
    if dp_ids is not None and not dp_ids.empty and {"sleeper_id", "gsis_id"} <= set(dp_ids.columns):
        for sid, gs in dp_ids[["sleeper_id", "gsis_id"]].dropna().itertuples(index=False):
            sid = str(sid).strip().removesuffix(".0")
            if looks_like_gsis(str(gs).strip()):
                out[sid] = str(gs).strip()
    for pid, m in (players or {}).items():
        gs = str((m or {}).get("gsis_id") or "").strip()
        if looks_like_gsis(gs):
            out[str(pid)] = gs
    return out


def tool_points(ffo: pd.DataFrame, scoring: Mapping[str, Any]) -> pd.DataFrame:
    """Per (gsis_id, week): league-scored points of the plays ffopportunity
    lists (its ACTUAL columns; lost fumbles charged at fum + fum_lost) and
    xFP. Used by the tools for Points minus xFP on players the exports do not
    hold (free agents); the exports use the league's own Points."""
    if ffo is None or ffo.empty:
        return pd.DataFrame(columns=["gsis_id", "week", "pts", "xfp"])
    f = ffo[ffo["player_id"].notna()].copy()
    fum = float(scoring.get("fum") or 0) + float(scoring.get("fum_lost") or 0)
    f["pts"] = (component_points(f, scoring, ACTUAL_SCORE_MAP)
                + fum * (_num(f, "rec_fumble_lost") + _num(f, "rush_fumble_lost")))
    f["xfp"] = component_points(f, scoring)
    f["gsis_id"] = f["player_id"].astype(str).str.strip()
    f["week"] = pd.to_numeric(f["week"], errors="coerce")
    f = f.dropna(subset=["week"])
    f["week"] = f["week"].astype(int)
    return f.groupby(["gsis_id", "week"], as_index=False)[["pts", "xfp"]].sum()


TOOL_CURRENT_MAX_AGE_DAYS = 2.0


def _tool_read(cfg: "X.ExternalConfig", name: str, current: bool, fetch) -> pd.DataFrame:
    """The tools' read: a completed season's cached file as it is (the build
    keeps it fresh; re-downloading whole seasons would cost a minute per
    inquiry), the current season's re-fetched once it is 2+ days old, and
    anything missing fetched."""
    path = Path(cfg.cache_dir) / name
    if path.exists() and path.stat().st_size > 0 and not (
            current and X.cache_is_stale(path, TOOL_CURRENT_MAX_AGE_DAYS)):
        if name.endswith(".gz"):
            return pd.read_csv(path, compression="gzip", low_memory=False)
        return X.read_cached_csv(path, low_memory=False,
                                 **({"dtype": {"gsis_id": str}} if "red_zone" in name else {}))
    try:
        return fetch()
    except Exception:
        if path.exists():
            return _tool_read(cfg, name, False, fetch)
        raise


def usage_table(pids: Iterable[str], season: int, through_week: int, gsis_by_pid: Mapping[str, str],
                scoring: Mapping[str, Any], recent: int = 3, cache_dir: Optional[Path] = None,
                positions: Optional[Mapping[str, str]] = None) -> pd.DataFrame:
    """One row per Sleeper pid: games, snap %, targets / carries / red-zone
    looks per game, xFP per game and Points minus xFP per game over `season`
    weeks 1..through_week, and the same for the last `recent` of those weeks
    (by NFL week, so a bye shortens the window). Read from the build's cache,
    refreshed when stale like every other nflverse file. Rows with no data
    read NaN."""
    from . import inquiry as Q
    cfg = X.ExternalConfig(cache_dir=Path(cache_dir) if cache_dir else Q.repo_root() / ".cache")
    n = int(recent)
    cols = [c.format(n=n) for c in TOOL_COLUMNS]
    pids = [str(p) for p in pids]
    try:
        cur = season >= date.today().year
        stats = _tool_read(cfg, f"nflverse_stats_player_week_{season}.csv", cur,
                           lambda: X.load_nflverse_stats_player_week(cfg, season, force_refresh=True))
        snaps = _tool_read(cfg, f"nflverse_snap_counts_{season}.csv", cur,
                           lambda: X.load_nflverse_snap_counts(cfg, season, force_refresh=True))
        rosters = _tool_read(cfg, f"nflverse_weekly_rosters_{season}.csv", cur,
                             lambda: X.load_nflverse_weekly_rosters(cfg, season, force_refresh=True))
        ffo = _tool_read(cfg, ffo_path(cfg.cache_dir, season).name, cur,
                         lambda: load_ff_opportunity(cfg, season, season, force_refresh=True))
        rz = _tool_read(cfg, red_zone_path(cfg.cache_dir, season).name, cur,
                        lambda: load_red_zone(cfg, season, season, force_refresh=True))
        dp = _tool_read(cfg, "dynastyprocess_playerids.csv", False,
                        lambda: X.load_dynastyprocess_playerids(cfg))
    except Exception:
        return pd.DataFrame(index=pd.Index(pids, name="pid"), columns=cols, dtype=float)
    u = season_usage(season, stats, snaps, ffo, rz, pfr_to_gsis_bridge([rosters], dp), scoring)
    u = u[u["week"] <= int(through_week)]
    tp = tool_points(ffo, scoring)
    u = u.merge(tp, on=["gsis_id", "week"], how="left")
    te_bonus = float(scoring.get("bonus_rec_te") or 0)
    want = {gsis_by_pid.get(p) for p in pids} - {None}
    u = u[u["gsis_id"].isin(want)].copy()
    if te_bonus and positions:
        te = {gsis_by_pid.get(p) for p in pids if positions.get(p) == "TE"}
        u.loc[u["gsis_id"].isin(te), "xfp"] = u["xfp"].fillna(0) + te_bonus * u["_rec_exp"]
    u["xfp"] = u["xfp"].fillna(0.0)
    u["diff"] = u["pts"] - u["xfp"]
    last = u[u["week"] > int(through_week) - n]
    a = u.groupby("gsis_id").agg(G=("week", "size"), s=(SNAP, "mean"), t=(TARGETS, "mean"),
                                 c=(CARRIES, "mean"), r=(RZ, "mean"), x=("xfp", "mean"), d=("diff", "mean"))
    l = last.groupby("gsis_id").agg(s=(SNAP, "mean"), x=("xfp", "mean"), d=("diff", "mean"))
    rows = []
    for pid in pids:
        g = gsis_by_pid.get(pid)
        if g not in a.index:
            rows.append([0] + [np.nan] * (len(cols) - 1))
            continue
        A, L = a.loc[g], (l.loc[g] if g in l.index else None)
        lv = (lambda k, nd: round(float(L[k]), nd) if L is not None and pd.notna(L[k]) else np.nan)
        rows.append([int(A["G"]), round(A["s"], 2), lv("s", 2), round(A["t"], 1), round(A["c"], 1),
                     round(A["r"], 1), round(A["x"], 1), lv("x", 1),
                     round(A["d"], 1) if pd.notna(A["d"]) else np.nan, lv("d", 1)])
    return pd.DataFrame(rows, index=pd.Index(pids, name="pid"), columns=cols)


def usage_flags(t: pd.DataFrame, names: Mapping[str, str], recent: int = 3,
                role: float = 3.0, luck: float = 4.0) -> List[str]:
    """Data flags (not verdicts) for the tools' caveats: recent xFP per game
    `role`+ away from the season's (an opportunity change), and recent points
    minus xFP `luck`+ away from 0 (scoring beyond / below the opportunity)."""
    n = int(recent)
    out = []
    for pid, r in t.iterrows():
        nm = names.get(pid, pid)
        xs, xl = r.get("xFP/G"), r.get(f"xFP L{n}")
        dl = r.get(f"Pts-xFP L{n}")
        if pd.notna(xs) and pd.notna(xl) and abs(xl - xs) >= role:
            out.append(f"{nm}: xFP L{n} {xl:g} vs season {xs:g} — opportunity "
                       f"{'UP' if xl > xs else 'DOWN'} (snap% L{n} {r.get(f'Snap% L{n}')} vs {r.get('Snap%')}) — "
                       f"check the depth chart / news for a role change")
        if pd.notna(dl) and abs(dl) >= luck:
            out.append(f"{nm}: points minus xFP L{n} {dl:+g}/game — scoring "
                       f"{'above' if dl > 0 else 'below'} what the opportunity usually yields; "
                       f"efficiency / TD swings tend not to repeat")
    return out
