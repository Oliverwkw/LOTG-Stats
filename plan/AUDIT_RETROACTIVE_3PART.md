# Retroactive 3-part audit: Phases 0 → 3A.3

Build artifact: run 26686065243 (most recent successful, post #161).

Methodology: per-phase results-based audit deriving ≥5 verification cases from the original PR spec. Diff sweep + code-based audit folded in for Phase 3A.3 specifically (most recent).

---

## Phase 0 — Sheet + column foundation reorders

**10/10 PASS.** xlsx tab order, player_week 3rd-column, league_week first-3, all dropped columns confirmed absent. No bugs.

## Phase 1A — N/A vs 0 sweep

**6/7 PASS, 1 FAIL.**

| Case | Result |
|---|---|
| FAAB N/A on 811 free_agent rows | ✅ |
| FAAB N/A on 42 commissioner rows | ✅ |
| **FAAB NOT N/A on waiver rows** | ❌ 30 waiver rows with N/A |
| team_year Win % vs self N/A | ✅ |
| team_all_time Record vs self N/A | ✅ |
| % of starts made → 0 (never N/A) | ✅ |
| Player addition value never N/A | ✅ |

### 🐛 Bug 1: 30 waiver rows have `FAAB = N/A`

Examples: AceMatthew → Damien Williams 2021-10-06; LWebs53 → JaMycal Hasty 2021-09-15. All 2021. `Total FAAB bid = 0.0, Number of bids = 1.0`. These are $0 waiver claims where Sleeper's `faab` setting was missing/null, so my `_preserve_na("faab") = True` propagated the None → "N/A". Per spec, waiver FAAB should always be numeric (0 acceptable). Need to fall back to 0 for waiver rows specifically.

## Phase 1B — wk-1 prev-week + unique counts

**11/11 PASS.** Wk1 2022-2025 all show non-zero Increase / Starter turnover from previous week. Unique counts in distinct range (3-6 QBs/team-year, 63 QBs league-all-time). shmuel256 2025 TE started = 5 (per your spec ≥ 2). No bugs.

## Phase 1C — Adjusted player averages + derived consumers

**7/8 PASS, 1 FAIL.**

| Case | Result |
|---|---|
| Adjusted Avg points / PPG starter / PPG bench in player_year + player_all_time (6 cases) | ✅ |
| Rashee Rice 2024 Adjusted Avg (16.23) > Avg (3.82) | ✅ |
| **RR 2024 PPG starter vs bench diff = Adj_starter − Adj_bench** | ❌ shows 0, expected 16.225 |

### 🐛 Bug 2: PPG starter vs bench diff returns 0 when one side is None

Rashee Rice 2024 had no played bench weeks → `Adjusted PPG bench = None` internally → catalog fills to 0.0 in CSV. My diff lambda guards `if r["Adjusted PPG bench"] is not None` and returns `None` if either side is missing → output shows 0. Should treat None as 0 in the diff (player with no bench weeks has effective PPG bench = 0).

## Phase 2 — Hardship + Luck rebuild

**8/9 PASS, 1 FAIL.**

| Case | Result |
|---|---|
| Starter-adjusted Hardship on team_week / team_year / team_all_time / league_week (4 cases) | ✅ |
| **Starter-adj Hardship ≤ Hardship invariant** | ❌ 1 row violates (plehv79 2022 wk3: SA=17.1, H=16.6) |
| Hardship populates real values (97.8% non-zero team-weeks) | ✅ |
| Top hardship realistic (max=145) | ✅ |
| 2021 wk1-2 partial fill (10/16 zeros, deferred NFLverse 2020 backfill) | ✅ |
| Tre' Harris 2025 wk5 injury flag set | ✅ |

### 🐛 Bug 3: 1 team-week with SA Hardship > Hardship (rounding)

plehv79 2022 wk3 shows SA=17.1, H=16.6. Per design SA ≤ H always (SA = expected × starter_pct, starter_pct ≤ 1). Likely accumulation of per-player rounded-to-4-decimal SAs slightly exceeding sum of rounded H values. Tiny magnitude (0.5 / 16.6 = 3%). Cosmetic but should be guaranteed.

## Phase 3A — % of points redefined + Number of trades on player_week

**6/6 PASS.** Number of trades column present (335 non-zero rows). % of points max ~15% (sensible starter share). Team for highest % of points names only real teams. Aaron Jones 2023 trade activity visible.

## Phase 3A.2 — Tenure-from-transactions

**8/8 PASS.** Hunter Renfrow = 5 teams ✅. No zero-team rows. ≥5-team players exist (22 in player_all_time). All player_year + player_all_time rows have non-blank Top Team and Last team.

## Phase 3A.3 — Time-rostered top/last team + FY-keyed

**8/9 PASS, 1 FAIL.**

| Case | Result |
|---|---|
| Aaron Jones 2023 Top Team = shmuel256 | ✅ (was your specific spec) |
| **Aaron Jones 2023 Last team = shmuel256** | ❌ actual: BROsenzweig |
| Bijan Robinson 2023 Last team populated | ✅ shows plehv79 (suspicious — likely same bug) |
| Najee Harris 2021 Top == Last (single team) | ✅ |
| Top Team in player_year / player_all_time only valid team names (2 cases) | ✅ |
| Multi-team 2024 spot checks (3 cases) | ✅ |

### 🐛 Bug 4: Last team for player_year uses full FY window, not in-season

Aaron Jones FY 2023 window in my code is `[Sept 1 2023, Sept 1 2024]`. He was on shmuel256 the entire 2023 NFL season; in the 2024 offseason (still within FY 2023's full window) he was traded to BROsenzweig → that trade ranks as the latest tenure event → BROsenzweig wins Last team for 2023.

Same root cause for **Bijan Robinson 2023 Last team = plehv79**: he was on stevenb123 the 2023 season; traded to plehv79 in 2024 offseason → captured in FY 2023's full window → plehv79 wins.

Fix: `tenure_last_event_fy` should accumulate only events that fall inside the **in-season** window `[Sept 1 FY, Feb 1 FY+1]`, not the full FY window. Top team already uses in-season; Last team should too.

## Phase 3A.3 — DIFF SWEEP

Only `player_year.csv` and `player_all_time.csv` differ vs the prior build. New columns added (`Points (full season)`, `Avg points (full season)`, `Taxi-eligible`) — all from Phase 3B which shipped in the same PR set. **No unexpected sheet diffs.**

---

## Summary of bugs surfaced

| # | Phase | Bug | Severity |
|---|---|---|---|
| 1 | 1A | 30 waiver rows have FAAB=N/A (should be 0) | Low — old 2021 $0-bid edge case |
| 2 | 1C | PPG starter vs bench diff returns 0 when one side has no weeks | Medium — affects pure-starter / pure-bench players |
| 3 | 2 | 1 team-week (plehv79 2022 wk3) has SA Hardship > Hardship by 0.5 (rounding) | Low — cosmetic |
| 4 | 3A.3 | Last team uses full FY window; offseason trade after Feb 1 wins over season-end team | Medium — affects every player traded in offseason of FY |

Triage call: do you want all four fixed as one PR, or pick which to prioritize?
