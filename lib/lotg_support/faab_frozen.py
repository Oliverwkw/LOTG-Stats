"""The frozen FAAB base (2026-11-10): every fitted piece of the base value is fit ONCE on all history, stored under
data/faab_value/frozen/, and a normal rebuild only applies it. A refreeze (`scripts/faab_rebuild.py --refreeze`) is a
deliberate, reviewed change, like a params.json refit.

Why (Oliver, 2026-11-10): "if KTC were to completely vanish from reality, the faab values of any player at any time
should not change. It is used to help make the model, but it should not ever change anything." The quarterly
walk-forward refits it replaces moved every player at each refit boundary (median weekly change in the base 0.133 log
across a refit vs 0.002 within a quarter; 32% of $25+ players moved 25%+) and passed KTC's own drift (its scale rose
~0.33 log 2020 -> 2026) straight into the base. And a 100% identical player (team and league context included) in 2021
and 2026 must get the same value: year-to-year differences only from football context (replacement level, supply).

What is fit once (FrozenBase.fit), on everything available at the freeze:
  - the aging curves (faab_base.Football; the replacement level is NOT a fit: each row reads its last five complete
    NFL seasons, a football-context input stored on the row as `ctx_repl`);
  - the stats translator S: stats -> "KTC at the same position rank", 5 player folds x BAGS bags (fold_of), every row
    weighted the same. The target is KtcScale: a player's KTC rank at his position that month, read on the median KTC
    at that rank pooled over every month (QB40 / RB70 / WR100 / TE35 are the research's caps; past them the pooled
    curve continues by rank, see KtcScale). It removes KTC's scale drift: in research the SD of quarterly mean
    residuals fell 0.100 -> 0.051 (all rows), 0.360 -> 0.064 past the caps (a ratio extension left 0.138);
  - the supply step: a row's predicted rank at his position among every board player that week (`u_rank`, the
    research's one clearly significant football factor: drift share +0.133 against a random-walk bar of 0.047), and a
    small model of the remaining residual on it. Leak-free: a fold-k row's rank is taken against the universe as the
    fold-k translator sees it (a model that never saw his KTC), and the supply model of a fold-k row is fit on the
    other folds;
  - the KTC-scale -> league-price maps (isotonic), the league-price models (ld), their curves (fit_curve) and the
    position quantile maps (qpos), all on every date;
  - the holding-value map (one map, faab_formula.Formula.holding_map), fit after the base on the smoothed values.

Applying (FrozenBase.apply) reads no KTC file: the grid's stats, the league's own prices (anchors), the replacement
level and the supply universe (the grid's own players). `context` puts every date-derived input on the row
(ctx_repl, u{b}, aS{b}, a_*); `apply_rows` is then a function of the row's columns only (tests/test_faab_frozen.py).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

from . import faab_base as B
from . import faab_frame as kp

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "data" / "faab_value" / "frozen"
GRID_START = pd.Timestamp("2020-09-09")       # the 2020 startup draft: the first valued date
UNIVERSE_START = pd.Timestamp("2020-04-07")   # the first Tuesday of the KTC panel's first month (supply ranks of the
                                              # translator's training rows need a universe from then)
RANK_CAP = {"QB": 40, "RB": 70, "WR": 100, "TE": 35}
T_OFF = 100.0                                 # the supply step works on log(S + 100)
DEPTH_LEVELS = (4500.0, 3000.0, 1500.0)      # the position's depth: players valued above each (elite / starter / flex)
SUPPLY_COLS = ["posc", "age", "exp", "tS1", "u_rank"]   # the depth counts and draft classes (_Z: n4500 .. own_cls)
# halve the translator's season drift on the KTC panel but made the league evidence worse (2026-11-14 report), so a
# refreeze keeps the first frozen base's supply inputs
SUPPLY_KW = dict(max_iter=150, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=300, random_state=0,
                 categorical_features=[0])
VERSION = 1


def t_(x):
    return np.log(np.clip(np.asarray(x, dtype=float), 0, None) + T_OFF)


def t_inv(z):
    return np.clip(np.exp(np.asarray(z, dtype=float)) - T_OFF, 0, 9999)


def ucols(b):
    """a bag's supply-context columns on a row: the rank, then the depth counts (supply_ctx)"""
    return [f"u{b}"] + [f"u{b}_{int(lv)}" for lv in DEPTH_LEVELS]


def _Z(rows, s1, u, cols):
    """the supply step's inputs: the translator (tS1), the rank (u_rank; u_cap = capped at the position's RANK_CAP:
    deeper than that the rank mostly counts how many fringe players the universe holds, which grows as the league's
    all-time rostered pool does), the depth counts and the draft classes (ctx_cls3 / ctx_own on the rows)"""
    u = np.asarray(u, dtype=float).reshape(len(rows), -1)
    cap = pd.Series(rows.pos.values).map(RANK_CAP).values.astype(float)
    d = dict(posc=rows.posc.values, age=rows.age.values, exp=rows.exp.values, tS1=t_(s1), u_rank=u[:, 0],
             u_cap=np.fmin(u[:, 0], cap))
    for i, lv in enumerate(DEPTH_LEVELS):
        d[f"n{int(lv)}"] = u[:, 1 + i] if u.shape[1] > 1 + i else np.nan
    nan = np.full(len(rows), np.nan)
    d["cls3"] = rows.ctx_cls3.values if "ctx_cls3" in rows else nan
    d["own_cls"] = rows.ctx_own.values if "ctx_own" in rows else nan
    return pd.DataFrame(d)[list(cols)]


# ------------------------------------------------------------------ the translator's target
class KtcScale:
    """KTC -> the value at the same position rank, pooled over months: a player's KTC rank at his position in a month,
    read on the median KTC every month gave that rank. KTC's own scale drifted (rank 200 overall: 876 in 2020, 2,411
    in 2026; 193 -> 398 players at 1,000+ a month), so the same player at the same rank gets the same target in
    any month.

    Past the research's caps (QB40 / RB70 / WR100 / TE35, where every month has the rank) the pooled curve simply
    continues by rank, over the months deep enough to have that rank, kept non-increasing. Measured on the KTC panel
    (5 player folds, the same stats model): SD of quarterly mean residuals past the caps 0.360 raw, 0.138 with the
    month's own KTC ratio to its cap-rank value, 0.064 with the rank curve (and no season trend: -0.07 .. -0.14), so
    the rank curve it is. Used only to fit; never applied."""

    def __init__(self, curve, months):
        self.curve, self.months = curve, months

    @staticmethod
    def _per(dates):
        return pd.to_datetime(pd.Series(dates)).dt.to_period("M").astype(str).values

    @staticmethod
    def _ranks(P):
        per = KtcScale._per(P.date.values)
        return P.groupby([per, P.pos.values]).ktc.rank(ascending=False, method="first").values, per

    @classmethod
    def fit(cls, panel):
        P = panel[panel.ktc.notna() & (panel.ktc > 0)]
        prk, per = cls._ranks(P)
        med = pd.Series(P.ktc.values).groupby([P.pos.values, prk.astype(int)]).median()
        curve = {p: np.minimum.accumulate(med.loc[p].sort_index().values.astype(float)) for p in RANK_CAP if p in med.index.get_level_values(0)}
        months = {k: np.sort(g.values.astype(float)) for k, g in pd.Series(P.ktc.values).groupby([per, P.pos.values])}
        return cls(curve, months)

    def at_rank(self, pos, r):
        out = np.full(len(r), np.nan)
        for p in np.unique(pos):
            m = pos == p; c = self.curve.get(p)
            if c is None: continue
            out[m] = c[np.clip(np.asarray(r)[m].astype(int), 1, len(c)) - 1]
        return out

    def target(self, panel):
        """the training target of panel rows (ktc > 0)"""
        prk, _ = self._ranks(panel)
        return self.at_rank(panel.pos.values, prk)

    def normalize(self, pos, dates, v):
        """any KTC value (a league row's KTC at pickup) on the same scale: its rank among that month's panel at the
        position (the latest panel month at or before it, else the first), read on the curve"""
        per = self._per(dates); v = np.asarray(v, dtype=float); pos = np.asarray(pos)
        keys = sorted(self.months); out = np.full(len(v), np.nan)
        for i, (p, m, x) in enumerate(zip(pos, per, v)):
            if np.isnan(x) or x <= 0 or p not in self.curve: continue
            arr = self.months.get((m, p))
            if arr is None:
                c = [k for k in keys if k[1] == p and k[0] <= m] or [k for k in keys if k[1] == p]
                if not c: continue
                arr = self.months[c[-1] if c[-1][0] <= m else c[0]]
            r = len(arr) - np.searchsorted(arr, x, side="right") + 1
            out[i] = self.curve[p][min(r, len(self.curve[p])) - 1]
        return out


# ------------------------------------------------------------------ the supply universe and ranks
def universe(F):
    """the supply universe: every board player (the grid's players) on each Tuesday, once drafted into the NFL"""
    from .faab_features import NFL_DRAFT
    d = pd.to_datetime(F.date); dy = F.dyear.fillna(0).astype(int)
    nfl = pd.to_datetime(dy.map(lambda y: NFL_DRAFT.get(y, f"{max(y, 1900)}-05-01")))
    keep = (d.dt.dayofweek == 1) & ((dy < d.dt.year) | ((dy == d.dt.year) & (d >= nfl)))
    return F[keep.values]


def supply_ctx(rows, s, U, uval, levels=DEPTH_LEVELS):
    """the supply context of each row, on the latest universe Tuesday at or before its date, among the universe players
    at his position (his own player left out): column 0 = his rank (1 + the number valued above him), then one column
    per depth level = how many are valued above it (how deep the position is at the elite / starter / flex levels that
    week). `s` and `uval` must come from the same model (the row's fold)."""
    ud, gi, sids, upos = _universe_index(U)
    uval = np.asarray(uval)
    rd = pd.to_datetime(rows.date).values.astype("datetime64[ns]")
    j = np.searchsorted(ud, rd, side="right") - 1
    lv = np.asarray(levels, dtype=float)
    out = np.full((len(rows), 1 + len(lv)), np.nan)
    rp = rows.pos.values; s = np.asarray(s, dtype=float)
    # the row's own universe value that Tuesday (the last universe row of his sid and that date), else -inf
    code = sids.get_indexer(rows.sid.astype(str).to_numpy(dtype=object))
    at = upos.reindex(np.where((code >= 0) & (j >= 0), code * len(ud) + j, -1)).to_numpy()
    OV = np.full(len(rows), -np.inf); ok = ~np.isnan(at)
    OV[ok] = uval[at[ok].astype(np.int64)]
    keys = pd.Series(np.arange(len(rows))).groupby([np.where(j >= 0, j, -1), rp]).indices
    for (jj, p), ix in keys.items():
        if jj < 0: continue
        u = ud[jj]; g = gi.get((u, p))
        if g is None: continue
        asc = np.sort(uval[g])
        cnt = len(asc) - np.searchsorted(asc, s[ix], side="right")
        ov = OV[ix]
        out[ix, 0] = 1 + cnt - (ov > s[ix])
        above = len(asc) - np.searchsorted(asc, lv, side="right")
        out[ix, 1:] = above[None, :] - (ov[:, None] > lv[None, :])
    return out


_UIX = {}


def _universe_index(U):
    """what supply_ctx reads from the universe itself, built once per universe frame (per process): its Tuesdays, the
    rows of each (Tuesday, position), and each (sid, Tuesday)'s last row (the row a dict over the universe keeps)"""
    if _UIX.get("U") is U and _UIX.get("n") == len(U): return _UIX["ix"]
    Ud = U.date.values.astype("datetime64[ns]"); Up = U.pos.values
    Us = U.sid.astype(str).to_numpy(dtype=object)     # numpy: iterating an arrow-backed column is ~10x slower
    ud = np.unique(Ud)
    gi = pd.Series(np.arange(len(U))).groupby([Ud, Up]).indices
    sc, sids = pd.factorize(Us)
    key = sc.astype(np.int64) * len(ud) + np.searchsorted(ud, Ud)
    upos = pd.Series(np.arange(len(U), dtype=float), index=key)
    upos = upos[~upos.index.duplicated(keep="last")]
    ix = (ud, gi, pd.Index(sids), upos)
    _UIX.clear(); _UIX.update(U=U, n=len(U), ix=ix)
    return ix


def supply_rank(rows, s, U, uval):
    """the rank column of supply_ctx (1 + the number of universe players at the position valued above the row's)"""
    return supply_ctx(rows, s, U, uval, levels=())[:, 0]


# ------------------------------------------------------------------ draft-class context
def class_table(picks):
    """NFL rounds 1-2 picks per (draft year, position) from a draft-picks table (season, round, position): the incoming
    early-round talent at each position. Draft results are football facts (no hindsight column is read)."""
    p = picks[(picks["round"] <= 2) & picks.position.isin(list(RANK_CAP))]
    return p.groupby(["season", "position"]).size().astype(float)


def class_table_from_universe(U):
    """the same table from the universe's own players (their draft year and round), when no draft-picks table is given:
    a league's universe holds every early-round skill player (rostered in a superflex dynasty league)"""
    u = U.drop_duplicates("sid"); u = u[(u.dround <= 2) & u.dyear.notna()]
    return u.groupby([u.dyear.astype(int).values, u.pos.values]).size().astype(float)


def class_ctx(rows, table):
    """per row: `ctx_cls3` = NFL round 1-2 picks at his position in the last three drafts held by the row's date (the
    talent arriving at the position: more of it, less scarcity), `ctx_own` = those in his own draft class at his
    position (classmates competing for the same roles; NaN when he was undrafted or before 2000)"""
    from .faab_features import NFL_DRAFT
    d = pd.to_datetime(pd.Series(rows.date).values); yr = d.year.values
    held = np.array([x >= pd.Timestamp(NFL_DRAFT.get(int(y), f"{int(y)}-05-01")) for x, y in zip(d, yr)], dtype=bool)
    last = np.where(held, yr, yr - 1); pos = np.asarray(rows.pos.values)
    tab = table.to_dict()
    cls3 = np.array([sum(tab.get((int(y) - i, p), 0.0) for i in range(3)) for y, p in zip(last, pos)], dtype=float)
    dy = pd.to_numeric(pd.Series(rows.dyear).values, errors="coerce") if "dyear" in rows else np.full(len(rows), np.nan)
    own = np.array([tab.get((int(y), p), 0.0) if not np.isnan(y) and y >= 2000 and y <= l else np.nan
                    for y, p, l in zip(dy, pos, last)], dtype=float)
    return cls3, own


# ------------------------------------------------------------------ this season's role (the league-price step)
ROLE = (("r_tgt", "e_x_cur_tgt_share", "e_x_l0_tgt_share"), ("r_snap", "s_snap_cur", "s_snap_l0"),
        ("r_car", "e_x_cur_car_share", "e_x_l0_car_share"), ("r_xfp", "e_x_cur_xfp_share", "e_x_l0_xfp_share"))
ROLE_GAMES = 6.0                              # this season's share counts fully from his 6th game
ROLE_COLS = [n for n, _, _ in ROLE] + [f"{n}_d" for n, _, _ in ROLE]
USE_ROLE = False                              # off: +2 calls and -0.004 trade error, but 6 more far-off trades (v4, 2026-11-14)


def add_role(rows):
    """this season's role: target / snap / carry / expected-points share, this season's weighted by games played (a
    sixth per game, full from 6) against last season's (`r_*`), and the change itself (`r_*_d`, also games-weighted).
    Football reason: a role shows in usage weeks before points settle; a share held over 6+ games is the player's role,
    so a breakout (or a lost job) should move his price that fast, not at last season's pace."""
    rows = rows.copy()
    w = np.clip(np.nan_to_num(pd.to_numeric(rows.c_gp, errors="coerce").values.astype(float)) / ROLE_GAMES, 0, 1) if "c_gp" in rows \
        else np.zeros(len(rows))
    for name, cur, l0 in ROLE:
        cu = rows[cur].values.astype(float) if cur in rows else np.full(len(rows), np.nan)
        lo = rows[l0].values.astype(float) if l0 in rows else np.full(len(rows), np.nan)
        cw = np.where(np.isnan(cu), 0.0, w)
        rows[name] = np.where(np.isnan(lo), np.where(cw > 0, cu, np.nan), cw * np.nan_to_num(cu) + (1 - cw) * lo)
        rows[f"{name}_d"] = np.where(np.isnan(cu) | np.isnan(lo), np.nan, w * (cu - lo))
    return rows


def add_class_ctx(rows, table):
    rows = rows.copy(); rows["ctx_cls3"], rows["ctx_own"] = class_ctx(rows, table)
    return rows


# ------------------------------------------------------------------ fits run in worker processes
def _fit_translator(task):
    """one (bag, fold) stats translator on the panel's other folds, every row weighted the same"""
    b, k = task
    X, ys, folds, ens = B._SHARED["_SM"]
    m = folds[b] != k
    sm = kp.StatsModel(list(X.columns), ensemble=ens)
    sm.models = [(t, kp._gbm(**kw).fit(X[m], ys[t][m])) for t, kw in ens]
    return sm


def _sha(*frames):
    h = hashlib.sha256()
    for f in frames:
        h.update(pd.util.hash_pandas_object(f.reset_index(drop=True), index=False).values.tobytes())
    return h.hexdigest()


class FrozenBase:
    """the stored base: per bag, the translators (5 folds), supply models, league-price models, curves and quantile
    maps; the aging curves; the feature lists; and the holding-value map"""

    def __init__(self, bags, meta):
        self.bags, self.meta = bags, meta
        self.holding = meta.get("holding")

    # ---- fit
    @classmethod
    def fit(cls, Fd, LR, U, football, bags=None, workers=None, log=print, ens=None, ld_kw=None, supply_kw=None, classes=None,
            reuse=None):
        """Fd: the KTC panel frame (stats + ktc); LR: league rows (faab_base.league_rows); U: the supply universe
        (universe()); football: a faab_base.Football already fit (its curves are stored); classes: NFL round 1-2 picks
        per (draft year, position) (class_table; default: from the universe's own players)"""
        import time
        t0 = time.time(); nb = B.BAGS if bags is None else bags; ens = B.ENS if ens is None else ens
        skw = dict(SUPPLY_KW, **(supply_kw or {}))
        Fd = Fd[Fd.ktc.notna() & (Fd.ktc > 0)].reset_index(drop=True)
        Fd = football.add_pv(Fd.copy())
        classes = class_table_from_universe(U) if classes is None else classes
        Fd = add_role(add_class_ctx(Fd, classes))
        scale = KtcScale.fit(Fd); Fd["yp"] = scale.target(Fd)
        FC = [c for c in dict.fromkeys([c for c in B.feats(Fd) if not c.startswith("e_x_")] + B.PVF
                                       + [c for c in Fd.columns if c.startswith("e_x_")]) if c not in kp.FORBIDDEN]
        folds = [B.fold_of(Fd.sid, b) for b in range(nb)]
        if reuse is not None:         # a stored base's translators and supply models (a league-price-step change only)
            assert reuse.meta["FC"] == FC and reuse.meta["bags"] == nb, "reuse: the stored base's translator inputs differ"
            T = {b: reuse.bags[b]["trans"] for b in range(nb)}
        else:
            with B._Pool(workers) as pool:
                pool.share(_SM=(Fd[FC], {"sqrt": np.sqrt(Fd.yp.values), "raw": Fd.yp.values}, folds, ens))
                fits = pool.map(_fit_translator, [(b, k) for b in range(nb) for k in range(5)])
            T = {b: [fits[b * 5 + k] for k in range(5)] for b in range(nb)}
        log(f"frozen fit: {nb * 5} translators on {len(Fd)} panel rows ({time.time() - t0:.0f}s)")
        U = football.add_pv(U.copy()).reset_index(drop=True)
        UP = {(b, k): T[b][k].predict(U) for b in range(nb) for k in range(5)}
        log(f"frozen fit: supply universe {len(U)} rows predicted ({time.time() - t0:.0f}s)")
        LRp = add_role(add_class_ctx(football.add_pv(LR.copy()).reset_index(drop=True), classes))
        P, sup = [], {}
        for b in range(nb):
            fd = folds[b]; S1 = np.zeros(len(Fd)); u = np.zeros((len(Fd), 1 + len(DEPTH_LEVELS)))
            for k in range(5):
                m = fd == k
                S1[m] = T[b][k].predict(Fd[m]); u[m] = supply_ctx(Fd[m], S1[m], U, UP[(b, k)])
            Z = _Z(Fd, S1, u, SUPPLY_COLS)
            r = t_(Fd.yp.values) - Z.tS1.values
            g = reuse.bags[b]["supply"] if reuse is not None else [B.HistGradientBoostingRegressor(**skw).fit(Z[fd != k], r[fd != k]) for k in range(5)]
            S = np.zeros(len(Fd))
            for k in range(5):
                m = fd == k; S[m] = t_inv(Z.tS1.values[m] + g[k].predict(Z[m]))
            sup[b] = g
            kt = Fd.assign(S=S, fold=fd, sqS=np.sqrt(S))
            o = LRp.assign(fold=B.fold_of(LRp.sid, b))
            o["S"] = cls._S_rows(o, T[b], g, U, UP, b, cols=SUPPLY_COLS)
            o["sqS"] = np.sqrt(o.S.clip(0))
            o = B.add_anchor(o, o); kt = B.add_anchor(kt, o)
            o["ktc"] = scale.normalize(o.pos.values, o.date.values, o.ktc.values)    # KTC at pickup on the rank scale
            kt["ktc"] = kt.yp.values
            a = o[o.ktc.notna()]
            iso = B.IsotonicRegression(out_of_bounds="clip").fit(a.ktc, a.y)
            kt["y"] = iso.predict(kt.ktc); kt["w"] = 1.0
            COLS = list(dict.fromkeys(["posc"] + [c for c in B.feats(o) if c != "posc"] + ["sqS"] + B.AF + B.PVF + ([c for c in ROLE_COLS if o[c].notna().any() and kt[c].notna().any()] if USE_ROLE else [])))
            COLS = [c for c in COLS if c not in kp.FORBIDDEN]
            P.append((o, kt, COLS, iso))
        log(f"frozen fit: supply models and league rows ({time.time() - t0:.0f}s)")
        COLS = P[0][2]
        tasks = [(b, k, sd) for b in range(nb) for k in range(5) for sd in B.LD_SEEDS]
        with B._Pool(workers) as pool:
            pool.share(_LD=[(o[COLS], o.y.values, o.w.values, o.fold.values, kt[COLS], kt.y.values, kt.w.values, kt.fold.values)
                            for o, kt, _, _ in P], _LD_KW=dict(ld_kw or {}))
            got = dict(zip(tasks, pool.map(B._fit_ld, tasks)))
        bagd = []
        for b in range(nb):
            o, kt, _, iso = P[b]; cv, qS, qP, ld = [], [], [], []
            for k in range(5):
                ok = o[o.fold != k]; ref = kt[kt.fold != k]
                cv.append(B.fit_curve(ok)); qS.append(B.qpos_fit_col(ref.assign(S=ref.S.clip(0)), "S")); qP.append(B.qpos_fit_col(ref, B.NM))
                ld.append([x for sd in B.LD_SEEDS for x in got[(b, k, sd)]])
            bagd.append(dict(trans=T[b], supply=sup[b], ld=ld, cv=cv, qS=qS, qP=qP, iso=iso))
        import sklearn
        meta = dict(version=VERSION, freeze_date=str(_dt.date.today()), bags=nb, FC=FC, COLS=COLS, SUPPLY_COLS=SUPPLY_COLS,
                    depth_levels=list(DEPTH_LEVELS),
                    football=football.curves(), rank_cap=RANK_CAP, rank_curve={p: list(map(float, c)) for p, c in scale.curve.items()},
                    data_sha256=_sha(Fd[["sid", "date", "yp"] + FC], LRp[["sid", "date", "y", "w", "ch", "price"]]),
                    rows=dict(panel=len(Fd), league=len(LRp), universe=len(U)),
                    versions=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                                  sklearn=sklearn.__version__, scipy=__import__("scipy").__version__),
                    ens=[[t, kw] for t, kw in ens], supply_kw={k: v for k, v in skw.items()}, ld_kw=dict(ld_kw or {}))
        log(f"frozen fit done ({time.time() - t0:.0f}s)")
        return cls(bagd, meta)

    # ---- S on any rows (translator + supply)
    @staticmethod
    def _S_rows(rows, Tb, gb, U, UP, b, S1=None, u=None, cols=SUPPLY_COLS):
        """S = the translator + the supply step; u: the rows' supply context (supply_ctx), else computed from U / UP"""
        fd = B.fold_of(rows.sid, b); S = np.zeros(len(rows))
        for k in range(5):
            m = fd == k
            if not m.any(): continue
            r = rows[m]
            s1 = _pred(("t", b, k), Tb[k].predict, r[Tb[k].F]) if S1 is None else S1[m]
            uu = supply_ctx(r, s1, U, UP[(b, k)]) if u is None else u[m]
            Z = _Z(r, s1, uu, cols)
            S[m] = t_inv(Z.tS1.values + _pred(("s", b, k), gb[k].predict, Z))
        return S

    def ucols(self, b):
        return ucols(b)

    # ---- apply
    def football(self, seasons):
        return B.Football(seasons).set_curves(self.meta["football"])

    def universe_values(self, U):
        """the translator on the supply universe, every (bag, fold)"""
        return {(b, k): _pred(("t", b, k), self.bags[b]["trans"][k].predict, lambda T=self.bags[b]["trans"][k]: U[T.F], base=U,
                              cols=self.bags[b]["trans"][k].F)
                for b in range(len(self.bags)) for k in range(5)}

    def context(self, F, hist, U, UP, football, classes=None):
        """every date-derived input on the rows: the replacement level and production value (ctx_repl, PV ...), the
        league-price anchors (a_*), and per bag the supply rank (u{b}) and the anchor's S (aS{b}); `_S1_{b}` caches the
        translator for apply_rows. hist: league rows with sid, date, price, ch and S{b} per bag (league_history)."""
        F = football.add_pv(F.copy())
        F = add_role(add_class_ctx(F, class_table_from_universe(U) if classes is None else classes))
        a = B.anchor_columns(F, hist)
        for k, v in a.items(): F[k] = v
        for b in range(len(self.bags)):
            fd = B.fold_of(F.sid, b); S1 = np.zeros(len(F)); u = np.zeros((len(F), 1 + len(DEPTH_LEVELS)))
            for k in range(5):
                m = fd == k
                if not m.any(): continue
                T = self.bags[b]["trans"][k]
                S1[m] = _pred(("t", b, k), T.predict, lambda: F.loc[m, T.F], base=F, m=m, cols=T.F)
                u[m] = supply_ctx(F.loc[m, ["sid", "date", "pos"]], S1[m], U, UP[(b, k)])     # (all it reads)
            F[f"_S1_{b}"] = S1
            for i, c in enumerate(ucols(b)): F[c] = u[:, i]
            F[f"aS{b}"] = np.where(F.a_hi.values >= 0, hist[f"S{b}"].values[np.maximum(F.a_hi.values, 0)], np.nan)
        return F

    def league_history(self, LR, U, UP, football, classes=None):
        """the league rows the anchors read, with each bag's S"""
        h = add_class_ctx(football.add_pv(LR.copy()).reset_index(drop=True), class_table_from_universe(U) if classes is None else classes)
        for b, bg in enumerate(self.bags):
            h[f"S{b}"] = self._S_rows(h, bg["trans"], bg["supply"], U, UP, b, cols=self.meta["SUPPLY_COLS"])
        return h[["sid", "date", "price", "ch"] + [f"S{b}" for b in range(len(self.bags))]]

    def apply_rows(self, F):
        """(L, S) of rows that carry their context (context()): a function of the rows' columns only (no date)"""
        L_all, S_all = [], []
        COLS = self.meta["COLS"]
        TF = self.bags[0]["trans"][0].F
        # the ld models read the translator's columns plus a few: their cache keys combine the translator columns' row
        # hashes (taken once) with the rest's (a row's key is still a function of exactly the columns the model reads)
        XT = [c for c in COLS if c not in set(TF)] if set(TF) <= set(COLS) else None
        Fb = F.copy()            # F + this bag's S, sqS, a_dS (set per bag on one copy: the frame F.assign made each time)
        for b, bg in enumerate(self.bags):
            S1 = F[f"_S1_{b}"].values if f"_S1_{b}" in F else self._S1(F, bg["trans"], b)
            S = self._S_rows(F, bg["trans"], bg["supply"], None, None, b, S1=S1, u=F[ucols(b)].values, cols=self.meta["SUPPLY_COLS"])
            Fb["S"] = S; Fb["sqS"] = np.sqrt(np.clip(S, 0, None))
            Fb["a_dS"] = np.sqrt(np.clip(S, 0, None)) - np.sqrt(np.clip(F[f"aS{b}"].values, 0, None))
            fd = B.fold_of(F.sid, b); L = np.zeros(len(F))
            for k in range(5):
                m = fd == k
                if not m.any(): continue
                r = Fb[m]
                fn = lambda X, ms=bg["ld"][k]: B.ld_pred(ms, X, COLS)
                if XT is None: LD = _pred(("ld", b, k), fn, r[COLS])
                else: LD = _pred(("ld", b, k), fn, lambda r=r: r[COLS], base=F, m=m, cols=TF, extra=r[XT])
                L[m] = B.hybrid(LD, B.LG8(r, bg["cv"][k], bg["qS"][k], bg["qP"][k], B.A_PV, B.NM))
            L_all.append(B.gated_boost(Fb, L, B.BOOST, 2, 30)); S_all.append(S)
        return np.mean(L_all, axis=0), np.mean(S_all, axis=0)

    @staticmethod
    def _S1(F, Tb, b):
        fd = B.fold_of(F.sid, b); S1 = np.zeros(len(F))
        for k in range(5):
            m = fd == k
            if m.any(): S1[m] = _pred(("t", b, k), Tb[k].predict, F.loc[m, Tb[k].F])
        return S1

    def apply(self, F, LR, U, seasons, log=print, chunk="YS", classes=None, workers=None, cache=None):
        """the base (L, S and the context columns) on every row of F, a chunk of dates at a time.

        Every step is a function of the row (its own columns, the shared universe and league history), so the result
        does not depend on how the rows are chunked. With `workers` > 1 (default faab_base.WORKERS; 1 = in this
        process) the universe's 25 translator predictions, the league history and then quarter-sized chunks run over
        forked processes, one tree thread each (the trees' predictions do not depend on the thread count), and come back
        in date order: the same frame as one process. Forked so the rows and models are shared, not copied; the parent
        runs no OpenMP code before it forks (every prediction happens in the children).

        `cache`: a folder for the prediction cache (faab_predict_cache): each model's prediction for a row whose inputs
        are byte-identical to a row it predicted in the last run is read back instead of recomputed (the same float)."""
        global PC
        if cache is not None and PC is None:
            from . import faab_predict_cache as PCM
            PC = PCM.PredictCache(cache, cache_tag(self.meta))
            try:
                out = self.apply(F, LR, U, seasons, log=log, chunk=chunk, classes=classes, workers=workers)
                h, m = PC.hits, PC.misses
                PC.save()
                log(f"frozen base: prediction cache {h} rows read back, {m} predicted")
                return out
            finally:
                PC = None
        import time
        t0 = time.time()
        n = max(1, int(workers or B.WORKERS))
        fb = self.football(seasons)
        Uc = fb.add_pv(U.copy()).reset_index(drop=True)
        classes = class_table_from_universe(Uc) if classes is None else classes
        d = pd.to_datetime(F.date)
        spans, masks = _date_chunks(d, chunk)
        if n <= 1:
            UP = self.universe_values(Uc)
            hist = self.league_history(LR, Uc, UP, fb, classes)
            log(f"frozen base: universe {len(Uc)} rows, league rows {len(hist)} ({time.time() - t0:.0f}s)")
            out = []
            for (lo, hi), m in zip(spans, masks):
                out.append(self._apply_chunk(F[m], hist, Uc, UP, fb, classes))
                log(f"frozen base: {lo.date()} .. {hi.date()}: {int(m.sum())} rows ({time.time() - t0:.0f}s)")
            return pd.concat(out, ignore_index=True)
        import gc
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        from concurrent.futures.process import BrokenProcessPool
        global _FZ_STATE
        keys = [(b, k) for b in range(len(self.bags)) for k in range(5)]
        _, qmasks = _date_chunks(d, "QS")                  # smaller pieces for the processes (less memory each, better balance)

        def pool():
            return ProcessPoolExecutor(n, mp_context=mp.get_context("fork"), initializer=_one_thread)
        gc.collect(); gc.freeze()                # the children share the parent's objects: keep the collector off them
        try:
            _FZ_STATE = dict(FB=self, Uc=Uc, fb=fb, classes=classes, LR=LR)
            with pool() as ex:
                UP = {}
                for kk, (v, new) in zip(keys, ex.map(_fork_universe, keys)): UP[kk] = v; _pc_add(new)
                hist, new = ex.submit(_fork_history, UP).result(); _pc_add(new)
            log(f"frozen base: universe {len(Uc)} rows, league rows {len(hist)} ({time.time() - t0:.0f}s)")
            _FZ_STATE.update(UP=UP, hist=hist, F=F, masks=qmasks)
            with pool() as ex:
                out = []
                for c, new in ex.map(_fork_chunk, range(len(qmasks))): out.append(c); _pc_add(new)
        except BrokenProcessPool as e:          # a process died (out of memory): the same result, one process
            log(f"frozen base: worker process lost ({e}); running in one process")
            _FZ_STATE = None; gc.unfreeze()
            return self.apply(F, LR, U, seasons, log=log, chunk=chunk, classes=classes, workers=1)
        finally:
            _FZ_STATE = None; gc.unfreeze()
        log(f"frozen base: {len(qmasks)} quarter chunks, {int(sum(m.sum() for m in qmasks))} rows, over {n} processes ({time.time() - t0:.0f}s)")
        # each piece keeps F's row order; put the rows back in the order one process returns them (by `chunk`, then F's order)
        return pd.concat(out, ignore_index=True).iloc[_serial_order(qmasks, masks)].reset_index(drop=True)

    def _apply_chunk(self, Fm, hist, Uc, UP, fb, classes):
        C = self.context(Fm, hist, Uc, UP, fb, classes)
        C["L"], C["S"] = self.apply_rows(C)
        C["sqS"] = np.sqrt(C.S.clip(0)); C["fold"] = B.fold_of(C.sid, 0)
        C["a_dS"] = C.sqS.values - np.sqrt(np.clip(C["aS0"].values, 0, None))
        C = C.drop(columns=[c for c in C.columns if c.startswith("_S1_")])
        for c in C.columns:
            if C[c].dtype == "float64" and c not in ("L", "S"): C[c] = C[c].astype("float32")
        return C

    # ---- store
    @staticmethod
    def _slim(m, n_features):
        """zero the tree-node fields only training reads (gain, count, depth, bin_threshold): predictions are unchanged
        (checked on a probe matrix, else the model is kept whole) and the stored base is ~2.4x smaller"""
        import copy
        rng = np.random.default_rng(0)
        X = rng.normal(0, 3, size=(400, n_features)); X[:, 0] = np.arange(400) % 4
        s = copy.deepcopy(m)
        for it in s._predictors:
            for p in it:
                for f in ("gain", "count", "depth", "bin_threshold"):
                    if f in p.nodes.dtype.names: p.nodes[f] = 0
        return s if np.array_equal(m.predict(X), s.predict(X)) else m

    def save(self, path=DIR):
        import joblib
        path = Path(path); path.mkdir(parents=True, exist_ok=True)
        for b, bg in enumerate(self.bags):
            bg = dict(bg)
            for sm in bg["trans"]:
                sm.models = [(t, self._slim(m, len(sm.F))) for t, m in sm.models]
            bg["ld"] = [[self._slim(m, len(self.meta["COLS"])) for m in ms] for ms in bg["ld"]]
            bg["supply"] = [self._slim(m, len(SUPPLY_COLS)) for m in bg["supply"]]
            joblib.dump(bg, path / f"bag{b}.joblib", compress=("xz", 6))
        meta = dict(self.meta); meta["holding"] = self.holding
        meta["files"] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(path.glob("bag*.joblib"))}
        (path / "manifest.json").write_text(json.dumps(meta, indent=1, default=str))
        return path

    def save_holding(self, holding, path=DIR):
        self.holding = holding; self.meta["holding"] = holding
        m = json.loads((Path(path) / "manifest.json").read_text()); m["holding"] = holding
        (Path(path) / "manifest.json").write_text(json.dumps(m, indent=1, default=str))

    @classmethod
    def load(cls, path=DIR):
        path = Path(path); meta = json.loads((path / "manifest.json").read_text())
        files = []
        for b in range(meta["bags"]):
            f = path / f"bag{b}.joblib"
            got = hashlib.sha256(f.read_bytes()).hexdigest(); want = meta.get("files", {}).get(f.name)
            if want and got != want:
                raise ValueError(f"{f} does not match the manifest's sha256: refreeze or restore it")
            files.append((f, got))
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(min(len(files), 5) or 1) as ex:
            bags = list(ex.map(lambda t: _load_bag(*t), files))
        return cls(bags, meta)


MODEL_CACHE = ROOT / ".cache" / "faab" / "frozen_models"


def _load_bag(f, sha):
    """one bag file: joblib's xz pickle reads through its pure-Python unpickler (~3 s a bag), so the same objects are
    kept once as a plain pickle (zlib level 1) under MODEL_CACHE, named by the file's sha256, and read back from there
    (~0.7 s): the same models either way. A missing or unreadable copy is rebuilt from the file."""
    import pickle, zlib
    c = MODEL_CACHE / f"{sha}.pkl.z"
    try:
        if c.exists(): return pickle.loads(zlib.decompress(c.read_bytes()))
    except Exception:                       # noqa: BLE001 - a bad copy: read the file and write it again
        pass
    import joblib
    obj = joblib.load(f)
    try:
        c.parent.mkdir(parents=True, exist_ok=True); tmp = c.with_suffix(f".tmp{id(obj)}")
        tmp.write_bytes(zlib.compress(pickle.dumps(obj, protocol=5), 1)); tmp.replace(c)
    except Exception:                       # noqa: BLE001 - no cache (read-only disk): the file is the source anyway
        pass
    return obj


def _date_chunks(d, freq):
    """(spans, row masks) of the dates `d` cut at `freq` edges counted from the first year's 1 January (empty pieces left out)"""
    edges = list(pd.date_range(d.min().normalize() - pd.offsets.YearBegin(1), d.max() + pd.offsets.YearBegin(1), freq=freq))
    sp, ms = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = ((d >= lo) & (d < hi)).values
        if m.any(): sp.append((lo, hi)); ms.append(m)
    return sp, ms


def _serial_order(pieces, masks):
    """the positions that put rows stacked piece by piece (each piece in F's order) into the order of rows stacked
    chunk by chunk under `masks` (each chunk in F's order); every piece must sit inside one chunk or span several whole
    ones in order"""
    pos = np.concatenate([np.flatnonzero(m) for m in pieces])
    cid = np.full(len(masks[0]), -1)
    for i, m in enumerate(masks): cid[m] = i
    return np.lexsort((pos, cid[pos]))


_FZ_STATE = None


def _one_thread():
    try:
        from threadpoolctl import threadpool_limits
        global _LIMITS
        _LIMITS = threadpool_limits(1)
    except Exception:                  # noqa: BLE001 - only a speed setting
        pass


def _fork_universe(bk):
    b, k = bk; S = _FZ_STATE; T = S["FB"].bags[b]["trans"][k]
    return _pred(("t", b, k), T.predict, lambda: S["Uc"][T.F], base=S["Uc"], cols=T.F), _pc_new()


def _fork_history(UP):
    S = _FZ_STATE
    return S["FB"].league_history(S["LR"], S["Uc"], UP, S["fb"], S["classes"]), _pc_new()


def _fork_chunk(i):
    S = _FZ_STATE
    return S["FB"]._apply_chunk(S["F"][S["masks"][i]], S["hist"], S["Uc"], S["UP"], S["fb"], S["classes"]), _pc_new()


PC = None           # the prediction cache (faab_predict_cache.PredictCache) while apply() runs with one


def _pred(key, fn, X, base=None, m=None, cols=None, extra=None):
    """fn(X): a model's predictions for the rows of X (exactly the columns it reads), through the cache when one is set.
    X may be a function returning the frame: it is then built only for rows the cache does not hold.
    `base`, `cols` (with `m`, a row mask of base): X's rows are base.loc[m] and the cache keys are read from base's row
    hashes over `cols`, taken once for every model that reads them (a row's hash is a function of that row only);
    `extra`: a frame of the rows' other columns, whose hashes are combined in (X = those columns plus `extra`'s)."""
    if PC is None: return fn(X() if callable(X) else X)
    h = None
    if base is not None:
        h1, h2 = _frame_hashes(base, tuple(cols))
        h = (h1, h2) if m is None else (h1[m], h2[m])
        if extra is not None:
            from . import faab_predict_cache as PCM
            h = PCM.combine(h, PCM.row_hashes(extra))
    return PC.predict(key, fn, X, h=h)


_FH = []            # (frame, columns, hashes) of the frames whose row hashes were taken in this process (the last few)


def _frame_hashes(base, cols):
    for b, c, h in _FH:
        if b is base and c == cols: return h
    from . import faab_predict_cache as PCM
    h = PCM.row_hashes(base[list(cols)])
    _FH.append((base, cols, h)); del _FH[:-4]
    return h


def _pc_new():
    return PC.take_new() if PC is not None else None


def _pc_add(new):
    if PC is not None and new is not None: PC.add(new[0]); PC.hits += new[1]; PC.misses += new[2]


def cache_tag(meta):
    """the cache's identity: the base's manifest plus the code of the functions whose outputs it stores"""
    from . import faab_predict_cache as PCM
    return PCM.tag_for(meta, "|".join(PCM.code_id(f) for f in (kp.StatsModel.predict, B.ld_pred, _Z, PCM.row_hashes, PCM.combine)))


def exists(path=DIR):
    """a stored base: its manifest (committed) is there; its model files are checked when it is loaded (ensure)"""
    return (Path(path) / "manifest.json").exists()


ASSET_ENV = "FAAB_FROZEN_URL"     # where the model files can be downloaded from (a release asset folder URL)


def ensure(path=DIR, log=print):
    """the model files the manifest lists, present and matching its sha256: downloaded from the manifest's
    `asset_url` (or $FAAB_FROZEN_URL) when missing. Never refits: a missing base is an error, not a refreeze (a refit on
    newer data would be a different base)."""
    import os
    import urllib.request
    p = Path(path); m = json.loads((p / "manifest.json").read_text())
    url = os.environ.get(ASSET_ENV) or m.get("asset_url")
    for name, sha in m.get("files", {}).items():
        f = p / name
        if f.exists() and hashlib.sha256(f.read_bytes()).hexdigest() == sha: continue
        if not url:
            raise FileNotFoundError(f"{f} is missing or differs from the manifest, and no asset_url / ${ASSET_ENV} is set: "
                                    f"restore it (the release asset of the freeze), or refreeze deliberately (--refreeze)")
        log(f"downloading {name} from {url}")
        urllib.request.urlretrieve(f"{url.rstrip('/')}/{name}", f)
        if hashlib.sha256(f.read_bytes()).hexdigest() != sha:
            raise ValueError(f"{name} from {url} does not match the manifest's sha256")
    return p


def file_hashes(path=DIR):
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(Path(path).glob("*")) if f.is_file()}
