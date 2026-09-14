# Run 497: the 3-part audit of PR #426 (injury gap-fill, NA, night sweeps)

PR #426 (branch `claude/dataset-validation-injuries-c2srhv`, head `9c24b6d`)
was built by run **497** (`workflow_dispatch` on the branch, 2026-09-14
17:17→17:28 UTC). Baseline is run **496** (main `ccbfb73`, 05:52 UTC the same
day). The branch forks at `01fc67b` (#425), which changed only a test and a note,
so 496 is the true build parent. Both `LOTG_outputs` artifacts were pulled with
`gh run download` and diffed per column, NaN-aware, on canonical keys.

**Verdict: the build change is right, and bigger than the PR said. 275
`Injury?` flags cleared, not 262, and every one of them is a real appearance.
The run finished green while two guards were red. Both were defects in the
guards, not the build, and both are fixed here. Every other diff traces back to
those 275 flips or to the 2026 opener change. Nothing is unexplained.**

## Part 1 — code-based

| | run 496 | run 497 | run 497 exports, guards fixed |
|---|---|---|---|
| conclusion | success | success (guards red under `continue-on-error`) | — |
| pytest | 1 failed, 383 passed | **2 failed**, 404 passed | **406 passed**, and 406 passed on the committed (run-496) exports too |
| new ERROR lines in `build_debug.log` | 0 | **0** | — |
| schema | — | no column added, removed or renamed | — |

Run 497 appended only INFO lines, plus the usual KTC `WARN ... info:`. The union
logged for every season, with no snap-count loader error. `snap_counts_2026.csv`
is published (HTTP 200), so no 404 will show up in the health email:

    snap_appearances season=2020 added=2261 ... 2025 added=3071, 2026 added=162

The two red guards in run 497:

1. `test_no_injury_flag_coincides_with_snaps_played`: 3 offenders, all
   "Michael Carter". **False alarm.** The guard matched players to snap counts
   by name. The 2021 and 2022 NYJ weekly rosters list two players as "Michael
   Carter": the RB (`00-0036924`, `CartMi03`) on shmuel256's roster, and Michael
   Carter II the CB (`CartMi02`). The CB took 53/40/33 snaps. The RB took **0**
   in 2021 wks 12-13 and 2022 wk 13; he was hurt. The build joins on ids and kept
   his flags, which is correct.
2. `test_no_trade_is_filed_against_the_wrong_side_of_a_boundary`: BROsenzweig
   2026 has 12 offseason trades against the guard's 13. **False alarm.** The PR
   moved the build's near edge to the schedule's week-1 opener (Wed 2026-09-09).
   This guard still recounted from `_nfl_kickoff_thursday` (Sept 10), so it filed
   the 2026-09-09 BROsenzweig/JacobRosenzweig trade as offseason.

## Part 2 — results-based (cases from the change spec)

| # | spec item | case | result |
|---|---|---|---|
| 1 | gap-fill | Gabe Davis 2023 wk 11, 67 snaps, 0.00 | `Injury?` True → False |
| 2 | gap-fill | Cole Kmet 2024 wk 9, a **starter**, 66 snaps | flag cleared; Oliverwkw's team_week goes from 9 → 8 injuries, 5 → 4 starter injuries, Hardship 69.64 → 50.78, Luck −0.2265 → −0.1258 |
| 3 | gap-fill | Roman Wilson 2024 (the one newly admitted player) | wk 6 True → False; wks 5 and 7 stay True |
| 4 | gap-fill | Michael Carter RB 2021 wks 12-13 and 2022 wk 13, 0 snaps | stay True (see Part 1) |
| 5 | gap-fill | 16 flips whose names are spelled differently upstream (A.J. Dillon 6 snaps, D.J. Chark 44, Demario Douglas 38, Tre Harris 32, Dont'e Thornton Jr. 23, K.J. Hamler 19, D'Wayne Eskridge 12, Jimmy Horn Jr. 11) | all flipped; snaps > 0 confirmed through the pfr id |
| 6 | gap-fill | direction and scope | 275 True → False, **0** False → True; `Bye?`, `Suspension?`, `Points`, `NFL team`, `Position` unchanged on every row |
| 7 | gap-fill | reconciliation | team_all_time `Weeks of injuries` summed over the 8 teams: 3,826 → 3,551 = **−275** exactly |
| 8 | gap-fill | the fixed guard | passes on run 497's exports; fails with 273 offenders on run 496's exports with the marker planted (no Carter) |
| 9 | NA → suspension | replay `designation()` from main and from the PR over the committed tracker | 247 rows, **1** changed: Josh Jacobs wk 1 `NA Active` None → suspension. Lands when week 1 finalizes (Tue 09-15); 2026 has no player_week rows yet |
| 10 | position pin | tracker row for Travis Hunter | `position` = WR, `gsis_id` = 00-0040718 |
| 11 | resolved gsis | tracker `gsis_id` column | 245 well-formed, 2 blank (Jack Strand, Mike Washington, as documented), **0** placeholders |
| 12 | opener | 2026-09-09 17:23 trade | BROsenzweig 13 → 12 offseason and 0 → 1 in-season; JacobRosenzweig 4 → 3 and 0 → 1; 2020-2025 splits unchanged |
| 13 | formula notes | `formulas.csv` | only `Injury?` and `Suspension?` Formula/Notes changed |

Per season the flips are 2020 **14**, 2021 **22**, 2022 **14**, 2023 **59**, 2024
**80**, 2025 **86**, across 223 team-weeks, 43 team-seasons and 128 players, 13
of them starters. The PR's 262 / 215 / 43 / 121 came from the same name-based
bridge that produced the Carter false alarm. It missed the 16 spellings in case
5 and counted the 3 Carter weeks.

## Part 3 — diff sweep, every change classified

Historical rows (2020-2025) moved only through columns that depend on
`Injury?`. No KTC-valued column moved. The only 2026 cells that moved are the
opener change and one cascade.

| sheet | columns (changed cells) | mechanism | class |
|---|---|---|---|
| player_week | `Injury?` (275) | the fix | intended |
| player_week | 20 `… streak` columns (275 each; rostered-bucket and 10+/20+ streaks up to 481) | a played week that scored 0 is no longer N/A, so it gets a value (0) and breaks the streak | by-design cascade |
| player_week | `Positional scoring percentile` (9,451) | an all-time pooled percentile; 275 scoreless weeks re-enter the pool | by-design cascade |
| player_week | `Change from …` (414 / 703 / 1,946 / 3,569), `Difference in averages … previous 5 games` and `Cuff adjusted difference` (~1,087) | running averages over played weeks now include those weeks | by-design cascade |
| player_week | `consecutive weeks on bench … excluding injury/bye` (27, each +1) | cleared weeks now count as bench weeks | by-design cascade |
| player_week | `Activated Cuff?` (3, 0 → 1: Chuba Hubbard 2021 wk 14, Tank Dell 2024 wk 6, Jake Tonges 2025 wk 17) | the column averages "last 5 played games", and those can now include scoreless weeks. Mechanism not traced line by line | needs-human-judgment (low) |
| team_week | `Number of Injuries` (223), `Number of starter injuries` (58), `Hardship` (331), `Starter-adjusted Hardship` (112), `Most injured?` and its streak, donuts / under-10 (213), `% of starters …`, `Number of cuffs …` | direct and indirect effects of the flips (Hardship also moves in weeks without a flip, through the averages that feed expected points) | intended / by-design |
| team_week | `Luck` (756) | 96 year-weeks move: 83 contain a flip, 15 move through the averages. All 8 teams move per week, the known amplification | by-design cascade |
| team_week | `Loss from hardship?` + both 2-sided flags (shmuel256 / stevenb123 2022 wk 5), `Loss from bye?` / `Win from bye?` (JacobRosenzweig / AceMatthew 2025 wk 12, Hardship 101.29 → 97.21) | the Hardship margin changed; no `Bye?` flag moved | by-design cascade |
| team_year / team_all_time / league_* | the rollups of the above, `Avg yearly luck` (all 8), `Times Most injured?`, `Weeks of injuries` | rollups | by-design cascade |
| team_year | `Drafting skill` (2), `Trading skill` (4), `Add/Drop skill` (1), each ±0.1 | league-relative scores with injury-adjusted inputs | by-design cascade |
| team_year / team_all_time / league_all_time | `Offseason trades` / `Inseason trades` (2026 BROsenzweig and JacobRosenzweig, plus both all-time rollups) | opener change (case 12) | intended, **but not listed in the PR's predicted diff** |
| trades | `Trade addition value` (20), `Trade impact score` (1), `O-Score` (28) | all 21 value rows involve a flipped player; O-Score is a volatile percentile | by-design cascade |
| add_drops / player_additions | `Player addition value`, `Injury adjusted % of starts …`, `Games played on team` (142), `PPG of 5 games before pickup` (76), `O-Score` | every value row names a flipped player (Isaiah Likely's 2026-06-16 pickup reads his flipped 2025 weeks) | by-design cascade |
| rookie / non-rookie picks | `Player addition value`, `Injury adjusted …` (picked player flipped in every row), `Pick-adjusted Difference …` (66 / 68), `O-Score` | pick-adjusted is relative to the slot baseline, so rows without a flipped player move too | by-design cascade |
| formulas | `Injury?`, `Suspension?` | PR text | intended |

## Borderline items

- **The Sept 9 trade struck before kickoff now counts as in-season.** This is
  **by-design**: the comparison works in whole days, which is also how every
  Thursday opener in 2020-2025 was treated. It would only matter if the league
  wants the boundary at kickoff time.
- **Green CI while guards are red** is a settled decision (see the comment on
  `Surface any failing guard`). The run is annotated. Read `pytest.log`, not
  the badge.
- **Merge hazard: the PR rewrites every row of `data/injury_tracker.csv`** to
  add `gsis_id`. `main` had no tracker commit after the fork at audit time, but
  the gameday sweep commits to `main` on game days. If one lands before merge,
  rebase, and check that the swept rows carry `gsis_id` and pinned positions.
  **needs-human-judgment** at merge time.
- **Snap-count revisions will show as UNATTRIBUTED diffs** in the weekly health
  email. The PR already says so; this is the safe direction. **by-design.**
- `Games played on team` is `st["inj_weeks"]` (rostered weeks not flagged
  injured). The name is loose, but that predates this PR.

## Fixed in the follow-up commit

1. The gap-fill guard now keys players on normalized name plus fantasy
   position, and keeps only keys that resolve to a single pfr id (with position
   pins honoured). Carter can no longer collide, and the A.J./Jr. spellings now
   bridge.
2. The season-window guard recounts from the schedule's week-1 opener, falling
   back to the Thursday, and still counts its far edge from the Thursday, the
   same rule as `_season_window`. It now asserts **completed seasons only**. A
   first version that kept 2026 went red on the branch's own committed exports,
   which predate the opener change, so either export vintage would fail it. The
   2026 boundary stays pinned by `test_the_2026_opener_is_the_boundary_the_build_uses`.
   Mutation-tested: planting a +1/−1 offseason/in-season swap on stevenb123
   2025 fails the guard.
3. The wrong figures are corrected where they were committed: `src/lotg.py`
   (two comments), the `load_nflverse_snap_counts` docstring, the
   `test_injury_gap_fill` docstring, and `plan/INQUIRY_PLAYBOOK.md`. That means
   262 → 275, "Gabe Davis 2024 wk11" → 2023 wk 11, and the corrected per-season
   table.

## Round 2 — run 498 (head `08a76f4`) and a second pass over the branch

Run 498 is results pending. A second pass looked at what round 1 had not:

- **The digest the merge will send.** Run 497's digest, against the committed
  ranks snapshot, has 178 board moves and 40 crossings. Run 496's had 81 and 12.
  The extra moves are the injury flips re-valuing settled history: new boards for
  Hardship, Weeks of injuries, Most injured?, donuts and under-10s, and the lede
  already calls the week "a recompute". Every direction and value was checked
  against the diff (e.g. LWebs53 at 458 passing Oliverwkw at 454 on Weeks of
  injuries). One line was **wrong**: "the 2023.0 season passes the 2022.0
  season". `league_year` has no text column, so a row taken from it is a float64
  Series and the label printed the float. It is older than this PR, and it had
  never reached a committed digest, because no league-season board had moved
  since the label was written. This PR is what moves one, so the merge would
  have put it in the league email. **Fixed**: `_board_label` renders the year
  whole, and `migrate_board_label` reads an old baseline's "the YYYY.0 season"
  in the new spelling. The row key keeps its stored spelling
  (`league_year|2023.0`). Verified by rebuilding the digest on run 497's exports
  and the committed snapshot with and without the fix: 40 crossings and 178
  board moves both times, identical board and row keys, and exactly the 3 float
  labels changed. The new check in `test_digest` fails against the unfixed code.
- **Merge timing, needs-human-judgment.** The Tuesday 2026-09-15 13:47 UTC build
  sends week 1's email. If this PR is merged before that build, the ~100
  recompute moves above ride along with the first results week. Merged after,
  they arrive in week 2's.
- **Night-game sweeps, by-design.** `gameday()` shifts UTC back 6 hours, so the
  20:53 anticipatory fire's latest measured landing (00:05 UTC) still resolves
  to the Monday gameday; the margin is 3h52m inside the measured delay band.
  `test_injury_tracker` pins a 03:30 UTC → previous-day case. A fire later than
  06:00 UTC lands on a no-game day and exits, which is a loss, not a
  corruption.
- **Merge state.** GitHub reports the PR mergeable and CLEAN, no checks are
  required, and `main` has had no commit since the fork, so the tracker-CSV
  rewrite has nothing to conflict with yet.
