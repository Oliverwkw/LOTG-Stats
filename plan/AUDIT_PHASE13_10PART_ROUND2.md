# Phase 13 follow-up — second, independent 10-part audit (Round 2)

A repeat of the `plan/AUDIT_PHASE13_10PART.md` battery against the same
codebase state (PR #319, `claude/phase-13-audit-tsapoy`), run by 4 fresh
parallel sub-agents using **different spot-check examples** (different
teams, players, transactions, seasons) than the original document, per
the standing instruction to keep re-running the battery with new examples
until a clean pass. This round found **3 new, real bugs** (Parts 1 and 8)
that the first 10-part audit's example set didn't happen to exercise.

## Part 1 — Cross-sheet reconciliation: 1 bug found, FIXED

Fresh examples: AceMatthew/Oliverwkw (2020), LWebs53/stevenb123 (2023), 6
fresh team/year pairs for the Record check, 10 fresh players for the
player_all_time rollup check. All reconciliation invariants held **except**:

- **"Number of trades" 2020 week-bucket mismatch.** `league_week`'s count
  (derived from each trade's `Date` via the calendar-anchored `_trade_wk()`,
  `src/lotg.py:14514-14528`) disagreed with `team_week`'s count (derived
  from `tx_by_week`, keyed by the ESPN email-parser's roster-vote
  `trade_week` heuristic, `src/espn_2020.py`) for several 2020 weeks — e.g.
  week 1 showed `league_week`=1, `team_week` summed to 0 instead of the
  expected 2 (a 2-team trade should double-count across the two
  participating teams' rows). 2021+ Sleeper-native trades use one shared
  `created` timestamp for both paths and never hit this, so it was isolated
  to 2020.
  **FIXED**: `src/espn_2020.py`'s trade-injection loop (was `wk =
  t["trade_week"] or 1`) now computes the week bucket with the identical
  calendar rule as `_trade_wk()` (kickoff Sept 7, offseason trades within 7
  days roll into wk 1, deeper-offseason trades get 0 — no double `or 1`
  coercion of a legitimate 0). Verified post-fix: every 2020 week's
  `team_week` sum is now an exact 2x of `league_week`'s count (the expected
  per-trade double-counting ratio for 2-team trades), with zero
  week-bucket mismatches.

## Part 2 — Stat-family hand-checks (24+ cases): PASS

Efficiency/Margin (15 fresh rows across 2020/2022/2024/2025), Diff hi/lo
starters (6 fresh rows), All-play Win% (3 fresh team/year combos) all
matched to 4 decimals. Win Variance N/A-gating verified correct by code
inspection (no live N/A case exists in this cached 2020-2025 dataset since
all 6 seasons are complete).

## Part 3 — N/A vs 0 sweep: 1 new bug found, FIXED

- **picks.csv KTC-checkpoint columns ("KTC on draft day", "KTC at end of
  rookie year", "KTC 1-4 years after draft day") rendered `0.0` instead of
  N/A** under the sandbox's KTC-unreachable condition (`dynasty-daddy.com`
  403). Root cause: `src/lotg.py:9020` gated BOTH the "N/A" default
  initialization (line 9022) and the real-value backfill behind the same
  `_ktc_idx is not None` check — when the KTC index failed to build, the
  columns never even got their N/A default, falling through to a later
  generic numeric fill of `0.0`. Compounding cause: `_preserve_na()` had no
  matching rule for these column names (only the transactions/trades KTC
  columns were covered).
  **FIXED**: split the "N/A" default-initialization out from the
  `_ktc_idx is not None` guard so it always runs; added the 6 KTC
  checkpoint columns to `_preserve_na()`'s allowlist as defense-in-depth.
  Verified post-fix: all 6 columns are 100% N/A (0 non-null) across all 450
  `picks.csv` rows under the unchanged sandbox condition.

Previously-fixed items (FAAB pre-2022, Number of bids 2020) reconfirmed
still correctly N/A, not re-flagged.

## Part 4 — Edge cases (30+ cases): PASS

Different examples (startup-pool players: McCaffrey/Barkley/Mahomes/Kelce/
etc.; vet-pool players: Love/Ryan/Darnold/Pollard/etc.; suspension cases:
Ridley/Hopkins/Watson/Addison/Rice; Wan'Dale Robinson multi-team trade
chain). Synthetic future picks, multi-team trade chains, suspension/bye/
injury mutual exclusivity, 3-year retention N/A gating, zero-activity teams,
non-playoff elimination weeks, and the 2020/2026 season boundaries all
behaved correctly with no discrepancies.

## Part 5 — Duplicate/redundant column sweep: PASS

Systematic pairwise near-equality scan found no new true duplicate-column
pair beyond the already-documented same-NFL-team-family pattern and the
sandbox-artifact KTC=0.0-everywhere-in-picks pattern (the latter explained
by the same Part 3 fix above — these were build-time captures from before
the fix landed).

## Part 6 — Data-quality gaps: PASS

0 duplicate (Player, Year) / (Player, Year, Week) pairs; 0 exact-duplicate
transaction/trade rows; 0 null violations in key columns; 0 player-name
spelling collisions; 0 orphaned transaction/trade rows referencing an
absent (Team, Season).

## Part 7 — Metric accuracy / odd-result hunt: PASS

Weekly PF range 45.36-231.60 (no row exceeds Max PF), luck bounded
[-0.92, 0.73], transaction skill 33.9-47.9 — all realistic. One legitimate
non-monotonic uptick in "Startup draft players remaining" (LWebs53
2022->2023, 3->4) traced to a real trade acquiring four 2020-startup-class
vets — correct by design, not a bug.

## Part 8 — Asset-story tracking (no-teleport test): 1 bug found, FIXED

Traced 16+ players/picks (Hooper, D.Jones, Minshew, Booker, Goff, Shaheed,
Rivers, M.Davis, Chandler, Ertz, Washington, Okonkwo, Barner, Winston, plus
picks for Ferguson/Skattebo/Beckham/Olave/Gesicki/Schoonmaker/Allgeier/
Bryce Young/3 unowned future picks). All link references in-range; no
teleports for free-agent-add or pick-trade chains.

- **Chronological inversion in 3 of 450 `picks.csv` rows** ("Link to next
  transaction" resolved to a date BEFORE "Link to previous transaction"):
  Allen Lazard (2022 2.08), Marquez Valdes-Scantling (2022 4.08), Odell
  Beckham (2023 4.07) — all three are "vet picks" (a veteran free agent
  selected with a rookie-pick slot) who each had an earlier, unrelated
  waiver-wire history that predated the pick itself.
  Root cause: `src/lotg.py:15305-15309` anchored the drafted player's
  chain-start timestamp to `min(all of the player's event dates) - 1 day`,
  regardless of whether the player's globally-earliest event actually
  preceded this particular draft — mis-threading "next" to point at the
  player's pre-draft history instead of the real post-draft event.
  **FIXED**: the anchor now only considers the player's events ON OR AFTER
  this pick's own draft-anchor date (`_fallback`), so an unrelated
  pre-draft history under a different team no longer pollutes the
  chain-start. Verified post-fix: all three players' next/previous links
  now resolve in correct chronological order (e.g. Beckham: prev `T#200`
  2022-10-06 -> next `#910` 2023-09-20).

## Part 9 — Comprehensive cell-by-cell sweep: PASS (beyond the Part 8 finding)

No negative counts/streaks/FAAB/tenure values; all percentile columns
bounded [0.8, 100]; Age 20.8-48.4; Points -5.32 to 57.9 (negative scores
from turnovers are correct); Record sums match team_week game counts for
all 48 team-year rows; 0 duplicate keys in player_year/team_week/
team_year/picks; league_week PF reconciles exactly to Σteam_week PF for a
fresh 2024 wk9 slice.

## Part 10 — ESPN-2020 integration audit: PASS

Fresh examples — teams JacobRosenzweig/plehv79/LWebs53/AceMatthew; players
AJ Dillon, Christian Kirk, Devonta Freeman, Latavius Murray, Tony Pollard.
2020 reconciles like any other season (PF/tx-count sums match exactly); no
teleports across the 2020->2021 seam (all 5 players' roster transitions
trace to dated events — trades, drops/adds, or the 2021 vet-pool
supplemental draft); FAAB/bids N/A columns hold; standings/records
cross-check against `data/commissioner_pick_trades.csv` reconciles;
`pytest tests/ -q` 14/14 passed.

## Fixes applied this round (`src/lotg.py`, `src/espn_2020.py`)

1. **2020 trade week-bucketing consistency** (`src/espn_2020.py`): use the
   same calendar-anchored week rule as `_trade_wk()` instead of the
   roster-vote heuristic, so `team_week` and `league_week` agree on which
   week a 2020 trade lands in.
2. **picks.csv KTC-checkpoint N/A defaulting** (`src/lotg.py:9018-9023`):
   decouple the "N/A" default initialization from the `_ktc_idx is not
   None` guard so it always runs even when the KTC index fails to build;
   added the 6 checkpoint columns to `_preserve_na()`.
3. **picks.csv chronological-inversion fix** (`src/lotg.py:15305-15309`):
   anchor a drafted vet-pick player's chain-start only against their
   events on/after the pick's own draft-anchor date, not their globally
   earliest event.

## Verification

- Offline build (`scripts/offline_build.py`) completes cleanly, no errors.
- `pytest tests/ -q`: 14/14 passed.
- `picks.csv` KTC checkpoint columns: 0 non-null / 100% N/A across all 450
  rows under the unchanged sandbox KTC-unreachable condition (previously
  100% fabricated `0.0`).
- `picks.csv` Lazard/MVS/Beckham next/previous-transaction links now
  resolve in correct chronological order.
- `team_week`/`league_week` 2020 "Number of trades": every week's
  `team_week` sum is now an exact 2x of `league_week`'s count (matching
  the expected per-trade double-counting ratio for 2-team trades), with
  zero week-bucket mismatches remaining.

### Conclusion

This round found 3 real, narrow bugs that the first 10-part audit's
particular example choices didn't surface — confirming the value of
repeating the battery with fresh examples. All three are fixed and
verified. Per the standing instruction, a further round (Round 3) should
be run with yet another fresh set of examples to confirm a clean pass
before concluding the audit series.
