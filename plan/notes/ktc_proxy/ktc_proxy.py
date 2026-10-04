"""KTC proxy experiment — reproduction script for plan/notes/KTC_PROXY_MODEL.md.

NOT part of the build and not run by CI. It reads the committed KTC history
(data/ktc_backfill/*.json + exports/raw/ktc_provenance.csv), pulls public
nflverse data into .cache/ktc_proxy/ (gitignored), and writes nothing outside
that cache unless --out is given.

    pip install pandas scikit-learn scipy pyarrow
    python plan/notes/ktc_proxy/ktc_proxy.py backtest            # reproduce the note's tables
    python plan/notes/ktc_proxy/ktc_proxy.py season-end --ktc-csv new_ktc.csv \\
        --freeze 2026-10-03 --eval 2027-01-12                        # the pre-registered test

--ktc-csv adds KTC rows the repo does not hold (columns: sleeper_id,date,ktc —
superflex value, the build's `sf_trade_value`).
"""
from __future__ import annotations

import argparse
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
REPO = Path(__file__).resolve().parents[3]
CACHE = REPO / ".cache" / "ktc_proxy"
NFLV = "https://github.com/nflverse/nflverse-data/releases/download"
# Thursday kickoff of each season's week 1 (week-N stats are treated as known on
# kickoff + 7(N-1) + 5 days, i.e. the Tuesday after the week).
KO = {2019: "2019-09-05", 2020: "2020-09-10", 2021: "2021-09-09", 2022: "2022-09-08",
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


def _wkdate(season, week):
    return pd.Timestamp(KO[int(season)]) + pd.to_timedelta(7 * (np.asarray(week, dtype=int) - 1) + 5, unit="D")


# ------------------------------------------------------------------------- features
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

    # n_: last three completed seasons (nflverse regular season, PPR)
    ns = pd.concat([_read(f"sp_{y}.csv") for y in seasons])
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
    Wg = {key: v.sort_values("avail") for key, v in pd.concat(W).groupby(["player_id", "season"])}
    names = ["c_gp", "c_ppg", "c_tgt", "c_car", "c_att", "c_ts", "c_l4ppg", "c_ryd", "c_pyd"]
    out = {c: np.full(len(df), np.nan) for c in names}
    for i, (g, cur, dt) in enumerate(zip(df.gsis, df.cur, df.date)):
        if cur < 0:
            continue
        v = Wg.get((g, cur))
        if v is None:
            out["c_gp"][i] = 0
            continue
        v = v[v.avail <= dt]
        out["c_gp"][i] = len(v)
        if len(v):
            out["c_ppg"][i] = v.fantasy_points_ppr.mean(); out["c_tgt"][i] = v.targets.mean()
            out["c_car"][i] = v.carries.mean(); out["c_att"][i] = v.attempts.mean()
            out["c_ts"][i] = v.target_share.mean(); out["c_l4ppg"][i] = v.fantasy_points_ppr.tail(4).mean()
            out["c_ryd"][i] = v.rushing_yards.mean(); out["c_pyd"][i] = v.passing_yards.mean()
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
    for i, (g, dt) in enumerate(zip(df.gsis, df.date)):
        v = cg.get(g)
        if v is None:
            continue
        v = v[v.year_signed <= (dt.year if dt.month >= 4 else dt.year - 1)]
        if not len(v):
            continue
        r = v.iloc[-1]
        kc["k_apy"][i] = r.apy_cap_pct; kc["k_gtd"][i] = r.guaranteed; kc["k_years"][i] = r.years
        kc["k_yrs_left"][i] = r.year_signed + r.years - (dt.year if dt.month >= 3 else dt.year - 1)
    for n, v in kc.items():
        df[n] = v

    # d_: depth-chart rank as of the date (weekly charts to 2024, daily ESPN snapshots 2025+)
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
    snapdates = np.sort(D.avail.unique())
    Dg = {key: v.sort_values("avail") for key, v in D.groupby("gsis_id")}
    dr = np.full(len(df), np.nan); dage = np.full(len(df), np.nan)
    for i, (g, dt) in enumerate(zip(df.gsis, df.date)):
        last = snapdates[snapdates <= np.datetime64(dt)]
        if not len(last):
            continue
        v = Dg.get(g)
        v = v[v.avail <= dt] if v is not None else None
        if v is None or not len(v):
            dr[i] = 9
            continue
        r = v.iloc[-1]
        dage[i] = (last[-1] - np.datetime64(r.avail)) / np.timedelta64(1, "D")
        dr[i] = r["rank"] if dage[i] <= 21 else 9  # off every chart for 3+ weeks
    df["d_rank"] = dr; df["d_stale"] = dage

    # s_: offensive snap share (last season, season before, this season, last 3 games)
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
    SA = sn.groupby(["gsis", "season"]).offense_pct.mean()
    df["s_snap_l0"] = SA.reindex(list(zip(df.gsis, df.lcs))).values
    df["s_snap_l1"] = SA.reindex(list(zip(df.gsis, df.lcs - 1))).values
    sn["cum"] = sn.groupby(["gsis", "season"]).offense_pct.transform(lambda s: s.expanding().mean())
    sn["l3"] = sn.groupby(["gsis", "season"]).offense_pct.transform(lambda s: s.rolling(3, 1).mean())
    left = df[["date", "gsis"]].assign(rid=np.arange(len(df))).dropna(subset=["gsis"])
    left["date"] = left.date.astype("datetime64[ns]")
    sn["avail"] = pd.to_datetime(sn.avail).astype("datetime64[ns]")
    m = pd.merge_asof(left.sort_values("date"), sn.sort_values("avail")[["gsis", "avail", "season", "cum", "l3"]],
                      left_on="date", right_on="avail", by="gsis").set_index("rid")
    ok = m.season.values == df.cur.values[m.index]
    df["s_snap_cur"] = np.nan; df["s_snap_l3"] = np.nan
    df.loc[m.index[ok], "s_snap_cur"] = m.cum[ok].values
    df.loc[m.index[ok], "s_snap_l3"] = m.l3[ok].values

    # e_: career to date + calendar (e_t tracks drift in KTC's overall level)
    car = ns.groupby(["player_id", "season"]).agg(ppr=("fantasy_points_ppr", "sum"), g=("games", "sum")).reset_index()
    car["ppg"] = car.ppr / car.g.replace(0, np.nan)
    cp = {pid: g[["season", "ppg", "g"]].values for pid, g in car.groupby("player_id")}
    best, games, elite = [], [], []
    for g, lcs in zip(df.gsis, df.lcs):
        v = cp.get(g)
        v = v[v[:, 0] <= lcs] if v is not None else None
        if v is None or not len(v):
            best.append(np.nan); games.append(np.nan); elite.append(np.nan)
            continue
        good = v[v[:, 2] >= 6]
        best.append(np.nanmax(good[:, 1]) if len(good) else np.nan)
        games.append(np.nansum(v[:, 2])); elite.append((good[:, 1] >= 15).sum())
    df["e_career_best"] = best; df["e_career_games"] = games; df["e_n_elite"] = elite
    df["e_t"] = (df.date - pd.Timestamp("2020-01-01")).dt.days / 365.25
    df["e_doy"] = df.date.dt.dayofyear
    return df.sort_values(["sid", "date"]).reset_index(drop=True)


def features(df):
    return (["posc", "age", "dovr", "dround", "undrafted", "exp", "month"]
            + [c for c in df.columns if c[:2] in ("n_", "c_", "k_", "d_", "s_", "e_")])


# --------------------------------------------------------------------------- models
from sklearn.ensemble import HistGradientBoostingRegressor  # noqa: E402
from sklearn.model_selection import GroupKFold  # noqa: E402


def _gbm(**kw):
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
    return x


class AnchoredModel:
    """KTC from the player's last known KTC (any age) plus the stats features."""

    def __init__(self, F):
        self.F = F + ["ranc", "gap", "sest", "res_anc", "dsest"]

    def fit(self, x):
        self.m = _gbm(max_iter=800).fit(x[self.F], np.sqrt(x.ktc) - x.ranc, sample_weight=_recency(x))
        return self

    def predict(self, x):
        return np.square(np.clip(self.m.predict(x[self.F]) + x.ranc.values, 0, None))


class RoutedAnchored:
    """What the backtest picked per anchor age (see the note): carry the anchor
    forward when it is <=10 days old (nothing beat it), the 1-period-trained
    anchored model to 120 days, the multi-age-trained one beyond."""

    SHORT, LONG = 10, 120

    def __init__(self, F):
        self.one, self.multi = AnchoredModel(F), AnchoredModel(F)

    def fit(self, d):
        self.one.fit(anchor_rows(d, (1,)))
        self.multi.fit(anchor_rows(d, ANCHOR_LAGS))
        return self

    def predict(self, x):
        g = x.gap.values
        return np.where(g <= self.SHORT, x.anc.values,
                        np.where(g <= self.LONG, self.one.predict(x), self.multi.predict(x)))


def stats_oof(d, F, folds=5):
    """Player-held-out stats estimate for every row (single sqrt model — the anchored model's input)."""
    o = np.zeros(len(d))
    for tr, te in GroupKFold(folds).split(d, groups=d.sid):
        m = _gbm().fit(d.iloc[tr][F], np.sqrt(d.ktc.values[tr]), sample_weight=_recency(d.iloc[tr]))
        o[te] = np.square(np.clip(m.predict(d.iloc[te][F]), 0, None))
    return o


# -------------------------------------------------------------------------- metrics
def metrics(y, p):
    from scipy.stats import pearsonr, spearmanr
    y, p = np.asarray(y, float), np.asarray(p, float)
    e = np.abs(y - p); big = y >= 1000
    # calib: n-weighted RMS of the mean signed error within each KTC quintile (the
    # calibration check from plan/notes/POINTS_ABOVE_EXPECTATION.md). r and MAE can
    # look fine while every band is off the same way; bias is the overall mean error.
    q = pd.qcut(y, 5, labels=False, duplicates="drop")
    band = pd.DataFrame(dict(q=q, d=p - y)).groupby("q").d.agg(["size", "mean"])
    calib = np.sqrt((band["size"] * band["mean"] ** 2).sum() / band["size"].sum())
    return dict(n=len(y), r=round(pearsonr(y, p)[0], 4), rho=round(spearmanr(y, p)[0], 4), mae=round(e.mean()),
                median=round(np.median(e)), w250=round((e <= 250).mean(), 3),
                within10pct_1k=round((e[big] <= 0.1 * y[big]).mean(), 3), calib=round(calib), bias=round(np.mean(p - y)))


def show(label, m):
    print(f"{label:52s} " + " ".join(f"{k}={v}" for k, v in m.items()), flush=True)


# ------------------------------------------------------------------------ commands
def cmd_backtest(a):
    fetch(2026)
    # 1) monthly: stats-only trained before 2025-03-01, scored on everything after
    d = build(load_ktc("M")); F = features(d)
    fut = (d.date >= "2025-03-01").values
    sm = StatsModel(F).fit(d[~fut])
    show("monthly | stats-only, frozen at 2025-03-01", metrics(d.ktc[fut], sm.predict(d[fut])))
    # 2) weekly: anchored vs carry-forward, players held out, by anchor age
    w = build(load_ktc("W")); F = features(w)
    w["sest"] = np.sqrt(stats_oof(w, F))
    x1 = anchor_rows(w, (1,))
    xa = anchor_rows(w, ANCHOR_LAGS)
    for name, train in (("anchored (lag-1 training)", x1), ("anchored (multi-lag training)", xa)):
        p = np.zeros(len(xa))
        for tr_sids, te_sids in _player_folds(w):
            m = AnchoredModel(F).fit(train[train.sid.isin(tr_sids)])
            te = xa.sid.isin(te_sids).values
            p[te] = m.predict(xa[te])
        xa["p_" + name] = p
    xa["p_routed"] = np.where(xa.gap <= RoutedAnchored.SHORT, xa.anc,
                              np.where(xa.gap <= RoutedAnchored.LONG, xa["p_anchored (lag-1 training)"],
                                       xa["p_anchored (multi-lag training)"]))
    show("ALL anchor ages | carry forward", metrics(xa.ktc, xa.anc))
    show("ALL anchor ages | routed", metrics(xa.ktc, xa.p_routed))
    for lo, hi in ((0, 10), (11, 45), (46, 120), (121, 400)):
        s = xa[(xa.gap >= lo) & (xa.gap <= hi)]
        print(f"-- anchor {lo}-{hi} days old")
        show("   carry forward", metrics(s.ktc, s.anc))
        show("   stats-only (held-out player)", metrics(s.ktc, np.square(s.sest)))
        for name in ("anchored (lag-1 training)", "anchored (multi-lag training)", "routed"):
            show("   " + name, metrics(s.ktc, s["p_" + name]))


def _player_folds(d, k=5):
    sids = np.array(sorted(d.sid.unique()))
    for tr, te in GroupKFold(k).split(sids, groups=sids):
        yield set(sids[tr]), set(sids[te])


def cmd_season_end(a):
    """Pre-registered test (see the note): models frozen at --freeze, scored at --eval."""
    fetch(int(a.eval[:4]))
    T0, T1 = pd.Timestamp(a.freeze), pd.Timestamp(a.eval)
    w = build(load_ktc("W", a.ktc_csv)); F = features(w)
    train = w[w.date <= T0].copy()
    sm = StatsModel(F).fit(train)
    train["sest"] = np.sqrt(stats_oof(train, F))
    w["sest"] = np.sqrt(StatsModel(F, [("sqrt", dict())]).fit(train).predict(w))  # frozen live estimate
    w.loc[train.index, "sest"] = train.sest  # training rows keep their player-held-out estimate
    am = RoutedAnchored(F).fit(train)
    tol = pd.Timedelta(days=a.tol_days)
    # anchor: latest KTC in [T0 - tol, T0] (never after the freeze); target: nearest to T1 within tol
    a0 = w[(w.date <= T0) & (w.date >= T0 - tol)].sort_values("date").groupby("sid").tail(1).set_index("sid")
    c1 = w[(w.date - T1).abs() <= tol].assign(dist=lambda d: (d.date - T1).abs())
    a1 = c1.sort_values("dist").groupby("sid").head(1).set_index("sid")
    both = a0.index.intersection(a1.index)
    x = a1.loc[both].reset_index()
    x["anc"] = a0.loc[both, "ktc"].values; x["gap"] = (x.date - a0.loc[both, "date"].values).dt.days
    x["ranc"] = np.sqrt(x.anc); x["sest_anc"] = a0.loc[both, "sest"].values
    x["res_anc"] = x.ranc - x.sest_anc; x["dsest"] = x.sest - x.sest_anc
    print(f"players with KTC near both {T0.date()} and {T1.date()}: {len(x)}")
    show("M1 carry KTC from freeze date", metrics(x.ktc, x.anc))
    show("M2 stats-only, frozen model", metrics(x.ktc, sm.predict(x)))
    m2, m3 = sm.predict(x), am.predict(x)
    show("M3 anchored on freeze-date KTC, frozen model", metrics(x.ktc, m3))
    # M5 was added after the 2025 rehearsal (see the note) — not part of the original registration.
    show("M5 mean of M2 and M3", metrics(x.ktc, (m2 + m3) / 2))
    print(f"mean signed error  M2 {np.mean(m2 - x.ktc):+.0f}  M3 {np.mean(m3 - x.ktc):+.0f}  (level drift check)")
    # M4: weekly — each week between T0 and T1 predicted from the previous week's KTC
    wk = w[(w.date > T0) & (w.date <= T1)]
    xw = anchor_rows(w[w.date <= T1], (1,))
    xw = xw[xw.date.isin(wk.date) & (xw.gap <= 10)]
    if len(xw):
        show("M4 weekly: carry last week's KTC", metrics(xw.ktc, xw.anc))
        show("M4 weekly: anchored (1-period model), frozen", metrics(xw.ktc, am.one.predict(xw)))
    if a.out:
        x.assign(m1=x.anc, m2=m2, m3=m3, m5=(m2 + m3) / 2)[["sid", "name", "pos", "date", "ktc", "m1", "m2", "m3", "m5"]] \
            .to_csv(a.out, index=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backtest")
    s = sub.add_parser("season-end")
    s.add_argument("--freeze", default="2026-10-03")
    s.add_argument("--eval", required=True)
    s.add_argument("--ktc-csv", help="sleeper_id,date,ktc rows covering the freeze and eval dates")
    s.add_argument("--out", help="write per-player season-end predictions here")
    s.add_argument("--tol-days", type=int, default=4,
                   help="how far from each date a KTC value may be (default 4; use ~30 for a rehearsal on sparse history)")
    a = ap.parse_args()
    {"backtest": cmd_backtest, "season-end": cmd_season_end}[a.cmd](a)


if __name__ == "__main__":
    main()
