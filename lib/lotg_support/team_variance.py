"""Team-level score swings and lineup correlation: how up-and-down a team's
scores are, how much its starters rise and fall together, and whether it took
more risk as an underdog. Names are plain words [per user, 2026-10-29: "most
understandable to avg person w/o stats background"]: "swing" = standard
deviation (how far a score typically lands from its average), "riskiness" =
swing relative to lineups of the same strength.

team_week (one row per team-week; all "before kickoff", from data known then):
- `Lineup swing`: the standard deviation of the starters' total the lineup
  carried INTO the week, sqrt(sum_i s_i^2 + 2 sum_{i<j} rho_ij s_i s_j). s_i is
  the player's own SD over his previous `WINDOW` played weeks (point in time:
  only weeks before this one), shrunk toward his position's SD with weight
  `SHRINK`; rho_ij comes from `PAIR_RHO` (same NFL team, or the two sides of one
  NFL game), every other pair 0. A player with no history gets his position's.
- `Lineup swing vs league`: that over the mean of every team's that week, so
  1.20 = 20% swingier than the league's average lineup. Comparing within a week
  puts the 9-starter (2020-23) and 10-starter (2024+) seasons on one scale for
  this column; the raw `Lineup swing` is NOT normalised and grows with the 10th
  slot.
- `Lineup riskiness`: Lineup swing over the swing a lineup with the same
  Enhanced Projection normally carries that week: exp(dlog SD - B dlog proj),
  each d = minus the week's league mean, B = `PROJ_SLOPE` (fitted 0.49: swing
  grows with the square root of the projection). Raw swing is mostly talent
  (Spearman +0.43 with pre-week Win %); riskiness is not (-0.02), so it is the
  manager's pick of boom-or-bust vs steady players at a given strength.
  1.05 = 5% swingier than normal for that projection.
- `Swing added by stacking`: Lineup swing minus the swing the same starters
  would have if they were unrelated (the correlation terms' share, in points).
- `Matchup swing`: the SD of the MARGIN, sqrt(Var(own) + Var(opp) -
  2 Cov(own, opp)): how far the result typically lands from the projected
  margin. Starters in the opponent's NFL games lower it.
- `QB-receiver stacks`: started WR/TE from a started QB's NFL team (a QB with
  two of them is 2). The existing `Stacks` also counts RBs; QB-RB barely
  move together here (rho 0.05), so this is the pass-catcher-only count.
- `Starter pairs in the same NFL game`: pairs of own starters in one NFL game
  (same team or opponents).
- `Pairs sharing an NFL game with opponent`: (own starter, opponent starter)
  pairs in one NFL game.
- `Boom week?` / `Bust week?`: starters' points at least 120% / at most 80% of
  the league median that week (starters' points, so the semifinal +5 in PF is
  out; the league that week = every team_week row).

team_year / team_all_time: `Weekly score swing` (SD of the starters' weekly
points) and `Weekly score swing %` (that / the mean) — AceMatthew's league-chat
charts, "scoring level vs consistency"; every week with a matchup, playoffs and
consolation included, which reproduces them exactly (median 17.0%, r = -0.41
against the mean over completed seasons). On team_year also `Avg score (first
6 weeks)` and `Weekly score swing % (first 6 weeks)` (his second chart, which
sets a season in progress against past seasons at the same point; N/A until a
team has all `FIRST_N` weeks). Then `Boom week %`, `Bust week %`, `Avg lineup
swing vs league`, `Avg lineup riskiness` and the same as an underdog /
favorite (pre-week Win % (Enhanced Projection) below / at or above 50%), `Avg
swing added by stacking`, `Underdog win % (risky lineup)` / `(safe lineup)`
(riskiness >= 1 / < 1) and the three pair counts summed (like `Stacks`).
league_year / league_all_time: the two underdog win % pooled over every team,
plus `Underdog weeks (...)` counts so the sample is visible.

`PAIR_RHO` and `POS_SD` were fitted once on every played player-week 2020 -
2026 wk 8 (residual from the player's season mean, players with 6+ played
weeks; 2,000-10,000 pairs per same-team type) and are fixed here, so a week's
row does not move when later weeks arrive. tests/test_team_variance.py refits
them from the exports and fails if a value drifts by more than 0.08.
"""
from __future__ import annotations

import itertools
import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

WINDOW = 17          # previous played weeks behind a player's spread
SHRINK = 4.0         # pseudo-weeks of his position's spread mixed in
BOOM = 1.20          # starters' points >= 120% of the week's league median
BUST = 0.80          # <= 80%
FIRST_N = 6         # the early-season window of the first-6-weeks pair
UNDERDOG_COL = "Pre-week Win % (Enhanced Projection)"
PROJ_COL = "Enhanced Projection"
PROJ_SLOPE = 0.5     # d log(lineup SD) / d log(projection) across a week's lineups (fitted 0.49)

# Residual spread by position (points per week), every played week 2020-2026 wk 8.
POS_SD = {"QB": 7.2, "RB": 6.7, "WR": 7.0, "TE": 6.3}
DEFAULT_SD = 6.9

# Correlation of two players' weekly residuals: ("same" NFL team | "opp", the two
# sides of one game, positions sorted). Fitted values; unlisted pairs are 0.
PAIR_RHO: Dict[Tuple[str, str, str], float] = {
    ("same", "QB", "WR"): 0.30, ("same", "QB", "TE"): 0.27, ("same", "QB", "RB"): 0.05,
    ("same", "QB", "QB"): -0.36, ("same", "TE", "WR"): 0.02, ("same", "RB", "WR"): -0.02,
    ("same", "RB", "TE"): -0.03, ("same", "TE", "TE"): 0.05,
    ("opp", "QB", "QB"): 0.18, ("opp", "QB", "WR"): 0.07, ("opp", "QB", "TE"): 0.05,
    ("opp", "QB", "RB"): 0.03, ("opp", "WR", "WR"): 0.06, ("opp", "TE", "TE"): 0.11,
    ("opp", "TE", "WR"): 0.04, ("opp", "RB", "TE"): 0.03, ("opp", "RB", "WR"): 0.02,
    ("opp", "RB", "RB"): -0.03,
}

WEEK_COLUMNS = [
    "Lineup swing", "Lineup swing vs league", "Lineup riskiness",
    "Swing added by stacking",
    "Matchup swing", "QB-receiver stacks", "Starter pairs in the same NFL game",
    "Pairs sharing an NFL game with opponent", "Boom week?", "Bust week?",
]
COUNT_COLUMNS = ["QB-receiver stacks", "Starter pairs in the same NFL game", "Pairs sharing an NFL game with opponent"]
HV_WIN, LV_WIN = "Underdog win % (risky lineup)", "Underdog win % (safe lineup)"
HV_N, LV_N = "Underdog weeks (risky lineup)", "Underdog weeks (safe lineup)"
SCORE_COLUMNS = ["Avg weekly score", "Weekly score swing", "Weekly score swing %"]
TEAM_COLUMNS = SCORE_COLUMNS[:1] + [
    "Weekly score swing", "Weekly score swing %", "Boom week %", "Bust week %",
    "Avg lineup swing vs league", "Avg lineup riskiness",
    "Avg lineup riskiness as underdog", "Avg lineup riskiness as favorite",
    "Avg swing added by stacking",
    HV_WIN, LV_WIN,
] + COUNT_COLUMNS
FIRST_SUFFIX = f" (first {FIRST_N} weeks)"
SOFAR_SUFFIX = " (to this point)"
FIRST_COLUMNS = [c + FIRST_SUFFIX for c in SCORE_COLUMNS]
SOFAR_COLUMNS = [c + SOFAR_SUFFIX for c in SCORE_COLUMNS]
PCTL_COLUMNS = ["Avg weekly score percentile" + SOFAR_SUFFIX, "Weekly score swing % percentile" + SOFAR_SUFFIX]
STYLE, STYLE_SOFAR = "Scoring style", "Scoring style" + SOFAR_SUFFIX
TEAM_YEAR_COLUMNS = (TEAM_COLUMNS[:3] + FIRST_COLUMNS + SOFAR_COLUMNS + PCTL_COLUMNS + [STYLE, STYLE_SOFAR]
                     + TEAM_COLUMNS[3:])
LEAGUE_MEDIAN = "Median team weekly score swing %"
LEAGUE_COLUMNS = [HV_WIN, LV_WIN, HV_N, LV_N]
LEAGUE_YEAR_COLUMNS = [LEAGUE_MEDIAN] + LEAGUE_COLUMNS
ALL_COLUMNS = list(dict.fromkeys(WEEK_COLUMNS + TEAM_YEAR_COLUMNS + LEAGUE_YEAR_COLUMNS))
# Lower-cased names, for the workbook's topic band (`lotg._col_topic`).
TOPIC_NAMES = frozenset(c.lower() for c in ALL_COLUMNS)

_NO_TEAM = {"", "NFL", "NAN", "NONE", "FA", "N/A"}


def _team(t) -> str:
    s = str(t or "").strip().upper()
    return "" if s in _NO_TEAM else s


def nfl_opponents(games: Optional[pd.DataFrame]) -> Dict[Tuple[int, int, str], str]:
    """(season, week, NFL team) -> its opponent that week, regular season only."""
    out: Dict[Tuple[int, int, str], str] = {}
    if games is None or games.empty or not {"season", "week", "home_team", "away_team"}.issubset(games.columns):
        return out
    g = games
    if "game_type" in g.columns:
        g = g[g["game_type"].astype(str).str.upper() == "REG"]
    for s, w, h, a in g[["season", "week", "home_team", "away_team"]].itertuples(index=False):
        try:
            s, w = int(s), int(w)
        except (TypeError, ValueError):
            continue
        h, a = _team(h), _team(a)
        if h and a:
            out[(s, w, h)] = a
            out[(s, w, a)] = h
    return out


def relation(team_a: str, team_b: str, opp_of_a: Optional[str]) -> Optional[str]:
    """'same' NFL team, 'opp' (two sides of one game), else None."""
    if not team_a or not team_b:
        return None
    if team_a == team_b:
        return "same"
    if opp_of_a and opp_of_a == team_b:
        return "opp"
    return None


def pair_rho(rel: Optional[str], pos_a: str, pos_b: str) -> float:
    if rel is None:
        return 0.0
    a, b = sorted((str(pos_a).upper(), str(pos_b).upper()))
    return PAIR_RHO.get((rel, a, b), 0.0)


def _flag(v) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def player_sd(pw: pd.DataFrame) -> pd.Series:
    """Each player_week row's pre-week spread: the SD of the player's previous
    `WINDOW` played weeks (bye / injured / no-points rows are not played),
    shrunk toward his position's spread. Index = pw's index."""
    key = "Player ID" if "Player ID" in pw.columns else "Player"
    d = pd.DataFrame({
        "k": pw[key].astype(str),
        "o": pd.to_numeric(pw["Year"], errors="coerce") * 100 + pd.to_numeric(pw["Week"], errors="coerce"),
        "pts": pd.to_numeric(pw["Points"], errors="coerce"),
        "pos": pw["Position"].astype(str).str.upper() if "Position" in pw.columns else "",
    }, index=pw.index)
    played = d["pts"].notna() & d["o"].notna()
    for c in ("Bye?", "Injury?"):
        if c in pw.columns:
            played &= ~pw[c].map(_flag)
    p = d[played].drop_duplicates(["k", "o"]).sort_values(["k", "o"])
    grp = p.groupby("k", sort=False)["pts"]
    # Stats through each played week (inclusive); a row reads the last one BEFORE it.
    p = p.assign(n=grp.cumcount().add(1).clip(upper=WINDOW),
                 var=grp.transform(lambda s: s.rolling(WINDOW, min_periods=2).var(ddof=1)))
    prior = d.assign(_i=np.arange(len(d))).dropna(subset=["o"]).sort_values("o")
    hist = p[["k", "o", "n", "var"]].sort_values("o")
    m = pd.merge_asof(prior, hist, on="o", by="k", allow_exact_matches=False, direction="backward")
    pos_var = m["pos"].map(lambda x: POS_SD.get(x, DEFAULT_SD) ** 2)
    n = m["n"].where(m["var"].notna(), 0.0).fillna(0.0)
    var = ((n * m["var"].fillna(0.0)) + SHRINK * pos_var) / (n + SHRINK)
    out = pd.Series(np.nan, index=d.index)
    out.iloc[m["_i"].to_numpy()] = np.sqrt(var.to_numpy())
    # Rows with no Year/Week (none in practice) take the position's spread.
    miss = out.isna()
    out[miss] = d.loc[miss, "pos"].map(lambda x: POS_SD.get(x, DEFAULT_SD))
    return out


def _cov(a: Sequence[tuple], b: Optional[Sequence[tuple]], opp: Dict, y: int, w: int) -> float:
    """Sum of rho s s over pairs (within `a` when b is None, else across a x b).
    Items are (pos, nfl team, sd)."""
    pairs = itertools.combinations(a, 2) if b is None else itertools.product(a, b)
    tot = 0.0
    for (pa, ta, sa), (pb, tb, sb) in pairs:
        r = pair_rho(relation(ta, tb, opp.get((y, w, ta))), pa, pb)
        if r:
            tot += r * sa * sb
    return tot


def _same_game_pairs(a: Sequence[tuple], b: Optional[Sequence[tuple]], opp: Dict, y: int, w: int) -> int:
    pairs = itertools.combinations(a, 2) if b is None else itertools.product(a, b)
    return sum(1 for (_, ta, _), (_, tb, _) in pairs if relation(ta, tb, opp.get((y, w, ta))))


def week_columns(pw: pd.DataFrame, tw: pd.DataFrame, games: Optional[pd.DataFrame]) -> pd.DataFrame:
    """The team_week columns, one row per team_week (Team, Year, Week) that has
    starters; a week with none gets no row, so a left merge leaves it N/A."""
    keys = ["Team", "Year", "Week"]
    cols = keys + WEEK_COLUMNS + ["_pts"]
    if pw is None or pw.empty or tw is None or tw.empty:
        return pd.DataFrame(columns=cols)
    opp = nfl_opponents(games)
    st = pw[pw["Starter/Bench"].astype(str) == "Starter"].copy()
    if st.empty:
        return pd.DataFrame(columns=cols)
    st["_sd"] = player_sd(pw).loc[st.index]
    st["_y"] = pd.to_numeric(st["Year"], errors="coerce")
    st["_w"] = pd.to_numeric(st["Week"], errors="coerce")
    st["_t"] = st["NFL team"].map(_team) if "NFL team" in st.columns else ""
    st["_p"] = st["Position"].astype(str).str.upper()
    st["_pts"] = pd.to_numeric(st["Points"], errors="coerce")
    st = st.dropna(subset=["_y", "_w"])
    lineups: Dict[Tuple[str, int, int], List[tuple]] = {}
    pts: Dict[Tuple[str, int, int], float] = {}
    for (t, y, w), g in st.groupby(["Team", "_y", "_w"], sort=False):
        k = (str(t), int(y), int(w))
        lineups[k] = list(zip(g["_p"], g["_t"], g["_sd"]))
        pts[k] = float(g["_pts"].sum(min_count=1)) if g["_pts"].notna().any() else np.nan
    var: Dict[Tuple[str, int, int], float] = {}
    rows = []
    for k, lu in lineups.items():
        _, y, w = k
        ind = sum(s * s for _, _, s in lu)
        v = ind + 2.0 * _cov(lu, None, opp, y, w)
        var[k] = v
        qbs = [t for p, t, _ in lu if p == "QB" and t]
        catchers = [t for p, t, _ in lu if p in ("WR", "TE") and t]
        rows.append({"Team": k[0], "Year": y, "Week": w,
                     "Lineup swing": math.sqrt(max(v, 0.0)),
                     "Swing added by stacking": math.sqrt(max(v, 0.0)) - math.sqrt(ind),
                     "QB-receiver stacks": sum(catchers.count(q) for q in qbs),
                     "Starter pairs in the same NFL game": _same_game_pairs(lu, None, opp, y, w),
                     "_pts": pts[k]})
    out = pd.DataFrame(rows)
    # Opponent terms, read from team_week's Opponent.
    t2 = tw[["Team", "Year", "Week", "Opponent"] + ([PROJ_COL] if PROJ_COL in tw.columns else [])].copy()
    t2["Year"] = pd.to_numeric(t2["Year"], errors="coerce")
    t2["Week"] = pd.to_numeric(t2["Week"], errors="coerce")
    opp_of = {(str(t), int(y), int(w)): str(o) for t, y, w, o in t2.dropna(subset=["Year", "Week"])[["Team", "Year", "Week", "Opponent"]].itertuples(index=False)}
    m_sd, pairs_opp = [], []
    for t, y, w in zip(out["Team"], out["Year"], out["Week"]):
        k = (t, y, w)
        ok = (opp_of.get(k), y, w)
        if ok[0] is None or ok not in lineups:
            m_sd.append(np.nan)
            pairs_opp.append(np.nan)
            continue
        cv = _cov(lineups[k], lineups[ok], opp, y, w)
        m_sd.append(math.sqrt(max(var[k] + var[ok] - 2.0 * cv, 0.0)))
        pairs_opp.append(_same_game_pairs(lineups[k], lineups[ok], opp, y, w))
    out["Matchup swing"] = m_sd
    if PROJ_COL in t2.columns:
        _pj = {(str(t), int(y), int(w)): p for t, y, w, p in
               zip(t2["Team"], t2["Year"], t2["Week"], pd.to_numeric(t2[PROJ_COL], errors="coerce"))
               if pd.notna(y) and pd.notna(w)}
        proj = pd.Series([_pj.get(k, np.nan) for k in zip(out["Team"], out["Year"], out["Week"])], index=out.index)
    else:
        proj = pd.Series(np.nan, index=out.index)
    ls = np.log(out["Lineup swing"].where(out["Lineup swing"] > 0))
    lp = np.log(proj.where(proj > 0))
    ok = ls.notna() & lp.notna()
    _g = [out["Year"], out["Week"]]
    dls = ls - ls.where(ok).groupby(_g).transform("mean")
    dlp = lp - lp.where(ok).groupby(_g).transform("mean")
    out["Lineup riskiness"] = np.exp(dls - PROJ_SLOPE * dlp).where(ok).round(4)
    out["Pairs sharing an NFL game with opponent"] = pairs_opp
    wk = out.groupby(["Year", "Week"])
    out["Lineup swing vs league"] = out["Lineup swing"] / wk["Lineup swing"].transform("mean")
    med = wk["_pts"].transform("median")
    out["Boom week?"] = (out["_pts"] >= BOOM * med).where(out["_pts"].notna() & med.notna())
    out["Bust week?"] = (out["_pts"] <= BUST * med).where(out["_pts"].notna() & med.notna())
    for c in ("Lineup swing", "Swing added by stacking", "Matchup swing"):
        out[c] = out[c].round(2)
    out["Lineup swing vs league"] = out["Lineup swing vs league"].round(4)
    for c in COUNT_COLUMNS:
        out[c] = out[c].astype("Int64")
    for c in ("Boom week?", "Bust week?"):
        out[c] = out[c].astype(object)
    return out[cols]


def _underdog_frame(wc: pd.DataFrame, tw: pd.DataFrame) -> pd.DataFrame:
    """wc plus `_dog` (True underdog / False favorite / NaN unknown) and `_win`."""
    t2 = tw[["Team", "Year", "Week"] + [c for c in (UNDERDOG_COL, "Win?") if c in tw.columns]].copy()
    t2["Year"] = pd.to_numeric(t2["Year"], errors="coerce")
    t2["Week"] = pd.to_numeric(t2["Week"], errors="coerce")
    t2["Team"] = t2["Team"].astype(str)
    f = wc.merge(t2, on=["Team", "Year", "Week"], how="left")
    wp = pd.to_numeric(f.get(UNDERDOG_COL), errors="coerce")
    f["_dog"] = (wp < 0.5).astype(float).where(wp.notna())          # 1 underdog / 0 favorite / NaN
    f["_win"] = f["Win?"].map(lambda v: 1.0 if _flag(v) else (0.0 if str(v).strip().lower() in ("false", "0", "no") else np.nan)) \
        if "Win?" in f.columns else np.nan
    f["_hv"] = (f["Lineup riskiness"] >= 1.0).astype(float).where(f["Lineup riskiness"].notna())
    return f


def _scores(p: pd.Series, suffix: str = "") -> Dict[str, float]:
    """Average, swing (SD) and swing % (SD / average) of weekly scores."""
    sd = float(p.std(ddof=1)) if len(p) >= 2 else np.nan
    m = float(p.mean()) if len(p) else np.nan
    return {"Avg weekly score" + suffix: round(m, 2) if len(p) else np.nan,
            "Weekly score swing" + suffix: round(sd, 2) if not np.isnan(sd) else np.nan,
            "Weekly score swing %" + suffix: round(sd / m, 4) if m and not np.isnan(sd) else np.nan}


def _first(g: pd.DataFrame, n: Optional[int], suffix: str) -> Dict[str, float]:
    """The three score columns over weeks 1..n (N/A until all n weeks are in)."""
    if not n:
        return {c + suffix: np.nan for c in SCORE_COLUMNS}
    p = g.loc[g["Week"] <= n, "_pts"].dropna()
    if p.size < n:
        return {c + suffix: np.nan for c in SCORE_COLUMNS}
    return _scores(p, suffix)


def _style(avg, pct, mid_avg, mid_pct) -> Optional[str]:
    if any(pd.isna(v) for v in (avg, pct, mid_avg, mid_pct)):
        return None
    return ("High-scoring" if avg >= mid_avg else "Low-scoring") + (", up-and-down" if pct >= mid_pct else ", steady")


def _styles(ty: pd.DataFrame) -> pd.DataFrame:
    """Cross-season columns on the team_year rollup: `Scoring style` = the
    quadrant of (Avg weekly score, Weekly score swing %) against the medians of
    COMPLETED seasons; the `(to this point)` style and percentiles compare every
    team-season over the same weeks as the season in progress."""
    ty = ty.copy()
    cur = ty["Year"].max()
    done = ty[ty["Year"] < cur]
    ma, mp = done["Avg weekly score"].median(), done["Weekly score swing %"].median()
    ty[STYLE] = [_style(a, p, ma, mp) for a, p in zip(ty["Avg weekly score"], ty["Weekly score swing %"])]
    a_s, p_s = ty[SOFAR_COLUMNS[0]], ty[SOFAR_COLUMNS[2]]
    ty[STYLE_SOFAR] = [_style(a, p, a_s.median(), p_s.median()) for a, p in zip(a_s, p_s)]
    ty[PCTL_COLUMNS[0]] = (100 * a_s.rank(pct=True)).round(1)
    ty[PCTL_COLUMNS[1]] = (100 * p_s.rank(pct=True)).round(1)
    return ty


def _period(g: pd.DataFrame, sofar: Optional[int] = None) -> Dict[str, float]:
    p = g["_pts"].dropna()
    boom = g["Boom week?"].dropna().astype(bool)
    bust = g["Bust week?"].dropna().astype(bool)
    rel = g["Lineup swing vs league"]
    vc = g["Lineup riskiness"]
    dog = g["_dog"]
    is_dog, is_fav = dog == 1.0, dog == 0.0
    hv = g["_hv"]
    win = g["_win"]

    def _wr(mask):
        x = win[mask].dropna()
        return (float(x.mean()), int(len(x))) if len(x) else (np.nan, 0)

    hv_wr, hv_n = _wr(is_dog & (hv == 1.0))
    lv_wr, lv_n = _wr(is_dog & (hv == 0.0))
    return {
        **_scores(p),
        **_first(g, FIRST_N, FIRST_SUFFIX),
        **_first(g, sofar, SOFAR_SUFFIX),
        "Boom week %": round(float(boom.mean()), 4) if len(boom) else np.nan,
        "Bust week %": round(float(bust.mean()), 4) if len(bust) else np.nan,
        "Avg lineup swing vs league": round(float(rel.mean()), 4) if rel.notna().any() else np.nan,
        "Avg lineup riskiness": round(float(vc.mean()), 4) if vc.notna().any() else np.nan,
        "Avg lineup riskiness as underdog": round(float(vc[is_dog].mean()), 4) if vc[is_dog].notna().any() else np.nan,
        "Avg lineup riskiness as favorite": round(float(vc[is_fav].mean()), 4) if vc[is_fav].notna().any() else np.nan,
        "Avg swing added by stacking": round(float(g["Swing added by stacking"].mean()), 2)
        if g["Swing added by stacking"].notna().any() else np.nan,
        HV_WIN: round(hv_wr, 4) if hv_n else np.nan,
        LV_WIN: round(lv_wr, 4) if lv_n else np.nan,
        HV_N: hv_n, LV_N: lv_n,
        **{c: int(pd.to_numeric(g[c], errors="coerce").fillna(0).sum()) for c in COUNT_COLUMNS},
    }


def rollup(wc: pd.DataFrame, tw: pd.DataFrame, keys: Sequence[str], columns: Iterable[str]) -> pd.DataFrame:
    """Period rows over `keys` (["Team", "Year"], ["Team"], ["Year"] or [] for
    one league-wide row), restricted to `columns`."""
    columns = list(columns)
    keys = list(keys)
    if wc is None or wc.empty:
        return pd.DataFrame(columns=keys + columns)
    f = _underdog_frame(wc, tw)
    # "to this point" = weeks 1..the last week the season in progress has played
    cur = f["Year"].max()
    sofar = int(f.loc[f["Year"] == cur, "Week"].max())
    if keys:
        rows = [{**dict(zip(keys, k if isinstance(k, tuple) else (k,))), **_period(g, sofar)}
                for k, g in f.groupby(keys, sort=True)]
    else:
        rows = [_period(f, sofar)]
    out = pd.DataFrame(rows)
    if keys == ["Team", "Year"]:
        out = _styles(out)
    if LEAGUE_MEDIAN in columns:
        ty = rollup(wc, tw, ["Team", "Year"], ["Weekly score swing %"])
        med = ty.groupby(keys)["Weekly score swing %"].median().round(4) if keys else \
            pd.Series([ty["Weekly score swing %"].median()]).round(4)
        out[LEAGUE_MEDIAN] = med.values if keys else med.iloc[0]
    for c in (HV_N, LV_N, *COUNT_COLUMNS):
        if c in out.columns:
            out[c] = out[c].astype("Int64")
    return out[keys + columns]


def _key(v):
    """Merge key that ignores the frame's dtype: '2023', 2023 and 2023.0 match."""
    try:
        f = float(v)
        return int(f) if not math.isnan(f) else None
    except (TypeError, ValueError):
        return str(v)


def attach(frame: Optional[pd.DataFrame], cols: pd.DataFrame, keys: Sequence[str],
           columns: Sequence[str]) -> Optional[pd.DataFrame]:
    """`frame` with `columns` read from `cols` by `keys` (dtype-blind; a row with
    no match reads N/A). Existing columns of those names are replaced. With no
    keys, the one row of `cols` goes on every row of `frame`."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame
    frame = frame.drop(columns=[c for c in columns if c in frame.columns])
    if cols is None or cols.empty:
        for c in columns:
            frame[c] = np.nan
        return frame
    if not keys:
        for c in columns:
            frame[c] = cols[c].iloc[0]
        return frame
    look = {tuple(_key(v) for v in k): i for i, k in
            enumerate(zip(*[cols[c] for c in keys]))}
    pos = [look.get(tuple(_key(v) for v in k)) for k in zip(*[frame[c] for c in keys])]
    for c in columns:
        src = cols[c].tolist()
        vals = [src[i] if i is not None else None for i in pos]
        s = pd.Series(vals, index=frame.index, dtype=cols[c].dtype if cols[c].dtype != bool else object)
        frame[c] = s
    return frame
