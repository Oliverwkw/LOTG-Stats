# Phase 13 — comprehensive 10-part audit

Build under audit: local offline build (`scripts/offline_build.py`, league id
`1192931349575991296`, seasons 2019–2025) on top of `6d83635` (Phase 13 #318,
"Startup draft players remaining = N/A for not-yet-played seasons" — the last
committed Phase-13 fix before this audit). The audit battery is the standard
9-part RUN3 battery (`plan/AUDIT_PHASE12_FINDINGS_RUN3.md`) plus a 10th part
dedicated to ESPN-2020 integration specifically, per the Phase 13 MASTER_TODO
spec.

This audit used 4 parallel sub-agents (Parts 1-3, Parts 4-6, Parts 7 & 9,
Part 10) whose findings were cross-checked against each other and against
direct CSV/pandas verification before being accepted. Two agent claims were
**rejected as false positives** after independent reproduction (see below).

---

## Part 1 — Cross-sheet reconciliation: PASS

All RUN3 invariants still hold post-Phase-13 (league_week = Σ team_week for
PF/tx/injuries/suspensions/bye/FAAB/donuts; team_year Record = Σ team_week
Win?; 11 award rollups Δ=0; Total trades = Offseason + Inseason; player_all_time
= Σ player_year for drops/trades/starts). 2020 reconciles identically to every
other season — no special-cased breakage at the 2020↔2021 seam.

## Part 2 — Stat-family hand-checks (20 cases): PASS

Efficiency = PF/MaxPF, Margin = PF−PA, #284 records, Diff hi/lo starters,
All-play−Win%, Win Variance (2026 N/A-gated) all check out for 2020-2025
alike. No season-specific formula divergence found for 2020.

## Part 3 — N/A vs 0 sweep: 2 bugs found, both fixed (see Fixes below)

- **Amount of FAAB spent** rendered `0.0` for every 2020/2021 team_week /
  team_year / league_week / league_year row instead of `N/A`, even though the
  league had no FAAB system before 2022 (confirmed existing convention at
  `src/lotg.py` transactions-row gate, `int(season) < 2022`). **FIXED.**
- **Number of bids** rendered fabricated `0`/`1` values for every 2020 waiver
  transaction instead of `N/A`. Competing-waiver-claim data for 2020 is
  documented as unrecoverable from a single manager's ESPN cookies
  (`plan/notes/espn_2020_backfill.md`, "DECISION PENDING" item — resolved here
  as N/A, matching the FAAB-bid columns' existing treatment of the same gap).
  **FIXED.**

## Part 4 — Edge cases (50+ cases): PASS

2020 startup-pick edge cases (9 synthetic future-pick slots, multi-team
seasons, suspensions/byes/injuries, retention-rate N/A gating) behave
identically for 2020 as for 2021+. No 2020-specific edge-case regressions.

## Part 5 — Duplicate / redundant column sweep: PASS

No new true duplicates introduced by the ESPN-2020 backfill. The
same-NFL-team family noted in RUN3 is unchanged.

## Part 6 — Data-quality gaps: 1 bug found, fixed (see Fixes below)

- **player_year duplicate-name rows.** A small number of players (confirmed:
  Justin Jefferson, DJ Moore, Tyler Johnson) had the appearance of "two
  player_year rows for the same year." Root cause: the tx-only padding pass
  (added in Phase 12 to backfill `player_year` rows for players who only
  appear in transactions, e.g. Tom Brady's 2023 drop-to-FA) keyed its
  "does this row already exist" check by `(Player ID, Year)` only. When a
  same-named player had a transaction-only event under a *different*
  Sleeper ID than the one already carrying their real, pw-derived row for
  that year, the padding pass added a second, phantom row under the
  alternate ID — same display name, same year, looking like a duplicate.
  `player_week.csv` itself was clean for all affected players; the bug was
  isolated to the padding step. **FIXED** (padding now also checks a
  `(name, year)` set built from the real rows and skips any pad row that
  would collide with one).

## Part 7 — Metric accuracy / odd-result hunt: PASS

Score extremes, luck/unluck leaders, transaction-skill range, and
3-year-retention churn for 2020-era rookie classes all read as realistic
dynasty outcomes, not bugs.

## Part 8 — Asset-story tracking (no-teleport test): PASS

0 out-of-range link references across transactions/trades. The 10
zero-event startup cornerstones and the 71 initial-roster vets remain the
known, by-design Phase-13 origin gap (no realized transaction before their
first appearance) — not a defect (see Part 10 cross-check below).

## Part 9 — Comprehensive cell-by-cell sweep: PASS

No new findings beyond Parts 1-8 across a wide cell-by-cell pass over
team_week/team_year/league_year/picks/player_week/player_year/transactions/trades.

## Part 10 — ESPN-2020 integration audit: PASS (1 robustness gap found, fixed)

Specifically verified for the 2020 ESPN backfill:
- **2020 reconciles like any other season** — same Part 1 invariants hold
  for 2020 rows as for 2021+ (no 2020-specific carve-out needed).
- **No teleports across the 2020→2021 seam** — every team's 2021 week-1
  roster traces back to a real 2020 end-of-season roster state (startup
  draft + 2020 adds/drops/trades), confirmed via the email-trade-augmented
  chain documented in `plan/notes/espn_2020_backfill.md`.
- **2020-specific N/A columns are correct**: FAAB (2020 had no real bidding —
  `bidAmount=0` for every 2020 waiver) and Number of bids (2020 competing-claim
  data unrecoverable) both now render N/A — see Part 3/6 fixes.
- **Standings/playoffs/records for 2020 are right**, including the 8-team
  2020 startup-draft-derived rosters and the email-sourced trade ledger
  (cross-checked against `data/commissioner_pick_trades.csv` — reconciles).
- **Nothing in 2021+ regressed**: all RUN3-era invariants and the full test
  suite (`pytest tests/`, 14/14) and `scripts/audit_player_history.py`
  (659 players audited, 0 continuity breaks) still pass post-fix.
- **Robustness gap (not a 2020-specific data bug, but discovered via the
  2020-integration code path):** the picks-KTC enrichment pass
  (`src/lotg.py`, dynasty-daddy `build_index()` call) left `_ktc_idx`
  unbound if `build_index()` raised before assigning it — in this sandboxed
  offline environment, dynasty-daddy is unreachable (proxy returns 403),
  so every build hit `UnboundLocalError: _ktc_idx` deep in the picks pass.
  This is an environment-specific failure mode (CI/production has real
  dynasty-daddy access), but the code should degrade gracefully rather than
  crash regardless of environment. **FIXED** (`_ktc_idx = None` initialized
  before the `try:` block).

### Investigated and REJECTED as false positives

- **"71 initial-roster vets untraceable to a 2020 origin."** One sub-agent
  (Part 4-6) reported 0/8 spot-checked vets resolving to a 2020 startup-draft
  origin. Direct re-verification against `exports/picks.csv`'s
  `Year=='startup'` pool found all 8 names present and correctly attributed.
  The sub-agent's check was bugged; no real defect exists. This matches the
  Part 10 sub-agent's independent finding (71/71 resolved cleanly).
- **"Startup draft players remaining is always 0."** One sub-agent (Part
  1-3) flagged this column as universally zero across all team/week/year
  rows, suspecting the Phase-13 `Startup draft players remaining = N/A for
  not-yet-played seasons` fix (#318) had over-broadened the N/A gate into
  played seasons too. Root-caused via temporary debug instrumentation in
  `_startup_remaining_maps` / `_startup_remaining_count`
  (`src/lotg.py:877-928`) across two offline builds: the intersection logic
  is correct and produces real, non-zero, sensibly-declining counts across
  every team and season 2020-2025. The "always 0" read was a stale-export
  artifact from earlier in the audit session, not a build-time bug. No code
  change made (instrumentation fully reverted, confirmed zero net diff
  before any real fix work began).

---

## Fixes applied (`src/lotg.py`)

1. **KTC `_ktc_idx` UnboundLocalError robustness fix.** Initialize
   `_ktc_idx = None` before the `try:` block that calls
   `build_index(...)`, so a KTC-index build failure (network unavailable,
   dynasty-daddy down, etc.) degrades to "no KTC enrichment" instead of
   crashing the whole picks pass.
2. **"Amount of FAAB spent" N/A for pre-2022 seasons.** Gated the
   team_week / team_year / league_week / league_year rollups to `None` for
   `season < 2022` (mirroring the existing per-transaction FAAB gate), and
   added `"amount of faab spent"` to the `_preserve_na()` allowlist so the
   export pipeline's blanket fill-with-0.0 step doesn't re-zero it.
3. **"Number of bids" N/A for 2020.** Gated the per-transaction
   `Number of bids` (and the dependent `Total FAAB bid`, already gated)
   computation to skip for `season == 2020`, per the documented decision in
   `plan/notes/espn_2020_backfill.md` that 2020 competing-waiver-claim data
   is unrecoverable from a single manager's cookies. Added
   `"number of bids"` to `_preserve_na()`.
4. **player_year duplicate-name pad rows.** The tx-only player×year padding
   pass now also tracks a `(name, year)` set from the real, pw-derived
   `player_year` rows and skips adding a pad row whenever its `(name, year)`
   already has a real row under a different Player ID, eliminating the
   phantom duplicate-name rows (confirmed clean: 0 remaining `(Player,
   Year)` duplicates in the rebuilt `player_year.csv`).

## Verification

- Offline build (`scripts/offline_build.py`) completes cleanly with no
  errors or new warnings.
- `pytest tests/ -q`: 14/14 passed.
- `scripts/audit_player_history.py exports/LOTG_Stats.xlsx`: 659 players
  audited, 0 continuity breaks.
- Spot-checked rebuilt exports directly: `Amount of FAAB spent` is NaN for
  every 2020/2021 row and a real positive number for every 2022+ row in
  team_week/team_year/league_week/league_year; `Number of bids` is NaN for
  every 2020 transaction and a real 1/2/3+ value for 2022+ waiver claims;
  `player_year.csv` has 0 duplicate (Player, Year) pairs and Justin
  Jefferson / DJ Moore / Tyler Johnson each have exactly one row per year.
