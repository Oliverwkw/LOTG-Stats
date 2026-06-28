# Phase 13 Round 9 — Parts C+D (header-comment accuracy + asset-history narrative accuracy)

Self-designed full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 2 of 5 in Round 9 (sibling Parts A/B —
`AUDIT_PHASE13_ROUND9_PARTSAB.md` — landed CLEAN at `642f111`).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (behind the branch tip; `642f111` was NOT an ancestor of
HEAD — HEAD was an ancestor of origin, not the reverse). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`642f111`, the Round-9 Parts A/B tip
carrying all Round-5..Round-8 fixes including the 4 Round-7 + 3 Round-8 Parts C/D
stale-tooltip fixes) before any work, then confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: 450 picks,
649 player_all_time rows, 793 header tooltips across 12 data sheets.

All examples below are NOVEL — different columns/players/teams/picks than every
prior round (Rounds 4-9-A/B exclusion list honoured). New surfaces cited here:
the **O-Score** Notes + **picks `Number of trades`** Notes (Part C defects);
**Calvin Ridley**, **Davante Adams** player chains and the **2023 1.07 (Dalton
Kincaid)** made-pick chain (Part D).

**Result: 2 real doc/code-drift defects found and FIXED** (in 2 tooltip TEXT
entries — the shared `O-Score` global definition and the picks `Number of trades`
Notes — both in `src/formulas.py`). Both belong to the SAME root-cause family as
Rounds 6/7/8: text that conflates the **2020 ESPN startup draft** with the **2021
supplemental veteran draft**, labelling the inaugural startup draft as a "2021"
event. Part D is fully CLEAN at full population. The 4 Round-7 + 3 Round-8 Parts
C/D fixes were re-confirmed still correct (no regression).

The prompt's specifically-requested EXHAUSTIVE week-16/17 + draft-type sweep is
documented below: every match of "Week 16/17", "16/17 games", "2021 draft",
"startup", "vet draft", "playoff", "Semifinal", "Championship", "Final" in
`src/formulas.py` was traced to the season-aware code logic; the two surviving
draft-conflation tooltips above were the only stale ones, and every week/game-count
claim is now season-aware-correct.

---

## Part C — Header-comment (column-tooltip) accuracy sweep

Resolved every header tooltip in the built workbook exactly as the build does
(`formulas.column_definitions()`, `(sheet, normcol)` per-sheet key first then
`(None, normcol)` global fallback; `IDENTITY_ALLOWLIST` + generated-prefix columns
skipped) and diffed against the comment text actually attached to each header cell
across all 12 data sheets.

### Coverage / attachment / misattachment — CLEAN
- **793** header comments attached. **0 MISSING** (every documented non-identity
  column carries its tooltip), **0 MISMATCHED** (every attached comment's text
  equals the expected per-sheet/global definition byte-for-byte), **0 UNEXPECTED**.
- `formulas.undocumented_columns(catalog)`, catalog built from the REAL built
  workbook header rows (None trailing cells filtered), returns **[]** — complete
  coverage on all 12 data sheets.
- Re-run post-fix: still 793 / 0 / 0 / 0 / [].

### EXHAUSTIVE week-16/17 + draft-type sweep (the specifically-requested pattern)

Searched `src/formulas.py` broadly for `Week 16` / `Week 17` / `17 games` /
`16 games` / `17 weeks` / `16 weeks` / `17-week` / `16-week` / `2021 draft` /
`startup` / `vet draft` / `veteran draft` / `playoff` / `Semifinal` /
`Championship` / `Final` / `week-16` / `week-17`, and verified EVERY match's
week / game-count / draft-type claim against the actual season-aware code logic.

**Week / game-count claims — all CORRECT (the Round-8 fixes hold + no new misses):**
- `PF` (team_week, line 861) — "the Semifinal week (Week 15 in the 16-week 2020
  season; Week 16 in the 17-week 2021+ seasons)" matches the code applying the +5
  homefield bonus at `playoff_start` (15 for 2020, 16 for 2021+; lotg.py
  4271-4297). Correct (Round-8 fix).
- `Win %` / `Record` (team_year, lines 966/969) — "(16 games in the completed 2020
  season, 17 in each completed 2021+ season)" matches the data (2020 = 16
  team_week rows/team; 2021-25 = 17). Correct (Round-8 fix).
- `Regular season record` (line 978) — "the 'Week N' matchups" — year-agnostic, no
  hard count. Correct.
- KTC "end of season" tooltips (lines 114/123/195) — "the Monday after the fantasy
  championship — the day after NFL week-17 Sunday" — `_championship_monday`
  (lotg.py 8004-8008) is a FIXED calendar anchor = week1-Sunday + 16 weeks + 1 day
  (NFL week-17 Monday), applied UNIFORMLY to every season incl. 2020; it is NOT the
  league's bracket Final week. The tooltip describes the calendar anchor the code
  actually computes → accurate as written. Left as-is (matches the Round-8
  determination).
- `Luck` `postboost` (line 372) — "championship-bracket weeks
  (Final/Semifinal/3rd Place)" — keyed by WEEK NAME, year-agnostic. Correct.
- `Dropped avg points` / `Dropped total points` (lines 186/189) — "next 17 PLAYED
  games" is a fixed post-drop nflverse window (lotg.py 7796-7798 `[:17]`), NOT a
  season-week count → not a 2020-season claim. Correct.
- All the Championship/Semifinal/Final/3rd-place/Playoff-bracket tooltips
  (lines 396-399, 983-997, 1043-1071) are keyed by bracket/week-NAME, year-agnostic.
  Correct.

### Doc/code drift — **2 DEFECTS FOUND + FIXED** (the 2020-startup-draft-label family)

The two tooltips below are the only ones in `src/formulas.py` that still conflate
the **2020** ESPN startup draft with the **2021** veteran draft (labelling the
startup draft as a "2021" event). Both were investigated against the code AND the
full-population data and corrected.

**1. `O-Score` Notes (transactions / trades / picks — shared global definition) —
WRONG YEAR + imprecise pool claim.** (`src/formulas.py` line 184.)
- Old Notes: *"For picks, the **2021 vet/startup draft** is excluded from every
  percentile pool."*
- Two problems vs the code (lotg.py 16123-16146):
  1. *Year conflation* — "2021 ... startup" mislabels the inaugural **2020** ESPN
     startup draft as a 2021 event. The code's own comment: *"Non-rookie =
     2021 vet draft + 2020 startup. They are scored in their OWN percentile pool
     (ranked only against each other)."*
  2. *"excluded from every percentile pool"* is inaccurate — the code does NOT
     exclude them from EVERY pool; it scores startup + vet in their OWN separate
     percentile pool (`_add_oscore(..., pool_mask=_nr_osc)`, lotg.py 16139-16146),
     keeping them only out of the rookie pool.
- Full-population data confirms the user-visible OUTCOME the note was trying to
  describe: **all 152 startup + all 32 vet pick O-Scores are N/A** (0 non-null of
  184) — so "its rows are N/A" is the accurate user-facing fact (this is the
  outcome Round 7 verified and chose to leave; the year-conflation half of the
  sentence is what this round corrects).
- **Fix:** rewrote to "the two non-rookie drafts (the 2020 ESPN startup draft and
  the 2021 supplemental veteran draft) are scored only in their OWN percentile
  pool, kept out of the rookie-pick pool; in practice every one of those rows ends
  up N/A." — names both drafts with their correct years, states the
  own-pool behaviour the code performs, and preserves the accurate N/A outcome.

**2. `Number of trades` Notes (picks) — WRONG YEAR (startup labelled 2021).**
(`src/formulas.py` line 346.)
- Old Notes: *"The **2021 startup (vet) draft** and the synthetic award picks
  (2.09 toilet reward, 5.xx FAAB buy) are AWARDS, not trades, so they count 0
  here…"*
- "2021 startup (vet) draft" collapses two DIFFERENT events — the **2020** ESPN
  startup draft and the **2021** vet draft — into one mislabelled "2021" draft.
  The 2020 startup picks weren't tradeable on ESPN (the drafter is the pick's
  Original Team — see the `Startup draft players remaining` tooltip, line 1243),
  and the 2021 vet picks are awards; BOTH legitimately count 0 trades.
- Full-population data confirms the count claim: **all 152 startup picks AND all 32
  vet picks have `Number of trades` = 0** (0 nonzero in each set) — so "they count
  0 here" is accurate; only the year label was wrong.
- **Fix:** rewrote to "The 2020 ESPN startup draft, the 2021 supplemental veteran
  draft, and the synthetic award picks (2.09 toilet reward, 5.xx FAAB buy) are all
  AWARDS/non-tradeable, not trades, so they count 0 here…" — separates the two
  drafts with their correct years and keeps the (correct) count-0 statement.

Both fixes are pure tooltip-TEXT changes in `src/formulas.py` — no numeric/cell
output changed; the Part C structural sweep (793 attached / 0 missing / 0
mismatched / 0 unexpected / 0 undocumented) still passes on the rebuilt workbook,
and both corrected tooltips render byte-for-byte as written.

### Re-confirmation of the 7 prior Round-7/8 Parts C/D fixes — STILL CORRECT
Verified against the rebuilt CSV data + tooltip text:
- **Startup draft players remaining** (Round 7) — tooltip names the inaugural 2020
  startup, "(Distinct from the 2021 rookie/vet draft.)". Correct.
- **Draft Value / Number of first-round picks made / Total number of picks made**
  (Round 7) — "Excludes BOTH non-rookie drafts: the 2020 ESPN startup draft and the
  2021 supplemental veteran draft." 2020 = 0 for all teams. Correct.
- **PF Semifinal week / Win % / Record** (Round 8) — the 2020-16-week-aware text
  matches the data. Correct, no regression.

(Also investigated but correctly year-agnostic / left as-is: line 306
"a startup/vet-draft player's pre-draft history is excluded" — describes a RULE,
not a year, and is correct. The internal CODE comments in `src/lotg.py` that use
"2021 startup/vet" shorthand are developer comments, NOT user-visible tooltips —
out of Part C scope; the user-facing column definitions all live in
`src/formulas.py`.)

---

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the column-1 hover comment from every picks row (**450/450 present**)
and every player_all_time row (**649/649 present**) — **0 rows with real history
but a missing/empty comment** (the inverse failure mode). Then:

- **Chronology — CLEAN.** Parsed every dated line in all 1,099 comments;
  **0 chronological inversions** — player 0, picks 0.
- **Dangling refs — CLEAN.** **0** `T#N` / `PH#N` / `#N` references in any history
  text (the narratives are plain-English) — player 0, picks 0.
- **Fabrication — CLEAN.** Cross-checked **2,982** dated event lines (`added by` /
  `dropped by` / `traded to`) across all 649 player comments against the real
  `transactions.csv` / `trades.csv` rows, matched on `(date, team)` + the right
  event type (adds/drops against transactions.csv `Team`+`Date`, drops also against
  trade-driven moves; trades against trades.csv `Team`+`Date`): **0 fabricated add
  lines, 0 fabricated drop lines, 0 fabricated trade lines.** Every claimed event
  actually occurred, attributed to the stated team.
- **Pick origin & draft attribution — CLEAN.** For all **450** picks the pick's
  OWN origin header (`{yr} {num} — originally {orig}'s pick`, year-aware:
  startup→2020, vet→2021) is present (0 missing); for all **353 made** picks the
  OWN draft line naming the drafted player + number is present (0 missing). The 97
  picks WITHOUT a draft line are exactly the **2026/2027/2028 future-class unmade
  picks** (Player Picked = "Unknown") — correctly NO draft line yet, but each
  carries its origin header + full pick-trade chain. Not a defect.
- **First-event origin — CLEAN.** **0** player comments begin with an orphan
  `dropped`/`traded` event lacking a preceding add / draft / origin header.
- **Teleport scan (the I/J pattern) — CLEAN.** **0 cross-team `added→added`** (no
  intervening close) — i.e. **0 true teleports**. 5 SAME-team `added→added` pairs
  surfaced, all the documented Sleeper duplicate-add pattern (one roster stint, two
  records sharing one exit date) — all 5 prior-round cases (Ameer Abdullah, Deuce
  Vaughn, Mitchell Trubisky, Ryan Tannehill, Taysom Hill), re-confirmed benign.

### Novel chains verified end-to-end (first event = origin, last = current status)

- **Calvin Ridley** (player_all_time, 5 trades): first = `2020 9.01 — originally
  Oliverwkw's pick` + `2020 Draft: Oliverwkw drafted Calvin Ridley (9.01)`; **5**
  trade events narrated == pat `Number of trades` = 5 (2021-12-04 → shmuel256,
  2023-03-23 → stevenb123, 2023-12-10 → shmuel256, 2025-08-07 → Oliverwkw,
  2025-10-13 → shmuel256); last = `2025-11-18 dropped by shmuel256`, matching
  `Last team = shmuel256`. Chronological. Every trade line reconciles to
  trades.csv (received side + mirror sent side confirmed for each, e.g. the
  2021-12-04 shmuel256-got-Ridley side mirrors Oliverwkw's sent-Ridley side); the
  final drop reconciles to the `2025-11-18 shmuel256 dropped Calvin Ridley`
  transactions.csv row.
- **Davante Adams** (player_all_time, 4 trades): first = `2020 2.02 — originally
  LWebs53's pick` + `2020 Draft: LWebs53 drafted Davante Adams (2.02)`; **4** trade
  events (2022-09-24 → shmuel256, 2025-04-14 → plehv79, 2025-07-30 → LWebs53,
  2025-08-30 → AceMatthew) == pat `Number of trades` = 4; last = `2025-08-30 traded
  to AceMatthew`, matching `Last team = AceMatthew`. Chronological; all 4 lines
  reconcile to trades.csv.
- **2023 1.07 → Dalton Kincaid** (picks, 2 pick-trades): origin `originally
  stevenb123's pick` → `2021-10-27 pick traded to shmuel256` → `2022-10-19 pick
  traded to AceMatthew` → `2023 Draft: AceMatthew drafted Dalton Kincaid (1.07)`.
  Both pick-trade lines reconcile to trades.csv (the `2023 1.07(D. Kincaid)` label
  on the received side of each deal, both mirror sides confirmed). First = origin
  (stevenb123 = Original Team), made by AceMatthew (= Team), 2 pick-trades ==
  picks `Number of trades` = 2.

---

## Verification

- `pytest tests/ -q`: **15 passed** in ~75s, 0 failed / 0 skipped (incl. the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`).
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- Part C structural sweep re-run post-fix on the rebuilt workbook: still 793
  attached / 0 missing / 0 mismatched / 0 unexpected / 0 undocumented; both
  corrected tooltips render byte-for-byte as written.
- Build artifacts reverted; only `src/formulas.py` (the 2 fixes) + this new file
  remain.

## Conclusion

**Part C found 2 real doc/code-drift defects** — both tooltip TEXT, both fixed in
`src/formulas.py`, both the SAME root cause as Rounds 6/7/8 (the inaugural draft is
the **2020** ESPN startup, distinct from the **2021** veteran draft; the tooltips
conflated/mislabelled them):
1. `O-Score` Notes said "the 2021 vet/startup draft is excluded from every
   percentile pool" — startup is 2020, and the code scores startup + vet in their
   OWN pool (not excluded from every pool); rewritten to name both drafts with
   correct years, the own-pool behaviour, and the accurate N/A outcome.
2. picks `Number of trades` Notes said "The 2021 startup (vet) draft … count 0
   here" — startup is 2020; rewritten to separate the 2020 ESPN startup draft and
   the 2021 supplemental veteran draft, keeping the correct count-0 fact (verified:
   all 152 startup + 32 vet picks = 0 trades).

The Part C structural sweep is otherwise CLEAN (793 comments, 0
missing/mismatched/unexpected, 0 undocumented), the EXHAUSTIVE week-16/17 +
draft-type sweep found no remaining week/game-count misstatements (the Round-8
fixes hold), and the 7 prior Round-7/8 fixes are re-confirmed correct with no
regression. **Part D is fully CLEAN at full population** — 450 picks + 649 players
all present, 2,982 event lines with 0 fabrications, 0 chronological inversions, 0
dangling refs, 0 missing-comment-with-real-history, 0 true (cross-team) teleports
(the 5 same-team add→add pairs are the documented Sleeper duplicate-add pattern),
with novel chains (Calvin Ridley, Davante Adams, 2023 1.07 Dalton Kincaid) verified
end-to-end.

This continues the Round 2-8 pattern: broader/deeper full-population checks keep
surfacing real, narrow defects sample-based checks miss — here a *fourth* batch of
the 2020-vs-2021 draft-seam tooltip drift (after Round 6's retention/
playoff-elimination, Round 7's startup/vet-draft labels, and Round 8's
16-week-season game counts), specifically the two remaining tooltips that still
labelled the inaugural 2020 ESPN startup draft as a "2021" event.
