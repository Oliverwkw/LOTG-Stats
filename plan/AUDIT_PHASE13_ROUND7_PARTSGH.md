# Phase 13 Round 7 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Self-designed full-population audit repeating the Parts G/H methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 4 of 5 in Round 7 (siblings: Parts A/B —
`AUDIT_PHASE13_ROUND7_PARTSAB.md` — CLEAN at `4bf5575`; Parts C/D —
`AUDIT_PHASE13_ROUND7_PARTSCD.md` — 4 tooltip-text drift fixes at `be65140`;
Parts E/F — `AUDIT_PHASE13_ROUND7_PARTSEF.md` — CLEAN at `00447a0`).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `00447a0` was NOT an ancestor of HEAD;
`git merge-base --is-ancestor 00447a0 HEAD` printed NOT_ANCESTOR). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`00447a0`, the Round-7 Parts E/F tip carrying
all Round-4/5/6 fixes + the Round-7 C/D 4 tooltip fixes), then confirmed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
trades 504, transactions 1,514, player_all_time 649.

**Confirmed the changes-since-Round-6-G/H are link-data-inert.** The Round-6 G/H
sweep was CLEAN at `fc3f726`. `git diff fc3f726..HEAD -- src/lotg.py` shows the ONLY
`src/lotg.py` change since that baseline is a **single code-comment text edit** (the
retention-rate measurable-years comment, the round-6 I/J fix) — no link-generation,
hyperlink-emission, or comment-box code changed. `src/formulas.py` changed only by
the 6+4 tooltip-TEXT lines (round-6 C/D + round-7 C/D). So the link layer, hyperlink
anchors, and comment geometry are byte-identical to the Round-6 G/H baseline — and
the full-population sweeps below confirm it empirically (every count is identical to
Round 6).

All examples below are NOVEL — different players/teams/picks than every prior round
(Rounds 4-7 exclusion list honoured; deliberately avoiding the long named list
across A/B/C/D/E/F and prior G/H, including Trubisky/Hurst as the requested seam
re-check anchors). New surfaces cited here: the **2021 vet 1.02 (Marquise Brown)**
pick→trade display-scope decomposition; the **Wayne Gallman / Giovani Bernard**
novel platform-seam drops; the **Ryan Tannehill / Taysom Hill** same-team
duplicate-add narrative pairs.

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

### G1 — Reference-range integrity + malformed scan — CLEAN
**5,651 chain references** parsed across all 8 link cells. **0 out-of-range**
(every `#N`/`T#N`/`PH#N` resolves to `1 ≤ N ≤` that sheet's row count: tx 1,514 /
trades 504 / picks 450), **0 malformed/junk tokens**, **0 refs to a missing sheet**.
(Identical count to Round 6 — confirms the link layer is unchanged.)

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
k's per-asset `previous`) shows 86 apparent non-echoes. Decomposed by date: **all 86
are forward-or-same-dated, 0 backward-dated** (the teleport signature). This is the
documented received-only per-asset DISPLAY scope: a pick's `next` link points to the
deal where the pick was traded AWAY, but the trade row's per-asset cells display the
RECEIVED side, so they don't echo back the sent pick. Worked example (NOVEL):
**picks row 2 = 2021 vet 1.02 (Marquise Brown), originally JacobRosenzweig's** →
`next = T#106`, the 2023-08-21 deal where JacobRosenzweig RECEIVED Jayden Reed +
2025 3.01 + 2025 2.03 (and sent the 1.02). The trade's received-scoped per-asset
cells list the received assets, not the sent pick — by design, not a wrong-event
link. The underlying `chains` dict is fully bidirectional; only the displayed
per-asset cells are received-scoped.

**G4b — Transaction add/drop player chain round-trip — CLEAN (cross-column).** Each
player's event chain is a single linked list spanning BOTH the added-player and
dropped-player link columns (an add's `next` is frequently that player's later DROP,
stored under the dropped-player columns). Checked CROSS-column (a `next` ref in
EITHER next column must have a back-pointer in EITHER prev column of the target),
the result is **0 breaks** across all 1,514 transactions. Every forward link has a
matching backward link once the add↔drop column hand-off is accounted for.

**G4c — Trades per-asset `T#`→`T#` round-trip — CLEAN (0 teleports).** The
same-direction trades-only round-trip shows 91 apparent asymmetries; classified by
date, **all 91 are forward-or-same-dated, 0 backward-dated**. Same Round-5/6
decomposition (received-only per-asset display scope + same-timestamp mirror-row
tie-break artifact); 0 links point to a wrong EVENT.

### G5 — Platform-seam-teleport fix re-verify — HOLDS (link + narrative layers)

**Seam-drop link layer.** The 2020→2021 platform seam synthesizes one drop per
holdover player at `2021-08-23`. Full-population scan: **12 seam drops
(`Date dropped/traded` = 2021-08-23), 11 distinct players, exactly 1 player with >1
seam drop** — that's Mitchell Trubisky with his two 2020 waiver adds both closing at
the seam (the documented Round-7 C/D Sleeper duplicate-add pattern, one stint). The
other 10 are clean one-drop holdovers. NOVEL examples verified end-to-end:
- **Wayne Gallman** — added by AceMatthew 2020-12-04, last event
  `2021-08-23: dropped by AceMatthew` — exactly ONE seam drop, no teleport across
  the empty 2021/2022 seasons. Raw tx confirms `Date dropped/traded 2021-08-23`.
- **Giovani Bernard** — multi-stint 2020 churn ending
  `2021-08-23: dropped by AceMatthew` — one clean seam drop, chronologically
  ordered throughout.

**Narrative layer full-population teleport scan (all 649 player + 450 pick history
comments).** **0 chronological inversions** (player 0, picks 0). **5 add→add
(no intervening close) suspects, all 5 SAME-team → 0 cross-team teleports.** Each is
the documented Sleeper duplicate-add pattern (a FA record + a commissioner
correction / re-logged add for the SAME roster stint). NOVEL cases run to ground:
- **Ryan Tannehill** (player_all_time, never previously cited): the flagged
  same-team `stevenb123` add→add pair is the `2021-12-05 / 2022-06-19` re-add
  bracketing a single stint that closes via `2022-06-20: traded to Oliverwkw`; the
  full 2020→2024 narrative is chronologically perfect across 4 owners.
- **Taysom Hill** (lwebs53→lwebs53) — same same-team duplicate-add shape.

The pick-chain sibling-collision fix (698ccea) and the platform-seam-teleport fix
both still hold given everything that changed since Round 6 (the single
retention-rate code-comment edit + the round-7 C/D tooltip-text fixes) — verified
empirically, not assumed.

---

## Part H — Workbook-structural integrity sweep

### H1 — Every sheet opens without corruption — CLEAN
All 13 sheets load via openpyxl with no error; dimensions reconcile to the CSV
populations + 1 header row each: formulas 439×4, player_week 21377×65, player_year
1860×62, player_all_time 650×56, team_week 809×101, team_year 49×127, team_all_time
9×137, league_week 102×59, league_year 7×62, league_all_time 2×55, transactions
1515×56, trades 505×69, picks 451×41. Identical to Round 6 — no drift.

### H2 — Hyperlink target-anchor integrity — CLEAN (0 off-by-one)
Parsed every internal hyperlink directly from each sheet's XML `<hyperlinks>` block
joined to its `.rels` Targets (openpyxl's per-cell `.location` is empty for these
rels-style links, so XML parsing is authoritative).
- **63,292 internal hyperlinks** swept (identical to Round 6). **0 malformed,
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
  col A row≥2, parsed directly from `xl/comments/*.xml`). **0 empty, 0 mojibake**
  (scanned every comment XML for `Ã`/`â€`/`Â`/`ï¿½`/`�`; all valid UTF-8 incl.
  em-dashes and accented names). Identical totals to Round 6.
- **Header-tooltip height fix (900px cap) — HOLDS** against current row counts.
  Read the persisted VML geometry (`xl/drawings/commentsDrawing*.vml`, `<ns1:shape>`
  `style="…;width:…px;height:…px"`, row from `<ns2:Row>`): all **793** header boxes
  are width **460px**, heights **80–620px across 17 distinct values** (per-comment
  line-count sizing, not flat). **0 over the 900px cap, 0 pinned at the cap.**
- **History-hover height (1,100px cap) — HOLDS.** All **1,099** history boxes are
  width **560px**, heights **90–507px across 25 distinct values**, **0 over the
  1,100px cap, 0 pinned at the cap.**
- Box-count reconciles: 793 + 1,099 = **1,892 = total comments** — no orphan or
  missing geometry.

### H4 — Freeze panes / tab colors / auto-filter / conditional-formatting vs CURRENT extent — CLEAN
This is the prompt's specific concern (re-verify against the now-current row counts).
- **Freeze panes:** all 13 correct (formulas `A2`; team_week `F2` = 5-col pin; the
  other 11 `E2` = 4-col pin); all within column extent.
- **Tab colors:** all set per family (player `5B9BD5`, team `70AD47`, league
  `FFC000`, transactions `ED7D31`, trades `7030A0`, picks `808080`, formulas
  `44546A`).
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
- **Column-width full-scan fix** survives: the `min(40, …)` cap holds the longest
  values (e.g. player_all_time col A width 26 for the longest player names; no long
  value under-sized).

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~76s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` (roster-lineage continuity end to end)
  and `test_pick_chain_link_integrity` (the Part-G pick↔trade round-trip guard).
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- **No source changes were needed (no defects).** Build artifacts reverted.

## Conclusion
**Parts G and H are CLEAN at full population — ZERO defects.** Link integrity:
5,651 chain refs + 63,292 hyperlinks all in-range; 0 sibling self-links (698ccea
holds); 0 chronology violations; 0 picks semantic off-by-one; and — crucially —
**0 teleports** (every link asymmetry decomposes into by-design received-only
per-asset display scope or same-event mirror rows, all forward-or-same-dated, never
a wrong/earlier event). The platform-seam-teleport fix holds in BOTH the link layer
(12 clean seam drops, the only multi-drop being Trubisky's documented duplicate-add)
and the narrative-comment layer (0 cross-team add→add teleports; the 5 same-team
suspects are the Sleeper duplicate-add pattern). Workbook structure: all 13 sheets
open clean; the header-tooltip (900px cap, 620px longest) and history-hover
(1,100px cap, 507px longest) geometry fixes are genuinely persisted and unclipped on
the CURRENT workbook; freeze panes, tab colors, auto-filter ranges, and all
conditional-formatting ranges match the current row/column extents exactly. The
single `src/lotg.py` change since the Round-6 G/H baseline is a code-comment text
edit (link-data-inert); the round-7 C/D / E/F work is provably link-data-inert, and
the full-population sweeps confirm it empirically (every count identical to Round 6).
No code change required for Parts G/H this round.
