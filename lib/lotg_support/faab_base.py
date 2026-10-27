"""Walk-forward base value for the FAAB system (the `Lf` the formula and rules start from).

Every fitted piece is refit at each quarterly snapshot R on data dated before R and used only for dates in
[R, next R): aging curves and replacement levels (NFL seasons complete before R), the stats translator S (stats ->
KTC's superflex scale, KTC panel rows before R, out of fold by player so a player's own KTC never feeds his S), the
KTC-scale -> league-price map, and the league-price model with its curves (league prices before R). Then each
player's values are smoothed across dates and routed toward his last league price, causally.

KTC is the translator's training target only; no value is ever read from KTC on the date being valued.

Moved from the research scripts (common / anchor / chain / pv / v3 / v4 / v7-v10 / tl_base / wf_base2) with the
logic unchanged; `REPRO` switches restore two research-era behaviours exactly, for reproduction checks only:
  - aging_cap_2024: the survivor aging curve kept seasons <= 2024 regardless of the snapshot (it let the last
    complete season count as all drop-offs at 2021-23 snapshots, and would freeze the curve from 2027);
  - fold_map: the stored fold assignment; production uses a stable hash of the Sleeper id.
"""
from __future__ import annotations

import hashlib
import time

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

from . import faab_frame as kp

REPRO = dict(aging_cap_2024=False, fold_map=None)
# Out-of-fold predictions for top players moved 30-40% with nothing but the fold assignment (Gibbs's base $3,539 ->
# $2,204 on the same data, 2026-10; across six assignments he was bimodal, ~$2,200 or ~$3,540, by which comparable
# players shared his held-out fold). Each quarter is therefore fit under BAGS assignments and a player's base is the
# mean of his log values. Measured on the 2026-10 quarter's top 150: two single draws differ by a median 15%, two
# independent 3-bag means by 9% (the 1/sqrt(n) the noise predicts); 5 bags leave ~7%.
BAGS = 5
DEMAND = {"QB": 16, "RB": 24, "WR": 32, "TE": 9}   # weekly starters league-wide (1 QB + SF, 2 RB, 3 WR, 1 TE, 2 FLEX)
ENS = [("sqrt", dict(max_leaf_nodes=63, learning_rate=0.05, max_iter=800)), ("raw", dict(max_iter=500))]
CFG = (0.3, 0.0, 2.5); A_PV = 0.67; NM = "pv_main"
PVF = ["PV", "pv_ppg", "lPV"]
AF = ["a_lp", "a_gap", "a_g", "a_dS", "a_free", "a_trade"]
LO, HI = np.log1p(100), np.log1p(1000)
BOOST = (0.4, 0.0, 0.35)


# ------------------------------------------------------------------ small helpers (common)
def era_weight(d):
    d = pd.to_datetime(d)
    return np.select([d < "2021-01-01", d < "2021-07-01", d < "2022-01-01"], [0.25, 0.5, 0.75], 1.0)


def feats(df):
    return kp.features(df)


def gbm(**kw):
    p = dict(max_iter=500, learning_rate=0.03, max_leaf_nodes=8, min_samples_leaf=15, l2_regularization=1.0,
             random_state=0, categorical_features=[0])
    p.update(kw)
    return HistGradientBoostingRegressor(**p)


def folds(groups, k=5, seed=0):
    u = pd.Series(groups).unique(); rng = np.random.RandomState(seed); rng.shuffle(u)
    f = {g: i % k for i, g in enumerate(u)}
    return np.array([f[g] for g in groups])


def fold_of(sids, bag=0):
    """out-of-fold group by player: a stable hash of the Sleeper id (and the bag), or the stored map in reproduction
    mode (bag 0)"""
    sids = pd.Series(sids).astype(str)
    salt = "" if bag == 0 else f"{bag}:"
    stable = sids.map(lambda s: int(hashlib.md5((salt + s).encode()).hexdigest(), 16) % 5)
    fm = REPRO.get("fold_map")
    return (sids.map(fm).fillna(stable) if (fm and bag == 0) else stable).astype(int).values


# ------------------------------------------------------------------ NFL seasons, aging, production value (pv / v7 / v8 / v9)
def load_seasons(last):
    """season totals 2016..last (regular season, PPR) with age at Sept 1"""
    dp = pd.read_csv(kp.REPO / "exports/snapshot/dynastyprocess_playerids.csv")
    bd = dict(zip(dp.gsis_id, pd.to_datetime(dp.birthdate, errors="coerce")))
    X = []
    for y in range(2016, last + 1):
        f = kp.CACHE / f"sp_{y}.csv"
        if not f.exists(): continue
        s = pd.read_csv(f, low_memory=False, usecols=["player_id", "position", "season", "games", "fantasy_points_ppr"])
        X.append(s[s.position.isin(DEMAND)])
    s = pd.concat(X).groupby(["player_id", "season", "position"], as_index=False).sum()
    s["ppg"] = s.fantasy_points_ppr / s.games.replace(0, np.nan)
    s["age"] = (pd.to_datetime(s.season.astype(str) + "-09-01") - s.player_id.map(bd)).dt.days / 365.25
    return s


def aging_curves(s):
    a = s[(s.games >= 8) & (s.ppg >= 8)][["player_id", "season", "position", "ppg", "age"]]
    b = a.assign(season=a.season - 1)[["player_id", "season", "ppg"]].rename(columns={"ppg": "ppg_next"})
    m = a.merge(b, on=["player_id", "season"]).dropna(subset=["age"])
    m["lr"] = np.log(m.ppg_next / m.ppg)
    cur = {}
    for p, g in m.groupby("position"):
        g = g[(g.age > 20) & (g.age < 38)]
        cur[p] = np.polyfit(g.age, g.lr, 2, w=np.sqrt(g.ppg))
    return cur


def production_value(df, repl, cur, years=5, disc=0.75, games=15):
    pos = df.pos.values; R = np.array([repl.get(p, 10) for p in pos])
    w0 = np.where(df.c_gp.fillna(0).values > 0, 0.8, 1.0)
    num, den = np.zeros(len(df)), np.zeros(len(df))
    for gp, ppg, w in (("c_gp", "c_ppg", 1.0), ("n_gp_l0", "n_ppg_l0", w0), ("n_gp_l1", "n_ppg_l1", 0.4), ("n_gp_l2", "n_ppg_l2", 0.15)):
        g = np.nan_to_num(df[gp].values.astype(float)); x = np.nan_to_num(df[ppg].values.astype(float))
        num += g * w * x; den += g * w
    base = (num + 4.0 * R) / (den + 4.0); has = den > 0; age = df.age.fillna(25).values
    pv = np.zeros(len(df)); ppg = base.copy()
    for y in range(years):
        pv += disc ** y * games * np.clip(ppg - R, 0, None)
        lr = np.array([np.polyval(cur[p], a + y) if p in cur else 0 for p, a in zip(pos, age)])
        ppg = ppg * np.exp(np.clip(lr, -0.5, 0.3))
    pv[~has] = np.nan
    return pv, base


class Football:
    """the snapshot's football priors: replacement levels, per-game aging curve, survivor aging curve (with
    drop-offs), and the career table the ceiling reads. Refit from seasons complete before each snapshot."""

    def __init__(self, seasons):
        self.ALL = seasons
        self.SEAS = seasons[seasons.games >= 6]
        self.CAR = set(self.SEAS.player_id)
        self.repl, self.cur, self.cur2 = {}, {}, {}

    def fit(self, last):
        s = self.ALL[self.ALL.season <= last]
        self.repl = {p: float(np.mean([g[g.games >= 6].ppg.sort_values(ascending=False).iloc[n]
                                         for _, g in s[(s.position == p) & (s.season >= last - 4)].groupby("season")]))
                     for p, n in DEMAND.items()}
        self.cur = aging_curves(s)
        self.cur2 = self._aging_v2(s, last)
        return self

    def _aging_v2(self, ALL, last):
        """per-game survivor curve + the extra cliff risk by age (season totals with drop-offs counted)"""
        a = ALL[(ALL.games >= 12) & (ALL.ppg >= 8)][["player_id", "season", "position", "fantasy_points_ppr", "age"]].dropna(subset=["age"])
        nxt = ALL[["player_id", "season", "fantasy_points_ppr", "games"]].assign(season=lambda d: d.season - 1).rename(columns={"fantasy_points_ppr": "pts_next", "games": "g_next"})
        m = a.merge(nxt, on=["player_id", "season"], how="left")
        m = m[m.season <= (2024 if REPRO["aging_cap_2024"] else last - 1)]
        m["pts_next"] = m.pts_next.fillna(0); m["g_next"] = m.g_next.fillna(0)
        m["ab"] = np.clip(np.round(m.age), 21, 35)
        cur = {}
        for p, g in m.groupby("position"):
            r_all = g.groupby("ab").apply(lambda t: t.pts_next.sum() / t.fantasy_points_ppr.sum())
            r_sur = g[g.g_next >= 6].groupby("ab").apply(lambda t: t.pts_next.sum() / t.fantasy_points_ppr.sum())
            n = g.groupby("ab").size()
            d = np.log(r_all / r_sur).dropna()
            c = np.polyfit(d.index.values, d.values, 2, w=np.sqrt(n.reindex(d.index).values))
            cur[p] = self.cur[p] + c
        return cur

    # -- production value pieces (v7 / v8 / tl_base)
    def age_factor(self, pos, a0, a1):
        n = max(0, int(round(a1 - a0)))
        return float(np.exp(sum(np.polyval(self.cur[pos], a0 + j) for j in range(n)))) if pos in self.cur else 1.0

    def career_ceiling_aged(self, df, top=2):
        out = np.full(len(df), np.nan); S = self.SEAS
        for i, (g, lcs, pos, age) in enumerate(zip(df.gsis.values, df.lcs.values, df.pos.values, df.age.values)):
            v = S[(S.player_id == g) & (S.season <= lcs)] if g in self.CAR else None
            if v is None or not len(v) or np.isnan(age): continue
            aged = [p * self.age_factor(pos, sa, age) if not np.isnan(sa) else p for p, sa in zip(v.ppg.values, v.age.values)]
            out[i] = np.mean(sorted(aged, reverse=True)[:top])
        return out

    def pv8_level(self, df, ceil_w):
        pos = df.pos.values; R = np.array([self.repl.get(p, 10) for p in pos])
        w0 = np.where(df.c_gp.fillna(0).values > 0, 0.8, 1.0)
        num, den = np.zeros(len(df)), np.zeros(len(df))
        for gp, ppg, w in (("c_gp", "c_ppg", 1.0), ("n_gp_l0", "n_ppg_l0", w0), ("n_gp_l1", "n_ppg_l1", 0.4), ("n_gp_l2", "n_ppg_l2", 0.15)):
            g = np.nan_to_num(df[gp].values.astype(float)); x = np.nan_to_num(df[ppg].values.astype(float)); num += g * w * x; den += g * w
        rec = (num + 4 * R) / (den + 4)
        S3 = np.vstack([np.where(np.nan_to_num(df[f"n_gp_l{i}"].values.astype(float)) >= 6, df[f"n_ppg_l{i}"].values.astype(float), np.nan) for i in range(3)]).T
        srt = -np.sort(-np.nan_to_num(S3, nan=-1), axis=1)[:, :2]; srt = np.where(srt < 0, np.nan, srt)
        with np.errstate(all="ignore"):
            peak = np.nanmean(srt, axis=1)
        n_s = np.sum(~np.isnan(srt), axis=1)
        cg = np.nan_to_num(df.c_gp.values.astype(float)); cp = np.nan_to_num(df.c_ppg.values.astype(float))
        pg = np.where(np.isnan(peak), 0, 16.0 * n_s / 2)
        prov = (cg * cp + pg * np.nan_to_num(peak) + 4 * R) / (cg + pg + 4)
        level = 0.5 * rec + 0.5 * prov
        if ceil_w > 0:
            ceil = self.career_ceiling_aged(df)
            level = np.where(np.isnan(ceil), level, (1 - ceil_w) * level + ceil_w * np.maximum(ceil, level))
        return level, R, pos, 17 * availability(df), den > 0, df.age.fillna(25).values

    def pv9(self, df, ceil_w=0.3, beta=0.0, h=2.5, out_now=None, cap=0.35):
        """production value on a continuous clock: f = share of the current season played (0 in the offseason).
        Season y is f years nearer; its discount is 0.75^(y - f) and its aging runs y - f years. (beta = 0: the
        research legacy term is off in this configuration.)"""
        assert beta == 0.0, "legacy boost is not ported (CFG has beta = 0)"
        level, R, pos, games, has, age = self.pv8_level(df, ceil_w)
        out = np.zeros(len(df), bool) if out_now is None else np.asarray(out_now, bool)
        cw = np.nan_to_num(df.c_weeks.values.astype(float)); f = np.where(cw > 0, np.clip(cw / 18, 0, 1), 0.0)
        lr = np.array([[np.clip(np.polyval(self.cur2[p], a_ + k), -1.0, 0.3) if p in self.cur2 else 0.0 for k in range(7)] for p, a_ in zip(pos, age)])
        cum = np.concatenate([np.zeros((len(df), 1)), np.cumsum(lr, axis=1)], axis=1)
        pv = np.zeros(len(df))
        for y in range(6):
            tau = np.clip(y - f, 0, None); k = np.floor(tau).astype(int); fr = tau - k
            G = cum[np.arange(len(df)), k] + fr * lr[np.arange(len(df)), np.minimum(k, 6)]
            g_y = games * ((1 - f) if y == 0 else f if y == 5 else 1.0)
            pv += 0.75 ** tau * np.where(out & (y == 0), 0.0, g_y) * np.clip(level * np.exp(G) - R, 0, None)
        pv[~has] = np.nan
        return np.log1p(pv)

    def add_pv(self, F):
        F["PV"], F["pv_ppg"] = production_value(F, self.repl, self.cur); F["lPV"] = np.log1p(F.PV)
        F[NM] = self.pv9(F, *CFG)
        return F


def availability(df, prior_rate=0.88, prior_games=17.0):
    gp = np.zeros(len(df)); poss = np.zeros(len(df))
    for i in range(3):
        season = df.lcs.values - i; innfl = (season >= df.dyear.values)
        g = np.nan_to_num(df[f"n_gp_l{i}"].values.astype(float))
        gp += np.where(innfl, g, 0); poss += np.where(innfl, np.where(season >= 2021, 17, 16), 0)
    cg = np.nan_to_num(df.c_gp.values.astype(float)); cw = np.nan_to_num(df.c_weeks.values.astype(float))
    gp += cg; poss += np.maximum(cg, cw - 0.5 * (cw > 0))
    return (gp + prior_rate * prior_games) / (poss + prior_games)


def track_record(df, full=34.0):
    g = np.nan_to_num(df.e_career_games.values.astype(float)) + np.nan_to_num(df.c_gp.values.astype(float))
    return np.clip(g / full, 0, 1)


# ------------------------------------------------------------------ anchor, hybrid, smoothing/routing (anchor / chain)
def add_anchor(rows, hist):
    """anchor = the player's most recent league price strictly before the row's date"""
    h = hist.sort_values("date")[["sid", "date", "price", "S", "ch"]].rename(columns={"date": "a_date", "price": "a_price", "S": "a_S", "ch": "a_ch"})
    h["a_date"] = h.a_date.astype("datetime64[ns]")
    r = rows[["sid", "date"]].copy(); r["rid"] = np.arange(len(r)); r["date"] = r.date.astype("datetime64[ns]")
    r["q"] = r.date - pd.Timedelta(days=1)
    m = pd.merge_asof(r.sort_values("q"), h.sort_values("a_date"), left_on="q", right_on="a_date", by="sid").set_index("rid").sort_index()
    out = rows.copy()
    out["a_lp"] = np.log1p(m.a_price.values)
    gap = (m.date - m.a_date).dt.days.values
    out["a_gap"] = gap
    out["a_g"] = np.where(np.isnan(gap), np.nan, kp.nfl_weeks_between(np.where(np.isnan(gap), m.date, m.a_date), m.date))
    out["a_dS"] = np.sqrt(out.S.clip(0).values) - np.sqrt(np.clip(m.a_S.values, 0, None))
    out["a_free"] = (m.a_ch.values == "free").astype(float); out.loc[np.isnan(gap), "a_free"] = np.nan
    out["a_trade"] = (m.a_ch.values == "trade").astype(float); out.loc[np.isnan(gap), "a_trade"] = np.nan
    return out


def hybrid(LD, LG):
    s = np.clip((np.maximum(LD, LG) - LO) / (HI - LO), 0, 1); return (1 - s) * LD + s * LG


def smooth_route(tl, hist, a=0.1, b=1.0, k=1.0, c=0.25):
    """tl: sid, date, L (raw log1p $). hist: league prices sid, date, y. Smoothed (Ls) and routed (Lf) log1p $,
    each date using only earlier dates and league prices strictly before it"""
    tl = tl.sort_values(["sid", "date"]).reset_index(drop=True)
    prev = tl.groupby("sid").date.shift()
    days = (tl.date - prev).dt.days.fillna(0).values
    g = np.where(prev.isna(), 0, kp.nfl_weeks_between(prev.fillna(tl.date), tl.date))
    lam = np.where(prev.isna(), 1.0, 1 - np.exp(-(a * days / 30 + b * g)))
    Ls = np.empty(len(tl)); sid = tl.sid.values; L = tl.L.values
    for i in range(len(tl)):
        Ls[i] = L[i] if (i == 0 or sid[i] != sid[i - 1]) else Ls[i - 1] + lam[i] * (L[i] - Ls[i - 1])
    tl["Ls"] = Ls
    h = hist[["sid", "date", "y"]].rename(columns={"date": "a_date", "y": "a_y"}).copy()
    h["a_date"] = h.a_date.astype("datetime64[ns]")
    t2 = tl.assign(rid=np.arange(len(tl)), q=tl.date - pd.Timedelta(days=1))
    m = pd.merge_asof(t2.sort_values("q"), h.sort_values("a_date"), left_on="q", right_on="a_date", by="sid").set_index("rid").sort_index()
    aa = m[["sid", "a_date"]].dropna().assign(rid=lambda x: x.index).rename(columns={"a_date": "date"})
    base = tl[["sid", "date", "Ls"]].sort_values("date")
    mm = pd.merge_asof(aa.sort_values("date"), base, on="date", by="sid", direction="backward").set_index("rid")
    aLs = pd.Series(np.nan, index=m.index); aLs.loc[mm.index] = mm.Ls.values
    first = tl.groupby("sid").Ls.transform("first"); aLs = aLs.fillna(pd.Series(first.values, index=m.index).where(m.a_y.notna()))
    gg = np.where(m.a_y.notna(), kp.nfl_weeks_between(m.a_date.fillna(m.date), m.date) + c * (m.date - m.a_date).dt.days.fillna(0).values / 30, 0)
    kk = tl[k].values if isinstance(k, str) else k
    lam2 = gg / (gg + kk)
    tl["Lf"] = np.where(m.a_y.notna(), (1 - lam2) * (m.a_y.values + tl.Ls.values - aLs.values) + lam2 * tl.Ls.values, tl.Ls.values)
    tl["Lf"] = tl.Lf.clip(lower=0); tl["a_y"] = m.a_y.values; tl["a_date"] = m.a_date.values
    return tl


# ------------------------------------------------------------------ curves and the league-price model (v3 / v4 / v8 / v10)
def _pchip_from_iso(x, y, w, xs):
    iso = IsotonicRegression(out_of_bounds="clip").fit(x, y, sample_weight=w)
    ys = np.maximum.accumulate(iso.predict(xs)) + np.arange(len(xs)) * 1e-4
    return PchipInterpolator(xs, ys, extrapolate=True)


def fit_curve(o):
    a = o[(o.date >= "2022-01-01") & o.ktc.notna()]
    return _pchip_from_iso(a.ktc, a.y, a.w, np.r_[0, np.linspace(500, 9500, 19), 9999])


def qpos_fit_col(k_, col):
    out = {}
    for p in ("QB", "RB", "WR", "TE"):
        g = k_[(k_.pos == p) & k_[col].notna()]; q = np.linspace(0, 1, 201)
        out[p] = (np.quantile(g[col], q) + np.arange(201) * 1e-6, np.quantile(g.ktc, q))
    return out


def qpos_col(x, pos, f):
    return np.array([np.interp(v, *f[p]) if not np.isnan(v) else np.nan for v, p in zip(x, pos)])


def LG8(rows, cv, fS, fP, a, pvcol):
    ls = cv(np.clip(qpos_col(rows.S.clip(0).values, rows.pos.values, fS), 0, 9999))
    lp = cv(np.clip(qpos_col(rows[pvcol].values, rows.pos.values, fP), 0, 9999))
    ae = a * track_record(rows)
    return np.where(np.isnan(lp), ls, (1 - ae) * ls + ae * np.nan_to_num(lp))


def ld_models(o, k_, cols, pw, seeds):
    ms = []
    for sd in seeds:
        ms.append(gbm(random_state=sd, max_features=0.6).fit(o[cols], o.y, sample_weight=o.w))
        X = pd.concat([o[cols], k_[cols]]); y = np.r_[o.y.values, k_.y.values]; w = np.r_[o.w.values, k_.w.values * pw]
        ms.append(gbm(random_state=sd, max_features=0.6).fit(X, y, sample_weight=w))
    return ms


def ld_pred(ms, X, cols):
    return np.clip(np.mean([m.predict(X[cols]) for m in ms], 0), 0, None)


def stage(df):
    return np.clip(np.nan_to_num(df.exp.values.astype(float), nan=3), 0, 3)


def rookie_boost(df, b):
    st = stage(df); out = np.zeros(len(df))
    for s, v in enumerate(b): out[st == s] = v
    return out


def gated_boost(df, L, b, lo=10.0, hi=100.0):
    """rookie boost at full strength for real assets ($hi+), fading to none for fringe players ($lo-)"""
    g = np.clip((L - np.log1p(lo)) / (np.log1p(hi) - np.log1p(lo)), 0, 1)
    return L + g * rookie_boost(df, b)


# ------------------------------------------------------------------ walk-forward (wf_base2)
def league_rows(o0, PA):
    """league prices with channel, log price and era weight"""
    obs = o0.join(PA[["Addition type", "Season", "Price paid (FAAB)"]], on="rowid")
    obs["price"] = obs["Price paid (FAAB)"]; t = obs["Addition type"]
    obs["ch"] = np.select([t.eq("Commissioner"), t.eq("Draft") & obs.Season.eq(2020), t.eq("Draft"), t.eq("Trade"), t.eq("Waiver") & obs.price.gt(0)],
                          ["comm", "startup", "draft", "trade", "waiver"], "free")
    obs = obs[obs.ch != "comm"].copy(); obs.loc[obs.ch == "free", "price"] = 0.0
    obs["y"] = np.log1p(obs.price); obs["w"] = era_weight(obs.date) * np.where(obs.ch == "free", 0.5, 1.0)
    return obs


class WalkForward:
    """one quarterly snapshot's models, fit on data before R, applied to rows in [R, R1)"""

    def __init__(self, FC, football, bag=0):
        self.FC = FC; self.fb = football; self.bag = bag

    def with_S(self, df, Sfold):
        self.fb.add_pv(df); df["fold"] = fold_of(df.sid, self.bag); df["S"] = np.nan
        for k in range(5):
            m = df.fold == k
            if m.any(): df.loc[m, "S"] = Sfold[k].predict(df[m])
        df["sqS"] = np.sqrt(df.S.clip(0)); return df

    def obs_prep(self, LR, Fd, R, R1, Sfold):
        hist = self.with_S(LR[LR.date < R1].copy(), Sfold)
        obs = hist[hist.date < R].copy(); kt = self.with_S(Fd[Fd.date < R].copy(), Sfold)
        obs = add_anchor(obs, obs); kt = add_anchor(kt, obs)
        a = obs[obs.ktc.notna()]; a = a[a.date >= "2022-01-01"] if (a.date >= "2022-01-01").sum() >= 150 else a
        iso = IsotonicRegression(out_of_bounds="clip").fit(a.ktc, a.y); kt["y"] = iso.predict(kt.ktc); kt["w"] = era_weight(kt.date)
        return obs.reset_index(drop=True), kt.reset_index(drop=True), hist

    @staticmethod
    def curve_rows(o):
        a = o[o.ktc.notna()]; return a[a.date >= "2022-01-01"] if (a.date >= "2022-01-01").sum() >= 150 else a

    def block(self, R, R1, F_all, LR, Fd, log=print):
        t0 = time.time()
        Fd_R = self.fb.add_pv(Fd[Fd.date < R].copy()); Fd_R["fold"] = fold_of(Fd_R.sid, self.bag)
        Sfold = [kp.StatsModel(self.FC, ensemble=ENS).fit(Fd_R[Fd_R.fold != k]) for k in range(5)]
        obs, kt, hist = self.obs_prep(LR, Fd, R, R1, Sfold)
        F = self.with_S(F_all[(F_all.date >= R) & (F_all.date < R1)].copy(), Sfold)
        F = add_anchor(F, hist)
        COLS = list(dict.fromkeys(["posc"] + [c for c in feats(obs) if c != "posc"] + ["sqS"] + AF + PVF))
        L = np.zeros(len(F)); ref_all = kt[kt.date >= R - pd.Timedelta(days=3 * 365)]
        for k in range(5):
            m = (F.fold == k).values
            if not m.any(): continue
            o, kk = obs[obs.fold != k], kt[kt.fold != k]
            ms = ld_models(o, kk, COLS, 0.03, (0, 1, 2)); LD = ld_pred(ms, F[m], COLS)
            cv = fit_curve(self.curve_rows(o).assign(date=pd.Timestamp("2022-06-01"))); ref = ref_all[ref_all.fold != k]
            qS, qP = qpos_fit_col(ref.assign(S=ref.S.clip(0)), "S"), qpos_fit_col(ref, NM)
            L[m] = hybrid(LD, LG8(F[m], cv, qS, qP, A_PV, NM))
        F["L"] = gated_boost(F, L, BOOST, 2, 30); F["snap"] = R
        log(f"snapshot {R.date()}{f' bag {self.bag}' if self.bag else ''}: {len(F)} rows, obs {len(obs)}, panel {len(Fd_R)}, {time.time() - t0:.0f}s")
        return F


def bagged_block(FC, football, R, R1, F_all, LR, Fd, bags=None, log=print):
    """the snapshot's block under `bags` fold assignments; L (and S) averaged across them, the rest from bag 0"""
    bags = BAGS if bags is None else bags
    F = WalkForward(FC, football, 0).block(R, R1, F_all, LR, Fd, log=log)
    if bags <= 1: return F
    Ls, Ss = [F.L.values], [F.S.values]
    for b in range(1, bags):
        Fb = WalkForward(FC, football, b).block(R, R1, F_all, LR, Fd, log=log)
        Ls.append(Fb.L.values); Ss.append(Fb.S.values)
    F["L"] = np.mean(Ls, axis=0); F["S"] = np.mean(Ss, axis=0); F["bags"] = bags
    return F


def season_done(R):
    """last NFL season whose regular season ended before R"""
    return max(y for y, k in kp.KO.items() if pd.Timestamp(k) + pd.Timedelta(weeks=19) <= R)
