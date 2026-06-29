# Phase 13 — 10-part audit (this cycle, Round 1), Parts 1-3: CLEAN

First segment (Parts 1, 2, 3) of the 10-part audit, run as the third audit type
of the current standing cycle. Prior to this, the cycle's 3-part audit passed
clean (Round 2, `e6444ab`) and the 5-agent battery achieved its first fully-clean
round (Round 12, `50a86fc..a693e9a`). This 10-part type had not yet run this
cycle.

## Environment / freshness

- **Worktree self-check:** the recurring stale-worktree bug recurred — HEAD
  landed at `6d83635`, and `git merge-base --is-ancestor a693e9a HEAD` printed
  NOT_OK. Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`a693e9a`, the
  Round-12 Parts I/J tip). Confirmed `OK_AT_OR_AHEAD` with `git log -1` = `a693e9a`.
- **Build:** fresh offline build (`PYTHONPATH=src:lib python3
  scripts/offline_build.py`, exit 0; only the 2 expected network-unavailable
  warnings — `api.sleeper.app/v1/league/0` and `…/draft/espn_2020_draft`).
- **Tests:** `PYTHONPATH=src:lib python3 -m pytest tests/ -q` → **15 passed**.
- **Determinism:** ran the build TWICE from identical source; every sheet
  (data CSVs, picks, trades, transactions, all by md5/cmp) is **byte-identical**
  across the two builds. (Note: the build regenerates `picks/trades/transactions/
  xlsx/zip` with diffs vs the *committed* baseline, but those are confined to KTC/
  O-Score columns — 100% NaN in the no-network sandbox — plus stale-commit drift;
  per the audit-series convention `exports/` is build output and was restored with
  `git checkout -- exports/`. A first transient `cmp` "DIFFERS" on transactions.csv
  was investigated and ruled out — re-running md5/cmp after the build fully
  flushed showed identical files; it was a copy/race artifact, not nondeterminism.)

Full population: player_year 1,859; player_all_time 649; player_week 21,376;
team_week 808; team_year 48; team_all_time 8; league_week 101; league_year 6;
league_all_time 1; picks 450; trades 504; transactions 1,514. (Same stable shapes
as Rounds 6-12.)

All examples below are NOVEL — disjoint from every prior round's documented cast
(avoided Puka Nacua / Rachaad White / Jordan Addison / Treylon Burks / Anthony
McFarland / Antonio Brown and the Rounds 4-12 + Phase-12 RUN3 exclusion lists).

## Result: PASS on Parts 1-3, zero defects, no source change.

---

## Part 1 — Cross-sheet reconciliation: PASS (full population)

Every additive aggregate reconciles exactly across grains (0 mismatch unless noted):

- **player_all_time == Σ player_year**, 20 additive columns: Points, Number of
  transactions/drops/trades, Weeks missed due to injury/suspension, Weeks as
  starter, and all 13 "Times as …" award counters (POTW/QB/RB/WR/TE OTW,
  Benchwarmer + Bench QB/RB/WR/TE OTW, Highest/Lowest starter, Captain). **0/649
  mismatches each.**
- **team_year == Σ team_week**: PF→Points, Points against, all 12 "Times …"
  award rollups (Brosenzweig/Sisenzweig/Highest/Lowest/Narrowest/Largest/Most+
  Least efficient/Top-half/One-man-army/Most-bench/Most-injured), Win?→Record W,
  weeks-count→Record games (W+L+T, incl. playoffs), donuts, under-10/over-20..50
  (player + starter variants), Number of Injuries→Weeks of injuries (+ suspensions,
  + starter variants), Number of transactions, FAAB, Starter-adjusted Hardship,
  Loss-from-hardship?→Losses-from-hardship. **0 mismatches across 48 team-seasons.**
- **team_all_time == Σ team_year** (12 award rollups + Points + Points against):
  **0 mismatches.**
- **league_week == Σ team_week** (PF, transactions, injuries, suspensions, bye,
  donuts): **0.** **league_year == Σ team_year** (transactions): **0.**
- **player_year Points == Σ player_week Points**: **0/all rows.**
- **trades.csv ↔ picks/team provenance:** 504 rows = 247 distinct trade events;
  every row's "Number of teams involved" equals its actual {Team + traded-with}
  set size; rows-per-trade == team-set size for all 247; Σ team-counts = 504. Per
  Team/Season trade rows == team_year Total trades (0 mismatch), and team_year
  Total trades == Offseason + Inseason (Δ=0 all rows).
- **transactions.csv internal:** 1,514 rows (matches the documented 1,052 FA + 448
  waiver + 14 commissioner decomposition); all 6 seasons present.

### Observations (NOT defects — pre-existing, matches prior dispositions)

- **Hardship year-sum vs team_week-sum differs by ≤0.0004** on 13 team-seasons —
  pure 4-decimal display-rounding accumulation (Σ of rounded weeklies vs separately
  rounded annual). This is the known F4 float-noise (deferred/won't-fix per user);
  Starter-adjusted Hardship reconciles exactly.
- **transactions.csv row count does NOT equal team_year "Number of transactions".**
  team_year's count is an event-credit model that folds trades into the count
  (1,929 total), while transactions.csv is one row per add-event + pure-drop rows
  (1,514) and excludes trades (which live in trades.csv). This is stable vs the
  committed baseline (both 1,929 / 1,514) and across all prior clean rounds; prior
  Part B rounds verified the 1,514 decomposition and the league=Σteam / team_week=
  team_year invariants (all of which hold) without claiming detail-file == count.
  The in-source comment near `src/lotg.py:4434` ("reconciles row-for-row")
  describes the intent of one non-trade counting branch, not a global guarantee.
  No reconciliation contract is violated; left as-is, consistent with prior rounds.

---

## Part 2 — Stat-family hand-checks: PASS (22 novel cases, all hand-verified)

Each value recomputed from raw player_week / team_week and matched to the export:

1. Breece Hall 2023 Points = Σ pw = **259.5** ✓
2. Drake London 2024 PPG starter = Σ starter pts / starter weeks = **15.006** ✓
3. De'Von Achane 2023 Weeks as starter = count Starter rows = **7** ✓
4. (= #2) ✓
5. Kyren Williams 2024 Starter floor = min starter pts = **8.6**; ceiling = max =
   **31.6** ✓
6. Josh Jacobs 2021 Times as Captain? = Σ weekly Captain? = **1** ✓
7. Nico Collins 2024 Times as WR of the week? = **1** ✓
8. stevenb123 2024 wk7 Margin = PF − PA = **50.06** ✓
9. plehv79 2023 wk9 Efficiency = PF / Max PF = **0.8149** ✓
10. JacobRosenzweig 2024 Win % = W/games = **0.235** ✓
11. Jaylen Warren 2023 boom/bust gating sane ✓ (N/A — no started weeks)
12. Tank Dell 2023 wk11 % of points (if starter) = player pts / team PF = **0.3078** ✓
13. Sam Howell 2023 wk2 Change from previous week = wk2 − wk1 pts = **5.08** ✓
14. Rhamondre Stevenson PPG starter-vs-bench diff = **Adjusted** PPG starter −
    **Adjusted** PPG bench = **0.2379** ✓ (confirmed the diff intentionally uses the
    bye/injury/suspension-adjusted variants, per `src/lotg.py:11987` Phase-1C
    clarification — my first attempt used the raw variants; verified correct)
15. LWebs53 2023 "All-play win % minus Win %" = AP − Win% = **−0.0084** ✓
16. AceMatthew 2022 Avg points = Points/games = **122.62** ✓
17. shmuel256 2025 Differential = PF − PA = **592.32** ✓
18. Zach Charbonnet 2023: bench rows carry "Diff from worst benchable starter (if
    bench)", starter rows N/A — mutual exclusivity holds ✓
19. BROsenzweig 2023 Avg max PF = Max PF/games = **160.12** ✓
20. Jerome Ford Avg points = Points / rostered weeks (38) = **9.43** ✓ (confirms
    Avg points denominator = all rostered weeks)
21. Chuba Hubbard 2024 Starter boom % = share started ≥20 = 6/14 = **42.9%** ✓
22. Calvin Ridley 2020 Starter bust % = share started ≤5 = 1/14 = **7.1%** ✓

---

## Part 3 — N/A vs 0 sweep: PASS (full population)

Every column that distinguishes "no data → N/A" from "real zero → 0" verified
across all rows:

- **"…from previous week" (team_week / league_week / player_week):** the genuine
  first period is correctly N/A and only the first period. team_week 2020 wk1 →
  100% N/A for all 8 teams across Increase-in-points / Starter-turnover / Roster-
  turnover (800/808 populated otherwise). league_week 2020 wk1 → N/A (RUN3-F5 fix
  held and now correctly anchors to 2020 as earliest). player_week Change-from-
  previous-week → N/A on **all 617** players' first-ever week.
- **Change-in-win%-from-previous-season (team_year):** N/A on all 8 first seasons,
  populated on 100% of non-first seasons.
- **Change-in-points-from-previous-season (player_year):** N/A on all 649 first
  seasons. All 156 non-first N/A rows fully explained (NOT a defect): 141 have a
  NaN current-season Points (roster-only year), 9 have a NaN *prior*-season Points
  (can't diff from a NaN baseline), 6 are true gap-years (prior calendar season
  absent). 0 unexplained.
- **Volatility / floor / ceiling (player_year):** Starter scoring volatility is
  N/A for 0-start AND 1-start seasons (std needs ≥2 — 212 one-start seasons all
  correctly N/A) and 100% populated for ≥2-start. Floor/ceiling N/A for 0-start,
  100% populated for ≥1-start.
- **Win Variance (team_year):** populated for all played seasons 2020-2025 (this
  build's team_year spans 2020-2025; no in-progress 2026 team_year row present).
- **3-year roster retention:** populated for 2020-2022 (3-yr-forward window
  complete), N/A for 2023-2025 (window not yet complete). Correct.
- **(if starter) / (if bench) columns:** perfect mutual exclusivity — "% of points
  (if starter)" 100% populated on starters / 100% N/A on bench; "Diff from worst
  benchable starter (if bench)" the reverse.
- **FAAB:** 2020-2021 (pre-Sleeper) 100% N/A; 2022+ a correct mix of N/A
  (zero-cost FA adds with no bid) and real $0 bids.
- **KTC-dependent columns (30 across picks/trades/transactions):** 100% NaN (N/A,
  not 0) under the no-network sandbox — confirms the Round-2 KTC-N/A fix
  generalizes to every KTC consumer.
- **Real-0 columns render integer 0, never NaN-where-data-exists:** team_year
  Number of donuts (0 NaN), player_year Number of drops (1,081 real zeros, 0 NaN),
  team_week Number of transactions (274 real-zero weeks, 0 NaN).

---

## Conclusion

Parts 1-3 of the 10-part audit are **CLEAN** — zero defects. All cross-sheet
aggregates reconcile at full population, 22 novel stat-family hand-checks match
raw source, and the N/A-vs-0 distinction is correct across every relevant column.
The build is byte-deterministic across two independent rebuilds; tests 15/15. No
source change. (Remaining segments — Parts 4-10 — to be run separately.)
