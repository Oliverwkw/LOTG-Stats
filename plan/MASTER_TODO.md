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
- [ ] Exclude 2021 vet draft from team draft stats
- [ ] Roster turnover refactor (averages, weekly avg, week-1 boundary, in-season = championship-vs-wk1 unique)
- [ ] Starter injury/suspension weeks column
- [ ] "Number of starters X over/under Y" companion columns + rollups
- [ ] Future draft capital fix (updates on trade; 0 only if no picks in 3 years)
- [ ] NFL-team roll-ups additive (rookie stats already correct — verify)
- [ ] Cuffs rostered/started → unique players
- [ ] Activated cuff = cuff becomes starter; injured player doesn't need to have started
- [ ] Cuff at pickup relaxed (starter at any point in prev 3 weeks)
- [ ] team_all_time: regroup Win % vs and Record vs columns by stat type (all Win % together, then all Record together)
- [ ] team_all_time: add 4 columns: Highest Win % vs a team, [opponent team name], Lowest Win % vs a team, [opponent team name]
- [ ] **3-part audit** (code / results / diff)

## Phase 5 — League sheets
- [ ] 🔍 # transactions formula trace + # trades (once per trade incl 3+team)
- [ ] Position/NFL team/players rostered+started: league-wide unique; all-time/yearly = "most"
- [ ] Number of starting donuts column
- [ ] Weekly starter turnover = league total (not average)
- [ ] All-time/yearly "highest/lowest starters" disambiguate
- [ ] 🔍 league_week col O + league_year col S (UPST duplicate?)
- [ ] 🔍 league_all_time "increase in points from previous week" — define or remove
- [ ] 🔍 2022 wk 16-17 only 7 TEs started
- [ ] Weekly trades: offseason in wk-1 rollup only if within 7 days prior to Wk 1
- [ ] **3-part audit** (code / results / diff)

## Phase 6 — Transactions
- [ ] Same-day commissioner add+drop heuristic excludes from tx counts
- [ ] Split link to next/previous (added player + dropped player); include trades
- [ ] # times picked up by this team includes trades; add # times dropped column
- [ ] Tanking = change in tanking (right before vs right after)
- [ ] 🔍 Player addition value never blank — investigate
- [ ] FAAB premium % column replaces FAAB % difference
- [ ] KTC pick value at draft = Sept 1 snapshot
- [ ] KTC future value = Monday of prev championship game
- [ ] 🔍 KTC values audit (Ronald Jones / Josh Gordon as canary)
- [ ] **3-part audit** (code / results / diff)

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
