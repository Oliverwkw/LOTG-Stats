# Phase 13 Round 13 — Parts E+F (domain-bounds/plausibility + N/A-vs-0 correctness)

Fresh full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_ROUND12_PARTSEF.md`, run against the freshly-built
`exports/*.csv` on branch `claude/agent-part-audits-1yy87u`. Agent 3 of 5 in
Round 13. Siblings this round landed CLEAN with 0 defects: Parts A/B (Agent 1)
and Parts C/D (Agent 2). Two cross-agent items were pre-flagged for review and
are honoured below where my sweep touches them (offline empty KTC; 2026-snapshot
cutoff at 2025).

**Build under audit:** the fresh offline build already completed by the harness
(exit 0); I audited the delivered `exports/*.csv` directly and did **not**
rebuild or modify `src/`/`exports/` (per task). HEAD `8b94b0c`. Full population
this round: picks **514** (incl. 161 future-pool rows Year 2026-2030), trades
504, transactions 1,510, player_all_time 649, player_year 1,859, player_week
21,376, team_year 48, team_all_time 8, team_week 808, league_year 6,
league_week 101, league_all_time 1. CSV column counts are larger than the
Round-12 xlsx-sheet counts because the CSV exports carry the full column set
(picks 41, trades 44, tx 56, tw 112, ty 138, tat 148, lw 66, ly 69, pw 92,
py 69, pat 63). Note picks grew 450→514 vs Round-12 (future-pick pool now
present); transactions 1,514→1,510 — population drift, not a shape regression.

**N/A marker note:** in the CSV exports the undefined/"N/A" value renders as the
**empty string** (`''`) — there are **0** literal `N/A` strings across all 12
CSVs (the xlsx uses the literal `N/A`; the CSV writes NaN as empty). All Part F
work below therefore treats empty-string as the N/A marker and a literal `0`/`0.0`
as a real defined zero.

All examples are NOVEL vs Round-12 where the underlying set allowed it.

**Result: CLEAN — 0 confirmed defects.** Every numeric/derived column is
in-domain and internally consistent (Part E), and every conditionally-defined
column renders N/A correctly in BOTH directions (0 over-narrow, 0 over-broad)
at full population (Part F). Several anomalies were flagged and run to ground
(all by-design/known-offline or documentation-nuance); two are surfaced as
needs-human-judgment. No source change required.

---

## Part E — Domain-bounds & plausibility sweep (every numeric/derived column)

### Sentinel / nan / inf scan — CLEAN
Full-population literal scan for `nan`/`inf`/`-inf`/`infinity` (case-insensitive)
across all 12 data sheets → **0**. Sentinel scan for `9999`/`99999`/`-9999`
(and `.0` variants) in every column → **0**. No sentinel masquerades as data.

### Bounded-domain columns — CLEAN
- **[0,1] columns** (every `win %`/`win rate`/`efficiency`/`…rate`/
  `retention rate`/`% of starts made while rostered`, excluding by-design signed
  `minus`/`change`/`difference`/`variance`/`differential`/`net`/`luck`): **0 OOB**.
  NOVEL traces — `team_year.Win %` [0.176, 0.824], `team_all_time.All-play win %`
  [0.348, 0.577], `picks.% of starts made while rostered by drafting team`
  [0.000, 1.000], `player_all_time.% of starts` [0.000, 1.000].
- **[0,100] percentile / boom% / bust% / quartile** (every such column, streaks
  excluded): **0 OOB**. NOVEL — `player_all_time.Rostered boom %` [0, 33.3],
  `team_week.% of starters middle 50%` [0, 100], `transactions.FAAB premium %`
  [0, 100] (n=87).
- **Efficiency = PF/MaxPF ≤ 1** on all 6 team/league sheets: `team_week`
  [0.3278, 1.0000], `team_year` [0.7527, 0.8718], `league_week` [0.6966, 0.9024]
  — **0 over-1**.
- **Ages** [18, 60] (16 true age columns): **0 OOB**. NOVEL full ranges —
  `picks.Age when drafted` [20.89, 43.07], `team_week.Player average age`
  [23.52, 29.94]. `player_week.Age`/`player_year.Age` top **48.37** is the
  factually-correct retired-QB roster-hold curiosity (documented prior rounds).
- **Week numbers** all in **[1, 17]** (team_week/player_week/league_week), 0 phantom.
- **Year/Season**: every season-keyed sheet (league/team/player _week/_year,
  trades.Season, transactions.Season) is strictly **{2020…2025}** — 0 values
  ≥2026 (2026-snapshot cutoff honoured). `picks.Year` carries `2026-2030`
  future-pool slots + text `startup`/`2021 (vet)` by design (not season-keyed).

### Count columns — CLEAN
Strict non-negative true-count scan (`number of`/`times as`/`weeks …`/`bids`/
`donut`/`drops`/`trades`/`appearances`/`starts before`/`weeks before`/
`length of tenure` … excluding avg/ppg/diff/skill/score/streak/rate/%/value/
adjusted/points/turnover): **0 negative true-counts** at full population.
`trades.Number of teams involved` ∈ exactly **{2, 3}**.

### Negatives run to ground — all by-design signed
Every column carrying a negative was classified against its tooltip vocabulary;
**0 unexplained** negatives. Verified directly:
- **Negative share of points backed by negative points**: `player_week.% of
  points (if starter)` has 12 negative rows, **all 12** have `Points < 0`;
  `% of team points on team this season` 1 negative row has `Points < 0`;
  `% of team points on team` 0 negatives. 0 negative-share rows with Points ≥ 0.
- **Negative single-week ceilings** (`player_all_time.Rostered scoring ceiling`
  < 0): only **Clayton Tune −0.88, Jake Fromm −0.80, Max Brosmer −3.06, Richie
  James −0.10, Roman Wilson −0.60**. Four are single-rostered-week players
  (ceiling==floor). NOVEL run-down: **Roman Wilson** has **18** rostered weeks
  yet ceiling==floor==−0.6 — verified against `player_week`: 17 of those weeks
  were **injury/bye** (2024 rookie IR, all `Points 0`, excluded from the scoring
  distribution) and his **only played week** was 2025 W9 (−0.6). Correct, not a bug.

### Internal logical-constraint checks — CLEAN
- **Max PF ≥ PF/Points** on all 6 team/league sheets: **0** violations (808
  team-weeks, 48 team-seasons, 8 all-time, etc.).
- **Weeks as starter ≤ Weeks rostered** and **starter+bench == rostered** on
  `player_all_time` (649) and `player_year` (1,859): **0** violations each.
- **Win? ↔ PF vs Points-against** across all **808** team-weeks: 0 rows with
  `Win?=True & PF<PA`, 0 with `Win?=False & PF>PA`, 0 `PF==PA` ties.
- **Record ↔ Win %** (`team_year`): all **48** — `wins/(wins+losses)` == `Win %`
  to 3dp, **0** mismatches.
- **One Champion per year**: every season 2020-2025 has exactly one `Champion`
  and 8 distinct placements — 0 duplicate/missing.
- **team_all_time.Playoff win %** in [0, 1], empty/N/A only for
  **JacobRosenzweig** (0 playoff appearances) — consistent with his 0-0 playoff
  record.
- **Plausibility of extremes**: `player_week.Points` [−5.32 (Davis Mills 2021 W4)
  … 57.9 (Tyreek Hill 2020 W12)]; `team_week.PF` [45.36 … 231.6]; `team_year.Luck`
  [−3.81, 3.95]; `3-year roster retention rate` [0, 0.3158]; `transactions.Net
  points` max **1661.9** (Jalen Hurts, stevenb123, 2020 rookie waiver held 6 yrs —
  ~277/yr, legitimate); `trades.Net points` [−250.6 … +1026.98] (Allen Robinson +
  the pick that became A. St. Brown). All realistic dynasty outcomes.

**Part E conclusion:** every bounded column is in-domain; every negative is a
by-design signed column traced to its tooltip (incl. NOVEL negative-share and
the 18-week-rostered/1-week-played Roman Wilson ceiling); all internal logical
constraints hold at full population; no sentinel/nan/inf; no 2026 leak. **CLEAN.**

---

## Part F — N/A-vs-0 correctness (every conditionally-defined column)

Read every sheet as raw strings. Enumerated **133** numeric columns where empty
(N/A) and a real `0` coexist (the distinction is live) and re-derived the gate
for each targeted NOVEL family independently, checking BOTH failure modes.

### player_week change family — CLEAN (exact set-identity gate)
Re-derived `Change from previous week` as **defined iff (current week active AND
a prior active week exists)**, where active = NOT injury/suspension/bye. Compared
the derived N/A set against the export by row identity: **0 mismatches over
21,376 rows** (all 5,115 non-active rows N/A; 600 first-active-week active rows
N/A; every value-bearing row correct). Value cross-check: 188 real-0s are weeks
whose points equal the prior active week's (NOVEL real-0: **AJ Barner 2025 W15**).
The other three change columns render sensibly: `Change from previous 5 weeks
avg` (empty 7,750 / real-0 11), `Change from career average to that point`
(5,715 / 21), `Change from overall career average` (5,115 / 61).

### player_year `Change in points from previous season` — CLEAN (matches source exactly)
The source (`src/lotg.py` 13159) is a plain
`groupby("Player ID")["Points (full season)"].diff()` — N/A **only** on the first
player_year row per player, NOT gated on full-season==0. I re-derived the native-
order groupby-diff and compared to the export: **0 value mismatches over 1,210
defined rows and 0 N/A-set mismatches**. The column is exactly correct per source.
Real-0s (same full-season two consecutive appearing seasons) render `0`, NOT N/A:
NOVEL **Christian Watson 2024, Jordan Travis 2025, Foster Moreau 2022**.

> Documentation nuance (see needs-judgment #2): my initial naive "N/A iff current
> OR prior full-season==0" gate produced 91 apparent mismatches — all are the
> **correct** plain-diff behaviour (e.g. **Drew Brees 2024** full-season 0, prior
> appearing season 2020 fs 225.94 → export `-225.94`, spanning a multi-year
> roster-hold gap). The Round-12 template's prose called such fs==0 rows "correctly
> N/A", but the actual source emits a value; the current export is right per source.

### picks Weeks-before-first-start / Number-of-starts-before-next-transaction — CLEAN
- `Weeks before first start`: N/A iff the drafted player never started
  (`% of starts made while rostered` 0 or N/A) — **0 mismatches** over 514 picks
  (283 N/A). The 85 real-0s are vets who started their first roster week (NOVEL:
  **Najee Harris, Kyle Pitts**).
- `Number of starts before next transaction` N/A set (161) is **exactly aligned**
  with `Length of tenure on team` N/A (0 XOR) — the documented unmade-pick gate.

### trades received/sent PPG + Difference of averages — CLEAN
`Difference of averages` is N/A iff BOTH `Avg PPG of received players on team`
AND `Avg PPG of sent players over same time` are N/A — **0 mismatches** over 504
trades (49 N/A). 4 real-0 differences render `0`, distinct from N/A.

### transactions FAAB-difference-over-second-place — CLEAN (no-runner-up N/A correct)
Among the **122** rows with `Number of bids ≥ 2`, **15** show N/A. Confirmed NOT
defects: the source pools only competing bids `≤ winner_bid`; when the winning bid
sat below the other pooled bids there is no qualifying runner-up → correctly N/A
(NOVEL: **Allen Lazard 2024** won 8 vs total-bid 19, **Tank Dell 2023** won 6 vs
28 w/ 3 bids, **Jared Wiley 2024** won 1 vs 37 w/ 5 bids, **Oronde Gadsden 2025**,
**KeAndre Lambert-Smith 2025**). Both-direction structural check: **0** rows carry
a value with `< 2` bids. The 32 real-0s are top-bid ties won on priority (NOVEL:
**Tez Johnson, Tyler Johnson 2024**).

### transactions Average-PPG / Length-of-tenure / Dropped-points — CLEAN (real-0s)
- `Average PPG on team`: **0 value-with-no-add**; 25 real-0s are adds who logged
  real team weeks averaging exactly 0 (NOVEL: **Tyler Lockett, Tre Tucker, Chig
  Okonkwo**).
- `Length of tenure on team`: **0** value-without-add; 71 real-0s are same-day
  add-and-drop pairs.
- `Dropped total points`: **0** value-without-drop; 83 real-0s (dropped a player
  who scored 0 after the drop).

### FAAB pre-2022 (pre-Sleeper) N/A era — CLEAN + NOVEL Sleeper-waiver seam
- `Amount of FAAB spent`: **N/A for every 2020 and 2021 row** across all four
  sheets (team_year 8+8, league_year 1+1, team_week 128+136, league_week 16+17),
  populated 2022+. `transactions.Faab`/`Total FAAB bid`: **all 2020 (206) and
  all 2021 (236) empty**, populated 2022+.
- **NOVEL — 2021 Sleeper-waiver-no-FAAB seam:** in 2021, `Number of bids` is
  populated for **exactly the 30 waiver transactions** (mostly 1, two are 2) while
  all 199 free-agent + 7 commissioner rows are N/A, and every 2021 `Faab` is N/A.
  This is consistent, not a defect: the league was on Sleeper in 2021 (waiver-
  claim counts recoverable) but had **no FAAB budget** until 2022. 2020 (ESPN)
  correctly has both `Number of bids` and `Faab` N/A for all 206 rows.

### Other live gates re-verified bidirectionally — CLEAN
| Column / re-derived gate | over-narrow | over-broad |
|---|---:|---:|
| `team_week.Starter/Roster turnover from previous week` — N/A iff **league** first week (exactly the 8 rows at **2020 Week 1**; later season-openers carry a real cross-season value) | **0** | **0** |
| `team_year.Change in win % from previous season` — empty set is **exactly** the 8 first-season (2020) rows per team; 5 real-0s | **0** | **0** |
| `team_year.Win Variance` — populated for all 6 seasons 2020-2025 (no 2026 season exists to gate; cutoff honoured) | — | — |
| `player_all_time.Points` — empty iff 0 rostered weeks; 0 rows empty-with-rostered>0, 0 real-0-with-rostered==0 | **0** | **0** |
| KTC columns (picks/trades/transactions, 32 cols) — 100% empty offline; **0** fake `0` leaked (over-broad N/A→0) | **0** | **0** |

**Part F conclusion:** every conditionally-defined column renders N/A correctly in
BOTH directions at full population — **0 over-narrow, 0 over-broad** — including
the exact player_week active-week change gate, the player_year plain full-season
diff (verified against source), the trades dual-side difference gate, the FAAB
no-qualifying-runner-up N/A, the 2020/2021 pre-Sleeper FAAB era, the 2021
Sleeper-waiver `Number of bids` seam, and the league-first-week-only turnover
mask. **CLEAN.**

---

## Anomalies flagged (over-inclusive) — three categories

### (a) CONFIRMED DEFECTS — none.

### (b) LIKELY BY-DESIGN / DOCUMENTED / KNOWN-OFFLINE
1. **All KTC columns 100% empty** (picks 13, trades 5, transactions 14). Known
   offline condition — KTC index build fails offline (network 403) and the
   on-disk `data/ktc_backfill/` is not merged in the offline harness (cross-agent
   item i). No fake-0 leaked; every KTC cell is the empty/N/A marker.
2. **O-Score populated ONLY on the 439 pure-drop transactions** (range 6.5-43.8,
   ceiling 50); `picks.O-Score` and `trades.O-Score` and every non-pure-drop
   `transactions.O-Score` are empty. Consistent with the O-Score contract
   (`src/lotg.py` 17546: "N/A unless all four components present", KTC required &
   missing offline) PLUS the documented pure-drop path (17699 `_mr.fillna(0.0)`
   fills KTC=0). Honours its own N/A contract — no inconsistency across sheets.
3. **Drafting skill & Trading skill 100% empty; Transaction skill populated**
   (team_year 47/48, team_all_time 8/8). Direct downstream of #2: pick/trade
   O-Scores are all N/A (KTC required) → their shrunk-mean skills are N/A; only
   the pure-drop-fed Transaction skill can compute. Consistent, not a defect.
4. **Age up to 48.37** (`player_week`/`player_year`, retired-QB roster-hold) —
   documented completeness curiosity, in-domain.
5. **5 negative Rostered scoring ceilings** incl. **Roman Wilson −0.6 with 18
   rostered weeks** — verified single *played* week (17 injury/bye weeks excluded);
   ceiling==floor by construction. Plausible.
6. **2021 `Number of bids` populated on 30 waiver rows while all 2021 FAAB is
   N/A** — Sleeper-waiver-no-FAAB era; free-agent/commissioner rows correctly N/A.
7. **`player_year.Change in points from previous season` across multi-year
   roster-hold gaps** (Drew Brees 2024 = −225.94 from 2020) — plain full-season
   `groupby.diff()`; "previous season" = previous appearing season. Matches source
   exactly (0 mismatches). Documented gap-year semantics.
8. **Large Net-points extremes** (Jalen Hurts 1661.9; trades +1026.98 / −250.6) —
   legitimate long-tenure / franchise-asset values.

### (c) NEEDS-HUMAN-JUDGMENT
1. **Offline Transaction skill is a partial/degraded signal.** Because every
   *add* O-Score is N/A offline (KTC missing), the populated `Transaction skill`
   (team_year/team_all_time) is computed from **drop-only** O-Scores. It renders
   as a normal-looking value (e.g. 28.3-34.4 all-time) even though it omits all
   add-transaction quality that an online build would include. Not a source
   defect (the shrunk mean correctly drops N/A O-Scores), but a human should be
   aware the offline skill column silently reflects only drops.
2. **Round-12 template mischaracterised the change-in-points gate.** The Round-12
   Parts E/F write-up describes `Change in points from previous season` as "N/A
   iff current OR prior full-season==0"; the actual source is a plain
   `groupby.diff()` that emits a **value** (not N/A) for fs==0 rows (Drew Brees
   2024 → −225.94 spanning 2020→2024). The current export is correct **per
   source**; surfacing so a human can confirm the fs==0 roster-hold rows producing
   large year-over-year swings are intended (they faithfully implement the code).

---

## Verification
- **No rebuild** performed (task: audit the fresh `exports/*.csv` as delivered;
  do not rebuild/modify src/exports). Determinism/pytest not re-run for that
  reason; all findings are direct pandas re-derivations against the delivered CSVs.
- Sentinel/nan/inf: **0**. 2026 leak in season-keyed sheets: **0**. Literal `N/A`
  strings in CSVs: **0** (empty-string is the universal N/A marker).
- Part E logical constraints re-derived at full population (Max PF≥PF, starter+
  bench==rostered, Win?↔PF/PA on 808, Record↔Win% on 48, one-Champion-per-year).
- Part F gates re-derived independently with 0 mismatches on the player_week
  active-week change family (21,376), player_year full-season diff (1,210 defined),
  picks weeks-before-first-start (514), trades difference-of-averages (504), and
  the turnover / change-in-win% / FAAB-era masks.

## Conclusion
**Parts E + F are CLEAN — 0 confirmed defects.** Every numeric/derived column is
in-domain and internally consistent; every conditionally-defined column renders
N/A correctly in both directions at full population. Eight anomalies were flagged
and resolved as by-design/known-offline; two are surfaced for human judgment (the
offline drops-only Transaction skill, and a Round-12 template gate mischaracter-
isation that does not affect current-export correctness). No source change required.
