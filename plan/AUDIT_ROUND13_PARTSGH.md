# Phase 13 Round 13 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Fresh full-population audit repeating the Parts G/H methodology of
`plan/AUDIT_PHASE13_ROUND12_PARTSGH.md`, run against the FRESH offline build already
present in `exports/`. Agent 4 of 5 in Round 13 on branch
`claude/agent-part-audits-1yy87u` (HEAD `09669d6`). Siblings this round all landed
CLEAN: Parts A/B, C/D, E/F (0 defects each). This part-pair audits the exports as-is
— no rebuild, no source/exports modification.

**Build under audit:** the fresh offline build already in `exports/` (built cleanly,
exit 0; the two expected network-unavailable warnings). Full population differs from
Round 12 (fresh build with future picks extended through 2030):
picks **514** (was 450), player_all_time 649, player_year 1,859, player_week 21,376,
team_year 48, team_all_time 8, team_week 808, league_year 6, league_week 101,
league_all_time 1, trades 504, transactions **1,510** (was 1,514). Total workbook
comments **2,054** (was 1,892). `pytest tests/ -q` = **46 passed / 0 failed** in ~67s
(the suite grew from Round 12's 15 tests). All worked examples are NOVEL vs the
Round-12 cast (Mike Gesicki, Darius Slayton, Mike Williams, etc. all excluded); the
anchor here is the **Kyle Williams 2025 3.05 pick** (8-trade multi-hop chain).

**Result: CLEAN.** Zero confirmed defects. Both Part G (link integrity) and Part H
(structural integrity) invariants hold at full population. No source change required.

---

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

### G1. Link-token universe and in-range validation (full population)

Link cells are `;`-separated token lists; each token is `#N` (→transactions row N),
`T#N` (→trades row N), or `PH#N` (→picks.csv row N) — all 1-based display rows. The
non-link terminal in THIS build is the **empty cell / empty per-asset slot** (Round 12
used a literal `N/A` string; this build renders terminals blank — 0 literal `N/A` in
any link column, semantically identical: "no next/previous event").

Swept every link column at FULL population from the CSVs:
- transactions — 4 cols: next/prev × added-player / dropped-player (1,510 rows)
- trades — 2 cols: `Link to next/previous transaction per asset` (504 rows)
- picks — 2 cols: `Link to next/previous transaction` (514 rows)

**Result: 5,645 real link tokens checked; 0 unparseable, 0 out-of-range, 0 dangling.**
No token points past its target sheet's row count (max tx=1,510, tr=504, pk=514).
3,413 empty terminals (whole-cell blanks 3,145 + per-asset blanks inside `;`-lists),
all legitimate chain terminals. **0 self-references** — no transactions `#N` column
row links to its own row.

**xlsx hyperlink layer (the actual clickable links).** Loaded the workbook WITH
hyperlinks and resolved **all 60,398** cell hyperlinks across every sheet (the
per-asset trade cells, the player-name cross-links throughout player_week/year, plus
the link columns): **0 malformed targets, 0 out-of-range, 0 non-local** — every
`#'sheet'!<cell>` target lands on an existing sheet at a data row
2 ≤ row ≤ max_row, col ≤ max_col.

### G2. Chronological monotonicity (no-teleport) across every chain-bearing sheet

For every datable link token, confirmed a `next` link resolves to a same-or-later
date and a `prev` link to a same-or-earlier date (resolving `#`/`T#` to the target
row's own Date; picks rows carry no own Date so their chronology is covered via the
resolved target dates).

- **transactions: 3,519 datable cross-date checks, 0 teleports.**
- **trades (per-asset): 1,167 datable cross-date checks, 0 teleports.**
- **Total 4,686 datable checks, 0 teleports** — every next within-or-forward date,
  every prev within-or-backward date.

### G3. Player/asset-identity of every link (direct no-teleport / mis-link test)

Rather than recompute the name-chain, validated every STORED link directly: each
next/prev token must land on a row that actually involves the SAME player/asset as the
source cell's context. This directly catches cross-player teleports and mis-links.

- **transactions added/dropped links: 0 identity failures** (every next/prev added-link
  target contains the source's Player Added; every dropped-link target contains the
  source's Player Dropped).
- **trades per-asset links: 0 identity failures** — every token target shares a player
  asset OR a pick asset with the source trade. (Note: the pick-asset match had to
  accept BOTH label forms — numbered `YYYY R.NN` and the numberless future-pick
  `YYYY R(Owner)` — because future picks whose draft slot isn't set yet carry only the
  owner form. All 176 initially-flagged tokens resolved to a shared future-pick asset;
  see Anomalies.)
- **picks links: 0 identity failures** — every next/prev target either contains the
  matching pick asset OR contains the DRAFTED PLAYER (the by-design draft-row bridge:
  a pick's chain TERMINATES at its `PH#` draft row, and the pick's "next transaction"
  bridges into the drafted player's first later event). All 127 initially-flagged
  tokens were this bridge; see Anomalies.

### G4. Mirror-row / asset-conservation across every trade event

Grouped all 504 trade rows by exact Date (247 event groups) and verified multiset of
`Assets received` == multiset of `Assets sent` within each group — i.e. every asset a
team received was sent by a counterparty on the same event, so every trade leg has its
mirror row present. **247 date-groups, 0 conservation mismatches, 0 orphaned legs.**

### G5. No-teleport ORIGIN sweep (every player enters via a real event)

For all 649 player_all_time players, confirmed each has at least one ENTRY event —
a transaction Add, a trade "received", OR a draft pick (picks.csv, incl. the 152
`startup`-draft rows that carry the initial-roster vets). **649/649 players have an
origin; 0 teleports, 0 untraceable rosters.** (In this build even the startup
cornerstones/initial-roster vets resolve to a `startup` picks row, so the Round-12
"documented zero-event origin gap" does not surface as a gap here.)

### G6. Comment ≡ comment invariant and no-stale-narrative (full cross-check)

- **Pick≡player comment equality (FULL, not sampled):** for every picks row whose
  drafted player also has a player_all_time lineage comment (**353** such rows), the
  two comment bodies are **byte-identical — 0 mismatches.**
- **No stale narrative text (FULL automated cross-check):** parsed every dated line
  (`YYYY-MM-DD` + a named team) out of all 1,163 body comments (649 player_all_time +
  514 picks) and confirmed each `(date, team)` resolves to an actually-existing
  transactions or trades event involving a team named on that line — **4,736 dated
  lines checked, 0 unresolved.**

### G7. Worked example — Kyle Williams 2025 3.05 pick (NOVEL, 8-trade chain)

The `2025 3.05(K. Williams)` pick (drafted by shmuel256, **Original Team =
BROsenzweig**, `Number of trades = 8`) threads correctly through **8 distinct trade
events, all 8 with both mirror rows present**, chronologically ordered 2023-08-04 →
2025-07-20:

| Date | mirror pair | received-by |
|---|---|---|
| 2023-08-04 | T#16 ↔ T#59 | AceMatthew ← BROsenzweig |
| 2023-09-25 | T#19 ↔ T#356 | shmuel256 ← AceMatthew |
| 2023-11-01 | T#361 ↔ T#450 | stevenb123 ← shmuel256 |
| 2024-05-13 | T#164 ↔ T#460 | LWebs53 ← stevenb123 |
| 2024-10-09 | T#180 ↔ T#483 | stevenb123 ← LWebs53 |
| 2025-03-17 | T#391 ↔ T#491 | shmuel256 ← stevenb123 |
| 2025-06-25 | T#299 ↔ T#394 | plehv79 ← shmuel256 |
| 2025-07-20 | T#300 ↔ T#395 | shmuel256 ← plehv79 |

The picks-sheet `Link to previous transaction = T#395` (the last, 2025-07-20 trade in
which shmuel256 re-acquired the pick) is the correct terminal; its `Link to next
transaction` is correctly empty because Kyle Williams was never moved as a player after
the draft (verified: 0 post-draft player events). Cross-checked at the xlsx layer:
T#16's per-asset PREV cell for this pick hyperlinks to `#'picks'!A182` (= `PH#181`,
Kyle Williams's own draft row) — the pick chain's `PH#` draft terminal — confirming
pick-chain ↔ draft-row ↔ player-chain connect end to end with zero crossing errors.

---

## Part H — Workbook structural integrity (full population)

### H1. Sheet inventory & row/col shape vs CSV

13 sheets, **0 missing, 0 extra, 0 duplicate** names; every CSV has its sheet and
vice-versa. Every DATA sheet's xlsx `max_row` = its CSV line count (header + data) on
all 12: player_week 21,377; player_year 1,860; player_all_time 650; team_week 809;
team_year 49; team_all_time 9; league_week 102; league_year 7; league_all_time 2;
transactions 1,511; trades 505; picks 515. **No truncation.**

Column counts match CSV exactly on 11 of 12 data sheets. Two by-design rendering
differences (both documented, both verified benign):
- **trades:** xlsx `max_col` = 72 vs CSV 44 — the two `Link to …per asset` columns are
  expanded into 15 sub-columns each (headers on the first, `None` thereafter). Verified
  the sub-columns carry real per-asset data: each cell shows the asset NAME as display
  text with the ref as a hyperlink, and those hyperlinks reproduce the CSV token lists
  exactly (e.g. T#16 next = `#70;T#468;T#356;T#189` → `transactions!A71`, `trades!A469`,
  `trades!A357`, `trades!A190`). Not orphan/empty columns.
- **formulas:** xlsx `max_row` = **458** vs CSV 452 lines — the 6 extra rows are the
  section-divider labels (PLAYER SHEETS row 2, TEAM SHEETS 126, LEAGUE SHEETS 311,
  TRANSACTIONS 325, TRADES 380, PICKS 420), a visual grouping the CSV dump omits. Same
  +6 by-design difference as every prior round.

### H2. Auto-filter range == sheet dimension; frozen panes sane

For all 12 data sheets, `auto_filter.ref` exactly equals the sheet's `dimensions` —
e.g. player_week `A1:CN21377`, player_all_time `A1:BK650`, team_all_time `A1:ER9`,
transactions `A1:BD1511`, trades `A1:BT505` (filter spans the full per-asset expansion),
picks `A1:AO515`. No truncated/over-extended ranges. The `formulas` sheet has no
auto-filter (by design). Frozen panes are set and sane on every sheet (`A2` on formulas;
`E2`/`F2`/`D2` header+key-column freezes on the data sheets).

### H3. Conditional-formatting ranges fully cover data, no orphans

Each data sheet that carries CF has exactly 1 rule-range, spanning row 2 through
`max_row` on a single in-range column: player_week `L2:L21377`, player_year
`AK2:AK1860`, player_all_time `AI2:AI650`, team_week `I2:I809`, team_year `D2:D49`,
team_all_time `B2:B9`, transactions `AH2:AH1511`, trades `AG2:AG505`, picks `V2:V515`.
Every CF range starts at row 2, ends exactly at its sheet's `max_row`, sits on a column
≤ `max_column` — **0 out-of-bounds, 0 truncated, 0 orphaned.** The three league sheets
carry no CF (by design).

### H4. Comment count and placement internally consistent

Total **2,054** comments. Per sheet the header tooltips (row 1) and body chain-comments
(rows ≥ 2) decompose cleanly — **player_all_time** 61 header + 649 body (exactly 1 per
data row); **picks** 39 header + 514 body (exactly 1 per data row); every other sheet
header tooltips only, 0 body. **All 1,163 body comments sit in column A; 0 misplaced;
0 orphan headers** (no row-1 comment beyond `max_column`). Every sheet's header-tooltip
count is ≤ its column count (e.g. team_all_time 130 ≤ 148, team_year 119 ≤ 138,
player_week 82 ≤ 92, league_all_time 62 ≤ 62 — every column tooltipped).

### H5. Formulas-sheet coverage of every data column

`tests/test_formulas_coverage.py` (reuses the build's own `formulas.undocumented_columns`
against `plan/stats_catalog.json`) → **"All non-obvious columns documented"**, 0
uncovered. `exports/formulas.csv` carries 451 documented `Stat` rows across the 4
columns (Stat / Sheet / Formula / Notes); the full `pytest` run (46 tests) passes.

---

## Anomalies flagged (over-inclusive; three categories)

### (a) CONFIRMED DEFECTS
**None.**

### (b) LIKELY BY-DESIGN / DOCUMENTED
1. **Terminal represented as empty cell, not literal `N/A`.** 0 literal `N/A` in any
   link column; 3,413 empty terminals instead. The Round-12 doc described terminals as
   a literal `N/A` string. Semantically identical ("no next/previous event") and verified
   benign — every non-empty token resolves in-range, monotonic, and identity-correct;
   the one worked-example empty terminal (Kyle Williams next-link) is correctly empty
   because the player never moved post-draft. Representation difference only.
2. **trades xlsx 72 cols vs CSV 44** — per-asset expansion of the two link columns into
   15 sub-columns each; sub-columns verified to carry asset-name text + correct
   hyperlinks matching the CSV tokens. (H1)
3. **formulas xlsx 458 rows vs CSV 452** — 6 section-divider label rows the CSV omits.
   (H1)
4. **Picks "next transaction" bridges into the drafted PLAYER's chain** (not a pick
   asset) — the by-design draft-row bridge; 127 tokens, all resolve to the drafted
   player. (G3)
5. **Trade per-asset links keyed on future-pick owner form** `YYYY R(Owner)` — 176
   tokens whose shared asset is a numberless future pick; all resolve once both pick
   label forms are accepted. (G3)
6. **Population differs from Round 12** (picks 514 vs 450, transactions 1,510 vs 1,514,
   comments 2,054 vs 1,892, tests 46 vs 15) — fresh build with future picks extended
   through 2030; not a defect, noted for cross-round continuity.
7. **Offline KTC columns empty** (picks/transactions/trades KTC-at-* columns) — the
   known cross-agent offline-403 item; my link/structural sweep revealed NO new angle
   (KTC columns are value columns, carry no link tokens, and their emptiness does not
   affect any chain or hyperlink). Noted, not re-litigated.

### (c) NEEDS-HUMAN-JUDGMENT
**None.** (Item (b)(1), the empty-vs-`N/A` terminal rendering, is the only borderline
call; classified by-design because it is semantically equivalent and all present links
validate, but flagged here so a human is aware the terminal representation changed from
the Round-12 documentation.)

---

## Verification

- Link tokens (CSV): 5,645 real refs — 0 out-of-range, 0 unparseable, 0 self-ref.
- xlsx hyperlinks: 60,398 — 0 malformed, 0 out-of-range.
- Monotonicity: 4,686 datable checks — 0 teleports.
- Identity: transactions 0 / trades 0 / picks 0 mis-links.
- Trade conservation: 247 event groups — 0 mirror/conservation failures.
- Origin sweep: 649/649 players entered via a real event — 0 teleports.
- Comments: 2,054 total; pick≡player 353 byte-identical; 4,736 dated comment lines all
  resolve; 1,163 body comments all in column A; 0 orphans/misplaced.
- Structure: 13 sheets, 0 missing/extra/dup; row/col shapes consistent (trades +col and
  formulas +6-row differences by-design); auto-filter == dimensions on all 12; CF ranges
  row2..max_row in-column; formulas coverage complete.
- `pytest tests/ -q`: **46 passed / 0 failed** in ~67s.
- No `src/` or `exports/` modification; only this findings doc written.

## Conclusion

**Parts G + H are CLEAN — zero confirmed defects.** The link layer (5,645 CSV ref
tokens + 60,398 xlsx hyperlinks) is fully in-range, monotonic-in-time (4,686 checks,
0 teleports), identity-consistent (0 mis-links across transactions/trades/picks),
self-reference-free, asset-conserving (247 trade groups mirror perfectly), and
origin-complete (649/649 players, 0 teleports). The pick≡player comment invariant (353
byte-identical) and no-stale-narrative cross-check (4,736 dated lines) hold, and the
NOVEL 8-trade Kyle Williams 2025-3.05 pick chain verified end to end incl. its `PH#`
draft-row bridge. Every structural invariant — sheet inventory, row/col shapes (trades
per-asset expansion + formulas dividers by-design), auto-filter ranges, CF ranges, and
comment counts/placement (2,054 total; 1,163 body all in column A; 0 orphans) plus full
formulas coverage — is internally consistent at full population. No source change
required.
