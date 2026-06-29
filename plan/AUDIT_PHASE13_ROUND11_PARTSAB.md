# Phase 13 Round 11 — Parts A+B (full-population completeness + cross-sheet reconciliation)

Self-designed full-population audit repeating the Parts A/B methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 1 of 5 in Round 11. Round 10 found defects
(not fully clean across all 5 part-pairs), so the repeating-cycle rule advances
the audit to Round 11 (a fresh full repeat).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `b31c4ee` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`b31c4ee`, the Round-10
Parts I/J tip carrying all Round-5..Round-10 fixes) before any work, then
confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache.

All examples below are NOVEL — different players/teams/picks/seasons than every
prior round. Deliberately avoided the Rounds 4-10 exclusion cast (Tee Higgins,
Jaylen Waddle, Andrei Iosivas, Boston Scott, Chris Carson, Amon-Ra St. Brown,
CeeDee Lamb, Jelani Woods, Kene Nwangwu, Mason Rudolph, Joe Milton, Jameson
Williams 2022 1.05, Bijan Robinson 2023 1.01, Christian McCaffrey startup 1.01,
Kyle Pitts 1.02, AceMatthew 2023 FAAB, JacobRosenzweig 2025 FAAB, stevenb123 2024
FAAB, plehv79 2023, and the rest of the prior pick/player lists). This round's
novel cast: **Garrett Wilson, Sam LaPorta, Amari Rodgers 2022, Anthony Firkser
2021, Brandin Cooks 2025, shmuel256 2022 FAAB, LWebs53 2025 FAAB, plehv79 2023
FAAB, and 2023 pick 1.03 Jahmyr Gibbs** (with corroborating 2024 1.01 Marvin
Harrison spot-check).

**Result: CLEAN.** Zero defects found. Every Part A completeness check and every
Part B cross-sheet invariant reconciles at full population (0 mismatch), with
exactly the documented exclusions named and justified. No source change required.

---

## Dataset under audit (full population)

6 seasons (2020-2025), 8 teams, 48 team-seasons, 808 team-weeks, 101 league-weeks,
21,376 player-weeks, 1,859 player_year rows, 649 player_all_time rows, 450 picks,
504 trades, 1,514 transactions. (Shapes: tw 808×101, ty 48×127, tat 8×137,
lw 101×59, ly 6×62, pw 21376×65, py 1859×62, pat 649×56, picks 450×41,
trades 504×41, tx 1514×56.) Identical to Rounds 6/7/8/9/10 — confirms a stable
build.

---

## Part A — League-history completeness (full population, no sampling)

### Seasons present in every season-keyed sheet — CLEAN
team_week / team_year / league_week / league_year / player_week / player_year all
carry exactly `{2020,2021,2022,2023,2024,2025}`. 0 missing, 0 extra. tx Season
column also exactly those 6. picks.csv keys by draft-class label (`startup`,
`2021`, `2021 (vet)`, `2022`…`2028`) by design — future classes 2026-2028 are
correct, not a season gap.

### team_all_time — CLEAN
All 8 teams (AceMatthew, BROsenzweig, JacobRosenzweig, LWebs53, Oliverwkw,
plehv79, shmuel256, stevenb123) appear exactly once; 0 duplicates. Per-season
team-set symmetric-diff between team_week and team_year = ∅ for every one of the
6 years.

### Week completeness — CLEAN
Every active team has every week 1..N in team_week, N matching league_week
exactly: 2020 → 1..16; 2021-2025 → 1..17 (incl. playoffs). 0 missing weeks,
0 phantom weeks; per-(team,season) week-set == league_week week-set every season
(0 deviating teams in all 6 years). league_week row count = 101 = 16 + 17×5
exactly.

### Duplicate-row sweep — CLEAN
0 duplicate rows on natural keys: team_week (Team,Year,Week) = 0; player_year
(Player,Year) = 0; player_week (Player,Year,Week) = 0; league_week (Year,Week) =
0.

### player_week → player_year → player_all_time rollup — CLEAN
- `pw` players (617) ⊆ `py` players (649) == `pat` players (649): 0 in
  pw-not-py, 0 py-not-pat, 0 pat-not-py.
- Exactly one player_all_time row per player (0 duplicate names).
- Every (player, year) in player_week has a player_year row (0 orphans).
- **188 player_year rows / 177 distinct players have NO matching player_week
  (player,year)** — the documented added+dropped-between-weekly-snapshots
  pattern. Verified at full population: every one has Number of transactions > 0
  (0 with zero tx), Points is NaN for 100% (0 non-NaN), Weeks as starter = 0 for
  100% (0 nonzero), and every one carries a player_all_time row (0 missing).
  NOVEL examples (each confirmed: pat row present, 0 pw rows, NaN Points,
  matching tx count): **Amari Rodgers 2022** (1 tx), **Anthony Firkser 2021**
  (1 tx), **Brandin Cooks 2025** (1 tx).

### Picks grid — CLEAN
450 picks; every slot present; 0 blank Numbers; all 8 teams present as Original
Team. Per-class counts: startup = 152, 2021 = 32, 2021 (vet) = 32, 2022 = 32,
2023 = 32, 2024 = 33, 2025 = 40, 2026 = 33, 2027 = 32, 2028 = 32 — identical to
Rounds 7/8/9/10 (the 2024/2025/2026 extras are the documented reward /
toilet-future picks; the future-pool classes' repeated placeholders are keyed by
original team, not real duplicate slots).

### Trades raw-vs-export reconciliation — CLEAN (504, exact-timestamp matched)
Reconciled the raw Sleeper ledger (`exports/snapshot/season_*/weeks/week_*/
transactions.json`, `type==trade & status==complete`) against trades.csv on exact
ET timestamp (raw `created` UTC ms → America/New_York). 238 distinct raw complete
trades 2021-2025 (16/38/55/67/62 per year). Per-season export rows: 2020:24 /
2021:31 / 2022:77 / 2023:111 / 2024:135 / 2025:126 = 504.

Isolated to **exactly 3 raw trades absent from the export, 0 export trades
fabricated** — all 3 the documented exclusions (re-confirmed this round by exact
tid + ET timestamp + payload):
1. **2021-08-29 11:30:24 tid 737729902018686976** — phantom player-swap merge
   (`adds={7607:6,7611:8} drops={7607:8,7611:6}` plus a 2022 R4 pick).
2. **2023-11-08 12:31:38 tid 1028033090754654208** — net-zero $5↔$5 FAAB swap
   (roster 2↔4, `adds=None drops=None picks=[]`).
3. **2024-12-08 19:13:35 tid 1171639841122508800** — net-zero $1↔$1 FAAB swap
   (roster 2↔4, same shape).

235 from 2021-2025 (238 − 3) + 12 ESPN-2020 = 247 distinct Sleeper trades × ~2
mirror sides = 504 trades.csv rows.

### Transactions raw-vs-export reconciliation — CLEAN
transactions.csv: 1,514 rows = 1,052 free_agent + 448 waiver + 14 commissioner.
All 6 seasons present (2020:207 / 2021:237 / 2022:261 / 2023:310 / 2024:250 /
2025:249); no season silently missing. Identical to Rounds 6/7/8/9/10.

---

## Part B — Cross-sheet reconciliation at full scale (every row + novel traces)

All numeric invariants computed across EVERY row, N/A-aware (abs tolerance 1e-6
to 1e-3 by column type).

### Full-population numeric invariants — all 0 mismatch
- **B1 — league_week == Σ team_week** per (Year,Week), 7 columns (PF, Number of
  transactions, Number of Injuries, Number of suspensions, Number of players on
  bye, Amount of FAAB spent, Number of donuts): **0 mismatches.** (FAAB N/A on
  both sides for 2020-2021 pre-Sleeper era — NaN-aware.)
- **B2 — team_year Record wins == Σ team_week Win?** across all 48 team-seasons:
  **0 mismatches.**
- **B3 — team_all_time `Times …` rollups == Σ team_year**, all 12 such columns:
  **0 mismatches.**
- **B4 — player_all_time == Σ player_year**, 8 additive counters (Points, Number
  of transactions, Number of drops, Number of trades, Times as Player of the
  week?, Weeks as starter, Weeks missed due to injury, Weeks missed due to
  suspension): **0 mismatches** across all 649 players.
- **B5 — league_year == Σ team_year** (Number of transactions, Amount of FAAB
  spent): **0 mismatches** (FAAB N/A on both sides 2020-2021, NaN-aware).

### Cross-sheet traces with NOVEL examples — all consistent
- **player_year Points == Σ player_week Points, novel Garrett Wilson** (2022-2025):
  196.8 / 207.8 / 242.8 / 98.5 — each equals the sum of that year's player_week
  Points exactly (diff = 0.0 all years). And **Sam LaPorta** (2023-2025):
  225.4 / 161.3 / 106.9 — exact each year.
- **player_all_time additive end-to-end, novel Garrett Wilson**: Points 745.9 ==
  Σ py 745.9; Weeks as starter 44 == Σ py 44; trades/transactions/drops/POTW all
  0 == 0. **Sam LaPorta**: Points 493.6 == Σ py 493.6; trades 1 == Σ py 1; Weeks
  as starter 21 == Σ py 21. All match.
- **Transaction-only players have a player_all_time row** (roster moves reflected
  even with no scored player_week): NOVEL **Amari Rodgers 2022, Anthony Firkser
  2021, Brandin Cooks 2025** — all three present in pat with py-tx == pat-tx
  (1 each), 0 player_week rows, NaN Points.
- **FAAB spent sums correctly tx → team_week → team_year**, three-way equality.
  NOVEL examples **shmuel256 2022**: Σ transactions Faab $30.0 == team_week Σ
  FAAB $30.0 == team_year "Amount of FAAB spent" $30.0; **LWebs53 2025**:
  $91.0 == $91.0 == $91.0; **plehv79 2023**: $125.0 == $125.0 == $125.0.
- **Draft pick traces to the team that ultimately used it.** NOVEL example
  **2023 pick 1.03 (Jahmyr Gibbs)**: Original Team AceMatthew → used by
  stevenb123, `Number of trades = 1`, `Commissioner moved? = False`. trades.csv
  corroborates exactly: on 2023-06-11 21:21:38 AceMatthew *sent*
  "2023 1.03(J. Gibbs)" (receiving Diontae Johnson + 2023 1.06 + 2023 2.02) and
  stevenb123 *received* it (both mirror rows present) — the pick changed hands
  exactly once, to the team shown as having used it. (Corroborating spot-check:
  2024 1.01 Marvin Harrison, Original/Used = stevenb123, Number of trades = 2,
  both legs found in trades.csv.)

---

## Verification

- `pytest tests/ -q` (via `PYTHONPATH=src:lib python3 -m pytest`): **15 passed**
  in ~57s, 0 failed / 0 skipped — including the full-build
  `test_player_history_continuity` and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- No source changes were needed (no defects). `git status` clean except this
  findings file.

## Conclusion

**Parts A + B are fully CLEAN at full population — ZERO defects.** All
completeness checks (seasons, teams, weeks, player rollups, picks grid, trade
count 504, transaction count 1,514, zero duplicate rows) and all cross-sheet
numeric invariants (B1-B5) reconcile to 0 mismatch. The Part B cross-sheet traces
— transaction → player_all_time consistency, FAAB summing tx→team_week→team_year,
draft-pick provenance to the using team, and player_year==Σplayer_week==
player_all_time — all verify exactly with NOVEL examples (Garrett Wilson, Sam
LaPorta, Amari Rodgers, Anthony Firkser, Brandin Cooks, shmuel256 2022 FAAB,
LWebs53 2025 FAAB, plehv79 2023 FAAB, 2023 1.03 Jahmyr Gibbs). The 3 raw trades
excluded from the export are exactly the documented exclusions (1 phantom-merge +
2 net-zero FAAB swaps), re-confirmed by exact tid/timestamp/payload. No source
change was required for Parts A/B this round.
