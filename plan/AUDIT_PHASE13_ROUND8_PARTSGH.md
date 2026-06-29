# Phase 13 Round 8 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Self-designed full-population audit repeating the Parts G/H methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 4 of 5 in Round 8 (siblings: Parts A/B —
`AUDIT_PHASE13_ROUND8_PARTSAB.md` — CLEAN at `e87b0b7`; Parts C/D —
`AUDIT_PHASE13_ROUND8_PARTSCD.md` — 3 tooltip-text 2020-season fixes at `518a581`;
Parts E/F — `AUDIT_PHASE13_ROUND8_PARTSEF.md` — CLEAN at `965a21c`, confirming the
underlying 2020 16-week DATA was already correct and only the C/D text needed
fixing).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `git merge-base --is-ancestor 965a21c HEAD`
printed nothing — `965a21c` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`965a21c`, the Round-8 Parts E/F tip
carrying all Round-5/6/7 fixes + the Round-8 C/D 3 tooltip-text fixes), then
confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
trades 504, transactions 1,514, player_all_time 649.

**Confirmed the changes-since-Round-7-G/H are link-data-inert.** The Round-7 G/H
sweep was CLEAN at `00447a0`. `git diff e87b0b7..HEAD -- src/` shows the ONLY
source change since the Round-8 A/B baseline is the **3 Round-8 C/D tooltip-TEXT
edits** in `src/formulas.py` (`PF` Semifinal-week wording, `Win %` and `Record`
"16-in-2020 / 17-in-2021+" game-count wording) — all pure header-tooltip TEXT, no
link-generation, hyperlink-emission, or comment-box geometry code touched. So the
link layer, hyperlink anchors, and comment geometry are byte-identical to the
Round-7 G/H baseline — and the full-population sweeps below confirm it empirically
(every count is identical to Round 7).

All examples below are NOVEL — different players/teams/picks than every prior round
(Rounds 4-7 + Round 8 A/B/C/D/E/F exclusion lists honoured; deliberately avoiding
Marquise Brown 1.02 / Jakobi Meyers / Wayne Gallman / Giovani Bernard / Ryan
Tannehill / Taysom Hill / Cooper Kupp / Wan'Dale Robinson / George Pickens / Kyle
Pitts as the prior G/H + C/D anchors). New surfaces cited here: the **2021 1.03
(Trevor Lawrence)** pick→trade received-scope decomposition; the **Lynn Bowden /
Travis Fulgham / Kyle Rudolph** novel platform-seam holdovers; **Damien Harris
2021 vet 1.03** as a second received-scope worked example.

**Result: CLEAN — 0 defects found in Parts G or H.** Every link reference is
in-range, chronologically ordered, and round-trip consistent (the only link
asymmetries decompose into by-design received-only per-asset display scope and
same-event mirror rows — all forward-or-same-dated, 0 teleports). Every
workbook-structural invariant holds against the CURRENT row counts. The pick-chain
sibling-collision fix (698ccea) and the platform-seam-teleport fix both still hold.
No code change required.

---

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

Swept every link column across all chain-bearing sheets at FULL population:
transactions (1,514 × 4 link cols: next/prev × added/dropped player), trades
(504 × 2 per-asset link cols), picks (450 × 2). player_all_time carries its asset
history as hover comments only (0 `link to …` columns) — no ref-range surface.

Link cells are `;`-separated token lists; each token is `#N` (→transactions),
`T#N` (→trades), `PH#N` (→picks), or the literal `N/A` per-asset no-link
placeholder. (A naive whitespace/comma split mis-fragments multi-token cells and
mis-flags the `N/A` placeholder — splitting strictly on `;` and treating `N/A` as
a valid no-link token is the correct parse, confirmed by enumerating every
distinct non-`#`-shaped token: only `N/A` appears, 254 occurrences.)

### G1 — Reference-range integrity + malformed scan — CLEAN
**5,651 chain references** parsed across all 8 link cells. **0 out-of-range**
(every `#N`/`T#N`/`PH#N` resolves to `1 ≤ N ≤` that sheet's row count: tx 1,514 /
trades 504 / picks 450), **0 malformed/junk tokens**, **0 refs to a missing
sheet**. (Identical count to Round 6/7 — confirms the link layer is unchanged.)
Per-link-column ref counts: tx next-added 1,003 / prev-added 750 / next-dropped 762
/ prev-dropped 1,162; trades next 894 / prev 937; picks next 274 / prev 123.

### G2 — Pick sibling self-link (the 698ccea fix) — CLEAN / HOLDS
**0 cross-`PH#` sibling links across all 450 picks** — no picks-sheet `Link to
previous/next transaction` cell points at a DIFFERENT picks row. The
full-numbered-identity keying still holds. The fix is intact.

### G3 — Chronological ordering — CLEAN
Parsed the `Date` of every dated neighbor referenced by every transactions and
trades link cell (full population, both directions, all 4 tx link cols + both
trade cols): **0 chronology violations** — no `next` link points to an
earlier-dated event, no `previous` link to a later-dated one. (`PH#` refs carry no
row date — draft-anchor terminals — and are excluded from the date comparison by
construction.)

### G4 — Round-trip consistency

**G4a — Pick ↔ trade forward round-trip — CLEAN.** For every pick whose `Link to
previous transaction` is a trade `T#k`, that trade's `Link to next transaction per
asset` echoes this pick's `PH#` — **0 breaks across all 450 picks**. This is also
the invariant the existing `test_pick_chain_link_integrity` guard checks; it passes
against the fresh build.

**G4a' — Pick `next`=T#k vs trade-k `prev` — 86 received-scope display artifacts,
0 teleports.** The reverse direction (a pick's `next`=T#k should be echoed by trade
k's per-asset `previous`) shows 86 apparent non-echoes. I classified each by an
independent **acquisition-date test** (the pick's `next`-trade date vs the latest
date among the pick's `prev`-trades): **all 86 are forward-or-same-dated, 0
backward-dated** (the teleport signature). This is the documented received-only
per-asset DISPLAY scope: a pick's `next` link points to the deal where the
pick/its drafted player was traded AWAY, but the trade row's per-asset cells
display the RECEIVED side, so they don't echo back the sent pick. Worked examples
(both NOVEL):
- **picks row 35 = 2021 1.03 (Trevor Lawrence), originally & made by AceMatthew,
  `Number of trades = 0`** → `next = T#22`, the 2024-05-13 blockbuster where
  AceMatthew SENT `Trevor Lawrence; DeVonta Smith; Chris Olave; 2024 1.08(B.
  Thomas); 2025 1.03(O. Hampton); 2027 2; 2028 2` and RECEIVED `Keenan Allen;
  Tyreek Hill; Joe Mixon; James Conner; Justin Jefferson`. The trade's per-asset
  `previous` cells (`PH#349; T#261; T#141; T#452; #729`) trace the FIVE RECEIVED
  assets back to their own origins, not the sent Lawrence pick — by design, not a
  wrong-event link. Forward-dated (pick made 2021, traded 2024).
- **picks row 3 = 2021 vet 1.03 (Damien Harris), originally & made by AceMatthew**
  → `next = T#5`, the 2021-08-29 deal where AceMatthew sent `Damien Harris; Jakobi
  Meyers; Dyami Brown` and received `David Montgomery`; trade #5's per-asset
  `previous = PH#358` is the David-Montgomery received-scope origin, not PH#3.
  Forward-dated.

The underlying `chains` dict is fully bidirectional; only the displayed per-asset
cells are received-scoped.

**G4b — Transaction add/drop player chain round-trip — CLEAN (cross-column).** Each
player's event chain is a single linked list spanning BOTH the added-player and
dropped-player link columns (an add's `next` is frequently that player's later DROP,
stored under the dropped-player columns). Checked CROSS-column (a `#`-`next` ref in
EITHER next column must have a back-pointer in EITHER prev column of the target),
the result is **0 breaks** across all 1,514 transactions. Every forward link has a
matching backward link once the add↔drop column hand-off is accounted for.

**G4c — Trades per-asset `T#`→`T#` round-trip — CLEAN (0 teleports).** The
same-direction trades-only round-trip shows 91 apparent asymmetries; classified by
date, **all 91 are forward-or-same-dated, 0 backward-dated**. Same Round-5/6/7
decomposition (received-only per-asset display scope + same-timestamp mirror-row
tie-break artifact); 0 links point to a wrong EVENT.

### G5 — Platform-seam-teleport fix re-verify — HOLDS (link + narrative layers)

**Seam-drop link layer.** The 2020→2021 platform seam synthesizes one drop per
holdover player at `2021-08-23`. Full-population scan: **12 seam drops
(`Date dropped/traded` = 2021-08-23), 11 distinct players, exactly 1 player with >1
seam drop** — that's Mitchell Trubisky with his two 2020 waiver adds both closing at
the seam (the documented Round-7/8 C/D Sleeper duplicate-add pattern, one stint).
The other 10 are clean one-drop holdovers. NOVEL examples verified end-to-end
against both transactions.csv and the player_all_time narrative comment:
- **Lynn Bowden** — multi-stint 2020 churn: added by shmuel256 2020-12-17, dropped
  2020-12-26, picked up SAME day by stevenb123, held across the empty seam, last
  event `2021-08-23: dropped by stevenb123` — exactly ONE seam drop, narrative
  chronologically perfect across two owners, no teleport over the empty 2021/2022
  seasons.
- **Travis Fulgham** — two stints (a brief stevenb123 stint 2020-10-15→10-17, then
  BROsenzweig 2020-10-21) ending `2021-08-23: dropped by BROsenzweig` — one clean
  seam drop.
- **Kyle Rudolph** — added by JacobRosenzweig 2020-12-04, last event
  `2021-08-23: dropped by JacobRosenzweig` — exactly ONE seam drop.

**Narrative layer full-population teleport scan (all 649 player + 450 pick history
comments).** **0 chronological inversions** (player 0, picks 0). **5 add→add
(no intervening close) suspects, all 5 SAME-team → 0 cross-team teleports.** Each is
the documented Sleeper duplicate-add pattern (a FA record + a commissioner
correction / re-logged add for the SAME roster stint). The 5 map to exactly the
prior-round-documented players (Ameer Abdullah, Deuce Vaughn, Mitchell Trubisky,
Ryan Tannehill, Taysom Hill) — stable count/identity vs Round 7/8-C/D, 0 NEW
cross-team teleport surfaced.

The pick-chain sibling-collision fix (698ccea) and the platform-seam-teleport fix
both still hold given everything that changed since Round 7 (the 3 Round-8 C/D
tooltip-text edits) — verified empirically, not assumed.

---

## Part H — Workbook-structural integrity sweep

### H1 — Every sheet opens without corruption — CLEAN
All 13 sheets load via openpyxl with no error. Dimensions reconcile to the CSV
populations + 1 header row each for the 11 row-mirrored data sheets: player_week
21377×65, player_year 1860×62, player_all_time 650×56, team_week 809×101, team_year
49×127, team_all_time 9×137, league_week 102×59, league_year 7×62, league_all_time
2×55, transactions 1515×56, picks 451×41. The two non-1:1 sheets are by-design and
stable vs Round 7: **formulas** is a 439×4 definitions reference (not a CSV mirror —
the 432 CSV data rows render with extra structural rows), and **trades** is 505×69
(the xlsx carries 28 extra computed link/display columns beyond the 41 CSV columns —
exactly Round 7's reported `trades 505×69`). No drift.

### H2 — Hyperlink target-anchor integrity — CLEAN (0 off-by-one)
Parsed every internal hyperlink directly from each sheet's XML `<hyperlinks>` block
joined to its `.rels` Targets (openpyxl's per-cell `.location` is empty for these
rels-style links, so XML parsing is authoritative).
- **63,292 internal hyperlinks** swept (identical to Round 6/7). **0 malformed,
  0 point to a missing sheet, 0 point out of the target sheet's row range**
  (`2 ≤ row ≤` that sheet's max_row). Per-sheet: player_week 42,660, player_year
  7,699, transactions 5,914, player_all_time 2,773, trades 2,222, picks 1,200,
  team_week 808, team_all_time 16.
- **Semantic off-by-one** (the after-sort/filter concern): for every picks
  `Link to previous/next transaction` cell with a displayed ref, the hyperlink
  resolves to exactly `target_sheet!A{k+1}` (the row whose index IS k, accounting
  for the header) — **0 mismatches across 397 checked picks link cells**. No
  off-by-one survived the auto-filter applied to every sheet.

### H3 — Comment encoding & box geometry — CLEAN (re-verifies the formatting fixes)
- **1,892 comments** (793 header tooltips on row 1 + 1,099 asset-history hovers on
  col A row≥2, parsed directly from `xl/comments/comment*.xml`). **0 empty, 0
  mojibake** (scanned every comment for `Ã`/`â€`/`Â\xa0`/`ï¿½`/`�`; all valid UTF-8
  incl. em-dashes and accented names). Identical totals to Round 6/7.
- **Header-tooltip height fix (900px cap) — HOLDS** against current row counts.
  Read the persisted VML geometry (`xl/drawings/commentsDrawing*.vml`,
  `<ns1:shape>` `style="…;width:…px;height:…px"`, row from `<ns2:Row>`): all **793**
  header boxes are width **460px**, heights **80–620px across 17 distinct values**
  (per-comment line-count sizing, not flat). **0 over the 900px cap, 0 pinned at
  the cap.**
- **History-hover height (1,100px cap) — HOLDS.** All **1,099** history boxes are
  width **560px**, heights **90–507px across 25 distinct values**, **0 over the
  1,100px cap, 0 pinned at the cap.**
- Box-count reconciles: 793 + 1,099 = **1,892 = total comments** — no orphan or
  missing geometry.

### H4 — Freeze panes / tab colors / auto-filter / conditional-formatting vs CURRENT extent — CLEAN
This is the prompt's specific concern (re-verify against the now-current row
counts).
- **Freeze panes:** all 13 correct (formulas `A2`; team_week `F2` = 5-col pin; the
  other 11 `E2` = 4-col pin); all within column extent.
- **Tab colors:** all set per family (player `5B9BD5`, team `70AD47`, league
  `FFC000`, transactions `ED7D31`, trades `7030A0`, picks `808080`, formulas
  `44546A`; the `00` ARGB prefix is the alpha channel).
- **Auto-filter ranges:** every data sheet's filter == `A1:{maxcol}{maxrow}`
  spanning EXACTLY the current extent — **0 mismatches** (formulas correctly has
  none). E.g. trades `A1:BQ505`, transactions `A1:BD1515`, picks `A1:AO451`,
  player_all_time `A1:BD650`, player_week `A1:BM21377`.
- **Conditional-formatting (color-scale) ranges:** every range spans exactly
  `2:max_row` and **0 ranges exceed the sheet extent** — player_week `L2:L21377`,
  player_year `AH2:AH1860`, player_all_time `AF2:AF650`, team_week `I2:I809`,
  team_year `D2:D49`, team_all_time `B2:B9`, transactions `AH2:AH1515`, trades
  `AE2:AE505`, picks `V2:V451`. Not stale-short, not stale-long — tracks the
  current row counts precisely.

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~75s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` (roster-lineage continuity end to end)
  and `test_pick_chain_link_integrity` (the Part-G pick↔trade round-trip guard).
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- **No source changes were needed (no defects).** Build artifacts reverted
  (`git checkout -- exports/`; `git clean -fd exports/ .cache/`); `git status`
  clean except this findings file.

## Conclusion
**Parts G and H are CLEAN at full population — ZERO defects.** Link integrity:
5,651 chain refs + 63,292 hyperlinks all in-range; 0 sibling self-links (698ccea
holds); 0 chronology violations; 0 picks semantic off-by-one; and — crucially —
**0 teleports** (every link asymmetry decomposes into by-design received-only
per-asset display scope or same-event mirror rows, all forward-or-same-dated by an
independent acquisition-date test, never a wrong/earlier event). The
platform-seam-teleport fix holds in BOTH the link layer (12 clean seam drops, the
only multi-drop being Trubisky's documented duplicate-add) and the
narrative-comment layer (0 cross-team add→add teleports; the 5 same-team suspects
are the Sleeper duplicate-add pattern). Workbook structure: all 13 sheets open
clean; the header-tooltip (900px cap, 620px longest) and history-hover (1,100px
cap, 507px longest) geometry fixes are genuinely persisted and unclipped on the
CURRENT workbook; freeze panes, tab colors, auto-filter ranges, and all
conditional-formatting ranges match the current row/column extents exactly. The
only source change since the Round-7 G/H baseline is the 3 Round-8 C/D
tooltip-TEXT edits (provably link-data-inert), and the full-population sweeps
confirm it empirically (every count identical to Round 7). No code change was
required for Parts G/H this round.
