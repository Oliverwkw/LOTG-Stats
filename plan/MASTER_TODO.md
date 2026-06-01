# LOTG-Stats Master TODO

**Workflow per phase:**
1. PR opened
2. User merges + runs build
3. Claude runs **3-part audit** (see below)
4. Iterate until all three parts pass
5. Mark phase complete; move to next

**3-part audit (MANDATORY after every PR):**

1. **Code-based audit** — build runs cleanly, expected columns exist, schema matches, no errors in build_debug.log.
2. **Results-based audit** — for each change in the PR spec, derive **≥5 concrete verification cases** that the spec was actually implemented correctly. e.g. spec says "Last team uses fantasy year, in-season only" → find a player whose 2024 offseason trade should NOT override their 2023 Last team, and verify the cell holds the season-ending team. Cases must come from the change spec — not from comparing to the prior build.
3. **Diff-based audit** — diff sweep against previous build's CSVs (sorted by canonical keys) to confirm nothing *else* changed. Flag any non-intended sheet/column diff as UNEXPECTED.

When the results-based audit surfaces a bug, log it but continue to the diff sweep — fix all bugs together in a follow-up PR rather than serially.

---

## Phase 0 — Quick foundation ✅
- [x] Sheet order
- [x] player_week: Year as 3rd column
- [x] league_week: Year → Week Name → Week → rest
- [x] Drop columns: player_all_time (Rookie?, Age); team sheets (Largest deficit, Combined matchup); league sheets (Tanking, Luck)

## Phase 1 — Global rules ✅ (1A + 1B + 1C all merged)
- [x] N/A vs 0 sweep (Faab on FA/commissioner N/A; Win % vs self N/A; % starts made → 0; player addition value → 0)
- [x] Pick asset horizon verified at 3 years
- [x] Week-1 prev-week = previous season's last played week (≈ championship week)
- [x] "Number of X started/rostered" → unique players at team_year / team_all_time / league_year / league_all_time
- [x] Adjusted Avg points / PPG starter / PPG bench in player_year + player_all_time (alongside non-adjusted)
- [x] All derived consumers of player averages use Adjusted variants

## Phase 2 — Hardship + Luck
- [ ] Hardship redefined per spec; NFLverse backfill for early-2021 + new pickups
- [ ] 🔍 Investigate 2021 wk 1-2 hardship=0 with 23/30 injuries
- [ ] Starter-adjusted hardship column next to every hardship column
- [ ] Starter injury count column in league_week
- [ ] Luck rebuild; audit distribution; iterate weights
- [ ] **3-part audit** (code / results / diff)

## Phase 3 — Player sheets ✅
- [x] 🔍 Number of teams bug (Renfrow=5 not 4); fix partial-week rosterings — verified Renfrow=5
- [x] Top team / Last team → time rostered (not weeks) — shipped 3A.3; in-season FY window for Last team (PR #162)
- [x] Drop yearly rows for never-rostered players — verified 0 zero-team rows in player_year (1493 rows, all Number of teams ≥ 1)
- [x] Split Points (while rostered) vs Points (full season, NFLverse) — both cols present in player_year + player_all_time
- [x] Change-in stats use full-season values; only N/A for rookie years
- [x] Career average from NFLverse — Avg points (full season) col present
- [x] % of points redefined: starter contribution to team total; + team-name cols for highest/lowest — 4 cols present
- [x] Taxi-eligible boolean in player_all_time
- [x] Number of trades column in player_week (auto-rolls to year + all-time)
- [x] **3-part audit** — covered by retroactive audit (AUDIT_RETROACTIVE_3PART.md) + per-PR audits #160-#166. All 4 surfaced bugs fixed in PR #162; Hardship+SA fixes in #163/#164; caching in #165/#166.

### Phase 3 closeout — data-quality fix-ups
- [x] Tyler Conklin / Ryan Izzo gsis_id swap — Sleeper's `gsis_id` field for these 2 TEs is transposed; bridge now validates Sleeper's gsis against NFLverse's display_name last-name and falls back to DP when they disagree.

## Phase 4 — Team sheets
**Sub-PR plan:** 4A age/picks (1-2) · 4B draft stats (3,7,8) · 4C roster turnover + starter cols (4,5,6) · 4D cuffs (9,10,11) · 4E win/record regroup (12,13).

- [x] 🔍 Team age including picks ≈ player age (0-future-pick bug) — **4A**: `_picks_held_by_team_at` looked up roster id with the raw display handle against a dict keyed by `_norm_team_name`; 5 of 8 teams (any with capitals) resolved to None → 0 picks counted. Now normalizes the lookup key.
- [x] Player + team avg age = average of weekly averages (incl with-picks variant) — **4A**: confirmed both columns aggregate as `mean` of weekly team_week values in team_year / team_all_time / league_year / league_all_time.
- [x] Exclude 2021 vet draft from team draft stats — **4B**: drop "(vet)"-tagged pick_history rows from the Draft Value / # first round picks / total picks rollups (32 rows). Vet picks remain in pick_history.
- [x] Roster turnover refactor — **4C**: in-season = symmetric difference (unique players changed) between Wk1 and championship(final)-week roster/lineup; offseason = prev-championship vs this-Wk1 (full symdiff, no more /2); added "Average weekly starter/roster turnover" (mean of weekly from-prev-week); team_all_time turnover now per-season AVERAGE not sum. [in-season def + avg cols confirmed w/ user]
- [x] Starter injury/suspension weeks column — **4C**: "Weeks of starter injuries"/"Weeks of starter suspensions" — injured/suspended player-weeks where the player counts as a starter under the SAME heuristic as Starter-adjusted Hardship (starter_pct > 0 over the SA baseline window). [per user]
- [x] "Number of starters X over/under Y" companion columns + rollups — **4C**: added "Number of starter donuts / starters under 10 / starters over 20/30/40/50" companions; FIXED "Number of players …" to count ALL rostered (gameday) players, not just starters. Rolls up to team_year/all_time. [per user]
- [x] Future draft capital fix (updates on trade; 0 only if no picks in 3 years) — **4B**: replaced `_future_cap_from_traded` (only saw Sleeper's traded_picks snapshot → omitted un-traded own picks) with `_future_cap_held`, which walks the corrected pick-ownership ledger (own retained + acquired − traded away). team_week uses the week's date (updates on trade); team_year + tanking use the season-end (Feb 1) snapshot.
- [x] NFL-team roll-ups additive (rookie stats already correct — verify) — **4B verified**: team_year "Number of rookies started" = unique rookies (2 for AceMatthew 2024, not the weekly sum of 20); "Most number from same NFL team" rolls up as max. Correct, no change.
- [x] Cuffs rostered/started → unique players — **4D**: `Number of cuffs rostered/started` at team_year/all_time + league_year/all_time now count DISTINCT cuff players (via `_build_unique_cuff_counts` over Player ID), not summed player-weeks. team_week/league_week stay per-week counts.
- [x] Activated cuff = cuff becomes starter; injured player doesn't need to have started — **4D**: split into `_cuff_rostered_flag` (handcuff present: low scorer + injured/suspended better same-team/pos teammate, injured teammate need not have started) and player_week "Activated Cuff?" = rostered cuff AND the cuff STARTED. team_week rostered=Σ rostered flag, started=Σ activated.
- [x] Cuff at pickup relaxed (starter at any point in prev 3 weeks) — **4D**: `Cuff at time of pickup?` now true if the qualifying teammate was a STARTER in any of the pickup week + 2 prior weeks (was: pickup week only).
- [x] team_all_time: regroup Win % vs and Record vs columns by stat type (all Win % together, then all Record together) — **4E**: `_append_team_vs_columns` regroups for team-all-time only (team_year stays interleaved); all "Win % vs …" (fixed buckets then per-team) then all "Record vs …".
- [x] team_all_time: add 4 columns: Highest Win % vs a team, [opponent team name], Lowest Win % vs a team, [opponent team name] — **4E**: "Highest/Lowest Win % vs a team" + "Team for highest/lowest Win %" (opponents actually played only). Injected just before the Win% group.
- [ ] **3-part audit** (code / results / diff)

## Phase 4.5 — Workshop Luck (before Phase 5) ✅
- [x] Rebuilt Luck from scratch (the "G2" model — full derivation + 12-model experiment in `plan/LUCK_REWORK.md`). Weekly = result-surprise (outcome vs calibrated pregame talent + Bros/Sis, postseason-boosted) + closeness-gated scoring-variance (opp collapse / own pop) − heavy adversity + efficiency + nail-biter term. Season/all-time = plain SUM of weekly (no win% multiplier — calibrated pregame_p nets out winning). Retired the old multiplier-based formula + `_LUCK_WINPCT_BLEND`.
  - Scorecard: winner>loser 0.88; corr(Σ,win%) +0.18 (winning≠lucky); corr(Σ,WinVar) +0.56; adversity strongly −; 2025 plehv-beats-champion = top outlier; AceMatthew 2024 = 6th unluckiest season; Bros/Sis at extremes; postseason 1.55×; small margins gated in. Weights are tunable constants in `team_week_luck_formula`.
- [x] All-time luck aggregation fix — team_all_time luck was a raw SUM over every week, which let chronic adversity (a persistent roster trait) pile up unbounded (steven +7.1 / shmuel −6.9). Changed to the **MEAN of per-season luck totals**, renamed column **"Avg yearly luck"**. Ranking identical, spread 14.0→2.8, all-time now on a single-season scale + tenure-fair. Weekly model + team_year (sum of weekly) unchanged. Details in `plan/LUCK_REWORK.md`.

## Phase 5 — League sheets
**Sub-PR plan:** 5A schema/simple fixes (3,4,6,7,8) · 5B count semantics + hi/lo starters + trade window (1,2,5,9).

- [x] 🔍 # transactions formula trace + # trades (once per trade incl 3+team) — **5B**: league `Number of trades` now counts DISTINCT trade events (by timestamp) per period — once per trade regardless of #teams (was the per-team sum: 2024 137→67). # transactions left as-is (sum of team transactions is correct league-wide).
- [x] Position/NFL team/players rostered+started: league-wide unique; all-time/yearly = unique across period — **5B**: rookies started/rostered and "Number of NFL teams among starting/rostered players" on league_year/all_time now count DISTINCT players / NFL teams across the period (was weekly sum for rookies → 626, weekly max for NFL teams → 10). QB/WR/RB/TE counts were already unique.
- [x] Number of starting donuts column — **5A**: added to league_week/year/all_time (sum of team_week "Number of starter donuts").
- [x] Weekly starter turnover = league total (not average) — **5A**: league_week now SUMs team turnover (was mean).
- [x] All-time/yearly "highest/lowest starters" disambiguate — **5B**: added "Highest starter score" + "Lowest starter score" (max/min single-starter score league-wide) next to "Difference between highest and lowest starters" on league_week/year/all_time.
- [x] 🔍 league_week col O + league_year col S (UPST duplicate?) — **5A**: confirmed `UPST` == `Number of wins with pregame avg max PF from opponent`; dropped the descriptive duplicate, standardized on `UPST` across league_week/year/all_time.
- [x] 🔍 league_all_time "increase in points from previous week" — define or remove — **5A**: removed from league_all_time (week-over-week delta is meaningless all-time); kept on league_week/year.
- [x] 🔍 2022 wk 16-17 only 7 TEs started — **5A verified**: legit — toilet-bracket teams that didn't set a full lineup (plehv79 scored 45.4 in 2022 Toilet Semis, JacobRosenzweig in Toilet Trash). Not a rollup bug.
- [x] Weekly trades: offseason in wk-1 rollup only if within 7 days prior to Wk 1 — **5C**: per-week sheets keep "Number of trades", bucketing an offseason trade into Wk 1 only if within 7 days of kickoff. PLUS (user request) team_year/all_time + league_year/all_time replace "Number of trades" with **Offseason / Inseason / Total trades** (distinct trade events; offseason = before Sept 7 kickoff). Also redefined league "Difference between highest and lowest starters" = Highest − Lowest starter (league range) so the 5B hi/lo columns reconcile.
- [ ] **3-part audit** (code / results / diff)

## Phase 6 — Transactions
- [x] Same-day commissioner add+drop heuristic excludes from tx counts — **6B**: a transaction whose every player movement nets to zero on its own roster that day AND involves a commissioner action is a no-op correction → excluded from tx/trade counts AND from the transactions/trades detail. Covers commish add+drop, a team-drop the commish re-added, an add the commish immediately undid, and a commish-reversed trade (15 such commish washes in the data, e.g. LWebs53 2022-09-23 Abdullah/Burkhead).
- [x] Split link to next/previous (added player + dropped player); include trades — **6D**: transactions now have 4 link columns — next/previous for the ADDED player and the DROPPED player — each following that player's chain across teams AND trades, referenced as `#N` (transaction row) / `T#N` (trade row). (Trades.csv keeps its per-team chain; tanking-delta is 6E.)
- [x] # times picked up by this team includes trades; add # times dropped column — **6C**: `Number of times picked up by this team` now interleaves trade-ins with waiver/FA adds (chronological running count); added `Number of times dropped by this team` (incl. trades away), N/A on pure-pickup rows.
- [x] Tanking = change in tanking (right before vs right after) — **6E**: the transactions/trades `Tanking` column is now the MARGINAL change in the team's tanking score from that single move, holding all else constant — `(1/6)·Δage_term + (1/9)·Δfuture_cap`. PF/MaxPF terms cancel; age term recomputes the roster's "Team age including picks" with the added/dropped (or received/sent, incl. picks-as-future-rookies) entities swapped against the team-week roster age `A` and entity count `N`; future-capital term = round-weighted future picks received − sent (trades only). Positive = younger/more-picks (tank), negative = win-now.
- [x] 🔍 Player addition value never blank — **6A verified**: 0 blank/N-A rows in transactions.csv (already satisfied).
- [x] FAAB premium % column replaces FAAB % difference — **6A**: renamed to `FAAB premium %` = (winning_bid − runner_up) / winning_bid × 100 (normalized by bid size, bounded 0–100; was divided by runner-up).
- [x] KTC pick value at draft = Sept 1 snapshot — **6F**: "Change in pick value at draft time" now snapshots the pick's post-draft value at **Sept 1** of the pick's draft year (was Sept 5).
- [x] KTC future value dates — **6F** (+ follow-up): replaced the fixed Jan-5 ladder. **End of season** = the Monday after THIS season's fantasy championship game (next championship after the move; championship Monday = day after NFL wk-17 Sunday: 2021→Jan 3 '22, 2024→Dec 30 '24). **1 year later / 2 years later** = exactly 1 and 2 calendar years after the transaction/trade date itself (a fixed horizon from the move, not anchored to later championships). Applies to trades.csv + transactions.csv.
- [x] 🔍 KTC values audit (Ronald Jones / Josh Gordon as canary) — **6F**: verified the KTC engine is faithful to KTC. Build values match dynasty-daddy `sf_trade_value` (correct for this superflex league) **to the dollar** (Josh Gordon 61/61/14, Ronald Jones 1892/2392/6); date-aware NaN-before-existence handled (Gordon pre-Sept-2021 reinstatement). dynasty-daddy uses the verbatim KTC 0–9999 scale (top assets = 9999 today and historically), so values are genuine KTC — they read low only due to superflex non-QB deflation.
- [x] **3-part audit** (code / results / diff) — **Phase 6 wrap-up**: holistic sweep of transactions.csv + trades.csv. Schema matches catalog exactly (43 / 28 cols). All features verified: FAAB premium % ∈ [0,100], Player addition value 0 blank, # picked-up/dropped gated to Player Added/Dropped presence, KTC dates exact, tanking delta both-signed, link refs in range. **One bug found + fixed**: the 6D player-chain links bucketed every no-add row into a phantom `chains["nan"]` (pure-drop rows carry `Player Added`=NaN→`str()`="nan", which slipped past the `!= "N/A"` guard), so the added-player link columns were populated with garbage on all 362 no-add rows (and symmetrically the dropped-player links on no-drop rows). Fixed with a `_real_player()` guard — see fix PR.

## Phase 7 — Trades
- [ ] 🔍 Rows with both Assets received + sent blank — fix root cause
- [ ] FAAB-as-asset capture (FAAB tradeable)
- [ ] Enhanced Avg PPG (excludes injured/bye/suspended + includes future-draft-pick PPG)
- [ ] # teams involved in trade column
- [ ] Link to next transaction per asset
- [ ] Trade addition value never blank; Asset age difference never blank
- [ ] Avg PPG received includes draft-pick PPG after arrival
- [ ] Assets retained now / Assets traded away / Assets dropped to FA include relevant draft picks
- [ ] V2 trade addition value (Cuffs etc.)
- [ ] **3-part audit** (code / results / diff)

## Phase 8 — Pick history
- [ ] 🔍 Commissioner-moved over-fires — investigate
- [ ] **3-part audit** (code / results / diff)

## Phase 9 — Taxi / IR / suggestions
- [ ] Taxi columns: player_week Taxi?; player_year Weeks in taxi; player_all_time Weeks in taxi; team_week Players in taxi; team_year/all_time Unique players in taxi + Total taxi-player-weeks
- [ ] IR columns (Sleeper roster.reserve, NOT NFL injury designation): player_week IR slot?; player_year/all_time Weeks on IR; team_week Players on IR; team_year/all_time Unique players on IR + Total IR player-weeks
- [ ] Suggest 3-5 enhancement ideas (draft-class scorecard, schedule luck, trade equity at N years)
- [ ] **3-part audit** (code / results / diff)

## Phase 10 — Revisit league notes
- [ ] Survey league.metadata / settings / per-season text across Sleeper years; decide tracked vs manual overlay
- [ ] **3-part audit** (code / results / diff)

## Phase 11 — Formulas sheet rebuild
**Moved from Phase 2 per user — better done after Phases 2–10 settle the formulas they describe.**
- [ ] Every non-obvious column gets an entry
- [ ] xlsx styling (color, wrap text, group by sheet, hyperlinks)
- [ ] **3-part audit** (code / results / diff)

## Phase 12 — Duplicate-column sweep
- [ ] Scan all sheets for identical-valued columns; remove redundancy
- [ ] Document survivors in formulas sheet
- [ ] **3-part audit** (code / results / diff)

## Phase 12.5 — Formatting (TBD)
- [ ] TBD — reserved for output/xlsx formatting work (styling, column widths, number formats, conditional formatting, sheet polish). Scope when we get there.

## Phase 13 — ESPN 2020 backfill
- [ ] Scope when we get there
- [ ] **3-part audit** (code / results / diff)

## Phase 14 — In-season weekly digest email
**Trigger:** Tuesday 10am ET, in-season only (build runs first, then emails). Skip weeks with no completed games since last email.

**Delivery / recipients:** TBD (user will specify before phase starts).

**What to surface:**
- All-time top/bottom 5 rank changes (players): "Kyler Murray's −0.4 points passes JJ McCarthy for 4th lowest all-time."
- All-time team rank changes: "BROsenzweig passes Shmuel256 in Max PF for 3rd place all-time."
- Projected end-of-season ranks (linear extrapolation from current pace): "Oliverwkw is on pace for 4th-highest yearly hardship."

**Implementation outline:**
- Capture prior-week ranks snapshot (commit to repo or store as workflow artifact).
- Diff vs current week's ranks; produce a narrative list of crossings.
- HTML email template with sections: All-time leaderboard moves / Team all-time moves / On-pace projections.
- Cron-scheduled workflow with workflow_dispatch fallback for manual reruns.
- In-season gate: skip if current week is offseason (e.g. before Sleeper's week 1 or after week 17).

- [ ] **3-part audit** (code / results / diff)
