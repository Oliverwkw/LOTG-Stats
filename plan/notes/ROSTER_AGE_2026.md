# All eight teams by average roster age — current (2026) rosters

**Question.** "Give all 8 teams by avg age (current rosters)."

**Short answer.** shmuel256 is the league's oldest roster at **27.98**, plehv79
the youngest at **24.41** — a 3.6-year spread across a top four (shmuel256,
BROsenzweig, AceMatthew, stevenb123) that is all above 26 and a bottom four
(JacobRosenzweig, Oliverwkw, LWebs53, plehv79) that is all below 25.4. There is
a real gap between the two halves: 26.37 to 25.31 is the widest step anywhere in
the table.

---

## The ranking

Current rosters as of the committed snapshot (captured 2026-08-06), aged at
2026-08-07. `python scripts/inquire.py age`.

| # | Team | Players | Avg age | Median | Youngest | Oldest |
|---|---|---|---|---|---|---|
| 1 | shmuel256 | 34 | **27.98** | 27.16 | 21.89 (Dylan Sampson) | 38.50 (Matthew Stafford) |
| 2 | BROsenzweig | 29 | **27.68** | 27.16 | 22.95 (DJ Giddens) | 42.68 (Aaron Rodgers) |
| 3 | AceMatthew | 35 | **27.32** | 27.21 | 21.87 (KC Concepcion) | 34.28 (Keenan Allen) |
| 4 | stevenb123 | 36 | **26.37** | 25.93 | 22.26 (Ja'Kobi Lane) | 32.59 (Derrick Henry) |
| 5 | JacobRosenzweig | 29 | **25.31** | 24.50 | 21.98 (Jordyn Tyson) | 31.81 (Jared Goff) |
| 6 | Oliverwkw | 34 | **25.18** | 25.01 | 21.43 (Kenyon Sadiq) | 31.67 (Hunter Henry) |
| 7 | LWebs53 | 36 | **24.49** | 23.64 | 21.55 (Carnell Tate) | 30.90 (Deshaun Watson) |
| 8 | plehv79 | 35 | **24.41** | 23.94 | 21.19 (Jeremiyah Love) | 30.89 (Patrick Mahomes) |

Every rostered player has a birth date in the Sleeper dictionary — 268 of 268,
no missing denominators anywhere in the table.

## Including future picks

The build carries a companion column, `Team age including picks`, which averages
the next three drafts' picks in at their expected rookie age (a pick in year Y is
priced as someone born Sept 1 of Y−22). It reorders the middle of the table,
because pick ownership is very unevenly distributed — plehv79 and LWebs53 hold 19
of the 96 picks each, shmuel256 and stevenb123 hold 6.

| Team | Avg age | Picks held | Incl. picks | Rank change |
|---|---|---|---|---|
| shmuel256 | 27.98 | 6 | **26.68** | 1 → 1 |
| BROsenzweig | 27.68 | 15 | **25.06** | 2 → 3 |
| AceMatthew | 27.32 | 9 | **25.72** | 3 → 2 |
| stevenb123 | 26.37 | 6 | **25.40** | 4 → 4 |
| JacobRosenzweig | 25.31 | 14 | **23.58** | 5 → 6 |
| Oliverwkw | 25.18 | 8 | **24.13** | 6 → 5 |
| LWebs53 | 24.49 | 19 | **23.00** | 7 → 7 |
| plehv79 | 24.41 | 19 | **22.93** | 8 → 8 |

BROsenzweig is the sharpest case: third-oldest by players, but a pick stack that
drops it below AceMatthew on the combined measure. Oliverwkw and
JacobRosenzweig swap for the same reason in the other direction.

## Where the roster ages came from, and how they got there

Same date (today), each team's **2025 final roster** versus its **current** one —
so the delta is roster turnover only, with natural ageing removed:

| Team | 2025 final roster | Now | Δ | Rank |
|---|---|---|---|---|
| shmuel256 | 28.22 | 27.98 | −0.24 | 2 → 1 |
| BROsenzweig | 27.84 | 27.68 | −0.16 | 3 → 2 |
| AceMatthew | 28.24 | 27.32 | −0.92 | 1 → 3 |
| stevenb123 | 25.96 | 26.37 | **+0.41** | 6 → 4 |
| JacobRosenzweig | 26.38 | 25.31 | −1.07 | 4 → 5 |
| Oliverwkw | 25.42 | 25.18 | −0.24 | 7 → 6 |
| LWebs53 | 26.34 | 24.49 | **−1.85** | 5 → 7 |
| plehv79 | 24.71 | 24.41 | −0.30 | 8 → 8 |

stevenb123 is the only team that got **older** through the offseason; LWebs53 got
younger by nearly two years, the largest move in either direction, and dropped
from mid-table to seventh. shmuel256 inherits the top spot without doing anything
— AceMatthew shed 0.92 years and passed it downward.

## Sensitivity — does the ranking depend on how a roster is counted?

Rosters are not the same size here (29 to 36), and the build's definition of
"roster" includes taxi-squad and IR players — a deep bench of young stashes pulls
a mean down. Re-run under three pools:

| Team | all (build) | active (no taxi/IR) | starters only | median |
|---|---|---|---|---|
| shmuel256 | 27.98 (1) | 28.39 (1) | 27.69 (1) | 27.16 (2) |
| BROsenzweig | 27.68 (2) | 28.21 (2) | 27.48 (2) | 27.16 (3) |
| AceMatthew | 27.32 (3) | 27.52 (3) | 26.97 (4) | 27.21 (1) |
| stevenb123 | 26.37 (4) | 26.74 (4) | 27.00 (3) | 25.93 (4) |
| JacobRosenzweig | 25.31 (5) | 25.51 (5) | 25.26 (5) | 24.50 (5) |
| Oliverwkw | 25.18 (6) | 25.44 (6) | 25.23 (6) | 25.01 (6) |
| LWebs53 | 24.49 (7) | 24.63 (7) | 24.17 (7) | 23.64 (8) |
| plehv79 | 24.41 (8) | 24.20 (8) | 24.12 (8) | 23.94 (7) |

The starters column is the weakest of the four and is reported anyway: the 2026
season has not started, so several managers have not set a lineup and Sleeper
writes its `"0"` empty-slot sentinel — the pools are 7 to 10 players, not a
uniform 10 (stevenb123 and AceMatthew field 7, shmuel256 and plehv79 9). *By
design*, not a defect, but it makes that column the least comparable across
teams.

**The answer holds.** The top two and the ordering of positions 5-6 are identical
under all four readings. Two borderline items, both flagged rather than filtered:

- **AceMatthew vs stevenb123 (3rd/4th) swaps on starters only.** AceMatthew's
  bench is older than its lineup; stevenb123's is younger. Their means differ by
  0.95 years on the full roster and by −0.03 on the ten starters. *Needs human
  judgement* — which one is "older" depends on whether you mean the roster or
  the team that takes the field.
- **LWebs53 vs plehv79 (7th/8th) swaps on the median.** plehv79 has the lower
  mean but the higher median: it carries the league's single youngest player
  (Jeremiyah Love, 21.19) and more young depth, while LWebs53's distribution is
  flatly younger. *By design* — mean and median answer different questions about
  a skewed roster; the mean is what the build reports and what the table above
  ranks on.

## Method and guards

`analysis.roster_ages(2026)` — added for this inquiry, see below. Ages are
`(date − birth date) / 365.25`, rounded to 2, over every player on the roster,
with birth dates from the Sleeper dictionary in `exports/snapshot/`. That is the
build's own arithmetic for `team_week."Player average age"`, restated so it can
be applied to a season the exports do not cover.

**The guard that licenses it:** `check_roster_age_matches_build` recomputes the
column from the snapshot for every team-week the build did compute and requires
an exact match. It passes for all **680 team-weeks across 2021-2025** (`python
scripts/inquire.py validate`). The measure applied to 2026 is therefore the same
measure, not a lookalike.

## Caveats

- **The exports stop at 2025**, so this cannot be read off `team_week` — the
  2026 season is in progress and has no scored weeks. Everything above is
  computed from `exports/snapshot/season_2026/rosters.json`, the live roster
  state at capture (2026-08-06). Any move made after that capture is not here.
- **The 2026 rookie draft is complete** (2026-07-12), so this year's rookies are
  already on the rosters and counted as players. The picks column covers
  2027-2029 only, matching the build's three-year age horizon.
- **The picks-inclusive column is not back-testable.** Only the current
  season's snapshot carries `traded_picks.json`, so unlike the player-age column
  there is no historical build number to check it against; it reads current
  ownership directly (traded picks from the file, everything else still with its
  original owner, 96 picks accounted for = 3 years × 4 rounds × 8 teams). The
  build reaches the same figure by walking trade events to a past date — a route
  that is unnecessary and unavailable for "now". Treat the player-age table as
  verified and the picks table as consistent-but-unverified.
- **Ages are of players as rostered, not as playing.** Aaron Rodgers (42.68) and
  Keenan Allen (34.28, no NFL team in the dictionary) are still on rosters and
  still count. This matches the build, which has always aged the roster rather
  than the active lineup — the 2025 tables include Philip Rivers at 44.04 on
  LWebs53 for the same reason.
- **Not held constant:** nothing here is a counterfactual, so no lineup model or
  replay assumption is involved. The only judgement calls are the reference date
  and the roster pool, both reported above under every alternative.

## What was added

The primitive did not exist: `inquiry.Players` deliberately keeps only
name/position/team, and no helper aged a roster. Added to
`lib/lotg_support/analysis.py` (inquiry-only; the build does not import it) —
`roster_ages`, `player_age`, `pick_expected_age`, `week_reference_date`,
`picks_held`, `birth_dates`, the `check_roster_age_matches_build` guard wired
into `analysis.validate`, three tests in `tests/test_analysis.py`, and an `age`
subcommand on `scripts/inquire.py`. Nothing under `src/`, `config/`,
`.github/workflows/`, `exports/` or `data/` changed.
