# Phase 13 — 10-Part Audit Round 1, PART 10: ESPN-2020 integration audit

**Branch:** `claude/phase-13-audit-tsapoy`
**Starting commit:** 751a6c0 (worktree was stale at 6d83635; reset to origin)
**Scope:** Audit the integration of the 2020 season (ESPN API/backfill via
`src/espn_2020.py`) into the otherwise-Sleeper pipeline (2021–2025), with the
six checklist concerns: 16-week season handling, ESPN→unified player/team
identity, 2020 startup-draft distinction, 2020 transactions/trades ledger,
2020 awards/records folding into all-time, and 2020-specific N/A conventions.

**Result: CLEAN. No source change.**

Build: `PYTHONPATH=src:lib python3 scripts/offline_build.py` → exactly 2
unresolved fetches (`/league/0` live-league + `/draft/espn_2020_draft`
delegating stub) — both expected. Tests: 15 passed before and after (no
change). All examples below are NOVEL (not in the prior-rounds exclusion list).

---

## Methodology

Traced 2020 data end-to-end: `espn_2020.load_espn_2020()` →
`emit_sleeper_2020()` → `_Espn2020Client` injection in `lotg.py:1937` → the
unified `exports/*.csv`. Hand-recomputed season-length-dependent denominators
from `team_week.csv` and reconciled the trade/draft/award folds against the raw
ESPN dump (`data/espn_2020_raw/`).

---

## 1. 16-week-2020 vs 17-week-2021–2025 — CLEAN

`emit_sleeper_2020` (espn_2020.py:574) emits the 2020 league with
`playoff_week_start: 15, last_scored_leg: 16, leg: 16`. Every season-length
calculation reads these per-season settings rather than hardcoding 17:

- **Week structure:** `team_week.csv` 2020 = weeks 1–16, 8 teams each = 128
  team-weeks exactly (no week 17/18; `last_completed_week` excludes wk17 for
  seasons ≤2020, lotg.py:2974).
- **Regular-season vs playoff split (NOVEL, hand-computed):** reg-season game
  counts per season = 2020:14, 2021–2025:15 — exactly `playoff_week_start − 1`.
  2020 correctly has a 14-game regular season + 2 playoff weeks (15 Semis, 16
  Finals); Sleeper seasons have 15 + 2.
- **PPG denominator (NOVEL):** Alvin Kamara 2020 = 375.8 pts / 16 = 23.4875 avg
  (matches `Avg points`). Not /14, not /17. Champion shmuel256 = 2501.88 / 16 =
  156.37.
- **All-play denominator (NOVEL, hand-computed):** shmuel256 2020 all-play =
  72-40-0 over **112** comparisons (16 weeks × 7 opponents) = 0.6429, exactly
  matching the export's `All-play win %`. Confirms the all-play denominator
  scales with the 16-week season, not a fixed 17.
- **Semifinal +5 homefield bonus lands on the right week (NOVEL):** raw ESPN
  wk15 PF shmuel256 = 189.76 / plehv79 = 146.28; export = 194.76 / 151.28
  (+5 each — both were the higher seed in their wk15 Semifinal). Because
  `playoff_start` = 15 for 2020 (vs 16 for 2021+), the bonus correctly anchors
  on the Semifinal week in both eras (lotg.py:4271-4294).

## 2. ESPN→unified player/team identity — CLEAN (no ghosts)

- **Teams:** `team_all_time.csv` has exactly 8 teams, all the canonical
  managers (AceMatthew, BROsenzweig, JacobRosenzweig, LWebs53, Oliverwkw,
  plehv79, shmuel256, stevenb123). No duplicate/ghost team. The ESPN
  `teamId`→manager→stable-Sleeper-`roster_id` remap (espn_2020.py:57-68) folds
  2020 into the same 8 roster identities used 2021+.
- **Players:** 0 ghost/numeric-name players in 2020 `player_year` (247 players)
  and 0 empty-`Player` rows in 2020 `player_week` (2632 rows). The
  `_clean_id` float-string normalization ('6007.0'→'6007', espn_2020.py:125)
  and the baked `player_id_map.csv` bridge resolve every 2020 ESPN playerId to
  the Sleeper player identity.

## 3. 2020 startup draft vs 2021 (vet) draft — CLEAN

`picks.csv` by Year: **startup = 152** (19 rounds × 8 teams), **2021 (vet) =
32**, plus 2021–2028 rookie drafts. The two are cleanly distinguished. Startup
R1.01 = Oliverwkw → Christian McCaffrey (matches espn_2020.py self-test). All
152 startup picks have resolved player names (0 empty). No NEW instance of the
exhausted 2020-vs-2021-conflation family.

## 4. 2020 transactions / trades ledger — CLEAN

- **Transactions:** 207 2020 rows in `transactions.csv`; every row has an add
  and/or drop (0 empty); FAAB always 0 (2020 ESPN had no FAAB — correct, not a
  gap). The EXECUTED-only filter + per-transaction (not per-item) grouping
  (espn_2020.py:291-334) match Sleeper's add+drop swap shape.
- **Trades:** the email layer has 13 entries → **24 mirror rows** in
  `trades.csv` (12 player-leg trades × 2 sides). The 13th entry
  (`2020-09-09T21:45:18Z`, `involves_picks=true`, **0 legs** — the documented
  on-platform startup-slot swap with no resolvable legs) emits **no row**
  because the trade-row loop iterates `roster_ids` and its `roster_ids` is empty
  (lotg.py:5312). This is the **documented single exclusion** (verified clean in
  Round 5 PARTSIJ and Round 6 PARTSIJ) — NOT a new defect.
- **Commissioner pick-trade overlay (NOVEL verification):** all 4 distinct 2020
  overlay timestamps in `data/commissioner_pick_trades.csv` (2020-10-29
  17:09:26, 2020-11-29 23:57:04, 2020-12-01 16:47:53, 2020-12-16 16:43:22)
  **exactly match** emitted trade `created` timestamps (et216, et218, et219,
  et222), so every reconstructed pick leg injects into the correct trade. The
  overlay matcher's guard `_frm/_to in roster_ids` (lotg.py:4062) means picks
  only attach to trades that already have those rosters — consistent with the
  empty-leg trade carrying no picks.
- **league_week trade count is consistent with trades.csv:** total 2020
  league_week `Number of trades` = 12 (sum across weeks), counting distinct
  trade dates from `trades_rows` (lotg.py:14771-14777). The empty-leg trade has
  no row, so it is excluded identically from both the trade rows and the count —
  no phantom and no double-count.

## 5. 2020 awards / records folding into all-time — CLEAN

- **Player of the week (NOVEL):** POTW per season = 2020:**16**, 2021–2025:17
  each = **101** total. 2020 correctly contributes exactly 16 (one per its 16
  weeks), reconfirming the 101-week total from Part 7.
- **All-time fold has 0 mismatches:** for every player, all-time
  `Times as Player of the week?` exactly equals the sum of their per-year
  values (0 mismatches across all players) — no double-count, no mis-key when
  2020 is folded in.
- **Records fold (NOVEL, hand-traced):** Tyler Lockett's 2020 Week 7 (53.0 pts,
  JacobRosenzweig — his 4-TD game) is his all-time `Starter scoring ceiling`
  (53.0) and his all-time POTW count (1) folds in exactly that single 2020 POTW
  (his only one in any season). Tyreek Hill W12 (57.9) is the top 2020
  single-week starter score; it and the other 2020 POTWs all carry through.

## 6. 2020-specific N/A / zero-fill conventions — CLEAN

The "N/A starter points" convention is **not 2020-specific** and is correctly
distinguished from a data gap. Every season has N/A-points players
(2020:11, 2021:30, 2022:44, 2023:28, 2024:33, 2025:42), and **every** N/A row
(all seasons) has `Weeks as starter = 0` with `Points (full season) = 0.0`
(0 N/A rows with nonzero starter weeks). The 11 2020 N/A players (e.g. Dez
Bryant, Frank Gore, Marcus Mariota, Devine Ozigbo — bench-only/never-started
LWebs53/AceMatthew rosterings) follow the identical league-wide
"rostered but never started → starter Points = N/A" rule, not a shorter-season
artifact. Bye? (153 True) and Injury? (394 True) are populated for 2020 the
same as other seasons.

---

## Conclusion

PART 10 is **CLEAN**. The ESPN-2020 backfill integrates into the Sleeper-era
unified pipeline correctly across all six audited dimensions. The 16-week
season is honored everywhere via per-season `playoff_week_start`/`leg` settings
(reg-season split 14 games, PPG /16, all-play /112); ESPN identities map to the
8 stable managers/rosters and the Sleeper player space with no ghosts; the
startup draft is distinct from the 2021 vet draft; transactions and the 13-entry
trade layer (12 with legs → 24 rows; 1 documented empty-leg exclusion) plus the
timestamp-matched commissioner pick overlay all reconcile; awards/records fold
into all-time with no double-counting; and the N/A convention is a consistent
league-wide rule, not a 2020 data gap. No source change. Tests 15/15.
