"""Dated stats features for the FAAB value base (the e_x_* columns): weekly usage, efficiency and status, team
strength, competition, durability, finishes and track record, awards, pre-NFL profile and off-field status, each
counted only from when it was known.

  build_store()            cached downloads (lotg_support.faab_data) -> parquet feature store in .cache/faab/xf/
  load_store(); add_x(df)  attach e_x_* columns to any frame with gsis + date, as known on that date

Moved from the research scripts (xfeat / awards / xfinish / xjoin) with paths parameterised and the logic unchanged,
so the base reproduces. Committed inputs: data/suspensions.csv, data/faab_value/offfield_events.csv (retirements,
legal, left-the-team, dated) and data/faab_value/awards.csv (the parsed awards; used when the Wikipedia pages are not
cached, and rewritten by build_store when a fresh parse finds at least as many rows).
"""
from __future__ import annotations

import glob
import json
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from . import faab_data as D
from . import faab_frame as kp

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "faab_value"
XF_DIR = D.CACHE / "xf"
KO_ALL = {2016: "2016-09-08", 2017: "2017-09-07", 2018: "2018-09-06", 2019: "2019-09-05", 2020: "2020-09-10", 2021: "2021-09-09",
          2022: "2022-09-08", 2023: "2023-09-07", 2024: "2024-09-05", 2025: "2025-09-04", 2026: "2026-09-10", 2027: "2027-09-09"}
KO = {k: pd.Timestamp(v) for k, v in KO_ALL.items()}


# ------------------------------------------------------------------ weekly / team / static
def build_week(X, FC, OUT, years):
    """xf_week / xf_team / xf_bodyparts / xf_roster_first / xf_last_season / xf_games / xf_static in OUT"""
    YEARS = years
    KO = {k: v for k, v in KO_ALL.items()}
    P = pd.read_parquet(f"{X}/players.parquet")
    PFR2G = dict(zip(P.pfr_id, P.gsis_id)); ESPN2G = dict(zip(P.espn_id.astype(str), P.gsis_id))
    def key(d):
        """season / week as int, gsis as str, so every source joins"""
        d = d.copy()
        for c in ("season", "week"):
            if c in d: d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=[c for c in ("season", "week") if c in d])
        for c in ("season", "week"):
            if c in d: d[c] = d[c].astype(int)
        if "gsis" in d: d["gsis"] = d.gsis.astype(str)
        return d
    def rd(f):
        try: return pd.read_parquet(f"{X}/{f}.parquet")
        except Exception: return None

    # ---------------------------------------------------------------- weekly
    wk = []
    for y in YEARS:
        e = rd(f"ep_weekly_{y}")
        if e is None: continue
        e = e[e.week <= 18]
        g = e.groupby(["player_id", "season", "week"]).agg(
            xfp=("total_fantasy_points_exp", "sum"), fp=("total_fantasy_points", "sum"),
            tgt=("rec_attempt", "sum"), car=("rush_attempt", "sum"), att=("pass_attempt", "sum"), ay=("rec_air_yards", "sum"),
            rz=("rec_touchdown_exp", "sum"), team=("posteam", "first"),
            tgt_t=("rec_attempt_team", "first"), car_t=("rush_attempt_team", "first"), ay_t=("rec_air_yards_team", "first"),
            xfp_t=("total_fantasy_points_exp_team", "first"), recyd=("rec_yards_gained", "sum")).reset_index().rename(columns={"player_id": "gsis"})
        wk.append(g)
    W = pd.concat(wk, ignore_index=True)
    # snaps (pfr ids) -> offense / defense / special teams
    sn = []
    for y in YEARS:
        try: s = pd.read_csv(f"{FC}/snap_{y}.csv", low_memory=False)
        except FileNotFoundError: continue
        s = s[s.game_type == "REG"]; s["gsis"] = s.pfr_player_id.map(PFR2G)
        sn.append(s.groupby(["gsis", "season", "week"]).agg(off=("offense_snaps", "sum"), off_pct=("offense_pct", "max"), dfn=("defense_snaps", "sum"),
                                                              dfn_pct=("defense_pct", "max"), st_pct=("st_pct", "max")).reset_index())
    W = key(W).merge(key(pd.concat(sn)), on=["gsis", "season", "week"], how="outer")
    # routes: pass plays on the field (participation; time_to_throw present = dropback)
    rt = []
    for y in YEARS:
        pp = rd(f"pbp_participation_{y}")
        if pp is None: continue
        pp = pp[pp.time_to_throw.notna() & pp.offense_players.notna()]
        wkn = pp.nflverse_game_id.str.split("_").str[1].astype(int)
        ex = pp.assign(week=wkn, season=y).assign(p=pp.offense_players.str.split(";")).explode("p")
        rt.append(ex.groupby(["p", "season", "week"]).size().rename("routes").reset_index().rename(columns={"p": "gsis"}))
    if rt: W = key(W).merge(key(pd.concat(rt)), on=["gsis", "season", "week"], how="left")
    # NGS (weekly rows week >= 1)
    for f, cols in [("ngs_receiving", {"avg_separation": "sep", "avg_yac_above_expectation": "yacoe"}),
                    ("ngs_rushing", {"rush_yards_over_expected_per_att": "ryoe", "percent_attempts_gte_eight_defenders": "box8"}),
                    ("ngs_passing", {"completion_percentage_above_expectation": "cpoe", "aggressiveness": "aggr", "avg_time_to_throw": "ttt"})]:
        n = rd(f); n = n[(n.week >= 1) & (n.season_type == "REG")].rename(columns={"player_gsis_id": "gsis", **cols})
        W = key(W).merge(key(n[["gsis", "season", "week"] + list(cols.values())].drop_duplicates(["gsis", "season", "week"])), on=["gsis", "season", "week"], how="left")
    # PFR advanced
    adv = []
    for y in range(2018, 2027):
        parts = []
        for t, cols in [("rec", {"receiving_broken_tackles": "brk_rec", "receiving_drop": "drops"}),
                        ("rush", {"rushing_broken_tackles": "brk_rush", "rushing_yards_after_contact": "yaco", "carries": "car_pfr"}),
                        ("pass", {"passing_bad_throws": "bad", "times_pressured": "press"})]:
            a = rd(f"advstats_week_{t}_{y}")
            if a is None: continue
            a = a[a.game_type == "REG"].assign(gsis=lambda d: d.pfr_player_id.map(PFR2G)).rename(columns=cols)
            parts.append(a[["gsis", "season", "week"] + list(cols.values())].groupby(["gsis", "season", "week"]).sum().reset_index())
        if parts:
            m = parts[0]
            for q in parts[1:]: m = m.merge(q, on=["gsis", "season", "week"], how="outer")
            adv.append(m)
    W = key(W).merge(key(pd.concat(adv)), on=["gsis", "season", "week"], how="left")
    # roster status and injury reports
    ro, ij = [], []
    for y in YEARS:
        r = rd(f"roster_weekly_{y}")
        if r is not None:
            r = r[r.game_type == "REG"] if "game_type" in r else r
            ro.append(r[["gsis_id", "season", "week", "status", "team"]].rename(columns={"gsis_id": "gsis", "team": "r_team"}).drop_duplicates(["gsis", "season", "week"]))
        i = rd(f"injuries_{y}")
        if i is not None:
            i = i[i.game_type == "REG"]
            ij.append(i[["gsis_id", "season", "week", "report_status", "report_primary_injury"]].rename(columns={"gsis_id": "gsis"}).drop_duplicates(["gsis", "season", "week"]))
    W = key(W).merge(key(pd.concat(ro)), on=["gsis", "season", "week"], how="outer").merge(pd.concat(ij), on=["gsis", "season", "week"], how="left")
    W = W[W.gsis.notna() & (W.gsis != "nan") & (W.gsis != "None")]
    # big weeks (20+ PPR; 25+ for QBs) from the weekly stat files
    bw = []
    for y in YEARS:
        try: w = pd.read_csv(f"{FC}/wk_{y}.csv", low_memory=False, usecols=["player_id", "position", "season", "week", "season_type", "fantasy_points_ppr", "attempts", "sacks_suffered", "passing_epa", "rushing_epa", "receiving_epa", "passing_tds", "rushing_tds", "receiving_tds", "carries", "rushing_yards", "targets", "receptions", "passing_yards"])
        except FileNotFoundError: continue
        w = w[w.season_type == "REG"]
        thr = np.where(w.position == "QB", 25.0, 20.0)
        bw.append(w.assign(gsis=w.player_id, big=(w.fantasy_points_ppr >= thr).astype(float), good=(w.fantasy_points_ppr >= thr * 0.75).astype(float),
                           dropbacks=w.attempts.fillna(0) + w.sacks_suffered.fillna(0), pass_epa=w.passing_epa, skill_epa=w.rushing_epa.fillna(0) + w.receiving_epa.fillna(0),
                           ppr=w.fantasy_points_ppr, ppr2=w.fantasy_points_ppr ** 2, td_pts=6 * (w.rushing_tds.fillna(0) + w.receiving_tds.fillna(0)) + 4 * w.passing_tds.fillna(0),
                           rush_car=w.carries, rush_yds=w.rushing_yards, gl_tgt=w.targets, rec=w.receptions, pass_yds=w.passing_yards)
                  [["gsis", "season", "week", "big", "good", "dropbacks", "pass_epa", "skill_epa", "ppr", "ppr2", "td_pts", "rush_car", "rush_yds", "gl_tgt", "rec", "pass_yds"]])
    W = key(W).merge(key(pd.concat(bw)), on=["gsis", "season", "week"], how="left")
    W["played"] = (W.off.fillna(0) + W.dfn.fillna(0) > 0) | W.xfp.notna()
    W["inj_out"] = W.report_status.isin(["Out", "Doubtful"]) | W.status.isin(["RES", "PUP"])
    W["on_ir"] = W.status.isin(["RES", "PUP"])
    W["exempt"] = W.status.isin(["EXE"])                        # excused absence (personal leave / exempt list)
    W["no_team"] = W.status.isna() & ~W.played
    W["known"] = pd.to_datetime(W.season.map(KO)) + pd.to_timedelta(7 * (W.week - 1) + 5, unit="D")

    # season-to-date per player: sums and weighted means
    W = W.sort_values(["gsis", "season", "week"])
    SUMS = ["exempt", "ppr", "ppr2", "td_pts", "dropbacks", "pass_epa", "skill_epa", "big", "good", "xfp", "fp", "tgt", "car", "att", "ay", "rz", "tgt_t", "car_t", "ay_t", "xfp_t", "recyd", "off", "dfn", "routes",
            "brk_rec", "brk_rush", "drops", "yaco", "car_pfr", "bad", "press", "played", "inj_out", "on_ir", "no_team"]
    for c in SUMS:
        if c in W: W[c] = W[c].astype(float)
    g = W.groupby(["gsis", "season"])
    C = W[["gsis", "season", "week", "known"]].copy()
    for c in SUMS:   # running season totals, carried through weeks with no row from that source
        if c in W: C[c] = g[c].cumsum(); C[c] = C[c].groupby([W.gsis, W.season]).ffill()
    for c, wcol in [("sep", "tgt"), ("yacoe", "tgt"), ("ryoe", "car"), ("box8", "car"), ("cpoe", "att"), ("aggr", "att"), ("ttt", "att"),
                    ("off_pct", None), ("dfn_pct", None), ("st_pct", None)]:
        if c not in W: continue
        w = W[wcol].fillna(0) if wcol else W[c].notna().astype(float)
        num = (W[c].fillna(0) * w).groupby([W.gsis, W.season]).cumsum(); den = w.where(W[c].notna(), 0).groupby([W.gsis, W.season]).cumsum()
        C[c] = num / den.replace(0, np.nan)
    _ir = W.on_ir.fillna(0).astype(bool); _prev = _ir.groupby([W.gsis, W.season]).shift().fillna(False).astype(bool)
    C["ppr_max"] = W.ppr.fillna(0).groupby([W.gsis, W.season]).cummax()        # best single game so far this season
    C["ir_onsets"] = (_ir & ~_prev).astype(float).groupby([W.gsis, W.season]).cumsum()
    C["body_parts"] = W.groupby(["gsis", "season"]).report_primary_injury.transform(lambda s: s.where(W.loc[s.index, "inj_out"]).expanding().apply(lambda _: 0, raw=True)) if False else np.nan
    bp = W[W.inj_out.fillna(0).astype(bool) & W.report_primary_injury.notna()].groupby(["gsis", "season"]).report_primary_injury.nunique().rename("bp_season")
    C["weeks"] = C.week
    tm = W.dropna(subset=["team"]).drop_duplicates(["team", "season", "week"])[["team", "season", "week", "xfp_t"]].sort_values(["team", "season", "week"])
    tm["t_xfp_cum"] = tm.groupby(["team", "season"]).xfp_t.cumsum(); tm["t_games"] = tm.groupby(["team", "season"]).cumcount() + 1
    tm[["team", "season", "week", "t_xfp_cum", "t_games"]].to_parquet(f"{OUT}/xf_team.parquet")
    C["team"] = W.groupby(["gsis", "season"]).team.ffill().values
    pos_of = dict(zip(P.gsis_id.astype(str), P.position)); bd = dict(zip(P.gsis_id.astype(str), pd.to_datetime(P.birth_date, errors="coerce")))
    K = C[["gsis", "season", "week", "known", "team"]].copy(); K["off_pct"] = C.off_pct; K["pos"] = K.gsis.map(pos_of)
    K = K.dropna(subset=["team", "off_pct"]); K = K[K.pos.isin(["QB", "RB", "WR", "TE"])]
    K["r"] = K.groupby(["team", "season", "week", "pos"]).off_pct.rank(ascending=False, method="first")
    top = K[K.r <= 2].pivot_table(index=["team", "season", "week", "pos"], columns="r", values=["off_pct", "gsis"], aggfunc="first")
    top.columns = [f"{a}{int(b)}" for a, b in top.columns]; top = top.reset_index()
    K = K.merge(top, on=["team", "season", "week", "pos"], how="left")
    K["comp_gsis"] = np.where(K.gsis == K.gsis1, K.gsis2, K.gsis1); K["comp_share"] = np.where(K.gsis == K.gsis1, K.off_pct2, K.off_pct1)
    K["comp_age"] = (K.known - K.comp_gsis.map(bd)).dt.days / 365.25
    C = C.merge(K[["gsis", "season", "week", "comp_share", "comp_age"]], on=["gsis", "season", "week"], how="left")
    C.to_parquet(f"{OUT}/xf_week.parquet"); bp.reset_index().to_parquet(f"{OUT}/xf_bodyparts.parquet")
    gl_cols = [c for c in ["gsis", "season", "week", "known", "team", "ppr", "off_pct", "rush_car", "rush_yds", "gl_tgt", "rec", "pass_yds"] if c in W]
    W.loc[W.played.astype(bool), gl_cols].to_parquet(f"{OUT}/xf_gamelog.parquet")      # one row per game played (game_form)
    W.loc[W.inj_out.fillna(False).astype(bool), ["gsis", "season", "week", "known"]].to_parquet(f"{OUT}/xf_injweeks.parquet")   # weeks out / on IR (since_injury)
    print("weekly", C.shape, "players", C.gsis.nunique())

    # ---------------------------------------------------------------- roster presence: first week on any NFL roster each season, last season on one
    RP = []
    for y in YEARS:
        r = rd(f"roster_weekly_{y}")
        if r is None: continue
        r = r[(r.game_type == "REG") if "game_type" in r else slice(None)]
        r = r.sort_values("week"); g_ = r.groupby("gsis_id")
        RP.append(pd.DataFrame({"first_week": g_.week.min(), "first_team": g_.team.first(), "last_team": g_.team.last()}).reset_index().assign(season=y).rename(columns={"gsis_id": "gsis"}))
    RP = pd.concat(RP); RP.to_parquet(f"{OUT}/xf_roster_first.parquet")
    RW = []                                                                   # every REG week's team (rookie_backup_spend)
    for y in YEARS:
        r = rd(f"roster_weekly_{y}")
        if r is None: continue
        r = r[(r.game_type == "REG") if "game_type" in r else slice(None)]
        RW.append(r[["gsis_id", "season", "week", "team"] + [c for c in ("draft_club",) if c in r]].rename(columns={"gsis_id": "gsis"}))
    pd.concat(RW).dropna(subset=["gsis"]).astype({"gsis": str}).to_parquet(f"{OUT}/xf_roster_team.parquet")
    RP.groupby("gsis").season.max().rename("last_roster_season").reset_index().to_parquet(f"{OUT}/xf_last_season.parquet"); print("roster presence", RP.shape)

    # ---------------------------------------------------------------- team strength by date (schedules + betting lines)
    G = rd("games"); G = G[G.season >= 2015]
    G["gameday"] = pd.to_datetime(G.gameday)
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        sp = np.where(side == "home", -G.spread_line, G.spread_line)       # spread_line > 0 = home favoured
        rows.append(pd.DataFrame({"team": G[f"{side}_team"], "season": G.season, "game_type": G.game_type, "gameday": G.gameday,
                                  "pts": G[f"{side}_score"], "opp_pts": G[f"{opp}_score"], "implied": G.total_line / 2 - sp / 2 * (1 if side == "home" else 1),
                                  "coach": G[f"{side}_coach"] if f"{side}_coach" in G else None}))
    T = pd.concat(rows, ignore_index=True)
    T["implied"] = np.where(T.team.isin(G.home_team), T.implied, T.implied)
    T["win"] = (T.pts > T.opp_pts).astype(float).where(T.pts.notna())
    depth = {"WC": 1, "DIV": 2, "CON": 3, "SB": 4}
    T["depth"] = T.game_type.map(depth).fillna(0) + ((T.game_type == "SB") & (T.win == 1)).astype(float)
    T.to_parquet(f"{OUT}/xf_games.parquet"); print("team-games", T.shape)

    # ---------------------------------------------------------------- pre-NFL static
    cb = rd("combine"); dp = rd("draft_picks")
    st = P[["gsis_id", "birth_date", "college_name", "college_conference", "draft_year", "draft_pick", "espn_id", "pfr_id", "position"]].rename(columns={"gsis_id": "gsis"})
    cb = cb.assign(gsis=cb.pfr_id.map(PFR2G))
    def ht_in(h):
        try: a, b = str(h).split("-"); return int(a) * 12 + int(b)
        except Exception: return np.nan
    cb["ht_in"] = cb.ht.map(ht_in)
    cb["speed"] = cb.wt * 200 / cb.forty ** 4
    st = st.merge(cb.dropna(subset=["gsis"])[["gsis", "ht_in", "wt", "forty", "vertical", "broad_jump", "cone", "shuttle", "speed"]].drop_duplicates("gsis"), on="gsis", how="left")
    st = st.merge(dp.dropna(subset=["gsis_id"])[["gsis_id", "age"]].rename(columns={"gsis_id": "gsis", "age": "draft_age"}).drop_duplicates("gsis"), on="gsis", how="left")
    P5 = {"SEC", "Big Ten", "Big 12", "ACC", "Pac-12"}
    st["p5"] = st.college_conference.isin(P5).astype(float)
    # college usage (ESPN ids carry over from college to the NFL)
    us = pd.concat([pd.read_parquet(f) for f in glob.glob(f"{X}/cfb/usage_players_*.parquet")], ignore_index=True)
    us = us[us.player_id.notna()]                    # (a blank id matched whichever NFL player has a blank ESPN id)
    us["gsis"] = us.player_id.astype(str).map(ESPN2G); us = us.dropna(subset=["gsis"])
    # one row per player and season: his team's row, the one with the most opportunities (an all-star game is a row
    # of its own; picking between them by sort order changed past values whenever nflverse's player table changed)
    us = (us.assign(_o=us.opportunities.astype(float).fillna(-1), _t=us.touches.astype(float).fillna(-1), _p=us.pos_team.astype(str))
          .sort_values(["gsis", "season", "_o", "_t", "_p"], kind="mergesort").drop_duplicates(["gsis", "season"], keep="last")
          .drop(columns=["_o", "_t", "_p"]))
    us = us.merge(st[["gsis", "birth_date", "draft_year"]], on="gsis", how="left")
    us = us[us.season < us.draft_year.fillna(9999)]
    us["age_s"] = (pd.to_datetime(us.season.astype(str) + "-09-01") - pd.to_datetime(us.birth_date)).dt.days / 365.25
    us["share"] = us[["target_share", "touch_share"]].max(axis=1)
    last = us.sort_values(["gsis", "season"], kind="mergesort").groupby("gsis").tail(1).set_index("gsis")
    bo = us[us.share >= 0.20].sort_values(["gsis", "season"], kind="mergesort").groupby("gsis").head(1).set_index("gsis").age_s
    cu = pd.DataFrame({"c_last_tgt_share": last.target_share, "c_last_touch_share": last.touch_share, "c_last_epa_opp": last.epa_per_opportunity,
                       "c_max_share": us.groupby("gsis").share.max(), "c_breakout_age": bo, "c_seasons": us.groupby("gsis").season.nunique(),
                       "c_rz_share": last.rz_touches / last.team_touches.replace(0, np.nan)})
    st = st.merge(cu, left_on="gsis", right_index=True, how="left")
    st.to_parquet(f"{OUT}/xf_static.parquet"); print("static", st.shape, "with college usage", st.c_max_share.notna().sum(), "with combine", st.forty.notna().sum())


# ------------------------------------------------------------------ awards (Wikipedia)
def build_awards(X, OUT):
    """xf_awards.parquet: (gsis, season, award, known) from the cached Wikipedia wikitext"""
    P = pd.read_parquet(f"{X}/players.parquet")
    def norm(s):
        s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
        s = re.sub(r"\(.*?\)", "", s); s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s.lower())
        return re.sub(r"[^a-z]", "", s)
    P["k"] = P.display_name.map(norm)
    P["ck"] = P.college_name.fillna("").map(norm)
    BY = P.groupby("k")
    def wt(f):
        t = json.load(open(f))["parse"]["wikitext"]["*"]
        t = re.sub(r"\{\{sortname\|([^|}]+)\|([^|}]+)(?:\|[^}]*)?\}\}", lambda m: f"[[{m.group(1)} {m.group(2)}]]", t)   # {{sortname|First|Last}} -> [[First Last]]
        return re.sub(r"<ref[^>]*?/>|<ref.*?</ref>", "", t, flags=re.S)
    def links(txt): return [m.split("|")[-1] for m in re.findall(r"\[\[([^\]]+)\]\]", txt) if not m.startswith(("File:", "Image:"))]
    def match(name, season, college=None, pos=None):
        k = norm(name)
        if k not in BY.groups: return None
        c = BY.get_group(k)
        if college is not None:   # a college award goes to someone drafted 1-4 years later
            c = c[c.draft_year.between(season + 1, season + 4)]
            if norm(college) and len(c) > 1: c = c[c.ck.str.contains(norm(college)[:6])] if c.ck.str.contains(norm(college)[:6]).any() else c
            if not len(c): return None
        else:
            c = c[(c.rookie_season.fillna(0) <= season) & (c.last_season.fillna(9999) >= season)] if len(c) > 1 else c
        if pos is not None and len(c) > 1: c = c[c.position.isin(pos)] if c.position.isin(pos).any() else c
        return c.gsis_id.iloc[0] if len(c) == 1 or (len(c) > 1 and c.gsis_id.nunique() == 1) else (c.gsis_id.iloc[0] if len(c) else None)
    rows = []
    FANT = {"QB", "RB", "WR", "TE", "FB"}
    # All-Pro by season page
    for f in sorted(glob.glob(f"{X}/wiki/*_All-Pro_Team.json")):
        y = int(re.search(r"(\d{4})_All", f).group(1)); t = wt(f)
        for line in t.split("\n|-"):
            if not re.search(r"Quarterback|Running back|Wide receiver|Tight end", line): continue
            cells = line.split("\n|")
            for cell in cells[1:]:
                for chunk in re.split(r"<br\s*/?>", cell):
                    ls = links(chunk)
                    if not ls: continue
                    name = ls[0]; tag = re.search(r"\((AP[^)]*)\)", chunk)
                    if not tag: continue
                    tier = "allpro2" if "AP-2" in tag.group(1) else ("allpro1" if re.search(r"\bAP\b(?!-)", tag.group(1)) else None)
                    if tier:
                        g = match(name, y)
                        if g: rows.append((g, y, tier, f"{y + 1}-01-15"))
    # AP season awards and college awards: rows with a year then a player link
    AW = {"AP_NFL_Most_Valuable_Player": ("mvp", False), "AP_NFL_Offensive_Player_of_the_Year": ("opoy", False),
          "AP_NFL_Offensive_Rookie_of_the_Year": ("oroy", False), "AP_NFL_Comeback_Player_of_the_Year": ("cpoy", False),
          "List_of_Heisman_Trophy_winners": ("heisman", True), "Biletnikoff_Award": ("biletnikoff", True), "Doak_Walker_Award": ("doak_walker", True),
          "John_Mackey_Award": ("mackey", True), "Davey_O_Brien_Award": ("obrien", True), "Maxwell_Award": ("maxwell", True), "Walter_Camp_Award": ("walter_camp", True)}
    for page, (aw, college) in AW.items():
        try: t = wt(f"{X}/wiki/{page}.json")
        except Exception: continue
        for line in t.split("\n|-"):
            ym = re.search(r"\b(20[01]\d|202[0-6])\b", line)
            if not ym: continue
            y = int(ym.group(1))
            if y < 2010: continue
            ls = [l for l in links(line[ym.end():]) if not re.search(r"season|football|NFL|team|College|University|\d{4}", l)]
            if not ls: continue
            g = match(ls[0], y, college=(ls[1] if college and len(ls) > 1 else ("" if college else None)))
            if g:
                rows.append((g, y, aw, f"{y}-12-15" if college else f"{y + 1}-02-10"))
                if aw == "heisman" and re.search(r"\]\]\s*/\s*\[\[", line): rows.append((g, y, "multi_position", f"{y}-12-15"))   # e.g. CB/WR
    # Heisman finalists from season pages (where they exist)
    for f in sorted(glob.glob(f"{X}/wiki/*_Heisman_Trophy.json")):
        try: t = wt(f)
        except Exception: continue
        y = int(re.search(r"(\d{4})_Heis", f).group(1))
        for line in t.split("\n|-")[:12]:
            ls = [l for l in links(line) if not re.search(r"season|football|team|College|University|\d{4}", l)]
            if ls:
                g = match(ls[0], y, college="")
                if g: rows.append((g, y, "heisman_finalist", f"{y}-12-15"))
    A = pd.DataFrame(rows, columns=["gsis", "season", "award", "known"]).drop_duplicates(["gsis", "season", "award"])
    A.to_parquet(f"{OUT}/xf_awards.parquet")
    return A


# ------------------------------------------------------------------ finishes
def build_finish(FC, OUT, last):
    """xf_finish.parquet: finishes and track record known after each completed season, through last"""
    s = []
    for y in range(2014, last + 1):
        try: d = pd.read_csv(f"{FC}/sp_{y}.csv", low_memory=False, usecols=["player_id", "position", "season", "games", "fantasy_points_ppr"])
        except FileNotFoundError: continue
        s.append(d[d.position.isin(["QB", "RB", "WR", "TE"])])
    S = pd.concat(s).groupby(["player_id", "season", "position"], as_index=False).sum()
    S["ppg"] = S.fantasy_points_ppr / S.games.replace(0, np.nan)
    S = S[S.games >= 8].copy(); S["rank"] = S.groupby(["season", "position"]).ppg.rank(ascending=False)
    rows = []
    for g, d in S.groupby("player_id"):
        d = d.set_index("season").sort_index()
        for y in range(int(d.index.min()), last + 1):
            rk = {yy: d["rank"].get(yy, np.nan) for yy in range(y - 9, y + 1)}
            def streak(k):
                n = 0
                for yy in range(y, y - 10, -1):
                    if rk.get(yy, np.nan) <= k: n += 1
                    else: break
                return n
            pos = d.position.iloc[0]; start = {"QB": 16, "RB": 24, "WR": 30, "TE": 12}.get(pos, 24)
            rows.append((g, y, streak(2), streak(5), streak(12), sum(rk.get(yy, 99) <= 12 for yy in range(y - 5, y + 1)), sum(rk.get(yy, 99) <= 5 for yy in range(y - 5, y + 1)),
                         sum(rk.get(yy, 99) <= start for yy in range(y - 2, y + 1))))
    F = pd.DataFrame(rows, columns=["gsis", "season", "streak2", "streak5", "streak12", "top12_6y", "top5_6y", "starter_3y"])
    F.to_parquet(f"{OUT}/xf_finish.parquet")
    return F


# ------------------------------------------------------------------ as known on a date (xjoin)
def load_store(XF=None):
    """read the feature store built by build_store() into this module (add_x reads it)"""
    global C, FIN, BP, ST, TM, TMF, FN, GT, GT_SEAS, RF, RT, LS, SUSP, OFF, AW, GL, RW, IW
    XF = str(XF or XF_DIR)
    C = pd.read_parquet(f"{XF}/xf_week.parquet"); C["known"] = pd.to_datetime(C.known); C["gsis"] = C.gsis.astype(str)
    FIN = C.sort_values("week").groupby(["gsis", "season"]).tail(1).set_index(["gsis", "season"])     # each season's final state
    BP = pd.read_parquet(f"{XF}/xf_bodyparts.parquet").set_index(["gsis", "season"]).bp_season
    ST = pd.read_parquet(f"{XF}/xf_static.parquet"); ST["gsis"] = ST.gsis.astype(str); ST = ST.drop_duplicates("gsis").set_index("gsis")
    TM = pd.read_parquet(f"{XF}/xf_team.parquet"); TM["known"] = TM.season.map(KO) + pd.to_timedelta(7 * (TM.week - 1) + 5, unit="D")
    TMF = TM.sort_values("week").groupby(["team", "season"]).tail(1).set_index(["team", "season"])
    FN = pd.read_parquet(f"{XF}/xf_finish.parquet"); FN["gsis"] = FN.gsis.astype(str); FN = FN.set_index(["gsis", "season"])
    GT = pd.read_parquet(f"{XF}/xf_games.parquet"); GT["gameday"] = pd.to_datetime(GT.gameday)
    GT_SEAS = GT.groupby(["team", "season"]).agg(win_pct=("win", "mean"), depth=("depth", "max"), implied=("implied", "mean"))
    RF = pd.read_parquet(f"{XF}/xf_roster_first.parquet"); RF["gsis"] = RF.gsis.astype(str); RF = RF.set_index(["gsis", "season"])
    RT = RF[[c for c in ("first_team", "last_team") if c in RF]]; RF = RF.first_week
    LS = pd.read_parquet(f"{XF}/xf_last_season.parquet"); LS["gsis"] = LS.gsis.astype(str); LS = LS.set_index("gsis").last_roster_season
    RW = pd.read_parquet(f"{XF}/xf_roster_team.parquet") if Path(f"{XF}/xf_roster_team.parquet").exists() else None
    GL = pd.read_parquet(f"{XF}/xf_gamelog.parquet") if Path(f"{XF}/xf_gamelog.parquet").exists() else None
    if GL is not None: GL["gsis"] = GL.gsis.astype(str); GL["known"] = pd.to_datetime(GL.known)
    IW = pd.read_parquet(f"{XF}/xf_injweeks.parquet") if Path(f"{XF}/xf_injweeks.parquet").exists() else None
    if IW is not None: IW["gsis"] = IW.gsis.astype(str); IW["known"] = pd.to_datetime(IW.known)
    SUSP = pd.read_csv(ROOT / "data" / "suspensions.csv")
    OFF = pd.read_csv(DATA / "offfield_events.csv", parse_dates=["start", "end"])
    AW = (pd.read_parquet(f"{XF}/xf_awards.parquet") if Path(f"{XF}/xf_awards.parquet").exists() else pd.read_csv(DATA / "awards.csv")); AW["known"] = pd.to_datetime(AW.known); AW["gsis"] = AW.gsis.astype(str)


def _rates(s):
    """derived per-game / share / rate stats from a frame of season totals and means"""
    pl = s.played.replace(0, np.nan); out = {}
    mx = s.ppr_max.fillna(0) if "ppr_max" in s else 0.0
    xs = np.maximum(mx - s.ppr / pl, 0).fillna(0)      # how far the best game sits above the player's own average
    fp_r = s.fp - 0.5 * xs                             # ... counted at half (one game can't carry a season; no bias for the rest)
    out["xfp_pg"] = s.xfp / pl; out["fpoe_pg"] = (fp_r - s.xfp) / pl
    out["tgt_share"] = s.tgt / s.tgt_t.replace(0, np.nan); out["ay_share"] = s.ay / s.ay_t.replace(0, np.nan)
    out["car_share"] = s.car / s.car_t.replace(0, np.nan); out["xfp_share"] = s.xfp / s.xfp_t.replace(0, np.nan)
    out["wopr"] = 1.5 * out["tgt_share"] + 0.7 * out["ay_share"]
    out["routes_pg"] = s.routes / pl; out["yprr"] = s.recyd / s.routes.replace(0, np.nan); out["tprr"] = s.tgt / s.routes.replace(0, np.nan)
    out["off_pct"] = s.off_pct; out["dfn_pct"] = s.dfn_pct; out["st_pct"] = s.st_pct
    out["def_share"] = s.dfn / (s.off.fillna(0) + s.dfn.fillna(0)).replace(0, np.nan)
    for c in ["sep", "yacoe", "ryoe", "box8", "cpoe", "aggr", "ttt"]: out[c] = s[c]
    touches = (s.tgt.fillna(0) + s.car.fillna(0)).replace(0, np.nan)
    out["brk_rate"] = (s.brk_rec.fillna(0) + s.brk_rush.fillna(0)) / touches
    out["drop_rate"] = s.drops / s.tgt.replace(0, np.nan); out["yaco_att"] = s.yaco / s.car_pfr.replace(0, np.nan)
    out["bad_rate"] = s.bad / s.att.replace(0, np.nan); out["press_rate"] = s.press / s.att.replace(0, np.nan)
    out["games"] = s.played
    out["fpoe_touch"] = (fp_r - s.xfp) / (s.tgt.fillna(0) + s.car.fillna(0)).replace(0, np.nan)   # efficiency: points over expected per touch
    n_ = s.played.where(s.played >= 3); ppr_r = s.ppr - 0.5 * xs; mu = ppr_r / n_
    out["ppr_cv"] = np.sqrt(np.maximum((s.ppr2 - mx ** 2 + (mx - 0.5 * xs) ** 2) / n_ - mu ** 2, 0)) / mu.where(mu > 2)
    out["top_game_share"] = mx / s.ppr.where((s.ppr > 20) & (s.played >= 3))      # share of the season's points from its best game      # week-to-week volatility (low lows)
    out["td_share"] = s.td_pts / s.ppr.where(s.ppr > 20)                                   # share of fantasy points from touchdowns
    out["epa_db"] = s.pass_epa / s.dropbacks.where(s.dropbacks >= 50)         # passing EPA per dropback (QB quality)
    out["skill_epa_pg"] = s.skill_epa / pl
    out["big"] = s.big; out["good"] = s.good; out["big_rate"] = s.big / pl; out["good_rate"] = s.good / pl
    return pd.DataFrame(out, index=s.index)

def rostered_recent(date_v, fw_l0, fw_cur, ko_cur, in_season):
    """1 when the player has a team, whatever the depth charts say: in the season, on an NFL roster (any status:
    active, reserve/IR, suspended, practice squad) this season by the date; in the offseason, on one last season (a year
    on IR or suspended is not "no NFL team"). `fw_l0` / `fw_cur` are his first regular-season roster weeks of those
    seasons (NaN = not on one)."""
    date_v = np.asarray(date_v, dtype="datetime64[ns]"); fw_l0 = np.asarray(fw_l0, dtype=float); fw_cur = np.asarray(fw_cur, dtype=float)
    ko_cur = np.asarray(ko_cur, dtype="datetime64[ns]")
    on_cur = np.asarray(in_season, dtype=bool) & ~np.isnan(fw_cur) & (date_v >= ko_cur + ((np.nan_to_num(fw_cur) - 1) * 7 - 3).astype("timedelta64[D]"))
    return np.where(np.asarray(in_season, dtype=bool), on_cur, ~np.isnan(fw_l0)).astype(float)


DUD_PTS, FULL_SNAPS = 5.0, 0.5


def offseason_move(date_v, up_s, first_team_up, last_team_prev, no_cur_team=None):
    """1 from March 15 (free agency) until the upcoming season's kickoff when the player's Week-1 team differs from the
    last team he was on the season before (a signing or an offseason trade). The Week-1 roster stands in for the
    signing, the same small hindsight as the 'unsigned' flag; in season, e_x_new_team covers it. `no_cur_team` (True
    where e_x_new_team is not known yet: no game of his in the stats so far) keeps the flag on past kickoff, up to 5
    weeks, so the days between kickoff and his first game are not a gap."""
    date_v = np.asarray(date_v, dtype="datetime64[ns]")
    mar15 = pd.to_datetime([f"{int(y)}-03-15" for y in up_s]).values
    ko = np.array([KO.get(int(y), pd.Timestamp(f"{int(y)}-09-08")) for y in up_s], dtype="datetime64[ns]")
    a, b = pd.Series(first_team_up), pd.Series(last_team_prev)
    moved = (a.notna() & b.notna() & (a.astype(str) != b.astype(str))).values
    open_ = (date_v < ko) if no_cur_team is None else ((date_v < ko) | (np.asarray(no_cur_team, dtype=bool) & (date_v < ko + np.timedelta64(35, "D"))))
    return (moved & (date_v >= mar15) & open_).astype(float)


def coach_follow(up_s, first_team_up, last_team_prev, gt):
    """1 when the player changed teams for the upcoming season (Week-1 team differs from his last team the season
    before) and his new team's head coach in its first game is the coach his old team had in its last game (he
    followed his coach: Likely BAL -> NYG with John Harbaugh, 2026). `gt`: team games with season, gameday, coach."""
    up_s = np.asarray(up_s, dtype=int); a, b = pd.Series(first_team_up).astype(object), pd.Series(last_team_prev).astype(object)
    if gt is None or "coach" not in gt or gt.coach.isna().all(): return np.zeros(len(up_s))
    g = gt[gt.game_type == "REG"].dropna(subset=["coach"]).sort_values("gameday")
    first = g.groupby(["team", "season"]).coach.first(); last = g.groupby(["team", "season"]).coach.last()
    cf = first.reindex(pd.MultiIndex.from_arrays([a.values, up_s])).values
    cl = last.reindex(pd.MultiIndex.from_arrays([b.values, up_s - 1])).values
    moved = a.notna().values & b.notna().values & (a.astype(str).values != b.astype(str).values)
    return (moved & pd.notna(cf) & pd.notna(cl) & (cf.astype(str) == cl.astype(str))).astype(float)


ROOKIE_W1_MULT = 4.0      # a Week-1 waiver bid (100-dollar budget) counts 4x a rookie-draft dollar: Oliver, 2026-11-08


_TEAM_PREP: dict = {}


def _team_prep(roster):
    """team_on's roster tables (each week's team from when it is known, each season's first team), built once per
    roster frame: rookie_backup_spend calls team_on once per rookie, and the prep was ~0.5 s a call"""
    hit = _TEAM_PREP.get(id(roster))
    if hit is not None and hit[0] is roster:
        return hit[1]
    r = roster.dropna(subset=["gsis", "team"]).copy(); r["gsis"] = r.gsis.astype(str); r["season"] = r.season.astype(int)
    r["known"] = r.season.map(lambda y: KO.get(int(y), pd.Timestamp(f"{int(y)}-09-08"))) + pd.to_timedelta(7 * (r.week.astype(int) - 1) - 3, unit="D")
    r = r.sort_values(["season", "week"])
    first = r.groupby(["gsis", "season"]).team.first()
    out = (r.sort_values("known")[["gsis", "season", "known", "team"]], first)
    _TEAM_PREP.clear(); _TEAM_PREP[id(roster)] = (roster, out)
    return out


def team_on(gsis, dates, roster):
    """each player's NFL team on each date: the latest REG roster week known by then (a week's roster counts from 3 days
    before its kickoff week), else his first roster week that season (before kickoff: the small hindsight the move flags
    use). The season is the one whose rosters count from March 1. roster: gsis, season, week, team."""
    d = pd.DataFrame({"gsis": pd.Series(gsis).astype(str).values, "date": pd.to_datetime(pd.Series(dates)).values, "_i": np.arange(len(gsis))})
    d["s"] = np.where(d.date.dt.month >= 3, d.date.dt.year, d.date.dt.year - 1)
    rk, first = _team_prep(roster)
    m = kp.merge_asof(d.sort_values("date"), rk, left_on="date", right_on="known",
                      by="gsis", direction="backward").set_index("_i").sort_index()
    t = np.where(m.season.values == d.s.values, m.team.values, None)
    f = first.reindex(pd.MultiIndex.from_arrays([d.gsis.values, d.s.values])).values
    return np.where(pd.notna(t), t, f).astype(object)


BACKUP_USE = {"RB": ("rush_car", "gl_tgt", "off_pct"), "TE": ("gl_tgt", "off_pct"), "QB": ("off_pct",)}
BACKUP_FLOOR = {"rush_car": 2.0, "gl_tgt": 1.0, "off_pct": 0.1}      # a last-season figure under this per game is not compared


def rookie_backup_spend(rows, adds, info, roster, gl=None, w1_mult=ROOKIE_W1_MULT):
    """what the league spent on each player's same-team, same-position rookies of this season, by the date, and whether
    the player is keeping his own workload.
    rows: sid, gsis, date, pos. adds: the league's acquisitions (sid, date, type, price). info: sid, gsis, pos, dyear
    (rookie season). gl: one row per game played (gsis, season, known, rush_car, gl_tgt, off_pct).
    A rookie's spend = his largest price this season up to the date: a rookie-draft price, or a waiver bid (x w1_mult in the
    first 10 days of the season, x1 after). Trades and free-agent adds do not count. A rookie's own row is 0.
    Held = the player's own per-game carries, targets and snap share this season so far, each over his per-game figure
    last season (RB all three, TE targets + snaps, QB snaps; a last-season figure under BACKUP_FLOOR is skipped; each ratio
    capped at 1.5), averaged; NaN where no spend, no game yet this season, or nothing to compare. Returns (spend, held)."""
    rows = rows.reset_index(drop=True); out = np.zeros(len(rows)); nan = np.full(len(rows), np.nan)
    dt = pd.to_datetime(rows.date).values; di = pd.DatetimeIndex(dt); s_row = np.where(di.month >= 3, di.year, di.year - 1)
    a = adds[adds.type.isin(["Draft", "Waiver"])].copy(); a["sid"] = a.sid.astype(str); a["date"] = pd.to_datetime(a.date)
    inf = info.dropna(subset=["dyear"]).drop_duplicates("sid").assign(sid=lambda x: x.sid.astype(str)).set_index("sid")
    a = a[a.sid.isin(inf.index)]
    a["s"] = np.where(a.date.dt.month >= 3, a.date.dt.year, a.date.dt.year - 1)
    a = a[a.s.values == inf.dyear.reindex(a.sid).values.astype(float)]          # acquired in his rookie season
    if not len(a): return out, nan
    ko = a.s.map(lambda y: KO.get(int(y), pd.Timestamp(f"{int(y)}-09-08")))
    a["spend"] = np.where(a.type.eq("Waiver"), a.price.astype(float) * np.where(a.date < ko + pd.Timedelta(days=10), w1_mult, 1.0), a.price.astype(float))
    a = a[a.spend > 0]
    if not len(a): return out, nan
    gs_row = rows.gsis.astype(str).values
    team_row = team_on(gs_row, dt, roster)
    r_pos = rows.pos.values; r_sid = rows.sid.astype(str).to_numpy(dtype=object)
    parts = []
    by_sp = pd.DataFrame(dict(s=s_row, p=r_pos)).groupby(["s", "p"]).indices      # rows of each (season, position), ascending
    for (s, sid), g in a.groupby(["s", "sid"]):
        pos, gs = inf.pos.get(sid), inf.gsis.get(sid)
        if pos is None or pd.isna(gs): continue
        m = by_sp.get((s, pos), np.zeros(0, dtype=np.intp)); m = m[r_sid[m] != sid]
        if not len(m): continue
        g = g.sort_values("date"); got = np.maximum.accumulate(g.spend.values)
        k = np.searchsorted(g.date.values.astype("datetime64[ns]"), dt[m].astype("datetime64[ns]"), side="right")
        paid = np.where(k > 0, got[np.clip(k - 1, 0, None)], 0.0)
        ud, inv = np.unique(dt[m], return_inverse=True)        # the rookie's team is a function of the date: once per date
        parts.append((m, paid, str(gs), ud, inv.ravel()))
    if parts:            # every rookie's team on his dates in one team_on call (it is row by row), added in the same order
        tall = team_on(np.concatenate([np.full(len(p[3]), p[2]) for p in parts]), np.concatenate([p[3] for p in parts]), roster)
        at = 0
        for m, paid, _, ud, inv in parts:
            tr = tall[at:at + len(ud)][inv]; at += len(ud)
            out[m] += paid * ((tr == team_row[m]) & pd.notna(tr))
    held = nan.copy()
    if gl is None: return out, held
    gls = gl.assign(gsis=gl.gsis.astype(str)); gix = gls.groupby(["gsis", "season"]).indices
    G, GK = {}, {}

    ucols = sorted({c for v in BACKUP_USE.values() for c in v})

    def grp(key):        # each (player, season)'s games, sorted by when known: built when a row first reads it
        if key not in G:  # (known in that order, each usage column as float with blanks 0, the sorted known dates)
            ix = gix.get(key)
            if ix is None: G[key] = None
            else:
                g = gls.iloc[np.sort(ix)].sort_values("known"); kn = pd.to_datetime(g.known).values
                G[key] = (kn, {c: g[c].astype(float).fillna(0).to_numpy() for c in ucols}); GK[key] = np.sort(kn)
        return G[key]
    memo = {}            # a row reads his games known by the date: each (player, season, position, games known) once
    r_pos = np.asarray(rows.pos.values, dtype=object)
    for i in np.where(out > 0)[0]:
        pi = r_pos[i]; cols = BACKUP_USE.get(pi)
        if not cols: continue
        k1 = (gs_row[i], s_row[i]); g1, g0 = grp(k1), grp((gs_row[i], s_row[i] - 1))
        if g1 is None or g0 is None: continue
        mk = (gs_row[i], s_row[i], pi, int(np.searchsorted(GK[k1], dt[i], side="right")))
        if mk not in memo:
            keep = g1[0] <= dt[i]
            r_ = [min(float(np.nanmean(g1[1][c][keep])) / v0, 1.5) for c in cols
                  for v0 in [float(np.nanmean(g0[1][c]))] if v0 >= BACKUP_FLOOR[c]] if keep.any() else []
            memo[mk] = float(np.mean(r_)) if r_ else None
        if memo[mk] is not None: held[i] = memo[mk]
    return out, held


NFL_DRAFT = {2020: "2020-04-23", 2021: "2021-04-29", 2022: "2022-04-28", 2023: "2023-04-27", 2024: "2024-04-25", 2025: "2025-04-24", 2026: "2026-04-23"}


DEPARTED_PPG = {"QB": 16.0, "RB": 13.0, "WR": 13.0, "TE": 10.5}   # last-season PPR/game ~ a $200 base value (inputs, 2026-11-08)


def departed(dp, roster, gl, min_games=6):
    """(team, position, season) where a player left in the offseason who was worth replacing: on the team's roster in
    his last REG week of season-1, not on its roster in his first week of the season (another team, or none), and
    DEPARTED_PPG+ PPR per game over 6+ games in season-1. gl: one row per game played (gsis, season, ppr)."""
    r = roster.dropna(subset=["gsis", "team"]).assign(gsis=lambda x: x.gsis.astype(str)).sort_values(["season", "week"])
    last = r.groupby(["gsis", "season"]).team.last(); first = r.groupby(["gsis", "season"]).team.first()
    pos = dp.dropna(subset=["gsis_id"]).assign(gsis_id=lambda x: x.gsis_id.astype(str)).drop_duplicates("gsis_id").set_index("gsis_id").position
    g = gl.assign(gsis=gl.gsis.astype(str)).groupby(["gsis", "season"]).ppr.agg(["mean", "count"])
    out = set(); seasons = set(r.season.astype(int))
    for (gs, y), t in last.items():
        if y + 1 not in seasons: continue                                       # next season's rosters not out yet
        q = g.loc[(gs, y)] if (gs, y) in g.index else None
        ps = pos.get(gs)
        if q is None or q["count"] < min_games or ps not in DEPARTED_PPG or q["mean"] < DEPARTED_PPG[ps]: continue
        if first.get((gs, y + 1)) != t: out.add((t, ps, y + 1))
    return out


def nfl_draft_comp(rows, dp, roster, max_round=2, gone=None):
    """same-team, same-position rookies the NFL took in rounds 1-2 (max_round) this season (from the NFL draft to the end of the
    season, i.e. the season whose rosters count from March 1), counted per row. rows: sid, gsis, date, pos. dp: the
    dynastyprocess ids (gsis_id, position, draft_year, draft_round). roster: gsis, season, week, team, draft_club
    (nflverse weekly rosters; a rookie's team = his draft club, else his first roster team). A player's own row is 0.
    gone: departed()'s set; a rookie whose team lost a same-position player worth replacing that offseason replaced
    him, and does not count."""
    rows = rows.reset_index(drop=True); out = np.zeros(len(rows))
    dt = pd.to_datetime(rows.date).values; di = pd.DatetimeIndex(dt); s_row = np.where(di.month >= 3, di.year, di.year - 1)
    d = dp.dropna(subset=["gsis_id", "draft_year", "draft_round"]).copy()
    d = d[(d.draft_round.astype(float) >= 1) & (d.draft_round.astype(float) <= max_round) & d.position.isin(["QB", "RB", "WR", "TE"])]
    d["gsis_id"] = d.gsis_id.astype(str); d["draft_year"] = d.draft_year.astype(int)
    r = roster.dropna(subset=["gsis"]).assign(gsis=lambda x: x.gsis.astype(str))
    club = r.dropna(subset=["draft_club"]).groupby("gsis").draft_club.first() if "draft_club" in r else pd.Series(dtype=object)
    first = r.sort_values(["season", "week"]).groupby(["gsis", "season"]).team.first()
    team_row = team_on(rows.gsis.astype(str).values, dt, roster)
    gs_row = rows.gsis.astype(str).values
    for x in d.itertuples():
        t = club.get(x.gsis_id) if x.gsis_id in club.index else first.get((x.gsis_id, x.draft_year))
        nd = NFL_DRAFT.get(x.draft_year)
        if t is None or pd.isna(t) or nd is None or (gone and (t, x.position, x.draft_year) in gone): continue
        m = (s_row == x.draft_year) & (dt >= np.datetime64(pd.Timestamp(nd))) & (rows.pos.values == x.position) & (gs_row != x.gsis_id) & (team_row == t)
        out[m] += 1.0
    return out


def ypc_with_current(rows, gl):
    """yards per carry over the last two complete seasons AND this season's games known by the date (100+ carries
    between them); NaN otherwise. gl: one row per game played (gsis, season, known, rush_car, rush_yds)."""
    rows = rows.reset_index(drop=True); out = np.full(len(rows), np.nan)
    g = gl.dropna(subset=["rush_car"]).assign(gsis=lambda x: x.gsis.astype(str), known=lambda x: pd.to_datetime(x.known))
    # per player: his games' season, known date, carries and yards as arrays, in the frame's order (the order the
    # sums below have always added them in)
    se_, kw_ = g.season.values, g.known.values.astype("datetime64[ns]")
    car_, yds_ = g.rush_car.to_numpy(dtype=float), g.rush_yds.fillna(0).to_numpy(dtype=float)
    kn = {k: (se_[ix], kw_[ix], car_[ix], yds_[ix]) for k, ix in g.groupby("gsis").indices.items()}
    dt = pd.to_datetime(rows.date).values.astype("datetime64[ns]"); di = pd.DatetimeIndex(dt); s_row = np.where(di.month >= 3, di.year, di.year - 1)
    memo = {}            # the rows read depend only on (player, season, this season's games known): each once
    for i, (gs, y) in enumerate(zip(rows.gsis.astype(str).to_numpy(dtype=object), s_row)):
        v = kn.get(gs)
        if v is None: continue
        se, kw, car, yds = v
        mk = (gs, y, int(((se == y) & (kw <= dt[i])).sum()))
        r = memo.get(mk, memo)
        if r is memo:
            sel = (se >= y - 2) & (se <= y) & ((se < y) | (kw <= dt[i]))
            c = float(car[sel].sum())
            r = memo[mk] = float(yds[sel].sum()) / c if c >= 100 else None
        if r is not None: out[i] = r
    return out


def overtaken_by_rookie(rows, gl, roster, dp, min_games=8, own_min=4, gap=4.0):
    """last season (season-1), a same-team, same-position ROOKIE outscored the player: (rookie PPR/g - his PPR/g) /
    gap, capped at 1; 0 when no rookie did (rookie: 8+ games, his draft year = season-1, on the player's last team of
    season-1; the player: 4+ games). rows: gsis, date, pos. gl: one row per game (gsis, season, ppr). roster: gsis,
    season, week, team. dp: dynastyprocess ids (gsis_id, position, draft_year)."""
    rows = rows.reset_index(drop=True); out = np.zeros(len(rows))
    di = pd.DatetimeIndex(pd.to_datetime(rows.date).values); s_row = np.where(di.month >= 3, di.year, di.year - 1)
    g = gl.assign(gsis=gl.gsis.astype(str)).groupby(["gsis", "season"]).ppr.agg(["mean", "count"])
    r = roster.dropna(subset=["gsis", "team"]).assign(gsis=lambda x: x.gsis.astype(str)).sort_values(["season", "week"])
    last = r.groupby(["gsis", "season"]).team.last()
    d = dp.dropna(subset=["gsis_id", "draft_year"]).assign(gsis_id=lambda x: x.gsis_id.astype(str)).drop_duplicates("gsis_id")
    best = {}                                                   # (team, pos, season) -> the best rookie's PPR/g
    for x in d.itertuples():
        y = int(x.draft_year); q = g.loc[(x.gsis_id, y)] if (x.gsis_id, y) in g.index else None
        t = last.get((x.gsis_id, y))
        if q is None or q["count"] < min_games or t is None: continue
        k = (t, x.position, y); best[k] = max(best.get(k, 0.0), float(q["mean"]))
    memo = {}            # a row reads only (player, season, position): each once
    gsv, posv = rows.gsis.to_numpy(dtype=object), rows.pos.to_numpy(dtype=object)      # numpy: no per-row column lookups
    for i in range(len(rows)):
        gs, y = str(gsv[i]), int(s_row[i]) - 1
        mk = (gs, y, posv[i]); r = memo.get(mk, memo)
        if r is memo:
            r = None
            q = g.loc[(gs, y)] if (gs, y) in g.index else None
            t = last.get((gs, y))
            if not (q is None or q["count"] < own_min or t is None):
                b = best.get((t, posv[i], y), 0.0)
                if not (d.draft_year[d.gsis_id == gs] == y).any():                 # not a rookie himself
                    r = float(np.clip((b - q["mean"]) / gap, 0, 1))
            memo[mk] = r
        if r is not None: out[i] = r
    return out


def te_top3(rows, gl, pos=None, top=3):
    """a TE who finished a season in the top `top` TEs by total PPR: 1 for last season (season-1), 0.5 for the one
    before, else 0 (the larger). rows: gsis, date, pos. gl: one row per game (gsis, season, ppr, and position unless
    `pos`, a gsis -> position map, is given)."""
    rows = rows.reset_index(drop=True); out = np.zeros(len(rows))
    g = gl.assign(gsis=gl.gsis.astype(str))
    te = g.gsis.map(pos).eq("TE") if pos is not None else g.position.eq("TE")
    t = g[te.values].groupby(["season", "gsis"]).ppr.sum().reset_index()
    t["rk"] = t.groupby("season").ppr.rank(ascending=False, method="first")
    best = {(g, int(y)) for g, y, r in zip(t.gsis, t.season, t.rk) if r <= top}
    di = pd.DatetimeIndex(pd.to_datetime(rows.date).values); s_row = np.where(di.month >= 3, di.year, di.year - 1)
    for i in np.where(rows.pos.values == "TE")[0]:
        g, y = str(rows.gsis.values[i]), int(s_row[i])
        out[i] = 1.0 if (g, y - 1) in best else (0.5 if (g, y - 2) in best else 0.0)
    return out


TE_BIG, TE_MID = 11.0, 10.0      # PPR per game: a TE's big season / a mid-or-worse one (8+ games)


def te_one_off(rows, gl, roster, min_games=8):
    """a TE whose last season (season-1) was his one big year (TE_BIG+ PPR a game) on a team he had just joined, after
    mid-or-worse seasons (under TE_MID, 8+ games) in the five before it: (count - 1) / 2, capped at 1 (3+ = full), else
    0. rows: gsis, date, pos. gl: one row per game played (gsis, season, ppr). roster: gsis, season, week, team."""
    rows = rows.reset_index(drop=True); out = np.zeros(len(rows))
    di = pd.DatetimeIndex(pd.to_datetime(rows.date).values); s_row = np.where(di.month >= 3, di.year, di.year - 1)
    g = gl.assign(gsis=gl.gsis.astype(str)).groupby(["gsis", "season"]).ppr.agg(["mean", "count"])
    r = roster.dropna(subset=["gsis", "team"]).assign(gsis=lambda x: x.gsis.astype(str)).sort_values(["season", "week"])
    first = r.groupby(["gsis", "season"]).team.first(); last = r.groupby(["gsis", "season"]).team.last()
    gsv = rows.gsis.values; memo = {}
    for i in np.where(rows.pos.values == "TE")[0]:      # a function of (player, season): each once
        gs, y = str(gsv[i]), int(s_row[i])
        if (gs, y) in memo: out[i] = memo[(gs, y)]; continue
        memo[(gs, y)] = 0.0
        b = g.loc[(gs, y - 1)] if (gs, y - 1) in g.index else None
        if b is None or b["count"] < min_games or b["mean"] < TE_BIG: continue
        t0, tp = first.get((gs, y - 1)), last.get((gs, y - 2))
        if t0 is None or tp is None or t0 == tp: continue
        n = sum(1 for k in range(2, 7) if (gs, y - k) in g.index and g.loc[(gs, y - k)]["count"] >= min_games and g.loc[(gs, y - k)]["mean"] < TE_MID)
        out[i] = memo[(gs, y)] = min(max((n - 1) / 2.0, 0.0), 1.0)
    return out


TOP_ADDS = 5      # the league's top N pre-Week-1 free-agent bids of a season are "top adds"


def league_undrafted(rows, adds):
    """for each row from the league's rookie draft to the end of that season (2021 on): 1 if the player was not taken in
    that draft, less credit for a pre-Week-1 free-agent bid (his largest bid from the draft to kickoff + 4 days, known by
    the row's date, over the season's TOP_ADDS-th largest such bid, $5 at least: a top add = 0); 0 if he was drafted;
    NaN before the draft or in 2020 (the startup). adds: sid, date, type, price (player_additions)."""
    rows = rows.reset_index(drop=True); out = np.full(len(rows), np.nan)
    dt = pd.to_datetime(rows.date).values; di = pd.DatetimeIndex(dt); s_row = np.where(di.month >= 3, di.year, di.year - 1)
    a = adds.assign(sid=adds.sid.astype(str), date=pd.to_datetime(adds.date)); a["s"] = np.where(a.date.dt.month >= 3, a.date.dt.year, a.date.dt.year - 1)
    sid = rows.sid.astype(str).values
    for y in sorted(set(s_row)):
        if y < 2021 or y not in KO: continue
        dr = a[(a.type == "Draft") & (a.s == y)]
        if not len(dr): continue
        d0 = dr.date.min(); got = set(dr.sid)
        fa = a[a.type.isin(["Waiver", "Free agency"]) & (a.date > d0) & (a.date <= KO[y] + pd.Timedelta(days=4))]
        px = fa.price.astype(float).fillna(0)
        cut = max(float(np.sort(px.values)[::-1][TOP_ADDS - 1]) if len(px) >= TOP_ADDS else 0.0, 5.0)
        m = np.where((s_row == y) & (dt >= np.datetime64(d0)))[0]
        fd = {k: np.sort(v.date.values) for k, v in fa.groupby("sid")}; memo = {}
        fp = {k: v.price.astype(float).fillna(0).values[np.argsort(v.date.values, kind="stable")] for k, v in fa.groupby("sid")}
        for i in m:
            if sid[i] in got: out[i] = 0.0; continue
            t = fd.get(sid[i])
            mk = (sid[i], 0 if t is None else int(np.searchsorted(t, dt[i], side="right")))   # his bids known by the date
            if mk not in memo:        # his bids on or before the date: the first mk[1] by date
                memo[mk] = 1.0 - min(float(fp[sid[i]][:mk[1]].max()) / cut, 1.0) if mk[1] else 1.0
            out[i] = memo[mk]
    return out


def vet_deal_cap(rows, contracts):
    """the share of the salary cap (APY) of a veteran contract the player signed this season (the season whose rosters
    count from March 1), NaN if none: what the NFL market paid him. Rookie deals don't count; two signings in one season
    keep the bigger. rows: gsis, date. contracts: Over The Cap's history (lotg_support.contracts.load_contracts)."""
    c = contracts[contracts.gsis_id.notna()].copy()
    c = c[~(c.draft_year.notna() & (c.year_signed <= c.draft_year))]
    c = c.sort_values("apy_cap_pct").drop_duplicates(["gsis_id", "year_signed"], keep="last")
    m = {(str(g), int(y)): float(x) for g, y, x in zip(c.gsis_id, c.year_signed, c.apy_cap_pct) if pd.notna(y)}
    di = pd.DatetimeIndex(pd.to_datetime(rows.date).values); s = np.where(di.month >= 3, di.year, di.year - 1)
    return np.array([m.get((str(g), int(y)), np.nan) for g, y in zip(rows.gsis.values, s)])


def game_ceiling(rows, cache=None):
    """per row, from ffopportunity's weekly file (every NFL player's PPR by game, cached by faab_data): over the last two
    complete seasons and this one, games known by the date (game day + 1): g20_2y / g30_2y = games at 20+ / 30+ PPR,
    ng_2y = games, sd_streak_2y = the longest run of games under 10, sd_share_2y = share of games under 10; team_run =
    his team's (that of his last game) share of expected fantasy points from runs (rush / (rush + rec)) this season (4+
    games), else last season: a pass-first offense reads low; last_opp_ratio = his touches + targets in his last game this
    season over his average in the (up to) 3 games this season before it (2+ such games averaging 4+; an early exit or a
    benching reads near 0). rows: gsis, date. Returns {name: array}; NaN without data."""
    import glob
    cache = Path(cache or D.CACHE)
    N = len(rows); out = {k: np.full(N, np.nan) for k in ("g20_2y", "g30_2y", "ng_2y", "sd_streak_2y", "sd_share_2y", "team_run", "last_opp_ratio")}
    fs = sorted(glob.glob(str(cache / "ep_weekly_*.parquet"))); gp = cache / "games.parquet"
    if not fs or not gp.exists(): return out
    cols = ["season", "week", "game_id", "player_id", "posteam", "total_fantasy_points", "rush_fantasy_points_exp_team", "rec_fantasy_points_exp_team", "rush_attempt", "rec_attempt"]
    G = pd.concat([pd.read_parquet(f, columns=cols) for f in fs])
    G = G.merge(pd.read_parquet(gp, columns=["game_id", "gameday"]), on="game_id", how="left")
    G["known"] = pd.to_datetime(G.gameday) + pd.Timedelta(days=1)
    G = G.dropna(subset=["player_id", "known"]).sort_values(["player_id", "known"], kind="mergesort")
    G["opp"] = G.rush_attempt.fillna(0) + G.rec_attempt.fillna(0)
    by = {k: (v.known.values, v.season.values.astype(int), v.total_fantasy_points.to_numpy(dtype=float), v.posteam.values, v.opp.to_numpy(dtype=float)) for k, v in G.groupby("player_id")}
    T = G.drop_duplicates(["game_id", "posteam"]).sort_values("known", kind="mergesort")
    tb = {k: (v.known.values, v.season.values.astype(int), v.rush_fantasy_points_exp_team.to_numpy(dtype=float), v.rec_fantasy_points_exp_team.to_numpy(dtype=float)) for k, v in T.groupby("posteam")}
    d = pd.to_datetime(rows.date).values.astype("datetime64[ns]"); di = pd.DatetimeIndex(d); s = np.where(di.month >= 3, di.year, di.year - 1)
    for i, g in enumerate(rows.gsis.astype(str).values):
        t = by.get(g)
        if t is None: continue
        k = int(np.searchsorted(t[0], d[i], side="right")); w = t[1][:k] >= s[i] - 1
        if not w.any(): continue
        p = t[2][:k][w]; sd = p < 10
        out["g20_2y"][i] = (p >= 20).sum(); out["g30_2y"][i] = (p >= 30).sum(); out["ng_2y"][i] = len(p); out["sd_share_2y"][i] = sd.mean()
        best = cur = 0
        for x in sd:
            cur = cur + 1 if x else 0; best = max(best, cur)
        out["sd_streak_2y"][i] = best
        cs = np.where(t[1][:k] == s[i])[0]
        if len(cs) >= 3:
            pr = t[4][cs[-4:-1]]
            if pr.mean() >= 4: out["last_opp_ratio"][i] = t[4][cs[-1]] / pr.mean()
        u = tb.get(t[3][k - 1])
        if u is not None:
            kk = int(np.searchsorted(u[0], d[i], side="right")); ww = u[1][:kk] == s[i]
            if ww.sum() < 4: ww = u[1][:kk] == s[i] - 1
            if ww.any():
                ru, re_ = np.nansum(u[2][:kk][ww]), np.nansum(u[3][:kk][ww])
                out["team_run"][i] = ru / max(ru + re_, 1e-9)
    return {k: np.round(v, 5) for k, v in out.items()}


def qb_change_form(rows, cache=None):
    """per row: a receiver's PPR per game in games his team's usual QB did not start (the passer with the most attempts
    that game was not the one with the most attempts that season), and his PPR per game in the other games, over the
    last four complete seasons and this one, known by the date (game day + 1): (ppg_alt_qb, n_alt_qb, ppg_main_qb).
    Proven success through a QB change (Oliver 2026-11-22: Chase "when Burrow went down"). NaN without such games."""
    import glob
    cache = Path(cache or D.CACHE)
    N = len(rows); a_p, a_n, m_p = np.full(N, np.nan), np.full(N, np.nan), np.full(N, np.nan)
    fs = sorted(glob.glob(str(cache / "ep_weekly_*.parquet"))); gp = cache / "games.parquet"
    if not fs or not gp.exists(): return a_p, a_n, m_p
    G = pd.concat([pd.read_parquet(f, columns=["season", "game_id", "player_id", "posteam", "pass_attempt", "total_fantasy_points"]) for f in fs])
    G = G.merge(pd.read_parquet(gp, columns=["game_id", "gameday"]), on="game_id", how="left")
    G["known"] = pd.to_datetime(G.gameday) + pd.Timedelta(days=1); G = G.dropna(subset=["player_id", "known", "posteam"])
    pa = G.groupby(["posteam", "season", "player_id"]).pass_attempt.sum().reset_index().sort_values("pass_attempt", kind="mergesort")
    main = pa.drop_duplicates(["posteam", "season"], keep="last").set_index(["posteam", "season"]).player_id
    gs = G.sort_values("pass_attempt", kind="mergesort").drop_duplicates(["game_id", "posteam"], keep="last").set_index(["game_id", "posteam"]).player_id
    G["starter"] = [gs.get((g, t)) for g, t in zip(G.game_id, G.posteam)]
    G["alt"] = [st != main.get((t, y)) for st, t, y in zip(G.starter, G.posteam, G.season)]
    G = G.sort_values(["player_id", "known"], kind="mergesort")
    by = {k: (v.known.values, v.season.values.astype(int), v.total_fantasy_points.to_numpy(dtype=float), v.alt.values.astype(bool)) for k, v in G.groupby("player_id")}
    d = pd.to_datetime(rows.date).values.astype("datetime64[ns]"); di = pd.DatetimeIndex(d); s = np.where(di.month >= 3, di.year, di.year - 1)
    for i, g in enumerate(rows.gsis.astype(str).values):
        t = by.get(g)
        if t is None: continue
        k = int(np.searchsorted(t[0], d[i], side="right")); w = t[1][:k] >= s[i] - 4
        al = w & t[3][:k]; mn = w & ~t[3][:k]
        if al.any(): a_p[i] = t[2][:k][al].mean(); a_n[i] = al.sum()
        if mn.any(): m_p[i] = t[2][:k][mn].mean()
    return np.round(a_p, 5), a_n, np.round(m_p, 5)


def contract_left(rows, contracts):
    """seasons left on the player's latest NFL contract after this one (0 = its final season; the season whose rosters
    count from March 1), from the latest deal signed in or before that season; negative = his last deal has run out,
    NaN = no deal on record. rows: gsis, date. contracts: Over The Cap's history (lotg_support.contracts.load_contracts)."""
    c = contracts[contracts.gsis_id.notna() & contracts.year_signed.notna() & contracts.years.notna()]
    by = {str(k): v[["year_signed", "years"]].to_numpy(dtype=float) for k, v in c.groupby(c.gsis_id.astype(str))}
    di = pd.DatetimeIndex(pd.to_datetime(rows.date).values); s = np.where(di.month >= 3, di.year, di.year - 1)
    out = np.full(len(rows), np.nan)
    for i, (g, y) in enumerate(zip(rows.gsis.astype(str).values, s)):
        v = by.get(g)
        if v is None: continue
        v = v[v[:, 0] <= y]
        if len(v): ys, n = v[np.argmax(v[:, 0])]; out[i] = ys + n - 1 - y
    return out


def game_form(gl, gsis, date_v, l0_s, n=10):
    """Game-by-game form as known on each date. `gl`: one row per game played (gsis, season, known, ppr, off_pct).
    Returns a dict of arrays:
      duds_2y / full_2y: in the last two complete seasons (l0_s and l0_s - 1), games with a full role (50%+ of the
        offensive snaps, so not a game he left hurt or a backup's cameo) and, of those, games under 5 PPR (a dud);
      s15_4y / s16_4y / ppg_l0 / ppg_l1: complete seasons (8+ games) of the last four at 15+ / 16+ PPR per game, the
        last two seasons' PPG; ppg_cur / gp_cur: this season's PPR per game and games so far;
      ypc_2y: yards per carry over the last two complete seasons (100+ carries);
      max_2y: his best single game (PPR) known by the date in the last two complete seasons and this one;
      g15_3y: games at 15+ PPR in the last three complete seasons;
      form_last / form_prev: mean PPR of his last `n` games played by the date and of the `n` before (NaN when he has
        fewer than n / 2n games); they cross seasons, so a rookie who faded late carries that into year two."""
    gsis = np.asarray(gsis).astype(str); date_v = np.asarray(date_v, dtype="datetime64[ns]"); l0_s = np.asarray(l0_s, dtype=int)
    N = len(gsis); out = {k: np.full(N, np.nan) for k in ("duds_2y", "full_2y", "form_last", "form_prev", "s15_4y", "s16_4y", "ppg_l0", "ppg_l1", "ppg_cur", "gp_cur", "ypc_2y", "max_2y", "g15_3y")}
    if gl is None or not len(gl): return out
    g = gl.dropna(subset=["ppr"]).copy(); g["gsis"] = g.gsis.astype(str)
    full = g.off_pct.fillna(0).values >= FULL_SNAPS
    g["full"] = full.astype(float); g["dud"] = (full & (g.ppr.values < DUD_PTS)).astype(float)
    by_s = g.groupby(["gsis", "season"])[["full", "dud"]].sum()
    for k, c in (("full_2y", "full"), ("duds_2y", "dud")):
        a = by_s[c].reindex(pd.MultiIndex.from_arrays([gsis, l0_s])).fillna(0).values
        b = by_s[c].reindex(pd.MultiIndex.from_arrays([gsis, l0_s - 1])).fillna(0).values
        out[k] = a + b
    # big seasons: PPR per game in each complete season with 8+ games played; how many of the last four reached 15 / 16,
    # and last season's PPG (8+ games)
    ss = g.groupby(["gsis", "season"]).ppr.agg(["mean", "size"]); ppg = ss["mean"].where(ss["size"] >= 8)
    lk = [ppg.reindex(pd.MultiIndex.from_arrays([gsis, l0_s - k])).values for k in range(4)]
    out["s15_4y"] = sum(np.nan_to_num(x) >= 15 for x in lk).astype(float); out["s16_4y"] = sum(np.nan_to_num(x) >= 16 for x in lk).astype(float)
    out["ppg_l0"] = lk[0]; out["ppg_l1"] = lk[1]
    n15 = g.assign(g15=(g.ppr.values >= 15).astype(float)).groupby(["gsis", "season"]).g15.sum()
    out["g15_3y"] = sum(n15.reindex(pd.MultiIndex.from_arrays([gsis, l0_s - k])).fillna(0).values for k in range(3))
    # yards per carry over the last two complete seasons (100+ carries between them)
    if "rush_car" in g:
        rc = g.groupby(["gsis", "season"])[["rush_car", "rush_yds"]].sum()
        c2 = sum(rc.rush_car.reindex(pd.MultiIndex.from_arrays([gsis, l0_s - k])).fillna(0).values for k in range(2))
        y2 = sum(rc.rush_yds.reindex(pd.MultiIndex.from_arrays([gsis, l0_s - k])).fillna(0).values for k in range(2))
        out["ypc_2y"] = np.where(c2 >= 100, y2 / np.maximum(c2, 1), np.nan)
    g = g.sort_values(["gsis", "known"]); groups = {k: (v.known.values.astype("datetime64[ns]"), v.ppr.values.astype(float), v.season.values.astype(int)) for k, v in g.groupby("gsis")}
    memo = {}           # a row's values depend only on (player, games known by the date, last complete season)
    for i in range(N):
        t = groups.get(gsis[i])
        if t is None: continue
        k = int(np.searchsorted(t[0], date_v[i], side="right"))          # games known by the date
        key = (gsis[i], k, l0_s[i]); r = memo.get(key)
        if r is None:
            cs = np.r_[0.0, np.cumsum(t[1][:k])]
            fl = (cs[k] - cs[k - n]) / n if k >= n else None
            fp = (cs[k - n] - cs[k - 2 * n]) / n if k >= 2 * n else None
            cur = t[2][:k] == l0_s[i] + 1                                # this season's games so far (none in the offseason)
            gc = cur.sum(); pc = t[1][:k][cur].mean() if cur.any() else None
            rec = t[2][:k] >= l0_s[i] - 1                                # the last two complete seasons and this one
            mx = t[1][:k][rec].max() if rec.any() else None
            r = memo[key] = (fl, fp, gc, pc, mx)
        fl, fp, gc, pc, mx = r
        if fl is not None: out["form_last"][i] = fl
        if fp is not None: out["form_prev"][i] = fp
        out["gp_cur"][i] = gc
        if pc is not None: out["ppg_cur"][i] = pc
        if mx is not None: out["max_2y"][i] = mx
    return out


def since_injury(gl, iw, gsis, date_v):
    """(PPR per game, games) in the games he played after his last week out or on IR (an Out / Doubtful report, IR or
    PUP), both known by the date; NaN when no such week is known (a player with no injury on record). The week he was
    out is left out even if he played in it. `gl`: games played (gsis, season, week, known, ppr); `iw`: the weeks out
    (gsis, season, week, known)."""
    gsis = np.asarray(gsis).astype(str); date_v = np.asarray(date_v, dtype="datetime64[ns]"); N = len(gsis)
    ppg, gp = np.full(N, np.nan), np.full(N, np.nan)
    if gl is None or iw is None or not len(gl) or not len(iw): return ppg, gp
    g = gl.dropna(subset=["ppr"]).assign(gsis=lambda x: x.gsis.astype(str), k=lambda x: x.season.astype(int) * 100 + x.week.astype(int)).sort_values("known")
    w = iw.assign(gsis=lambda x: x.gsis.astype(str), k=lambda x: x.season.astype(int) * 100 + x.week.astype(int)).sort_values("known")
    G = {a: (v.known.values.astype("datetime64[ns]"), v.k.values, v.ppr.values.astype(float)) for a, v in g.groupby("gsis")}
    I_ = {a: (v.known.values.astype("datetime64[ns]"), np.maximum.accumulate(v.k.values)) for a, v in w.groupby("gsis")}
    memo = {}
    for i in range(N):
        t = I_.get(gsis[i])
        if t is None: continue
        j = int(np.searchsorted(t[0], date_v[i], side="right"))
        if j == 0: continue
        u = G.get(gsis[i])
        k = int(np.searchsorted(u[0], date_v[i], side="right")) if u is not None else -1
        key = (gsis[i], j, k); r = memo.get(key)       # depends only on the weeks out and games known by the date
        if r is None:
            last = t[1][j - 1]; ppg_, gp_ = np.nan, 0
            if u is not None:
                m = u[1][:k] > last
                gp_ = int(m.sum()); ppg_ = float(u[2][:k][m].mean()) if gp_ else np.nan
            r = memo[key] = (ppg_, gp_)
        ppg[i], gp[i] = r
    return ppg, gp


def _known_games(gl, gsis):
    """{gsis: that player's game-log rows sorted by when each game is known}"""
    g = gl.assign(gsis=gl.gsis.astype(str)).sort_values(["known", "season", "week"])
    return {a: v for a, v in g.groupby("gsis") if a in set(gsis)}


def _rows_of(keys, where=None):
    """{key: the row positions holding it, ascending} (over the rows where `where`, all by default)"""
    keys = np.asarray(keys, dtype=object); ix = np.arange(len(keys)) if where is None else np.where(where)[0]
    if not len(ix): return {}
    return {k: ix[v] for k, v in pd.Series(keys[ix]).groupby(keys[ix], sort=False).indices.items()}


def _n_known(known, dv):
    """for each date in dv, how many of `known` are on or before it: the set `known <= date` is the same for every date
    with the same count (NaT is never on or before a date), so a per-row result read off that set depends only on it"""
    return np.searchsorted(np.sort(np.asarray(known, dtype="datetime64[ns]")), dv, side="right")


def target_lead(rows, gl, min_games=4, share=0.18, horizon=17):
    """(weight, share) of the player's last week leading his team in season-to-date targets (at least `min_games` team
    games into a season, with `share`+ of the team's targets), known by the row's date: weight = 1 at that week, fading to
    0 over his next `horizon` games played (Oliver 2026-11-09: a target leader keeps a boost "extended over a large part of
    the following 17 games after the targets lead is lost"); NaN share / 0 weight when he never led. `gl`: games played
    with gsis, season, week, known, team, gl_tgt."""
    N = len(rows); w, sh = np.zeros(N), np.full(N, np.nan)
    if gl is None or "team" not in gl or not len(gl): return w, sh
    g = gl.dropna(subset=["team"]).assign(gsis=lambda x: x.gsis.astype(str), gl_tgt=lambda x: x.gl_tgt.fillna(0).astype(float))
    g = g.sort_values(["season", "week"])
    g["cum"] = g.groupby(["season", "team", "gsis"]).gl_tgt.cumsum()
    lead = []
    for (s, t), d in g.groupby(["season", "team"]):
        wk = np.sort(d.week.unique())
        piv = d.pivot_table(index="week", columns="gsis", values="gl_tgt", aggfunc="sum").reindex(wk).fillna(0).cumsum()
        tot = piv.sum(axis=1).values; ng = np.arange(1, len(wk) + 1)
        best = piv.values.max(axis=1); arg = piv.values.argmax(axis=1)
        second = np.sort(piv.values, axis=1)[:, -2] if piv.shape[1] > 1 else np.zeros(len(wk))
        for k in range(len(wk)):
            if ng[k] >= min_games and tot[k] > 0 and best[k] / tot[k] >= share and best[k] > second[k]:
                lead.append((piv.columns[arg[k]], s, wk[k], best[k] / tot[k]))
    if not lead: return w, sh
    L = pd.DataFrame(lead, columns=["gsis", "season", "week", "share"])
    kn = g.drop_duplicates(["gsis", "season", "week"]).set_index(["gsis", "season", "week"]).known
    L["known"] = kn.reindex(pd.MultiIndex.from_frame(L[["gsis", "season", "week"]])).values
    L = L.dropna(subset=["known"]).sort_values("known")
    LG = {a: v for a, v in L.groupby("gsis")}; GG = _known_games(g, set(L.gsis))
    # the same per-row arithmetic on arrays taken out of the frames once (the loop read them off pandas every row)
    LA = {a: (l.known.values.astype("datetime64[ns]"), l.season.values, l.week.values, l.share.values) for a, l in LG.items()}
    UA = {a: (u.known.values.astype("datetime64[ns]"), u.season.values, u.week.values) for a, u in GG.items()}
    gs = np.asarray(rows.gsis).astype(str); dv = np.asarray(rows.date, dtype="datetime64[ns]")
    for a, ix in _rows_of(gs, np.isin(gs, list(LA))).items():     # per player: a row's result is a function of (j, games known)
        l = LA[a]; uk, us, uw = UA[a]
        J = np.searchsorted(l[0], dv[ix], side="right"); K = _n_known(uk, dv[ix]); memo = {}
        for i, j, k in zip(ix, J, K):
            if j == 0: continue
            r = memo.get((j, k))
            if r is None:
                rs, rw = l[1][j - 1], l[2][j - 1]
                after = ((us > rs) | ((us == rs) & (uw > rw))) & (uk <= dv[i])
                r = memo[(j, k)] = max(0.0, 1.0 - after.sum() / horizon)
            w[i] = r; sh[i] = l[3][j - 1]
    return w, sh


def recent_max(rows, gl, n=3, min_off=0.5):
    """the best PPR game in the player's last `n` healthy games known by the date (a game on at least `min_off` of the
    offensive snaps; Oliver 2026-11-09: "within the last 3 healthy games ... had a game over 30")"""
    N = len(rows); out = np.full(N, np.nan)
    if gl is None or not len(gl): return out
    g = gl[gl.off_pct.fillna(0) >= min_off] if "off_pct" in gl else gl
    GG = _known_games(g.dropna(subset=["ppr"]), set(np.asarray(rows.gsis).astype(str)))
    GA = {a: (u.known.values.astype("datetime64[ns]"), u.ppr.values) for a, u in GG.items()}
    gs = np.asarray(rows.gsis).astype(str); dv = np.asarray(rows.date, dtype="datetime64[ns]")
    for a, ix in _rows_of(gs, np.isin(gs, list(GA))).items():
        u = GA[a]; K = np.searchsorted(u[0], dv[ix], side="right"); memo = {}
        for i, k in zip(ix, K):
            if k:
                r = memo.get(k)
                if r is None: r = memo[k] = float(u[1][max(0, k - n):k].max())
                out[i] = r
    return out


def touch_games(rows, gl, thr=20):
    """career games with more than `thr` touches (carries + receptions) known by the date (Oliver 2026-11-09: an RB with
    few such games has not carried a workhorse load yet)"""
    N = len(rows); out = np.zeros(N)
    if gl is None or not len(gl) or "rec" not in gl: return out
    g = gl.assign(t=gl.rush_car.fillna(0) + gl.rec.fillna(0))
    g = g[g.t > thr]
    GG = _known_games(g, set(np.asarray(rows.gsis).astype(str)))
    GA = {a: u.known.values.astype("datetime64[ns]") for a, u in GG.items()}
    gs = np.asarray(rows.gsis).astype(str); dv = np.asarray(rows.date, dtype="datetime64[ns]")
    for a, ix in _rows_of(gs, np.isin(gs, list(GA))).items():
        out[ix] = np.searchsorted(GA[a], dv[ix], side="right")
    return out


def season_ranks(gl, pos_of, pos):
    """{(gsis, season): rank} by total PPR among `pos` players in each complete regular season"""
    g = gl.assign(gsis=gl.gsis.astype(str)); g = g[g.gsis.map(pos_of) == pos]
    t = g.groupby(["season", "gsis"]).ppr.sum().reset_index()
    t["rk"] = t.groupby("season").ppr.rank(ascending=False, method="min")
    return t.set_index(["gsis", "season"]).rk


def te_slide(rows, gl, pos_of, l0_s, top=7, deep=20, recent=4, top_wk=5, recover=3):
    """(slide, recovered, was_top) for TEs: slide = 1 when his last two complete seasons both finished outside the top `top` TEs
    by total PPR, 2 when the last one was also outside the top `deep` (Oliver 2026-11-09); recovered = 1 when at least
    `recover` of his last `recent` games known by the date were top-`top_wk` TE weeks (his top-5 form back over several
    weeks), which lifts the fade; was_top = 1 when a season before those two finished in the top `top`"""
    N = len(rows); slide, rec, was = np.zeros(N), np.zeros(N), np.zeros(N)
    if gl is None or not len(gl): return slide, rec, was
    rk = season_ranks(gl, pos_of, "TE")
    gs = np.asarray(rows.gsis).astype(str); l0 = np.asarray(l0_s).astype(int)
    r0 = rk.reindex(pd.MultiIndex.from_arrays([gs, l0])).values; r1 = rk.reindex(pd.MultiIndex.from_arrays([gs, l0 - 1])).values
    out0 = np.nan_to_num(r0, nan=99) > top; out1 = np.nan_to_num(r1, nan=99) > top
    played = ~np.isnan(r0) | ~np.isnan(r1)
    slide = (out0 & out1 & played).astype(float) * (1 + (np.nan_to_num(r0, nan=99) > deep))
    best = rk[rk <= top].reset_index()
    wm = {}
    for i in np.where(slide > 0)[0]:
        k_ = (gs[i], l0[i])
        if k_ not in wm: wm[k_] = float(((best.gsis == gs[i]) & (best.season < l0[i] - 1)).any())
        was[i] = wm[k_]
    g = gl.assign(gsis=gl.gsis.astype(str)); g = g[g.gsis.map(pos_of) == "TE"].dropna(subset=["ppr"])
    g["wk_rk"] = g.groupby(["season", "week"]).ppr.rank(ascending=False, method="min")
    GG = _known_games(g, set(gs[slide > 0])); dv = np.asarray(rows.date, dtype="datetime64[ns]")
    GA = {a: (u.known.values.astype("datetime64[ns]"), u.wk_rk.values) for a, u in GG.items()}
    for i in np.where(slide > 0)[0]:
        u = GA.get(gs[i])
        if u is None: continue
        k = int(np.searchsorted(u[0], dv[i], side="right"))
        if k >= recover: rec[i] = float((u[1][max(0, k - recent):k] <= top_wk).sum() >= recover)
    return slide, rec, was


def qb_hurt_or_top(rows, gl, pos_of, l0_s, top=5, min_g=6, hurt_g=12):
    """consecutive complete seasons, back from the last one, in which a QB either finished top `top` in PPR per game
    (at least `min_g` games) or was hurt (played fewer than `hurt_g` games but some), counted only while at least one
    of them is a top finish and at least one a hurt season (Oliver 2026-11-09: Burrow, top 5 when healthy; a QB top 5
    every year is priced by that already)"""
    N = len(rows); out = np.zeros(N)
    if gl is None or not len(gl): return out
    g = gl.assign(gsis=gl.gsis.astype(str)); g = g[g.gsis.map(pos_of) == "QB"].dropna(subset=["ppr"])
    t = g.groupby(["season", "gsis"]).ppr.agg(["sum", "size"]).reset_index()
    t["ppg"] = t["sum"] / t["size"]
    t["rk"] = t.where(t["size"] >= min_g).groupby("season").ppg.rank(ascending=False, method="min")
    t["top"] = t.rk <= top; t["hurt"] = (t["size"] < hurt_g) & ~t.top
    T = {(a, int(b)): (bool(tp), bool(h)) for a, b, tp, h in zip(t.gsis, t.season, t.top, t.hurt)}
    gs = np.asarray(rows.gsis).astype(str); l0 = np.asarray(l0_s).astype(int); memo = {}
    for i in np.where(np.isin(gs, list({a for a, _ in T})))[0]:
        k = (gs[i], l0[i])
        if k not in memo:
            n = tops = hurts = 0; s = l0[i]
            while (gs[i], s) in T:
                tp, h = T[(gs[i], s)]
                if not (tp or h): break
                n += 1; tops += tp; hurts += h; s -= 1
            memo[k] = n if tops and hurts else 0
        out[i] = memo[k]
    return out


def big_games(rows, gl, min_off=0.5):
    """career games known by the date with at least `min_off` of the offensive snaps ("significant snaps")"""
    N = len(rows); out = np.zeros(N)
    if gl is None or not len(gl) or "off_pct" not in gl: return out
    GG = _known_games(gl[gl.off_pct.fillna(0) >= min_off], set(np.asarray(rows.gsis).astype(str)))
    GA = {a: u.known.values.astype("datetime64[ns]") for a, u in GG.items()}
    gs = np.asarray(rows.gsis).astype(str); dv = np.asarray(rows.date, dtype="datetime64[ns]")
    for a, ix in _rows_of(gs, np.isin(gs, list(GA))).items():
        out[ix] = np.searchsorted(GA[a], dv[ix], side="right")
    return out


def pass_ypg(rows, gl, cur_s, l0_s, in_season, min_g=4):
    """passing yards per game: this season's games known by the date once he has `min_g`, else the last complete
    season's (at least `min_g` games); NaN otherwise. `gl` needs pass_yds."""
    N = len(rows); out = np.full(N, np.nan)
    if gl is None or not len(gl) or "pass_yds" not in gl: return out
    g = gl.dropna(subset=["pass_yds"]).assign(gsis=lambda x: x.gsis.astype(str))
    GG = {a: v for a, v in g.groupby("gsis")}
    gs = np.asarray(rows.gsis).astype(str); dv = np.asarray(rows.date, dtype="datetime64[ns]")
    cur_s = np.asarray(cur_s); l0_s = np.asarray(l0_s); ins = np.asarray(in_season, dtype=bool)
    GA = {a: (v.season.values, v.known.values.astype("datetime64[ns]"), v.pass_yds.values.astype(float)) for a, v in GG.items()}
    memo = {}            # a row reads this season's games known by the date or last season's: each combination once
    NK = np.zeros(N, dtype=np.int64)                 # (the set of games known by the date: by how many are)
    for a, ix in _rows_of(gs, (np.asarray(rows.pos) == "QB") & np.isin(gs, list(GA))).items():
        NK[ix] = _n_known(GA[a][1], dv[ix])
    for i in np.where(np.asarray(rows.pos) == "QB")[0]:
        v = GG.get(gs[i])
        if v is None: continue
        mk = (gs[i], bool(ins[i]), cur_s[i], l0_s[i], int(NK[i]) if ins[i] else -1)
        r = memo.get(mk, memo)
        if r is memo:     # (whole yards: the sum is exact in any order)
            se, kn, py = GA[gs[i]]
            c = ((se == cur_s[i]) & (kn <= dv[i])) if ins[i] else np.zeros(len(se), dtype=bool)
            u = c if c.sum() >= min_g else (se == l0_s[i]); nu = int(u.sum())
            r = memo[mk] = float(py[u].sum() / nu) if nu >= min_g else None
        if r is not None: out[i] = r
    return out


def season_keys(dates):
    """(this season, in season?, last complete season) for each date, as add_x defines them"""
    dv = pd.to_datetime(pd.Series(dates)).values.astype("datetime64[ns]")
    seasons = np.array(sorted(KO)); ko = np.array([KO[y] for y in seasons], dtype="datetime64[ns]")
    j = np.searchsorted(ko, dv, side="right") - 1; cur_s = seasons[np.clip(j, 0, None)]
    ins = (dv < (ko[np.clip(j, 0, None)] + np.timedelta64(20 * 7, "D"))) & (j >= 0)
    return cur_s, ins, np.where(ins, cur_s - 1, cur_s)


def round5_columns(rows, gl, pos_of, adds):
    """the round-5 rule inputs (Oliver 2026-11-09) for rows (sid, gsis, date, pos): target lead, last-3 healthy max, 20+
    touch games, TE slide, QB hurt-or-top streak, games on half the snaps, league draft price, passing yards a game"""
    cur_s, ins, l0 = season_keys(rows.date)
    out = {}
    out["e_x_tgt_lead_w"], out["e_x_tgt_lead_sh"] = target_lead(rows, gl)
    out["e_x_recent_max3"] = recent_max(rows, gl)
    out["e_x_touch20"] = touch_games(rows, gl)
    out["e_x_te_slide"], out["e_x_te_recovered"], out["e_x_te_was_top"] = te_slide(rows, gl, pos_of, l0)
    out["e_x_qb_hurt_top"] = qb_hurt_or_top(rows, gl, pos_of, l0)
    out["e_x_big_games"] = big_games(rows, gl)
    out["e_x_league_draft_price"] = league_draft_price(rows, adds)
    out["e_x_pass_ypg"] = pass_ypg(rows, gl, cur_s, l0, ins)
    out["e_x_catch3"] = catch_rate(rows, gl)
    return out


def rb_room(rows, gl, roster, dp, pos_of, top=15, proven_ppg=None, min_games=6):
    """(prev_rank, comp) for RBs (Oliver 2026-11-09, the Aug 2025 Conner trade): prev_rank = his RB rank by total PPR in
    his last complete season (NaN if unranked); comp = how many RBs his team (on the date) added for the season after it:
    rookies the NFL took in rounds 1-2 (counted from the draft) plus veterans who joined it that offseason with a proven
    season (DEPARTED_PPG+ PPR a game over 6+ games in either of the two seasons before). The joiners use the team's first
    roster week (the small hindsight the move flags use)."""
    N = len(rows); rank = np.full(N, np.nan); comp = np.zeros(N)
    if gl is None or roster is None or not len(gl): return rank, comp
    _, _, l0 = season_keys(rows.date); l0 = np.asarray(l0).astype(int)
    gs = np.asarray(rows.gsis).astype(str); is_rb = np.asarray(rows.pos) == "RB"
    rk = season_ranks(gl, pos_of, "RB"); rank = np.where(is_rb, rk.reindex(pd.MultiIndex.from_arrays([gs, l0])).values, np.nan)
    rook = nfl_draft_comp(rows.assign(pos=np.where(is_rb, "RB", "_")), dp, roster, max_round=2)   # no `gone`: a rookie competes either way
    thr = (proven_ppg or DEPARTED_PPG)["RB"]
    g = gl.assign(gsis=gl.gsis.astype(str)).groupby(["gsis", "season"]).ppr.agg(["mean", "count"])
    proven = set(i for i, q in g.iterrows() if q["count"] >= min_games and q["mean"] >= thr)
    r = roster.dropna(subset=["gsis", "team"]).assign(gsis=lambda x: x.gsis.astype(str)).sort_values(["season", "week"])
    first = r.groupby(["gsis", "season"]).team.first(); last = r.groupby(["gsis", "season"]).team.last()
    joins = {}                                                  # (team, season) -> RBs who joined it that offseason with a proven season
    for (p_, y), t in first.items():
        if pos_of.get(p_) != "RB" or last.get((p_, y - 1)) == t: continue
        if (p_, y - 1) in proven or (p_, y - 2) in proven: joins.setdefault((t, int(y)), set()).add(p_)
    team = team_on(gs, pd.to_datetime(rows.date).values, roster)
    for i in np.where(is_rb)[0]:
        j = joins.get((team[i], int(l0[i]) + 1), set()) - {gs[i]}
        comp[i] = rook[i] + len(j)
    return rank, comp


def catch_rate(rows, gl, seasons=3, min_tgt=30):
    """receptions / targets over his last two complete seasons and this one (games known by the date); NaN under
    `min_tgt` targets. gl: games played with gsis, season, known, gl_tgt, rec (Oliver 2026-11-10: the target-lead boost
    is for a receiver who catches the ball)"""
    N = len(rows); out = np.full(N, np.nan)
    if gl is None or "rec" not in gl or not len(gl): return out
    g = gl.dropna(subset=["gl_tgt"]).assign(gsis=lambda x: x.gsis.astype(str), known=lambda x: pd.to_datetime(x.known))
    by = {k: (v.season.values.astype(int), v.known.values.astype("datetime64[ns]"), v.gl_tgt.values.astype(float), np.nan_to_num(v.rec.values.astype(float)))
          for k, v in g.groupby("gsis")}
    _, _, l0 = season_keys(rows.date)
    gs = np.asarray(rows.gsis).astype(str); dv = np.asarray(pd.to_datetime(pd.Series(np.asarray(rows.date))).values, dtype="datetime64[ns]")
    for a, ix in _rows_of(gs, np.isin(gs, list(by))).items():   # a row's mask is a function of (season, games known)
        t = by[a]; K = _n_known(t[1], dv[ix]); memo = {}
        for i, k in zip(ix, K):
            mk = (int(l0[i]), k); r = memo.get(mk, memo)
            if r is memo:
                m = (t[0] >= int(l0[i]) - (seasons - 2)) & (t[1] <= dv[i])
                tg = t[2][m].sum()
                r = memo[mk] = t[3][m].sum() / tg if tg >= min_tgt else None
            if r is not None: out[i] = r
    return out


def league_draft_done(rows, adds):
    """1 on dates after that calendar year's league rookie draft (its Draft additions' day), 0 before or on it, NaN in a
    year with no Draft rows (the summer rule then runs to kickoff - 3 days, as before): Oliver 2026-11-09, the summer
    level shift ends with the draft"""
    a = adds[adds.type == "Draft"].dropna(subset=["date"])
    day = pd.to_datetime(a.date).dt.normalize().groupby(pd.to_datetime(a.date).dt.year).max()
    dv = pd.to_datetime(pd.Series(np.asarray(rows.date))).dt.normalize()
    d = dv.dt.year.map(day)
    return np.where(d.isna(), np.nan, (dv > d).astype(float))


def league_draft_price(rows, adds):
    """what the league paid for the player in its rookie draft (the latest Draft addition on or before the date, in
    league FAAB); NaN if he was never drafted in it"""
    a = adds[adds.type == "Draft"].dropna(subset=["price"]).sort_values("date")
    D = {s: (v.date.values.astype("datetime64[ns]"), v.price.values.astype(float)) for s, v in a.groupby(a.sid.astype(str))}
    sid = np.asarray(rows.sid).astype(str); dv = np.asarray(rows.date, dtype="datetime64[ns]"); out = np.full(len(rows), np.nan)
    for a, ix in _rows_of(sid, np.isin(sid, list(D))).items():
        t = D[a]; j = np.searchsorted(t[0], dv[ix], side="right")
        out[ix[j > 0]] = t[1][j[j > 0] - 1]
    return out


def offseason_flags(date_v, fw, ko_up, jun1, career_over):
    """(unsigned, offseason) for each row. `fw` = the player's first regular-season roster week of the upcoming season
    (NaN = never on one), `ko_up` its kickoff, `jun1` its June 1.
    unsigned: from June 1 until he first appears on a roster, for a player NOT on a Week-1 roster (signed in-season or
    never). The weekly rosters start at Week 1, so a player on the Week-1 roster is taken as signed all summer (the same
    small hindsight as before); before 2026-11-04 every Week-1 player was flagged from June 1 to kickoff - 3 days.
    offseason: the same June 1 -> kickoff - 3 days window for every player (the summer, when the league's players-vs-picks
    prices differ), so the fit can weigh it as its own rule instead of through the unsigned flag."""
    date_v = np.asarray(date_v, dtype="datetime64[ns]"); fw = np.asarray(fw, dtype=float)
    ko_up = np.asarray(ko_up, dtype="datetime64[ns]"); jun1 = np.asarray(jun1, dtype="datetime64[ns]")
    late = np.where(np.isnan(fw), np.datetime64("2100-01-01"), ko_up + ((np.nan_to_num(fw) - 1) * 7 - 3).astype("timedelta64[D]"))
    signed_at = np.where(np.nan_to_num(fw, nan=99) <= 1, jun1, late)
    unsigned = ((date_v >= jun1) & (date_v < signed_at) & (np.asarray(career_over) == 0)).astype(float)
    offseason = ((date_v >= jun1) & (date_v < ko_up - np.timedelta64(3, "D"))).astype(float)
    return unsigned, offseason


def add_x(df):
    """df: gsis, date (any index). Returns df with e_x_* columns."""
    d = df[["gsis", "date"]].copy(); d["gsis"] = d.gsis.astype(str); d["date"] = pd.to_datetime(d.date); d["_i"] = np.arange(len(d))
    seasons = np.array(sorted(KO)); ko = np.array([KO[y] for y in seasons], dtype="datetime64[ns]")
    j = np.searchsorted(ko, d.date.values.astype("datetime64[ns]"), side="right") - 1
    cur_s = seasons[np.clip(j, 0, None)]
    in_season = d.date.values < (ko[np.clip(j, 0, None)] + np.timedelta64(20 * 7, "D"))
    d["cur_s"] = cur_s; d["in_season"] = in_season & (j >= 0)
    d["l0_s"] = np.where(d.in_season, cur_s - 1, cur_s)            # last COMPLETE season
    # this season to date: last weekly state known by the date
    m = kp.merge_asof(d.sort_values("date"), C.sort_values("known").rename(columns={"known": "date_k"}), left_on="date", right_on="date_k", by="gsis", direction="backward")
    m = m.set_index("_i").sort_index()
    cur_ok = d.in_season.values & (m.season.values == d.cur_s.values)
    cur = _rates(m); cur.loc[~cur_ok, :] = np.nan
    # last complete season and the one before
    def fin(season_col):
        k = pd.MultiIndex.from_arrays([d.gsis.values, season_col])
        return FIN.reindex(k).reset_index(drop=True)
    f0 = fin(d.l0_s.values); f1 = fin(d.l0_s.values - 1)
    l0 = _rates(f0); l1 = _rates(f1)
    out = pd.DataFrame(index=np.arange(len(d)))
    for c in cur.columns: out[f"e_x_cur_{c}"] = cur[c].values; out[f"e_x_l0_{c}"] = l0[c].values
    for c in ["xfp_pg", "fpoe_pg", "tgt_share", "yprr", "def_share", "off_pct"]: out[f"e_x_l1_{c}"] = l1[c].values
    for c in ["big", "good", "big_rate", "epa_db", "games", "xfp_share", "fpoe_touch", "ppr_cv", "td_share", "top_game_share"]: out[f"e_x_l1_{c}"] = l1[c].values
    # competition: the top same-position teammate's snap share and age (this season, else end of last)
    out["e_x_comp_share"] = np.where(cur_ok, m.comp_share.values, f0.comp_share.values); out["e_x_comp_age"] = np.where(cur_ok, m.comp_age.values, f0.comp_age.values)
    # changed teams since last season
    t_now = np.where(cur_ok, m.team.values, None); t_l0 = f0.team.values
    out["e_x_new_team"] = np.where(pd.notna(t_now) & pd.notna(t_l0), (t_now != t_l0).astype(float), np.nan)
    # team strength: win % so far, implied points from the betting lines for games up to a week ahead, last season win % and playoff depth
    tq = pd.DataFrame({"team": np.where(pd.notna(t_now), t_now, t_l0), "date": d.date.values, "s": np.where(d.in_season, d.cur_s, d.cur_s + 0)}).reset_index(drop=True)
    wp, imp = np.full(len(d), np.nan), np.full(len(d), np.nan)
    for (tm, ss), ix in tq.groupby(["team", "s"]).groups.items():
        g = GT[(GT.team == tm) & (GT.season == ss)].sort_values("gameday")
        if not len(g): continue
        dd = tq.loc[ix, "date"].values.astype("datetime64[ns]"); gd = g.gameday.values.astype("datetime64[ns]")
        k_done = np.searchsorted(gd, dd, side="left"); k_seen = np.searchsorted(gd, dd + np.timedelta64(7, "D"), side="right")
        cw = np.r_[0, np.nancumsum(g.win.fillna(0).values)]; cn = np.r_[0, np.cumsum(g.win.notna().values)]; ci = np.r_[0, np.nancumsum(g.implied.fillna(0).values)]; cin = np.r_[0, np.cumsum(g.implied.notna().values)]
        wp[ix] = np.where(cn[k_done] > 0, cw[k_done] / np.maximum(cn[k_done], 1), np.nan); imp[ix] = np.where(cin[k_seen] > 0, ci[k_seen] / np.maximum(cin[k_seen], 1), np.nan)
    gp_team = np.full(len(d), np.nan)
    for (tm, ss), ix in tq.groupby(["team", "s"]).groups.items():
        g = GT[(GT.team == tm) & (GT.season == ss) & (GT.game_type == "REG")]
        gp_team[ix] = np.searchsorted(np.sort(g.gameday.values.astype("datetime64[ns]")), tq.loc[ix, "date"].values.astype("datetime64[ns]"), side="left")
    out["e_x_team_games_cur"] = np.where(cur_ok, gp_team, np.nan)      # team games played so far (the availability denominator)
    out["e_x_team_win_cur"] = wp; out["e_x_team_implied_cur"] = imp
    ls = GT_SEAS.reindex(pd.MultiIndex.from_arrays([tq.team.values, d.l0_s.values]))
    out["e_x_team_win_l0"] = ls.win_pct.values; out["e_x_team_depth_l0"] = ls.depth.values; out["e_x_team_implied_l0"] = ls.implied.values
    # the player's current team's offense: expected fantasy points per game this season vs last ("ascendant offense")
    team = np.where(cur_ok, m.team.values, f0.team.values if "team" in f0 else None)
    tq = pd.DataFrame({"team": team, "date": d.date.values, "_i": d._i.values}).dropna(subset=["team"]).sort_values("date")
    tcur = kp.merge_asof(tq, TM.sort_values("known")[["team", "known", "season", "t_xfp_cum", "t_games"]], left_on="date", right_on="known", by="team", direction="backward").set_index("_i").reindex(d._i.values)
    ok_t = (tcur.season.values == d.cur_s.values) & d.in_season.values
    out["e_x_team_xfp_cur"] = np.where(ok_t, tcur.t_xfp_cum.values / tcur.t_games.values, np.nan)
    tl0 = TMF.reindex(pd.MultiIndex.from_arrays([team, d.l0_s.values])); out["e_x_team_xfp_l0"] = (tl0.t_xfp_cum / tl0.t_games).values
    out["e_x_team_trend"] = out.e_x_team_xfp_cur - out.e_x_team_xfp_l0
    # durability over this season to date + the last complete season
    cw = np.where(cur_ok, m.weeks.values, 0); co = np.where(cur_ok, m.inj_out.values, 0); ci = np.where(cur_ok, m.ir_onsets.values, 0)
    w0 = np.nan_to_num(f0.weeks.values.astype(float)); o0 = np.nan_to_num(f0.inj_out.values.astype(float))
    out["e_x_inj_rate_2y"] = (np.nan_to_num(co) + o0 + np.nan_to_num(f1.inj_out.values.astype(float))) / np.maximum(np.nan_to_num(cw) + w0 + np.nan_to_num(f1.weeks.values.astype(float)), 1)
    out["e_x_ir_2y"] = np.nan_to_num(ci) + np.nan_to_num(f0.ir_onsets.values.astype(float)) + np.nan_to_num(f1.ir_onsets.values.astype(float))
    bp = lambda s: BP.reindex(pd.MultiIndex.from_arrays([d.gsis.values, s])).fillna(0).values
    out["e_x_bodyparts_3y"] = bp(d.cur_s.values) * cur_ok + bp(d.l0_s.values) + bp(d.l0_s.values - 1)
    out["e_x_cur_exempt"] = np.where(cur_ok, np.nan_to_num(m.exempt.values.astype(float)), 0.0)    # weeks on the exempt list this season
    out["e_x_no_team_frac"] = np.where(cur_ok, np.nan_to_num(m.no_team.values.astype(float)) / np.maximum(np.nan_to_num(m.weeks.values.astype(float)), 1), np.nan)
    # track record through the last complete season: consecutive top-2 / top-5 / top-12 finishes, top-12 / top-5 seasons in the last 6
    fn = FN.reindex(pd.MultiIndex.from_arrays([d.gsis.values, d.l0_s.values]))
    for c in ["streak2", "streak5", "streak12", "top12_6y", "top5_6y", "starter_3y"]: out[f"e_x_{c}"] = fn[c].fillna(0).values
    # off the field (a little hindsight is allowed here): out of the league after his last roster season, unsigned from June 1
    # until he first appears on a roster, suspended, or a dated off-field event (retirement, legal, left the team)
    date_v = d.date.values.astype("datetime64[ns]"); g_ = d.gsis.values
    last = LS.reindex(g_).values
    feb1 = pd.to_datetime([f"{int(x) + 1}-02-01" if not np.isnan(x) else "2100-01-01" for x in last]).values
    out["e_x_career_over"] = (date_v >= feb1).astype(float)
    up_s = np.where(d.date.dt.month.values >= 3, d.date.dt.year.values, d.date.dt.year.values - 1)       # the season whose rosters count from June 1
    fw = RF.reindex(pd.MultiIndex.from_arrays([g_, up_s])).values
    ko_up = np.array([KO.get(int(y), pd.Timestamp(f"{int(y)}-09-08")) for y in up_s], dtype="datetime64[ns]")
    jun1 = pd.to_datetime([f"{int(y)}-06-01" for y in up_s]).values
    out["e_x_unsigned"], out["e_x_offseason"] = offseason_flags(date_v, fw, ko_up, jun1, out.e_x_career_over.values)
    ko_c = np.array([KO.get(int(y), pd.Timestamp(f"{int(y)}-09-08")) for y in d.cur_s.values], dtype="datetime64[ns]")
    out["e_x_rostered_recent"] = rostered_recent(date_v, RF.reindex(pd.MultiIndex.from_arrays([g_, d.l0_s.values])).values,
                                                 RF.reindex(pd.MultiIndex.from_arrays([g_, d.cur_s.values])).values, ko_c, d.in_season.values)
    gf = game_form(GL, g_, date_v, d.l0_s.values)
    if "first_team" in RT:
        out["e_x_moved_off"] = offseason_move(date_v, up_s, RT.first_team.reindex(pd.MultiIndex.from_arrays([g_, up_s])).values,
                                              RT.last_team.reindex(pd.MultiIndex.from_arrays([g_, up_s - 1])).values,
                                              np.isnan(out.e_x_new_team.values.astype(float)))
        out["e_x_coach_follow"] = coach_follow(up_s, RT.first_team.reindex(pd.MultiIndex.from_arrays([g_, up_s])).values,
                                               RT.last_team.reindex(pd.MultiIndex.from_arrays([g_, up_s - 1])).values, GT)
    for k_, v_ in gf.items(): out[f"e_x_{k_}"] = v_
    out["e_x_ppg_since_inj"], out["e_x_gp_since_inj"] = since_injury(GL, globals().get("IW"), g_, date_v)
    sus = np.zeros(len(d))
    for r in SUSP.itertuples():
        ko = KO.get(int(r.season)); a = np.datetime64(ko - pd.Timedelta(days=30)); b = np.datetime64(ko + pd.Timedelta(days=7 * int(r.week_end)))
        sus = np.maximum(sus, ((g_ == r.gsis_id) & (date_v >= a) & (date_v < b)).astype(float) * min(1.0, (int(r.week_end) - int(r.week_start) + 1) / 17))
    out["e_x_suspended"] = sus
    off = np.zeros(len(d))
    for r in OFF.itertuples():
        b = np.datetime64(r.end) if pd.notna(r.end) else np.datetime64("2100-01-01")
        off = np.maximum(off, ((g_ == r.gsis_id) & (date_v >= np.datetime64(r.start)) & (date_v < b)).astype(float))
    out["e_x_offfield"] = off
    # full seasons as a starting QB (300+ dropbacks) in the last four complete seasons
    fs = np.zeros(len(d))
    for k in range(4):
        fk = FIN.reindex(pd.MultiIndex.from_arrays([g_, d.l0_s.values - k]))
        fs += (np.nan_to_num(fk.dropbacks.values.astype(float)) >= 300)
    out["e_x_qb_full_4y"] = fs
    # pre-NFL profile
    s = ST.reindex(d.gsis.values)
    for c in ["draft_pick", "ht_in", "wt", "forty", "vertical", "broad_jump", "cone", "shuttle", "speed", "draft_age", "p5",
              "c_last_tgt_share", "c_last_touch_share", "c_last_epa_opp", "c_max_share", "c_breakout_age", "c_seasons", "c_rz_share"]:
        out[f"e_x_{c}"] = s[c].values.astype(float)
    # awards known by the date (counts; NFL ones decayed by seasons since)
    a = AW.merge(d[["gsis", "date", "_i"]], on="gsis")
    a = a[a.known <= a.date]
    yrs = (a.date.dt.year - a.season).clip(lower=0)
    a = a.assign(w=np.where(a.award.isin(["allpro1", "allpro2", "mvp", "opoy", "cpoy"]), 0.5 ** (yrs / 3.0), 1.0))
    piv = a.pivot_table(index="_i", columns="award", values="w", aggfunc="sum")
    for c in ["allpro1", "allpro2", "mvp", "opoy", "oroy", "cpoy", "heisman", "heisman_finalist", "multi_position",
              "biletnikoff", "doak_walker", "mackey", "obrien", "maxwell", "walter_camp"]:
        out[f"e_x_aw_{c}"] = piv[c].reindex(out.index).fillna(0).values if c in piv else 0.0
    out.index = df.index
    return pd.concat([df, out], axis=1)

_ADDX_ROWS = None


def _add_x_part(m):
    return add_x(_ADDX_ROWS[m])


def add_x_parallel(df, workers=None, min_rows=20000):
    """add_x(df) with the rows split by player id over `workers` forked processes (default faab_base.WORKERS; 1 = in
    this process; serial under `min_rows` rows): every e_x_ column is a function of the row (id, date) and the loaded
    store, so the parts, put back in df's row order, are the same frame"""
    global _ADDX_ROWS
    if not workers:
        try:
            from . import faab_base as B
            workers = B.WORKERS
        except Exception:                 # noqa: BLE001 - no scikit-learn: one process
            workers = 1
    g = np.array([x if isinstance(x, str) else "" for x in df.gsis.to_numpy(dtype=object)], dtype=object)   # no id: one part
    ug = sorted(set(g)); n = min(max(1, int(workers)), len(ug))
    if n <= 1 or len(df) < min_rows:
        return add_x(df)
    part = {x: i % n for i, x in enumerate(ug)}
    pid = np.array([part[x] for x in g])
    masks = [pid == i for i in range(n)]
    import multiprocessing as mp
    _ADDX_ROWS = df
    try:
        with mp.get_context("fork").Pool(n) as pool:
            out = pool.map(_add_x_part, masks, chunksize=1)
    finally:
        _ADDX_ROWS = None
    pos = np.concatenate([np.flatnonzero(m) for m in masks])
    return pd.concat(out).iloc[np.argsort(pos, kind="stable")]


def xcols(df): return [c for c in df.columns if c.startswith("e_x_")]


def build_store(last=None, log=print):
    """the whole feature store from the cached downloads (run faab_data.fetch_all first)"""
    last = last or D.current_season()
    XF_DIR.mkdir(parents=True, exist_ok=True)
    build_week(str(D.CACHE), str(D.FRAME_CACHE), str(XF_DIR), range(2016, last + 1))
    A = build_awards(str(D.CACHE), str(XF_DIR))
    prior = len(pd.read_csv(DATA / "awards.csv")) if (DATA / "awards.csv").exists() else 0
    if len(A) >= prior:
        A.sort_values(["season", "award", "gsis"]).to_csv(DATA / "awards.csv", index=False)
    build_finish(str(D.FRAME_CACHE), str(XF_DIR), last - 1)
    log(f"feature store: {XF_DIR} ({len(A)} award rows)")


TEAM_FIX = {"LAR": "LA", "OAK": "LV", "SD": "LAC", "STL": "LA"}


def vacated_role(rows, cache=None):
    """per row, in the offseason (March 15 to the upcoming season's kickoff): the share of his upcoming team's expected
    fantasy points (ffopportunity, last season) held by players at his position who were on that team at the end of
    last season and are not on it in week 1 (left, cut, retired), minus the share other newcomers at his position
    brought from their old teams. His upcoming team = his week-1 roster team (the same small hindsight as moved_off).
    rows: gsis, date, pos. Returns an array; NaN outside the window or without data."""
    import glob
    cache = Path(cache or D.CACHE); N = len(rows); out = np.full(N, np.nan)
    fs = sorted(glob.glob(str(cache / "ep_weekly_*.parquet"))); rs = sorted(glob.glob(str(cache / "roster_weekly_*.parquet")))
    if not fs or not rs: return out
    G = pd.concat([pd.read_parquet(f, columns=["season", "game_id", "player_id", "posteam", "total_fantasy_points_exp", "total_fantasy_points_exp_team"]) for f in fs])
    G["season"] = G.season.astype(int); G["posteam"] = G.posteam.replace(TEAM_FIX)
    ts = G.drop_duplicates(["game_id", "posteam"]).groupby(["posteam", "season"]).total_fantasy_points_exp_team.sum()
    ps = G.groupby(["player_id", "posteam", "season"]).total_fantasy_points_exp.sum().reset_index()
    ps["share"] = ps.total_fantasy_points_exp.values / ts.reindex(pd.MultiIndex.from_arrays([ps.posteam, ps.season])).values
    sh = ps.set_index(["player_id", "posteam", "season"]).share
    W = pd.concat([pd.read_parquet(f, columns=["season", "week", "team", "position", "gsis_id", "game_type", "draft_number", "rookie_year"]) for f in rs])
    W = W[(W.game_type == "REG") & W.gsis_id.notna()].sort_values(["season", "week"], kind="mergesort")
    W["season"] = W.season.astype(int); W["team"] = W.team.replace(TEAM_FIX)
    g = W.groupby(["gsis_id", "season"]); FT = g.team.first(); LT = g.team.last(); PO = g.position.last()
    wk1 = W[W.week == W.groupby("season").week.transform("min")]
    first = {(t, s): set(v) for (t, s), v in wk1.groupby(["team", "season"]).gsis_id}
    LTd = LT.reset_index(); LTd["pos"] = PO.values
    ends = {k: v for k, v in LTd.groupby(["team", "season", "pos"])}
    FTd = FT.reset_index(); FTd["pos"] = PO.values
    # a drafted rookie arriving takes a share by draft slot (round 1 0.15, round 2 0.08, picks 65-100 0.04)
    dn = pd.to_numeric(g.draft_number.last(), errors="coerce").values; ry = pd.to_numeric(g.rookie_year.last(), errors="coerce").values
    FTd["rk_share"] = np.where(ry == FTd.season.values, np.select([dn <= 32, dn <= 64, dn <= 100], [0.15, 0.08, 0.04], 0.0), 0.0)
    starts = {k: v for k, v in FTd.groupby(["team", "season", "pos"])}
    d = pd.to_datetime(rows.date); up = np.where(d.dt.month.values >= 3, d.dt.year.values, d.dt.year.values - 1)
    gs = rows.gsis.astype(str).values; pv = rows.pos.astype(str).values; dv = d.values.astype("datetime64[ns]")
    for i in range(N):
        y = int(up[i]); ko = np.datetime64(KO.get(y, pd.Timestamp(f"{y}-09-08")))
        if not (np.datetime64(f"{y}-03-15") <= dv[i] < ko): continue
        tm = FT.get((gs[i], y))
        if tm is None or pd.isna(tm): continue
        stay = first.get((tm, y), set()); e = ends.get((tm, y - 1, pv[i])); s_ = starts.get((tm, y, pv[i]))
        if e is None: continue
        left = e[(e.gsis_id != gs[i]) & ~e.gsis_id.isin(stay)]
        v = np.nansum(sh.reindex(pd.MultiIndex.from_arrays([left.gsis_id, [tm] * len(left), [y - 1] * len(left)])).values)
        if s_ is not None:
            new = s_[(s_.gsis_id != gs[i])]
            new = new[LT.reindex(pd.MultiIndex.from_arrays([new.gsis_id, [y - 1] * len(new)])).values != tm]
            if len(new):
                ot = LT.reindex(pd.MultiIndex.from_arrays([new.gsis_id, [y - 1] * len(new)])).values
                v -= np.nansum(sh.reindex(pd.MultiIndex.from_arrays([new.gsis_id.values, ot, [y - 1] * len(new)])).values) + new.rk_share.sum()
        out[i] = round(float(v), 5)
    return out


def activated_cuff(rows, cache=None, exit_ratio=0.4):
    """per row: how many team games in a row (ending with his team's latest game known by the date: game day + 1) his
    team's lead RB has missed or left early (touches + targets under exit_ratio of his average this season before
    the streak), when this player was the team's second RB going into the streak (lead / second = most / second-most
    expected fantasy points among the team's RBs this season before the streak, the lead with 2+ games). 1 = the
    starter just went down and the backup has not yet had a full game as the lead. 0 for anyone else in season with
    data, NaN before his team's first game or without data. rows: gsis, date, pos. ffopportunity weekly + games."""
    import glob
    cache = Path(cache or D.CACHE); N = len(rows); out = np.full(N, np.nan)
    fs = sorted(glob.glob(str(cache / "ep_weekly_*.parquet"))); gp = cache / "games.parquet"
    if not fs or not gp.exists(): return out
    cols = ["season", "game_id", "player_id", "posteam", "position", "total_fantasy_points_exp", "rush_attempt", "rec_attempt"]
    G = pd.concat([pd.read_parquet(f, columns=[c for c in cols if c != "position"] + ["position"]) for f in fs])
    G = G.merge(pd.read_parquet(gp, columns=["game_id", "gameday"]), on="game_id", how="left").dropna(subset=["gameday", "posteam"])
    G["season"] = G.season.astype(int); G["posteam"] = G.posteam.replace(TEAM_FIX)
    G["known"] = pd.to_datetime(G.gameday) + pd.Timedelta(days=1)
    G["opp"] = G.rush_attempt.fillna(0) + G.rec_attempt.fillna(0)
    R_ = G[G.position == "RB"]
    spans = {}                                       # cuff gsis -> list of (from, to, k)
    for (tm, s), g in G.groupby(["posteam", "season"]):
        games = g.drop_duplicates("game_id").sort_values("known", kind="mergesort")[["game_id", "known"]].values
        rb = R_[(R_.posteam == tm) & (R_.season == s)]
        by_g = {gid: v.set_index("player_id") for gid, v in rb.groupby("game_id")}
        cum, cnt, opp_sum = {}, {}, {}
        start = None                                  # (lead, cuff, avg) when a streak is running
        for j, (gid, kn) in enumerate(games):
            v = by_g.get(gid)
            nxt = games[j + 1][1] if j + 1 < len(games) else kn + np.timedelta64(8, "D")
            # the lead and second going into this game
            order = sorted(cum, key=lambda p: -cum[p])
            if start is None and len(order) >= 2 and cnt[order[0]] >= 2:
                lead, cuff = order[0], order[1]; avg = opp_sum[lead] / cnt[lead]
                o = float(v.opp.get(lead, 0.0)) if v is not None and lead in v.index else 0.0
                if avg >= 4 and o < exit_ratio * avg: start = (lead, cuff, avg, j)
            elif start is not None:
                lead, cuff, avg, j0 = start
                o = float(v.opp.get(lead, 0.0)) if v is not None and lead in v.index else 0.0
                if o >= exit_ratio * avg: start = None
            if start is not None:
                spans.setdefault(start[1], []).append((kn, nxt, j - start[3] + 1))
            if v is not None:
                for p, r in v.iterrows():
                    cum[p] = cum.get(p, 0.0) + float(np.nan_to_num(r.total_fantasy_points_exp)); cnt[p] = cnt.get(p, 0) + 1
                    opp_sum[p] = opp_sum.get(p, 0.0) + float(r.opp)
    first = G.groupby("season").known.min()
    d = pd.to_datetime(rows.date).values.astype("datetime64[ns]"); di = pd.DatetimeIndex(d); s = np.where(di.month >= 3, di.year, di.year - 1)
    for i, g in enumerate(rows.gsis.astype(str).values):
        f0 = first.get(int(s[i]))
        if f0 is None or d[i] < np.datetime64(f0) or d[i] > np.datetime64(f"{int(s[i]) + 1}-02-15"): continue
        out[i] = 0.0
        for a, b, k in spans.get(g, ()):
            if np.datetime64(a) <= d[i] < np.datetime64(b): out[i] = k; break
    return out


DRAFT_TEAM_FIX = {"GNB": "GB", "SFO": "SF", "NWE": "NE", "LVR": "LV", "KAN": "KC", "NOR": "NO", "TAM": "TB", "LAR": "LA", "SDG": "LAC", "OAK": "LV", "STL": "LA", "SD": "LAC"}


def rookie_qb_pick(rows, roster, cache=None):
    """per row: the overall pick of the highest QB his NFL team (on the date: team_on) took in round 1 of this season's
    NFL draft, from that draft's day through the season (the season starts March 1); 0 if none, NaN without a team.
    rows: gsis, date. roster: team_on's roster frame. nflverse draft_picks."""
    cache = Path(cache or D.CACHE); N = len(rows); out = np.full(N, np.nan)
    f = cache / "draft_picks.parquet"
    if not f.exists() or roster is None: return out
    dk = pd.read_parquet(f, columns=["season", "round", "pick", "team", "position"])
    q = dk[(dk.position == "QB") & (dk["round"] == 1)]
    best = {}
    for r in q.itertuples():
        k = (DRAFT_TEAM_FIX.get(r.team, r.team), int(r.season)); best[k] = min(best.get(k, 999), int(r.pick))
    t = team_on(rows.gsis.astype(str).values, rows.date.values, roster)
    d = pd.to_datetime(rows.date); s = np.where(d.dt.month >= 3, d.dt.year, d.dt.year - 1)
    for i in range(N):
        if t[i] is None or pd.isna(t[i]): continue
        y = int(s[i]); nd = pd.Timestamp(NFL_DRAFT.get(y, f"{y}-04-25"))
        out[i] = best.get((TEAM_FIX.get(t[i], t[i]), y), 0) if d.iloc[i] >= nd else 0.0
    return out


def on_team(rows, roster, team="NYG"):
    """per row: 1 if his NFL team on the date (team_on) is `team`, 0 if another, NaN without one. rows: gsis, date"""
    t = team_on(rows.gsis.astype(str).values, rows.date.values, roster)
    return np.array([np.nan if (x is None or pd.isna(x)) else float(TEAM_FIX.get(x, x) == team) for x in t])


def suspended_last(rows, susp):
    """per row: the share of last season's 17-18 weeks he was suspended (data/suspensions.csv; the season starts
    March 1), 0 if none. A suspension is not an injury: the availability dock reads those games as missed.
    rows: gsis, date. susp: player_name, gsis_id, season, week_start, week_end."""
    d = pd.to_datetime(rows.date); s = np.where(d.dt.month >= 3, d.dt.year, d.dt.year - 1)
    w = {}
    for r in susp.dropna(subset=["gsis_id"]).itertuples():
        k = (str(r.gsis_id), int(r.season)); w[k] = w.get(k, 0) + int(r.week_end) - int(r.week_start) + 1
    g = rows.gsis.astype(str).values
    return np.array([min(w.get((g[i], int(s[i]) - 1), 0) / 17.0, 1.0) for i in range(len(rows))])


def depth_chart(rows, seasons=None, stale=21, prev=(21, 56)):
    """per row: his depth-chart rank at his position on the latest chart out by the date (weekly nflverse charts to
    2024, counted from 4 days before each game; daily ESPN snapshots from August 2025), NaN when no chart is out within
    `stale` days of the date or he is on none; and his best rank on the charts `prev` days before (a benched or promoted
    player). rows: gsis, date. Returns (rank, prev_rank)."""
    N = len(rows); rk = np.full(N, np.nan); pv = np.full(N, np.nan)
    seasons = seasons or range(2020, pd.Timestamp.today().year + 1)
    Dl = []
    for y in seasons:
        d = kp._read(f"dc_{y}.csv")
        if d is None: continue
        if "depth_team" in d.columns:
            d = d[(d.formation == "Offense") & d.position.isin(kp.POS) & (d.game_type == "REG")].copy()
            d["avail"] = (kp._wkdate(y, d.week) - pd.Timedelta(days=4)).values
            d["rank"] = pd.to_numeric(d.depth_team, errors="coerce")
        else:
            d = d[d.pos_abb.isin(kp.POS)].copy()
            d["avail"] = pd.to_datetime(d.dt.str[:10])
            d["rank"] = d.pos_rank
        Dl.append(d[["gsis_id", "avail", "rank"]])
    if not Dl: return rk, pv
    Dd = pd.concat(Dl).dropna(subset=["gsis_id"]).groupby(["gsis_id", "avail"])["rank"].min().reset_index()
    by = {g: (v.avail.values.astype("datetime64[D]"), v["rank"].values) for g, v in Dd.sort_values("avail").groupby("gsis_id")}
    dts = pd.to_datetime(pd.Series(rows["date"]).values).values.astype("datetime64[D]")
    gs = pd.Series(rows["gsis"]).values
    for i in range(N):
        a = by.get(gs[i])
        if a is None: continue
        av, r = a; t = dts[i]
        j = np.searchsorted(av, t, side="right") - 1
        if j >= 0 and (t - av[j]).astype(int) <= stale: rk[i] = r[j]
        m = (av <= t - np.timedelta64(prev[0], "D")) & (av >= t - np.timedelta64(prev[1], "D"))
        if m.any(): pv[i] = r[m].min()
    return rk, pv


def team_now_l0(rows, roster, cache=None):
    """per row: last complete season's win % and mean implied points of the NFL team he is on at the date (team_on),
    not the team he played for: a player who moved in the offseason is judged by his new team. NaN when his team is
    unknown. rows: gsis, date. roster: gsis, season, week, team. Schedules + lines from games.parquet."""
    cache = Path(cache or D.CACHE); gp = cache / "games.parquet"
    N = len(rows); w = np.full(N, np.nan); im = np.full(N, np.nan)
    if not gp.exists() or roster is None: return w, im
    G = pd.read_parquet(gp)                 # every game, playoffs too (as GT_SEAS)
    T = pd.concat([pd.DataFrame({"team": G.home_team, "season": G.season, "win": (G.home_score > G.away_score).astype(float).where(G.home_score.notna()),
                                 "implied": G.total_line / 2 + G.spread_line / 2}),
                   pd.DataFrame({"team": G.away_team, "season": G.season, "win": (G.away_score > G.home_score).astype(float).where(G.home_score.notna()),
                                 "implied": G.total_line / 2 - G.spread_line / 2})])
    T["team"] = T.team.replace(TEAM_FIX)
    TS = T.groupby(["team", "season"]).agg(win=("win", "mean"), implied=("implied", "mean"))
    t = team_on(rows["gsis"].values, rows["date"].values, roster)
    dd = pd.to_datetime(pd.Series(rows["date"]).values); s = np.where(dd.month >= 3, dd.year, dd.year - 1)
    k = TS.reindex(pd.MultiIndex.from_arrays([pd.Series(t).replace(TEAM_FIX).values, s - 1]))
    return k.win.values, k.implied.values
