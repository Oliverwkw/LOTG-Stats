# Phase 13 Round 5 — Parts G+H (asset-chain link integrity + workbook-structural integrity)

Self-designed full-population audit repeating the Parts G/H methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Worktree self-verified — the recurring
stale-worktree environment bug recurred (HEAD landed at `6d83635`, behind the
branch tip; origin tip was `4ff269d`, the just-landed Parts E/F fix). Hard-reset
to `origin/claude/phase-13-audit-tsapoy` (`4ff269d`) before any work, then
confirmed `git merge-base --is-ancestor 4ff269d HEAD` → OK_AT_OR_AHEAD.

Build under audit: fresh offline build (`scripts/offline_build.py`, exit 0; only
the expected `api.sleeper.app` / `espn_2020_draft` network-unavailable warnings)
— NOT a stale cache. Fresh export reflects both prior round-5 fixes: trades.csv
504 rows (post Parts A/B wash fix), picks.csv 450, transactions.csv 1,512,
player_all_time 649.

All examples below are NOVEL — different players/teams/picks than every prior
round (avoiding Josh Doctson, Kenny Pickett, Hunter Henry, K.J. Osborn, Carter,
Stevenson, Pacheco, Jefferson, DJ Moore, Tyler Johnson, Larry Fitzgerald, Cam
Newton, Mike Gesicki, the BROsenzweig/JacobRosenzweig 5.xx pick examples, the
2026 2.09 toilet pick) except where the 4 wash-fix-surfaced trades are checked
specifically as their own genuinely-novel link surface.

**Result: CLEAN — 0 defects found in Parts G or H.** Three apparent
link-asymmetries and one comment-geometry concern were each run to ground and
shown to be correct/by-design behavior. No code change required.

---

## Part G — Asset-chain link integrity at full scale (no-teleport, exhaustive)

### Reference-range integrity — CLEAN
Every `PH#`/`T#`/`#` reference in every link column across all three
chain-bearing sheets, full population (transactions 1,512 × 4 link cols, trades
504 × 2, picks 450 × 2): **0 out-of-range refs**, **0 refs to a missing sheet**.
player_all_time carries its asset history as hover comments only (no link
columns), so it has no ref-range surface — confirmed by inspecting its column
set.

### Sibling self-links (the 698ccea fix) — CLEAN
**0 sibling self-links across all 450 picks** — no picks-sheet `Link to
previous/next transaction` points at a DIFFERENT picks row. The
`(year, round, number-within-round, orig)` full-numbered-identity keying still
holds. NOVEL spot-confirm: **PH#123 = 2023 4.03 (J. Reed), orig AceMatthew**
correctly resolves `prev = T#325` (shmuel256's 2021-10-18 receipt of that pick),
not a same-owner sibling; **PH#114 = 2023 3.02 (J. Hyatt)** and the 2025 round-2
sibling cluster (PH#169/174/175/177/180 — Egbuka/Skattebo/Burden/T. Harris/Bech)
each resolve to their own distinct trade with no cross-bucket collision.

### Chronological ordering — CLEAN
Parsed the `Date` of every `T#`/`#` neighbor referenced by every transactions
and trades link cell (full population): **0 chronology violations** — no `next`
link points to an earlier-dated event, no `prev` link to a later-dated one.
(PH# refs carry no row date — they are draft-anchor terminals/starts — so they
are excluded from the date comparison by construction.)

### Round-trip consistency — CLEAN (0 teleports)
- **Pick ↔ trade forward round-trip:** for every pick whose `Link to previous
  transaction` is a trade `T#k`, that trade's `next-per-asset` echoes this pick's
  `PH#` — **0 breaks** across all 450 picks. (This is the invariant the existing
  `tests/test_pick_chain_links.py` guard checks; it passes against the fresh
  build.)
- **Player-chain round-trip, full population (472 directed link pairs
  examined):** decomposed exhaustively into:
  - **276** = display-scope sent-side: the back-reference target trade carries
    the player only on its **Assets sent** side, so its per-asset (received-only,
    by design — `src/lotg.py` ~line 15563) display columns correctly carry no
    entry for that player. The underlying `chains` dict is fully bidirectional
    (built from both received AND sent + tx add/drop); only the *displayed*
    per-asset cells are received-scoped.
  - **196** = same-event mirror-row: the back-pointer lands on a *different
    mirror row of the SAME trade event* (identical date/deal — e.g. William
    Fuller's 2020-10-07 Aiyuk-swap, where AceMatthew's drop `#48` points back to
    plehv79's mirror `T#257` rather than AceMatthew's own `T#2`). The link lands
    on the correct EVENT, just the other participating team's row.
  - **0** = different-event teleports.

  So **0 links point to a wrong event**. The mirror-row asymmetry is the
  pre-existing stable-sort tie-break artifact explicitly accepted in Round-2
  (two same-timestamp mirror rows are interchangeable references to one deal);
  no teleport, no fabricated link.

### The 4 wash-fix trades as a novel link surface — checked, CLEAN, NO picks involved
Per the prompt's specific instruction, verified whether any of the 4 trades that
newly survive after the Parts A/B commissioner-wash fix involved **draft picks**
(which would be a genuinely-novel pick-chain link case checked in no prior
export). They do **NOT**:

| Wash-fix trade (tid) | Date | Assets | Pick involved? |
|---|---|---|---|
| Josh Doctson (903835630847717376) | 2022-11-30 | Josh Doctson ↔ $1 FAAB | No (FAAB only) |
| Kenny Pickett one-way (1126272571940544512) | 2024-08-05 | Kenny Pickett → LWebs53 | No (player only) |
| Hunter Henry (1142929980331048960) | 2024-09-20 | Hunter Henry → AceMatthew | No (player only) |
| K.J. Osborn ↔ Pickett (1142924638763274240) | 2024-09-20 | K.J. Osborn ↔ Kenny Pickett | No (players only) |

All four are player/FAAB-only swaps, so they introduced **no new pick-chain
links** — the 698ccea sibling-collision fix surface is unchanged by the A/B
fix. (NB: the separate 2024-09-18 Hunter-Henry-for-`2026 4(Oliverwkw)` trade
— picks.csv rows 176/235 — is a *different, pre-existing* trade that was never
wash-deleted; its pick link is unaffected.) Their player-chain links were
nonetheless verified internally consistent: e.g. `T#172` (LWebs53 recv Kenny
Pickett, 2024-08-05) `prev-per-asset = PH#75` (his draft-pick origin) and
`next = #279`; `T#81` (BROsenzweig recv K.J. Osborn) `prev = T#454`; `T#55`
(BROsenzweig recv Josh Doctson) `next = #213`. Per-asset link-list length aligns
1:1 with received-asset count for every trade that received ≥1 chainable asset
(0 misalignments; the only "N/A-recv" rows correctly show literal `N/A` link
cells).

---

## Part H — Workbook-structural integrity sweep

### Every sheet opens without corruption — CLEAN
All 13 sheets load via openpyxl with no error; dimensions reconcile to the CSV
populations + 1 header row each (transactions 1513, trades 505, picks 451,
player_all_time 650, player_week 21377, team_week 809, …).

### Hyperlink target-anchor integrity — CLEAN (0 off-by-one)
- **63,280 internal hyperlinks** swept. **0 point to a missing sheet, 0
  point out of the target sheet's row range** (≥2, ≤ that sheet's max_row).
- **Semantic anchor correctness** (the off-by-one-after-sort concern): for every
  picks `Link to previous/next transaction` cell, the displayed ref text
  (`T#k`/`PH#k`/`#k`) hyperlinks to exactly `target_sheet!A{k+1}` — the row whose
  index IS k — **0 mismatches**. For 1,075 transactions `Player Added` name
  links, each resolves to the correct `player_all_time` row for that exact name
  — **0 mismatches**. No off-by-one survived the auto-filter applied to every
  sheet.

### Comment encoding & box geometry — CLEAN (re-verifies the just-landed fixes)
- **1,892 comments** total (793 header tooltips + 1,099 asset-history hovers).
  **0 garbled/mojibake**, **0 empty** — all valid UTF-8 including em-dashes and
  accented names; the `_bold_comment_verbs` rich-text rewrite (which touches only
  `xl/comments/commentN.xml`, leaving the VML geometry verbatim) preserves
  encoding and box size.
- **Header-tooltip height fix (900px cap, summed-wrapped-line-count height) —
  HOLDS.** Read the actual persisted VML shape geometry
  (`xl/drawings/commentsDrawingN.vml`, `width:Wpx;height:Hpx`): all **793**
  header boxes are width 460px, heights span **80–620px** across **17 distinct
  values** (confirming per-comment line-count sizing, not a flat height).
  **0 boxes exceed the 900px cap, 0 pinned at the cap** — the longest column
  definition (the 2,244-char `O-Score` tooltip at `transactions!AH1`) sizes to
  exactly **620px**, matching the code formula `min(900, max(80, 16·nl + 12))`
  with `nl = 38` wrapped rows at 62 chars/row. The old 520px cap would have
  clipped it; under the 900 cap it is whole.
- **History-hover height — HOLDS.** All **1,099** history boxes are width 560px,
  heights **90–507px** across **25 distinct values**, **0 over the 1,100px cap**.
- Box-count reconciles: 793 + 1,099 = 1,892 = total comments (no orphan/missing
  geometry).

### Column-width full-scan fix — HOLDS on the now-larger sheets
The width pass scans EVERY data row (`ws.iter_rows`, not the old first-200
window) and sets `min(40, max(10, maxlen+2))`. Verified the fix survives the
wash-fix's larger trades sheet — no long value past the old window is
under-sized; widths are computed from the full extent.

### Freeze panes / tab colors / conditional-formatting ranges vs CURRENT extent — CLEAN
This is the prompt's specific concern (these formatting fixes landed before
round 5 and hadn't been re-verified against the wash-fix's now-different row
counts):
- **Freeze panes:** all 13 correct for their pin count (`formulas` A2,
  `team_week` F2 = 5-col pin, the other 11 E2 = 4-col pin); all within column
  extent.
- **Tab colors:** all set per family (player=`5B9BD5`, team=`70AD47`,
  league=`FFC000`, transactions=`ED7D31`, trades=`7030A0`, picks=`808080`,
  formulas=`44546A`).
- **Auto-filter ranges:** every data sheet's `A1:{maxcol}{maxrow}` spans exactly
  the current extent — **0 mismatches** (formulas sheet correctly has none).
- **Conditional-formatting ranges:** **0 ranges extend past the sheet extent**,
  and every headline color-scale range spans exactly `2:max_row` — including the
  grown **trades `AE2:AE505`** (the full 504 wash-fix rows + header),
  `transactions AH2:AH1513`, `picks V2:V451`, `player_week L2:L21377`, etc.
  Not stale-short, not stale-long — the CF/filter extents track the round-5
  row counts precisely.

---

## Verification
- `pytest tests/ -q`: **15 passed** in ~76s (incl. the full-build
  `test_player_history_continuity` and the `test_pick_chain_link_integrity`
  Part-G guard, both green against the fresh build).
- Offline build: exit 0, only the expected network-unavailable warnings.
- Build artifacts reverted; `git status` clean except this new file.

## Conclusion
**Parts G and H are CLEAN at full population.** Link integrity: 63,280
hyperlinks + every PH#/T#/# chain ref in-range, semantically correct anchors
(0 off-by-one), 0 sibling self-links, 0 chronology violations, and — crucially
— **0 teleports** (every one of 472 player-link asymmetries decomposes into
by-design received-only display scope or same-event mirror-row references, never
a wrong event). The 698ccea sibling-collision keying still holds; the 4
wash-fix-surfaced trades involve no draft picks, so they introduce no new
pick-chain links. Workbook structure: all 13 sheets open clean; the just-landed
header-tooltip height fix (900px cap, line-count sizing) and column-width
full-scan fix are genuinely persisted in the VML geometry and correct on the
CURRENT rebuilt workbook (longest header tooltip = exactly 620px, no clipping);
freeze panes, tab colors, auto-filter ranges, and all conditional-formatting
ranges match the round-5 wash-fix's now-different row/column extents exactly.
No code change required.
