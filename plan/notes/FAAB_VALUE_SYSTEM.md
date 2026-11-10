# FAAB value system and the rating page

What every QB/RB/WR/TE is worth in the league's own FAAB dollars on a date. The values come from stats only and
use only what was known that day, the way the league values players. A 1.05 rookie pick is about $1,050.

## How a value is made

1. **Base value (walk-forward)**:
   - Production value: projected points above superflex replacement, aged by position curves.
   - A stats translator: stats in, never KTC in. It is fitted to the KTC history only as a training scale.
   - A league-price model fitted to LOTG drafts, trades and waivers.
   - Every model is refit at each quarterly snapshot, on data dated before that snapshot. Values are then smoothed causally across dates.
2. **General rules** (`lib/lotg_support/faab_value.py`): about 45 characteristics, such as:
   - usage (expected points), team share, availability, a sustained elite record, QB passing quality;
   - early-career draft and college pedigree, efficiency, volatility and TD dependence, age cliffs;
   - injury status, off-field events, the replacement line (vets ranked below the line are worth about 0).
   - from Oliver's notes on the worst-fit trades (2026-11-07): a veteran TE whose role is within 2.5 expected PPG
     of TE replacement is near waiver level (`te_line`); the replacement line fades in from age 25 to 28 instead of
     sparing only the first three seasons; an older player's drop in expected PPG fades his record boosts
     (`regress`, fitted to 0 so far); a player on any NFL roster (IR, suspended) is never "no NFL team"
     (`e_x_rostered_recent`).
   - second round of Oliver's notes (2026-11-07): the TE line keys on usage levels, not a rank (how many TEs hold a
     real role changes year to year). It has two tiers on a 4th-season-on TE's expected PPG (this season once he
     has 4+ games, else the blend): a capped light drop below `te_thr` (`te_soft`, fitted 11.25) and a harsher one
     below `te_thr2` (`te_line`, 9.5; held at 10 or under on Oliver's call, since the free fit puts one harsh cut
     at 11.1 for -0.03 total). A proven TE (2 of the last 4 seasons at 15+ / 16+ PPR a game, or last season,
     `e_x_s15_4y` / `e_x_s16_4y` / `e_x_ppg_l0`) can get a softer line (`te_relief`, fitted 0).
     The old-player decline: past an age wall (RB 30, WR 31, TE 32; never QBs) a player whose usage (15% = full)
     AND fantasy points per game (game-log PPR; 5% is noise, 20% = full) both fell loses his record boosts
     (`rec_age`, fitted 1.0) and value (`old_cliff`, fitted -1.5): Kelce May 2024 $3,343 -> $435. Requiring the
     points drop spares an old receiver whose role was trimmed while he still scores (Adams, Evans on a new team);
     the first version (usage only, RB wall 29, QBs too) took Adams to $9 and fought the Stafford/Henry/Kittle calls.
     Third round (Ekeler 2024, Adams 2025, the healthy-player misses): availability's clean-record boost has its own
     strength (`avail_up`); the fit keeps it equal to the missed-games one (without it trades improve 1.115 -> 1.105
     but 8 calls fail). `share_age` (team-share talent fades past the age wall) and `anchor_old` (older players pulled
     toward their current-usage value) both fit 0: each one that fixes Ekeler / Adams also takes Henry, Kittle and
     Jacobs below Oliver's calls. `rookie_day3` (day-3 / undrafted rookies held near their slot) fitted -0.25.
     Offseason signings and YPC (Oliver: "offseason signings def should be included"; Najee's YPC): `e_x_moved_off`
     (`faab_features.offseason_move`) = from March 15 to kickoff, his Week-1 team differs from his last team the
     season before (Week-1 roster as the signing, small hindsight); `vet_move` docks a 27+ non-QB who changed teams
     (fitted -0.17); `ypc_bad` docks an RB from his 4th season with under 4.1 yards per carry over the last two
     seasons (`e_x_ypc_2y`, 100+ carries; fitted -1.67). The refit set old_cliff / rec_age to 0 again, so they are
     held at their earlier fitted -1.5 / 1.0 (Kelce May 2024 $435, Oliver's call).
     Follow-up (2026-11-07, Jonnu / Everett / Osborn / Reed): the move flag stays on past kickoff, up to 5 weeks,
     until his first game is in the stats (`no_cur_team`): between kickoff and that game neither e_x_moved_off nor
     e_x_new_team fired, so Jonnu's MIA -> PIT move missed `vet_move` on 2025-09-07. This season's usage fades in
     over a player's first 4 games (`w4`, a quarter a game) wherever a rule switched from last season's number to
     this season's at 4 games (te_x, peak share, the decline's usage and PPG drops, a QB's PPG); Everett / Gesicki
     2022 709% -> 88% off. No params changed (total 7.691 -> 7.672).
     Then (Oliver's call): a WR in his 4th season on who has not had a starter's role (expected PPG over WR
     replacement) last season, the one before, or this season (2+ games) gets the full replacement line whatever
     his age (`wr_no_role`; Osborn Nov 2023 $80 -> $47; Reed 2025 untouched). Tried and rejected: the line by
     season instead of age (Parker Washington's calls: 8.11-8.86), and holding wr_talent / availability at their
     #559 strengths (refits 8.00 / 7.71, both also zero ypc_bad and peak_share). `boom_week` (raise only): a TE
     under 29 (fading from 27) whose best game in the last two complete seasons and this one (`e_x_max_2y`) is
     28+ PPR (+8 = full), for cheap players (under `boom_hi`); held at 1.0 / $1,000 on Oliver's call for Pitts
     (the fit sets it to 0; TE-only costs ~0.05; for every position it lifts old RBs / WRs with one big game and
     costs 0.1-2.2). The first TE tier (`te_soft`) bound opened to -3 and held at -2.0 on Oliver's call (Henry and
     the 9-11 TEs too high): the fit with it free stays at -1.0, but -2.0 refits best of -1.5 / -2.0 / -2.5
     (total 7.470, calls 102/121, trades 1.039) and takes the harsh tier (`te_line`) to 0. Pitts $155 -> $320,
     Kincaid $331 -> $121, Strange $222 -> $85, Kelce $178 -> $55.
     Last round (Oliver, no refit): `boom_week` now needs a 40+ PPR game (TE under 29); every position at 40+ with
     the age fade scored slightly worse (+0.025), so it stays TE-only. Moving 28 -> 40 costs 3 calls (Kraft and
     Likely "stay near the reviewed" fail; they were held up by the 28+ version): total 7.470 -> 7.805, Pitts $320
     -> $255. `fresh_start` (raise only, held 2.17 on Oliver's call: Likely / Worthy June 2026 964% -> 99% off):
     offseason (e_x_moved_off), a non-QB under 28 who moved and followed his head coach (`e_x_coach_follow`, from
     the schedules' coach columns: the new team's coach in its first game = the old team's in its last), with 3+
     games at 15+ PPR in the last three seasons (`e_x_g15_3y`, 5+ = full); it also lifts the TE line and the
     replacement line for him. It reaches only Likely 2026-06-09 in today's inputs.
     Then limited to a player who would otherwise be worth under $200 (`FRESH_MAX`, Oliver): Likely was $13 without it.
     Next round (Oliver, 2026-11-08, from Rachaad White's Sept 2024 trade, model $1,737 vs $373 of picks):
     `ypc_bad` now starts in an RB's 3rd season (exp >= 2: two complete seasons behind `e_x_ypc_2y`), strength
     unchanged (-1.17). White's 3.67 YPC over 2022-23 gives x0.28 -> $493 (Oliver: $400-700). Total 7.816 -> 7.798,
     trades 1.035 -> 1.029, calls 99/121; 12 other evidence rows move (7 cheap RBs); on the 2026-10-28 board
     Braelon Allen $85 -> $29, Vidal $34 -> $28, Wright $15 -> $8. The -1.17 was fitted on 4th-year-plus RBs: the
     3rd-year reach is an extrapolation (half strength would put White at ~$926).
     `rookie_backup` (lower only) BUILT AT 0: a non-rookie RB (`BACKUP_POS`) whose team added a same-position rookie
     the league paid for this season (`e_x_rookie_backup` = each rookie's largest rookie-draft price or waiver bid,
     a bid in the first 10 days of the season x4 = `ROOKIE_W1_MULT`; $250 = 1, cap 2). Early (his first 4 games,
     gone by 8) a drop in his OWN per-game carries / targets / snaps vs last season (`e_x_rookie_backup_held`
     under 0.9, 0.6 = full) raises it up to 1.5x; later a kept workload (0.75 -> 0.95) fades it out. A rookie's
     low usage never dampens it. Every strength makes trades worse (-0.25: 1.051; -1.0: 1.075; RB+TE same, +QB
     costs calls): Warren / Kaleb Johnson 2025 (held 1.38), Dobbins / RJ Harvey 2025, Tracy / Skattebo 2025,
     Gordon 2021 and White himself (below the $373 paid) all get worse; James Robinson 2021 improves. The inputs
     columns come from `faab_pipeline.backup_columns` (feature store `xf_roster_team` + the game log, which now
     carries targets).
     `draft_comp` (lower only, set to -1.5 on Oliver's call to explain Quentin Johnston, May 2025: model $870 for
     a 4th + $20; Oliver: "around two good 3s" = ~$190-220): same-team, same-position rookies the NFL took in
     rounds 1-2 this season (`e_x_draft_comp`, from NFL draft day until March; a second one counts half), from the
     player's 3rd season, for base values $200-600 (fading 150-200 and 600-800). QJ $870 -> $194 (Tre Harris).
     No other refit. Total 7.798 -> 7.952, trades 1.029 -> 1.056, calls 99 -> 100/121; over 100% off 71 -> 74
     (+$25), 41 -> 40 (+$100). Fixes Mike Williams 2023, Deebo 2025, Reed 2025; breaks Kirk Jul-Aug 2024 (BTJ),
     Claypool 2022, Gordon 2021, Dobbins 2025. Rounds 1-3 from the 2nd season (Oliver's first spec) scored 8.914
     and docked 2nd-year Burden $1,595 -> $356. Board 2026-10-28: Garrett Wilson $1,093 -> $885.
     Exception (Oliver): a rookie does not count when his team lost a same-position player worth replacing that
     offseason (`faab_features.departed`: on the roster in his last week of the season before, not in his first
     week of this one, and `DEPARTED_PPG` PPR/game over 6+ games before: RB/WR 13, TE 10.5, QB 16 ~ a $200 base,
     as base values are not in the inputs for every player). Reaches DeVonta Smith 2026 (A.J. Brown left; $100 ->
     $446 back), Kirk 2024 (Ridley left; BTJ) and DJ Moore 2021. Total 7.952 -> 7.893, trades 1.056 -> 1.044,
     over 100% off 74 -> 72 (+$25), 40 -> 39 (+$100).
     Trade-note rules, 2026-11-08 (Oliver's review of the two far-off lists; each strength set by a one-rule scan,
     no other refit; the objective's parts are in the PR):
     `cheap_deal` (lower only, -2.5): a non-QB who moved (signed / traded since last season) on a veteran deal signed
     this season under 3% of the cap for an RB (1.5% = full), 4% WR (1.5%), 3% TE (1%) (`e_x_vet_deal_cap`, Over The
     Cap via nflverse, `lotg_support.contracts`), for base values from $300 (full by $600). Ekeler 2024 $1,234 -> $141.
     `share_old_cap` / `share_old_age` (1.25, 31): an older WR's share_talent multiplier is capped at x1.25 (full from
     31, fading in from 29). Adams 2025-04 $894 -> $628. At 29-30 it breaks the A.J. Brown call.
     `undrafted` (lower only, -2): a rookie not taken in the league's rookie draft and not a top pre-Week-1 add
     (`e_x_league_undrafted`: 1, less his largest bid from the draft to kickoff + 4 days over that season's 5th-largest
     such bid), fading out over his first 4 games. Luke McCaffrey 2024 $197 -> ~$30, LeQuint Allen 2025 $99 -> ~$20.
     `te_one_off` (lower only, -1): a TE whose last season was his one big year (11+ PPR a game) on a team he had just
     joined, after 2+ mid seasons (under 10, 8+ games) in the five before (3 = full), now on the move again; fades over
     4 games. Jonnu Smith 2025 $167 -> $61.
     `team_q_lo` (raise-only strength 0.5 on the negative side only): a bad team counts extra for base values under
     $75 (fading out by $150). Tre Tucker 2025 $111 -> $79. Trades and cuts better; the "Michael Wilson up (>= $500)"
     call fails (the objective is +0.04 worse, all calls). Both directions scored worse (cuts).
     `qb_paid` (raise only, 0.75): a QB a new team just signed to a veteran deal at 8%+ of the cap (15% = full), until
     he plays (fading over 4 games); the replacement line is lifted for him. Carr 2023-03 $71 -> $337 (Wilson 2022 and
     Garoppolo 2023 are the others it reaches). Without the in-season fade it broke the Carr 2023-11 trade.
     `avail_young_floor` / `avail_young_age` (0.5, 24): the availability multiplier is floored at x0.5 under 24, fading
     out by 26. Dobbins 2023 $78 -> $104.
     ypc_bad now reads `e_x_ypc_3s` (the last two complete seasons and this season's games known by the date) where it
     has 100+ carries: Mixon 2021-12 $1,872 -> $2,132, Akers, White 2024, Najee 2024 better.
     Tested and NOT kept (the numbers are in the PR): a 2.5x cap on the value 4 weeks earlier (needs grid rows the
     committed inputs don't have), spike reset after 3 games on a new team (17 rows, one trade worse), early exits
     counted as missed games (with or without a missed-next-game check: calls break; the version that improves trades
     is really a low-snap-games penalty), a 3-good-game streak on spike (no trade moves), a vacated-role boost (more
     trades worse than better), a young-elite boost and an award age fade (both blocked by the top-end and veteran
     calls), a rushing-share WR dock (Deebo 2022 and 2025 trades worse), a lighter usage prior for young players.
     Defect found (fixed in round 3, below): `wr_talent` was `clip(raw - usage)` with raw = 0 for QBs / RBs, so a QB or RB with usage
     under replacement gets wr_talent = -usage (Mac Jones 2022 x1.07, Fields 2021 x1.48). Fixing it moves trades
     0.987 -> 0.982 and cuts better but fails two calls (Henderson, Love > Egbuka); waiting on Oliver.
     Trade-note rules round 3, 2026-11-08 (Oliver's 16 items; one-rule strength scans, no other refit):
     the 2025 2.09 toilet-reward hop 2 moved from the 2025-04-15 Adams trade to the 2025-06-25 Roschon Johnson /
     Jerry Jeudy trade (data/commissioner_pick_trades.csv, a build change). Calls are dated (`faab_calls.CALL_DATES`:
     first review 2026-10-24, second 2026-10-25, chat consensus 2026-10-26) and each group is scored on the latest
     board on or before its date; the Michael Wilson call is now >= $400. Kept:
     `overtaken` (lower only, -1.5): a player 29+ outscored last season by a same-team, same-position rookie
     (`faab_features.overtaken_by_rookie`, by PPR/game gap over 4), fading over 8 games of this season (Kupp 2024
     $1,225 -> $288; with no age gate the Coker and Doubs calls break).
     `wr_pair` (lower only, -2, a post-rule): when two WRs on one team are both over $1,750, the lesser is docked by
     the other's target share (`wr_mates` rows in the export; Waddle $2,205 -> $1,171).
     `wr_talent` is WR/TE only (the QB/RB defect above, fixed), with `young_upside` (0.45) for QBs/RBs in their first
     two seasons by how far production lags usage.
     `young_elite` (raise only, 1.0): an RB/WR under 24 (gone by 25) at 18-22+ PPG (Jefferson 2022 $3,027 -> $3,562).
     `te_top3` (0.5): a top-3 TE by this-season PPG keeps more of the TE-line relief (Schultz $121 -> $314; flag:
     Pitts on the board $255 -> $694).
     `rookie_r1` (lower only, -1.5): a non-rookie RB whose team just drafted an RB in NFL round 1 (`e_x_draft_comp_r1`),
     when he himself was a pick after 64 or undrafted (Robinson $2,246 -> $910). `r1_wr` (-0.3): the WR version for 2+ year WRs (Deebo 2024
     $2,183 -> $2,079).
     `ROOKIE_PRIOR` RB 0.25: a second-year RB's rookie usage counts a quarter in the usage prior (Kyren 2023; the
     Monangai call now passes; at WR/TE it breaks "Nabers > Tet").
     `lag_cap` (a cap at a multiple of the value 28 days earlier, from the export's `lag_rows`) is built and off (99)
     until a rebuild provides the lag rows. Result on the local inputs: over 100% off 67 -> 61 (+$25), 32 -> 26 (+$100).
     Tested, NOT kept: season-start ages (Deebo 2025, Gainwell worse), a cuff role that ends in season, injury-report
     weeks over two seasons (trades better, 10 calls break), ACL-recovery forgiveness, a lower alpha floor, a vacated
     12-PPG role boost, faster award decay, an award cap, NFL round-3 draft capital for WRs (Cooper).
     Investigated, nothing to change: Tannehill vs Carr (the base model's prior PPG), Sutton (the Burrow side),
     Adams/Rodgers 2022 (a 4-for-1 consolidation).
     From the game log (`faab_features.game_form`), built on Oliver's call; `duds` and `slump` are fitted to 0:
     - `duds` (lower only): a WR/TE's full-role games (50%+ of snaps) under 5 PPR in the last two complete seasons,
       past 2.
     - `slump` (lower only): a non-QB in his first four seasons whose last 10 games fell 10%+ below the 10 before,
       across seasons.
     - `peak_share` (raise only): a WR/TE under 25 (fading from 24) whose best season's share of team expected
       points is 26.5%+. It is narrow on purpose: on the 2026-10-24 board it reaches 1 player (JSN at 26.2% and
       Puka at 25 are outside it). Oliver allows stat rules that reach
       one or two players today.
   - the summer (2026-11-04): one level shift for every player against picks and FAAB from June 1 to 3 days
     before kickoff (`e_x_offseason`, either sign, 0 on every in-season board). Before this, the "unsigned from
     June 1" flag fired for every player on a Week-1 roster too (the weekly rosters start at Week 1), so the
     off-field rule (x0.435) did this job by accident, on 77 of 214 fitted trades. `e_x_unsigned` now marks only
     players off the Week-1 roster (signed in-season or never).
   - QBs (#531): draft capital fading over four seasons; an established starter (usage over the line, 2+ top-12
     seasons, fading 30-34); an opening (a QB who has played well, ahead only of an aging backup holding the
     snaps; an early-career bet since 2026-11-07: full in a QB's first two seasons, fading to 0 by his fifth). Its
     strength (0.6) is the one the rating-page votes pick: trades, cuts and calls don't move with it (it reaches one
     trade row), so the plain fit's small pull toward 0 had zeroed it in #558. On IR, a player's usage and availability read his seasons before the injury, since the IR rule already
     charges for this one.

   Each characteristic's strength is one number, used the same way on every date and for every player. There
   are no names and no pins. Sign locks keep each rule pointing the only plausible way: an injury can only lower
   a value, an award can only raise it.
3. **Fit**: all strengths are fitted jointly. Trades and cuts count for more than one person's calls.

   | Term | Weight |
   |---|---|
   | Completed trades (both sides on the trade day's own board; see "Evidence timing") | 3 |
   | Cuts (worth under ~$100 on the cut day's board) | 3 |
   | The league's calls (`faab_calls.py`, tests on the 2026-10-24 board) | 1 |
   | Rating-page votes, capped (below) | ≤ 1.5 |
   | Pull of every strength toward 0 | small |

Results on 2026-10-24:

| | Rules off | Fitted |
|---|---|---|
| Trade error (median + mean \|log side ratio\|) | higher | 1.125 |
| Cuts valued over $100 | 8.7% | 5.6% |
| League calls passing | – | 89 / 116 |

The remaining misses are mostly young mid-tier receivers the league likes more than the stats do: Ladd,
P. Washington, Coker, J. Price. Addison and Jamo are also on the list.

## Round 4 rules: the final stage (2026-11-09)

Ten rules act on the value the other rules produce, after the usage anchor and top compression
(`faab_value.final_terms`; `explain` lists them with the rest, and its stages now include `top`, the value before
them). Each one passed the noise bar below on the committed inputs, or was kept on Oliver's call where marked, and
each has its reason in the code beside it.

| Rule | Strength | What it does | Why |
|---|---|---|---|
| `vet_floor` | 0.8 | A QB/RB/WR/TE in his 5th season or later, 60%+ of the snaps and 9+ PPR a game (this season from 3 games, else last season), is pulled 0.8 of the way (in log) toward $40 | A team starting a scoring veteran would not cut him for a waiver body. The PPR floor keeps out a blocking TE who plays the snaps without the points. Tested without TEs (trades -0.048) and with them (-0.055), and PPR floors 0-12: 9 is best |
| `rb_duds` | -0.2 | An RB's full-role games under 5 PPR in the last two seasons, before his 3rd game | A low floor the league prices in until this season shows otherwise (the WR/TE `duds` rule's RB side) |
| `wr_band` | -0.25 | WRs valued $1,300-2,300, fading out to $900 / $3,000 | How the league values WRs (Oliver): it pays less for that tier than the base does |
| `qb_band` | -0.1 | The same band for QBs | Fixes the Nix / Dak / Love "low first" calls; -0.1 keeps Purdy's call (-0.15 loses it) |
| `rb_band` | +0.2 | RBs valued $45-90, fading out to $25 / $160 | A cheap RB with a path is worth a bit more than the base gives |
| `rb_inj` | -0.2 | An RB 26+ with injuries to several body parts (3 seasons; 2 = full), unless he has averaged 19+ PPR a game over 3+ games since his last week out (0.25 less per game past 3, down to 14) | Wear the league discounts; a back who has played like a star since he returned has answered it (Oliver: Walker 2026, 14.8 over 23 games) |
| `spike_vet_rb` | -0.2 | A 4th-season-on RB's big-week spike bonus, before his 3rd game | A veteran's big weeks are last season's, already in his price |
| `qb_inj` | -0.1 | A QB's out-or-doubtful share of his weeks (2 seasons; 25% = full) | Superflex needs the QB every week (Oliver: Lamar's injuries) |
| `wr_backup` | -0.1 | A non-rookie WR whose team's league owner spent $100+ of FAAB on a same-team rookie WR ($250 = full, cap 2) | The league expects the rookie's role to come out of his. **Kept on Oliver's call: it fails the late-half bar** (late -0.0006) |
| `wr_clean_old` | -0.1 | A WR 26+: the clean-record boost (`avail_up`) is trimmed | Consistent on trades (16 better / 5 worse, 5/5 folds) and keeps CeeDee > Kyren and Jefferson top 12, Oliver's condition |

All ten together on the committed inputs: trade error 0.953 -> 0.816 (early half -0.061, late -0.042; 86 trades
better, 30 worse; 5/5 folds; bootstrap P(worse) < 0.001), far-off trades 61 -> 50 (+$25 per side) and 26 -> 23
(+$100), calls 108 -> 110 of 121 (under the tolerances below). Not done: the late-season WR discount (Oliver: noise),
exempting held rules from the strength pull (Oliver: cheating), the starter-seasons and separation rules.

**The calls' tolerances** (`faab_calls`): a range call passes within 5% of its bounds and a player-over-player call
only when it misses by under 1% (3% random noise on the board flipped about 8 passing calls). One call's loss is
capped at 0.5 (log units), so no single call outweighs the trades. The Rice call is ">= $800" (Oliver; Boston's
call unchanged).

## Round 5: Oliver's notes on the failing calls (2026-11-09)

Calls changed (`faab_calls`): McConkey is a low first / top-2 second ($453-1,200, was a low first), Coker at least
a mid second (>= $222; his breakout call is folded into it), Kraft's "stays near the reviewed" call centres on $800
(was $918), Henderson's low-first call is dropped (it was Oliver's, not the league's; his league-chat call stays), and
the replacement-level bubble is a mid-late second to an early third, $93-222 (2.05 to 3.03 on the pick board; was
$50-300). Prices are the 2026 pick board's slots.

New rules, all in `final_terms`, each the smallest strength that fixed its call. Their inputs are computed at
export from the game log (`faab_features.round5_columns`, `faab_pipeline.qb_base`), so they are off until a rebuild
writes the columns. None moves trades by more than the noise bar, so they are judgment rules held on Oliver's notes.

| Rule | Strength | What it does | Call it fixes |
|---|---|---|---|
| `tgt_lead` | +0.5 | A WR/TE (base $50-1,000) who led his team in season-to-date targets (18%+ of them, 4+ games in) and has since lost the lead, fading over his next 17 games, with a team QB of base $600+ | McConkey, Kraft. A current leader is left out (his usage already prices him; with leaders in, Golden / Egbuka / Parker Washington calls broke) |
| `rb_touch` | -0.4 | An RB in his 2nd or 3rd season with fewer than 3 career games over 20 touches (2 = 1/3 off, 0 = full) | Tuten (1 such game). Oliver's "by snap count" read as touches: Tuten had 8 games over 20 snaps but 1 over 20 touches. Every season: trades +0.008; with a snap-share gate: no better |
| `te_slide` | -0.1 | A TE whose last two seasons both finished outside the top 7 by total PPR (x2 if the last was outside the top 20), who had a top-7 season before them, unless 3 of his last 4 games were top-5 TE weeks | LaPorta. The OC change Oliver named is not in the data, so the earlier-top-7 gate stands in for it: without it the rule also hits Kraft (never top 7) and breaks his and Loveland's calls |
| `qb_tough` | +0.2 | A QB whose last 2+ complete seasons were each either top 5 in PPR a game (6+ games) or hurt (under 12 games), with at least one of each (4 = full) | Burrow > Mendoza. Without the "one of each" condition it lifted Allen (top 5 every year) and broke the top-3 calls |
| `snap_cap` | on | A QB with under 2 career games on half the snaps is worth at most his league rookie-draft price | Burrow > Mendoza (Mendoza $2,062 -> $1,235). At every position: trades +0.005 |
| `qb_ypg` | -0.1 | A QB worth $1,000+ with low passing volume: passing yards a game (this season from 4 games, else last) under 230, full 40 below | Hurts < Caleb, Hurts <= $1,800 (186.6 a game). Time to throw (Hurts 98th percentile in 2024) also docked Allen, Lamar and Purdy and broke their calls |
| `young_boom` | 0 | A 2nd-3rd season RB/WR/TE under $1,000 with 12+ PPR a game and a 30+ game in his last 3 healthy games (half the snaps) | Built, held at 0: Coker's call passes without it and trades were slightly worse with it |

On inputs with these columns computed from the committed game logs (the QB gate approximated from the nearest
board): calls 112 -> 119 of 119, trades +0.002 (10 better / 13 worse, both halves down), far-off trades 50 -> 50.

### Round 5b: the Aug 2025 Conner trade and the summer shift (Oliver 2026-11-09)

The 2025-08-02 trade (Conner $54, Pollard $46, Dobbins $24 for $292 of picks/FAAB) was 2.1x off. Most of the gap is
the summer level shift (x0.43 on every player from June 1 to 3 days before kickoff, a date-only flag): with it off the
side is $247. No rule reads whether a player was traded; every value is the player's on the day before.

| Rule | Strength | What it does | Result |
|---|---|---|---|
| `rb_hold` | +0.6 | An RB who was a top-15 RB (total PPR) last season, whose team added no proven RB (13+ PPR a game over 6+ games in either of the two seasons before, joining that offseason) and no rounds 1-2 rookie; base $400-1,000 (fading over the 25% past each end), only while his value at that stage is under $600 (fading from $450) | Conner $54 -> $98, the trade 2.1x -> 1.6x. Uncapped it lifted Henry and broke both his calls (trades +0.009) |
| `draft_comp` new-arrival cut | `DRAFT_COMP_NEW` 0.5 | draft_comp is halved for a player who joined the team that offseason (`e_x_moved_off` / `e_x_new_team`), unless the rookie is a first-rounder | Dobbins (RJ Harvey, round 2) $24 -> $28 with rb_hold |

Together: trades -0.0019 (early -0.0021, late -0.0018; 4 better / 3 worse), far-off 50 -> 49, calls 119 of 119.
Under the -0.007 bar; in on Oliver's call. Today rb_hold reaches Henry (x1.38, his calls pass) and Etienne (x1.02).

Tried and left off: ending the summer shift at the league rookie draft (`SUMMER_TO_DRAFT`, column
`e_x_league_draft_done`): trades +0.075 and far-off 49 -> 55; with its own strength after the draft the trades still
want -0.75 to -0.83, so the shift does not end with the draft. Raising picks and FAAB in summer instead of cutting
players (best x1.4): trade error 0.883 vs 0.819, far-off 54 vs 49, because the shift acts before the final-stage
rules (vet floor, bands, the $25 pad), so cheap players drop only to ~x0.77. try-rule now clears its cached
characteristics for `F.` constants (it reported trades +0.0000 for SUMMER_TO_DRAFT before).

### Round 5c: catch rate on the target lead, a smaller post-draft summer shift (Oliver 2026-11-10)

- `tgt_lead` now needs a typical catch rate: receptions / targets over the last two complete seasons and this one
  (`e_x_catch3`, 30+ targets) at or above the position median (WR 0.64, TE 0.69, from 2018-26 seasons with 50+
  targets), fading to 0 at 2 points below. McConkey 0.682 and Kraft 0.709 keep it; Quentin Johnston 0.601 (Oct 2025)
  loses it. With the column: trades -0.0012, far-off 51 -> 50, calls 119 of 119.
- Summer: `summer` -0.7 before the league draft (x0.50) and `SUMMER_TO_DRAFT` 0.524 lifts about half of it after
  (-0.33, x0.72), on Oliver's football reasoning (after the draft the picks are players). The Aug 2025 Conner trade
  goes from $172 vs $292 to $276 vs $292 (near even). Oliver accepted the cost: on the committed inputs trades +0.038
  and far-off 51 -> 54 (with `e_x_catch3`: 50 -> 53), calls unchanged.

### Round 5d: the summer window (Oliver 2026-11-10)

Grid on the committed inputs (start = NFL draft -30/0/+14 days, Mar 1, May 1, Jun 1, Jul 1; end = kickoff -17/-3/+0/+4/
+7/+10/+14 days; fade-in 0-90 days, fade-out 0-14; strength -0.5 to -0.9; post-draft lift 0.25-0.8). Kept:
`summer_weight` rises from 0 at 90 days before the NFL draft (late January, the season over) to full at the draft
(rookies have teams), and runs through Week 1 (kickoff + 7 days); no fade-out (every fade-out scored worse). Strength
-0.7; `SUMMER_TO_DRAFT` 0.5 of it lifts after the league draft (Oliver's pick): the Aug 2025 Conner trade $271 vs
$292. Trades 0.863 -> 0.847 vs round 5c; far-off 54 -> 53. Lift 0.6: trades 0.856, Conner $292 (even); 0.25: 0.829, $230.
The window is computed from the date in `faab_value`, so it needs no rebuild.

### Round 5e: old RBs at first-round prices (Oliver 2026-11-10)

After the 2026-11-10 rebuild, Henry's "low first" call failed at $1,269 (the 1.02 on the 2026 pick board). Oliver: the call
is a mid-low first, so it is now its own call, 1.07-1.04 ($783-1,135). New final-stage rule `rb_old_hi` -0.1: an RB 32+
valued $1,000+ (fading in from $750) is docked, because the league won't pay first-round money for a back that old
however well he runs (the drop comes without warning). -0.1 is the smallest strength that passes the call. Today it
reaches only Henry's 9 vote/call-board rows (no trade or cut row moves), so it is a judgment rule like `boom_week`.
Calls 128 -> 129 of 129.

## Votes that count as calls (2026-11-10)

Oliver's rule: a rating-page vote that is unanimous, with 3+ teams agreeing, counts as a call. A team is one person;
each team's latest answer counts. As of the 2026-11-10 pull, 29 items (a price check on one player on one board, or
one pair) had 3+ teams answering, and 10 were unanimous (`faab_calls.VOTE_CALLS`). "About right" = within 15% of the
value shown (the vote page's band), then the usual 5% call tolerance. On the committed inputs 7 pass and 3 fail:
DJ Moore about $266 (board $126), Tyler Warren about $909 (board $745), Eli Stowers below $142 (board $213).

Rules for those three (module constants; Oliver approved these strengths on 2026-11-10):

| Constant | Strength | What | Why |
|---|---|---|---|
| `OUT_CLEAN` | 0.5 | Spare this share of `inj_out` (x0.55) for a player who missed no games over two seasons and has played | An Out tag on a durable player is most likely a short absence. Today `inj_out` (x0.55) is harsher than `inj_ir` (x0.69) |
| `OUT_LONG` | 1.0 | ... and grow the spare up to the whole discount with 34+ games since his last absence | The longer his run without missing time, the more likely the tag is a one-off (Moore: 92 games) |
| `ROOKIE_LOST` | -0.4 | A rookie on IR/PUP with at most 1 NFL game who has missed 75%+ of his team's games | He loses his rookie year: no role and no tape, so he is worth less than his draft price alone |

Together: calls 126 -> 129 of 129. No trade or cut row moves, so the trades can't test these. They are judgment
rules, like `boom_week`. Softening `inj_out` for everyone fails: it loses Addison, Hunter > Addison, Monangai and the
Hurts calls.

## The noise bar, and every rule needs a reason

FAAB formula changes are build changes (they go in a PR) but are exempt from the 3-part audit in
`plan/MASTER_TODO.md` (Oliver, 2026-11-09). This section is their check instead: keep editing the formula this way.

`python scripts/faab_value.py try-rule "name=value ..."` (`lotg_support.faab_trials`) scores a change against the
current params in about 3 seconds: the objective's parts, the calls lost and gained, trade error in each half of the
trades (split at the median date), trades better / worse, far-off trades, 5 folds and a paired bootstrap.
`F.NAME=value` changes a rule's fixed shape (`F.VET_FLOOR_PPG=9`); `--base` applies changes to both sides (testing a
rule on top of others); `--data DIR` reads another inputs folder. Put its output in the rule's PR.

A rule passes when trade error drops by 0.007+, each half by 0.003+, more trades get better than worse, and the total
drops. In a shuffled-feature null run (1,372 random features, 2026-11-08) 0 passed this bar; about 1 in 40 passed
the old one (trade error and total down).

**Every rule needs a logical football or league reason as well (Oliver, 2026-11-09).** Passing the bar shows the
evidence supports a rule; it does not explain it. A rule with no reason is not added; ask Oliver for one.

**Rules that only calls or votes support** (they touch 0-1 trade or cut rows, so trades cannot test them; they are
judgment rules, held on Oliver's calls): `boom_week`, `peak_share` (0 rows); `qb_opening`, `two_way`, `qb_paid`,
`fresh_start`, `wr_pair`, `te_one_off`, `severe`, `inj_ir` (1 each). `overtaken` touches 19 rows with trades
neutral (2 better, 1 worse). Counts from 2026-11-08 on the committed inputs.

## Evidence timing (2026-11-09)

A trade is valued on its own day's board (`faab_pipeline.board_day`). Every board reads only what was known before
its day: league prices strictly before it, KTC the day before, weekly stats from the Tuesday after the games. Two
same-day events are counted by date only, so a trade made earlier that day could see them: the NFL draft (a trade
before that day's round starts, from the exact trade time: Thursday 8pm, Friday 7pm, Saturday noon ET, reads the day
before's board) and the league's rookie draft (its picks have no time, so a trade that day reads the day before's).
Cuts follow the same rule by day. Offseason trade days that are not Tuesdays are added to the grid as full boards
(`evidence_dates`); in a cached snapshot the model's output for those rows is carried from each player's latest
earlier row (`refresh_block`), and the rows are smoothed after the regular grid so no other day's value moves.
A player missing from the chosen board is read from the latest board up to 7 days before it. Before this, every
row was the latest board strictly before the trade: 86 of 214 trades were 2-7 days stale.

**Cached blocks re-read the stats** (`refresh_block`). Before 2026-11-09 a cached snapshot block kept the `e_x_*`
columns of the run that fit it, so a column added since was empty on every cached row: the 2026-11-08 rebuild lost
14 game-log columns (`e_x_ppg_l0`, `e_x_duds_2y`, `e_x_rostered_recent`, ...) on every pre-2026 row and its trade
error went 0.95 -> 1.12. The rebuild now refreshes every cached block's `e_x_*` columns from today's features.

## Commands

```bash
python scripts/faab_value.py board -n 40
python scripts/faab_value.py value "bucky irving" "Jaxon Dart"         # current value + rank; any spelling (exact, part of a name, typo)
python scripts/faab_value.py explain "Bucky Irving" "Bhayshul Tuten"   # every rule's multiplier (exact names; suggests close ones)
python scripts/faab_value.py calls
python scripts/faab_value.py votes                                     # votes vs the board
python scripts/faab_value.py try-rule "vet_floor=0.8" "wr_band=-0.25"  # a change vs the current params: the noise bar's numbers
python scripts/faab_value.py fit --out data/faab_value/params.json     # deliberate refit, reviewed in a PR
python scripts/faab_value.py publish                                   # rewrite the page's board/questions
```

## How the inputs are rebuilt (self-sustaining)

`scripts/faab_rebuild.py` (`lotg_support.faab_pipeline`) rebuilds `data/faab_value/inputs.csv` and `evidence.json`
from public data and the repo's own exports. `.github/workflows/faab_rebuild.yml` runs it weekly (Wednesdays) and
commits the inputs and the page data. It never refits the rule strengths.

| Stage | Module | What it does |
|---|---|---|
| Downloads | `faab_data` | nflverse / ffopportunity / college stats / Wikipedia awards / dynasty-daddy KTC histories into `.cache/` (git-ignored) |
| Features | `faab_features` | dated `e_x_*` stats, each counted from when it was known |
| Frame | `faab_frame` | per (player, date) stats frame (the KTC-proxy feature builder, moved into lib) |
| Inputs | `faab_inputs` | Sleeper ids, trades, cuts, pick prices, KTC training panel, valuation grid, evidence |
| Base | `faab_base` | the walk-forward base: one model set per quarterly snapshot, fit only on data before it |
| Formula | `faab_formula` | base -> `V_raw` on any date (floors, legacy, breakout, rookie slot, injuries, offseason blend) |

Finished quarterly snapshots never change, so the weekly run reuses their cached blocks and refits only the current
quarter (`--full` refits all, about 2–3 hours).

The port reproduces the research run exactly: every feature table, the base at two snapshots, and `V_raw` on five
dates, all with zero difference. Two research-era behaviours changed on purpose (`faab_base.REPRO` restores them for
reproduction):

- **Aging curve:** it kept seasons ≤ 2024 regardless of the snapshot. That counted the last complete season as all
  drop-offs at the 2021–23 snapshots, and would have frozen the curve from 2027. It now uses seasons before the
  last complete one.
- **Folds:** players outside the stored fold map were assigned folds with Python's `hash()`, which changes between
  runs. Folds are now a stable hash of the Sleeper id.

Points over expected also count only the best game's excess at half, the definition the rules already used.

**The build's FAAB Value columns** (2026-11-09): the rebuild also writes `history.csv` (every rostered player on
every grid date, valued with every rule and the committed `params.json`, sorted by date so git stores each week as
a small delta) and `pick_prices.csv` (the slot medians `faab_inputs.Picks` prices picks with, one block per league
draft day). `lotg_support.faab_history.FaabIndex` reads them for the build: every column in KTC value units has a
"FAAB Value" twin beside it (53 on add_drops, trades, both pick sheets and player_additions), same dates, same
depth tax, FAAB moved at $1 = $1, a pick at its FAAB pick price until its draft and then the drafted player.
Blank before 2021. A merged refit re-values the history with `scripts/faab_rebuild.py --history-only` (the
workflow runs it on a push that changes `params.json`; a manual dispatch can too). A draftee's first value lands on
the grid date after the league draft, so the draft-day columns take it (`FaabIndex.player_entering`).

**Pick slots fade in** (2026-11-10, Oliver: "pick number is not known until the end of the season"):
`faab_inputs.Picks.value` and `FaabIndex.pick` (so the fit's trade evidence, the build's FAAB Value twins and the
off-build columns alike) price a pick through `lotg_support.faab_pick_slots`. Before, a pick was its round's average
until January of its draft year and its exact slot after, so an in-season trade of next year's pick never saw the
standings and a January trade saw the slot before the final. Now, while its deciding season is next up or under way,
it is the slot prices weighted by its original team's projected odds that day: the KTC Price paid's model
(`acquisition.project_slot_odds` / `post_season_slot_odds`), with roster strength = the team's best 15 FAAB values
from the history, blended toward record (Max PF within the bottom four from the 2026 draft) by week 8, the spread
narrowing from 2.75 slots to 1.0; after the regular season the bottom four by the rule and the playoff block by the
bracket; the exact slot once the final is played. Two or more drafts out: still the round average. Original team: a
future label's "(team)", else rookie_picks' Original Team for the slot (or for the player later taken with it, since
the build masks a pick to "2026 3.??" before its season). A pick the build shows as "2027 4.??" with no drafted
player has no original team and stays at the round average. Result on main at 54bc73c (no refit): 81 of 214 trades'
pick sides move, trade error 0.842 -> 0.832, far-off trades 52 -> 52 at +$25 (two off, two on), 25 -> 23 at +$100.
`scripts/faab_rebuild.py --reprice-picks` re-derives evidence.json's pick values on the committed inputs (the full
rebuild does it anyway). `faab_pick_slots.FADE_IN = False` restores the old rule for comparisons.

**FAAB versions of the KTC-derived columns, off the build** (2026-11-09, Oliver: keep them out of the sheets): the
build writes `exports/raw/faab_derived/` (artifact only, `.gitignore`): O-Score on trades / add_drops / picks (pure
drops, both pick pools, the non-rookie de-trend), Trade impact score, the three manager skills, Wins added with the
lineage shares in FAAB values, Price paid (every traded asset at its FAAB value; a rookie pick at the FAAB slot
price) and Points above expectation refit on those prices. Each file holds the KTC column, its `(FAAB values)`
version and every component the scores read. `scripts/faab_derived.py check` recomputes all of them from those
components (0 differing rows = the offline recompute is exact); `compare` sets each column against its FAAB
version. `lotg_support.faab_derived.Search` recomputes the FAAB versions under one global transform of every FAAB
value (v -> a * v ** b) for the transform search; Wins added keeps its identity lineage there. `scripts/faab_derived.py search --dir <artifact>/raw/faab_derived
--today <build date>` runs it (the side output's `_fd_pk_recv` / `_fd_pk_sent` give each pick's label and drafted
player, so a no-transform run reproduces the build exactly). Finding (2026-11-09, report only, nothing adopted): a power
of about 0.25 (v -> 50 * (v / 50) ** 0.25) brings trades, picks and the per-season drafting / trading skills 27-43%
closer to today's KTC columns, leaves add/drop unchanged, and moves Price paid / Points above expectation further away
(they sit beside waiver bids in real dollars). log KTC on log FAAB over player-days has slope 0.27-0.29.

**Committed data the pipeline reads:**

- `chat_evidence.csv`: the league chat's valuations (player, date, log price, weight, kind), with no names or text;
- `offfield_events.csv`: retirements, legal and left-the-team events, dated;
- `awards.csv`: the parsed awards, the fallback when Wikipedia is not cached;
- `../suspensions.csv`.

**Votes and calls keep their dates.** The inputs keep the 2026-10-24 board, which the league's calls are judged on,
and every player a vote was about, on the board he was shown on (`evidence.json` `vote_dates`).

## The rating page

`docs/rate/` is a static page on GitHub Pages. Every question shows two players the board values about the
same, each with its board value and the nearest useful rookie-pick comparison. A comparison is either one
slot ("about the 2.03") or, for players worth more than the 1.01, a package ("about the 1.01 + 1.03 + 1.05").
Slot prices are the league's median draft prices for each slot, from drafts held before the board date.
Every part of an answer is optional, and nothing advances until Submit:

- which player is worth more, or "too close to call";
- for each player: too high / about right / too low;
- for each player: what you would pay;
- why.

One submission therefore gives up to three signals: the pick, plus a price check on each player. The pairs are
aimed where they teach the rules the most:

- close calls across positions;
- each player the rules moved most, against his nearest neighbour;
- pairs the rules pulled in opposite directions;
- random near pairs.

Every answer records:

- the voter's **team** (people value their own players more, so own-player answers count half; non-members count a quarter);
- the **board date** and the **values shown**, so an answer is judged against what was known then;
- the client time.

**Votes are signals, not edits.** They never set or move a player's value. They enter the fit as one capped
term, so they can only change how much a general rule weighs:

- its weight = 1.5 × min(1, teams answering / 4) × n / (n + 100);
- one team alone reaches at most a quarter of that;
- one team's share of the vote weight is capped at 35%;
- the term is always below the trades and cuts terms.

**How a price answer is scored** (#531): "too low" / "too high" only say the value shown is not right in that
direction, with no cap and no minimum (any higher / lower value agrees). "About right" is within 15% of the
value shown. A typed amount is a target, within 15%. Each answer is scored on its own; none is turned into a
point estimate (before #531 a bare "too low" counted as exactly x4/3, which held Jaxson Dart near $375 when
every voter said he was worth far more).

`votes` lists where the board and the votes disagree, and which rule terms put each side where it is, followed
by every "why" note. Those are the leads for a missing characteristic. Uneven participation is expected and handled by the caps.

### One-time setup (owner)

1. **Google Form** (forms.google.com), titled "LOTG value check".
   - Settings: *do not collect email addresses*, no sign-in required, allow more than one response. The repo is
     public, and the responses become a public CSV.
   - Add 17 **Short answer** questions, none required, titled exactly:
     `team`, `question_id`, `kind`, `board_date`, `player_a`, `player_b`, `shown_a`, `shown_b`, `answer`,
     `verdict_a`, `verdict_b`, `amount_a`, `amount_b`, `why`, `own`, `client_time`, `page_version`.
     `why` can be Short answer too; it holds a sentence or two.
2. **Entry ids**: ⋮ → *Get pre-filled link*.
   - Type each question's own title into its box, then *Get link* → copy.
   - The link holds `entry.NNNN=team&entry.MMMM=question_id…`. Put those ids into `docs/rate/config.json`.
   - Set `form_action` to the form URL with `viewform` replaced by `formResponse`.
3. **Responses sheet**: Responses → *Link to Sheets*.
   - In the sheet: File → Share → *Publish to web* → the responses tab → **CSV** → Publish → copy the URL.
   - Add it as the repo **variable** (Settings → Secrets and variables → Actions → Variables) `FAAB_VOTES_CSV_URL`.
4. **Pages**: Settings → Pages → *Deploy from a branch* → `main` / `/docs`. The page is then at
   `https://oliverwkw.github.io/LOTG-Stats/rate/`.

`.github/workflows/faab_votes.yml` runs daily (and on demand). It pulls the sheet into
`data/votes/responses.csv` and writes `data/votes/report.md`. It never refits.
