# Phase 13 Round 8 — Parts C+D (header-comment accuracy + asset-history narrative accuracy)

Self-designed full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 2 of 5 in Round 8 (sibling Parts A/B —
`AUDIT_PHASE13_ROUND8_PARTSAB.md` — landed CLEAN at `e87b0b7`).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (behind the branch tip; `e87b0b7` was NOT an ancestor of
HEAD — `merge-base HEAD e87b0b7 == HEAD`, i.e. HEAD was an ancestor of origin, not
the reverse). Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`e87b0b7`, the
Round-8 Parts A/B tip carrying all Round-5/6/7 fixes including the 4 Round-7 Parts
C/D stale-tooltip fixes) before any work, then confirmed `OK_AT_OR_AHEAD`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: 450 picks,
649 player_all_time rows, 793 header tooltips across 12 data sheets.

All examples below are NOVEL — different columns/players/teams/picks than every
prior round (Rounds 4-8-A/B exclusion list honoured). New surfaces cited here:
the **PF** Semifinal-homefield tooltip + **Win %** / **Record** "17 games"
tooltips (Part C defects); **Cooper Kupp**, **Wan'Dale Robinson** player chains,
the **2022 2.01 (George Pickens)** made-pick chain, and **Ryan Tannehill** as the
novel same-team duplicate-add case (Part D).

**Result: 3 real doc/code-drift defects found and FIXED** (in 3 tooltip TEXT
entries spanning `PF`, `Win %`, `Record` in `src/formulas.py`) — all the SAME
root cause as Round 7: tooltips that hard-code a **2021+-only** game/week count
and silently mis-state the **2020** ESPN season (a 16-week / 16-game season whose
Semifinal fell on Week 15, vs the 17-week / 17-game 2021+ seasons with the
Semifinal on Week 16). Part D is fully CLEAN at full population. This continues
the Round-6/7 pattern (doc/code drift around the 2020-vs-2021 structural seam).

The 4 Round-7 Parts C/D fixes were RE-CONFIRMED still correct (no regression) —
see "Re-confirmation of the 4 Round-7 fixes" below.

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
  workbook header rows, returns **[]** — complete coverage on all 12 data sheets.
- Re-run post-fix: still 793 / 0 / 0 / 0 / [].

### Re-confirmation of the 4 Round-7 fixes — STILL CORRECT (no regression)
Verified against the rebuilt CSV data:
- **Startup draft players remaining** — 2020 is the MAX per team (mean 12.25),
  declining monotonically to 2025 (mean 1.125): the decay of *2020-startup*
  retention exactly. Tooltip "the players the team drafted in the inaugural 2020
  startup draft … (Distinct from the 2021 rookie/vet draft.)" is correct.
- **Draft Value / Number of first round picks made / Total number of picks made**
  — 2020 = 0 for all 8 teams (both the 2020 ESPN startup AND the 2021 vet draft
  excluded; rookie-draft only). 2021 ROOKIE draft IS counted (mean 1.0 first-round
  / 4.0 total per team = 32 picks/8 teams). The corrected "Excludes BOTH non-rookie
  drafts" text matches the data.

### Doc/code drift — **3 DEFECTS FOUND + FIXED** (the 2020-16-week-season family)

Cross-checked tooltip text against the actual `src/lotg.py` computation AND the
full-population data for a NOVEL sample of columns. Many matched exactly —
re-verified TODAY:
- **Brosenzweig** (loss while 2nd-HIGHEST scorer, `r_desc==2`) / **Sisenzweig**
  (win while 2nd-LOWEST scorer, `r_asc==2`) == code (lotg.py 10948-10966).
- **All-play win %** — `Σ(teams with strictly lower PF) / (n−1 other teams)`, ties
  contribute to neither numerator but stay in the denominator == code (lotg.py
  16308-16315). Matches "Ties count as neither a win nor a loss but stay in the
  denominator."
- **Offseason trades** — `Date < date(season, 9, 7)` (Sept-7 kickoff cutoff) ==
  code `_trade_is_offseason` (lotg.py 11510-11513). Matches "(Sept 7)".
- **Tanking / Trade addition value future-pick round weights** `{R1:0.25, R2:0.09,
  R3:0.03, R4:0.01}` == `_FUTURE_PICK_WEIGHTS` (lotg.py 2887).
- **Dropped avg points** "next 17 PLAYED games" == code `[:17]` (lotg.py 7805).
- **Number of teams** Renfrow=5 example == data (player_all_time = 5).
- **Lowest starter score** "Can be negative" == data (league_week min = −2.5).

Three tooltip-TEXT defects surfaced — every one the SAME doc/code drift: the
tooltip hard-codes a game/week count that is only correct for the 17-week 2021+
seasons and silently mis-states the **2020** ESPN season (16 weeks: 14 regular +
Semifinal Week 15 + Final Week 16; 16 total games).

**1. `PF` (team_week) — WRONG Semifinal week for 2020.** (`src/formulas.py` line
861.)
- Old FORMULA: *"in the Semifinal week **(Week 16)** each matchup's HIGHER SEED
  gets +5 homefield advantage…"*
- The code applies the +5 homefield bonus at `playoff_start`, which the code's own
  comment states is *"15 for 2020 (Semifinal wk15) and 16 for 2021+"* (lotg.py
  4271-4297, `semis_bonus_by_week[playoff_start][higher] = 5.0`). Data confirms:
  the 2020 Semifinal is **Week 15** (`team_week` Week-15 rows carry Week Name
  "Semifinal", 4 teams) while 2021+ Semifinals are Week 16. So "(Week 16)" is wrong
  for 2020 — the +5 lands on Week 15 there.
- **Fix:** rewrote to "(Week 15 in the 16-week 2020 season; Week 16 in the 17-week
  2021+ seasons)".

**2 & 3. `Win %` and `Record` (team_year) — hard-code "17 games" for a completed
season, wrong for 2020.** (`src/formulas.py` lines 966, 969.)
- Old text (both): *"(17 games in a completed season)"* / *"(17 in a completed
  season)"*.
- The 2020 season played **16 games** total per team (verified: every team's
  `team_week` row count = 16; `Record` values sum to 16, e.g. shmuel256 12-4,
  LWebs53/Oliverwkw 10-6, stevenb123 3-13). 2021-2025 each play 17. So "17 in a
  completed season" silently excludes the one already-completed 16-game season.
- **Fix:** rewrote both to "(16 in the completed 2020 season, 17 in each completed
  2021+ season)".

(Investigated but NOT changed:
- **KTC "end of season" / "Monday after the fantasy championship — the day after
  NFL week-17 Sunday"** — the code anchor `_championship_monday` is a FIXED
  calendar checkpoint (week1-Sunday + 16 weeks + 1 day, NFL week-17 Monday) applied
  uniformly to every season including 2020; it is NOT the league's bracket Final
  week. The tooltip describes the calendar anchor the code actually computes, so it
  is accurate as written — left as-is.
- **Regular season record** tooltip "the 'Week N' matchups" — year-agnostic and
  correct (2020 has 14 such games, 2021+ 15, but the tooltip states no hard count).
- **Luck `postboost`** "championship-bracket weeks (Final/Semifinal/3rd Place)" —
  keyed by WEEK NAME not week number, so year-agnostic and correct.)

All three fixes are pure tooltip-TEXT changes in `src/formulas.py` — no
numeric/cell output changed; the Part C structural sweep (793 attached / 0 missing
/ 0 mismatched / 0 undocumented) still passes on the rebuilt workbook, and all
three corrected tooltips render byte-for-byte as written.

---

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the column-1 hover comment from every picks row (**450/450 present**)
and every player_all_time row (**649/649 present**) — **0 rows with real history
but a missing/empty comment** (the inverse failure mode). Then:

- **Chronology — CLEAN.** Parsed every dated line in all 1,099 comments;
  **0 chronological inversions** — player 0, picks 0.
- **Dangling refs — CLEAN.** **0** `T#N` / `PH#N` / `#N` references in any history
  text (the narratives are plain-English) — player 0, picks 0.
- **Fabrication — CLEAN.** Cross-checked **4,727** dated event lines (`added by` /
  `dropped by` / `traded to`) across all 1,099 comments against the real
  `transactions.csv` / `trades.csv` rows, matched on `(date, team)` + the right
  event type (drops matched against `Player Dropped` AND the added player's `Date
  dropped/traded`): **0 fabricated add lines, 0 fabricated drop lines, 0 fabricated
  trade lines.** Every claimed event actually occurred, attributed to the stated
  team.
- **Pick origin & draft attribution — CLEAN.** For all **450** picks the pick's
  OWN origin header (`{yr} {num} — originally {orig}'s pick`, year-aware:
  startup→2020, vet→2021) is present (0 missing); for all **353 made** picks the
  OWN draft line naming the drafted player + number is present (0 missing).
- **First-event origin — CLEAN.** **0** player comments begin with an orphan
  `dropped`/`traded` event lacking a preceding add / draft / origin header.
- **Teleport scan (the I/J pattern) — CLEAN.** **0 cross-team `added→added`** (no
  intervening close) — i.e. **0 true teleports**. 5 SAME-team `added→added` pairs
  surfaced, all the documented Sleeper duplicate-add pattern (one roster stint, two
  records sharing one exit date). 4 were prior-round cases (Ameer Abdullah, Deuce
  Vaughn, Mitchell Trubisky, Taysom Hill); the 5th is NOVEL and verified below.
  - **Ryan Tannehill** (player_all_time): `2021-12-05 added by stevenb123
    (commissioner, dropped Taysom Hill)` + `2022-06-19 added by stevenb123 (free
    agent)`, BOTH stevenb123, BOTH with raw `Date dropped/traded = 2022-06-20`
    (the trade to Oliverwkw). One stint, two records (a commissioner correction +
    a re-logged free-agent), one exit. Both add lines are real transactions.csv
    rows (covered by the 0-fabrication check). Faithful rendering of the raw
    ledger, not a narrative defect.

### Novel chains verified end-to-end (first event = origin, last = current status)

- **Cooper Kupp** (player_all_time, 6 trades): first = `2020 6.01 — originally
  Oliverwkw's pick` + `2020 Draft: Oliverwkw drafted Cooper Kupp (6.01)`; **6**
  trade events narrated == pat `Number of trades` = 6 — note 2025-08-02 carries
  **two distinct trade events** (13:54:05 Oliverwkw, 13:56:36 LWebs53), correctly
  rendered as two separate lines; last = `2025-11-04 dropped by BROsenzweig`,
  matching `Last team = BROsenzweig`. Chronological. The 2024-05-03 21-asset
  blockbuster line reconciles to trades.csv.
- **Wan'Dale Robinson** (player_all_time, 6 trades): first = `2022 4.02 —
  originally AceMatthew's pick`, with **2 pre-draft PICK-trade lines** (2021-12-04,
  2022-07-03, correctly labeled "pick traded to") then `2022 Draft: stevenb123
  drafted Wan'Dale Robinson (4.02)`, then **6 player-trade events** (2022-11-28 →
  AceMatthew, 2023-08-10 → shmuel256, 2024-04-28 → Oliverwkw, 2025-08-07 →
  shmuel256, 2025-08-22 → BROsenzweig, 2025-12-02 → shmuel256) == pat trades = 6;
  last = `2025-12-02 traded to shmuel256`, matching `Last team = shmuel256`. The
  2024-04-28 line reconciles BYTE-FOR-BYTE to the Oliverwkw side of trades.csv
  (`Wan'Dale Robinson; 2024 2.03(J. McCarthy); 2024 2.08(X. Legette); $10 FAAB`
  received; `George Kittle; 2025 4.01(J. Blue); 2024 2.05(K. Coleman)` sent),
  mirror side (shmuel256) confirmed.
- **2022 2.01 → George Pickens** (picks, 2 pick-trades): origin `originally
  JacobRosenzweig's pick` → `2022-07-02 pick traded to stevenb123` → `2022-08-11
  pick traded to plehv79` → `2022 Draft: plehv79 drafted George Pickens (2.01)` →
  then the post-draft player chain (`2022-11-29 → shmuel256`, `2024-06-13 →
  JacobRosenzweig`). Both pick-trade lines reconcile to trades.csv (the
  `2022 2.01(G. Pickens)` label on the received side of each deal, both mirror
  sides confirmed). First = origin, made by plehv79 (= Team), 2 pick-trades ==
  picks `Number of trades` = 2 (the pick changed hands twice before being made;
  the post-draft player trades are the player's chain, not the pick's count).

---

## Verification

- `pytest tests/ -q`: **15 passed**, 0 failed / 0 skipped (incl. the full-build
  `test_player_history_continuity` and `test_pick_chain_link_integrity`).
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- Part C structural sweep re-run post-fix on the rebuilt workbook: still 793
  attached / 0 missing / 0 mismatched / 0 undocumented; all 3 corrected tooltips
  render byte-for-byte as written.
- Build artifacts reverted; only `src/formulas.py` (the 3 fixes) + this new file
  remain.

## Conclusion

**Part C found 3 real doc/code-drift defects** — all tooltip TEXT, all fixed in
`src/formulas.py`, all the same root cause (a count hard-coded to the 17-week
2021+ seasons that silently mis-states the completed 16-week 2020 ESPN season):
1. `PF` said the Semifinal +5 homefield lands on "(Week 16)" — for 2020 it lands
   on Week 15 (the code applies it at `playoff_start`, 15 for 2020 / 16 for 2021+).
2. `Win %` said "(17 games in a completed season)" — 2020 was a completed 16-game
   season.
3. `Record` said "(17 in a completed season)" — same 2020 16-game miss.

The Part C structural sweep is otherwise CLEAN (793 comments, 0
missing/mismatched, 0 undocumented), and the 4 Round-7 fixes are re-confirmed
correct with no regression. **Part D is fully CLEAN at full population** — 450
picks + 649 players all present, 4,727 event lines with 0 fabrications, 0
chronological inversions, 0 dangling refs, 0 missing-comment-with-real-history, 0
true (cross-team) teleports (the 5 same-team add→add pairs are the documented
Sleeper duplicate-add pattern), with novel chains (Cooper Kupp, Wan'Dale Robinson,
2022 2.01 George Pickens) verified end-to-end and Ryan Tannehill confirmed as the
benign same-team dup-add case.

This continues the Round 2-7 pattern: broader/deeper full-population checks keep
surfacing real, narrow defects sample-based checks miss — here a *third* family of
tooltips (after Round 6's retention/playoff-elimination and Round 7's
startup/vet-draft labels) that drifted around the same 2020-vs-2021 structural seam
(the 16-week ESPN season vs the 17-week Sleeper seasons).
