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
        try: w = pd.read_csv(f"{FC}/wk_{y}.csv", low_memory=False, usecols=["player_id", "position", "season", "week", "season_type", "fantasy_points_ppr", "attempts", "sacks_suffered", "passing_epa", "rushing_epa", "receiving_epa", "passing_tds", "rushing_tds", "receiving_tds"])
        except FileNotFoundError: continue
        w = w[w.season_type == "REG"]
        thr = np.where(w.position == "QB", 25.0, 20.0)
        bw.append(w.assign(gsis=w.player_id, big=(w.fantasy_points_ppr >= thr).astype(float), good=(w.fantasy_points_ppr >= thr * 0.75).astype(float),
                           dropbacks=w.attempts.fillna(0) + w.sacks_suffered.fillna(0), pass_epa=w.passing_epa, skill_epa=w.rushing_epa.fillna(0) + w.receiving_epa.fillna(0),
                           ppr=w.fantasy_points_ppr, ppr2=w.fantasy_points_ppr ** 2, td_pts=6 * (w.rushing_tds.fillna(0) + w.receiving_tds.fillna(0)) + 4 * w.passing_tds.fillna(0))
                  [["gsis", "season", "week", "big", "good", "dropbacks", "pass_epa", "skill_epa", "ppr", "ppr2", "td_pts"]])
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
    print("weekly", C.shape, "players", C.gsis.nunique())

    # ---------------------------------------------------------------- roster presence: first week on any NFL roster each season, last season on one
    RP = []
    for y in YEARS:
        r = rd(f"roster_weekly_{y}")
        if r is None: continue
        r = r[(r.game_type == "REG") if "game_type" in r else slice(None)]
        RP.append(r.groupby("gsis_id").week.min().rename("first_week").reset_index().assign(season=y).rename(columns={"gsis_id": "gsis"}))
    RP = pd.concat(RP); RP.to_parquet(f"{OUT}/xf_roster_first.parquet")
    RP.groupby("gsis").season.max().rename("last_roster_season").reset_index().to_parquet(f"{OUT}/xf_last_season.parquet"); print("roster presence", RP.shape)

    # ---------------------------------------------------------------- team strength by date (schedules + betting lines)
    G = rd("games"); G = G[G.season >= 2015]
    G["gameday"] = pd.to_datetime(G.gameday)
    rows = []
    for side, opp in (("home", "away"), ("away", "home")):
        sp = np.where(side == "home", -G.spread_line, G.spread_line)       # spread_line > 0 = home favoured
        rows.append(pd.DataFrame({"team": G[f"{side}_team"], "season": G.season, "game_type": G.game_type, "gameday": G.gameday,
                                  "pts": G[f"{side}_score"], "opp_pts": G[f"{opp}_score"], "implied": G.total_line / 2 - sp / 2 * (1 if side == "home" else 1)}))
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
    us["gsis"] = us.player_id.astype(str).map(ESPN2G); us = us.dropna(subset=["gsis"])
    us = us.merge(st[["gsis", "birth_date", "draft_year"]], on="gsis", how="left")
    us = us[us.season < us.draft_year.fillna(9999)]
    us["age_s"] = (pd.to_datetime(us.season.astype(str) + "-09-01") - pd.to_datetime(us.birth_date)).dt.days / 365.25
    us["share"] = us[["target_share", "touch_share"]].max(axis=1)
    last = us.sort_values("season").groupby("gsis").tail(1).set_index("gsis")
    bo = us[us.share >= 0.20].sort_values("season").groupby("gsis").head(1).set_index("gsis").age_s
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
    global C, FIN, BP, ST, TM, TMF, FN, GT, GT_SEAS, RF, LS, SUSP, OFF, AW
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
    RF = pd.read_parquet(f"{XF}/xf_roster_first.parquet"); RF["gsis"] = RF.gsis.astype(str); RF = RF.set_index(["gsis", "season"]).first_week
    LS = pd.read_parquet(f"{XF}/xf_last_season.parquet"); LS["gsis"] = LS.gsis.astype(str); LS = LS.set_index("gsis").last_roster_season
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
    m = pd.merge_asof(d.sort_values("date"), C.sort_values("known").rename(columns={"known": "date_k"}), left_on="date", right_on="date_k", by="gsis", direction="backward")
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
    tcur = pd.merge_asof(tq, TM.sort_values("known")[["team", "known", "season", "t_xfp_cum", "t_games"]], left_on="date", right_on="known", by="team", direction="backward").set_index("_i").reindex(d._i.values)
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
    signed_at = np.where(np.isnan(fw), np.datetime64("2100-01-01"), ko_up + ((np.nan_to_num(fw) - 1) * 7 - 3).astype("timedelta64[D]"))
    jun1 = pd.to_datetime([f"{int(y)}-06-01" for y in up_s]).values
    out["e_x_unsigned"] = ((date_v >= jun1) & (date_v < signed_at) & (out.e_x_career_over.values == 0)).astype(float)
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
