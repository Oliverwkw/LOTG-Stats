# Phase 13 Round 12 — Parts E+F (domain-bounds/plausibility + N/A-vs-0 correctness)

Self-designed full-population audit repeating the Parts E/F methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 3 of 5 in Round 12. Siblings this round:
Parts A/B — `AUDIT_PHASE13_ROUND12_PARTSAB.md` — landed CLEAN at `50a86fc`;
Parts C/D — `AUDIT_PHASE13_ROUND12_PARTSCD.md` — landed CLEAN at `1027ab4`.
Round 11 was not clean across all 5 part-pairs (C/D 2 tooltip fixes, E/F 1
computational fix `9b6719f`, G/H 1 build-determinism fix `9fdbb7e`), so the
repeating-cycle rule advanced the audit to Round 12 (a fresh full repeat).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `git merge-base --is-ancestor 1027ab4 HEAD`
printed STALE — `1027ab4` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`1027ab4`, the Round-12 Parts C/D tip,
carrying all Round-5..Round-12/CD fixes including the Round-11 E/F
date-string-compare fix and the Round-11 G/H build-determinism fix), then
confirmed `OK_AT_OR_AHEAD` with `git log -1 --oneline` showing `1027ab4`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
player_all_time 649, player_year 1,859, player_week 21,376, team_year 48,
team_all_time 8, team_week 808, trades 504, transactions 1,514, league_year 6,
league_week 101, league_all_time 1, formulas 432. (Cols: tw 101, ty 127,
tat 137, lw 59, ly 62, pw 65, py 62, pat 56, picks 41, trades 41, tx 56 — the
same stable shapes as Rounds 6-12.)

All examples below are NOVEL — different players/teams/picks/seasons/stats than
every prior round (Rounds 4-12 exclusion lists honoured). This round deliberately
targeted N/A-vs-0 families NOT deeply re-derived by recent E/F rounds — the
**player_week change family** (`Change from previous week / previous 5 weeks avg /
career average to that point / overall career average`), the **player_year
change-in-points-from-previous-season full-season gate**, the **trades received/
sent PPG + Difference-of-averages gate**, the **picks Weeks-before-first-start /
Number-of-starts-before-next-transaction gates**, the **transactions FAAB
difference-over-second-place no-qualifying-runner-up N/A**, and the
**Average-PPG-on-team / Length-of-tenure / Dropped-points real-0s** — steering
clear of the now-exhausted streak family, the (if starter)/(if bench) family, the
adjusted-played-week gates, the Win%-vs-opponent / Result / Taxi-eligible /
Weeks-between-pickup-and-start surfaces, and the 2020-vs-2021 draft seam.

**Result: CLEAN.** Zero defects found. Every numeric/derived column is in-domain
and internally consistent (Part E), and every conditionally-defined column renders
N/A correctly in BOTH directions (0 over-narrow, 0 over-broad) at full population
(Part F). No source change required.

---

## Note on the committed `exports/` (stale, NOT a regression) — verified deterministic

The committed `exports/transactions.csv`, `trades.csv`, and `picks.csv` were last
regenerated at commit `afa5686` (Round-11 Parts C/D). The Round-11 E/F fix
(`9b6719f`, the `Weeks between pickup and start` date-string compare) and the
Round-11 G/H determinism fix (`9fdbb7e`) both modified `src/lotg.py` but committed
**source only** and reverted their `exports/` artifacts. So a fresh build legitimately
differs from the committed CSVs — e.g. **Irv Smith / AceMatthew 2022-09-21** shows
`Weeks between pickup and start = N/A` in the committed (pre-fix) CSV but the
correct `0` in a fresh build, exactly the Round-11 E/F fix propagating. This is
the **expected** source-vs-stale-export gap, NOT non-determinism.

To honour the prompt's "if you ever see export differences across identical-source
rebuilds, that itself is a regression worth investigating" directive, I ran the
determinism check directly: **two FULL fresh builds from the identical current HEAD
source produced byte-identical `transactions.csv`, `trades.csv`, and `picks.csv`**
(`diff -q` → IDENTICAL on all three, including the tied-timestamp `#N` link
renumbering that the Round-11 G/H fix stabilised). The build is deterministic; the
Round-11 G/H fix holds. I audited against the fresh (correct) build and, per the
sibling-round convention, leave the committed `exports/` untouched (no source
change this round to regenerate from).

---

## Part E — Domain-bounds & plausibility sweep (every numeric/derived column)

Scanned all 12 data sheets at full population. Established per-column plausible
domains + internal logical constraints.

### Sentinel / nan / inf scan — CLEAN
Full-population literal scan for `nan`/`inf`/`-inf`/`infinity` across all 12 data
sheets → **0**. Sentinel scan for `9999`/`99999`/`-9999` in every numeric column
→ **0**. No sentinel masquerades as data; every conditionally-absent value is the
true string `N/A`.

### Bounded-domain columns — CLEAN
- **Win % / rate / efficiency** (every `win %`/`win rate`/`efficiency`/`…rate`
  column, excluding by-design signed `minus`/`change`/`difference`/`variance`/
  `differential`/`vs`/`net` columns and `retention`): **0 out of [0, 1]**.
- **Percentile / boom % / bust %** (every `percentile`/`boom`/`bust`): **0 out of
  [0, 100]**. NOVEL ranges traced in `player_year`: `Floor percentile`
  [1.40, 100.00], `Ceiling percentile` [1.40, 100.00], `Consistency percentile`
  [1.70, 100.00], `Rostered floor percentile` [0.80, 100.00] — all in-bounds.
- **FAAB premium %** (`transactions`): n=87, range [0.0, 100.0], 0 OOB.
- **Ages** (16 true age columns across all sheets; substring false positives
  excluded): **0 out of [18, 60]**. NOVEL full ranges — `team_week.Player average
  age` [23.52, 29.94], `team_year.Player average age` [23.85, 29.82],
  `league_year.Team age including picks` [24.02, 24.50], `picks.Age when drafted`
  [20.89, 43.07], `player_week.Age` [20.62, 48.37] (the ~48 top is the
  factually-correct retired-QB roster-hold documented in prior rounds — a
  completeness curiosity, not a domain violation).
- **Week numbers** (`league_week`/`player_week`/`team_week`): all in **[1, 17]**,
  0 phantom week-0 / week>17.
- **Year/Season**: every season-keyed sheet's numeric values in **[2020, 2025]**;
  `picks.Year` numeric span **[2021, 2028]** (future-pool picks) plus the text
  labels `startup` / `2021 (vet)` — all by design.

### Count columns — CLEAN
- Strict true-count scan (`number of`/`times as`/`total number`/`weeks as`/`bids`/
  `donut`, excluding avg/ppg/diff/skill/score/streak/margin/luck/net/change/rate/
  %/value/adjusted/points): **0 negative true-counts** at full population.
- NOVEL donut/threshold-count ranges, all non-negative: `team_week.Number of
  donuts` [0, 18], `team_week.Number of players under 10` [5, 29],
  `team_week.Number of starters over 20` [0, 7], `team_year.Number of donuts`
  [40, 186], `team_year.Number of players over 30` [3, 20] — all plausible.
- `trades.Number of teams involved` ∈ exactly **{2, 3}** (0 impossible 1-team or
  4-team trade).
- `transactions.% of starts made while rostered` and its `Injury adjusted`
  variant both in **[0, 1]** (n=1514 each, 0 OOB).

### Negatives run to ground — all by-design signed, NOT defects
A full sweep enumerated every column carrying any negative numeric value and
classified each against its tooltip vocabulary (`minus`/`change`/`difference`/
`variance`/`differential`/`net`/`margin`/`par`/`floor`/`ceiling`/`points`/`ppg`/
`avg`/`score`/`% of`/`o-score`/`tanking`/`addition value`/`age difference`):
**0 UNEXPLAINED negative columns** — every negative is a legitimately-signed
column. Verified directly:
- **Negative-share**: all **12** `player_week.% of points (if starter)` negative
  rows have **Points < 0** (NOVEL: Bhayshul Tuten 2025 W14 −2.50, Chimere Dike
  2025 W13 −0.10, Chris Olave 2024 W6 −0.50, J.J. McCarthy 2025 W12 −0.52, Cam
  Newton 2020 W7 −0.18, Chase Claypool 2020 W7 −1.20). A negative-scoring start
  yields a negative share of team points — bounded and explained.
- **Negative single-week ceilings**: `player_all_time.Rostered scoring ceiling`
  < 0 only for **Clayton Tune −0.88, Jake Fromm −0.80, Max Brosmer −3.06, Richie
  James −0.10, Roman Wilson −0.60** — each a single-rostered-week player whose
  only week was negative (ceiling==floor). Tooltip allows negatives.
- `transactions.Points Added` has exactly **1** negative (Jerick McKinnon,
  2020-09-23, −0.1) — a single negative-scoring started week; legitimate.
- `team_year.Differential` [−516.88, +592.32] and `Avg differential`
  [−30.40, +34.84] — signed PF-minus-PA composites; legitimately signed.

### Internal logical-constraint checks — CLEAN (NOVEL traces)
- **Win? reconciles with PF vs Points against**: across all **808** team-weeks,
  **0** rows with `Win?=True & PF<PA`, **0** with `Win?=False & PF>PA`, **0**
  `PF==PA` ties — no impossible win/loss-vs-score combination anywhere.
- **Record reconciles with Win %** (`team_year`): all **48** team-seasons —
  `wins/(wins+losses)` == `Win %` to 3dp, **0** mismatches.
- **Result structural distinctness**: every season 2020-2025 carries exactly one
  of `{Champion, 2nd, 3rd, 4th, 5th, 6th, 7th, 8th}` — 0 duplicate/missing places,
  exactly **1 Champion per year** (no impossible double-champion).
- **Champion re-derived from the bracket Final game** (NOVEL full trace): per
  season the `team_week` `Week Name = Final` winner (by `Win?`) is the Champion —
  2020 shmuel256 (Win?=True, 143.9 vs Oliverwkw 118.1), 2021 stevenb123 (162.0
  vs LWebs53 157.72), 2022 LWebs53 (117.88 vs stevenb123 112.06), 2023 LWebs53
  (147.78 vs plehv79 141.34), 2024 stevenb123 (181.38 vs shmuel256 173.38), 2025
  shmuel256 (164.7 vs AceMatthew 141.54) — all 6 match the `Result` Champion.
- **Championship-appearances consistency**: `team_all_time.Number of championship
  appearances` == per-team count of `Result ∈ {Champion, 2nd}` (finalists) for
  all 8 managers (AceMatthew 1, BROsenzweig 0, JacobRosenzweig 0, LWebs53 3,
  Oliverwkw 1, plehv79 1, shmuel256 3, stevenb123 3) — **0** mismatches.
- **Week of playoff elimination ↔ bracket membership**: every season carries
  exactly **4 zeros** (the Champion/2nd/3rd/4th bracket "made-it" sentinel) +
  **4 real elimination weeks** (5th-8th) — 0 anomalies (no Champion with a real
  elimination week, no 5th-8th team with a 0 sentinel) across all 6 seasons.
- **team_all_time.Playoff win %** in **[0, 1]**, N/A only for **JacobRosenzweig**
  (never reached the winners' bracket — consistent with his never being
  Champion/2nd/3rd/4th).

**Part E conclusion:** every bounded column is in-domain; every negative is a
by-design signed column traced to its tooltip (incl. the NOVEL negative-share
negative-points rows and negative single-week ceilings); all internal logical
constraints (Win?↔PF/PA on 808 team-weeks, Record↔Win% on 48 team-seasons,
one-Champion-per-year re-derived from the bracket Final, championship
appearances↔finalists, elimination week↔bracket membership) hold at full
population; no sentinel/nan/inf. **CLEAN.**

---

## Part F — N/A-vs-0 correctness (every conditionally-defined column)

Read every sheet as raw strings (`dtype=str, keep_default_na=False`) to preserve
the exact `N/A`-vs-`0` distinction. Enumerated **111 columns** where literal
`N/A` and a real numeric `0` coexist (the distinction is live) and re-derived the
gate for each NOVEL family independently, checking BOTH failure modes (real-0
silently N/A; missing-data silently 0). For the player_week change family I used a
**set-identity** re-derivation (replicating the source's exact ordered loops) so
the comparison is per-physical-row and definitive, not an order-sensitive zip.

### player_week change family — CLEAN (0/0 all four, NOVEL)
Re-derived each column's N/A set by replaying the source's ordered accumulators
(`src/lotg.py` ~10220-10259; active = NOT injury/suspension/bye; deltas span
seasons), then compared the derived N/A set against the export N/A set
**by row identity**, plus a numeric cross-check on the value-bearing rows:

| Column | derived-N/A ⊕ export-N/A | numeric mismatch |
|---|---:|---:|
| `Change from previous week` (N/A iff no prior active week; 1048 N/A) | **0** | **0** |
| `Change from previous 5 weeks avg` (N/A until 5 active weeks; 3812) | **0** | **0** |
| `Change from career average to that point` (N/A iff 0 prior active; 1048) | **0** | **0** |
| `Change from overall career average` (N/A iff player has 0 active weeks; 99) | **0** | **0** |

NOVEL real-0 (change exactly 0 because this week's points equal the prior active
week's): **AJ Barner 2025 W15 (5.7), AJ Dillon 2021 W2 (3.6), Aaron Rodgers 2023
W2/W3 (0.0)** — each a real `0` carrying a genuine prior-active comparison, NOT
leaked from N/A.

### player_year `Change in points from previous/career` — CLEAN (full-season gate)
The source (`src/lotg.py` ~12144) computes the diff on **`Points (full season)`**
(NFLverse full-season totals, not the rostered `Points`) grouped by Player ID. A
naïve rostered-`Points` `.diff()` spuriously "flagged" **156** rows as
over-broad-N/A — confirmed NOT defects: each is a season where the current OR the
comparable prior NFL season had **`Points (full season) == 0`** (the player logged
no NFL games that year), so the year-over-year change is genuinely undefined and
correctly **N/A**. Re-derived against the actual full-season values: **146** of the
156 have current-year full-season 0; the remaining **10** have a prior-year
full-season 0 (NOVEL: **A.J. Green 2022** prior-2021→2022-fs-0 retired,
**Ameer Abdullah 2024** prior player_year row 2021-fs-0, **Marcus Mariota 2022**,
**Foster Moreau 2022** — each compared against an absent/0 prior NFL season). The
export's N/A is the semantically-correct answer (a `.diff()` would emit a spurious
±156-point swing). Genuine real-0s (same full-season points across two played
years) render `0`, NOT N/A: NOVEL **Christian Watson 2024, Hendon Hooker 2025,
Josh Doctson 2022/2023**.

### trades received/sent PPG + Difference of averages — CLEAN (0/0, NOVEL)
- `Difference of averages` gate (`src/lotg.py` ~9766): N/A iff BOTH `Avg PPG of
  received players on team` AND `Avg PPG of sent players over same time` are N/A
  (no rostered NFL weeks on either side) — **0 over-broad-N/A, 0 value-should-be-
  N/A** across all 504 trades.
- Real-0s are legitimate, not leaked N/A: **Elijah Mitchell** (plehv79←Oliverwkw,
  2024-08-09) and **Jermaine Burton** (stevenb123←Oliverwkw, 2024-12-09) each
  logged real team weeks averaging exactly `0.0` PPG → `Avg PPG of received/sent
  players = 0`; the 4 `Difference of averages == 0` rows pair such a 0.0-avg
  player against a FAAB/pick-only side (empty→treated as 0.0) → 0.0−0.0 = a real
  `0`. Correct.

### picks Weeks-before-first-start / Number-of-starts-before-next-transaction — CLEAN
- `Weeks before first start`: N/A iff the drafted player never started for the
  drafting team (`% of starts made while rostered by drafting team` is 0 or N/A) —
  **0 over-broad-N/A, 0 value-when-never-started**. The **85** real-0s are
  vets who started in their very first roster week (NOVEL: **Matt Ryan**
  2021(vet) 2.05, **Jameis Winston** 2021(vet) 3.03, **Kirk Cousins**
  2021(vet) 3.05) — a real `0` (zero weeks waited), distinct from N/A.
- `Number of starts before next transaction`: N/A (97) iff the pick was **unmade**
  — exactly aligned with `Length of tenure on team` N/A (0 mismatch), the
  documented "Unknown"-pick gate; the **122** real-0s are made picks whose player
  logged 0 starts before the next roster move. Correct in both directions.

### transactions FAAB difference-over-second-place — CLEAN (no-runner-up N/A is correct)
A naïve "≥2 bids ⇒ must have a value" gate "flagged" **13** rows showing N/A
despite `Number of bids ≥ 2` — confirmed NOT defects. The source (`src/lotg.py`
~5513) filters the competing-bid pool to `b <= winner_bid_val` (bids strictly
above the winning bid belonged to OTHER players in the same waiver run); when that
leaves no qualifying runner-up, `FAAB difference over second place` / `FAAB
premium %` are genuinely undefined → correctly **N/A** (NOVEL: **Hunter Renfrow**
2025 won 0 vs total-bid 4, **Nico Collins** 2023 won 7 vs total-bid 18,
**Dont'e Thornton** 2025 won 16 vs total-bid 72 — in each the winning bid was
below the other pooled bids). Conversely **0** rows carry a value without a genuine
qualifying runner-up. The **32** real-0s are top-bid ties won on priority (NOVEL:
**Jordan Mason** 2024 won 42 w/ 4 bids diff 0, **Jaylin Lane** / **Malik
Washington** 2025) — a real `0` (won by tiebreak at an equal top bid), NOT N/A.

### transactions Average-PPG-on-team / Length-of-tenure / Dropped-points — CLEAN
- `Average PPG on team`: **25** real-0s are added players who logged real team
  weeks averaging exactly 0 (NOVEL: **Hassan Haskins, Eno Benjamin, Chig Okonkwo,
  Tre' McKitty, Tre Tucker**), distinct from the N/A no-roster-week rows.
- `Length of tenure on team`: value iff a player was added — **0 over-broad-N/A,
  0 drop-only-with-value**; the **71** real-0s are same-day add-and-drop pairs
  (NOVEL: **Marcus Mariota** 2020-12-24 16:32:21→16:33:30, **J.D. McKissic**
  2021-09-07 18:42:20→18:47:22, **Leonard Fournette** 2023-10-18
  08:52:23→16:43:38) — a real `0`-day tenure, not N/A.
- `Dropped total points`: value iff a player was dropped — **0/0**; all **90**
  genuine `0`s carry a real `Player Dropped` (dropped a player who scored 0 after
  the drop), 0 leaked from N/A.

### Other live N/A-vs-0 gates re-verified bidirectionally — CLEAN (0 over-narrow, 0 over-broad)
| Column / re-derived gate | over-narrow | over-broad |
|---|---:|---:|
| `team_week.Roster/Starter turnover from previous week` — N/A iff **league** wk1 (exactly the 8 rows at 2020 Week 1; later season-openers carry a real offseason value) | **0** | **0** |
| `team_year/week/league_week/league_year.Amount of FAAB spent` — N/A iff Year<2022 (all 4 sheets) | **0** | **0** |
| `team_year.3-year roster retention rate` — N/A iff Year+3>2025; real-0 = LWebs53 2021/2022 (0% retention) | **0** | **0** |
| `team_all_time.Playoff win %` — N/A iff never reached winners' bracket (JacobRosenzweig); real-0 distinct | — | — |

Notable subtlety correctly applied: the turnover N/A mask is **exactly** the 8
league-first-week rows (2020 Week 1), **not** every per-season opener — every
later season's Week-1 row carries a real cross-season offseason turnover value
(the column compares to the prior season's final week). A per-season-first-week
gate would spuriously expect 48 N/A; the export's 8 is the correct
league-history-first-week semantics.

**Part F conclusion:** every conditionally-defined column renders N/A correctly in
BOTH directions at full population — **0 over-narrow** (real 0s shown as N/A) and
**0 over-broad** (missing-data shown as 0) — including the subtle full-season
change-in-points gate, the trades dual-side difference gate, the FAAB
no-qualifying-runner-up N/A, and the league-first-week-only turnover mask. **CLEAN.**

---

## Verification
- Determinism: two FULL fresh builds from identical current-HEAD source →
  byte-identical `transactions.csv` / `trades.csv` / `picks.csv` (`diff -q`
  IDENTICAL on all three). The Round-11 G/H tied-timestamp-sort determinism fix
  holds. The diff vs the committed `exports/` is the expected source-vs-stale-CSV
  gap (committed at `afa5686`, before the Round-11 E/F + G/H source-only fixes).
- `pytest tests/ -q` (via `PYTHONPATH=src:lib python3 -m pytest`): **15 passed**
  in ~63s, 0 failed / 0 skipped — incl. the full-build
  `test_player_history_continuity` and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.

## Conclusion
**Parts E + F are CLEAN — zero defects found.** Every numeric/derived column is
in-domain and internally consistent (all bounded columns in [0,1]/[0,100]/[18,60]/
[1,17]/[2020,2025]; every negative a by-design signed column traced to its
tooltip; Win?↔PF/PA, Record↔Win%, one-Champion-per-year re-derived from the
bracket Final, championship-appearances↔finalists, and elimination-week↔bracket
membership all reconcile at full population; no nan/inf/sentinel). Every
conditionally-defined column renders N/A correctly in BOTH directions (0
over-narrow, 0 over-broad) — re-derived with NOVEL surfaces across the player_week
change family, the player_year full-season change-in-points gate, the trades
received/sent-PPG difference gate, the picks weeks-before-first-start /
starts-before-next-tx gates, the transactions FAAB no-runner-up N/A, and the
average-PPG / tenure / dropped-points / turnover / FAAB-spent / retention gates.
No source change required.
