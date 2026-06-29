# Phase 13 Round 10 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Self-designed full-population audit repeating the Parts G/H methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run **fresh** (a from-scratch
redo, not a continuation) against `claude/phase-13-audit-tsapoy`. Agent 4 of 5 in
Round 10 (siblings: Parts A/B — `AUDIT_PHASE13_ROUND10_PARTSAB.md` — CLEAN at
`f95d3ea`; Parts C/D — `AUDIT_PHASE13_ROUND10_PARTSCD.md` — 2 NEW-family tooltip
fixes (`Taxi-eligible` first-year gate + `Result` finish vocabulary) at `814cdb6`;
Parts E/F — `AUDIT_PHASE13_ROUND10_PARTSEF.md` — 2 computational fixes at `a683193`,
the second of which (the `Result` 5th-8th ranking-window change) was then **reverted**
in `70ebfc0`; I/J remains after this part-pair).

**Why this is a from-scratch redo.** The prior G/H attempt at this exact part-pair
was built on a codebase state that has since been corrected. Commit `a683193`
(Round 10 E/F) had "fixed" the `Result` column's 5th-8th non-playoff ranking to use
a pure regular-season window (`cutoff` = 15 pre-2025) on the reasoning that it
disagreed with `last_place_by_season`. That reasoning was **wrong**: toilet-bowl
bracket results were intentionally part of final standings for 2020-2024 by original
league/code design (the in-code comment "Determine season finishing positions
(Result) from playoff/toilet brackets when available" and the pre-existing tooltip
language both predate this audit chain). Commit `70ebfc0` reverted **just** that
ranking-window change back to the original `cutoff = 17 if season < 2025 else 15`
logic and rewrote the `Result` tooltip in `src/formulas.py` to explain that `Result`
and `last_place_by_season` are two intentionally-different metrics that can legitimately
disagree for 2021-2023. The OTHER E/F fix — the Taxi-eligible pad-row fix (4
transaction-only first-year-2025 never-started players: Joe Milton, Jordan Watkins,
Zavier Scott, Tanner McKee) — is **unchanged and still correct**; this audit verified
it but does not flag it.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed diverged; `git merge-base --is-ancestor 70ebfc0 HEAD` printed NOT_OK
(`70ebfc0` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy`, then confirmed `OK_AT_OR_AHEAD` with
`git log -1 --oneline` = `70ebfc0` ("Revert Result 5th-8th ranking window…").

**Build under audit:** fresh offline build (`PYTHONPATH=src:lib python3
scripts/offline_build.py`, exit 0; only the 2 expected network-unavailable warnings —
`api.sleeper.app/v1/league/0` and `…/draft/espn_2020_draft`). Not a stale cache.
Full population: picks 450, player_all_time 649, player_year 1,859, player_week
21,376, team_year 48, team_all_time 8, team_week 808, league_year 6, league_week
101, league_all_time 1, trades 504, transactions 1,514. Total workbook comments
**1,892**.

All worked examples below are NOVEL — different players/picks/teams/seasons than the
prior rounds' documented anchors (deliberately avoiding the prior G/H seam/anchor
names Wayne Gallman / Giovani Bernard / Lynn Bowden / Travis Fulgham / Kyle Rudolph /
Marquise Brown 1.02 / Trevor Lawrence 1.03 / Damien Harris 1.03, and the Round-10
C/D player chains Wan'Dale Robinson / James Conner / Cam Akers / James Cook). New
surfaces cited here: the **Darius Slayton 19-event multi-stint add+drop chain** as
the round-trip-symmetry worked example; the **2024 2.09 → Ja'Lynn Polk
toilet-reward provenance chain** (JacobRosenzweig origin) plus its **2025 (Oliverwkw)
and 2026 (Oliverwkw)** siblings as the toilet-bowl provenance verification surface;
the **picks A442 ≡ player_all_time A255 byte-identical-comment** invariant.

**Result: CLEAN — 0 defects found in Parts G or H.** Every link reference is
in-range, chronologically ordered, and round-trip consistent. Every workbook-structural
invariant holds against the CURRENT row counts. The reverted `Result` ranking-window
logic and its rewritten tooltip are correctly in place, no narrative/comment text
anywhere asserts the now-reverted (incorrect) "Result must agree with
last-place-by-season" claim, and the Taxi-eligible state of the 4 named players is
correct. No code change required.

`pytest tests/ -q` (run as `PYTHONPATH=src:lib python3 -m pytest`) = **15 passed /
0 failures** — unchanged from the 15/15 baseline. (Note: the bare `pytest` binary on
this image is a uv-managed interpreter without pandas; the project's own
pandas-bearing interpreter is `python3 -m pytest`, which is what the build itself
uses.)

---

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

### G1. Link-token universe and in-range validation (full population)

Link cells are `;`-separated token lists; each token is `#N` (→transactions row N),
`T#N` (→trades row N), or `PH#N` (→picks.csv row N) — all 1-based display rows
(`f"#{i+1}"` etc. in `src/lotg.py`). The sole non-link sentinel is the literal
string `N/A` (asset never moved again / no prior event).

Swept every link column at FULL population:
- transactions — 4 cols: next/prev × added-player / dropped-player (1,514 rows)
- trades — 2 cols: `Link to next/previous transaction per asset` (504 rows)
- picks — 2 cols: `Link to next/previous transaction` (450 rows)

**Result: 5,651 real link tokens checked; 0 unparseable, 0 out-of-range, 0
dangling.** The only non-token value encountered is the `N/A` sentinel (254
occurrences, all legitimate chain terminals). No token points past its target
sheet's row count (max tx=1,514, tr=504, pk=450). No broken row links anywhere.

### G2. Chronological monotonicity (no-teleport) across every chain-bearing sheet

For every datable link token, confirmed a `next` link resolves to a same-or-later
date and a `prev` link to a same-or-earlier date, resolving `#`/`T#`/`PH#` to the
target row's own Date.

- transactions add/drop chains: **0 teleports** (every next/prev within-date order).
- trades per-asset chains: **0 teleports.**
- picks chains: 397 datable target tokens, **0 teleports** (picks rows carry no own
  Date column, so chronology is verified via the resolved target's date).

### G3. Round-trip / recomputation consistency of the player chain

Rebuilt the per-player name-keyed event chain (transactions add+drop + trade
received/sent player assets, sorted by date, same-event rows skipped via the `_tx_id`
event map) exactly as `src/lotg.py::_neighbors` does, then compared the recomputed
next/prev to the stored link cells across all 1,514 transaction rows × 4 columns.

**152 field-level differences, 100% explained** by the stored value being a `PH#`
draft-terminal ref (the source additionally anchors a player's prior/next event to
their DRAFT row in picks.csv via the PH# logic at `src/lotg.py` ~L15523+, which the
plain name-chain recomputation does not model). **0 non-PH-explained mismatches** —
i.e. wherever the stored ref is a transaction/trade ref, it matches the recomputation
exactly. The PH# anchors were all already confirmed in-range in G1.

**Worked example — Darius Slayton (NOVEL, 19 events across 2021-2025):** the
add+drop chain threads correctly through five stints (2021 supplemental-draft add at
`#1312` whose prev is `PH#17`, the 2021 → 2024 → 2025 waiver churn, and trades),
with every `next`/`prev` landing on a same-or-forward-dated DISTINCT event and every
mirror/same-event row skipped. No self-references, no teleports, prev/next pairs
reconcile.

### G4. Result / last-place / toilet-bowl narrative text — the reverted-fix surface

Extracted all 1,892 workbook comments and scanned every one touching
`result | last place | toilet | standings | finish | 5th-8th` (37 distinct comment
bodies). Findings:

- **No comment asserts the reverted-incorrect claim** that `Result` must always
  agree with `last_place_by_season`. A targeted regex for any "(result/finish) …
  (agree/match/same/equal/consistent) … (last/regular)" assertion returned **0 hits**.
- The `Result` header tooltip (`team_year!C1`) is byte-for-byte the reverted/correct
  text: "…ranked by record (PF as tiebreaker) through Week 17 for 2020-2024 (which
  folds in the toilet bowl bracket — by league design, toilet-bowl results counted
  toward final standings those seasons) or through Week 15 for 2025+…" with the Notes
  "Can disagree with the all-time last-place stats, which are always
  regular-season-only." This matches `src/formulas.py` L1037-1039.
- **Toilet-bowl pick-provenance comments are NOT confused with Result-ranking.** The
  "originally X's pick (toilet-bowl reward)" lines (picks A442/A443/A451,
  player_all_time A255/A309/…) are pick OWNERSHIP-lineage text describing the 2.09
  synthetic award pick, structurally distinct from any finish-ranking statement.
- All other standings comments (`Record vs last place`, `Win % vs last place`,
  `Number of last place finishes`, `Toilet bowl record`, `Toilet losers game record`,
  `Toilet bowl win %`, the regular-season-only `Record` companion) read correctly and
  are mutually consistent.

**Toilet-reward provenance cross-checked against actual bracket results (NOVEL):**
the 2.09's "originally X's pick" origin equals the prior season's Toilet Final
winner in every case — 2023 Toilet Final winner = JacobRosenzweig → 2024 2.09 origin;
2024 winner = Oliverwkw → 2025 2.09 origin; 2025 winner = Oliverwkw → 2026 2.09
origin. All match.

**Pick-comment ≡ player-comment invariant:** the `picks` G1 tooltip promises the
pick's lineage comment is "identical to the comment on that player." Verified
byte-identical for the 2024 2.09 → Ja'Lynn Polk chain: `picks!A442` ==
`player_all_time!A255` (true). The lineage is chronologically ordered
(2024-07-13 trade → 2024 draft → 2025-09-01 drop), no dangling/stale steps.

### G5. Taxi-eligible row state (Part G(b))

`player_all_time` has 649 data rows; `Taxi-eligible` value counts = **True 43 /
False 606**. The 4 named transaction-only first-year-2025 never-started players all
correctly show **True**: Joe Milton, Jordan Watkins, Zavier Scott, Tanner McKee.
The E/F pad-row fix still holds.

---

## Part H — Workbook structural integrity (full population)

### H1. Row counts match CSV exports and expectations

Every sheet's `max_row` = its CSV line count, i.e. header + data rows:
formulas 439; player_week 21,377 (=21,376+1); player_year 1,860 (=1,859+1);
player_all_time 650 (=649+1); team_week 809 (=808+1); team_year 49 (=48+1);
team_all_time 9 (=8+1); league_week 102; league_year 7; league_all_time 2;
transactions 1,515 (=1,514+1); trades 505 (=504+1); picks 451 (=450+1). No truncation.

### H2. Auto-filter range == sheet dimension on every data sheet

For all 12 data sheets, `auto_filter.ref` exactly equals the sheet's `dimensions`
(A1 : <max_col><max_row>) — e.g. player_all_time `A1:BD650`, picks `A1:AO451`,
team_all_time `A1:EG9`, transactions `A1:BD1515`. No truncated or over-extended
filter ranges. The `formulas` reference sheet has no auto-filter (by design).

### H3. Conditional-formatting ranges fully cover data, no orphans

Each data sheet carries exactly 1 CF rule-range, spanning row 2 (first data row)
through `max_row` on a single column: player_week `L2:L21377`, player_year
`AH2:AH1860`, player_all_time `AF2:AF650`, team_week `I2:I809`, team_year `D2:D49`,
team_all_time `B2:B9`, transactions `AH2:AH1515`, trades `AE2:AE505`, picks
`V2:V451`. Every CF range's last row == that sheet's `max_row` and its column ≤
`max_column` — **0 out-of-bounds, 0 truncated, 0 orphaned** formatting beyond the
data region.

### H4. Comment count and placement internally consistent

Total **1,892** comments. Per sheet, header tooltips (row 1) and body chain-comments
(rows ≥ 2) decompose cleanly:
- **player_all_time:** 54 header tooltips + **649 body chain-comments = exactly 1
  per data row** (649 data rows).
- **picks:** 39 header tooltips + **450 body chain-comments = exactly 1 per data row**
  (450 data rows).
- Every other sheet: header tooltips only, 0 body comments.
- **All 1,099 body chain-comments sit in column A only** (the chain-narrative anchor);
  0 misplaced into any other column.
- **0 orphan header comments**: no row-1 comment sits beyond `max_column`, and no
  header comment sits on an empty header cell.

Header-tooltip counts are all ≤ their sheet's column count (only formula-bearing
columns receive a tooltip), consistent with the `src/formulas.py` registry.

---

## Conclusion

Parts G and H are **CLEAN — 0 defects**. The link layer (5,651 tokens) is fully
in-range, monotonic-in-time, and round-trip consistent; the reverted `Result`
ranking-window logic and its rewritten tooltip are correctly in place with no
stale/contradictory narrative anywhere; the toilet-bowl provenance chains verify
against actual bracket winners and the pick≡player comment invariant holds; and every
structural invariant (row counts, auto-filter ranges, conditional-formatting ranges,
comment counts/placement) is internally consistent against the CURRENT data. No
source change required; only this findings doc is committed.
