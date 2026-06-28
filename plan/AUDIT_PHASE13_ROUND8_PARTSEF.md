# Phase 13 Round 8 — Parts E+F (domain-bounds/plausibility + N/A-vs-0 correctness)

Self-designed full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 3 of 5 in Round 8 (siblings: Parts A/B —
`AUDIT_PHASE13_ROUND8_PARTSAB.md` — landed CLEAN at `e87b0b7`; Parts C/D —
`AUDIT_PHASE13_ROUND8_PARTSCD.md` — found+fixed 3 tooltip-text 2020-season
defects at `518a581`, all the same family as Round 6/7: counts hard-coded to the
17-week 2021+ seasons that silently mis-state the completed 16-week 2020 ESPN
season).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635`, which was an *ancestor of* origin (not a descendant);
`git merge-base --is-ancestor 518a581 HEAD` did NOT print OK. Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`518a581`, the Round-8 Parts C/D tip
carrying the 3 tooltip fixes plus all Round-4/5/6/7 fixes), then confirmed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
player_all_time 649, player_year 1,859, player_week 21,376, team_year 48,
team_all_time 8, team_week 808, trades 504, transactions 1,514, league_year 6,
league_week 101, league_all_time 1.

All examples below are NOVEL — different players/teams/seasons/picks than every
prior round (Rounds 4/5/6/7 and Round 8 Parts A/B/C/D exclusion lists honoured;
notably avoiding the PF/Win%/Record C/D tooltips, Cooper Kupp, Wan'Dale Robinson,
George Pickens, Ryan Tannehill, A.J. Brown, Kyle Pitts, Alvin Kamara, Bo Melton,
Brock Wright, Derek Watt, JacobRosenzweig's clutch N/A as the headline, the
ws==1 single-start gate, the playoff-elimination headline, and the Round-5/6/7
E/F player lists). New surfaces cited here: the **2020 Semifinal +5 homefield
bonus landing on Week 15** (data, not tooltip); the **Regular-season win %
denominator 14-for-2020 / 15-for-2021** (data); the **2020 per-team elimination
weeks 11-13** (≤14); the **2025 $10,000 FAAB budget** that makes a $120 single
bid / $522 total in-domain; **Jacory Croskey-Merritt**'s $120 bid; the
**plehv79 2025 $258 spend**; the **90 real-zero `Dropped total points`** drops.

**Result: CLEAN.** Zero defects found. Every numeric/categorical column across all
13 export sheets is in-domain at full population, and every conditionally-defined
column renders N/A correctly in BOTH directions. The specifically-requested
COMPUTED-DATA re-verification — that no DATA is miscalculated for 2020 by a
hard-coded week-16/17 assumption — passes at full population: every
season-length-dependent column (PF Semifinal homefield bonus, Record, Win %,
Regular-season win %, Week of playoff elimination, FAAB era-gating) computes the
*correct 2020 value*, anchored on the season's real 16-week structure (Semifinal
Week 15) rather than the 2021+ 17-week structure (Semifinal Week 16). No source
change was required this round.

---

## Specifically-requested deep dive — 2020 16-week vs 2021+ 17-week: is any DATA (not just text) miscalculated?

Given Round 8 Parts C/D found three *tooltips* that hard-coded a 17-week count, I
specifically audited whether the same seam corrupts any **computed value**. I
(1) grepped `src/lotg.py` + `src/espn_2020.py` for every hard-coded `16`/`17`/
`playoff_start`/`semi`/`championship` site, (2) classified each as
season-aware-dynamic vs hard-coded, and (3) cross-checked the actual exported
2020 DATA against the 16-week reality. **No 2020 data defect found.**

### Week structure is per-season-correct — CLEAN
- `league_week` / `team_week` / `player_week` carry **2020 = weeks 1..16** and
  **2021-2025 = weeks 1..17** (0 phantom week-17 for 2020, 0 missing weeks).
- 2020 playoff Week Names land on the *16-week* bracket: **Week 15 =
  {Semifinal, Toilet Semis}**, **Week 16 = {Final, 3rd Place, Toilet Final,
  Toilet Trash}** — vs 2021's **Week 16 Semifinal / Week 17 Final**. The code
  computes these off the season's `playoff_week_start` setting
  (`espn_2020.py` line 574 sets `playoff_week_start=15` for 2020; Sleeper supplies
  16 for 2021+), NOT a hard-coded constant.

### The PF Semifinal +5 homefield bonus lands on the RIGHT week for 2020 — CLEAN (data-verified)
This is the COMPUTED counterpart of the Round-8 C/D `PF` tooltip fix. `lotg.py`
4271-4297 applies the +5 higher-seed homefield bonus at `playoff_start` (15 for
2020, 16 for 2021+). Verified directly against the 2020 Week-15 Semifinal rows:

| 2020 Semifinal team (Wk15) | team_week PF | Σ starter player_week Points | diff |
|---|---:|---:|---:|
| shmuel256 (higher seed) | 194.76 | 189.76 | **+5.00** ✓ |
| plehv79 (higher seed) | 151.28 | 146.28 | **+5.00** ✓ |
| LWebs53 (lower seed) | 170.32 | 170.32 | 0.00 ✓ |
| Oliverwkw (lower seed) | 155.40 | 155.40 | 0.00 ✓ |

The +5 lands on **Week 15** (the 2020 Semifinal) for exactly the two higher
seeds, +0 for the two lower seeds — i.e. the bonus is NOT mis-applied to a
hard-coded Week 16. The DATA behind the C/D tooltip fix is itself correct.

### Record / Win % / Regular-season win % use the correct 2020 denominators — CLEAN (data-verified)
COMPUTED counterpart of the Round-8 C/D `Win %` / `Record` tooltip fixes:
- **`Record`** sums to **16** for every 2020 team (e.g. AceMatthew 6-10,
  BROsenzweig 8-8, shmuel256 12-4, stevenb123 3-13) vs **17** for every
  2021-2025 team — the 16-game 2020 season is reflected, not a hard-coded 17.
- **`Win %`** = W / (season games): shmuel256 2020 = 12/16 = 0.7500 ✓ (a
  hard-coded /17 would give 0.7059).
- **`Regular season record`** sums to **14** for 2020 (e.g. shmuel256 10-4,
  JacobRosenzweig 4-10) vs **15** for 2021+, and **`Regular season win %`** uses
  the per-season denominator: 2020 = W/14 (AceMatthew 5/14 = 0.3571 ✓),
  2021 = W/15 (0.4000 ✓). No hard-coded 15-game regular season bleeds into 2020.

### Week of playoff elimination respects the 14-week 2020 regular season — CLEAN (data-verified)
Per-season max non-zero elimination week: **2020 = 13**, 2021 = 15, 2022 = 14,
2023 = 14, 2024 = 15, 2025 = 14. **0 of the 8 2020 rows carry an elimination
week > 14** (the 2020 regular season's last week). 2020 non-bracket teams are
eliminated weeks 11-13 (stevenb123 11, AceMatthew/JacobRosenzweig 12,
BROsenzweig 13), bracket teams (shmuel256 Champion / Oliverwkw 2nd / LWebs53 3rd
/ plehv79 4th) carry the `0` sentinel. The week-15 elimination value appears
ONLY for the 15-week 2021/2024 seasons — it does not leak into 2020.

### Latent `min(17,…)` trade-week clamps — present but never mis-bucket 2020 data
Two defensive clamps exist that would *cap* a computed week at 17 rather than the
season's true 16 for 2020 — `lotg.py` line 6362 (`_trade_week_for_date`) and
`espn_2020.py` line 657 (`_calendar_trade_wk`). I checked whether any 2020 trade
actually reaches the clamp boundary: the **latest 2020 trade is dated 2020-12-16,
which buckets to Week 15** — every one of the 24 2020 trade rows buckets to a
week ≤ 15, comfortably inside the 16-week season. The clamp therefore **never
fires for any real 2020 datum** (no 2020 trade is dated in a would-be Week 16/17),
so it produces no incorrect value. (The 2020 ESPN add/drop transactions use the
real ESPN `scoringPeriod` directly — `espn_2020.py` line 623 — with no clamp.)
The latent clamp is cosmetically loose (`min(17)` rather than season-aware) but
is **not a data defect**: it is unreachable for 2020 in the actual ledger and
correct for 2021+. Noted, not changed (no minimal targeted fix would alter any
exported cell; changing it would be speculative refactoring with zero data
impact).

### Calendar anchors (`_championship_monday`, `excluded` week) — intentionally fixed, not season-bracket — CLEAN
- `_championship_monday` (`lotg.py` 8004-8008, `week1_sunday + 16 weeks + 1 day`)
  is a fixed NFL-week-17-Monday KTC checkpoint applied uniformly to every season
  INCLUDING 2020 — it is the calendar anchor the code intends (re-confirmed in
  Round-8 C/D as accurately described by its tooltip), NOT the league's bracket
  Final week, so it is correct as a uniform anchor.
- `excluded = 18 if season >= 2021 else 17` (`lotg.py` 2974) — the
  "last-played-week excluding the championship week" helper correctly excludes a
  *later* week for 2020 (17) than for 2021+ (18) — i.e. it IS season-aware, the
  right direction (2020's empty weeks 17-18 are excluded).

---

## Part E — Domain-bounds & plausibility sweep (every numeric/categorical column, every sheet)

Scanned all 12 data sheets (league_all_time / league_week / league_year / picks /
player_all_time / player_week / player_year / team_all_time / team_week /
team_year / trades / transactions; the 13th sheet, `formulas`, is the
definitions reference). Established per-column plausible domains and scanned the
FULL column population for out-of-domain values.

### Bounded-domain columns — CLEAN
- **Ages** (genuine age columns only — `Age`, `Age when drafted`, `Player average
  age`, `Team age including picks`): `player_week.Age` [20.62, 48.37],
  `player_year.Age` [20.77, 48.37], `picks.Age when drafted` [20.89, 43.07],
  `team_week.Team age including picks` [22.19, 28.42],
  `team_week.Player average age` [23.52, 29.94], `team_year` /
  `team_all_time` / `league_year` / `league_all_time` age columns all bounded —
  **0 out of [18, 60]** across all 16 age columns on all sheets. (The ~48 top of
  range is the factually-correct retired-QB roster-holding curiosity documented
  in prior rounds — a completeness matter, not a domain violation.)
- **Week numbers** (`league_week.Week`, `player_week.Week`, `team_week.Week`):
  all in **[1, 17]**. 0 phantom week-0, 0 week>18. (2020 maxes at 16 — see the
  per-season deep dive above.)
- **Year/Season** (every season-keyed sheet): all numeric played-season values in
  **[2020, 2025]**, 0 OOB. `picks.Year`'s `startup`/`(vet)` text labels and the
  97 future-pool numeric years 2026-2028 are by-design future picks, not a span
  violation.
- **Dates** (`trades.Date` ×504, `transactions.Date` ×1,514,
  `transactions.Date dropped/traded` ×1,003, parsed): **0 dates outside
  2019-2026**, 0 impossible month/day.
- **Percentage / percentile columns** (every `%` / `percentile` / boom% / bust%
  across all sheets, excluding the by-design signed-difference columns):
  `player_year` Starter/Rostered boom%/bust% all in **[0, 100]** (0 OOB);
  all win% columns on team_all_time (`All time`, `Regular season`, `Playoff`,
  `Toilet bowl`, `All-play`, `Win % vs <each team>`, `Win % vs playoff/non-playoff/
  champions/last place`) in **[0, 1]**. The only sub-zero % is `player_week.% of
  points (if starter)` (12 rows, min −0.0417) — the documented negative-share
  case when a player scored negative fantasy points (same Garoppolo-class case as
  Round-5/6/7 E/F), bounded and explainable.
- **Count columns** (`Number of …`, `Times as …`, `Total trades`, donuts, weeks,
  streaks, `Total number of …`, `Record`, across every sheet — excluding
  explicitly-signed substrings): **0 negative counts** at full population.

### FAAB-budget plausibility — run to ground, IN-domain (NOT a defect)
A naive `[0, 100]` FAAB domain initially flagged **1** `transactions.Faab` value
(`$120`) and **6** `Total FAAB bid` values (max `$522`) as "out of range" — these
are NOT defects. The league's **FAAB budget is season-configured and well above
$100**: `season_2022/league.json settings.waiver_budget = 125`, and
**`season_2025/league.json settings.waiver_budget = 10000`** (the league moved to
a high-budget / auction-style FAAB in 2025). The flagged values are all 2025:
**Jacory Croskey-Merritt** drew a $120 winning bid against a $522 total bid pool —
trivially inside the $10,000 budget. Corroborated by 2025 team-season spends that
themselves exceed $100 (plehv79 $258, shmuel256 $109, stevenb123 $101). The
initial [0,100] bound was simply the wrong assumed domain for this league; the
values are in-domain. `Number of bids` range [1, 7] is plausible.

### Large-magnitude / sentinel scan — all legitimate aggregates
A full-population scan for any `|value| ≥ 9000` and an explicit `9999`/`99999`/
`±inf`/`-1` sentinel scan returned **0 sentinel masquerading as data** (0 inf,
0 round-number placeholders); the only large magnitudes are legitimate season/
career sums (e.g. `league_all_time.PF`, `trades.Trade impact score`), identical
in character to Round-5/6/7 E/F.

**Part E conclusion: CLEAN** — every bounded column in-domain; the only negatives
are by-design signed columns; the only near-50 ages are factually-correct
retired-QB holdings; the apparent FAAB-over-100 values are in-domain under the
real (season-configured, up to $10,000) FAAB budget; no sentinel masquerades as
data.

---

## Part F — N/A-vs-0 correctness (every conditionally-defined column, full population)

Enumerated every `_preserve_na`-governed column directly from `src/lotg.py`'s live
`_preserve_na()` (resolved against the function source, not a static copy) and
verified, for the FULL row population, that N/A renders correctly.

### Universal "N/A-not-blank-not-nan" invariant — CLEAN
Scanned EVERY column on EVERY sheet for literal `"nan"` text: **0 literal-`nan`
occurrences anywhere** (all 12 data sheets). Every conditionally-absent value
renders the true string `N/A`, never a leaked `nan`. The core Part F invariant
holds at full population.

### Bidirectional condition correctness — CLEAN (0 over- AND 0 under-broadened)
For each conditional column I re-derived condition X independently from the raw
sheet and checked BOTH failure modes (in-condition-but-not-N/A = over-narrow, and
out-of-condition-but-N/A = over-broad). NOVEL surfaces this round:

| Column / condition (re-derived) | Rows in-condition | over-narrow | over-broad |
|---|---:|---:|---:|
| `transactions.Faab` — value iff waiver & season≥2022 (389) | 389 | **0** | **0** |
| `transactions.Number of bids` — value iff waiver & season≥2021 (419) | 419 | **0** | **0** |
| `transactions.Total FAAB bid` — N/A for 2020 & 2021 waivers (no-FAAB era) | 59 | — | all N/A ✓ |
| `transactions.{Dropped avg points, Dropped total points}` vs has-`Player Dropped` (352 no-drop) | 352 | **0** | **0** |
| `transactions.Length of tenure on team` vs has-`Player Added` (439 no-add) | 439 | **0** | **0** |
| `transactions.O-Score` — KTC-independent, computes offline | 1,514 | 1,075 N/A / 439 real | (correct) |
| `trades.O-Score` / `picks.O-Score` — KTC-dependent, offline | 504 / 450 | — | all N/A ✓ |
| `player_week` all 5 `(if starter)` cols vs `Starter` (7,531) | 7,531 | **0** | **0** |
| `player_week.Difference from worst benchable starter (if bench)` vs `Bench` (13,845) | 13,845 | **0** | **0** |
| `player_year.Points` — N/A iff no player_week presence (188) | 188 | **0** | **0** |
| `player_year.{volatility, ...}` — N/A iff `Weeks as starter` < 2 (1,010) | 1,010 | **0** | **0** |
| `player_year.PPG starter` — N/A iff `Weeks as starter` < 1 (798) | 798 | **0** | **0** |
| `picks.Length of tenure on team` — N/A iff unmade pick (97 "Unknown") | 97 | **0** | **0** |
| `team_year.Amount of FAAB spent` — N/A iff Year<2022 (16) | 16 | **0** | **0** |
| `league_week.Amount of FAAB spent` — N/A iff Year<2022 (33) | 33 | **0** | **0** |
| `team_week.Amount of FAAB spent` — N/A iff Year<2022 (264) | 264 | **0** | **0** |
| `league_year.Amount of FAAB spent` — N/A iff Year<2022 (2) | 2 | **0** | **0** |
| `team_year.3-year roster retention rate` — N/A iff Year+3>2025 (24) | 24 | **0** | **0** |
| `team_year`/`team_all_time` `Drafting/Trading skill` — O-Score N/A offline | 48 / 8 | — | all N/A ✓ |
| `team_year.Transaction skill` — KTC-independent, computes | 48 | 47 real / 1 N/A | (correct) |

Notable bidirectional exactness re-confirmed at full population:
- The `(if starter)/(if bench)` player_week columns are **0/0 in both directions
  across all 21,376 player-weeks**.
- `player_year.Points` N/A count (**188**) equals EXACTLY the count of
  player_year rows whose `(Player, Year)` has zero player_week presence (the
  documented added+dropped-between-snapshots transaction-only rows) — 0 scored
  rows wrongly N/A'd, 0 weekly-present rows wrongly N/A'd.
- The 97 `picks.Length of tenure on team` = N/A rows are EXACTLY the 97 unmade
  future-pool picks (`Player Picked == "Unknown"`, Years 2026-2028) — the
  remaining 353 made picks all carry a numeric tenure. Bidirectionally exact.

### Real-0-vs-N/A (the "0 is meaningful, not N/A" direction) — CLEAN
- `transactions.Dropped total points` carries **90 genuine `0` values** — drops of
  players who never scored another NFL fantasy point after being dropped. These
  correctly render `0` (a real zero), NOT N/A; only the 352 no-drop rows are N/A.
  Confirms the `_preserve_na` comment's intent ("an explicit 0 is real").
- `transactions.O-Score` carries **439 real values** offline (KTC-independent) and
  drives `Transaction skill` (47/48 team-seasons computed), correctly distinct
  from the fully-N/A KTC-dependent `picks.O-Score`/`trades.O-Score`. The one
  `Transaction skill` = N/A team-season is the documented no-scored-O-Score case.

### 2020-specific N/A — every FAAB column correctly N/A for the no-FAAB era — CLEAN
The league had **no FAAB system pre-2022**. Verified at full population that
EVERY FAAB column is N/A for 2020 (and 2021): `team_year.Amount of FAAB spent`
2020 = `{N/A}` for all 8 teams; `league_week`/`team_week`/`league_year` pre-2022
FAAB rows are 100% N/A; all 29 2020 waiver `Number of bids` and `Faab` and all 59
2020+2021 waiver `Total FAAB bid` values are N/A — and EVERY 2022+ FAAB cell is
numeric (0 N/A). No real FAAB datum is wrongly N/A'd, and no pre-2022 cell is
fabricated to `0`.

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~73s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- **No source changes were needed (no defects in Parts E/F this round).** Build
  artifacts reverted (`git checkout -- exports/`, `git clean -fd exports/
  .cache/`); only this new file is added; `git status` otherwise clean.

## Conclusion
**Parts E + F are fully CLEAN at full population — ZERO defects.** Every
numeric/categorical column across all 13 sheets is in-domain (no out-of-range
age/week/year/date/percentage, no negative counts, no `9999`/`inf` sentinel; the
apparent FAAB-over-100 values are in-domain under the league's real
season-configured budget, up to $10,000 in 2025). Every conditionally-defined
column renders N/A correctly in BOTH directions — **0 literal-`nan`, 0
over-narrowing, 0 over-broadening** — verified column-by-column with NOVEL surfaces
(the $10,000-budget FAAB plausibility, Jacory Croskey-Merritt's $120 bid, the 90
real-zero dropped-points, the 97 "Unknown" unmade-pick tenures, the 439
KTC-independent transaction O-Scores).

The specifically-requested COMPUTED-DATA deep dive confirms **no 2020 data is
miscalculated by a hard-coded week-16/17 assumption**: the PF Semifinal +5
homefield bonus lands on Week 15 for 2020 (data-verified, +5 to exactly the two
higher seeds), Record/Win %/Regular-season win % use the correct 16-game /
14-game 2020 denominators, the playoff-elimination weeks stay ≤14 for 2020, and
every season-length-dependent column is anchored on the season's real
`playoff_week_start` rather than a constant. The two latent `min(17,…)`
trade-week clamps never fire for any real 2020 datum (the latest 2020 trade
buckets to Week 15) and so produce no incorrect value — a cosmetic looseness, not
a data defect. The Round-8 C/D tooltip fixes were pure TEXT; this round confirms
the DATA those tooltips describe was correct for 2020 all along. No source change
was required for Parts E/F this round.
