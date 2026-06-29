# Phase 13 Round 5 — Parts A+B (full-population completeness + cross-sheet numeric reconciliation)

Self-designed full-population audit repeating the Parts A/B methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy` (worktree self-verified at/ahead of `e6444ab`,
after a fast-forward reset to fix the recurring stale-worktree environment
bug). Build under audit: offline build (`scripts/offline_build.py`, exit 0,
only the expected `api.sleeper.app` / `espn_2020_draft` network-unavailable
warnings). All examples below are NOVEL — different players/teams/seasons than
any prior round (deliberately avoiding BROsenzweig 2025 picks, Pacheco,
Jefferson, DJ Moore, Tyler Johnson, Larry Fitzgerald, Cam Newton,
Josh Doctson-as-drop-chain, Mike Gesicki, JacobRosenzweig 2.02/2.09,
AceMatthew, X. Worthy, etc.).

**Result: 1 real defect found and fixed** (commit on `src/lotg.py`).
Everything else CLEAN at full population.

---

## Part A — League-history completeness (full population, no sampling)

Dataset under audit: 6 seasons (2020-2025), 8 teams, 48 team-seasons,
808 team-weeks, 21,376 player-weeks, 1,857 player_year rows, 649
player_all_time rows, 450 picks, 504 trades (post-fix), 1,504 transactions.

### Seasons present in every season-keyed sheet — CLEAN
team_year / team_week / league_year / league_week / player_year all carry
exactly {2020,2021,2022,2023,2024,2025}; 0 missing, 0 extra. picks.csv keys by
draft-class label (`startup`, `2021`, `2021 (vet)`, `2022`…`2028`) as designed
— future-pick classes 2026-2028 are correct, not a season gap.

### team_all_time — CLEAN
All 8 teams (AceMatthew, BROsenzweig, JacobRosenzweig, LWebs53, Oliverwkw,
plehv79, shmuel256, stevenb123) appear exactly once; 0 duplicates. Every team
present in team_year AND team_week for all 6 seasons; team_year vs team_week
team-set diff = 0 every season.

### Week completeness — CLEAN
Every active team has every week 1..N in team_week, N matching league_week
exactly: 2020 → 1..16; 2021-2025 → 1..17 (incl. playoffs). 0 missing weeks,
0 phantom weeks, team_week week-set == league_week week-set every season.

### player_week → player_year → player_all_time rollup — CLEAN
- pw players (617) ⊆ py players (649) ⊆ pat players (649): 0 in pw-not-py,
  0 in py-not-pat, 0 in pat-not-py.
- Exactly one player_all_time row per player (0 dup names — the Round-4
  phantom-name-pad fix holds).
- Every (player, year) in player_week has a player_year row (0 orphans).
- The 32 players present in player_year but NOT player_week were investigated
  and are CORRECT: each was added+dropped between weekly snapshots (Number of
  transactions/drops > 0, Points = NaN, Weeks as starter = 0) so they earn a
  transaction-tracking player_year row but never a scored player_week row.
  Novel examples: Blaine Gabbert 2022 (4 tx / 2 drops), Dwayne Haskins 2022
  (6 tx / 3 drops), Kyle Juszczyk 2024, Tanner McKee 2025.

### Picks grid — CLEAN
450 picks; season-class labels enumerate correctly including future picks.
No structural gaps surfaced (Parts G/H pick-chain was Round-4 scope).

### Trades raw-vs-export reconciliation — **1 DEFECT FOUND + FIXED**

Reconciled the raw Sleeper ledger (`exports/snapshot/season_*/weeks/week_*/
transactions.json`, complete-status only) against distinct trade events in
trades.csv, DST-aware (export Date is America/New_York local; raw `created` is
UTC ms). Pre-fix the per-season counts did NOT reconcile:

| Year | raw complete trades | net-zero swaps | expected | export distinct | pre-fix |
|------|--------------------:|---------------:|---------:|----------------:|---------|
| 2021 | 16 | 0 | 16 (−1 phantom merge) | 15 | OK (by design) |
| 2022 | 38 | 0 | 38 | 37 | **−1** |
| 2023 | 55 | 1 | 54 | 54 | OK |
| 2024 | 67 | 1 | 66 | 63 | **−3** |
| 2025 | 62 | 0 | 62 | 62 | OK |

**5 raw trades were missing from trades.csv.** Root-cause analysis of each:

- **1 was a correct, documented exclusion** — 2021 tid 737729902018686976
  (Michael Carter ↔ Rhamondre Stevenson, LWebs53/shmuel256): the "Manual 2021
  botched-trade merge" (`src/lotg.py` ~line 3984). Sleeper split one real
  pick trade into a pick-swap + a phantom player-swap; the phantom is merged
  into the pick trade (which IS in the export, carrying the 2022 4.07).
  Correctly excluded, not a defect.

- **4 were a real defect** — caught by the commissioner-wash sweep:
  - 2022 tid 903835630847717376 — Josh Doctson, LWebs53 → BROsenzweig + $1 FAAB
  - 2024 tid 1126272571940544512 — Kenny Pickett, BROsenzweig → LWebs53
  - 2024 tid 1142929980331048960 — Hunter Henry, Oliverwkw → AceMatthew
  - 2024 tid 1142924638763274240 — K.J. Osborn ↔ Kenny Pickett,
    JacobRosenzweig/BROsenzweig

  **Root cause:** the Phase-6B commissioner-wash detector classifies a
  `(player, UTC-day)` as a "wash" when that player's net roster movement on
  the day is zero AND any commissioner action touched it. In each of these 4
  cases a *real, manager-initiated trade* moved a player, and a *separate*
  commissioner action later the **same UTC day** reversed it (a vetoed/undone
  trade). The trade's only player(s) all became wash-pdays, so the entire
  trade landed in `wash_tx_ids` and was silently deleted from trades.csv AND
  from the trade counts. (Confirmed via build instrumentation: all 4 hit the
  wash `continue` gate before ever reaching `trades_rows.append`.)

  **Fix** (`src/lotg.py`, in the wash-building loop ~line 4146): a
  `trade`-type transaction is never classified as a commissioner wash. A trade
  is a genuine event that occurred even if the commissioner later reversed it;
  only the reversing commissioner (and ancillary add/drop) legs remain no-ops
  to drop. Tracked `_tx_is_trade[txid]` and `continue` past trades before the
  wash test. Verified precisely scoped: across all seasons exactly 4 txns
  newly survive (1×2022 + 3×2024), every one a trade; the reversing
  commissioner legs still wash correctly so rosters end in the right state and
  tx/trade counts stay row-for-row consistent.

  **Post-fix reconciliation:** 2022/2023/2024/2025 all reconcile EXACTLY;
  2021's only remaining gap is the documented Carter/Stevenson phantom merge.
  trades.csv 496 → 504 rows (+4 trades × 2 sides); distinct trade events
  243 → 247. Σ team_year "Total trades" 496 → 504. Affected players now carry
  the correct trade counts (e.g. Kenny Pickett all-time trades = 2).

### Transactions raw-vs-export reconciliation — CLEAN
transactions.csv: 1,504 rows (free_agent 1,042 / waiver 448 / commissioner
14). Raw complete non-trade Sleeper events (2021-2025) = 1,246; the export
adds 2020 (ESPN ledger) and applies the documented wash/synthetic-pick
removals. Per-year row counts present for all 6 seasons; no season silently
missing.

---

## Part B — Cross-sheet numeric reconciliation at full scale (every row)

All computed across EVERY row, not sampled. Post-fix:

- **player_all_time == Σ player_year**, 13 additive counters (Points,
  Number of transactions / drops / trades, Times as Player/Captain/QB/RB/WR/TE
  of the week, Weeks missed injury / suspension, Weeks as starter):
  **0 mismatches**.
- **league_week == Σ team_week** per (Year,Week), 7 columns (PF, Number of
  transactions, Injuries, suspensions, players on bye, FAAB spent, donuts):
  **0 mismatches**.
- **team_year Record wins == Σ team_week Win?** across all 48 team-seasons:
  **0 mismatches**.
- **team_all_time award rollups == Σ team_year**, all 12 `Times …` columns:
  **0 mismatches**.
- **league_year == Σ team_year** (Number of transactions, Amount of FAAB
  spent): **0 mismatches**.

### Documented non-defect (re-confirmed)
`league_week "Number of trades"` is intentionally NOT a simple sum across
team_week (each trade is counted once per participating team in team_week —
ratio ~2.0-2.1 incl. occasional 3-team deals — but once per distinct trade in
league_week). This is the deliberate dedup flagged out-of-scope in Round 2,
code unchanged; the per-year league_year `Total trades` (247) equals the
distinct-trade count, consistent end to end.

---

## Verification

- `pytest tests/ -q`: **15 passed** (incl. the 73s full-build
  `test_player_history_continuity` — confirms the 4 newly-surfaced trades do
  not break roster-lineage continuity; a transient `BadZipFile` seen earlier
  was a parallel build writing the xlsx mid-test, not a regression).
- Offline build: exit 0, no new warnings.
- Build artifacts reverted; `git status` clean except `src/lotg.py` + this
  file.

## Conclusion

**1 real defect found and fixed:** commissioner-wash over-deletion silently
dropped 4 real trades (2022 Doctson, 2024 Pickett, 2024 Henry, 2024
Osborn↔Pickett) that were reversed by a same-UTC-day commissioner action.
Fixed by exempting `trade`-type transactions from the wash sweep. All Part A
completeness checks and all Part B cross-sheet invariants are now 0-mismatch
at full population, with documented exclusions (2 net-zero swaps, 1 phantom
2021 player-swap merge) named and justified. This continues the Round 2-4
pattern: full-population checks keep surfacing narrow real bugs that
sample-based checks miss — here, a same-day commissioner-reversal interaction
that the wash heuristic conflated with a no-op correction.
