"""Inputs of the FAAB value base, built from the repo's own exports (no research artifacts):

  player_additions_sid   exports/player_additions.csv with a Sleeper id per row (name match, KTC-at-pickup tie-break)
  trades                 exports/trades.csv -> sides of assets (players by player_additions row, FAAB, picks)
  drops                  exports/add_drops.csv -> (sid, date) of every cut
  league_frame           the stats frame on each league transaction's date (kp.build + e_x features)
  ktc_panel              monthly KTC per player (dynasty-daddy history + the repo's KTC backfill and provenance),
                         the stats translator's training scale, with its stats frame
  grid_frame             every rostered player on the valuation grid: daily Sept 1 - Feb 15, Tuesdays otherwise,
                         plus every evidence date
  evidence               owned-player evidence for the holding-value map: trades and drafts, and the league chat's
                         valuations (data/faab_value/chat_evidence.csv: sid, date, log price, weight, kind; no names)
  pick_value             a pick's price on a date from the league's drafts held before it

Moved from the research scripts (obs / trades_parse / drops / feats / dense / wf_base2 / faab_wf) unchanged in logic.
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import faab_frame as kp

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "exports"
DATA = ROOT / "data" / "faab_value"
PICK = re.compile(r"^(\d{4}) (\d)(?:\.(\d\d))?")
FA = re.compile(r"\$(\d+(?:\.\d+)?) FAAB")


def _norm(s):
    s = str(s).lower().replace(".", "").replace("'", "").replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def player_additions_sid(exports=EXPORTS):
    """player_additions with the Sleeper id of each row's player (unique name match; ambiguous names resolved by the
    KTC value recorded at pickup)"""
    pa = pd.read_csv(exports / "player_additions.csv")
    pl = json.load(open(exports / "snapshot" / "sleeper_players_nfl.json"))
    by = {}
    for sid, p in pl.items():
        if p.get("position") in ("QB", "RB", "WR", "TE") or set(p.get("fantasy_positions") or []) & {"QB", "RB", "WR", "TE"}:
            n = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}"
            by.setdefault(_norm(n), []).append(sid)
    pv = pd.read_csv(exports / "raw" / "ktc_provenance.csv")
    pv = pv[pv.asset.astype(str).str.fullmatch(r"\d+")]; pv["asset"] = pv.asset.astype(str)
    pvg = {a: g.sort_values("target_date") for a, g in pv.groupby("asset")}

    def ktc_at(sid, d):
        g = pvg.get(sid)
        if g is None: return np.nan
        g = g[g.target_date <= d]
        return g.value.iloc[-1] if len(g) else np.nan
    sids = []
    for r in pa.itertuples():
        c = by.get(_norm(r.Player), [])
        if len(c) == 1: sids.append(c[0]); continue
        if not c: sids.append(None); continue
        k = getattr(r, "_" + str(list(pa.columns).index("KTC at pickup") + 1))
        sids.append(min(c, key=lambda s: abs((ktc_at(s, r.Date[:10]) if not np.isnan(ktc_at(s, r.Date[:10])) else 1e9) - (k if k == k else 0))))
    pa["sid"] = sids
    return pa


def trades(pa, exports=EXPORTS):
    """{trade date-time: {team: [(kind, x, label)]}}; kind faab (x = $), pick (label), player (x = player_additions row),
    startupplayer / unknown (sides the evidence leaves out)"""
    pa = pa.copy(); pa["d"] = pa.Date.astype(str).str[:10]
    t = pd.read_csv(exports / "trades.csv"); t["d"] = t.Date.astype(str).str[:10]
    out = {}
    for r in t.itertuples(index=False):
        side = []
        for a in str(r[4]).split("; "):          # the 5th column: assets received
            a = a.strip()
            if not a or a == "nan": continue
            mm = FA.search(a)
            if mm: side.append(("faab", float(mm.group(1)), None)); continue
            mm = PICK.match(a)
            if mm:
                if mm.group(1) == "2020" and r.d[:4] == "2020":
                    side.append(("startup", None, a)); continue
                side.append(("pick", None, a)); continue
            c = pa[(pa.Team == r.Team) & (pa.d == r.d) & (pa["Addition type"] == "Trade") & (pa.Player == a)]
            if len(c) == 0:
                c = pa[(pa.d == r.d) & (pa["Addition type"] == "Trade") & (pa.Player == a)]
            side.append(("player", c.index[0], a) if len(c) else ("unknown", None, a))
        out.setdefault(r.Date, {})[r.Team] = side
    return out


def drops(pa, exports=EXPORTS):
    ad = pd.read_csv(exports / "add_drops.csv", usecols=["Team", "Player Dropped", "Date"])
    ad = ad.dropna(subset=["Player Dropped"]); ad = ad[ad["Player Dropped"].astype(str).str.strip() != ""]
    ad["date"] = pd.to_datetime(ad.Date.astype(str).str[:10])
    nm = pa.dropna(subset=["sid"]).drop_duplicates("Player", keep="last").set_index("Player").sid.astype(str)
    ad["sid"] = ad["Player Dropped"].map(nm)
    return ad.dropna(subset=["sid"])[["sid", "date", "Player Dropped", "Team"]].rename(columns={"Player Dropped": "name"})


class Picks:
    """rookie-pick prices on a date: the median price of each slot over the league's drafts held before it"""

    def __init__(self, pa, exports=EXPORTS):
        pa = pa.copy(); pa["d"] = pd.to_datetime(pa.Date.astype(str).str[:10])
        dr = pa[pa["Addition type"] == "Draft"]
        self.draft_day = dr.groupby("Season").d.min(); self.draft_day.index = self.draft_day.index.astype(int)
        rp = pd.read_csv(exports / "rookie_picks.csv")
        rp = rp[rp.Number.astype(str).str.fullmatch(r"\d\.\d\d")].assign(Year=lambda x: x.Year.astype(str))
        self.m = rp.merge(dr[["Player", "Season", "sid", "Price paid (FAAB)"]].assign(Season=lambda x: x.Season.astype(str)),
                          left_on=["Player Picked", "Year"], right_on=["Player", "Season"], how="left")

    def slot_values(self, date):
        m = self.m.dropna(subset=["Price paid (FAAB)"]); held = m.Year.astype(int).map(lambda y: self.draft_day.get(y, pd.Timestamp(f"{y}-07-15")))
        return m[held.values < pd.Timestamp(date)].groupby("Number")["Price paid (FAAB)"].median()

    def value(self, label, d):
        """a pick's price on date d (the exact slot once the order is set, else its round's average; 5th+ = $20;
        5% off a year per draft further out)"""
        mm = PICK.match(str(label)); sv_ = self.slot_values(d)
        if mm is None or not len(sv_): return np.nan
        y, rn, sl = int(mm.group(1)), int(mm.group(2)), mm.group(3)
        rnd = sv_.groupby(sv_.index.str[0].astype(int)).mean()
        if rn >= 5: return 20.0
        nxt = d.year if d.month <= 8 else d.year + 1
        v = sv_.get(f"{rn}.{sl}", rnd.get(rn, np.nan)) if (sl and y == d.year and d.month <= 8) else rnd.get(rn, np.nan)
        return v * 0.95 ** max(0, y - nxt)


def league_frame(pa):
    """the stats frame on each priced league transaction's date (rowid = the player_additions row)"""
    obs = pd.DataFrame(dict(sid=pa.sid.astype(str), date=pd.to_datetime(pa.Date.astype(str).str[:10]), ktc=pa["KTC at pickup"],
                            rowid=pa.index, src="obs"))
    obs = obs[pa.sid.notna().values]
    F = kp.build(obs); F["date"] = F.date.astype("datetime64[ns]")
    return F


def ktc_panel(repo=ROOT):
    """monthly KTC per player (median of the month): dynasty-daddy's history wins where both exist"""
    D = repo / "data" / "ktc_cache"
    dirj = json.load(open(D / "directory.json"))
    n2s = {p["name_id"]: str(p["sleeper_id"]) for p in dirj if p.get("sleeper_id")}
    rows = []
    for f in glob.glob(str(D / "players" / "*.json")):
        sid = n2s.get(os.path.basename(f)[:-5])
        if not sid: continue
        try: hist = json.load(open(f))
        except Exception: continue
        for r in hist if isinstance(hist, list) else []:
            v = r.get("sf_trade_value")
            if v: rows.append((sid, r["date"][:10], float(v)))
    dd = pd.DataFrame(rows, columns=["sid", "date", "ktc"]); dd["date"] = pd.to_datetime(dd.date)
    dd["per"] = dd.date.dt.to_period("M")
    ddm = dd.groupby(["sid", "per"]).agg(ktc=("ktc", "median"), date=("date", "median")).reset_index()
    rep = kp.load_ktc("M")
    both = pd.concat([ddm.assign(src="dd"), rep.assign(src="repo")]).sort_values("src").drop_duplicates(["sid", "per"], keep="first")
    Fd = kp.build(both[["sid", "date", "ktc"]].assign(src="ktcM", rowid=-1)); Fd["date"] = Fd.date.astype("datetime64[ns]")
    return Fd


def grid_dates(start="2021-01-01", end=None):
    days = pd.date_range(start, end or pd.Timestamp.today().normalize(), freq="D")
    return days[((days.month >= 9) | (days.month == 1) | ((days.month == 2) & (days.day <= 15))) | (days.dayofweek == 1)]


def grid_frame(pa, extra, start="2021-01-01", end=None):
    """every player the league has rostered, on every grid date and every evidence date"""
    sids = sorted(set(pa.sid.dropna().astype(str)))
    G = pd.DataFrame([(s, d) for s in sids for d in grid_dates(start, end)], columns=["sid", "date"])
    G = pd.concat([G, extra[["sid", "date"]].assign(date=lambda x: pd.to_datetime(x.date))]).drop_duplicates().reset_index(drop=True)
    G = G[G.date >= start]
    F = kp.build(G.assign(ktc=np.nan)); F["date"] = F.date.astype("datetime64[ns]")
    return F[F.pos.isin(["QB", "RB", "WR", "TE"])]


def evidence(LR, chat=None):
    """owned-player evidence: the league's trades and drafts (from the league rows) + the chat's valuations"""
    t = LR[LR.ch.isin(["trade", "draft"])][["sid", "date", "y", "w", "ch"]].rename(columns={"ch": "typ"})
    c = pd.read_csv(DATA / "chat_evidence.csv", dtype={"sid": str}) if chat is None else chat
    c = c.assign(date=pd.to_datetime(c.date))
    return pd.concat([t.assign(src="txn"), c.assign(src="chat")], ignore_index=True).assign(sid=lambda x: x.sid.astype(str))
