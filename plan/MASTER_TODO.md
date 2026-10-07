# LOTG-Stats Master TODO

**Workflow per phase:**
1. PR opened
2. User merges + runs build
3. Claude runs **3-part audit** (see below)
4. Iterate until all three parts pass
5. Mark phase complete; move to next

**3-part audit (MANDATORY after every PR):**

> **Build source (MANDATORY — do NOT get this wrong):** the audit ALWAYS uses the
> real **GitHub Actions build artifacts** — the `LOTG_outputs` artifact from the
> post-merge build run vs. the artifact from the specified baseline run (e.g.
> "diff against 412" = CI run #412's artifact). **NEVER run `scripts/offline_build.py`
> as the audit source of truth.** The offline build targets a different config
> (2025 league, `min_season 2019`/`max_season 2025`, KTC unreachable → N/A) and
> different data than the live CI build, so its CSVs do not match the shipped
> outputs and cannot validate them. `offline_build.py` is only a local dev
> smoke-test that the code executes — it is not an audit input.
>
> If the CI artifacts can't be downloaded in-session (e.g. raw GitHub artifact
> API returns "GitHub access is not enabled for this session — an org admin must
> connect the Claude GitHub App", and the GitHub MCP exposes no artifact-download
> tool), **report the blocker and request the artifacts** (or ask an admin to
> connect the app / have the workflow commit exports) — do NOT substitute a local
> offline build.

1. **Code-based audit** — build runs cleanly, expected columns exist, schema matches, no errors in build_debug.log.
2. **Results-based audit** — for each change in the PR spec, derive **≥5 concrete verification cases** that the spec was actually implemented correctly. e.g. spec says "Last team uses fantasy year, in-season only" → find a player whose 2024 offseason trade should NOT override their 2023 Last team, and verify the cell holds the season-ending team. Cases must come from the change spec — not from comparing to the prior build.
3. **Diff-based audit** — diff sweep of the post-merge CI build's CSVs against the baseline CI run's CSVs (sorted by canonical keys) to confirm nothing *else* changed. Flag any non-intended sheet/column diff as UNEXPECTED.

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
- [x] Hardship redefined per spec; NFLverse backfill for early-2021 + new pickups
- [x] 🔍 Investigate 2021 wk 1-2 hardship=0 with 23/30 injuries
- [x] Starter-adjusted hardship column next to every hardship column
- [x] Starter injury count column in league_week
- [x] Luck rebuild; audit distribution; iterate weights
- [x] **3-part audit** (code / results / diff)

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
- [x] **3-part audit** (code / results / diff)

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
- [x] **3-part audit** (code / results / diff)

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
- [x] Add columns (split across sub-PRs):
  - [x] **8C** PPG/points cluster — `Avg PPG on team`, `Avg PPG on team adjusted by position`, **`Avg career PPG`, `Avg career PPG adjusted by position`** (split per user: on-team window AND whole-career, each position-adjusted; career = injury-adjusted nflverse games-played), `Points added`, `Avg points added`, `Avg points added adjusted by position`. N/A for unmade picks.
  - [x] **8D** KTC cluster (this PR) — `KTC on draft day`, `KTC at end of rookie year`, `KTC 1 / 2 / 5 years after draft day` (drafted player's 1QB KTC at each checkpoint; drafted players added to the KTC index; N/A for unmade/untracked/future-or-pre-April-2021 dates). Also: **removed the one-off `audit_phase7.yml` workflow** from the Actions list; added a weekly-audit note to Phase 14.
  - [x] **8E** draft/usage cluster — age when drafted; Player addition value (on-team baseline: on-team adj PPG × (1+%starts) × (1+inj %starts) + CUFF_BONUS); cuff when drafted; weeks before first start; number of starts before next transaction; % of starts made while rostered by drafting team; injury-adjusted % of starts. [user: removed "change in tanking" from this cluster]
  - [x] **8F** links — `Link to next transaction` (drafted player's first post-draft event) + `Link to previous transaction` (pick's last trade); each `Trade N` team cell hyperlinks (xlsx) to its trades-page row. Bridges player + pick chains through the draft row.
- [x] **All dataset times → US Eastern (DST-aware)** — folded into the 8C PR per user. The 3 timestamp columns (`transactions.Date`, `transactions."Date dropped/traded"`, `trades.Date`) convert UTC→America/New_York, formatted `YYYY-MM-DD HH:MM:SS` (no offset). Display-only, applied last (after all date logic), so internal comparisons stay on UTC.
- [x] **3-part audit** (code / results / diff)

## Phase 9 — Taxi / IR / suggestions — **SCRAPPED (taxi/IR)**
- [~] ~~Taxi columns~~ / ~~IR columns~~ — **dropped: no weekly data available.** Sleeper exposes `roster.taxi`/`roster.reserve` only as a single roster SNAPSHOT (end-of-season per past year; live week for current). Transactions don't record IR/taxi slot moves, and matchup `players` includes IR/taxi players every week (no per-week flag). So genuine per-week taxi/IR history isn't reconstructable; only end-of-season membership is, which isn't worth the columns. (`Taxi-eligible` boolean in player_all_time, already shipped, stays.)
- [x] Suggested **25** enhancement ideas; user selected a batch → tracked in **Enhancements** below.

## Enhancements — user-selected from the 25-idea list (batched PRs, each gets the 3-part audit)
- [x] **PR A — Manager skill** (#234, merged): team_year + team_all_time `Drafting / Trading / Transaction skill` = **sample-size-shrunk mean O-Score**, `(n·mean + K·50)/(n+K)`, **K=5**. Drafting = picks made (Final Team); Trading = trades (Team); Transaction = transactions (Team). N/A for a (team, year) with no moves of a type. **KEPT AS-IS** — user decided against the value-vs-average revision ("rather keep it 0-100, assume it changes with time").
- [x] **PR B — Team cluster** (#235, merged; #236 revised + merged):
  - **All-play win %** (team_year + team_all_time) — each week scored vs every other team; pooled all-time. + **All-play win % minus Win %** (team_all_time uses `All time win %`): schedule luck, + = unlucky record, − = lucky.
  - **Loss from hardship?** (team_week T/F) + **Losses from hardship** (team_year/all_time count, nullable int). Definition (fix #1, #236): counterfactual lineup = team's ACTUAL STARTERS (real pts) + hurt would-be-starters who missed (subbed at their **starter-adjusted hardship**), best valid lineup via `compute_optimal_lineup` (bounded to slots, **healthy bench EXCLUDED** — only "what if hurt guys available", not optimal start/sit); flag a loss when that beats opponent actual PF. Hardship is injury+suspension, byes excluded.
  - **Luck**: each flagged week subtracts **0.25** (on top of the ADV term).
- [x] **PR C — Player cluster** (player_year + player_all_time) — NEXT: consistency = scoring **volatility** (std-dev of started-week points), **floor** = lowest started-week points ever, **ceiling** = highest started-week points ever, **boom %** (% of started weeks ≥ 20), **bust %** (≤ 5); + **PAR** (points above positional replacement: player pts − replacement baseline = league-wide avg of the "last startable" player at that position per week; provide total + per-game). N/A for players who never started. [floor/ceiling are absolute min/max over STARTED weeks, not percentiles — no existing column dupes them]
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

- [x] **11A — Formulas-sheet content completeness.** A `_ROWS` entry (`src/formulas.py`) for every NON-OBVIOUS output column (skip pure identity cols: Player/Team/Year/Week/Position/Points). ~80–100 new entries (e.g. Cuff adjusted difference, PPG starter-vs-bench diff, Brosenzweig/Sisenzweig, the weekly award flags, Taxi-eligible, the new awards/streaks/PAR cluster). Add a build-time assert that flags any output column with no Formulas entry so coverage can't silently drift. (Pure docs → diff = formulas.csv only.)
- [x] **11B — Formulas-sheet styling + color-led organization.** Bold/filled header row; wrap-text on Formula/Notes; per-column widths; group/section the rows by their `Sheet` value with **color-coded bands per sheet** so it reads as a reference. (xlsx-only; CSV unchanged.)
- [x] **11C — Style ALL other sheets.** Reorder columns into a sensible reading order, **color-code** (headers + per-section/topic banding, consistent palette across sheets), header styling, freeze panes, number formats, wrap where useful. Also tame the **trades per-asset link columns** (the xlsx explodes them into one col per received asset, K≈15 → ~30 mostly-empty cols; `#203`): cap/scroll slots, hide empties, narrow widths.
- [x] **11D — Hyperlinks.** **Player-name hyperlinks**: every single-name cell (`Player`, `Player Picked`, `Player Added`/`Dropped`) links to that player's `player_all_time` row (needs a name→row anchor map). Exception: per-week player references (`Reference player name`, best-startable/worst-benchable refs) link to the relevant **player_week** row instead. Decide trades multi-name list cells (xlsx = one link per cell: leave to the existing per-asset event links, or explode). (xlsx-only.)
- [x] **11E — General formatting sweep for max usability.** Final polish pass across the whole workbook: conditional formatting, alignment, consistent number/percent formats, sheet/tab order & colors, anything that improves day-to-day usability.

## Phase 12 — Large-scale full-dataset audit ✅
**Upgraded to a deep, end-to-end correctness audit of the entire dataset. Reusable
9-part format lives in `plan/AUDIT_PHASE12.md`; first-pass findings + the 55-improvement
list in `plan/AUDIT_PHASE12_FINDINGS.md`. Flow: implement the queue below (with periodic
3-part audits per run), THEN re-run the full 9-part battery until all 9 parts are clean.**

### 9-part audit — first pass complete
- [x] First full 9-part run: dataset largely clean (Parts 8/9 clean, 54/55 edge cases pass, 8/9 rollups reconcile). 8 bugs + 55-improvement list produced.
- [x] Reconciliation logic committed as durable guard — `tests/test_cross_sheet_reconciliation.py` (1 known-open: player_all #tx = Σ player_year, = Bug #1).
- [x] **Re-run the full 9-part battery until ALL 9 parts come back clean** — runs 2 (#283) and 3 (`plan/AUDIT_PHASE12_FINDINGS_RUN3.md`) both CLEAN on data correctness. Run-3 fixes: F1 docs / F2 Playoff-tiebreaker / F5 league_week first-week N/A (#288), F6 team NFL-teams-among distinct (#289). Cross-type sweep (every fix-class from runs 1-3) came back clean. Deferred: F3 → Phase 13, F4 (float-noise) + F7 (NFL sentinel) won't-fix per user.

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
- [x] **9** Clutch index — DONE: team_all_time `Playoff PF minus regular-season PF` + `Playoff win % minus regular-season win %` (reg-vs-playoff delta).
- [x] **10** Consistency rank — DONE: `Consistency / Floor / Ceiling percentile` (player_year), confirmed **position-adjusted** (ranked within season, position).
- [x] **15** Trade tree / lineage string — DONE **via the pick hover-comments** (full "originally …'s pick → commissioner moved → drafted → traded to … → …" lineage per asset). No separate column, per user.
- [x] **16** **"3-year retention rate"** — DONE: % of draft capital still on roster after N=3 years, team_year + team_all_time (measured start-of-year; audited run 3, populated 2021/2022, N/A once 3yr-later is in-progress).
- [~] **26** Sparklines for weekly PF / player PPG trends — **SCRAPPED** per user.
- [x] **27** Hyperlink team names → team_all_time (opponent/counterparty) — DONE (i7 #277, context-aware team-name hyperlinks).
- [x] **28** Hyperlink pick labels in trades → picks sheet — DONE (per-asset pick links fall back to the picks-sheet home row via `pick_home_phref`/PH# refs, #261).
- [x] **30** Conditional highlight of all-time records (highs/lows) — DONE (i7 #278/#279 conditional-formatting batch).
- [x] **32** Tooltip/comment on cryptic headers pulling the Formulas definition — DONE (i7 #280/#281 sheet-aware header tooltips).
- [x] **33** Color "In Progress" streak cells — DONE (i7 #279 light-green In-Progress).
- [x] **34** Two-tone bands within topic groups (subtle) for wide sheets — DONE (i7 #278 banding).
- [x] **35** Backfill missing birth_dates — DONE: 0/201 drafted picks have N/A `Age when drafted` (96 N/A are future picks). Bug #2 finished it.
- [x] **36** Position-switcher audit — HANDLED: one stable position/player, 0 per-week variance; Taysom Hill→TE, Travis Hunter→WR sensible.
- [x] **37** NFL-team-per-week — DONE: `NFL team` 0/18,744 N/A, correctly reflects mid-season NFL trades (Adams LV→NYJ, Hopkins KC/TEN, Diggs→HOU→NE).
- [x] **38** Dedup name variants — DONE: 0 normalized-name collisions (players keyed by Sleeper pid).
- [~] **39** KTC confidence flag — SKIPPED (low payoff): KTC 99.5% covered (1/201 picks N/A); build log already reports the win-impact gap. Revisit only if sparse-history issue surfaces.
- [x] **40** Sleeper-vs-nflverse points — DONE (folded into Bug #5: `Points (full season)`).
- [x] **41** Injury-tracker coverage report — DEFERRED to Phase 14 (needs 2026 in-season data).

### Infra (assistant's judgment — selected)
- [~] **42** Round all float outputs deterministically — **WON'T FIX** per user (= run-3 F4; the ~1e-16 noise in team_year/all aggregates is masked in the xlsx by the `0.00` number format).
- [~] **43** Promote the audit battery to committed tests — reconciliation + sanity-range + freshness + formulas-coverage suites committed (`tests/`); the extra **N/A-vs-0 + edge-case suites SCRAPPED** per user.
- [x] **45** Build-time data-quality log — DONE (`src/lotg.py:14965`; emits sanity/anomaly summary each build).
- [x] **49** CI step running the test suite — DONE (`build.yml` "Run test suite against the build" runs `pytest tests/` every build).

**Skipped from the 55:** 44/46/47/48/50, and nothing from section E except the already-planned Phase 14 digest email.

- [x] **3-part audit** per fix PR, then the full **9-part audit re-run until clean** — complete (runs 1-3; every fix PR 3-part-audited, full battery re-run clean).

**✅ Phase 12 COMPLETE.** Only intentionally-deferred items remain: F3 → Phase 13; F4/#42 (float-noise) and F7 (NFL sentinel) won't-fix; #26 sparklines + #43 extra test suites scrapped; #41 injury-tracker → Phase 14.

## Phase 13 — ESPN 2020 backfill
**Goal:** integrate the league's first season (2020, played on ESPN leagueId 34086 before
Sleeper) into the dataset, filling every column to the max. Source notes + verified
teamId→manager crosswalk: `plan/notes/espn_2020_backfill.md`. 2020 rules: 8 teams, 16-round
[actually 19-round] snake superflex startup, 16-week season, playoffs **wks 15–16**, **no
FAAB**, picks tradeable **off-platform only**, KTC has no pre-Aug-2021 history.

The user's 7-step plan (with status):
- [x] **1. Scope what ESPN data fills which columns** — done (`espn_2020_backfill.md`).
- [x] **2. Pull the data once (hardcoded) + load it.** Dump captured (`data/espn_2020_raw/`, leagueId 34086, commissioner cookies); loader + Sleeper-shape adapter built & validated (`src/espn_2020.py`, PR #291); wired into `lotg.py` as the earliest season and shipped to CI. Build evidence: 2020 present across all sheets (team_week 128 rows, player_week 2632, trades 24, 152 startup picks) — runs 372+ through the run-397 build.
- [x] **3. Columns that must treat ESPN/2020 differently** — done & verified in build: `Startup draft players remaining` recomputed off 2020-startup pick ids (Phase-12 F3 fixed); 2020 FAAB columns `0→N/A` (264 team-weeks, confirmed in the run 397-vs-395 diff); "Number of bids" N/A for 2020; Semifinal +5 homefield gated off for 2020 (Bug B); week-17 playoff weeks. (2020 draft-day KTC stays N/A by design; "KTC at end of rookie year" carries a real value because most startup players' rookie year is post-2021.)
- [x] **4. KTC / nflverse / other backfill hole-fix** — done. Cross-era ripples confirmed: 2021 wk1 "from previous week"/turnover now populates; 2020 wk1 is the new N/A boundary; 3-yr retention / future-pick windows span 2020→2023. **Hardship cross-era confirm closed** — see the post-#291 findings block below.
- [x] **5. Confirm initial-roster vets' origin + perfect asset tracing** — done. 2020 startup picks (152) serve as the origin for the 71 initial-roster vets' chains; no-teleport + asset-chain link integrity re-verified CLEAN across audit rounds 5–12 (`AUDIT_PHASE13_ROUND*_PARTSGH.md`) and guarded by `tests/test_pick_chain_links.py`.
- [x] **6. Off-platform pick-trade reconstruction** — done via the commissioner-ledger layer (PR #314, "fill in commissioner-moved pick trades from the league ledger"). Build evidence: 24 trades in 2020 incl. the off-platform pick legs; Trading-skill / pick-vs-player metrics balanced.
- [x] **7. Comprehensive 10-part audit** — done. The full battery ran across 12 rounds (`plan/AUDIT_PHASE13_ROUND{5..12}_PARTS{AB,CD,EF,GH,IJ}.md` + the round-1 10-part `AUDIT_PHASE13_ROUND1*`/`AUDIT_PHASE13_10PART_*` set) plus the closing 3-part `plan/AUDIT_PHASE13_RUN397_vs_395.md`. Bugs found & fixed: KTC `_ktc_idx` UnboundLocalError robustness; "Amount of FAAB spent" 0.0→N/A pre-2022; "Number of bids" 0/1→N/A for 2020; player_year/player_all_time pid-collision duplicate-name rows; Weeks-between-pickup-and-start date-string compare; build-determinism tied-timestamp sort; 2020→2021 platform-seam teleport; commissioner-wash deleting real same-day-reversed trades. Final round (run 397) is CLEAN, no source change; the run 397-vs-395 diff confirms every change is intended (0 regressions). False positives investigated: 71-vets-untraceable; Startup-draft-players-remaining-always-0.

### Post-#291 integration audit (CI build run 27660107808) — findings
2020 **matchups/scores integrated correctly**: player_week (2632 rows), team_week (128 = 8×16), team_year (8), 16 weeks; PF=Σstarters reconciles; Record W=ΣWin? exact. Cross-era ripples confirmed expected (2021 wk1 from-prev now populates; career-baseline `Change from career` & all-time streaks now include 2020; Luck 670-row diff is just the deferred F4 float-noise, max Δ 0.04). Fixes:
- [x] **Bug A — 2020 transactions (374) + trades (13) missing.** Adapter set `created: None`; the build's date gate dropped them. FIXED: `created` = ESPN proposedDate epoch ms (moves) / email-date epoch (trades).
- [x] **Bug B — Semifinal +5 homefield applied to 2020.** Gated the bonus to seasons ≥ 2021 (`lotg.py` ~4014); 2020 keeps the Semifinal/Toilet labels but no +5.
- [x] **Bug C / FEATURE — 2020 startup draft (152 picks) absent from the picks sheet** — DONE. The `>5 rounds` exclusion was relaxed for startup drafts; build now emits **152 picks with `Year = startup`** (their own O-Score universe), serving as the origin for the 71 vets' chains. Verified present in the run-397 build.
- [x] **Confirm Hardship 16-row 2021 change** (max Δ 7.8) is the legit cross-era effect (expected-if-healthy baselines now include 2020), not a regression — **CONFIRMED**. Diffed Hardship across the exact 2020-integration boundary (build run 371 `54fd41fa`, 0 rows of 2020 → run 372 `e68b8890`, 128 rows of 2020 — the only difference between the two builds). Result: **exactly 16 rows changed, all in 2021, all on one team (JacobRosenzweig), a constant +7.82 every week, and 0 changes in 2022+.** A flat per-week +7.82 for a single team = that team's season-long injured stash (Josh Doctson, injured 16/17 wks, 0 pts all year) gaining a 2020-anchored expected-if-healthy baseline where pre-integration there was none. Monotonic increase, bounded at exactly the predicted 7.82, no spillover elsewhere → cross-era baseline extension, not a regression. (Independently, Hardship is byte-stable across runs 395↔397, so no ongoing drift.)

### ⭐ O-Score addition for startup picks — ✅ DONE
The **2020 ESPN startup draft** is in the picks sheet: the `>5 rounds` exclusion was relaxed for
startup drafts, the 152 startup picks carry `Year = startup` and their own O-Score universe (not
pooled with rookie picks), and they serve as the **origin** for the 71 initial-roster vets'
asset-history chains. Confirmed in the run-397 build (152 `startup` rows). The chain +
reconciliation parts of the 10-part audit passed on this basis.

---

**✅ Phase 13 COMPLETE** (merged: #291/#292 integration, #314 off-platform pick trades, #318
startup-N/A, **#319** the 12-round audit-fix batch). All 7 steps done; the post-#291 findings
(Bugs A/B/C + the Hardship cross-era confirm) are all closed. The closing run 397-vs-395 3-part
audit (`plan/AUDIT_PHASE13_RUN397_vs_395.md`) found 0 regressions. **Clear to start Phase 14.**

### Phase 13 follow-up 2 — the flat Sept 7 anchor, everywhere else
Write-up in `plan/notes/SEASON_CALENDAR_ANCHORS.md`. From the over-inclusive sweep the user
asked for after the startup chain.
- [x] **All 17 flat `date(season, 9, 7)` anchors retired** for `_week_thursday()` /
  `_season_week_of()`. Real kickoff is the Thursday after Labor Day and moves six days across
  the seasons on record, so a 7-day week bucket was up to 3 days out: **26 of 268 distinct
  trades (10%) sat in the wrong fantasy week** (2020×12, 2021×4, 2022×10, 2024×8, 2025×19
  rows). Transactions were never affected — they take Sleeper's own bucket (2021+) or ESPN's
  `scoringPeriodId` (2020); only trades re-derived a week the platform already knew.
- [x] **Four near-identical copies of the date→week rule collapsed to one.** Three in
  `lotg.py`, one in `espn_2020.py`, each with its own anchor. The tanking pair keep their
  documented quirk (deep-offseason clamps to week 1) as an explicit `max(1, ...)`.
- [x] **Two false statements removed from the Formulas sheet** — startup picks counting 0
  trades, and the drafter being `Original Team`. Both retired by the startup fix; this sheet
  is the league's own documentation.
- [x] **152 dead lines deleted** — the legacy pick-chain mutator behind `if False:`, which
  still parses and so reads as live, and carried its own copy of the "5.0X is a FAAB buy"
  skip that the startup fix had to chase through four other places.
- [x] **`_R5XX_BASE`'s "real drafts are 4 rounds" comment corrected** (the sentinel maths is
  safe; the premise is what licensed the broken string checks), and the **draft-value round-5
  remap now asserts** the startup exclusion it silently depends on 60 lines upstream.
- [x] **Which SEASON a dated move belongs to** [per user]. A season runs kickoff week 1 to the
  end of its championship game, and everything after that championship belongs to the NEXT
  season. One comparison: **the first season whose championship has not happened yet.** Both
  edges occur, because the final's date moves (2020: Dec 28; 2021: ran to Jan 3) — a January
  move before the final keeps the old season, a late-December move after it takes the new one.
  17 rows have a listed year differing from their date, in both directions; **only 2 change
  from what the build produced before** (2025-01-01 Metchie 2024→2025, 2025-12-30 Gray
  2025→2026), because Sleeper's league rollover happened to agree with the real calendar
  almost everywhere. Three corrections on the way: it is NOT a month rule (a first cut moved
  84 rows, a second 16 — both miss half the seam); `created_dt` IS in scope in the accumulator
  loop; and the rule reads the **league clock**, since 2021-01-01 00:00 UTC displays as
  2020-12-31. `_season_window` and `_move_season` share `_season_end_monday`, so the split and
  the label cannot drift. Guards: every row's `Season` agrees with its own DISPLAYED `Date`
  (0 of 2016 disagree), each year mismatch straddles a real championship, and `player_year` tx
  counts reconcile to `transactions.csv` (0 of 1859).
- [x] **The weekly counters follow the season too** [per user]. `team_week`/`team_year`
  "Number of transactions"/"Number of trades"/"Amount of FAAB spent" reached team_year by
  SUMMING team_week, which filed a post-championship move under the season that had just
  finished — team_week has no bucket for it, since in its own season it is offseason. Loop 1
  now resolves each move's season with the SAME timestamp rule as Loop 2 (`status_updated` for
  a waiver, `created` otherwise — both displaced moves are waivers, so getting this wrong
  would have recreated the defect) and credits the weekly counter only when the season
  matches, plus a season-scoped counter always. team_year reads the latter; team_all_time and
  league_year already roll up from team_year; league_all_time rolls up from team_year too.
  league_week still sums weeks, which is right. Moves exactly 2 rows: Oliverwkw 2024 W17
  1->0 (season 33->32), stevenb123 2025 W17 2->1 (season 59->58).
- [x] **league_all_time was short by a whole season.** It summed team_week, so it dropped the
  offseason moves AND all of 2026 (in progress, no played weeks, no team_week rows): 1929
  against team_all_time's 2011. Summing the season counters instead fixed only half — an
  in-progress season's team_year row comes from a SEPARATE seeding path that counts
  transactions_rows/trades_rows straight, including the synthesized lineage-closing rows the
  per-event counters never credit. All three all-time counters now roll up from team_year,
  the same source team_all_time sums, so the two all-time sheets cannot disagree. A later line
  that re-summed team_week into league_all_time's FAAB, undoing the total set above, is gone.
- [x] **Synthesized rows now count as if they were not synthesized** [per user]. The
  lineage-closing transactions (2020->2021 platform-transfer releases, terminal dead-end cuts,
  arrivals with no recorded add) are appended AFTER the weekly loop, so the per-event counters
  never saw them: in transactions.csv, in no team's season total. **28 of 56 completed
  team-seasons were short, by 85 moves**; JacobRosenzweig 2021 read 2 against 13 detail rows.
  The TEAM counters are rebuilt from the final rows now — same fix, same place, same reasoning
  as the player_year/player_all_time rebuild directly above them. An in-season synthesized row
  also gets its team_week bucket, from its own date on the league clock (no Sleeper leg exists
  to read). Real rows keep their leg: re-deriving every week from dates would shift a Wednesday
  waiver back a week. `_league_day()` extracted from `_move_season` so season and week are read
  off one clock. Guards in `tests/test_synthesized_rows.py`.
- [x] **The manual-transactions overlay bypassed the counters** — it increments team_week
  directly, so shmuel256's hand-entered 2023 Puka Nacua pickup sat in a week but in no season
  total. Season-scoped now. It also carried a **third flat date anchor (`Sept 5`)** the
  earlier sweep missed because it was not one of the Sept 7 variants; now `_season_week_of`.

### Phase 13 follow-up — startup picks were numbered by SLOT, not draft ORDER
Surfaced by an inquiry ("what % of Oliverwkw's points is Nick Chubb?"), full write-up in
`plan/notes/STARTUP_DRAFT_ORDER.md`.
- [x] **74 of 152 startup picks mislabeled.** The startup is a snake, so a team's constant
  draft slot is not the position it picks from on even rounds. `espn_2020.py` discarded
  ESPN's `roundPickNumber` and `lotg.py` rebuilt the number as `round.slot`, reversing all
  72 even-round picks (+2 in round 5, see below). Chubb, 16th overall, read `2.01` instead
  of `2.08`. Fixed by carrying `pick_in_round` through and numbering by true draft order —
  the same convention the rookie/vet ledger already uses.
- [x] **Every startup pick-adjusted value was computed against the wrong neighbours.**
  `_window_slots` recovers overall position as `(round-1)*8 + number`, so a reversed even
  round shifts the 8-nearest baseline by most of a round. Self-correcting once the numbers
  are true order; ~0.2-0.3 sd of movement on all four adjusted columns (Chubb's Player
  addition value diff: −17.55 → −29.97). Startup `O-Score` is downstream of two of them and
  moves too — **it cannot be checked offline (KTC N/A there), so verify it in the results
  audit.**
- [x] **The 6 picks that broke the snake are the startup slot swap.** They are the only
  picks carrying ESPN's `owningTeamIds`: LWebs53 and AceMatthew exchanged their round 4, 5
  and 8 picks. Corroborated by the lone picks-involving email trade (2020-09-09, ~6h before
  the draft finished) and by `espn_2020_backfill.md`'s own prose. `Original Team` is now the
  slot's owner and `Final Team` the drafter; drafter attribution no longer special-cases the
  startup on the retired premise that ESPN picks were never traded.
- [x] **The swap is a recorded trade.** Its email has no player legs, so it parsed to an
  empty shell that produced no trade row. The shell now takes its two teams from the draft
  record (the only pick-only email of the season, matched against the only pair of swap
  partners in the picks) and its six pick legs from `data/commissioner_pick_trades.csv` —
  the same overlay that fills in the picks the other 2020 trade emails dropped, keyed
  `pick_year 2020` with `orig_owner` = the slot's owner. Result: two `trades.csv` rows
  (504 -> 506), three picks each way, all six pick rows at `Number of trades` 1.
- [x] **`Startup draft players remaining` credits the drafter again.** `_startup_remaining_maps`
  still keyed on `Original Team`, which after the ownership fix is the *counterparty* on the
  six swapped picks — crediting Mike Evans to the manager who sold the slot. Wrong by up to 3
  players across **160 team-weeks**, both swap teams, every season. The 2020 week-1 rosters
  settle it: 0 unexplained players under the drafter model, 10 under the slot-owner model.
- [x] **Two more "5.0X is a FAAB buy" shortcuts, in the link builders.** The PH# anchor and
  the previous-transaction lookup both route a `5.0X` to the `_R5XX_BASE` sentinel, so all
  eight startup round-5 picks looked up a key nothing writes and lost their chain — including
  the two swapped ones, whose round-4 and round-8 counterparts in the same deal both linked
  fine. All six now link to their own side of the trade (`T#1` / `T#135`).
- [x] 🔍 **2020 offseason fully reconciled** (per user). 152 startup picks + 10 adds − 6 drops
  reproduce all eight 2020 week-1 rosters exactly, 0 unexplained either way. Earliest 2020
  transaction is 2020-09-09 23:33, 108 minutes after the slot swap and before the draft ended.
  Guarded by `test_2020_week_one_rosters_reconcile_to_the_draft_and_the_ledger`.
- [x] 🔍 **The unmatched 2020-11-29 22:23:39 ESPN trade was VETOED** — 5 vetoes vs 2 upholds,
  final `TRADE_ACCEPT` records `status=CANCELED`, and Fitzpatrick never appears on AceMatthew
  after it. The real Cook deal (for a 10-pick haul) followed 94 minutes later at 23:57:04 and
  is already in the ledger. Correctly excluded; no action.
- [x] **`check_research_file` no longer requires a researched player to be rostered.** It is a
  TYPO check: an unsigned free agent is exactly what deserves a research note, and a rostered
  player can be cut mid-season without the note becoming wrong. Now resolves the name against
  the player dictionary — a name that is nobody is a typo, an ambiguous partial says so.
  (Nick Chubb, researched as "unsigned free agent at 30", failed the roster form the week he
  went unrostered.) [per user]
- [x] **Three "5.0X is a FAAB buy" shortcuts had to learn about the startup.** Its round 5
  holds eight REAL picks (two of them swapped), so `pick_lookup`, `_pick_to_drafted` and
  `_pick_hist_lines` were skipping them — the round-5 legs read 0 trades and rendered as a
  bare `2020 5.??` while their round-4/8 counterparts in the same deal read 1. Carved out
  via `_su_row()`, which also fixes the NaN-is-truthy trap on the `_is_startup` flag. The
  seven genuine 5.0X buys (2025/2026) are unaffected, guarded by a test.
- [x] **The in-season/offseason boundary is dynamic now** (per user: "it changes"). It was a
  fixed Sept 7, wrong at both ends: kickoff is the Thursday after Labor Day and moves six
  days across the seasons on record (Sept 4 in 2025, Sept 10 in 2020/2026), and the far end
  did not exist — a season ran to New Year rather than to its championship. Now
  (`_nfl_kickoff_thursday(season)` .. championship Monday from `_finals_weeks()`). On the
  data as it stands **only the slot swap moves** (2020-09-09 < the Sept 10 kickoff): every
  other trade sits well inside its window, and no trade at all falls after a championship,
  so that half is a guard, not a restatement.
- [x] **The first season's `Offseason trades` is a real count, not N/A.** It was blanked
  alongside offseason turnover on the premise that there is no offseason before the first
  season — but the slot swap is one. Blanking left 2020 reading `Offseason N/A + Inseason 4
  = Total 5`, and disagreed with team_all_time, which counts the split off the trade dates.
  Turnover stays N/A (no prior-season roster to diff). Side effect: with the NaN gone the
  column renders as an integer (`1`, not `1.0`) across every season, matching its
  `Inseason`/`Total` siblings — a formatting diff on every row, no value change.

## Phase 14 — In-season weekly digest email
**Trigger:** Tuesday 14:00 UTC (~10am ET) build+digest+**email**; plus a Thursday 16:00 UTC pregame build with **no email**. Runs year-round since #379 (a week with no movement renders empty and `--skip-empty` drops it); snapshot rotates only on the Tuesday send run so emails diff week-to-week. (Wired into `build.yml`.)

**Title / subject wording:** one helper, `digest.digest_title(meta)`, produces both the email subject and the `<h1>` inside it, so they can't drift. In-season it reads `LOTG weekly digest — 2026 season, week 7` (no "through" — the digest reports the week's *changes*, not a cumulative total). In the offseason there is no week to name, so it gives the build date instead: `LOTG weekly digest — 2026 season, August 4, 2026`.

**Delivery / recipients:** `config/digest.yaml` — the real Tuesday digest goes to the whole league (8), `test_recipients` + `audit_recipients` = okeimweiss only. **Sending is LIVE**: credentials are AES-encrypted in `config/digest_credentials.enc`, decrypted at send time with the `DIGEST_KEY` secret (verified by the "Send test digest email" runs). `SMTP_USERNAME`/`SMTP_PASSWORD` still override if set. Optional, not yet set: `DIGEST_RECIPIENTS` / `DIGEST_TEST_RECIPIENTS` / `DIGEST_AUDIT_RECIPIENTS` secrets, which override the committed lists so the addresses need not sit in this public repo (audit finding F4).

**What to surface** (OVER-INCLUSIVE — every numeric column auto-discovered, not a headline subset; full phrasing in `plan/phase14_phrasing.csv`). Per-section rules:
- **player_all_time**: top/bottom-5 crossings. "Kyler Murray passes JJ McCarthy for 4th-lowest Points all-time (−0.4)."
- **team_all_time**: ANY movement among the 8 (full board, riser side, one line). "BROsenzweig passes shmuel256 for 3rd-highest Max PF all-time."
- **league_all_time**: milestones only (round-number crossings of major totals) — no leaderboard. "League Total trades passes 200."
- **Yearly on-pace** (player_year/team_year top-bottom 5; league_year floor(#seasons/3)≤5), **from week 3 only**: "Oliverwkw is on pace for 4th-highest Hardship this season." Cumulative scale by weeks; rate/level as-is.
- **Weekly-counting stats** (awards `Times…`, `Wins/Losses from hardship|byes` — ≤1/week) get NO on-pace; instead a **new single-season record** alert (actual value beats the best in ANY prior season): "AceMatthew sets a new single-season record for Times One-man army? (11) — most in any season." Plus all-time crossings. **Boolean season flags** (0/1, e.g. #363 `Rostered by champion?`) get neither on-pace nor record — only all-time count crossings.
- All yearly ranking (on-pace + records) is vs completed single seasons across ALL years, not just the current one.
- **Single-week records** (weekly sheets player_week/team_week/league_week): the just-completed week's values ranked vs EVERY week ever, top/bottom 5 both ends. "shmuel256's PF this week (201) is the 2nd-highest single week ever." Values shared by >5 week-rows (0-piles, tied maxes) skipped. This is how the weekly sheets are directly involved.
- **Only changes** are reported — on-pace standings + records diffed week-over-week, so a still-3rd team / standing record is silent (keeps the digest to ~dozens of lines).
- **New data first, edits at the bottom** (PR #426). Every move is attributed by `email_summary.attribute`, using `digest.new_data_since` as its evidence.
  - A move new data could explain reads where it always has. That covers a completed week's games, a brand-new transaction, and KTC/tenure drift. A move that both new data and an edit could explain also stays here.
  - A move only an edit explains goes under **"Changes from edits, not new data"** at the end of the email, under the same section titles one level down.
  - **Evidence:**
    - which weeks completed since the prior snapshot, and who played in them;
    - who is in new transaction rows. A transaction reaches only transaction stats (`_TX_MARKERS`).
    - pooled stats (percentiles, tiers) move with any new week;
    - a past row counts as new data only on a stat that keeps accruing (`_FORWARD_MARKERS`).
  - **Was there an edit at all?** The snapshot stores `meta.inputs_fingerprint`, `digest.edit_fingerprint` over the committed `src/`, `lib/`, `data/` and `config/league.yaml`.
    - It excludes bot-written paths (the tracker, `data/digest/`, `data/audit/`) and the digest-rendering modules.
    - If the fingerprint is unchanged, there is no edits section.
    - If either snapshot lacks one, the email splits as if an edit may have landed.
  - The lede's "re-valued history" count uses the same test, so it equals the size of the edits section.
  - Tests: `tests/test_digest_attribution.py`.
- **Test email button**: `.github/workflows/digest_test_email.yml` (Actions → "Send test digest email" → Run workflow) + `send_digest.py --test`. Appears in the Actions UI once merged to main.

**Implementation outline** (progress; full design in `plan/PHASE14_DIGEST_PLAN.md`):
- [x] Capture prior-week ranks snapshot (commit to repo or store as workflow artifact) — `lib/lotg_support/digest.py` `build_snapshot()` + `data/digest/ranks_snapshot.json`, rotated by the CLI.
- [x] Diff vs current week's ranks; produce a narrative list of crossings — `diff_snapshots()` (top/bottom-N crossing detection, both leaderboard ends, new-entity guard).
- [x] On-pace projections — `project_on_pace()` + `diff_pace()` (linear pace extrapolation, ranked vs completed seasons; horizon learned from history; week-3 gate; only reports rank CHANGES).
- [x] Over-inclusive ALL-stats auto-discovery (`discover_numeric_columns`) — every numeric column, not a headline subset.
- [x] Phrasing catalog CSV (`plan/phase14_phrasing.csv`, 431 stats) — `--phrasing-csv`.
- [x] HTML email template with sections: All-time moves (players/teams) / On pace (players/teams/league) — `render_digest_html()`.
- [x] In-season gate — superseded by #379: the digest builds year-round and the in-season-only pieces (on-pace, single-season records, single-week highlights) self-gate to empty. `is_in_season()` remains as the season/offseason predicate.
- [x] CLI + tests — `scripts/build_digest.py`, `tests/test_digest.py`.
- [x] Delivery — `config/digest.yaml` recipients + `scripts/send_digest.py` (SMTP via env secrets; safe no-op until `SMTP_USERNAME`/`SMTP_PASSWORD` are added).
- [x] Scheduled runs — folded into `build.yml`: Tuesday send + Thursday pregame no-email, `workflow_dispatch` `send_email` toggle, snapshot rotated only on the send run.
- [x] Turn on real sending — done via the `DIGEST_KEY` secret + encrypted credentials (not the `SMTP_USERNAME`/`SMTP_PASSWORD` route originally planned); confirmed by two successful test-email runs.

**Weekly automated audit** — BUILT (#368), hardened by #369/#370: `.github/workflows/weekly_health_email.yml` mails a private dataset-health check to the maintainer every Wednesday 15:00 UTC (breakages + missed injury weeks), `workflow_dispatch` fallback. It runs a **full cold-cache rebuild** (no `actions/cache/restore`, i.e. the `force_refresh_cache` condition) and diffs that against the committed exports, so Part 1 asks "does a from-scratch rebuild still reproduce what we ship?". Observes only — caches aren't saved and `permissions: contents: read`.
- [x] **Confirm the first live Wednesday run** — confirmed: scheduled runs succeeded every Wednesday from 2026-09-02 on (09-02, 09-09, 09-16, 09-23).

**Run 456 (2026-08-04) offseason email — investigated, no code fix needed.** The first year-round offseason digest reported two team crossings that no offseason event could have caused (`Number of donuts`, `Weeks of injuries` — both frozen historical facts). They are the one-off tail of the #381 live-status fix, not a digest bug:
- The baseline it diffed against was captured 2026-07-28 off run 454's exports — the last build *before* #381. In that build Sleeper's live `injury_status` (a batch of late-July training-camp PUP/Out designations) was still stamping `Injury?` on completed-season zero-point weeks, which inflated `Weeks of injuries` and suppressed `Number of donuts` across the league.
- #381 froze completed seasons against live status; run 455 (07-30) rebuilt with correct values, and run 456 diffed correct-vs-contaminated. The *reversion* is what surfaced as "Oliverwkw passes AceMatthew for 5th-highest Number of donuts" (59/59 tie → 64/62) and "stevenb123 passes BROsenzweig for 6th-highest Weeks of injuries" (468/469 → 465/464).
- Confirmation that it can't recur: runs 455 and 456 are identical on both columns, while every pre-#381 run differed by the day it ran (448–452 on 07-21 vs 454 on 07-28). The volatile-column exclusion (#380) is not the right lever here — these columns *should* move when a real donut/injury happens.

**Tagging fix-driven moves "(from bug fix)" — investigated and DROPPED** (don't re-derive this). The ask was for the email to label a leaderboard move that a fix caused rather than an event. Two routes, both dead:
- *From the data* ("did a completed season's numbers change?"). Doesn't discriminate: historical rows are not frozen — they carry present-day-valued columns (a 2021 row's KTC, ages, adjusted averages, percentiles). Measured on run 455 → 456, a week with roster activity and **no** code change, restricted to only the columns that can produce a crossing: 627/649 players and 8/8 teams show changed history. Fails identically at column, per-entity, and per-row granularity — it would tag everything, every week. Activity also brings history with it (a waiver claim arrives with every prior season that player played).
- *From the repo* (fingerprint `src`/`lib`/`scripts`/`config`/workflows/`data` per snapshot, tag when they differ). Detects the cause correctly, but only per BUILD: it says "a fix landed this week", never "this move came from it", so a week with a fix plus real activity tags every line. Sharpening it to per-move means rebuilding the week's data under the previous code — a second ~25-minute build every Tuesday.
- So per-move attribution requires a signal neither the data nor the repo can provide cheaply. Left untagged; the run-456 write-up above is the record for that week.

- [x] **3-part audit** (code / results / diff) — `plan/AUDIT_PHASE14_3PART.md`. Clean on data (Phase 14 is additive; zero `src/` or CSV changes; 9/9 hand-checked digest claims reconcile). 4 code findings F1–F4 all fixed (#369), plus 3 post-merge fixes from the run-447 cold-rebuild audit (#370).

## Phase 14.5 — Split the picks sheet; de-trend the non-rookie O-Score
**Why:** an inquiry into the worst startup picks by O-Score showed the two drafts
are not comparable. A 19-round startup snake and a 4-round rookie draft have
different slot economics, so the same O-Score means different things in each —
and *within* the startup, an early bust and a 19th-round bust with the same
on-field return were graded alike.

- [x] **`picks.csv` -> `non_rookie_picks.csv` + `rookie_picks.csv`** (2020 startup
  + 2021 vet | every rookie draft). The frame is still BUILT as one table and
  split at OUTPUT: every `PH#N` ref is `ph`'s positional index + 1, and the pick
  chains are keyed the same way, so splitting mid-build would renumber them and
  move rows on sheets this change must not touch. The xlsx resolver maps a `PH#N`
  into whichever sheet now holds that row (verified: 942 links, 254/254 trades
  pick-links land on a row whose pick Number matches the label).
- [x] **Non-rookie O-Score de-trended for draft slot**, after it is computed:
  `expected = a + b·ln(overall position)` with `b` clamped ≤ 0 (monotone), each
  score moved HALF the way off its expectation, clamped to 0-100 (raised to
  THREE QUARTERS in the follow-up below). Startup + vet
  are ONE sequence (vet continues after the startup's last pick), matching the
  pick-adjustment window's own ordering. Centred on the fitted curve's own mean,
  so the pool's mean O-Score is unchanged and a clamped slope is a true no-op.
  On the committed data: 184 rows, slope −5.94, median shift 1.9, max 12.6;
  Julio Jones 13.1→8.4, Michael Thomas 18.2→11.4, McCaffrey 93.4→80.8, Bryce
  Love 9.8→12.1, Josh Allen (mid-draft) 98.6→98.7.
- [x] **Drafting skill: a non-rookie pick weighs 0.5** against a rookie pick's
  1.0 (the machinery already supported weights — pure drops use 1/3). Lands on
  team_all_time and team_year 2021; the startup's Year is the non-numeric
  "startup" tag, so it reaches the all-time grade only. Expected all-time deltas
  −1.3 (stevenb123) to +2.3 (shmuel256); 2021 deltas −1.4 to +3.6.
- [x] **The current rookie class is held out of the pick-adjustment reference
  pools until week 8** — the same half-season gate that already withheld its
  O-Score, now one shared predicate (`_early_rookie_class_mask`). It still
  RECEIVES a diff, it just no longer defines one. **This was not previously the
  case** (measured: all 169 older rookie picks reconcile exactly only with the
  2026 class IN the pools, 0 without), so it is a real behaviour change, made
  deliberately at the user's direction.
- [x] **Both sheets appear separately in the weekly digest** (`_BOARD_SHEETS`
  gains two entries with their own titles, so each gets its own section).
- [x] Offline diff vs `origin/main`: **add_drops, trades, player_additions and
  every player/team/league sheet byte-identical**; only `formulas.csv` (docs) and
  the pick sheets themselves differ. Suite green (279 passed, 1 skipped).
- [x] **3-part audit round 1 — run 480 vs run 479.** Code: 280 passed, sanity
  0/0, and KTC DID resolve live (12,010 lookups), so the de-trend and the
  re-weight were really exercised. Results: the split is exhaustive/disjoint and
  order-preserving (184+364=548, 0 overlap); 1052 PH# links land correctly (320
  number-labelled, 310 name-labelled, 0 wrong, 0 out of range); the de-trend
  refits out of the published CSV to slope -6.0443 / intercept 74.4829 against
  the logged -6.0421 / 74.4730 (1-dp rounding), mean O-Score preserved to 4 dp,
  shift monotone -12.79 -> +2.96, nothing clamped; Drafting skill reconstructs
  EXACTLY at w=0.5/1.0 on 8/8 all-time and 40/40 team_year rows (unweighted
  reproduces none of them). Diff: zero movement on player/league sheets;
  everything that moved maps to the wall clock (+2d), a KTC anniversary rolling
  over, the week-8 gate, or the de-trend. No unexpected diffs.
- [x] **Round-1 defects fixed** (all four were invisible in a green run):
  - The retired `picks.csv` shipped anyway — the build only ever WRITES, so the
    checkout's copy survived untouched into the artifact AND into
    `LOTG_Exports.zip` (which globs `*.csv`), frozen with pre-de-trend
    O-Scores, and `git add exports` had nothing to stage. Named in
    `_RETIRED_EXPORTS` and deleted each build; the refresh commit now stages
    that deletion (`git add -A exports`).
  - Four test files still read the retired file and PASSED on it —
    `test_pick_chain_links` was checking FRESH trades/add_drops refs against the
    FROZEN table, `test_startup_draft_order` was guarding the Phase-13 ordering
    fix on it, `test_draft_capital`'s build gate keyed on it, and
    `test_forecast`'s write sentinel watched a file the build no longer writes.
    All repointed.
  - `PH#N` had become unresolvable: it is the FRAME's positional index and the
    frame interleaves the two sheets, so N indexes neither. The build now writes
    `exports/raw/pick_ref_index.csv` (`lotg_support.pick_index`), and the link
    audit, the chain guard and `inquiry.load_sheet("picks")` all rebuild the
    frame in build order through it. Readers tolerate its absence.
  - `data/audit/schema_baseline.json` still pinned `picks`, so the first
    Wednesday health email would have gone red on "sheet missing" + two unpinned
    sheets. Re-pinned.
- [x] **3-part audit round 2 — runs 481 and 482.** Round 2 caught a fifth defect
  the local suite structurally could not: pointing all of
  `test_startup_draft_order` at `non_rookie_picks` broke the one test in it that
  guards ROOKIE picks (the 5.0X draft-day FAAB buys), which found zero of them
  and tripped its own "the guard would be vacuous" assertion. Locally every test
  in that file SKIPS, because the committed `exports/` still predates the split —
  only CI can see this class of break until the first refresh commit lands.
  Fixed to read both sheets. Run 482: **280 passed, 0 failed**, sanity 0/0,
  `picks.csv` retired out of the artifact AND out of `LOTG_Exports.zip`, the ref
  index written (548 refs, rebuilding the pre-split frame order exactly against
  run 479), the schema pin matching both sheets, and **every shipped sheet
  byte-identical to runs 481 and 480** — the fixes moved no data, which is
  exactly what retiring a stale file and emitting a map should do.

### Phase 14.5 follow-up — de-trend to 0.75, and length in the pick addition value
Both asked for after reading the round-2 boards; both are re-gradings, not fixes.

- [x] **`NONROOKIE_OSCORE_LAMBDA` 0.5 -> 0.75.** Half read the right way and the
  only question was how hard to lean. At 0.75 the startup's worst first-rounders
  (Michael Thomas 1.07, Ezekiel Elliott 1.03, Clyde Edwards-Helaire 1.08) all sit
  inside the bottom nine, and the deep darts get their relief (Josh Doctson 19.07
  4th-worst -> 10th, Bryce Love 19.06 6th -> 12th). Still short of 1.0 on the
  original reasoning. Non-rookie only — the rookie board cannot move on this.
- [x] **Pick `Player addition value` gains `x (1 + starts before next transaction
  / 170)`.** Its two % terms are RATES, so the same start rate graded alike over
  one season and six. 170 is roughly a decade of starts: the factor is 1.0 with
  no starts, <=1.2 for 90% of picks, and 1.56 at the longest run (95 starts). Scales the PPG term only; the handcuff bonus lands after.
  BOTH pick sheets; the add_drops / trades / player_additions versions of the
  column are deliberately untouched.
- [x] Predicted from the committed build before shipping (a simulator that
  reproduced all 353 published O-Scores exactly): non-rookie max shift 7.8 /
  mean 1.46, rookie max 4.7 / mean 0.47 and no lambda component at all. One
  entry changes hands in each sheet's top 20 (McCaffrey 1.01 out for Jared Goff
  19.05; Jayden Daniels out for James Cook) and one in each bottom 20 (Matt
  Breida out for DeVante Parker; Jaydon Blue out for Terrace Marshall).
- [x] **3-part audit round 3 — run 483.** 280 passed, sanity 0/0, de-trend logged
  at lambda 0.75 / max shift 19.2. The diff vs run 482 is fully explained and has
  nothing else in it: `Player addition value`, its pick-adjusted difference and
  `O-Score` on BOTH pick sheets (484 + 365 cells), `Drafting skill` downstream
  (5 all-time + 34 team_year), 4 documentation cells in `formulas`, and every
  other sheet byte-identical — `add_drops`, `trades` and `player_additions` among
  them, which is what confirms the addition-value change stayed picks-only.
  Every pre-registered prediction landed: the shipped boards swap exactly
  McCaffrey -> Jared Goff (top 20), Matt Breida -> DeVante Parker (bottom 20),
  Jayden Daniels -> James Cook, Jaydon Blue -> Terrace Marshall, at the predicted
  boundary values (80.4 / 20.8 / McCaffrey 74.9).
- [x] **The starts term extended to `player_additions` only.** That sheet is the
  cross-channel comparable, its main variable is a one-sided level (like the pick
  sheets'), and it already carried `Starts on team` — so the term goes in
  unchanged and stays uniform across channels, which is the column's contract.
  Scoring longevity on the pick sheets but not here would have made the same
  drafted player say two different things in two places (321 rows overlap,
  corr 0.911). Deliberately NOT extended to `add_drops` or `trades`: their
  addition value is a DIFFERENCE against a dropped/sent side, so length there
  claims a small edge held long beats a big edge held briefly — a different
  claim; and `trades` has no starts column at all, plus an additive pick term
  that would leave pick-only hauls stuck at factor 1.0 while player hauls scale
  to ~1.5. Predicted: 705 of 1,932 rows move (36%), max delta +20.28 (Josh Allen
  36.29 -> 56.57), mean 1.54 on the movers; by channel Draft 221/388, Trade
  230/465, Free agency 139/616, Waiver 114/457. One column, no O-Score on this
  sheet and no skill metric downstream.
  **Run 485 confirmed every one of those figures exactly** — 705 rows, +20.28
  (Josh Allen 36.29 -> 56.57), mean 1.54, zero zero-start rows moved, and all
  four per-channel counts on the nose. `Player addition value` was the ONLY
  column that moved on the sheet, and every other sheet came back byte-identical
  (plus 2 documentation cells in `formulas`). 281 passed.
  - [x] **Raised and DECIDED: the flat divisor stays.** 170 is elapsed starts, so
    it partly measures how long ago the move happened — rookie classes average
    12.0 starts (2021) down to 2.4 (2025), and the percentile pools mix the
    classes. A cohort-relative divisor (starts / starts AVAILABLE since the move)
    would neutralise that. The maintainer's call is NOT to: **rewarding longevity
    is the point of the term**, and normalising it away would leave a third rate
    measure, which is the thing this was added to fix. A pick that held a starting
    job for six years is meant to outrank one that held it for one, even though
    part of that gap is simply having had the years. Do not re-propose.
- [x] **Accepted, self-healing: the first post-merge digest is blind to the pick
  boards.** `data/digest/ranks_snapshot.json` keys its board entries by SHEET
  NAME (254 under `picks|...`), and `digest.diff_events` skips any event whose
  `(sheet, column, end)` slot is absent from the prior snapshot — so the two
  renamed sheets produce no crossings at all on the first run. Confirmed on run
  480: 11 board moves, no pick section, despite 337 pick O-Scores having changed.
  It does NOT flood the email with false "new row" entries, and it self-heals the
  moment the Tuesday cron rotates the snapshot. Flagged, reviewed and accepted as
  is — but expect NEXT Tuesday's digest to say nothing about the startup board
  being re-graded, and do not read that as a bug.
- [x] **Formulas sweep.** Coverage clean (0 undocumented columns, 0 plan-vs-catalog
  drift). Verified against the build's own numbers: O-Score inside 0-100 on all
  four sheets, the pure-drop 0-50 ceiling (max 47.7), the Drafting-skill shrink
  reproducing 8/8 all-time, the +5 handcuff bonus landing at exactly 5.0 on all 8
  cuff rows, and lambda 0.75 / divisor 170 matching the source constants. Three
  fixes:
  - **`Tanking` and `Team` still named `picks` as one of their sheets** — a sheet
    that no longer exists. The committed coverage guard only checks
    columns-without-an-entry, never entries-naming-something-gone, so a rename is
    invisible to it in exactly this direction.
  - **The new starts-term note claimed the factor stays "inside ~1.0-1.2"; it is
    1.000-1.559.** True for 90% of picks, wrong for the tail (95 starts -> 1.56).
    Corrected to state both.
  - `PH#N` prose still read "= picks row"; it now names the two sheets and says
    the ref counts through them as one frame.

## Bench / healthy-week columns (from the Pat Freiermuth inquiry)
The inquiry ("how unique is Freiermuth's time on JacobRosenzweig": 75 healthy
games, 11 starts) had to derive "games held without starting" by hand. Asked for
on player_year, player_all_time and player_additions: starts, weeks on bench,
healthy weeks on bench, bench points, total healthy weeks, start %, healthy
start %, injured weeks — "insofar as they do not already exist", no duplicates,
all in the weekly email.

- [x] **Already present, not duplicated.** player_year / player_all_time: starts
  (`Weeks as starter`), `Weeks on bench`, start % (`% of starts`), injured weeks
  (`Weeks missed due to injury`). player_additions: starts (`Number of starts before next drop`), healthy
  weeks (`Games played on team`), start % (`% of starts made while rostered`),
  healthy start % (`Injury adjusted % of starts made while rostered` — already
  healthy starts / healthy weeks, Freiermuth 11/75 = 0.1467).
- [x] **Added to player_year + player_all_time**: `Healthy weeks on bench`,
  `Healthy weeks rostered`, `Healthy % of starts`, `Total points on bench`.
  "Healthy" = not a bye, injury or suspension week — the `_played` flag the
  Adjusted averages already divide by, so no new definition.
- [x] **Added to player_additions**: `Bench weeks on team`, `Healthy bench weeks
  on team`, `Injured weeks on team`, `Bench points on team` — from the same
  `_tenure_stats` window as the starts / `Games played on team`.
- [x] **Removed player_additions `Starts on team`** [per user: "keep the old
  duplicate starts column, delete the new one"]. It was identical to `Number of
  starts before next drop` on every row (both `_tenure_stats["starts"]`); that
  one is older (add_drops since 2025; both reached player_additions in #409), so
  it stays. Its readers — the Player addition value formula text and
  `test_pick_sheets_split`'s starts-term check — now name the kept column; the
  xlsx/digest have no hard reference. The digest's prior board slots for the
  removed column simply produce no events.
- [x] Plan CSV + `stats_catalog.json` + Formulas entries + schema pin
  (`data/audit/schema_baseline.json`) + phrasing reference rows. The digest
  needs no change: `discover_numeric_columns` picks up every numeric column,
  `Healthy % of starts` projects as a rate ("%"), the rest scale as counts, and
  the player_additions names carry "on team" so they read as forward-accruing.
- [x] Guard: `tests/test_bench_health_columns.py` recomputes all eight from
  player_week (skips on pre-merge exports; fails on a partial set).
- [x] **3-part audit** (code / results / diff) on the first post-merge build —
  **PASS** (2026-09-30): run 550 (merge `88f0df8`) vs baseline run 548. Diff: only
  the 12 new columns + `Starts on team` removed + Formulas rows (Stat set: +8 new,
  `Starts on team` gone, `Number of starts before next drop` sheet label widened,
  Player addition value text renamed); 0 changed cells in any other column, row
  counts unchanged, build-log error profile identical to baseline. Results: all
  player_year / player_all_time values recompute exactly from player_week;
  Freiermuth, Bryce Young, Thielen 2021 (start in an injury week) and 2020 rows
  check out. Flagged, by design: `Healthy % of starts` = 0.0 (not N/A) on the 73
  zero-healthy player-years and 249 pad rows, same as `% of starts`; run 550's
  player_additions double-counted 10 multi-stint pairs, since fixed by #444/#445
  (0 mismatches on current exports).
  Expected diff: the 12 new columns on the three sheets, `Starts on team` gone
  from player_additions, their Formulas rows, nothing else. The first Tuesday
  digest after merge will list the new player_year columns' on-pace standings
  once (`diff_pace` treats a column absent from the prior snapshot as newly
  entered); the all-time and event boards stay silent on them for one week. Results cases to check: Freiermuth's JacobRosenzweig row (bench
  weeks 76, healthy bench 64, injured 7, bench points 532.2 as of 2026 wk 2);
  Bryce Young's stevenb123 row (healthy bench = games played, 0 starts); a
  player with a start in an injury week (24 such starter-weeks exist) so
  healthy starts < starts; a 2020 row; a zero-rostered-week padded row.

## PPG grid + a position-adjusted twin of every player PPG column
From the "which starting / rostered / healthy PPG combinations are missing"
inquiry. Asked for: fill every gap in the grid on player_year, player_all_time
and player_additions (player_week excluded), then give EVERY player PPG column a
position-adjusted version, all treated like the other averages in the weekly
email. Scope decisions [per user]: team / league averages are left out (a team's
PF mixes every position, so the per-position factor means nothing there);
"anything that makes statistical sense" among the derived per-game columns.

- [x] **The grid.** "Healthy" points equal gross points (all 4,671 bye / injury /
  suspension rows in player_week score exactly 0), so the grid is starter /
  rostered / bench points over started / rostered / healthy weeks. New where
  missing: player_year + player_all_time `PPG starter per rostered week`,
  `Adjusted PPG starter per rostered week`; player_additions `Adjusted Avg points
  added`, `Avg points added per rostered week`, `Adjusted Avg points added per
  rostered week`, `Avg points per rostered week on team`, `PPG bench on team`,
  `Adjusted PPG bench on team`. Rostered points / started weeks deliberately not
  built (mixes two week sets; measures nothing).
- [x] **Twins** (`<column> adjusted by position`), one factor (`_pos_factor`:
  that season's league starter avg / position starter avg):
  player_year (13: Avg points, Adjusted Avg points, PPG starter / bench and their
  Adjusted and per-rostered-week forms, PPG starter vs bench diff, Starter PAR
  per game, Avg points (full season), both Change in avg points columns);
  player_all_time (11, full career instead of the season/change columns);
  player_additions (6 grid twins + PPG of 5 games before pickup); add_drops (4:
  Average PPG on team, dropped player's PPG over same time, PPG of 5 games before
  pickup, Dropped avg points); trades (3: received on team, sent over same time,
  received 5 games before); player_week (4: PPG as team starter + its "this
  season" form, the 5-game start/sit difference and its cuff-adjusted form).
  Multi-season averages scale each WEEK (or nflverse season) by its own season's
  factor before averaging; the two nflverse backfill seasons borrow the first
  league season's factor (they are scored with its rules). add_drops / trades /
  player_additions keep their sheet's existing convention (the move's season).
- [x] **Deliberately NOT twinned** (classified): team/league averages (by design,
  per user); player_week `Change from previous week / previous 5 weeks avg /
  career average to that point / overall career average` (a single week's points
  minus a baseline, not an average); `Positional scoring percentile` and the
  tier %s (already within-position); pick sheets (every PPG column there already
  has a twin).
- [x] **Doc fixes found on the way** (defects, doc-only; plus the two add_drops
  difference notes now say "blank when both sides are blank"): `PPG starter vs bench
  diff` said PPG starter − PPG bench; the code (since Phase 1C) uses the Adjusted
  pair and reads a missing side as 0 — 747 of 1,058 two-sided player_year rows
  differ from the documented formula. `Difference of averages adjusted by
  position` said "all-time" position averages; they are per-season.
- [x] Plan CSV + `stats_catalog.json` + Formulas entries + schema pin +
  `_preserve_na` (a twin is blank exactly where its base is) + a `_column_kind`
  override for the trades pre-trade twin (the "trade " text marker would catch
  it). Digest: every new name carries a rate marker ("avg" / "ppg" / "diff"), so
  it projects as-is and waits on the rate gates like its base; "adjusted by
  position" makes the twins derived (lower prominence) exactly like the existing
  twins; two display phrasings added. No existing column's kind, N/A rule or
  number format moved (checked over every catalog column).
- [x] Guard: `tests/test_ppg_position_adjusted.py` recomputes the grid and the
  factor from player_week and checks every twin against it.
- [x] **Playoff PPG split, player_all_time only** [per user: "Semifinals and
  finals only", starter PPG]: `Regular-season PPG starter` ("Week N" starts),
  `Playoff PPG starter` (championship-bracket Semifinal + Final starts; 3rd Place
  and the toilet bracket are neither), `Playoff minus regular-season PPG
  starter` (the player's own clutch index), each with its position-adjusted
  twin. Every start counts, as in `PPG starter`; player points carry no
  semifinal +5 (a team PF bonus). 122 players have a Semifinal/Final start in
  the offline build.
- [x] **Stale add_drops difference fixed** (defect): add_drops' final pass left
  the first-pass `Difference of averages` (+ adjusted) and the Player addition
  value built on it when it blanked BOTH sides (never rostered a week here, no
  dropped-player window). Now blank, and the addition value is 0.0 as the
  Formulas sheet documents for a player never rostered a week. Exactly 3 rows:
  K.J. Osborn (Oliverwkw 2023-01-11, value 10.10 -> 0), Gardner Minshew
  (stevenb123 2022-01-08, 11.82 -> 0), Tyler Huntley (stevenb123 2022-01-09,
  10.60 -> 0 — its +5 handcuff bonus goes with it). O-Score unchanged (all
  three were already N/A); nothing else moved.
- [x] **phase14_phrasing.csv regenerated in full** (defect: nothing regenerates
  it, so it still listed the retired `transactions` / `picks` sheets, "Number of
  transactions", "Transaction skill", a week-3 on-pace gate, and had no rows for
  add_drops, player_additions, the pick sheets or the year sheets' all-time
  boards). Every existing row now comes from `phrasing_catalog()` over the
  committed exports; this PR's new columns' rows from the offline build. 886 ->
  1,493 rows. The 90 dropped (sheet, stat) pairs all name something gone, except
  two correctly unranked: `Reference player name` (text) and league_all_time
  `Number of donuts` (not a milestone stat). Guard:
  `tests/test_phrasing_reference.py` fails on a row naming a sheet or column
  that no longer exists (it fails on the old file).
- [x] **add_drops position factor keyed to the FANTASY season** [per user:
  "use FFB year like everything else — calendar year should pretty much never
  be used"] (defect): `_tx_season` was the calendar year of the move's UTC
  timestamp; it is now the row's own `Season` (`_move_season`: league time,
  bounded by championships), as trades / player_additions / picks already did.
  Swept every `_pos_factor` caller: this was the only calendar-year one. Offline
  build: exactly the 6 of 1,503 rows whose Season differs from that year move
  (late-December-after-the-final / early-January-before-it moves), plus a ±0.1
  O-Score percentile ripple on 7 others. Note (by design of per-season
  baselines, unchanged): a move filed under a season with no starts yet (e.g.
  an August pickup before week 1) has no baseline and scales by 1.0.
- [x] **Team + league count labels** [per user: clear "(starters)" vs
  "(roster)" in the spreadsheet and the email]: `Number of donuts` -> `Donuts
  (roster)`, `Number of starter donuts` / league `Number of starting donuts` ->
  `Donuts (starters)`, `Number of players under 10 / over 20..50` -> `Players
  under 10 pts (roster)` / `Players over N pts (roster)`, `Number of starters
  …` -> `Players … pts (starters)`, on team_week/year/all_time and
  league_week/year/all_time. `Number of games within 5/10` (games, not players)
  unchanged. Kind, N/A rule, number format, header topic and every digest
  classification checked identical old -> new; `_EXTRA_COUNT_PREFIXES` gains
  the new prefixes so they still render as integers; the digest's " pts" suffix
  now only applies to the games columns (the player names carry "pts"
  themselves). Values unchanged (offline build, renamed columns compared cell by
  cell). The digest snapshot is keyed by column name, so
  `digest.migrate_snapshot_columns` rewrites the old names on read (like
  `migrate_board_label`): the first Tuesday digest after merge still diffs
  these boards against last week instead of going blind to them for a week.
- [x] **Playoff points as counts** [per user: "playoff points, regular season
  points, playoff − regular season", player_all_time + team sheets where
  missing]: player_all_time `Regular-season points as starter`, `Playoff points
  as starter`, `Playoff minus regular-season points as starter` (the counts
  behind the PPG split: same Semifinal + Final definition, 0 with no start in a
  phase); team_all_time `Regular-season points`, `Playoff points`, `Playoff
  minus regular-season points` (team PF; the "Playoff record" games — Semifinal
  + Final — so a higher seed's semifinal carries the +5). team_all_time had
  only the per-game clutch index (`Playoff PF minus regular-season PF`; it
  counted the 3rd Place game until the playoff-definition entry below). Not added to team_year: a
  season's playoff total is 0 until the playoffs, so the email's on-pace
  projection would scale that 0 by weeks played and report noise every week of
  the regular season. Additive only (offline build: 6 new columns, 6 Formulas
  rows, nothing else).
  - [x] **The two total differences dropped** [per user, on review]: `Playoff
    minus regular-season points as starter` and `Playoff minus regular-season
    points` subtracted TOTALS, so they were always about -11,000 to -12,000 and
    tracked regular-season volume, not playoff performance; the per-game
    columns carry that comparison.
  - [x] **Start counts added** [per user]: player_all_time `Regular-season
    games started` and `Playoff games started` (Semifinal + Final), the
    denominators of the two PPG columns. Every start counts, as in `Weeks as
    starter`; integer-formatted and banded with it.
- [x] **Position factor: previous season's until week 5** [per user, from the
  "no baseline before kickoff" note]: a season with fewer than 5 weeks played
  (the season in progress through week 4, and moves filed under it before
  kickoff) uses the PREVIOUS season's factor; once its week 5 is in, the whole
  season switches to its own — retroactively, as every build recomputes. A
  season past every one on record uses the latest (was: no baseline -> 1.0).
  5 = `digest.MIN_YEARLY_WEEK`, so an adjusted number settles the week the email
  first reports it; a test keeps the two equal. Moved to
  `lotg_support.position_factor` (unit-tested on synthetic seasons in
  `tests/test_position_factor.py` — the offline harness stops at 2025, where
  every season is complete, so it cannot see the rule). Reaches EVERY
  `_pos_factor` caller, including existing columns and the handcuff test's
  TE-equivalent threshold, but only for the season in progress: on the committed
  exports 2026 (2 weeks) now uses 2025's factors (TE 1.232 instead of a
  two-week 1.356). Completed seasons are untouched.
- [x] **Email: "Records" and "Leaderboard changes"** [per user]: the new-data
  half of the digest is two visually distinct parts — a gold-ruled "Records"
  block (every first-place move: rank 1 at either end, any board, single-season
  records included) then a navy-ruled "Leaderboard changes" block (everything
  else, milestones included). On-pace 1sts are NOT records [per user, on
  review]: the "On pace this season" sections stay whole under Leaderboard
  changes — a projection is not a record yet. Inside each, the usual sections
  in the usual order and grouping, one heading level down
  (`digest.split_records` / `_part_html`). The lede and the edits section are
  unchanged. Guard: `check_records_and_leaderboard_changes_are_two_parts`.
- [x] **One playoff definition on every sheet** [per user]: playoff = the
  championship bracket's Semifinal + Final ONLY; regular season = the "Week N"
  weeks before the playoffs start; 3rd Place and the toilet bracket (Toilet
  Semis / Final / Trash) count as NEITHER. Audit of every playoff / regular-
  season mask in the build: the bracket records (`_BRACKET`), the player
  playoff split, the playoff points counts and the standings-leader streak
  (weeks before `playoff_week_start`) already matched. Two did not and now do:
  team_all_time's clutch index (`Playoff PF minus regular-season PF`,
  `Playoff win % minus regular-season win %` — both counted 3rd Place as
  playoff) and Luck's postseason ×1.8 weight on the result-surprise part
  (`_POST` included 3rd Place, so the 3rd-place game's Luck — and every team_year
  / team_all_time Luck sum over it — moves). Formulas rows and
  plan/LUCK_REWORK.md updated. Guards in tests/test_ppg_position_adjusted.py:
  the clutch index recomputed from team_week, and no `isin` mask in src/lotg.py
  naming 3rd Place beside Semifinal/Final.
- [x] **3-part audit** on the first post-merge build — CLEAN, see
  `plan/AUDIT_ROUND14_446_AND_9PART.md` (runs 561/563 branch vs 562 same-time
  main; post-merge run 564 cell-identical to 563). Expected diff: the 64 new
  columns on seven sheets (the two total differences dropped, the two start
  counts added), their Formulas rows (and the four corrected ones), the
  3 stale-difference add_drops rows, the 6 fantasy-season add_drops rows (+ a
  ±0.1 O-Score ripple), the donut / points-threshold renames on the team and
  league sheets, the clutch index on teams that played a 3rd Place game and
  Luck on 3rd Place weeks (plus the team_year / team_all_time Luck sums and
  anything ranked on them), nothing else. The first Tuesday digest after merge lists the
  new player_year columns' on-pace standings once; boards stay silent on them
  for a week (new slots are absent from the prior snapshot).

## Wins added (trades + add_drops)
Asked for (2026-10-01): a wins added/lost formula for every trade and add/drop —
"for every week, would not making this move have changed if I won. +1 if switch
to win, −1 if switch to loss" — that handles Peter trading away McBride and
Oliverwkw's Waddle → Conner → Ekeler flip. One column on each sheet, `Wins added`
(after `Trade impact score` / `Player addition value`); the rule lives in
`lotg_support.wins_added`, the build only stores it.

Rules [per user, 2026-10-01]:
- Each week on its own against the real opponent; no re-seeding, no bracket
  replay. Playoffs, 3rd place and the toilet bracket count as normal weeks. The
  2026+ two-week final is ONE game (both weeks summed).
- Given-up assets count from the move to today — and keep counting after the
  returned assets are dropped or traded. A given-up pick = the player drafted
  with it. Two stops [per user, 2026-10-01, revised from "no cap" / "re-acquired
  = a different player" after the column summed to −726 / −522]: the count ends
  once the league lets him go (on no roster for 4 straight weeks) and when the
  team re-acquires him (the earlier move's count ends the week before).
- Lineage must scale with size: what a received asset is later traded for
  carries this move's share of that trade = KTC of the lineage inputs / KTC of
  the team's whole side on that trade's day (FAAB weight 0), read as a
  probability (averaged over removed / kept). Chosen over the integer
  majority-rule and production-share alternatives. Drops end lineage.
- FAAB is left out entirely (house rules move budgets untrackably). A
  FAAB-only sale is a pure drop; a FAAB-only purchase a pure add.
- Lineup: best feasible counterfactual lineup with no other start/sit decision —
  removed starters leave, arrivals may fill or displace if eligible and better,
  open slots no arrival fills go to the best eligible bench player (bench never
  displaces), players move between slots to keep it legal. A player started by
  nobody that week counts for at most 1.5 × his average over his previous 3 NFL
  games. Every substitution must be plausible [per user, 2026-10-01]: the
  incoming player's last-3-game average >= the outgoing player's − 5 (a forced
  fill vs the best-averaging legal filler). A player with fewer than 3 prior
  NFL games (a rookie's first three) never moves in, but can be moved out.
  The opponent's lineup changes only if its roster does.
- 2020 included (ESPN backfill via `espn_2020.emit_sleeper_2020`).

- [x] **`Wins added per season`** [per user, 2026-10-01] beside it on both
  sheets: Wins added × 17 / games the team has played since the move (the
  2026+ two-week final is one game; 17 for every year). A loss the week after a
  drop reads −17. N/A before the move's first game. A rate, so the weekly email
  holds a move off its boards until 5 weeks after it (`digest.BoardGate`,
  `EVENT_MIN_WEEKS`) like every other rate on the move sheets — no digest
  change needed; the test pins the classification. Chosen over "live games"
  (weeks something from the move was still in play) as the denominator: most
  drops are live ~4 weeks, so one flip read ±17 / ±8.5 and the board filled with
  2020 one-week flukes.
- [x] **One nflverse path (branch run 599 caught it).** The build first handed
  the engine its own `nfl_games_by_sid` while recomputes re-scored `.cache`
  through a looser sid → gsis bridge; the two disagreed on some players' 3-game
  history, so the plausibility / unproven tests flipped games (stevenb123's
  McBride row built 5, recomputed 6). Now the build persists its enriched bridge
  (Sleeper gsis with the last-name correction → DynastyProcess → nflverse) to
  `exports/raw/wins_added_gsis_bridge.csv` and both paths score through
  `wins_added.nflverse_points_from_cache` with it.
- [x] `lib/lotg_support/wins_added.py` (+ `explain()` for tracing a row week by
  week), the build hook at the end of `build_all` (before the KTC provenance
  dump), Plan CSV + `stats_catalog.json` + Formulas + schema pin + phrasing rows.
  Not build-volatile: like `Points added` it grows on old rows only as new weeks
  are played.
- [x] Guard: `tests/test_wins_added.py` — eight synthetic cases (slot movement,
  bench cap, forced fills only, the ±1 flip, opponent + mirror row, KTC-share
  lineage, drops end lineage, re-acquired player), every real lineup legal and
  every PF = starters (+5) over 2020–today, and a recompute of 24 sample rows
  against the exported column (skips on pre-merge exports; settled-by-completed-
  seasons rows without KTC-shared lineage only).
- Local recompute from the run-597 exports (2026 through week 3): every real
  lineup legal and every PF reconciled (832 team-weeks), 0 unresolved names, 186
  uncapped entries (players with no prior NFL game), nflverse re-scoring =
  Sleeper on 16,835 / 16,845 rostered player-weeks (10 stat corrections).
- **Negativity, diagnosed (2026-10-01).** As first built the column summed to
  −726 (trades) / −522 (add_drops) at run 597. Variants: the lineage window,
  the 4-week-unrostered stop and the re-acquisition stop each help add_drops
  (to −234 / −211 / −378) but barely move trades (−619 / −678 / −692). The
  main cause is hindsight in the lineup rule — a given-up player is compared
  with whichever starter happened to score worst that week. Deciding the
  lineup on prior form and scoring it on actual points gives trades +101
  (154 positive / 113 negative) and, with both stops, add_drops +4; the
  by-season slide (2020 trades −4.5 → 2025 −0.2) disappears. The two stops
  are adopted. Instead of deciding lineups on prior form, the user chose the
  plausibility test + unproven-rookie rule above (scoring stays on actual
  points): trades −179 (134 positive / 155 negative), add_drops −20 (78 / 89),
  562 rookie entries blocked; Spearman vs Trade impact score +0.38, vs
  Player addition value +0.25. A mild lean remains on old trades (2020 mean
  −1.06, 2025 0.00).
  Old moves swinging more games than new ones is intended [per user] — no
  per-season normalisation.
- [x] **3-part audit — PASS (2026-10-01): post-merge run 604 (merge `4c37f25`, #458)
  vs the last pre-merge main run 597** (one post-merge build, no paired base —
  per user). Branch runs 599-603 caught two bugs before merge (build vs
  recompute nflverse bridge; rate 0-filled instead of N/A), both fixed.
  Part 1: 526 passed / 2 standing skips, both new guards ran, no build ERROR
  today, `INFO wins added: 2176 rows … 0 guard warnings, unresolved []`;
  exports committed (ae35b04), email/rotation skipped. Part 2: an independent
  recompute from run 604's own sheets + its persisted bridge reproduces EVERY
  row — 1,795 non-KTC rows directly, the 381 KTC-share rows with the build's
  player KTC replayed from `raw/ktc_provenance.csv`; rate = total × 17 / games
  on all 2,176. Cases: stevenb123 McBride +6 (2023 wk15, 2024 wk5/6/12/17, 2025
  wk7) with plehv79's mirror −1 at 2024 wk5/12; LWebs53's Kyren drop 0 and the
  Taylor trade −7.07; Waddle trade carries Ekeler/Burks at 0.245; all 39
  FAAB-only sales equal the same move as a pure drop; week-1 rookies (Caleb
  Douglas, Denzel Boston, Kenyon Sadiq) cannot enter a counterfactual; 2020 rows
  populated; the one no-game move reads N/A; plehv79 2023 In Progress / 2024 2,
  every 2026 streak N/A, 56/56 team-seasons recompute. Part 3: only the two new
  columns, `Winning season streak` (13 cells, exactly the previewed rows), 2
  Formulas rows + 1 edited; everything else is wall-clock tenure or the daily
  KTC "years later" roll (and the O-Score / skill columns reading it). No row
  added or removed.
- [x] **Fix: forced fills with two+ open slots** (found 2026-10-01 while porting
  the rule to `whatif.py`'s plausible model). `cf_lineup_points` judged EVERY
  forced fill against the single best-averaging legal filler, so with two
  starters removed the second slot usually stayed empty — 2025 wk 14, Lamar +
  Godwin out of shmuel256, every WR measured against Herbert's QB average.
  Now the bar is the h-th best filler (h = open slots). Impact on run 604's
  data (build bridge + KTC replayed from provenance): trades 138 / 566 rows
  move (135 down, 3 up; sum −183 → −283), add_drops 32 / 1,610 (all down;
  −14 → −21) — the empty slot had been crediting multi-starter returns (LWebs53
  2020 startup swap +9.67 → +3.49; shmuel256 2023 Kamara trade +4 → −1). Unit
  test pins the two-hole case. 3-part audit vs run 604 after merge.
  **Extended [per user]: the lineup rule is slot-aware.** Checking the
  2022-09-27 Jefferson 4-for-1 (shmuel256 / LWebs53) week by week showed (a)
  slots left EMPTY when no bench player passed plausibility or scored > 0
  (shmuel256 2024 wk 6-7: 9 of 10 filled) and (b) a bench player benching a
  real starter through a slot reshuffle — the count-based check let LWebs53
  2022 wk 8 start Geno Smith for Tom Brady. Now: the pool is the real roster
  minus the move's return plus what it gave up; every cleared slot is filled
  by a different player (plausible first, else best eligible); a given-up
  player takes one explicit role (fill a cleared slot / a real empty slot /
  displace one named starter); a bench player only fills a cleared slot,
  directly or by one starter sliding into it. Unit tests: no bench-for-starter
  reshuffle, a 0-point filler still fills, the 4-for-1 shape.
  **Then, per user, three more rules:** given-up players come first for
  cleared slots (LWebs53 2022 wk 5: Adams belongs in Jefferson's slot, not
  Adams into Aaron Jones' flex with bench Reynolds in Jefferson's slot); a real
  starter still on the roster never sits while a real bench player starts;
  a rookie in his first 3 games may move in if he really started that week.
  Filling every cleared slot ranks before points. The bench fill is a
  legality-checked search over the whole lineup (a one-slide approximation let
  two fillers lean on the same slide and left slots empty).
  **Final rules [per user]** — the sequence: (1) the move's return comes off
  the lineup and the bench, leaving its slots empty; (2) what it gave up joins
  the bench; (3) the empty slots fill from the bench, given-up and real bench
  players competing on points, each filler within 5 of the h-th best option
  (best eligible if nobody is); (4) a remaining given-up player who outscored a
  starter, is within 5 of that starter's 3-game average and fits (after
  rearranging) swaps in; (5) re-decide the game. Kept on top of the sequence:
  a real starter still on the roster never sits while a real bench player
  starts, and the best lineup obeying every rule is taken (filled slots, then
  fewest implausible fillers, then points). Given-up-first priority for empty
  slots was tried and dropped. Search: over (given-up players used, starters
  displaced) with a bound, the bench fill exact by matroid greedy, lineups
  cached — 88 s for every row (a role-by-role search took 41 min).
  Full local sweep: 28,656 counterfactual lineups, every move and week, keep
  every rule. vs run 604: trades 177 / 566 rows move (−183 → −135), add_drops
  41 (−14 → −18).
  Guard: `test_counterfactual_lineups_keep_the_rules_on_real_moves` checks
  every counterfactual lineup of the Jefferson 4-for-1 and a spread of moves
  (1,367 lineups): pool = roster − return + given-up, the starter-before-bench
  invariant, no cleared slot empty while an eligible proven player sits, no
  unproven entrant who did not really start.
  **3-part audit — PASS (2026-10-02): post-merge run 610 (merge `df151ca`,
  #459) vs the last pre-merge main run 607** (branch runs 605-609; 608
  cancelled mid-rework). Part 1: 532 passed / 2 standing skips — both the
  real-move lineup guard and the recompute guard ran; no build ERROR; `0 guard
  warnings, unresolved []`; exports committed (d8d8fdd); email / rotation
  skipped. Part 2: an independent recompute of run 610 from its own sheets +
  bridge reproduces all 2,176 rows (381 KTC-share rows with the build's player
  KTC replayed from provenance); rate = total × 17 / games everywhere; the
  Jefferson 4-for-1 weeks fill every slot (LWebs53 2022 wk 5: Adams, Evans,
  Cook, Rodgers in; wk 8 Brady stays; shmuel256 four cleared slots → four
  different players). Part 3: only `Wins added` (177 trades / 41 add_drops
  rows — exactly the predicted set) and `Wins added per season` (172 / 37; the
  rest round the same), one Formulas note; everything else is wall-clock tenure
  or the daily KTC "2 years later" roll and the add_drops O-Score / Add/Drop
  skill reading it. No row added or removed.
- [x] **Trade impact score's win term IS Wins added** [per user, 2026-10-02 —
  revised from "match its would-he-have-played test": feeding Wins added in
  keeps the score a distinct metric (a z-scored blend of five signals) without
  a second, cruder win counterfactual inside it]. The old term (`_tpi_wins` +
  KTC-share downstream credit) only looked at weeks a received player started
  (always 0 on 313 / 566 trades), swapped in the top-k given-up scorers with
  hindsight and never adjusted the opponent; removed with its downstream
  machinery and margin map. Wins added now computes ONCE, just before the
  composite (dates through the same UTC → Eastern conversion the export uses),
  for both sheets — the end-of-build pass is gone. Expected: Trade impact score
  and the trades O-Score / Trading skill move; Wins added identical to run 614.
  `Points lost` left alone [per user]: it never builds a lineup (raw given-up
  points over weeks a received player started); measured on run 607 it reads
  2.4x the given-up players' plausible-start points on 1-3 player trades, ~10%
  below a full replacement view — recorded, by design.
  **3-part audit — PASS (2026-10-02): post-merge run 617 (merge `db94b6a`,
  #460) vs the last pre-merge main run 614** (branch runs 615-616; 615 caught
  the early pass reading the pick frame's "Final Team" — fixed). Part 1: 554
  passed / 2 standing skips; no build ERROR; wins added `0 guard warnings,
  unresolved []`; no exports commit (no roster change); email / rotation
  skipped. Part 2: Trade impact score recomputed from the exported columns
  (0.6 × Σ w·z, Wins added ×2.0 as the win term) matches 566 / 566; Wins added
  identical to run 614 on every row (branch 616); Burrow (AceMatthew
  2022-09-28) Wins added −4.0 → score −2.1, O-Score 75.9 → 55.9. Part 3: Trade
  impact score (559 rows), trades O-Score (561 — its change equals the Trade
  impact score percentile change / 4: corr 1.0, median residual 0.04), Trading
  skill (54 team_year / 8 all-time), 2 Formulas rows; the rest is the 2026 wk 4
  Thursday game's stats arriving (player points, dropped / career PPG and the
  add_drops / pick O-Score and skills reading them). No row added or removed.
- [x] **Build runtime** (#463 / `3837869`, outputs unchanged). Job wall time
  roughly halved: build step 9m43s → 3m25s, test step 8m54s → 2m01s, digest
  16s → 3s (run 617 → 619). Wins added: displacer matching by depth-first
  walk over valid assignments (not every permutation) + legality cached by
  eligibility profile per season; `replay.is_legal` builds slot sets once.
  Boldness: promotion events from one itertuples pass, base expectations
  without a Python agg lambda / `.at` lookups. Workbook: per-column data-cell
  styles memoised and copied (openpyxl's per-assignment style hashing). Digest:
  `two_sided_columns` / `rank_column` without per-column iterrows. CI:
  pytest-xdist `-n auto` in build.yml and the health email; conftest writes
  `pytest_results.json` from the xdist controller only.
  **Audit — PASS (2026-10-02): post-merge run 619 vs the last pre-merge main
  run 617** (branch run 618 identical). Every export CSV byte-identical; xlsx
  identical but for `docProps/core.xml` (timestamp); digest HTML identical
  (build-inputs fingerprint changes on any code merge, by design); test
  results identical test by test (554 passed / 2 standing skips, same skip
  reasons). Remaining build time is spread: workbook ~77s, wins added ~50s,
  boldness ~45s (offline-build measurement).
- [x] **Boldness + Lineup Boldness + live-season outcome fixes** (#461, merged
  before a branch build and reverted in e8eaa35; re-landed as #462 / `8c7c207`
  with two fixes from branch build 612). Fix 1: Lineup Boldness fed the single-*current*-position
  `compute_optimal_lineup`, so Cordarrelle Patterson (WR-eligible in 2021) was locked out of WR
  and stevenb123 2021 wk9's ex-ante max came out below the lineup set. It is now
  `best_lineup_value`, which is exact and uses per-season eligibility. Fix 2: no-history
  starters (Rivers 2025 wk15, Etienne 2022 wk1) now take the positional prior instead of N/A.
  **3-part audit — PASS (2026-10-02): post-merge run 614 vs the last pre-merge main run
  610** (branch runs 612, 613). Part 1: 550 passed / 2 standing skips; no new build ERROR
  (the 8 KTC 403s also appear in 610); `boldness: 7771 starts, 832 lineups in 133s`; exports
  committed (2bcdf89). Part 2: no bench row has Boldness and every starter does; 0 negatives;
  0 lineups below their boldest start; team_year / team_all_time = the mean of team_week
  (0 mismatches); the 2020 ESPN season is included (1,150 starts). The 2026 outcome cells
  are blank: 8 eliminations, the tiebreaker, and 3×320 champion flags. Completed seasons
  are untouched: 4 bracket zeros per year, and all-time championship counts unchanged.
  Inquiry-path recompute of 2020 wk5 / 2023 wk7 / 2026 wk3 is within 0.05 per start (β
  calibrated on the committed rather than the build's inputs). Part 3: vs 610 only the new
  columns, the 2026 cells above, and formulas (+2 rows, 2 notes); no row added or removed.
  **Needs human judgment:**
  - a dead start (`Starter unavailable?`, e.g. Chris Rodriguez 2025 wk15 = 3.39) is scored
    like any other start;
  - Etienne 2022 wk1 now reads 8.12 bold because the RB positional prior knows nothing of
    his role;
  - Lineup Boldness exceeds the sum of start Boldness on 5 empty-slot weeks, the biggest
    being plehv79's thrown 2022 wk16 (74.18).
- [x] **Boldness: empty slots and dead starts are not boldness; `Empty slots` column** (#464 /
  `866dc04`) [per user, 2026-10-02]. Lineup Boldness now judges only the filled slots, and a
  starter's reference must take his place among them. A dead start (flagged bye / injured /
  suspended, scored 0) is judged the same way: N/A, slot out. The new `Empty slots` is a count
  on team_week, summed on team_year / team_all_time; dead starts are not counted. Also fixed
  the #463 `-n auto` race in `test_reads_are_pure` (it read `exports/raw/pytest.log` mid-write;
  this failed branch run 620). The season-relative Lineup Boldness for the 2024 second flex was
  declined: leave it as is.
  **3-part audit — PASS (2026-10-02): post-merge run 623 vs the last pre-merge main run 619**
  (branch runs 620, 622; 621 cancelled). Part 1: 557 passed / 2 standing skips, no new build
  ERROR, exports committed (050cc87); 623 is cell-identical to branch run 622. Part 2:
  - `Empty slots` > 0 on exactly 6 team-weeks: plehv79 2022 wk16 = 6 and wk17 = 2,
    JacobRosenzweig 2022 wk13 and wk17 = 1, shmuel256 2020 Final = 2, LWebs53 2025 wk9 = 1;
  - year / all-time sums and the Lineup Boldness means reconcile (0 mismatches);
  - the 26 starters without Boldness are exactly the 26 dead starts;
  - every changed lineup holds an empty slot or a dead start;
  - 0 lineups fall below their boldest start.

  Part 3: only Boldness (35 cells), Lineup Boldness (11 / 8 / 5), the new column, and formulas
  (+1 row) changed; no row was added or removed.
- [x] **Boldness inquiry ↔ export parity** (#465 / `f31128c`). Two causes, both fixed:
  - beta's calibration picked up the league-roster fallback from #462, so build and snapshot
    inputs gave different beta (RB 0.8762 vs 0.8753); it is now NFL-only (RB 0.8741);
  - outside the build, "any points" scored the week in progress; it now stops at the
    committed build's last team_week.

  **3-part audit — PASS (2026-10-02): post-merge run 625 vs the last pre-merge main run
  623** (branch run 624). Part 1: 559 passed / 2 standing skips, no new ERROR. Exports NOT
  committed: no roster change; they land with Tuesday's cron, per the no-force rule. Part 2:
  the inquiry path vs 625's exports differs on 0 of 7,771 starts and 0 of 832 lineups;
  Empty slots and the dead-start / sum invariants are unchanged. Part 3: only Boldness (176
  cells), Lineup Boldness (97 team-weeks, 15 team-years), each by hundredths (undoing #462's
  beta ripple); 625 is cell-identical to 624. Open (needs judgment): `Q.played_weeks` still
  counts a live week as played for analysis / draft_capital / forecast / replay.
- [x] **Inquiry: played weeks are final weeks** (#466 / `8a1a3cb`). `Q.played_weeks` counted
  any week with points, so from Thursday night analysis / draft_capital / forecast / replay
  read the live week's partial scores as final. Today's 2026 forecast would have booked wk4
  with roster 4 on 15.6 and the rest on 0. It now stops at `Q.finalized_week` (the committed
  build's last team_week). The forecast's in-season switch keeps "has kickoff happened" via
  `include_in_progress=True`. Inquiry-only.
  **3-part audit — PASS (2026-10-02): post-merge run 627 vs the last pre-merge main run 625**
  (branch run 626). Part 1: 560 passed / 2 standing skips, no new ERROR, exports committed
  (ae00446; this also lands #465's values). Part 2:
  - 2026 played = [1, 2, 3], started = [1, 2, 3, 4], forecast observed = [1, 2, 3];
  - boldness inquiry vs the committed exports: 0 of 7,771 starts and 0 of 832 lineups differ.

  Part 3: 627 is cell-identical to both 625 and 626.

## Sequential re-audit of #446–#455 + winning-season streak fix (2026-10-01)
Asked for: re-do every audit since #446 against SEQUENTIAL main builds (last
pre-merge run → first post-merge run), in case the paired same-time
`audit-base` convention hid a change. Pairs 560→564 (#446/#447), 564→567
(#448), 567→568 (#449), 568→570 (no PR), 570→581 (#450/#452; run 571 was a
guard-skipped fire), 581→584 (#453), 584→589 (#454), 589→597 (#455).
- [x] **No missed PR change** (doc nit: #452's body says "Unchanged: the received
  side" though its pick-held rule moved 15 received-side rows — the rule itself
  says so; behaviour is as intended). Every completed-season change in a non-volatile
  column is the PR's own documented change (#446 twins + renames + position
  factor; #448 move counts / trade-week clock; #452 dropped points as scored,
  sent-side window, pick-held rule — which also moves the received side, despite
  the PR body's "Unchanged: the received side" line; #455 trades Difference of
  averages N/A on 111 rows with no received side — confirmed caused by #455:
  same-time base run 598 kept the values) or live drift by design (open
  windows into 2026, career averages, the all-time pooled Positional scoring
  percentile and the tier % / streak columns on it, the all-time vs-opponent
  streaks, wall-clock Tenure). Formulas rows track the PRs exactly; no
  completed-season row was added or removed in any pair.
- [x] **Fixed: `Winning season streak` counted the in-progress season** (found in
  568→570, not caused by any PR, invisible to a same-time pair). 2026's
  provisional Win % extended the run at 1-1 and broke it at 1-2, flipping
  completed rows week to week. Now [per user]: the streak reads the REGULAR-
  season record across the board (playoff / consolation games don't count), and
  a season counts once it is decided — .500 clinched even losing out extends
  it, .500 out of reach even winning out breaks it, otherwise N/A and the run
  is left alone (a finished regular season is always decided). Regular-season
  games = playoff start − 1 (2020: 14, 2021-25: 15, 2026: 14). On run 597's
  data 13 of 56 team_year rows move: every 2026 row → N/A (nobody decided at
  week 3), plehv79 2024 (8-9 overall, 8-7 regular) becomes a winning season
  (2023 → In Progress, 2024 → 2), and the 2025 rows of AceMatthew / shmuel256 /
  stevenb123 read their run length instead of In Progress. Guard:
  `tests/test_winning_season_streak.py`. Expected diff: team_year `Winning
  season streak` only + its Formulas row.

## Points above expectation (player_additions, follow-up to #389)
- [x] **Price paid (FAAB) + Points above expectation (total / rate)** (#467 / `764f709`) [per user,
  2026-10-03]. Three new player_additions columns, `lotg_support.acquisition`;
  design and model-selection evidence in `plan/notes/POINTS_ABOVE_EXPECTATION.md`.
  Total = X − Y over the weeks he was rostered, Y = what same-channel,
  same-price, same-position acquisitions actually scored over the same weeks
  since acquisition, never-cut (a peer's off-roster week counts what he scored
  elsewhere). Rate = total ÷ weeks rostered. Price in FAAB $ (FA / $0 claim 0,
  the bid, draft slot's expected draft-day KTC ÷ 100, trade sent side's
  dollars on the money curve — KTC places an asset on the rookie board, a mid first = $1,000, KTC/100 below the 4.08, set in the day's market — the field's 49th player = $1,000, above by standing over the top 10 (best player averages $3,500), below half that market effect blended with the board; a player priced above replacement (the league's last rostered spot, faded; nearest covered date when KTC data is thin); picks on a market-relative board (draft-day ratio to the anchor × the day's anchor); a traded pick's slot is projected from what was knowable — roster strength preseason, blended into the order stat (record; Max PF within the bottom four from 2026) by week 8, then the rule and the bracket after the regular season — never the eventual slot (a look-back found hindsight no closer to how teams traded); trades sum dollars and split by dollars; every traded pick priced on the board (slot, or round average) × 0.95 per draft beyond the next (user; the league-trade fit of 0.80 was too steep); per user, option B). Additive: no existing
  column changes except as below. Expected diff: the 3 new columns + Formulas
  rows. Build log line `points above expectation: N additions, U unpriced, B
  trade sides off the exported KTC margin` — B must be 0. Guard:
  `tests/test_acquisition.py`.
  Unquoted picks [per user, 2026-10-03]: branch run 37148919888 left 9 rows (5
  late-2020 trade sides) unpriced, every unvalued asset a 2021+ pick traded
  before KTC priced picks — and the trades sheet silently LEFT those picks out
  of its KTC columns. A pick with no quote on a date is now estimated from the
  same pick 1-3 classes later at the same lead time before its draft
  (`_pick_ktc_estimate`, inside `_side_values`; logged `pick KTC estimated`),
  so trades' KTC value differences, Pick value received and Change in pick
  value at draft time move on those deals (and O-Score / Trading skill /
  Trade impact score with them). Startup (2020) picks are never estimated:
  branch run 37149868441 priced the startup pick swap's 4ths/5ths as rookie
  4ths (Pick value received 3,350 on T#1 / T#155) — not a similar asset.
  **3-part audit — PASS (2026-10-04): post-merge run 648 vs the last pre-merge main run
  627** (branch runs 37148919888 … 37170007545). Part 1: 583 passed / 2 standing skips, no
  build ERROR (the only matches are "data-quality sanity: 0 ERROR"), log line `1971
  additions, 0 unpriced, 0 trade sides off the exported KTC margin`; exports committed
  (`0602a63`, roster change). Part 2 (15 checks, all pass): free agency $0 (611), waiver =
  winning bid (489), commissioner blank (6), rookie 5.0X = $20 (9), FAAB-only buys = the
  dollars (33 trades); no pick above the one before it in all 8 drafts, startup 1.01 CMC
  $3,457 > 1.04 Cook $2,686; Cook (Luke, 2020-11-29) the top price $5,605, McBride for a
  2025 4th $20.5, the 2026-07-10 Oliverwkw trade fully priced; rate = total ÷ weeks, never-
  rostered 0 / 0 (337), this week's move 0, short holds centred (mean −1.2 over 755),
  Formulas rows present. Part 3: only the 3 new columns and 3 Formulas rows, plus — by
  design — the 5 late-2020 trades' KTC margins / Pick value received / Change in pick
  value (pick estimate) and their relative ripple (Trade impact score 61, O-Score 279,
  Trading skill 28, Add/Drop skill 7); clock / rolling drift (Tenure days 247, Length of
  tenure, KTC N years later incl. a 2024-10-03 trade reaching its 2-year mark). No row
  added or removed. Open: digest — exempt stats locked at the move from the 5-week gate
  (separate PR, per user).

## Digest: stats locked at the move skip the 5-week gate
- [x] **#468 3-part audit PASS** (post-merge run 37212429492 vs pre-merge main run 648):
  code reviewed + 583 guards green; results — the 15 rule-flagged lines (Mooney, Trigg,
  Okonkwo, Love, Ferguson, Royals, Z. Branch, MarShawn Lloyd…) all in "Changes from edits,
  not new data", 1 item with the news, lede as before, snapshot written via
  `--write-snapshot`; diff — 0 cells differ across all 15 export sheets (digest-only change).
- [x] **`digest.LOCKED_AT_MOVE`** [per user, 2026-10-03, all sheets]. A trade, add/drop,
  pickup or draft-pick row used to stand only on the high end of a counting stat until
  `EVENT_MIN_WEEKS` (5) NFL weeks after the move. Columns the move fixes the moment it is
  made have no sample to wait for and now stand on every end at once: deal-time KTC values,
  Pick value received, pre-move form (PPG of 5 games before), FAAB bids and margins, Price
  paid (FAAB), KTC at pickup / on draft day, ages at the move, asset counts, and Tanking
  (user: a judgement of the move when made). Listed explicitly (not by name pattern); not
  locked: cuff flags (not digest boards), pick-adjusted differences (their pools move),
  "N years later" checkpoints. Guards: `check_locked_at_move_columns_skip_the_wait`,
  `check_locked_at_move_columns_exist`.
- [x] **A gate-rule change is an edit, not news** [per user, 2026-10-03]. The snapshot
  meta records every gate setting it ranked under (`gate_rules`: LOCKED_AT_MOVE, the
  5-week event wait, the week-8 rookie wait, the yearly week-5 wait).
  `mark_rule_releases` re-ranks this week's frames under the prior run's rules (a
  snapshot without them = nothing locked, today's waits) and flags each event line whose
  place differs under them, plus each all-time player-board line of a rookie the old
  week-8 rule would still hold (`rule_release`); `email_summary.attribute` sends those
  to "Changes from edits, not new data" even when the inputs fingerprint is unchanged
  (digest.py is not fingerprinted). Brand-new moves stay news. Unchanged rules flag
  nothing, and a week with no build change puts nothing in the edits section (quiet-week
  replay: 0 / 0). Guard: `check_a_gate_rule_change_goes_to_the_edits_section`.
  Effect on today's digest (committed exports): 14 changed lines, all on locked columns
  of young moves (e.g. 2026 1.01 Jeremiyah Love's 7,573 KTC on draft day); 15 lines
  flagged (the 13 releases + 2 rows they pushed down), all in the edits section with the
  2025 Mac Jones recompute; 1 item with the news; the lede reads as main's.
- [x] **`scripts/build_digest.py` only writes the snapshot with `--write-snapshot`**
  (CI passes it in build.yml). It used to overwrite whatever `--snapshot` it was given,
  so a by-hand comparison's second run diffed against the first's output. Guard:
  `check_year_round_build` step 3 (a run without the flag leaves the file byte-identical).

## Points above expectation: per-position tenure curves
- [x] **#469 3-part audit PASS** (post-merge run 37216195042 vs pre-merge main run
  37212429492): code reviewed, 586 guards green (3 new tenure tests fail on the old model);
  results — Mahomes −87 → +289, Kelce 492 → 608, Jacobs 607 → 514, Chubb 49 → −38, Watson
  −702 → −548, matching the pre-merge dump experiment to 0.005; rate = total ÷ weeks, never-
  rostered 0, commissioner blank all hold; diff — only `Points above expectation (total /
  rate)` moved (1,624 / 1,613 cells, corr 0.989 / 0.986), every other cell of all 15 sheets
  identical; the post-merge player_additions equals the branch build's byte for byte.
- [x] **`acquisition.points_above_expectation`** [per user, 2026-10-04: "tenure, not age";
  must stay accurate in 10/15/20 years]. Free agency fitted alone; paid channels pooled
  with their own price curves + shared position knots, per-position offseason slope,
  position × price-percentile × tenure; piecewise-linear offseason curve with data-driven
  hinges (`MIN_TENURE_ADDITIONS`) and doubling knots — no named horizon. Ridge 30.
  Replay of the build as of 2022-26: calibration RMS 0.03-0.04 every year (old drifted
  0.071 → 0.132; oldest-tenure error 0.03 → 0.33). Guards:
  `test_each_position_ages_on_its_own_tenure_curve`,
  `test_expectation_keeps_working_as_history_grows` (15-season synthetic league),
  `test_long_held_rb_is_the_surprise_not_the_qb` (all three fail on the old model).
  Evidence: plan/notes/POINTS_ABOVE_EXPECTATION.md "Tenure curves".
- [ ] **Yearly re-check of the expectation model** [per user, 2026-10-04] — once a season,
  after the championship. The model refits every build and grows its own hinges/knots,
  but its settings (EXPECTATION_RIDGE 30, MIN_TENURE_ADDITIONS 40, BASE_KNOT_WEEKS,
  TAIL_QUANTILE 0.95) were tuned on 2020-26 data. `lotg_support.expectation_recheck`
  replays the build as of each past season (out of fold, only what was known then) on the
  model's inputs, which every build writes to `exports/raw/pae_additions.json.gz`
  (artifact only, gitignored):
  ```
  gh run download <run id> -n LOTG_outputs -D /tmp/lotg
  PYTHONPATH=lib python scripts/pae_recheck.py --dump /tmp/lotg/raw/pae_additions.json.gz
  ```
  Baseline (2026-10-04, as of 2022-26): calibration 0.040 / 0.032 / 0.034 / 0.031 / 0.038,
  oldest-tenure error <= 0.06. It prints "ok" or "RE-TUNE: ..." — act past calibration 0.06,
  oldest-tenure 0.10, or calibration rising two seasons running: sweep the four settings
  (and the ablations in plan/notes/POINTS_ABOVE_EXPECTATION.md), change only what the
  replay supports, as a build PR with the 3-part audit. Record each year's table here.
  Weekly early warning: `test_latest_season_inside_the_retune_limits` replays the latest
  season on every build (~5 s) and fails past the same limits.

## Phase 15 — TBD: OLD LEAGUES
- [ ] **TBD.** Placeholder for integrating other historical/old leagues' data (e.g. the
  separate ESPN leagues seen in the 2020 emails — UChicago '24 = leagueId 57687541, UChi
  Fantasy = 54022297 — and any earlier seasons). Scope, sources, and whether they belong in
  this dataset at all to be decided later. Reuse the Phase-13 ESPN dump script + loader
  pattern where applicable.
- **Design note (2026-09-26, per user): redraft data only affects the "Records" part
  of the weekly email.** Whatever old-league / redraft data Phase 15 brings in may
  set or break FIRST-PLACE marks (the digest's "Records" block — `digest.is_record`,
  rank 1 at either end, projections excluded), but it must not reach the "Leaderboard changes" block: no
  2nd-5th place moves, on-pace standings, event-board shuffles or milestones driven
  by redraft rows. Design the integration (which boards redraft rows enter, how
  they are keyed in the rank snapshot) so that holds.
- **Plan (2026-09-27, per user):**
  - **Separate redraft-inclusive sheets.** Recreate the team, player and league
    sheets with every piece of data we can find, including the redraft years. These
    live *alongside* the main sheets, not merged into them: the main sheets stay
    2020+ and unchanged.
  - **Email asterisks.** In the weekly email's "Records" block, mark with an
    asterisk (`*`) any record that is *also* a record when the redraft years are
    included. The records themselves are still decided on the main (2020+) data;
    the asterisk only says that the mark also holds over the longer history. Add
    a one-line legend to the email explaining the asterisk.
- **Data status (checked 2026-09-27):** nothing pre-2020 is in the repo. The
  redraft years are earlier seasons of the *same* ESPN league: 34086's metadata
  lists `previousSeasons: [2017, 2018, 2019]`. Without login cookies, the ESPN API
  returns 401 for 2018/2019 (they exist but are private) and 404 for 2017 through
  the league-history endpoint (unclear: may need the login, or may be gone). To
  pull them, the commissioner runs `scripts/espn_dump_2020.py --season 2019` / `2018`
  with their `espn_s2`/`SWID` cookies. 2017 needs a small change to use the
  league-history endpoint. Unverified until then: whether per-week lineups (not
  just scores) survive for the older seasons, and whether ESPN's player IDs from
  those years map through `player_id_map.csv`.

## Boldness: next man up + two-term lift (from the 2026 wk 4 inquiry)
- [x] **#470 3-part audit PASS** (post-merge run 37217627715, merge `84edf9d`, vs
  pre-merge main run 37216195042; branch run 37217067618 identical cell for cell).
  Part 1: 588 passed / 2 standing skips; no ERROR in this run's build_debug.log;
  `boldness: 7771 starts, 832 lineups`; email / rotation skipped; no exports commit
  (code-only merge, lands Tuesday). Part 2: next man up must have appeared for the team
  (2025: 25 → 5 events off-rule, the 5 are the `used or present` fallback); changed picks
  match who really started — 2023 wk 9 MIN Jaren Hall (not Dobbs, who had played only
  for ARI), 2024 wk 10 DAL Cooper Rush (not Trey Lance), 2024 wk 14 SF Isaac Guerendo
  (not Ke'Shawn Vaughn), 2024 wk 18 CLE Dorian Thompson-Robinson (not Bailey Zappe);
  lift (a, b) QB .36/.69, RB .37/.84, WR .09/1.14, TE .20/1.01; Mike Davis 2020 wk 3 by
  hand .373 × 22.80 + .843 × 5.99 = 13.55 = model, Hayden Hurst's exported 6.38 =
  13.55 − 7.17; 0 negatives, 0 lineups below their boldest start, team_year = mean of
  team_week (≤ 0.005 rounding); Formulas row updated. Part 3: only player_week
  Boldness (694), team_week (295) / team_year (49) / team_all_time (8) Lineup Boldness
  and 1 Formulas row moved; the other 11 sheets identical. Top 3 all-time unchanged;
  largest move LWebs53 2022 wk 12, 9.98 → 2.54.
  - needs-human-judgment: which backup is "next" in an ambiguous backfield. 2026 wk 4
    MIA: the model lifts Ollie Gordon (E 4.72, had the week-3 work) and Sleeper's
    current depth chart lists Jaylen Wright first. The depth chart is current-only,
    so it cannot be used historically.
  - by-design: WR b = 1.14. A promoted WR gets about 14% over his own E, and his
    starter's E barely matters (a = .09). That is what the data fit.
  - by-design: the fit uses only backups who played that week (the same selection as
    before).
- [x] **#471 next man up by touches** [per user, 2026-10-04: "the player who got the most
  touches ... in games where the players being compared were healthy"]. 3-part audit
  PASS on the boldness change (post-merge run 37220023483, merge `55fea81`, vs #470's
  run 37217627715; branch run 37219361784 identical cell for cell). Part 1: boldness
  `7771 starts, 832 lineups`, no ERROR; **1 unrelated failure** —
  `test_every_sleeper_status_pair_is_classified`: Sleeper started emitting
  injury_status "Active" (status Active) for one player, free agent Joe Mixon, between
  the branch run and this one. needs-human-judgment: add a designation or an
  UNDECIDED_STATUS_PAIRS entry. Boldness treats it as available (not in
  LIVE_OUT_STATUSES), which is right. Part 2: D'Ernest Johnson 2021 wk 10 (Chubb out,
  21.7 pts) now gets the CLE lift, so Oliverwkw's lineup 7.17 → 1.91; 2026 wk 4 MIA lifts
  Gordon (3 v 2 touches in their one shared game); 0 negatives, 0 lineups below their
  boldest start, team_year = mean of team_week (≤ 0.005); Formulas row updated.
  Part 3: only player_week Boldness (526), team_week (253) / team_year (42) /
  team_all_time (8) Lineup Boldness and 1 Formulas row moved.
  - needs-human-judgment: **WR picks.** On the 102 WR events where the rules disagree,
    the target-based pick out-targeted the E pick in the absence week only 40% vs 48%,
    yet the lift RMSE is better (7.22 vs 7.33). RB 62% vs 36%, TE 56% vs 37%, QB 4/5.
  - needs-human-judgment: **one shared game decides 68 of 242 differing events**, and
    on those the touch pick wins 51% vs 46% (barely better than a coin flip). Possible
    fix: require ≥ 2 shared games, otherwise use E. Not built.
- [ ] **`Empty slots` counts dead starts** [per user, 2026-10-05: "count starting out
  (injured, suspended, bye) players as an empty slot"]. Reverses #464's "dead starts are not
  counted". A dead start is unchanged: a starter flagged bye / injured / suspended who scored
  0 (a flagged starter who scored keeps his slot and is not counted). Lineup Boldness is
  unchanged — dead starts were already out of the comparison. Local preview (snapshot +
  nflverse cache, not the audit source): 26 dead starts (= #464's audited 26) on 23
  team-weeks; team_week total 13 → 39 (2020: 2 → 10; 2021–25: 11 → 29).
  Merged #476 / `6d74c1f` after branch run 667 (all steps green, no error annotation).
  **3-part audit — PASS (2026-10-05; Part 3 completed by a second session): post-merge run 668
  (exports committed `db7948e`) vs pre-merge main run 666 (`64bbf48`).** The run-666
  artifact could not be read in-session (the proxy blocks `*.blob.core.windows.net`, so
  artifacts and job logs are unreachable). Run 668's committed exports and raw logs were
  used instead, and `Empty slots` was checked against run 653's committed exports
  (`e6ebe27`). The column has not changed since #464, so 653 still holds the old
  definition there. Part 1: 606 passed / 2 standing skips; 0 ERROR lines in run 668's section of
  build_debug.log; `boldness: 7771 starts, 832 lineups`; no email / rotation. Part 2:
  - all 26 dead starts in player_week (flag + 0 pts) have N/A Boldness;
  - on every completed team-week (832 rows, same keys), new = old + dead starts, 0 mismatches;
  - exactly 23 team-weeks changed, all of them dead-start weeks (2020 6, 2021 8, 2022 4,
    2023 2, 2024 1, 2025 2); total 13 → 39;
  - team_year (56) / team_all_time (8) = Σ team_week, 0 mismatches; 14 team-years moved;
  - cases: JacobRosenzweig 2020 wk12 0 → 2 (Julio Jones, Mark Andrews), wk14 0 → 2 (Cooks,
    Julio Jones); BROsenzweig 2021 wk9 0 → 2 (Hopkins, Sermon); plehv79 2025 wk6 0 → 1
    (Quentin Johnston); LWebs53 2025 wk15 0 → 1 (Chris Rodriguez); plehv79 2022 wk16 stays 6,
    LWebs53 2025 wk9 stays 1, shmuel256 2020 Final stays 2 (no dead start);
  - the Formulas Empty slots / Lineup Boldness text and the Empty slots equation read the new
    definition.

  Part 3 — PASS (full every-sheet sweep, artifacts 668 vs 666 downloaded with `gh run
  download`; also branch run 667 vs 666). Run 668 = run 667 cell for cell on all 15 CSVs.
  The build_debug.log error/warn profile is identical to 666 (old nflverse 404s + KTC proxy).
  Changed cells vs 666:
  - intended: `Empty slots` team_week 23 / team_year 14 / team_all_time 7 (every team but
    shmuel256; the earlier note said 6); formulas 2 Formula + 1 Equation. Lineup Boldness:
    0 cells changed (now checked against the data, not just the code). Excel sheets total 39.
  - by-design (KTC calendar roll, not this PR): add_drops KTC 1y/2y on 6 rows + O-Score
    ±0.1 on 5; player_additions KTC N-years-after on 16 rows. All are forward horizons that
    land on 2026-10-04/05 (today), so they read the intraday KTC value. 3 of them go 354 → 0.0
    (Thompkins, Gus Edwards, Zach Wilson, 2023-10-04 +3y) = the absent-from-today's-directory
    artifact.
  - no other sheet changed.
  - by-design: 2026 has no dead start yet (weeks 1–3), so the live season does not exercise
    the change.

## Sleeper projection columns (from the #480 projection-band work)
- [ ] **Sleeper's own weekly projections as columns** [per user, 2026-10-07: "make sleeper
  projection columns"]. Source: `api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular&position[]=QB|RB|WR|TE`
  (undocumented — the endpoint Sleeper's app uses; Rotowire). Week-specific back to 2018,
  thin in 2018 (~85 WRs/wk), full from 2019; verified NOT today's numbers re-served (per-week
  team/opponent, retired players present, injured weeks absent, corr with past weeks > future).
  Score each row's `stats` with that season's league rules (`boldness.scoring_table(y)`);
  a row with no `pts_ppr` is NO projection (Brady 2021 = adp only), never 0.
  - Covers 7,795 / 7,851 starts 2020-26. Accuracy 2020-25 per start: MAE 6.42, corr 0.373,
    bias +0.30 — best of everything tested (Boldness E 6.43 / 0.345 / −1.28).
  - To decide with the user: which sheets/columns (player_week "Sleeper projection",
    "Points v Sleeper projection"; team_week projected PF / PA, "Beat projection?"; year /
    all-time rollups), whether Comeback size / Boldness should switch to it, and how the
    build caches it (weekly files in .cache like nflverse; live week refetched).
  - Build risk: undocumented endpoint — must degrade to N/A (never 0) when unreachable.
  - **Use a 50/50 blend of Sleeper and Boldness E** as the projection [per user, 2026-10-07]
    — for Comeback size and any projection column; Boldness alone where Sleeper has no
    projection (missing, adp-only, or ~0 for a player who was not ruled out). 2020-25,
    7,475 starts: MAE 6.354 v Sleeper 6.418 v Boldness 6.428; best in all six seasons;
    out of sample (weight fit on one half, scored on the other) 50/50 matches the fitted
    weight; beats Sleeper alone in 100% of 2,000 bootstrap resamples. The errors offset
    (Sleeper +0.31 high, Boldness −1.28 low and blind to role changes like Taysom Hill /
    Jalen Hurts 2020-21). Gain is small (~0.06 pts/start, ~1%). Caveat: by RMSE the best
    mix is 70-80% Sleeper (bias ~0, 8.08 v 8.10) — 50/50 keeps a −0.49 bias. Re-tune the
    win-chance spread (SD_PER_ROOT_POINT) and re-check the 2.5·√n projection band on the
    blend before shipping.

## Game-time columns (from the 2026 wk 4 MNF-comeback inquiry)
- [x] **player_week `Game slot` + team_week margins / comebacks by stage** [per user,
  2026-10-05]. `lotg_support.gametime`, week grain only (no rollups); `inquire.py
  gametime` is the inquiry side (margin entering any stage, `--slots` points by slot).
  - `Game slot`: Thursday / Friday / Saturday / (Christmas) Wednesday, Sunday morning
    (< 1 pm ET), Sunday early, Sunday late, SNF (≥ 7 pm), MNF, Tuesday / Wednesday
    (after Monday); Bye; N/A on the 'NFL' sentinel. Bench rows too.
  - `Margin entering SNF` / `Monday` / `last game`: own going in − opponent going in;
    going in = PF − starters' points from that kickoff on (semifinal +5 counts).
    Monday = first game after Sunday (COVID makeups included); last game = latest
    kickoff with a starter from either side, only if SNF or later. N/A when the stage
    did not happen.
  - `Down entering {SNF, Monday, last game} comeback` ×5: `(margin overcome)` =
    −Margin entering when behind then and won (old definition); `(points overcome)` =
    opponent's FINAL − own going in, when > 0 and the team won (a lead going in still
    counts); `(% of points going in)` / `(% of opponent's final)` / `(per player left)`
    = points overcome ÷ own going in / opponent's final / own starters still to play.
    N/A otherwise.
  - The abandoned 2022 wk 17 Bills-Bengals game (struck from nflverse) is restored as
    Monday 2023-01-02 20:30 wherever the schedule is read (build, inquiry), its 29
    real stat lines (Sleeper stats API → data/struck_game_stats.csv) go into the
    nflverse weekly stats + season totals (`lotg_support.struck_games`), and
    data/game_day_status.csv marks Chase / Knox / Gabe Davis / Perine active for it
    [per user: a normal game with a short stat pool]. Offline A/B diff (smoke, not audit): their
    4 Bye? flags clear (no Injury? set); every other change follows from 4 more
    played 0-point weeks — PPG / bust / floor / donut / streak columns for those 4,
    Positional scoring percentile (1394 cells, pool grew by 4), BROsenzweig 2022 wk 17
    Empty slots 1 → 0 and Chase's Boldness blank → 0.0, Luck ±0.01 that week.
  - Local recompute on the committed exports (completed seasons): 832 team-weeks;
    Monday comebacks 98, SNF 165, last game 97; #1 Monday = LWebs53 2021 wk 2 (63.78,
    49.4%, 33.1%, 21.26 per player).
  Merged #477 / `be459ac` after branch run 671 (artifact checked). **3-part audit — PASS
  (2026-10-06): post-merge main run 672 (exports committed `6395ca3`, roster change) vs
  pre-merge main run 668.**
  - Part 1: 620 passed / 2 standing skips (incl. test_gametime export = recompute and
    test_struck_games on real data); 0 ERROR lines in run 672's section; `schedule:
    restored 1 struck game(s)`, `gametime: 14480 team-games; 0 scoring starter(s) with no
    game`. The 2 PerformanceWarnings at lotg.py ~21629/21663 are pre-existing (run 668 has
    the same pair at 21578/21612).
  - Part 2 cases: LWebs53 2021 wk2 Monday −63.78 → margin/points overcome 63.78, 49.4%,
    33.1%, 21.26/player; plehv79 2023 Semifinal +3.68 going in → margin overcome blank,
    points overcome 55.12; BROsenzweig 2020 wk6 margin overcome 44.04 vs points overcome
    56.04 (opponent's 12 MNF pts); 2023 wk17 Monday blank (no game); AceMatthew 2025 semi
    SNF margin 51.28 = raw 46.28 + the +5; 2020 wk5 BUF/TEN slot Tuesday (COVID makeup);
    Chase 2022 wk17 MNF / not bye / not injured / Boldness 0.0, BROsenzweig Empty slots 0;
    Hurst 2022 full season 141.0; 0 comebacks on a loss; 46 blank last-game margins.
  - Part 3: run 672 = branch run 671 cell for cell on all 15 CSVs. vs 668 (235 sheet/column
    entries): intended — the Hamlin restoration (4 Bye? flags clear, 4 played 0-pt weeks
    and their PPG / bust / floor / donut / streak / percentile cascade, Empty slots, Luck
    ±0.005, Hurst / Beasley / McKenzie 2022, Boldness / prev-5 / PAE / cuff windows, 2 Diggs
    Wins added trades, a few trade / add_drop / pick rows); by-design live drift — 2026 wk4
    DET @ CAR SNF stats that landed after run 668 (13 player_year rows, 4 career-only
    players, Hubbard trade row 283), tenure +1 day, KTC forward horizons (incl. 0.0 roll
    artifacts); formulas +3 rows. Nothing else.
  - `scripts/audit_weekly.py` Part 2 flagged the stale schema pin (also missing #464 / #469
    / Price paid columns); re-pinned from run 672 (`data/audit/schema_baseline.json`).
- [x] **Comeback columns renamed + extended, Comeback size** [per user, 2026-10-06].
  Per stage X ∈ {SNF, Monday, last game}: `Margin overcome (entering X)`, `Points
  overcome (entering X)`, `% of own points scored X or later` (`in last game`; every
  game, not just comebacks), `% of opponent's final points overcome (entering X)`,
  `Points overcome per player left (entering X)`, NEW `Margin overcome per player left
  (entering X)`, NEW `% of opponent's score overcome (X or later)` (margin overcome ÷
  opponent going in), NEW `Comeback size (entering X)`; plus NEW `Comeback size` over
  every kickoff of the matchup but the first. % columns now fractions with a percent
  format (fixes #477's `% of points going in` rendering ×100 — 86.0 → 8600.00%).
  - Comeback size = depth (−z, standard deviations behind the expected finish) × the
    win chance later reached (1 = won) × (¼ + ¾ × the share of the turnaround made by
    the team's own players) [per user: a hold counts, "but not as a big one"].
    Expected points = Boldness' pre-kickoff E (recency, that season's scoring, rookie
    slot prior, next-man-up cuffs; dead starts 0) [per user: "account for cuffs and
    everything else we've done in past predictions"], handed over by the build from
    `boldness.build_columns`; fallback season-to-date PPG + last season + position.
    Spread 2.0·√E. Log loss over 2020-25 kickoffs: 0.393 (Boldness E) v 0.398
    (season-average model) v 0.410 (flat position averages); under-10% win chances
    predicted 2.1% v won 2.2%.
  - Points in time are kickoff WINDOWS [per user: "is this taking into account
    overlapping games"]: a kickoff opens one only ≥ 3h after the previous one, so 4:05
    + 4:25 (590 checkpoints) and Monday doubleheaders (~50) are one window — no game is
    counted finished while still being played. Also moves #477's "entering last game"
    to the window start in 44 team-weeks (late half of a Monday doubleheader).
  Merged #479 / `6e3c1ed` on top of #478 (`0c4edc8`, ancestor verified; #479's diff
  removes no #478 line) after branch runs 676 / 677 / 678 (artifacts checked).
  **3-part audit — PASS (2026-10-07): post-merge main run 679 (exports committed
  `9617dae`, roster change) vs run 673** (last pre-merge main build; 674 was a skipped
  schedule run with no artifact). Covers #478 + #479 together.
  - Part 1: 638 passed / 2 standing skips (incl. test_gametime export = recompute,
    calibration, overlapping windows; #478's digest tests); 0 ERROR lines in run 679's
    section; `gametime: … 7851 boldness expectations for 7851 starts`.
  - Part 2 cases: the 9 scale-preserving renames carry 673's values exactly (0 differ);
    % of opponent's final = 673's 0-100 value ÷ 100; % of own points scored SNF or later
    on all 840 games; LWebs53 2021 wk 2 Monday: own share 0.4064 (88.40 / 217.54), margin
    per player 21.26, % of opponent's score overcome 0.3306 (63.78 / 192.92); Peter
    (plehv79) 2021 wk 5 Comeback size 2.20; hold plehv79 2025 wk 3 0.31; BROsenzweig
    2024 wk 14 0.00 (hole only mid-4 pm window); 840/840 sizes, none negative; 44
    last-game margins moved, all now = Margin entering Monday (doubleheader's first
    kickoff), 0 value↔N/A flips. Workbook: the 4 % columns 0.00%, the rest 0.00.
  - Part 3 (`audit_weekly.py`, 11 flags, all classified): intended — team_week schema
    (15 old names out, 25 in; re-pinned from run 679) and the 44 Margin entering last
    game rows; live drift — AceMatthew's 2026-10-06 Will Shipley waiver (Tank Bigsby drop:
    player_all_time / player_year Number of drops, team / league FAAB +17) and 514
    player_additions PAE rows ±0.01-0.05 (volatile_columns: the expectation refits on
    every build; branch run 678 with the same code already showed it, `acquisition.py`
    imports nothing either PR touched). Nothing else.
  - Digest (run 679): 2 lines, both the windows fix to Margin entering last game, filed
    under "Changes from edits" with #478's drop-off wording and workbook decimals; 0
    comeback-column lines (rename migration + high-end-only held).
    Rejected: log2(1/win chance) (a hopeless loser rallying to 2% scored 11.5, the
    league's biggest); 1 − win chance (squashes the big comebacks together).
  - Digest: the three scale-preserving renames carry their board history
    (`gametime.LEGACY_COLUMNS` via `migrate_count_column`); the % boards start fresh;
    the overcome columns rank at the high end only (`gametime.HIGH_END_ONLY`).
