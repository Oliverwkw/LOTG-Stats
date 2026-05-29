# LOTG-Stats Master TODO

**Workflow per phase:**
1. PR opened
2. User merges + runs build
3. Claude audits results
4. Iterate until audit clean
5. **Diff sweep** — confirm only intended changes occurred (no collateral damage on unrelated sheets/columns)
6. Mark phase complete; move to next

---

## Phase 0 — Quick foundation
- [ ] Sheet order: formulas / player_week / player_year / player_all_time / team_week / team_year / team_all_time / league_week / league_year / league_all_time / transactions / trades / pick_history
- [ ] player_week: Year as 3rd column
- [ ] league_week: Year → Week Name → Week → rest (note: user wrote "league_year"; that sheet has no Week Name. Treating as league_week. Verify in audit.)
- [ ] Drop columns: player_all_time (Rookie?, Age); team_week/team_year/team_all_time (Largest deficit overcome, Combined matchup score); league_week/league_year/league_all_time (Tanking, Luck)
- [ ] **Diff sweep**: confirm no unrelated column moves / value changes

## Phase 1 — Global rules
- [ ] Bye weeks excluded from every average
- [ ] Injured/suspended weeks excluded from every player-week average
- [ ] Week-1 prev-week = previous season's championship week (mid-season pickups: week before pickup)
- [ ] Pick asset horizon = exactly 3 years
- [ ] "Number of X started/rostered" → unique players everywhere
- [ ] Duplicate-column sweep + document survivors
- [ ] N/A vs 0 sweep (Win % vs self N/A; FAAB on FA/commissioner N/A; % starts made 0 when never started; player addition value never blank)
- [ ] **Diff sweep**

## Phase 2 — Formulas sheet rebuild
- [ ] Every non-obvious column gets an entry
- [ ] xlsx styling (color, wrap text, group by sheet, hyperlinks)
- [ ] **Diff sweep**

## Phase 3 — Hardship + Luck
- [ ] Hardship redefined per spec; NFLverse backfill for early-2021 + new pickups
- [ ] 🔍 Investigate 2021 wk 1-2 hardship=0 with 23/30 injuries
- [ ] Starter-adjusted hardship column next to every hardship column
- [ ] Starter injury count column in league_week
- [ ] Luck rebuild; audit distribution; iterate weights
- [ ] **Diff sweep**

## Phase 4 — Player sheets
- [ ] 🔍 Number of teams bug (Renfrow=5 not 4); fix partial-week rosterings
- [ ] Top team / Last team → time rostered (not weeks)
- [ ] Drop yearly rows for never-rostered players
- [ ] Split Points (while rostered) vs Points (full season, NFLverse)
- [ ] Change-in stats use full-season values; only N/A for rookie years
- [ ] Injury/suspension-adjusted average points + change-in pairs
- [ ] Career average from NFLverse
- [ ] % of points redefined: starter contribution to team total; + team-name cols for highest/lowest
- [ ] Taxi-eligible boolean in player_all_time
- [ ] Number of trades column in player_week (auto-rolls to year + all-time)
- [ ] Verify PPG bench excludes injured/suspended/bye
- [ ] **Diff sweep**

## Phase 5 — Team sheets
- [ ] 🔍 Team age including picks ≈ player age (likely 0-future-pick bug)
- [ ] Player + team avg age = average of weekly averages (incl with-picks variant)
- [ ] Exclude 2021 vet draft from team draft stats
- [ ] Roster turnover refactor (averages, weekly avg, week-1 boundary, in-season = championship-vs-wk1 unique)
- [ ] Starter injury/suspension weeks column
- [ ] "Number of starters X over/under Y" companion columns + rollups
- [ ] Future draft capital fix (updates on trade; 0 only if no picks in 3 years)
- [ ] NFL-team roll-ups additive (rookie stats already correct — verify)
- [ ] Cuffs rostered/started → unique players
- [ ] Activated cuff = cuff becomes starter; injured player doesn't need to have started
- [ ] Cuff at pickup relaxed (starter at any point in prev 3 weeks)
- [ ] **Diff sweep**

## Phase 6 — League sheets
- [ ] 🔍 # transactions formula trace + # trades (once per trade incl 3+team)
- [ ] Position/NFL team/players rostered+started: league-wide unique; all-time/yearly = "most"
- [ ] Number of starting donuts column
- [ ] Weekly starter turnover = league total (not average)
- [ ] All-time/yearly "highest/lowest starters" disambiguate
- [ ] 🔍 league_week col O + league_year col S (UPST duplicate?)
- [ ] 🔍 league_all_time "increase in points from previous week" — define or remove
- [ ] 🔍 2022 wk 16-17 only 7 TEs started
- [ ] Weekly trades: offseason in wk-1 rollup only if within 7 days prior to Wk 1
- [ ] **Diff sweep**

## Phase 7 — Transactions
- [ ] Same-day commissioner add+drop heuristic excludes from tx counts
- [ ] Split link to next/previous (added player + dropped player); include trades
- [ ] # times picked up by this team includes trades; add # times dropped column
- [ ] Tanking = change in tanking (right before vs right after)
- [ ] 🔍 Player addition value never blank — investigate
- [ ] FAAB premium % column replaces FAAB % difference
- [ ] KTC pick value at draft = Sept 1 snapshot
- [ ] KTC future value = Monday of prev championship game
- [ ] 🔍 KTC values audit (Ronald Jones / Josh Gordon as canary)
- [ ] **Diff sweep**

## Phase 8 — Trades
- [ ] 🔍 Rows with both Assets received + sent blank — fix root cause
- [ ] FAAB-as-asset capture (FAAB tradeable)
- [ ] Enhanced Avg PPG (excludes injured/bye/suspended + includes future-draft-pick PPG)
- [ ] # teams involved in trade column
- [ ] Link to next transaction per asset
- [ ] Trade addition value never blank; Asset age difference never blank
- [ ] Avg PPG received includes draft-pick PPG after arrival
- [ ] Assets retained now / Assets traded away / Assets dropped to FA include relevant draft picks
- [ ] V2 trade addition value (Cuffs etc.)
- [ ] **Diff sweep**

## Phase 9 — Pick history
- [ ] 🔍 Commissioner-moved over-fires — investigate
- [ ] **Diff sweep**

## Phase 10 — Taxi / IR / suggestions
- [ ] Taxi columns: player_week Taxi?; player_year Weeks in taxi; player_all_time Weeks in taxi; team_week Players in taxi; team_year/all_time Unique players in taxi + Total taxi-player-weeks
- [ ] IR columns (Sleeper roster.reserve, NOT NFL injury designation): player_week IR slot?; player_year/all_time Weeks on IR; team_week Players on IR; team_year/all_time Unique players on IR + Total IR player-weeks
- [ ] Suggest 3-5 enhancement ideas (draft-class scorecard, schedule luck, trade equity at N years)
- [ ] **Diff sweep**

## Phase 11 — Revisit league notes
- [ ] Survey league.metadata / settings / per-season text across Sleeper years; decide tracked vs manual overlay
- [ ] **Diff sweep**

## Phase 12 — ESPN 2020 backfill
- [ ] Scope when we get there
- [ ] **Diff sweep**
