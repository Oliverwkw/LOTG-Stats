# Phase 13 Round 8 — Parts A+B (full-population completeness + cross-sheet reconciliation)

Self-designed full-population audit repeating the Parts A/B methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 1 of 5 in Round 8. Round 7 found and fixed
4 text-only defects (Parts C/D stale tooltip text re: 2020 ESPN startup vs 2021
Sleeper vet draft terminology), so — not being FULLY clean across all 5 part-pairs
— the repeating-cycle rule advances the audit to Round 8.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `36e24d0` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`36e24d0`, the Round-7
Parts I/J tip carrying all Round-5 + Round-6 + Round-7 fixes) before any work,
then confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache.

All examples below are NOVEL — different players/teams/picks than every prior
round (Rounds 4-7 exclusion list: Josh Doctson, Kenny Pickett, Hunter Henry,
K.J. Osborn, Michael Carter, Rhamondre Stevenson, Pacheco, Jefferson, DJ Moore,
Tyler Johnson, Larry Fitzgerald, Cam Newton, Mike Gesicki, AJ Dillon, Matt Ryan,
Tony Pollard, Mattison, Drake, Meyers, Taysom Hill, Kerryon Johnson, Aaron Jones,
T.J. Hockenson, Robbie Chosen, CEH, KJ Hamler, Jalen Guyton, Mitchell Trubisky,
Hayden Hurst, DeeJay Dallas, Marquez Valdes-Scantling, Odell Beckham,
Parris Campbell, Phillip Lindsay, Blaine Gabbert, Dwayne Haskins, Kyle Juszczyk,
Tanner McKee, X. Worthy, A.J. Green, A.T. Perry, Adam Trautman, Amari Cooper,
Ameer Abdullah, and the prior pick examples).

**Result: CLEAN.** Zero defects found. Every Part A completeness check and every
Part B cross-sheet invariant reconciles at full population (0 mismatch), with
exactly the documented exclusions named and justified. No source change required.

---

## Dataset under audit (full population)

6 seasons (2020-2025), 8 teams, 48 team-seasons, 808 team-weeks, 101 league-weeks,
21,376 player-weeks, 1,859 player_year rows, 649 player_all_time rows, 450 picks,
504 trades, 1,514 transactions. (Shapes: tw 808×101, ty 48×127, tat 8×137,
lw 101×59, ly 6×62, lat 1×55, pw 21376×65, py 1859×62, pat 649×56, picks 450×41,
trades 504×41, tx 1514×56.) Identical to Round 6/7 — confirms a stable build.

---

## Part A — League-history completeness (full population, no sampling)

### Seasons present in every season-keyed sheet — CLEAN
team_week / team_year / league_week / league_year / player_week / player_year all
carry exactly `{2020,2021,2022,2023,2024,2025}`. 0 missing, 0 extra. picks.csv
keys by draft-class label (`startup`, `2021`, `2021 (vet)`, `2022`…`2028`) by
design — future classes 2026-2028 are correct, not a season gap.

### team_all_time — CLEAN
All 8 teams (AceMatthew, BROsenzweig, JacobRosenzweig, LWebs53, Oliverwkw,
plehv79, shmuel256, stevenb123) appear exactly once; 0 duplicates. Every team
present in team_year AND team_week for all 6 seasons; per-season team-set
symmetric-diff between team_week and team_year = ∅ for every year.

### Week completeness — CLEAN
Every active team has every week 1..N in team_week, N matching league_week
exactly: 2020 → 1..16; 2021-2025 → 1..17 (incl. playoffs). 0 missing weeks,
0 phantom weeks; per-(team,season) week-set == league_week week-set every season
(mismatched-team list empty for all 6 years).

### player_week → player_year → player_all_time rollup — CLEAN
- `pw` players (617) ⊆ `py` players (649) == `pat` players (649): 0 in
  pw-not-py, 0 py-not-pat, 0 pat-not-py.
- Exactly one player_all_time row per player (0 duplicate names).
- Every (player, year) in player_week has a player_year row (0 orphans).
- The 32 distinct players present in player_year but NEVER in player_week
  (the documented added+dropped-between-snapshots pattern — a transaction-tracking
  player_year row with no scored player_week row) every one has a player_all_time
  row. Stable count vs Rounds 5/6/7. NOVEL examples verified to carry a pat row:
  **Bo Melton 2024** (2 tx), **Brock Wright 2022** (2 tx), **Derek Watt 2023**
  (2 tx) — plus surfaced candidates Anthony Firkser 2021, Brandon Powell 2023,
  Collin Johnson 2021, Demetric Felton 2021/2022.

### Picks grid — CLEAN
450 picks; every slot present; 0 blank Numbers; all 8 teams present as Original
Team. startup = 152 (19 rounds × 8), 0 duplicate Numbers. Per-class counts:
2021 = 32, 2021 (vet) = 32, 2022 = 32, 2023 = 32, 2024 = 33, 2025 = 40 — all with
0 duplicate Numbers. Future-pool classes 2026 = 33 / 2027 = 32 / 2028 = 32 each
show 28 "duplicate" Numbers — these are the documented not-yet-ordered future-pool
placeholders (one per team per round keyed by original team; the `1.??`/`2.??`
labels collide on Number by design), NOT real duplicate slots. Consistent with
Rounds 6/7.

### Trades raw-vs-export reconciliation — CLEAN (504, exact-timestamp matched)
Reconciled the raw Sleeper ledger (`exports/snapshot/season_*/weeks/week_*/
transactions.json`, `type==trade & status==complete`) against trades.csv on exact
ET timestamp (raw `created` UTC ms → America/New_York, the export Date format).
Per-season raw-complete vs export-distinct-dates vs export-rows:

| Year | raw complete | export distinct | export rows |
|------|-------------:|----------------:|------------:|
| 2021 | 16 | 15 | 31 |
| 2022 | 38 | 38 | 77 |
| 2023 | 55 | 54 | 111 |
| 2024 | 67 | 66 | 135 |
| 2025 | 62 | 62 | 126 |

Isolated to **exactly 3 raw trades absent from the export, 0 export trades
fabricated** — all 3 the documented exclusions (re-confirmed by exact tid + ET
timestamp + payload this round):
1. **2021-08-29 11:30:24 tid 737729902018686976** — the manual botched-trade
   phantom player-swap merge (`adds={7607:6,7611:8} drops={7607:8,7611:6}` plus a
   2022 R4 pick; Sleeper split one real pick trade into a phantom player-swap which
   is merged into the pick trade that IS in the export).
2. **2023-11-08 12:31:38 tid 1028033090754654208** — net-zero $5↔$5 FAAB swap
   (roster 2↔4, `adds=None drops=None picks=[]`).
3. **2024-12-08 19:13:35 tid 1171639841122508800** — net-zero $1↔$1 FAAB swap
   (roster 2↔4, same shape).

247 distinct Sleeper trades (12 ESPN-2020 + 235 from 2021-2025: 15+38+54+66+62)
× ~2 mirror sides = 504 trades.csv rows. The Round-5 commissioner-wash fix holds
(no real trade wrongly washed) and no trade is double-counted.

### Transactions raw-vs-export reconciliation — CLEAN
transactions.csv: 1,514 rows = 1,052 free_agent + 448 waiver + 14 commissioner.
All 6 seasons present (2020:207 / 2021:237 / 2022:261 / 2023:310 / 2024:250 /
2025:249); no season silently missing. Identical to Rounds 6/7.

---

## Part B — Cross-sheet reconciliation at full scale (every row + novel traces)

All numeric invariants computed across EVERY row, N/A-aware.

### Full-population numeric invariants — all 0 mismatch
- **B1 — league_week == Σ team_week** per (Year,Week), 7 columns (PF, Number of
  transactions, Injuries, Suspensions, Players on bye, Amount of FAAB spent,
  Donuts): **0 mismatches.** (FAAB N/A on both sides for 2020-2021 pre-Sleeper era,
  handled NA-aware — no false positive.)
- **B2 — team_year Record wins == Σ team_week Win?** across all 48 team-seasons:
  **0 mismatches.**
- **B3 — team_all_time award rollups == Σ team_year**, all 12 `Times …` columns:
  **0 mismatches.**
- **B4 — player_all_time == Σ player_year**, additive counters (Points, Number of
  transactions, Number of drops, Number of trades, Times as Player of the week?,
  Weeks as starter): **0 mismatches.**
- **B5 — league_year == Σ team_year** (Number of transactions, Amount of FAAB
  spent): **0 mismatches.**

### Cross-sheet traces with NOVEL examples — all consistent
- **player_year == Σ player_week, novel player A.J. Brown** (all 6 seasons):
  py Points 214.4 / 164.1 / 286.1 / 289.7 / 216.9 / 220.3 each equals the
  sum of that year's player_week Points exactly (diff = 0.0 all years).
- **FAAB in transactions.csv sums into team_year "Amount of FAAB spent"** for every
  (team, season) 2022-2025: **0 mismatches**. NOVEL example **plehv79 2023**:
  Σ transactions Faab = $125.0 == team_year "Amount of FAAB spent" $125.0.
- **team_week FAAB == team_year FAAB** for every (team, season) 2022-2025:
  **0 mismatches** — the third leg confirming tx → team_week → team_year all agree.
- **Transaction-only players have a player_all_time row** (roster moves reflected
  even with no scored week): NOVEL Bo Melton 2024 / Brock Wright 2022 /
  Derek Watt 2023 all present in pat with the correct tx counts.
- **Draft pick traces to the team that ultimately used it.** NOVEL example
  **2021 pick 1.02 (Kyle Pitts)**: Original Team JacobRosenzweig → used by
  stevenb123, `Number of trades = 1`. trades.csv corroborates: JacobRosenzweig
  *sent* "2021 1.02(K. Pitts)" and *received* "D'Andre Swift; 2021 4.01(R. Moore)"
  — the pick changed hands exactly once, to the team shown as having used it.
  (Cross-checked startup 1.01 Christian McCaffrey: Original = used = Oliverwkw,
  0 trades, not commissioner-moved — an un-traded pick traces to its origin team.)
- **pat additive end-to-end, novel Alvin Kamara**: Points 1390.0 == Σ py 1390.0;
  Number of trades 3 == Σ py 3; Weeks as starter 70 == Σ py 70; Number of
  transactions 0 == Σ py 0. All match.

---

## Verification

- `pytest tests/ -q`: **15 passed** in ~75s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- No source changes were needed (no defects). Build artifacts reverted; `git
  status` clean except this findings file.

## Conclusion

**Parts A + B are fully CLEAN at full population — ZERO defects.** All
completeness checks (seasons, teams, weeks, player rollups, picks grid, trade
count 504, transaction count 1,514) and all cross-sheet numeric invariants
(B1-B5) reconcile to 0 mismatch. The cross-sheet traces requested for Part B —
transaction → trade/player_week consistency, FAAB summing tx→team_week→team_year,
draft-pick provenance to the using team, and player_year==Σplayer_week — all
verify exactly with NOVEL examples (A.J. Brown, plehv79 2023, Kyle Pitts 1.02,
Alvin Kamara, Bo Melton, Brock Wright, Derek Watt). The 3 raw trades excluded
from the export are exactly the documented exclusions (1 phantom-merge + 2
net-zero FAAB swaps), re-confirmed by exact tid/timestamp/payload. No source
change was required for Parts A/B this round.
