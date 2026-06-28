# Phase 13 Round 9 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Self-designed full-population audit repeating the Parts G/H methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 4 of 5 in Round 9 (siblings: Parts A/B —
`AUDIT_PHASE13_ROUND9_PARTSAB.md` — CLEAN at `642f111`; Parts C/D —
`AUDIT_PHASE13_ROUND9_PARTSCD.md` — found+fixed 2 tooltip-text 2020-startup-draft
label defects in `src/formulas.py` at `133d85e` — the shared `O-Score` Notes and
the picks `Number of trades` Notes, both mislabelling the inaugural **2020** ESPN
startup draft as a "2021" event; Parts E/F — `AUDIT_PHASE13_ROUND9_PARTSEF.md` —
CLEAN at `cafa982`, confirming the underlying N/A-vs-0 DATA those two corrected
tooltips describe was already correct).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `git merge-base --is-ancestor cafa982 HEAD`
did NOT print OK — `cafa982` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`cafa982`, the Round-9 Parts E/F tip
carrying all Round-4..Round-8 fixes + the 2 Round-9 C/D tooltip fixes), then
confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: picks 450,
trades 504, transactions 1,514, player_all_time 649.

**Confirmed the changes-since-Round-8-G/H are link-data-inert.** The Round-8 G/H
sweep was CLEAN at `965a21c`. `git diff 965a21c..HEAD -- src/` shows the ONLY
source change since that baseline is the **2 Round-9 C/D tooltip-TEXT edits** in
`src/formulas.py` (the `O-Score` Notes and the picks `Number of trades` Notes — both
pure header-tooltip TEXT). `src/lotg.py` — which generates every link cell,
hyperlink anchor, and comment box — is **byte-identical** (`git diff 965a21c..HEAD
-- src/lotg.py` is empty). So the link layer, hyperlink anchors, and comment
geometry are functionally identical to the Round-8 G/H baseline — and the
full-population sweeps below confirm it empirically (every link/hyperlink count is
identical to Round 8). The ONE structural delta is in H3: the corrected (longer)
`O-Score` tooltip TEXT grew its header comment box from 620px → 668px — still far
under the 900px cap, 0 pinned/clipped (i.e. the geometry correctly tracks the new
text length; see H3 below).

All examples below are NOVEL — different players/teams/picks than every prior round
(Rounds 4-9 Parts A/B/C/D/E/F + prior G/H exclusion lists honoured; deliberately
avoiding the long named list incl. the prior G/H seam anchors Wayne Gallman /
Giovani Bernard / Lynn Bowden / Travis Fulgham / Kyle Rudolph / Mitchell Trubisky /
Hayden Hurst, the prior pick anchors Marquise Brown 1.02 / Trevor Lawrence 1.03 /
Damien Harris vet 1.03, and Ryan Tannehill / Taysom Hill / Ameer Abdullah / Deuce
Vaughn as narrative examples). New surfaces cited here: the **2024 pick chain
2026 2.09 toilet-future** received-scope decomposition example is avoided (prior
round); instead **picks row 215 received-scope** worked example; the **Dexter
Williams / Tyron Billy-Johnson / Anthony McFarland / Brian Hill / Malcolm Brown**
novel platform-seam holdovers (the latter a rich multi-stint chain); and the
**668px O-Score header box** as the H3 geometry surface.

**Result: CLEAN — 0 defects found in Parts G or H.** Every link reference is
in-range, chronologically ordered, and round-trip consistent (the only link
asymmetries decompose into by-design received-only per-asset display scope and
same-event mirror rows — all forward-or-same-dated, 0 teleports). Every
workbook-structural invariant holds against the CURRENT row counts. The pick-chain
sibling-collision fix (698ccea) and the platform-seam-teleport fix both still hold
— verified empirically with fresh examples, not assumed. No code change required.

---

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

Swept every link column across all chain-bearing sheets at FULL population from the
canonical CSVs: transactions (1,514 × 4 link cols: next/prev × added/dropped
player), trades (504 × 2 per-asset link cols), picks (450 × 2). player_all_time
carries its asset history as hover comments only (verified: **0** `Link to …`
columns) — no ref-range surface.

Link cells are `;`-separated token lists; each token is `#N` (→transactions),
`T#N` (→trades), `PH#N` (→picks), or the literal `N/A` per-asset no-link
placeholder. Splitting strictly on `;` and treating `N/A` as a valid no-link token
is the correct parse — confirmed by enumerating every distinct non-`#`-shaped
token: only `N/A` appears (3,281 occurrences across all 8 link columns; this counts
the per-asset `N/A` placeholders in multi-asset cells, a superset of Round-8's
254-cell figure which counted whole-cell `N/A`s — same semantics, finer granularity).

### G1 — Reference-range integrity + malformed scan — CLEAN
**5,651 chain references** parsed across all 8 CSV link cells. **0 out-of-range**
(every `#N`/`T#N`/`PH#N` resolves to `1 ≤ N ≤` that sheet's row count: tx 1,514 /
trades 504 / picks 450), **0 malformed/junk tokens**, **0 refs to a missing sheet**.
The 5,651 total is **identical to Rounds 6/7/8** — confirms the link layer is
unchanged. Per-CSV-link-column ref counts: tx next-added 1,003 / prev-added 750 /
next-dropped 762 / prev-dropped 1,162; trades next 746 / prev 831; picks next 274 /
prev 123. (The trades next/prev per-column counts are at the CANONICAL CSV level;
the Round-8 doc's 894/937 were measured on the xlsx, which carries 28 extra computed
link/display columns beyond the 41 CSV columns — the canonical 5,651 grand total is
identical either way.)

### G2 — Pick sibling self-link (the 698ccea fix) — CLEAN / HOLDS
**0 cross-`PH#` sibling links across all 450 picks** — no picks-sheet `Link to
previous/next transaction` cell points at a DIFFERENT picks row (0 `PH#` tokens in
either picks link column). The full-numbered-identity keying still holds. The fix is
intact.

### G3 — Chronological ordering — CLEAN
Parsed the `Date` of every dated neighbor referenced by every transactions and
trades link cell (full population, both directions, all 4 tx link cols + both trade
cols): **4,692 neighbor-date comparisons, 0 chronology violations** — no `next` link
points to an earlier-dated event, no `previous` link to a later-dated one. (`PH#`
refs carry no row date — draft-anchor terminals — and are excluded from the date
comparison by construction.)

### G4 — Round-trip consistency

**G4a — Pick ↔ trade forward round-trip — CLEAN.** For every pick whose `Link to
previous transaction` is a trade `T#k` (**123 such picks**), that trade's `Link to
next transaction per asset` echoes this pick's `PH#` — **0 breaks**. This is also
the invariant the existing `test_pick_chain_link_integrity` guard checks; it passes
against the fresh build.

**G4a' — Pick `next`=T#k vs trade-k `prev` — 86 received-scope display artifacts,
0 teleports.** The reverse direction (a pick's `next`=T#k should be echoed by trade
k's per-asset `previous`) shows **86 apparent non-echoes**. I classified each by an
independent **acquisition-date test** (the pick's `next`-trade date vs the latest
date among the pick's `prev`-trades): **all 86 are forward-or-same-dated, 0
backward-dated** (the teleport signature). This is the documented received-only
per-asset DISPLAY scope: a pick's `next` link points to the deal where the pick / its
drafted player was traded AWAY, but the trade row's per-asset `previous` cells
display the RECEIVED side, so they don't echo back the sent pick — by design, not a
wrong-event link. The underlying `chains` dict is fully bidirectional; only the
displayed per-asset cells are received-scoped. (86 is identical to Rounds 6/7/8.)

**G4b — Transaction add/drop player chain round-trip — CLEAN (cross-column).** Each
player's event chain is a single linked list spanning BOTH the added-player and
dropped-player link columns (an add's `next` is frequently that player's later DROP,
stored under the dropped-player columns). Checked CROSS-column (a `#`-`next` ref in
EITHER next column must have a back-pointer in EITHER prev column of the target):
**1,625 next-# refs checked, 0 breaks** across all 1,514 transactions. Every forward
link has a matching backward link once the add↔drop column hand-off is accounted for.

**G4c — Trades per-asset `T#`→`T#` round-trip — CLEAN (0 teleports).** The
same-direction trades-only round-trip shows **91 apparent asymmetries**; classified
by date, **all 91 are forward-or-same-dated, 0 backward-dated**. Same Round-5/6/7/8
decomposition (received-only per-asset display scope + same-timestamp mirror-row
tie-break artifact); 0 links point to a wrong EVENT. (91 is identical to Rounds
6/7/8.)

### G5 — Platform-seam-teleport fix re-verify — HOLDS (link + narrative layers)

**Seam-drop link layer.** The 2020→2021 platform seam synthesizes one drop per
holdover player at `2021-08-23 20:00:00`. Full-population scan: **12 seam-drop rows
(`Date dropped/traded` = 2021-08-23)**, each identified by the HOLDOVER it carries in
its `Player Added` column. The 12 added-holdovers are 11 distinct players —
**exactly 1 player with >1 seam-drop row**, Mitchell Trubisky (rows 447 & 459, his
two 2020 waiver adds both closing at the seam — the documented Sleeper duplicate-add
pattern, one stint). The other 10 are clean one-holdover-each rows. (The 3 `N/A`
values seen in `Player Dropped` on the seam rows are simply rows whose seam-drop
ADDED a holdover without dropping anyone in the same record — not a defect; the
seam-drop subject is the ADDED holdover.) NOVEL holdovers verified end-to-end against
both transactions.csv and the player_all_time narrative comment — each begins with a
2020 add and ends with **exactly ONE** `2021-08-23: dropped` seam event,
chronologically ordered, no teleport across the empty 2021/2022 seasons:
- **Anthony McFarland** (plehv79) — `2020-09-30: added by plehv79 (free agent;
  dropped Ryan Tannehill)` → `2021-08-23: dropped by plehv79`. One clean seam drop.
- **Brian Hill** (plehv79) — `2020-11-27: added by plehv79 (free agent)` →
  `2021-08-23: dropped by plehv79`. One clean seam drop.
- **Dexter Williams** (LWebs53) — `2020-12-24: added by LWebs53 (free agent; dropped
  Tre'Quan Smith)` → `2021-08-23: dropped by LWebs53`. One clean seam drop.
- **Tyron Billy-Johnson** (Oliverwkw) — `2020-12-27: added by Oliverwkw (free agent)`
  → `2021-08-23: dropped by Oliverwkw`. One clean seam drop.
- **Malcolm Brown** (shmuel256) — a rich MULTI-STINT chain, all chronological with a
  single seam exit: `2020-09-12: added by shmuel256 (free agent)` → `2020-09-15:
  traded to Oliverwkw (Oliverwkw got Malcolm Brown; Denzel Mims; sent Justin
  Jefferson; DeVante Parker)` → `2020-12-23: dropped by Oliverwkw` → `2020-12-23:
  added by shmuel256 (free agent; dropped Todd Gurley)` → `2021-08-23: dropped by
  shmuel256`. The holdover's own seam drop is the single 2021-08-23 line at the end;
  the earlier trade + re-add are all 2020-dated and in order — no teleport.

**Narrative layer full-population teleport scan (all 649 player + 450 pick history
comments).** **0 chronological inversions** (player 0, picks 0). **5 add→add
(no intervening close) suspects, all 5 SAME-team → 0 cross-team teleports.** Each is
the documented Sleeper duplicate-add pattern (a FA record + a commissioner
correction / re-logged add for the SAME roster stint). The 5 map to exactly the
prior-round-documented players — **Ameer Abdullah (stevenb123), Deuce Vaughn
(BROsenzweig), Mitchell Trubisky (LWebs53), Ryan Tannehill (stevenb123), Taysom Hill
(LWebs53)** — stable count/identity vs Round 7/8, 0 NEW cross-team teleport surfaced.
**0 history comments carry any `#`/`T#`/`PH#` ref token** (the narratives are
plain-English).

The pick-chain sibling-collision fix (698ccea) and the platform-seam-teleport fix
both still hold given everything that changed since Round 8 (the 2 Round-9 C/D
tooltip-text edits) — verified empirically with fresh examples, not assumed.

---

## Part H — Workbook-structural integrity sweep

### H1 — Every sheet opens without corruption — CLEAN
All **13 sheets** load via openpyxl with no error. Dimensions reconcile to the CSV
populations + 1 header row each for the 11 row-mirrored data sheets: player_week
21377×65, player_year 1860×62, player_all_time 650×56, team_week 809×101, team_year
49×127, team_all_time 9×137, league_week 102×59, league_year 7×62, league_all_time
2×55, transactions 1515×56, picks 451×41. The two non-1:1 sheets are by-design and
stable vs Round 7/8: **formulas** is a 439×4 definitions reference (not a CSV mirror),
and **trades** is 505×69 (the xlsx carries 28 extra computed link/display columns
beyond the 41 CSV columns). **All dimensions byte-identical to Round 8.** No drift.

### H2 — Hyperlink target-anchor integrity — CLEAN (0 off-by-one)
Parsed every internal hyperlink directly from each sheet's XML `<hyperlinks>` block
joined to its `.rels` Targets (openpyxl's per-cell `.location` is empty for these
rels-style links, so XML parsing is authoritative).
- **63,292 internal hyperlinks** swept (identical to Rounds 6/7/8). **0 malformed,
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
  incl. em-dashes and accented names). Totals identical to Rounds 6/7/8.
- **Header-tooltip height fix (900px cap) — HOLDS** against current row counts.
  Read the persisted VML geometry (`xl/drawings/commentsDrawing*.vml`,
  `<ns1:shape>` `style="…;width:…px;height:…px"`, row from `<ns2:Row>`): all **793**
  header boxes are width **460px**, heights **80–668px across 17 distinct values**
  (per-comment line-count sizing, not flat). **0 over the 900px cap, 0 pinned at
  the cap.**
  - **The longest header box is now 668px (was 620px in Rounds 6/7/8).** This is the
    `O-Score` tooltip (picks col 22), the single longest column definition: its TEXT
    grew from 2,244 → **2,402 chars** because the Round-9 C/D fix rewrote its Notes
    ("…the two non-rookie drafts (the 2020 ESPN startup draft and the 2021
    supplemental veteran draft) are scored only in their OWN percentile pool…"). The
    box geometry correctly tracked the longer text (620→668px) and the comment ends
    with the full corrected sentence "…in practice every one of those rows ends up
    N/A. Percentiles are within each sheet (picks vs picks, etc.)." — **not clipped,
    not pinned, 232px of headroom under the 900px cap.** This is the expected,
    correct behaviour and confirms the Round-9 C/D text fix is fully persisted and
    rendered whole.
- **History-hover height (1,100px cap) — HOLDS.** All **1,099** history boxes are
  width **560px**, heights **90–507px across 25 distinct values**, **0 over the
  1,100px cap, 0 pinned at the cap** (unchanged from Rounds 6/7/8 — the C/D edits
  touched only header tooltips, not history hovers).
- Box-count reconciles: 793 + 1,099 = **1,892 = total comments** — no orphan or
  missing geometry.

### H4 — Freeze panes / tab colors / auto-filter / conditional-formatting vs CURRENT extent — CLEAN
This is the prompt's specific concern (re-verify against the now-current row counts).
- **Freeze panes:** all 13 correct (formulas `A2`; team_week `F2` = 5-col pin; the
  other 11 `E2` = 4-col pin); all within column extent.
- **Tab colors:** all set per family (player `5B9BD5`, team `70AD47`, league
  `FFC000`, transactions `ED7D31`, trades `7030A0`, picks `808080`, formulas
  `44546A`; the `00` ARGB prefix is the alpha channel).
- **Auto-filter ranges:** every data sheet's filter == `A1:{maxcol}{maxrow}`
  spanning EXACTLY the current extent — **0 mismatches** (formulas correctly has
  none). E.g. trades `A1:BQ505`, transactions `A1:BD1515`, picks `A1:AO451`,
  player_all_time `A1:BD650`, player_week `A1:BM21377`, team_week `A1:CW809`,
  team_year `A1:DW49`, team_all_time `A1:EG9`, league_week `A1:BG102`,
  league_year `A1:BJ7`, league_all_time `A1:BC2`, player_year `A1:BJ1860`.
- **Conditional-formatting (color-scale) ranges:** every range spans exactly
  `2:max_row` and **0 ranges exceed the sheet extent** — player_week `L2:L21377`,
  player_year `AH2:AH1860`, player_all_time `AF2:AF650`, team_week `I2:I809`,
  team_year `D2:D49`, team_all_time `B2:B9`, transactions `AH2:AH1515`, trades
  `AE2:AE505`, picks `V2:V451`. Not stale-short, not stale-long — tracks the
  current row counts precisely (all identical to Round 8).

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~79s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` (roster-lineage continuity end to end)
  and `test_pick_chain_link_integrity` (the Part-G pick↔trade round-trip guard).
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- **No source changes were needed (no defects).** Build artifacts reverted
  (`git checkout -- exports/`; `git clean -fd exports/ .cache/`); `git status`
  clean except this findings file.

## Conclusion
**Parts G and H are CLEAN at full population — ZERO defects.** Link integrity:
5,651 chain refs + 63,292 hyperlinks all in-range; 0 sibling self-links (698ccea
holds); 0 chronology violations (4,692 neighbor-date checks); 0 picks semantic
off-by-one; and — crucially — **0 teleports** (every link asymmetry decomposes into
by-design received-only per-asset display scope (86 picks + 91 trades) or same-event
mirror rows, all forward-or-same-dated by an independent acquisition-date test, never
a wrong/earlier event). The platform-seam-teleport fix holds in BOTH the link layer
(12 clean seam-drop rows, the only multi-row being Trubisky's documented duplicate
add — verified with NOVEL holdovers Anthony McFarland, Brian Hill, Dexter Williams,
Tyron Billy-Johnson, and the rich multi-stint Malcolm Brown) and the
narrative-comment layer (0 cross-team add→add teleports; the 5 same-team suspects are
the stable Sleeper duplicate-add pattern). Workbook structure: all 13 sheets open
clean; the header-tooltip (900px cap, now-668px longest after the Round-9 C/D O-Score
text grew — 232px headroom, 0 pinned/clipped) and history-hover (1,100px cap, 507px
longest) geometry fixes are genuinely persisted and unclipped on the CURRENT
workbook; freeze panes, tab colors, auto-filter ranges, and all
conditional-formatting ranges match the current row/column extents exactly. The only
source change since the Round-8 G/H baseline is the 2 Round-9 C/D tooltip-TEXT edits
(`src/lotg.py` byte-identical); they are provably link-data-inert and their ONE
visible structural effect — the O-Score header box growing 620→668px to fit the
corrected longer text — is itself correct and within cap. No code change was required
for Parts G/H this round.
