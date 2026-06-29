# Phase 13 Round 7 — Parts E+F (domain-bounds/plausibility + N/A-vs-0-vs-blank correctness)

Self-designed full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 3 of 5 in Round 7 (siblings: Parts A/B —
`AUDIT_PHASE13_ROUND7_PARTSAB.md` — landed CLEAN at `4bf5575`; Parts C/D —
`AUDIT_PHASE13_ROUND7_PARTSCD.md` — found+fixed 4 tooltip-text drift defects in
`src/formulas.py` at `be65140`).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635`, which was an *ancestor of* origin (not a descendant);
`git merge-base --is-ancestor be65140 HEAD` did NOT print OK. Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`be65140`, the Round-7 Parts C/D tip
carrying the 4 tooltip-text fixes plus all Round-4/5/6 fixes), then confirmed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
player_all_time 649, player_year 1,859, player_week 21,376, team_year 48,
team_all_time 8, team_week 808, trades 504, transactions 1,514, league_year 6,
league_week 101, league_all_time 1.

All examples below are NOVEL — different players/teams/seasons/picks than every
prior round (Rounds 4/5/6 and Round 7 Parts A/B/C/D exclusion lists honoured;
notably avoiding Aidan O'Connell, Aaron Rodgers, Deuce Vaughn, Ameer Abdullah,
Mitchell Trubisky, the 2024 1.01/1.02 picks, the 2026 2.09 toilet pick, Tom
Brady/Drew Brees ages, Jimmy Garoppolo, the playoff-elimination sentinel, and the
Round-5/6 E/F player lists). New surfaces cited here: **JacobRosenzweig**'s
never-winners-bracket clutch N/A; **stevenb123 / shmuel256 / plehv79** startup-
retention decay; the **ws==1 single-start** volatility/consistency gate boundary
(212 rows); the **439 transactions.O-Score** that survive offline (and drive
Transaction skill while Drafting/Trading skill go N/A); JacobRosenzweig 2020's
transaction-skill N/A.

**Result: CLEAN.** Zero defects found. Every numeric/categorical column is
in-domain at full population, and every conditionally-defined column renders
N/A correctly in BOTH directions. The specifically-requested re-verification —
that the ACTUAL 2020 DATA for the 4 columns whose tooltips Parts C/D just fixed is
consistent with the corrected understanding — passes at full population: the three
rookie-draft-only columns are **0 for all 8 teams in 2020** (the 19-round 2020
ESPN startup IS excluded, as now-correctly-documented), and `Startup draft players
remaining` peaks in 2020 for all 8 teams and decays monotonically — exactly the
decay of *2020-startup* retention. No source change was required this round.

---

## Part E — Domain-bounds & plausibility sweep (every numeric/categorical column, every sheet)

Scanned all 12 data sheets (league_all_time / league_week / league_year / picks /
player_all_time / player_week / player_year / team_all_time / team_week /
team_year / trades / transactions). Established per-column plausible domains and
scanned the FULL column population for out-of-domain values.

### Bounded-domain columns — CLEAN
- **Ages** (true age columns only — `Age`, `Age when drafted`, `Player average
  age`, `Team age including picks`; substring-"age" false positives excluded):
  `player_week.Age` [20.62, 48.37], `player_year.Age` [20.77, 48.37],
  `picks.Age when drafted` [20.89, 43.07], `team_week.Team age including picks`
  [22.19, 28.42], `team_year` [22.45, 27.88], `league_year` [24.02, 24.50] — all
  inside [18, 60], **0 out of range** across all 9 age columns. (Top of range is
  the factually-correct retired-QB roster-holding curiosity already documented in
  Round-5/6 E/F — a holding/completeness matter, not a domain violation; not
  re-litigated here.)
- **Week numbers** (`league_week.Week`, `player_week.Week`, `team_week.Week`):
  all in **[1, 17]**. 0 phantom week-0, 0 week>18.
- **Year/Season** (every season-keyed sheet): all numeric values in **[2020,
  2025]** for the played-season sheets; `picks.Year`'s `startup` / `2021 (vet)`
  text labels and `2026-2028` future-pick years are by-design (not a span
  violation); 0 bad numeric years.
- **Dates** (`trades.Date` ×504, `transactions.Date` ×1,514, `transactions.Date
  dropped/traded` ×1,003, parsed `YYYY-MM-DD`): **0 dates outside 2019-2026**, 0
  impossible month/day.
- **Percentage / percentile columns** (every `%` / `percentile` / boom% / bust%
  across player_year, player_all_time, team_year, etc.): **0 values outside
  [0, 100]** among the non-signed columns. The signed-difference columns
  (`…minus…`, `change in…`, `…differential`, etc.) are correctly excluded from the
  [0,100] gate by design.
- **Count columns** (`Number of …`, `Times as …`, `Total trades`, donuts, weeks/
  games, streaks, `Total number of …`, across every sheet — excluding explicitly-
  signed substrings like margin/luck/variance/difference/net/impact/score/points/
  ppg/value): **0 negative counts** at full population.

### Large-magnitude / sentinel scan — all legitimate aggregates
A full-population scan for any `|value| ≥ 9000` returned only legitimate season/
career sums, identical in character to Round-5/6 E/F:
`league_all_time.PF` 112,807 / `Max PF` 138,091 / `Number of players under 10`
12,913; `league_year.PF` 17,935-20,221 / `Max PF` 21,592-24,840;
`team_all_time.Points` 13,072-14,872 / `Points against` 13,721-14,378 / `Max PF`
16,260-18,335; `trades.Trade impact score` (smooth distribution −13,859…+30,738).
**No `9999` / `99999` / `±inf` / NaN-as-number placeholder anywhere** (explicit inf
scan: 0 hits).

**Part E conclusion: CLEAN** — every bounded column in-domain; all large
magnitudes are legitimate aggregates; no sentinel masquerades as data.

---

## Part F — N/A-vs-0-vs-blank correctness (every conditionally-defined column, full population)

Enumerated every `_preserve_na`-governed column directly from `src/lotg.py`'s live
`_preserve_na()` (resolved against the function, not a static copy) and verified,
for the FULL row population, that N/A renders correctly.

### Universal "N/A-not-blank-not-nan" invariant — CLEAN
For **every** `_preserve_na` column on **every** sheet I counted blank-string and
literal-`"nan"` occurrences. Across all sheets — picks (8 preserve-na cols),
player_all_time (26), player_week (11), player_year (30), team_all_time (49),
team_week (11), team_year (48), trades (16), transactions (30), league_all_time
(4), league_week (6), league_year (5) — the result is **0 blank strings and 0
literal-`nan` text in any preserve-na column** (TOTAL cols with a blank/nan
leak: **0**). Every conditionally-absent value renders the true string `N/A`. The
core Part F invariant holds at full population.

### Bidirectional condition correctness — CLEAN (0 over- AND 0 under-broadened)
For each conditional column I re-derived condition X independently from the raw
sheet and checked BOTH failure modes (in-condition-but-not-N/A, and
out-of-condition-but-N/A). NOVEL surfaces this round:

| Column / condition (re-derived) | Rows in-condition | In-cond but NOT N/A (over-narrow) | Out-of-cond but N/A (over-broad) |
|---|---|---|---|
| `transactions.Faab` — value iff waiver & season≥2022 (389) | 389 | **0** | **0** (waiver-pre2022 59 + non-waiver 1,066 all N/A) |
| `transactions.Number of bids` — value iff waiver & season≥2021 (419) | 419 | **0** | **0** (waiver-2020 29 + non-waiver 1,066 all N/A) |
| `transactions.{Number of times dropped by this team, Dropped avg points, Dropped total points}` vs has-`Player Dropped` (352 no-drop) | 352 | **0** | **0** |
| `transactions.Length of tenure on team` vs has-`Player Added` (439 no-add) | 439 | **0** | **0** |
| `transactions` 12 KTC + Net-KTC cols — KTC index unreachable offline | 1,514 | — | all N/A ✓ |
| `player_week` all 5 `(if starter)` cols vs `Starter/Bench=='Bench'` (13,845) | 13,845 | **0** | **0** |
| `player_week.Difference from worst benchable starter (if bench)` vs `Starter` (7,531) | 7,531 | **0** | **0** |
| `team_year.Amount of FAAB spent` — N/A iff Year<2022 (16) | 16 | **0** | **0** |
| `team_year.3-year roster retention rate` — N/A iff Year+3>2025 (24) | 24 | **0** | **0** |
| `team_year.{Win Variance, All-play win %}` — all 48 seasons complete | 48 | **0** N/A | — |
| `picks.Length of tenure on team` — N/A iff unmade pick (97 unmade, 353 made) | 97 | **0** | **0** |
| `player_year.Points` — N/A iff no player_week presence for (Player, Year) | 188 | **0** | **0** (188 N/A == exactly the 188 no-weekly-presence rows) |
| `player_year.{PPG starter, Adjusted PPG starter, Floor/Ceiling percentile, Starter PAR}` — N/A iff Weeks as starter==0 (798) | 798 | **0** | **0** |
| `player_year.{Starter scoring volatility, Consistency percentile}` — N/A iff Weeks as starter<2 (1,010) | 1,010 | **0** | **0** |
| `trades` 7 KTC-diff / Pick-value / O-Score cols — KTC-dependent offline | 504 | — | all N/A ✓ |
| `picks` O-Score + 7 KTC checkpoints — KTC-dependent offline | 450 | — | all N/A ✓ |
| `team_year`/`team_all_time` `Drafting/Trading skill` — picks/trades O-Score N/A offline → skill N/A | 48 / 8 | — | all N/A ✓ |

Notable bidirectional exactness re-confirmed at full population:
- The `(if starter)/(if bench)` player_week columns are **0/0 in both directions
  across all 21,376 player-weeks** (every starter row populated, every bench row
  N/A, and vice versa).
- `player_year.Points` N/A count (**188**) equals EXACTLY the count of player_year
  rows whose `(Player, Year)` has zero player_week presence (the documented
  added+dropped-between-snapshots transaction-only rows) — **0 scored rows wrongly
  N/A'd, 0 weekly-present rows wrongly N/A'd.**
- The volatility/consistency columns have a **stricter ≥2-starts** gate than the
  ≥1-start `PPG starter` family. Re-derived against the *correct* condition, both
  are **0/0**. The 212 rows that are N/A-with-starts for volatility/consistency are
  **exactly** the `Weeks as starter == 1` single-start players (a 1-start player
  has no variance/consistency to compute) — verified: all 212 have ws==1. Not a
  defect; the two column families legitimately differ in their start-count gate.

### Investigated, run to ground, NOT a defect

- **`Transaction skill` is NOT all-N/A offline, unlike `Drafting/Trading skill`** —
  this looked anomalous (all three are "shrunk-mean O-Score" columns) but is
  **correct**: `transactions.O-Score` does NOT depend on the unreachable KTC index
  and carries **439 real values** offline (only 1,075/1,514 are N/A), whereas
  `picks.O-Score` (450/450 N/A) and `trades.O-Score` (504/504 N/A) ARE
  KTC-dependent and fully N/A offline. So `Transaction skill` correctly computes
  (47/48 team-seasons; 8/8 team-all-time) while `Drafting/Trading skill` correctly
  go N/A. The one team-season with `Transaction skill` = N/A — **JacobRosenzweig
  2020** — has 3 transactions but **0 of them carry a real O-Score** (2020
  transaction O-Scores are unrecoverable), so there is genuinely no score to
  shrink-mean. Bidirectionally correct.
- **`team_all_time` clutch + `Playoff win %` = N/A for exactly 1 of 8 teams** —
  this is **JacobRosenzweig**, whose 6-season finishes are 7th/8th/8th/7th/8th/6th:
  they **never reached the winners' bracket (top-4)** in league history, so there
  is no playoff PF/win% delta to compute. Correct N/A; all 7 other teams (who each
  made the bracket at least once) carry real values.
- **`league_week` week-over-week columns N/A for exactly 1 of 101 rows** — that row
  is the league's very first week (**2020 Week 1**), where the prior week doesn't
  exist. Correct N/A (the Round-2 F5 fix still holds).
- **`trades.Asset difference in average age` = 0 (not N/A) for 86 single-side /
  FAAB-only rows** — documented intentional design (`src/lotg.py` ~9571 reports
  `0.0` rather than blank when one side has no aged asset). Re-confirmed, left
  unchanged (same as Round-5/6 E/F).

### Specifically requested — 2020 DATA of the 4 Parts-C/D-fixed columns matches the corrected tooltip understanding

Parts C/D corrected 4 tooltips that had conflated the league's inaugural **2020**
ESPN startup draft (19 rounds) with the **2021** veteran draft. The corrected
understanding: the code treats the 2020 startup and 2021 vet drafts as two
SEPARATE excluded events; `Draft Value` / `Number of first round picks made` /
`Total number of picks made` count **rookie-draft selections only** (so the
19-round 2020 startup is excluded → 0 for 2020), and `Startup draft players
remaining` tracks how many of a team's OWN **2020**-startup picks it still rosters
(so it must peak in 2020 and decay). I re-verified the ACTUAL `team_year` DATA at
full population (all 8 teams, all 6 seasons), with NOVEL team examples:

**Three rookie-draft-only columns — 2020 == 0 for ALL 8 teams (startup excluded):**
- `Draft Value` 2020 = **0.0** for all 8 teams (only value present: `0.0`).
- `Number of first round picks made` 2020 = **0** for all 8 teams.
- `Total number of picks made` 2020 = **0** for all 8 teams.

This confirms the 19-round 2020 ESPN startup is excluded from these three columns
(otherwise 2020 would carry large draft-count/value totals) — exactly as the
corrected tooltips now document.

**`Startup draft players remaining` — peaks in 2020, decays (2020-startup retention):**
Full per-team time series (NOVEL teams cited):

| Team | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|
| stevenb123 | **15** | 9 | 3 | 0 | 0 | 0 |
| shmuel256 | **7** | 3 | 1 | 2 | 1 | 0 |
| plehv79 | **14** | 12 | 4 | 4 | 4 | 1 |
| JacobRosenzweig | **17** | 10 | 6 | 3 | 2 | 0 |
| AceMatthew | **9** | 6 | 3 | 2 | 3 | 3 |
| LWebs53 | **12** | 9 | 3 | 4 | 1 | 1 |
| Oliverwkw | **12** | 8 | 7 | 6 | 1 | 1 |
| BROsenzweig | **12** | 9 | 6 | 3 | 3 | 3 |

For **0 of 8 teams** is any later year ≥ the 2020 value — 2020 is the maximum for
every team, with a broadly monotone decay (e.g. stevenb123 15→9→3→0→0→0;
JacobRosenzweig 17→10→6→3→2→0; shmuel256 starting from the smallest startup
retention, 7). This is exactly the decay of **2020-startup** retention the
corrected tooltip describes. If the column tracked a 2021 event (as the OLD tooltip
text wrongly said), the 2020 column would read ≈0 — it does not. The DATA is
consistent with the corrected understanding.

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~61s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- **No source changes were needed (no defects in Parts E/F this round).** Build
  artifacts reverted; only this new file is added.

## Conclusion
**Parts E + F are fully CLEAN at full population — ZERO defects.** Every
numeric/categorical column across all 12 sheets is in-domain (no out-of-range age/
week/year/date/percentage, no negative counts, no `9999`/`inf` sentinel). Every
conditionally-defined column renders N/A correctly in BOTH directions — **0 blank
strings, 0 literal-`nan`, 0 over-narrowing, 0 over-broadening** — verified
column-by-column with NOVEL surfaces (the ws==1 single-start volatility gate, the
439 KTC-independent transaction O-Scores driving Transaction skill,
JacobRosenzweig's never-winners-bracket clutch N/A). The specifically-requested
re-verification confirms the ACTUAL 2020 DATA for the 4 Parts-C/D-fixed columns
matches the corrected understanding exactly: **Draft Value / first-round picks /
total picks = 0 for all 8 teams in 2020 (the 2020 ESPN startup is excluded), and
Startup draft players remaining peaks in 2020 for all 8 teams and decays** —
confirming the data was already consistent with the corrected tooltip text (the
Parts C/D fixes were pure text, and the DATA they now describe was correct all
along). No source change was required for Parts E/F this round.
