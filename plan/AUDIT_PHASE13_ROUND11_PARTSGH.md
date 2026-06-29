# Phase 13 Round 11 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Self-designed full-population audit, run **fresh from scratch** against
`claude/phase-13-audit-tsapoy`. Agent 4 of 5 in Round 11 (siblings: Parts A/B —
CLEAN; Parts C/D — 2 tooltip fixes; Parts E/F — 1 computational fix at `9b6719f`,
the `Weeks between pickup and start` date-string compare). This part-pair (G+H)
was previously attempted and lost to a session limit with no salvageable diff;
this is the clean redo.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed behind the tip and `git merge-base --is-ancestor 9b6719f HEAD` did NOT
print `OK_AT_OR_AHEAD`. Hard-reset to `origin/claude/phase-13-audit-tsapoy`, after
which `git log -1 --oneline` = `9b6719f` and the merge-base check printed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`PYTHONPATH=src:lib python3
scripts/offline_build.py`, exit 0; only the 2 expected network-unavailable
warnings — `api.sleeper.app/v1/league/0` and `…/draft/espn_2020_draft`). Not a
stale cache. Full population: picks 450, player_all_time 649, player_year 1,859,
player_week 21,376, team_year 48, team_all_time 8, team_week 808, league_year 6,
league_week 101, league_all_time 1, trades 504, transactions 1,514. Total workbook
comments **1,892**.

`pytest tests/ -q` (run as `PYTHONPATH=src:lib python3 -m pytest`) = **15 passed /
0 failures**, both before and after the fix below.

All worked examples are NOVEL — different players/picks/teams/seasons than every
prior round (deliberately avoiding the prior anchors Darius Slayton, Wayne Gallman,
Giovani Bernard, Lynn Bowden as a chain example, Travis Fulgham, Kyle Rudolph,
Marquise Brown, Trevor Lawrence, Damien Harris, AJ Dillon, Ja'Lynn Polk, Wan'Dale
Robinson, James Conner, Cam Akers, James Cook, Irv Smith, Mariota, Bridgewater,
Likely, Rivers, Rush). New surfaces cited here: the **Mike Williams 30-event
multi-stint add/drop/trade chain** (2020-2024) as the round-trip worked example,
and the **2021-08-23 20:00:00 season-end orphan-drop tie cluster** as the
determinism-root-cause surface.

**Result: NOT clean for determinism — 1 real BUILD-DETERMINISM defect found and
FIXED in `src/lotg.py`.** Both Part G (link integrity) and Part H (structural
integrity) invariants HOLD in every build, before and after the fix — no link is
ever dangling, out-of-range, or mis-ordered, and no structural count is ever wrong.
But the *byte content* of `transactions.csv` (and the `#N` link refs that
`picks.csv` inherits from it) was **non-deterministic** between independent builds:
an unstable pandas sort left rows tied on `(Team, Date)` in a run-dependent order,
silently renumbering the position-based `#N`/`PH#`-adjacent link references. This is
the same non-determinism the Round-11 E/F agent flagged out-of-scope; I traced it to
its root cause, confirmed it is a real ordering-ambiguity bug with a clean
deterministic tiebreaker, fixed it, and verified two independent builds are now
byte-identical across all 12 CSVs.

---

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

### G1. Link-token universe and in-range validation (full population)

Link cells are `;`-separated token lists; each token is `#N` (→transactions row N),
`T#N` (→trades row N), or `PH#N` (→picks.csv row N) — all 1-based display rows. The
sole non-link sentinel is the literal `N/A` (asset never moved again / no prior
event).

Swept every link column at FULL population, reading the `;`-joined ref lists from
the CSVs (the xlsx renders the trades per-asset columns as the asset NAME with the
ref carried as a hyperlink, so the ref *tokens* live in the CSV):
- transactions — 4 cols: next/prev × added-player / dropped-player (1,514 rows)
- trades — 2 cols: `Link to next/previous transaction per asset` (504 rows)
- picks — 2 cols: `Link to next/previous transaction` (450 rows)

**Result: 5,651 real link tokens checked; 0 unparseable, 0 out-of-range, 0
dangling.** The only non-token value is the `N/A` sentinel (254 occurrences, all
legitimate chain terminals). No token points past its target sheet's row count
(max tx=1,514, tr=504, pk=450). No broken row links anywhere.

**xlsx hyperlink layer (the actual clickable links).** Separately loaded the
workbook *with* formulas/hyperlinks and resolved **all 63,292** cell hyperlinks
across every sheet (link columns plus the player-name cross-link hyperlinks
throughout player_week/player_year/etc.): **0 malformed targets, 0 out-of-range**
(every `#'sheet'!A<row>` target lands on an existing sheet at a data row
2 ≤ row ≤ max_row). 0 self-references in any link column.

### G2. Chronological monotonicity (no-teleport) across every chain-bearing sheet

For every datable link token, confirmed a `next` link resolves to a same-or-later
date and a `prev` link to a same-or-earlier date (resolving `#`/`T#` to the target
row's own Date; picks rows carry no own Date so their chronology is verified via the
resolved target's date).

- **4,692 datable cross-date checks, 0 teleports** (every next within-or-forward
  date, every prev within-or-backward date).

### G3. Round-trip / recomputation consistency of the player chain

Rebuilt the per-player name-keyed event chain (transactions add+drop + trade
received/sent player assets, sorted by date) the way `src/lotg.py::_neighbors`
does, then compared the recomputed next/prev to the stored link cells across all
1,514 transaction rows × 4 columns.

**152 field-level differences, 100% explained** by the stored value being a `PH#`
draft-terminal ref (the source additionally anchors a player's first/last event to
their DRAFT row in picks.csv, which the plain name-chain recomputation does not
model). **0 non-PH-explained mismatches** — wherever the stored ref is a
transaction/trade ref, it matches the recomputation exactly. The PH# anchors were
all confirmed in-range in G1. (Identical count to the prior-round recomputation.)

**Worked example — Mike Williams (NOVEL, ~30 events 2020-2024):** the chain threads
correctly through a 2020-rookie-season FA carousel (LWebs53 draft 17.02 → six
in-season add/drop hops between Oliverwkw, plehv79, AceMatthew, LWebs53, stevenb123,
shmuel256), the 2021 supplemental-vet-draft re-entry (plehv79 2.04), then a
four-trade run (2022 to stevenb123, 2023 to shmuel256, 2023 to AceMatthew, 2024 to
shmuel256) ending in a 2024-11-26 drop. Verified directly on the workbook: every
`next added` link lands on a same-or-later-dated MW row whose `prev added` mirrors
back exactly (0 mirror errors, 0 monotonicity errors), the earliest add (2020-09-16)
has no prior add, and the final drop's `prev dropped` = `T#383` resolves to the
2024-10-29 "shmuel256 got Mike Williams" trade — matching the comment narrative
line verbatim. No self-references, no teleports.

### G4. Comment ≡ comment invariant and pick-provenance narrative (no stale text)

- **Comment inventory (full):** 1,892 comments total. 1,099 BODY chain-comments,
  **all in column A** (649 player_all_time + 450 picks = exactly 1 per data row),
  **0 misplaced into any other column, 0 orphan header comments** (no row-1 comment
  beyond max_column or on an empty header cell).
- **Pick≡player comment equality (FULL, not sampled):** for every picks row whose
  drafted player also has a player_all_time lineage comment (353 such rows), the two
  comment bodies are **byte-identical — 0 mismatches.**
- **Toilet-bowl 2.09 provenance (cross-checked against bracket winners):** the three
  2.09 toilet-reward picks read "originally X's pick (toilet-bowl reward)" with
  X = the prior-season Toilet-Final winner in every case — 2024 → JacobRosenzweig,
  2025 → Oliverwkw, 2026 → Oliverwkw — and their trade-lineage lines are
  chronologically ordered with no dangling/stale step.
- **No stale narrative text:** spot-traced the Mike Williams comment's dated trade
  lines against the current trades-sheet cell values (T#383 etc.) — every embedded
  date/assets claim matches the linked row.

### G5. Taxi-eligible row state (Part G(b))

`player_all_time` 649 data rows; the 4 named transaction-only first-year-2025
never-started players (Joe Milton, Jordan Watkins, Zavier Scott, Tanner McKee)
remain correctly `Taxi-eligible = True` (the E/F pad-row fix still holds). Not
re-flagged per the standing corrections.

---

## Part H — Workbook structural integrity (full population)

### H1. Row counts match CSV exports and expectations

Every DATA sheet's xlsx `max_row` = its CSV line count (header + data):
player_week 21,377; player_year 1,860; player_all_time 650; team_week 809;
team_year 49; team_all_time 9; league_week 102; league_year 7; league_all_time 2;
transactions 1,515; trades 505; picks 451. **No truncation.**

The `formulas` reference sheet is the one intentional exception: xlsx `max_row` =
**439** vs CSV 433. The 6 extra xlsx rows are **section-divider header rows**
(`PLAYER SHEETS`, `TEAM SHEETS`, `LEAGUE SHEETS`, `TRANSACTIONS`, `TRADES`, `PICKS`)
that the xlsx build inserts as visual group labels but the CSV dump omits. Verified
the inverse holds: **every one of the 432 CSV formula `Stat` rows is present in the
xlsx (0 missing)** — so this is a by-design rendering difference, not truncation or
orphaning. (Matches the prior round's reported `formulas 439`.)

### H2. Auto-filter range == sheet dimension on every data sheet

For all 12 data sheets, `auto_filter.ref` exactly equals the sheet's `dimensions`
(`A1:<max_col><max_row>`) — e.g. player_all_time `A1:BD650`, picks `A1:AO451`,
team_all_time `A1:EG9`, transactions `A1:BD1515`, trades `A1:BQ505`. No truncated or
over-extended filter ranges. The `formulas` reference sheet has no auto-filter
(by design).

### H3. Conditional-formatting ranges fully cover data, no orphans

Each data sheet carries exactly 1 CF rule-range, spanning row 2 (first data row)
through `max_row` on a single column: player_week `L2:L21377`, player_year
`AH2:AH1860`, player_all_time `AF2:AF650`, team_week `I2:I809`, team_year `D2:D49`,
team_all_time `B2:B9`, transactions `AH2:AH1515`, trades `AE2:AE505`, picks
`V2:V451`. Every CF range starts at row 2, ends exactly at its sheet's `max_row`,
and sits on a column ≤ `max_column` — **0 out-of-bounds, 0 truncated, 0 orphaned**.

### H4. Comment count and placement internally consistent

Total **1,892** comments. Per sheet: header tooltips (row 1) and body chain-comments
(rows ≥ 2) decompose cleanly — **player_all_time** 54 header + 649 body (1 per data
row); **picks** 39 header + 450 body (1 per data row); every other sheet header
tooltips only, 0 body. All 1,099 body comments sit in column A; 0 misplaced; 0 orphan
headers. Header-tooltip counts are all ≤ their sheet's column count.

---

## Build-determinism defect — root cause, fix, and verification

### What was wrong

`transactions.csv` (and the `#N` link refs `picks.csv` inherits from it) was
**non-deterministic** between independent builds. Two from-scratch HEAD-source
builds differed in ~24 `transactions.csv` rows and ~6 `picks.csv` rows — exactly the
out-of-scope non-determinism the E/F agent flagged. Reproduced here: build-vs-build
diffs of 24 (transactions) + 6 (picks) changed lines.

**Root cause (traced):** the final transaction ordering — the order that assigns
each row its 1-based position, and therefore every `#N` link reference into it — is
set by `tx = tx.sort_values(["Team","Date"])` (src/lotg.py ~L15331). pandas
`sort_values` defaults to **quicksort, which is NOT stable**, so rows tied on
`(Team, Date)` land in a run-dependent order. And many rows ARE tied: 459
transaction rows share a timestamp with at least one other row (146 distinct tied
instants, up to 24 rows on one). The largest cluster is the **season-end orphan-drop
synthesis**, which stamps a whole per-team batch with a single
`YYYY-08-23 20:00:00` instant (e.g. JacobRosenzweig's Golden Tate drop, plehv79's
Anthony McFarland drop, stevenb123's Lynn Bowden drop). When quicksort reshuffles
such a tied block, the rows' positions swap and every `#N` ref that targets them
(in transactions' own next/prev columns AND in picks' inherited `#N` link tokens)
silently renumbers — e.g. `#350`↔`#351`, `#463`↔`#464`, `#1001`↔`#1002`. The pick
ROWS themselves are byte-identical between builds; only their cross-reference tokens
churn, because those tokens point into the permuted transactions sheet. (A first
attempt at stabilizing the earlier `transactions_rows.sort` did NOT fix it, which is
how the true downstream pandas sort was localized.)

This is a genuine ordering-ambiguity bug, NOT irreducible: the tied rows have a
canonical identity available. It never produced a broken/dangling/out-of-range link
in any build (G1-G3 pass on every build) — but it makes the artifact
non-reproducible, which is itself a defect worth fixing.

### Fix

Made the two relevant pandas sorts **stable with a full identity tiebreaker**
(`src/lotg.py`, 2 edits):
- transactions: `sort_values(["Team","Date","Player Added","Player Dropped"],
  kind="stable", na_position="first")` — `(Player Added, Player Dropped)` is unique
  within every `(Team, Date)` group (0 residual duplicates verified; it is the same
  identity the dedup pass two blocks earlier treats as unique).
- trades: `sort_values(["Team","Date","Assets received","Assets sent"],
  kind="stable", na_position="first")` — same rationale for the per-asset `T#N`
  refs (trades showed no churn empirically but is stabilized for safety).

Low-risk: it only fixes the ORDER of already-tied rows; it adds/removes no row,
changes no value, and the chosen tiebreaker is a deterministic function of existing
data.

### Verification

- **Two independent from-scratch builds with the fix are byte-identical across ALL
  12 CSVs — TOTAL CHANGED LINES = 0** (was 24 transactions + 6 picks pre-fix).
- Part G re-run on the post-fix build: **5,651 tokens, 0 bad / 0 out-of-range /
  254 N/A / 4,692 datable / 0 teleports** — identical to pre-fix; link integrity
  fully preserved.
- Part H re-run on the post-fix build: all row-count / auto-filter / CF-range /
  comment invariants hold; total comments still **1,892**.
- `PYTHONPATH=src:lib python3 -m pytest tests/ -q` = **15 passed** with the fix
  (incl. `test_pick_chain_links` and `test_player_history_continuity`).
- Build artifacts reverted (`git checkout -- exports/`); only the `src/lotg.py`
  fix + this findings doc are committed.

---

## Conclusion

Parts G and H link/structural invariants are **CLEAN** in every build — the link
layer (5,651 ref tokens + 63,292 xlsx hyperlinks) is fully in-range, monotonic-in-
time, round-trip consistent, and stale-text-free; the pick≡player comment invariant
and toilet-bowl provenance hold; and every structural invariant (row counts,
auto-filter ranges, CF ranges, comment counts/placement) is internally consistent.

But the build was **non-deterministic**, and that is a real defect: an unstable
pandas `sort_values(["Team","Date"])` permuted same-timestamp rows between runs,
silently renumbering the position-based `#N` link references (transactions and the
picks tokens inherited from them). **Fixed** with stable sorts carrying a full
identity tiebreaker; two independent builds are now byte-identical and 15/15 tests
pass. The non-determinism the E/F agent observed is hereby resolved, not merely
documented.
