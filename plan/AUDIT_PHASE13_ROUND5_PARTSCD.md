# Phase 13 Round 5 — Parts C+D (header-comment accuracy + asset-history narrative accuracy)

Self-designed full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy` (worktree self-verified — the recurring
stale-worktree environment bug recurred: HEAD landed at `6d83635`, behind the
branch tip; fast-forward-reset to `daaa38a`, the just-landed Parts A/B
commissioner-wash fix, before any work). Build under audit: offline build
(`scripts/offline_build.py`, exit 0; only the expected `api.sleeper.app` /
`espn_2020_draft` network-unavailable warnings). trades.csv rebuilt to 504
rows (+4 from the A/B wash-sweep fix), picks.csv 450 rows — the freshly-built
export, not a stale cache.

All examples below are NOVEL — different players/teams/picks than every prior
round (avoiding Pacheco, Jefferson-as-example, DJ Moore-as-example, Tyler
Johnson-as-example, Larry Fitzgerald, Cam Newton, Mike Gesicki, the
BROsenzweig/JacobRosenzweig pick examples, X. Worthy, etc.). The 4
wash-fix-surfaced trades (Doctson/Pickett/Henry/Osborn) are checked
specifically as a genuinely novel surface (those trades existed in no export
when any prior comment-accuracy audit ran).

**Result: CLEAN — 0 defects found in Parts C or D.** Three apparent anomalies
were each run to ground and shown to be correct behavior (a phantom
same-roster re-add the comment correctly omits; same-name pid collisions where
the comment correctly tracks one pid; and multi-origin pick headers where the
flagged "wrong" first line is a legitimately-earlier pick-origin header and
the row's OWN header is present further down). No code change required.

---

## Part C — Header-comment (column-tooltip) accuracy sweep

Resolved every header tooltip in the built workbook via
`formulas.column_definitions()` exactly as the build does
(`(sheet, normcol)` per-sheet key first, then `(None, normcol)` global
fallback; identity columns in `IDENTITY_ALLOWLIST` skipped) and diffed against
the comment text actually attached to each header cell across all 12 data
sheets.

- **Coverage — CLEAN.** `formulas.undocumented_columns(catalog)`, with the
  catalog built from the REAL built-workbook header rows (not a static list),
  returns **NONE** — every non-identity, non-generated column on all 12 data
  sheets has a Formulas entry.
- **Attachment — CLEAN.** **793** header comments attached. **0 missing**
  (every documented non-identity column carries its tooltip), **0 mismatched**
  (every attached comment's text equals the expected per-sheet/global
  definition byte-for-byte), **0 unexpected** (no comment attached to an
  identity/undocumented column).
- **Doc/code drift — CLEAN.** Spot-confirmed the formula text still matches the
  code TODAY for a novel sample beyond the C/D Round-4 `Hardship` fix: the
  picks `Number of trades` tooltip (count of trade hops incl. off-platform
  commissioner moves, awards count 0) matches `_pick_hist_lines`'s `_ntr`
  accounting; the picks `Number` tooltip's snake-draft even-round reversal
  (`position = team_count + 1 − draft_slot`) matches the displayed `2.??`
  blanking + 2.09/5.xx fixed-slot logic; `Commissioner wash exclusion`'s
  tooltip ("a trade the commissioner reversed" is covered) is consistent with
  the A/B fix that now EXEMPTS trade-type txns from deletion — the tooltip
  describes the no-op legs that still wash, not the surviving trade, so it is
  not stale after the A/B change.
- **Cross-sheet same-name collisions — CLEAN.** **17** column names carry
  sheet-divergent definitions (e.g. `number of trades` across 10 sheets,
  `tanking` across team-sheets vs transactions/trades, `pf` team_week vs
  league, `top team` player_year-alias vs player_all_time-most-time,
  `length of tenure on team` picks vs transactions, `player addition value`
  picks vs transactions, the 9 `avg/net/difference points*` trades vs
  transactions vs picks). **0 misattributed** — each sheet's header resolves
  to ITS OWN definition. Verified the fallback path too: sheets in a collision
  group that lack a sheet-specific entry (e.g. `number of trades` on
  player_week/team_week/league_week) correctly inherit the
  subject-count definition, and `picks` correctly gets the pick-specific
  "changed hands by TRADE" text rather than the team-subject text.

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the column-1 hover comment from every picks row (**450/450
present**) and every player_all_time row (**649/649 present**) — **0 rows with
real history but a missing/empty comment** (the inverse failure mode). Then:

- **Chronology — CLEAN.** Parsed every dated line in all 1,099 comments;
  **0 chronological inversions** (no comment narrates a later-dated event
  before an earlier one).
- **Dangling refs — CLEAN.** **0** `T#N` / `PH#N` / `#N`-style references in
  any history text point out of range or to a non-existent row (the
  narrative comments are plain-English by design; none smuggle a bad ref).
- **Fabrication — CLEAN.** Cross-checked **2,656** dated event lines
  (`added by` / `dropped by` / `traded to`) across all 649 player comments
  against the real `transactions.csv` / `trades.csv` rows, matched on
  `(date, team)` + player/asset membership: **0 fabricated add lines, 0
  fabricated drop lines, 0 fabricated trade lines**. Every claimed event
  actually occurred, attributed to the stated team.
- **Pick origin & draft attribution — CLEAN.** For all **450** picks, the
  pick's OWN origin header (`{yr} {num} — originally {orig}'s pick`) is present
  in its comment (0 missing); for all **353** MADE picks, the pick's OWN draft
  line naming its drafted player + number is present (0 missing).

### Wash-fix trades (novel surface) — correctly reflected

The 4 trades that newly survive after the A/B commissioner-wash fix all appear
correctly in the affected players' history comments AND reconcile with the
trade counts:

- **Josh Doctson**: comment line `2022-11-30: traded to BROsenzweig
  (… got Josh Doctson; sent $1 FAAB)` — matches both mirror rows in
  trades.csv; all-time Number of trades = 1.
- **Kenny Pickett**: 2 trade lines (`2024-08-05 → LWebs53`,
  `2024-09-20 → JacobRosenzweig … sent K.J. Osborn`); all-time trades = 2
  (exactly the count cited in the A/B writeup).
- **K.J. Osborn**: the 2024-09-20 Pickett↔Osborn swap appears from Osborn's
  side as `traded to BROsenzweig (… got K.J. Osborn; sent Kenny Pickett)` —
  the mirror of Pickett's line, directions consistent; all-time trades = 5.
- **Hunter Henry**: the 2024-09-18 → Oliverwkw and 2024-09-20 → AceMatthew
  legs both present; all-time trades = 5.

The two sides of the newly-surviving same-UTC-day Pickett↔Osborn swap mirror
each other in the comments with no teleport and no double-count — the narrative
layer absorbed the A/B fix cleanly.

### Three anomalies investigated → all correct behavior, not defects

A deliberately strict count-based cross-check surfaced three apparent
discrepancies; each was root-caused and shown to be correct:

1. **Tyler Johnson — comment shows 3 of 4 raw `Player Added` rows.** The
   omitted row (2021-11-14 LWebs53 free-agent add, no drop) is a Sleeper
   duplicate "add" of a player ALREADY on the roster (added 2021-11-13, not
   dropped until the 2021-11-15 trade to shmuel256). The comment's chain
   (added 11-13 → traded 11-15 → dropped by shmuel256 12-01 → re-added 12-22 →
   dropped 12-22 → added 2024-09-10 → dropped 2024-09-27) is gap-free and
   causal. The comment is MORE correct than the raw row count — it omits a
   physically-impossible re-add. Not a defect.

2. **DJ Moore / Justin Jefferson — extra `Player Added`-by-name rows not in
   the comment.** Genuine Sleeper name collisions: "DJ Moore" = WR pid 4983 +
   CB pid 4961; "Justin Jefferson" = WR pid 6794 + LB pid 13524. The
   player_all_time row + comment correctly belong to the WR pid (DJ Moore
   drafted 2020 5.02 by LWebs53; Justin Jefferson drafted 2020 11.01 by
   Oliverwkw — both with complete draft→trade chains). The "extra" free-agent
   adds-by-name are the OTHER pid (the defender) and correctly do NOT appear in
   the WR's history. Pre-existing condition documented across prior rounds (the
   Round-4 phantom-row guard already prevents a SECOND phantom row); not
   introduced or affected by the A/B fix; the narrative is accurate. Not a
   defect.

3. **17 picks whose comment's FIRST line names a different origin than the
   row's `Original Team`.** All are 2020 startup picks (rounds 7–19) whose
   drafted player was later traded as a FUTURE pick that became them (e.g.
   Odell Beckham, 2020 7.06 plehv79, later moved as the "2023 4.07" pick →
   that pick's `0000` origin header sorts to line 1; Matt Ryan, 2020 19.01
   Oliverwkw, also re-drafted 2021 vet 2.05 BROsenzweig). The pick comment IS
   the drafted player's full history, which legitimately carries MULTIPLE
   pick-origin headers. The row's OWN header (`2020 7.06 — originally
   plehv79's pick`) is present (line 2) — verified for all 450 picks (0
   missing). Multi-origin headers are correct narrative behavior. Not a defect.

---

## Verification

- `pytest tests/ -q`: **15 passed** in ~77s (incl. the full-build
  `test_player_history_continuity` and `test_pick_chain_link_integrity`).
- Offline build: exit 0, no new warnings.
- Build artifacts reverted; `git status` clean except this new file.

## Conclusion

**Parts C and D are CLEAN at full population.** Header tooltips: 793 attached,
0 missing / 0 mismatched / 0 misattached, complete coverage, 17 cross-sheet
collisions all correctly resolved per-sheet. Asset-history comments: 450 picks
+ 649 players all present, 2,656 event lines with 0 fabrications, 0
chronological inversions, 0 dangling refs, 0 missing-comment-with-real-history.
The 4 A/B-surfaced wash-fix trades are correctly reflected in both narrative
and counts (Kenny Pickett all-time trades = 2, matching A/B). Three strict-check
anomalies each resolved to correct behavior (phantom re-add omission, same-name
pid collisions, multi-origin pick headers). No code change required.
