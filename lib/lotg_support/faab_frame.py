"""Per-(player, date) stats frame for the FAAB value base — the feature builder of plan/notes/ktc_proxy/ktc_proxy.py,
moved into the library so the base model does not depend on a notes script.

Every feature is computed from what was public on the row's date: the last three completed NFL seasons (n_),
this season to date (c_), the latest contract signed (k_), depth-chart rank (d_), snap shares (s_), career to date
and the calendar (e_). `StatsModel` maps those stats to KTC's superflex scale, the stats translator's training
target (KTC is never an input). Data: lotg_support.faab_data fetches the stat files into .cache/ktc_proxy/.

The original script stays in plan/notes as the reproduction of KTC_PROXY_MODEL.md; its season calendar here is
extended back to 2014 so the walk-forward base has three completed seasons behind 2017.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / ".cache" / "ktc_proxy"
NFLV = "https://github.com/nflverse/nflverse-data/releases/download"
# Thursday kickoff of each season's week 1 (week-N stats are treated as known on
# kickoff + 7(N-1) + 5 days, i.e. the Tuesday after the week).
KO = {2014: "2014-09-04", 2015: "2015-09-10", 2016: "2016-09-08", 2017: "2017-09-07", 2018: "2018-09-06",
      2019: "2019-09-05", 2020: "2020-09-10", 2021: "2021-09-09", 2022: "2022-09-08",
      2023: "2023-09-07", 2024: "2024-09-05", 2025: "2025-09-04", 2026: "2026-09-10",
      2027: "2027-09-09"}  # 2027 is a placeholder — confirm before relying on it
POS = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}


# ----------------------------------------------------------------------------- data
def fetch(last_season: int) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    files = {"contracts.parquet": f"{NFLV}/contracts/historical_contracts.parquet"}
    for y in range(2019, last_season + 1):
        files[f"sp_{y}.csv"] = f"{NFLV}/stats_player/stats_player_reg_{y}.csv"
        files[f"wk_{y}.csv"] = f"{NFLV}/stats_player/stats_player_week_{y}.csv"
        files[f"dc_{y}.csv"] = f"{NFLV}/depth_charts/depth_charts_{y}.csv"
        files[f"snap_{y}.csv"] = f"{NFLV}/snap_counts/snap_counts_{y}.csv"
    for name, url in files.items():
        p = CACHE / name
        if p.exists() and p.stat().st_size > 0:
            continue
        try:
            urllib.request.urlretrieve(url, p)
        except Exception as exc:  # a season not yet published is fine
            print(f"skip {name}: {exc}", file=sys.stderr)


def _read(name, **kw):
    p = CACHE / name
    return pd.read_csv(p, low_memory=False, **kw) if p.exists() else None


def load_ktc(gran: str, extra_csv: str | None = None) -> pd.DataFrame:
    """One KTC value per (player, period): median of daily values. gran 'M' or 'W'."""
    rows = []
    for f in glob.glob(str(REPO / "data/ktc_backfill/*.json")):
        sid = os.path.basename(f)[:-5]
        for r in json.load(open(f)):
            if r.get("sf_trade_value") is not None:
                rows.append((sid, r["date"], float(r["sf_trade_value"])))
    pv = pd.read_csv(REPO / "exports/raw/ktc_provenance.csv")
    pv = pv[pv.asset.astype(str).str.fullmatch(r"\d+")]
    rows += [(str(a), d, float(v)) for a, d, v in pv[["asset", "quote_date_used", "value"]].itertuples(index=False)]
    if extra_csv:
        x = pd.read_csv(extra_csv)
        rows += [(str(int(a)), str(d)[:10], float(v)) for a, d, v in x[["sleeper_id", "date", "ktc"]].itertuples(index=False)]
    k = pd.DataFrame(rows, columns=["sid", "date", "ktc"]).drop_duplicates(["sid", "date"], keep="last")
    k["date"] = pd.to_datetime(k.date)
    k["per"] = k.date.dt.to_period(gran)
    return k.groupby(["sid", "per"]).agg(ktc=("ktc", "median"), date=("date", "median")).reset_index()


def player_info(sids) -> pd.DataFrame:
    pl = json.load(open(REPO / "exports/snapshot/sleeper_players_nfl.json"))
    dp = pd.read_csv(REPO / "exports/snapshot/dynastyprocess_playerids.csv")
    dp = dp[dp.sleeper_id.notna()].copy()
    dp["sid"] = dp.sleeper_id.astype("int64").astype(str)
    dp = dp.drop_duplicates("sid").set_index("sid")
    out = []
    for s in sids:
        p = pl.get(s, {})
        d = dp.loc[s] if s in dp.index else None
        bd = d.birthdate if d is not None and isinstance(d.birthdate, str) else p.get("birth_date")
        pos = d.position if d is not None and isinstance(d.position, str) else p.get("position")
        out.append(dict(sid=s, name=p.get("full_name") or (d["name"] if d is not None else None), pos=pos, bd=bd,
                        gsis=d.gsis_id if d is not None else None,
                        dyear=d.draft_year if d is not None else np.nan,
                        dovr=d.draft_ovr if d is not None else np.nan,
                        dround=d.draft_round if d is not None else np.nan,
                        yexp_now=p.get("years_exp")))
    info = pd.DataFrame(out)
    # Sleeper's years_exp is as of the snapshot (2026 season) — fallback only.
    info["dyear"] = info.dyear.fillna(2026 - pd.to_numeric(info.yexp_now, errors="coerce"))
    info["undrafted"] = info.dovr.isna() | (info.dovr == 0)
    info.loc[info.undrafted, "dovr"] = 300
    info.loc[info.undrafted, "dround"] = 8
    return info


def merge_asof(left, right, **kw):
    """pd.merge_asof with the date keys cast to nanoseconds: pandas 3 builds some datetimes at microsecond
    resolution, and merge_asof refuses keys of different resolutions"""
    on = kw.get("on"); lk = kw.get("left_on", on); rk = kw.get("right_on", on)
    def ns(df, c):
        if c is not None and c in df and str(df[c].dtype).startswith("datetime64"):
            df = df.copy(); df[c] = df[c].astype("datetime64[ns]")
        return df
    return pd.merge_asof(ns(left, lk), ns(right, rk), **kw)


def _wkdate(season, week):
    return pd.Timestamp(KO[int(season)]) + pd.to_timedelta(7 * (np.asarray(week, dtype=int) - 1) + 5, unit="D")


# ------------------------------------------------------------------------- features
_TABLES: dict = {}
_WK_MEAN = ["fantasy_points_ppr", "targets", "carries", "attempts", "target_share", "rushing_yards", "passing_yards"]


def _pd_mean(x):
    """Series.mean() of a numpy column, bit for bit (pandas' nanops.nanmean without bottleneck: NaN filled with 0,
    summed in the column's float dtype, or float64 for integers, over the non-NaN count)"""
    if x.dtype.kind == "f":
        m = np.isnan(x)
        if m.any():
            x = x.copy(); np.putmask(x, m, 0)
        with np.errstate(all="ignore"):
            return x.sum(dtype=x.dtype) / x.dtype.type(m.size - m.sum())
    return x.sum(dtype=np.float64) / np.float64(x.size)


def _tables(seasons):
    """the stat tables build() reads that do not depend on its rows: read and grouped once per process (the rebuild
    calls build three times: league rows, the KTC panel, the grid), keyed on the files and their mtimes"""
    files = [CACHE / f"{p}_{y}.csv" for y in seasons for p in ("sp", "wk", "dc", "snap")] + [REPO / "exports/snapshot/dynastyprocess_playerids.csv"]
    key = (tuple(seasons), tuple((str(f), f.stat().st_mtime_ns if f.exists() else None) for f in files))
    if _TABLES.get("key") == key:
        return _TABLES
    T = {"key": key}
    ns = pd.concat([_read(f"sp_{y}.csv") for y in seasons])
    T["ns"] = ns
    W = []
    for y in seasons:
        w = _read(f"wk_{y}.csv", usecols=["player_id", "season", "week", "season_type", "fantasy_points_ppr",
                                          "targets", "carries", "attempts", "target_share", "rushing_yards",
                                          "passing_yards"])
        if w is None:
            continue
        w = w[w.season_type == "REG"].copy()
        w["avail"] = _wkdate(y, w.week).values
        W.append(w)
    T["Wg"] = {key: v.sort_values("avail") for key, v in pd.concat(W).groupby(["player_id", "season"])}
    T["Wa"] = {key: v.avail.values for key, v in T["Wg"].items()}
    T["Wc"] = {key: [np.ascontiguousarray(v[c].to_numpy()) for c in _WK_MEAN] for key, v in T["Wg"].items()}
    D = []
    for y in seasons:
        d = _read(f"dc_{y}.csv")
        if d is None:
            continue
        if "depth_team" in d.columns:
            d = d[(d.formation == "Offense") & d.position.isin(POS) & (d.game_type == "REG")].copy()
            d["avail"] = (_wkdate(y, d.week) - pd.Timedelta(days=4)).values
            d["rank"] = pd.to_numeric(d.depth_team, errors="coerce")
        else:
            d = d[d.pos_abb.isin(POS)].copy()
            d["avail"] = pd.to_datetime(d.dt.str[:10])
            d["rank"] = d.pos_rank
        D.append(d[["gsis_id", "avail", "rank"]])
    D = pd.concat(D).groupby(["gsis_id", "avail"]).agg(rank=("rank", "min")).reset_index()
    T["snapdates"] = np.sort(D.avail.unique())
    T["Dg"] = {key: v.sort_values("avail") for key, v in D.groupby("gsis_id")}
    T["Da"] = {key: v.avail.values for key, v in T["Dg"].items()}
    T["Dr"] = {key: (list(v.avail), v["rank"].to_numpy()) for key, v in T["Dg"].items()}
    dp = pd.read_csv(REPO / "exports/snapshot/dynastyprocess_playerids.csv")
    pfr2g = dict(zip(dp.pfr_id, dp.gsis_id))
    sn = []
    for y in seasons:
        s = _read(f"snap_{y}.csv")
        if s is None:
            continue
        s = s[s.game_type == "REG"].copy()
        s["gsis"] = s.pfr_player_id.map(pfr2g)
        s["avail"] = _wkdate(y, s.week).values
        sn.append(s[["gsis", "season", "week", "avail", "offense_pct"]])
    sn = pd.concat(sn).dropna(subset=["gsis"]).sort_values(["gsis", "season", "week"])
    T["SA"] = sn.groupby(["gsis", "season"]).offense_pct.mean()
    # each game's season-to-date and last-3 mean: the same window kernels as a per-group expanding() / rolling(3, 1)
    # transform, in one pass (the per-group lambdas took ~25 s a call)
    g = sn.offense_pct.reset_index(drop=True).groupby([sn.gsis.values, sn.season.values])
    sn["cum"] = g.expanding().mean().droplevel([0, 1]).sort_index().values
    sn["l3"] = g.rolling(3, 1).mean().droplevel([0, 1]).sort_index().values
    sn["avail"] = pd.to_datetime(sn.avail).astype("datetime64[ns]")
    T["sn"] = sn.sort_values("avail")[["gsis", "avail", "season", "cum", "l3"]]
    car = ns.groupby(["player_id", "season"]).agg(ppr=("fantasy_points_ppr", "sum"), g=("games", "sum")).reset_index()
    car["ppg"] = car.ppr / car.g.replace(0, np.nan)
    T["cp"] = {pid: g[["season", "ppg", "g"]].values for pid, g in car.groupby("player_id")}
    _TABLES.clear(); _TABLES.update(T)
    return _TABLES


def build(k: pd.DataFrame) -> pd.DataFrame:
    """Every feature is computed from what was public on the row's date."""
    df = k.merge(player_info(k.sid.unique()), on="sid")
    df = df[df.pos.isin(POS)].copy()
    df["posc"] = df.pos.map(POS)
    df["age"] = (df.date - pd.to_datetime(df.bd)).dt.days / 365.25
    df["month"] = df.date.dt.month
    df["lcs"] = np.where(df.month >= 2, df.date.dt.year - 1, df.date.dt.year - 2)  # last completed season
    df["exp"] = df.lcs - df.dyear + 1
    df = df[~((df.date.dt.year == df.dyear) & (df.month < 5))]  # pre-NFL-draft rookie rows
    df = df.reset_index(drop=True)
    seasons = sorted(int(y) for y in KO if (CACHE / f"sp_{y}.csv").exists())

    T = _tables(seasons)

    # n_: last three completed seasons (nflverse regular season, PPR)
    ns = T["ns"]
    agg = ns.groupby(["player_id", "season"]).agg(
        gp=("games", "sum"), ppr=("fantasy_points_ppr", "sum"), tgt=("targets", "sum"), car=("carries", "sum"),
        att=("attempts", "sum"), ts=("target_share", "mean"), pyd=("passing_yards", "sum"),
        ryd=("rushing_yards", "sum"), recyd=("receiving_yards", "sum")).reset_index()
    agg["ppg"] = agg.ppr / agg.gp.replace(0, np.nan)
    agg["pos"] = agg.player_id.map(dict(zip(ns.player_id, ns.position)))
    agg["prank"] = agg.groupby(["season", "pos"]).ppr.rank(ascending=False)
    A = agg.set_index(["player_id", "season"])
    cols = {}
    for lag in (0, 1, 2):
        sub = A.reindex(list(zip(df.gsis, df.lcs - lag)))
        innfl = ((df.lcs - lag >= df.dyear) & df.gsis.notna()).values
        for c in ["gp", "ppg", "ppr", "tgt", "car", "att", "ts", "prank", "pyd", "ryd", "recyd"]:
            v = sub[c].values.astype(float)
            if c in ("gp", "ppr", "tgt", "car", "att", "pyd", "ryd", "recyd"):
                v = np.where(np.isnan(v) & innfl, 0, v)  # in the league that year, no stat row = 0
            cols[f"n_{c}_l{lag}"] = v
    df = pd.concat([df, pd.DataFrame(cols)], axis=1)
    df["n_best_ppg"] = df[["n_ppg_l0", "n_ppg_l1", "n_ppg_l2"]].max(axis=1)
    df["n_best_rank"] = df[["n_prank_l0", "n_prank_l1", "n_prank_l2"]].min(axis=1)

    # c_: current season to date (Sep-Jan rows only)
    df["cur"] = np.where(df.month >= 9, df.date.dt.year, np.where(df.month == 1, df.date.dt.year - 1, -1))
    Wg, Wa = T["Wg"], T["Wa"]
    names = ["c_gp", "c_ppg", "c_tgt", "c_car", "c_att", "c_ts", "c_l4ppg", "c_ryd", "c_pyd"]
    out = {c: np.full(len(df), np.nan) for c in names}
    # a row's figures depend only on how many of the season's weeks were known by its date (each group is sorted by
    # avail, so the known weeks are a prefix): each (player, season, weeks known) is computed once, as before
    memo = {}
    for i, (g, cur, dt) in enumerate(zip(df.gsis, df.cur, df.date)):
        if cur < 0:
            continue
        v = Wg.get((g, cur))
        if v is None:
            out["c_gp"][i] = 0
            continue
        mk = (g, cur, int(np.searchsorted(Wa[(g, cur)], np.datetime64(dt), side="right")))
        r = memo.get(mk)
        if r is None:
            n = mk[2]
            if n:
                ppr, tgt, car_, att, ts, ryd, pyd = (c[:n] for c in T["Wc"][(g, cur)])
                r = [n, _pd_mean(ppr), _pd_mean(tgt), _pd_mean(car_), _pd_mean(att), _pd_mean(ts), _pd_mean(ppr[-4:]),
                     _pd_mean(ryd), _pd_mean(pyd)]
            else:
                r = [0]
            memo[mk] = r
        out["c_gp"][i] = r[0]
        if r[0]:
            (out["c_ppg"][i], out["c_tgt"][i], out["c_car"][i], out["c_att"][i], out["c_ts"][i], out["c_l4ppg"][i],
             out["c_ryd"][i], out["c_pyd"][i]) = r[1:]
    for c, v in out.items():
        df[c] = v
    df["c_weeks"] = [((dt - pd.Timestamp(KO[c])).days // 7 + 1) if c > 0 else np.nan for c, dt in zip(df.cur, df.date)]
    df["c_weeks"] = df.c_weeks.clip(upper=18)
    pre = (df.cur > 0) & (df.c_weeks <= 0)  # season not kicked off yet: no games is missing, not zero
    for c in [c for c in df.columns if c.startswith("c_")]:
        df.loc[pre, c] = np.nan

    # k_: latest contract signed by the row's date (year granularity: visible from April)
    c = pd.read_parquet(CACHE / "contracts.parquet")
    c = c[c.gsis_id.notna()][["gsis_id", "position", "year_signed", "years", "apy_cap_pct", "guaranteed", "value"]]
    c = c[c.position == c.gsis_id.map(dict(zip(df.gsis, df.pos)))]  # nflverse mis-keys some namesakes
    cg = {key: v.sort_values(["year_signed", "value"]) for key, v in c.groupby("gsis_id")}  # tag vs extension tie
    kc = {n: np.full(len(df), np.nan) for n in ["k_apy", "k_gtd", "k_yrs_left", "k_years"]}
    memo = {}                          # a row reads only its player and two year cut-offs: each combination once
    for i, (g, dt) in enumerate(zip(df.gsis, df.date)):
        v = cg.get(g)
        if v is None:
            continue
        ys, yl = (dt.year if dt.month >= 4 else dt.year - 1), (dt.year if dt.month >= 3 else dt.year - 1)
        mk = (g, ys, yl); r = memo.get(mk, memo)
        if r is memo:
            v = v[v.year_signed <= ys]
            if len(v):
                x = v.iloc[-1]
                r = (x.apy_cap_pct, x.guaranteed, x.years, x.year_signed + x.years - yl)
            else:
                r = None
            memo[mk] = r
        if r is None:
            continue
        kc["k_apy"][i], kc["k_gtd"][i], kc["k_years"][i], kc["k_yrs_left"][i] = r
    for n, v in kc.items():
        df[n] = v

    # d_: depth-chart rank as of the date (weekly charts to 2024, daily ESPN snapshots 2025+)
    snapdates, Dg, Da = T["snapdates"], T["Dg"], T["Da"]
    dr = np.full(len(df), np.nan); dage = np.full(len(df), np.nan)
    memo = {}                          # a row reads the charts known by its date: each (player, charts known) once
    for i, (g, dt) in enumerate(zip(df.gsis, df.date)):
        t = np.datetime64(dt)
        a = Da.get(g)
        mk = (g, int(np.searchsorted(snapdates, t, side="right")), -1 if a is None else int(np.searchsorted(a, t, side="right")))
        r = memo.get(mk)
        if r is None:
            r = (np.nan, np.nan)
            if mk[1]:                                       # some chart was out by the date
                if mk[2] <= 0:                              # none had him (or he has none)
                    r = (9, np.nan)
                else:
                    av, rk = T["Dr"][g]
                    da = (snapdates[mk[1] - 1] - np.datetime64(av[mk[2] - 1])) / np.timedelta64(1, "D")
                    r = (rk[mk[2] - 1] if da <= 21 else 9, da)  # off every chart for 3+ weeks
            memo[mk] = r
        dr[i], dage[i] = r
    df["d_rank"] = dr; df["d_stale"] = dage

    # s_: offensive snap share (last season, season before, this season, last 3 games)
    SA = T["SA"]
    df["s_snap_l0"] = SA.reindex(list(zip(df.gsis, df.lcs))).values
    df["s_snap_l1"] = SA.reindex(list(zip(df.gsis, df.lcs - 1))).values
    left = df[["date", "gsis"]].assign(rid=np.arange(len(df))).dropna(subset=["gsis"])
    left["date"] = left.date.astype("datetime64[ns]")
    m = merge_asof(left.sort_values("date"), T["sn"], left_on="date", right_on="avail", by="gsis").set_index("rid")
    ok = m.season.values == df.cur.values[m.index]
    df["s_snap_cur"] = np.nan; df["s_snap_l3"] = np.nan
    df.loc[m.index[ok], "s_snap_cur"] = m.cum[ok].values
    df.loc[m.index[ok], "s_snap_l3"] = m.l3[ok].values

    # e_: career to date + calendar (e_t tracks drift in KTC's overall level)
    cp = T["cp"]
    best, games, elite = [], [], []
    memo = {}
    for g, lcs in zip(df.gsis, df.lcs):
        r = memo.get((g, lcs))
        if r is None:
            v = cp.get(g)
            v = v[v[:, 0] <= lcs] if v is not None else None
            if v is None or not len(v):
                r = (np.nan, np.nan, np.nan)
            else:
                good = v[v[:, 2] >= 6]
                r = (np.nanmax(good[:, 1]) if len(good) else np.nan, np.nansum(v[:, 2]), (good[:, 1] >= 15).sum())
            memo[(g, lcs)] = r
        best.append(r[0]); games.append(r[1]); elite.append(r[2])
    df["e_career_best"] = best; df["e_career_games"] = games; df["e_n_elite"] = elite
    df["e_t"] = (df.date - pd.Timestamp("2020-01-01")).dt.days / 365.25
    df["e_doy"] = df.date.dt.dayofyear
    return df.sort_values(["sid", "date"]).reset_index(drop=True)


def features(df):
    return (["posc", "age", "dovr", "dround", "undrafted", "exp", "month"]
            + [c for c in df.columns if c[:2] in ("n_", "c_", "k_", "d_", "s_", "e_")])


# --------------------------------------------------------------------------- models


def _gbm(**kw):
    from sklearn.ensemble import HistGradientBoostingRegressor   # only the model needs scikit-learn
    p = dict(max_iter=600, learning_rate=0.04, max_leaf_nodes=31, min_samples_leaf=20, max_features=0.5,
             random_state=0, categorical_features=[0])
    p.update(kw)
    return HistGradientBoostingRegressor(**p)


def _recency(d, half_life_years=1.0):
    t = (d.date - pd.Timestamp("2020-01-01")).dt.days.values / 365.25
    return 0.5 ** ((t.max() - t) / half_life_years)


STATS_ENSEMBLE = [  # (target, gbm kwargs) — averaged
    ("sqrt", dict(max_leaf_nodes=63, learning_rate=0.03, max_iter=1500)),
    ("raw", dict()),
    ("sqrt", dict(loss="absolute_error")),
]


class StatsModel:
    """KTC from stats/contract/depth/age/draft only — the backup if KTC vanishes."""

    def __init__(self, F, ensemble=STATS_ENSEMBLE):
        self.F, self.ens, self.models = F, ensemble, []

    def fit(self, d):
        self.models = []
        for t, kw in self.ens:
            y = np.sqrt(d.ktc.values) if t == "sqrt" else d.ktc.values
            self.models.append((t, _gbm(**kw).fit(d[self.F], y, sample_weight=_recency(d))))
        return self

    def predict(self, d):
        ps = [np.square(np.clip(m.predict(d[self.F]), 0, None)) if t == "sqrt" else m.predict(d[self.F])
              for t, m in self.models]
        return np.clip(np.mean(ps, 0), 0, 9999)


ANCHOR_LAGS = (1, 2, 4, 8, 13, 26, 52)  # augmentation: anchors 1 period to ~1 year old


def nfl_weeks_between(a, b):
    """Regular-season NFL weeks played between dates a and b (vectorised). The
    information since an anchor arrives with games, not calendar days: across an
    offseason a months-old KTC barely goes stale (see the note)."""
    a = np.asarray(a, "datetime64[ns]"); b = np.asarray(b, "datetime64[ns]"); n = np.zeros(len(a))
    for ko in KO.values():
        s = np.datetime64(pd.Timestamp(ko)); e = np.datetime64(pd.Timestamp(ko) + pd.Timedelta(days=7 * 18))
        lo = np.maximum(a, s); hi = np.minimum(b, e)
        n += np.clip((hi - lo) / np.timedelta64(1, "D"), 0, None) / 7
    return n


def add_anchor_info(x):
    """g_since: NFL weeks since the anchor; g_frac: share of the gap that was in season."""
    x["g_since"] = nfl_weeks_between(x.date - pd.to_timedelta(x.gap, unit="D"), x.date)
    x["g_frac"] = x.g_since / np.maximum(x.gap / 7, 1)
    return x


def anchor_rows(d, lags=(1,)):
    """One row per (row, lag): the player's KTC `lag` observations earlier as the anchor."""
    out = []
    g = d.groupby("sid")
    for L in lags:
        x = d.copy()
        x["anc"] = g.ktc.shift(L); x["gap"] = (d.date - g.date.shift(L)).dt.days
        x["sest_anc"] = g.sest.shift(L)
        out.append(x[x.anc.notna()])
    x = pd.concat(out, ignore_index=True)
    x["ranc"] = np.sqrt(x.anc)
    x["res_anc"] = x.ranc - x.sest_anc  # how far KTC sat from the stats estimate at the anchor
    x["dsest"] = x.sest - x.sest_anc    # how much the stats estimate moved since the anchor
    return add_anchor_info(x)


class AnchoredModel:
    """KTC from the player's last known KTC (any age) plus the stats features."""

    def __init__(self, F):
        self.F = F + ["ranc", "gap", "sest", "res_anc", "dsest", "g_since", "g_frac"]

    def fit(self, x):
        self.m = _gbm(max_iter=800).fit(x[self.F], np.sqrt(x.ktc) - x.ranc, sample_weight=_recency(x))
        return self

    def predict(self, x):
        return np.square(np.clip(self.m.predict(x[self.F]) + x.ranc.values, 0, None))


class RoutedAnchored:
    """What the backtest picked per anchor age (see the note). Up to 120 days: the
    1-period-trained anchored model, moved off the anchor only in proportion to
    the football played since it, lam = g / (g + H) with g = NFL weeks since the
    anchor (no games -> carry the anchor). Beyond 120 days: the multi-age-trained
    model, unshrunk (the shrink cost accuracy there)."""

    LONG, H = 120, 1.0

    def __init__(self, F):
        self.one, self.multi = AnchoredModel(F), AnchoredModel(F)

    def fit(self, d):
        self.one.fit(anchor_rows(d, (1,)))
        self.multi.fit(anchor_rows(d, ANCHOR_LAGS))
        return self

    @classmethod
    def combine(cls, x, p_one, p_multi):
        lam = x.g_since.values / (x.g_since.values + cls.H)
        near = x.anc.values + lam * (np.asarray(p_one) - x.anc.values)
        return np.minimum(np.where(x.gap.values <= cls.LONG, near, np.asarray(p_multi)), 9999)  # KTC's cap

    def predict(self, x):
        return self.combine(x, self.one.predict(x), self.multi.predict(x))
