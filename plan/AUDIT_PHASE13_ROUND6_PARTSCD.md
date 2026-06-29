# Phase 13 Round 6 — Parts C+D (header-comment accuracy + asset-history narrative accuracy)

Self-designed full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. This is agent 2 of 5 in Round 6.

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `81ef7e6` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`81ef7e6`, the Round-6
Parts A/B tip — CLEAN) before any work, then confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Reflects all prior fixes:
transactions.csv 1,514, trades.csv 504, picks.csv 450, player_all_time 649,
player_year 1,859.

All examples below are NOVEL — different columns/players/teams/picks than every
prior round (deliberately avoiding Josh Doctson, Kenny Pickett, Hunter Henry,
K.J. Osborn, Carter, Stevenson, Pacheco, Jefferson, DJ Moore, Tyler Johnson,
Larry Fitzgerald, Cam Newton, Mike Gesicki, the BROsenzweig pick examples, the
2026 2.09 toilet pick, Trubisky/Hurst as *new findings* — they are re-verified
here only as the specifically-requested I/J-synth-drop narrative check —
AJ Dillon, Matt Ryan, Tony Pollard, Mattison, Drake, Meyers, Taysom Hill,
Kerryon Johnson, Aaron Jones, T.J. Hockenson, Robbie Chosen, CEH, KJ Hamler,
Jalen Guyton; and avoiding the Round-4 `Hardship` tooltip already fixed).

**Result: 2 real doc/code-drift defects found and FIXED** (both in
`src/formulas.py` tooltip text — Part C). Part D is fully CLEAN at full
population, including the specifically-requested re-verification that the two
I/J-synthesized drop events (Trubisky, Hurst) are now correctly narrated.

---

## Part C — Header-comment (column-tooltip) accuracy sweep

Resolved every header tooltip in the built workbook exactly as the build does
(`formulas.column_definitions()`, `(sheet, normcol)` per-sheet key first then
`(None, normcol)` global fallback; `IDENTITY_ALLOWLIST` columns skipped) and
diffed against the comment text actually attached to each header cell across all
12 data sheets.

### Coverage / attachment / misattachment — CLEAN
- **793** header comments attached. **0 MISSING** (every documented non-identity
  column carries its tooltip), **0 MISMATCHED** (every attached comment's text
  equals the expected per-sheet/global definition byte-for-byte), **0 UNEXPECTED**
  (no comment on an identity/undocumented column).
- `formulas.undocumented_columns(catalog)`, with the catalog built from the REAL
  built-workbook header rows (not a static list), returns **0** — complete
  coverage on all 12 data sheets.
- **17 cross-sheet same-name columns** carry sheet-divergent definitions
  (`avg net points`, `avg points added`, `difference of averages`, `net points`,
  `points added`, `points lost`, `length of tenure on team`, `player addition
  value`, `number of trades` across 10 sheets, `pf`, `tanking`, `top team`, the
  position-adjusted variants…). Each sheet's header resolves to ITS OWN
  definition — **0 misattributed**, fallback path verified (e.g. `number of
  trades` on player_week/team_week inherits the subject-count text, picks gets
  the "changed hands by TRADE" text).

### Doc/code drift — **2 DEFECTS FOUND + FIXED**

Spot-checked tooltip FORMULA text against the actual `src/lotg.py` computation
for a NOVEL sample of columns (not the Round-4 `Hardship` fix). Most matched
exactly — verified:
- `FAAB premium %` tooltip `(winning_bid − runner_up) / winning_bid × 100`
  == code `(winner_bid_val − second) / winner_bid_val * 100.0` (lotg.py ~5526).
- `Win Variance` tooltip `-1 × (standings_place − (pf_place + maxpf_place)/2)`
  == code `-1 * (place − ((pf_place + maxpf_place)/2))` (lotg.py ~13380).
- `Efficiency` tooltip `PF / Max PF` == code `pf / maxpf_sum` (lotg.py 13406).
- `3-year roster retention rate` FORMULA `|roster_Y ∩ roster_{Y+3}| / |roster_Y|`
  == code `len(_ros & _future) / len(_ros)` (lotg.py 12991).

Two tooltip-TEXT defects surfaced (the formula/meaning the doc states no longer
matches the data the code produces today):

**1. `3-year roster retention rate` — stale "measurable years" note**
(`src/formulas.py` line 1084).
- The note claimed: *"currently only 2021→2024 and 2022→2025 are measurable
  (2023+ pending)."*
- Reality in the built export: **2020→2023, 2021→2024 AND 2022→2025 are ALL
  measurable** (8 populated `team_year` rows each; 2023/2024/2025 source years
  correctly N/A because their Y+3 season hasn't been played). The note predates
  the 2020 ESPN-backfill being in the pipeline; once 2020 week-1 rosters exist,
  2020→2023 (the 2023 week-1 roster exists) became measurable but the note was
  never updated. NOVEL columns/data: e.g. the 2020→2023 rate of 0.1053 (2 of a
  19-player 2020 week-1 roster still present at 2023 week 1).
- **Fix:** rewrote the note to state the RULE (measurable only for source years Y
  whose Y+3 season has been played; currently 2020→2023, 2021→2024, 2022→2025; Y
  of 2023+ still pending its Y+3 season) rather than a hard-coded year list that
  goes stale every season.

**2. `Week of playoff elimination` — tooltip describes the sentinel BACKWARDS and
mislabels the metric** (`src/formulas.py` lines 1040-1042).
- Old FORMULA text: *"The week the team was knocked out of the playoffs (0 if it
  won it all or didn't make the bracket)."*
- This is wrong two ways, verified against the code (`_playoff_elimination_weeks`,
  lotg.py ~13110) and the full-population data:
  1. The metric is the REGULAR-SEASON week the team was mathematically eliminated
     from playoff (top-4 bracket) CONTENTION — the code runs only on weeks
     `Week < playoff_start` and fires when ≥4 other teams can no longer be caught.
     It is NOT "knocked out of the playoffs."
  2. The `0` sentinel is exactly BACKWARDS: the data shows that in EVERY completed
     season (2020-2025) exactly the **4 bracket (top-4) teams** carry `0`, and the
     **4 non-bracket teams** carry their REAL elimination week (10-15). So `0`
     means the team DID make the bracket; a team that "didn't make the bracket"
     carries a real week, never 0 — the opposite of what the tooltip said. (This
     exact imprecision was flagged-and-deferred to Parts C/D scope in Round-5 E/F;
     the Round-5 C/D agent ran before that deferral note existed, so it had not
     yet been corrected.)
- **Fix:** rewrote the FORMULA text to accurately describe the
  regular-season-contention elimination and the correct sentinel meaning (0 for
  the 4 bracket teams; non-bracket teams carry the real week), and added a Notes
  clarification that it is computed over regular-season weeks only.

Both fixes are pure tooltip-TEXT changes in `src/formulas.py` — no numeric/cell
output changed; the Part C structural sweep (793 attached / 0 missing / 0
mismatched / 0 unexpected / 0 undocumented) still passes on the rebuilt
workbook, and both corrected tooltips render byte-for-byte as written.

---

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the column-1 hover comment from every picks row (**450/450 present**)
and every player_all_time row (**649/649 present**) — **0 rows with real history
but a missing/empty comment** (the inverse failure mode). Then:

- **Chronology — CLEAN.** Parsed every dated line in all 1,099 comments;
  **0 chronological inversions** (no comment narrates a later-dated event before
  an earlier one) — player 0, picks 0.
- **Dangling refs — CLEAN.** **0** `T#N` / `PH#N` / `#N` references in any
  history text point out of range (the narrative comments are plain-English by
  design; none smuggle a bad ref) — player 0, picks 0.
- **Fabrication — CLEAN.** Cross-checked **2,658** dated event lines
  (`added by` / `dropped by` / `traded to`) across all 649 player comments
  against the real `transactions.csv` / `trades.csv` rows, matched on
  `(date, team)` + player/asset membership: **0 fabricated add lines, 0
  fabricated drop lines, 0 fabricated trade lines**. Every claimed event actually
  occurred, attributed to the stated team.
- **Pick origin & draft attribution — CLEAN.** For all **450** picks the pick's
  OWN origin header (`{yr} {num} — originally {orig}'s pick`, year-aware:
  startup/(vet) picks anchor at their literal season year) is present (0 missing);
  for all **353 made** picks the OWN draft line naming the drafted player +
  number is present (0 missing). (An initial check spuriously flagged 152 startup
  picks because the `Year` column shows the text label `startup` while the comment
  uses the literal `2020` — corrected the check; all 450 then verified present.)
- **First-event origin — CLEAN.** **0** player comments begin with an orphan
  `dropped`/`traded` event lacking any preceding add / draft / origin-header
  (every chain starts with a proper origin).
- **Teleport scan (the I/J pattern) — CLEAN.** Scanned every player + pick
  comment for an `added` immediately followed by another `added` ≥2 seasons later
  with no intervening close: **0 suspects**. Consecutive same-team `dropped`-pair
  scan: **0 suspects** (the Round-6 A/B draft-reacquisition false positives are
  not even flagged here, because an intervening draft line breaks the sequence).

### Specifically requested — the 2 I/J-synthesized drop events now narrate correctly

The Round-5 I/J platform-seam-teleport fix synthesized 2 brand-new drop events
(Mitchell Trubisky, Hayden Hurst-pattern) that existed in NO export when any
prior comment-accuracy audit ran. Re-verified both player_all_time history
comments now narrate the new synthesized drop — not the old broken/missing
narrative, and not double-counted/fabricated:

- **Mitchell Trubisky** (player_all_time row 470): the chain reads
  `2020-12-23: added by LWebs53 (free agent)` → **`2021-08-23: dropped by
  LWebs53`** (the synth transfer drop) → `2023-12-06: added by LWebs53 (… dropped
  Israel Abanikanda)` → … Chronologically consistent, NO teleport across the
  empty 2021/2022 seasons. The synth drop appears EXACTLY ONCE; it corresponds to
  exactly **1** `2021-08-23` Trubisky-drop row in transactions.csv (no
  double-count) and produces exactly the documented 2021 transaction-only
  player_year row (1 tx / 1 drop / NaN points / 0 starter weeks).
- **Hayden Hurst** (player_all_time row 236): `2020 12.05 — originally
  stevenb123's pick` → `2020 Draft: stevenb123 drafted Hayden Hurst (12.05)` →
  **`2021-08-23: dropped by stevenb123`** (synth) → `2022-10-07: added by
  stevenb123 (… dropped Cole Kmet)` → `2022-12-21: dropped by stevenb123`.
  Same correct shape: synth drop appears exactly once, 1 matching transactions.csv
  row, the documented 2021 transaction-only player_year row (1 tx / 1 drop / NaN
  points / 0 starter weeks).

Both synth drops are also covered by the fabrication cross-check above (their
`dropped by` lines reconcile to the real transactions.csv rows) and the teleport
scan (0 suspects) — so they are correct on every Part D dimension.

---

## Verification

- `pytest tests/ -q`: **15 passed** in ~73s, 0 failed / 0 skipped — including the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- Part C structural sweep re-run post-fix on the rebuilt workbook: still 793
  attached / 0 missing / 0 mismatched / 0 unexpected / 0 undocumented; both
  corrected tooltips render as written.
- Build artifacts reverted; only `src/formulas.py` (the 2 fixes) + this new file
  remain.

## Conclusion

**Part C found 2 real doc/code-drift defects** — both in tooltip TEXT, both
fixed in `src/formulas.py`:
1. `3-year roster retention rate`'s "measurable years" note was stale (omitted
   the now-measurable 2020→2023) — rewritten to state the rule, not a year list.
2. `Week of playoff elimination`'s tooltip described the `0` sentinel BACKWARDS
   (0 is the bracket teams, not the non-bracket teams) and mislabeled the metric
   as "knocked out of the playoffs" rather than regular-season elimination from
   bracket contention — rewritten accurately (this was the Round-5 E/F deferral).

The Part C structural sweep (793 comments, 0 missing/mismatched/unexpected, 0
undocumented columns, 17 cross-sheet collisions all per-sheet-resolved) is
otherwise CLEAN. **Part D is fully CLEAN at full population** — 450 picks + 649
players all present, 2,658 event lines with 0 fabrications, 0 chronological
inversions, 0 dangling refs, 0 missing-comment-with-real-history, 0 teleport
suspects — and the two I/J-synthesized drop events (Trubisky, Hurst) are now
correctly narrated (synth drop present exactly once, no teleport, no
double-count, reconciling to one transactions.csv row each).

This continues the Round 2-5 pattern: broader/deeper full-population checks keep
surfacing real, narrow defects sample-based checks miss — here two tooltip-text
drifts that crept in as the dataset grew (2020 backfill making 2020→2023
retention measurable) and as a sentinel's meaning was never written up
accurately (the playoff-elimination 0).
