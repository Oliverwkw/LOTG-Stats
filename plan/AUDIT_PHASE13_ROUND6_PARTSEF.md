# Phase 13 Round 6 — Parts E+F (domain-bounds/plausibility + N/A-vs-0-vs-blank correctness)

Self-designed full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. This is agent 3 of 5 in Round 6.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `5b29101` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`5b29101`, the Round-6
Parts C/D tip carrying the 2 stale-tooltip-text fixes) before any work, then
confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Reflects all prior fixes:
picks.csv 450, trades.csv 504, transactions.csv 1,514, player_all_time 649,
player_year 1,859, team_year 48, league_year 6.

All examples below are NOVEL — different players/teams/seasons than every prior
round (deliberately avoiding Josh Doctson, Kenny Pickett, Hunter Henry,
K.J. Osborn, Carter, Stevenson, Pacheco, Jefferson, DJ Moore, Tyler Johnson,
Larry Fitzgerald, Cam Newton, Mike Gesicki, the BROsenzweig-pick examples, the
2026 2.09 toilet pick, Trubisky/Hurst, AJ Dillon, Matt Ryan, Tony Pollard,
Mattison, Drake, Meyers, Taysom Hill, Kerryon Johnson, Aaron Jones,
T.J. Hockenson, Robbie Chosen, CEH, KJ Hamler, Jalen Guyton).

**Result: CLEAN.** Zero defects found. Every numeric/categorical column is
in-domain at full population, and every conditionally-defined column renders
N/A correctly in BOTH directions (rows in-condition get N/A, rows out-of-condition
never do). The specifically-requested re-verification — that the playoff-elimination
`0` sentinel's ACTUAL DATA matches the Parts-C/D-corrected tooltip — passes
24/24 + 24/24 across all 6 seasons.

---

## Part E — Domain-bounds & plausibility sweep (every numeric/categorical column, every sheet)

Scanned all 12 data sheets (league_all_time / league_week / league_year / picks /
player_all_time / player_week / player_year / team_all_time / team_week /
team_year / trades / transactions). Established per-column plausible domains and
scanned the FULL column population for out-of-domain values.

### Bounded-domain columns — CLEAN
- **Ages** (genuine birthdate-based age columns only): `player_year.Age`
  [20.77, 48.37], `player_week.Age` [20.62, 48.37], `picks.Age when drafted`
  [20.89, 43.07], `team_year.Player average age` [23.85, 29.82],
  `team_year.Team age including picks` [22.45, 27.88], `league_year.Player average
  age` [25.90, 26.27] — all inside [18, 60], **0 out of range**. The top of the
  range is legitimately old: the oldest player-seasons are **Tom Brady 2025 =
  48.37, 2024 = 47.39** and **Drew Brees 2025 = 46.80** — retired QBs still sitting
  on never-dropped rosters, whose Age = (season date − birthdate) keeps
  incrementing. The value is factually correct (Brady really is 48 in 2025) and
  in-domain; it is the holding, not the age, that is the curiosity, and that
  holding is a completeness concern already covered by Parts A/B, not a
  domain-bounds violation. (A regex pre-pass spuriously matched the substring
  "age" inside `Average PPG`, `career average`, `Activated Cuff?`, `weekly roster
  turnover` etc.; each was confirmed to be NOT an age column and excluded.)
- **Week numbers** (`league_week.Week`, `player_week.Week`, `team_week.Week`):
  all in [1, 17]. **0 phantom week-0, 0 week>18.**
- **`Week of playoff elimination`** (the documented sentinel column, NOT in
  `_preserve_na`): distinct values `{0, 10, 11, 12, 13, 14, 15}` — all in [0, 18];
  no out-of-domain week. (Sentinel semantics verified in Part F below.)
- **Year/Season** (every season-keyed sheet): all in [2020, 2025]; `picks.Year`'s
  `startup`/`(vet)`/`2026-2028` text/future labels are by-design, not a span
  violation.
- **Dates** (every `Date` / `Date dropped/traded` column across transactions /
  trades, parsed `YYYY-MM-DD`): **0 dates outside the 2019-2026 league span**, 0
  impossible month/day.
- **0-100 percentage columns** scanned explicitly (Starter/Rostered boom %, bust %,
  and consistency / floor / ceiling percentiles on player_year + player_all_time):
  every value in **[0.4, 100.0]** — no >100% and no <0%.
- **Win % / rate / fraction columns**: scanned for negatives and absurd magnitudes;
  the only negatives are the **signed-difference columns by design** —
  `All-play win % minus Win %`, `Playoff win % minus regular-season win %`,
  `Change in win % from previous season`, and `player_week.% of points (if
  starter)` (a fractionally-negative share when the player scored negative fantasy
  points — the same documented Garoppolo-class case from Round-5 E/F, here
  confirmed bounded to −0.0417). Not implausible.
- **Counts** (`Number of …`, `Times as …`, `Total trades`, donuts, weeks missed,
  bids, games, streaks, drops, transactions across every sheet): scanned for
  negatives excluding the explicitly-signed substrings (margin/luck/variance/
  difference/added/net/impact/minus/change/premium/o-score/score). The 2 apparent
  "negative count" hits were **false positives** — `transactions.PPG of 5 games
  before pickup` (−1.18) and `transactions.Dropped total points` (−344.94) are
  points/PPG aggregates, not counts, and negative fantasy points are legal. **0
  genuine negative counts.**

### Sentinel / large-magnitude scan — all legitimate aggregates
- **No `9999` / `99999` / `±inf` placeholders anywhere.** A full-population scan
  for any `|value| ≥ 9000` returned only legitimate season/career sums:
  `league_all_time.PF` 112,807 / `Max PF` 138,091 / `Number of players under 10`
  12,913; `league_year.PF` 17,935-20,221 / `Max PF` 21,592-24,840;
  `team_all_time.Points` 13,072-14,872 / `Points against` 13,721-14,378 /
  `Max PF` 16,260-18,335; and `trades.Trade impact score` (smooth distribution
  −13,859…+30,738). No sentinel masquerading as data.

**Part E conclusion: CLEAN** — every bounded column in-domain; all large
magnitudes are legitimate aggregates; the only negatives are by-design signed
columns; the only near-50 ages are factually-correct retired-QB holdings.

---

## Part F — N/A-vs-0-vs-blank correctness (every conditionally-defined column, full population)

Enumerated every `_preserve_na`-governed column directly from `src/lotg.py`'s
`_preserve_na()` (resolved against the live function, not a static list) and
verified, for the FULL row population, that N/A renders correctly.

### Universal "N/A-not-blank-not-nan" invariant — CLEAN
For **every** `_preserve_na` column on **every** sheet I counted blank-string and
literal-`"nan"` occurrences. Across all sheets — picks (8 preserve-na cols),
player_all_time (26), player_week (11), player_year (30), team_all_time (49),
team_week (11), team_year (48), trades (16), transactions (30), league_* — the
result is **0 blank strings and 0 literal-`nan` text in any preserve-na column**.
Every conditionally-absent value renders the true string `N/A`, never a blank or
a leaked `nan`. This is the core Part F invariant and it holds at full population.

### Bidirectional condition correctness — CLEAN (0 over- AND 0 under-broadened)
For each conditional column I re-derived condition X independently from the raw
sheet and checked BOTH failure modes (in-condition-but-not-NA, and
out-of-condition-but-NA). NOVEL surfaces:

| Column / condition (re-derived) | Rows in-condition | In-cond but NOT N/A (over-narrow) | Out-of-cond but N/A (over-broad) |
|---|---|---|---|
| `player_week.% of points (if starter)` & all 5 `(if starter)` cols vs `Starter/Bench=='Starter'` (7,531) | 7,531 | **0** | **0** |
| `player_week.Difference from worst benchable starter (if bench)` vs `Bench` (13,845) | 13,845 | **0** | **0** |
| `transactions.Number of bids` — 2021+ waiver (419) | 419 | **0** (all numeric) | — |
| `transactions.Number of bids` — 2020 waiver ESPN-unrecoverable (29) | 29 | — | all N/A ✓ |
| `transactions.Number of bids` — non-waiver (1,066) | 1,066 | — | all N/A ✓ |
| `transactions.Faab` — 2022+ waiver (389) | 389 | **0** (all numeric) | — |
| `transactions.Faab` — pre-2022 / non-waiver (444 / 1,066) | 444 / 1,066 | — | all N/A ✓ |
| `transactions.{Number of times dropped by this team, Dropped avg points, Dropped total points}` vs has-a-`Player Dropped` (1,162) | 1,162 | **0** | **0** |
| `transactions.Length of tenure on team` vs has-a-`Player Added` (no-add → N/A) | 439 N/A | — | **0** (no pure-drop row fabricates a tenure) |
| `picks.Length of tenure on team` vs made-pick (97 unmade) | 97 | **0** | **0** |
| `team_year.Amount of FAAB spent` — pre-2022 N/A (16) / 2022+ numeric (32) | 16 / 32 | **0** | **0** |
| `league_year.Amount of FAAB spent` — 2020/2021 N/A, 2022-2025 numeric (460/665/698/809) | 2 / 4 | **0** | **0** |
| `team_year.{Win Variance, All-play win %}` — needs ≥2 played weeks (all 48 complete) | 48 | **0** N/A | — |
| `team_year.3-year roster retention rate` — N/A iff Y+3 unplayed | Y∈{2023,24,25}=24 | — | **0** (Y∈{2020,21,22}=24 all populated) |
| `player_year.Points` — N/A iff transaction-only row (no player_week presence) | 188 | — | **0** scored row wrongly N/A'd; 188 N/A == exactly the 188 no-player_week rows |
| `transactions` 12 KTC + `Net KTC` cols — KTC index unreachable offline | 1,514 | — | all N/A ✓ |
| `picks` 7 KTC checkpoints + `O-Score` — KTC-dependent, offline | 450 | — | all N/A ✓ |
| `trades` `Pick value received` / `O-Score` / 5 KTC-diff cols — KTC-dependent, offline | 504 | — | all N/A ✓ |
| `team_year` / `team_all_time` `Drafting/Trading skill` — shrunk-mean O-Score, O-Score N/A offline → skill N/A | 48 / 8 | — | all N/A ✓ |

Notable bidirectional exactness: the `(if starter)`/`(if bench)` player_week
columns are **0/0 in both directions across all 21,376 player-weeks** (every
starter row populated, every non-starter N/A — and vice versa); and
`player_year.Points` N/A count (**188**) equals EXACTLY the count of player_year
rows with zero player_week presence (the documented "added+dropped between weekly
snapshots" transaction-only rows from Round-6 A/B) with **0 scored rows wrongly
N/A'd** — a textbook clean conditional.

### Specifically requested — playoff-elimination `0` sentinel: ACTUAL DATA matches the Parts-C/D-corrected tooltip

Parts C/D corrected the `Week of playoff elimination` tooltip to state `0` =
the 4 bracket / top-4 teams (NOT "missed the bracket"), with real regular-season
elimination weeks 10-15 for the others. I re-verified the **actual `team_year`
data** still matches the now-corrected description, mapping each row's `Result`
(Champion/2nd/…/8th) to bracket (top-4) vs non-bracket and checking the sentinel,
**across every one of the 6 completed seasons (2020-2025)**:

- **Bracket teams (Champion / 2nd / 3rd / 4th) carry `0`: 24/24** — exactly 4 per
  season, every season, **0 exceptions**.
- **Non-bracket teams (5th / 6th / 7th / 8th) carry a REAL elimination week in
  [10, 15]: 24/24** — exactly 4 per season, **0 exceptions**.
- **0 violations in either direction** (no bracket team carries a non-zero week;
  no non-bracket team carries `0`).

NOVEL spot examples (different teams/seasons than Round-4/5 E/F and Round-6 C/D
which spoke in aggregate): **2022 BROsenzweig finished 4th → ElimWeek 0**
(bracket); **2024 JacobRosenzweig finished 8th → ElimWeek 10** (earliest
elimination observed); **2025 plehv79 finished 5th → ElimWeek 14**; **2020
shmuel256 Champion → 0** / **2020 stevenb123 8th → week 11**; **2021 BROsenzweig
6th → week 15** (latest). The `0`-sentinel-for-bracket convention is exactly what
the corrected tooltip now says, and the data confirms it at full population. (This
column is intentionally NOT in `_preserve_na`: `0` is a meaningful sentinel here,
correctly distinct from the genuine elimination weeks — the numeric default-fill
to `0` for the `None`-valued bracket teams is the intended behavior, now
accurately documented.)

### Investigated, not a defect (documented intentional behavior, re-confirmed)
- **`trades.Asset difference in average age` = 0 for 86 FAAB-only / single-side
  rows** — `src/lotg.py` ~9571 deliberately reports `0.0` (not blank) when one
  side has no aged asset. Documented design choice (also flagged in Round-5 E/F);
  left unchanged.
- **`trades.Trade addition value` = 0 (22 rows) / `transactions.Tanking` = 0** —
  real computed zeros, not fabricated placeholders; not in N/A scope.

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~73s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- **No source changes were needed (no defects).** Build artifacts reverted
  (`git checkout -- exports/`, `git clean -fd exports/`); only this new file is added.

## Conclusion
**Parts E + F are fully CLEAN at full population — ZERO defects.** Every
numeric/categorical column across all 12 sheets is in-domain (the only negatives
are by-design signed columns; the only near-50 ages are factually-correct
retired-QB roster holdings; no `9999`/`inf` sentinel masquerades as data). Every
conditionally-defined column renders N/A correctly in BOTH directions — **0 blank
strings, 0 literal-`nan`, 0 over-narrowing, 0 over-broadening** — across the full
population, verified column-by-column with NOVEL surfaces (the 21,376-row
`(if starter)/(if bench)` split, the 188 transaction-only `player_year.Points`
rows, the 419/29/1,066 bids partition, the FAAB pre/post-2022 split). The
specifically-requested re-verification confirms the playoff-elimination `0`
sentinel's ACTUAL DATA matches the Parts-C/D-corrected tooltip exactly: **24/24
bracket teams = 0, 24/24 non-bracket teams = real week 10-15, 0 violations across
all 6 seasons.** No source change was required for Parts E/F this round.
