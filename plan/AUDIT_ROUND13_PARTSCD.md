# Phase 13 Round 13 — Parts C+D (header-comment / tooltip accuracy + asset-history narrative accuracy)

Fresh full-population audit repeating the Parts C/D methodology of
`plan/AUDIT_PHASE13_ROUND12_PARTSCD.md`, run against the fresh offline build on
branch `claude/agent-part-audits-1yy87u` (HEAD `97e5dcd` — "Refresh committed
exports from deterministic offline rebuild (Round 13 audit baseline)"). Agent 2
of 5 in Round 13 (sibling Parts A/B landed CLEAN — `plan/AUDIT_ROUND13_PARTSAB.md`).

**Build under audit:** the committed `exports/*.csv` + `exports/LOTG_Stats.xlsx`
from the Round-13 baseline rebuild. NOT rebuilt or modified by this agent
(`git status` clean throughout; only this findings file is new). Full
population: 808 team-weeks, 514 pick rows, 649 player_all_time rows, **1,163
asset-history hover comments** (649 player_all_time + 514 picks), the 451-row
`formulas.csv` tooltip catalog.

All examples below are NOVEL — different stats/players/picks/teams than every
prior round. This round targeted the explicitly-named stat families (Efficiency,
Margin, All-play Win%, percentile/rate, "if starter"/"if bench" splits,
change-from-previous families, FAAB-difference, retention-rate gates) plus novel
surfaces not scrutinized recently: the **percentile / boom-bust tier** family,
**Playoff-minus-regular clutch** metrics, **Brosenzweig/Sisenzweig**,
**Net points / Net KTC** internal consistency, and the **single-flag-per-week
award** family. Part D new chains: **A.J. Brown 2020 5.06**, **Jermaine Burton
2024 3.08** (8-hop chain through both commissioner-injected legs), the **Cook
trade 10-pick commissioner bundle**, and the novel **2025-07-30 11:38:33 3-team
trade** (LWebs53 / plehv79 / stevenb123).

**Result: no CONFIRMED DEFECTS in Part C tooltip accuracy or Part D narrative
accuracy.** Every audited tooltip's claimed formula/behavior matches the exported
data at full population, and all 1,163 asset-history hover-comments are accurate
(0 fabrications, 0 inversions, 0 dangling references). THREE anomalies are
flagged over-inclusively below — all classify as by-design / needs-human-judgment,
and TWO of them (empty KTC, un-ingested 2026 season) are primarily Part A/B
(population/freshness) matters cross-referenced here so they are not silently
dropped.

---

## Part C — Header-comment / tooltip accuracy sweep (formula text vs the exported data)

Full population on each numeric claim (every team-week / team-year / player-week /
player-year row, not samples). Every check below was recomputed from inputs.

### Stats verified CORRECT (tooltip text matches the data) — full population

- **Efficiency** = PF / Max PF — recomputed all 808 team-weeks: **0 mismatches**
  (max abs diff 5e-5 = 4-dp rounding), **0 rows > 1** (tooltip "≤ 1" holds,
  including Semifinal weeks where PF carries the +5 homefield bonus — Max PF
  carries it too, so the ratio still ≤ 1).
- **Margin** = PF − Points against — **0/808 mismatches**; sign consistent with
  Win? (0 wins with Margin<0, 0 losses with Margin>0, 0 ties). CORRECT.
- **All-play win %** — recomputed the "each week, score vs EVERY other team; wins
  = teams with strictly lower PF that week / other teams that week" formula per
  (Team,Year): **0 mismatches across all 48 team-seasons** (NOVEL AceMatthew 2023
  = 0.5546 recomputed exactly).
- **All-play win % minus Win %** = All-play − actual Win % — **0/48 mismatches**.
- **Consistency / Floor / Ceiling percentile** (player_all_time) — position-
  adjusted percentile (mode-derived position from player_week), INVERTED for
  Consistency (lowest volatility = 100), highest floor/ceiling = 100 as stated:
  **max abs diff < 0.05** across 338–413 ranked players, ranking direction
  confirmed. CORRECT.
- **Starter boom / upper-quartile / middle-50% / lower-quartile / bust %** — the
  5 positional tier shares **sum to ~100% for all 1,051 rows** (99.8–100.1, 0
  rows off by > 0.5), matching the "5-tier positional split sums to ~100%"
  tooltip.
- **FAAB difference over second place / FAAB premium % / Number of bids / Total
  FAAB bid** — internal consistency (premium% = diff/Faab×100: 0/87 mismatches;
  uncontested waivers blank difference: 297/297; Total ≥ winning: 0 violations)
  AND traced to RAW Sleeper data for NOVEL **Jacory Croskey-Merritt 2025 wk1**:
  losing bids 50/47/75/115/61/54 + winning 120 → Number of bids **7** ✓, Total
  FAAB **522** ✓, difference over 2nd **120−115 = 5** ✓, premium **4.17%** ✓.
  Every clause of all four tooltips matches the raw ledger.
- **3-year roster retention rate** = |week-1 roster_Y ∩ week-1 roster_Y+3| /
  |roster_Y| — recomputed from player_week week-1 rosters: **0 mismatches across
  all 24 measurable team-years**, and correctly **blank for 2023+** (Y+3 not yet
  played), matching "Blank until Y+3 season is played (2020→2023, 2021→2024,
  2022→2025 so far)". Real 0s (LWebs53 2021/2022) are genuine, not blanks.
- **Difference from best startable bench (if starter) / worst benchable starter
  (if bench)** — the two columns are **mutually exclusive** (0 starter-col values
  on bench rows, 0 bench-col values on starter rows). Starter values recomputed
  for all 1,360 2024 starters = his points − best bench: **0 mismatches**. (See
  Anomaly #3 for a wording note on "who could have started instead".)
- **Change from previous 5 weeks avg / Change from career average to that point /
  Change from overall career average** (player_week) — recomputed on NOVEL **Sam
  LaPorta** (40 played) and **Kyren Williams** (51 played): **0 mismatches** on
  all three, with non-played (bye/injury/susp) weeks correctly excluded from both
  baseline and output.
- **Net points** = Points Added − Points Lost — **0/1,510 mismatches**. (Net KTC
  families are structurally consistent but 100% blank — see Anomaly #1.)
- **Brosenzweig** (LOST while exactly one team scored strictly higher) and
  **Sisenzweig** (WON while exactly one team scored strictly lower) — recomputed
  across all team-weeks: **0 mismatches** (16 Brosenzweig, 21 Sisenzweig flagged).
- **One-man army? / Most bench points? / Highest score? / Lowest score?** —
  **exactly one winner per league-week (101/101)** as the "one winner per
  league-week" tooltips claim. **Most injured?** correctly allows shared ties
  (1–4 winners/week) matching its "Ties shared / needs ≥1 injury" note.
- **Playoff PF minus regular-season PF** (winners-bracket Semifinal/Final/3rd
  Place mean PF − regular-season mean PF) — **0/7 mismatches** once all "Week N"
  rows (incl. Week 15) count as regular season; correctly blank for the team that
  never reached the winners' bracket.
- **Playoff win % minus regular-season win %** — **0/7 mismatches**, same gating.

Every audited tooltip matched the exported data with NOVEL examples. No wording
implied a different computation than the data shows (the one borderline phrasing
is Anomaly #3, which carries no numeric defect).

**Win Variance** is on the prior-rounds "exhausted" list; confirmed populated
(48 non-null) and deferred to those rounds rather than re-derived, per the
novel-surface directive.

---

## Part D — Asset-history hover-comment narrative accuracy (full population)

Extracted the col-1 hover comment from every row of `exports/LOTG_Stats.xlsx` via
openpyxl: **649 player_all_time + 514 picks = 1,163** comments, every row covered
(0 missing). Cross-checked against `transactions.csv`, `trades.csv`, `picks.csv`,
and `data/commissioner_pick_trades.csv`.

### Full-population automated checks — CLEAN
- **Dangling / malformed-reference sweep** across all 1,163 comments (empty `()`,
  `nan`/`None`/`NaN`, `undefined`, `got ;`, `sent ;`, `;;`, `drafted ()`,
  numbered `#N`/`T#N`/`PH#N` link refs): **0 hits**.
- **Fabrication sweep**: every dated `traded to` line (matched on (date,
  receiving-team) against trades.csv), every `added by` and `dropped by` line
  (matched on (date, team, player) against transactions.csv) across all
  player_all_time comments: **0 fabricated trade lines, 0 fabricated adds, 0
  fabricated drops.**
- **Chronological-ordering sweep**: every explicit `YYYY-MM-DD:` dated line in all
  1,163 comments — **0 chronological inversions**.
- **Pick-comment trade-count reconciliation** (pre-draft `pick traded to` lines vs
  the row's `Number of trades`): aligned by pick IDENTITY, **514/514 consistent**.
  A naive positional alignment flagged exactly 2 rows (2023 4.07 Odell Beckham,
  2022 2.08 Allen Lazard) — these are the DOCUMENTED startup-seed key-collision
  from Round 12 (a startup pick's comment seeds the drafted player's full career
  onto later same-slot picks); both flagged picks carry the CORRECT
  `Number of trades` (4 and 2) in picks.csv once matched by identity. Not a defect.

### Manual trace verification with NOVEL examples — all consistent
- **A.J. Brown 2020 5.06** — originally plehv79 (20-FAAB draft-day buy) → drafted
  by plehv79 → **2025-07-30 11:38:33 3-team trade** (received by LWebs53) →
  **2025-08-01 traded to BROsenzweig**. Each comment leg renders the RECEIVING
  team's OWN asset list, matching trades.csv byte-for-byte (LWebs53 got Jack Bech;
  Luther Burden; Dallas Goedert; A.J. Brown; 2027 3(plehv79); $25 FAAB / sent 2027
  1(stevenb123); 2028 1(stevenb123); 2027 2(BROsenzweig); BROsenzweig got A.J.
  Brown; Rhamondre Stevenson / sent 2026 3(plehv79); 2026 1(LWebs53)).
  player_all_time counts reconcile: **Number of trades = 2**, drops = 0,
  transactions = 0, Last team = BROsenzweig, Top team = plehv79. Correct
  direction; correct per-team multi-team attribution (novel 3-team deal).
- **Jermaine Burton 2024 3.08** — an 8-hop chain, all consistent and monotonic:
  2020-11-29 LWebs53→AceMatthew (Cook trade, commissioner-injected) → 2021-12-04
  AceMatthew→LWebs53 (returned) → 2022-03-09 LWebs53→stevenb123 (Mostert swap,
  commissioner-injected) → 2022-06-06 →shmuel256 → 2024-05-03 →Oliverwkw → drafted
  by Oliverwkw → 2024-12-09 →stevenb123 → 2025-08-11 →plehv79 → 2025-09-02
  dropped. The two commissioner-ledger rows that both read "LWebs53's 2024 3rd,
  from LWebs53" are NOT a conflict — the pick left LWebs53 in 2020 and RETURNED in
  2021-12-04 before the 2022 hop. Narrative accurate end-to-end.
- **Cook trade 10-pick commissioner bundle** (2020-11-29 23:57:04) — the
  commissioner overlay (`commissioner_pick_trades.csv`: LWebs53→AceMatthew, 2021
  R1/R2/R4, 2022 R1/R3, 2023 R1, 2024 R1/R3, 2025 R1/R3) is injected seamlessly
  into the recorded Dalvin Cook / Alexander Mattison trade and renders as a single
  deal listing all 10 picks at LWebs53's actual finishing slots (1.06/2.06/4.06;
  1.07/3.07; 1.08; 1.08/3.08; 1.03/3.03). Each individual pick's own comment shows
  the matching "2020-11-29: pick traded to AceMatthew (...)" → draft line. Fully
  reconciles to the ledger; no special "commissioner" wording (by design — the
  overlay is meant to look native).

**Part D verdict: no defects.** Correct trade direction, correct per-team
multi-team attribution (verified on a novel 3-team deal), correct commissioner-
overlay injection (verified on the 10-pick Cook bundle and the two-legged Burton
chain), correct chronology, zero fabrications, zero dangling references — all
1,163 comments at full population.

---

## Anomalies flagged (over-inclusive)

### (a) CONFIRMED DEFECTS
**None** in Part C tooltip accuracy or Part D narrative accuracy.

### (b) LIKELY BY-DESIGN / ACCEPTABLE WORDING
- **Anomaly #3 — "Difference from best startable bench (if starter)" wording.**
  Tooltip says "the best bench player **who could have started instead**"
  (implying positional eligibility). In all 1,360 checked 2024 starter rows the
  numeric value equals `starter points − overall-max-bench points` (positional
  filtering never bit numerically — the top bench scorer was always startable in
  some slot in this superflex league). In 10 tie cases (two bench players at an
  identical top score, e.g. shmuel256 2024 wk6: Justin Fields QB 22.70 vs Tyrone
  Tracy RB 22.70) the value is identical either way and the `Reference player
  name` names the FLEX-eligible bench player (Tracy), consistent with the
  eligibility wording. **No numeric defect; the reference name is always a valid
  best-startable-bench player.** Acceptable.

### (c) NEEDS-HUMAN-JUDGMENT
- **Anomaly #1 — KTC columns are 100% empty build-wide (cross-cutting; primarily
  Part A/B).** Every KTC-derived column across `transactions`, `trades`, and
  `picks` has **0 non-null values** (KTC value of added/dropped at deal time / end
  of season / 1yr / 2yr; Net KTC at all horizons; Pick value received; picks'
  KTC-on-draft-day family). Yet the committed offline source
  `data/ktc_backfill/*.json` **does** hold real superflex values (556/563 files
  non-zero, max 9999). Root cause: `lotg_support.ktc.build_index` performs a live
  dynasty-daddy network fetch that fails offline (403 Forbidden through the
  proxy); the outer `try/except` at `src/lotg.py:9002` swallows it and leaves
  `_ktc_idx = None`, so the offline-available backfill is **never reached/merged**.
  Downstream effects: **O-Score is blank on all 504 trades and all 514 picks but
  populated on 439 transactions** (the transactions path tolerates missing KTC,
  the trades/picks paths blank out entirely — a scope inconsistency vs the O-Score
  tooltip which claims all three sheets); **Trade impact score is populated
  (504/504) but its KTC-value-weighting term is silently 0-filled** (the code
  comment at 10695-10701 warns this makes the score non-deterministic across
  builds). *Classification:* the empty KTC is plausibly an accepted offline-build
  limitation (KTC is network-sourced), BUT the fact that the committed backfill is
  bypassed offline — leaving dozens of tooltip'd columns 100% empty and O-Score
  inconsistent across sheets — warrants a human decision on whether offline builds
  should fall back to the backfill. This belongs to Part A/B (Agent 1 landed CLEAN
  without noting it); flagged here so it is not silently dropped.
- **Anomaly #2 — 2026 season present in the snapshot but not ingested (freshness;
  primarily Part A/B).** `exports/snapshot/season_2026/weeks/week_01/` contains 57
  transactions plus real `trade`-type entries dated 2026-05-03, 2026-07-10, and
  2026-07-12, but `transactions.csv` and `trades.csv` both **end in 2025**
  (0 rows dated 2026), and 2026 picks render as `1.??`/`2.??` Unknown (draft not
  processed). Consequently **6 rows in `commissioner_pick_trades.csv` with 2026
  timestamps are unrealized** (the 2026 2.09 hop Oliver→Luke→Sam; the 2029 3rd
  away-and-back; the 2030 4th; the 5.01/5.02 FAAB-buy sentinels — including the
  ledger-documented **first-ever 5-team trade, 2026-07-10 21:22:18**). The build's
  unmatched-commissioner-row warning (`src/lotg.py:6121-6128`) routes through the
  debug-gated `_log`, so in a normal (non-debug) build these are **silent**. No
  internal inconsistency results (pick trade-counts and lineages agree with the
  ingested data, which simply omits all 2026 activity). *Classification:* plausibly
  an intentional "process only completed seasons" cutoff (today is 2026-07-14,
  2026 hasn't started), but the committed ledger explicitly documents 2026
  off-platform hops that go unrealized — a human should confirm whether the cutoff
  is intended and whether the unmatched-commish warning should be surfaced
  non-silently. Part A/B scope; flagged here for completeness.

---

## Verification
- `PYTHONPATH=src:lib python3 -m pytest tests/ -q`: **46 passed** in ~69s, 0
  failed / 0 skipped — including the narrative-continuity / pick-chain-integrity /
  cross-sheet-reconciliation guards.
- No source or export changes (`git status` clean except this findings file).
- Part C recomputations and Part D sweeps all run against the FRESH committed
  exports (not a rebuild).

## Conclusion
**Parts C + D carry ZERO confirmed defects at full population.** Part C
cross-checked a large NOVEL tooltip set (Efficiency, Margin, All-play Win% and its
minus-Win% delta, the percentile + 5-tier boom/bust family, the FAAB-difference
family verified against RAW Sleeper bids, 3-year retention with its Y+3 gate, the
if-starter/if-bench split, all three change-from families, Net points,
Brosenzweig/Sisenzweig, the single-flag-per-week award family, and the
Playoff-minus-regular clutch metrics) against the exported data — every tooltip's
claimed formula/behavior matches with 0 mismatch. Part D's 1,163 asset-history
hover-comments are fully accurate (correct trade direction, correct per-team
multi-team attribution on a novel 3-team deal, correct commissioner-overlay
injection on the 10-pick Cook bundle and the two-legged Burton chain, correct
chronology, zero fabrications/dangling refs). Three anomalies were flagged
over-inclusively: one is acceptable tooltip wording (best-startable-bench), and
two (100%-empty KTC bypassing the committed backfill offline; un-ingested 2026
season with 6 unrealized commissioner ledger rows) are primarily Part A/B
population/freshness matters cross-referenced here for human review. No Part C/D
source change is required.
