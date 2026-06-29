# Phase 13 Round 9 — Parts E+F (domain-bounds/plausibility + N/A-vs-0 correctness)

Self-designed full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 3 of 5 in Round 9 (siblings: Parts A/B —
`AUDIT_PHASE13_ROUND9_PARTSAB.md` — landed CLEAN at `642f111`; Parts C/D —
`AUDIT_PHASE13_ROUND9_PARTSCD.md` — found+fixed 2 tooltip-text 2020-startup-draft
label defects in `src/formulas.py` at `133d85e` — the `O-Score` Notes and the
picks `Number of trades` Notes, both mislabelling the inaugural **2020** ESPN
startup draft as a "2021" event; the agent there judged this draft-label tooltip
family now likely exhausted after 4 consecutive rounds of finding instances).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `git merge-base --is-ancestor 133d85e HEAD`
did NOT print OK — 133d85e was not an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`133d85e`, the Round-9 Parts C/D tip
carrying the 2 tooltip fixes plus all Round-4..Round-8 fixes), then confirmed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
player_all_time 649, player_year 1,859, player_week 21,376, team_year 48,
team_all_time 8, team_week 808, trades 504, transactions 1,514, league_year 6,
league_week 101, league_all_time 1.

All examples below are NOVEL — different players/teams/seasons/picks than every
prior round (Rounds 4-9 Parts A/B/C/D exclusion lists honoured; notably avoiding
shmuel256/AceMatthew/BROsenzweig/stevenb123 as the Win%/Record headline teams,
Jacory Croskey-Merritt's $120 bid, the plehv79 $258 spend, the ws==1 single-start
gate headline, the 2020-Week-15 PF Semifinal pair shmuel256+plehv79, Calvin
Ridley/Davante Adams/Dalton Kincaid, and the Round-5/6/7/8 E/F surfaces). New
surfaces cited here: the **2020 Semifinal +5 homefield bonus on LWebs53/Oliverwkw
(higher seeds) vs plehv79/shmuel256 (lower seeds)** with the **fresh 2023 (17-week)
Semifinal counterpart on Week 16**; **LWebs53 10-6 / plehv79 9-7 / Oliverwkw 10-6
2020 Win % = /16**; the **152 startup + 32 vet picks O-Score=N/A vs Number-of-trades
real-0** outcome (the data behind the Round-9 C/D tooltip fixes); the **48 Week-1
`Difference in pregame avg max PF from opponent` N/A** rows; the **90 genuine-0
`Dropped total points`** drops alongside the **352 no-drop N/A** rows.

**Result: CLEAN.** Zero defects found. Every numeric/categorical column across all
13 export sheets is in-domain at full population, and every conditionally-defined
column renders N/A correctly in BOTH directions. The specifically-requested
COMPUTED-DATA re-verification — that no DATA is miscalculated for 2020 by a
hard-coded week-16/17 assumption — passes at full population with FRESH examples:
every season-length-dependent column (PF Semifinal homefield bonus, Record, Win %,
Regular-season win %) computes the *correct 2020 value*, anchored on the season's
real 16-week structure (Semifinal Week 15) rather than the 2021+ 17-week structure
(Semifinal Week 16). The two columns whose tooltips Round-9 C/D just corrected
(`O-Score`, picks `Number of trades`) render the EXACT N/A-vs-0 outcome the
corrected text now describes. No source change was required this round.

---

## Specifically-requested deep dive — 2020 16-week vs 2021+ 17-week: is any DATA (not just text) miscalculated? (fresh examples)

Round-9 C/D corrected two more *tooltip* entries in the recurring 2020-vs-2021
draft-seam family. As in Rounds 6/7/8, I re-verified directly that the COMPUTED
values for every season-length-dependent column are correct for 2020's 16-week
season, NOT trusting prior rounds. **No 2020 data defect found.**

### Week structure is per-season-correct — CLEAN
`team_week` max week per season: **2020 = 16**, 2021-2025 = 17. (0 phantom week-17
for 2020, 0 missing weeks.) The 2020 Week-16 bracket names are
`{Final, 3rd Place, Toilet Final, Toilet Trash}` and the Semifinals land on
**Week 15** — vs 2023's plain `Week 15` regular matchup and Week-16 Semifinal.

### PF Semifinal +5 homefield bonus lands on the RIGHT week per season — CLEAN (data-verified, FRESH)
`lotg.py` 4271-4297 applies the +5 higher-seed homefield bonus at `playoff_start`
(15 for 2020, 16 for 2021+). Verified `team_week.PF` minus Σ starter
`player_week.Points` directly:

| Season / Week | Semifinal team | PF − Σ starters | seed |
|---|---|---:|---|
| **2020 Wk15** | LWebs53 | +0.00 | lower |
| 2020 Wk15 | Oliverwkw | +0.00 | lower |
| 2020 Wk15 | plehv79 | **+5.00** | higher |
| 2020 Wk15 | shmuel256 | **+5.00** | higher |
| **2023 Wk16** | LWebs53 | **+5.00** | higher |
| 2023 Wk16 | Oliverwkw | **+5.00** | higher |
| 2023 Wk16 | plehv79 | +0.00 | lower |
| 2023 Wk16 | shmuel256 | +0.00 | lower |

The +5 lands on **Week 15** for the two 2020 higher seeds and on **Week 16** for
the two 2023 higher seeds — i.e. season-aware off `playoff_start`, never a
hard-coded week. 2023 Week 15 is a plain "Week 15" regular matchup (no bonus), so
the bonus does not leak to a constant week. The DATA behind the recurring PF
tooltip fix is itself correct for both season lengths.

### Record / Win % / Regular-season win % use the correct 2020 denominators — CLEAN (FRESH teams)
- **`Record`** sums to **16** for every 2020 team and **17** for every 2021-2025
  team (per-season min==max==season length). FRESH 2020 examples: LWebs53 10-6,
  plehv79 9-7, Oliverwkw 10-6.
- **`Win %`** = W / (season games), 2020 uses **/16**: LWebs53 10/16 = 0.6250 ✓
  (a hard-coded /17 would give 0.5882), plehv79 9/16 = 0.5625 ✓, Oliverwkw
  10/16 = 0.6250 ✓ — all three match /16, none matches /17.
- **`Regular season record`** sums to **14** for 2020 (min==max==14) and **15** for
  2021+ — the per-season regular-season denominator is correct, no hard-coded 15
  bleeding into 2020.

No season-length-dependent column is miscalculated for 2020. (The Round-6/7/8/9
C/D tooltip fixes were pure TEXT; the DATA those tooltips describe has been —
and remains — correct for 2020.)

---

## Part E — Domain-bounds & plausibility sweep (every numeric/categorical column, every sheet)

Scanned all 12 data sheets (league_all_time / league_week / league_year / picks /
player_all_time / player_week / player_year / team_all_time / team_week /
team_year / trades / transactions; the 13th sheet, `formulas`, is the definitions
reference). Established per-column plausible domains and scanned the FULL column
population for out-of-domain values.

### Bounded-domain columns — CLEAN
- **Ages** (true age columns only — `Age`, `Age when drafted`, `Player average
  age`, `Team age including picks`; the signed `Asset difference in average age` /
  `Age difference` columns correctly excluded from the [18,60] gate): across all
  16 age columns on all sheets, **0 out of [18, 60]**. Ranges: `player_week.Age`
  [20.62, 48.37], `player_year.Age` [20.77, 48.37], `picks.Age when drafted`
  [20.89, 43.07], `team_week.Team age including picks` [22.19, 28.42],
  `team_week.Player average age` [23.52, 29.94], `league_year` age columns
  [24.02-26.27]. (The ~48 top of range is the factually-correct retired-QB
  roster-holding curiosity documented in prior rounds — a completeness matter, not
  a domain violation.)
- **Week numbers** (`league_week.Week`, `player_week.Week`, `team_week.Week`): all
  in **[1, 17]**. 0 phantom week-0, 0 week>18. (2020 maxes at 16 — see the deep
  dive above.)
- **Year/Season** (every season-keyed sheet): all numeric played-season values in
  **[2020, 2025]**, 0 OOB. `picks.Year`'s `startup` / `2021 (vet)` text labels and
  the future-pool numeric years 2026-2028 are by-design, not a span violation.
- **Dates** (`trades.Date` ×504, `transactions.Date` ×1,514,
  `transactions.Date dropped/traded` ×1,003, parsed): **0 dates outside
  2019-2026**. Observed spans: trades [2020-09-12, 2025-12-04], transactions
  [2020-09-09, 2025-12-30], drop/trade dates [2020-09-11, 2025-12-24] — all 0
  impossible month/day.
- **Percentage / percentile / rate columns** (every `%` / `percent` / `percentile`
  / `rate` / boom% / bust% across all sheets, excluding by-design signed-difference
  columns): the only sub-zero value is `player_week.% of points (if starter)` (12
  rows, min −0.0417) — the documented negative-share case when a player scored
  negative fantasy points (same class as Round-5/6/7/8 E/F), bounded and
  explainable. All win%/percentile/rate columns are in [0, 100] (or [0, 1]).
- **Count columns** (STRICT true-count keys — `number of`, `times as`,
  `total trades`, `donut`, `total number`, `count`, `picks made`, `bids`,
  `weeks as/at`, `games played`, `number of times` — excluding signed/average
  substrings): **0 negative true-count values** at full population.

### "Count"-keyword false positives run to ground — NOT defects
A keyword scan that included the substring `games` initially flagged three columns
with negative values: `trades.Avg PPG of received players on team` (min −0.50),
`trades.Avg PPG of sent players over same time` (min −0.08), and
`transactions.PPG of 5 games before pickup` (min −1.18). These are **points-per-game
AVERAGE** columns (`PPG`/`Avg`), not counts — they are legitimately negative when a
player averaged negative fantasy points over the window. Excluding the
average/PPG/signed substrings, the STRICT true-count scan returns **0 negative
counts** across all 12 sheets. Not defects.

### Large-magnitude / sentinel scan — CLEAN
A full-population scan for literal `nan`/`inf`/`-inf` text (0 hits — see Part F)
and for `9999`/`99999` sentinels in count columns (0 hits) returned **0 sentinel
masquerading as data**. The only large magnitudes are legitimate season/career sums
(`league_all_time.PF`, `trades.Trade impact score`), identical in character to
prior E/F rounds.

**Part E conclusion: CLEAN** — every bounded column in-domain; the only negatives
are by-design signed columns (signed-difference + PPG averages + the negative-points
starter share); the only near-50 ages are factually-correct retired-QB holdings;
no sentinel masquerades as data.

---

## Part F — N/A-vs-0 correctness (every conditionally-defined column, full population)

Enumerated every `_preserve_na`-governed column directly from `src/lotg.py`'s live
`_preserve_na()` (resolved against the function source at lines 1183-1357, not a
static copy) and verified, for the FULL row population, that N/A renders correctly.

### Universal "N/A-not-blank-not-nan-not-inf" invariant — CLEAN
Scanned EVERY column on EVERY sheet for literal `"nan"` and `"inf"`/`"-inf"` text:
**0 literal-`nan` and 0 literal-`inf` occurrences anywhere** (all 12 data sheets).
Every conditionally-absent value renders the true string `N/A`, never a leaked
`nan`/`inf`. The core Part F invariant holds at full population.

### Bidirectional condition correctness — CLEAN (0 over- AND 0 under-broadened)
For each conditional column I re-derived condition X independently from the raw
sheet and checked BOTH failure modes (in-condition-but-N/A = over-narrow, and
out-of-condition-but-not-N/A = over-broad). NOVEL surfaces this round:

| Column / condition (re-derived) | In-cond rows | over-narrow | over-broad |
|---|---:|---:|---:|
| `transactions.Faab` — value iff waiver & season≥2022 | 389 | **0** | **0** |
| `transactions.Number of bids` — value iff waiver & season≥2021 | 419 | **0** | **0** |
| `transactions.Total FAAB bid` — N/A for 2020+2021 waivers, value 2022+ | 59 / 389 | **0** | **0** |
| `transactions.Dropped total points` vs has-`Player Dropped` (352 no-drop) | 352 | **0** | **0** |
| `player_week` all `(if starter)` / `(if bench)` cols vs `Starter/Bench` (21,376) | 21,376 | **0** | **0** |
| `picks.Length of tenure on team` — N/A iff unmade pick ("Unknown") | 97 | **0** | **0** |
| `team_year.Amount of FAAB spent` — N/A iff Year<2022 | 16 | **0** | **0** |
| `team_week.Amount of FAAB spent` — N/A iff Year<2022 | — | **0** | **0** |
| `league_week.Amount of FAAB spent` — N/A iff Year<2022 | — | **0** | **0** |
| `league_year.Amount of FAAB spent` — N/A iff Year<2022 | — | **0** | **0** |
| `team_year.3-year roster retention rate` — N/A iff Year+3>2025 | 24 | **0** | **0** |
| `player_year.{Starter scoring volatility, …}` — N/A iff Weeks as starter<2 | 1,010 | **0** | **0** |
| `player_year.PPG starter` — N/A iff Weeks as starter<1 | 798 | **0** | **0** |

Notable bidirectional exactness re-confirmed at full population (FRESH cuts):
- The `(if starter)/(if bench)` player_week columns are **0/0 in both directions
  across all 21,376 player-weeks** (every starter row populated, every bench row
  N/A, and vice versa).
- The volatility/consistency family uses a **stricter ≥2-starts** gate (1,010 rows
  N/A) than the ≥1-start `PPG starter` family (798 rows N/A); re-derived against the
  correct gate, both are **0/0**.
- The 97 `picks.Length of tenure on team` = N/A rows are EXACTLY the 97 unmade
  future-pool picks (`Player Picked == "Unknown"`); the 353 made picks all carry a
  numeric tenure. Bidirectionally exact.

### SPECIFICALLY REQUESTED — the Round-9-C/D-corrected columns render the correct N/A-vs-0 outcome
Round-9 C/D corrected the `O-Score` Notes and the picks `Number of trades` Notes
(both had labelled the 2020 ESPN startup draft as "2021"). I verified the ACTUAL
N/A-vs-0 DATA for the 2020 startup-draft and 2021 vet-draft exclusion sets matches
exactly what the corrected text now claims:

- **`picks.O-Score`** — corrected tooltip: the two non-rookie drafts are scored
  only in their OWN percentile pool, "in practice every one of those rows ends up
  N/A." Data: **all 152 startup picks AND all 32 vet picks render N/A** (0 non-null
  of 184); in fact ALL 450 picks' O-Score is N/A offline (KTC-dependent). The
  N/A-not-0 outcome the corrected text describes is exact.
- **`picks.Number of trades`** — corrected tooltip: the 2020 ESPN startup draft, the
  2021 supplemental veteran draft, and the synthetic award picks "count 0 here."
  Data: **all 152 startup picks render real `0` (NOT N/A); all 32 vet picks render
  real `0` (NOT N/A)** — 0 N/A in either set. The 0-not-N/A direction is correct:
  these non-tradeable/award picks carry a genuine zero, while the rookie-draft picks
  correctly carry positive trade counts (distribution: 268×0, then 1→11 trades up
  to a single 11-trade pick). The corrected "count 0 here" text is data-accurate.

This is the data counterpart of the Round-9 C/D fix: the text was corrected (year
label), and Parts E/F confirm the underlying N/A-vs-0 treatment was already correct.

### Real-0-vs-N/A (the "0 is meaningful, not N/A" direction) — CLEAN
- `transactions.Dropped total points` carries **90 genuine `0` values** (drops of
  players who never scored another NFL fantasy point) rendered as a real `0`, NOT
  N/A; the 352 no-drop rows are all N/A (0 leaked to a number). (The non-zero drop
  rows span large negatives, e.g. −81.5 / −284.68, confirming the column captures
  post-drop scoring including the real-0 floor.)
- `transactions.O-Score` carries **439 real values** offline (KTC-independent) and
  drives `Transaction skill` (47/48 team-seasons computed), correctly distinct from
  the fully-N/A KTC-dependent `picks.O-Score` (450/450 N/A) and `trades.O-Score`
  (504/504 N/A). `Drafting skill` / `Trading skill` are all-N/A offline (depend on
  picks/trades O-Score); the one `Transaction skill` = N/A team-season is
  **JacobRosenzweig 2020** (3 transactions, 0 with a recoverable 2020 O-Score) — the
  documented no-scored-O-Score case, correctly N/A.

### 2020/2021-specific N/A — every no-FAAB-era column correctly N/A — CLEAN (FRESH)
The league had **no FAAB system pre-2022**. Verified at full population that EVERY
`Amount of FAAB spent` cell is N/A for Year<2022 and numeric for Year≥2022 across
all four sheets that carry it: `team_year` (8/8 teams N/A in 2020, 8/8 N/A in 2021,
0 N/A in 2022+), `team_week`, `league_week`, `league_year` — **0 pre-2022 cell
fabricated to a number, 0 real ≥2022 FAAB datum wrongly N/A'd**. The
`transactions.Total FAAB bid` is N/A for all 59 2020+2021 waiver rows and numeric
for all 389 2022+ waiver rows.

### Week-over-week first-week N/A — CLEAN (FRESH cut)
- `league_week` week-over-week columns (`Increase in points from previous week`,
  `Starter turnover from previous week`) are N/A for **exactly 1 of 101 rows** —
  the league's very first week (**2020 Week 1**), where the prior week doesn't
  exist. Correct N/A (the Round-2 F5 fix still holds).
- `team_week.Difference in pregame avg max PF from opponent` is N/A for **exactly
  48 rows** — all Week-1 rows (6 seasons × 8 teams), where no prior-week opponent
  average exists. Correct N/A in both directions (every non-Week-1 row populated).
- `team_all_time` clutch + `Playoff win %` columns are N/A for exactly 1 of 8 teams
  — **JacobRosenzweig**, who never reached the winners'-bracket playoffs; the other
  7 teams carry real values. Correct N/A.

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~75s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- **No source changes were needed (no defects in Parts E/F this round).** Build
  artifacts reverted (`git checkout -- exports/`, `git clean -fd exports/ .cache/`);
  only this new file is added; `git status` otherwise clean.

## Conclusion
**Parts E + F are fully CLEAN at full population — ZERO defects.** Every
numeric/categorical column across all 13 sheets is in-domain (no out-of-range
age/week/year/date/percentage, no negative true-counts, no `nan`/`inf`/`9999`
sentinel; the only negatives are by-design signed-difference columns, PPG averages,
and the negative-points starter share). Every conditionally-defined column renders
N/A correctly in BOTH directions — **0 literal-`nan`, 0 literal-`inf`, 0
over-narrowing, 0 over-broadening** — verified column-by-column with NOVEL surfaces
(LWebs53/plehv79/Oliverwkw 2020 Win%=/16, the 2023-Week-16 PF Semifinal +5 bonus
counterpart, the 48 Week-1 pregame-diff N/A rows, the 90 genuine-0 dropped-points,
and the 152 startup + 32 vet picks O-Score-N/A vs Number-of-trades-real-0 outcome).

The specifically-requested COMPUTED-DATA deep dive confirms (with FRESH examples)
that **no 2020 data is miscalculated by a hard-coded week-16/17 assumption**: the
PF Semifinal +5 homefield bonus lands on Week 15 for 2020 and Week 16 for 2023
(both data-verified, +5 to exactly the higher seeds), and Record / Win % /
Regular-season record use the correct 16-game / 14-game 2020 denominators. The two
columns whose tooltips Round-9 C/D just corrected (`O-Score`, picks `Number of
trades`) render the EXACT N/A-vs-0 outcome the corrected text describes — confirming
the Round-9 C/D fixes were pure TEXT and the underlying N/A-vs-0 DATA was already
correct. No source change was required for Parts E/F this round.

This continues the Round 4-8 E/F pattern: the season-length tooltip bug family that
keeps surfacing in Parts C/D has, in every E/F pass, been confirmed text-only — the
COMPUTED 2020 data has been correct all along, and remains so this round.
