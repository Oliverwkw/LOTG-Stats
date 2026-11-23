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
          youth_role=0.0, te_lo=0.0, te_hi=0.0, inj_ir=0.0, inj_out=0.0, prone=0.0, two_way=0.0, aw_college=0.0, aw_nfl=0.0, usage=0.0, youth_usage=0.0, qb_lo=0.0, qb_hi=0.0, rb_lo=0.0, rb_hi=0.0, wr_lo=0.0, wr_hi=0.0, youth_age=26.0, spike=0.0, team_up=0.0, severe=0.0, spike_hi=1500.0, anchor_w=0.0, anchor_slope=0.5, qb_quality=0.0, elite_streak=0.0, track=0.0, recurring=0.0, steady=0.0, pedigree=0.0, efficiency=0.0, opening=0.0, team_q=0.0, new_team_burst=0.0, share_talent=0.0, availability=0.0, rb_multi=0.0, wr_talent=0.0, pick_boom=0.0, rb_age=0.0, rookie_capital=0.0, alpha=0.0, off_field=0.0, journeyman=0.0, bust=0.0, bubble=0.0, line_frac=0.8, summer=0.0, te_line=0.0, regress=0.0, te_thr=11.0, te_soft=0.0, te_thr2=9.0, te_relief=0.0, te_pv16=0.0, old_cliff=0.0, rec_age=0.0, avail_up=0.0, share_age=0.0, anchor_old=0.0, rookie_day3=0.0, vet_move=0.0, ypc_bad=0.0, duds=0.0, peak_share=0.0, slump=0.0, boom_week=0.0, boom_hi=600.0, fresh_start=0.0, rookie_backup=0.0, draft_comp=0.0, cheap_deal=0.0, undrafted=0.0, te_one_off=0.0, team_q_lo=0.0, qb_paid=0.0, avail_young_floor=0.0, avail_young_age=24.0, share_old_cap=99.0, share_old_age=30.0, wr_pair=0.0, young_upside=0.0, young_elite=0.0, te_top3=0.0, rookie_r1=0.0, r1_wr=0.0, lag_cap=99.0, lag_floor=0.0, overtaken=0.0)
BOUNDS = dict(y200=(80, 230), y450=(250, 520), y650=(500, 950), lvl=(0.6, 1.6), vet=(0.2, 1.0), vet_hi=(600, 3500), top_g=(0.45, 0.85),
              youth_role=(-0.5, 2.0), te_lo=(-1.5, 0.8), te_hi=(-1.0, 0.6), inj_ir=(-1.0, 0.3), inj_out=(-0.8, 0.3), prone=(-2.5, 0.5),
              two_way=(0.0, 2.5), aw_college=(-0.3, 1.5), aw_nfl=(-0.3, 1.0), usage=(-0.3, 1.5), youth_usage=(-0.3, 2.0), qb_lo=(-0.5, 0.4), qb_hi=(-0.6, 0.6), rb_lo=(-0.5, 0.15), rb_hi=(-0.6, 0.6), wr_lo=(-0.5, 0.15), wr_hi=(-0.6, 0.6), youth_age=(24.5, 29.0), spike=(-0.5, 2.0), team_up=(-0.5, 1.0), severe=(-1.5, 0.3), spike_hi=(500.0, 3000.0), anchor_w=(0.0, 0.7), anchor_slope=(0.2, 0.9), qb_quality=(-0.5, 2.0), elite_streak=(0.0, 1.5), track=(-0.3, 1.0), recurring=(-0.6, 0.2), steady=(-0.3, 1.0), pedigree=(-0.3, 1.0), efficiency=(-0.3, 1.2), opening=(-0.3, 1.2), team_q=(-0.3, 0.8), new_team_burst=(-0.3, 1.2), share_talent=(-0.3, 1.2), availability=(0.0, 1.5), rb_multi=(-0.3, 1.0), wr_talent=(-0.3, 1.0), pick_boom=(-0.3, 1.5), rb_age=(-1.2, 0.2), rookie_capital=(-0.3, 1.5), alpha=(-0.3, 1.0), off_field=(-5.0, 0.0), journeyman=(-2.0, 0.3), bust=(-2.0, 0.3), bubble=(0.0, 4.0), line_frac=(0.4, 1.1), summer=(-1.5, 0.5), te_line=(-3.0, 0.0), regress=(0.0, 1.0), te_thr=(9.5, 13.0), te_soft=(-3.0, 0.0), te_thr2=(7.0, 10.0), te_relief=(0.0, 1.0), te_pv16=(0.0, 1.0), old_cliff=(-3.0, 0.0), rec_age=(0.0, 1.0), avail_up=(0.0, 1.5), share_age=(0.0, 1.0), anchor_old=(0.0, 0.7), rookie_day3=(-3.0, 0.0), vet_move=(-2.0, 0.0), ypc_bad=(-2.0, 0.0), duds=(-1.5, 0.0), peak_share=(0.0, 1.5), slump=(-1.5, 0.0), boom_week=(0.0, 1.5), boom_hi=(300.0, 1500.0), fresh_start=(0.0, 4.0), rookie_backup=(-2.0, 0.0), draft_comp=(-2.5, 0.0), cheap_deal=(-2.5, 0.0), undrafted=(-2.5, 0.0), overtaken=(-2.5, 0.0), wr_pair=(-3.0, 0.0), lag_cap=(1.5, 99.0), lag_floor=(0.0, 500.0), young_upside=(0.0, 1.5), young_elite=(0.0, 2.0), te_top3=(0.0, 1.0), rookie_r1=(-2.5, 0.0), r1_wr=(-2.5, 0.0), te_one_off=(-2.5, 0.0), team_q_lo=(0.0, 1.5), qb_paid=(0.0, 2.5))
P0.update(vet_floor=0.0, rb_duds=0.0, wr_band=0.0, qb_band=0.0, rb_band=0.0, rb_inj=0.0, spike_vet_rb=0.0, qb_inj=0.0, wr_backup=0.0, wr_clean_old=0.0, tgt_lead=0.0, young_boom=0.0, rb_touch=0.0, te_slide=0.0, qb_tough=0.0, qb_ypg=0.0, snap_cap=0.0, rb_hold=0.0, rb_old_hi=0.0,
          boom_bust=0.0, td_dep=0.0, one_game=0.0, young_starter=0.0, carry=0.0, qb_pedigree=0.0, qb_starter=0.0, ir_no_double=0.0, qb_opening=0.0)
# round 6 (Oliver's 2026-11-22 notes on the failing calls and the far-off trades): every one starts at 0 (off)
P0.update(young_peak=0.0, qb_proof=0.0, wr_room_top=0.0, flop_r1=0.0, rb_role=0.0, boom_rate_lo=0.0, rb_pass_team=0.0, contract_old=0.0, contract_boom=0.0, ceiling_lo=0.0, new_home=0.0, comp_young=0.0, wr_adv=0.0, soph_fall=0.0, wr_room=0.0, summer_old=0.0, cutdown=0.0)
BOUNDS.update(vet_floor=(0.0, 1.0), rb_duds=(-1.0, 0.0), wr_band=(-0.6, 0.0), qb_band=(-0.6, 0.0), rb_band=(0.0, 0.6), rb_inj=(-1.0, 0.0),
    spike_vet_rb=(-1.0, 0.0), qb_inj=(-1.0, 0.0), wr_backup=(-1.0, 0.0), wr_clean_old=(-1.0, 0.0), tgt_lead=(0.0, 1.5), young_boom=(0.0, 1.5), rb_touch=(-1.5, 0.0), te_slide=(-1.5, 0.0), qb_tough=(0.0, 1.0), qb_ypg=(-1.0, 0.0), snap_cap=(0.0, 1.0), rb_hold=(0.0, 1.5), rb_old_hi=(-1.0, 0.0),
    rb_hi=(0.0, 0.6), wr_hi=(-0.6, 0.0), qb_hi=(-0.2, 0.2),   # wr_hi: top-end WR fade, lower only, held -0.5 (Oliver 2026-11-18)
    
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
    ir_no_double=(0.0, 1.0),                                                      # a blend weight (IR: prior seasons stand in), either direction
    young_peak=(0.0, 0.5), qb_proof=(0.0, 0.5), wr_room_top=(0.0, 0.5), flop_r1=(-1.5, 0.0), rb_role=(0.0, 1.0), boom_rate_lo=(-1.5, 0.0), rb_pass_team=(-1.0, 0.0), contract_old=(-1.5, 0.0), contract_boom=(0.0, 1.0), ceiling_lo=(-1.5, 0.0), new_home=(0.0, 1.0), comp_young=(0.0, 1.0), wr_adv=(0.0, 1.5), soph_fall=(-1.5, 0.0), wr_room=(0.0, 1.0), summer_old=(-1.5, 0.0), cutdown=(-2.0, 0.0))
RAISE_ONLY = ["young_peak", "qb_proof", "wr_room_top", "contract_boom", "new_home", "rb_hold", "tgt_lead", "young_boom", "qb_tough", "vet_floor", "rb_band", "young_elite", "young_upside", "qb_paid", "team_q_lo", "fresh_start", "boom_week", "aw_nfl", "aw_college", "usage", "steady", "youth_usage", "youth_role", "elite_streak", "track", "qb_quality", "wr_talent", "rb_multi", "efficiency",
              "pedigree", "rookie_capital", "alpha", "availability", "pick_boom", "new_team_burst", "team_up", "two_way", "share_talent", "spike", "team_q", "opening",
              "young_starter", "carry", "qb_pedigree", "qb_starter", "qb_opening", "peak_share", "avail_up", "wr_adv", "wr_room"]
LOWER_ONLY = ["wr_hi", "rb_touch", "te_slide", "qb_ypg", "rb_duds", "wr_band", "qb_band", "rb_inj", "spike_vet_rb", "qb_inj", "wr_backup", "wr_clean_old", "r1_wr", "rookie_r1", "wr_pair", "overtaken", "te_one_off", "undrafted", "cheap_deal", "draft_comp", "rookie_backup", "te_line", "te_soft", "old_cliff", "rookie_day3", "vet_move", "ypc_bad", "duds", "slump", "inj_ir", "inj_out", "severe", "prone", "recurring", "off_field", "journeyman", "bust", "rb_age", "boom_bust", "td_dep", "one_game", "soph_fall", "summer_old", "cutdown", "ceiling_lo", "contract_old", "boom_rate_lo", "rb_pass_team", "flop_r1"]
_bad = [k for k in RAISE_ONLY if BOUNDS[k][0] < 0] + [k for k in LOWER_ONLY if BOUNDS[k][1] > 0]
assert not _bad, f"rules with the wrong sign allowed: {_bad}"
VET_AGE = {"QB": 33, "RB": 26.5, "WR": 28.5, "TE": 28.5}
# round 6 (Oliver 2026-11-22, Kelce 2024: "still producing"): old_cliff eases (by OLD_KEEP, full 3 PPR/g past the line) for
# an old player still scoring like a starter at his position (PPR per game now, the same blend old_cliff reads)
OLD_KEEP, OLD_KEEP_PPG = 1.0, {"RB": 14.0, "WR": 14.0, "TE": 11.0}
AGE_WALL = {"QB": 99, "RB": 30, "WR": 31, "TE": 32}     # past this, a declining player's value goes whatever his record (old_cliff, rec_age);
                                                         # not QBs (the superflex QB rules carry their own age fade, and the calls hold old QBs up)
UK = 2.5     # no NFL team (off every depth chart, no games, not hurt): x0.08
def col(R, c): return R[c].values.astype(float) if c in R else np.full(len(R), np.nan)
UPSIDE_EXP = 2       # young_upside: a player in his first three seasons
ELITE_AGE = 24.0     # young_elite: full under this age, none a year older
ROOKIE_PRIOR = {"QB": 1.0, "RB": 0.25, "WR": 1.0, "TE": 1.0}   # share of the 4-game usage prior a rookie year gets (Kyren 2023)
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
def summer_weight(R):
    """the summer window on each row's date (Oliver 2026-11-10, grid of start/end dates and fades): 0 until SUMMER_FADE_IN
    days before the NFL draft, rising to 1 at the draft, 1 until SUMMER_END days after kickoff (Week 1 still counts),
    then 0. A year without an NFL draft or kickoff date falls back to the exported June 1 -> kickoff - 3 flag."""
    if "date" not in R: return np.nan_to_num(col(R, "e_x_offseason"))
    from .faab_features import KO, NFL_DRAFT
    d = pd.to_datetime(R.date).dt.normalize(); y = d.dt.year
    nd = pd.to_datetime(y.map(NFL_DRAFT)); ko = pd.to_datetime(y.map(lambda v: KO.get(v)))
    up = np.clip(((d - nd).dt.days.values + SUMMER_FADE_IN) / max(SUMMER_FADE_IN, 1e-9), 0, 1) if SUMMER_FADE_IN > 0 \
        else ((d - nd).dt.days.values >= 0).astype(float)
    since = (d - ko).dt.days.values
    down = np.clip((SUMMER_END - since) / SUMMER_FADE_OUT, 0, 1) if SUMMER_FADE_OUT > 0 else (since < SUMMER_END).astype(float)
    w = up * down
    known = nd.notna().values & ko.notna().values
    return np.where(known, np.nan_to_num(w), np.nan_to_num(col(R, "e_x_offseason")))


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
    # (in his second season the prior is his rookie year, which counts for less: ROOKIE_PRIOR games of 4, RBs least)
    rp = np.where(exp_ == 1, R.pos.map(ROOKIE_PRIOR).fillna(1.0).values, 1.0)
    xc, xl = col(R, "e_x_cur_xfp_pg"), col(R, "e_x_l0_xfp_pg"); g = np.where(np.isnan(xc), 0, cur_gp); gl = np.where(np.isnan(xl), 0, 4.0 * rp)
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
    # trial (votes 2026-11-10): an Out tag on a player with a clean record (no games missed over two seasons, has played)
    out_clean = ((np.nan_to_num(col(R, "e_x_inj_rate_2y")) == 0) & (np.nan_to_num(col(R, "e_x_l0_games")) + np.nan_to_num(col(R, "e_x_cur_games")) > 0)).astype(float)
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
    # the summer (summer_weight: fading in over the 90 days before the NFL draft, through Week 1): one level shift for
    # every player against picks and FAAB, which the league prices differently in the offseason (0 on in-season boards);
    # SUMMER_TO_DRAFT of it lifts after the league's rookie draft (Oliver: after it, the picks are players)
    summer = summer_weight(R) * (1 - np.nan_to_num(col(R, "e_x_league_draft_done")) * SUMMER_TO_DRAFT)
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
    # ---- round 6 (Oliver 2026-11-22)
    # advanced receiving stats (yards / targets per route, separation, top-5 seasons) for a receiver in a middle value
    # band, NOT net of what he produces: "guys in his range with advanced stats like his should get a bigger boost"
    # (Garrett Wilson); wr_talent above counts only the talent beyond production
    wr_adv = np.isin(posv, ["WR", "TE"]) * np.clip(wr_talent_raw, 0, 2)
    # a big early season, then one or two seasons well under it while still playing the snaps: the big year was not him
    # (Oliver: BTJ "carried by his big first year but awful since DESPITE getting snaps"; a second bad year counts again)
    p1, p0_, pc_ = col(R, "e_x_ppg_l1"), col(R, "e_x_ppg_l0"), col(R, "e_x_ppg_cur")
    big1 = np.nan_to_num(p1) >= SOPH_PPG
    bad0 = big1 & (np.nan_to_num(col(R, "e_x_l0_games")) >= SOPH_G) & (np.nan_to_num(col(R, "e_x_l0_off_pct")) >= SOPH_SNAP) & (np.nan_to_num(p0_, nan=99) < SOPH_DROP * np.nan_to_num(p1))
    badc = big1 & (cur_gp >= 4) & (np.nan_to_num(pc_, nan=99) < SOPH_DROP * np.nan_to_num(p1))
    soph_fall = np.isin(posv, ["RB", "WR", "TE"]) * (exp_ <= SOPH_EXP) * (bad0.astype(float) + bad0 * badc * w4)
    # an aging top teammate at his position (29+, full at 32) holding the snaps, for a WR under 28: the room opens soon
    # (Oliver: Puka over ARSB, "his competition is a very-aging Tae Adams, not a young stud Jamo"); `opening` above is the
    # same for young players only
    wr_room = (posv == "WR") * np.clip((np.nan_to_num(col(R, "e_x_comp_age")) - WR_ROOM_AGE) / 3.0, 0, 1) * np.clip(np.nan_to_num(col(R, "e_x_comp_share")) / 0.6, 0, 1) \
        * np.clip((WR_ROOM_MAXAGE + 2.0 - np.nan_to_num(age, nan=30)) / 2.0, 0, 1)
    # the summer shift is bigger for an older player (29+, full at 32): a summer price is a bet on next season's role
    # (Oliver: Adams 2025, "play with a bigger summer cut for older players")
    summer_old = summer * np.clip((np.nan_to_num(age, nan=25) - SUMMER_OLD_AGE) / 3.0, 0, 1)
    # roster cutdown (late August to Sep 3): a player near or under the replacement line is a body the team must make room
    # for (Oliver: the 2026-09-01 Pat Bryant / Tre' Harris trade "made to create roster space on cutdown day")
    if "date" in R:
        dd_ = pd.to_datetime(R.date); md = dd_.dt.month.values * 100 + dd_.dt.day.values
        cut_w = ((md >= CUTDOWN[0][0] * 100 + CUTDOWN[0][1]) & (md <= CUTDOWN[1][0] * 100 + CUTDOWN[1][1])).astype(float)
    else:
        cut_w = np.zeros(len(R))
    n_ = col(R, "line_n"); rr_ = col(R, "rank_raw")
    near_line = np.where(np.isnan(n_) | np.isnan(rr_), 0.0, np.clip((rr_ - 0.6 * n_) / (0.3 * n_), 0, 1))
    cutdown = cut_w * near_line
    return dict(_ya=youth_age, wr_adv=wr_adv, soph_fall=soph_fall, wr_room=wr_room, summer_old=summer_old, cutdown=cutdown, usage_h=usage_h, xfp_zh=xfp_hb - rep, youth_usage_h=youth * np.clip(usage_h, 0, 3) / 3, qb_played=qb_played, old_cliff=np.clip((np.nan_to_num(age, nan=25) - R.pos.map(AGE_WALL).fillna(31).values) / 2.0, 0, 1.5) * drop_old * (1 - OLD_KEEP * np.clip((np.nan_to_num(pn_) - R.pos.map(OLD_KEEP_PPG).fillna(99).values) / 3.0, 0, 1)),
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
                # elite production at a young age: fantasy points per game (this season from 4 games, else last season)
                # at 18+ PPR (22 = full) for an RB/WR under ELITE_AGE, gone a year later: the rarest asset (Oliver:
                # Jefferson at 23, 2022; kept off the 2026 top 3's 24-25 year-olds so they stay inside the top-3 band)
                young_elite=np.isin(R.pos.values, ["RB", "WR"]) * np.clip((np.nan_to_num(pn_, nan=0) - 18.0) / 4.0, 0, 1) * np.clip(ELITE_AGE + 1.0 - np.nan_to_num(age, nan=30), 0, 1),
                te_top3=(R.pos.values == "TE") * np.nan_to_num(col(R, "e_x_te_top3")),
                # an RB the NFL did not draft early (pick 65+ or undrafted) whose team took a 1st-round RB this season
                # (e_x_draft_comp_r1): the job is the rookie's (Oliver: James Robinson after Etienne, 2021)
                rookie_r1=(R.pos.values == "RB") * (exp_ >= 1) * np.clip(np.nan_to_num(col(R, "e_x_draft_comp_r1")), 0, 1) * (np.nan_to_num(col(R, "e_x_draft_pick"), nan=999) > 64),
                # a veteran WR whose team took a 1st-round WR this season (Oliver: Deebo 2024 after Pearsall)
                r1_wr=(R.pos.values == "WR") * (exp_ >= 2) * np.clip(np.nan_to_num(col(R, "e_x_draft_comp_r1")), 0, 1),
                te_one_off=(R.pos.values == "TE") * np.nan_to_num(col(R, "e_x_te_one_off")) * np.fmax(np.nan_to_num(col(R, "e_x_new_team")), np.nan_to_num(col(R, "e_x_moved_off")))
                    * (1 - np.clip(cur_gp / 4.0, 0, 1)),
                undrafted=(exp_ == 0) * np.nan_to_num(col(R, "e_x_league_undrafted")) * (1 - np.clip(cur_gp / 4.0, 0, 1)),
                rookie_day3=(exp_ == 0) * (R.pos.values != "QB") * np.where(np.isnan(pk), 1.0, np.clip((pk - 100) / 60, 0, 1)),
                rec_age=np.clip((np.nan_to_num(age, nan=25) - R.pos.map(AGE_WALL).fillna(31).values + 2.0) / 3.0, 0, 1) * drop_old, qb_early=qb_early, te_x=te_x, boom_week=boom_week, fresh=fresh, wr_no_role=wr_no_role, te_proven=te_proven, te_proven16=te_proven16, duds=duds, peak_share=peak_share, slump=slump, regress=regress, rostered=np.nan_to_num(col(R, "e_x_rostered_recent")), avail_prior=avail_prior, qb_starter=qb_starter, qb_pedigree=qb_pedigree, young_starter=young_starter, carry=carry, one_game=one_game, boom_bust=boom_bust, td_dep=td_dep, off_field=off_field, summer=summer, journeyman=journeyman, bust=bust, rb_multi=rb_multi, wr_talent=wr_talent, pick_boom=pick_boom, rb_age=rb_age, rookie_capital=rookie_capital, alpha=alpha,
                availability=availability, efficiency=efficiency, opening=opening, team_q=np.clip(team_q, -1.5, 1.5), new_team_burst=new_team_burst, share_talent=share_talent,
                xfp_z=xfp_z, qbq=qbq, elite=elite, track=track, recurring=recurring, steady=steady, pedigree=pedigree, spike=np.clip(spike / 0.5, 0, 1.5) * (1 - 0.4 * np.clip(boom_bust_early(R, cur_gp), 0, 1.5)) * (R.pos.values != "QB") * np.clip((29.0 + SPIKE_PROVEN * (np.nan_to_num(col(R, "e_x_s15_4y")) >= 1) - np.nan_to_num(age, nan=30)) / 3.0, 0, 1), team_up=trend, severe=severe.astype(float), usage=usage, youth_usage=youth * np.clip(usage, 0, 3) / 3, youth_role=youth * role, two_way=two_way, aw_college=np.clip(np.nan_to_num(awc), 0, 2) * early,
                aw_nfl=np.clip(np.nan_to_num(awn), 0, 3), prone=np.nan_to_num(col(R, "e_x_inj_rate_2y")),
                ir=np.isin(inj, ["IR", "PUP"]).astype(float), out=np.isin(inj, ["Out", "Doubtful"]).astype(float) * (1.0 - OUT_CLEAN * out_clean * (1.0 + OUT_LONG * np.clip(np.nan_to_num(col(R, "e_x_gp_since_inj")) / 34.0, 0, 1))),
                te=(R.pos.values == "TE").astype(float), vet_age=np.clip((np.nan_to_num(age, nan=25) - R.pos.map(VET_AGE).fillna(30).values) / 2, 0, 1),
                un=np.nan_to_num(col(R, "un_x")))
RULE_KEYS = {"r1_wr": "r1_wr", "rookie_r1": "rookie_r1", "young_elite": "young_elite", "young_upside": "young_upside", "overtaken": "overtaken", "qb_paid": "qb_paid", "te_one_off": "te_one_off", "undrafted": "undrafted", "qb_starter": "qb_starter", "qb_pedigree": "qb_pedigree", "young_starter": "young_starter", "carry": "carry", "one_game": "one_game", "boom_bust": "boom_bust", "td_dep": "td_dep", "off_field": "off_field", "summer": "summer", "old_cliff": "old_cliff", "vet_move": "vet_move", "ypc_bad": "ypc_bad", "rookie_backup": "rookie_backup", "duds": "duds", "peak_share": "peak_share", "slump": "slump", "journeyman": "journeyman", "bust": "bust", "rb_multi": "rb_multi",
             "wr_talent": "wr_talent", "pick_boom": "pick_boom", "rb_age": "rb_age", "rookie_capital": "rookie_capital", "alpha": "alpha",
             "availability": "availability", "efficiency": "efficiency", "opening": "opening", "team_q": "team_q", "new_team_burst": "new_team_burst",
             "share_talent": "share_talent", "recurring": "recurring", "steady": "steady", "pedigree": "pedigree", "elite_streak": "elite", "track": "track",
             "qb_quality": "qbq", "severe": "severe", "usage": "usage", "youth_usage": "youth_usage", "youth_role": "youth_role", "two_way": "two_way",
             "aw_college": "aw_college", "aw_nfl": "aw_nfl", "prone": "prone", "inj_ir": "ir", "inj_out": "out"}
FRESH_MAX = 200.0     # fresh_start reaches only a player whose value without it is under this

# ---- the final stage (round 4, Oliver 2026-11-09): rules on the value the rules above produce, applied after the usage
# anchor and top compression, each a log multiplier. Every one passed the noise bar on trades (FAAB_VALUE_SYSTEM.md)
# and has a football reason, written beside it.
VET_FLOOR = 40.0           # vet_floor: the floor ($) a veteran starter's value is pulled toward
VET_FLOOR_EXP = 4          # ... from his 5th NFL season
VET_FLOOR_SNAPS = 0.6      # ... with 60%+ of the offensive snaps (this season or last)
VET_FLOOR_PPG = 9.0        # ... and at least this PPR per game (this season from 3 games, else last season); 0 = off
VET_FLOOR_POS = ("QB", "RB", "WR", "TE")   # TEs too: the PPR floor keeps out a blocking TE who plays the snaps without the points
BAND_LOG = np.log([900.0, 1300.0, 2300.0, 3000.0])   # wr_band / qb_band: full from $1,300 to $2,300, fading out to $900 / $3,000
RB_BAND_LOG = np.log([25.0, 45.0, 90.0, 160.0])      # rb_band: full from $45 to $90, fading out to $25 / $160
RB_INJ_AGE = 26.0          # rb_inj: an RB this old or older ...
RB_INJ_PPG = 19.0          # ... is spared when he has averaged this since his last week out (3+ games) ...
RB_INJ_PPG_STEP = 0.25     # ... less this per game past 3 ...
RB_INJ_PPG_MIN = 14.0      # ... down to this (Walker 2026: 14.8 over 23 games since his last absence)
WR_BACKUP_MIN = 100.0      # wr_backup: at least this much league spend ($) on the same-team rookie WR (Oliver: a FAAB floor)
# round 5 (Oliver 2026-11-09, his notes on the failing calls)
TGT_LEAD_LO, TGT_LEAD_HI = 50.0, 1000.0   # tgt_lead: base value range it reaches (McConkey's to Kraft's)
TGT_LEAD_LOST = True             # ... only once the lead is lost (a current leader's usage is already in his value)
CATCH_MED = {"WR": 0.64, "TE": 0.69}   # tgt_lead: median catch rate, WR/TE seasons with 50+ targets, 2018-26 game logs
TGT_LEAD_CATCH_GAP = 0.02         # ... the boost fades out this far below the median
TGT_LEAD_QB = 600.0              # ... with a team QB whose base value is this much (full; none below 75% of it; Herbert $629 on 2026-10-24)
YOUNG_BOOM_EXP = (1, 2)          # young_boom: 2nd-3rd NFL season (Sleeper's exp 1-2; Coker is a 2024 UDFA, exp 2)
YOUNG_BOOM_PPG, YOUNG_BOOM_PTS = 12.0, 30.0   # ... with this PPR/g and a game over this in his last 3 healthy games
YOUNG_BOOM_MAX = 450.0           # ... for a player worth under this (full under 75% of it): a star is priced by his ceiling already
RB_TOUCH_N = 3                   # rb_touch: an RB past his rookie year with fewer than this many 20+ touch games
RB_TOUCH_EXP = 2                 # ... up to this NFL season (exp)
RB_TOUCH_SNAP = 1.0              # ... with a snap share (this season once 3 games, else last) under this
TE_SLIDE_TOP = True              # te_slide: only a TE who had a top-7 season before the slide (a fall, not a slow riser)
QB_TOUGH_MIN = 2                 # qb_tough: at least this many straight seasons hurt-or-top-5 (full at 4)
YPG_THR, YPG_SPAN, YPG_MIN_V = 230.0, 40.0, 1000.0   # qb_ypg: passing yards a game under THR (full SPAN below), QBs worth $1,000+
SNAP_CAP_GAMES = 2               # snap_cap: fewer than this many career games on half the snaps -> at most his league draft price
SNAP_CAP_POS = ("QB",)          # ... at these positions (every position: trades worse, +0.005)
OUT_CLEAN = 0.5                  # an Out tag on a clean record (no games missed over two seasons, has played): half its discount spared
OUT_LONG = 1.0                   # ... rising to all of it with 34+ games since his last absence (Oliver 2026-11-10, votes)
ROOKIE_LOST = -0.4               # a rookie on IR/PUP with <= 1 NFL game and 75%+ of team games missed: rookie year lost (x0.67, Oliver 2026-11-10)
SUMMER_FADE_IN = 90               # summer: rises from 0 this many days before the NFL draft to full at the draft (Oliver 2026-11-10 grid)
SUMMER_FADE_OUT = 0               # ... fading out linearly over this many days before SUMMER_END (0 = hard stop)
SUMMER_END = 7                    # ... and ends this many days after kickoff (Week 1 still counts)
SUMMER_TO_DRAFT = 0.5             # ... share of it lifted after the league draft (Oliver: a smaller post-draft impact; the Aug 2025
                                  # Conner trade $271 vs $292 at -0.7; Oliver chose 0.5)
RB_OLD_AGE, RB_OLD_MINV = 32.0, 1000.0   # rb_old_hi: RBs this old, valued at least this (fading in from 75% of it)
RB_HOLD_TOP = 15                 # rb_hold: last season's RB rank (total PPR) at or above this
RB_HOLD_LO, RB_HOLD_HI = 400.0, 1000.0   # ... base value range, fading over the 25% past each end (Conner $667 on 2025-08-02)
RB_HOLD_MAXV = 600.0            # ... only while his value at this stage is under this (fading from 75% of it)
COMP_YOUNG_AGE = (24.0, 28.0)   # comp_young: the share of the rookie-competition docks spared, full at or under 24, none from 28
COMP_NO_STACK = True             # the three docks for one rookie (draft_comp, r1_wr, wr_backup) as the strongest of them, not their sum
WR_ADV_BAND = (200.0, 300.0, 1500.0, 2200.0)   # wr_adv: base value band (fading in / full / fading out) it reaches
SOPH_PPG, SOPH_DROP, SOPH_SNAP, SOPH_G, SOPH_EXP = 14.0, 0.7, 0.6, 10, 2   # soph_fall: a big early season (14+ PPR/g) then seasons under 70% of it on 60%+ snaps (10+ games)
WR_ROOM_AGE, WR_ROOM_MAXAGE = 29.0, 28.0   # wr_room: the top teammate WR 29+ (full at 32) for a WR under 28 (fading out by 30)
SUMMER_OLD_AGE = 29.0            # summer_old: the summer shift's extra for players 29+ (full at 32)
CEIL_EXP = 1
SPIKE_DROP, YPC_ROLE = 1.0, 1.0
YPC_REC = 0.0
UPSIDE_ROLE = 1.0
SPIKE_ROOKIE_G = 0.001
LEAD_SPARE, RB_YOUNG_COMP = 0.0, -1.0
LEAD_SHARE, LEAD_G = 0.2, 99
ROLE_G = 1
W_FAROFF, FAR_AT, W_CALLS, FAR_OK_RISE = 0.0, 1.8, 1.0, 0.5     # the fit's far-off term (0 = off): trades past 1.8x (80% off) are penalised; W_CALLS weights the calls
RB_JOB_FLOOR = 40.0
PROVEN_FLOOR, PROVEN_PPG, PROVEN_AGE = 0.0, 10.0, 34.0
LOW_ADD, LOW_S, LOW_PPG = 0.0, 60.0, 0.0
SUMMER_MOVE = 0.0                 # share of the summer shift lifted for a player who moved teams that offseason (e_x_moved_off)
SUMMER_LOW, SUMMER_LOW_V = 0.0, (40.0, 150.0)
DC2_FLOOR, DC2_IMPL = 0.0, 26.0     # depth chart: an RB listed second on a top offense (implied points) is worth at least this (the handcuff)
DC1_FLOOR, DC1_WIN, DC1_G = 50.0, 0.65, 6   # depth chart: a starter on a contender (win % so far, 6+ team games) is worth at least this
# (Oliver 2026-11-23: "the fade on bad aging RBs is too strong. White, Dowdle, Aaron Jones ... should be worth a solid
# fourth") an RB 27+ who still holds a share of a backfield this season (4+ games, 40%+ of the snaps, 8+ PPR/g, not on
# IR/PUP) is a weekly flex play a contender pays a late pick for: the age / injury / replacement-line docks cannot take
# him under VET_RB_FLOOR dollars (a solid 4th: $30 at 8 PPR/g, VET_RB_STEP more per PPR/g, VET_RB_CAP at most)
VET_RB_FLOOR, VET_RB_AGE, VET_RB_G, VET_RB_SNAP, VET_RB_PPG, VET_RB_STEP, VET_RB_CAP = 30.0, 27.0, 4, 0.40, 8.0, 2.5, 40.0
PAID_UP, PAID_CAP, PAID_BAND = 0.0, (0.07, 0.12), (-2.0, -1.0, 400.0, 800.0)   # a non-QB the NFL just paid a big veteran deal (APY share of the cap), until he plays
TEAM_NOW_ROOKIE = False
COACH_EASE = 0.0                  # share of the negative team-quality docks lifted in the offseason when his team has a new head coach
TEAM_NOW = True                   # team quality (last season) from the team he is on at the date (load_inputs)
QB_BENCH = -1.0                   # depth chart: a QB who was his team's starter on the charts 3-8 weeks ago and is not now (log, lower only)
DC2_RB, DC2_BAND = 0.0, (-2.0, -1.0, 150.0, 300.0)   # depth chart: an RB listed second on his team's chart (the handcuff), base band
DC1_UP, DC1_POS, DC1_BAND = 0.0, ("WR", "RB", "TE"), (-2.0, -1.0, 60.0, 150.0)   # depth chart: listed first at his position
OUT_ROOKIE = 1.0
# far-off #3 (Fuller 2020, "consistent week-to-week production"): a missed-games dock fades (AVAIL_NOW = how much) for a
# player who has played every team game this season (AVAIL_NOW_G+ games) at AVAIL_NOW_PPG+ PPR/g: he is healthy and producing now
AVAIL_NOW, AVAIL_NOW_G, AVAIL_NOW_PPG, AVAIL_NOW_POS = 1.0, 3, 14.0, ("WR",)
AVAIL_NOW_BAND = (-2.0, -1.0, 1e9, 2e9)
# (Oliver 2026-11-23, Roman Wilson: "6 targets every healthy game this year ... probably worth a low 3/high 4") a young
# WR who has earned a steady target role this season (4+ games, 7+ expected PPR/g, 12%+ of the team's targets, 40%+ of
# the snaps), missed 3+ of the team's games and is healthy now: the missed games, not the role, sank his value, and a
# team pays a late 3rd for that role back on the field: worth at least TGT_FLOOR dollars (0 = off)
TGT_FLOOR, TGT_ROLE_AGE, TGT_ROLE_G, TGT_ROLE_XFP, TGT_ROLE_SH, TGT_ROLE_SNAP, TGT_ROLE_MISS = 57.0, 26.0, 4, 7.0, 0.12, 0.40, 3   # ... back from 3+ missed games
# far-off #3 (Aiyuk 2020: "rookie, target competition"): a rookie's breakout bonus is a few games' sample; it is capped at
# SPIKE_ROOKIE_CAP (a multiplier; 99 = off) while he has under SPIKE_ROOKIE_CAP_G games
SPIKE_ROOKIE_CAP, SPIKE_ROOKIE_CAP_G = 1.6, 6
# far-off #3 (Fuller 2020, "consistent week-to-week production boost in that range"): a low-base WR scoring like a starter
# two seasons running (PROD_L0+ PPR/g last season, PROD_CUR+ over PROD_G+ games this one) is raised (PROD_LO, a log term)
PROD_LO, PROD_L0, PROD_CUR, PROD_G, PROD_POS = 0.4, 12.0, 14.0, 4, ("WR",)
PROD_BAND = (40.0, 80.0, 200.0, 300.0)
# far-off #5 (Brooks 2024-12-09, "bigger cut for injury severity": he left his last game after 1 touch with a re-torn ACL;
# no injury tag yet): a skill player with no tag whose last game's touches + targets fell under EXIT_R of his recent
# average (an early exit or a benching) takes EXIT (a log term) until he plays again
EXIT, EXIT_R = -1.5, 0.25
# far-off #7 / #24 (Dobbins: "run-first offense, no competition"): a young RB's missed-games dock fades (RUN_AVAIL = how
# much) when the carries are his once healthy: a run-first team (team_run 0.25 none -> 0.30 full) whose other RBs are older (28+)
RUN_AVAIL = 1.0
# far-off #9 (Mike Davis 2020-10-01, "huge carries, cuff"): a cheap RB whose share of his team's expected points this
# season (3+ games) is well above last season's (+XFP_JUMP_LO none, +XFP_JUMP_HI full) has the job now: raised (XFP_JUMP)
XFP_JUMP, XFP_JUMP_LO, XFP_JUMP_HI, XFP_JUMP_BAND = 3.0, 0.08, 0.18, (-2.0, -1.0, 60.0, 120.0)
# Oliver (round 6, #57 Herbert): "an activated cuff should be a short term boost, esp pre-playing". When his team's lead
# RB has just missed a game or left one early (e_x_cuff_act = games in a row, 1 = just went down) the RB who was second
# going in is raised by CUFF_ACT (log), fading over CUFF_FADE games as the injury shows in his own usage, at a base
# under CUFF_BAND's top. Does not stack on xfp_jump / rb_role (the larger counts).
RQB_OFF = True
RQB_WR, RQB_PICK, RQB_SH, RQB_BAND = 2.0, 12, 0.2, (-2.0, -1.0, 300.0, 600.0)   # (trial) top target of a top-12 rookie QB
# (#57 Herbert, #19 "cuff premium"): a young RB behind one lead back (that back holds CUFF_PREM_COMP+ of the other RBs'
# share) with a role of his own this season (CUFF_PREM_SH+ of the team's expected points): one injury from the job
CUFF_PREM, CUFF_PREM_COMP, CUFF_PREM_SH, CUFF_PREM_AGE, CUFF_PREM_BAND = 1.0, 0.65, 0.10, 26.0, (-2.0, -1.0, 80.0, 160.0)
# Oliver (round 6, #28 / #35, "a real phenomenon", kept although it costs trades overall): the league pays a small
# premium for Giants players: an NYG player (his NFL team on the date, e_x_nyg) is raised by NYG_UP (log) in NYG_BAND
NYG_UP, NYG_BAND = 0.2231, (-2.0, -1.0, 300.0, 600.0)
AVAIL_UP_XFP, AVAIL_UP_POS, AVAIL_UP_V = (10.0, 13.0), ("WR", "TE"), 100.0
VAC_SPARE = 0.0
SUSP_EASE = 1.0
NOT_BACK, NOT_BACK_G = -0.3, 14
NOT_BACK_SKIP = ("Out", "Doubtful", "Questionable")
CONTRACT_SIT, CONTRACT_SIT_MID, CONTRACT_SIT_AGE, CONTRACT_SIT_BAND = 0.0, 22.5, 30.0, (-2.0, -1.0, 400.0, 800.0)
DOCK_CAP, DOCK_KEEP, DOCK_POS = -99.0, ("summer",), ("QB", "RB", "WR", "TE")
SPIKE_DAY3, SPIKE_DAY3_PICK = 0.5, 100
CUFF_ACT, CUFF_FADE, CUFF_BAND = 2.0, (1.0, 2.0, 4.0), (-2.0, -1.0, 150.0, 300.0)
# far-off #14 / #16 / #20 / #48 / #51 (Pacheco to Detroit, Samuel to Buffalo, Gallup, JSN after DK, Palmer 2024): in the
# offseason, a player whose upcoming team lost players at his position holding a share of its expected points (net of
# other newcomers', e_x_vacated) has a role opening: raised (VAC_UP, a log term; VAC_LO none, VAC_HI full) in VAC_BAND
VAC_UP, VAC_LO, VAC_HI, VAC_BAND = 1.0, 0.05, 0.2, (-2.0, -1.0, 300.0, 500.0)
VAC_STACK = 1.0
VAC_WR_RANK = (24, 0.0)   # (best position rank, weight of vac_up for a WR/TE never that good; 1 = off)
VAC_POS = (1.0, 1.0, 1.0)   # vac_up weight for RB, WR, TE (Oliver 2026-11-23: test RB-only / half for WRs)
VAC_LESS = False   # vac_up only when his own share of his team's expected points last season is under the share that left
VAC_IMPL = (18.0, 22.0)  # vac_up fades in with his team's implied points last season (none at [0], full from [1]; (0, 1) = always full)
# far-off #14 (Oliver 2026-11-22, Pacheco to Detroit: "removing some docks from RBs in a range under a certain age when
# they switch teams"): an RB under MOVE_AGE who changed teams this offseason (or is new and has under 4 games there),
# at a base under MOVE_V (fading out at 1.5x), has his old-role docks eased by MOVE_EASE (0..1): bad YPC, duds, wear
# (rb_inj) and missed games, which were read behind his old line, in his old committee
MOVE_PROVEN, MOVE_PROVEN_AGE, MOVE_PROVEN_RANK = 0.17, 28.0, 15   # log boost on top of MOVE_EASE (Oliver: Pacheco)
REPL_TOP_RANK = 3
REPL_TOP2 = 0.0    # share of the replacement-line dock lifted for a former top-REPL_TOP_RANK PPR finisher at his position (NFL, last 4 seasons; Oliver)
MOVE_IMPL = 24.0   # ... and a new team scoring at least this many implied points a game last season (0 = any)
MOVE_VAC = 0.1     # MOVE_EASE only for a move into a vacated role (e_x_vacated at least this; -99 = any move)
MOVE_FIRST = False   # first NFL team switch only (Oliver): needs e_x_n_teams (scratch-only; tested 11-22: same result, every case was a first switch)
MOVE_EASE, MOVE_AGE, MOVE_V, MOVE_DOCKS = 1.0, 28.0, 200.0, ("ypc_bad", "rb_duds", "rb_inj", "availability", "replacement line", "share_talent", "usage")
OUT_STAR, OUT_STAR_PPG, OUT_STAR_POS = 0.5, 18.0, ("RB",)
VAC_OWN = 0.06    # ... for a player who had a role last season (his share of his team's expected points) or missed it (under 8 games)
TD_SPIKE, TD_SPIKE_SNAP, TD_SPIKE_V = -1.2, 0.55, (1000.0, 1500.0)
RUN_UP = 0.0
RUN_UP_BAND = (-2.0, -1.0, 250.0, 400.0)   # rb_run_team: a young RB (under 27) at a base under $250
RB_YOUNG_G = 1   # rb_young_comp before this many games this season (the offseason read; in-season his own games say)
SPIKE_ROOKIE_COMP = 0.6   # ... when young teammates (under 28) hold 60%+ of the position's share (Kittle, Deebo)
UPSIDE_BAND = (200.0, 300.0, 1e9, 2e9)   # ... at a base of $300+ (a priced-in prospect; a cheap backup's upside is the bet)
ROLE_BAND = (-2.0, -1.0, 100.0, 150.0)   # rb_role base band
SPIKE_DROP_EXP, SPIKE_DROP_BAND = 2, (-2.0, -1.0, 1e9, 2e9)
ROLE_LO = 0.0   # rb_role: -1 = a lost job lowers too, 0 = only a won job raises
CEIL_POS = ("RB", "WR", "TE")
CEIL_VET_EXP = 5   # ceiling_lo skips a WR past this many seasons (a vet's ceiling is known and priced)
PEAK_AGE = 24.5
PEAK_SEASONS = 2
PEAK_BAND = (2500.0, 2900.0)
QB_PROOF_N = 6
QB_SPARE = 1.0
COMP_POS, COMP_BAND = ("WR",), (560.0, 580.0, 760.0, 780.0)   # comp_young's reach
QB_START_ADD, QB_START_SNAP, QB_START_PPG, QB_START_FLOOR = 0.0, 0.9, 13.0, 60.0   # Penix floor: a 3rd ($60); 10 PPG (Oliver) floors Mills / O'Connell / Cousins, whom the league traded for less
FLOP_PPG = 10.0   # flop_r1: under 10 PPR a game (6 = full)
# round 6 (Oliver 2026-11-22, Ridley 2023: "formerly great players with a resurgence get a bigger spike"): the spike's
# age fade starts SPIKE_PROVEN years later for a player with a 15+ PPR/g season in the last four
SPIKE_PROVEN = 0.0
BOOM_RATE, BOOM_V, BOOM_POS = (0.3, 0.15), (500.0, 550.0, 850.0, 950.0), ("RB",)   # boom_rate_lo: RB, base $550-850 (Chase Brown; Jacobs at $1,006 is outside)
RUN_LO = (0.17, 0.21)
RUN_BAND = (500.0, 550.0, 850.0, 950.0)   # rb_pass_team's base band
RUN_BOOM = 0.3   # rb_pass_team only for an RB whose 20+ game rate is under this (9 = every RB)
CONTRACT_AGE = 28.0   # contract_old from 27 (half) / 28 (full); contract_boom under it
CEIL_FULL_L0 = True   # ceiling_lo: only with a full (8+ game) last season, so a sample cut short by injury is not judged
CEIL_PTS, CEIL_SPAN, CEIL_BAND = 28.0, 4.0, (150.0, 250.0, 99999.0, 99999.0)   # ceiling_lo: best game under 28 PPR (24 = full), base $250+
NEW_HOME_PPG, NEW_HOME_G, NEW_HOME_V = 3.0, 5, (1200.0, 1800.0)   # ... at a value (after compression) fading in over NEW_HOME_V   # new_home: 3+ PPR a game over last season (9+ = full) on a new team, 5+ games
CUTDOWN = ((8, 24), (9, 3))      # cutdown: the days before and at the NFL's roster cutdown (late August to Sep 3)
DRAFT_COMP_NEW = 0.5             # draft_comp: share taken off for a player who joined the team that offseason (not vs a first-rounder)


def catch_ok(R, pos):
    """1 for a WR/TE who catches at least his position's typical share of his targets (last two seasons and this one,
    e_x_catch3), fading to 0 at TGT_LEAD_CATCH_GAP below it; 1 where the column is missing (Oliver 2026-11-10: McConkey
    68% and Kraft 71% keep the target-lead boost, Quentin Johnston 60% does not)"""
    c = col(R, "e_x_catch3"); med = np.select([pos == "WR", pos == "TE"], [CATCH_MED["WR"], CATCH_MED["TE"]], np.nan)
    return np.where(np.isnan(c) | np.isnan(med), 1.0, np.clip((c - med + TGT_LEAD_CATCH_GAP) / max(TGT_LEAD_CATCH_GAP, 1e-9), 0, 1))


def rb_moved(R):
    """1 (fading) for an RB under MOVE_AGE who switched teams (MOVE_EASE): see MOVE_EASE"""
    if not MOVE_EASE: return np.zeros(len(R))
    mv = (np.nan_to_num(col(R, "e_x_moved_off")) > 0) | ((np.nan_to_num(col(R, "e_x_new_team")) > 0) & (np.nan_to_num(col(R, "e_x_gp_cur")) < 4))
    if MOVE_FIRST: mv = mv & (np.nan_to_num(col(R, "e_x_n_teams"), nan=9) <= 2)   # his first NFL team switch only (Oliver)
    if MOVE_VAC > -9: mv = mv & (np.nan_to_num(col(R, "e_x_vacated"), nan=-1) >= MOVE_VAC)   # (Oliver: Pacheco takes over Monty's role) only into a vacated role
    if MOVE_IMPL: mv = mv & (np.nan_to_num(col(R, "e_x_team_implied_l0")) >= MOVE_IMPL)   # ... on a good offense (his new team's, TEAM_NOW)
    return MOVE_EASE * (R.pos.values == "RB") * (np.nan_to_num(col(R, "age"), nan=99) < MOVE_AGE) * mv * np.interp(np.maximum(np.nan_to_num(col(R, "V_raw")), 0), [MOVE_V, 1.5 * MOVE_V], [1, 0])


def final_terms(R, v, p, X):
    """{rule: log multiplier} of the final stage on value v (one per row of R)"""
    pos = R.pos.values; exp_ = np.nan_to_num(col(R, "exp")); age = np.nan_to_num(col(R, "age"), nan=25.0)
    cur_g = np.nan_to_num(col(R, "e_x_cur_games")); gp = np.nan_to_num(col(R, "e_x_gp_cur"))
    lv = np.log(np.maximum(v, 1.0)); T = {}
    # a veteran starter is never worth nothing: a 5th-year-plus QB/RB/WR who plays 60%+ of the snaps has a floor near $40
    # (a team that starts him would not cut him for a waiver body). vet_floor closes that share of the log gap.
    snap = np.fmax(np.nan_to_num(col(R, "e_x_cur_off_pct")), np.nan_to_num(col(R, "e_x_l0_off_pct")))
    ppg = np.where(gp >= 3, col(R, "e_x_ppg_cur"), col(R, "e_x_ppg_l0"))
    gate = np.isin(pos, VET_FLOOR_POS) * (exp_ >= VET_FLOOR_EXP) * (snap >= VET_FLOOR_SNAPS) * ((VET_FLOOR_PPG <= 0) | (np.nan_to_num(ppg) >= VET_FLOOR_PPG))
    T["vet_floor"] = p.get("vet_floor", 0.0) * gate * np.clip(np.log(VET_FLOOR) - lv, 0, 4)
    # an RB's duds (full-role games under 5 PPR, last two seasons) before he has played 3 games: a low floor the league
    # prices in until this season shows otherwise (the WR/TE duds rule's RB side, preseason only)
    T["rb_duds"] = p.get("rb_duds", 0.0) * (pos == "RB") * (gp < 3) * np.clip(np.nan_to_num(col(R, "e_x_duds_2y")) / 2.0, 0, 1.5)
    # the league pays less for a WR1-tier WR than the base does ($1.3-2.3K, Oliver: "how we value WRs"), and the same
    # for a mid-tier QB; a cheap RB ($45-90) is worth a bit more (a handcuff with a path)
    T["wr_band"] = p.get("wr_band", 0.0) * (pos == "WR") * np.interp(lv, BAND_LOG, [0, 1, 1, 0])
    T["qb_band"] = p.get("qb_band", 0.0) * (pos == "QB") * np.interp(lv, BAND_LOG, [0, 1, 1, 0])
    T["rb_band"] = p.get("rb_band", 0.0) * (pos == "RB") * np.interp(lv, RB_BAND_LOG, [0, 1, 1, 0])
    # an RB 26+ hurt in several places (distinct body parts on the report, 3 seasons): wear the league discounts, unless he
    # has scored like a star since he came back (19+ PPR a game over 3+ games, less with more games: Oliver, Walker 2026)
    thr = np.maximum(RB_INJ_PPG - RB_INJ_PPG_STEP * np.maximum(np.nan_to_num(col(R, "e_x_gp_since_inj")) - 3, 0), RB_INJ_PPG_MIN)
    back = (np.nan_to_num(col(R, "e_x_gp_since_inj")) >= 3) & (np.nan_to_num(col(R, "e_x_ppg_since_inj")) >= thr)
    won_ = (AT_WON_JOB != 0) & (np.nan_to_num(col(R, "exp")) >= 2) & (np.nan_to_num(col(R, "e_x_rookie_backup")) > 0) & (np.nan_to_num(col(R, "e_x_gp_cur")) >= 1) & (np.nan_to_num(col(R, "e_x_gp_cur")) <= 2) \
        & (np.nan_to_num(col(R, "e_x_cur_big")) >= 1) & (np.nan_to_num(col(R, "e_x_cur_xfp_share")) >= 0.2)   # AT_WON_JOB: won the job, so no wear dock
    T["rb_inj"] = p.get("rb_inj", 0.0) * (pos == "RB") * (age >= RB_INJ_AGE) * ~back * ~won_ * np.clip(np.nan_to_num(col(R, "e_x_bodyparts_3y")) / 2.0, 0, 1.5)
    # a veteran RB's big weeks are last season's before his 3rd game: the spike bonus (a breakout) counts less for him
    T["spike_vet_rb"] = p.get("spike_vet_rb", 0.0) * X["spike"] * (pos == "RB") * (cur_g < 3) * (exp_ >= 3)
    # a rookie whose rookie year is being lost on IR/PUP (at most 1 NFL game, 75%+ of his team's games missed): no role, no tape
    T["rookie_lost"] = ROOKIE_LOST * (exp_ == 0) * np.isin(R.injury.fillna("").values, ["IR", "PUP"]) * (cur_g <= 1) * (np.nan_to_num(col(R, "e_x_inj_rate_2y")) >= 0.75)
    # a QB who misses games (out-or-doubtful share of his weeks, 2 seasons; 25% = full): superflex needs him every week
    T["qb_inj"] = p.get("qb_inj", 0.0) * (pos == "QB") * np.clip(np.nan_to_num(col(R, "e_x_inj_rate_2y")) / 0.25, 0, 1.5)
    # a veteran WR whose team's league owner just paid for a same-team rookie WR (e_x_rookie_backup, $250 = 1, capped at
    # 2): the league expects the rookie's role to come out of his (never a WR who is himself a rookie)
    rbk = np.nan_to_num(col(R, "e_x_rookie_backup"))
    T["wr_backup"] = p.get("wr_backup", 0.0) * (pos == "WR") * (exp_ >= 1) * (rbk >= WR_BACKUP_MIN) * np.clip(rbk / 250.0, 0, 2.0)
    # a WR 26+ with a clean record: the clean-record boost (avail_up) is worth less to the league for him
    T["wr_clean_old"] = p.get("wr_clean_old", 0.0) * np.maximum(X["availability"], 0) * (pos == "WR") * (age >= 26)
    # round 5. A young receiver/back who just had a 30+ PPR game in his last three healthy games and scores 12+ a game:
    # the league prices the ceiling it has just seen (Oliver 2026-11-09, Coker)
    ppg_b = np.where(gp >= 3, col(R, "e_x_ppg_cur"), col(R, "e_x_ppg_l0"))
    T["young_boom"] = p.get("young_boom", 0.0) * np.isin(pos, ("RB", "WR", "TE")) * (exp_ >= YOUNG_BOOM_EXP[0]) * (exp_ <= YOUNG_BOOM_EXP[1]) \
        * (np.nan_to_num(ppg_b) >= YOUNG_BOOM_PPG) * (np.nan_to_num(col(R, "e_x_recent_max3")) > YOUNG_BOOM_PTS) \
        * np.interp(lv, np.log([0.75 * YOUNG_BOOM_MAX, YOUNG_BOOM_MAX]), [1, 0])
    # an RB past his rookie year who has rarely carried a full load (few career games over 20 touches): the league does
    # not pay for a workhorse it has not seen (Oliver 2026-11-09, Tuten: one such game)
    sn_b = np.where(cur_g >= 3, col(R, "e_x_cur_off_pct"), col(R, "e_x_l0_off_pct"))
    T["rb_touch"] = p.get("rb_touch", 0.0) * (pos == "RB") * (exp_ >= 1) * (exp_ <= RB_TOUCH_EXP) * (np.nan_to_num(sn_b) < RB_TOUCH_SNAP) \
        * np.where(np.isnan(col(R, "e_x_touch20")), 0.0, np.clip(1 - np.nan_to_num(col(R, "e_x_touch20")) / RB_TOUCH_N, 0, 1))   # no game log: off
    # a TE whose last two seasons both finished outside the top 7 TEs (twice as much when the last was outside the top
    # 20), unless 3 of his last 4 games were top-5 TE weeks (Oliver 2026-11-09, LaPorta; the OC change he named is not in
    # the data)
    sl = np.nan_to_num(col(R, "e_x_te_slide"))
    if TE_SLIDE_TOP: sl = sl * (np.nan_to_num(col(R, "e_x_te_was_top")) > 0)
    T["te_slide"] = p.get("te_slide", 0.0) * (pos == "TE") * sl * (1 - np.nan_to_num(col(R, "e_x_te_recovered")))
    # a QB who has been either hurt or top 5 for several straight seasons: when he plays he is elite (Oliver 2026-11-09, Burrow)
    st = np.nan_to_num(col(R, "e_x_qb_hurt_top"))
    T["qb_tough"] = p.get("qb_tough", 0.0) * (pos == "QB") * (st >= QB_TOUGH_MIN) * np.clip(st / 4.0, 0, 1)
    # a receiver who led his team in targets (18%+ of them, 4+ games into a season) and has since lost the lead, fading
    # over his next 17 games, with a good QB (base $600+): the league keeps paying for a good QB's go-to target after an
    # injury or a new teammate takes the lead for a while (Oliver 2026-11-09, McConkey and Kraft)
    base = np.maximum(col(R, "V_raw"), 0); qv = np.nan_to_num(col(R, "e_x_qb_base")); tl = np.nan_to_num(col(R, "e_x_tgt_lead_w"))
    T["tgt_lead"] = p.get("tgt_lead", 0.0) * np.isin(pos, ("WR", "TE")) * (base >= TGT_LEAD_LO) * (base <= TGT_LEAD_HI) \
        * np.interp(qv, [0.75 * TGT_LEAD_QB, TGT_LEAD_QB], [0, 1]) * tl * ((tl < 0.999) | (not TGT_LEAD_LOST)) \
        * catch_ok(R, pos)
    # a QB with almost no NFL snaps (under 2 career games on half the snaps) is worth at most what the league paid for
    # him in its rookie draft (Oliver 2026-11-09, Mendoza)
    pr = col(R, "e_x_league_draft_price")
    capped = (p.get("snap_cap", 0.0) > 0) & np.isin(pos, SNAP_CAP_POS) & (np.nan_to_num(col(R, "e_x_big_games"), nan=99) < SNAP_CAP_GAMES) & ~np.isnan(pr)
    T["snap_cap"] = np.where(capped, np.minimum(0.0, np.log(np.maximum(np.nan_to_num(pr), 1.0)) - lv), 0.0)
    # a $1,000+ QB with low passing volume (passing yards a game, this season once 4 games else last): the knock on Hurts
    # (Oliver 2026-11-09: "a stat Hurts famously was very bad at"; time to throw, the other candidate, docks Allen, Lamar
    # and Purdy as much as him and breaks their calls)
    ypg = np.nan_to_num(col(R, "e_x_pass_ypg"), nan=YPG_THR)
    T["qb_ypg"] = p.get("qb_ypg", 0.0) * (pos == "QB") * np.interp(lv, np.log([0.75 * YPG_MIN_V, YPG_MIN_V]), [0, 1]) \
        * np.clip((YPG_THR - ypg) / YPG_SPAN, 0, 1.5)
    # an RB 32 or older valued $1,000+ (fading in from $750): the league will not pay first-round money for a back that
    # age, however well he is still running, since the drop comes without warning (Oliver 2026-11-10, Henry)
    T["rb_old_hi"] = p.get("rb_old_hi", 0.0) * (pos == "RB") * (age >= RB_OLD_AGE) * np.interp(lv, np.log([0.75 * RB_OLD_MINV, RB_OLD_MINV]), [0, 1])
    # an RB who was a top-15 RB last season and whose team added no proven RB (a 13+ PPR/game season in the last two) and
    # no rounds 1-2 rookie for this one: the job is still his, which the league pays for even as he ages (Oliver
    # 2026-11-09, the Aug 2025 Conner trade). Base RB_HOLD_LO-HI, fading over the 25% beyond each end.
    rk_ = col(R, "e_x_rb_prev_rank")
    T["rb_hold"] = p.get("rb_hold", 0.0) * (pos == "RB") * (np.nan_to_num(rk_, nan=99) <= RB_HOLD_TOP) * (np.nan_to_num(col(R, "e_x_rb_comp"), nan=1) == 0) \
        * np.interp(base, [0.75 * RB_HOLD_LO, RB_HOLD_LO, RB_HOLD_HI, 1.25 * RB_HOLD_HI], [0, 1, 1, 0]) \
        * np.interp(lv, np.log([0.75 * RB_HOLD_MAXV, RB_HOLD_MAXV]), [1, 0])
    mvd = rb_moved(R)
    for k in ("rb_duds", "rb_inj"):
        if k in MOVE_DOCKS: T[k] = T[k] * (1 - mvd)
    return T


# Targeted rules (Oliver 2026-11-23: "a targeted attach for each of the 9 ... something unique or nearly-unique"). Each keys
# on stats only (any player can meet it in any season); strengths 0 = off. AT_* names the trade that prompted it.
AW_ELITE, AW_ELITE_BAND, AW_ELITE_POS = 0.45, (2000.0, 4000.0), ("RB",)   # share of the NFL-award boost removed for a top base (0 = off)
AT_EX_ELITE = 2.72 # Saquon Barkley 2026: a 28+ RB/WR who finished top 3 at his position in the last 4 seasons and is still his
                   # team's depth-chart starter (not on IR / PUP: Oliver, a short-term Out keeps it): a former elite starter is not a cheap aging body yet
WR_TOP, WR_TOP_AT = 0.4, 3600.0   # a WR's final value above WR_TOP_AT keeps only this share of the excess (1 = off)
AT_EX_ELITE_IR = 1.03  # AT_EX_ELITE on IR / PUP x this (Oliver 2026-11-23: still about a 2.08 on IR; over 1 because the IR docks still apply)
AT_EX_ELITE_OUT = 1.17 # AT_EX_ELITE on Out / Doubtful x this (Oliver: 2.05 healthy, 2.06 Out, 2.08 IR)
AT_TE_TD = 1.3     # Cole Kmet 2022: a young TE (under 26) with a 16%+ target share and no touchdowns last season (14+ games): TDs follow volume
AT_PAID_BRK = 0.6  # Mike Williams 2022: a WR just paid 9%+ of the cap after a breakout (14+ PPG, 4+ over the year before): the team bet on him
AT_CROWD = -0.5     # Hunter Renfrow 2022 (Davante Adams arrives): offseason, after a one-year jump (5+ PPG over the year before) his team added
                   # receivers holding 8%+ of its expected points (vacated <= -0.08): the jump came in a role the newcomer now takes
AT_OUT_EARLY = 0.5 # Tee Higgins 2024: Out in week 1-2 with no game played, a 12+ game starter last season: a short early absence
AT_CUR_LEAD = 0.2  # Courtland Sutton 2022: 3+ games, a 25%+ target share and 5+ PPG over last season: a new lead role
AT_EFF_LEAD = 0.0  # Damien Harris 2021: an RB at 4.8+ yards a carry (2 seasons) whose team's lead back left (vacated 10%+)
AT_MOVE_PAID = 1.0 # Curtis Samuel 2024: a WR who signed with a new team (new deal) into a 15%+ vacated role: no waiver body
AT_FADE = -0.3      # Tre Tucker 2025: 8+ games in, his opportunity fell under 45% of his earlier level, on a team winning under 25%
AT_LEAD_CHEAP = 0.5  # Jakobi Meyers 2021: his team's target leader (24%+ share last season) priced under $100 base: no waiver body
AT_WON_JOB = 1.8   # Malcolm Brown 2020: a veteran RB behind a league-priced rookie who led the backfield once games began (20%+ xFP share)


def _attach(R, T_, pos, raw):
    c_ = lambda n, d=0.0: np.nan_to_num(col(R, n), nan=d)
    def spare(k, m, a):
        if k in T_: T_[k] = np.where(m, np.where(T_[k] < 0, T_[k] * (1 - a), T_[k]), T_[k])
    off_ = (c_("e_x_offseason") > 0) | (c_("e_x_gp_cur") == 0)
    if AT_TE_TD:
        T_["at_te_td"] = AT_TE_TD * ((pos == "TE") & (c_("age", 99) < 26) & (c_("e_x_l0_tgt_share") >= 0.16) & (c_("e_x_l0_td_share") <= 0.01) & (c_("e_x_l0_games") >= 14) & (c_("e_x_gp_cur") < 4))
    if AT_PAID_BRK:
        m = (pos == "WR") & (c_("e_x_vet_deal_cap") >= 0.09) & (c_("e_x_ppg_l0") >= 14) & (c_("e_x_ppg_l0") - c_("e_x_ppg_l1", 99) >= 4) & off_
        spare("replacement line", m, 1.0); T_["at_paid_brk"] = AT_PAID_BRK * m
    if AT_CROWD:
        T_["at_crowd"] = AT_CROWD * (np.isin(pos, ["WR", "TE"]) & (c_("exp") >= 1) & (c_("e_x_offseason") > 0) & (c_("e_x_vacated") <= -0.08) & (c_("e_x_ppg_l0") - c_("e_x_ppg_l1", 99) >= 5))
    if AT_OUT_EARLY:
        m = (R.injury.fillna("").values == "Out") & (c_("e_x_team_games_cur", 9) <= 2) & (c_("e_x_gp_cur") == 0) & (c_("e_x_l0_games") >= 12) & (c_("exp") >= 2) & (raw >= 300)
        spare("inj_out", m, AT_OUT_EARLY)
    if AT_CUR_LEAD:
        m = (pos == "WR") & (c_("e_x_gp_cur") >= 3) & (c_("e_x_cur_tgt_share") >= 0.25) & (c_("e_x_ppg_cur") - c_("e_x_ppg_l0", 99) >= 5) & (raw < 300)
        spare("replacement line", m, 1.0); T_["at_cur_lead"] = AT_CUR_LEAD * m
    if AT_EFF_LEAD:
        T_["at_eff_lead"] = AT_EFF_LEAD * ((pos == "RB") & (c_("exp") >= 1) & (c_("e_x_ypc_2y") >= 4.8) & (c_("e_x_vacated") >= 0.1) & (c_("e_x_offseason") > 0))
    if AT_MOVE_PAID:
        m = (pos == "WR") & (c_("e_x_moved_off") > 0) & (c_("e_x_vet_deal_cap") > 0) & (c_("e_x_vacated") >= 0.15)
        spare("replacement line", m, AT_MOVE_PAID)
    if AT_FADE:
        T_["at_fade"] = AT_FADE * (np.isin(pos, ["WR", "TE", "RB"]) & (c_("e_x_gp_cur") >= 8) & (c_("e_x_last_opp_ratio", 9) < 0.45) & (c_("e_x_team_win_cur", 1) < 0.25))
    if AT_LEAD_CHEAP:
        T_["at_lead_cheap"] = AT_LEAD_CHEAP * ((pos == "WR") & (c_("e_x_tgt_lead_w") >= 1) & (c_("e_x_l0_tgt_share") >= 0.24) & (raw < 100) & (c_("exp") >= 1))
    if AT_EX_ELITE:
        T_["at_ex_elite"] = AT_EX_ELITE * (np.isin(pos, ["RB", "WR"]) & (c_("age") >= 28) & (c_("e_x_best_rank_4y", 99) <= 3) & (c_("e_x_dc_rank", 9) == 1) & (raw < 400)) \
            * np.select([np.isin(R.injury.fillna("").values, ["IR", "PUP"]), np.isin(R.injury.fillna("").values, ["Out", "Doubtful"])], [AT_EX_ELITE_IR, AT_EX_ELITE_OUT], 1.0)   # (Oliver) IR/PUP: a share of the raise
    if AT_WON_JOB:
        m = (pos == "RB") & (c_("exp") >= 2) & (c_("e_x_rookie_backup") > 0) & (c_("e_x_gp_cur") >= 1) & (c_("e_x_gp_cur") <= 2) & (c_("e_x_cur_big") >= 1) & (c_("e_x_cur_xfp_share") >= 0.2) & (raw < 100)
        for k in ("rookie_backup", "share_talent", "replacement line"): spare(k, m, 1.0)
        T_["at_won_job"] = AT_WON_JOB * m   # (rb_inj spared in final_terms)


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
    # WRs at the top (wr_hi, lower only): an elite RB stands further above a flex-level starter than an elite WR does (top-3
    # PPG over the 24th, rostered, weeks 1-14: RB 1.75-2.20 vs WR 1.66-1.85 in 2021-25, RB higher in 4 of 5), and the
    # league's own fit already prices the top RBs up (rb_hi at its +0.6 bound). Held at -0.5 on Oliver's call (2026-11-18:
    # "JSN jumped Gibbs & Bijan ... increase the fade on WRs in that range"); trades are indifferent (-0.08 to -0.6 all
    # within 0.0003), -0.75 breaks CeeDee > Kyren.
    unpriced = np.clip((p.get("spike_hi", 1500) - v) / (0.6 * p.get("spike_hi", 1500)), 0, 1)     # a breakout the base value has not priced in
    T_ = {k: p.get(k, 0) * X[x] for k, x in RULE_KEYS.items()}
    # on IR the IR rule already charges for this season's injury: availability counts only the seasons before it
    # availability: missed games lower a value (availability); a clean record raises it by its own strength (avail_up)
    # (#17 Tucker "max $15") the clean-record boost needs a role: it fades in from AVAIL_UP_XFP[0] to [1] expected
    # PPR/g this season (4+ games; else last season's) for a WR / TE: every game played as a small part is no premium
    avr = np.ones(len(R))
    if float(AVAIL_UP_XFP[1]) > 0:
        xg = np.where(np.nan_to_num(col(R, "e_x_cur_games")) >= 4, col(R, "e_x_cur_xfp_pg"), col(R, "e_x_l0_xfp_pg"))
        avr = np.where(np.isin(pos, AVAIL_UP_POS) & ~np.isnan(xg) & (np.nan_to_num(col(R, "V_raw"), nan=0) < AVAIL_UP_V), np.clip((np.nan_to_num(xg) - float(AVAIL_UP_XFP[0])) / (float(AVAIL_UP_XFP[1]) - float(AVAIL_UP_XFP[0])), 0, 1), 1.0)
    av_ = lambda x: p.get("availability", 0) * np.minimum(x, 0) + p.get("avail_up", 0) * np.maximum(x, 0) * avr
    T_["availability"] = np.where(X["ir"] > 0, (1 - p.get("ir_no_double", 0.0)) * av_(X["availability"]) + p.get("ir_no_double", 0.0) * av_(X["avail_prior"]), av_(X["availability"]))
    # a young player's missed games: the availability drop is floored (avail_young_floor, a multiplier; 0 = off) under
    # avail_young_age, fading out over the 2 years after (Oliver: Brooks, Dobbins, Kyren)
    yf = p.get("avail_young_floor", 0.0)
    if yf > 0:
        yw = np.clip((p.get("avail_young_age", 24.0) + 2.0 - np.nan_to_num(col(R, "age"), nan=30)) / 2.0, 0, 1)
        T_["availability"] = np.maximum(T_["availability"], (1 - yw) * T_["availability"] + yw * np.log(yf))
    if PROD_LO:
        T_["prod_lo"] = PROD_LO * ((np.nan_to_num(col(R, "e_x_ppg_l0")) >= PROD_L0) & (np.nan_to_num(col(R, "e_x_ppg_cur")) >= PROD_CUR) & (np.nan_to_num(col(R, "e_x_gp_cur")) >= PROD_G) & np.isin(pos, PROD_POS)) * np.interp(raw, PROD_BAND, [0, 1, 1, 0])
    if VAC_UP:
        T_["vac_up"] = VAC_UP * np.select([pos == "RB", pos == "WR", pos == "TE"], [float(v) for v in VAC_POS], 0.0) * (np.nan_to_num(col(R, "exp")) >= 1) * ((np.nan_to_num(col(R, "e_x_l0_xfp_share")) >= VAC_OWN) | (np.nan_to_num(col(R, "e_x_l0_games")) < 8)) * np.clip((np.nan_to_num(col(R, "e_x_vacated")) - VAC_LO) / (VAC_HI - VAC_LO), 0, 1) * np.interp(raw, VAC_BAND, [0, 1, 1, 0]) \
            * np.interp(np.nan_to_num(col(R, "e_x_team_implied_l0"), nan=99), VAC_IMPL, [0, 1]) \
            * ((np.nan_to_num(col(R, "e_x_l0_xfp_share")) < np.nan_to_num(col(R, "e_x_vacated"))) | (not VAC_LESS))
        if float(VAC_WR_RANK[1]) < 1:   # a WR/TE who has never finished in the top VAC_WR_RANK[0] at his position (last 4 seasons) is
            # not yet proven in a lead role: only VAC_WR_RANK[1] of the raise (Oliver 2026-11-23, Gabe Davis / Xavier Worthy vs Curtis Samuel / Cooper Kupp)
            un_ = np.isin(pos, ["WR", "TE"]) & ~(np.nan_to_num(col(R, "e_x_best_rank_4y"), nan=999) <= float(VAC_WR_RANK[0]))
            T_["vac_up"] = np.where(un_, T_["vac_up"] * float(VAC_WR_RANK[1]), T_["vac_up"])
        # ... fading out on a bad offense (his new team's, TEAM_NOW), and (VAC_LESS, Oliver) only into a bigger role than his own
    if XFP_JUMP:
        xj = np.nan_to_num(col(R, "e_x_cur_xfp_share")) - np.nan_to_num(col(R, "e_x_l0_xfp_share"), nan=1)
        T_["xfp_jump"] = XFP_JUMP * (pos == "RB") * (np.nan_to_num(col(R, "e_x_gp_cur")) >= 3) * np.clip((xj - XFP_JUMP_LO) / (XFP_JUMP_HI - XFP_JUMP_LO), 0, 1) * np.interp(raw, XFP_JUMP_BAND, [0, 1, 1, 0])
    if RQB_WR:
        rq = col(R, "e_x_rookie_qb_pick")
        T_["rqb_wr"] = RQB_WR * np.isin(pos, ["WR", "TE"]) * (np.nan_to_num(rq) > 0) * (np.nan_to_num(rq) <= RQB_PICK) * (np.nan_to_num(col(R, "e_x_l0_tgt_share")) >= RQB_SH) * (np.nan_to_num(col(R, "e_x_moved_off")) == 0) * (np.nan_to_num(col(R, "e_x_offseason")) > 0 if RQB_OFF else 1) * np.interp(raw, RQB_BAND, [0, 1, 1, 0])
    if NYG_UP:
        T_["nyg"] = NYG_UP * np.nan_to_num(col(R, "e_x_nyg")) * np.interp(raw, NYG_BAND, [0, 1, 1, 0])
    if CUFF_PREM:
        T_["cuff_prem"] = CUFF_PREM * (pos == "RB") * (np.nan_to_num(col(R, "age"), nan=99) < CUFF_PREM_AGE) * (np.nan_to_num(col(R, "e_x_comp_share")) >= CUFF_PREM_COMP) \
            * (np.nan_to_num(col(R, "e_x_cur_xfp_share")) >= CUFF_PREM_SH) * (np.nan_to_num(col(R, "e_x_gp_cur")) >= 1) * np.interp(raw, CUFF_PREM_BAND, [0, 1, 1, 0])
    if CUFF_ACT:
        ca = np.nan_to_num(col(R, "e_x_cuff_act"))
        T_["cuff_act"] = CUFF_ACT * (pos == "RB") * (ca > 0) * np.interp(ca, CUFF_FADE, [1, 0.6, 0]) * np.interp(raw, CUFF_BAND, [0, 1, 1, 0])
    if NOT_BACK:   # (#20 Godwin 2022 "off injury") in the offseason, not yet back from the injury that ended last season
        nb = (np.nan_to_num(col(R, "e_x_gp_since_inj"), nan=9) == 0) * (np.nan_to_num(col(R, "e_x_l0_games"), nan=17) <= NOT_BACK_G) * (np.nan_to_num(col(R, "e_x_l0_games"), nan=0) >= 4) \
            * (np.nan_to_num(col(R, "e_x_gp_cur")) == 0) * (np.nan_to_num(col(R, "e_x_susp_last")) == 0) \
            * ~np.isin(R.injury.fillna("").values, NOT_BACK_SKIP)    # a game-week tag (Out) is this season's injury, priced by inj_out
        T_["not_back"] = NOT_BACK * nb * np.isin(pos, ["RB", "WR", "TE", "QB"])
    if SUSP_EASE:   # (#18 Ridley 2023) games lost to last season's suspension are no injury record
        sl = np.clip(np.nan_to_num(col(R, "e_x_susp_last")) / 0.5, 0, 1) * (np.nan_to_num(col(R, "e_x_gp_cur")) < 4)
        T_["availability"] = np.where(T_["availability"] < 0, T_["availability"] * (1 - SUSP_EASE * sl), T_["availability"])
    if RUN_AVAIL:
        ra = (pos == "RB") * (np.nan_to_num(col(R, "age"), nan=99) < 27) * (np.nan_to_num(col(R, "e_x_comp_age"), nan=0) >= 28) * np.clip((np.nan_to_num(col(R, "e_x_team_run")) - 0.25) / 0.05, 0, 1)
        T_["availability"] = np.where(T_["availability"] < 0, T_["availability"] * (1 - RUN_AVAIL * ra), T_["availability"])
    if AVAIL_NOW:
        gpc, tgc = np.nan_to_num(col(R, "e_x_gp_cur")), col(R, "e_x_team_games_cur")
        now_ = (gpc >= AVAIL_NOW_G) & (gpc >= np.nan_to_num(tgc, nan=99)) & (np.nan_to_num(col(R, "e_x_ppg_cur")) >= AVAIL_NOW_PPG) & np.isin(pos, AVAIL_NOW_POS)
        T_["availability"] = np.where(T_["availability"] < 0, T_["availability"] * (1 - AVAIL_NOW * now_ * np.interp(raw, AVAIL_NOW_BAND, [0, 1, 1, 0])), T_["availability"])
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
    # ... a bit less for a player who himself joined the team that offseason, unless the rookie is a first-rounder: the
    # team brought him in for the job as well (Oliver 2026-11-09, Dobbins and RJ Harvey, 2025)
    new_ = np.fmax(np.nan_to_num(col(R, "e_x_new_team")), np.nan_to_num(col(R, "e_x_moved_off"))) * (np.nan_to_num(col(R, "e_x_draft_comp_r1")) == 0)
    T_["draft_comp"] = T_["draft_comp"] * (1 - DRAFT_COMP_NEW * new_)
    # a cheap player's team counts for more: a mediocre player on a bad team is worth little, on a good one he has a
    # path (team_q_lo, extra team-quality strength at base under $75, fading out by $150: Oliver, Tre Tucker 2025)
    # round 6 (Oliver 2026-11-22): the rookie-competition docks weigh less on a younger player (comp_young, full under
    # COMP_YOUNG_AGE[0], none from [1]): a 26-year-old in his prime is not pushed aside by a rookie the way a vet is (Garrett Wilson)
    yw_ = np.clip((COMP_YOUNG_AGE[1] - np.nan_to_num(col(R, "age"), nan=30)) / (COMP_YOUNG_AGE[1] - COMP_YOUNG_AGE[0]), 0, 1)
    yw_ = yw_ * np.isin(pos, COMP_POS) * np.interp(raw, COMP_BAND, [0, 1, 1, 0])   # narrowed to a position and a base band
    spare = 1 - p.get("comp_young", 0.0) * yw_
    # ... and (Oliver: "his previous numbers were lowered by bad QB play") the bad-team dock eases by QB_SPARE in the same reach
    T_["team_q"] = np.where(T_["team_q"] < 0, T_["team_q"] * (1 - QB_SPARE * (yw_ > 0) * np.interp(raw, COMP_BAND, [0, 1, 1, 0]) * np.isin(pos, COMP_POS)), T_["team_q"])
    T_["draft_comp"] = T_["draft_comp"] * spare; T_["r1_wr"] = T_["r1_wr"] * spare
    if COMP_NO_STACK:          # one rookie, one dock: the strongest of draft_comp, r1_wr and wr_backup (final stage), not their sum
        wb_ = p.get("wr_backup", 0.0) * (R.pos.values == "WR") * (np.nan_to_num(col(R, "exp")) >= 1) * (np.nan_to_num(col(R, "e_x_rookie_backup")) >= WR_BACKUP_MIN) \
            * np.clip(np.nan_to_num(col(R, "e_x_rookie_backup")) / 250.0, 0, 2.0) * spare
        m_ = np.minimum(np.minimum(T_["draft_comp"], T_["r1_wr"]), wb_)
        nb_ = yw_ > 0                     # only inside comp_young's reach (position and base band)
        T_["draft_comp"] = np.where(nb_, m_ - wb_, T_["draft_comp"]); T_["r1_wr"] = np.where(nb_, 0.0, T_["r1_wr"])
    T_["wr_adv"] = p.get("wr_adv", 0.0) * X["wr_adv"] * np.interp(raw, WR_ADV_BAND, [0, 1, 1, 0])
    T_["soph_fall"] = p.get("soph_fall", 0.0) * X["soph_fall"]
    T_["wr_room"] = p.get("wr_room", 0.0) * X["wr_room"]
    T_["summer_old"] = p.get("summer_old", 0.0) * X["summer_old"]
    T_["cutdown"] = p.get("cutdown", 0.0) * X["cutdown"]
    # round 6 (Oliver 2026-11-22, MHJ like BTJ: "a severe second-year slump despite getting snaps that continued into (RB/WR: a TE grows slower, Loveland)
    # the third year"): flop_r1 = a 1st-round RB/WR/TE (pick 1-32, full by pick 16) in his 2nd-3rd season (exp 1-2) who
    # plays the snaps (60%+) but scores under FLOP_PPG PPR a game: last season, and again this season (4+ games) counts twice
    pk_ = col(R, "e_x_draft_pick"); r1_ = np.where(np.isnan(pk_), 0, np.clip((33 - pk_) / 17, 0, 1))
    ex_ = np.nan_to_num(col(R, "exp")); fz = np.isin(pos, ["RB", "WR"]) * (ex_ >= 1) * (ex_ <= 2) * r1_
    f0 = (np.nan_to_num(col(R, "e_x_l0_off_pct")) >= 0.6) * np.clip((FLOP_PPG - np.nan_to_num(col(R, "e_x_ppg_l0"), nan=99)) / 4.0, 0, 1)
    fc = (np.nan_to_num(col(R, "e_x_gp_cur")) >= 4) * (np.nan_to_num(col(R, "e_x_cur_off_pct")) >= 0.6) * np.clip((FLOP_PPG - np.nan_to_num(col(R, "e_x_ppg_cur"), nan=99)) / 4.0, 0, 1)
    T_["flop_r1"] = p.get("flop_r1", 0.0) * fz * (f0 + fc)
    # round 6 (Oliver 2026-11-22, far-off #1/#4/#13/#14/#45: an RB who lost or won the job): rb_role = this season's snap
    # share (3+ games) minus last season's, 25 points = full, either way (a job lost lowers him, a job won raises him)
    sc_, s0_ = col(R, "e_x_cur_off_pct"), col(R, "e_x_l0_off_pct")
    T_["rb_role"] = p.get("rb_role", 0.0) * (pos == "RB") * (np.nan_to_num(col(R, "e_x_gp_cur")) >= ROLE_G) * ~np.isnan(sc_) * ~np.isnan(s0_) \
        * np.clip((np.nan_to_num(sc_) - np.nan_to_num(s0_)) / 0.25, ROLE_LO, 1) * np.interp(raw, ROLE_BAND, [0, 1, 1, 0])
    # (xfp_jump, the same job won read from expected points, does not stack on it: the larger of the two counts)
    if "xfp_jump" in T_: T_["xfp_jump"] = np.maximum(T_["xfp_jump"] - np.maximum(T_["rb_role"], 0), 0)
    if "cuff_act" in T_: T_["cuff_act"] = np.maximum(T_["cuff_act"] - np.maximum(T_["rb_role"], 0) - T_.get("xfp_jump", 0), 0)
    # round 6 (Oliver 2026-11-22, Chase Brown: "streaks of single-digit games and his pass-first offense"): boom_rate_lo =
    # an RB/WR/TE (8+ games in the window) with few 20+ PPR games over the last two seasons and this one (e_x_g20_2y / e_x_ng_2y;
    # BOOM_RATE[0] = none, [1] = full) at a value of BOOM_V+ (fading in), the league's starters win weeks with them;
    # rb_pass_team = an RB on a pass-first offense (his team's share of expected fantasy points from runs, e_x_team_run,
    # RUN_LO[1] = none, RUN_LO[0] = full)
    ng_ = np.nan_to_num(col(R, "e_x_ng_2y")); br_ = np.nan_to_num(col(R, "e_x_g20_2y")) / np.maximum(ng_, 1)
    T_["boom_rate_lo"] = p.get("boom_rate_lo", 0.0) * np.isin(pos, BOOM_POS) * (ng_ >= 8) * np.clip((BOOM_RATE[0] - br_) / (BOOM_RATE[0] - BOOM_RATE[1]), 0, 1) * np.interp(raw, BOOM_V, [0, 1, 1, 0])
    tr_ = col(R, "e_x_team_run")
    # (far-off #7, Dobbins 2023 "run-first offense, no competition"): an RB on a run-first offense (e_x_team_run 25%
    # none, 30% full) whose other RBs are older (28+): the carries are his (RUN_UP, raise only)
    T_["rb_run_team"] = RUN_UP * (pos == "RB") * (np.nan_to_num(col(R, "age"), nan=99) < 27) * np.interp(raw, RUN_UP_BAND, [0, 1, 1, 0]) * (np.nan_to_num(col(R, "e_x_comp_age"), nan=0) >= 28) * np.clip((np.nan_to_num(col(R, "e_x_team_run")) - 0.25) / 0.05, 0, 1)
    T_["rb_pass_team"] = p.get("rb_pass_team", 0.0) * (pos == "RB") * ~np.isnan(tr_) * ((br_ < RUN_BOOM) | (ng_ < 8)) * np.interp(raw, RUN_BAND, [0, 1, 1, 0]) * np.clip((RUN_LO[1] - np.nan_to_num(tr_, nan=1)) / (RUN_LO[1] - RUN_LO[0]), 0, 1)
    # round 6 (Oliver 2026-11-22: "contract length might be a good one"; Kirk "aging on an expiring contract", Singletary
    # "expiring contract -> his boom raised FA speculation"): e_x_contract_left = seasons left on his latest NFL deal after
    # this one (0 = the final year; Over The Cap). An RB/WR/TE CONTRACT_AGE+ in his final year may be cut or moved
    # (contract_old); a younger one in his final year who just spiked is a free agent other teams will pay (contract_boom)
    cl_ = col(R, "e_x_contract_left"); last_ = (~np.isnan(cl_)) & (np.nan_to_num(cl_, nan=9) == 0) & np.isin(pos, ["RB", "WR", "TE"])
    age_ = np.nan_to_num(col(R, "age"), nan=25.0)
    T_["contract_old"] = p.get("contract_old", 0.0) * last_ * np.clip((age_ - CONTRACT_AGE + 1) / 2.0, 0, 1)
    T_["contract_boom"] = p.get("contract_boom", 0.0) * last_ * (age_ < CONTRACT_AGE) * np.clip(X["spike"], 0, 1.5)
    # Oliver (round 6): a final contract year cuts both ways with his situation: in a bad offense he may leave for a
    # better one (raised), in a good one he may leave it (lowered). Situation = his team's implied points (this season
    # from 4 games, else last), CONTRACT_SIT_MID +-4 for full; CONTRACT_SIT a log strength (0 = off)
    if CONTRACT_SIT:
        ti = np.where(np.nan_to_num(col(R, "e_x_team_games_cur")) >= 4, col(R, "e_x_team_implied_cur"), col(R, "e_x_team_implied_l0"))
        sit = np.clip((CONTRACT_SIT_MID - np.nan_to_num(ti, nan=CONTRACT_SIT_MID)) / 4.0, -1, 1)
        T_["contract_sit"] = CONTRACT_SIT * last_ * (age_ < CONTRACT_SIT_AGE) * sit * np.interp(raw, CONTRACT_SIT_BAND, [0, 1, 1, 0])
    # round 6 (Oliver 2026-11-22: "a knock against players in this range with no more than X games over 20 and zero over
    # 30"; Fannin "a low ceiling, his boom weeks are only so big"): an RB/WR/TE past his rookie year whose best game in
    # the last two complete seasons and this one (e_x_max_2y) is under CEIL_PTS: the league pays for the weeks that win
    # matchups. Full CEIL_SPAN under it; only for base values in CEIL_BAND (fading in / full / fading out)
    mx_ = col(R, "e_x_max_2y")
    ceil_ = np.isin(pos, CEIL_POS) * (np.nan_to_num(col(R, "exp")) >= CEIL_EXP) * ~np.isnan(mx_) * (~np.isnan(col(R, "e_x_ppg_l0")) | (not CEIL_FULL_L0)) * np.clip((CEIL_PTS - np.nan_to_num(mx_, nan=99)) / CEIL_SPAN, 0, 1)
    T_["ceiling_lo"] = p.get("ceiling_lo", 0.0) * ceil_ * ~((pos == "WR") & (np.nan_to_num(col(R, "exp")) > CEIL_VET_EXP)) * np.interp(raw, CEIL_BAND, [0, 1, 1, 0])
    T_["team_q_lo"] = p.get("team_q_lo", 0.0) * np.minimum(X["team_q"], 0) * np.interp(raw, [75, 150], [1, 0])
    T_["cheap_deal"] = p.get("cheap_deal", 0.0) * X["cheap_deal"] * np.interp(raw, [300, 600], [0, 1])
    T_["boom_week"] = p.get("boom_week", 0.0) * X["boom_week"] * np.clip((p.get("boom_hi", 600.0) - v) / (0.6 * p.get("boom_hi", 600.0)), 0, 1)
    T_["spike"] = p.get("spike", 0) * X["spike"] * unpriced; T_["team_up"] = p.get("team_up", 0) * X["team_up"] * unpriced
    # round 6 (far-off #1, Rhamondre 2023 "lost his starting role"): an RB/WR/TE whose PPR a game this season (4+ games)
    # is well under last season's: the breakout bonus fades (SPIKE_DROP = how much; under 80% of last season starts, 60% = full)
    pc6, p06 = col(R, "e_x_ppg_cur"), col(R, "e_x_ppg_l0")
    fall6 = (np.nan_to_num(col(R, "e_x_gp_cur")) >= 4) * ~np.isnan(pc6) * ~np.isnan(p06) * np.clip((0.8 - np.nan_to_num(pc6) / np.maximum(np.nan_to_num(p06), 1)) / 0.2, 0, 1)
    # (far-off #3, Aiyuk 2020: a rookie's 3 good games behind young established targets): a rookie's breakout bonus fades in with his games (SPIKE_ROOKIE_G = full)
    T_["spike"] = T_["spike"] * np.where((np.nan_to_num(col(R, "exp")) == 0) & (np.nan_to_num(col(R, "e_x_comp_share")) >= SPIKE_ROOKIE_COMP) & (np.nan_to_num(col(R, "e_x_comp_age"), nan=99) < 28), np.clip(np.nan_to_num(col(R, "e_x_gp_cur")) / SPIKE_ROOKIE_G, 0, 1), 1.0)
    T_["spike"] = np.where((np.nan_to_num(col(R, "exp")) == 0) & (np.nan_to_num(col(R, "e_x_gp_cur")) < SPIKE_ROOKIE_CAP_G), np.minimum(T_["spike"], np.log(SPIKE_ROOKIE_CAP)), T_["spike"])
    # (vac_up does not stack on a breakout: the larger counts, VAC_STACK = 0; 1 = both count)
    if "vac_up" in T_ and VAC_STACK < 1: T_["vac_up"] = np.maximum(T_["vac_up"] - (1 - VAC_STACK) * np.maximum(T_["spike"], 0), 0)
    if SPIKE_DAY3:   # (#24 / #44 Renfrow "way down") a day-3 / undrafted WR's breakout season, priced in the offseason
        d3 = (pos == "WR") * (np.nan_to_num(col(R, "e_x_draft_pick"), nan=300) > SPIKE_DAY3_PICK) * (np.nan_to_num(col(R, "exp")) >= 2) * (np.nan_to_num(col(R, "e_x_gp_cur")) < 3)
        T_["spike"] = np.where(T_["spike"] > 0, T_["spike"] * (1 - SPIKE_DAY3 * d3), T_["spike"])
    T_["spike"] = T_["spike"] * (1 - SPIKE_DROP * fall6 * np.isin(pos, ["RB", "WR", "TE"]) * (np.nan_to_num(col(R, "exp")) >= SPIKE_DROP_EXP) * np.interp(raw, SPIKE_DROP_BAND, [0, 1, 1, 0]))
    # (far-off #1, Mattison 2023 took the job): an RB's bad yards per carry counts less once he has the snaps this
    # season (3+ games, 25+ points over last season = full by YPC_ROLE)
    gain6 = (np.nan_to_num(col(R, "e_x_gp_cur")) >= 3) * np.clip((np.nan_to_num(col(R, "e_x_cur_off_pct")) - np.nan_to_num(col(R, "e_x_l0_off_pct"), nan=1)) / 0.25, 0, 1)
    T_["ypc_bad"] = T_["ypc_bad"] * (1 - YPC_ROLE * gain6)
    # (far-off #6, Mims 2020): an Out tag on a rookie who has not played an NFL game yet (a camp injury) costs him
    # less: his value is his draft slot, not this week (OUT_ROOKIE spared)
    T_["exit_early"] = EXIT * (np.nan_to_num(col(R, "e_x_last_opp_ratio"), nan=9) < EXIT_R) * (R.injury.fillna("").values == "") * np.isin(pos, ["RB", "WR", "TE"])
    # an Out tag on a player scoring like a star this season (OUT_STAR_PPG+ PPR/g over 5+ games) is a week-to-week
    # absence the league does not halve him for (K. Walker 2026-11-22, Out with 24.6 PPR/g): the dock fades by OUT_STAR
    T_["inj_out"] = T_["inj_out"] * (1 - OUT_STAR * np.isin(pos, OUT_STAR_POS) * (np.nan_to_num(col(R, "e_x_gp_cur")) >= 5) * (np.nan_to_num(col(R, "e_x_ppg_cur")) >= OUT_STAR_PPG))
    T_["inj_out"] = T_["inj_out"] * (1 - OUT_ROOKIE * (np.nan_to_num(col(R, "exp")) == 0) * (np.nan_to_num(col(R, "e_x_gp_cur")) == 0))
    # (far-off #5, Brooks Dec 2024): young upside needs a role once the season is well along: a player with 2+ games
    # played whose team has played 10+ and who is on under 30% of the snaps (15% = none left) keeps UPSIDE_ROLE less of it
    nr6 = (np.nan_to_num(col(R, "e_x_gp_cur")) >= 2) * (np.nan_to_num(col(R, "e_x_team_games_cur")) >= 10) * np.clip((0.3 - np.nan_to_num(col(R, "e_x_cur_off_pct"), nan=1)) / 0.15, 0, 1)
    T_["young_upside"] = T_["young_upside"] * (1 - UPSIDE_ROLE * nr6 * np.interp(raw, UPSIDE_BAND, [0, 1, 1, 0]))
    # (far-off #4, Rhamondre 2025 "a receiving back, PPR boost"): an RB who earns targets (this season's target share, else
    # last season's; 8% none, 14% full) is paid for catches, so bad yards per carry counts less (YPC_REC)
    ts6 = np.where(np.isnan(col(R, "e_x_cur_tgt_share")), col(R, "e_x_l0_tgt_share"), col(R, "e_x_cur_tgt_share"))
    mvd_ = rb_moved(R)
    for k in ("ypc_bad", "availability"):
        if k in MOVE_DOCKS: T_[k] = np.where(T_[k] < 0, T_[k] * (1 - mvd_), T_[k])
    T_["ypc_bad"] = T_["ypc_bad"] * (1 - YPC_REC * np.clip((np.nan_to_num(ts6) - 0.08) / 0.06, 0, 1))
    T_["position curve"] = X["te"] * curve(p["te_lo"], p["te_hi"]) + np.select([pos == "QB", pos == "RB", pos == "WR"], [top_curve(p["qb_lo"], p["qb_hi"]), top_curve(p["rb_lo"], p["rb_hi"]), top_curve(p["wr_lo"], p["wr_hi"])], 0.0)
    # TE line in two tiers: a light drop below te_thr (capped, te_soft) and a harsh one below te_thr2 (te_line); a proven
    # TE's line is eased by te_relief
    tx_ = np.nan_to_num(X["te_x"], nan=99.0); pv = p.get("te_pv16", 0.0); relief = 1 - p.get("te_relief", 0.0) * ((1 - pv) * X["te_proven"] + pv * X["te_proven16"])
    relief = relief * (1 - p.get("te_top3", 0.0) * X["te_top3"])         # a recent top-3 TE season eases it too (Schultz 2022)
    T_["te_line"] = relief * (p.get("te_soft", 0.0) * np.clip((p.get("te_thr", 11.0) - tx_) / 2.5, 0, 1)
                              + p.get("te_line", 0.0) * np.clip((p.get("te_thr2", 9.0) - tx_) / 2.5, 0, 1.5))
    T_["no NFL team"] = -UK * X["un"] * (1 - X["rostered"])     # on a roster last season or this one (IR, suspended): he has a team
    # an older player's regression fades his record boosts (elite streak, NFL awards, top-12 track)
    # ... and near or past the age wall, a declining player's record boosts fade (rec_age) and his value drops (old_cliff),
    # scaled by the drop in his expected PPG: an old star in decline is priced on his next season, not on his record (the
    # vet discount above spares expensive players). An old player still producing (no drop) keeps his value
    for k_ in ("elite_streak", "aw_nfl", "track"): T_[k_] = T_[k_] * (1 - p.get("regress", 0.0) * X["regress"]) * (1 - p.get("rec_age", 0.0) * X["rec_age"])
    if AW_ELITE:   # (Oliver 2026-11-23, Bijan Robinson > Jahmyr Gibbs) an NFL award confirms talent that a top stats base
        # already prices: the award boost fades out as the base rises through AW_ELITE_BAND
        T_["aw_nfl"] = T_["aw_nfl"] * (1 - AW_ELITE * np.interp(raw, AW_ELITE_BAND, [0, 1]) * np.isin(pos, AW_ELITE_POS))
    # replacement level: a veteran (4th season on) ranked near or below the line is a waiver-wire body worth ~0;
    # players in their first three seasons keep their upside value
    if "rank_raw" in R:
        n_ = col(R, "line_n"); vetr = (np.nan_to_num(col(R, "exp")) >= 3) * np.where(X["wr_no_role"] > 0, 1.0, np.clip((np.nan_to_num(col(R, "age"), nan=28) - 25.0) / 3.0, 0, 1))   # 4th season on, fading in from 25 to 28 (a WR who never had a starter's role: full)
        T_["replacement line"] = -p.get("bubble", 0.0) * np.nan_to_num(vetr * np.clip((col(R, "rank_raw") - p.get("line_frac", 0.8) * n_) / (0.25 * n_), 0, 1.5))
    if "replacement line" in T_: T_["replacement line"] = T_["replacement line"] * (1 - X["qb_paid"])
    # round 6 (far-off #2, Ridley 2025 "clear #1 target"): his team's target leader last season (e_x_tgt_lead_w = 1, a
    # 20%+ share) is no waiver body: the replacement line spares him by LEAD_SPARE
    lead6 = (pos == "WR") * (np.nan_to_num(col(R, "e_x_tgt_lead_w")) >= 1) * (np.nan_to_num(col(R, "e_x_l0_tgt_share")) >= LEAD_SHARE) * (np.nan_to_num(col(R, "e_x_gp_cur")) < LEAD_G)
    if "replacement line" in T_: T_["replacement line"] = T_["replacement line"] * (1 - LEAD_SPARE * lead6)
    # (#16 Samuel 2024 "top option in BUF") an offseason arrival into a big vacated role is no waiver body either
    if VAC_SPARE and "replacement line" in T_:
        vs = np.isin(pos, ["WR", "TE"]) * np.clip((np.nan_to_num(col(R, "e_x_vacated")) - 0.1) / 0.1, 0, 1)
        T_["replacement line"] = T_["replacement line"] * (1 - VAC_SPARE * vs)
    # (far-off #2, White 2025 "lost his job to Bucky"): an RB 25+ whose team's other RBs include a young one (their
    # average age under 24) holding 45-60% of the RB share: the job is going to him (RB_YOUNG_COMP, lower only)
    T_["rb_young_comp"] = RB_YOUNG_COMP * (pos == "RB") * (np.nan_to_num(col(R, "age"), nan=0) >= 25) * (np.nan_to_num(col(R, "e_x_comp_age"), nan=99) < 24) \
        * np.interp(np.nan_to_num(col(R, "e_x_comp_share")), (0.3, 0.45, 0.6, 0.72), (0, 1, 1, 0)) * (np.nan_to_num(col(R, "e_x_gp_cur")) < RB_YOUNG_G)   # a share past 72%: he is the star's handcuff (a cuff premium), not losing a committee
    # a fresh start (followed his coach to a new team): the role-based docks (TE line, replacement line) are lifted
    # and the move is priced by its own strength (fresh_start, held on Oliver's call). Only for a player who would
    # otherwise be worth under $200 (Oliver): a valued player's price already carries his role
    fr = X["fresh"] * (v * np.exp(sum(T_.values())) < FRESH_MAX)
    for k_ in ("te_line", "replacement line"):
        if k_ in T_: T_[k_] = T_[k_] * (1 - fr)
    T_["fresh_start"] = p.get("fresh_start", 0.0) * fr
    # round 6 (far-off trades): the docks mostly measure one weakness from several angles (a so-so player is slow, often
    # hurt, below the replacement line, with duds): stacked past DOCK_CAP (log; the seasonal summer shift aside) they
    # double-count it, so the negative terms are scaled back together to the cap (None = off)
    # round 6 (depth charts, weekly to 2024, daily from Aug 2025): what the team says the role is today
    dcr_ = col(R, "e_x_dc_rank"); dcp_ = col(R, "e_x_dc_prev"); hl_ = R.injury.fillna("").values == ""
    T_["paid_up"] = PAID_UP * (pos != "QB") * np.interp(np.nan_to_num(col(R, "e_x_vet_deal_cap")), PAID_CAP, [0, 1]) \
        * (1 - np.clip(np.nan_to_num(col(R, "e_x_gp_cur")) / 4.0, 0, 1)) * np.interp(raw, PAID_BAND, [0, 1, 1, 0])
    T_["qb_bench"] = QB_BENCH * (pos == "QB") * (dcr_ >= 2) * (dcp_ == 1) * hl_
    T_["dc2_rb"] = DC2_RB * (pos == "RB") * (dcr_ == 2) * np.interp(raw, DC2_BAND, [0, 1, 1, 0])
    T_["dc1_up"] = DC1_UP * np.isin(pos, DC1_POS) * (dcr_ == 1) * hl_ * np.interp(raw, DC1_BAND, [0, 1, 1, 0])
    if COACH_EASE:   # (Likely 2026, Harbaugh to the Giants) a new head coach: last season's bad-team docks say less before he plays
        nc_ = np.nan_to_num(col(R, "e_x_new_coach")) * (np.nan_to_num(col(R, "e_x_gp_cur")) == 0)
        for k in ("team_q", "team_q_lo"):
            if k in T_: T_[k] = np.where(T_[k] < 0, T_[k] * (1 - COACH_EASE * nc_), T_[k])
    if MOVE_EASE:   # the rest of MOVE_DOCKS (role docks from his old team), eased with the same weight
        for k in MOVE_DOCKS:
            if k in T_ and k not in ("ypc_bad", "availability", "rb_duds", "rb_inj"): T_[k] = np.where(T_[k] < 0, T_[k] * (1 - mvd_), T_[k])
    if MOVE_PROVEN:   # (Oliver, Pacheco 2026) the vacated-role move for a back young enough who has had a top-15 PPR RB season
        T_["move_proven"] = MOVE_PROVEN * (mvd_ > 0) * (np.nan_to_num(col(R, "age"), nan=99) < MOVE_PROVEN_AGE) \
            * (np.nan_to_num(col(R, "e_x_best_rank_4y"), nan=99) <= MOVE_PROVEN_RANK)
    if REPL_TOP2 and "replacement line" in T_:   # (Oliver 2026-11-23) a former top-2 finisher at his position (NFL, last 4 seasons) is no replacement body
        t2 = np.nan_to_num(col(R, "e_x_best_rank_4y"), nan=99) <= REPL_TOP_RANK
        T_["replacement line"] = np.where(t2, T_["replacement line"] * (1 - REPL_TOP2), T_["replacement line"])
    if SUMMER_MOVE and "summer" in T_:   # (Oliver, Curtis Samuel 2024) a player who changed teams this offseason: the new
        # team has just paid for him, so the summer cut on him is smaller
        mo_ = np.nan_to_num(col(R, "e_x_moved_off")) > 0
        T_["summer"] = np.where(mo_, T_["summer"] * (1 - SUMMER_MOVE), T_["summer"])
    if SUMMER_LOW and "summer" in T_:
        pre_ = v * np.exp(sum(t for k, t in T_.items() if k != "summer"))
        T_["summer"] = T_["summer"] * np.interp(pre_, SUMMER_LOW_V, (1 - SUMMER_LOW, 1.0))
    _attach(R, T_, pos, raw)
    if DOCK_CAP > -90:
        ks = [k for k in T_ if k not in DOCK_KEEP]
        neg = sum(np.minimum(T_[k], 0) for k in ks)
        sc = np.where(neg < DOCK_CAP, DOCK_CAP / np.minimum(neg, -1e-9), 1.0) * np.isin(pos, DOCK_POS) + (1 - np.isin(pos, DOCK_POS))
        for k in ks: T_[k] = np.where(T_[k] < 0, T_[k] * sc, T_[k])
    v = v * np.exp(sum(T_.values()))
    # usage anchor: pull part of the way toward the value the current role implies (history-built values drift to what a player does now)
    w = p.get("anchor_w", 0.0) + p.get("anchor_old", 0.0) * X["near_wall"]       # older players: priced on what they do now
    ndz = p.get("ir_no_double", 0.0) * X["ir"]; z = np.where(np.isnan(X["xfp_zh"]), X["xfp_z"], (1 - ndz) * np.nan_to_num(X["xfp_z"]) + ndz * X["xfp_zh"])
    z = np.where(np.isnan(X["xfp_z"]) & (ndz == 0), np.nan, z)
    u = 50.0 * np.exp(p.get("anchor_slope", 0.5) * np.clip(np.nan_to_num(z, nan=0.0), -3, 12))
    v2 = np.where(np.isnan(z) | (w <= 0), v, np.exp((1 - w) * np.log(np.maximum(v, 1)) + w * np.log(u)))
    v3 = np.where(v2 > 2000, 2000 * (np.maximum(v2, 2000) / 2000) ** p["top_g"], v2)
    TF = final_terms(R, v3, p, X)
    TF["wr_backup"] = TF["wr_backup"] * (1 - p.get("comp_young", 0.0) * yw_)
    # round 6 (Oliver 2026-11-22, Kenneth Walker: "huge success in a new place this year"): a player on a new NFL team
    # this season (e_x_new_team) scoring NEW_HOME_PPG+ PPR a game more than last season over NEW_HOME_G+ games. Applied
    # after the top compression: it is a star-level jump the top end otherwise flattens (x2.4 in rules = x1.15 at $2,300)
    # round 6 (Oliver 2026-11-22, Puka > ARSB: "his competition is a very-aging Tae Adams, not a young stud Jamo"): the WR
    # target-room rule (wr_room) for a star WR, after the top compression (it flattens a rules-stage boost there)
    TF["wr_room_top"] = p.get("wr_room_top", 0.0) * X["wr_room"] * np.interp(v3, (2000.0, 2500.0), (0.0, 1.0))
    # round 6 (Oliver 2026-11-22, Chase > Puka: "proven success even with a QB change when Burrow went down"): a star
    # receiver who kept scoring in QB_PROOF_N+ games his team's usual QB did not start (4 seasons + this one), as a share
    # of his PPR a game with him (0.7 = none, 0.9 = full); after the top compression, $2,000-2,500 fade-in
    rq_ = np.nan_to_num(col(R, "e_x_ppg_alt_qb")) / np.maximum(np.nan_to_num(col(R, "e_x_ppg_main_qb")), 1)
    TF["qb_proof"] = p.get("qb_proof", 0.0) * np.isin(R.pos.values, ["WR", "TE"]) * (np.nan_to_num(col(R, "e_x_n_alt_qb")) >= QB_PROOF_N) \
        * np.clip((rq_ - 0.7) / 0.2, 0, 1) * np.interp(v3, (2000.0, 2500.0), (0.0, 1.0))
    # round 6 (Oliver 2026-11-22, Jefferson 2022 "at his peak, >= $3,500"): a WR under PEAK_AGE with two or more 16+ PPR
    # seasons in the last four, after the top compression (it flattens his rules value), $2,500-2,900 fade-in
    TF["young_peak"] = p.get("young_peak", 0.0) * (R.pos.values == "WR") * (np.nan_to_num(col(R, "age"), nan=30) < PEAK_AGE) \
        * (np.nan_to_num(col(R, "e_x_s16_4y")) >= PEAK_SEASONS) * np.interp(v3, PEAK_BAND, (0.0, 1.0))
    dppg = np.nan_to_num(col(R, "e_x_ppg_cur")) - np.nan_to_num(col(R, "e_x_ppg_l0"), nan=99)
    TF["new_home"] = p.get("new_home", 0.0) * np.nan_to_num(col(R, "e_x_new_team")) * (np.nan_to_num(col(R, "e_x_gp_cur")) >= NEW_HOME_G) \
        * np.clip((dppg - NEW_HOME_PPG) / 6.0, 0, 1) * np.interp(v3, NEW_HOME_V, [0, 1])
    # far-off #10 (CEH 2022-10-08, "TD spike, no huge weeks"): an RB scoring well over his expected points (TDs) on a
    # part-time role (under TD_SPIKE_SNAP of the snaps) early in a season (3-8 games) is lowered after the top compression
    # (TD_SPIKE, a log term; full at +4 PPR/g over expected, none at +2), fading in over TD_SPIKE_V
    oe_ = np.nan_to_num(col(R, "e_x_ppg_cur")) - np.nan_to_num(col(R, "e_x_cur_xfp_pg"), nan=99)
    gpf = np.nan_to_num(col(R, "e_x_gp_cur"))
    TF["td_spike"] = TD_SPIKE * (R.pos.values == "RB") * (gpf >= 3) * (gpf <= 8) * (np.nan_to_num(col(R, "e_x_cur_off_pct"), nan=1) < TD_SPIKE_SNAP) \
        * np.clip((oe_ - 2.0) / 2.0, 0, 1) * np.interp(v3, TD_SPIKE_V, [0, 1])
    out = v3 * np.exp(sum(TF.values()))
    # round 6 (Oliver 2026-11-22, Penix: "inflate the base value by a 3rd for every QB under contract for next year, with
    # a full hold on the starting job when healthy, averaging 10+ a game as the starter"): a superflex starter with a
    # job next year is a roster asset whatever his injuries; adds QB_START_ADD dollars (about a 3rd) to his value
    qg_ = np.nan_to_num(col(R, "e_x_gp_cur")) >= 3
    snp_ = np.where(qg_, np.nan_to_num(col(R, "e_x_cur_off_pct")), np.nan_to_num(col(R, "e_x_l0_off_pct")))
    qpp_ = np.where(qg_, np.nan_to_num(col(R, "e_x_ppg_cur")), np.nan_to_num(col(R, "e_x_ppg_l0")))
    qs_ = (R.pos.values == "QB") * (np.nan_to_num(col(R, "e_x_contract_left"), nan=-1) >= 1) * (snp_ >= QB_START_SNAP) * (qpp_ >= QB_START_PPG)
    out = np.where(qs_ > 0, np.maximum(out, QB_START_FLOOR), out) if QB_START_FLOOR else out + QB_START_ADD * qs_   # floor variant: at least a 3rd
    # round 6 (far-off #6, Malcolm Brown 2020 "won the RB job: worth 75+"): an RB who has just taken the job (this season
    # 55%+ of the snaps, 25+ points over last season's) is worth at least RB_JOB_FLOOR, a multiplier cannot lift a $2 body
    sj_ = np.nan_to_num(col(R, "e_x_cur_off_pct")); s0j = np.nan_to_num(col(R, "e_x_l0_off_pct"))
    job_ = (R.pos.values == "RB") * (np.nan_to_num(col(R, "e_x_gp_cur")) >= 1) * (sj_ >= 0.55) * (sj_ - s0j >= 0.25)
    out = np.where(job_ > 0, np.maximum(out, RB_JOB_FLOOR), out)
    # round 6 (Oliver: far-off trades must go under 100%): a proven producer is never a free body in a trade. The
    # league never trades a player who scored PROVEN_PPG+ PPR/g over a real sample (this season from 4 games, else
    # last season from 8) for nothing: he is worth at least PROVEN_FLOOR (a late pick), under age PROVEN_AGE
    pg_ = np.nan_to_num(col(R, "e_x_gp_cur")) >= 4
    ppv = np.where(pg_, np.nan_to_num(col(R, "e_x_ppg_cur")), np.where(np.nan_to_num(col(R, "e_x_l0_games")) >= 8, np.nan_to_num(col(R, "e_x_ppg_l0")), 0))
    pr_ = np.isin(R.pos.values, ["RB", "WR", "TE", "QB"]) * (ppv >= PROVEN_PPG) * (np.nan_to_num(col(R, "age"), nan=99) < PROVEN_AGE)
    if PROVEN_FLOOR: out = np.where(pr_ > 0, np.maximum(out, PROVEN_FLOOR * np.clip((ppv - PROVEN_PPG) / 2.0 + 0.5, 0.5, 1.0)), out)
    # round 6 (depth charts): the team's own chart sets a floor under two roles a multiplier can take to nothing
    dcr2 = col(R, "e_x_dc_rank"); tgc = np.nan_to_num(col(R, "e_x_team_games_cur"))
    imp_ = np.where(tgc >= 3, np.nan_to_num(col(R, "e_x_team_implied_cur")), np.nan_to_num(col(R, "e_x_team_implied_l0")))
    if DC2_FLOOR: out = np.where((R.pos.values == "RB") * (dcr2 == 2) * (imp_ >= DC2_IMPL) > 0, np.maximum(out, DC2_FLOOR), out)
    if DC1_FLOOR:
        c1 = np.isin(R.pos.values, ["RB", "WR", "TE"]) * (dcr2 == 1) * (tgc >= DC1_G) * (np.nan_to_num(col(R, "e_x_team_win_cur")) >= DC1_WIN) * (R.injury.fillna("").values == "")
        out = np.where(c1 > 0, np.maximum(out, DC1_FLOOR), out)
    if VET_RB_FLOOR:
        vr_ = (R.pos.values == "RB") * (np.nan_to_num(col(R, "age")) >= VET_RB_AGE) * (np.nan_to_num(col(R, "e_x_gp_cur")) >= VET_RB_G) \
            * (np.nan_to_num(col(R, "e_x_cur_off_pct")) >= VET_RB_SNAP) * (np.nan_to_num(col(R, "e_x_ppg_cur")) >= VET_RB_PPG) \
            * ~np.isin(R.injury.fillna("").values, ["IR", "PUP"])
        vf_ = np.minimum(VET_RB_FLOOR + VET_RB_STEP * (np.nan_to_num(col(R, "e_x_ppg_cur")) - VET_RB_PPG), VET_RB_CAP)
        out = np.where(vr_ > 0, np.maximum(out, vf_), out)
    if TGT_FLOOR:
        tr_ = (R.pos.values == "WR") * (np.nan_to_num(col(R, "age"), nan=99) < TGT_ROLE_AGE) * (np.nan_to_num(col(R, "e_x_gp_cur")) >= TGT_ROLE_G) \
            * (np.nan_to_num(col(R, "e_x_cur_xfp_pg")) >= TGT_ROLE_XFP) * (np.nan_to_num(col(R, "e_x_cur_tgt_share")) >= TGT_ROLE_SH) \
            * (np.nan_to_num(col(R, "e_x_cur_off_pct")) >= TGT_ROLE_SNAP) * (R.injury.fillna("").values == "") \
            * (np.nan_to_num(col(R, "e_x_team_games_cur")) - np.nan_to_num(col(R, "e_x_gp_cur")) >= TGT_ROLE_MISS)
        out = np.where(tr_ > 0, np.maximum(out, TGT_FLOOR), out)
    if LOW_ADD:
        lp_ = np.where(pg_, np.nan_to_num(col(R, "e_x_ppg_cur")), np.nan_to_num(col(R, "e_x_ppg_l0")))
        out = out + LOW_ADD * np.exp(-out / LOW_S) * np.isin(R.pos.values, ["RB", "WR", "TE", "QB"]) * (lp_ >= LOW_PPG)
    # (Oliver 2026-11-23: "increase WR fade over 3600 even more", Jaxon Smith-Njigba about $3,750 on Oct 24) a WR above
    # $3,600 keeps only WR_TOP of the excess: an elite WR stands less far above the next tier than an elite RB or QB
    if WR_TOP < 1: out = np.where((R.pos.values == "WR") & (out > WR_TOP_AT), WR_TOP_AT + (out - WR_TOP_AT) * WR_TOP, out)
    if explain:
        return out, dict(T_, **TF), dict(base=raw, curve=v0, vet=v1, rules=v, anchor=v2, top=v3, final=out)
    return out

# ------------------------------------------------------------------ inputs and evidence
REG_KEYS = ["young_peak", "qb_proof", "wr_room_top", "flop_r1", "rb_role", "boom_rate_lo", "rb_pass_team", "contract_old", "contract_boom", "ceiling_lo", "new_home", "comp_young", "wr_adv", "soph_fall", "wr_room", "summer_old", "cutdown", "rb_hold", "rb_old_hi", "tgt_lead", "young_boom", "rb_touch", "te_slide", "qb_tough", "qb_ypg", "vet_floor", "rb_duds", "wr_band", "qb_band", "rb_band", "rb_inj", "spike_vet_rb", "qb_inj", "wr_backup", "wr_clean_old", "r1_wr", "rookie_r1", "te_top3", "young_elite", "young_upside", "wr_pair", "overtaken", "qb_paid", "team_q_lo", "te_one_off", "undrafted", "cheap_deal", "draft_comp", "rookie_backup", "fresh_start", "boom_week", "qb_starter", "qb_pedigree", "ir_no_double", "qb_opening", "young_starter", "carry", "one_game", "boom_bust", "td_dep", "off_field", "summer", "te_line", "te_soft", "te_relief", "old_cliff", "rec_age", "avail_up", "share_age", "anchor_old", "rookie_day3", "vet_move", "ypc_bad", "regress", "duds", "peak_share", "slump", "journeyman", "bust", "rb_multi", "wr_talent", "pick_boom", "rb_age",
            "rookie_capital", "alpha", "availability", "efficiency", "opening", "team_q", "new_team_burst", "share_talent", "recurring", "steady", "pedigree",
            "elite_streak", "track", "qb_quality", "spike", "team_up", "severe", "qb_lo", "qb_hi", "rb_lo", "rb_hi", "wr_lo", "wr_hi", "usage", "youth_usage",
            "youth_role", "te_lo", "te_hi", "inj_ir", "inj_out", "prone", "two_way", "aw_college", "aw_nfl"]
W_TRADES, W_CUTS = 3.0, 3.0      # trade/cut history counts more than one person's calls


def load_inputs(data=DATA):
    R = pd.read_csv(Path(data) / "inputs.csv", dtype={"sid": str, "injury": str, "wr_mate": str}, keep_default_na=False, na_values=[""])
    R["injury"] = R.injury.fillna("")
    # round 6 (Samuel 2024 read Washington's 4-13): last season's team quality is the team he is on now, not the one
    # he played for (a player who moved in the offseason is judged by his new team; once he has played this season the
    # team he played for stands, as before)
    if TEAM_NOW:
        for a, b in (("e_x_team_win_l0", "e_x_tnow_win_l0"), ("e_x_team_implied_l0", "e_x_tnow_implied_l0")):
            if a in R and b in R: R[a] = R[b].where(R[b].notna() & (R[a].notna() | TEAM_NOW_ROOKIE) & ~(R.get("e_x_gp_cur", pd.Series(0, index=R.index)).fillna(0) > 0), R[a])   # a rookie (no team last season) keeps none unless TEAM_NOW_ROOKIE
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


def far_ok_mask(ev, path=None):
    """per fitted trade: how far off (ratio - 1) it was when Oliver judged it fine although far off, NaN if he has not (data/faab_value/far_off_ok.csv: date + the
    Sleeper ids of every player in it); the far-off term leaves those out"""
    path = Path(path or DATA / "far_off_ok.csv")
    if not path.exists(): return np.zeros(len(ev.trades), bool)
    ok = {(r.date, r.sids): float(r.was_off) for r in pd.read_csv(path, dtype=str).itertuples()}
    sid = ev.E.sid.astype(str).values
    return np.array([ok.get((str(d)[:10], ";".join(sorted(sid[j] for s_ in sides for j in s_[1]))), np.nan) for d, sides in ev.trades])


def far_err(V, trades, at=FAR_AT):
    """far-off trades (Oliver, round 6: every trade he has not OK'd under 100% off): the mean, over trades, of how far
    past `at` (a ratio of the sides, +25 each) a trade's |log ratio| goes; 0 for a trade within it"""
    r = np.array([np.log((a[0] + V[a[1]].sum() + 25) / (b[0] + V[b[1]].sum() + 25)) for _, (a, b) in trades])
    return float(np.mean(np.maximum(np.abs(r) - np.log(at), 0)))


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
    ok_ = far_ok_mask(ev)
    far_at = np.where(np.isnan(ok_), FAR_AT, 1 + np.nan_to_num(ok_) + FAR_OK_RISE)   # an OK'd trade: only past +50 points

    def obj(p, detail=False):
        ya = p.get("youth_age", 26.0)
        if ya not in cache:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                cache[ya] = characteristics(ev.R, ya)
        V = ev.values(p, cache[ya])
        vb = {gd: pd.Series(V[i], index=ev.Ts[gd].name.values) for gd, i in ev.pTs.items()}
        c, t = LC.score({d: vb[gd] for d, gd in ev.call_boards.items()}, ref, qbs, exp=exp_)
        rc = [(n, min(x, LC.CALL_CAP)) for n, x in LC.row_calls(ev.R, V)]; c += sum(x for _, x in rc); t = t + rc
        ve = V[ev.pE]
        te, ce = trade_err(ve, ev.trades)[0], cut_err(ve, ev.cuts)
        vo = votes.loss(ev.vote_values(V[ev.pVR])) if votes is not None and len(votes.C) else 0.0
        reg = 0.02 * sum(abs(p[k]) for k in REG_KEYS)
        fo = far_err(ve, ev.trades, far_at) if W_FAROFF else 0.0
        tot = W_CALLS * c + W_TRADES * te + W_CUTS * ce + vo + reg + W_FAROFF * fo
        return dict(total=tot, calls=c, trades=te, cuts=ce, votes=vo, reg=reg, faroff=fo, tests=t) if detail else tot
    obj.cache = cache            # module constants read by characteristics() (try-rule's F.X=v) need it cleared
    return obj


def _ok(q): return q["y200"] < q["y450"] < q["y650"] < 1000


def fit(obj, starts, restarts=8, passes=3, polish=4, seed=0, log=print, workers=None):
    """coordinate search over every rule's strength within its sign-locked bounds, perturbed restarts, a polish.

    The candidates are scored over `workers` forked processes (default FIT_WORKERS: one per CPU; 1 = in this process)
    with the search's choices made in the same order as before 2026-11-10, so the fit lands on the same parameters:
    a coordinate step's 13 values of one strength are independent of each other (only that strength moves when one is
    taken), and the polish draws its random steps in the same order and re-scores any step drawn before a move from the
    moved point.

    A parameter with no BOUNDS entry is not a fitted strength: it is held at the starting point's value (Oliver,
    2026-11-10: keep the values as they are) and returned unchanged."""
    p0 = min(starts, key=obj)
    fixed = {k: v for k, v in p0.items() if k not in BOUNDS}
    if fixed:
        log(f"held (no bounds): {', '.join(f'{k}={v:g}' for k, v in fixed.items())}")
        inner = obj

        def obj(q, detail=False): return inner({**q, **fixed}, detail)
        starts = [{k: v for k, v in p0.items() if k in BOUNDS}]
    with _Scorer(obj, workers) as score:
        p = _fit(obj, score, starts, restarts, passes, polish, seed, log)
    return {k: p[k] if k in p else fixed[k] for k in p0}


def _fit(obj, score, starts, restarts, passes, polish, seed, log):
    p = min(starts, key=obj); best = obj(p); rng = np.random.default_rng(seed)
    log(f"start: total {best:.3f}")
    scale_keys = ("y200", "y450", "y650", "lvl", "vet", "vet_hi", "top_g", "spike_hi", "youth_age")

    def coord(p, best, n):
        for _ in range(n):
            for k, (lo, hi) in BOUNDS.items():
                qs = [q for q in (dict(p, **{k: float(x)}) for x in np.linspace(lo, hi, 13)) if _ok(q)]
                for q, e in zip(qs, score(qs)):
                    if e < best: best, p = e, q        # p moves only in k, so the later q are unchanged
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
        # 400 random steps around the current point: the noise is drawn step by step, key by key, as before (each step
        # draws one normal per strength whether it is taken or not); a batch is scored at once and, after the first
        # step that improves, the rest of the batch is rebuilt from the new point and scored again
        drawn, queue, B = 0, [], max(1, 2 * score.n)
        while drawn < 400 or queue:
            while len(queue) < B and drawn < 400:
                queue.append([rng.normal(0, 0.08) for _ in p]); drawn += 1
            batch, queue = queue[:B], queue[B:]
            qs = [{k: float(np.clip(v * np.exp(z) if k in scale_keys[:7] else v + z, *BOUNDS[k])) for (k, v), z in zip(p.items(), zs)} for zs in batch]
            ok = [j for j, q in enumerate(qs) if _ok(q)]
            es = dict(zip(ok, score([qs[j] for j in ok])))
            for j in ok:
                if es[j] < best:
                    best, p = es[j], qs[j]
                    queue = batch[j + 1:] + queue
                    break
        d = obj(p, True)
        log(f"pass {it + 1}: total {d['total']:.3f} | calls {d['calls']:.3f} ({sum(x == 0 for _, x in d['tests'])}/{len(d['tests'])} pass) "
            f"| trades {d['trades']:.3f} | cuts {d['cuts']:.3f} | votes {d['votes']:.3f}")
    return p


FIT_WORKERS = int(__import__("os").environ.get("FAAB_WORKERS", "0")) or (__import__("os").cpu_count() or 1)
_OBJ = None


def _score_one(q):
    return _OBJ(q)


class _Scorer:
    """obj over a list of parameter sets, in order: in this process (n == 1) or over a forked pool"""

    def __init__(self, obj, workers=None):
        self.obj, self.n, self.pool = obj, max(1, int(workers or FIT_WORKERS)), None

    def __enter__(self):
        global _OBJ
        if self.n > 1:
            import multiprocessing as mp
            _OBJ = self.obj; self.pool = mp.get_context("fork").Pool(self.n)
        return self

    def __exit__(self, *a):
        global _OBJ
        if self.pool is not None: self.pool.terminate(); self.pool.join()
        _OBJ = None
        return False

    def __call__(self, qs):
        if not qs: return []
        if self.pool is None or len(qs) == 1: return [self.obj(q) for q in qs]
        return self.pool.map(_score_one, qs, chunksize=max(1, len(qs) // (2 * self.n)))
