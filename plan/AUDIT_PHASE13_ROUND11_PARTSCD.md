# Phase 13 Round 11 — Parts C+D (header-comment / tooltip accuracy + asset-history narrative accuracy)

Self-designed full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_COMPLETENESS_AND_CELLSWEEP.md`, run fresh against
`claude/phase-13-audit-tsapoy`. Agent 2 of 5 in Round 11 (sibling Parts A/B —
`AUDIT_PHASE13_ROUND11_PARTSAB.md` — landed CLEAN at `898f3df`).

**Worktree self-verify:** the recurring stale-worktree environment bug recurred —
HEAD landed at `6d83635` (`git merge-base --is-ancestor 898f3df HEAD` printed
NOT_OK; `898f3df` was NOT an ancestor of HEAD). Hard-reset to
`origin/claude/phase-13-audit-tsapoy` (`898f3df`, the Round-11 Parts A/B tip
carrying all Round-5..Round-11/AB fixes), then confirmed `OK_AT_OR_AHEAD` with
`git log -1 --oneline` showing `898f3df`.

**Build under audit:** fresh offline build (`scripts/offline_build.py`, exit 0;
only the 2 expected network-unavailable warnings — `api.sleeper.app/v1/league/0`
and `…/draft/espn_2020_draft`). Not a stale cache. Full population: 450 picks,
649 player_all_time rows, **1,099 asset-history hover comments** (649 player +
450 pick), and the full `_ROWS` tooltip catalog in `src/formulas.py`.

All examples below are NOVEL — different stats/players/picks/teams than every
prior round (Rounds 4-11/AB + Rounds 5-10 C/D exclusion lists honoured). This
round deliberately targeted stat tooltips NOT scrutinized in recent rounds
(steering away from the now-exhausted PF/Win%/Record/O-Score/Result/Taxi-eligible
/2020-vs-2021-draft-seam families). New surfaces cited: **Hardship**, **Drafting
skill** (the two Part C defects); **All-play win %**, **Win Variance**, the FAAB
auction family (**Number of bids / FAAB difference over second place / FAAB
premium %**), **Starter PAR / boom% / bust% / volatility**, **Difference from
best startable bench**, the manager-**skill** shrinkage family; and (Part D)
**Tyjae Spears 2023 3.08**, **Romeo Doubs 2022 3.04**, **Rachaad White**,
**Jaylen Warren**, **Matt Ryan** (re-drafted vet), **Odell Beckham**, **Allen
Lazard**, **Kyler Murray**, **Ryan Tannehill** chains.

**Result: 2 real doc/code-drift defects found and FIXED** — both tooltip TEXT in
`src/formulas.py`, both a NEW family (NOT the 2020-vs-2021 seam, NOT the
Round-10 Taxi/Result family):

1. **`Hardship`** — the tooltip claimed Hardship sums "over every **would-be-
   starter** who missed the week" and the Notes asserted "A would-be-starter is
   judged by the same recent-started-share heuristic as Starter-adjusted
   Hardship." **The code does NO such gating.** `Hardship` =
   `Σ _points_lost_inj_susp` (`src/lotg.py` ~10646-10664, 10864, 10888), set for
   EVERY missed (injury/susp, points==0, not bye) rostered player at their FULL
   expected-if-healthy points — starters and bench alike. The would-be-starter
   start-share weighting (`eff_starter_pct`) applies ONLY to
   **Starter-adjusted Hardship** (`_starter_adj_points_lost`). Proven from the
   export: 785 team-weeks have `Hardship > Starter-adjusted Hardship`, and
   AceMatthew 2020 wk1 has `Hardship = 27.24` with `Starter-adjusted Hardship =
   0.0` (week-1 start-share is 0 by design, yet Hardship is non-zero — so
   Hardship cannot be would-be-starter-gated). Fixed the Formula + Notes to
   describe the real "every missed rostered player, full expected points, no
   start gate (so Hardship ≥ Starter-adjusted Hardship)" behavior.

2. **`Drafting skill`** — the tooltip pointed the reader to "`picks.Final Team`"
   as the column identifying the picks a team made. That column was renamed to
   **`picks.Team`** (the picks `Team` tooltip itself documents "(Formerly 'Final
   Team')"); the exported picks sheet has `Team` / `Original Team` and NO `Final
   Team` column, so the reference was a dangling user-visible pointer. Fixed to
   "`picks.Team` (the roster that made the selection, formerly 'Final Team')".

Part D is fully CLEAN at full population. No `src/lotg.py` logic change was
needed (both defects were stale tooltip TEXT; the computed values were correct).

---

## Part C — Header-comment / tooltip accuracy sweep (formula text vs real code + data)

Methodology: rather than re-verify tooltip ATTACHMENT (Rounds 7-10 already
established 793/0/0/0 attached / missing / mismatched / unexpected and
`undocumented_columns()==[]`; re-confirmed stable this round), this round
cross-checked each tooltip's CLAIMED formula/behavior against the actual
`src/lotg.py` computation AND the exported data, for stats not re-verified clean
in recent rounds. Full population on each numeric claim.

### Stats verified CORRECT (tooltip text matches code AND data)

- **All-play win %** — tooltip: "(Σ over weeks of teams with strictly lower PF) /
  (Σ over weeks of other teams); ties count as neither win nor loss but stay in
  the denominator." Code (`src/lotg.py` 16333-16342): `< _r["_pf"]` (strict),
  denominator `n-1` (other teams), tie neither. Independently recomputed from
  `team_week` for NOVEL **shmuel256 2024 (0.6639)**, **Oliverwkw 2021 (0.605)**,
  **plehv79 2025 (0.1429)** — all equal the export to 4 dp. CORRECT.
- **Win Variance** — tooltip: `-1 × (standings_place − (pf_place + maxpf_place)/
  2)`. Code (13403): `-1 * (place - ((pf_place + maxpf_place)/2))`. Byte-exact.
  Spot-checked NOVEL **BROsenzweig 2022 (-1.0)**, **LWebs53 2024 (-0.0)**,
  **shmuel256 2023 (-0.5)**. CORRECT.
- **FAAB auction family** (Number of bids / Total FAAB bid / FAAB difference over
  second place / FAAB premium %) — code (3946-3970, 5461-5556): the bid COUNT is
  tallied BEFORE failed claims are filtered (→ "complete + failed"); runner-up
  excludes bids `> winner_bid_val` (invalidated); premium% = `(win − runner)/
  win × 100`. Verified on NOVEL 2023 contested waivers: **Isaiah Likely**
  (win 21, diff 3 → runner 18, 14.29%), **Kyren Williams** (26, diff 6, 23.08%),
  **Joshua Kelley** (20, diff 5, 25.0%), **Tank Dell** (win 6, 3 bids, diff/
  premium BLANK — the other 2 bids exceeded the win and were invalidated, so no
  valid runner-up). Every value matches the tooltip arithmetic. CORRECT.
- **Starter PAR / boom% / bust% / volatility / floor / ceiling** — code
  (12846-12883): replacement = mean of bottom `ceil(n/3)` started scores per
  (year, week, position); boom = share ≥20×100, bust = share ≤5×100, volatility
  = std, floor/ceiling = min/max over started weeks. Matches tooltips. Sanity-
  checked NOVEL **Brock Purdy** (boom 41.5, PAR 366.65, PAR/g 8.94), **DK
  Metcalf** (PAR 708.47), **Travis Etienne**. CORRECT. (Note: "Share" wording is
  the established 0-100 convention with the `%` in the column name; consistent
  across the whole boom/bust catalog — not drift.)
- **Drafting / Trading / Transaction skill shrinkage** — code (16263, 16279-
  16314): `(Σw·O + 5·50)/(Σw + 5)` (K=5, prior=50); Transaction skill weights
  pure drops 1/3 (`_tx_wt`, 16292-16295), others 1.0. Matches all three
  tooltips. CORRECT (apart from the stale `Final Team` column name, fixed).
- **Difference from best startable bench / worst benchable starter** — code
  (4989-4990): starter pts − best bench scorer; bench pts − worst starter.
  Matches the tooltip direction/sign. CORRECT.
- **Hardship rollups** — league_week Hardship == Σ team_week Hardship (0
  mismatches across all 101 league-weeks); team_year Hardship == Σ its team_week
  (NOVEL **stevenb123 2022 = 571.328** exact). Confirms the corrected tooltip's
  "aggregate by SUMMING" claim. CORRECT.

### Defects FIXED (see top): Hardship would-be-starter mis-claim; Drafting skill `Final Team` stale column reference.

---

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the col-1 hover comments from the rebuilt workbook (`exports/
LOTG_Stats.xlsx`): **649 player_all_time + 450 picks = 1,099** comments, every
row covered. Cross-checked the generated narrative against `trades.csv`,
`transactions.csv`, and `picks.csv`.

### Full-population automated checks — CLEAN
- **Dangling-reference sweep** across all 1,099 comments (empty `()`, `nan`,
  `None`, `got ;`, trailing `sent ;`, `;;`, `drafted (`): **0 issues**. Every
  `(F. Last)` pick reference resolves; no empty asset lists.
- **Pick comment trade-count reconciliation**: for each of the 450 pick
  comments, the count of `pick traded to` + `Commissioner moved to` lines was
  diffed against the row's `Number of trades`. 448 matched exactly. The 2
  apparent outliers (startup `7.06` Odell Beckham, startup `17.08` Allen Lazard,
  both NumTrades=0 but with `pick traded to` lines) are NOT defects: a startup
  pick's comment renders the drafted PLAYER's FULL career history, which
  correctly SEEDS every pick the player was later drafted at (Beckham also became
  the 2023 4.07 pick, Lazard the 2022 2.08 pick). Verified the secondary picks
  carry the correct counts (2023 4.07 Beckham NumTrades=4 = its 4 hops; 2022 2.08
  Lazard NumTrades=2), and the startup picks correctly read 0 (the startup pick
  itself was never traded). This is exactly the documented multi-draft-seed
  behavior — accurate, not fabricated.

### Manual trace verification with NOVEL examples — all consistent, no inversions
- **Tyjae Spears 2023 3.08** — pick Original LWebs53 → 2 hops (2021-12-04 to
  shmuel256; 2022-12-01 to Oliverwkw) → drafted by Oliverwkw, Number of trades=2.
  Each comment line renders the RECEIVING team's mirror row from trades.csv
  exactly (correct direction). No post-draft moves. Matches picks.csv.
- **Romeo Doubs 2022 3.04** — pick Original shmuel256, 3 pre-draft hops that
  RETURN to shmuel256 (who drafts him), Number of trades=3; then the PLAYER is
  traded twice post-draft (to Oliverwkw 2023-11-01, to BROsenzweig 2024-08-03),
  player_all_time Number of trades=2. Both counts reconcile; directions correct.
- **Jaylen Warren** (undrafted FA) — added by LWebs53 2022-09-14 (dropped Irv
  Smith), dropped by LWebs53 2022-09-21 (added Raheem Mostert), added by plehv79
  2022-10-12, traded to BROsenzweig 2025-09-24. Matches transactions.csv exactly;
  the counterparty annotations ("added X"/"dropped X") are on the correct side.
- **Matt Ryan** (re-drafted veteran) — seeds BOTH the 2020 ESPN startup 19.01
  (Oliverwkw) and the 2021 supplemental veteran 2.05 (BROsenzweig); the comment
  labels them "2020 Draft" and "2021 supplemental veteran draft" RESPECTIVELY —
  the 2020-vs-2021 seam is CORRECTLY distinguished (no startup/vet conflation).
  Events render in causal order (2020 draft → 2020 trade → 2020 drop → 2021 vet
  draft → 2022 drop).
- **Ryan Tannehill** — at the identical timestamp 2021-12-05 the comment renders
  "dropped by LWebs53 (added Taysom Hill)" BEFORE "added by stevenb123 (dropped
  Taysom Hill)" — the documented departures-before-arrivals same-timestamp rule,
  so the chain reads causally (no teleport).
- **Kyler Murray** 2023-05-25 3-team trade — the comment shows the shmuel256-
  specific mirror ("shmuel256 got Alvin Kamara; Mike Williams; Kyler Murray;
  sent Trey Lance; …"), matching the shmuel256 row in trades.csv, NOT the
  Oliverwkw counterparty view. Correct per-team attribution in a multi-team deal.
- **Rachaad White**, **Odell Beckham**, **Allen Lazard** chains all traced
  end-to-end against trades/transactions with correct directions.

**Part D verdict: CLEAN.** No fabrications, no inversions (every trade renders
the receiving team's own asset list), no dangling references, draft seeding (incl.
re-drafted vets and multi-pick players) and same-timestamp ordering correct, all
1,099 comments at full population.

---

## Verification

- `pytest tests/ -q` (via `PYTHONPATH=src:lib python3 -m pytest`): **15 passed**,
  0 failed / 0 skipped — including `test_player_history_continuity` (the
  narrative-continuity guard) and `test_pick_chain_link_integrity`.
- Offline build: **exit 0**, only the 2 expected network-unavailable warnings.
  Post-fix rebuild confirmed the corrected Hardship + Drafting skill tooltips
  render in `exports/formulas.csv` and the `team_week` Hardship header comment.
- Source change: tooltip TEXT only in `src/formulas.py` (Hardship Formula+Notes;
  Drafting skill Formula). No `src/lotg.py` logic change.

## Conclusion

**Parts C + D — 2 real tooltip-drift defects found and FIXED, otherwise CLEAN at
full population.** Part C: the **Hardship** tooltip falsely claimed a
would-be-starter gate that the code never applies (the gate lives only in
Starter-adjusted Hardship; proven by 785 team-weeks where Hardship > SA-Hardship
and AceMatthew 2020 wk1 Hardship=27.24 vs SA=0.0); the **Drafting skill** tooltip
referenced the renamed `picks.Final Team` column (now `picks.Team`). Both are a
NEW drift family, distinct from the exhausted 2020-vs-2021 seam and the Round-10
Taxi/Result family. Every other audited tooltip (All-play win %, Win Variance,
the FAAB auction family, Starter PAR/boom/bust, the manager-skill shrinkage,
start/sit differences, Hardship rollups) matches its code and data with NOVEL
examples. Part D's 1,099 asset-history hover-comments are fully accurate — correct
trade direction, correct per-team multi-team attribution, correct draft seeding
(re-drafted vets + multi-pick players), correct same-timestamp ordering, zero
dangling references, all reconciling to trades/transactions/picks at full scale.
