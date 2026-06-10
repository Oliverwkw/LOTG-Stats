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
- [x] 🔍 Rows with both Assets received + sent blank — fix root cause — **7A**: investigated all 8 both-blank rows (= 4 unique trades). Root cause = **FAAB-only trades** (Sleeper moved `waiver_budget` but no players/picks). Same root cause as the FAAB-as-asset item below.
- [x] FAAB-as-asset capture (FAAB tradeable) — **7A**: FAAB is now captured as a `$N FAAB` asset in Assets received/sent (summed per receiving roster from `waiver_budget`). **Net-zero swaps deleted**: trades where nothing changed hands (no players/picks, FAAB nets to zero per roster — symmetric $5↔$5 / $1↔$1 joke trades) are dropped from trades.csv and all trade counts. Two of the four blank trades were such swaps (deleted); the other two are real one-way FAAB transfers (now show `$2 FAAB` / `$5 FAAB`). FAAB excluded from player-chain links, # picked-up/dropped, and event-log tenure windows.
- [x] Enhanced Avg PPG (excludes injured/bye/suspended + includes future-draft-pick PPG) — **7D**: the Avg PPG metrics are built on the nflverse weekly game log, which only has rows for games actually played — so injured-inactive / bye / suspended weeks are already excluded (verified, documented). Drafted-pick PPG inclusion shipped via the item below.
- [x] # teams involved in trade column — **7B**: `Number of teams involved` = distinct teams in the deal (this team + counterparties), 2 for a normal swap, 3+ for multi-team. (Appended at the end of the trades column order for a clean catalog diff — reposition in the formatting phase if desired.)
- [x] Link to next transaction per asset — **7B**: replaced the per-team `Link to next/previous transaction` with `Link to next/previous transaction per asset` — a `;`-joined list aligned 1:1 with `Assets received`, each received player's next/prev event ref (`#N` tx / `T#N` trade) via the shared player chain; picks/FAAB carry `N/A`.
- [x] Trade addition value never blank; Asset age difference never blank — **7C**: both now always populated. `Trade addition value` already resolved one-sided player trades (missing side = 0); the only remaining blanks were pick-only / FAAB-only / never-played trades → now 0 (no on-team player value). `Asset difference in average age` was blank whenever one side had no aged asset (FAAB-only / empty give-away side) → now 0 (no measurable age differential; players + picks both carry ages). No two-sides-with-players trade was ever wrongly blank (verified).
- [x] Avg PPG received includes draft-pick PPG after arrival — **7D**: "Avg PPG of received players on team" now folds in the player drafted with each received pick, over their post-draft tenure on THIS team (draft ≈ late Aug of the pick year → next exit), but only when this team actually made the selection (pick_history Final Team == team). Picks flipped before the draft (288 of 478 received-pick instances) and not-yet-drafted future picks contribute nothing. Cascades into Difference of averages (adjusted) and Trade addition value. Default chosen (questions dismissed): exclude undrafted picks; window = post-draft on-team tenure.
- [x] Assets retained now / Assets traded away / Assets dropped to FA include relevant draft picks — **7C verified**: the V2 return-from-trades classifier already keys received assets as `("player", pid)` AND `("pick", meta)`, so picks flow into `Assets retained now` (114 rows) and `Assets traded away` (204 rows). `Assets dropped to FA` is correctly player-only (0 picks) — a draft pick can't be dropped to free agency (it's either traded or used in the draft). No change needed.
- [x] Points Added/Lost/Net (+ per-week avgs) on transactions & trades — **#200**: realized starter-points outcome of each move. Transactions: added player's started-week points; dropped player's real NFL points over those same weeks; net; + avgs. Trades: top-k "maximize" rule (received starters matched vs best players traded away each week); + avgs.
- [x] **Fix 3-team trades** (#201) — "Assets sent" must be ONLY what each team actually dropped (each asset appears once in received, once in sent across the deal). Currently Assets sent = union of every other team's received → 3+ team trades double-count (see 2023-06-12 01:21:38). Rebuild the sent side (+ `_drop_player_ids`/`_drop_pick_meta`/sent FAAB) from the real drops / pick previous-owner / FAAB sender.
- [x] **Fix transaction & trade links** (#202/#203) — each link must point to the next/previous transaction OR trade **chronologically** that includes the added/dropped player; many trade link cells aren't real hyperlinks. Make trade links real cross-sheet hyperlinks too.
- [x] **6 position-adjusted points-avg columns** — added `Avg points added/lost/net adjusted by position` (3 per sheet). Transactions scale by the added/dropped player's position; trades scale each asset by its own position (× league_starter_avg / pos_avg).
- [x] **"Length of tenure on team"** column on transactions (#204) (for the added player); **reorder** transactions + trades so all the Link columns are at the END of the sheet.
- [x] **Cuff at time of pickup** — the reference (handcuff) player must now STILL be rostered by the team at the pickup week (not just a starter in the prior 3 weeks). Logic + formulas wording fixed.
- [x] **Ridley/rosters** — pull nflverse WEEKLY rosters so players on a roster but with no stats (IR / suspended / PUP, e.g. Calvin Ridley 2022 on JAX) keep their real team; only true FA/retired get the "NFL" sentinel. Resolution: week stats → season stats → weekly roster → season roster → "NFL".
- [x] V2 trade addition value (Cuffs etc.) — **7E**. Trade addition value mirrors the transaction Player addition value: adj_diff × (1 + pct_starts) × (1 + pct_starts_inj) + CUFF_BONUS(5) **+ a pick-value term** (future picks valued with the tanking round weights, received−sent, × _TRADE_PICK_COEFF=20 so pick-heavy hauls register; applies even when adj_diff is None). [confirmed w/ user: mirror transaction V2; cuff def = same as transactions; pick value tunable coefficient]
- [x] **3-part audit** (code / results / diff) — **PASS** (see `plan/AUDIT_PHASE7_3PART.md`, PR #207): build clean; 40/40 spec invariants pass; same-snapshot diff confirms only intended trade/transaction columns + the expected NFL-team/availability/cuff cascade changed; `pick_history` untouched. Open cosmetic follow-ups: FAAB string lumping in one 3-team trade (low) — **fixed** (received FAAB now rendered per-sender), `trades` catalog duplicate columns (→ Phase 12).

## Phase 8 — Picks (rename from "pick history")
- [x] **Rename the sheet "pick history" → "picks"** (#8A): output sheet/CSV `pick_history.csv`→`picks.csv`, catalog header + stats_catalog.json key `Pick History`→`picks`, the `PH#N` link target sheet, README, and formulas references all updated. Internal frame/var names (`ph`, `FRAME_KEY`) unchanged.
- [x] 🔍 Commissioner-moved over-fires — **8G**: detection ran per-season BEFORE that season's own trades were folded into `pick_trade_events`, so every ordinary traded pick hit the "no events" branch and got flagged (172/288 fired). Fix: (1) rewrite the test to "is the snapshot owner reachable through ANY recorded trade hop?" (membership, not chain-END equality — robust to picks traded again in a later season), and (2) clear + rerun detection AFTER the season loop once the ledger is complete. True commissioner moves (off-platform reassignments the ledger never explains) still flag.
- [x] Each "Trade N" team cell hyperlinks to the corresponding trade row on the trades page — done in **8F** (xlsx hyperlink; best-effort alignment, commissioner-moved hops un-linked).
- [x] **"Length of tenure on team"** column (#8B): days the DRAFTED player stayed on the drafting team (Final Team), from the draft anchor (≈ Aug 28 of the pick year) to that player's next exit (or today). Mirrors the transactions tenure column. Placed right after "Player Picked".
- [ ] Add columns (split across sub-PRs):
  - [x] **8C** PPG/points cluster — `Avg PPG on team`, `Avg PPG on team adjusted by position`, **`Avg career PPG`, `Avg career PPG adjusted by position`** (split per user: on-team window AND whole-career, each position-adjusted; career = injury-adjusted nflverse games-played), `Points added`, `Avg points added`, `Avg points added adjusted by position`. N/A for unmade picks.
  - [x] **8D** KTC cluster (this PR) — `KTC on draft day`, `KTC at end of rookie year`, `KTC 1 / 2 / 5 years after draft day` (drafted player's 1QB KTC at each checkpoint; drafted players added to the KTC index; N/A for unmade/untracked/future-or-pre-April-2021 dates). Also: **removed the one-off `audit_phase7.yml` workflow** from the Actions list; added a weekly-audit note to Phase 14.
  - [x] **8E** draft/usage cluster — age when drafted; Player addition value (on-team baseline: on-team adj PPG × (1+%starts) × (1+inj %starts) + CUFF_BONUS); cuff when drafted; weeks before first start; number of starts before next transaction; % of starts made while rostered by drafting team; injury-adjusted % of starts. [user: removed "change in tanking" from this cluster]
  - [x] **8F** links — `Link to next transaction` (drafted player's first post-draft event) + `Link to previous transaction` (pick's last trade); each `Trade N` team cell hyperlinks (xlsx) to its trades-page row. Bridges player + pick chains through the draft row.
- [x] **All dataset times → US Eastern (DST-aware)** — folded into the 8C PR per user. The 3 timestamp columns (`transactions.Date`, `transactions."Date dropped/traded"`, `trades.Date`) convert UTC→America/New_York, formatted `YYYY-MM-DD HH:MM:SS` (no offset). Display-only, applied last (after all date logic), so internal comparisons stay on UTC.
- [ ] **3-part audit** (code / results / diff)

## Phase 9 — Taxi / IR / suggestions — **SCRAPPED (taxi/IR)**
- [~] ~~Taxi columns~~ / ~~IR columns~~ — **dropped: no weekly data available.** Sleeper exposes `roster.taxi`/`roster.reserve` only as a single roster SNAPSHOT (end-of-season per past year; live week for current). Transactions don't record IR/taxi slot moves, and matchup `players` includes IR/taxi players every week (no per-week flag). So genuine per-week taxi/IR history isn't reconstructable; only end-of-season membership is, which isn't worth the columns. (`Taxi-eligible` boolean in player_all_time, already shipped, stays.)
- [x] Suggested **25** enhancement ideas; user selected a batch → tracked in **Enhancements** below.

## Enhancements — user-selected from the 25-idea list (batched PRs, each gets the 3-part audit)
- [x] **PR A — Manager skill** (#234, merged): team_year + team_all_time `Drafting / Trading / Transaction skill` = **sample-size-shrunk mean O-Score**, `(n·mean + K·50)/(n+K)`, **K=5**. Drafting = picks made (Final Team); Trading = trades (Team); Transaction = transactions (Team). N/A for a (team, year) with no moves of a type. **KEPT AS-IS** — user decided against the value-vs-average revision ("rather keep it 0-100, assume it changes with time").
- [x] **PR B — Team cluster** (#235, merged; #236 revised + merged):
  - **All-play win %** (team_year + team_all_time) — each week scored vs every other team; pooled all-time. + **All-play win % minus Win %** (team_all_time uses `All time win %`): schedule luck, + = unlucky record, − = lucky.
  - **Loss from hardship?** (team_week T/F) + **Losses from hardship** (team_year/all_time count, nullable int). Definition (fix #1, #236): counterfactual lineup = team's ACTUAL STARTERS (real pts) + hurt would-be-starters who missed (subbed at their **starter-adjusted hardship**), best valid lineup via `compute_optimal_lineup` (bounded to slots, **healthy bench EXCLUDED** — only "what if hurt guys available", not optimal start/sit); flag a loss when that beats opponent actual PF. Hardship is injury+suspension, byes excluded.
  - **Luck**: each flagged week subtracts **0.25** (on top of the ADV term).
- [ ] **PR C — Player cluster** (player_year + player_all_time) — NEXT: consistency = scoring **volatility** (std-dev of started-week points), **floor** = lowest started-week points ever, **ceiling** = highest started-week points ever, **boom %** (% of started weeks ≥ 20), **bust %** (≤ 5); + **PAR** (points above positional replacement: player pts − replacement baseline = league-wide avg of the "last startable" player at that position per week; provide total + per-game). N/A for players who never started. [floor/ceiling are absolute min/max over STARTED weeks, not percentiles — no existing column dupes them]
- [x] **PR D — Awards + streaks** (branch `prd-awards-streaks`). FINAL design (supersedes earlier draft):
  - **New weekly team awards** (team_week flag + `Times …?` count on team_year/all): **One-man army?** (team whose top starter had the greatest share of its PF), **Most bench points?**, **Most injured?** (most injured players on roster, starters+bench).
  - **New player award** (player_week flag + `Times as Captain?` on player_year/all): **Captain?** (the one starter league-wide with the biggest single-team carry; Captain's team = that week's One-man army).
  - **Streaks live ONLY in the weekly sheets** (team_week / player_week) — none in year/all-time except the two season-grain ones below. A streak per weekly award + dedicated: team_week = Highest/Lowest score, Narrowest victory, Largest blowout, Most/Least efficient, Top half, One-man army, Most bench points, Most injured, Bottom half, 150+ PF, Standings leader, Quiet, **Win streak vs this opponent** (rivalry, vs that week's opp). player_week = one per player award (Player/QB/RB/WR/TE of week, Benchwarmer, Bench QB/RB/WR/TE, Highest/Lowest starter, Captain).
  - All streaks are **ALL-TIME (don't reset between seasons)**, EXCEPT Win/Loss which keep their existing within-season + cross-season running columns unchanged.
  - **TERMINAL ENCODING** (key design): each run shows its length ONLY on its final week (most recent if ongoing, else peak before reset); intermediate weeks = `"In Progress"`; non-streak weeks = `0`. Makes a descending sort give a clean top-N longest list (one row per streak; numbers sort above the text). Implemented via `_terminalize_streaks()`.
  - **Season-grain streaks** (season is their "week", so they sit on team_year, terminal-encoded): **Playoff appearance streak**, **Winning season streak**. No all-time version.
  - Validated locally (build clean; Captain↔One-man army 85=85; win/loss left running; rivalry top = shmuel 10-0 vs Jacob).
- [x] **PR E — in-season freshness audit** (branch `pre-in-season-freshness`). Report written to **`plan/IN_SEASON_FRESHNESS.md`** (no output columns change — report only). Confirmed source cadences (Sleeper live; nflverse weekly stats/rosters/injuries lag ~Tue–Wed; DynastyDaddy KTC 6h snapshot + immutable history; DynastyProcess infrequent). Findings → follow-up fixes below.
  - **Follow-up fix A (HIGHEST):** `last_completed_week` finalizes the trailing week as soon as any team has points>0, so the in-progress week (live Sleeper scores + nflverse not yet published) is treated as final. Gate it: only finalize a week when all matchups are final on both sides AND nflverse has that week (`nflverse_has_week`); else drop it. Fixes the latest-week errors in every weekly column + everything downstream, and resolves the false-injury risk (fix B).
  - **Follow-up fix B:** false `Injury?` from nflverse lag (gap-fill marks played-but-not-yet-published players injured). Mostly mitigated (bounded to last nflverse week, ≥1-active-game, no overwrite); fully resolved by fix A. Affected: Injury?/Hardship/SA-Hardship/Losses from hardship/Luck/Most injured?.
  - **Follow-up fix C:** standings/playoffs/champion/last-place/Result are provisional mid-season and `champion` defaults to the current leader (mislabels mid-season leader "Champion"). Gate these to completed seasons; N/A the in-progress season. Affects Record/Win% vs playoff/champion/last-place, Result, Week of playoff elimination, Tanking, current-season Playoff-appearance/Winning-season streak.
  - **Follow-up fix D (small):** O-Score + manager skill are provisional for current-season events; exclude current-season events from manager skill (or flag provisional) until the season ends.
  - **Follow-up fix E (optional, low):** recent-pick O-Score uses last KTC *checkpoint* (e.g. draft-day) not today's live value; add a current-KTC component.
  - No change needed: "to-date" tenure windows (correct by design, grow in-season) and Age (anchored to week date).
- Dropped from the batch: ⑨ asset lineage (already in trades sheet), ⑬ all-play *record* (win% only), ⑳ bench-blunder/blowout/nail-biter/toilet (already covered by max PF / margin / PF extremes), ㉕ projections (deferred to Phase 14).

## Phase 10 — Revisit league notes — **SCRAPPED**
- [~] ~~Survey league.metadata / settings / per-season text; decide tracked vs manual overlay~~ — **dropped per user.** The only league-notes use we wanted was the commissioner's per-player notes for the off-platform 2.09 / 5.0X picks; we got those a different way (detecting draft-day commissioner-forced adds → synthetic picks, PRs #230–#233).

## Phase 11 — Formulas sheet + full xlsx styling, hyperlinks & formatting
**Moved from Phase 2 per user — better done after Phases 2–10 settle the formulas they describe. Old Phase 12.5 (formatting) folded in here as 11C–11E.** Each sub-PR gets its own **3-part audit** (code / results / diff). Run sequentially (each builds on the prior).

- [ ] **11A — Formulas-sheet content completeness.** A `_ROWS` entry (`src/formulas.py`) for every NON-OBVIOUS output column (skip pure identity cols: Player/Team/Year/Week/Position/Points). ~80–100 new entries (e.g. Cuff adjusted difference, PPG starter-vs-bench diff, Brosenzweig/Sisenzweig, the weekly award flags, Taxi-eligible, the new awards/streaks/PAR cluster). Add a build-time assert that flags any output column with no Formulas entry so coverage can't silently drift. (Pure docs → diff = formulas.csv only.)
- [ ] **11B — Formulas-sheet styling + color-led organization.** Bold/filled header row; wrap-text on Formula/Notes; per-column widths; group/section the rows by their `Sheet` value with **color-coded bands per sheet** so it reads as a reference. (xlsx-only; CSV unchanged.)
- [ ] **11C — Style ALL other sheets.** Reorder columns into a sensible reading order, **color-code** (headers + per-section/topic banding, consistent palette across sheets), header styling, freeze panes, number formats, wrap where useful. Also tame the **trades per-asset link columns** (the xlsx explodes them into one col per received asset, K≈15 → ~30 mostly-empty cols; `#203`): cap/scroll slots, hide empties, narrow widths.
- [ ] **11D — Hyperlinks.** **Player-name hyperlinks**: every single-name cell (`Player`, `Player Picked`, `Player Added`/`Dropped`) links to that player's `player_all_time` row (needs a name→row anchor map). Exception: per-week player references (`Reference player name`, best-startable/worst-benchable refs) link to the relevant **player_week** row instead. Decide trades multi-name list cells (xlsx = one link per cell: leave to the existing per-asset event links, or explode). (xlsx-only.)
- [ ] **11E — General formatting sweep for max usability.** Final polish pass across the whole workbook: conditional formatting, alignment, consistent number/percent formats, sheet/tab order & colors, anything that improves day-to-day usability.

## Phase 12 — Large-scale full-dataset audit
**Upgraded to a deep, end-to-end correctness audit of the entire dataset. Reusable
9-part format lives in `plan/AUDIT_PHASE12.md`; first-pass findings + the 55-improvement
list in `plan/AUDIT_PHASE12_FINDINGS.md`. Flow: implement the queue below (with periodic
3-part audits per run), THEN re-run the full 9-part battery until all 9 parts are clean.**

### 9-part audit — first pass complete
- [x] First full 9-part run: dataset largely clean (Parts 8/9 clean, 54/55 edge cases pass, 8/9 rollups reconcile). 8 bugs + 55-improvement list produced.
- [x] Reconciliation logic committed as durable guard — `tests/test_cross_sheet_reconciliation.py` (1 known-open: player_all #tx = Σ player_year, = Bug #1).
- [ ] **Re-run the full 9-part battery until ALL 9 parts come back clean** (after the queue below).

### Bugs (batched fixes; each gets a 3-part audit)
- [x] **#2 Age=0 → real age** on padded tx-only player_year rows — computed from birth_date at Nov 1 of the year (user: "Age should never be 0").
- [x] **#3 PPG starter/bench (+adjusted) = 0 → N/A** for never-started/never-benched — added the 5 cols to `_preserve_na`.
- [x] **#5 Re-score from PPR → actual league scoring** — `_league_score` + COMPLETE `_LEAGUE_SCORE_MAP`/`_BONUS` (all Sleeper keys → nflverse cols, incl. league pass-int −2, distinct fumble rules, st_td, IDP, kicking). Auto-detect log fires on ANY scoring-settings change (`_prev_scoring_sig`). 98.6% exact; residuals are nflverse-vs-Sleeper RAW DATA diffs, not formula gaps. Full-season blend uses Sleeper pts for rostered weeks. (Audited #256 — tiny ripple, CLEAN.)
- [x] **#8 Round Luck at output** (round(6)) — kills the ~1e-16 nondeterminism.
- [x] **3 new team_all_time columns** (#257): Number of playoff appearances / championship appearances (Champion or runner-up) / last place finishes. Placed right after `Championships`; in-progress 2026 not counted. **Audit follow-up #258**: the audit found last-place finishes were built from `last_place_by_season` (standings[-1]) and disagreed with the displayed `Result`'s "8th"; rebuilt all three counts from `season_finish` so they're mutually + Result-consistent (Jacob 2→3, stevenb 0→1, plehv/shmuel 1→0; total still 5).
- [x] **#1 player_year missing rows for tx-only (player, season)** (#259, stacked on #258) — `player_all #tx` ≠ Σ player_year (114 off). Two gaps fixed by extending the tx-only pad: (a) offseason-only moves bucketed under FY (Y-1) by `_fy_for_date` → `_season_leadin_tenure` recovers the lead-in window (live 2026 AND historical, e.g. Eskridge 2022); (b) initial-roster vets dropped with no recorded 'add' (no tenure stint) → `tx_team_events_by_pair` uses the real move's `Team`. Reconciles exactly (0 off); the known-open guard is now a **hard assert**. Padded rows carry real Age/Top-Last team/Number of teams.
- [x] **#6 Trades next/previous links** (#261, merged + audited CLEAN) — every non-FAAB per-asset cell now links: picks fall back to their picks-sheet home row (`pick_home_phref`), players to their `player_all_time` row (xlsx). FAAB stays unlinked. Only the `2021 2.??` cell remained (undetermined slot) → fixed by #262.
- [x] **2021 rookie draft Original Team** (#262, corrected by #263) — Sleeper mislabeled the linear 2021 rookie draft as snake, so R2/R4 `Original Team` read off the reversed even-round draft_slot (repeats: LWebs53×2 etc.) and `2021 2.??` never resolved. Fix: take Original Team from the pick's NUMBER **position** in the round → stevenb123, Jacob, AceMatthew, BRO, plehv79, LWebs53, Oliverwkw, shmuel256 (8 distinct, no repeats). **#263 correction:** #262 also wrongly linearized the pick number/player (showed 2.01=Carter); the number+player are keyed by Sleeper's draft_slot and were already right (2.01 Justin Fields … 2.08 Michael Carter) — restored. Player↔Number + Final-Team-per-player unchanged from pre-#262. Commissioner moves re-determined from the chains (now aligned to Sleeper's pick identity): 10 untracked startup hops flagged True, real ledger trade 2.08 (shmuel256→LWebs53→M. Carter) stays False. Closes #261's lone `2.??` cell. Phase 13 ESPN backfill can refine these chains into explicit trade legs.
- [~] **#4 Unused/leftover FAAB column — DROPPED** per user: Sleeper budgets mix 120/125 + per-team rollover + 20-FAAB pick purchases from leftover FAAB; "unless this can all be tracked with certainty, not estimates, don't make this column." Reverted.
- [x] **#7 Wrap all cells on all sheets** — data cells wrap on every sheet (audited #255, CLEAN).

### Selected improvements (from the 55 list — user-chosen; build BEFORE the next full 9-part audit, with periodic 3-part audits)
- [ ] **9** Clutch index — **team_all_time only** (reg-season vs playoff PF/win% delta).
- [ ] **10** Consistency rank — **position-adjusted** league-wide percentile of volatility/floor/ceiling.
- [ ] **15** Trade tree / lineage string — one readable "2021 1.04 → … → 2026 1st" per current asset.
- [ ] **16** → **"3-year retention rate"** — % of draft capital still on roster after **N=3** years; **exclude returners**; **team_year + team_all_time**; measured at **start-of-year**.
- [ ] **26** Sparklines for weekly PF / player PPG trends.
- [ ] **27** Hyperlink team names → team_all_time — **opponent / counterparty links only**.
- [ ] **28** Hyperlink pick labels in trades → picks sheet.
- [ ] **30** Conditional highlight of all-time records (highs/lows) in their cells.
- [ ] **32** Tooltip/comment on cryptic headers pulling the Formulas definition.
- [ ] **33** Color "In Progress" streak cells subtly so active runs stand out.
- [ ] **34** Two-tone bands alternating within topic groups (**subtle**) for wide sheets.
- [ ] **35** Backfill missing birth_dates from a secondary source (mostly handled by Bug #2; finish coverage).
- [ ] **36** Position-switcher audit (Taysom Hill etc.) — confirm weekly position.
- [ ] **37** NFL-team-per-week validation vs schedule for traded players.
- [ ] **38** Dedup near-identical name variants ("AJ" vs "A.J.") across sources.
- [ ] **39** Confidence flag on KTC values sourced from sparse pre-2021 history.
- [ ] **40** Cross-check Sleeper points vs nflverse fantasy points; flag divergences — **effectively folded into Bug #5**; confirm/close.
- [ ] **41** Injury-tracker coverage report once 2026 data lands (PR E follow-up).

### Infra (assistant's judgment — selected)
- [ ] **42** Round all float outputs deterministically (extend the Luck fix everywhere).
- [ ] **43** Promote the audit battery to committed tests (reconciliation done; add sanity-range + N/A-vs-0 + edge-case suites).
- [ ] **45** Build-time data-quality log → emit sanity-range/anomaly summary into build_debug.log every run.
- [ ] **49** CI step running the test suite (coverage + reconciliation + freshness) on every build.

**Skipped from the 55:** 44/46/47/48/50, and nothing from section E except the already-planned Phase 14 digest email.

- [ ] **3-part audit** per fix PR, then the full **9-part audit re-run until clean**.

## Phase 13 — ESPN 2020 backfill
- [ ] Scope when we get there
- [ ] **Off-platform pick-trade backfill:** try to manually determine and add all 1st- and 2nd-round pick trades that happened OFF-platform (pre-Sleeper / side deals) so trade metrics (KTC won/lost, retro grades, pick-vs-player outcomes, manager Trading skill) are balanced and not missing legs.
- [ ] **Trades can no longer be an asset start point:** after this backfill, re-audit the trades-sheet `Link to previous transaction per asset` — a trade must never be an asset's origin (every first-trade `previous`=N/A endpoint must chain back to the earlier draft/acquisition). See the Phase 12 bug #6 note.
- [ ] **Initial-roster vets' history origin (71 players):** these veterans were placed on 2021 startup rosters but were NOT in the recorded vet draft and never added as FA, so their asset-history hover-comment currently begins mid-stream at their first trade instead of an "originally …" origin line (every other comment starts with the pick/FA origin). They have no startup-draft pick to seed from, and `player_tenures` can't see the initial stint (no `add` event → the pre-trade stint is skipped). Once ESPN 2020 + the off-platform startup data lands we can assign each an "originally on \_\_\_'s 2021 startup roster" origin. Full list saved at `plan/notes/initial_roster_vets_2021.txt`. Detect them the same way: a player_all_time comment whose first line is neither `… — originally …` nor an `added by/dropped by` line.
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

**Also schedule a weekly automated audit** (alongside the digest): run the 3-part audit harness against the latest build on a weekly cron, surface any UNEXPECTED diffs / schema breaks / non-2026 build errors (e.g. email or log them), so regressions from data drift or upstream-source changes are caught without a manual pass. Reuse the audit methodology; workflow_dispatch fallback for ad-hoc runs.

- [ ] **3-part audit** (code / results / diff)
