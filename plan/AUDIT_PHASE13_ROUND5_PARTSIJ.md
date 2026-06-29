# Phase 13 Round 5 — Parts I+J (ESPN-2020 re-verification + build/test cleanliness)

Self-designed full-population audit repeating the Parts I/J methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. This is agent 5 of 5 (the LAST of the round).

Worktree self-verified — the recurring stale-worktree environment bug recurred
(HEAD landed at `6d83635`, behind the branch tip; `37b92ee` was NOT an ancestor
of HEAD). Hard-reset to `origin/claude/phase-13-audit-tsapoy` (`37b92ee`, the
just-landed Parts G/H writeup) before any work, then confirmed the reset tip.

Build under audit: fresh offline build (`scripts/offline_build.py`, exit 0; only
the expected `api.sleeper.app/v1/league/0` and
`api.sleeper.app/v1/draft/espn_2020_draft` network-unavailable warnings) — not a
stale cache. Pre-fix export reflected both prior round-5 fixes: trades.csv 504
rows, picks.csv 450, transactions.csv 1,512, player_all_time 649, player_year
1,857.

All examples below are NOVEL — different players/teams than every prior round
(deliberately avoiding Josh Doctson, Kenny Pickett, Hunter Henry, K.J. Osborn,
Carter, Stevenson, Pacheco, Jefferson, DJ Moore, Tyler Johnson, Larry
Fitzgerald, Cam Newton, Mike Gesicki, BROsenzweig/JacobRosenzweig pick examples,
the 2026 2.09 toilet pick, AND the generic "261 player / 195 picks" aggregates
the original Round-4 Part I/J used). The novel 2020 spot-cases used here are the
2020 ESPN email-trade players: Kerryon Johnson, Stefon Diggs, Robbie Chosen,
Myles Gaskin, Clyde Edwards-Helaire, Aaron Jones, T.J. Hockenson, Ryan
Fitzpatrick, Damien Harris, Mike Davis — plus the defect case Mitchell Trubisky
and the regression-guard cases Alexander Mattison / Kenyan Drake / Jakobi Meyers
/ Taysom Hill / Hayden Hurst.

**Result: 1 real defect found and fixed** (`src/lotg.py`) — a 2020->2021
platform-seam TELEPORT: a player on a team's final 2020 (ESPN) roster who was
absent the entire 2021/22 Sleeper seasons and then re-added by the SAME team
years later had his 2020 add chain straight across the empty seasons to that
later re-add, with no transfer-day drop closing the 2020 holding. Everything
else in Parts I and J is CLEAN at full population.

---

## Do the round-5 fixes touch anything 2020-specific? — verified NO (by construction)

The prompt asks specifically whether the Parts A/B trade-wash fix or any other
round-5 fix interacts with the structurally-distinct 2020 ESPN pipeline. Run to
ground, not assumed:

- **Parts A/B wash fix is a provable no-op for 2020.** The commissioner-wash
  sweep flags a player-day only when `_pd_commish` is True, which requires a
  transaction of `type == "commissioner"`. `src/espn_2020.py`'s
  `emit_sleeper_2020` emits ONLY `waiver`, `free_agent`, and `trade` types — it
  emits ZERO `commissioner`-type transactions (grep confirms no "commissioner"
  string in the emitter). Confirmed in the export: all 207 2020 transactions are
  178 `free_agent` + 29 `waiver`, 0 commissioner; all 14 commissioner-typed rows
  league-wide are 2021+. So no 2020 transaction or trade was ever a wash
  candidate — before or after the A/B fix. (The A/B fix's new `_tx_is_trade`
  guard is reached only for txns that would otherwise be wash candidates; 2020
  has none.)
- **Parts E/F 2.09-Unknown fix is 2026-only** — it touches the synthetic 2.09
  toilet-reward future-pick emission, which never produces 2020 rows.
- 2020 trade count is unchanged by the round-5 fixes (12 events, exactly the
  pre-round-5 baseline).

So the only round-5 interaction with the 2020 pipeline is my OWN Part I fix
below — which is itself a 2020->2021 boundary fix.

---

## Part I — ESPN-2020 specific re-verification (full population)

### 2020 completeness — CLEAN
- **team_week grid:** 8 teams × 16 weeks = 128 rows, complete; every team has
  exactly weeks 1..16, 0 gaps, 0 phantom weeks. league_week 2020 = 16 weeks
  1..16.
- **team_year** 8/8 teams; **player_year** 247 rows; **player_week** 2,632 rows
  / 236 distinct players. No 2020 season silently short.

### 2020 trades raw-vs-export reconciliation — CLEAN (DST-aware)
Reconciled the raw ESPN ledger (`data/espn_2020_raw/email_trades.json`, 13
entries) against trades.csv 2020 rows:
- 12 email trades carry player legs → exactly **12 distinct export trade events
  (24 mirror rows)**. 1 empty-leg entry (2020-09-09, `involves_picks=true`, the
  one on-platform startup-slot swap with no legs) is the documented exclusion.
- Date sets match exactly once converted UTC→America/New_York (the only apparent
  mismatch, email `2020-09-30T02:18Z` vs export `2020-09-29`, is the EDT local
  shift, not a missing trade).
- The reconstructed PICK legs in the comments (e.g. CEH's `2021 1.05(J. Williams)`
  on 2020-12-01; the Ryan-Fitzpatrick/Cook 2020-11-29 nine-pick bundle; the
  Hockenson `2021 2.01(J. Fields)` on 2020-12-16) each map to a row in
  `data/commissioner_pick_trades.csv` matched on the exact UTC `created` — not
  fabricated.

### 2020 comment accuracy — CLEAN (0 fabrications, full population)
- **All 39 2020-dated `traded to` lines** across every player_all_time comment
  reconcile to a real email trade event on that local date with the named
  recipient — **0 fabrications**.
- **All 175 2020-dated `added by` lines** reconcile to a real transactions.csv
  2020 add event `(date, team, player)` — **0 fabrications**.
- **0 chronological inversions** across all 649 player + 450 pick comments.
- **2020 startup-draft picks:** all **152** (19 rounds × 8 teams) carry their
  own origin header AND (for made picks) their own draft line — 0 missing. Novel
  spot-confirms: Aaron Jones `startup 4.07` orig BROsenzweig; T.J. Hockenson
  `startup 13.02` orig LWebs53; Kerryon Johnson `startup 13.04` orig AceMatthew;
  Robbie Chosen `startup 16.07` orig BROsenzweig — each matching the email-trade
  origins.

### 2020->2021 cross-boundary link integrity (no teleports) — **1 DEFECT FOUND + FIXED**

The platform-seam (ESPN 2020 → Sleeper 2021) is the highest-risk Part I surface.
A direction-and-range sweep of every `T#`/`#`/`PH#` ref in every link column
(**4,070 refs pre-fix**) found 297 refs crossing the 2020/2021 boundary, all
correctly forward/backward — **0 wrong-direction teleports in the link columns**.

But a *narrative*-layer full-population scan (every player history comment for
the pattern "2020 `added by` immediately followed by a 2021+ `added by`, no
intervening close") surfaced exactly **1 row**:

**Mitchell Trubisky** — `2020-12-23: added by LWebs53 (free agent)` → next event
`2023-12-06: added by LWebs53`. His 2020-12-23 add's `Date dropped/traded` read
**2023-12-06** and its next-link pointed at the 2023 drop, **teleporting the
holding across all of 2021 and 2022** — seasons in which Trubisky has NO
player_week rows on any team (player_year 2020 `Number of drops = 0` → he ended
2020 on LWebs53's roster; he reappears only in 2023 weeks 14-15 on LWebs53).

**Root cause** (`src/lotg.py`, the 2020->2021 transfer-drop synthesis, ~line
7150). Two synthesis mechanisms exist to close a 2020 holding at the platform
seam, and Trubisky fell through the gap between BOTH:
1. The **terminal-orphan roster-diff** synth (within-season dead-end cuts) skips
   him because his last 2020 week (16) IS the season's final week — no
   within-season gap to detect.
2. The **transfer-day drop** synth was gated by `not _has_2021_arrival`: any
   2021+ re-acquisition suppressed the transfer drop (correctly, for vet
   re-drafts like AJ Dillon). But Trubisky's re-acquisition is by the **SAME
   team (LWebs53) in 2023** — and the general arrival-anchored reconciliation
   only synthesizes the old team's drop when a **DIFFERENT** team picks the
   player up. A same-team re-add after a multi-season gap closes nothing, so the
   `_has_2021_arrival` suppression left the 2020 holding permanently open.

**Fix.** Track `_arrival_2021_team` (the team of the first 2021+ recorded
re-acquisition) and a `_pids_in_2021` set (every pid on any scored 2021 roster).
Fire the transfer-day drop when the player is held by the boundary team AND
(no 2021+ recorded re-acquisition at all — original behavior) OR (the
re-acquisition is by the SAME boundary team AND the player is absent from the
ENTIRE 2021 season — a genuine release into the void followed by a fresh later
stint). This is deliberately the NARROWEST condition that closes the teleport:

- A first attempt keyed only on "re-acquired by a different team" over-fired:
  it incorrectly dropped **Alexander Mattison** (on LWebs53's 2020 final roster
  AND continuously on LWebs53 all of 2021 — a true carryover whose first 2021
  scored week is week 3, so he's absent from the literal week-1 snapshot
  `first_wk_roster_st`). Adding the "absent from the entire 2021 season" guard
  fixes that.
- A second attempt (same-team-after-gap using only per-team 2021 presence)
  introduced a DOUBLE-DROP for **Kenyan Drake** (on LWebs53's 2020 final roster,
  then on JacobRosenzweig ALL of 2021 via a roster-snapshot-only arrival with no
  recorded transaction): firing an LWebs53 transfer drop duplicated the existing
  general-reconciliation LWebs53 drop. Requiring absence from the ENTIRE 2021
  season (any team) — not just this team — leaves Drake (and the similar
  Jakobi Meyers→plehv79, Taysom Hill→LWebs53 moves) untouched, since each is on
  SOME 2021 roster. Those moved-to-another-team-at-the-transfer cases are a
  pre-existing roster-snapshot-arrival condition the baseline already handles;
  the fix does not touch them.

**Post-fix verification (full population):**
- The fix synthesizes **exactly 2** transfer drops vs. baseline (ADDED 2,
  REMOVED 0): **Mitchell Trubisky** (LWebs53) and **Hayden Hurst** (stevenb123)
  — the only two players on a 2020 final roster who are absent from the entire
  2021 season and re-acquired later by that same team. Both teleports closed:
  Trubisky now `2021-08-23: dropped by LWebs53` between the 2020 add and the 2023
  re-add.
- **0 boundary teleport suspects**, **0 consecutive same-team double-drops**,
  **0 chronological inversions** across all 649 player + 450 pick comments
  post-fix.
- **Regression guards all correct:** Mattison (carryover) — no transfer drop;
  Drake→JacobRosenzweig, Meyers→plehv79, Taysom Hill→LWebs53 (moved teams) — no
  transfer drop; AJ Dillon / Matt Ryan / Tony Pollard (the documented prior-bug
  cases) — still exactly ONE 2020-12-31 drop each, no spurious second.
- Cross-boundary link sweep re-run on the rebuilt workbook: 4,074 refs (+4 from
  the 2 new synth rows' links), **0 out-of-range, 0 wrong-direction teleports**.
- The 2 new rows produce 2 transaction-only player_year rows
  (Trubisky-2021, Hurst-2021: 1 tx / 1 drop / NaN points / 0 starter weeks —
  the documented "added+dropped between snapshots" pattern). transactions.csv
  1,512 → 1,514; player_year 1,857 → 1,859.

---

## Part J — Build/test cleanliness — CLEAN

- **`pytest tests/ -q`: 15 passed** in ~78s, 0 failed / 0 skipped — INCLUDING
  the full-build `test_player_history_continuity` (validates roster-lineage
  continuity end to end, so it confirms the 2 new transfer drops do NOT break
  continuity) and `test_pick_chain_link_integrity`. No net-new warnings vs the
  pre-round-5 baseline.
- **Offline build: exit 0**, only the 2 expected network-unavailable warnings
  (`api.sleeper.app/v1/league/0`, `…/draft/espn_2020_draft`). No new warnings,
  no tracebacks.
- The cumulative round-5 src diff (`src/lotg.py`: A/B wash fix + E/F 2.09-Unknown
  fix + this Part I transfer-drop fix) introduces no net-new pytest warnings or
  regressions vs the pre-round-5 baseline (15/15 throughout the round).
- **`git status` clean** after reverting build artifacts — only `src/lotg.py`
  (the fix) + this new file.

---

## ROUND 5 OVERALL SUMMARY — NOT fully clean (3 defects fixed this round)

This 5-agent (Parts A/B … I/J) self-designed full-population audit pass found and
fixed real defects, so it is **NOT a clean pass**:

| Agent / Parts | Result |
|---|---|
| **A/B** — completeness + cross-sheet reconciliation | **1 fix**: commissioner-wash sweep deleting 4 real same-UTC-day-reversed trades (2022 Josh Doctson, 2024 Kenny Pickett, 2024 Hunter Henry, 2024 K.J. Osborn↔Pickett). None involved draft picks. trades.csv 496→504. |
| **C/D** — header-comment + asset-history narrative accuracy | CLEAN |
| **E/F** — domain-bounds + N/A-vs-0-vs-blank | **1 fix**: undrafted 2026 2.09 toilet-reward pick rendered `Player Picked = "N/A"` instead of the `"Unknown"` placeholder the other 96 undrafted future picks use. |
| **G/H** — link integrity + workbook structure | CLEAN |
| **I/J** — ESPN-2020 re-verification + build/test cleanliness | **1 fix**: 2020->2021 platform-seam teleport — a player on a 2020 final roster, absent all of 2021/22, re-added later by the same team had no transfer-day drop, so the 2020 add teleported across the empty seasons (Mitchell Trubisky, + Hayden Hurst). |

> NOTE: An interim writeup (Parts G/H) stated "this round so far found/fixed 2
> defects." With this Parts I/J finding the round total is **3 defects fixed**
> across 3 of the 5 agent-pairs (A/B, E/F, I/J); C/D and G/H came back clean.

Per the user's repeating-cycle instruction: because this 5-agent audit pass was
**not fully clean** (3 fixes were needed), this whole 5-agent audit type must be
**re-run with fresh examples** after the 10-part audit stage, as part of
repeating the 3-part / 5-agent / 10-part cycle until all three audit types come
back clean on consecutive passes.

This continues the Rounds 2-4 pattern: broader/deeper full-population checks keep
surfacing real, narrow bugs that sample-based checks miss — here, three distinct
same-day / cross-pipeline / cross-season edge-interactions (a same-UTC-day
commissioner reversal, a synthesized-future-pick placeholder divergence, and a
same-team re-acquisition across the ESPN→Sleeper platform seam) that each held
for the common case but broke for one narrow row.
