# Max PF vs Sleeper's own season max points

**Question.** Does the build's `Max PF` agree with Sleeper's season max points
(`rosters[].settings.ppts`), and where it doesn't, why — down to the week?

**Method.** For each of the 40 Sleeper team-seasons (2021-2025), sum the
build's routine (`lineup.compute_optimal_lineup`) over the regular-season weeks
(`week < playoff_week_start`) from the snapshot's `players_points`, and compare
with `ppts + ppts_decimal/100`. Sleeper's total covers the regular season only.
For each gap, re-solve every week of that team-season with alternative position
listings (Sleeper `fantasy_positions`, `inquiry.season_eligibility`, nflverse
weekly roster positions) and look for the weeks whose deltas sum to the gap
exactly. Every alternative was also run across all 40 team-seasons, so a
listing that closes one gap but opens another is caught.

## Result

Against the committed exports before this change, 34 of 40 matched (Travis
Hunter's 2025 gap was already closed by `FANTASY_POSITION_PINS`). The six gaps,
build minus Sleeper:

| Team-season | Gap | Week(s) | Cause | Status |
|---|---|---|---|---|
| stevenb123 2021 | +2.82 | 13 | Taysom Hill listed QB (TE today) | closed: Hill QB in 2021 |
| LWebs53 2021 | +15.10 | 14 | Hill listed QB; LWebs53 started him at SUPER_FLEX | closed: Hill QB in 2021 |
| shmuel256 2021 | -3.10 | 3 (+2.30), 7 (+0.80) | Cordarrelle Patterson WR-eligible (RB today) | closed: Patterson RB/WR in 2021 |
| LWebs53 2023 | -0.10 | 9 | Hill QB-eligible | closed: Hill QB/TE from 2022 |
| LWebs53 2024 | +3.54 | 11 | Hill (41.52 on the bench) counted at TE | Sleeper-side |
| stevenb123 2024 | +1.00 | 6 or 13 | stat correction | Sleeper-side |

All 40 now reconcile (`tests/test_max_pf_pins.py`): 38 match to the cent, and
the other two differ by exactly the amount Sleeper's own frozen total is off.
In both the build's lineup is legal, so copying Sleeper would make Max PF
wrong.

**Listings tested and rejected:**
- Hill QB/TE in 2021: leaves both 2021 gaps open (+2.82, +15.10). Sleeper scored
  him as QB-only that season.
- Patterson RB/WR in 2022: opens Oliverwkw 2022 week 4 (+3.50). RB-only from 2022.
- Hill QB-only for all of 2023 or 2024: opens 2023 weeks 8 and 13 (-9.96, -3.30)
  and 2024 weeks 4, 9 and 10; he also filled strict TE slots in 2024 weeks 4
  and 10.

**LWebs53 2024 (+3.54).** Extra eligibility can only raise Max PF, and the build
is already above Sleeper, so no multi-position listing can close it. The only
single change that does is Hill as QB-only in week 11 alone (Hill's points stay
in the lineup at the superflex instead of TE, exactly -3.54). Excluding Jayden
Daniels that week also gives exactly 3.54, but he started, so nothing explains
it. With Hill listed QB/TE the build's lineup (Hill at TE, 41.52, which
nflverse reproduces under league scoring) is legal, so the lower Sleeper
total is Sleeper's: stale points, or a one-week QB-only label.

**stevenb123 2024 (+1.00).** Sleeper's `fpts` for stevenb123 is also 1.00
below the sum of the weekly matchup points, and Shmuel256's `fpts_against`
1.00 low; every other roster's totals match. That is a 1-point correction to a
stevenb123 starter that landed after Sleeper froze its season totals. The two
met only in weeks 6 and 13. The repo cannot separate them: snapshot history
starts 2026-06, `stats_nfl.json` is empty, and Sleeper's API was unreachable
from the session.

## What the listings move (team_week `Max PF`)

| Season | Week | Team | Before | After |
|---|---|---|---|---|
| 2021 | 3 | shmuel256 | 171.90 | 174.20 |
| 2021 | 7 | shmuel256 | 141.10 | 141.90 |
| 2021 | 13 | stevenb123 | 190.96 | 188.14 |
| 2021 | 14 | LWebs53 | 243.76 | 228.66 |
| 2021 | 17 | LWebs53 | 184.50 | 180.52 |
| 2023 | 9 | LWebs53 | 161.92 | 162.02 |

Classification of what is borderline:

- **needs-human-judgment** — 2021 week 17 is a playoff week. Sleeper's `ppts`
  stops at the regular season, so it cannot be checked; it follows from Hill's
  2021 QB listing applying to the whole season.
- **by-design** — only Max PF and the routines that must reproduce it
  (`replay.check_max_pf`, replay's ceiling model, `draft_capital`) read the
  listings, by passing `week=`. Position-based columns (player_week `Position`,
  percentiles, the hardship/bye counterfactual lineups) keep current labels.
- **by-design** — downstream of `Max PF` (Efficiency, team_year/all-time
  Max PF, Avg max PF, UPST's pregame average, `Max PF in a loss/win`) moves
  with it. The 2026 draft order uses 2025 Max PF, which nothing here touches.
- **defect, Sleeper-side** — stevenb123 2024 +1.00 and LWebs53 2024 +3.54
  are Sleeper's season totals, not the build; the test pins both to the cent.
