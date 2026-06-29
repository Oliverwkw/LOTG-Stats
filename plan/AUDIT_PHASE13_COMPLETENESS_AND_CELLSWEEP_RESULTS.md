# Phase 13 Round-4 audit — results (full-population completeness + cell/comment sweep)

Self-designed battery (`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`,
Parts A-J) run against PR #319 (`claude/phase-13-audit-tsapoy`) on top of
`fba4dd7` (all Round 1-3 fixes). 5 sub-agents, one part-pair each, run
sequentially (worktree-creation in this environment repeatedly produced
stale base commits — each agent now self-verifies and fast-forwards to the
branch tip before doing any work). **6 distinct real bugs found and fixed
across 4 commits**, two part-pairs came back clean.

## Parts E & F — domain bounds + N/A correctness (`a1dd0dd`): 3 fixes

1. **`Age difference` (transactions) fabricated a spurious value on
   single-side rows.** Treated the missing side of a single-side
   transaction as age 0, producing a bogus ±30-40 "year" gap on
   780/1504 rows. Fixed to require both ages present.
2. **`Total FAAB bid` wrongly N/A'd a genuine $0 total.** `... or None`
   collapsed real $0 totals (uncontested/all-$0 claims) to N/A on
   126/389 2022+ waivers. Fixed to preserve real 0.
3. **`Number of times dropped/picked up by this team` undercounted
   synthesized pure-drop rows.** The running-count pass ran before
   57 synth rows were appended. Added a re-tally after synthesis;
   433 drop-only rows now counted correctly.

## Parts A & B — league-history completeness + reconciliation (`7acbd11`): 2 fixes

Enumerated the full expected grid (6 seasons x 8 teams x real week counts;
450 picks; 496 trades; 1504 transactions) and diffed against actual rows —
0 missing/extra at the structural level, but:

1. **player_year/player_all_time undercounted drops/transactions for
   synthesized lineage-closing rows** (2020->2021 platform-transfer
   releases, terminal dead-end cuts, synthesized arrivals) — the
   per-event counters fired before these rows were appended. 54
   (pid,season) drop undercounts + 72 transaction undercounts. Rebuilt
   the counters from the final rendered transactions ledger (single
   source of truth) instead of the scattered per-event counts.
2. **A Sleeper full_name-collision pid got a phantom `player_all_time`
   row** with no `player_year` backing, also pulling the real player's
   trade count by name collision. Fixed by requiring a `player_year` row
   before padding `player_all_time`.

Part B (cross-sheet numeric reconciliation) was independently verified
clean at full scale after the fix: 0 mismatches across every invariant
(pa==Σpy, league_week==Σteam_week, Record==ΣWin?, all 12 award rollups).

## Parts C & D — comment accuracy (`c549e42`): 1 fix

New check type — first time the audit series checked comment TEXT, not
just cell values, for accuracy.

- **Header tooltips (793 across 12 sheets):** 0 missing, 0 misattached,
  0 wrongly-resolved cross-sheet collisions (17 same-name columns with
  per-sheet-specific definitions all verified correct). 1 doc/code drift
  found: **`Hardship`'s tooltip described a schedule-strength metric
  ("opponent average max PF") that the code doesn't compute** — the
  actual formula sums fantasy points lost to injured/suspended would-be
  starters. Stale since an earlier commit. Fixed the tooltip text in
  `src/formulas.py` to match the real computation.
- **Asset-history hover-comments (450 picks + 649 player_all_time, full
  population):** 0 fabricated events, 0 unknown teams, 0 chronological
  inversions, 0 dangling refs, 0 missing comments for rows with real
  history. Clean.

## Parts G & H — asset-chain link integrity + workbook structure (`698ccea`): 1 fix (root-caused, not just patched)

A first attempt at this part ran out of session budget mid-investigation
but left a real, diagnosed finding with a draft fix; the relaunched agent
independently re-derived the bug from scratch before trusting it, confirmed
it was real, and fixed the root cause rather than the inherited patch:

- **Pick-chain key collisions caused bogus self-links between sibling
  picks.** `pick_chains` was keyed by `(year, round, original-owner)`,
  which isn't unique when one team holds multiple same-round picks that
  were originally its own (e.g. BROsenzweig's 2025 5.02/5.03/5.06,
  JacobRosenzweig's 2025 5.01/5.05). All such picks' draft-terminal
  entries collided into one bucket, so "previous/next transaction"
  lookups could return an unrelated sibling pick's terminal instead of
  the real trade (or `None`). Confirmed 6 sibling self-links pre-fix.
  **Fixed at the root**: re-keyed `pick_chains`/`pick_home_phref` by the
  full numbered identity `(year, round, number-within-round, orig)`
  instead of patching the lookup to skip extra terminals. Also fixed a
  related pre-existing gap this exposed: the 2.09 "toilet pick"'s trades
  were keyed under a `_R209` sentinel round while its draft terminal used
  the displayed round 2, so it never linked to its own trade chain —
  aligned both sides to `_R209`.
- Added `tests/test_pick_chain_links.py` (in-range + no-sibling-self-link
  + pick<->trade round-trip) as a permanent regression guard; verified it
  fails on a synthetic pre-fix sibling-link and passes post-fix.
- Workbook-structural sweep (Part H): 63,415 hyperlinks all in-range with
  correct targets (0 off-by-one across 4,054 single-ref display links),
  1,892 comments all valid UTF-8 (0 garbled), freeze panes/tab
  colors/conditional formatting all match current sheet extents. Clean.

## Part I & J — ESPN-2020 re-verification + build cleanliness: PASS, no new defects

Re-applied the same full-population rigor specifically to 2020 (the
structurally distinct ESPN-email-backfill pipeline) as the highest-risk
area for a comment/data mismatch or a 2020-specific edge case in the
Parts G/H pick-chain fix:

- Completeness: 2020 team_week grid complete (128/128); trades/transactions
  reconcile exactly to the raw ESPN ledger with documented exclusions
  (1 unresolved pick-only trade entry; 5 ESPN offseason moves outside the
  scored-week range, verified non-harmful — none teleport into a 2021
  roster).
- Comment accuracy: all 261 player + 195 picks comments mentioning 2020,
  and all 399+225 dated-2020 event lines inside them, reconcile exactly
  to the ledger — 0 fabricated dates/teams, 0 inversions.
- Link integrity: 0 out-of-range/inverted/round-trip-broken links across
  all 2020-involved rows; 66 forward 2020->2021 cross-boundary links, all
  correctly forward (no teleports across the pipeline seam); the Parts
  G/H pick-chain fix re-verified clean at the Aug-2020 startup-draft
  boundary (all 152 startup picks: 0 sibling self-links, correct origin,
  no pre-draft "next" events).
- `pytest tests/ -q`: 15 passed, 0 failed, 0 skipped. Clean offline build,
  no new warnings.

## Conclusion

Round 4 — the first round to check full populations instead of samples,
and the first to audit comment TEXT (not just cell values) — found and
fixed **6 distinct real bugs across 4 commits**:
`a1dd0dd` (3 fixes), `7acbd11` (2 fixes), `c549e42` (1 fix), `698ccea`
(1 root-caused fix + 1 related gap + a new regression test). Two of the
five part-pairs (C/D barring the one tooltip drift, and I/J) came back
clean on full-population checks.

This continues the pattern from Rounds 2-3: broader/deeper checks than a
prior round keep surfacing real, narrow bugs that narrower or
sample-based checks missed — particularly around synthesized/padded rows
(the recurring theme: counters and key uniqueness assumptions that hold
for real, organically-created rows can break for rows added by a later
synthesis/padding pass). All fixes are verified at the same
full-population scale that found them, plus the existing pytest suite
(15/15 passing, up from 14 with the new pick-chain regression test).

No further audit rounds are currently planned for this self-designed
battery; per the standing instruction, future rounds with fresh examples
remain available if requested.
