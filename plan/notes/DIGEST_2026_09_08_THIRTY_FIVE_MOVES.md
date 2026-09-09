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

## The 3-part audit (#419, run 490 -> run 492)

Run 492 is the post-merge build on `b4ab92d`; it committed its exports as
`cd2d029`, so the audit diffs committed CSVs rather than artifacts.

**Part 2 — nine cases, written from the spec before the build ran. All pass**,
every predicted value exact: Hunter's 2025 weeks all read WR; Oliverwkw's
`Points from WRs` back to 44.0 / 38.9 / 47.2 weekly, 771.40 yearly, 4,836.48
all-time; `check_position_sources_agree()` empty (was 10); no pool of one; the
six percentiles back to 17.0 / 97.6 / 82.3 / 53.7 / 36.0 / 88.6; KTC back to
5,641 / 4,658 / 3,325; MHJ and Jeanty both down by the same 564.1; Nabers 2025
back to 0.9.

**Part 3 — diff sweep.** 8,153 changed cells, all accounted for:

* the pin — `player_week.Position` on exactly 10 rows (Hunter 2025 wks 8-17),
  the Oliverwkw WR columns, the percentile pools re-seating (95 `player_year`
  rostered-consistency rows, as predicted), the pick-adjusted KTC family;
* live churn from the roster moves that same evening — 9 new add/drops, `Tanking`
  (roster age), `Luck`, the link renumbering, `O-Score` and the skills.

**Nothing in a completed season moved that should not have.** No `Points`,
`Avg points`, `PF`, record or win% cell changed anywhere in 2020-2025.

**Part 1 — and the finding.** The four guards that were red before the merge went
green; **four different ones went red**, all Max PF: three in
`test_draft_capital` and `replay.check_max_pf`, on one row —
`2025 week 1 Oliverwkw: Max PF 167.14 != 168.04`.

There are **three** consumers of a fantasy position and the first fix reached
two. `apply_position_pins` covers the NFLverse files; `pin_sleeper_positions`
covers the map the build holds in memory — and the build was right, starting
Hunter for a ceiling of 168.04 (up from 167.14). But `inquiry.players()` reads
the COMMITTED snapshot JSON, which deliberately stays a faithful copy of what
Sleeper published and still said DB, so every model built on that layer left him
out. Sleeper carries `gsis_id: null` for him, so the read layer now bridges
through the committed DynastyProcess map, exactly as the build's enrichment does.

The lesson generalises past this player: **a pin has to reach every reader, and
"the snapshot is the record of what upstream said" and "the code should act on
the corrected label" are both right** — which is why the correction belongs at
each read, never in the stored file.

## The cascade rule (added after the run-492 digest)

Run 492's digest — corrected build against the run-490 baseline — carried 39
moves, **23 of them on the pick sheets, and not one of those 23 had its own value
change.** They were the fix unwinding. Restoring Hunter's KTC took his 2025 pick
1.02 off five boards at once, each of which he had held 1st place on:

| board | he held | now |
|---|---|---|
| lowest `KTC on draft day` | 0.0 | 5,641 → off |
| lowest `KTC at end of rookie year` | 0.0 | 4,658 → off |
| lowest `KTC 1 year after draft day` | 0.0 | 3,325 → off |
| lowest `Pick-adj Diff in KTC on draft day` | −6,034.4 | off |
| lowest `Pick-adj Diff in KTC at end of rookie yr` | −6,244.9 | off |

Five vacated first places, and everyone behind each stepped up one — which is
why they all read "3rd-lowest / 4th-lowest / 5th-lowest". On the HIGH end the
same thing via the pooled 1.01–1.04 baseline: Marvin Harrison's inflated 1,877.8
fell to 1,313.7, dropping him 1st → 4th, so Lance, Fields and Mac Jones each
gained a place without moving.

`digest._nobody_moved` is the rule: **a crossing survives only if at least one of
the entities it NAMES actually moved.** A mover that stood still, passing rows
that also stood still, is a cascade and is dropped.

Two subtleties, both learned from the data:

* **The rival counts.** "A.T. Perry passes Travis Hunter" has an unchanged mover
  and is still news — Hunter is the one who moved, and dropping the line hides
  the only thing that happened. Only when *neither* side moved is it noise. (On
  a ranking over values an overtake always implies somebody moved, so the pure
  cascade in the all-time sections is the TIE-JOIN, where two unchanged entities
  are promoted a rank because a third fell past them.)
* **Off the board is ambiguous**, and the prior board's worst place settles it. A
  row absent last week and present now either climbed past that cutoff or was
  carried in when the board shortened. Strictly worse than the cutoff = carried
  in = dropped; at or better = it climbed = kept. The boundary matters: reading
  it the other way lost `2025 week 4 joins a tie for 5th-highest Number of WR
  rostered (100)`, whose count really did go 99 → 100.

Effect on that digest: **39 → 16.** Six lines name Hunter, five are his knock-on
effects (the WR points, Nabers' percentile, the week-4 count, and the two picks
whose values moved with the pooled baseline), five are genuine league activity
(the Cyrus Allen adds, FAAB, a skill, an O-Score). **Zero pure-cascade lines
remain, down from 23.**

## Open, needing a decision

* **Next Tuesday's digest will report the fix as news.** Run 492 was a manual
  dispatch, and the snapshot rotation is gated to the Tuesday cron, so the
  committed baseline is still run 490's — it records Travis Hunter's Ceiling
  percentile as **100.0** where the corrected exports say **17.0**. On 2026-09-15
  the digest diffs corrected-against-buggy and surfaces the ~15 Hunter reversals
  as fresh leaderboard moves in the league's email.

  Re-baselining now (regenerating `data/digest/ranks_snapshot.json` from the
  committed exports) removes them — verified reproducible, a local run over the
  committed exports emits run 492's lede word for word and the same 39 moves.
  But it would ALSO swallow this week's ~24 genuine moves (the Cyrus Allen FAAB
  pickup and the rest), which the league should hear about. Left alone
  deliberately: the lede now classifies the reversals correctly as "a recompute,
  not a results week", so the noise is labelled rather than hidden, and no real
  news is lost. Flip it only if the phantom moves are judged worse than the
  silence.

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
