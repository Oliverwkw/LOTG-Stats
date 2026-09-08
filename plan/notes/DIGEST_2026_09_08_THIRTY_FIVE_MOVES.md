# The 2026-09-08 digest: 35 moves, and what was behind each

The Tuesday league digest (build run 490, sent 17:57 UTC to 8 recipients) carried
35 leaderboard moves on a week with no games played. This is the accounting, and
the four fixes that came out of it.

Reproduce any of it from the two committed snapshots — no rebuild needed:

```python
prev = json.load(open("<git show de5ea88:data/digest/ranks_snapshot.json>"))
curr = json.load(open("data/digest/ranks_snapshot.json"))
crossings = digest.diff_snapshots(prev, curr)                 # the 12 all-time
events = [digest.EventHighlight(**{k: e[k] for k in
          ("sheet", "label", "column", "end", "rank", "value", "key")})
          for e in curr["event_board"]]
board = digest.diff_events(prev["event_board"], events,
                           prior_row_keys=prev.get("row_keys"))   # the 23 board
```

The baseline is run 488's snapshot (Sep 1 20:18 UTC); run 489 (Sep 3) rebuilt in
between but does not rotate the digest baseline, so the window spans both.

## The causes, by count

| cause | moves |
|---|---:|
| Travis Hunter relabelled WR -> DB by Sleeper | **15** |
| NFLverse revised a raw stat the league scores | 9 |
| A percentile / O-Score pool re-seated | 5 |
| Real league activity (2 trades, 28 add/drops) | 5 |
| A calendar anniversary landing in the window | 1 |

### Travis Hunter, 15 of the 35

Sleeper flipped `position` on pid `12530` from `WR` to `DB` between Sep 1 and
Sep 8 (`exports/snapshot/sleeper_players_nfl.json`). He was the only league
player whose Sleeper position changed that week. NFLverse had already done the
same thing in August, which is why `external.FANTASY_POSITION_PINS` existed — but
that pin is applied on READ of the NFLverse files, and Sleeper is a second,
independent source of the same label that the pin never reached.

`pid_pos` is built straight from Sleeper's dictionary (`src/lotg.py`), holds ONE
label per player, and is applied to all of history. Three separate consequences:

* **team_week positional buckets** (`Number of X started/rostered`, `Points from
  Xs`) bucket on `pid_pos`, so 23.9 WR points and 17 rostered weeks left
  Oliverwkw's **settled 2025 season**. Only three team-weeks moved points
  (2025 wk 1, 2, 5 — the weeks Hunter started, −9.3/−5.2/−9.4) and `PF` was
  unchanged in all three: the points still counted for the team, they just
  stopped belonging to a position. That is what surfaced in the email as
  *"stevenb123 passes Oliverwkw for 6th-highest Points from WRs"* — stevenb123
  never moved (4,822.92 both weeks); Oliverwkw fell 4,836.48 -> 4,812.58.
* **The percentiles** (`Ceiling`/`Floor`/`Consistency` and their Rostered twins)
  group by `pid_pos`, so he became a DB pool of **one** and all six read 100.0
  by construction. Six of the 35 were that.
* **KTC** composes dynasty-daddy's slug as name + position
  (`ktc.derive_player_name_id`), so `travishunterwr` became `travishunterdb`,
  which has no history. All three populated checkpoints on his 2025 1.02 row went
  5,641 / 4,658 / 3,325 -> **0** — the only raw KTC values that changed anywhere
  in the exports. Because `Pick-adjusted Difference in KTC` measures 1.01-1.04
  against a *pooled* slot mean, the hole moved every other top pick with it:
  Marvin Harrison and Ashton Jeanty both by an identical **+564.1**, which is the
  fingerprint of a shared baseline rather than two independent moves.

### The other position source

`player_week.Position` is the AS-OF-WEEK label (NFLverse weekly, Sleeper only as
fallback), and the year/all-time DISTINCT counts read it instead of `pid_pos`.
So the shipped build contradicted itself: Oliverwkw's 2025 read

| | prev | curr |
|---|---|---|
| `Points from WRs` | 771.40 | **747.50** |
| `Number of WR started` | 9 | 9 |
| `Number of WR rostered` | 16 | 16 |

747.50 excludes a player the 9 still counts.
`analysis.position_source_disagreements()` states that as a checkable property;
it found exactly 10 disagreements, all Oliverwkw 2025, all Hunter.

**The build's own guards caught this and nobody was told.** Run 490 finished
green with five failing tests, because the test step is `continue-on-error` and
nothing downstream reported it. Two of the five were describing this exact bug:
`test_position_pins` (pool of one, player split across two pools in one season)
and `test_cross_sheet_reconciliation` (*"team_week Σ positional starter points =
PF"*, *"positional shares sum to 1"* — the points had left the WR bucket and
landed in none).

### McCaffrey and Hill: a trap worth writing down

Two moves looked like they could not be upstream, because both players'
`Points (full season)` and `Points (full career)` were unchanged and a diff of
their NFLverse `fantasy_points_ppr` game logs showed **zero** revised games.

They *are* upstream. `nfl_log_by_sid` does not read `fantasy_points_ppr` — it
recomputes each game with `_league_score(stats, scoring_settings, position)` from
the RAW columns. NFLverse had rewritten `fumble_recovery_yards_own`:

* McCaffrey 2022 wk 1: `1 -> 28`, and three `1 -> 0` corrections
* Hill 2022 wk 14: `1 -> 57`, and one `1 -> 0`

The league scores `fum_ret_yd` at 0.1/yd, so that is +2.4 pts over 72 games for
McCaffrey (+0.033/g; observed `Avg career PPG` 22.44 -> 22.48) and +5.5 over 94
for Hill (+0.059/g; observed 18.96 -> 19.02). Both reconcile within rounding.

**The trap: `fantasy_points_ppr` is not what this build scores.** Diffing it to
decide whether upstream moved will tell you "nothing changed" while every
league-scored number underneath has shifted. Diff the raw columns the league's
`scoring_settings` actually reference.

This also could not be answered from a checkout at the time, because CI never
committed `.cache` — the tracked copy was a hand-written 2026-06-29 vintage while
the shipped exports were built from newer data. The Tuesday build now commits the
cache it read, so next time this is a two-commit diff.

### The rest

* **9 NFLverse revisions.** 151 player-seasons of `Points (full season)` moved
  (2022: 48, 2023: 29, 2024: 39, 2025: 35) — the 65-day cache staleness that
  #418 fixed, flushing through. Several moves were the *rival* re-valuing while
  the mover stood still: Jerome Ford 2023 (unchanged at 12.041) "passed" Joshua
  Dobbs, whose 2023 total went 193.86 -> 193.36; Jameis Winston 2020 (unchanged)
  "passed" Joe Milton.
* **The league's own fantasy scoring never moved.** `Points` and `Avg points`
  changed on ZERO rows in `player_year` and `player_all_time`. Everything above
  is NFL-wide totals, not what Sleeper recorded for the league. Use a numeric
  comparison to establish that — an `.astype(str)` diff reports hundreds of
  phantom changes from float formatting.
* **5 from real activity**: two trades (2026-08-19 Oliverwkw/shmuel256, which
  surfaced late, and 2026-09-04 shmuel256/LWebs53) and 28 add/drops Sep 3-7.
  AceMatthew's 7 drops took his pure drops 40 -> 47 exactly.
* **1 calendar**: Puka Nacua's `KTC 3 years after pickup` went NaN -> 8,379
  because the three-year anniversary of the 2023-09-04 waiver is 2026-09-04,
  inside the window.

## What changed as a result

1. **The pin reaches the Sleeper map.** `FANTASY_POSITION_PINS` is now applied to
   `pid_meta["pos"]` / `pid_pos` by gsis_id, so one registry covers both
   upstreams. Fixes the WR buckets, the pool of one and the KTC slug together.
2. **A KTC slug cannot be zeroed by a relabel.** `player_name_id_candidates`
   falls back through the fantasy positions when the label we hold is not one
   dynasty-daddy ranks. Costs nothing on the normal path (a WR yields one slug).
3. **The two position sources are checkable.**
   `analysis.check_position_sources_agree()`, wired into `analysis.validate()`
   and `tests/test_position_pins.py`. Deliberately a guard, not a fix — choosing
   which source wins moves build output and wants an explicit decision.
4. **The digest stops reporting invisible overtakes.** An overtake whose two
   numbers print identically is dropped (`digest._indistinguishable`). The
   2026-09-08 email LED on a 0.0006 Tanking margin rendered "-0.0". Tie-joins are
   exempt — equal values are the point of that sentence.
5. **The lede counts new data properly.** `Crossing`/`EventCrossing` now carry
   `prev_value`, so an all-time event COUNT that grew reads as live. The email
   said "only 1 reflect new data" on a week with two trades and 28 add/drops;
   the same input now says 3 (4 including the headline), and leads on
   shmuel256's 102nd trade instead of the Tanking artifact.
6. **A failing guard is visible.** The Tuesday build annotates the run and writes
   the failing test names into the job summary. Still non-gating — see below.

## Open, needing a decision

* **Which position source wins** for the year/all-time distinct counts.
  As-of-week is the historically correct label; current-only is what the weekly
  counts have always used. Either way it rewrites settled values, so it is not a
  silent change.
* **Two brittle tests** keep the Tuesday suite red for reasons unrelated to data
  health, which is why the new step reports instead of failing:
  `test_analysis.py::test_current_rosters_can_be_aged_and_the_ranking_survives_the_pool`
  pins "the oldest roster is BROsenzweig" (now shmuel256 — any waiver claim
  falsifies it), and `test_forecast.py::test_an_unsigned_player_cannot_score`
  fails when it finds NO unsigned players, i.e. when there is nothing to test.
  Both are the `assert 0.5 > 0.5` shape #418 already fixed once. Settle them and
  the new step can become a hard failure.
* **`.cache` in git costs ~6 MB/week** (~300 MB/year on a 210 MB repo), plus a
  one-time ~17 MB for the first commit, now that the Tuesday build commits it.

  Measured against live upstream over the 2026-06-29 → 09-08 window. Raw file
  size misleads twice: git stores blobs zlib'd *and* deltas them against the
  previous version.

  | file group | raw | zlib | actually differs? | delta cost/wk |
  |---|---|---|---|---|
  | `weekly_rosters_*` (7) | 14 MB ea | 0.7 MB ea | **no** — 2021 and 2025 byte-identical | ~0 |
  | `stats_player_week_*` (8) | 6-7 MB ea | 1.1 MB ea | yes, all 8 | ~0.5 MB ea |
  | `player_ids` | 6.9 MB | 2.4 MB | yes | ~1 MB |
  | `games`, DP map, injuries | small | small | yes | ~1 MB total |

  **There is no cheap trim that keeps the point of this** — the expensive files
  are the attribution files. Dropping the roster files, which look like the
  problem at 14 MB each, saves approximately nothing. If the size does bite, the
  honest lever is *cadence* (commit monthly, or only when an investigation needs
  it), not file selection.
