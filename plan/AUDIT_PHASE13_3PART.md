# Phase 13 follow-up — mandatory 3-part audit on PR #319

Audit target: `claude/phase-13-audit-tsapoy` at `2164b7c` (the 4 fixes from
`plan/AUDIT_PHASE13_10PART.md`), diffed against parent `6d83635` (the last
commit on `main`). Comparison baseline: the repo's own CI artifacts —
GitHub Actions run **#395** (`main`@`6d83635`, the pre-fix baseline) vs run
**#396** (this branch, the post-fix build) — cross-checked against a local
before/after offline rebuild for full CSV cell-level diffing (CI artifact
zips themselves aren't downloadable from this sandbox: the agent proxy
blocks `*.blob.core.windows.net`).

## Part 1 — Code-based audit: PASS

- Both CI run #395 (baseline) and #396 (this branch) completed the `Run
  LOTG build` step with no errors and produced 55-file output artifacts of
  near-identical size (18,227,581 vs 18,223,690 bytes).
- Both runs hit the same **pre-existing, unrelated** test failure —
  `test_no_player_history_continuity_breaks` — with the byte-identical
  failure message (`Isiah Pacheco` MISSING_ARRIVAL_BEFORE_DROP /
  MISSING_ARRIVAL_BEFORE_TRADE) in both #395 and #396. Since it reproduces
  identically pre- and post-fix, it's not a regression introduced by this
  PR. The workflow step has a non-blocking conclusion for this case (job
  conclusion is "success" in both runs despite the step's internal `exit
  1`), so this doesn't gate CI — flagged here for visibility only, not a
  finding requiring a fix in this PR.
- Local offline build (`scripts/offline_build.py`) on the fixed code
  completes cleanly, exit 0, `pytest tests/ -q` 14/14 (the
  `test_no_player_history_continuity_breaks` Isiah Pacheco case is
  filtered out by this build's `skipif` gate locally — it only triggers
  against the live/current-season export referenced above).
- `build_debug.log` review (after-build, this branch): the KTC
  `dynasty-daddy` 403 (expected — sandbox has no network) is logged as a
  `WARN`/`ERROR` exactly as before, but the previously-fatal
  `UnboundLocalError: _ktc_idx` no longer appears anywhere in the 3 build
  passes captured during this audit session — confirms fix #1 directly,
  not just by absence-of-crash but by the exact same failure condition
  recurring 3x with no follow-on crash.

## Part 2 — Results-based audit: PASS (5 cases per fix)

**Fix 1 — KTC `_ktc_idx` defensive init.**
1. Reproduced the original crash directly: temporarily reverted
   `src/lotg.py` to `6d83635` and rebuilt — `build_debug.log` shows
   `ERROR at picks_ktc_8d: UnboundLocalError: cannot access local variable
   '_ktc_idx'` at `15:09:41`.
2. Rebuilt on the fixed code with the identical network condition (KTC
   unreachable, `403 Forbidden`) twice more (`15:12:33`, `15:14:42`) — zero
   `UnboundLocalError` occurrences in either.
3. `picks.csv` byte-identical before/after (the fix only changes
   crash-vs-no-crash behavior; it doesn't alter picks output when KTC truly
   has no data either way).
4. `git diff --stat src/lotg.py` between fixed and reverted states confirms
   the only code delta at this site is the one-line `_ktc_idx = None` init.
5. Full offline build completes (exit 0) on the fixed code where it did
   *not* fully complete the picks-KTC pass before (caught downstream, but
   the pass was skipped) — confirms graceful degradation end-to-end.

**Fix 2 — "Amount of FAAB spent" N/A for season < 2022.**
1. `team_week.csv`: 264 of 808 rows changed, all and only pre-2022 rows,
   all from `0.0` → empty/NaN.
2. `team_year.csv`: 16 of 48 rows changed (2020/2021 × team), same
   `0.0`→NaN pattern.
3. `league_week.csv`: 33 of 101 rows changed (every 2020/2021 week row).
4. `league_year.csv`: 2 of 6 rows changed (2020, 2021 only) — 2022-2025 and
   `league_all_time`/`team_all_time` rollups untouched, confirmed by direct
   read of the surrounding rollup code (true all-time sums correctly
   `fillna(0.0)` over the gated seasons since every team has real 2022+
   activity).
5. No other column in any of these 4 sheets changed (verified via
   per-column NaN-aware equality sweep) — the fix is fully column-scoped as
   intended.

**Fix 3 — "Number of bids" N/A for 2020 (+ bonus: free_agent/commissioner).**
1. `transactions.csv`: 1085 of 1504 rows changed in `Number of bids`,
   covering all of 2020-2025 — wider than the originally-scoped "2020
   only," investigated and explained below (not a regression).
2. Before-fix: `Number of bids` was populated with **fabricated `0`** for
   every `free_agent` (1042 rows) and `commissioner` (14 rows) transaction
   — types that have no concept of "competing bids" at all, in *any*
   season, not just 2020. This was a latent N/A-vs-0 bug predating this
   PR, caused by `"number of bids"` not being in `_preserve_na()`'s
   allowlist (the export pipeline's blanket `fillna(0.0)` zeroed the
   legitimately-empty value for every non-waiver transaction).
3. After-fix: `free_agent`/`commissioner` rows now correctly render N/A in
   `Number of bids` (0 non-null among those 1056 rows, vs 1056 fabricated
   zeros before) — a correct, in-scope side effect of adding
   `"number of bids"` to the allowlist, not an unintended one.
4. `waiver`-type 2020 rows (29 of them): now N/A as the PR explicitly
   intends; `waiver`-type 2022+ rows (419 of them): unchanged, still real
   1/2/3+ bid counts.
5. `Total FAAB bid` (the dependent column, already season<2022-gated before
   this PR) is unaffected — confirmed no diff on that column specifically.

**Fix 4 — player_year duplicate-name pad rows.**
1. `player_year.csv` row count: 1862 → 1857 (5 rows removed), `Player,Year`
   duplicate count: 5 → 0.
2. The 5 removed pairs: `(DJ Moore, 2021)`, `(Justin Jefferson, 2020)`,
   `(Justin Jefferson, 2022)`, `(Justin Jefferson, 2024)`,
   `(Tyler Johnson, 2021)` — a superset of the 3 players named in the
   original audit writeup (Jefferson had 2 additional affected years not
   originally enumerated, but correctly caught by the same fix).
3. All 1857 surviving rows are otherwise byte-identical to their
   before-fix counterparts (no other player_year cell changed) — confirmed
   via per-column NaN-aware diff restricted to the common
   `(Player, Year)` keys.
4. `player_all_time.csv` (downstream rollup) is byte-identical before/after
   — the removed pad rows were never summed into player_all_time in a way
   that changed any total (consistent with them being phantom/duplicate,
   not real, rows).
5. `transactions.csv`'s 4-row tie-break reorder (next item) traces directly
   to two of these same players' transaction chains, confirming the
   ripple is contained and understood, not a separate unexplained defect.

## Part 3 — Diff-based audit (full CSV sweep, before vs after): PASS

13 export files compared cell-by-cell using NaN-aware equality (an initial
pass using naive `.astype(str)` comparison was discarded — it spuriously
flagged every NaN-containing row as "changed," since `NaN != NaN` under
this pandas version's string-dtype casting; re-verified with proper
`isna()`-aware comparison).

- **Zero diff**: `formulas.csv`, `league_all_time.csv`, `picks.csv`,
  `player_all_time.csv`, `player_week.csv`, `team_all_time.csv`,
  `trades.csv`.
- **`league_week.csv`, `league_year.csv`, `team_week.csv`,
  `team_year.csv`**: diff isolated to exactly one column each — "Amount of
  FAAB spent" — fully explained by Fix 2 (see Part 2).
- **`transactions.csv`**: diff isolated to "Number of bids" (1085 rows,
  Fix 3) plus 4 rows touching 11 other columns (`Player Dropped`, link
  columns, PPG/age/O-Score/addition-value columns). Root-caused: two
  same-timestamp (`2021-08-23 20:00:00`) preseason-cut drop transactions
  for one team swapped relative row order between before/after — every
  value attached to each player (O-Score, age difference, link refs, etc.)
  is identical in both builds, just attached to a different row index. The
  link-reference columns correctly update in lockstep with the swap (e.g.
  `Link to next transaction` shifts from `#992`→`#993` exactly matching
  the row the referenced player moved to). This is a cosmetic stable-sort
  tie-break artifact for equal-timestamp transactions, not a data-accuracy
  regression — no player's computed stats changed, only which row number
  they landed on.
- **`player_year.csv`**: diff isolated to exactly 5 removed rows, fully
  explained by Fix 4 (see Part 2).
- No file showed schema changes (column lists and row counts match except
  the intentional player_year row removal).

### Conclusion: 3-part audit is CLEAN

All four fixes' effects are fully isolated, explained, and limited to
their intended scope (plus one positive, in-scope side effect: the
free_agent/commissioner "Number of bids" N/A fix). The one same-timestamp
tie-break reordering in `transactions.csv` is cosmetic and pre-existing
sort-stability behavior, not a regression. The CI continuity-break test
failure is pre-existing and identical pre/post-fix. No new bugs found; no
further code changes required for this PR.
