# Phase 13 Round 12 — Parts C+D (header-comment / tooltip accuracy + asset-history narrative accuracy)

Self-designed full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 2 of 5 in Round 12 (sibling Parts A/B —
`AUDIT_PHASE13_ROUND12_PARTSAB.md` — landed CLEAN at `50a86fc`).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (`git merge-base --is-ancestor 50a86fc HEAD` printed
NOT_OK; `50a86fc` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`50a86fc`, the Round-12 Parts A/B tip
carrying all Round-5..Round-12/AB fixes), then confirmed `OK_AT_OR_AHEAD` with
`git log -1 --oneline` showing `50a86fc`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: 450 picks,
649 player_all_time rows, **1,099 asset-history hover comments** (649 player +
450 pick), and the full **432-row `_ROWS` tooltip catalog** in `src/formulas.py`.

All examples below are NOVEL — different stats/players/picks/teams than every
prior round (Rounds 4-12/AB + Rounds 5-11 C/D exclusion lists honoured). This
round deliberately targeted stat tooltips NOT scrutinized in recent rounds,
steering well clear of the now-exhausted PF/Win%/Record/O-Score/Number-of-trades/
Taxi-eligible/Result/Hardship/Drafting-skill/All-play/Win-Variance/FAAB/Starter-
PAR families and the 2020-vs-2021 startup/vet seam. New surfaces cited (Part C):
**Increase in points from previous week** (cross-season carry), **UPST**,
**Number of donuts / Number of starter donuts / players-under-10 / over-20..50 /
Difference between highest and lowest starters**, **% of starts made while
rostered / Injury adjusted variant / Number of starts before next drop / Cuff at
time of pickup? / Player addition value**, **Captain? / % of points (if starter)
/ Times as Captain?**, **Differential / Avg differential / Losses from
hardship**, **Win streak vs Win streak counting previous season** (reset vs
carry), the **position/NFL-team starter counts** (Number of QB started / Number
of NFL teams among starting players / Most number of players started from same
NFL team), **PF Range / Margin range / Number of games within 5 / within 10**,
**Highest Win % vs a team / Team for highest Win %**, the picks **Number of
starts before next transaction / Weeks before first start**, and the player_week
**Change from previous week / Change from career average to that point**. Part D
new chains: **Cam Skattebo 2025 2.06** (rookie pick), **Emeka Egbuka 2025 2.01**,
**Keaton Mitchell** (FA/waiver/trade mix), and the novel **2024-09-24 14:24:21
3-team trade** (AceMatthew / shmuel256 / stevenb123).

**Result: CLEAN.** Zero defects found. Every audited tooltip's claimed
formula/behavior matches the actual `src/lotg.py` computation AND the exported
data at full population, and all 1,099 asset-history hover-comments are accurate
(no fabrications, no inversions, no dangling references). No source change
required.

---

## Part C — Header-comment / tooltip accuracy sweep (formula text vs real code + data)

Methodology: cross-checked each tooltip's CLAIMED formula/behavior against the
actual `src/lotg.py` computation AND the exported data, for stats not re-verified
clean in recent rounds. Full population on each numeric claim (every team-week /
team-year / player-week / league-week row, not samples).

### Stats verified CORRECT (tooltip text matches code AND data) — full population

- **Increase in points from previous week** — tooltip: "PF minus the prior
  week's PF (Week 1 compares to last season's final week)." Code
  (`src/lotg.py` 11418-11502): `prev_pf` is initialized ONCE per team (the loop
  groups by `Team` only, the year-reset block does NOT touch `prev_pf`; the
  inline comment at 11422-11424 documents the cross-season carry). Verified on
  NOVEL **shmuel256**: 0 mismatches across all weeks, and week-1 2021 = 143.58 −
  143.90 (the team's last 2020 week) = **−0.32** — proving the cross-season
  carry. CORRECT.
- **UPST** — tooltip: "1 if the team won while its pregame avg Max PF was below
  the opponent's." Final assignment (11197-11201) is `(Win? == 1) &
  (Difference in pregame avg max PF from opponent < 0)` (the earlier per-row
  `Max PF < opp_max` pass at 10938-10955 is OVERWRITTEN by this pregame-avg
  version). Recomputed across all 808 team-weeks: **0 mismatches**, total UPST =
  **144**. CORRECT.
- **Number of donuts / starter donuts / players under 10 / over 20-50 /
  Difference between highest and lowest starters** — code (4591-4607): `donuts`
  = roster scores `== 0.0` (exactly zero); `s_donuts` = starter scores `== 0.0`;
  `under10` = `< 10.0`; `over20/30/40/50` = strictly `>`; `diff_hi_lo` = `max −
  min` starter points. Data confirms: 0 team-weeks with starter-donuts > donuts,
  0 negative high-low spreads. CORRECT (matches "scored exactly 0" / "over N" /
  "top minus bottom starter").
- **% of starts made while rostered / Injury-adjusted variant / Number of starts
  before next drop / Cuff at time of pickup? / Player addition value** — code
  (7878-7972): starts = Starter pw rows between Date and drop date; `% of starts`
  = `starts / weeks_played` where `weeks_played` counts ALL weeks (bye/injury
  included — matches "Includes bye and injury weeks in the denominator");
  injury-adjusted excludes Bye?/Injury? from BOTH; Cuff = still-rostered teammate
  who started in any of the 3-week window, same NFL team+position, last-5 PPG ≥
  added + 10 (`(added_avg or 0) + 10 <= mate_avg`); addition value =
  `adj_diff*(1+pct)*(1+pct_inj) + CUFF_BONUS`. Every tooltip clause matches the
  code byte-for-byte. CORRECT.
- **Captain? / % of points (if starter) / Times as Captain?** — code
  (5010, 10362-10369): `% of points (if starter)` = `pts/pf` for starters, None
  for bench; Captain = the single league-wide starter with the max share that
  (year,week), alphabetical tiebreak (`sort_values("_p")`, take index 0). Data:
  exactly **1 Captain per league-week (101/101)**, 0 bench rows with a non-null
  share, and the NOVEL **2024 wk5 Captain = Ja'Marr Chase (share 0.2868)** equals
  that week's max starter share. CORRECT.
- **Change from previous week / Change from career average to that point**
  (player_week) — verified on NOVEL **Jordan Addison**: "week's points − prior
  PLAYED week" and "week's points − career PPG through the prior week" both
  recomputed across his whole career with **0 mismatches** (played-week filter
  excludes bye/injury/suspension, as the Notes state). CORRECT.
- **Differential / Avg differential / Losses from hardship** (team_year/
  team_all_time) — Differential = Σ Margin per period: **0 mismatches** across
  all 48 team-seasons (NOVEL **plehv79 2023 = 63.28** = Σ team_week Margin). Avg
  differential = Differential/games: **0 mismatches**. Losses from hardship =
  count of `Loss from hardship?` True weeks per (Team,Year): **0 mismatches**.
- **Win streak vs Win streak counting previous season** — tooltip: the former
  RESETS between seasons, the latter CARRIES. Verified on NOVEL **Oliverwkw**:
  the within-season streak (reset at year boundary) and the cross-season streak
  (no reset) both recompute with **0 mismatches**. CORRECT.
- **Number of QB started / Number of NFL teams among starting players / Most
  number of players started from same NFL team** — recomputed from player_week
  starters per (Team,Year,Week): **0 mismatches** for all three. CORRECT
  (count of QB starters; distinct NFL teams among starters; largest same-NFL-team
  starter group).
- **PF Range / Number of games within 5 / within 10** (league_week) — PF Range =
  max−min team PF that week: **0 mismatches**; games within 5/10 = count of
  matchups with `|margin| ≤ 5/10` (each game counted once, mirror rows /2): **0
  mismatches** both. CORRECT.
- **Highest Win % vs a team / Team for highest Win %** (team_all_time) — across
  all 8 teams, "Highest Win % vs a team" equals the max of the per-opponent
  `Win % vs <opp>` columns AND the named "Team for highest Win %" opponent
  carries exactly that value: **0 discrepancies**. CORRECT.
- **Number of starts before next transaction / Weeks before first start**
  (picks) — every one of the **353 made picks** has a starts value ≥ 0 (0 NaN,
  0 negative); all **97 unmade ("Unknown") picks** are N/A (0 non-null). Matches
  the "≥ 0 for every made pick, N/A only for an unmade pick" tooltip exactly.
- **Number of teams involved** (trades) — distribution: **474 rows = 2, 30 rows
  = 3**, none < 2. Matches "2 for a normal swap, 3+ for a multi-team trade".

Every audited tooltip matched both the code and the data with NOVEL examples. No
drift found in this round's (large) novel surface — Part C is CLEAN.

---

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the col-1 hover comment from every row of the rebuilt workbook
(`exports/LOTG_Stats.xlsx`): **649 player_all_time + 450 picks = 1,099**
comments, every row covered (0 missing). Cross-checked against `trades.csv`,
`transactions.csv`, and `picks.csv`.

### Full-population automated checks — CLEAN
- **Dangling / malformed-reference sweep** across all 1,099 comments (empty
  `()`, `nan`, `None`, `undefined`, `got ;`, trailing `sent ;`, `;;`, `drafted
  ()`, any `#N`/`T#N`/`PH#N` numbered link-ref): **0 issues**. The narratives are
  plain-English; every `(F. Last)` pick reference resolves; no empty asset lists.
- **Fabrication sweep**: every dated `traded to` / `pick traded to` line
  (matched on (date, receiving-team) against trades.csv) and every `added by` /
  `dropped by` line (matched on (date, team, player) against transactions.csv
  Player Added / Player Dropped) across all 1,099 comments: **0 fabricated trade
  lines, 0 fabricated add lines, 0 fabricated drop lines.**
- **Chronological-ordering sweep**: parsing every explicit `YYYY-MM-DD:` dated
  line in all 1,099 comments, **0 chronological inversions**. (A naive run that
  approximated the dateless "YYYY Draft:" lines at an Aug-28 anchor flagged 36
  comments, but every one is the anchor approximation being too LATE — the
  Sleeper rookie/vet draft genuinely runs in spring/summer, so a post-draft
  May/Jul/Aug trade legitimately follows the draft line; the explicit-dated-line
  check confirms 0 real inversions.)
- **Pick comment trade-count reconciliation** (positional, per workbook row to
  avoid the unmade-pick key collision): for each of the 450 pick comments, the
  count of `pick traded to` + `Commissioner moved` lines vs the row's `Number of
  trades`. **448 match exactly.** The 2 outliers are the documented
  multi-draft-seed behavior (NOT defects): **startup 7.06 Odell Beckham**
  (NumTrades=0, 4 lines) and **startup 17.08 Allen Lazard** (NumTrades=0, 2
  lines) — a startup pick's comment renders the drafted PLAYER's full career,
  seeding every later pick the player was drafted at; the secondary picks carry
  the matching counts (Beckham's **2023 4.07 NumTrades=4**, Lazard's **2022 2.08
  NumTrades=2**), while the startup pick itself correctly reads 0 (never traded).
- **Inverse missing-comment check**: 0 player_all_time rows with real history
  (Number of trades > 0 OR Number of transactions > 0) but an empty comment.

### Manual trace verification with NOVEL examples — all consistent, no inversions
- **Cam Skattebo 2025 2.06** (rookie pick) — Original plehv79 → 2 pre-draft hops
  (2023-11-28 to BROsenzweig; 2024-05-13 to LWebs53) → drafted by LWebs53 →
  player traded 2025-08-11 to stevenb123. Each comment leg renders the RECEIVING
  team's own asset list, matching trades.csv exactly (BROsenzweig/LWebs53/
  stevenb123 each "got …2.06(C. Skattebo)" / "got Cam Skattebo"). Correct
  direction throughout, no inversion.
- **2024-09-24 14:24:21 3-team trade** (AceMatthew / shmuel256 / stevenb123) —
  per-team attribution verified: Mike Gesicki's comment reads "traded to shmuel256
  (shmuel256 got Mike Gesicki; 2026 4(BROsenzweig); sent Keaton Mitchell; 2025
  4.04(D. Neal))" and Keaton Mitchell's reads "traded to stevenb123 (stevenb123
  got Keaton Mitchell; sent 2026 4(BROsenzweig); $8 FAAB)" — each renders the
  RECEIVING team's OWN leg from trades.csv, NOT a counterparty view. Correct
  multi-team per-team attribution.
- **Keaton Mitchell** (FA→trade→drop→FA mix) — 2023-11-08 added by shmuel256
  (waiver $32, dropped Clayton Tune) → 2024-09-24 traded to stevenb123 →
  2025-10-07 dropped by stevenb123 (added AJ Barner) → 2025-10-22 added by
  plehv79 (free agent). Reconciles to transactions.csv/trades.csv exactly;
  player_all_time Number of trades=1, Number of transactions=3 (2 adds + 1 drop),
  drops=1, Last team=plehv79 (the most recent add). The plehv79 add was a $0
  waiver claim rendered as "free agent" — the established convention (`_present`
  treats `0.0`/empty FAAB as absent → "free agent", `$N` otherwise), consistent
  with the $32 shmuel256 add rendering "waiver $32". Not a mislabel.
- **Emeka Egbuka 2025 2.01** — Original JacobRosenzweig → 2025-05-01 pick traded
  to plehv79 → drafted by plehv79 → 2025-07-30 player traded to stevenb123. The
  dated lines are causally ordered (the "2025 Draft" line precedes the 2025-07-30
  trade — correct, the rookie draft is in spring/summer). Directions correct.

**Part D verdict: CLEAN.** No fabrications, no inversions (every trade renders
the receiving team's own asset list, verified including a 3-team deal), no
dangling references, correct draft seeding (incl. the multi-pick startup-seed
behavior) and chronology, all 1,099 comments at full population.

---

## Verification

- `pytest tests/ -q` (via `PYTHONPATH=src:lib python3 -m pytest`): **15 passed**
  in ~63s, 0 failed / 0 skipped — including `test_player_history_continuity` (the
  narrative-continuity guard), `test_pick_chain_link_integrity`, and
  `test_cross_sheet_reconciliation`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
- No source changes required (no defects). Build artifacts reverted; `git status`
  clean except this findings file.

## Conclusion

**Parts C + D are fully CLEAN at full population — ZERO defects.** Part C
cross-checked a large NOVEL set of tooltips (Increase in points from previous
week with cross-season carry, UPST, the donut/score-bucket/high-low-spread
family, the start-rate / cuff / addition-value family, Captain / % of points,
Differential / Avg differential / Losses from hardship, Win-streak reset-vs-carry,
the position & NFL-team starter counts, PF Range / games-within-5/10, Highest
Win % vs a team, the picks start/tenure columns, and the player_week
change-from-prev/career columns) against the real `src/lotg.py` code AND the
exported data — every tooltip's claimed formula/behavior matches with 0 mismatch.
Part D's 1,099 asset-history hover-comments are fully accurate — correct trade
direction, correct per-team multi-team attribution (verified on a novel 3-team
deal), correct draft seeding (incl. the documented startup-pick multi-seed
behavior), correct chronology, zero fabrications, zero dangling references, zero
missing-comment-with-real-history — all reconciling to trades/transactions/picks
at full scale with NOVEL chains (Cam Skattebo, Emeka Egbuka, Keaton Mitchell,
the 2024-09-24 3-team trade). No source change was required for Parts C/D this
round.
