# Phase 13 Round 13 — Parts A+B (full-population completeness + cross-sheet reconciliation)

Self-designed full-population audit repeating the Parts A/B methodology of
`plan/AUDIT_PHASE13_ROUND12_PARTSAB.md`, run fresh against branch
`claude/agent-part-audits-1yy87u`. Agent 1 of 5 in Round 13.

**Build under audit:** the exports in `exports/*.csv` are FRESH from a just-completed
offline build (`PYTHONPATH=src:lib python3 scripts/offline_build.py`, exit 0; only
the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0` and
`…/draft/espn_2020_draft`). Audited the exports directly; did NOT rebuild and did
NOT modify `src/` or `exports/`.

All cited examples are NOVEL — different players/teams/picks than the Round-12
cast (Puka Nacua, Rachaad White, Jordan Addison, Anthony McFarland, Antonio Brown,
Oliverwkw 2024 / BROsenzweig 2022 / stevenb123 2025 FAAB, 2022 1.04 Treylon Burks)
and the Rounds 4-11 exclusion cast. This round's novel cast: **Nico Collins,
De'Von Achane, Brock Bowers, Sam Darnold, Hunter Henry 2022, Jake Bobo 2024,
Duke Johnson 2021, Will Dissly 2025, Golden Tate 2021, 2023 pick 2.03 De'Von
Achane, and AceMatthew 2023 / JacobRosenzweig 2024 / LWebs53 2025 FAAB.**

**Result: CLEAN — zero defects.** Every Part A completeness check and every Part B
cross-sheet invariant reconciles at full population (0 mismatch). Three
over-inclusive items are flagged, all classified LIKELY BY-DESIGN (2 documented
trade exclusions carried over from prior rounds; 1 out-of-scope future-season
2026 boundary that is new to this build). No source change required.

---

## Dataset under audit (full population)

6 exported seasons (2020-2025), 8 teams, 48 team-seasons, 808 team-weeks,
101 league-weeks, 21,376 player-weeks, 1,859 player_year rows, 649 player_all_time
rows, **514 picks** (10 drafted classes + 5 future-pool classes 2026-2030),
504 trades, 1,510 transactions. (Cols: tw 112, ty 138, tat 148, lw 66, ly 69,
pw 92, py 69, pat 63, picks 41, trades 44, tx 56.)

Row/col shapes differ from the Round-12 template (450 picks, fewer cols) because
this is a different branch/build that has advanced one league-year: the two extra
future-pick classes **2029 + 2030 (32 each = +64 picks → 514)**, plus additional
columns. That is an expected forward-roll, not a regression.

---

## Part A — League-history completeness (full population, no sampling)

### Seasons present in every season-keyed sheet — CLEAN
team_week / team_year / league_week / league_year / player_week / player_year all
carry exactly `{2020,2021,2022,2023,2024,2025}` — 0 missing, 0 extra. transactions
`Season` column is exactly those 6. **No 2026 season stats leaked into any
season-keyed sheet** (relevant to Anomaly #3 below). picks keys by draft-class
label (`startup`,`2021`,`2021 (vet)`,`2022`…`2030`), so future classes are correct,
not season gaps.

### team_all_time — CLEAN
All 8 teams (AceMatthew, BROsenzweig, JacobRosenzweig, LWebs53, Oliverwkw,
plehv79, shmuel256, stevenb123) appear exactly once; 0 duplicates. Per-season
team-set equality between team_week and team_year is exact for all 6 years
(n=8 each; symmetric-difference empty).

### Week completeness — CLEAN
Every active team has every week 1..N in team_week, N matching league_week
exactly: 2020 → 1..16; 2021-2025 → 1..17. 0 missing weeks, 0 phantom weeks;
per-(team,season) week-set == league_week week-set every season (0 deviating
teams in all 6 years). league_week row count = 101 = 16 + 17×5 exactly.

### Duplicate-row sweep — CLEAN
0 duplicate rows on every natural key: team_week (Team,Year,Week)=0; team_year
(Team,Year)=0; player_year (Player,Year)=0; player_week (Player,Year,Week)=0;
league_week (Year,Week)=0; player_all_time (Player)=0.

### player_week → player_year → player_all_time rollup — CLEAN
- pw players (617) ⊆ py players (649) == pat players (649): 0 pw-not-py,
  0 py-not-pat, 0 pat-not-py.
- Exactly one player_all_time row per player (0 duplicate names).
- Every (player,year) in player_week has a player_year row (0 orphans).
- **188 player_year rows / 177 distinct players have NO matching player_week
  (player,year)** — the documented added+dropped-between-weekly-snapshots
  pattern. Verified at full population: 188/188 have `Number of transactions` > 0,
  100% have NaN `Points`, 100% have `Weeks as starter` = 0, and every one carries
  a player_all_time row. NOVEL examples (each: pat row present, 0 pw rows, NaN
  Points, tx>0): **Hunter Henry 2022** (1 tx), **Jake Bobo 2024** (1 tx),
  **Duke Johnson 2021** (2 tx), **Will Dissly 2025** (1 tx), **Golden Tate 2021**
  (1 tx).

### Picks grid — CLEAN
514 picks; every slot present; 0 blank Numbers; all 8 teams present as Original
Team (0 blank). Per-class counts: startup=152, 2021=32, 2021 (vet)=32, 2022=32,
2023=32, 2024=33, 2025=40, 2026=33, 2027=32, 2028=32, 2029=32, 2030=32. The
2024/2025/2026 extras are the documented reward / toilet-future picks. The
(Year,Number) duplicate count of 160 is entirely within the future-pool classes
**2026-2030 (32 each)** and is fully resolved by Original Team: dup on
(Year,Number,**Original Team**) = **0**. Drafted classes (startup, 2021, 2021(vet),
2022-2025) have 0 (Year,Number) duplicates. This is the documented future-pool
placeholder pattern (placeholders keyed by original team, not real duplicate slots).

### Trades raw-vs-export reconciliation — CLEAN (504 export rows, exact-timestamp matched)
Reconciled the raw Sleeper ledger (`exports/snapshot/season_*/weeks/week_*/
transactions.json`, `type==trade & status==complete`) against trades.csv on exact
ET timestamp (raw `created` UTC ms → America/New_York). **254 distinct raw complete
Sleeper trades** across snapshot seasons 2021-2026. Per-season export rows:
2020:24 / 2021:31 / 2022:77 / 2023:111 / 2024:135 / 2025:126 = 504.

**235 distinct export sleeper-era timestamps all match a raw trade — 0 export rows
fabricated / 0 unmatched.** **19 raw trades are absent from the export** (254 − 235):
- **3 are the documented prior-round exclusions** (re-confirmed this round by exact
  tid + ET timestamp + payload):
  1. **2021-08-29 11:30:24 tid 737729902018686976** — phantom player-swap merge
     (`adds={7607:6,7611:8} drops={7607:8,7611:6}` + a 2023 R? pick).
  2. **2023-11-08 12:31:38 tid 1028033090754654208** — net-zero $5↔$5 FAAB swap
     (waiver_budget receiver/sender 4↔2, `adds=None drops=None picks=0`).
  3. **2024-12-08 19:13:35 tid 1171639841122508800** — net-zero $1↔$1 FAAB swap
     (waiver_budget 4↔2, same shape).
- **16 are 2026-season trades** (all `created` in 2026, tids 1313…-1382…). The
  export scope is 2020-2025; the 2026 fantasy season has not been played and is
  not built into any exported season-keyed sheet. See Anomaly #3.

### Transactions raw-vs-export count reconciliation — CLEAN (presence)
transactions.csv: 1,510 rows = 1,048 free_agent + 448 waiver + 14 commissioner.
All 6 seasons present (2020:206 / 2021:236 / 2022:260 / 2023:310 / 2024:249 /
2025:249) — no season silently missing. Per-season raw-vs-export counts are not a
clean 1:1 (export rows count add-rows AND drop-only rows — 408 export rows have a
blank Player Added — and offseason transactions are attributed to a different
season than the snapshot week-directory that stores them). This matches the prior
rounds' treatment of this check as count + season-presence, not exact raw==export
equality. See Anomaly #2.

---

## Part B — Cross-sheet reconciliation at full scale (every row + novel traces)

All numeric invariants computed across EVERY row, N/A-aware (NaN treated as 0 on
the empty side per the pre-Sleeper FAAB era).

### Full-population numeric invariants — all 0 mismatch
- **B1 — league_week == Σ team_week** per (Year,Week), 7 columns (PF, Number of
  transactions, Number of Injuries, Number of suspensions, Number of players on
  bye, Amount of FAAB spent, Number of donuts): **0 mismatches** (FAAB NaN-aware).
- **B2 — team_year `Record` wins == Σ team_week `Win?`** across all 48
  team-seasons: **0 mismatches** (leading "W-L[-T]" wins component parsed).
- **B3 — team_all_time `Times …` rollups == Σ team_year**, all 12 such columns:
  **0 mismatches**.
- **B4 — player_all_time == Σ player_year**, 8 additive counters (Points, Number
  of transactions, Number of drops, Number of trades, Times as Player of the
  week?, Weeks as starter, Weeks missed due to injury, Weeks missed due to
  suspension): **0 mismatches** across all 649 players.
- **B5 — league_year == Σ team_year** (Number of transactions, Amount of FAAB
  spent): **0 mismatches** (FAAB NaN-aware 2020-2021).

### Cross-sheet traces with NOVEL examples — all consistent
- **player_year Points == Σ player_week Points.** **Nico Collins** (2021-2025):
  73.9/90.8/224.9/195.8/226.2 — each equals that year's Σ player_week Points.
  **De'Von Achane** (2023-2025): 177.6/280.8/321.8 — exact. **Brock Bowers**
  (2024-2025): 247.7/176.2 — exact. **Sam Darnold** (2021,2022,2024,2025):
  137.62/42.54/296.32/222.6 — exact; his 2023 py `Points` is NaN with 0 pw rows
  (tx-only that year) — consistent.
- **player_all_time additive end-to-end.** **Nico Collins**: Points 811.6 == Σpy;
  Weeks as starter 32 == Σpy; tx 10 == Σpy; trades 2 == Σpy; POTW 0.
  **De'Von Achane**: Points 780.2 == Σpy; Weeks as starter 39 == Σpy; tx 0;
  trades 0. **Brock Bowers**: Points 423.9 == Σpy; Weeks as starter 26 == Σpy;
  POTW 1 == Σpy 1. All match.
- **Transaction-only players have a player_all_time row** (roster moves reflected
  with no scored player_week): NOVEL **Hunter Henry 2022, Jake Bobo 2024, Duke
  Johnson 2021, Will Dissly 2025, Golden Tate 2021** — all present in pat, 0
  player_week rows, NaN Points, py-year tx ≥ 1. Consistent with the B4
  pat==Σpy 0-mismatch result.
- **FAAB spent sums correctly tx → team_week → team_year**, three-way equality.
  NOVEL **AceMatthew 2023**: Σ transactions Faab $84.0 == team_week Σ FAAB $84.0
  == team_year "Amount of FAAB spent" $84.0; **JacobRosenzweig 2024**: $61 ==
  $61 == $61; **LWebs53 2025**: $91 == $91 == $91.
- **Draft pick traces to the team that ultimately used it.** NOVEL **2023 pick
  2.03 (De'Von Achane)**: Original Team **AceMatthew** → used by **Oliverwkw**,
  `Number of trades = 2`, `Commissioner moved? = False`. trades.csv corroborates
  exactly two legs before the draft: (1) 2022-09-28 12:49:48 AceMatthew *sent*
  "2023 2.03(D. Achane)" to stevenb123 (received Joe Burrow); (2) 2023-05-25
  18:16:56 stevenb123 *sent* it to Oliverwkw (who then drafted De'Von Achane).
  Mirror rows present on each leg. Matches `Number of trades = 2` exactly.

---

## Anomalies flagged (over-inclusive)

Per the over-inclusiveness directive, every borderline item is listed with its
classification. **No item is a CONFIRMED DEFECT.**

### #1 — Two net-zero FAAB-swap trades + one phantom-merge trade absent from trades.csv — LIKELY BY-DESIGN / DOCUMENTED EXCEPTION
The 3 raw Sleeper trades excluded from the export (tids 737729902018686976,
1028033090754654208, 1171639841122508800). These are the exact same 3 documented
exclusions named in `plan/AUDIT_PHASE13_ROUND12_PARTSAB.md` (Part A "Trades
raw-vs-export reconciliation"): 1 phantom player-swap merge and 2 net-zero
$X↔$X FAAB swaps. Re-confirmed this round by exact tid + ET timestamp + payload.

### #2 — Per-season raw-vs-export transaction counts do not reconcile 1:1 — LIKELY BY-DESIGN
Raw non-trade complete Sleeper records (2021-2025: 185/261/302/243/255) do not
equal export transaction rows (236/260/310/249/249). Root causes are structural
and match prior rounds' treatment of this as a presence-only check: (a) export
emits both add-rows and drop-only rows (408 export rows have blank Player Added),
and (b) offseason transactions are attributed to a different display Season than
the snapshot week-directory storing them. No season is missing; totals are stable
(1,510). Not asserted as exact equality by the Round-12 methodology. Flagged for
completeness; **needs no action** unless a future round tightens this to an exact
transaction-record→row bijection (would be a human-judgment decision).

### #3 — 16 raw 2026-season trades present in the snapshot but absent from the export — LIKELY BY-DESIGN (new this build)
The snapshot now contains a `season_2026` directory with 16 complete trades
(created Jan–Jul 2026) and 40 non-trade transactions. None appear in trades.csv /
transactions.csv, and no 2026 season stats appear in any season-keyed sheet
(all sheets are exactly {2020-2025}). This is consistent with the build's declared
season scope (2019-2025 per `plan/AUDIT_PHASE13_10PART.md`) and the fact that the
2026 NFL season has not been played (only 2026 dynasty offseason activity exists
as of the 2026-07-14 build date). Future draft-pick assets for 2026-2030 ARE
carried in picks.csv (as pick placeholders), which is the intended forward-roll.
Classification: by-design out-of-scope future season. Flagged as NEEDS-HUMAN-
CONFIRMATION only in the narrow sense of "confirm the build intentionally stops at
2025 and 2026 is not meant to be an exported season yet" — the export is internally
consistent about excluding it.

---

## Verification

- All Part A and Part B results above were computed via direct `PYTHONPATH=src:lib
  python3` + pandas against the fresh `exports/*.csv` and the raw
  `exports/snapshot/**/transactions.json` ledger. Every invariant reported as
  "0 mismatches" was checked across the FULL population (no sampling), NaN-aware.
- Trade reconciliation used exact ET-timestamp matching (raw `created` ms →
  America/New_York); pick provenance was corroborated against trades.csv mirror
  rows leg-by-leg.
- `pytest` is not installed in this environment (`No module named pytest`), so the
  test-suite parity step from Round 12 could not be run; verification rests on the
  direct pandas reconciliation above.
- No changes were made to `src/` or `exports/` (audit-only; read paths).

## Conclusion

**Parts A + B are fully CLEAN at full population — ZERO defects.** All completeness
checks (seasons, teams, weeks, player rollups, picks grid 514, trade count 504,
transaction count 1,510, zero duplicate rows) and all cross-sheet numeric
invariants (B1-B5) reconcile to 0 mismatch. All NOVEL cross-sheet traces (Nico
Collins, De'Von Achane, Brock Bowers, Sam Darnold; Hunter Henry / Jake Bobo /
Duke Johnson / Will Dissly / Golden Tate tx-only; AceMatthew 2023 / JacobRosenzweig
2024 / LWebs53 2025 FAAB; 2023 2.03 De'Von Achane pick provenance) verify exactly.
Three over-inclusive items are flagged, all LIKELY BY-DESIGN: the 3 documented
trade exclusions (#1), the presence-only transaction-count reconciliation (#2), and
the new out-of-scope 2026 future-season snapshot boundary (#3). No source change
required for Parts A/B this round.
