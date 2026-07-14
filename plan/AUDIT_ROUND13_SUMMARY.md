# Round 13 — 5-agent / 10-part full-population audit (summary)

Fresh full-population audit of the LOTG-Stats workbook, run as **5 sub-agents,
one at a time** (sequential, not parallel), each owning a part-pair of the
standard 10-part battery, under an explicit **over-inclusive** reporting rule
(flag every anomaly; classify each as CONFIRMED DEFECT / BY-DESIGN /
NEEDS-HUMAN-JUDGMENT; never silently drop; prefer false positives).

**Build under audit:** deterministic offline rebuild (`scripts/offline_build.py`,
exit 0, only the 2 expected network-unavailable warnings —
`api.sleeper.app/v1/league/0` and `.../draft/espn_2020_draft`). Committed
`exports/` were refreshed from this rebuild as the Round-13 baseline. Population:
6 seasons 2020-2025, 8 teams, 808 team-weeks, 21,376 player-weeks, 514 picks
(future pool now extends through 2030), 1,510 transactions, ~504 trades.

## Result: FULLY CLEAN — 0 confirmed defects across all 10 parts

| Agent | Parts | Scope | Result |
|-------|-------|-------|--------|
| 1 | A+B | full-population completeness + cross-sheet reconciliation | CLEAN |
| 2 | C+D | tooltip/formula-definition accuracy + asset-history narrative | CLEAN |
| 3 | E+F | domain-bounds/plausibility + N/A-vs-0 correctness | CLEAN |
| 4 | G+H | asset-chain link integrity + workbook-structural integrity | CLEAN |
| 5 | I+J | ESPN-2020 integration + build/test/determinism | CLEAN |

**Verification:** `pytest tests/` → 46 passed / 0 failed. Determinism: two
independent fresh builds produced **byte-identical** transactions/trades/picks/
player_year/team_year/player_week/team_week/league_week (md5 match). Offline
build exit 0. 661-player continuity audit: 0 breaks. Zero teleports across the
2020→2021 seam.

## Over-inclusive items surfaced (no confirmed defects — all by-design or for human awareness)

Two items were independently corroborated by multiple agents and are the only
items warranting a human glance. Neither is a defect in the committed exports:

1. **Offline KTC columns are 100% empty (latent offline-fallback gap).** The KTC
   index build (`build_index()`) does a live network fetch that 403s in the
   sandbox, so the `_ktc_idx = None` fallback leaves all KTC/O-Score-derived
   columns empty **offline**. Production (with real network) populates them
   normally, so the committed/CI exports are unaffected. The minor latent gap:
   the on-disk `data/ktc_backfill/` (563 files of real values) is never consulted
   as an offline fallback. **Human decision:** whether to wire the on-disk
   backfill in as an offline fallback. (Moot for 2020 — 2020 KTC is N/A in every
   environment, no pre-Aug-2021 KTC history exists.)

2. **`season_2026` snapshot present but build cuts off at 2025 (correct, but
   silent).** The snapshot carries real 2026-dated transactions/trades (incl. a
   documented first-ever 5-team trade) that are intentionally unrealized under
   the 2019-2025 build scope. Confirmed **no 2026 value leaks** into any
   season-keyed sheet (all exactly {2020-2025}; 2026-2030 picks correctly carried
   as future-pool placeholders). The only borderline: the unmatched-overlay /
   unmatched-commissioner-ledger warning is debug-gated, so the 6 unrealized 2026
   ledger rows are silent in a normal build. **Human decision:** whether to
   surface that warning non-silently. The cutoff itself is correct.

Other flagged-but-by-design items (per-agent docs have full detail): documented
trade exclusions (1 phantom-merge + net-zero FAAB swaps); presence-only
transaction-count reconciliation; 2020 bilateral trade double-count; `Commissioner
moved?` uniformly False (tripwire that correctly never fires); toilet-bracket
ranking by record+PF; xlsx per-asset column expansion; terminal links as empty
cells vs literal `N/A`; a Round-12-template wording slip on the change-in-points
gate (current export is correct per source).

## Per-part findings documents

- `plan/AUDIT_ROUND13_PARTSAB.md`
- `plan/AUDIT_ROUND13_PARTSCD.md`
- `plan/AUDIT_ROUND13_PARTSEF.md`
- `plan/AUDIT_ROUND13_PARTSGH.md`
- `plan/AUDIT_ROUND13_PARTSIJ.md`
