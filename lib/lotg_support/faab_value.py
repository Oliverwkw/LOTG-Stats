"""FAAB-unit player values from stats: one fixed set of general rules over a stats-only base value.

What the league would pay, in its own FAAB dollars, for every QB/RB/WR/TE on a date, the way the league
values players (its trades and cuts), using only what was known that day. Nothing here names a player or
pins a value: every rule acts on a measurable characteristic (usage, team share, availability, a sustained
elite record, age, injury status, ...) and is applied the same way on every date. Each rule's strength is
fitted ONCE, jointly, on

  - completed trades (both sides valued the day before; picks and FAAB at their walk-forward value),
  - cuts (a dropped player was worth under ~$100 the day before: the league's own rule of thumb),
  - the league's calls about specific players (`faab_calls`) — tests the rules are fitted to, never edits,
  - league members' rating-page votes (`faab_votes`), a capped signal that grows only as votes accumulate.

Trade/cut history outweighs the calls and votes (one person's view, a few voters). Sign locks keep each rule
pointing the way it can only plausibly point (an injury can only lower a value, an award only raise it); a
wrong-signed bound fails at import.

Inputs (data/faab_value/, plain text):
  inputs.csv      one row per (player, date) the rules read: the as-of date's board plus every trade side and
                  cut's day-before row. `V_raw` is the walk-forward base value (models refit quarterly on data
                  dated before each snapshot, smoothed causally); `rank_raw`/`line_n` are the player's base
                  rank that day and that season's replacement line (roster spots x 8); the excused-absence
                  fallback (exempt 2+ weeks -> preseason value) is already applied.
  evidence.json   the trades (each side: FAAB + pick value, players as (sid, date) keys) and cuts.
  params.json     the fitted rule strengths.
The base and the e_x_* stats columns are produced upstream (see plan/notes/FAAB_VALUE_SYSTEM.md).
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "faab_value"

def _rowmean(*cols):
    """Per-player mean of the non-NaN values; NaN for a player with none (no
    stats of that kind yet, expected), without numpy's empty-slice warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(np.vstack(cols), axis=0)


# ------------------------------------------------------------------ rules
P0 = dict(y200=200.0, y450=450.0, y650=650.0, lvl=1.0, vet=1.0, vet_hi=900.0, top_g=0.62,
          youth_role=0.0, te_lo=0.0, te_hi=0.0, inj_ir=0.0, inj_out=0.0, prone=0.0, two_way=0.0, aw_college=0.0, aw_nfl=0.0, usage=0.0, youth_usage=0.0, qb_lo=0.0, qb_hi=0.0, rb_lo=0.0, rb_hi=0.0, wr_lo=0.0, wr_hi=0.0, youth_age=26.0, spike=0.0, team_up=0.0, severe=0.0, spike_hi=1500.0, anchor_w=0.0, anchor_slope=0.5, qb_quality=0.0, elite_streak=0.0, track=0.0, recurring=0.0, steady=0.0, pedigree=0.0, efficiency=0.0, opening=0.0, team_q=0.0, new_team_burst=0.0, share_talent=0.0, availability=0.0, rb_multi=0.0, wr_talent=0.0, pick_boom=0.0, rb_age=0.0, rookie_capital=0.0, alpha=0.0, off_field=0.0, journeyman=0.0, bust=0.0, bubble=0.0, line_frac=0.8)
BOUNDS = dict(y200=(80, 230), y450=(250, 520), y650=(500, 950), lvl=(0.6, 1.6), vet=(0.2, 1.0), vet_hi=(600, 3500), top_g=(0.45, 0.85),
              youth_role=(-0.5, 2.0), te_lo=(-1.5, 0.8), te_hi=(-1.0, 0.6), inj_ir=(-1.0, 0.3), inj_out=(-0.8, 0.3), prone=(-2.5, 0.5),
              two_way=(0.0, 2.5), aw_college=(-0.3, 1.5), aw_nfl=(-0.3, 1.0), usage=(-0.3, 1.5), youth_usage=(-0.3, 2.0), qb_lo=(-0.5, 0.4), qb_hi=(-0.6, 0.6), rb_lo=(-0.5, 0.15), rb_hi=(-0.6, 0.6), wr_lo=(-0.5, 0.15), wr_hi=(-0.6, 0.6), youth_age=(24.5, 29.0), spike=(-0.5, 2.0), team_up=(-0.5, 1.0), severe=(-1.5, 0.3), spike_hi=(500.0, 3000.0), anchor_w=(0.0, 0.7), anchor_slope=(0.2, 0.9), qb_quality=(-0.5, 2.0), elite_streak=(0.0, 1.5), track=(-0.3, 1.0), recurring=(-0.6, 0.2), steady=(-0.3, 1.0), pedigree=(-0.3, 1.0), efficiency=(-0.3, 1.2), opening=(-0.3, 1.2), team_q=(-0.3, 0.8), new_team_burst=(-0.3, 1.2), share_talent=(-0.3, 1.2), availability=(0.0, 1.5), rb_multi=(-0.3, 1.0), wr_talent=(-0.3, 1.0), pick_boom=(-0.3, 1.5), rb_age=(-1.2, 0.2), rookie_capital=(-0.3, 1.5), alpha=(-0.3, 1.0), off_field=(-5.0, 0.0), journeyman=(-2.0, 0.3), bust=(-2.0, 0.3), bubble=(0.0, 4.0), line_frac=(0.4, 1.1))
P0.update(boom_bust=0.0, td_dep=0.0, one_game=0.0, young_starter=0.0, carry=0.0, qb_pedigree=0.0, qb_starter=0.0, ir_no_double=0.0, qb_opening=0.0)
BOUNDS.update(rb_hi=(0.0, 0.6), wr_hi=(-0.1, 0.1), qb_hi=(-0.2, 0.2),
    
    # can only LOWER value
    inj_ir=(-1.5, 0.0), inj_out=(-0.8, 0.0), severe=(-1.5, 0.0), prone=(-2.0, 0.0), recurring=(-0.8, 0.0), off_field=(-5.0, 0.0),
    journeyman=(-2.0, 0.0), bust=(-2.0, 0.0), rb_age=(-1.2, 0.0), boom_bust=(-1.0, 0.0), td_dep=(-1.0, 0.0), one_game=(-1.5, 0.0), young_starter=(0.0, 1.5), carry=(0.0, 1.0), opening=(0.0, 1.0),
    # can only RAISE value
    aw_nfl=(0.0, 1.0), aw_college=(0.0, 1.5), usage=(0.0, 1.5), steady=(0.0, 1.0), youth_usage=(0.0, 2.0), youth_role=(0.0, 1.0),
    elite_streak=(0.15, 1.5), track=(0.2, 1.0), qb_quality=(0.0, 2.0), top_g=(0.1, 0.85),
    # track and elite streak have floors (sustained records, per review); top compression can go further
    wr_talent=(0.0, 1.0), rb_multi=(0.0, 1.0), efficiency=(0.0, 1.2),
    pedigree=(0.0, 1.0), rookie_capital=(0.0, 1.5), alpha=(0.0, 1.0), availability=(0.0, 1.5), pick_boom=(0.0, 1.5), new_team_burst=(0.0, 1.2),
    team_up=(0.0, 0.6), two_way=(0.0, 2.5), share_talent=(0.3, 2.0),            # team share: a floor, per review ("increase team-share bonuses")
    spike=(0.0, 1.2), team_q=(0.0, 0.25),                                         # big weeks and team strength: capped
    qb_pedigree=(0.0, 1.5), qb_starter=(0.0, 1.0), qb_opening=(0.0, 1.5),        # QB draft capital, established starting QB, QB opening
    ir_no_double=(0.0, 1.0))                                                      # a blend weight (IR: prior seasons stand in), either direction
RAISE_ONLY = ["aw_nfl", "aw_college", "usage", "steady", "youth_usage", "youth_role", "elite_streak", "track", "qb_quality", "wr_talent", "rb_multi", "efficiency",
              "pedigree", "rookie_capital", "alpha", "availability", "pick_boom", "new_team_burst", "team_up", "two_way", "share_talent", "spike", "team_q", "opening",
              "young_starter", "carry", "qb_pedigree", "qb_starter", "qb_opening"]
LOWER_ONLY = ["inj_ir", "inj_out", "severe", "prone", "recurring", "off_field", "journeyman", "bust", "rb_age", "boom_bust", "td_dep", "one_game"]
_bad = [k for k in RAISE_ONLY if BOUNDS[k][0] < 0] + [k for k in LOWER_ONLY if BOUNDS[k][1] > 0]
assert not _bad, f"rules with the wrong sign allowed: {_bad}"
VET_AGE = {"QB": 33, "RB": 26.5, "WR": 28.5, "TE": 28.5}
UK = 2.5     # no NFL team (off every depth chart, no games, not hurt): x0.08
def col(R, c): return R[c].values.astype(float) if c in R else np.full(len(R), np.nan)
def boom_bust_early(R, cur_gp):
    cv = _rowmean(np.where(cur_gp >= 4, col(R, "e_x_cur_ppr_cv"), np.nan), col(R, "e_x_l0_ppr_cv"), col(R, "e_x_l1_ppr_cv"))
    tds = _rowmean(np.where(cur_gp >= 4, col(R, "e_x_cur_td_share"), np.nan), col(R, "e_x_l0_td_share"), col(R, "e_x_l1_td_share"))
    return np.clip((np.nan_to_num(cv, nan=0.5) - 0.5) / 0.25, 0, 1.5) + np.clip((np.nan_to_num(tds, nan=0.2) - 0.25) / 0.15, 0, 1.5)
def characteristics(R, youth_age=26.0):
    """the measurable characteristics the rules act on (each 0..1 or a small count)"""
    age = col(R, "age"); exp_ = np.nan_to_num(col(R, "exp"))
    cur_gp = np.nan_to_num(col(R, "e_x_cur_games"))
    snap = np.where(cur_gp >= 3, col(R, "e_x_cur_off_pct"), col(R, "e_x_l0_off_pct"))
    role = np.clip((np.nan_to_num(snap) - 0.45) / 0.35, 0, 1)                          # real offensive role (snap share 45% -> 80%)
    youth = np.clip((youth_age - np.nan_to_num(age, nan=26)) / 4.0, 0, 1)             # fades over the 4 years before youth_age (fitted)
    dshare = np.fmax(np.nan_to_num(col(R, "e_x_cur_def_share")), np.nan_to_num(col(R, "e_x_l0_def_share")))
    two_way = np.where(R.pos.isin(["WR", "RB", "TE", "QB"]).values, np.clip(dshare / 0.3, 0, 1), 0)   # 30%+ of snaps on defense
    early = np.clip((4.0 - exp_) / 3.0, 0, 1)                                             # college pedigree fades over 3 NFL seasons
    awc = (col(R, "e_x_aw_heisman") + 0.5 * col(R, "e_x_aw_heisman_finalist") + 0.5 * col(R, "e_x_aw_multi_position")
           + 0.3 * (col(R, "e_x_aw_biletnikoff") + col(R, "e_x_aw_doak_walker") + col(R, "e_x_aw_mackey") + col(R, "e_x_aw_obrien") + col(R, "e_x_aw_maxwell") + col(R, "e_x_aw_walter_camp")))
    awn = col(R, "e_x_aw_allpro1") + 0.5 * col(R, "e_x_aw_allpro2") + col(R, "e_x_aw_mvp") + 0.7 * col(R, "e_x_aw_opoy") + 0.3 * col(R, "e_x_aw_cpoy")
    inj = R.injury.fillna("").values
    # usage: expected fantasy points per game (what the role is worth, not what bounced right), this season blended
    # with last season as 4 games of prior, relative to the position's superflex replacement level
    xc, xl = col(R, "e_x_cur_xfp_pg"), col(R, "e_x_l0_xfp_pg"); g = np.where(np.isnan(xc), 0, cur_gp); gl = np.where(np.isnan(xl), 0, 4.0)
    xfp_b = (np.nan_to_num(xc) * g + np.nan_to_num(xl) * gl) / np.maximum(g + gl, 1e-9)
    rep = R.pos.map({"QB": 15.7, "RB": 12.1, "WR": 12.2, "TE": 10.5}).fillna(12).values
    best = np.fmax(np.nan_to_num(xl, nan=-9), np.nan_to_num(col(R, "e_x_l1_xfp_pg"), nan=-9))                # best of the last two full seasons
    xfp_b = np.where(best > -9, np.fmax(xfp_b, 0.85 * best), xfp_b)
    usage = np.where(g + gl > 0, np.clip((xfp_b - rep) / 6.0, -1, 2), 0.0)
    xfp_p = np.where(best > -9, np.fmax(np.nan_to_num(xl, nan=-9), 0.85 * best), np.nan); xfp_p = np.where(xfp_p > -9, xfp_p, np.nan)   # last full season(s) only
    xfp_hb = np.where(np.isnan(xfp_p), xfp_b, xfp_p)
    usage_h = np.where(np.isnan(xfp_hb), usage, np.clip((xfp_hb - rep) / 6.0, -1, 2))
    # big weeks (a breakout: non-QBs, fading out from 26 to 29): share of games at 15+ PPR (20+ is 'big'; 25/19 for QBs), this season with last season as prior
    cg_, gd_, l0g, l0d = cur_gp, np.nan_to_num(col(R, "e_x_cur_good")), np.nan_to_num(col(R, "e_x_l0_games")), np.nan_to_num(col(R, "e_x_l0_good"))
    spike = (gd_ + 0.5 * l0d + 0.5 * np.nan_to_num(col(R, "e_x_cur_big"))) / np.maximum(cg_ + 0.5 * l0g, 1)
    trend = np.clip(np.nan_to_num(col(R, "e_x_team_trend")) / 15.0, -1, 1) * (cur_gp >= 3)
    severe = np.isin(inj, ["IR", "PUP"]) * np.clip(np.nan_to_num(col(R, "age"), nan=26) / 30, 0.7, 1.2)
    # QB passing quality: EPA per dropback, this season (by dropbacks) blended with the last two full seasons
    e_c, e_0, e_1 = col(R, "e_x_cur_epa_db"), col(R, "e_x_l0_epa_db"), col(R, "e_x_l1_epa_db")
    wc = np.where(np.isnan(e_c), 0, np.clip(cur_gp / 8, 0, 1)); w0 = np.where(np.isnan(e_0), 0, 1.0); w1 = np.where(np.isnan(e_1), 0, 0.5)
    epa = (np.nan_to_num(e_c) * wc + np.nan_to_num(e_0) * w0 + np.nan_to_num(e_1) * w1) / np.maximum(wc + w0 + w1, 1e-9)
    cp = _rowmean(col(R, "e_x_l0_cpoe"), np.where(cur_gp >= 3, col(R, "e_x_cur_cpoe"), np.nan))
    qbq = np.where((R.pos.values == "QB") & (wc + w0 + w1 > 0), np.clip(0.75 * (epa - 0.10) / 0.15 + 0.25 * np.nan_to_num(cp) / 4, -1.5, 1.5), 0.0)
    # youth x usage counts only usage above replacement (a young player without a real role gets nothing)
    xfp_z = np.where(g + gl > 0, xfp_b - rep, np.nan)                                    # usage above replacement (expected PPG)
    # sustained elite record: consecutive top-2 seasons (Allen: 6-7 years), consecutive top-5, and top-12 seasons out of 6
    elite = np.clip(np.nan_to_num(col(R, "e_x_streak2")), 0, 7) / 4 + 0.5 * np.clip(np.nan_to_num(col(R, "e_x_streak5")), 0, 7) / 4
    track = np.nan_to_num(col(R, "e_x_top12_6y")) / 6
    # recurring injuries: distinct body parts on the report over 3 seasons beyond the first
    recurring = np.clip(np.nan_to_num(col(R, "e_x_bodyparts_3y")) - 1, 0, 4) / 2
    # sustained usage: the weaker of the last two full seasons' expected PPG, above replacement (one big year is not a track)
    l1x = col(R, "e_x_l1_xfp_pg"); steady = np.where(np.isnan(xl) | np.isnan(l1x), 0.0, np.clip((np.fmin(xl, l1x) - rep) / 6.0, -1, 2))
    # early-career pedigree: draft slot (top-64 picks) and college usage share, fading over the first 3 NFL seasons
    pick = col(R, "e_x_draft_pick"); dc = np.where(np.isnan(pick), 0.0, np.clip((64 - pick) / 63, 0, 1))
    cs = np.clip((np.nan_to_num(col(R, "e_x_c_max_share")) - 0.15) / 0.2, 0, 1)
    pedigree = early * (0.7 * dc + 0.3 * cs) * (R.pos.values != "QB")
    # a QB's draft capital: top-64 picks, fading over his first four NFL seasons (a franchise QB is given time)
    qb_pedigree = (R.pos.values == "QB") * dc * np.clip((5.0 - exp_) / 4.0, 0, 1)
    # an established starting QB before the age decline (superflex QB premium): usage above replacement (expected PPG, 3+ over = full),
    # two or more top-12 seasons in the last six (one = half), fading from 30 to 34
    qb_starter = (R.pos.values == "QB") * np.clip(np.nan_to_num(xfp_b - rep) / 3.0, 0, 1) * np.clip((34.0 - np.nan_to_num(age, nan=30)) / 4.0, 0, 1) * np.clip(np.nan_to_num(col(R, "e_x_top12_6y")) / 2, 0, 1)
    # a QB who has played well when healthy: fantasy PPG over the QB line (15.7; +2 = full) in last season (6+ games) or this one (4+)
    ppg_l0 = np.nan_to_num(col(R, "e_x_l0_xfp_pg") + col(R, "e_x_l0_fpoe_pg"), nan=0) * (np.nan_to_num(col(R, "e_x_l0_games")) >= 6)
    ppg_c = np.nan_to_num(col(R, "e_x_cur_xfp_pg") + col(R, "e_x_cur_fpoe_pg"), nan=0) * (cur_gp >= 4)
    qb_played = (R.pos.values == "QB") * np.clip((np.fmax(ppg_l0, ppg_c) - 15.7) / 2.0, 0, 1)
    # efficiency early in a career: points over expected per touch and rush yards over expected, last full season + this one
    ft = _rowmean(col(R, "e_x_l0_fpoe_touch"), np.where(cur_gp >= 3, col(R, "e_x_cur_fpoe_touch"), np.nan))
    ry = _rowmean(col(R, "e_x_l0_ryoe"), np.where(cur_gp >= 3, col(R, "e_x_cur_ryoe"), np.nan))
    eff = 0.5 * np.clip(np.nan_to_num(ft) / 0.15, -1, 1.5) + 0.5 * np.clip(np.nan_to_num(ry) / 0.8, -1, 1.5)
    efficiency = eff * early * (R.pos.values != "QB")
    # an opening: the top same-position teammate is 28+ and holds the snaps (aging competition), for young players
    opening = np.clip((np.nan_to_num(col(R, "e_x_comp_age")) - 27) / 3, 0, 1) * np.clip(np.nan_to_num(col(R, "e_x_comp_share")) / 0.6, 0, 1) * youth
    # team strength: win % (this season, with last season as prior), last season's playoff depth, implied points from the lines
    wcur, wl0 = col(R, "e_x_team_win_cur"), col(R, "e_x_team_win_l0")
    win = np.where(np.isnan(wcur), wl0, np.where(np.isnan(wl0), wcur, (wcur * np.clip(cur_gp, 0, 17) + wl0 * 6) / (np.clip(cur_gp, 0, 17) + 6)))
    imp = np.where(np.isnan(col(R, "e_x_team_implied_cur")), col(R, "e_x_team_implied_l0"), col(R, "e_x_team_implied_cur"))
    team_q = np.nan_to_num((win - 0.5) / 0.25) * 0.4 + np.nan_to_num(col(R, "e_x_team_depth_l0")) / 5 * 0.3 + np.nan_to_num((imp - 22) / 4) * 0.3
    # a new team, and a bigger share of it than last year's role (the new role is the information)
    sh_c, sh_0 = col(R, "e_x_cur_xfp_share"), col(R, "e_x_l0_xfp_share")
    new_team_burst = np.nan_to_num(col(R, "e_x_new_team")) * np.clip(np.nan_to_num(sh_c - sh_0) / 0.12, 0, 1.5) * (cur_gp >= 3)
    # talent independent of the offense: share of the team's expected points over three seasons
    shb = _rowmean(np.where(cur_gp >= 3, sh_c, np.nan), sh_0, col(R, "e_x_l1_xfp_share"))
    share_talent = np.where(R.pos.isin(["WR", "TE", "RB"]).values, np.clip(np.nan_to_num(shb, nan=0.12) - 0.15, -0.1, 0.15) / 0.08, 0.0)
    # availability over an extended period: games played out of games available this season and the last two, any reason
    # (injury, suspension); seasons before a player's NFL start don't count
    has_c = ~np.isnan(col(R, "e_x_cur_games")); tg = col(R, "e_x_team_games_cur")
    s_c = np.where(has_c, cur_gp, 0); n_c = np.where(has_c, np.clip(np.where(np.isnan(tg), cur_gp, tg), 0, 18), 0)
    g0_, g1_ = col(R, "e_x_l0_games"), col(R, "e_x_l1_games"); e0 = (exp_ >= 1) | ~np.isnan(g0_); e1 = (exp_ >= 2) | ~np.isnan(g1_)
    played = s_c + np.where(e0, np.nan_to_num(g0_), 0) + np.where(e1, np.nan_to_num(g1_), 0)
    avail_n = n_c + np.where(e0, 17, 0) + np.where(e1, 17, 0)
    avail = np.where(avail_n >= 17, played / np.maximum(avail_n, 1), np.nan)
    availability = np.where(np.isnan(avail), 0.0, np.clip((avail - 0.85) / 0.15, -3, 1))
    # the same, leaving out this season (when the IR rule is already charging for this season's injury)
    pn = played - s_c; an = avail_n - n_c
    avail_prior = np.where(an >= 17, np.clip((pn / np.maximum(an, 1) - 0.85) / 0.15, -3, 1), 0.0)
    posv = R.pos.values
    # positional scarcity: an RB with top finishes over several seasons is harder to find than a WR
    rb_multi = (posv == "RB") * np.clip((np.nan_to_num(col(R, "e_x_top5_6y")) + np.nan_to_num(col(R, "e_x_streak5"))) / 4, 0, 1.5)
    # receiver talent independent of the offense: yards and targets per route (last two full seasons), separation, top-5 seasons
    yp = _rowmean(col(R, "e_x_l0_yprr"), col(R, "e_x_l1_yprr")); tp = col(R, "e_x_l0_tprr")
    sp_ = _rowmean(col(R, "e_x_l0_sep"), np.where(cur_gp >= 3, col(R, "e_x_cur_sep"), np.nan))
    wr_talent_raw = np.isin(posv, ["WR", "TE"]) * np.clip(0.35 * np.nan_to_num((yp - 2.0) / 0.6) + 0.2 * np.nan_to_num((tp - 0.22) / 0.05)
                                                    + 0.2 * np.nan_to_num((sp_ - 2.8) / 0.4) + 0.25 * np.nan_to_num(col(R, "e_x_top5_6y")) / 3, -1, 2)
    # count talent only beyond what the player already produces (no double count for a star on a good offense)
    prod_z = np.clip(usage, -1, 2)
    wr_talent = np.clip(wr_talent_raw - prod_z, 0, 2)
    # a top pick finally playing as advertised: this season's points per game above his own last season (upswings only)
    fp_c = col(R, "e_x_cur_xfp_pg") + col(R, "e_x_cur_fpoe_pg"); fp_0 = col(R, "e_x_l0_xfp_pg") + col(R, "e_x_l0_fpoe_pg")
    pk = col(R, "e_x_draft_pick"); top_pick = np.where(np.isnan(pk), 0, np.clip((16 - pk) / 15, 0, 1))
    pick_boom = top_pick * (exp_ <= 4) * np.where((cur_gp >= 3) & ~np.isnan(fp_c) & ~np.isnan(fp_0), np.clip((fp_c - fp_0) / 6, 0, 1.5), 0.0)
    # RBs fall off a cliff from 29, whatever their value
    # ... and it is the hurt ones who fall: scaled by injury history and being hurt now (a durable, healthy vet RB holds up)
    hurt = 0.3 + 0.7 * np.clip(np.nan_to_num(col(R, "e_x_inj_rate_2y")) / 0.15, 0, 2) + 0.7 * np.isin(inj, ["IR", "PUP", "Out", "Doubtful"])
    rb_age = (posv == "RB") * np.clip((np.nan_to_num(age, nan=25) - 28.5) / 2, 0, 1.5) * hurt
    # a high-drafted rookie keeps his draft value through his rookie season
    rookie_capital = (exp_ == 0) * np.where(np.isnan(pk), 0, np.clip((64 - pk) / 63, 0, 1))
    # the team's top target: leading target share (this season with last as prior)
    tsc, ts0 = col(R, "e_x_cur_tgt_share"), col(R, "e_x_l0_tgt_share")
    tsb = np.where(np.isnan(tsc), ts0, np.where(np.isnan(ts0), tsc, (tsc * cur_gp + ts0 * 4) / (cur_gp + 4)))
    alpha = np.isin(posv, ["WR", "TE"]) * np.clip(np.nan_to_num(tsb - 0.18) / 0.07, 0, 1.5)
    # off the field: out of the league / unsigned after June 1 / a dated off-field event, plus the share of a season suspended
    off_field = np.clip(np.nan_to_num(col(R, "e_x_career_over")) + np.nan_to_num(col(R, "e_x_unsigned")) + np.nan_to_num(col(R, "e_x_offfield")), 0, 1)
    off_field = np.maximum(off_field, 0.5 * np.nan_to_num(col(R, "e_x_suspended")))
    # journeyman QB: 27+ with at most one full season as a starter in the last four (a dime a dozen)
    journeyman = (posv == "QB") * (np.nan_to_num(col(R, "e_x_qb_full_4y")) <= 1) * np.clip((np.nan_to_num(age, nan=25) - 26) / 2, 0, 1)
    # bust: nothing as a rookie and nothing again in year two (both well below replacement usage), and no breakout now
    xl1 = col(R, "e_x_l1_xfp_pg"); best2 = np.fmax(np.nan_to_num(xl, nan=0), np.nan_to_num(xl1, nan=0))
    bust = (posv != "QB") * (exp_ >= 2) * (exp_ <= 4) * np.clip((rep - 3 - best2) / 4, 0, 1) * (1 - np.clip(spike / 0.5, 0, 1))
    # low lows: week-to-week volatility and TD dependence, this season and the last two (big weeks are counteracted by these)
    cv = _rowmean(np.where(cur_gp >= 4, col(R, "e_x_cur_ppr_cv"), np.nan), col(R, "e_x_l0_ppr_cv"), col(R, "e_x_l1_ppr_cv"))
    tds = _rowmean(np.where(cur_gp >= 4, col(R, "e_x_cur_td_share"), np.nan), col(R, "e_x_l0_td_share"), col(R, "e_x_l1_td_share"))
    boom_bust = (posv != "QB") * np.clip((np.nan_to_num(cv, nan=0.5) - 0.5) / 0.25, 0, 1.5)
    td_base = np.where(posv == "RB", 0.38, 0.25)                 # an RB's normal TD share is higher (goal-line role)
    td_dep = (posv != "QB") * np.clip((np.nan_to_num(tds, nan=0.2) - td_base) / 0.15, 0, 1.5)
    # one game carrying a season: share of points from the best game (this season by games played, with last season as prior)
    tg_c, tg_0 = col(R, "e_x_cur_top_game_share"), col(R, "e_x_l0_top_game_share")
    wc_ = np.where(np.isnan(tg_c), 0, np.clip(cur_gp, 0, 17)); w0_ = np.where(np.isnan(tg_0), 0, 6.0 * np.clip(np.nan_to_num(col(R, "e_x_l0_games")) / 10, 0, 1))
    tgs = (np.nan_to_num(tg_c) * wc_ + np.nan_to_num(tg_0) * w0_) / np.maximum(wc_ + w0_, 1e-9)
    one_game = (posv != "QB") * np.where(wc_ + w0_ > 0, np.clip((tgs - 0.15) / 0.15, 0, 1.5), 0.0)
    # a young multi-season starter: seasons finishing as a positional starter (top-24 RB / 30 WR / 12 TE / 16 QB) in the last three,
    # plus this season on pace (by expected points), while still young ("a three-year track record" and under 25)
    on_pace = np.where(cur_gp >= 4, (np.nan_to_num(col(R, "e_x_cur_xfp_pg")) >= R.pos.map({"QB": 17, "RB": 11.5, "WR": 11.5, "TE": 8}).fillna(12).values).astype(float), 0.0)
    young_starter = np.clip((np.nan_to_num(col(R, "e_x_starter_3y")) + on_pace) / 3, 0, 1.3) * np.clip((27.0 - np.nan_to_num(age, nan=27)) / 3, 0, 1)
    # carrying a weak offense: team share counts more when the offense's implied points are low ("doing it with a much worse offense")
    imp_ = np.where(np.isnan(col(R, "e_x_team_implied_cur")), col(R, "e_x_team_implied_l0"), col(R, "e_x_team_implied_cur"))
    carry = np.clip(np.nan_to_num(col(R, "e_x_cur_xfp_share"), nan=0.0) / 0.2, 0, 1.5) * np.clip((23.0 - np.nan_to_num(imp_, nan=23)) / 3, 0, 1) * (posv != "QB") * np.clip(usage / 0.25, 0, 1)   # only with real usage
    return dict(_ya=youth_age, usage_h=usage_h, xfp_zh=xfp_hb - rep, youth_usage_h=youth * np.clip(usage_h, 0, 3) / 3, qb_played=qb_played, avail_prior=avail_prior, qb_starter=qb_starter, qb_pedigree=qb_pedigree, young_starter=young_starter, carry=carry, one_game=one_game, boom_bust=boom_bust, td_dep=td_dep, off_field=off_field, journeyman=journeyman, bust=bust, rb_multi=rb_multi, wr_talent=wr_talent, pick_boom=pick_boom, rb_age=rb_age, rookie_capital=rookie_capital, alpha=alpha,
                availability=availability, efficiency=efficiency, opening=opening, team_q=np.clip(team_q, -1.5, 1.5), new_team_burst=new_team_burst, share_talent=share_talent,
                xfp_z=xfp_z, qbq=qbq, elite=elite, track=track, recurring=recurring, steady=steady, pedigree=pedigree, spike=np.clip(spike / 0.5, 0, 1.5) * (1 - 0.4 * np.clip(boom_bust_early(R, cur_gp), 0, 1.5)) * (R.pos.values != "QB") * np.clip((29.0 - np.nan_to_num(age, nan=30)) / 3.0, 0, 1), team_up=trend, severe=severe.astype(float), usage=usage, youth_usage=youth * np.clip(usage, 0, 3) / 3, youth_role=youth * role, two_way=two_way, aw_college=np.clip(np.nan_to_num(awc), 0, 2) * early,
                aw_nfl=np.clip(np.nan_to_num(awn), 0, 3), prone=np.nan_to_num(col(R, "e_x_inj_rate_2y")),
                ir=np.isin(inj, ["IR", "PUP"]).astype(float), out=np.isin(inj, ["Out", "Doubtful"]).astype(float),
                te=(R.pos.values == "TE").astype(float), vet_age=np.clip((np.nan_to_num(age, nan=25) - R.pos.map(VET_AGE).fillna(30).values) / 2, 0, 1),
                un=np.nan_to_num(col(R, "un_x")))
RULE_KEYS = {"qb_starter": "qb_starter", "qb_pedigree": "qb_pedigree", "young_starter": "young_starter", "carry": "carry", "one_game": "one_game", "boom_bust": "boom_bust", "td_dep": "td_dep", "off_field": "off_field", "journeyman": "journeyman", "bust": "bust", "rb_multi": "rb_multi",
             "wr_talent": "wr_talent", "pick_boom": "pick_boom", "rb_age": "rb_age", "rookie_capital": "rookie_capital", "alpha": "alpha",
             "availability": "availability", "efficiency": "efficiency", "opening": "opening", "team_q": "team_q", "new_team_burst": "new_team_burst",
             "share_talent": "share_talent", "recurring": "recurring", "steady": "steady", "pedigree": "pedigree", "elite_streak": "elite", "track": "track",
             "qb_quality": "qbq", "severe": "severe", "usage": "usage", "youth_usage": "youth_usage", "youth_role": "youth_role", "two_way": "two_way",
             "aw_college": "aw_college", "aw_nfl": "aw_nfl", "prone": "prone", "inj_ir": "ir", "inj_out": "out"}
def apply_rules(R, p, X=None, explain=False):
    """base value -> curve/level -> aging-vet discount -> sum of rule terms (log multipliers) -> usage anchor -> top compression.
    explain=True also returns each rule's log multiplier and the stage values (what the board breakdown prints)."""
    if X is None or X.get("_ya") != p.get("youth_age", 26.0):
        with warnings.catch_warnings():          # all-NaN rows (no stats of that kind yet) are expected
            warnings.simplefilter("ignore", RuntimeWarning)
            X = characteristics(R, p.get("youth_age", 26.0))
    raw = np.maximum(col(R, "V_raw"), 0)
    xk = np.log1p([0, 40, 200, 450, 650, 1000, 1500, 2500, 3500]); yk = np.log1p([0, 40, p["y200"], p["y450"], p["y650"], 1000, 1500, 2500, 3500])
    v0 = p["lvl"] * np.where(raw >= 3500, raw, np.expm1(np.interp(np.log1p(raw), xk, yk)))
    v = v0 * (1 - (1 - p["vet"]) * X["vet_age"] * np.clip((p["vet_hi"] - v0) / (0.55 * p["vet_hi"]), 0, 1))
    v1 = v; lv = np.log(np.maximum(v, 1)); pos = R.pos.values
    curve = lambda lo, hi: np.interp(lv, np.log([150, 400, 900, 1800, 3000]), [lo, lo * 0.5, 0, hi * 0.5, hi])   # TE curve: ends move, middle stays
    top_curve = lambda lo, hi: np.interp(lv, np.log([150, 400, 900, 3000, 5000]), [lo, lo * 0.5, 0, 0, hi])   # QB/RB/WR: top end only above $3,000
    unpriced = np.clip((p.get("spike_hi", 1500) - v) / (0.6 * p.get("spike_hi", 1500)), 0, 1)     # a breakout the base value has not priced in
    T_ = {k: p.get(k, 0) * X[x] for k, x in RULE_KEYS.items()}
    # on IR the IR rule already charges for this season's injury: availability counts only the seasons before it
    T_["availability"] = np.where(X["ir"] > 0, (1 - p.get("ir_no_double", 0.0)) * T_["availability"] + p.get("ir_no_double", 0.0) * p.get("availability", 0) * X["avail_prior"], T_["availability"])
    nd = p.get("ir_no_double", 0.0) * X["ir"]                       # on IR: the healthy role (prior seasons) stands in for this season
    T_["usage"] = p.get("usage", 0) * ((1 - nd) * X["usage"] + nd * X["usage_h"])
    T_["youth_usage"] = p.get("youth_usage", 0) * ((1 - nd) * X["youth_usage"] + nd * X["youth_usage_h"])
    T_["qb_opening"] = p.get("qb_opening", 0.0) * X["qb_played"] * X["opening"]   # a young QB who has played well (PPG over the QB line), competition only an aging backup
    T_["spike"] = p.get("spike", 0) * X["spike"] * unpriced; T_["team_up"] = p.get("team_up", 0) * X["team_up"] * unpriced
    T_["position curve"] = X["te"] * curve(p["te_lo"], p["te_hi"]) + np.select([pos == "QB", pos == "RB", pos == "WR"], [top_curve(p["qb_lo"], p["qb_hi"]), top_curve(p["rb_lo"], p["rb_hi"]), top_curve(p["wr_lo"], p["wr_hi"])], 0.0)
    T_["no NFL team"] = -UK * X["un"]
    # replacement level: a veteran (4th season on) ranked near or below the line is a waiver-wire body worth ~0;
    # players in their first three seasons keep their upside value
    if "rank_raw" in R:
        n_ = col(R, "line_n"); vetr = (np.nan_to_num(col(R, "exp")) >= 3)
        T_["replacement line"] = -p.get("bubble", 0.0) * np.nan_to_num(vetr * np.clip((col(R, "rank_raw") - p.get("line_frac", 0.8) * n_) / (0.25 * n_), 0, 1.5))
    v = v * np.exp(sum(T_.values()))
    # usage anchor: pull part of the way toward the value the current role implies (history-built values drift to what a player does now)
    w = p.get("anchor_w", 0.0)
    ndz = p.get("ir_no_double", 0.0) * X["ir"]; z = np.where(np.isnan(X["xfp_zh"]), X["xfp_z"], (1 - ndz) * np.nan_to_num(X["xfp_z"]) + ndz * X["xfp_zh"])
    z = np.where(np.isnan(X["xfp_z"]) & (ndz == 0), np.nan, z)
    u = 50.0 * np.exp(p.get("anchor_slope", 0.5) * np.clip(np.nan_to_num(z, nan=0.0), -3, 12))
    v2 = np.where(np.isnan(z) | (w <= 0), v, np.exp((1 - w) * np.log(np.maximum(v, 1)) + w * np.log(u)))
    out = np.where(v2 > 2000, 2000 * (np.maximum(v2, 2000) / 2000) ** p["top_g"], v2)
    if explain:
        return out, T_, dict(base=raw, curve=v0, vet=v1, rules=v, anchor=v2, final=out)
    return out

# ------------------------------------------------------------------ inputs and evidence
REG_KEYS = ["qb_starter", "qb_pedigree", "ir_no_double", "qb_opening", "young_starter", "carry", "one_game", "boom_bust", "td_dep", "off_field", "journeyman", "bust", "rb_multi", "wr_talent", "pick_boom", "rb_age",
            "rookie_capital", "alpha", "availability", "efficiency", "opening", "team_q", "new_team_burst", "share_talent", "recurring", "steady", "pedigree",
            "elite_streak", "track", "qb_quality", "spike", "team_up", "severe", "qb_lo", "qb_hi", "rb_lo", "rb_hi", "wr_lo", "wr_hi", "usage", "youth_usage",
            "youth_role", "te_lo", "te_hi", "inj_ir", "inj_out", "prone", "two_way", "aw_college", "aw_nfl"]
W_TRADES, W_CUTS = 3.0, 3.0      # trade/cut history counts more than one person's calls


def load_inputs(data=DATA):
    R = pd.read_csv(Path(data) / "inputs.csv", dtype={"sid": str, "injury": str}, keep_default_na=False, na_values=[""])
    R["injury"] = R.injury.fillna("")
    return R


def load_params(path=None):
    p = json.load(open(path or DATA / "params.json"))
    return dict(P0, **{k: float(v) for k, v in p.items() if k in P0})


class Evidence:
    """the rows a fit reads: today's board (one row per name) and the trade/cut rows, with their structure"""

    def __init__(self, R, ev):
        self.as_of = pd.Timestamp(ev["as_of"])
        key = {(s, d): i for i, (s, d) in enumerate(zip(R.sid.values, R.date.values))}
        self.calls_date = ev.get("calls_date") or ev["as_of"]      # the league's calls are judged on the board they were about
        self.T = R[R.date == self.calls_date].drop_duplicates("name").reset_index(drop=True)
        rows = sorted({key[tuple(k)] for k in ev["cuts"]} | {key[tuple(k)] for t in ev["trades"] for s in t["sides"] for k in s["players"]})
        pos = {i: j for j, i in enumerate(rows)}
        self.E = R.iloc[rows].reset_index(drop=True)
        self.trades = [(t["date"], [(s["other_value"], [pos[key[tuple(k)]] for k in s["players"]]) for s in t["sides"]]) for t in ev["trades"]]
        self.cuts = np.array([pos[key[tuple(k)]] for k in ev["cuts"]], dtype=int)
        # boards the rating-page votes were asked on: board date -> the inputs' grid date holding its rows
        self.vote_dates = {str(pd.Timestamp(ev["as_of"]).date()): ev["as_of"], **ev.get("vote_dates", {})}
        self.VR = R[R.date.isin(set(self.vote_dates.values()))].drop_duplicates(["sid", "date"]).reset_index(drop=True)

    def vote_values(self, v):
        """values of the vote rows (aligned with VR) as {(board date, sid): value}"""
        by = {}
        for (sid, d), x in zip(zip(self.VR.sid.values, self.VR.date.values), v): by.setdefault(d, {})[sid] = float(x)
        return {(bd, sid): x for bd, gd in self.vote_dates.items() for sid, x in by.get(gd, {}).items()}

    @classmethod
    def load(cls, data=DATA):
        return cls(load_inputs(data), json.load(open(Path(data) / "evidence.json")))


def trade_err(V, trades):
    """median + mean |log ratio| of the two sides' totals (each side: its players' values + FAAB/picks, +25)"""
    r = np.array([np.log((a[0] + V[a[1]].sum() + 25) / (b[0] + V[b[1]].sum() + 25)) for _, (a, b) in trades])
    return float(np.median(np.abs(r)) + np.mean(np.abs(r))), r


def cut_err(V, cuts):
    """cuts valued over $100 the day before, in log units above $100 (capped at 2)"""
    return float(np.mean(np.minimum(np.maximum(0, np.log(V[cuts] / 100)), 2)))


def board(R, p, as_of=None):
    """the as-of date's board: one row per name, ranked by value"""
    as_of = as_of or R.date.max()
    T = R[R.date == as_of].drop_duplicates("name").copy()
    T["V"] = apply_rules(T, p)
    T = T.sort_values("V", ascending=False).reset_index(drop=True)
    T["rank"] = np.arange(1, len(T) + 1)
    return T


def explain(R, p, names):
    """each rule's multiplier and the stage values for the named players (what moved them, and how far)"""
    T = R[R.name.isin(names)].drop_duplicates("name").reset_index(drop=True)
    out, terms, stages = apply_rules(T, p, explain=True)
    rows = []
    for i, n in enumerate(T.name):
        t = {k: float(np.exp(v[i])) for k, v in terms.items() if abs(v[i]) > 0.005}
        rows.append(dict(name=n, **{f"${k}": round(float(v[i])) for k, v in stages.items()}, rules=dict(sorted(t.items(), key=lambda kv: -abs(np.log(kv[1]))))))
    return rows


def _norm(s): return " ".join("".join(c for c in s.lower() if c.isalnum() or c == " ").split())


def _initials(name, q):
    """q is the name's initials, the last word allowed a longer start: "cmc" Christian McCaffrey, "jsn" Jaxon Smith-Njigba"""
    w = _norm(name.replace("-", " ")).split()
    return len(w) >= 2 and len(q) > len(w) - 1 and q[:len(w) - 1] == "".join(x[0] for x in w[:-1]) and w[-1].startswith(q[len(w) - 1:])


def match_names(names, query, n=5):
    """board names for a typed query, best first: exact (ignoring case and punctuation, so "aj brown" is A.J. Brown),
else every name containing it ("Etienne" -> both), else initials ("CMC" -> Christian McCaffrey), else close spellings
("Jaxon Dart" -> Jaxson Dart). [] = no close name"""
    import difflib
    by = {}
    for x in names: by.setdefault(_norm(x), x)
    q = _norm(query)
    if q in by: return [by[q]]
    sub = [x for k, x in by.items() if q and q in k]
    ini = [x for x in by.values() if " " not in q and _initials(x, q)] if not sub else []
    return (sub or ini or [by[k] for k in difflib.get_close_matches(q, list(by), n, 0.6)])[:n]


# ------------------------------------------------------------------ fit
def objective(ev, ref, votes=None, band=True):
    """the fit's score for a parameter set: calls + 3 x trade error + 3 x cut penalty + capped votes + a light
    pull of every rule strength toward zero (a rule has to earn its strength)"""
    from . import faab_calls as LC
    T, E, VR = ev.T, ev.E, ev.VR
    qbs = set(T.name[T.pos == "QB"]); exp_ = pd.Series(T.exp.values, index=T.name.values) if band else None
    cache = {}

    def obj(p, detail=False):
        ya = p.get("youth_age", 26.0)
        if ya not in cache:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                cache[ya] = (characteristics(T, ya), characteristics(E, ya), characteristics(VR, ya) if votes is not None else None)
        XT, XE, XV = cache[ya]
        vt = apply_rules(T, p, XT)
        c, t = LC.score(pd.Series(vt, index=T.name.values), ref, qbs, exp=exp_)
        ve = apply_rules(E, p, XE)
        te, ce = trade_err(ve, ev.trades)[0], cut_err(ve, ev.cuts)
        vo = votes.loss(ev.vote_values(apply_rules(VR, p, XV))) if votes is not None and len(votes.C) else 0.0
        reg = 0.02 * sum(abs(p[k]) for k in REG_KEYS)
        tot = c + W_TRADES * te + W_CUTS * ce + vo + reg
        return dict(total=tot, calls=c, trades=te, cuts=ce, votes=vo, reg=reg, tests=t) if detail else tot
    return obj


def _ok(q): return q["y200"] < q["y450"] < q["y650"] < 1000


def fit(obj, starts, restarts=8, passes=3, polish=4, seed=0, log=print):
    """coordinate search over every rule's strength within its sign-locked bounds, perturbed restarts, a polish"""
    p = min(starts, key=obj); best = obj(p); rng = np.random.default_rng(seed)
    log(f"start: total {best:.3f}")
    scale_keys = ("y200", "y450", "y650", "lvl", "vet", "vet_hi", "top_g", "spike_hi", "youth_age")

    def coord(p, best, n):
        for _ in range(n):
            for k, (lo, hi) in BOUNDS.items():
                for x in np.linspace(lo, hi, 13):
                    q = dict(p, **{k: float(x)})
                    if not _ok(q): continue
                    e = obj(q)
                    if e < best: best, p = e, q
        return p, best
    gbest, gp = best, p
    for rs in range(restarts):
        q = {k: float(np.clip(v * np.exp(rng.normal(0, 0.3)) if k in scale_keys else v + rng.normal(0, 0.25), *BOUNDS[k])) for k, v in gp.items()}
        if not _ok(q): q = dict(gp)
        q, e = coord(q, obj(q), passes)
        log(f"restart {rs + 1}: {e:.3f} (best {min(e, gbest):.3f})")
        if e < gbest: gbest, gp = e, q
    p, best = gp, gbest
    for it in range(polish):
        p, best = coord(p, best, 1)
        for _ in range(400):
            q = {k: float(np.clip(v * np.exp(rng.normal(0, 0.08)) if k in scale_keys[:7] else v + rng.normal(0, 0.08), *BOUNDS[k])) for k, v in p.items()}
            if not _ok(q): continue
            e = obj(q)
            if e < best: best, p = e, q
        d = obj(p, True)
        log(f"pass {it + 1}: total {d['total']:.3f} | calls {d['calls']:.3f} ({sum(x == 0 for _, x in d['tests'])}/{len(d['tests'])} pass) "
            f"| trades {d['trades']:.3f} | cuts {d['cuts']:.3f} | votes {d['votes']:.3f}")
    return p
