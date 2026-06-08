# Phase 12 — Large-scale full-dataset audit (reusable format)

A systematic, end-to-end correctness pass over the **entire** output. Not tied
to a single PR — runs the full battery below, **logs every finding**, then fixes
are batched into follow-up PRs. **Re-run the whole battery until all 9 parts come
back clean.** Keep this format and re-run it after the **ESPN 2020 backfill**
(Phase 13) and any other large data change.

Latest run artifact lives at `/tmp/a<run>`; reconciliation logic is committed as
`tests/test_cross_sheet_reconciliation.py` (durable regression guard).

---

## The 9 parts

**Part 1 — Cross-sheet reconciliation.** Rollups must agree:
- weekly → year → all-time (team_year `Points` = Σ team_week `PF`; all-time = Σ years; same for player Points, `Number of transactions/drops/trades`, hardship weeks; award `Times X?` = Σ weekly `X?`).
- `Record` W-L ↔ Σ `Win?`; Win % = wins/games.
- player ↔ team ↔ league (league_week = Σ team_week; team weekly stats = Σ player_week for that team-week).
- distinct-count columns (year/all `Number of … started/rostered`, cuffs, NFL teams) use distinct players, not weekly sums.

**Part 2 — Stat-family hand-checks.** **20 cases**, of which **≥10 are edge values** (extremes / 0 / N/A) with **at least one of each** type. Derive the expected value from raw data and compare. Cover: scoring (Avg/Adjusted/PPG splits), hardship + SA-Hardship + Luck, all-play win%, PAR/consistency, O-Score (4 components), KTC checkpoints + pick-adjusted diffs, manager skill, turnover, FAAB, trade/transaction value + KTC-over-time, tenure, point/award streaks (incl. skip-missed-weeks).

**Part 3 — N/A vs 0 sweep.** Every `_preserve_na` column renders N/A on genuine no-data and 0 on a real zero; no silent 0-fills, no stray N/A on populated rows.

**Part 4 — Edge cases.** **≥50 unique edge cases across all sheets** to cover all bases: multi-team (traded) players (Top/Last team, Number of teams, tenure splits), 2021 vet/startup exclusions, synthetic 2.09/5.0X picks, commissioner moves + linkage, Taxi-eligible, in-season gates (2026 → N/A playoff/champion/Result), drafted-never-played + never-rostered players, ties, byes, suspensions, position switchers, IR/PUP, etc.

**Part 5 — Duplicate / redundant column sweep.** Scan every sheet for columns with identical (and near-identical) values → flag removal candidates; document survivors in the Formulas sheet.

**Part 6 — Data-quality gaps.** Missing players; name/gsis/NFL-team/position mismatches (re-run the known-error harness); sanity ranges (win% ∈ [0,1], efficiency ≤ 1, no negative counts, plausible ages); determinism (Luck float-noise → round at output).

**Part 7 — Metric accuracy / odd-result hunt.** Actively surface results that *look wrong*: outliers, huge unexpected season-over-season or vs-peer swings, values inconsistent with a player's/team's known reality, suspicious clustering, anything that doesn't read the way it should. Flag for investigation.

**Part 8 — Asset story tracking.** The workbook must tell a **complete start-to-finish story of every single player and pick**. Verify: each player is traceable across all their adds/drops/trades/starts; each pick is traceable from draft → every trade hop → current owner / player it became; no broken chains, no orphaned assets, no dead links.

**Part 9 — Comprehensive cell-by-cell sweep.** A fully exhaustive scan for abnormalities across every cell of every sheet: type mismatches, malformed values, unexpected blanks/zeros/negatives, encoding issues, mis-rendered N/A vs 0 vs "In Progress", stray text in numeric columns, broken links, formatting anomalies.

---

## Deliverables & flow
1. Run all 9 parts → categorized PASS/FAIL findings report.
2. After the **first run**, produce a list of **50 potential improvements** (visual, statistical, code-base, or otherwise) for the user to select from.
3. Fix logged bugs in batched PRs (each its own 3-part audit) + implement selected improvements.
4. **Re-run the full battery until all 9 parts are clean.**

## Pre-logged future fixes (found before/while scoping)
- **Trades next/previous links:** every NON-FAAB next/previous cell in trades should have a working link (FAAB is the only exception). Many are currently missing — fix.
- **Wrap all cells on all sheets**, not just the Formulas sheet.
- **Luck float-noise:** round at output to make builds deterministic (kills the ~1e-16 diff that pollutes every audit).
