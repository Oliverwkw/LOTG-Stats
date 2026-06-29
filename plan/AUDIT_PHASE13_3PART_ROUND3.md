# Phase 13 follow-up — 3-part audit ROUND 3 on PR #319

Third pass of the mandatory 3-part audit, run fresh against the CURRENT branch
tip `claude/phase-13-audit-tsapoy` @ `237e1a2` ("Phase 13 10-part audit Round 1
Part 10: ESPN-2020 integration CLEAN, no source change"), diffed against `main`.
This is the final 3-part stage of the governing 3-part → 5-agent → 10-part audit
cycle: the 5-agent audit (Round 12) and the 10-part audit (Round 1, Parts 1-10)
both came back fully clean immediately prior to this run. All spot-check examples
below are deliberately NOVEL — different players/teams/seasons/picks than those in
`AUDIT_PHASE13_3PART.md`, `_ROUND2.md`, the Round 12 PARTSAB-IJ docs, and the
10-part Round 1 docs.

Methodology: worktree reset to `origin/claude/phase-13-audit-tsapoy` (the
known stale-worktree bug DID trigger — reset confirmed HEAD at 237e1a2); local
offline build (`scripts/offline_build.py`, exit 0, only the two expected
`api.sleeper.app/league/0` + `espn_2020_draft` unresolved-fetch warnings from the
sandboxed no-network environment); full `pytest tests/ -q` = **15 passed**;
full-population (not sampled) internal-consistency invariants computed directly on
the freshly-built export CSVs.

## Part 1 — Code-based audit: PASS

`git diff main...HEAD -- src/` read in full (espn_2020.py +737 new;
formulas.py 56 lines of tooltip text; lotg.py +2114/-288). Every distinct logical
change maps 1:1 to a documented, scoped fix from the audit-history docs — no
stray/accidental edits. Specific NEW-logic blocks given direct scrutiny this round
(not just trusted from prior docs):

- **`espn_2020.py` ESPN→Sleeper adapter**: roster-id remap (ESPN teamId →
  stable Sleeper roster_id via `ESPN_TO_SLEEPER_RID`) so a cross-platform asset
  keeps one identity; `_clean_id` strips the `.0` float-string tail; EXECUTED-only
  filter on FA/waiver/ROSTER + TRADE_ACCEPT incidental drops; `_calendar_trade_wk`
  uses the same kickoff-anchored `//7` rule as lotg's `_trade_wk`. Logic is
  internally consistent; the 16-week season length (`last_scored_leg`/`leg`=16,
  `playoff_week_start`=15) is correctly threaded.
- **`(smallest) Playoff tiebreaker`** (brand-new computation, lotg ~14934):
  ranks each season's regular-season standings by (wins+0.5·ties, PF) descending,
  then takes the smallest PF gap among *adjacent equal-record* pairs. Verified by
  hand (Part 2). Correct.
- **`_pos_factor` per-season position baseline** (replaces the old all-time pooled
  `pos_avg_map`/`league_starter_avg`): `league_starter_avg(season) /
  pos_avg(season, pos)`, applied everywhere position adjustment was done
  (transactions, picks, trade-of-trades chains — the chain version correctly keys
  each weekly point's factor to the YEAR it was scored). Verified by hand (Part 2).
- **Future-pick deal-time valuation** (`_pick_val_label`): a pick traded before
  `date(year-1, 9, 1)` (its determining season hadn't completed) is valued as its
  round average ("YYYY R.??"); traded during/after, it resolves to its actual slot.
  Verified full-population (Part 2/3).
- **Pick-chain FULL numbered identity** `(year, round, number, orig)` + `_R209`
  sentinel + `_pick_neighbors` skipping every other `PH#`: verified 0 sibling
  self-links full-population, round-trip on a novel sibling pair (Part 2/3).
- **Player tx/drop counter rebuild from final `transactions_rows`**; pad-row
  collision guards (`existing_names`, `_py_pids`); taxi-eligible pad gate;
  `_sum_or_na` for the two "from previous week" league-week columns; stable-sort
  tiebreakers. All confirmed correct and isolated.

`pytest tests/ -q` (fresh build present): **15 passed, 0 failed, 0 skipped**, both
before and after the audit (no source change was made this round). Offline build
exit 0, no new warnings beyond the two known network-unavailable fetches.

## Part 2 — Results-based audit: PASS (NOVEL examples, hand-computed)

**(smallest) Playoff tiebreaker — NOVEL: 2022 season.**
Hand-built 2022 regular-season standings from team_week (Week-N rows only):
the only two same-record adjacent pairs are LWebs53/stevenb123 (both 12-?, PF gap
206.26) and JacobRosenzweig/plehv79 (both 3-9, PF 1804.20 vs 1789.78, gap 14.42).
min = **14.42** — exactly the league_year value. Confirms the new tiebreaker
computation (regular-season-weeks-only, same-record adjacent PF gap).

**Per-season position adjustment (`_pos_factor`) — NOVEL: 2023 pure adds
Gus Edwards / Robert Woods / Tim Boyle.**
Computed the 2023 starter baselines straight from player_week starters:
league-starter-avg = 14.6444; RB factor = 14.6444/14.2063 = 1.03084, WR =
1.00984, QB = 17.5527→0.83431. Then `Difference of averages adjusted by position`
= `Difference of averages` × factor (pure adds, so no dropped side):
- Gus Edwards (RB): 9.8647 × 1.03084 = **10.1689** ✓ (sheet: 10.1689)
- Robert Woods (WR): 5.8000 × 1.00984 = **5.8571** ✓ (sheet: 5.8571)
- Tim Boyle (QB): 4.1200 × 0.83431 = **3.4374** ✓ (sheet: 3.4374; QB<1 because
  QBs out-score the starter average — discounted, correct direction).

**Synthesized-row drop counter — NOVEL: Alec Pierce (3 drops).**
transactions.csv shows exactly 3 drop rows for Alec Pierce, each carrying a
populated "Number of times dropped by this team" (AceMatthew=1; BROsenzweig 1→2),
0 blank. player_all_time: drops=3 (= 3 rows), transactions=6 (3 drops + 3 adds).
No desync, no "one numbered one blank".

**Startup draft players remaining — NOVEL: stevenb123 2020 & 2022.**
stevenb123 drafted 19 startup (2020 ESPN, 19-round) players. Startup-picks ∩
season-end roster: 2020 (week 16, correct 16-week season end) = **15**; 2022
(week 17) = **3** (CeeDee Lamb, Lamar Jackson, Tee Higgins). team_year matches both.

**Pick-chain sibling collision (Part G) — NOVEL: 2025 round-2 Oliverwkw 2.02 +
2.09.** PH#170 (2025 2.02, C. Loveland) → prev T#228; PH#442 (2025 2.09 toilet
reward) → prev T#39 / next T#42. Round-trip: T#228 received "2025 2.02(C.
Loveland)"; T#39 received "2025 2.09". The two same-round siblings resolve to
their OWN distinct trades, not each other — the `_R209` sentinel keys the toilet
pick separately. (2024 round-2 JacobRosenzweig 2.02/2.09 confirmed identically.)

**Future-pick valuation — full sweep.** 648 traded-pick assets carry a resolved
slot ("YYYY R.YY"); 306 are round-only ("YYYY R(orig)") — every one a pick traded
before its determining season completed (e.g. a 2026 pick traded before
2025-09-01). Consistent with `_pick_val_label`.

## Part 3 — Diff/consistency audit (full population): PASS

Computed at FULL scale (every row, not sampled) on the freshly-built exports:

- **`player_all_time == Σ player_year`** across all additive counters present in
  both (Number of transactions / drops / trades, Points, Weeks as starter):
  **0 mismatches**. 0 names in player_all_time absent from player_year and vice
  versa (the `existing_names` + `_py_pids` pad guards hold — no phantom-name pads).
- **`team_year` Record wins == Σ `team_week` (Win?==1)** across all 48
  team-seasons: **0 mismatches**.
- **`team_all_time` award rollups == Σ `team_year`** (all 12 `Times …` award
  columns): **0 mismatches**.
- **`Hardship` `team_year` == Σ `team_week`** across all team-seasons:
  **0 mismatches** (engine unchanged by this PR; the diff only retitled its
  tooltip).
- **`Startup draft players remaining`** `league_year == Σ team_year` for every
  season: 2020=98, 2021=66, 2022=33, 2023=24, 2024=15, 2025=9 — all match
  (sensible monotonic decay as startup players age out). team_year matches the
  manual startup-pick ∩ season-end-roster intersection (Part 2).
- **`Amount of FAAB spent` season gate** (full population, all 4 sheets
  team_week / league_week / team_year / league_year): **0** pre-2022 rows carry a
  value and **0** 2022+ rows are blank. Exactly the intended scope.
- **`Number of bids` N/A scope** (full population): all 1052 `free_agent` rows
  N/A; all 29 `waiver` 2020 rows N/A (ESPN data unrecoverable); all 419 `waiver`
  2021+ rows numeric. Exactly the intended scope.
- **`Number of NFL teams among starting/rostered players`** (team grain): the new
  distinct rollup never exceeds Σ team_year (0 violations) and tops out at 31/33
  all-time — a true distinct count, not the old "max" rollup that pinned everyone
  near 10. Correctly non-additive.
- **Build determinism**: transactions.csv, picks.csv and trades.csv are
  **BYTE-IDENTICAL across three independent builds** — the stable-sort full-identity
  tiebreakers hold, so every "#N" / "T#N" / "PH#N" position ref is stable.

### Conclusion: 3-part audit ROUND 3 is **CLEAN**

All accumulated PR fixes are confirmed correct, scoped, and fully isolated on the
current branch tip, verified with fresh NOVEL examples (2022 tiebreaker; 2023
Gus Edwards/Robert Woods/Tim Boyle position adjustment; Alec Pierce drop chain;
stevenb123 startup-remaining; 2025 Oliverwkw 2.02/2.09 sibling chain) and
full-population invariants (every player / team / award / startup / FAAB / bids /
NFL-distinct invariant = 0 mismatches; three builds byte-identical).
`pytest tests/ -q` = 15/15.

**CLEAN — 0 defects found, nothing to fix.**

This is the third consecutive clean stage (5-agent Round 12 + 10-part Round 1 +
this 3-part Round 3), satisfying the governing cycle's "all three pass clean
consecutively" completion criterion.
