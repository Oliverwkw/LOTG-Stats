# Phase 13 Round 7 — Parts A+B (full-population completeness + cross-sheet numeric reconciliation)

Self-designed full-population audit repeating the Parts A/B methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 1 of 5 in Round 7. Round 6 found only 3
text-only defects (now fixed), so the repeating-cycle rule advances the audit to
Round 7.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `7cbe458` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`7cbe458`, the Round-6
Parts I/J tip carrying all Round-5 + Round-6 fixes) before any work, then confirmed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache.

All examples below are NOVEL — different players/teams/picks than every prior
round (Rounds 4-6 exclusion list: Josh Doctson, Kenny Pickett, Hunter Henry,
K.J. Osborn, Michael Carter, Rhamondre Stevenson, Pacheco, Jefferson, DJ Moore,
Tyler Johnson, Larry Fitzgerald, Cam Newton, Mike Gesicki, AJ Dillon, Matt Ryan,
Tony Pollard, Mattison, Drake, Meyers, Taysom Hill, Kerryon Johnson, Aaron Jones,
T.J. Hockenson, Robbie Chosen, CEH, KJ Hamler, Jalen Guyton, Mitchell Trubisky,
Hayden Hurst, DeeJay Dallas, Marquez Valdes-Scantling, Odell Beckham,
Parris Campbell, Phillip Lindsay, Blaine Gabbert, Dwayne Haskins, Kyle Juszczyk,
Tanner McKee, X. Worthy, and the various pick examples).

**Result: CLEAN.** Zero defects found. Every Part A completeness check and every
Part B cross-sheet invariant reconciles at full population (0 mismatch), with
exactly the documented exclusions named and justified. No source change required.

---

## Dataset under audit (full population)

6 seasons (2020-2025), 8 teams, 48 team-seasons, 808 team-weeks, 101 league-weeks,
21,376 player-weeks (7,531 starter / 13,845 bench), 1,859 player_year rows, 649
player_all_time rows, 450 picks, 504 trades, 1,514 transactions.

---

## Part A — League-history completeness (full population, no sampling)

### Seasons present in every season-keyed sheet — CLEAN
team_week / team_year / league_week / league_year / player_year / player_week all
carry exactly `{2020,2021,2022,2023,2024,2025}`. 0 missing, 0 extra. picks.csv
keys by draft-class label by design.

### team_all_time — CLEAN
All 8 teams (AceMatthew, BROsenzweig, JacobRosenzweig, LWebs53, Oliverwkw,
plehv79, shmuel256, stevenb123) appear exactly once; 0 duplicates. Every team
present in team_year AND team_week for all 6 seasons; per-season symmetric-diff = 0.

### Week completeness — CLEAN
Every active team has every week 1..N in team_week, N matching league_week
exactly: 2020 → 1..16; 2021-2025 → 1..17 (incl. playoffs). 0 missing, 0 phantom.

### player_week → player_year → player_all_time rollup — CLEAN
- `pw` players ⊆ `py` players == `pat` players (0 in pw-not-py, 0 py-not-pat,
  0 pat-not-py). Exactly one player_all_time row per player (649/649).
- Every (player, year) in player_week has a player_year row (0 orphans).
- The 32 distinct players present in player_year but NEVER in player_week
  (33 rows; all 0 starter weeks; the documented added+dropped-between-snapshots
  pattern) every one has a player_all_time row (0 missing). Stable count vs Round 6.
  NOVEL examples: **A.J. Green 2022** (1 tx / 1 drop), **A.T. Perry 2024**,
  **Adam Trautman 2021**, **Amari Cooper 2025**, **Ameer Abdullah 2021** (7 tx /
  3 drops — a high-churn case).

### Picks grid — CLEAN
450 picks; every slot present exactly once; 0 blank Numbers; all 8 teams present
as Original Team. startup = 152 (19 rounds × 8). Future-pool classes verified by
(round × original-team) grid:
- **2027 = 32** and **2028 = 32**: clean 8 teams × 4 rounds, every round dist
  `{1:8, 2:8, 3:8, 4:8}`, all 8 teams present — NOVEL classes not cited in
  prior rounds.
- 2026 = 33 (round-2 dist = 9, the documented +1 toilet-reward future pick);
  2024 = 33 / 2025 = 40 carry their extra reward picks. Consistent.

### Trades raw-vs-export reconciliation — CLEAN (504, exact-timestamp matched)
Reconciled the raw Sleeper ledger (`exports/snapshot/season_*/weeks/week_*/
transactions.json`, `type==trade & status==complete`) against trades.csv on exact
ET timestamp. Per-season raw-complete vs export-distinct: 2021 16/15, 2022 38/38,
2023 55/54, 2024 67/66, 2025 62/62. Isolated to **exactly 3 raw trades absent from
the export, 0 export trades fabricated** — all 3 the documented exclusions
(re-confirmed by exact tid + ET timestamp + payload):
1. **2021-08-29 11:30:24 tid 737729902018686976** — the manual botched-trade
   phantom player-swap merge.
2. **2023-11-08 12:31:38 tid 1028033090754654208** — net-zero $5↔$5 FAAB swap
   (roster 2↔4, no players/picks).
3. **2024-12-08 19:13:35 tid 1171639841122508800** — net-zero $1↔$1 FAAB swap.

247 distinct Sleeper trades (12 ESPN-2020 + 235 from 2021-2025) × ~2 mirror sides
= 504 trades.csv rows. Σ team_year Total trades = 504; Σ league_year Total trades
= 247 (12/15/38/54/66/62). Consistent end to end.

### Transactions raw-vs-export reconciliation — CLEAN
transactions.csv: 1,514 rows = 1,052 free_agent + 448 waiver + 14 commissioner.
All 6 seasons present (2020:207 / 2021:237 / 2022:261 / 2023:310 / 2024:250 /
2025:249); no season silently missing.

---

## Part B — Cross-sheet numeric reconciliation at full scale (every row)

All computed across EVERY row, N/A-aware:

- **B1 — league_week == Σ team_week** per (Year,Week), 7 columns (PF, transactions,
  Injuries, suspensions, players on bye, FAAB spent, donuts): **0 mismatches.**
  (FAAB is correctly N/A on BOTH sides for all of 2020 and 2021 — pre-2022 Sleeper
  era; an apparent "0.0 vs N/A" arises only from pandas summing an all-NaN column
  and is not a real discrepancy.)
- **B2 — team_year Record wins == Σ team_week Win?** across all 48 team-seasons:
  **0 mismatches**; W+L+T == game count 48/48.
- **B3 — team_all_time award rollups == Σ team_year**: all 12 `Times …` columns
  **0 mismatches**, PLUS deeper additive columns never previously spot-cited —
  **Losses from hardship, Weeks of starter injuries, Weeks of starter suspensions,
  Number of first round picks made, Total number of picks made, Number of rookies
  started/rostered, Number of (starter) donuts** all **0 mismatches**.
  All-time record == Σ team_week wins/games: 0 mismatches. The 5-way record
  decomposition (Regular season + Playoff + Toilet bowl + Third place + Toilet
  losers == All time record) reconciles exactly for all 8 teams.
- **B4 — player_all_time == Σ player_year**, 13 additive counters: **0 mismatches.**
  (The 32 transaction-only players show pat-Points == NaN with all py-Points == NaN
  in all 32 cases — consistent, the apparent "0.0 vs NaN" is again pandas summing
  all-NaN.) Independently, **pat "Weeks as starter" == count of player_week starter
  rows (7,531 total): 0 mismatches** at both the player_year and player_all_time
  level — a deep pw→py→pat chain verified to the raw weekly grid.
- **B5 — league_year == Σ team_year** (transactions, FAAB), N/A-aware:
  **0 mismatches.** Also **league_all_time == Σ league_year** for PF (112,807.18),
  weeks-missed-injury (3,837), weeks-missed-suspension (41), transactions (1,929),
  offseason/inseason/total trades (128/119/247): **0 mismatches.**
  league_year PF == Σ league_week PF == Σ team_week PF for all 6 years.
- **B6 — Number-of-transactions metric** (the count-of-actions metric, distinct
  from the transactions.csv add-row export): ly == Σ lw == Σ tw for all 6 years,
  total 1,929. Internally consistent; the 1,929 vs 1,514 gap is the intended design
  difference (action count vs add-row export), not a defect.

---

## Verification

- `pytest tests/ -q`: **15 passed** in ~61s, 0 failed / 0 skipped.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- No source changes were needed (no defects). Build artifacts reverted.

## Conclusion

**Parts A + B are fully CLEAN at full population — ZERO defects.** Beyond the
standard invariants (all 0-mismatch), this round deliberately exercised
less-obvious corners with novel coverage and found them all clean: the deep
player_week→player_all_time "Weeks as starter" chain against the raw 7,531 starter
rows; the team_all_time 5-way record decomposition; rarely-touched additive columns
(Losses from hardship, Weeks of starter injuries/suspensions, Number of first round
picks made, Total number of picks made, league_all_time rollups); the
2027/2028 future-pool pick grids; and the N/A-vs-0 boundary for FAAB (2020-2021)
and Points (transaction-only players). The 3 raw trades excluded from the export
are exactly the documented exclusions. No source change required for Parts A/B
this round.
