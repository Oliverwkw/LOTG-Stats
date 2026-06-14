# Phase 12 — 9-part audit, RUN 3

Build under audit: CI run `27472887593`, SHA `bc91f7a` (post #287 — Transaction
skill folds pure drops at 1/3 weight). Diff baseline for the 3-part pre-check:
`#286` (`b8b590f`, run 27471660862), ~50 min earlier (negligible KTC drift).

3-part pre-check of #287: **CLEAN** — build green (13/13 tests), Transaction skill
matches the 1/3-weight formula (43/46 exact; BROsenzweig 2024 = 37.0 as predicted),
Drafting/Trading skill unchanged, diff confined to team Transaction skill.

---

## Part 1 — Cross-sheet reconciliation: **PASS**
New axes vs RUN2 (committed test covers points/tx/PotW/Highest-score). 30+ checks, 0 fail:
- league_week = Σ team_week for PF, transactions, injuries, suspensions, bye, FAAB, donuts (Δ=0). Number of trades: league=distinct events, Σteam≥league by 11 (expected).
- team_year Record W = Σ team_week Win? (Δ=0); Win % = W/games (Δ=0).
- 11 award rollups Times X? = Σ weekly (One-man army, Most bench points, Most injured, Narrowest victory, Largest blowout, Most/Least efficient, Top half, Lowest score, Bros/Sis) — all Δ=0.
- Total trades = Offseason + Inseason (Δ=0).
- team_week PF = Σ starter Points exactly (670) or +5 (10 Semifinal homefield) — 0 unexplained.
- player_all_time = Σ player_year for drops, trades, weeks as starter (Δ=0).

## Part 2 — Stat-family hand-checks (in progress)
PASS so far: Efficiency=PF/MaxPF; Margin=PF−PA; #284 records (All-time = Σ sub-records;
Reg⊆Record; win% identities); Diff hi/lo starters = max−min starter; All-play−Win%;
Total picks ≥ first-round; % of points (starter) = Pts/team-PF (stored as fraction);
Win Variance (2026 N/A-gated, correct).

### Findings
- **F1 (doc) — Brosenzweig / Sisenzweig Formula text is wrong.** The Formulas sheet
  says Brosenzweig = "lost despite a top-half PF" and Sisenzweig = "won despite a
  bottom-half PF". The actual (and correct) code rule is **Brosenzweig = LOSS while the
  2nd-highest scoring team of the week; Sisenzweig = WIN while the 2nd-lowest scoring
  team** (`src/lotg.py:9844`). Build matches the real rule exactly (0/680 mismatch);
  only 12 Brosenzweig / 15 Sisenzweig fire, vs 77 "top-half loss" cases the doc implies.
  Fix the two Formula strings. (Severity: low, doc-only — but actively misleading.)

Part 2 batch 2 (all build-correct): Max PF ≥ PF; Efficiency ≤ 1; SA-Hardship ≤ Hardship;
Luck rounded (no float noise); 3-yr retention ∈ [0,1] (32 N/A = not-yet-3yr seasons);
Change-in-win% N/A on each team's first season (8/8); PAR/gm = PAR/weeks; Playoff−reg PF
plausible; negative Avg points (min −3.06, Max Brosmer 2025) = real backup-QB net-negative
games, NOT a bug.

## Part 3 — N/A vs 0 sweep: PASS (2 vestigial-column findings)
Numeric columns render N/A on genuine no-data, 0 on real zero. New player stat cols
(volatility/floor/ceiling/boom/bust/PAR/PPG) are N/A for never-started and populated for
starters (volatility 80% — the 20% gap = players with exactly 1 started week, std undefined,
correctly N/A). #284 record columns render real "W-L" strings incl. "0-0".

### Findings
- **F2 (cleanup) — `(smallest) Playoff tiebreaker` (league_year) is 100% N/A.** Hardcoded
  to "N/A" at `src/lotg.py:13666` — a permanently-empty placeholder column. Remove it (or
  populate). Reads as broken.
- **F3 (cleanup/reads-wrong) — `Startup draft players remaining` is 0 on EVERY team/league
  row (week/year/all-time), including 2021 wk1.** Explicitly nulled at `src/lotg.py:10025`
  (`tw[...] = None`), then None→0 filled at render. The metric was scrapped (can't be tracked
  until the Phase-13 ESPN/startup backfill), but the column survives showing a misleading 0
  (a reader sees "0 startup players left in 2021 week 1"). Remove the column, or render N/A
  and document it as pending Phase 13. Same family as F2 — vestigial columns RUN2's Part 5
  missed.

## Part 5 — Duplicate / redundant columns: PASS (no new)
No new true duplicates. The ~99%-equal player_week award/streak columns are sparse booleans
sharing the common False/0 value (differ on the rare hits) — not dupes. The IDENTICAL
"Most number of QBs started from same NFL team" == "...TE..." at year/all-time grain is the
known low-information same-NFL-team family (RUN2 F7; weekly grain differs — team_week shows
99.7% not 100%). league_all_time "identicals" are the single-row artifact. (Same-NFL-team
dedup remains a candidate cleanup, as RUN2 noted.)

## Part 6 — Data-quality gaps + sanity + determinism: PASS
0 orphan scoring players (all in player_all_time); 0 player_year players missing all-time;
0 multi-position players; 0 N/A in player_week NFL team / Position / Age (18,744 rows);
no >6-decimal float noise on sampled computed cols; known_player_column_errors.csv empty.
Sanity-range "failures" were my filter mis-flagging signed difference cols (All-play−Win%,
Change in win%, Playoff−reg win%) which correctly range negative.

## Part 4 — Edge cases: PASS (50 cases, 0 real failures)
#284 records (Championships≤appearances; Σchampionships=Σlast-place=5; equal 75-game reg
seasons; JacobRosenzweig 0-0 playoff ↔ 0 appearances). #285 dropped points (606 swap rows
carry them; |total|≥|avg|; implied games ∈[1,17]). Multi-team seasons (Aaron Rodgers 2024,
113 rows). New player stats (floor≤ceiling 0 viol; boom/bust/consistency ∈[0,100]; A.J. Green
2021 1-start → volatility N/A & floor==ceiling). 2026 fully gated (Result/champion/Win
Variance/retention all N/A). Suspensions (41)/byes (1084)/injuries (3443) — 0 both
injured+suspended. Picks: 9 synthetic 2.09/5.0X, Original Team 100%. Trades: 33 3+-team,
O-Score∈[0,100], 0 both-assets-blank. Pure-drop O-Score ≤50 & all populated.
- E13 (retention 0.67 for 2021-23) = CORRECT: 2021/2022 populated, 2023 N/A (3yr→2026 in
  progress). E40 (84 dup Year+Number picks) = CORRECT: future picks (2026-28) with
  undetermined "1.??" slots + "Unknown" player, disambiguated by Original Team. Not bugs.

## Part 7 — Odd-result hunt: PASS (no bugs)
Extremes all match reality: Josh Allen 1845 / Hurts 1626 / Mahomes 1570 top scorers;
Max Brosmer −3.06 bottom; stevenb 2025 wk10 224.32 high PF; plehv79 2022 wk16 45.36 low
(the known 3-starter toilet week); stevenb 2024 luckiest / shmuel 2024-23 unluckiest.
3-year retention 0–29% reads low but is realistic dynasty rookie-class churn (LWebs53 0%,
AceMatthew 29%); value-weighted, not count-based. Transaction skill 27.3–58.7 sensible.

## Part 8 — Asset-story tracking: PASS
0 out-of-range link refs: transactions 2731 #N + 233 T#N, trades 658 #N + 912 T#N all valid.
201 made picks all carry Original Team. (The known 10 zero-event startup cornerstones + 71
initial-roster vets remain the Phase-13 origin gap — unchanged, by design.)

## Part 9 — Cell-by-cell + aesthetics: PASS (1 content finding + F4 determinism)
xlsx rendering is clean: % of points uses `0.00%` format (shows 7.96%); Taxi-eligible
True/False (RUN2 F6 held); all 50 team_year integer-family cols use `0` format (RUN2 F7 held);
streaks show "In Progress"/0/N terminal encoding; `0.00` formats mask the F4 float noise on
screen. RUN2 F4 held (0 no-NFL-team injuries).

### Findings
- **F4 (determinism) — float noise in CSV aggregate columns.** ≥7-decimal values in
  team_year Hardship (23), Luck (13), Change in win % (22), and **Team age including picks**
  on team_year (40) / team_all_time (6) / league_year (5) / league_week (10). E.g.
  `0.05880000000000002`, `595.4783333333332`, `24.07235294117647`. The Bug-#8 round-at-output
  fix covered weekly Luck but not these year/all-time sums (Team age was never covered). The
  xlsx `0.00` format hides it visually, but the CSV exports carry the noise → pollutes every
  diff-based audit and is the exact nondeterminism MASTER_TODO infra #42 targets. Fix: round
  all float outputs at emit. (Severity: low for display, medium for audit-hygiene.)
- **F5 (content — incomplete prior fix) — league_week 2021 wk1 "from previous week" = 0.0,
  should be N/A.** RUN2's F5 fix (no prior week → N/A) was applied to team_week and
  player_week (both correctly N/A in 2021 wk1) but **league_week was missed**: "Increase in
  points from previous week" and "Starter turnover from previous week" render `0.0`.
  Confirmed semantics: 2021 wk2 (−44.78) and 2022 wk1 (−44.44, prior season) are correctly
  populated — only 2021 wk1 is the genuine no-prior case. Propagate the N/A gate to
  league_week. (Severity: low, 1 sheet × 1 week × 2 cols.)

---

## RUN 3 — Summary
**All 9 parts PASS on data correctness.** No reconciliation, link, chain, value-accuracy,
or edge-case failures. 5 findings, all low-severity (doc / cleanup / determinism / cosmetic):

| # | Type | Finding | Fix |
|---|------|---------|-----|
| F1 | doc | Bros/Sis Formula text says "top-half PF"; real rule = 2nd-highest/2nd-lowest scorer | **FIXED** — corrected 4 Formula strings |
| F2 | cleanup | `(smallest) Playoff tiebreaker` 100% N/A (hardcoded) | **FIXED** — now computes the tightest same-record PF seeding-tiebreaker gap per season (was N/A stub) |
| F3 | cleanup | `Startup draft players remaining` = 0 on every row (vestigial, scrapped metric) | DEFERRED → Phase 13 (ESPN/startup backfill) |
| F4 | determinism | float noise (≥7 dp) in CSV aggregates: Team age incl picks, Hardship, Luck, Change in win% | NOT FIXING (per user — masked in xlsx, not a real issue) |
| F5 | content | league_week 2021 wk1 "from previous week" = 0.0, should be N/A (team/player_week fixed, league missed) | **FIXED** — `_sum_or_na` returns N/A when all teams' values are missing |

### Fix PR (F1, F2, F5)
- F1: `src/formulas.py` — corrected Brosenzweig/Sisenzweig + their Times-rollup Formula text to "2nd-highest / 2nd-lowest scoring team of the week."
- F2: `src/lotg.py` league_year builder — replaced the `"N/A"` stub with a real computation: final regular-season standings (wins+0.5·ties, then PF), smallest PF gap among adjacent same-record pairs; N/A only if no record ties. Validated against team_year records (2021 = 23.18 among the three 10-5 teams; 2022 = 14.42; 2023 = 77.92; 2024 = 59.64; 2025 = 94.5). Formulas entry restored with the accurate description.
- F5: `src/lotg.py` league_week builder — `_sum_or_na` helper; "Increase in points / Starter turnover from previous week" now N/A when every team's value is missing (2021 wk1), matching team_week/player_week.

---

## Follow-up scan (post-#288) — "similar types of issues"
#288 verified CLEAN (tiebreaker 23.18/14.42/77.92/59.64/94.5; league_week 2021 wk1 N/A;
Bros/Sis docs corrected; only intended diffs + benign KTC/F4-noise). Then scanned the three
run-3 categories: (A) vestigial/stub columns, (B) incomplete-propagation across grains, (C)
doc-vs-behavior mismatches.

### F6 (real bug — incomplete propagation, same class as F5) — **NEW**
`Number of NFL teams among starting players` and `Number of NFL teams among rostered players`
roll up as **weekly `max`** on **team_year** (`src/lotg.py:12669-12670`) and **team_all_time**
(`13062-13063`) instead of **distinct-across-period**. League got the distinct fix (Phase 5B,
override at `13477-13483`/`13889`) but the **team grain was missed**.
- Evidence: team_all_time = **10 for all 8 teams** (the max possible in a 10-starter week);
  true distinct all-time = **28–31**. team_year AceMatthew 2024 = 10 vs true 20 (Δ team_year
  up to 11/12, team_all_time up to 21/11).
- The sibling distinct families (QB/WR/RB/TE started Δ=0, rookies Δ=0, cuffs accumulate 16–44)
  are all correct — only the NFL-teams-among pair was missed.
- Doc also under-specifies: Formula says "distinct … that week" but the column ships on
  year/all-time too (where league=distinct, team=max). Fix the rollup + clarify the doc.

### F7 (minor — sentinel leak) — **NEW**
`Number of NFL teams among rostered players` counts the **"NFL" FA/retired sentinel** as a
33rd NFL team → league_year/all-time render **33** (impossible; only 32 exist). Starters = 32
(no sentinel, since FA/retired never start). The team-grain distinct fix (F6) should exclude
the "NFL" sentinel so rostered tops out at 32.

### Categories clean
- (A) vestigial columns: only `Startup draft players remaining` (= F3, deferred Phase 13) and
  the known same-NFL-team `Most number of …` family (RUN2 F7, low-information by design). No new
  all-N/A or all-constant columns (league_all_time "constants" are the single-row artifact).
- (C) doc spot-checks: UPST, One-man army?, Number of QB started, Difference hi/lo starters all
  match behavior. Bros/Sis fixed in this PR.

### Dispositions
- **F6 — FIXED** (`src/lotg.py`, follow-up PR): team_year/team_all_time
  "Number of NFL teams among starting/rostered players" now use the league's
  `_league_unique_extras` distinct helper (`["Team","Year"]` and `["Team"]`),
  matching the behavior the Formulas Notes already documented. team_all_time
  starting → 28-31 (was 10); team_year → real per-season distinct (e.g.
  AceMatthew 15/18/15/20/20, was 8-10). Sibling distinct families untouched.
- **F7 — WON'T FIX** (per user): counting the "NFL" FA/retired sentinel as a
  33rd team in "Number of NFL teams among rostered players" is acceptable;
  kept consistent across team and league grains.

Verified-intentional / regressions-held: RUN2 F4 (no-NFL-team→Bye), F6 (Taxi True/False),
F7 (integer number formats) all still good. % of points, streak terminal encoding, #284
records, #285 dropped points, #287 1/3-weight Transaction skill all correct.
Still-open by design: Phase-13 startup-origin gap (10 cornerstones + 71 vets).
