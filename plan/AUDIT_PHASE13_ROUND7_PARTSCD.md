# Phase 13 Round 7 — Parts C+D (header-comment accuracy + asset-history narrative accuracy)

Self-designed full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 2 of 5 in Round 7 (sibling Parts A/B —
`AUDIT_PHASE13_ROUND7_PARTSAB.md` — landed CLEAN at `4bf5575`).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (diverged; `4bf5575` was NOT an ancestor of HEAD).
Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`4bf5575`, the Round-7 Parts
A/B tip carrying all Round-4/5/6 fixes) before any work, then confirmed
`OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: 450 picks,
649 player_all_time rows, 793 header tooltips across 12 data sheets.

All examples below are NOVEL — different columns/players/teams/picks than every
prior round (Rounds 4-7-A/B exclusion list honoured; see those docs). New
surfaces cited here: the `Startup draft players remaining` / `Draft Value` /
`Number of first round picks made` / `Total number of picks made` tooltips
(Part C defects); **Aidan O'Connell**, **Aaron Rodgers**, **Deuce Vaughn**,
**Ameer Abdullah** player chains and the **2024 1.01 (Marvin Harrison)** /
**2024 1.02 (Caleb Williams)** future-pick chains (Part D).

**Result: 4 real doc/code-drift defects found and FIXED** — all in
`src/formulas.py` tooltip TEXT (Part C), all the SAME root cause: tooltips that
mislabel the league's **2020** ESPN startup draft as "2021", and/or omit the
2020-startup exclusion the code actually applies. Part D is fully CLEAN at full
population. This matches the Round-6 pattern exactly (Round 6 found doc/code drift
in *less-common, conditionally-defined* columns; so did Round 7, in a different
less-common column family).

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
  equals the expected per-sheet/global definition byte-for-byte).
- `formulas.undocumented_columns(catalog)`, catalog built from the REAL built
  workbook header rows, returns **[]** — complete coverage on all 12 data sheets.
- The 24 generated/per-opponent columns (`Record vs …`, `Win % vs …`, `Team for
  …`, `Trade impact score`, `Trade addition value`) all carry their correct
  attached comment (resolved via per-sheet keys) — verified not a real
  misattachment, just the generated-prefix skip rule in `undocumented_columns`.

### Doc/code drift — **4 DEFECTS FOUND + FIXED** (all the 2020-startup-label family)

Cross-checked tooltip FORMULA/Notes text against the actual `src/lotg.py`
computation for a NOVEL sample of less-common / conditionally-defined columns
(per the Round-6 lesson). Many matched exactly — re-verified TODAY:
- **Luck** weekly tooltip `(0.27·OUT + 0.14·Sisenzweig − 0.14·Brosenzweig)·postboost
  + (0.36·OPP + 0.10·OWN)·GATE − 0.36·ADV + 0.12·EFF + 0.16·CLOSE − 0.25·LFH`
  == code (lotg.py ~11058-11065) coefficient-for-coefficient. (Sisenzweig/
  Brosenzweig are *real* custom league metrics, not garbled tokens —
  lotg.py 10948-10966.)
- **Trade impact score** five weights (WIN IMPACT 2.0, Avg net points 0.8, Trade
  addition value 0.5, Pick value received 0.5, Asset diff in avg age −0.3) and the
  ×1500 scale == code `_tpi_specs` + `1500.0 * _score` (lotg.py 10146-10179).
- **KTC value difference at deal time** depth-tax (best ×1, 2nd ×0.6, 3rd ×0.6², …)
  == code `_KTC_DEPTH_FACTOR = 0.6`, `_v * 0.6**i` over descending-sorted KTC
  (lotg.py 8227-8242).
- **Cuff at time of pickup?** (still-rostered teammate, starter in the previous 3
  weeks, same NFL team+position, ≥10 PPG more over last 5) == code (lotg.py
  7869-7924); **CUFF_BONUS = 5.0** matches "5 PPG" (lotg.py 7672).
- **Win Variance** `-1 × (place − (pf_place + maxpf_place)/2)` == code (lotg.py
  13381).
- **Week of playoff elimination** — the Round-6 fix still reads correctly
  (regular-season contention elimination; 0 = the 4 bracket teams).
- **3-year roster retention rate** — the Round-6 "measurable years" rewrite still
  correct (currently 2020→2023, 2021→2024, 2022→2025).
- **Trade addition value** pick coefficient "currently 20" == `_TRADE_PICK_COEFF =
  20.0` (lotg.py 8990).

Four tooltip-TEXT defects surfaced — every one is the SAME doc/code drift: the
tooltip names the **2020** ESPN startup draft as "2021" and/or omits the
2020-startup exclusion the code actually performs. The 2020 startup draft (the
inaugural 19-round ESPN draft) and the 2021 supplemental veteran draft are two
DIFFERENT events; the tooltips conflated them.

**1. `Startup draft players remaining` (team_week/year/all-time + league sheets) —
WRONG YEAR.** (`src/formulas.py` line 1242.)
- Old FORMULA: *"How many of the team's original **2021** startup-draft picks it
  still rosters."*
- The code counts the team's OWN **2020**-startup picks: `_startup_remaining_maps`
  filters on `pr.get("_is_startup")` (lotg.py 877-915), and the startup picks are
  emitted with `"Year": 2020, "_is_startup": True` from the *2020 ESPN startup
  draft (19 rounds)* (lotg.py 6151-6167). The code's own docstring: *"how many of
  a team's OWN 2020-startup picks it still rosters."*
- Full-population data confirms: the **2020** column is the maximum for every team
  (AceMatthew 9, JacobRosenzweig 17, stevenb123 15, …) and declines monotonically
  through 2025 — exactly the decay of *2020-startup* retention. If it tracked 2021,
  the 2020 column would read ≈0.
- **Fix:** rewrote to state the inaugural 2020 startup draft, with a note keyed on
  the drafted player_id and an explicit "(Distinct from the 2021 rookie/vet
  draft.)".

**2. `Draft Value` (team_year/all-time) — INCOMPLETE exclusion.**
(`src/formulas.py` line 1243→Notes.)
- Old Notes: *"Excludes the 2021 vet/startup draft."* — bundles startup as a 2021
  event and reads as a single draft.
- The code (lotg.py 13568-13585) excludes BOTH non-rookie drafts: it drops `(vet)`-
  tagged rows AND `_is_startup` rows, with the explicit comment *"Exclude the 2021
  supplemental veteran draft AND the 2020 ESPN startup draft … should count
  ROOKIE-draft selections only … the 19-round startup [was] inflating 2020 Draft
  Value ~4.6x."*
- Full-population data confirms: **2020 Draft Value = 0.0 for all 8 teams** (the
  19-round startup IS excluded; otherwise it'd be large). 2022+ carry real rookie-
  draft values.
- **Fix:** rewrote Notes to "Counts ROOKIE-draft selections only. Excludes BOTH
  non-rookie drafts: the 2020 ESPN startup draft (19 rounds) and the 2021
  supplemental veteran draft."

**3 & 4. `Number of first round picks made` and `Total number of picks made`
(team_year/all-time) — INCOMPLETE exclusion.** (`src/formulas.py` lines 1078,
1081.)
- Old Notes (both): *"Excludes the vet draft."* — omits the 2020-startup exclusion.
- Both columns derive from the SAME filtered `phx` as Draft Value (lotg.py
  13615-13625) — startup AND vet both dropped. Data confirms: **2020 Total number
  of picks made = 0 and Number of first round picks made = 0 for all 8 teams**
  (the 19-round startup is excluded).
- **Fix:** rewrote both Notes to "Rookie-draft picks only. Excludes BOTH non-rookie
  drafts: the 2020 ESPN startup draft and the 2021 supplemental veteran draft."

All four are pure tooltip-TEXT changes in `src/formulas.py` — no numeric/cell
output changed; the Part C structural sweep (793 attached / 0 missing / 0
mismatched / 0 undocumented) still passes on the rebuilt workbook, and all four
corrected tooltips render byte-for-byte as written.

(Investigated but NOT changed: the **O-Score** Notes phrase "the 2021 vet/startup
draft is excluded from every percentile pool … and its rows are N/A." The code
actually scores startup+vet in their OWN separate pool (lotg.py 16139-16146), but
every one of the 152 startup + 32 vet pick rows ends up **O-Score = N/A** in the
export (verified: 0 non-null) — so the user-visible claim ("its rows are N/A") is
accurate. Left as-is to avoid over-editing a long, otherwise-correct note. The
illustrative "~87% of adds that never started" is a soft descriptive figure, not a
hard fact.)

---

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the column-1 hover comment from every picks row (**450/450 present**)
and every player_all_time row (**649/649 present**) — **0 rows with real history
but a missing/empty comment** (the inverse failure mode). Then:

- **Chronology — CLEAN.** Parsed every dated line in all 1,099 comments;
  **0 chronological inversions** — player 0, picks 0.
- **Dangling refs — CLEAN.** **0** `T#N` / `PH#N` / `#N` references in any history
  text (the narratives are plain-English; none smuggle a bad ref) — player 0,
  picks 0.
- **Fabrication — CLEAN.** Cross-checked **2,658** dated event lines (`added by` /
  `dropped by` / `traded to`) across all 649 player comments against the real
  `transactions.csv` / `trades.csv` rows, matched on `(date, team)` + player/asset
  membership (drops matched against both `Player Dropped` and the added player's
  `Date dropped/traded`): **0 fabricated add lines, 0 fabricated drop lines, 0
  fabricated trade lines.** Every claimed event actually occurred, attributed to
  the stated team.
- **Pick origin & draft attribution — CLEAN.** For all **450** picks the pick's
  OWN origin header (`{yr} {num} — originally {orig}'s pick`, year-aware:
  startup→2020, vet→2021) is present (0 missing); for all **353 made** picks the
  OWN draft line naming the drafted player + number is present (0 missing).
- **First-event origin — CLEAN.** **0** player comments begin with an orphan
  `dropped`/`traded` event lacking a preceding add / draft / origin header.
- **Teleport scan (the I/J pattern) — CLEAN.** 5 `added→added` (no intervening
  close) suspects, **all 5 same-team, 0 cross-team** — i.e. **0 true teleports**.
  Each is the documented Sleeper duplicate-add pattern: a free-agent record + a
  commissioner correction (or a re-logged waiver) for the SAME roster stint,
  sharing ONE `Date dropped/traded`. Every add line is a real transactions.csv row
  (covered by the 0-fabrication check), so these are faithful renderings of the
  raw ledger, not narrative defects. Re-confirmed against raw rows:
  - **Ameer Abdullah**: `2021-12-05 commissioner` + `2021-12-06 free_agent` adds
    by stevenb123, BOTH with `Date dropped/traded = 2021-12-07` — one stint, two
    records, one drop. (The high-churn case Round-7 A/B cited.)
  - **Deuce Vaughn**: `2024-09-03 free_agent` + `2024-09-04 commissioner` adds by
    BROsenzweig, both dropping `2024-09-04`.
  - **Mitchell Trubisky**: `2020-12-04 waiver` + `2020-12-23 waiver` adds by
    LWebs53, both with the Round-5/6 I/J synth drop `2021-08-23`.

### Novel chains verified end-to-end (first event = origin, last = current status)

- **Aidan O'Connell** (player_all_time): first event = `2023-10-01 free-agent add`
  (no draft origin → correct FA origin); **3** trades narrated (2023-11-03 →
  shmuel256, 2023-12-06 → stevenb123, 2024-08-18 → plehv79) == pat `Number of
  trades` = 3; chronological; last = `2024-10-22 dropped by stevenb123` (off
  roster). All trade lines reconcile to trades.csv.
- **Aaron Rodgers** (player_all_time): first = `2020 15.07 — originally
  BROsenzweig's pick` + `2020 Draft: BROsenzweig drafted Aaron Rodgers (15.07)`;
  **3** trades (2020-12-16, 2022-09-24, 2024-03-02) == pat `Number of trades` = 3;
  last = `2024-11-29 added by AceMatthew` (on roster). Chronological.
- **2024 1.01 → Marvin Harrison** (picks): origin `originally stevenb123's pick`
  → `2021-10-27 pick traded to shmuel256` → `2023-08-23 pick traded back to
  stevenb123` → `2024 Draft: stevenb123 drafted Marvin Harrison (1.01)`. Both
  pick-trade lines reconcile to trades.csv (the pick label `2024 1.01(M. Harrison)`
  appears on the received side of both deals). First = origin, last = made.
- **2024 1.02 → Caleb Williams** (picks): origin `originally JacobRosenzweig's
  pick` → `2022-07-02 pick traded to stevenb123` → `2024 Draft: stevenb123 drafted
  Caleb Williams (1.02)`. Consistent.

---

## Verification

- `pytest tests/ -q`: **15 passed** in ~62s, 0 failed / 0 skipped (incl. the
  full-build `test_player_history_continuity` and `test_pick_chain_link_integrity`).
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- Part C structural sweep re-run post-fix on the rebuilt workbook: still 793
  attached / 0 missing / 0 mismatched / 0 undocumented; all 4 corrected tooltips
  render byte-for-byte as written.
- Build artifacts reverted; only `src/formulas.py` (the 4 fixes) + this new file
  remain.

## Conclusion

**Part C found 4 real doc/code-drift defects** — all tooltip TEXT, all fixed in
`src/formulas.py`, all the same root cause (the league's inaugural draft is
**2020** ESPN startup, distinct from the 2021 veteran draft; tooltips conflated
them / mislabeled the year / omitted the 2020-startup exclusion the code applies):
1. `Startup draft players remaining` said "2021 startup-draft picks" — it counts
   the 2020 startup picks.
2. `Draft Value` Notes "Excludes the 2021 vet/startup draft" — code excludes BOTH
   the 2020 startup AND the 2021 vet drafts.
3. `Number of first round picks made` Notes "Excludes the vet draft" — also
   excludes the 2020 startup.
4. `Total number of picks made` Notes "Excludes the vet draft" — same.

The Part C structural sweep is otherwise CLEAN (793 comments, 0
missing/mismatched, 0 undocumented). **Part D is fully CLEAN at full population**
— 450 picks + 649 players all present, 2,658 event lines with 0 fabrications, 0
chronological inversions, 0 dangling refs, 0 missing-comment-with-real-history, 0
true (cross-team) teleports (the 5 same-team add→add pairs are the documented
Sleeper duplicate-add pattern), with five novel chains (O'Connell, Rodgers, Vaughn,
2024 1.01 Marvin Harrison, 2024 1.02 Caleb Williams) verified end-to-end.

This continues the Round 2-6 pattern: broader/deeper full-population checks keep
surfacing real, narrow defects sample-based checks miss — here a *family* of
less-common-column tooltips that drifted around the 2020-vs-2021 draft distinction
as the codebase's startup/vet handling evolved across the audit rounds.
