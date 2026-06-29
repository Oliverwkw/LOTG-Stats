# Phase 13 — 10-part audit (this cycle, Round 1), Parts 4-6: CLEAN

Second segment (Parts 4, 5, 6) of the 10-part audit type. Continues directly
from Parts 1-3 (`d0da398`, CLEAN, no source change). This segment covers:

- **Part 4** — Edge cases (0-game players, mid-season trades, taxi-squad edges,
  bye weeks, never-played players, rookies, retirees, very short/long careers).
- **Part 5** — Duplicate/redundant column sweep across all output CSVs.
- **Part 6** — Data-quality gaps (missing data, N/A handling, broken joins,
  orphaned references).

## Result: PASS on Parts 4-6 — zero defects, no source change.

## Environment / freshness

- **Worktree self-check:** the recurring stale-worktree bug recurred — initial
  `git merge-base --is-ancestor d0da398 HEAD` printed `STALE`. Hard-reset to
  `origin/claude/phase-13-audit-tsapoy`; confirmed `git log -1` = `d0da398`
  ("Phase 13 10-part audit Round 1 Parts 1-3: CLEAN").
- **Build:** fresh offline build (`PYTHONPATH=src:lib python3
  scripts/offline_build.py`), exit 0; exactly the 2 expected network-unavailable
  warnings (`api.sleeper.app/v1/league/0` and `…/draft/espn_2020_draft`).
  Final populations matched prior rounds (player_week 21,376; team_week 808;
  player_year 1,859; player_all_time 649; picks 450; trades 504; transactions
  1,514).
- **Tests:** `PYTHONPATH=src:lib python3 -m pytest tests/ -q` → **15 passed**.

All illustrative examples below are NOVEL — disjoint from the documented cast of
prior rounds and the exclusion list (avoided AceMatthew, Irv Smith, Mariota,
Bridgewater, Likely, Ronnie Rivers, Cooper Rush, the 4 transaction-pad players,
Breece Hall, Drake London, Kyren Williams, Tank Dell, Chuba Hubbard, Calvin
Ridley as PRIMARY examples — where any appears it is only as incidental
roster-ledger context, not the illustrative subject).

---

## Part 4 — Edge cases: PASS

### Started once, scored zero — Aaron Rodgers 2023 (novel)
Rodgers tore his Achilles on the first drive of 2023 wk1. player_year row:
Points = 0.0, Weeks as starter = **1**. All starter-derived stats handled
cleanly and consistently:
- Starter scoring volatility = **NaN** (needs ≥2 starts — correct; the 1-start
  rule from Round-1 Part 3 holds here too).
- Starter scoring floor = ceiling = **0.0**; Starter boom % = 0.0; Starter
  bust % = **100.0** (0 ≤ 5 → bust).
- Times as Lowest starter on team? = **1** (he was the team's lowest scorer that
  week); Highest = 0.
- PPG starter = 0.0; Adjusted PPG bench = NaN (never benched); diff = 0.0.
No division-by-zero, no inf, no garbage. Confirms the "1 started week worth 0
points" edge is fully handled.

### Never-scored "ghost" players (32 all-time) — Dwayne Haskins, Frank Gore, Dez Bryant (novel)
Players rostered/transacted but who never recorded a single point. All scoring
columns are correctly NaN (Points, Avg points, all volatility/floor/ceiling/
boom/bust/PPG variants for both starter and rostered). Non-scoring counters
(Number of transactions, Number of drops) carry real integers (Haskins 6 tx / 3
drops; Gore 2/1; Bryant 4/2). `Weeks as starter` = 0.
- One consistency point examined and **cleared**: these ghosts show `% of points
  (highest team)` = **0.0** (not NaN) while `Team for highest % of points` =
  NaN. This is NOT an anomaly: the share column is filled to a real-0 for EVERY
  non-starter (204 *scoring* non-starters, e.g. Adonai Mitchell 140.66 pts but
  0 starts, share = 0.0 + NaN team-name; A.T. Perry; Aidan O'Connell) — the
  share is 0 of any team's starter total, with the team-name as the N/A
  companion. `% of points (highest team)` is never NaN in player_all_time
  (0/649); the ghosts simply land in the established 0.0-share/NaN-team bucket.

### Retirees re-rostered — Tom Brady 2023-2025, Drew Brees 2024-2025 (novel)
Brady retired after 2022; Brees after 2020. They reappear as roster-only
player-years with NaN/0 points at ages 46-48 (Brady 2025 Age = 48.37, the
oldest player-year in the dataset). Traced to **real** (if quirky) roster moves
in the transaction/trade ledger:
- Brady: dropped/added on LWebs53 (Jan-Feb 2022), re-added by stevenb123 (Dec
  2024, Dec 2025) — every player-year (2020-2025) reconciles to its ledger
  events; 2022 = 263.30 real pts, 2023 NaN (roster-only), 2024/2025 = 0.0.
- Brees: dropped by JacobRosenzweig → added by LWebs53 (2024-12-29), dropped
  (Feb 2025). player_year 2024 shows Top Team JacobRosenzweig / Last team
  LWebs53 / Number of teams = 2 — matches the swap exactly.
The retiree edge is handled correctly: real ledger moves → real (zero-point)
roster years, never phantom rows.

### Mid-season / multi-team — Adam Thielen 2023 (=4), Cooper Kupp 2024 (=5) (novel)
585 player-years sit on >1 team. Two large cases hand-traced against the
transaction+trade ledger, confirming `Number of teams` is correct BY DESIGN
(it is the union of player_week-derived teams with full-fantasy-year tenure
spans — `src/lotg.py:12050-12074`, deliberately catching offseason/partial-week
owners invisible to weekly snapshots):
- **Adam Thielen 2023** — `Number of teams` = 4 but player_week shows only 2
  (JacobRosenzweig, Oliverwkw). The FY2023 full-year window (Sep 2023-Sep 2024)
  contains four owners via trades: JacobRosenzweig↔Oliverwkw (2023-10-09),
  Oliverwkw↔shmuel256 (2024-05-03), LWebs53↔shmuel256 (2024-08-06) →
  {JacobRosenzweig, Oliverwkw, shmuel256, LWebs53} = **4**. ✓
- **Cooper Kupp 2024** — `Number of teams` = 5 but player_week shows only 1
  (shmuel256). FY2024 (Sep 2024-Sep 2025) offseason churn (Mar/Jul/Aug 2025
  trades across shmuel256, stevenb123, LWebs53, Oliverwkw, BROsenzweig) puts him
  on ~5 owners during the FY window though only shmuel256 rostered him during
  played weeks. ✓
The 2 vs 4 / 1 vs 5 gaps are the intended full-FY behavior, not a defect.

### Future-pick & "Unknown" rows
97 picks rows are future draft picks (2026/2027/2028, label `R.??`) plus the
synthetic 2026 2.09 — "Player Picked" = "Unknown" (player not yet known). All
their derived stats (Avg PPG, Points added, % of starts, Age when drafted,
Length of tenure, O-Score) are uniformly NaN — correct N/A for unrealized picks.
This is the sole "orphan" in the picked-player set and is legitimate.

### Bye weeks & season-length edges
- player_week Bye? = True on 1,237 rows; **0** of them carry >0 points (no
  bye-with-score contradictions).
- 2020 correctly has **16** weeks (ESPN backfill); 2021-2025 have **17**. No
  phantom week-17 in 2020 at either team_week or player_week grain.
- Lineup-config change handled: 9 starters 2020-2023 → 10 starters 2024-2025
  (the FLX2 slot appears only in 2024/2025, 136+136 = 272 starts). This is a
  real roster-rule change, correctly reflected — see Part 5 note below.

---

## Part 5 — Duplicate / redundant column sweep: PASS

Swept all 12 CSVs for (a) duplicate column NAMES and (b) byte-equal column
CONTENT. After excluding all-NaN KTC/O-Score columns (100% NaN in the
no-network sandbox — their pairwise "equality" is the trivial NaN==NaN artifact
already documented in Round-1 Part 3, and they DIFFER in a networked build),
every remaining equal-content pair was investigated and is **coincidental data
equality**, NOT redundant logic:

1. **`Most number of QBs started == Most number of TE started from same NFL
   team`** (team_year, team_all_time, league_*). Source (`src/lotg.py:4757,
   4763`) computes these via position-specific `max_same_team_by_pos(starters,
   "QB")` vs `"TE")` — genuinely distinct logic. They coincide because the
   league starts exactly one QB and (almost always) one TE, so the per-week
   max-from-same-NFL-team is 1 for both; the year/all-time `max` washes out the
   2 TE-less weeks. At team_week grain they DIFFER (QB = 1 on all 808 rows; TE =
   0 on 2). The *rostered* QB/TE variants differ at every grain (team_year QB
   rostered has values {1,2,3}; TE rostered {1,2}). Not a duplicate.

2. **`Weeks suspensions == Weeks of starter suspensions`** (team_year,
   team_all_time) and **`Number of suspensions == Number of starter
   suspensions`** (team_week). Source applies the starter gate IDENTICALLY to
   injuries and suspensions: `_missed_susp_starter = _missed_susp &
   _was_recent_starter` exactly parallels `_missed_injury_starter` (`src/lotg.py:
   10866-10867`). Proof it is coincidental: the injury pair clearly DIFFERS
   (3,837 total injury weeks vs 2,071 starter injury weeks), so the gate works.
   Suspensions coincide (41 == 41) only because every suspension-missed
   player-week in league history involves a star who was a recent starter — the
   5 suspended players are DeAndre Hopkins (plehv79 2022 wk1-6), Deshaun Watson
   (shmuel256 2022, 10 weeks), Rashee Rice (2025 wk1-6), plus 2 others. No
   bench-depth player was ever suspended, so the starter-gated count equals the
   total. Correct logic, coincidental data.

3. **`Drafting skill == Trading skill`** (team_year/all_time) and the extra
   league_all_time `…rostered…` equalities — all confined to columns that are
   100% NaN under no-network (KTC/O-Score dependent). Verified: Drafting skill
   and Trading skill are 48/48 NaN in this build. Trivial NaN==NaN, differ in a
   networked build. Not real duplicates.

Derived-column agreement spot-checks (catch columns that *should* derive from
each other but DISAGREE) — all **0 mismatches**:
- team_year `Win %` == W+0.5T / games parsed from `Record` (0/48).
- team_year `Differential` == Points − Points against (0/48).
- team_year `All-play win % minus Win %` == AP − Win% (0/48).
- player_all_time `PPG starter vs bench diff` == Adjusted PPG starter − Adjusted
  PPG bench where both present (0/385). Where one side is NaN (215 rows) the diff
  treats the missing side as 0 — this is the DOCUMENTED Phase-1C convention
  (`src/lotg.py:11991-11999`, "Treat missing side as 0 … Return None only when
  BOTH are missing", established by a prior Rashee-Rice-2024 audit). Verified
  exactly: for all 21 never-started players with bench games, diff == −(Adjusted
  PPG bench). Not a defect.

---

## Part 6 — Data-quality gaps: PASS

- **Orphaned references — none.** All player_year `Top Team`/`Last team` and
  player_all_time `Top team`/`Last team` values are among the 8 valid teams
  (0 strays). Every transactions.csv `Player Added`/`Player Dropped` resolves to
  a player_all_time entry (0 orphans, excluding the legitimate "Unknown" future
  picks). picks.csv `Player Picked`: 336/337 distinct names resolve; the only
  non-resolver is "Unknown" (future picks, Part 4).
- **Cross-sheet player-set consistency.** player_year ↔ player_all_time player
  sets are identical (0 in one but not the other, both directions).
- **Grain uniqueness (no broken joins inflating rows).** player_year
  (Player, Year), player_week (Player, Year, Week), and team_week
  (Team, Year, Week) all have **0** duplicate keys. player_all_time has 0
  duplicate player names.
- **Core columns never NaN where data must exist.** team_week Team/Year/Week/
  PF/Max PF/Efficiency/Win?/Margin = 0 NaN; team_year Team/Year/Points/Points
  against/Record/Win %/Result = 0 NaN; player_year Age = 0 NaN (range 20.77 to
  48.37, all plausible — youngest Braelon Allen 2024; oldest Brady 2025).
- **N/A consistency.** Future picks → all derived stats NaN. Never-started
  share columns → 0.0 share with NaN team-name (consistent across all 236
  non-starters). KTC/O-Score columns → 100% NaN (the established no-network N/A,
  not 0).
- **Rookie sanity.** 308 rookie-years / 1,551 non-rookie. Only 2 rookies older
  than 26 (Devaughn Vele 2024 at 26.92, Tyler Shough 2025 at 26.12) — both are
  genuine late-entry NFL rookies, not mis-classifications.

---

## Conclusion

Parts 4-6 of the 10-part audit are **CLEAN** — zero defects, no source change.
Every duplicate-column candidate resolved to coincidental data equality or the
documented no-network NaN artifact (not redundant logic); every edge case
(0-point started weeks, never-scored ghosts, re-rostered retirees, 4-5-team
mid-season movers, 16-vs-17-week seasons, the 9→10 starter expansion, future
picks) is handled correctly with consistent N/A treatment; and there are no
orphaned references, broken joins, or grain-uniqueness violations. Tests 15/15
before and after (no source touched). Remaining segments — Parts 7-10 — to be
run separately.
