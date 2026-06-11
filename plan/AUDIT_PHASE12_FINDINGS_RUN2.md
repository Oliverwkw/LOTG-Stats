# Phase 12 — 9-part audit, RUN 2 (content focus)

Run against the #282 CI build (`/tmp/a282`, SHA `8c3eaa37`). **All 9 parts PASS
on data correctness** — zero reconciliation, link, chain, or value-accuracy
failures. 8 minor findings (3 doc, 3 content-rendering, 2 cosmetic/harness),
fixed in the follow-up PR. The known Phase-13 startup-origin gap remains open
by design.

## Part-by-part verdicts

| Part | Verdict | Detail |
|---|---|---|
| 1. Cross-sheet reconciliation | **PASS** (36 rollup checks) | Points/tx/awards/hardship weekly→year→all-time all Δ=0; Record = Σ Win? (incl. playoffs); league = Σ team; team PF = Σ starters (modulo the intentional +5 W16 homefield); distinct counts verified. |
| 2. Stat-family hand-checks | **PASS** (33 cases, ≥12 edge) | PPG/Adjusted/volatility/floor/ceiling/boom%, PAR replacement math, all-play win %, Efficiency, FAAB sums, shrinkage skill, KTC = cache to the dollar, 1.01 pooled-mean rule, O-Score bounds, depth-tax mirror negation, tenure days, terminal streak encoding incl. skip-missed-weeks. |
| 3. N/A vs 0 sweep | **PASS** | 0 blank/mixed numeric cells; prior Age-0/PPG-0 fixes hold; all high-N/A columns semantically justified. |
| 4. Edge cases | **PASS** (55 cases) | Multi-team players, vet exclusions, synthetic picks, commish moves, 2026 gates, never-rostered picks, byes/suspensions, opponent symmetry, uniqueness of awards. Findings F4/F5/F6 below. |
| 5. Duplicate columns | **PASS** | No true duplicates. Same-NFL-team count family is low-information by design (≈ always 1); year-grain equalities are coincidence (weekly grain differs). Finding F7. |
| 6. Data-quality gaps | **PASS** | 0 mapping gaps (no player with rostered points but no NFLverse career); 0 missing players; sanity 0/0; builds deterministic. Finding F8 (stale curated cases). |
| 7. Odd-result hunt | **PASS** | Extremes match reality: Nacua waiver 98.5 / ARSB 99 / Chase 97 tops; Young/Burks/Moore/Brooks busts at the bottom; KTC trajectories (Burks 4217→601 collapse, Chase →9053 peak, Young dip-recover) correct; Kyren/Love/Rodgers swings correct. Note: small-sample PAR/gm leaderboard (n=1 starts). |
| 8. Asset story | **PASS** | 2,962 transaction link refs: 0 out-of-range, 0 wrong-subject; trades per-asset lists align 1:1; 0 broken chain reciprocity (60-player sample); 297/297 pick comments; pick comment ≡ drafted player comment. 595/605 player comments — the 10 missing are zero-event startup cornerstones (Mahomes/Allen/Hurts…), same Phase-13 origin gap as the 71 blank first-trade prev-links. |
| 9. Cell-by-cell sweep | **PASS** | 55,224 xlsx hyperlinks, 0 broken. All flagged negatives are legitimate (negative fantasy games; Win Variance is a signed rank-delta by design). No encoding/type/malformed-value issues. |

## Findings (all minor; fixed in follow-up PR)

1. **F1 (doc):** Formulas `Win?` said "1/0/0.5" — data renders `True`/`False` (no tie has ever occurred).
2. **F2 (doc):** Formulas `Record` / `Win %` said "regular season" — they include playoff + toilet games (17 games/season).
3. **F3 (doc):** `PF` doc didn't mention the intentional **+5 Week-16 homefield advantage** for the two higher seeds (Semifinal). It trips naive PF=Σstarters reconciliation; documented now.
4. **F4 (content):** 14 player-weeks of **no-NFL-team players** (retired/unsigned: Brady ×2, Brees, OBJ-2022 ×7, Doctson ×2, D.Thomas ×2) were classified `Injury?=True`, inflating team injury counts — and **decided one award**: stevenb123 2025w16 "Most injured?" (8 incl. Brady vs rightful 7). Fix: classify no-NFL-team weeks as **Bye** (no game exists), keeping them excluded from averages/hardship while removing the phantom injuries.
5. **F5 (content):** 2021 Week-1 "from previous week" columns (`Increase in points`, `Roster/Starter turnover`, `Difference in pregame avg max PF`) rendered `0.0` — no prior week exists; should be N/A.
6. **F6 (cosmetic):** `Taxi-eligible` rendered `1.0/0.0`; every other flag is `True/False`.
7. **F7 (cosmetic):** Same-family columns render inconsistent number formats (`1` vs `1.0`, e.g. Most-QBs vs Most-TE from same NFL team on team_week).
8. **F8 (harness):** The perpetual `WARN known-player validation mismatches: 2` is **stale curated cases**, not data: Addison 2024w9 "suspension" never happened (he played, 16.1 pts; his real 2025w1–3 suspension IS correctly flagged), and Lazard 2025w1 is correctly absent (dropped 2024-11-10, never re-rostered).

## Verified-intentional (no action)
- +5 Week-16 homefield advantage (user-confirmed rule).
- One-sided trades (16 rows) — genuine one-directional Sleeper deals (gifts/comp legs, e.g. Ray Davis; Kupp trade + trade-back 2 min later).
- 10-starter lineup from 2024 (league setting change); 3-starter 2022 Toilet-Semis week (manager checked out) → the all-time-worst 45.36 PF.
- Meme pickups of retired players are real transactions (kept; only their *injury classification* changes per F4).
- `Win Variance` = signed rank-delta (name is historical; tooltip explains it).

## Still-open (by design, Phase 13)
- Startup-origin gap: 71 initial-roster vets' histories begin mid-stream + 10 zero-event cornerstones have no comment + 71 first-trade `previous` endpoints blank — all resolve with the ESPN-2020 / off-platform backfill (`plan/notes/initial_roster_vets_2021.txt`).
