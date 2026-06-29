# Phase 13 Round 10 — Parts C+D (header-comment accuracy + asset-history narrative accuracy)

Self-designed full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 2 of 5 in Round 10 (sibling Parts A/B —
`AUDIT_PHASE13_ROUND10_PARTSAB.md` — landed CLEAN at `f95d3ea`).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `git merge-base --is-ancestor f95d3ea HEAD`
printed STALE — `f95d3ea` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`f95d3ea`, the Round-10 Parts A/B tip
carrying all Round-5..Round-9 fixes), then confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: 450 picks,
649 player_all_time rows, **793** header tooltips across 12 data sheets, 1,099
asset-history hover comments.

All examples below are NOVEL — different columns/players/teams/picks than every
prior round (Rounds 4-10 A/B + Rounds 5-9 C/D exclusion lists honoured). New
surfaces cited here: the **Taxi-eligible** + **Result** column tooltips (the two
Part C defects — a genuinely NEW family, NOT the 2020/2021 draft seam); and
**Wan'Dale Robinson**, **James Conner**, **Cam Akers** player chains plus the
**2022 2.02 (James Cook)** made-pick chain (Part D, all novel).

**Result: 2 real doc/code-drift defects found and FIXED** — both tooltip TEXT in
`src/formulas.py`, both in a **NEW** defect family unrelated to the now-exhausted
2020-vs-2021 draft-seam family that dominated Rounds 6-9:
1. **`Taxi-eligible`** — the tooltip said it was keyed ONLY off
   "Weeks-as-starter == 0 across the player's whole history", omitting the
   controlling **first-year-in-league** condition the code actually enforces.
2. **`Result`** — the tooltip enumerated the wrong finish vocabulary
   ("Champion / 2nd / 3rd / 4th / Missed playoffs / Last place") when the code
   actually emits ordinal **5th / 6th / 7th / 8th** for the non-playoff teams.

The prompt's specifically-requested INDEPENDENT re-verification of the
2020-vs-2021 startup/vet family (don't just trust Round 9) is documented below
and confirms that family is genuinely exhausted across both the `formulas.py`
tooltip layer AND the `lotg.py` generated-narrative layer AND the rendered
workbook. Part D is fully CLEAN at full population.

---

## Independent re-verification of the 2020-vs-2021 draft-seam family — CONFIRMED EXHAUSTED

Round 9 I/J's agent grepped both source files post-fix and found 0 remaining
mislabels. This round re-derived that conclusion from scratch (not trusting it):

- **`src/formulas.py` broad grep** for every `2021` line + `startup` / `vet` /
  `veteran` co-occurrence: the surviving hits (lines 184, 295, 306, 307, 346,
  1075, 1078, 1081, 1243) are all CORRECTLY-WORDED — each either names "the 2020
  ESPN startup draft" and "the 2021 supplemental veteran draft" as DISTINCT
  events (they co-occur only because both correct names sit in one sentence), or
  describes a year-agnostic RULE ("a startup/vet-draft player's pre-draft history
  is excluded", line 306 — applies to BOTH non-rookie drafts, not a year claim).
  **0 surviving mislabels.**
- **`src/lotg.py` grep** for `2021.*startup|startup.*2021|2021.*vet|vet.*2021`:
  every hit is a developer CODE COMMENT (`#`-prefixed) using "2021 vet/startup"
  shorthand to refer to BOTH drafts collectively — NOT a user-visible string.
  The only user-visible generated f-string for the vet draft (line 15801) reads
  `"{_yr} supplemental veteran draft: …"` (the Round-9 I/J fix), and the 2020
  startup line (15865) reads `"{_yr} Draft:"` → renders "2020 Draft:". Correct.
- **Rendered-workbook scan** (every cell value + every comment across all 13
  sheets) for `2021 startup` / `startup (vet)` / `vet/startup` / `startup/vet`:
  **2 hits, both benign** — the `Avg career PPG` tooltip's "a startup/vet-draft
  player's pre-draft history is excluded" (the year-agnostic RULE on `formulas`
  C407 and `picks` L1). **0 genuine mislabels.** Corroborating counts: 94
  cells/comments contain the correct "supplemental veteran draft" and 305 contain
  the correct "2020 Draft:" string.

**Conclusion:** the 2020-vs-2021 family is genuinely exhausted. The prompt's
hypothesis that "this family may be a distraction from other undiscovered issues"
proved CORRECT — looking beyond it surfaced the two NEW-family defects below.

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
  equals the expected per-sheet/global definition byte-for-byte), **0
  commented-but-undocumented**, **0 unexpected**.
- `formulas.undocumented_columns(catalog)`, catalog built from the REAL built
  workbook header rows, returns **[]** — complete coverage on all 12 data sheets.
- Re-run post-fix: still 793 / 0 / 0 / 0 / [].

### Quantitative tooltip claims spot-verified against the data (NEW-category sweep)
Beyond the structural diff, the FACTUAL claims embedded in tooltips were checked
against the full-population data to catch silent doc/code drift:
- **`Win?`** "(a tie would count as ½ a win; none has occurred yet)" — CLEAN:
  **0** team_week rows with Margin == 0 across all 808.
- **`Number of teams`** "(Renfrow = 5)" — CLEAN: Hunter Renfrow `Number of
  teams` = **5**.
- **`Lowest starter score`** "(can be negative)" — CLEAN: league min = **-2.5**.
- **`Efficiency`** "≤ 1" — CLEAN: team_week max = **1.0**, 0 over.
- **`O-Score`** "the ~87% of adds that never started" — CLEAN: **87.3%** of all
  1,514 transaction rows (the percentile pool population) have Points Added == 0.
- **`O-Score` pure drops** "0–50, tops out at 50" — CLEAN: 439 pure-drop O-Scores
  span **6.5–43.8**, none above 50.
- **`3-year roster retention rate`** "currently 2020→2023, 2021→2024, 2022→2025" —
  CLEAN: non-null only for source years **{2020, 2021, 2022}**.
- **`Playoff record` / `Playoff win %`** "'0-0' / N/A for never-winners'-bracket"
  — CLEAN: the lone never-bracket team shows `0-0` + Playoff win % N/A.

### Doc/code drift — **2 DEFECTS FOUND + FIXED** (a NEW family, not the draft seam)

**1. `Taxi-eligible` Formula+Notes — omitted the controlling first-year gate.**
(`src/formulas.py` line 857-859.)
- Old: *"TRUE if the player has never been a fantasy starter in any LOTG week …"*
  / Notes *"Keyed off Weeks-as-starter == 0 across the player's whole history;
  undrafted never-started rookies stay eligible."*
- The CODE (`src/lotg.py` `_is_taxi_eligible`, lines 12694-12711) requires TWO
  conditions: **`first_year_by_pid[pid] == current_season`** (the player's
  earliest player_year season is the latest/current season) **AND**
  `weeks_started == 0`. The code's own comment is explicit: *"TRUE if: player is
  currently in their first year in the league AND has never started… Resets at
  week 1 of the following season."* The tooltip dropped the first-year half and
  even claimed "across the player's whole history".
- **Full-population data proves the drift:** of the players with Weeks-as-starter
  == 0, **only 39 are Taxi-eligible==True** and **197 are False** — the 197 are
  never-started players from EARLIER league seasons (e.g. Adam Trautman, Ameer
  Abdullah, Andrei Iosivas), and there are **0** True-with-starts>0. All **39**
  True players have their first league season == **2025** (the current season),
  confirming the gate is first-year, not "whole history".
- **Fix:** rewrote the Formula to state BOTH conditions (first LOTG season AND
  never-started) and the Notes to explain the reset-at-year-2 behaviour and that
  a never-started VETERAN from an earlier season is NOT taxi-eligible. Pure
  tooltip TEXT — the 39/610 True/False split is unchanged after rebuild.

**2. `Result` Formula — wrong finish vocabulary (omits 5th-8th).**
(`src/formulas.py` line 1037-1039.)
- Old: *"The team's finish that season — Champion / 2nd / 3rd / 4th / Missed
  playoffs / Last place — from the playoff & toilet brackets."*
- The CODE (`src/lotg.py` season-finish, lines 13286-13335) assigns the four
  winners'-bracket places (Champion/2nd from the Final, 3rd/4th from the 3rd-place
  game) and then assigns the non-playoff teams explicit ordinals **5th / 6th /
  7th / 8th** by regular-season record (PF tiebreaker). The strings "Missed
  playoffs"/"Last place" exist only in a fallback (lines 13939-13947) that fires
  ONLY when `season_finish` has no entry for a team in a complete season — which
  never happens (the `_finish_rank` map, line 14000, and the data both show only
  Champion + 2nd..8th).
- **Full-population data proves the drift:** the `Result` column's distinct values
  are **{Champion, 2nd, 3rd, 4th, 5th, 6th, 7th, 8th}** (6 of each across the 6
  completed seasons) — **0 "Missed playoffs", 0 "Last place"**. Cross-check:
  Result==5th/6th/7th/8th rows all carry a non-zero `Week of playoff elimination`
  (10-15), and Champion/2nd/3rd/4th all carry 0, exactly as the bracket logic
  implies.
- **Fix:** rewrote the Formula to enumerate the real vocabulary (Champion / 2nd /
  3rd / 4th from the winners' bracket, then 5th-8th by regular-season standings
  with PF tiebreaker) and the Notes to clarify 8th == last place. Pure tooltip
  TEXT — the Result column values are unchanged after rebuild.

Both fixes are tooltip-TEXT-only in `src/formulas.py`; no numeric/cell output
changed. The Part C structural sweep (793 attached / 0 missing / 0 mismatched / 0
unexpected / 0 undocumented) still passes on the rebuilt workbook, and both
corrected tooltips render byte-for-byte as written.

### Re-confirmation of the prior Round-7/8/9 Parts C/D fixes — STILL CORRECT
The startup/vet-draft tooltips (Startup draft players remaining; Draft Value;
Number of first-round picks made; Total number of picks made; O-Score Notes;
picks Number of trades Notes; PF Semifinal-week; Win %/Record 16-vs-17 games)
all re-verified correct against the rebuilt data with no regression (see the
independent re-verification section above).

---

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the column-1 hover comment from every picks row (**450/450 present**)
and every player_all_time row (**649/649 present**) — **0 rows with real history
but a missing/empty comment** (the inverse failure mode; checked against
player_all_time rows with Number of trades > 0 or Number of transactions > 0).

- **Chronology — CLEAN.** Parsed every dated line in all 1,099 comments;
  **0 chronological inversions** — player 0, picks 0.
- **Dangling refs — CLEAN.** **0** `T#N` / `PH#N` / `#N` references in any history
  text (the narratives are plain-English) — player 0, picks 0.
- **Fabrication — CLEAN.** Cross-checked **2,658** dated event lines (`added by` /
  `dropped by` / `traded to`) across all 649 player comments against the real
  `transactions.csv` / `trades.csv` rows, matched on `(date, team)` + event type
  (adds → transactions `Player Added`; drops → transactions `Player Dropped` or
  trade-driven sends; trades → trades.csv `Team`+`Date`): **0 fabricated add
  lines, 0 fabricated drop lines, 0 fabricated trade lines.**
- **First-event origin / last-event status — CLEAN** (verified per-trace below).

### Novel chains verified end-to-end (first event = origin, last = current status)

- **Wan'Dale Robinson** (player_all_time, 6 trades, Last team shmuel256): first =
  `2022 4.02 — originally AceMatthew's pick` → two PICK-trade lines (2021-12-04 →
  shmuel256, 2022-07-03 → stevenb123) → `2022 Draft: stevenb123 drafted Wan'Dale
  Robinson (4.02)` → **6** player "traded to" events (2022-11-28 AceMatthew,
  2023-08-10 shmuel256, 2024-04-28 Oliverwkw, 2025-08-07 shmuel256, 2025-08-22
  BROsenzweig, 2025-12-02 shmuel256). The 6 received-side trade dates in
  trades.csv match exactly; `Number of trades` = 6; 0 tx adds/drops (Number of
  transactions = 0); last = traded to shmuel256 == Last team. Chronological.
- **James Conner** (player_all_time, 6 trades, Last team BROsenzweig): first =
  `2020 6.02 — originally LWebs53's pick` + `2020 Draft: LWebs53 drafted James
  Conner (6.02)` (correctly "2020 Draft", not startup-mislabelled) → **6** trade
  events, the 6 received-side dates matching trades.csv exactly; last = traded to
  BROsenzweig (2025-08-02) == Last team. 0 tx. Chronological.
- **Cam Akers** (player_all_time, 4 trades + 9 transactions / 5 drops, Last team
  AceMatthew): first = `2020 6.06 — originally plehv79's pick` + `2020 Draft:
  plehv79 drafted Cam Akers (6.06)` → 4 trades (2022-11-29, 2023-06-11,
  2023-08-14, 2023-10-13) → mixed adds/drops; the 4 received-side trade dates +
  4 tx-add dates + 5 tx-drop dates all match transactions.csv/trades.csv exactly
  (4 trades + 5 drops + 4 adds; Number of transactions = adds+drops = 9). The
  2024-11-22 same-day drop-then-add (LWebs53 drops, AceMatthew adds) renders drop
  before add (the `_evt_rank` rule); last = `2024-11-26 dropped by AceMatthew` ==
  Last team AceMatthew. Chronological, no teleport.
- **2022 2.02 → James Cook** (picks, 3 pick-trades, Original AceMatthew, Team
  shmuel256): origin `originally AceMatthew's pick` → 3 `pick traded to` lines
  (2021-12-04 Oliverwkw, 2022-06-20 stevenb123, 2022-07-03 shmuel256) — each
  matching a real trades.csv received-side `2022 2.02(J. Cook)` event, in order →
  `2022 Draft: shmuel256 drafted James Cook (2.02)`. First = origin (AceMatthew =
  Original Team), made by shmuel256 (= Team), `Number of trades` = 3. James Cook
  had no post-draft player trades, so the chain correctly terminates at the draft
  (no fabricated downstream events).

---

## Verification

- `pytest tests/ -q`: **15 passed** in ~77s, 0 failed / 0 skipped (incl. the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`
  — neither tooltip-text fix touches the narrative parser, so no companion change
  was needed this round).
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- Part C structural sweep re-run post-fix on the rebuilt workbook: still 793
  attached / 0 missing / 0 mismatched / 0 unexpected / 0 undocumented; both
  corrected tooltips render byte-for-byte as written.
- Data unchanged after the text-only fixes: Taxi-eligible still 39 True / 610
  False; Result still {Champion, 2nd..8th}.
- Build artifacts reverted; only `src/formulas.py` (the 2 fixes) + this new file
  remain.

## Conclusion

**Part C found 2 real doc/code-drift defects** — both tooltip TEXT, both fixed in
`src/formulas.py`, and crucially both in a **NEW defect family** distinct from the
2020-vs-2021 draft-seam family that Rounds 6-9 chased to exhaustion:
1. `Taxi-eligible` omitted the controlling **first-year-in-league** gate (data:
   39 first-year-2025 never-started True vs 197 earlier-season never-started
   False); rewritten to state both conditions + the year-2 reset.
2. `Result` enumerated a stale vocabulary ("Missed playoffs / Last place") when
   the code emits ordinal **5th-8th** (data: Result ∈ {Champion, 2nd..8th}, 0
   "Missed playoffs"/"Last place"); rewritten to the real ordinal vocabulary.

The Part C structural sweep is otherwise CLEAN (793 comments, 0
missing/mismatched/unexpected, 0 undocumented), every quantitative tooltip claim
spot-verified against the data holds, and the prior Round-7/8/9 startup-family
fixes re-confirm correct. **Part D is fully CLEAN at full population** — 450 picks
+ 649 players all present, 2,658 event lines with 0 fabrications, 0 chronological
inversions, 0 dangling refs, 0 missing-comment-with-real-history, with novel
chains (Wan'Dale Robinson, James Conner, Cam Akers, 2022 2.02 James Cook) verified
end-to-end.

**The 2020-vs-2021 draft-seam family is independently re-confirmed EXHAUSTED**
across the `formulas.py` tooltips, the `lotg.py` generated narratives, AND the
rendered workbook (the only co-occurrences left are correctly-worded distinct-name
references or year-agnostic rules). As the prompt anticipated, that now-familiar
family WAS distracting from other undiscovered issues — stepping past it surfaced
the two NEW-family tooltip drifts above. So **Round 10 Parts C/D is NOT clean** (2
defects found + fixed), both still pure TEXT (no cell/numeric output changed).
