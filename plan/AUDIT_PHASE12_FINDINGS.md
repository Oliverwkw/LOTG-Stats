# Phase 12 — Findings (first full pass) + 50+ improvements

First run of the 9-part audit against the latest build. The dataset is in very
good shape — Parts 8 (asset story) and 9 (cell sweep) came back clean, 54/55
edge cases passed, 8/9 rollups reconcile. Bugs found are listed first, then the
50+ improvements list to choose from.

## Bug findings (to fix, batched)
1. **player_year missing not-yet-played-season rows.** Players whose only 2026 activity is off-season transactions get no player_year 2026 row → `player_all #transactions` ≠ Σ player_year (114 players) and a hole in the asset story. *Fix:* pad player_year with current-season rows for players with off-season tx/trades (Age/Result/etc. N/A).
2. **`Age = 0` instead of N/A** on padded tx-only player_year rows (60 rows, no weekly data). Also verify players with known birth dates aren't mis-mapped to 0. *Fix:* render Age N/A when no birth-date-derived age; investigate any id/name-map gaps.
3. **`PPG starter` (and PPG bench / Adjusted variants) = 0.0 instead of N/A** for never-started / never-benched players (e.g. A.T. Perry, 0 starts → PPG starter 0.0). *Fix:* N/A when the denominator (weeks started/benched) is 0.
4. **FAAB exceeds the 100 budget.** Single `Faab` bid of 120; team_week `Amount of FAAB spent` up to 249 (plehv79 2025 wk1); season totals to 258. Either the budget isn't 100 or FAAB is mis-scaled/double-counted. *Fix:* confirm Sleeper FAAB budget + dedupe/scale.
5. **(minor) 1 player has `Points (full season)` < `Points` (rostered).** Should be ≥. Edge — investigate the single row.

## Pre-logged fixes (your flags + determinism)
6. **Trades next/previous links** — every NON-FAAB next/previous cell should link (FAAB is the only exception); many are currently empty.
7. **Wrap all cells on all sheets** (not just the Formulas sheet).
8. **Round Luck at output** to kill the ~1e-16 nondeterminism that pollutes every diff.

---

## 50+ potential improvements (select any)

### A. Statistical / new metrics
1. **Manager Elo / power-ranking history** — weekly Elo from H2H, rises/falls over time.
2. **Luck-adjusted standings** — re-rank each season by Pythagorean/all-play expected wins vs actual finish.
3. **Schedule-strength** column — avg opponent PF/win% faced per team-season.
4. **Playoff odds / contention window** — team age (incl. picks) vs win% cycles; rebuild-vs-contend signal.
5. **Positional ROI** — capital invested per position (draft + FAAB + trade) vs points returned.
6. **Buy-low / sell-high detector** — trades where an asset's KTC moved hardest *against* the deal direction.
7. **Empirical draft-value curve** — fit realized O-Score/KTC by slot to derive the league's *real* slot value.
8. **"True draft order" redo** — re-rank each class by realized outcome; surface steals & reaches.
9. **Clutch index** — regular-season vs playoff PF/win% delta per manager.
10. **Consistency rank** — league-wide percentile of each player's volatility/floor/ceiling.
11. **Boom/bust by position** — positional boom/bust thresholds instead of flat 20/5.
12. **Strength of victory/defeat** — quality of teams a manager beat/lost to.
13. **Win probability added (per week)** — how much each player's score swung their matchup outcome.
14. **Rolling form** — 3-week rolling PF / player PPG trend columns.
15. **Trade tree / lineage string** — one readable "2021 1.04 → … → 2026 1st" per current asset.
16. **Keeper/dynasty value retention** — % of a manager's draft capital still on roster N years later.
17. **Expected vs actual finish** delta (over/under-performance) per season.
18. **Head-to-head "rivalry index"** — every pair's record, avg margin, biggest blowout, closest game.
19. **Bench points lost to bye/injury** vs to bad start/sit (split the existing regret).
20. **Per-manager tendency profile** — trade freq, FAAB aggression, RB-vs-WR lean, churn vs patience.

### B. Visual / xlsx UX
21. **Conditional-format more value columns** (PAR, Luck, KTC diff, addition value) with the same scale.
22. **Data bars** on count/streak columns for quick magnitude scanning.
23. **Icon sets** (▲/▼) on change-from / season-over-season columns.
24. **A "Dashboard" tab** — league leaders, records, current standings, top streaks, at a glance.
25. **Per-team "team card" view** (filtered) — one printable page per manager.
26. **Sparklines** for weekly PF / player PPG trends.
27. **Hyperlink team names** → team_all_time (the team-name equivalent of 11D).
28. **Hyperlink pick labels** in trades to the picks sheet.
29. **Group/outline collapse** for the big roster-construction column blocks.
30. **Conditional highlight of records** (all-time highs/lows) in their cells.
31. **Freeze + filter presets / named views** per sheet.
32. **Tooltip/comment** on cryptic headers pulling the Formulas definition.
33. **Color the "In Progress" streak cells** subtly so active runs stand out.
34. **Two-tone bands** alternating within topic groups for very wide sheets.

### C. Data quality / sources
35. **Backfill missing birth_dates** (the Age=0 set) from a secondary source.
36. **Position-switcher audit** (Taysom Hill etc.) — confirm weekly position is right.
37. **NFL-team-per-week validation** vs schedule for traded players.
38. **Dedup near-identical name variants** (e.g., "AJ" vs "A.J.") across sources.
39. **Confidence flag** on KTC values sourced from sparse pre-2021 history.
40. **Cross-check Sleeper points** vs nflverse fantasy points; flag large divergences.
41. **Injury-tracker coverage report** once 2026 data lands (Part of PR E follow-up).

### D. Code-base / infra
42. **Round all float outputs** deterministically (kills Luck-style noise everywhere).
43. **Promote the audit battery** to committed tests (reconciliation done; add sanity-range + N/A-vs-0 + edge-case suites).
44. **Snapshot/golden-file test** — diff each sheet vs a checked-in golden to catch unintended changes.
45. **Build-time data-quality log** — emit the sanity-range/anomaly summary into build_debug.log every run.
46. **Parametrize thresholds** (boom 20 / bust 5 / 150-PF / FAAB budget) in config instead of hard-coded.
47. **Speed up the xlsx writer** (per-cell styling loops are the slow part) via column-level styles.
48. **Split lotg.py** (~13k lines) into modules per sheet/concern for maintainability.
49. **CI step running the test suite** (coverage + reconciliation + freshness) on every build.
50. **Type-annotate + lint** the hot paths; add a pre-commit.

### E. Stretch / product
51. **Weekly digest email** (Phase 14) seeded from these metrics.
52. **A web/Looker view** over the CSVs for interactive exploration.
53. **Historical "record book" sheet** — every all-time record with holder + date.
54. **What-if optimal-lineup replays** — season win% under perfect start/sit.
55. **Awards show** — auto-generated season superlatives per manager.
