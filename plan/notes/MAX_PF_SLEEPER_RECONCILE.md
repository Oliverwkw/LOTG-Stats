# Max PF vs Sleeper's own season max points

**Question.** Does the build's `Max PF` agree with Sleeper's season max points
(`rosters[].settings.ppts`), and where it doesn't, why — down to the week?

**Method.** For each of the 40 Sleeper team-seasons (2021-2025), sum the
build's routine (`lineup.compute_optimal_lineup`) over the regular-season weeks
(`week < playoff_week_start`) from the snapshot's `players_points`, and compare
with `ppts + ppts_decimal/100`. Sleeper's total covers the regular season only.
For each gap, re-solve every week of that team-season with alternative position
labels (Sleeper `fantasy_positions`, `inquiry.season_eligibility`, nflverse
weekly roster positions) and look for the weeks whose deltas sum to the gap
exactly.

## Result

Against the committed exports before this change, 34 of 40 matched (Travis
Hunter's 2025 gap was already closed by `FANTASY_POSITION_PINS`). The six gaps,
build minus Sleeper:

| Team-season | Gap | Week(s) | Cause | Evidence |
|---|---|---|---|---|
| stevenb123 2021 | +2.82 | 13 | Taysom Hill scored as QB (TE today) | QB label gives exactly -2.82; nflverse 2021 has him QB; LWebs53 started him at SUPER_FLEX in week 14 |
| LWebs53 2021 | +15.10 | 14 | Hill as QB | exactly -15.10 |
| shmuel256 2021 | -3.10 | 3 (+2.30), 7 (+0.80) | Cordarrelle Patterson WR (RB today) | he filled a strict WR slot in 2021 (`season_eligibility`) |
| LWebs53 2023 | -0.10 | 9 | Hill QB-eligible that week | exactly +0.10; a QB label in weeks 8/13 would open -9.96 / -3.30, so week 9 only (**inferred**; QB/TE fits equally) |
| LWebs53 2024 | +3.54 | 11 | Hill as QB | exactly -3.54; strict TE slot in weeks 4 and 10, so a one-week flip (**inferred**) |
| stevenb123 2024 | +1.00 | 6 or 13 | stat correction, not position | Sleeper's `fpts` is 1.00 below the sum of matchup points and Shmuel256's `fpts_against` 1.00 low; the two met only in weeks 6 and 13 |

With the four pins in `position_pins.MAX_PF_POSITION_PINS`, 39 of 40 match to
the cent (`tests/test_max_pf_pins.py`). Excluding Jayden Daniels in 2024 week
11 also yields exactly 3.54, but he started that week, so nothing would remove
him; the Hill reading is preferred because Hill is the confirmed cause in three
other gaps.

## What the pins move (team_week `Max PF`)

| Season | Week | Team | Before | After |
|---|---|---|---|---|
| 2021 | 3 | shmuel256 | 171.90 | 174.20 |
| 2021 | 7 | shmuel256 | 141.10 | 141.90 |
| 2021 | 13 | stevenb123 | 190.96 | 188.14 |
| 2021 | 14 | LWebs53 | 243.76 | 228.66 |
| 2021 | 16 | stevenb123 | 191.36 | 190.96 |
| 2021 | 17 | LWebs53 | 184.50 | 180.52 |
| 2023 | 9 | LWebs53 | 161.92 | 162.02 |
| 2024 | 11 | LWebs53 | 175.98 | 172.44 |

Classification of what is borderline:

- **needs-human-judgment** — the two 2021 playoff weeks (16, 17). Sleeper's
  `ppts` stops at the regular season, so they cannot be checked; they follow
  from treating Hill as QB and Patterson as WR for the whole 2021 season, which
  is what the regular-season evidence supports.
- **needs-human-judgment** — 2023 week 9 and 2024 week 11 are single-week
  labels inferred from exact gap matches, not read from a dated Sleeper record
  (none survives: snapshot history starts 2026-06, `stats_nfl.json` is empty,
  and Sleeper's API was unreachable from the session).
- **by-design** — only Max PF and the routines that must reproduce it
  (`replay.check_max_pf`, replay's ceiling model, `draft_capital`) read the
  pins, by passing `week=`. Position-based columns (player_week `Position`,
  percentiles, the hardship/bye counterfactual lineups) keep current labels.
- **by-design** — downstream of `Max PF` (Efficiency, team_year/all-time
  Max PF, Avg max PF, UPST's pregame average, `Max PF in a loss/win`) moves
  with it. The 2026 draft order uses 2025 Max PF, which no pin touches.
- **defect, unfixable here** — stevenb123 2024 +1.00 stays; it is Sleeper's
  stale season total, not the build.
