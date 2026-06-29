# Phase 13 Round 6 — Parts A+B (full-population completeness + cross-sheet numeric reconciliation)

Self-designed full-population audit repeating the Parts A/B methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. This is agent 1 of 5 in Round 6.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `5d154a7` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`5d154a7`, the Round-5
Parts I/J tip carrying all 3 Round-5 fixes) before any work, then confirmed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Reflects all Round-5 fixes:
trades.csv 504, picks.csv 450, transactions.csv 1,514, player_all_time 649,
player_year 1,859.

All examples below are NOVEL — different players/teams/picks than every prior
round (deliberately avoiding Josh Doctson, Kenny Pickett, Hunter Henry,
K.J. Osborn, Michael Carter, Rhamondre Stevenson, Pacheco, Jefferson, DJ Moore,
Tyler Johnson, Larry Fitzgerald, Cam Newton, Mike Gesicki, the BROsenzweig pick
examples, the 2026 2.09 toilet pick, Mitchell Trubisky/Hayden Hurst as *new*
findings, AJ Dillon, Matt Ryan, Tony Pollard, Mattison, Drake, Meyers, Taysom
Hill, Kerryon Johnson, Aaron Jones, T.J. Hockenson, Robbie Chosen, CEH).

**Result: CLEAN.** Zero defects found. Every Part A completeness check and every
Part B cross-sheet invariant reconciles at full population (0 mismatch), with
exactly the documented exclusions named and justified.

---

## Dataset under audit (full population)

6 seasons (2020-2025), 8 teams, 48 team-seasons, 808 team-weeks, 101 league-weeks,
21,376 player-weeks, 1,859 player_year rows, 649 player_all_time rows, 450 picks,
504 trades, 1,514 transactions.

---

## Part A — League-history completeness (full population, no sampling)

### Seasons present in every season-keyed sheet — CLEAN
team_week / team_year / league_week / league_year / player_year / player_week all
carry exactly `{2020,2021,2022,2023,2024,2025}`. 0 missing, 0 extra, fully
consistent. picks.csv keys by draft-class label (`startup`, `2021`, `2021 (vet)`,
`2022`…`2028`) by design — future classes 2026-2028 are correct, not a gap.

### team_all_time — CLEAN
All 8 teams (AceMatthew, BROsenzweig, JacobRosenzweig, LWebs53, Oliverwkw,
plehv79, shmuel256, stevenb123) appear exactly once; 0 duplicates. Every team
present in team_year AND team_week for all 6 seasons; team_year vs team_week
team-set symmetric-diff = 0 every season; 0 teams missing from team_year.

### Week completeness — CLEAN
Every active team has every week 1..N in team_week, N matching league_week
exactly: 2020 → 1..16; 2021-2025 → 1..17 (incl. playoffs). 0 missing weeks,
0 phantom weeks; per-(team,season) week-set == league_week week-set every season.

### player_week → player_year → player_all_time rollup — CLEAN
- pw distinct 617 ⊆ py distinct 649 ⊆ pat distinct 649: 0 in pw-not-py,
  0 in py-not-pat, 0 in pat-not-py.
- Exactly one player_all_time row per player (0 duplicate names).
- Every (player, year) in player_week has a player_year row (0 orphans).
- 32 players in player_year but never in player_week — investigated and CORRECT:
  the documented "added+dropped between weekly snapshots" pattern (a transaction-
  tracking player_year row with no scored player_week row). Count is stable.

### Picks grid — CLEAN
450 picks; every slot appears exactly once. startup = 152 (19 rounds × 8 teams),
0 duplicate slot numbers. Each future class = 32 (8 teams × 4 rounds) keyed by
(round, original team) — the apparent `1.??`/`2.??` "duplicate" Numbers are the
not-yet-ordered future-pool placeholders, exactly one per team per round, 0 real
dups. 2026 = 33 (the +1 is the documented Round-5 E/F 2.09 toilet-reward future
pick). 2024 = 33 / 2025 = 40 carry their extra reward picks with distinct Numbers,
0 repeated slots. 0 blank Numbers; all 8 teams present as Original Team.

### Trades raw-vs-export reconciliation — CLEAN (re-verified 504, DST-aware, NOVEL examples)

Reconciled the raw Sleeper ledger (`exports/snapshot/season_*/weeks/week_*/
transactions.json`, `type==trade` & `status==complete`) against trades.csv,
matching on the **exact** event timestamp (raw `created` UTC ms → America/New_York
local, the export Date format). Per-season raw-complete vs export-distinct:

| Year | raw complete | export distinct | diff |
|------|-------------:|----------------:|-----:|
| 2021 | 16 | 15 | 1 |
| 2022 | 38 | 38 | 0 |
| 2023 | 55 | 54 | 1 |
| 2024 | 67 | 66 | 1 |
| 2025 | 62 | 62 | 0 |

Exact-timestamp reconciliation isolates the diff to **exactly 3 raw trades absent
from the export, and 0 export trades fabricated** (every export Date 2021-2025 has
a matching raw ET timestamp). All 3 absences are the documented exclusions, here
named with NOVEL detail:

1. **2021-08-29 11:30:24 — tid 737729902018686976** (Michael Carter +
   Rhamondre Stevenson + 2022 R4): the documented "Manual 2021 botched-trade
   merge" — Sleeper split one real pick trade into a phantom player-swap; the
   phantom is merged into the pick trade (which IS in the export). Correctly
   excluded. *(Named in Round 5; re-confirmed, not re-counted.)*
2. **2023-11-08 12:31:38 — tid 1028033090754654208**: a perfectly symmetric
   **net-zero FAAB swap** — roster 2 ↔ roster 4 exchange `$5 ↔ $5`, no players,
   no picks (`adds=None, drops=None, draft_picks=[]`). A no-op "trade." NOVEL
   example. Correctly excluded.
3. **2024-12-08 19:13:35 — tid 1171639841122508800**: another symmetric
   **net-zero FAAB swap** — roster 2 ↔ roster 4 exchange `$1 ↔ $1`, no players,
   no picks. NOVEL example. Correctly excluded.

So 2020 (12 email trades) + 247 distinct Sleeper trades = the export's
**247 distinct trade events × ~2 mirror sides = 504 trades.csv rows**. No real
trade is wrongly washed (the Round-5 A/B commissioner-wash fix holds — the wash
sweep removed nothing that moves net assets) and no trade is double-counted.
`Σ team_year "Total trades" = 504`; per-season league_year `Total trades`
(12/15/38/54/66/62 = 247) equals the distinct count; the team_year ratio is the
expected ~2.0-2.1 (one count per participating team).

### I/J platform-seam teleport — generalized full-population re-scan — CLEAN

The Round-5 I/J fix closed the 2020→2021 ESPN→Sleeper-seam teleport (a player on
a 2020 final roster, absent ALL of 2021, re-added later by the SAME team had no
transfer-day drop, so the 2020 holding teleported across the empty seasons —
Mitchell Trubisky, Hayden Hurst). The prompt asks whether the same *systemic* gap
could exist for OTHER players, at ANY season seam, that the I/J agent did not
enumerate. I scanned the **entire population** for it three independent ways:

1. **Transaction-layer teleport scan.** For every ADD transaction, flagged any
   whose `Date dropped/traded` jumps across a FULL season in which the player has
   ZERO player_week presence anywhere, with NO intervening drop closing the
   holding. Result: **2 candidates surfaced — both CORRECT, not teleports:**
   - **KJ Hamler** (plehv79): `2020-09-24 added` → `2022-01-06 dropped by plehv79`
     → `2022-01-06 added by Oliverwkw`. Absent all 2021 (verified: not in the
     final 2021 `rosters.json` nor any 2021 matchup), but the holding IS closed by
     a real-transition drop (he sat un-scored on plehv79's bench through 2021,
     then was released into the 2022 offseason FA pool as Oliverwkw picked him up).
   - **Jalen Guyton** (shmuel256): `2020-12-27 added` → `2022-01-06 dropped by
     shmuel256` → `2022-01-06 added by stevenb123`. Same pattern, properly closed.

   The distinction from Trubisky/Hurst is decisive: Hamler/Guyton are re-acquired
   by a **DIFFERENT** team, so the roster-diff drop synthesis fires and closes the
   holding at the transfer instant. The I/J bug was specific to re-acquisition by
   the **SAME** team after a multi-season void, where no other-team-add event
   exists to trigger that synthesis. No such unclosed case remains.

2. **Narrative-layer teleport scan (all 649 player + 10 pick history comments).**
   Parsed every history comment's chronological event lines and flagged any
   `added by` immediately followed by another `added by` with a ≥2-season gap and
   no close between: **0 teleports.** Also **0 chronological inversions** across
   all 659 comments. Trubisky and Hurst both verified still correctly closed
   (`2021-08-23: dropped` synth lines present between the 2020 add and the later
   same-team re-add).

3. **Double-drop scan.** Flagged 5 consecutive-same-team `dropped by` pairs, all
   **FALSE POSITIVES** — each has an intervening draft re-acquisition the line
   regex didn't capture (drop → `(vet) draft / Draft: TEAM drafted …` → drop):
   DeeJay Dallas, Marquez Valdes-Scantling, Odell Beckham, Parris Campbell,
   Phillip Lindsay. **0 genuine double-drops.**

### Transactions raw-vs-export reconciliation — CLEAN
transactions.csv: 1,514 rows = 1,052 free_agent + 448 waiver + 14 commissioner.
All 6 seasons present (2020:207 / 2021:237 / 2022:261 / 2023:310 / 2024:250 /
2025:249); no season silently missing. 2020 = 178 FA + 29 waiver + 0 commissioner
(consistent with the ESPN-2020 emitter producing no commissioner-type rows). The
2 Round-5 I/J synth drops (Trubisky-2021, Hurst-2021) are present and each
produces the documented transaction-only player_year row (1 tx / 1 drop / NaN
points / 0 starter weeks).

---

## Part B — Cross-sheet numeric reconciliation at full scale (every row)

All computed across EVERY row, not sampled (boolean `Win?` parsed as True/False;
`N/A` treated as "not tracked", consistent on both sides):

- **B1 — league_week == Σ team_week** per (Year,Week), 7 columns (PF, Number of
  transactions, Injuries, suspensions, players on bye, FAAB spent, donuts):
  **0 mismatches.**
- **B2 — team_year Record wins == Σ team_week Win?** across all 48 team-seasons:
  **0 mismatches** (and record total W+L+T == team_week game count, 48/48 exact).
- **B3 — team_all_time award rollups == Σ team_year**, all 12 `Times …` columns:
  **0 mismatches.** Also team_all_time `All time record` == Σ team_week
  wins/games: **0 mismatches.**
- **B4 — player_all_time == Σ player_year**, 13 additive counters (Points,
  Number of transactions / drops / trades, Times as Player/Captain/QB/RB/WR/TE of
  the week, Weeks missed injury / suspension, Weeks as starter): **0 mismatches.**
  Spot-verified the 2 Round-5 I/J synth players reconcile exactly
  (Trubisky pat==Σpy on tx/drops/trades/starter-weeks; Hurst likewise).
- **B5 — league_year == Σ team_year** (Number of transactions, Amount of FAAB
  spent), N/A-aware: **0 mismatches.** 2020/2021 FAAB is `N/A` on both
  league_year and every team_year row (FAAB only tracked from 2022 Sleeper era) —
  consistent, not a gap.
- **B6 — league_year Total trades** = distinct-trade count (12/15/38/54/66/62 =
  247); Σ all team_year Total trades = **504** = 247 distinct × ~2 sides. The
  league_week "Number of trades" dedup (once per distinct trade, vs once per
  participating team in team_week) is the documented intentional design,
  unchanged, consistent end to end.

---

## Verification

- `pytest tests/ -q`: **15 passed** in ~76s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` (validates roster-lineage continuity
  end to end, confirming the existing synth drops do not break continuity) and
  `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- No source changes were needed (no defects). Build artifacts reverted.

## Conclusion

**Parts A + B are fully CLEAN at full population — ZERO defects.** All
completeness checks (seasons, teams, weeks, player rollups, picks grid, trade
count 504, transaction count 1,514) and all cross-sheet numeric invariants
reconcile to 0 mismatch. The generalized full-population re-scan for the I/J
same-team-re-acquisition-after-a-full-season-void teleport pattern found NO
remaining unclosed case anywhere (the only 2 same-team-gap candidates,
KJ Hamler and Jalen Guyton, are correctly drop-closed because they moved to a
different team at the transfer). The 3 raw trades excluded from the export are
exactly the documented exclusions (1 phantom-merge + 2 net-zero FAAB swaps),
named here with NOVEL detail. No source change was required for Parts A/B this
round.
