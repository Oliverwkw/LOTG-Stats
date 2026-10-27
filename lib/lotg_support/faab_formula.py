"""Date-aware formula: the walk-forward base (`Lf`) -> V_raw, the value the general rules in faab_value start from.

On any date, using only what was known then: the base value (injured players at the best of now, just before the
injury and preseason), this season's games so far (best game at half weight), the injury report for the latest
completed week, the last league price, the rookie-draft slot's price once the rookie draft has happened. Then:

  holding-value map  isotonic map base -> league price, fitted on owned-player evidence before the snapshot
                     (trades, drafts, and the league chat's valuations x4: data/faab_value/chat_evidence.csv)
  league terms       young / old QB, old RB, the decline past each position's fade age, past top finishes
                     (half-life 2.5 seasons), a breakout this season against the established level
  floors (soft)      young players hold their rookie-slot price, a sophomore-or-younger star holds 1.6x his last
                     price, a starting QB never under $50, production rank by position (smooth in rank)
  rookies            the slot's price x how they have played, fading out by the next rookie draft
  offseason          from the stats rollover to kickoff, the end-of-season view blends into the new-season view

Moved from the research scripts (fast_board / fast_board2 / fast_board3 / faab_wf) with the logic unchanged.
Floors are soft maxima (fmax + 0.12 log1p(exp(-|a-b|/0.12))), as in the research run, so floored players keep
their own differences.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from . import faab_frame as kp

KO = {int(k): pd.Timestamp(v) for k, v in kp.KO.items()}
P = {'oldqb': -0.6, 'oldrb': -0.2, 'h': 2.5, 'leg_cap': 0.4, 'kappa': 1.0, 'top_lo': 1200, 'top_hi': 2200, 'young_floor': 1.0,
     'last_w': 0.6, 'rookie_w': 0.9, 'hold': 1.6, 'scale': 1.0, 'te_f': 0.5, 'age_min': 0.6, 'prime_extra': 0.0}
TOP5 = {"QB": 22.0, "RB": 18.5, "WR": 17.0, "TE": 13.0}            # approx position top-5 PPG level
FADE = {"QB": (33, 37), "RB": (29, 33), "WR": (30, 33), "TE": (30, 33)}
EXP = {"QB": 14, "RB": 9, "WR": 7, "TE": 5}                        # rookie-year PPG that holds a slot's price
TIER_R, TIER_V = [1, 3, 6, 10, 16, 22], [2000, 2000, 1500, 1000, 500, 0]
TAU = 20.0
CRED_MIN = 0.35


def smax(a, b, t=0.12):
    a = np.asarray(a, float); b = np.asarray(b, float)
    return np.fmax(a, b) + t * np.log1p(np.exp(-np.abs(a - b) / t))


def weeks_done(date):
    s = max(y for y, k in KO.items() if k <= date + pd.Timedelta(days=200))
    return s, int(np.clip((date - KO[s]).days // 7 + (1 if (date - KO[s]).days % 7 >= 5 else 0), 0, 18)) if date >= KO[s] else 0


def yqb(d, size): return np.where(d.pos.values == "QB", size * np.clip((29 - d.age.fillna(30).values) / 1.5, 0, 1), 0.0)
def oldqb(d, size): return np.where(d.pos.values == "QB", size * np.clip((d.age.fillna(30).values - 35) / 3, 0, 1), 0.0)
def old_rb(d, size): return np.where(d.pos.values == "RB", size * np.clip((d.age.fillna(25).values - 28.5) / 1.5, 0, 1), 0.0)


def yqb_exp(d, size):
    """the young-QB discount is about an unproven track record, not age: full for a QB's first two seasons, half in
    his third, none after"""
    return yqb(d, size) * np.clip((3 - d.exp.fillna(0).values) / 2, 0, 1)


class Formula:
    """V_raw on any date from the base timeline TL (sid, date, Lf, a_y and the frame columns)"""

    def __init__(self, TL, PA, rookie_picks, evidence, seasons, player_week, injury_tracker, wk_dir=None):
        TL = TL.copy(); TL["date"] = pd.to_datetime(TL.date); TL["sid"] = TL.sid.astype(str)
        self.TL = TL.drop_duplicates(["sid", "date"]).sort_values(["sid", "date"])
        self._hist = {s_: (g.date.values, g.Lf.values) for s_, g in self.TL[["sid", "date", "Lf"]].groupby("sid")}
        n = self.TL.groupby("date").size(); self.GRID = sorted(n.index[n >= 0.5 * n.max()])
        self._by_date = {d: g for d, g in self.TL.groupby("date")}
        cg = self.TL.groupby("date").c_gp.apply(lambda x: x.notna().mean())
        self.C_MAX = float(cg.max()); cg = cg / cg.max()
        self.ROLL = [g for g, p in zip(cg.index[1:], cg.values[1:]) if p < 0.03 and cg[cg.index < g].iloc[-1] >= 0.03]
        self.SNAPS = sorted(self.TL.snap.dropna().unique()) if "snap" in self.TL else []
        pa = PA.copy(); pa["d"] = pd.to_datetime(pa.Date.astype(str).str[:10]); pa["sid"] = pa.sid.astype(str)
        self.DR = pa[pa["Addition type"] == "Draft"].sort_values("d")
        self.DRAFT_DAY = self.DR.groupby("Season").d.min(); self.DRAFT_DAY.index = self.DRAFT_DAY.index.astype(int)
        # rookie-draft slot of each young player, and the league's slot prices (drafts before a date)
        dr = pa[pa["Addition type"] == "Draft"].assign(Season=lambda x: x.Season.astype(str))
        rp = rookie_picks[rookie_picks.Number.astype(str).str.fullmatch(r"\d\.\d\d")].assign(Year=lambda x: x.Year.astype(str))
        self.m = rp.merge(dr[["Player", "Season", "sid", "Price paid (FAAB)"]], left_on=["Player Picked", "Year"], right_on=["Player", "Season"], how="left")
        self.SLOT_OF = self.m.dropna(subset=["sid"]).assign(sid=lambda x: x.sid.astype(str)).drop_duplicates("sid", keep="last").set_index("sid").Number
        E = evidence.copy(); E["date"] = pd.to_datetime(E.date); E["sid"] = E.sid.astype(str); self.E_ALL = E
        # past finishes for the legacy term: positional rank among 8+ game seasons, historic years
        X = seasons[seasons.games >= 8].copy()
        X["prank"] = X.groupby(["season", "position"]).ppg.rank(ascending=False)
        fifth = X[X.prank == 5].set_index(["season", "position"]).ppg
        X["historic"] = X.ppg >= 1.25 * pd.Series(list(zip(X.season, X.position))).map(fifth).values
        X["pts"] = np.select([X.prank <= 1, X.prank <= 3, X.prank <= 6], [1.0, 0.6, 0.3], 0.0) + 0.5 * X.historic
        X["pts2"] = X.pts + np.where((X.prank > 6) & (X.prank <= 12), 0.15, 0.0)
        self.LEG2 = {g: dd[["season", "pts2"]].values for g, dd in X[X.pts2 > 0].groupby("player_id")}
        self.PW = player_week; self.TRK = injury_tracker[injury_tracker.injury_status.isin(["IR", "PUP", "Out", "Doubtful"])]
        self.wk_dir = wk_dir or kp.CACHE
        self._wk, self._recal = {}, {}

    # ---- inputs on a date
    def _wkfile(self, s):
        if s not in self._wk:
            w = pd.read_csv(self.wk_dir / f"wk_{s}.csv", low_memory=False, usecols=["player_id", "position", "week", "season_type", "fantasy_points_ppr"])
            self._wk[s] = w[w.season_type == "REG"]
        return self._wk[s]

    def rob_at(self, date):
        s, n = weeks_done(date)
        w = self._wkfile(s); w = w[w.week <= n]
        return w.groupby("player_id").fantasy_points_ppr.apply(lambda s_: (lambda p: (sum(p) - 0.5 * p[-1]) / (len(p) - 0.5) if len(p) >= 4 else sum(p) / len(p))(sorted(s_)))

    def _prov(self, season, n):
        w = self._wkfile(season); w = w[w.week <= n]
        g = w.groupby(["player_id", "position"]).fantasy_points_ppr.agg(["mean", "size"]).reset_index()
        g = g[g["size"] >= max(3, n * 8 / 17)]
        g["prank"] = g.groupby("position")["mean"].rank(ascending=False)
        fifth = g.groupby("position")["mean"].apply(lambda x: x.nlargest(5).min())
        hist = g["mean"] >= 1.25 * g.position.map(fifth)
        pts = np.select([g.prank <= 1, g.prank <= 3, g.prank <= 6], [1.0, 0.6, 0.3], 0.0) + 0.5 * hist + np.where((g.prank > 6) & (g.prank <= 12), 0.15, 0.0)
        return dict(zip(g.player_id, pts * min(1.0, n / 18)))

    def legacy_t(self, d, h, date):
        s_, n = weeks_done(date); t = s_ - 1 + n / 18
        prov = self._prov(s_, n) if 0 < n < 18 else {}
        out = np.zeros(len(d))
        for i, g in enumerate(d.gsis.values):
            v = self.LEG2.get(g); tot = 0.0
            if v is not None:
                v = v[(v[:, 0] < s_) | ((v[:, 0] == s_) & (n >= 18))]; tot = float(np.sum(v[:, 1] * 0.5 ** ((t - v[:, 0]) / h)))
            out[i] = tot + prov.get(g, 0.0)
        return out

    def injuries_at(self, date, d):
        """status and body part for the latest completed week (2026+: the injury tracker; earlier: player_week's Injury?)"""
        s, n = weeks_done(date); st_, bp = pd.Series("", index=d.index), pd.Series("", index=d.index)
        if n == 0: return st_, bp, {}
        if s >= 2026:
            t = self.TRK[(self.TRK.season == s) & (self.TRK.week <= n)]
            cur = t[t.week == n].set_index("player_id")
            st_.update(cur.injury_status.reindex(d.index).dropna()); bp.update(cur.injury_body_part.fillna("").reindex(d.index).dropna())
            start = {}
            for sid in st_[st_ != ""].index:
                wks = set(t[t.player_id == sid].week); w = n
                while w - 1 in wks: w -= 1
                start[sid] = w
        else:
            p = self.PW[(self.PW.Year == s) & (self.PW.Week <= n)]; inj = p[p["Injury?"].astype(str).str.lower().isin(["true", "yes", "1"])]
            cur = set(inj[inj.Week == n].Player); start = {}
            for sid, nm in d.name.items():
                if nm in cur:
                    st_[sid] = "Out"; wks = set(inj[inj.Player == nm].Week); w = n
                    while w - 1 in wks: w -= 1
                    start[sid] = w
        return st_, bp, {k: KO[s] + pd.Timedelta(days=7 * (w - 1) - 3) for k, w in start.items()}

    def frame_at(self, date, stats_date=None):
        date = pd.Timestamp(date); sd = pd.Timestamp(stats_date) if stats_date is not None else date
        g = max(x for x in self.GRID if x <= sd); g_now = max(x for x in self.GRID if x <= date)
        d = self._by_date[g].drop_duplicates("sid").set_index("sid").copy()
        if g_now != g:
            nowr = self._by_date[g_now].drop_duplicates("sid").set_index("sid")
            for c in ["Lf", "a_y", "a_date", "age"]: d[c] = nowr[c].reindex(d.index).values
        dy = d.dyear.fillna(0).astype(int)
        d = d[(dy < date.year) | ((dy == date.year) & (date >= self.DRAFT_DAY.reindex(dy).fillna(pd.Timestamp(f"{date.year}-07-15")).values))]
        d["st"] = np.minimum(d.exp.fillna(0), 3)
        dp = self.DR[self.DR.d <= date].drop_duplicates("sid", keep="last").set_index("sid")["Price paid (FAAB)"]
        d["dprice"] = d.index.map(dp)
        inj, bp, start = self.injuries_at(sd, d); d["injury"] = inj.reindex(d.index).fillna("")
        s_ko = KO[weeks_done(sd)[0]]
        for sid, t0 in start.items():   # injured: the best of now, just before the injury and preseason
            hd, hl = self._hist.get(sid, (np.array([], "datetime64[ns]"), None))
            for t_ in (t0, s_ko - pd.Timedelta(days=1)):
                j = np.searchsorted(hd, np.datetime64(t_), side="right") - 1
                if j >= 0: d.loc[sid, "Lf"] = max(d.loc[sid, "Lf"], hl[j])
        d["c_ppg_raw"], d["c_gp_raw"] = d.c_ppg, d.c_gp
        d.loc[d.injury != "", ["c_ppg", "c_gp"]] = np.nan
        d["bp"] = bp.reindex(d.index).fillna(""); d["a_y"] = d.a_y.astype(float)
        return d

    def snap_of(self, date):
        return max([x for x in self.SNAPS if x <= np.datetime64(date)], default=self.SNAPS[0])

    def recal_at(self, R):
        """the holding-value map (base -> league price): isotonic on owned-player evidence before R (chat
        valuations x4), never below the base, smoothed so it has no flat steps"""
        R = pd.Timestamp(R)
        if R in self._recal: return self._recal[R]
        e = self.E_ALL[self.E_ALL.date < R].merge(self.TL[["sid", "date", "Lf"]], on=["sid", "date"], how="inner").dropna(subset=["Lf", "y"])
        xs = np.linspace(0, 9, 91)
        if len(e) < 40: ys = xs.copy()
        else:
            w = e.w.values * np.where(e.typ.isin(["accepted", "valuation", "offer", "ask"]), 4.0, 1.0)
            iso = IsotonicRegression(out_of_bounds="clip").fit(e.Lf, e.y, sample_weight=w)
            ys = np.maximum.accumulate(np.maximum(iso.predict(xs), xs))
        ys = np.convolve(np.pad(ys, 2, mode="edge"), np.ones(5) / 5, mode="valid"); ys = np.maximum.accumulate(ys) + 0.01 * np.arange(len(ys)) / len(ys)
        self._recal[R] = (lambda b, xs=xs, ys=ys: np.interp(b, xs, ys)); return self._recal[R]

    def slotv_at(self, date):
        m = self.m.dropna(subset=["Price paid (FAAB)"]); held = m.Year.astype(int).map(lambda y: self.DRAFT_DAY.get(y, pd.Timestamp(f"{y}-07-15")))
        return m[held.values < pd.Timestamp(date)].groupby("Number")["Price paid (FAAB)"].median()

    # ---- the formula pieces
    @staticmethod
    def robust_now(d, ROB):
        rob = d.index.map(d.gsis.to_dict()).map(ROB).values.astype(float); c = d.c_ppg.values.astype(float)
        return np.where(~np.isnan(rob) & ~np.isnan(c), rob, c)

    @staticmethod
    def breakout(d, Lb, beta, top_lo, top_hi, ROB):
        l0, l1 = d.n_ppg_l0.values.astype(float), d.n_ppg_l1.values.astype(float); g0, g1 = np.nan_to_num(d.n_gp_l0.values.astype(float)), np.nan_to_num(d.n_gp_l1.values.astype(float))
        inj = np.where(g0 >= 8, l0, np.where(g1 >= 8, l1, l0)); mx = np.where((g0 >= 8) & (g1 >= 8), np.fmax(l0, l1), inj)
        base = np.where(d.age.values >= 27, mx, inj)
        cg = np.nan_to_num(d.c_gp.values.astype(float)); rob = d.index.map(d.gsis.to_dict()).map(ROB).values.astype(float)
        cp = np.where(~np.isnan(rob) & ~np.isnan(d.c_ppg.values.astype(float)), rob, np.nan_to_num(d.c_ppg.values.astype(float)))
        with np.errstate(all="ignore"):
            rel = np.where((cg >= 3) & ~np.isnan(base) & (base > 0), np.clip(np.log(np.maximum(cp, 1) / base), -1, 1), 0.0)
        rel = np.where(rel < 0, rel * 0.25, rel) * np.clip(cg / 6, 0, 1) * np.clip((cp - 6) / 6, 0, 1)
        top = np.clip((np.log1p(top_hi) - Lb) / (np.log1p(top_hi) - np.log1p(top_lo)), 0, 1)
        out = beta * np.where(rel > 0, rel * top, rel)
        return out * np.where(d.pos.values == "TE", 0.5, 1.0)          # TE points swing less in value

    def prod_now(self, d, date, off):
        s_, n = weeks_done(date)
        if off: cols = [("n_ppg_l0", "n_gp_l0", s_), ("n_ppg_l1", "n_gp_l1", s_ - 1)]
        else: cols = [("c_ppg_raw", "c_gp_raw", s_), ("n_ppg_l0", "n_gp_l0", s_ - 1), ("n_ppg_l1", "n_gp_l1", s_ - 2)]
        num = np.zeros(len(d)); den = np.zeros(len(d))
        for pc, gc, y in cols:
            if y == s_ and not off: age = n / 2
            else:
                mid = KO.get(y, pd.Timestamp(f"{y}-09-08")) + pd.Timedelta(weeks=9)
                age = float(kp.nfl_weeks_between([mid], [date])[0])
            w = np.exp(-age / TAU); x = d[pc].values.astype(float); g = np.nan_to_num(d[gc].values.astype(float))
            if pc == "c_ppg_raw":
                rob = d.index.map(d.gsis.to_dict()).map(self._ROB).values.astype(float); x = np.where(~np.isnan(rob) & ~np.isnan(x), rob, x)
            ok = ~np.isnan(x) & (g > 0); num += np.where(ok, w * g * np.nan_to_num(x), 0); den += np.where(ok, w * g, 0)
        return np.where(den > 0, num / np.maximum(den, 1e-9), np.nan), den

    def cred_floor(self, d, date, off):
        eff, wg = self.prod_now(d, date, off)
        df = pd.DataFrame({"pos": d.pos.values, "now": np.where(wg >= 2, eff, np.nan)}, index=d.index)
        rk = df.groupby("pos").now.rank(ascending=False).values
        fl = np.where(np.isnan(rk), 0.0, np.interp(np.nan_to_num(rk, nan=99), TIER_R, TIER_V))
        fl = np.where(d.pos.values == "TE", fl * P["te_f"], fl)
        a0 = d.pos.map({k: v[0] for k, v in FADE.items()}).values.astype(float); a1 = d.pos.map({k: v[1] for k, v in FADE.items()}).values.astype(float)
        agef = 1 - (1 - P["age_min"]) * np.clip((d.age.values - a0) / (a1 - a0), 0, 1)
        return np.nan_to_num(fl * agef * np.clip(wg / 6, 0, 1))

    def final(self, d, date, off, recal, slotv, ROB):
        """final2 + final3 of the research run (prime term off; scale 1.0)"""
        self._ROB = ROB
        Lf = np.where((d.st.values == 2) & (d.Lf.values >= np.log1p(30)), d.Lf.values - 0.35, d.Lf.values)
        now = self.robust_now(d, ROB); elite_now = np.nan_to_num(now) >= d.pos.map(TOP5).values.astype(float)
        Lb = recal(Lf) + yqb_exp(d, -0.5) + oldqb(d, P["oldqb"]) + np.where(elite_now, 0.0, old_rb(d, P["oldrb"]))
        a0 = d.pos.map({k: v[0] for k, v in FADE.items()}).values.astype(float); a1 = d.pos.map({k: v[1] for k, v in FADE.items()}).values.astype(float)
        fade = 1 - np.clip((d.age.values - a0) / (a1 - a0), 0, 1); fade = np.where(elite_now, smax(fade, 0.5), fade)
        leg = self.legacy_t(d, P["h"], date); Lb = Lb + P["leg_cap"] * (1 - np.exp(-leg / P["kappa"])) * fade
        L = Lb + self.breakout(d, Lb, 1.3, P["top_lo"], P["top_hi"], ROB)
        slot = pd.Series(d.index.map(self.SLOT_OF.to_dict()), index=d.index); sv = slot.map(slotv.to_dict()).values.astype(float)
        dp = np.where(np.isnan(sv), np.nan_to_num(d.dprice.values.astype(float)), sv)
        LAST = np.expm1(d.a_y.values)
        dp = np.fmax(dp, np.where(d.st.values <= 1, P["last_w"] * np.nan_to_num(LAST), 0.0))
        lo, hi = np.where(d.pos.values == "TE", 3.0, 4.0), np.where(d.pos.values == "TE", 6.0, 9.0)
        cg = np.nan_to_num(d.c_gp.values.astype(float))
        prodf = np.where((cg < 3) | np.isnan(now), 1.0, np.clip((np.nan_to_num(now) - lo) / (hi - lo), 0, 1))
        young = (d.st.values <= 1) & (dp > 0)
        L = np.where(young, smax(L, np.log1p(P["young_floor"] * dp * prodf)), L)
        r0 = (d.st.values == 0) & (dp > 0); L = np.where(r0, (1 - P["rookie_w"]) * L + P["rookie_w"] * np.log1p(dp), L)
        L = L + 0.15 * np.clip((L - np.log1p(1200)) / (np.log1p(2000) - np.log1p(1200)), 0, 1)
        prod = np.where(cg >= 3, d.c_ppg.values.astype(float), d.n_ppg_l0.values.astype(float))
        hold = (d.age.values <= 26.5) & (d.st.values >= 2) & (np.nan_to_num(LAST) >= 2000) & (np.nan_to_num(prod) >= d.pos.map(TOP5).values.astype(float))
        L = np.where(hold, smax(L, np.log1p(LAST * P["hold"])), L)
        qb1 = (d.pos.values == "QB") & (d.d_rank.values == 1) & (d.injury.values == "")
        L = np.where(qb1, smax(L, np.log1p(50)), L)
        inj = d.injury.fillna("").astype(str).values; acl = d.bp.fillna("").astype(str).str.contains("ACL", regex=False).values
        mult = np.where(inj == "", 1.0, np.where(acl, 0.85, np.where(np.isin(inj, ["IR", "PUP"]), 0.95, 0.99)))
        L = np.log1p(np.expm1(L + np.log(mult)) * P["scale"]) - np.log(P["scale"]) if P["scale"] != 1.0 else L + np.log(mult)
        L = smax(L, np.log1p(self.cred_floor(d, date, off)))
        return np.expm1(L) * P["scale"]

    def formula_at(self, date, stats_date=None):
        date = pd.Timestamp(date); sd = pd.Timestamp(stats_date) if stats_date is not None else date
        d = self.frame_at(date, stats_date); rob = self.rob_at(sd); off = d.c_gp.notna().mean() < 0.03 * self.C_MAX
        v = pd.Series(self.final(d, sd, off, self.recal_at(self.snap_of(sd)), self.slotv_at(date), rob), index=d.index)
        # rookies: the draft slot's price x how they have played (3+ games); hurt before playing x0.8
        slot = d.index.map(lambda s: self.SLOT_OF.get(str(s))); sv = pd.Series(slot, index=d.index).map(self.slotv_at(date).to_dict()) * P["scale"]
        dy = d.dyear.fillna(0).astype(int).values
        end = pd.to_datetime([KO.get(y, pd.Timestamp(f"{max(y, 2000)}-09-08")) + pd.Timedelta(weeks=19) for y in dy]).values
        nxt = pd.to_datetime([self.DRAFT_DAY.get(y + 1, pd.Timestamp(f"{max(y, 2000) + 1}-07-15")) for y in dy]).values
        dt = np.datetime64(date)
        wr = np.clip((nxt - dt) / (nxt - end), 0, 1)
        wr = np.where(sv.notna().values & d.dprice.notna().values, wr, 0.0)
        cur = self.robust_now(d, rob); cg = d.c_gp.fillna(0).values; l0 = d.n_ppg_l0.values.astype(float); g0 = d.n_gp_l0.fillna(0).values
        rnow = np.where(cg >= 3, cur, np.where((g0 >= 3) & (dt > end - np.timedelta64(7, 'D')), l0, np.nan))
        f = np.where(~np.isnan(rnow), np.clip(1 + 0.06 * (rnow - d.pos.map(EXP).values), 0.75, 1.25), np.where(d.injury.values != "", 0.8, 1.0))
        rv = np.nan_to_num(sv.values * f, nan=1.0)
        v = pd.Series(np.exp((1 - wr) * np.log(np.maximum(v.values, 1)) + wr * np.log(np.maximum(rv, 1))), index=v.index)
        d["V_raw"] = v.values
        s_, n_ = weeks_done(sd)
        off_chart = (d.d_rank.values == 9) & (np.nan_to_num(d.d_stale.values.astype(float)) >= 28) & (d.injury.values == "")
        no_games = np.where(off or n_ == 0, np.nan_to_num(d.n_gp_l0.values.astype(float)) == 0, (n_ >= 3) & (np.nan_to_num(d.c_gp_raw.values.astype(float)) == 0))
        d["un_x"] = (off_chart & no_games).astype(float)       # no NFL team: off every chart, no games, not hurt
        return d

    def season_view_blend(self, date):
        date = pd.Timestamp(date); r = [x for x in self.ROLL if x <= date]
        if not r: return None, 1.0
        r = r[-1]; ko = min(k for k in KO.values() if k > r)
        if date >= ko: return None, 1.0
        return max(x for x in self.GRID if x < r), float((date - r) / (ko - r))

    def at(self, date):
        """V_raw (and the frame) on a date; through the offseason the end-of-season view blends into the new one"""
        ref, w = self.season_view_blend(date)
        d = self.formula_at(date)
        if ref is None: return d
        d0 = self.formula_at(date, ref)
        raw0 = d0.V_raw.reindex(d.index).fillna(d.V_raw)
        d["V_raw"] = np.exp((1 - w) * np.log(np.maximum(raw0, 1)) + w * np.log(np.maximum(d.V_raw, 1)))
        return d
