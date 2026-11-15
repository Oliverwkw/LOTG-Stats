"""Pieces of the FAAB base value (the `Lf` the formula and rules start from): football priors, the production value,
the league-price curves and models, anchors to a player's last league price, and the causal smoothing / routing.

The base is FROZEN (lotg_support.faab_frozen, 2026-11-10): every fitted piece here is fit once on all history and
stored; a normal rebuild only applies it. Nothing in this module reads the date as an input: the replacement level is
a function of the row's last five complete NFL seasons (football context), the aging curves are fit once, and every
row weighs the same whatever its date (the quarterly refits, the era weight, the 1-year recency weight and the
"2022 on" / "last 3 years" windows were removed with the quarterly snapshot loop).

KTC is a training scale only (the translator's target and the KTC-scale -> league-price maps, fit once); no value is
ever read from KTC when a row is valued.

Moved from the research scripts (common / anchor / chain / pv / v3 / v4 / v7-v10 / tl_base / wf_base2).
"""
from __future__ import annotations

import hashlib
import os

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

from . import faab_frame as kp

# Out-of-fold predictions for top players moved 30-40% with nothing but the fold assignment (Gibbs's base $3,539 ->
# $2,204 on the same data, 2026-10; across six assignments he was bimodal, ~$2,200 or ~$3,540, by which comparable
# players shared his held-out fold). The base is therefore fit under BAGS assignments and a player's base is the
# mean of his log values. Measured on the 2026-10 quarter's top 150: two single draws differ by a median 15%, two
# independent 3-bag means by 9% (the 1/sqrt(n) the noise predicts); 5 bags leave ~7%.
BAGS = int(os.environ.get("FAAB_BAGS", "5"))     # bags fit by a refreeze (applying uses every stored bag)
DEMAND = {"QB": 16, "RB": 24, "WR": 32, "TE": 9}   # weekly starters league-wide (1 QB + SF, 2 RB, 3 WR, 1 TE, 2 FLEX)
ENS = [("sqrt", dict(max_leaf_nodes=63, learning_rate=0.05, max_iter=800)), ("raw", dict(max_iter=500))]
CFG = (0.3, 0.0, 2.5); A_PV = 0.67; NM = "pv_main"
PVF = ["PV", "pv_ppg", "lPV"]
AF = ["a_lp", "a_gap", "a_g", "a_dS", "a_free", "a_trade"]
LO, HI = np.log1p(100), np.log1p(1000)
BOOST = (0.4, 0.0, 0.35)
REPL_YEARS = 5                 # the replacement level reads the row's last five complete NFL seasons


# ------------------------------------------------------------------ small helpers (common)
def feats(df):
    return kp.features(df)


def gbm(**kw):
    p = dict(max_iter=500, learning_rate=0.03, max_leaf_nodes=8, min_samples_leaf=15, l2_regularization=1.0,
             random_state=0, categorical_features=[0])
    p.update(kw)
    return HistGradientBoostingRegressor(**p)


def fold_of(sids, bag=0):
    """out-of-fold group by player: a stable hash of the Sleeper id (and the bag)"""
    sids = pd.Series(sids).astype(str)
    salt = "" if bag == 0 else f"{bag}:"
    code, uniq = pd.factorize(sids.to_numpy(dtype=object))        # each distinct id hashed once
    f = np.array([int(hashlib.md5((salt + s).encode()).hexdigest(), 16) % 5 for s in uniq], dtype=int)
    return f[code] if len(code) else np.zeros(0, dtype=int)


def season_done(R):
    """last NFL season whose regular season ended before R"""
    return max(y for y, k in kp.KO.items() if pd.Timestamp(k) + pd.Timedelta(weeks=19) <= R)


def seasons_done(dates):
    """season_done for every date (vectorised over the unique dates)"""
    d = pd.to_datetime(pd.Series(dates)).values.astype("datetime64[ns]")
    ys = np.array(sorted(kp.KO)); ends = np.array([pd.Timestamp(kp.KO[y]) + pd.Timedelta(weeks=19) for y in ys], dtype="datetime64[ns]")
    j = np.searchsorted(ends, d, side="right") - 1
    return np.where(j >= 0, ys[np.clip(j, 0, None)], ys[0] - 1)


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


def polyval_by_pos(coefs, pos, x):
    """np.polyval(coefs[pos[i]], x[i]) for every row (0 where the position has no curve): the same Horner steps
    np.polyval takes on each scalar, run on all of a position's rows at once, so the same floats"""
    x = np.asarray(x); out = np.zeros(len(x))
    pos = np.asarray(pos, dtype=object)
    for p, c in coefs.items():
        m = pos == p
        if not m.any(): continue
        xm = x[m]; y = np.zeros_like(xm)
        for cv in np.asarray(c): y = y * xm + cv
        out[m] = y
    return out


def production_value(df, R, cur, years=5, disc=0.75, games=15):
    """R: each row's replacement level (Football.repl_rows)"""
    pos = df.pos.values; R = np.asarray(R, dtype=float)
    w0 = np.where(df.c_gp.fillna(0).values > 0, 0.8, 1.0)
    num, den = np.zeros(len(df)), np.zeros(len(df))
    for gp, ppg, w in (("c_gp", "c_ppg", 1.0), ("n_gp_l0", "n_ppg_l0", w0), ("n_gp_l1", "n_ppg_l1", 0.4), ("n_gp_l2", "n_ppg_l2", 0.15)):
        g = np.nan_to_num(df[gp].values.astype(float)); x = np.nan_to_num(df[ppg].values.astype(float))
        num += g * w * x; den += g * w
    base = (num + 4.0 * R) / (den + 4.0); has = den > 0; age = df.age.fillna(25).values
    pv = np.zeros(len(df)); ppg = base.copy()
    for y in range(years):
        pv += disc ** y * games * np.clip(ppg - R, 0, None)
        lr = polyval_by_pos(cur, pos, age + y)
        ppg = ppg * np.exp(np.clip(lr, -0.5, 0.3))
    pv[~has] = np.nan
    return pv, base


class Football:
    """the football priors: the per-game aging curve and the survivor aging curve (with drop-offs), FIT ONCE on the
    seasons complete at the freeze (`fit`, or `set_curves` from the stored base), and each row's replacement level,
    which is not a fit: the mean over the row's last five complete seasons of each position's Nth-best PPG among 6+
    game seasons (N = league-wide weekly starters, DEMAND). A row's level is football context (how deep the position
    was), so an identical player with an identical league around him gets the identical level in any year."""

    def __init__(self, seasons):
        self.ALL = seasons
        self.SEAS = seasons[seasons.games >= 6]
        self.CAR = set(self.SEAS.player_id)
        self.cur, self.cur2 = {}, {}
        self._repl = {}
        self._memo()

    def _memo(self):
        """memo tables for the pure per-row pieces (cleared when the curves change). add_pv runs on the same rows
        repeatedly (panel, league rows, grid), so most rows repeat exactly."""
        self._af, self._ceil, self._seas_by = {}, {}, None

    def fit(self, last):
        """the aging curves on the seasons through `last` (the survivor curve needs the season after: through last - 1)"""
        self._memo()
        s = self.ALL[self.ALL.season <= last]
        self.cur = aging_curves(s)
        self.cur2 = self._aging_v2(s, last)
        self.fit_last = int(last)
        return self

    def curves(self):
        return dict(cur={k: list(map(float, v)) for k, v in self.cur.items()},
                    cur2={k: list(map(float, v)) for k, v in self.cur2.items()}, fit_last=getattr(self, "fit_last", None))

    def set_curves(self, c):
        self._memo()
        self.cur = {k: np.array(v, dtype=float) for k, v in c["cur"].items()}
        self.cur2 = {k: np.array(v, dtype=float) for k, v in c["cur2"].items()}
        self.fit_last = c.get("fit_last")
        return self

    def repl_for(self, last):
        """{pos: replacement PPG} from the seasons last-4..last (the ones in the data)"""
        r = self._repl.get(last)
        if r is None:
            s = self.ALL[(self.ALL.season <= last) & (self.ALL.season >= last - REPL_YEARS + 1)]
            r = {}
            for p, n in DEMAND.items():
                v = [g[g.games >= 6].ppg.sort_values(ascending=False).iloc[n] for _, g in s[s.position == p].groupby("season")
                     if (g.games >= 6).sum() > n]
                r[p] = float(np.mean(v)) if v else 10.0
            self._repl[last] = r
        return r

    def repl_rows(self, df):
        """each row's replacement level: from the last five NFL seasons complete by its date"""
        last = seasons_done(df.date.values)
        out = np.full(len(df), 10.0)
        pos = df.pos.values
        for y in np.unique(last):
            r = self.repl_for(int(y)); m = last == y
            out[m] = [r.get(p, 10.0) for p in pos[m]]
        return out

    def _aging_v2(self, ALL, last):
        """per-game survivor curve + the extra cliff risk by age (season totals with drop-offs counted)"""
        a = ALL[(ALL.games >= 12) & (ALL.ppg >= 8)][["player_id", "season", "position", "fantasy_points_ppr", "age"]].dropna(subset=["age"])
        nxt = ALL[["player_id", "season", "fantasy_points_ppr", "games"]].assign(season=lambda d: d.season - 1).rename(columns={"fantasy_points_ppr": "pts_next", "games": "g_next"})
        m = a.merge(nxt, on=["player_id", "season"], how="left")
        m = m[m.season <= last - 1]
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
        k = (pos, a0, a1)
        f = self._af.get(k)
        if f is None:
            n = max(0, int(round(a1 - a0)))
            # the curve at a0, a0 + 1, ... in one array (each element the scalar polyval's float), summed left to right
            f = self._af[k] = float(np.exp(sum(np.polyval(self.cur[pos], a0 + np.arange(n)).tolist()))) if pos in self.cur else 1.0
        return f

    def career_ceiling_aged(self, df, top=2):
        """the mean of a player's best `top` seasons (6+ games, through lcs), each aged to his current age. Per player
        the seasons are read from a dict of arrays (in SEAS's row order) and each (player, lcs, pos, age) result is
        memoised."""
        if self._seas_by is None:
            S = self.SEAS
            self._seas_by = {g: (x.season.values, x.ppg.values, x.age.values) for g, x in S.groupby("player_id", sort=False)}
        out = np.full(len(df), np.nan); by = self._seas_by; memo = self._ceil
        for i, (g, lcs, pos, age) in enumerate(zip(df.gsis.values, df.lcs.values, df.pos.values, df.age.values)):
            if g not in self.CAR or g not in by: continue        # (a NaN id is in neither)
            k = (g, lcs, pos, age)
            r = memo.get(k, memo)
            if r is memo:
                r = None
                se, pp, ag = by[g]; m = se <= lcs
                if m.any() and not np.isnan(age):
                    aged = [p * self.age_factor(pos, sa, age) if not np.isnan(sa) else p for p, sa in zip(pp[m], ag[m])]
                    r = np.mean(sorted(aged, reverse=True)[:top])
                memo[k] = r
            if r is not None: out[i] = r
        return out

    def pv8_level(self, df, ceil_w, R):
        pos = df.pos.values
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

    def pv9(self, df, ceil_w=0.3, beta=0.0, h=2.5, out_now=None, cap=0.35, R=None):
        """production value on a continuous clock: f = share of the current season played (0 in the offseason).
        Season y is f years nearer; its discount is 0.75^(y - f) and its aging runs y - f years. (beta = 0: the
        research legacy term is off in this configuration.)"""
        assert beta == 0.0, "legacy boost is not ported (CFG has beta = 0)"
        R = self.repl_rows(df) if R is None else R
        level, R, pos, games, has, age = self.pv8_level(df, ceil_w, R)
        out = np.zeros(len(df), bool) if out_now is None else np.asarray(out_now, bool)
        cw = np.nan_to_num(df.c_weeks.values.astype(float)); f = np.where(cw > 0, np.clip(cw / 18, 0, 1), 0.0)
        lr = np.column_stack([np.clip(polyval_by_pos(self.cur2, pos, age + k), -1.0, 0.3) for k in range(7)])   # 0 = no curve
        cum = np.concatenate([np.zeros((len(df), 1)), np.cumsum(lr, axis=1)], axis=1)
        pv = np.zeros(len(df))
        for y in range(6):
            tau = np.clip(y - f, 0, None); k = np.floor(tau).astype(int); fr = tau - k
            G = cum[np.arange(len(df)), k] + fr * lr[np.arange(len(df)), np.minimum(k, 6)]
            g_y = games * ((1 - f) if y == 0 else f if y == 5 else 1.0)
            pv += 0.75 ** tau * np.where(out & (y == 0), 0.0, g_y) * np.clip(level * np.exp(G) - R, 0, None)
        pv[~has] = np.nan
        return np.log1p(pv)

    def add_pv(self, F, R=None):
        """PV / pv_ppg / lPV / pv_main on F. R: each row's replacement level (default: from its date, repl_rows); the
        frozen base stores it on the row as `ctx_repl` so the value is a function of the row's columns only"""
        R = self.repl_rows(F) if R is None else np.asarray(R, dtype=float)
        F["ctx_repl"] = R
        F["PV"], F["pv_ppg"] = production_value(F, R, self.cur); F["lPV"] = np.log1p(F.PV)
        F[NM] = self.pv9(F, *CFG, R=R)
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
def anchor_index(rows, hist):
    """for each row, the position in `hist` of the player's most recent league price strictly before the row's date
    (-1: none), with that price's date"""
    h = pd.DataFrame(dict(sid=hist.sid.values, a_date=pd.to_datetime(hist.date.values).astype("datetime64[ns]"), hi=np.arange(len(hist))))
    r = pd.DataFrame(dict(sid=rows.sid.values, date=pd.to_datetime(rows.date.values).astype("datetime64[ns]"), rid=np.arange(len(rows))))
    r["q"] = r.date - pd.Timedelta(days=1)
    m = kp.merge_asof(r.sort_values("q"), h.sort_values("a_date"), left_on="q", right_on="a_date", by="sid").set_index("rid").sort_index()
    return m.hi.fillna(-1).astype(int).values, m.a_date.values, m.date.values


def anchor_columns(rows, hist):
    """the league-price anchor columns that do not depend on the translator: a_lp, a_gap, a_g, a_free, a_trade, and
    `a_hi` (the anchor's position in hist, -1 = none) for the anchor's S (a_dS, per bag)"""
    hi, a_date, date = anchor_index(rows, hist)
    ok = hi >= 0; j = np.where(ok, hi, 0)
    price = np.where(ok, hist.price.values[j].astype(float), np.nan); ch = np.where(ok, hist.ch.values[j], None)
    gap = np.where(ok, (date - a_date) / np.timedelta64(1, "D"), np.nan)
    out = dict(a_lp=np.log1p(price), a_gap=gap,
               a_g=np.where(ok, kp.nfl_weeks_between(np.where(ok, a_date, date), date), np.nan),
               a_free=np.where(ok, (ch == "free").astype(float), np.nan), a_trade=np.where(ok, (ch == "trade").astype(float), np.nan),
               a_hi=hi)
    return out


def add_anchor(rows, hist):
    """anchor = the player's most recent league price strictly before the row's date (hist has sid, date, price, S, ch)"""
    out = rows.copy()
    a = anchor_columns(rows, hist)
    for k, v in a.items():
        if k != "a_hi": out[k] = v
    aS = np.where(a["a_hi"] >= 0, hist.S.values[np.maximum(a["a_hi"], 0)], np.nan)
    out["a_dS"] = np.sqrt(out.S.clip(0).values) - np.sqrt(np.clip(aS, 0, None))
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
    Ls = np.empty(len(tl)); sid = tl.sid.to_numpy(dtype=object); L = tl.L.to_numpy()      # numpy arrays: per-element reads of an
    # arrow-backed column are ~20x slower in this loop
    for i in range(len(tl)):
        Ls[i] = L[i] if (i == 0 or sid[i] != sid[i - 1]) else Ls[i - 1] + lam[i] * (L[i] - Ls[i - 1])
    tl["Ls"] = Ls
    h = hist[["sid", "date", "y"]].rename(columns={"date": "a_date", "y": "a_y"}).copy()
    h["a_date"] = h.a_date.astype("datetime64[ns]")
    t2 = tl.assign(rid=np.arange(len(tl)), q=tl.date - pd.Timedelta(days=1))
    m = kp.merge_asof(t2.sort_values("q"), h.sort_values("a_date"), left_on="q", right_on="a_date", by="sid").set_index("rid").sort_index()
    aa = m[["sid", "a_date"]].dropna().assign(rid=lambda x: x.index).rename(columns={"a_date": "date"})
    base = tl[["sid", "date", "Ls"]].sort_values("date")
    mm = kp.merge_asof(aa.sort_values("date"), base, on="date", by="sid", direction="backward").set_index("rid")
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
    """KTC-scale -> league price (log1p $) over every league row with a KTC value (all years: the 'from 2022 on'
    window went with the frozen base; o.ktc is the position-rank-normalised KTC, faab_frozen.KtcScale)"""
    a = o[o.ktc.notna()]
    return _pchip_from_iso(a.ktc, a.y, a.w, np.r_[0, np.linspace(500, 9500, 19), 9999])


def qpos_fit_col(k_, col):
    out = {}
    for p in ("QB", "RB", "WR", "TE"):
        g = k_[(k_.pos == p) & k_[col].notna()]; q = np.linspace(0, 1, 201)
        out[p] = (np.quantile(g[col], q) + np.arange(201) * 1e-6, np.quantile(g.ktc, q))
    return out


def qpos_col(x, pos, f):
    """np.interp on each row's position's curve (NaN stays NaN): one call per position, the same floats as per row"""
    x = np.asarray(x, dtype=float); pos = np.asarray(pos, dtype=object)
    out = np.full(len(x), np.nan); ok = ~np.isnan(x)
    for p in pd.unique(pos[ok]):
        m = ok & (pos == p); out[m] = np.interp(x[m], *f[p])
    return out


def LG8(rows, cv, fS, fP, a, pvcol):
    ls = cv(np.clip(qpos_col(rows.S.clip(0).values, rows.pos.values, fS), 0, 9999))
    lp = cv(np.clip(qpos_col(rows[pvcol].values, rows.pos.values, fP), 0, 9999))
    ae = a * track_record(rows)
    return np.where(np.isnan(lp), ls, (1 - ae) * ls + ae * np.nan_to_num(lp))


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


def league_rows(o0, PA):
    """league prices with channel and log price. Every date weighs the same (the era weight that counted 2020 rows a
    quarter went with the frozen base); a $0 add counts half."""
    obs = o0.join(PA[["Addition type", "Season", "Price paid (FAAB)"]], on="rowid")
    obs["price"] = obs["Price paid (FAAB)"]; t = obs["Addition type"]
    obs["ch"] = np.select([t.eq("Commissioner"), t.eq("Draft") & obs.Season.eq(2020), t.eq("Draft"), t.eq("Trade"), t.eq("Waiver") & obs.price.gt(0)],
                          ["comm", "startup", "draft", "trade", "waiver"], "free")
    obs = obs[obs.ch != "comm"].copy(); obs.loc[obs.ch == "free", "price"] = 0.0
    obs["y"] = np.log1p(obs.price); obs["w"] = np.where(obs.ch == "free", 0.5, 1.0)
    return obs


# ------------------------------------------------------------------ the parallel fits
LD_SEEDS = (0, 1, 2)          # the league-price models' seeds
WORKERS = int(os.environ.get("FAAB_WORKERS", "0")) or (os.cpu_count() or 1)
_SHARED: dict = {}


def _fit_ld(task):
    """one (bag, fold, seed) pair of league-price models: league rows alone, and league rows + the KTC panel at 3%"""
    b, k, sd = task
    oX, oy, ow, of, kX, ky, kw, kf = _SHARED["_LD"][b]
    kwargs = _SHARED.get("_LD_KW", {})
    mo, mk = of != k, kf != k
    a = gbm(random_state=sd, max_features=0.6, **kwargs).fit(oX[mo], oy[mo], sample_weight=ow[mo])
    X = pd.concat([oX[mo], kX[mk]]); y = np.r_[oy[mo], ky[mk]]; w = np.r_[ow[mo], kw[mk] * 0.03]
    return [a, gbm(random_state=sd, max_features=0.6, **kwargs).fit(X, y, sample_weight=w)]


def _worker_init(shared):
    _SHARED.update(shared)
    try:
        from threadpoolctl import threadpool_limits
        _SHARED["_limits"] = threadpool_limits(1)    # one fit per core: the trees are the same on any thread count
    except Exception:                  # noqa: BLE001 - only a speed setting
        pass


class _Pool:
    """map over processes (spawned, so no OpenMP state is forked), or in this process when n == 1. `share` sets the
    data the next map's tasks read (sent once per worker)."""

    def __init__(self, workers=None):
        self.n = max(1, int(workers or WORKERS)); self.shared = {}

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def share(self, **kw): self.shared.update(kw)

    def map(self, fn, tasks):
        tasks = list(tasks)
        if self.n == 1 or len(tasks) <= 1:
            _SHARED.update(self.shared)
            try: return [fn(t) for t in tasks]
            finally:
                for k in self.shared: _SHARED.pop(k, None)
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(min(self.n, len(tasks)), mp_context=mp.get_context("spawn"), initializer=_worker_init,
                                 initargs=(self.shared,)) as ex:
            return list(ex.map(fn, tasks))
