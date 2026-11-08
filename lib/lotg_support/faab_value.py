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
          youth_role=0.0, te_lo=0.0, te_hi=0.0, inj_ir=0.0, inj_out=0.0, prone=0.0, two_way=0.0, aw_college=0.0, aw_nfl=0.0, usage=0.0, youth_usage=0.0, qb_lo=0.0, qb_hi=0.0, rb_lo=0.0, rb_hi=0.0, wr_lo=0.0, wr_hi=0.0, youth_age=26.0, spike=0.0, team_up=0.0, severe=0.0, spike_hi=1500.0, anchor_w=0.0, anchor_slope=0.5, qb_quality=0.0, elite_streak=0.0, track=0.0, recurring=0.0, steady=0.0, pedigree=0.0, efficiency=0.0, opening=0.0, team_q=0.0, new_team_burst=0.0, share_talent=0.0, availability=0.0, rb_multi=0.0, wr_talent=0.0, pick_boom=0.0, rb_age=0.0, rookie_capital=0.0, alpha=0.0, off_field=0.0, journeyman=0.0, bust=0.0, bubble=0.0, line_frac=0.8, summer=0.0, te_line=0.0, regress=0.0, te_thr=11.0, te_soft=0.0, te_thr2=9.0, te_relief=0.0, te_pv16=0.0, old_cliff=0.0, rec_age=0.0, avail_up=0.0, share_age=0.0, anchor_old=0.0, rookie_day3=0.0, vet_move=0.0, ypc_bad=0.0, duds=0.0, peak_share=0.0, slump=0.0, boom_week=0.0, boom_hi=600.0, fresh_start=0.0, rookie_backup=0.0, draft_comp=0.0, cheap_deal=0.0, undrafted=0.0, te_one_off=0.0, team_q_lo=0.0, qb_paid=0.0, avail_young_floor=0.0, avail_young_age=24.0, share_old_cap=99.0, share_old_age=30.0, wr_pair=0.0, young_upside=0.0, lag_cap=99.0, lag_floor=0.0, overtaken=0.0)
BOUNDS = dict(y200=(80, 230), y450=(250, 520), y650=(500, 950), lvl=(0.6, 1.6), vet=(0.2, 1.0), vet_hi=(600, 3500), top_g=(0.45, 0.85),
              youth_role=(-0.5, 2.0), te_lo=(-1.5, 0.8), te_hi=(-1.0, 0.6), inj_ir=(-1.0, 0.3), inj_out=(-0.8, 0.3), prone=(-2.5, 0.5),
              two_way=(0.0, 2.5), aw_college=(-0.3, 1.5), aw_nfl=(-0.3, 1.0), usage=(-0.3, 1.5), youth_usage=(-0.3, 2.0), qb_lo=(-0.5, 0.4), qb_hi=(-0.6, 0.6), rb_lo=(-0.5, 0.15), rb_hi=(-0.6, 0.6), wr_lo=(-0.5, 0.15), wr_hi=(-0.6, 0.6), youth_age=(24.5, 29.0), spike=(-0.5, 2.0), team_up=(-0.5, 1.0), severe=(-1.5, 0.3), spike_hi=(500.0, 3000.0), anchor_w=(0.0, 0.7), anchor_slope=(0.2, 0.9), qb_quality=(-0.5, 2.0), elite_streak=(0.0, 1.5), track=(-0.3, 1.0), recurring=(-0.6, 0.2), steady=(-0.3, 1.0), pedigree=(-0.3, 1.0), efficiency=(-0.3, 1.2), opening=(-0.3, 1.2), team_q=(-0.3, 0.8), new_team_burst=(-0.3, 1.2), share_talent=(-0.3, 1.2), availability=(0.0, 1.5), rb_multi=(-0.3, 1.0), wr_talent=(-0.3, 1.0), pick_boom=(-0.3, 1.5), rb_age=(-1.2, 0.2), rookie_capital=(-0.3, 1.5), alpha=(-0.3, 1.0), off_field=(-5.0, 0.0), journeyman=(-2.0, 0.3), bust=(-2.0, 0.3), bubble=(0.0, 4.0), line_frac=(0.4, 1.1), summer=(-1.5, 0.5), te_line=(-3.0, 0.0), regress=(0.0, 1.0), te_thr=(9.5, 13.0), te_soft=(-3.0, 0.0), te_thr2=(7.0, 10.0), te_relief=(0.0, 1.0), te_pv16=(0.0, 1.0), old_cliff=(-3.0, 0.0), rec_age=(0.0, 1.0), avail_up=(0.0, 1.5), share_age=(0.0, 1.0), anchor_old=(0.0, 0.7), rookie_day3=(-3.0, 0.0), vet_move=(-2.0, 0.0), ypc_bad=(-2.0, 0.0), duds=(-1.5, 0.0), peak_share=(0.0, 1.5), slump=(-1.5, 0.0), boom_week=(0.0, 1.5), boom_hi=(300.0, 1500.0), fresh_start=(0.0, 4.0), rookie_backup=(-2.0, 0.0), draft_comp=(-2.5, 0.0), cheap_deal=(-2.5, 0.0), undrafted=(-2.5, 0.0), overtaken=(-2.5, 0.0), wr_pair=(-3.0, 0.0), lag_cap=(1.5, 99.0), lag_floor=(0.0, 500.0), young_upside=(0.0, 1.5), te_one_off=(-2.5, 0.0), team_q_lo=(0.0, 1.5), qb_paid=(0.0, 2.5))
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
RAISE_ONLY = ["young_upside", "qb_paid", "team_q_lo", "fresh_start", "boom_week", "aw_nfl", "aw_college", "usage", "steady", "youth_usage", "youth_role", "elite_streak", "track", "qb_quality", "wr_talent", "rb_multi", "efficiency",
              "pedigree", "rookie_capital", "alpha", "availability", "pick_boom", "new_team_burst", "team_up", "two_way", "share_talent", "spike", "team_q", "opening",
              "young_starter", "carry", "qb_pedigree", "qb_starter", "qb_opening", "peak_share", "avail_up"]
LOWER_ONLY = ["wr_pair", "overtaken", "te_one_off", "undrafted", "cheap_deal", "draft_comp", "rookie_backup", "te_line", "te_soft", "old_cliff", "rookie_day3", "vet_move", "ypc_bad", "duds", "slump", "inj_ir", "inj_out", "severe", "prone", "recurring", "off_field", "journeyman", "bust", "rb_age", "boom_bust", "td_dep", "one_game"]
_bad = [k for k in RAISE_ONLY if BOUNDS[k][0] < 0] + [k for k in LOWER_ONLY if BOUNDS[k][1] > 0]
assert not _bad, f"rules with the wrong sign allowed: {_bad}"
VET_AGE = {"QB": 33, "RB": 26.5, "WR": 28.5, "TE": 28.5}
AGE_WALL = {"QB": 99, "RB": 30, "WR": 31, "TE": 32}     # past this, a declining player's value goes whatever his record (old_cliff, rec_age);
                                                         # not QBs (the superflex QB rules carry their own age fade, and the calls hold old QBs up)
UK = 2.5     # no NFL team (off every depth chart, no games, not hurt): x0.08
def col(R, c): return R[c].values.astype(float) if c in R else np.full(len(R), np.nan)
UPSIDE_EXP = 2       # young_upside: a player in his first three seasons
OVR_AGE = 29.0      # "an aging veteran who loses his role to a rookie": full from this age, none 2 years younger
BACKUP_POS = ("RB",)
DEAL_CHEAP = {"RB": 0.03, "WR": 0.04, "TE": 0.03}     # APY share of the cap: a backup's deal at or under this ...
DEAL_FULL = {"RB": 0.015, "WR": 0.015, "TE": 0.01}      # ... and a minimum-level deal (full)


def rookie_backup(R, exp_):
    """a non-rookie RB whose team just added a same-position rookie the league paid for (e_x_rookie_backup: draft price,
    Week-1 waiver bids x4; $250 = 1, capped at 2). Early in the season (his first 4 games, fading out by 8) a drop in his
    own carries / targets / snaps vs last season (e_x_rookie_backup_held under 0.9; 0.6 = full) raises it up to 1.5x;
    later, keeping his workload (held 0.75 -> 0.95) fades it out: the vet kept the job. Low rookie usage never dampens it."""
    sp = np.clip(np.nan_to_num(col(R, "e_x_rookie_backup")) / 250.0, 0, 2.0)
    h = col(R, "e_x_rookie_backup_held"); gp = np.nan_to_num(col(R, "e_x_cur_games"))
    early = 1 - np.clip((gp - 4) / 4.0, 0, 1)
    amp = 1 + 0.5 * early * np.where(np.isnan(h), 0, np.clip((0.9 - np.nan_to_num(h)) / 0.3, 0, 1))
    fade = 1 - (1 - early) * np.where(np.isnan(h), 0, np.clip((np.nan_to_num(h) - 0.75) / 0.2, 0, 1))
    return np.isin(R.pos.values, BACKUP_POS) * (exp_ >= 1) * sp * amp * fade


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
    # this season's usage fades in over his first 4 games (w4: 1 game = 25%, 4+ = all of it) where a rule switches from
    # last season's number to this season's, so week 3 is not priced on last season alone and week 4 is not a jump
    w4 = np.where(np.isnan(col(R, "e_x_cur_xfp_pg")), 0.0, np.clip(cur_gp / 4.0, 0, 1))
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
    xfp_z = np.where(g + gl > 0, xfp_b - rep, np.nan)
    # a WR who has not had a starter's role (expected PPG over WR replacement) last season, the one before, or so far
    # this season (2+ games): his youth no longer spares him from the replacement line (Osborn 2023)
    _xc2 = np.where(cur_gp >= 2, xc, np.nan)
    _bst = np.fmax(np.fmax(np.nan_to_num(xl, nan=-9), np.nan_to_num(col(R, "e_x_l1_xfp_pg"), nan=-9)), np.nan_to_num(_xc2, nan=-9))
    wr_no_role = ((R.pos.values == "WR") & (_bst > -9) & (_bst < rep) & ~np.isnan(col(R, "e_x_l1_xfp_pg"))).astype(float)                                    # usage above replacement (expected PPG)
    # a veteran TE (4th season on) whose role is below a usage level (expected PPG, fitted as te_thr in apply_rules): a
    # waiver-level body. The usage is this season's, fading in over his first 4 games from the blend; a level, not a rank, because
    # how many TEs hold a real role changes year to year (the shared replacement line ranks every position together,
    # so a TE14 sat well inside it)
    te_x = np.where((R.pos.values == "TE") & (exp_ >= 3) & (g + gl > 0), w4 * np.nan_to_num(xc) + (1 - w4) * xfp_b, np.nan)
    # a proven TE (two of the last four complete seasons at 15+ PPR a game, or last season) gets a softer TE line;
    # te_proven16 is the same at 16+ (apply_rules blends the two by te_pv16, fitted)
    _l0 = np.nan_to_num(col(R, "e_x_ppg_l0"))
    # a super-boom week: his best single game in the last two complete seasons and this one (e_x_max_2y), for a TE
    # under 29 (fading out from 27): 40+ PPR (Oliver: super-boom games only), +8 = full. apply_rules gives it only to
    # cheap players (under boom_hi): a ceiling a low value has not priced in (Pitts' 45.6 in 2025). Every position at
    # 40+ with the same age fade scores slightly worse (total +0.025); with no age fade it lifts old RBs / WRs with one
    # big game (Adams, Evans, Lockett, Derrick Henry: +0.7-1.2). So it is the TE ceiling only
    # a fresh start: a non-QB under 28 (full under 27) who changed teams and followed his head coach there
    # (e_x_coach_follow), with 3+ games at 15+ PPR in the last three seasons (5+ = full): the coach who used him is
    # buying him for a bigger role, so his old role is not the one he moves into (Likely BAL -> NYG with Harbaugh, 2026).
    # Offseason only (e_x_moved_off: March 15 to his first game for the new team); once he plays, his usage prices him
    fresh = (R.pos.values != "QB") * np.nan_to_num(col(R, "e_x_coach_follow")) * np.nan_to_num(col(R, "e_x_moved_off")) * np.clip(28.0 - np.nan_to_num(age, nan=30), 0, 1) \
        * np.clip((np.nan_to_num(col(R, "e_x_g15_3y")) - 2.0) / 3.0, 0, 1)
    boom_week = (R.pos.values == "TE") * np.clip((29.0 - np.nan_to_num(age, nan=30)) / 2.0, 0, 1) * np.clip((np.nan_to_num(col(R, "e_x_max_2y")) - 40.0) / 8.0, 0, 1)
    te_proven = (R.pos.values == "TE") * np.clip(np.fmax(np.nan_to_num(col(R, "e_x_s15_4y")) / 2.0, (_l0 >= 15).astype(float)), 0, 1)
    te_proven16 = (R.pos.values == "TE") * np.clip(np.fmax(np.nan_to_num(col(R, "e_x_s16_4y")) / 2.0, (_l0 >= 16).astype(float)), 0, 1)
    # dud games: in the last two complete seasons, full-role games (50%+ of the snaps) under 5 PPR, for a WR / TE
    # (a boom-or-bust receiver's floor); 2 or fewer is normal, each one past that counts a quarter, 8+ is the cap
    duds = np.isin(R.pos.values, ["WR", "TE"]) * np.clip((np.nan_to_num(col(R, "e_x_duds_2y")) - 2.0) / 4.0, 0, 1.5)
    # a young receiver who has already been a true alpha: his best season's share of the team's expected points
    # (this season fading in over 4 games from last season's, the last two with 8+) at 26.5%+, full by 29.5%, fading out from age 24 to 25 (an
    # alpha share that early is rare; later, the share and usage rules already price it)
    _sc, _s0 = col(R, "e_x_cur_xfp_share"), col(R, "e_x_l0_xfp_share")
    _pk = np.vstack([np.where(np.isnan(_sc), np.nan, w4 * np.nan_to_num(_sc) + (1 - w4) * np.where(np.isnan(_s0), np.nan_to_num(_sc), _s0)),
                     np.where(np.nan_to_num(col(R, "e_x_l0_games")) >= 8, col(R, "e_x_l0_xfp_share"), np.nan),
                     np.where(np.nan_to_num(col(R, "e_x_l1_games")) >= 8, col(R, "e_x_l1_xfp_share"), np.nan)])
    peak_sh = np.nanmax(np.where(np.isnan(_pk), -1, _pk), axis=0)
    peak_share = np.isin(R.pos.values, ["WR", "TE"]) * np.clip((peak_sh - 0.265) / 0.03, 0, 1.5) * np.clip(25.0 - np.nan_to_num(age, nan=30), 0, 1)
    # a young player's slump: his last 10 games (crossing seasons) against the 10 before, in his first four seasons;
    # a 10% drop is noise, a 40% drop is full
    f_l, f_p = col(R, "e_x_form_last"), col(R, "e_x_form_prev")
    slump = (R.pos.values != "QB") * (exp_ <= 3) * np.where(np.isnan(f_l) | np.isnan(f_p), 0.0,
                                                           np.clip(((np.nan_to_num(f_p) - np.nan_to_num(f_l)) / np.maximum(np.nan_to_num(f_p), 5.0) - 0.1) / 0.3, 0, 1.5))
    # regression of an older player (RBs 26 -> 28, others 28 -> 30): the drop in his expected PPG, this season vs last
    # (fading in over his first 4 games), else last season vs the one before; a 30% drop is full. It fades the record-based boosts (see apply_rules)
    # this season fades in by w4: now = w4 x this season + (1 - w4) x last, prev = w4 x last + (1 - w4) x the one before
    # (last season again when there is none before it, so the drop itself fades in)
    x1 = col(R, "e_x_l1_xfp_pg")
    now_ = np.where(w4 > 0, w4 * np.nan_to_num(xc) + (1 - w4) * np.where(np.isnan(xl), np.nan_to_num(xc), xl), xl)
    prev_ = np.where(w4 > 0, w4 * xl + (1 - w4) * np.where(np.isnan(x1), xl, x1), x1)
    drop = np.where(np.isnan(now_) | np.isnan(prev_) | (np.nan_to_num(prev_) <= 0), 0.0, np.clip((prev_ - now_) / np.maximum(prev_, 1e-9) / 0.3, 0, 1))
    # past the age wall a smaller drop is the signal, but it must show in both his usage (15% = full) and his fantasy
    # points per game (5% is noise, 20% = full): a role trimmed while he still scores (or a new team where he scores
    # more) is not a decline. Points (PPR from the game log): this season vs last (fading in over 4 games), else last season vs the one before
    drop_u = np.where(np.isnan(now_) | np.isnan(prev_) | (np.nan_to_num(prev_) <= 0), 0.0, np.clip((prev_ - now_) / np.maximum(prev_, 1e-9) / 0.15, 0, 1))
    pp_c, pp_0, pp_1 = col(R, "e_x_ppg_cur"), col(R, "e_x_ppg_l0"), col(R, "e_x_ppg_l1")
    wp4 = np.where(np.isnan(pp_c), 0.0, np.clip(np.nan_to_num(col(R, "e_x_gp_cur")) / 4.0, 0, 1))      # same fade-in, by games in the log
    pn_ = np.where(wp4 > 0, wp4 * np.nan_to_num(pp_c) + (1 - wp4) * np.where(np.isnan(pp_0), np.nan_to_num(pp_c), pp_0), pp_0)
    pv_ = np.where(wp4 > 0, wp4 * pp_0 + (1 - wp4) * np.where(np.isnan(pp_1), pp_0, pp_1), pp_1)
    drop_p = np.where(np.isnan(pn_) | np.isnan(pv_) | (np.nan_to_num(pv_) <= 0), 0.0, np.clip(((pv_ - pn_) / np.maximum(pv_, 1e-9) - 0.05) / 0.15, 0, 1))
    drop_old = np.minimum(drop_u, drop_p)
    a0 = np.where(R.pos.values == "RB", 26.0, 28.0)
    regress = drop * np.clip((np.nan_to_num(age, nan=25) - a0) / 2.0, 0, 1)
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
    ppg_c = np.nan_to_num(col(R, "e_x_cur_xfp_pg") + col(R, "e_x_cur_fpoe_pg"), nan=0) * w4
    qb_played = (R.pos.values == "QB") * np.clip((np.fmax(ppg_l0, ppg_c) - 15.7) / 2.0, 0, 1)
    # the QB opening is an early-career bet: full in his first two seasons, fading to 0 by his fifth (like QB draft capital)
    qb_early = np.clip((4.0 - np.nan_to_num(exp_, nan=0.0)) / 3.0, 0, 1)
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
    wr_talent = np.isin(posv, ["WR", "TE"]) * np.clip(wr_talent_raw - prod_z, 0, 2)   # (QBs/RBs: their own rule below)
    # a QB or RB in his first three seasons not producing yet: upside the stats have not shown (until 2026-11-08 this leaked into
    # wr_talent for every QB/RB with usage under replacement; now its own rule, young players only)
    young_upside = np.isin(posv, ["QB", "RB"]) * (exp_ <= UPSIDE_EXP) * np.clip(-prod_z, 0, 1)
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
    # the summer (June 1 -> kickoff - 3 days): one level shift for every player against picks and FAAB, which the league
    # prices differently once the draft is done (either sign; 0 on every in-season board)
    summer = np.nan_to_num(col(R, "e_x_offseason"))
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
    return dict(_ya=youth_age, usage_h=usage_h, xfp_zh=xfp_hb - rep, youth_usage_h=youth * np.clip(usage_h, 0, 3) / 3, qb_played=qb_played, old_cliff=np.clip((np.nan_to_num(age, nan=25) - R.pos.map(AGE_WALL).fillna(31).values) / 2.0, 0, 1.5) * drop_old,
                past_wall=np.clip((np.nan_to_num(age, nan=25) - R.pos.map(AGE_WALL).fillna(31).values) / 2.0, 0, 1),
                near_wall=(R.pos.values != "QB") * np.clip((np.nan_to_num(age, nan=25) - R.pos.map(AGE_WALL).fillna(31).values + 2.0) / 2.0, 0, 1),
                # a veteran (27 -> 29) on a new team: signed or traded since last season (offseason from March 15)
                vet_move=(R.pos.values != "QB") * np.fmax(np.nan_to_num(col(R, "e_x_new_team")), np.nan_to_num(col(R, "e_x_moved_off"))) * np.clip((np.nan_to_num(age, nan=25) - 27.0) / 2.0, 0, 1),
                # an RB who can't run: yards per carry over the last two seasons and this one so far (e_x_ypc_3s; else the
                # last two) under 4.1 (3.7 = full), from his 3rd season (a pattern over years, not a rookie behind a bad line;
                # this season counts so a workhorse running well now is not docked for two seasons ago: Mixon 2021)
                ypc_bad=(R.pos.values == "RB") * (exp_ >= 2) * np.clip((4.1 - np.nan_to_num(np.where(np.isnan(col(R, "e_x_ypc_3s")), col(R, "e_x_ypc_2y"), col(R, "e_x_ypc_3s")), nan=9.0)) / 0.4, 0, 1.5),
                rookie_backup=rookie_backup(R, exp_),
                # the NFL just drafted his replacement: same-team, same-position rookies taken in rounds 1-2 this season
                # (from the NFL draft day; a second one counts half), from his 3rd season (a 2nd-year player is still the
                # team's bet); gated to mid-priced players in apply_rules
                draft_comp=(exp_ >= 2) * np.clip(np.nan_to_num(col(R, "e_x_draft_comp")), 0, 1.5),
                # the NFL market's price: a veteran who changed teams (signed or traded since last season) on a cheap
                # veteran deal signed this season (APY share of the cap under DEAL_CHEAP for his position; DEAL_FULL = full).
                # Gated to players the base values (apply_rules): a cheap deal for a cheap player is no news
                cheap_deal=(R.pos.values != "QB") * np.fmax(np.nan_to_num(col(R, "e_x_new_team")), np.nan_to_num(col(R, "e_x_moved_off")))
                    * np.where(np.isnan(col(R, "e_x_vet_deal_cap")), 0.0, np.clip((R.pos.map(DEAL_CHEAP).fillna(0).values - np.nan_to_num(col(R, "e_x_vet_deal_cap")))
                                                                         / (R.pos.map(DEAL_CHEAP).fillna(1).values - R.pos.map(DEAL_FULL).fillna(0).values), 0, 1)),
                # a rookie the league passed on: not taken in its rookie draft and not a top pre-Week-1 add
                # (e_x_league_undrafted: 1 = neither, less credit for his bid); fades out over his first 4 games, when
                # his own usage prices him (Oliver: Luke McCaffrey 2024, a 3rd-round NFL pick no one here drafted)
                # a TE's one big year: last season on a team he had just joined, after mid-or-worse seasons
                # (e_x_te_one_off), and now on the move again (signed or traded since): the big year was the situation,
                # not him (Oliver: Jonnu Smith 2025). Fades out over his first 4 games for the new team
                # a QB a new team just paid as its starter (a veteran deal this season at 8%+ of the cap, 15% = full):
                # the market's call on his role until he plays (fading out over 4 games; Oliver: Carr to New Orleans 2023); the
                # replacement line is lifted with it
                qb_paid=(R.pos.values == "QB") * np.fmax(np.nan_to_num(col(R, "e_x_new_team")), np.nan_to_num(col(R, "e_x_moved_off")))
                    * np.clip((np.nan_to_num(col(R, "e_x_vet_deal_cap")) - 0.08) / 0.07, 0, 1) * (1 - np.clip(cur_gp / 4.0, 0, 1)),
                # last season a same-team rookie outscored him (e_x_overtaken), fading as he plays this season; an aging player only (OVR_AGE)
                overtaken=np.nan_to_num(col(R, "e_x_overtaken")) * (1 - np.clip(cur_gp / 8.0, 0, 1)) * np.clip((np.nan_to_num(age, nan=25) - OVR_AGE + 2.0) / 2.0, 0, 1),
                young_upside=young_upside,
                te_one_off=(R.pos.values == "TE") * np.nan_to_num(col(R, "e_x_te_one_off")) * np.fmax(np.nan_to_num(col(R, "e_x_new_team")), np.nan_to_num(col(R, "e_x_moved_off")))
                    * (1 - np.clip(cur_gp / 4.0, 0, 1)),
                undrafted=(exp_ == 0) * np.nan_to_num(col(R, "e_x_league_undrafted")) * (1 - np.clip(cur_gp / 4.0, 0, 1)),
                rookie_day3=(exp_ == 0) * (R.pos.values != "QB") * np.where(np.isnan(pk), 1.0, np.clip((pk - 100) / 60, 0, 1)),
                rec_age=np.clip((np.nan_to_num(age, nan=25) - R.pos.map(AGE_WALL).fillna(31).values + 2.0) / 3.0, 0, 1) * drop_old, qb_early=qb_early, te_x=te_x, boom_week=boom_week, fresh=fresh, wr_no_role=wr_no_role, te_proven=te_proven, te_proven16=te_proven16, duds=duds, peak_share=peak_share, slump=slump, regress=regress, rostered=np.nan_to_num(col(R, "e_x_rostered_recent")), avail_prior=avail_prior, qb_starter=qb_starter, qb_pedigree=qb_pedigree, young_starter=young_starter, carry=carry, one_game=one_game, boom_bust=boom_bust, td_dep=td_dep, off_field=off_field, summer=summer, journeyman=journeyman, bust=bust, rb_multi=rb_multi, wr_talent=wr_talent, pick_boom=pick_boom, rb_age=rb_age, rookie_capital=rookie_capital, alpha=alpha,
                availability=availability, efficiency=efficiency, opening=opening, team_q=np.clip(team_q, -1.5, 1.5), new_team_burst=new_team_burst, share_talent=share_talent,
                xfp_z=xfp_z, qbq=qbq, elite=elite, track=track, recurring=recurring, steady=steady, pedigree=pedigree, spike=np.clip(spike / 0.5, 0, 1.5) * (1 - 0.4 * np.clip(boom_bust_early(R, cur_gp), 0, 1.5)) * (R.pos.values != "QB") * np.clip((29.0 - np.nan_to_num(age, nan=30)) / 3.0, 0, 1), team_up=trend, severe=severe.astype(float), usage=usage, youth_usage=youth * np.clip(usage, 0, 3) / 3, youth_role=youth * role, two_way=two_way, aw_college=np.clip(np.nan_to_num(awc), 0, 2) * early,
                aw_nfl=np.clip(np.nan_to_num(awn), 0, 3), prone=np.nan_to_num(col(R, "e_x_inj_rate_2y")),
                ir=np.isin(inj, ["IR", "PUP"]).astype(float), out=np.isin(inj, ["Out", "Doubtful"]).astype(float),
                te=(R.pos.values == "TE").astype(float), vet_age=np.clip((np.nan_to_num(age, nan=25) - R.pos.map(VET_AGE).fillna(30).values) / 2, 0, 1),
                un=np.nan_to_num(col(R, "un_x")))
RULE_KEYS = {"young_upside": "young_upside", "overtaken": "overtaken", "qb_paid": "qb_paid", "te_one_off": "te_one_off", "undrafted": "undrafted", "qb_starter": "qb_starter", "qb_pedigree": "qb_pedigree", "young_starter": "young_starter", "carry": "carry", "one_game": "one_game", "boom_bust": "boom_bust", "td_dep": "td_dep", "off_field": "off_field", "summer": "summer", "old_cliff": "old_cliff", "vet_move": "vet_move", "ypc_bad": "ypc_bad", "rookie_backup": "rookie_backup", "duds": "duds", "peak_share": "peak_share", "slump": "slump", "journeyman": "journeyman", "bust": "bust", "rb_multi": "rb_multi",
             "wr_talent": "wr_talent", "pick_boom": "pick_boom", "rb_age": "rb_age", "rookie_capital": "rookie_capital", "alpha": "alpha",
             "availability": "availability", "efficiency": "efficiency", "opening": "opening", "team_q": "team_q", "new_team_burst": "new_team_burst",
             "share_talent": "share_talent", "recurring": "recurring", "steady": "steady", "pedigree": "pedigree", "elite_streak": "elite", "track": "track",
             "qb_quality": "qbq", "severe": "severe", "usage": "usage", "youth_usage": "youth_usage", "youth_role": "youth_role", "two_way": "two_way",
             "aw_college": "aw_college", "aw_nfl": "aw_nfl", "prone": "prone", "inj_ir": "ir", "inj_out": "out"}
FRESH_MAX = 200.0     # fresh_start reaches only a player whose value without it is under this


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
    # availability: missed games lower a value (availability); a clean record raises it by its own strength (avail_up)
    av_ = lambda x: p.get("availability", 0) * np.minimum(x, 0) + p.get("avail_up", 0) * np.maximum(x, 0)
    T_["availability"] = np.where(X["ir"] > 0, (1 - p.get("ir_no_double", 0.0)) * av_(X["availability"]) + p.get("ir_no_double", 0.0) * av_(X["avail_prior"]), av_(X["availability"]))
    # a young player's missed games: the availability drop is floored (avail_young_floor, a multiplier; 0 = off) under
    # avail_young_age, fading out over the 2 years after (Oliver: Brooks, Dobbins, Kyren)
    yf = p.get("avail_young_floor", 0.0)
    if yf > 0:
        yw = np.clip((p.get("avail_young_age", 24.0) + 2.0 - np.nan_to_num(col(R, "age"), nan=30)) / 2.0, 0, 1)
        T_["availability"] = np.maximum(T_["availability"], (1 - yw) * T_["availability"] + yw * np.log(yf))
    # team-share talent is a bet on the future: it fades past the age wall (share_age)
    T_["share_talent"] = T_["share_talent"] * (1 - p.get("share_age", 0.0) * X["past_wall"])
    # ... and an older WR's team share is capped (share_old_cap, a multiplier, full from share_old_age, fading in over the
    # 2 years before): a 30+ receiver's share is what he has done, not a long bet (Oliver: Adams 2025, "limit to 1.25-1.5")
    old_wr = (pos == "WR") * np.clip((np.nan_to_num(col(R, "age"), nan=25) - p.get("share_old_age", 30.0) + 2.0) / 2.0, 0, 1)
    T_["share_talent"] = np.where(old_wr > 0, np.minimum(T_["share_talent"], (1 - old_wr) * T_["share_talent"] + old_wr * np.log(p.get("share_old_cap", 99.0))), T_["share_talent"])
    # a rookie drafted on day 3 (pick 100+, or undrafted) is priced near his slot until he plays (rookie_day3)
    T_["rookie_day3"] = p.get("rookie_day3", 0.0) * X["rookie_day3"]
    nd = p.get("ir_no_double", 0.0) * X["ir"]                       # on IR: the healthy role (prior seasons) stands in for this season
    T_["usage"] = p.get("usage", 0) * ((1 - nd) * X["usage"] + nd * X["usage_h"])
    T_["youth_usage"] = p.get("youth_usage", 0) * ((1 - nd) * X["youth_usage"] + nd * X["youth_usage_h"])
    T_["qb_opening"] = p.get("qb_opening", 0.0) * X["qb_played"] * X["opening"] * X["qb_early"]   # a young QB who has played well (PPG over the QB line), competition only an aging backup
    T_["draft_comp"] = p.get("draft_comp", 0.0) * X["draft_comp"] * np.interp(raw, [150, 200, 600, 800], [0, 1, 1, 0])   # base $200-600 (fading 150-200, 600-800): Oliver
    # a cheap player's team counts for more: a mediocre player on a bad team is worth little, on a good one he has a
    # path (team_q_lo, extra team-quality strength at base under $75, fading out by $150: Oliver, Tre Tucker 2025)
    T_["team_q_lo"] = p.get("team_q_lo", 0.0) * np.minimum(X["team_q"], 0) * np.interp(raw, [75, 150], [1, 0])
    T_["cheap_deal"] = p.get("cheap_deal", 0.0) * X["cheap_deal"] * np.interp(raw, [300, 600], [0, 1])
    T_["boom_week"] = p.get("boom_week", 0.0) * X["boom_week"] * np.clip((p.get("boom_hi", 600.0) - v) / (0.6 * p.get("boom_hi", 600.0)), 0, 1)
    T_["spike"] = p.get("spike", 0) * X["spike"] * unpriced; T_["team_up"] = p.get("team_up", 0) * X["team_up"] * unpriced
    T_["position curve"] = X["te"] * curve(p["te_lo"], p["te_hi"]) + np.select([pos == "QB", pos == "RB", pos == "WR"], [top_curve(p["qb_lo"], p["qb_hi"]), top_curve(p["rb_lo"], p["rb_hi"]), top_curve(p["wr_lo"], p["wr_hi"])], 0.0)
    # TE line in two tiers: a light drop below te_thr (capped, te_soft) and a harsh one below te_thr2 (te_line); a proven
    # TE's line is eased by te_relief
    tx_ = np.nan_to_num(X["te_x"], nan=99.0); pv = p.get("te_pv16", 0.0); relief = 1 - p.get("te_relief", 0.0) * ((1 - pv) * X["te_proven"] + pv * X["te_proven16"])
    T_["te_line"] = relief * (p.get("te_soft", 0.0) * np.clip((p.get("te_thr", 11.0) - tx_) / 2.5, 0, 1)
                              + p.get("te_line", 0.0) * np.clip((p.get("te_thr2", 9.0) - tx_) / 2.5, 0, 1.5))
    T_["no NFL team"] = -UK * X["un"] * (1 - X["rostered"])     # on a roster last season or this one (IR, suspended): he has a team
    # an older player's regression fades his record boosts (elite streak, NFL awards, top-12 track)
    # ... and near or past the age wall, a declining player's record boosts fade (rec_age) and his value drops (old_cliff),
    # scaled by the drop in his expected PPG: an old star in decline is priced on his next season, not on his record (the
    # vet discount above spares expensive players). An old player still producing (no drop) keeps his value
    for k_ in ("elite_streak", "aw_nfl", "track"): T_[k_] = T_[k_] * (1 - p.get("regress", 0.0) * X["regress"]) * (1 - p.get("rec_age", 0.0) * X["rec_age"])
    # replacement level: a veteran (4th season on) ranked near or below the line is a waiver-wire body worth ~0;
    # players in their first three seasons keep their upside value
    if "rank_raw" in R:
        n_ = col(R, "line_n"); vetr = (np.nan_to_num(col(R, "exp")) >= 3) * np.where(X["wr_no_role"] > 0, 1.0, np.clip((np.nan_to_num(col(R, "age"), nan=28) - 25.0) / 3.0, 0, 1))   # 4th season on, fading in from 25 to 28 (a WR who never had a starter's role: full)
        T_["replacement line"] = -p.get("bubble", 0.0) * np.nan_to_num(vetr * np.clip((col(R, "rank_raw") - p.get("line_frac", 0.8) * n_) / (0.25 * n_), 0, 1.5))
    if "replacement line" in T_: T_["replacement line"] = T_["replacement line"] * (1 - X["qb_paid"])
    # a fresh start (followed his coach to a new team): the role-based docks (TE line, replacement line) are lifted
    # and the move is priced by its own strength (fresh_start, held on Oliver's call). Only for a player who would
    # otherwise be worth under $200 (Oliver): a valued player's price already carries his role
    fr = X["fresh"] * (v * np.exp(sum(T_.values())) < FRESH_MAX)
    for k_ in ("te_line", "replacement line"):
        if k_ in T_: T_[k_] = T_[k_] * (1 - fr)
    T_["fresh_start"] = p.get("fresh_start", 0.0) * fr
    v = v * np.exp(sum(T_.values()))
    # usage anchor: pull part of the way toward the value the current role implies (history-built values drift to what a player does now)
    w = p.get("anchor_w", 0.0) + p.get("anchor_old", 0.0) * X["near_wall"]       # older players: priced on what they do now
    ndz = p.get("ir_no_double", 0.0) * X["ir"]; z = np.where(np.isnan(X["xfp_zh"]), X["xfp_z"], (1 - ndz) * np.nan_to_num(X["xfp_z"]) + ndz * X["xfp_zh"])
    z = np.where(np.isnan(X["xfp_z"]) & (ndz == 0), np.nan, z)
    u = 50.0 * np.exp(p.get("anchor_slope", 0.5) * np.clip(np.nan_to_num(z, nan=0.0), -3, 12))
    v2 = np.where(np.isnan(z) | (w <= 0), v, np.exp((1 - w) * np.log(np.maximum(v, 1)) + w * np.log(u)))
    out = np.where(v2 > 2000, 2000 * (np.maximum(v2, 2000) / 2000) ** p["top_g"], v2)
    if explain:
        return out, T_, dict(base=raw, curve=v0, vet=v1, rules=v, anchor=v2, final=out)
    return out

# ------------------------------------------------------------------ inputs and evidence
REG_KEYS = ["young_upside", "wr_pair", "overtaken", "qb_paid", "team_q_lo", "te_one_off", "undrafted", "cheap_deal", "draft_comp", "rookie_backup", "fresh_start", "boom_week", "qb_starter", "qb_pedigree", "ir_no_double", "qb_opening", "young_starter", "carry", "one_game", "boom_bust", "td_dep", "off_field", "summer", "te_line", "te_soft", "te_relief", "old_cliff", "rec_age", "avail_up", "share_age", "anchor_old", "rookie_day3", "vet_move", "ypc_bad", "regress", "duds", "peak_share", "slump", "journeyman", "bust", "rb_multi", "wr_talent", "pick_boom", "rb_age",
            "rookie_capital", "alpha", "availability", "efficiency", "opening", "team_q", "new_team_burst", "share_talent", "recurring", "steady", "pedigree",
            "elite_streak", "track", "qb_quality", "spike", "team_up", "severe", "qb_lo", "qb_hi", "rb_lo", "rb_hi", "wr_lo", "wr_hi", "usage", "youth_usage",
            "youth_role", "te_lo", "te_hi", "inj_ir", "inj_out", "prone", "two_way", "aw_college", "aw_nfl"]
W_TRADES, W_CUTS = 3.0, 3.0      # trade/cut history counts more than one person's calls


def load_inputs(data=DATA):
    R = pd.read_csv(Path(data) / "inputs.csv", dtype={"sid": str, "injury": str, "wr_mate": str}, keep_default_na=False, na_values=[""])
    R["injury"] = R.injury.fillna("")
    return R


LAG_DAYS, LAG_SLACK = 28, 7       # "his value four weeks earlier": the latest row at least 28 days back, at most 35
PAIR_MIN = 1750.0                 # two WRs on one team both worth this much: the lesser one is docked (wr_pair)


def links(R):
    """positions in R of each row's top WR teammate that day (the export's wr_mate) and of his own row LAG_DAYS
    earlier (within LAG_SLACK more days); -1 = not in the inputs"""
    sid = R.sid.astype(str).values; d = pd.to_datetime(R.date).values
    key = {(a, x): i for i, (a, x) in enumerate(zip(sid, d))}
    wm = R["wr_mate"].fillna("").astype(str).values if "wr_mate" in R else np.full(len(R), "")
    mate = np.array([key.get((m, x), -1) if m not in ("", "nan") else -1 for m, x in zip(wm, d)], dtype=int)
    L = pd.DataFrame(dict(sid=sid, t=pd.to_datetime(d) - pd.Timedelta(days=LAG_DAYS), j=np.arange(len(R))))
    G = pd.DataFrame(dict(sid=sid, t=pd.to_datetime(d), i=np.arange(len(R))))
    m = pd.merge_asof(L.sort_values("t"), G.sort_values("t"), on="t", by="sid", direction="backward", tolerance=pd.Timedelta(days=LAG_SLACK))
    lag = np.full(len(R), -1, dtype=int); lag[m.j.values] = m.i.fillna(-1).astype(int).values
    return mate, lag


def post_rules(V, R, p, mate, lag, X=None):
    """the rules that read another row's value (after apply_rules; the other row's own value is taken before them):
    wr_pair: when a team's two WRs are both worth PAIR_MIN+, the lesser one x exp(wr_pair x the other's target share)
             (Oliver 2026-11-08: Waddle under Hill, Higgins under Chase, Godwin under Evans);
    lag_cap: no row above lag_cap x his value LAG_DAYS earlier (with a floor of lag_floor), when that row is in the
             inputs (Oliver 2026-11-08: CEH and Kirk, 2022-10). 99 = off."""
    V = np.asarray(V, dtype=float); out = V.copy()
    k = p.get("wr_pair", 0.0)
    if k and (mate >= 0).any():
        cur = np.nan_to_num(col(R, "e_x_cur_games"))
        sh = np.nan_to_num(np.where(cur >= 4, col(R, "e_x_cur_tgt_share"), col(R, "e_x_l0_tgt_share")))
        has = (mate >= 0) & (R.pos.values == "WR"); m = np.maximum(mate, 0)
        vm = np.where(has, V[m], 0.0)
        w = has * (V <= vm) * np.interp(np.minimum(V, vm), [PAIR_MIN - 250, PAIR_MIN], [0, 1])
        out = out * np.exp(k * w * np.where(has, sh[m], 0.0))
    c = p.get("lag_cap", 99.0)
    if c < 50 and (lag >= 0).any():
        has = lag >= 0
        lim = np.where(has, np.maximum(c * V[np.maximum(lag, 0)], p.get("lag_floor", 0.0)), np.inf)
        out = np.minimum(out, lim)
    return out


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
        # each group of calls on the board of the day it was made: call date -> the inputs' grid date holding it
        # (the export's choice when it kept that board, else the latest full board on or before the call date)
        from . import faab_calls as LC
        n = R.date.value_counts(); full = sorted(n.index[n >= 0.5 * n.max()]); cd = ev.get("call_dates") or {}
        self.call_boards = {}
        for d in LC.CALL_DATES:
            gd = cd.get(d)
            if gd is None or not (R.date == gd).any(): gd = max([x for x in full if x <= d] or [self.calls_date])
            self.call_boards[d] = gd
        R = R.reset_index(drop=True); self.R = R
        self.pTs = {gd: R[R.date == gd].drop_duplicates("name").index.values for gd in set(self.call_boards.values())}
        self.Ts = {gd: R.iloc[i].reset_index(drop=True) for gd, i in self.pTs.items()}
        self.mate, self.lag = links(R)
        rows = sorted({key[tuple(k)] for k in ev["cuts"]} | {key[tuple(k)] for t in ev["trades"] for s in t["sides"] for k in s["players"]})
        pos = {i: j for j, i in enumerate(rows)}
        self.pE = np.array(rows, dtype=int); self.E = R.iloc[rows].reset_index(drop=True)
        self.trades = [(t["date"], [(s["other_value"], [pos[key[tuple(k)]] for k in s["players"]]) for s in t["sides"]]) for t in ev["trades"]]
        self.cuts = np.array([pos[key[tuple(k)]] for k in ev["cuts"]], dtype=int)
        # boards the rating-page votes were asked on: board date -> the inputs' grid date holding its rows
        self.vote_dates = {str(pd.Timestamp(ev["as_of"]).date()): ev["as_of"], **ev.get("vote_dates", {})}
        self.pVR = R[R.date.isin(set(self.vote_dates.values()))].drop_duplicates(["sid", "date"]).index.values
        self.VR = R.iloc[self.pVR].reset_index(drop=True)

    def values(self, p, X=None):
        """every inputs row's value, the rules on other rows' values (post_rules) included"""
        return post_rules(apply_rules(self.R, p, X), self.R, p, self.mate, self.lag, X)

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
    T["V"] = with_links(R, p)[R.index.get_indexer(T.index)]
    T = T.sort_values("V", ascending=False).reset_index(drop=True)
    T["rank"] = np.arange(1, len(T) + 1)
    return T


def with_links(R, p):
    """every row's value with the rules on other rows' values (post_rules)"""
    mate, lag = links(R.reset_index(drop=True))
    return post_rules(apply_rules(R, p), R, p, mate, lag)


def call_values(ev, p):
    """{call date: name -> value}: each group of the league's calls on the board of the day it was made"""
    V = ev.values(p)
    vb = {gd: pd.Series(V[i], index=ev.Ts[gd].name.values) for gd, i in ev.pTs.items()}
    return {d: vb[gd] for d, gd in ev.call_boards.items()}


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
    first = ev.Ts[ev.call_boards[LC.CALL_DATES[0]]]
    qbs = set(first.name[first.pos == "QB"]); exp_ = pd.Series(first.exp.values, index=first.name.values) if band else None
    cache = {}

    def obj(p, detail=False):
        ya = p.get("youth_age", 26.0)
        if ya not in cache:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                cache[ya] = characteristics(ev.R, ya)
        V = ev.values(p, cache[ya])
        vb = {gd: pd.Series(V[i], index=ev.Ts[gd].name.values) for gd, i in ev.pTs.items()}
        c, t = LC.score({d: vb[gd] for d, gd in ev.call_boards.items()}, ref, qbs, exp=exp_)
        ve = V[ev.pE]
        te, ce = trade_err(ve, ev.trades)[0], cut_err(ve, ev.cuts)
        vo = votes.loss(ev.vote_values(V[ev.pVR])) if votes is not None and len(votes.C) else 0.0
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
