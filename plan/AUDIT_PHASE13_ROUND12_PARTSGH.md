# Phase 13 Round 12 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Self-designed full-population audit repeating the Parts G/H methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run **fresh from scratch**
against `claude/phase-13-audit-tsapoy`. Agent 4 of 5 in Round 12. Siblings this
round: Parts A/B — `AUDIT_PHASE13_ROUND12_PARTSAB.md` — CLEAN at `50a86fc`;
Parts C/D — `AUDIT_PHASE13_ROUND12_PARTSCD.md` — CLEAN at `1027ab4`; Parts E/F —
`AUDIT_PHASE13_ROUND12_PARTSEF.md` — CLEAN at `c7b912f`. Round 12 was 3-for-3
clean entering this part-pair. A prior attempt at this G+H pair lost to a session
limit with zero salvageable work (build-artifact churn only, no commit); this is
the clean redo.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` and `git merge-base --is-ancestor c7b912f HEAD` printed
`NOT_ANCESTOR` (`c7b912f` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`c7b912f`, the Round-12 Parts E/F tip
carrying all Round-5..Round-12/EF fixes including the Round-11 G/H build-
determinism stable-sort fix `9fdbb7e`), after which `git log -1 --oneline` =
`c7b912f` and the merge-base check printed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`PYTHONPATH=src:lib python3
scripts/offline_build.py`, exit 0; only the 2 expected network-unavailable
warnings — `api.sleeper.app/v1/league/0` and `…/draft/espn_2020_draft`). Not a
stale cache. Full population: picks 450, player_all_time 649, player_year 1,859,
player_week 21,376, team_year 48, team_all_time 8, team_week 808, league_year 6,
league_week 101, league_all_time 1, trades 504, transactions 1,514. Total workbook
comments **1,892**.

`pytest tests/ -q` (run as `PYTHONPATH=src:lib python3 -m pytest`) = **15 passed /
0 failures** in ~76s, incl. the full-build `test_player_history_continuity` and
the pick/player chain-link tests.

All worked examples are NOVEL — different players/picks/teams/seasons than every
prior round. The Round-11 G/H worked example (Mike Williams) and all prior anchors
(Darius Slayton, Wayne Gallman, Giovani Bernard, Lynn Bowden, Irv Smith, Mariota,
Bridgewater, Cam Skattebo, Emeka Egbuka, Elijah Mitchell, Jermaine Burton, …) were
explicitly excluded. New surface cited: the **Mike Gesicki 23-event multi-stint
add/drop/trade chain (2020-2025)** as the round-trip / no-stale-text worked example.

**Result: CLEAN.** Zero defects found. Both Part G (link integrity) and Part H
(structural integrity) invariants hold at full population, and the build is
**deterministic** — two independent from-scratch builds are byte-identical across
all 13 CSVs (the Round-11 G/H stable-sort + full-identity-tiebreaker fix `9fdbb7e`
still holds). No source change required.

---

## Determinism re-verification (the Round-11 G/H fix still holds)

Per the prompt's structural-integrity requirement, ran two FULL fresh from-scratch
builds from identical current-HEAD (`c7b912f`) source and diffed **all 13 CSVs**:

| CSV | changed lines |
|---|---:|
| transactions, trades, picks, player_week, player_year, player_all_time, team_week, team_year, team_all_time, league_week, league_year, league_all_time, formulas | **0 each** |

**TOTAL CHANGED LINES = 0.** The previously-non-deterministic surfaces (the
position-based `#N` link refs that pick up the transactions row order, and the
per-asset `T#N` trade refs) are now stable — the Round-11 G/H stable-sort with the
`(Team, Date, Player Added, Player Dropped)` / `(Team, Date, Assets received,
Assets sent)` full-identity tiebreaker (`src/lotg.py`, commit `9fdbb7e`) holds.

---

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

### G1. Link-token universe and in-range validation (full population)

Link cells are `;`-separated token lists; each token is `#N` (→transactions row N),
`T#N` (→trades row N), or `PH#N` (→picks.csv row N) — all 1-based display rows. The
non-link sentinel is the literal `N/A` (asset never moved again / no prior event /
— in the multi-asset trade columns — a single asset's terminal within a `;`-list).

Swept every link column at FULL population from the CSVs (the xlsx renders the
trades per-asset columns as the asset NAME with the ref carried as a hyperlink, so
the ref *tokens* live in the CSV):
- transactions — 4 cols: next/prev × added-player / dropped-player (1,514 rows)
- trades — 2 cols: `Link to next/previous transaction per asset` (504 rows)
- picks — 2 cols: `Link to next/previous transaction` (450 rows)

**Result: 5,651 real link tokens checked; 0 unparseable, 0 out-of-range, 0
dangling.** No token points past its target sheet's row count (max tx=1,514,
tr=504, pk=450). The only non-token value is the `N/A` sentinel (3,281 occurrences
— whole-cell terminals plus per-asset terminals inside the multi-asset trade
`;`-lists), all legitimate chain terminals. **0 self-references** in any
transactions `#N` column (a row never links to itself).

**xlsx hyperlink layer (the actual clickable links).** Separately loaded the
workbook *with* hyperlinks and resolved **all 63,292** cell hyperlinks across every
sheet (link columns plus the player-name cross-link hyperlinks throughout
player_week/player_year/etc.): **0 malformed targets, 0 out-of-range** — every
`#'sheet'!<cell>` target lands on an existing sheet at a data row
2 ≤ row ≤ max_row.

### G2. Chronological monotonicity (no-teleport) across every chain-bearing sheet

For every datable link token, confirmed a `next` link resolves to a same-or-later
date and a `prev` link to a same-or-earlier date (resolving `#`/`T#` to the target
row's own Date; picks rows carry no own Date so their chronology is covered via the
resolved target dates in G1/G3).

- **4,692 datable cross-date checks, 0 teleports** (every next within-or-forward
  date, every prev within-or-backward date).

### G3. Round-trip / recomputation consistency of the player chain

Rebuilt the per-player name-keyed event chain (transactions add+drop + trade
received/sent player assets, sorted by date, with same-event skip) the way
`src/lotg.py::_neighbors` does (`src/lotg.py` ~15459-15498), then compared the
recomputed next/prev to the stored link cells across all 1,514 transaction rows ×
4 columns.

**152 field-level differences, 100% explained** by the stored value being a `PH#`
draft-terminal ref (the source additionally anchors a player's first/last event to
their DRAFT row in picks.csv, which the plain name-chain recomputation does not
model). **0 non-PH-explained mismatches** — wherever the stored ref is a
transaction/trade ref it matches the recomputation exactly. The PH# anchors were
all confirmed in-range in G1. (Identical count to every prior round's
recomputation — stable.)

**Worked example — Mike Gesicki (NOVEL, 23 events 2020-2025):** the chain threads
correctly through a 2020-rookie stevenb123 draft (17.05) → 2020-12-31 drop →
2021 supplemental-veteran-draft re-entry by BROsenzweig (1.04) → a dense
2022-2025 carousel of free-agent add/drops and **three** distinct trades:
`T#148`/`T#53` (the 2022-09-27 BROsenzweig↔LWebs53 Gesicki-for-Gerald-Everett
swap — both mirror rows share the same instant and pair correctly), `T#57`/`T#152`
(the 2023-06-11 reverse, Gesicki+Allen Lazard for two picks), and `T#381`/`T#32`
(the 2024-09-24 AceMatthew↔shmuel256 trade). Verified directly on the workbook:
every `next added` link lands on a same-or-later-dated row (7/7 forward, 0
teleports), the trade-event pairs mirror, the earliest event (#1302, 2020-12-31)
carries `prev dropped = PH#421` (his stevenb123 draft terminal) and `next dropped =
PH#4`, and no self-references. The chain is round-trip consistent end to end.

### G4. Comment ≡ comment invariant and pick-provenance narrative (no stale text)

- **Comment inventory (full):** 1,892 comments total. 1,099 BODY chain-comments,
  **all in column A** (649 player_all_time + 450 picks = exactly 1 per data row),
  **0 misplaced into any other column, 0 orphan header comments** (no row-1 comment
  beyond max_column).
- **Pick≡player comment equality (FULL, not sampled):** for every picks row whose
  drafted player also has a player_all_time lineage comment (**353** such rows),
  the two comment bodies are **byte-identical — 0 mismatches.**
- **Toilet-bowl 2.09 provenance (cross-checked against bracket winners):** the
  three 2.09 toilet-reward picks read "originally X's pick (toilet-bowl reward)"
  with X = the prior-season Toilet-Final winner in every case — 2024 →
  JacobRosenzweig, 2025 → Oliverwkw, 2026 → Oliverwkw — and their trade-lineage
  lines are chronologically ordered with no dangling/stale step.
- **No stale narrative text (FULL automated cross-check):** parsed every dated
  transaction/trade line out of all 1,099 body comments and confirmed each cited
  `(date, team)` resolves to an actually-existing transactions or trades row —
  **4,727 dated lines checked, 0 unmatched.** Additionally spot-traced the Mike
  Gesicki comment's every dated trade/transaction line against the current
  transactions/trades cell values: all 23 lines (`T#148`/`T#57`/`T#381` trade
  assets, the AceMatthew waiver-$6 add, the Zach-Ertz drop, etc.) match the linked
  rows verbatim — zero stale text.

### G5. Taxi-eligible row state (Part G(b))

`player_all_time` 649 data rows; the 4 named transaction-only first-year-2025
never-started players (Joe Milton, Jordan Watkins, Zavier Scott, Tanner McKee)
remain correctly `Taxi-eligible = True` (per standing correction #2 — not
re-flagged).

---

## Part H — Workbook structural integrity (full population)

### H1. Row counts match CSV exports and expectations

Every DATA sheet's xlsx `max_row` = its CSV line count (header + data), confirmed
on all 12: player_week 21,377; player_year 1,860; player_all_time 650; team_week
809; team_year 49; team_all_time 9; league_week 102; league_year 7;
league_all_time 2; transactions 1,515; trades 505; picks 451. **No truncation.**

The `formulas` reference sheet is the one intentional exception: xlsx `max_row` =
**439** vs CSV 433 — the 6 extra xlsx rows are the **section-divider header rows**
(`PLAYER SHEETS`, `TEAM SHEETS`, `LEAGUE SHEETS`, `TRANSACTIONS`, `TRADES`,
`PICKS`) the xlsx build inserts as visual group labels but the CSV dump omits. A
by-design rendering difference, not truncation. (Matches every prior round's 439.)

### H2. Auto-filter range == sheet dimension on every data sheet

For all 12 data sheets, `auto_filter.ref` exactly equals the sheet's `dimensions`
(`A1:<max_col><max_row>`) — e.g. player_week `A1:BM21377`, player_all_time
`A1:BD650`, team_all_time `A1:EG9`, transactions `A1:BD1515`, trades `A1:BQ505`,
picks `A1:AO451`. No truncated or over-extended filter ranges. The `formulas`
reference sheet has no auto-filter (by design).

### H3. Conditional-formatting ranges fully cover data, no orphans

Each data sheet that carries CF has exactly 1 rule-range, spanning row 2 (first
data row) through `max_row` on a single column: player_week `L2:L21377`,
player_year `AH2:AH1860`, player_all_time `AF2:AF650`, team_week `I2:I809`,
team_year `D2:D49`, team_all_time `B2:B9`, transactions `AH2:AH1515`, trades
`AE2:AE505`, picks `V2:V451`. Every CF range starts at row 2, ends exactly at its
sheet's `max_row`, and sits on a column ≤ `max_column` — **0 out-of-bounds, 0
truncated, 0 orphaned**. The three league sheets (league_week / league_year /
league_all_time) carry no CF (by design).

### H4. Comment count and placement internally consistent

Total **1,892** comments. Per sheet: header tooltips (row 1) and body
chain-comments (rows ≥ 2) decompose cleanly — **player_all_time** 54 header + 649
body (1 per data row); **picks** 39 header + 450 body (1 per data row); every other
sheet header tooltips only, 0 body. All 1,099 body comments sit in column A; **0
misplaced; 0 orphan headers.** Every sheet's header-tooltip count is ≤ its column
count (e.g. team_all_time 119 ≤ 137, team_year 108 ≤ 127, player_week 55 ≤ 65,
league_all_time 55 ≤ 55).

---

## Verification

- **Determinism:** two FULL fresh from-scratch builds from identical current-HEAD
  source → byte-identical across **all 13 CSVs** (`diff` → 0 changed lines on every
  one). The Round-11 G/H stable-sort determinism fix `9fdbb7e` holds.
- `pytest tests/ -q` (via `PYTHONPATH=src:lib python3 -m pytest`): **15 passed** in
  ~76s, 0 failed / 0 skipped — incl. the full-build chain-link and player-history
  continuity tests.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- Build artifacts reverted (`git checkout -- exports/`); only this findings doc is
  committed (no source change this round).

## Conclusion

**Parts G + H are CLEAN — zero defects found.** The link layer (5,651 ref tokens +
63,292 xlsx hyperlinks) is fully in-range, monotonic-in-time (4,692 datable checks,
0 teleports), round-trip consistent (152 PH#-explained diffs, 0 non-PH mismatches),
self-reference-free, and stale-text-free (4,727 dated comment lines all resolve;
the NOVEL 23-event Mike Gesicki chain verified end to end). The pick≡player comment
invariant (353 byte-identical) and toilet-bowl 2.09 provenance hold. Every
structural invariant — row counts (vs CSV, +6 by-design formula dividers),
auto-filter ranges (== dimensions on all 12), CF ranges (row2..max_row, in-column),
and comment counts/placement (1,892 total; 1,099 body all in column A; 0 orphans) —
is internally consistent at full population. The build is deterministic. No source
change required.
