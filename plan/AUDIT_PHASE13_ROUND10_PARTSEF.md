# Phase 13 Round 10 — Parts E+F (domain-bounds/plausibility + N/A-vs-0 correctness)

Self-designed full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 3 of 5 in Round 10 (siblings: Parts A/B —
`AUDIT_PHASE13_ROUND10_PARTSAB.md` — landed CLEAN at `f95d3ea`; Parts C/D —
`AUDIT_PHASE13_ROUND10_PARTSCD.md` — found+fixed 2 tooltip-TEXT defects in a NEW
family at `814cdb6`: the **`Taxi-eligible`** tooltip omitted the first-year gate,
and the **`Result`** tooltip listed the wrong finish vocabulary — both rewritten
to the real ordinal {Champion, 2nd..8th} / dual-gate semantics).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `git merge-base --is-ancestor 814cdb6 HEAD`
did NOT print OK — 814cdb6 was NOT an ancestor of HEAD, HEAD was 39 commits behind
origin). Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`814cdb6`, the
Round-10 Parts C/D tip carrying both tooltip fixes plus all Round-5..Round-10
fixes), then confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
player_all_time 649, player_year 1,859, player_week 21,376, team_year 48,
team_all_time 8, team_week 808, trades 504, transactions 1,514, league_year 6,
league_week 101, league_all_time 1.

All examples below are NOVEL — different players/teams/seasons/picks than every
prior round (Rounds 4-10 Parts A/B/C/D exclusion lists honoured; notably avoiding
the Round-9 E/F surfaces — LWebs53/plehv79/Oliverwkw 2020 Win%, the 2023-Wk16 PF
Semifinal counterpart, the 48 Week-1 pregame-diff rows, the 90 genuine-0 dropped
points — and the Round-10 C/D Taxi examples Adam Trautman / Ameer Abdullah /
Andrei Iosivas, and the Round-10 C/D player chains Wan'Dale Robinson / James
Conner / Cam Akers / James Cook). New surfaces cited here: the **Result-column
5th-8th-vs-last-place internal inconsistency** in 2021/2022/2023; the **toilet-bowl
record leaking into the finish ranking** (2021 shmuel256 won the toilet bowl →
finished 5th despite a worse 5-10 regular record than JacobRosenzweig's 6-9); the
**4 tx-only first-year-2025 never-started players wrongly Taxi-eligible=False**
(**Joe Milton, Jordan Watkins, Zavier Scott**, + Tanner McKee); the NOVEL
veteran-never-started False set **Alex Collins (fy2021), Ben Sinnott (fy2024),
Bryce Love (fy2020)**; the **`Change in win % from previous season`** signed delta
(BROsenzweig year-over-year).

**Result: 2 real COMPUTATIONAL defects found and FIXED** (both in `src/lotg.py`) —
NOT tooltip text this time, but the actual DATA the Round-10 C/D tooltips describe:
1. **`Result` column 5th-8th ranking** used a hard-coded `cutoff = 17 if season <
   2025 else 15` games window that pulled the **toilet-bowl bracket games** into
   the "regular-season record" ranking for 2020-2024, contradicting both its own
   tooltip ("ranked by regular-season record") AND the export's separate
   `last_place_by_season` (which uses regular-season-only). The two disagreed on
   who finished last in **2021, 2022, and 2023**.
2. **`Taxi-eligible` column** wrongly rendered **False** for 4 transaction-only
   first-year-2025 never-started players, because the player_all_time pad rows
   (concatenated AFTER `_is_taxi_eligible` runs on `pa`) never received a
   `Taxi-eligible` value and silently defaulted to False/NaN — an **over-narrow
   gate** masking real eligibility.

Both fixes change exported DATA (higher-priority than text). Both are minimal and
targeted, verified before/after at full population, with `pytest tests/ -q` =
**15 passed / 0 regressions** and `pat == Σpy` still 0-mismatch after the pad fix.

---

## SPECIFICALLY REQUESTED — re-derive the `Result` column from raw standings (don't trust the column)

The prompt asked, given the C/D `Result` tooltip fix, to specifically re-derive
the `Result` DATA from raw standings — ordinals 2nd-8th by correct final standing,
ties broken consistently, Champion correct. I did, and it surfaced a real defect.

### Structural distinctness — CLEAN
Every one of the 6 completed seasons (2020-2025) carries exactly one of each place
**{Champion, 2nd, 3rd, 4th, 5th, 6th, 7th, 8th}** in `team_year.Result` — 0
duplicate places, 0 missing places, 0 out-of-vocabulary strings ("Missed playoffs"
/ "Last place" never appear, confirming the C/D vocabulary fix).

### Bracket places (Champion/2nd/3rd/4th) — CLEAN (NOVEL 2024 trace)
Re-derived from the `team_week` bracket games (`Week Name ∈ {Final, 3rd Place}`),
ranking the two participants by `Win?` (PF fallback): NOVEL **2024** —
stevenb123 won the Final (Win?=True, 181.38) → Champion; shmuel256 → 2nd;
BROsenzweig won the 3rd-place game (Win?=True, 201.84) → 3rd; plehv79 → 4th. All
4 match the column. The four winners'-bracket places are assigned correctly by the
actual game outcome every season.

### 5th-8th non-playoff ranking — **DEFECT FOUND** (toilet-bracket leakage)

Re-deriving the column EXACTLY as the code does (`games_df` filtered to
`Week <= cutoff`, `cutoff = 17 if season<2025 else 15`, rank by win% then PF)
reproduced the column with **0 mismatches** — so the column faithfully implements
the algorithm. But re-deriving against the **true regular season** (`Week <
playoff_start`: 14 weeks for 2020, 15 for 2021+) produced **6 disagreements** in
2021/2022/2023 — all among the bottom-four teams, where the **toilet-bowl bracket
games (weeks 15-17) flip the 5th-8th order**:

| Season | toilet-bowl detail | code's 5th-8th basis | effect |
|---|---|---|---|
| 2021 | shmuel256 won BOTH toilet games (Toilet Semis + Toilet Final), JacobRosenzweig lost both | record incl. toilet → shmuel256 5th, JacobRosenzweig 8th | flips vs regular-only |
| 2022 | plehv79 won the Toilet Trash game, JacobRosenzweig lost both | plehv79 7th, JacobRosenzweig 8th | flips vs regular-only |
| 2023 | JacobRosenzweig won BOTH toilet games, stevenb123 lost both | JacobRosenzweig 7th, stevenb123 8th | flips vs regular-only |

Whether toilet-bowl outcome *should* set the finish is defensible league policy —
but it created a **hard internal contradiction** in the export, because a SEPARATE
code path, `last_place_by_season` (`lotg.py` 13190-13248, filtered to
`Week < playoff_start` = regular-season-only), designates a DIFFERENT last-place
team and drives `Record vs last place`, `Win % vs last place`, the all-time
`Number of last place finishes`, and the all-time last-place class.

**Smoking-gun evidence (2021, pre-fix):** the `Result` column said JacobRosenzweig
finished **8th (last)**, but `Record vs last place` keyed off **shmuel256** as last
place — shmuel256 showed `0-0` (no record vs itself), while JacobRosenzweig (the
column's 8th-place team) showed `1-2` vs *someone else* designated last. Two
columns in the same sheet disagreed on who finished last in 2021/2022/2023.

The code comment AND the (Round-10-C/D-rewritten) `Result` tooltip both say 5th-8th
is "ranked by **regular-season** record (PF tiebreaker)". The code did NOT do that
for 2020-2024 (it used a 17-game window incl. the bracket); only 2025 (cutoff=15 =
its 15-week regular season) accidentally matched. So the code drifted from its own
documented + comment-stated intent.

**Fix (`src/lotg.py` ~13318):** replaced `games_df["Week"] <= cutoff` (the
hard-coded 17/15) with `games_df["Week"] < playoff_start` — the season's true
regular-season boundary, identical to the window `standings_by_season` /
`last_place_by_season` already use. `playoff_start` is already in scope and
guaranteed truthy at that point.

**Post-fix verification (full population):**
- Each season still has exactly Champion + 2nd..8th (no place lost/duplicated).
- The `Result`==8th team now AGREES with regular-season-last for all 6 seasons
  (2020 stevenb123, 2021 **shmuel256**, 2022 **plehv79**, 2023 **JacobRosenzweig**,
  2024 JacobRosenzweig, 2025 Oliverwkw). 2021/22/23 are the three fixed seasons.
- The `Result`==8th team now shows `Record vs last place` = **`0-0`** in EVERY
  season — internal consistency restored (the 8th team is the same team the
  "last place" columns key off).
- The all-time `Number of last place finishes` now equals the per-season
  `Result==8th` count for every team (**0 mismatches**): JacobRosenzweig 2,
  Oliverwkw/plehv79/shmuel256/stevenb123 1 each, others 0.
- The 6 Champions are unchanged (LWebs53 2022/23, shmuel256 2020/25,
  stevenb123 2021/24) — the fix touched only the 5th-8th tail.

---

## Part E — Domain-bounds & plausibility sweep (every numeric/categorical column, every sheet)

Scanned all 12 data sheets (league_all_time / league_week / league_year / picks /
player_all_time / player_week / player_year / team_all_time / team_week /
team_year / trades / transactions; the 13th sheet, `formulas`, is the definitions
reference). Established per-column plausible domains and scanned the FULL column
population for out-of-domain values.

### Bounded-domain columns — CLEAN
- **Ages** (true age columns only — `Age`, `Age when drafted`, `Player average
  age`, `Team age including picks`; substring-"age" false positives excluded):
  across all 16 age columns on all sheets, **0 out of [18, 60]**. Ranges:
  `player_week.Age` [20.62, 48.37], `player_year.Age` [20.77, 48.37],
  `picks.Age when drafted` [20.89, 43.07], `team_week.Player average age`
  [23.52, 29.94], `team_week.Team age including picks` [22.19, 28.42],
  `league_year` age columns [24.02-26.27]. (The ~48 top of range is the
  factually-correct retired-QB roster-holding curiosity documented in prior
  rounds — a completeness matter, not a domain violation.)
- **Week numbers** (`league_week.Week`, `player_week.Week`, `team_week.Week`):
  all in **[1, 17]**. 0 phantom week-0, 0 week>18. (2020 maxes at 16.)
- **Year/Season** (every season-keyed sheet): all numeric played-season values in
  **[2020, 2025]**, 0 OOB. `picks.Year`'s `startup` / `2021 (vet)` text labels and
  the future-pool numeric years 2026-2028 are by-design.
- **Dates** (`trades.Date` ×504, `transactions.Date` ×1,514,
  `transactions.Date dropped/traded` ×1,003, parsed): **0 dates outside
  2019-2026**. Spans: trades [2020-09-12, 2025-12-04], transactions
  [2020-09-09, 2025-12-30], drop/trade dates [2020-09-11, 2025-12-24] — 0
  impossible month/day.
- **Percentage / rate / percentile columns** (every `%` / `rate` / `percentile`
  / `boom` / `bust` / `efficiency`, excluding by-design signed columns): all
  absolute win%/rate/efficiency in **[0, 1]**, all boom/bust/percentile in
  **[0, 100]** — **0** out of range.

### Negatives run to ground — all by-design signed columns, NOT defects
A first-pass scan flagged 40+17 negatives; every one is a **signed** column:
- `player_week.% of points (if starter)` (12 rows, min −0.0417) +
  `player_year.% of points (highest/lowest team)` (1 row, −0.0001) — the
  documented negative-share case (a player who scored negative fantasy points
  yields a negative share of team points). Bounded, explainable.
- `team_all_time/team_year.All-play win % minus Win %`,
  `Playoff win % minus regular-season win %` — names literally contain "minus";
  signed differences, legitimately negative.
- `team_year.Change in win % from previous season` (min −0.4706, max +0.5294) —
  a signed year-over-year delta. NOVEL re-derivation: **BROsenzweig** 2021 =
  0.4118 − 0.5000 = −0.0882, 2022 = +0.1764, 2023 = −0.2353, 2024 = +0.2353,
  2025 = +0.0589 — every value recomputes exactly as Win% minus prior-year Win%
  (2020 N/A, the first season). By-design signed; not a defect.

### Negative true-counts — CLEAN
A STRICT true-count scan (`number of` / `times as` / `total number` / `donut` /
`bids` / `weeks as|at|missed`, excluding avg/ppg/difference/skill/score/streak/
margin/luck/net substrings): **0 negative true-count values** at full population.

### Sentinel / nan / inf scan — CLEAN
Full-population scan for literal `nan`/`inf`/`-inf` text → **0** (see Part F); for
`9999`/`99999` sentinels in count columns → **0**. No sentinel masquerades as data.

**Part E conclusion:** every bounded column is in-domain; the only negatives are
by-design signed columns; the only near-50 ages are factually-correct retired-QB
holdings; no sentinel/nan/inf masquerades as data. The one COMPUTATIONAL defect in
Part E scope — the `Result` 5th-8th ranking — was found and fixed (above).

---

## Part F — N/A-vs-0 correctness (every conditionally-defined column, full population)

### SPECIFICALLY REQUESTED — Taxi-eligible dual-gate, re-verified with FRESH examples (not the prior count)

The prompt asked to re-verify (not trust the Round-10 C/D count) that
`Taxi-eligible` is correctly gated by BOTH `first_year == current_season` AND
`weeks_started == 0`. Re-deriving both gates independently from
player_all_time + player_year surfaced an **over-narrow defect**.

**Defect found:** 4 players with first-league-season 2025 and 0 weeks-as-starter
rendered `Taxi-eligible = False` when they should be True:
**Joe Milton, Jordan Watkins, Zavier Scott** (all NOVEL) + Tanner McKee.

**Root-cause (traced via an instrumented build, then removed):** these 4 are
transaction-only players (added & dropped between weekly snapshots → 0 player_week
rows, NaN Points). They have no `pa` row when `_is_taxi_eligible` runs
(`lotg.py` 12694-12712); they are added to player_all_time afterward as **pad
rows** (`lotg.py` ~12832, `pd.concat`), and those pad-row dicts never set a
`Taxi-eligible` key — so the column defaulted to False/NaN, bypassing the gate.
The instrumented build confirmed each has a single player_year row at Year 2025
with a valid Player ID (Joe Milton 11557, Jordan Watkins 12634, Zavier Scott
11299, Tanner McKee 9230) — i.e. genuinely first-year-2025 never-started, the
exact profile that SHOULD be taxi-eligible.

**Fix (`src/lotg.py` ~12816):** the pad rows now compute `Taxi-eligible`. A tx-only
pad player has no player_week presence (hence 0 started weeks), so eligibility
reduces to the first-year gate: `current_season is not None and
first_year_by_pid.get(sid) == current_season`. Added the key to the pad-row dict.

**Post-fix verification (full population, BOTH gates re-derived):**
- `Taxi-eligible` True count: **39 → 43** (the 4 missing players now True).
- **0 over-broad** (True but gate fails) and **0 over-narrow** (gate passes but
  False) across all 649 player_all_time rows.
- All **43** `first_year==2025 & ws==0` rows → True; all **193**
  `first_year<2025 & ws==0` (veteran never-started) rows → False (NOVEL examples
  **Alex Collins** fy2021, **Ben Sinnott** fy2024, **Bryce Love** fy2020 — none in
  the C/D list); all **32** `first_year==2025 & ws>0` (rookies who started) → False.
- `player_all_time == Σ player_year` still 0-mismatch on all additive counters
  after the pad change (Number of transactions/drops/trades/Weeks as starter/
  Times as Player of the week?) — the pad fix added only the Taxi-eligible key.

### Universal "N/A-not-blank-not-nan-not-inf" invariant — CLEAN
Scanned EVERY column on EVERY sheet for literal `nan`/`inf`/`-inf`: **0
occurrences** across all 12 data sheets. Every conditionally-absent value renders
the true string `N/A`.

### Bidirectional condition correctness — CLEAN (0 over- AND 0 under-broadened)
Each conditional column's condition X re-derived independently; BOTH failure modes
checked. NOVEL/refreshed surfaces this round:

| Column / condition (re-derived) | over-narrow | over-broad |
|---|---:|---:|
| `Amount of FAAB spent` — N/A iff Year<2022 (team_year/team_week/league_week/league_year) | **0** | **0** |
| `transactions.Faab` — value iff waiver & season≥2022 (389) | **0** | **0** |
| `transactions.Number of bids` — value iff waiver & season≥2021 (419) | **0** | **0** |
| `picks.Length of tenure on team` — N/A iff unmade ("Unknown", 97) | **0** | **0** |
| `player_week` 6× `(if starter)`/`(if bench)` vs `Starter/Bench` (21,376) | **0** | **0** |
| `player_year.{Starter floor/ceiling, Floor/Ceiling percentile, PPG starter}` — N/A iff Weeks as starter <1 | **0** | **0** |
| `player_year.{Starter scoring volatility, Consistency percentile}` — N/A iff Weeks as starter <2 | **0** | **0** |
| `team_year.3-year roster retention rate` — N/A iff Year+3>2025 | **0** | **0** |

Notable exactness (FRESH cuts):
- The `(if starter)/(if bench)` player_week columns are **0/0 in both directions
  across all 21,376 player-weeks** (using the actual `Starter/Bench` flag).
- The starter floor/ceiling/percentile family uses a **≥1-start** gate (a
  single-started week still has a defined floor/ceiling — the 212-row Round-7
  boundary) while volatility/consistency use the stricter **≥2-start** gate; both
  re-derived against the correct per-family gate, both **0/0**. (A naïve uniform
  ≥2 gate spuriously "flagged" 212 floor/ceiling rows — confirmed NOT a defect.)
- `team_year.3-year roster retention rate` non-null only for source years
  {2020, 2021, 2022} (Year+3 ≤ 2025), N/A for all later — 0/0.

### Week-over-week / first-week N/A — CLEAN (FRESH cut)
- `league_week.{Increase in points from previous week, Starter turnover from
  previous week}` are N/A for **exactly 1 of 101 rows** — the league's first week
  (2020 Week 1). Correct (the Round-2 F5 fix still holds).
- `team_week.Difference in pregame avg max PF from opponent` is N/A for **exactly
  48 rows** — all Week-1 rows (6 seasons × 8 teams). Every non-Week-1 row
  populated. Correct in both directions.
- `team_all_time.Playoff win %` is N/A for exactly 1 team — **JacobRosenzweig**,
  who never reached the winners'-bracket playoffs (consistent with the now-fixed
  Result column: JacobRosenzweig is never Champion/2nd/3rd/4th). Correct N/A.

### Real-0-vs-N/A (the "0 is meaningful, not N/A" direction) — CLEAN
- `transactions.Dropped total points` carries **90 genuine `0` values** (drops of
  players who never scored another NFL fantasy point) rendered as a real `0`, NOT
  N/A; the **352** no-drop rows are all N/A (0 leaked to a number).

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~77s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`
  — run after BOTH fixes.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- Clean rebuild from committed source confirms both fixes hold: `Result`==8th team
  shows `0-0` Record vs last place every season; `Taxi-eligible` True count = 43.
- `player_all_time == Σ player_year` still 0-mismatch on all additive counters
  after the pad-row change.
- Build artifacts reverted (`git checkout -- exports/`, `git clean -fd exports/
  .cache/`); only `src/lotg.py` (the 2 fixes) + this new file remain.

## Conclusion
**Parts E + F are NOT clean — 2 real COMPUTATIONAL defects found and FIXED in
`src/lotg.py`** (higher-priority than the pure-text fixes of prior rounds, and both
directly in the specifically-requested re-verification surfaces):

1. **`Result` 5th-8th ranking** used a hard-coded 17-game window (pre-2025) that
   pulled the **toilet-bowl bracket** into the "regular-season record" ranking,
   contradicting its own tooltip + comment AND the export's `last_place_by_season`
   — so two columns disagreed on who finished **last** in 2021/2022/2023. Fixed to
   rank by the true regular season (`Week < playoff_start`); now the Result==8th
   team is internally consistent with every "last place" column (0-0 every season,
   all-time last-place counts reconcile).
2. **`Taxi-eligible`** was an **over-narrow gate**: 4 transaction-only
   first-year-2025 never-started players (Joe Milton, Jordan Watkins, Zavier Scott,
   Tanner McKee) bypassed `_is_taxi_eligible` via the player_all_time pad-row path
   and defaulted to False. Fixed so pad rows compute the first-year gate; True
   count 39 → 43, now 0/0 bidirectional against both gates.

Both changed exported DATA, both verified before/after at full population, 15/15
tests pass with 0 regressions, and `pat == Σpy` holds. Everything else in Parts
E/F is CLEAN: all bounded columns in-domain (the only negatives are by-design
signed columns — incl. the NOVEL `Change in win %` delta re-derived on
BROsenzweig — the only near-50 ages are factually-correct retired-QB holdings),
no nan/inf/sentinel, and every other conditionally-defined column renders N/A
correctly in BOTH directions (0 over-narrow, 0 over-broad) with NOVEL surfaces.

This round breaks the Round 5-9 E/F pattern of "always text-only, data was correct
all along": stepping past the (now-exhausted) 2020-vs-2021 draft-seam family — as
the Round-10 C/D agent did at the tooltip layer — surfaced two genuine DATA bugs
in the very columns C/D had just re-documented, exactly where the prompt directed
the re-derivation.
