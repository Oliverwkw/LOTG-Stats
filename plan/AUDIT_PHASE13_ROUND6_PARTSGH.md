# Phase 13 Round 6 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Self-designed full-population audit repeating the Parts G/H methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. This is agent 4 of 5 in Round 6.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `b9afaed` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`b9afaed`, the Round-6
Parts E/F tip — CLEAN, carrying the 2 Round-6 C/D tooltip-text fixes) before any
work, then confirmed `git merge-base --is-ancestor b9afaed HEAD` → `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Reflects all prior fixes:
transactions.csv 1,514, trades.csv 504, picks.csv 450, player_all_time 649,
player_year 1,859.

**Confirmed the C/D fixes are link-data-inert.** `git diff 5d154a7..HEAD` shows the
only source change since the Round-5 tip is `src/formulas.py` (6 lines = the 2
Round-6 C/D tooltip-text fixes); `src/lotg.py` (which generates every link cell,
hyperlink anchor, and comment) is byte-identical to the Round-5 baseline. So the
C/D / E/F round-6 work provably cannot have touched link data — and the
full-population G/H sweeps below confirm it empirically (all clean).

All examples below are NOVEL — different players/teams/picks than every prior
round (deliberately avoiding Josh Doctson, Kenny Pickett, Hunter Henry,
K.J. Osborn, Carter, Stevenson, Pacheco, Jefferson, DJ Moore, Tyler Johnson,
Larry Fitzgerald, Cam Newton, Mike Gesicki, the BROsenzweig/JacobRosenzweig pick
examples, the 2026 2.09 toilet pick, AJ Dillon, Matt Ryan, Tony Pollard,
Mattison, Drake, Meyers, Taysom Hill, Kerryon Johnson, Aaron Jones, Hockenson,
Robbie Chosen, CEH, KJ Hamler, Jalen Guyton, Brady, Brees) except where
Trubisky/Hurst are re-verified as the specifically-requested I/J teleport-fix
check.

**Result: CLEAN — 0 defects found in Parts G or H.** Every link reference is
in-range, chronologically ordered, and round-trip consistent (with the
documented received-scope/mirror-row display artifact decomposed and shown to
contain 0 actual teleports). Every workbook-structural invariant holds against
the CURRENT row counts. No code change required.

---

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

Swept every link column across all three chain-bearing sheets at FULL population:
transactions (1,514 rows × 4 link cols: next/prev × added/dropped player), trades
(504 × 2 per-asset link cols), picks (450 × 2). player_all_time carries its asset
history as hover comments only (verified: 0 `link to …` columns), so it has no
ref-range surface.

### G1 — Reference-range integrity — CLEAN
**5,651 chain references** parsed across all link cells. **0 out-of-range**
(every `#N`/`T#N`/`PH#N` resolves to `1 ≤ N ≤` that sheet's row count: tx 1,514 /
trades 504 / picks 450), **0 malformed/junk tokens**, **0 refs to a missing
sheet**.

### G2 — Pick sibling self-link (the 698ccea fix) — CLEAN
**0 cross-`PH#` sibling links across all 450 picks** — no picks-sheet `Link to
previous/next transaction` cell points at a DIFFERENT picks row. The
full-numbered-identity keying `(year, round, number-within-round, orig)` still
holds. The fix is intact.

### G3 — Chronological ordering — CLEAN
Parsed the `Date` of every dated neighbor referenced by every transactions and
trades link cell (full population, both directions): **0 chronology violations** —
no `next` link points to an earlier-dated event, no `previous` link to a
later-dated one. (`PH#` refs carry no row date — draft-anchor terminals — and are
excluded from the date comparison by construction.)

### G4 — Round-trip consistency

**Pick ↔ trade forward round-trip — CLEAN.** For every pick whose `Link to
previous transaction` is a trade `T#k`, that trade's `Link to next transaction
per asset` echoes this pick's `PH#` — **0 breaks across all 450 picks**. This is
also the invariant the existing `tests/test_pick_chain_links.py` /
`test_pick_chain_link_integrity` guard checks; it passes against the fresh build.

**Transaction add/drop player chain round-trip — CLEAN (cross-column).** Each
player's event chain is a single linked list that spans BOTH the added-player and
dropped-player link columns (an add's "next" event is frequently that same
player's later DROP, stored under the dropped-player columns, and vice versa).
Checked same-column-only, the round-trip shows 864/709 apparent asymmetries — but
checked CROSS-column (a `next` ref in EITHER next column must have a back-pointer
in EITHER prev column), the result is **0 breaks**. Every forward link has a
matching backward link once the add↔drop column hand-off is accounted for. This is
the per-player-chain design, not a teleport.

**Trades per-asset `T#`→`T#` round-trip — CLEAN (0 teleports).** The same-direction
trades-only round-trip shows 91 apparent asymmetries; classified by date, **all 91
point forward-or-same-date** (a legitimate next-event chain step, or a same-event
mirror row of the other participating team) and **0 are backward-dated** (the
teleport signature). This is exactly the Round-5 G/H decomposition (received-only
per-asset DISPLAY scope + same-timestamp mirror-row tie-break artifact); the
underlying `chains` dict is fully bidirectional, only the displayed per-asset
cells are received-scoped. 0 links point to a wrong EVENT.

### G5 — Platform-seam-teleport fix (I/J Round 5, Trubisky/Hurst) re-verify — HOLDS
Both synthesized 2020→2021 transfer drops survive the rebuild intact:
- **Mitchell Trubisky** — exactly **1** `2021-08-23` drop row in transactions.csv
  (LWebs53), and his player_all_time history comment narrates the
  `2021-08-23: dropped by LWebs53` line between the 2020 add and the 2023 same-team
  re-add. No teleport across the empty 2021/2022 seasons.
- **Hayden Hurst** — exactly **1** `2021-08-23` drop row (stevenb123), narrated in
  his history comment.

**Narrative-layer full-population teleport scan (all 649 player + 450 pick history
comments):** **0 chronological inversions**, **0 `added`→`added`-≥2-seasons-later-
with-no-close suspects**. The same-team-re-acquisition-after-a-full-season-void
pattern is fully closed everywhere.

The pick-chain sibling-collision fix (698ccea) and the platform-seam-teleport fix
both still hold given everything that changed since (Round-5's 3 fixes + Round-6's
2 tooltip fixes) — verified, not assumed.

---

## Part H — Workbook-structural integrity sweep

### H1 — Every sheet opens without corruption — CLEAN
All 13 sheets load via openpyxl with no error; dimensions reconcile to the CSV
populations + 1 header row each: transactions **1515**×56, trades **505**×69,
picks **451**×41, player_all_time **650**×56, player_year 1860×62, player_week
21377×65, team_week 809×101, team_year 49×127, team_all_time 9×137, league_week
102×59, league_year 7×62, league_all_time 2×55, formulas 439×4. The +1 rows from
the 2 new I/J synthesized transaction rows (transactions 1514+1 header = 1515) are
present and correct.

### H2 — Hyperlink target-anchor integrity — CLEAN (0 off-by-one)
- **63,292 internal hyperlinks** swept (up from Round-5's 63,280 by the +12
  hyperlinks the 2 new synth-row link cells add). **0 point to a missing sheet, 0
  point out of the target sheet's row range** (`2 ≤ row ≤` that sheet's max_row).
- **Semantic off-by-one** (the after-sort/filter concern): for every picks
  `Link to previous/next transaction` cell, the displayed ref text
  (`T#k`/`PH#k`/`#k`) hyperlinks to exactly `target_sheet!A{k+1}` (the row whose
  index IS k, accounting for the header) — **0 mismatches across all 450 picks**.
  No off-by-one survived the auto-filter applied to every sheet.

### H3 — Comment encoding & box geometry — CLEAN (re-verifies the formatting fixes)
- **1,892 comments** (793 header tooltips + 1,099 asset-history hovers, parsed
  directly from `xl/comments/*.xml`). **0 empty**, **0 mojibake** (scanned every
  comment XML for `Ã`/`â€`/`Â`/`ï¿½`/`�`; all valid UTF-8 incl. em-dashes and
  accented names).
- **Header-tooltip height fix (900px cap, summed-wrapped-line-count height) —
  HOLDS** against the current row counts. Read the persisted VML geometry
  (`xl/drawings/*.vml`, units in px): all **793** header boxes are width 460px,
  heights **80–620px across 17 distinct values** (per-comment line-count sizing,
  not flat). **0 over the 900px cap, 0 pinned at the cap.** The longest column
  definition (the 2,244-char `O-Score` tooltip) sizes to exactly **620px** —
  whole, not clipped (the old 520px cap would have truncated it).
- **History-hover height (1,100px cap) — HOLDS.** All **1,099** history boxes are
  width 560px, heights **90–507px across 25 distinct values**, **0 over the
  1,100px cap, 0 pinned at the cap**.
- Box-count reconciles: 793 + 1,099 = **1,892 = total comments** — no orphan or
  missing geometry. The 2 new I/J synth-row history comments are included and
  size correctly.

### H4 — Column-width / freeze panes / tab colors / auto-filter / conditional-
formatting vs CURRENT extent — CLEAN
This is the prompt's specific concern (re-verify against the now-current row
counts: trades 504, the 2 new synthesized transaction rows, etc.):
- **Freeze panes:** all 13 correct (`formulas` A2; `team_week` F2 = 5-col pin;
  the other 11 E2 = 4-col pin); all within column extent.
- **Tab colors:** all set per family (player `5B9BD5`, team `70AD47`, league
  `FFC000`, transactions `ED7D31`, trades `7030A0`, picks `808080`, formulas
  `44546A`).
- **Auto-filter ranges:** every data sheet's filter == `A1:{maxcol}{maxrow}`
  spanning EXACTLY the current extent — **0 mismatches** (formulas correctly has
  none). E.g. trades `A1:BQ505`, transactions `A1:BD1515`, picks `A1:AO451`,
  player_all_time `A1:BD650` — all track the current (post-I/J) row counts.
- **Conditional-formatting (color-scale) ranges:** every headline range spans
  exactly `2:max_row` and **0 ranges exceed the sheet extent** — incl. the grown
  **trades `AE2:AE505`** (504 rows + header), **transactions `AH2:AH1515`** (the
  +2 synth rows reflected), **picks `V2:V451`**, **player_all_time `AF2:AF650`**,
  `player_week L2:L21377`, etc. Not stale-short, not stale-long — the CF/filter
  extents track the round-6 row counts precisely.
- **Column-width full-scan fix** (scans every data row, `min(40, max(10,
  maxlen+2))`) survives the current larger sheets — verified no long value is
  under-sized.

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~60s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` (roster-lineage continuity end to
  end — confirms the 2 I/J synth drops don't break continuity) and
  `test_pick_chain_link_integrity` (the Part-G pick↔trade round-trip guard).
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- **No source changes were needed (no defects).** Build artifacts reverted.

## Conclusion
**Parts G and H are CLEAN at full population — ZERO defects.** Link integrity:
5,651 chain refs + 63,292 hyperlinks all in-range; 0 sibling self-links (698ccea
holds); 0 chronology violations; 0 picks semantic off-by-one; and — crucially —
**0 teleports** (every link asymmetry decomposes into by-design cross-column
chain hand-off, received-only per-asset display scope, or same-event mirror-row
references, all forward-or-same-dated, never a wrong/earlier event). The Round-5
platform-seam-teleport fix (Trubisky, Hurst) holds in both the link layer and the
narrative-comment layer. Workbook structure: all 13 sheets open clean; the
header-tooltip (900px cap, 620px longest) and history-hover (1,100px cap, 507px
longest) geometry fixes are genuinely persisted and uncipped on the CURRENT
workbook; freeze panes, tab colors, auto-filter ranges, and all
conditional-formatting ranges match the round-6 row/column extents exactly
(trades AE2:AE505, transactions AH2:AH1515 reflecting the 2 new synth rows). The
Round-6 C/D tooltip-text fixes are provably link-data-inert (only `src/formulas.py`
changed; `src/lotg.py` unchanged from the Round-5 baseline) and the empirical
full-population sweeps confirm it. No code change required for Parts G/H this round.
