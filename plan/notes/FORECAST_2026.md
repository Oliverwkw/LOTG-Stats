# What is each team's % chance of winning 2026?

**Question.** "Give % chance of each team winning this year."

**Short answer.** Asked on 2026-08-07 — rookie draft done, no NFL week played.
Two teams are clear of the field, and which of them leads depends on how much
weight you put on injuries and depth:

| Team | Champion | Reach the final | Make the playoffs | E[wins] (of 14) | Projected PF/wk |
|---|---:|---:|---:|---:|---:|
| stevenb123 | **27.9%** | 49.1% | 83.8% | 9.2 | 147.7 |
| shmuel256 | **21.6%** | 41.5% | 76.5% | 8.7 | 145.0 |
| AceMatthew | **17.1%** | 34.7% | 69.2% | 8.3 | 142.4 |
| BROsenzweig | **16.4%** | 33.6% | 68.4% | 8.2 | 142.1 |
| Oliverwkw | **11.9%** | 25.9% | 58.2% | 7.7 | 139.2 |
| JacobRosenzweig | **4.6%** | 12.7% | 34.6% | 6.5 | 132.5 |
| LWebs53 | **0.4%** | 1.5% | 5.4% | 3.9 | 117.9 |
| plehv79 | **0.2%** | 0.9% | 3.8% | 3.5 | 115.4 |

```bash
python scripts/forecast.py --season 2026 --detail --model all --sensitivity
```

20,000 simulated seasons over the real 2026 schedule, seeded and bracketed by
the same code a counterfactual replay uses.

**The headline is a two-horse race, not a coronation.** shmuel256 has the best
roster in the league on paper — a healthy lineup worth 151.1 points a week,
clear of anyone else — and still comes second, because it is also the roster
that loses the most to injury and has the least behind its starters. Run the
same simulation with the injury and depth model switched off and the order flips
(shmuel256 26.7%, stevenb123 25.3%). Report them as close.

**One thing this note does that the model alone cannot.** In August, the
injury designations in the snapshot are worthless, and the answer above is built
on outside reporting instead — see *"Why the preseason injury flags are thrown
away"* below. That research is a file
(`plan/notes/forecast_status_2026.csv`), one row per player, each with a
number, a note saying why, a URL and the date it was true.

---

## Why the preseason injury flags are thrown away

The snapshot flags fifteen players on 2026 rosters as reserve/IR/PUP. **Eleven
of them were injured in the closing weeks of 2025.** That is not a coincidence:
a manager parks a player in the IR slot in week 15 and never moves him, so an
August snapshot is a record of how *last* season ended, not of who is hurt now.
The 2026 `nflverse_injuries.csv` in the snapshot is **empty** — no NFL game has
been played, so no official injury report exists to correct it.

Believing those flags is wrong in both directions, and expensively so:

| Player | Snapshot says | What is actually true, 7 Aug 2026 |
|---|---|---|
| **Brock Bowers** (AceMatthew) | on reserve | **Fully healthy** and the reported standout of Raiders camp |
| **Patrick Mahomes** (plehv79) | on reserve | ACL+LCL in Wk15, but **fully cleared**, taking first-team reps, on track for Week 1 |
| **Cam Skattebo** (stevenb123) | on reserve | **"Good to go"**, taking the majority of first-team backfield work |
| **Tyreek Hill** (AceMatthew) | Questionable | Two knee surgeries, *"no power in my left leg"*, **unsigned free agent**; an insider says there is "no guarantee" he plays in 2026 |
| **Joe Mixon** (AceMatthew) | Questionable | Missed all of 2025, released, **unsigned**, reported to have told ex-teammates he is done |
| **Ricky Pearsall** (shmuel256) | IR | **Season-ending IR** — PCL surgery, six-to-twelve months |
| **George Kittle** (shmuel256) | PUP | Torn Achilles in January, on PUP; GM optimistic for Week 1, but the largest single downside on any contender |
| **Michael Penix** (Oliverwkw) | Questionable | Eight months from ACL surgery, not cleared for 11-on-11; **Tua starts Week 1** |
| **Brandon Aiyuk** (plehv79) | DNR | Still on the reserve/left-squad list; needs a reinstatement petition granted before he plays anywhere |

So `AvailabilityModel.designations="auto"` believes the flags **only once the
season has started**, and in the preseason they are replaced by
`plan/notes/forecast_status_2026.csv` — 21 researched players, every row with a
note, a source URL and a date. Twenty of them are on a startable roster.

Two things do not need research, because the snapshot states them plainly:
**taxi-squad players cannot be started at all**, and **a rostered player with no
NFL team cannot score for anyone** (capped at 35% availability, since he may yet
sign). That catches Keenan Allen, Nick Chubb and Najee Harris alongside Hill and
Mixon.

**None of this may touch the backtest.** Today's designations, today's free
agents and a research file written today are all future information to a
projection of 2022 — and letting the free-agent check into the backtest lifts
out-of-sample r from 0.68 to 0.73, which is leakage, not skill. The backtest
therefore runs with all three off, which makes the calibration a floor for the
live forecast rather than a flattering estimate of it.

## What the model does

Five things, each fitted from this league's own history rather than assumed.
Full detail with `--detail`.

**1. What a player is worth.** His scoring rate in this league over the previous
two seasons (0.65 / 0.35), over weeks the build flags as available, weighted
toward the recent end of each season (half-life 8 weeks), shrunk toward the
median rate of a rostered player at his position — and then **adjusted for
age**, on a curve fitted from the league's own year-over-year changes:

| | QB | RB | WR | TE |
|---|---:|---:|---:|---:|
| points per week per year of age | -0.11 | -0.17 | -0.12 | -0.02 |

Fitted as the age coefficient in `next_year_rate ~ this_year_rate + age`, so it
is the part of ageing that is not just regression to the mean; each position is
shrunk toward the pooled slope so TE cannot invent a curve from 101
observations. Over the 3.5 years of age that separate the oldest roster from
the youngest, this is worth a few points a week.

**2. What a rookie is worth — and how weak this class is.** A drafted rookie has
no rate, and pricing him at zero penalises whoever holds the most picks. He is
priced from his **draft-day KTC**, fitted against what past classes actually
returned in year one (zeros included — a rookie who never suits up is part of
what a pick is worth):

```
rookie-year ppg = 0.00200 x draft-day KTC + 0.90     r = 0.55, n = 169
```

This is what makes a weak class read as weak without anyone asserting it. And
2026 **is** the weakest class this league has drafted:

| | 2026 | earlier classes, same picks |
|---|---:|---:|
| mean draft-day KTC | 3,285 | 3,720 |
| median draft-day KTC | 2,777 | 3,266 |
| top-4 picks, mean KTC | 6,115 | 6,214 |

88% of the historical average overall — **ranked 6th of 6** — while the top four
picks price normally.

What that is worth in points, pricing the same 35 picks both ways:

| | market (KTC) | historical slot average |
|---|---:|---:|
| whole class, mean projected ppg | 7.46 | 8.15 |
| round 1 (the eight picks that could start) | 11.57 | 12.27 |
| round 3 | 6.33 | 5.82 |

So the class discount is about **8%**, and it is concentrated in **round 1** —
the only round whose players were going to crack a lineup. Round 3 actually
prices *above* its historical slot average, which is the point of using the
market rather than the slot: this class is not uniformly weak, it is weak
exactly where it matters and slightly rich where it does not. The effect on the
odds is small (`rookies by slot` in the sensitivity grid moves nobody by more
than 1.9 points) because the eight teams' rookie holdings are not that unequal
at the top — but LWebs53, with nine rookies, and plehv79, with five, are the two
carrying most of it.

**3. Who can actually play.** Covered above; four separate things, all of which
the first version of this model got wrong:

- **Taxi-squad players cannot be started.** They sit in the roster's player list
  and an optimal-lineup routine will happily start them. Oliverwkw's 1.02 pick
  Fernando Mendoza is on the taxi squad and was in the previous projection's
  starting eleven. Now excluded, in the backtest and live alike.
- **Reserve/IR and PUP designations are current and real.** plehv79 has
  **Patrick Mahomes on reserve** — he was the top player in their previous
  projection. shmuel256 has Kittle (PUP) and Pearsall (IR); AceMatthew has
  Bowers, Hill and Mixon. Such a player is available in **51%** of his remaining
  weeks — measured, from every player this league had injured in a week 1,
  against an 82% base rate. `Questionable` is ignored: in an August snapshot it
  is stale week-17 noise.
- **Everyone else misses time too**, at a rate that repeats year to year at only
  r ≈ 0.2, so a player's own availability is shrunk hard toward his position's
  base.

Availability is then **simulated, not averaged**: each draw knocks players out
and the lineup is refilled from whoever is left. That is what makes depth cost
something, and it is the single biggest change to the answer:

| Team | Healthy lineup | Fielded | Depth cost | Weekly swing from availability | Rookies | Unsigned | Researched |
|---|---:|---:|---:|---:|---:|---:|---:|
| stevenb123 | 150.0 | 147.7 | 2.4 | 3.0 | 2 | 0 | 4 |
| shmuel256 | **151.1** | 145.0 | **6.1** | 5.3 | 3 | 0 | 2 |
| AceMatthew | 145.3 | 142.4 | 2.9 | 3.2 | 3 | 3 | 4 |
| BROsenzweig | 145.4 | 142.1 | 3.3 | 3.2 | 0 | 0 | 0 |
| Oliverwkw | 142.0 | 139.2 | 2.8 | 2.5 | 1 | 1 | 3 |
| JacobRosenzweig | 134.8 | 132.5 | 2.3 | 2.4 | 3 | 0 | 0 |
| LWebs53 | 123.6 | 117.9 | 5.7 | 5.1 | 9 | 1 | 2 |
| plehv79 | 119.0 | 115.4 | 3.6 | 4.5 | 5 | 0 | 5 |

shmuel256 has the best starting eleven and the worst twelfth-through-fifteenth:
ordinary attrition costs them 6.1 a week where it costs stevenb123 2.4, and
their weekly spread is nearly twice as wide. stevenb123 carry 36 players
including four startable quarterbacks in a superflex league, and that is worth
about three and a half points a week of expected scoring plus a much tighter
distribution. **BROsenzweig is the only roster the research file does not touch
at all** — nobody on it is hurt, unsigned or a rookie.

**4. Who plays whom.** Every week is simulated over the season's **real
pairings**, so strength of schedule is handled whether or not it matters — and
whether it matters turned out to be a fact worth checking rather than assuming.
**2026 is a balanced double round-robin**: eight teams, fourteen weeks, every
pair exactly twice, so each team's mean opponent is exactly the average of the
other seven and no schedule edge exists. That is *not* true of 2021-2025, which
ran fifteen regular-season weeks, so some pairs met three times and some twice.
`schedule(year, strength).sos` prices each team's draw in those seasons.

Where matchups always bite is the bracket, and that is modelled in full: 1v4 and
2v3, +5 to the higher seed in the semifinal, and 2026's two-week final starting
in week 15.

**5. How much of this is knowable.** Every completed season's preseason roster
is projected the same way and regressed on what the team actually averaged:

```
realised weekly PF = 1.035 x projection      (both centred on their season's league mean)
correlation          0.70 in-sample, 0.68 leave-one-season-out
out-of-sample RMSE   10.0 points per week
```

Residual sd 9.9 splits into **team-strength error 8.4** — the part a forecast
could have got right — and the rest, which is a 15-week sample of a team whose
own week-to-week sd is **22.3**. There is also a league-wide week effect of
10.7, everyone up or down together, which is simulated for realism but cancels
head-to-head. Each simulated season draws a true level per team, then weekly
scores from an availability draw plus residual noise **scaled so the total
weekly variance still matches history** — availability is taken out of the
residual, not added on top, or injuries would be counted twice.

## The honest accounting: how much did any of this help?

Measured at team level, on 2022-2025, out of sample: **barely.**

| Projection | out-of-sample r | RMSE |
|---|---:|---:|
| flat two-season rate, rookies by slot, everyone always available | 0.759 | 8.77 |
| + within-season recency | 0.760 | 8.75 |
| + age curve | 0.764 | 8.68 |
| + rookies priced by KTC | 0.769 | 8.62 |
| + taxi players removed | 0.765 | 8.67 |
| + availability and next-man-up depth | 0.766 | 8.66 |

Every one of these is a real effect at the *player* level — the age curve
improves a player-level projection from r = 0.618 to 0.623 out of sample, KTC
beats pick slot for rookies at r = 0.57 against 0.55 — and every one of them
nearly washes out at team level, because an 8-team superflex league with 34-man
rosters is decided by the top ten starters, and the marginal player these
refinements move is the twentieth. **None of these differences is significant on
32 team-seasons.** Anyone quoting the improvement as a gain in accuracy would be
overselling it.

What they *do* change is who is favourite. The team-mean projection barely
moves; the ordering does, because two teams were separated by less than the
depth tax:

| | first model | + depth & ageing | + outside research |
|---|---:|---:|---:|
| stevenb123 | 22.3% | 27.3% | **27.9%** |
| shmuel256 | **34.0%** | 22.1% | 21.6% |
| AceMatthew | 15.7% | 14.8% | 17.1% |
| Oliverwkw | 7.3% | 12.7% | 11.9% |
| BROsenzweig | 15.4% | 17.8% | 16.4% |

The right way to read that is not "the model got better by 12 points on
shmuel256". It is that shmuel256's odds were resting on a projection that
started George Kittle from the IR list and never asked what happens when a
top-heavy roster loses someone.

## Sensitivity — reported over-inclusively

**The method.** Three strength models, same simulator:

| Team | roster | history (last year's table only) | uniform (no information) |
|---|---:|---:|---:|
| stevenb123 | 27.9 | 18.8 | 12.3 |
| shmuel256 | 21.6 | 19.1 | 12.6 |
| AceMatthew | 17.1 | 15.7 | 12.4 |
| BROsenzweig | 16.4 | 13.6 | 12.5 |
| Oliverwkw | 11.9 | 8.9 | 12.8 |
| JacobRosenzweig | 4.6 | 12.7 | 12.6 |
| LWebs53 | 0.4 | 6.9 | 12.6 |
| plehv79 | 0.2 | 4.3 | 12.2 |

`uniform` returning 12.5% each is the harness sanity check. The reason to prefer
`roster` over `history` is measured: rosters project realised scoring at
**r = 0.68** out of sample against **r = 0.30** for a team's own previous season.

**The assumptions.** Twelve variants, at a quarter of the sims (so the "default"
column sits about a point off the headline — that difference is the Monte-Carlo
yardstick for reading the rest of the row):

| Team | default | no depth/injury | no research | stale IR instead | unsigned play on | no age curve | no recency | rookies by slot | last season only | 3 seasons | k=3 | k=12 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| stevenb123 | 28.9 | 25.3 | 27.1 | 28.6 | 27.0 | 27.1 | 29.8 | 28.7 | 29.9 | 24.0 | 28.3 | 29.3 |
| shmuel256 | 22.0 | **26.7** | 24.4 | 22.1 | 24.3 | 26.2 | 22.7 | 21.9 | 22.5 | **26.4** | 22.8 | 20.3 |
| BROsenzweig | 16.1 | 15.5 | 16.5 | 17.6 | 16.4 | 16.3 | 16.4 | 15.9 | 12.6 | 15.0 | 16.5 | 15.5 |
| AceMatthew | 15.8 | 15.1 | 14.4 | 13.2 | 14.8 | 16.2 | 15.5 | 15.3 | 12.0 | 19.6 | 15.7 | 15.9 |
| Oliverwkw | 12.1 | 12.2 | 12.4 | 12.8 | 12.3 | 9.9 | 9.6 | 11.7 | 13.7 | 10.5 | 11.7 | 12.7 |
| JacobRosenzweig | 4.8 | 4.8 | 5.0 | 5.4 | 4.9 | 3.9 | 5.6 | 6.0 | 8.9 | 3.8 | 4.6 | 5.7 |
| LWebs53 | 0.2 | 0.3 | 0.2 | 0.3 | 0.2 | 0.2 | 0.2 | 0.3 | 0.2 | 0.3 | 0.3 | 0.2 |
| plehv79 | 0.1 | 0.1 | 0.1 | 0.1 | 0.1 | 0.2 | 0.1 | 0.1 | 0.2 | 0.4 | 0.1 | 0.3 |

**stevenb123 leads in ten of the twelve.** The two where shmuel256 leads are the
two that undo the reason: switching depth and injury off entirely, and weighting
three seasons instead of two (which reaches back to shmuel256's 2023). So the
top-two ordering is a genuine finding of the depth model, and it is the part of
this answer most worth arguing with. Nothing reorders the bottom two, or moves
anyone across the middle of the table.

The two columns worth reading closely are `no research` and `stale IR instead`,
because they are the price of the outside reporting. Research is worth +1.8 to
stevenb123 and +2.6 to AceMatthew against believing the stale flags — Ace gains
because Bowers is freed and loses because Hill and Mixon are written down, and
the freeing is worth more. (`unsigned play on` and `stale IR instead` only mean
anything with research off, since a researched row overrides both.)

## Guards

Run before the CLI answers, and in CI (`tests/test_forecast.py`, 30 checks):

1. **`check_bracket_pipeline`** — the real snapshot scores pushed through
   exactly the scores → standings → champion path the simulation uses must
   reproduce each completed season's playoff field and champion as `team_year`
   records them. Passes 2021-2025.
2. **`check_completed_season_certainty`** — forecasting a season already over
   leaves nothing to simulate, so it must return 100% for the team the build
   calls Champion. Passes 2021-2025.
3. **`check_research_file`** — the one hand-written input gets the strictest
   check: every row must name a player who is actually rostered, cite a URL,
   carry a valid date and a note saying why, and give an availability that is a
   probability.
4. **`check_schedule_is_balanced`** — reported, not asserted, precisely because
   the answer differs by season.

Plus, in the tests: taxi players are provably unstartable and provably were in
the raw week list; a roster never *gains* from an IR designation and the roster
carrying the most of them clearly loses; the depth cost is positive for every
team, differs between teams, and moves with the weekly spread; the simulated
per-week variance lands on the historical figure rather than above it; a league
of identical teams comes out uniform; and in a balanced schedule the
strength-of-schedule term is exactly zero even when the teams are wildly unequal.

## Held constant — and whether it can change the answer

- **In-season trades, waivers and drops.** The roster is frozen as of
  2026-08-07. Still the biggest omission: a deadline trade is exactly how a 15%
  team becomes a 25% team. Re-run in November and weeks already played stop
  being simulated and start updating each team's strength instead.
- **NFL matchup quality** — which defence a player draws in a given week. The
  committed data has no NFL schedule and no team-defence table, so this is out
  of reach here rather than merely unimplemented. It is also the least costly
  omission for a full-season question: opponent quality largely averages out
  over fourteen games, and it cancels further in a league where every team
  drafts from the same player pool.
- **Correlated byes.** Availability draws are independent, so a roster stacked
  on one NFL team does not lose them together as it really would. This
  understates the cost of stacking; `inquire.py stacks` can say who is exposed.
- **Camp news beyond the 21 players researched.** The research file covers
  everyone the snapshot flagged plus the notable free agents and the top of the
  rookie class; it does not cover every depth-chart battle in the league. It is
  also a snapshot of 7 Aug 2026 and will rot — the `as_of` column is there so a
  later reader can see how stale it has become.
- **Manager lineup skill**, beyond what is inside the historical scoring the
  calibration is fitted to.
- **Draft capital.** Future picks are not valued. plehv79 and LWebs53 are poor
  bets to win *this* season and that is all this note claims about them.
- **One unplaceable player.** stevenb123 rosters a player with no history in
  this league and no 2026 draft slot; he is projected at the undrafted prior of
  3 ppg and the run reports it rather than dropping him.

## Two caveats on the calibration

**2021 is the weak season in the fit** (r = 0.38, against 0.80-0.92 for
2023-2025), because the only history behind it is the 2020 ESPN backfill and the
league re-drafted veterans that spring. It is kept rather than dropped —
removing a season because it fits badly is how a model flatters itself — but the
recent three seasons describe how well this works today, and they are better
than the pooled number.

**The backtest cannot see IR designations, and the live forecast can.** A past
season's snapshot carries its *final* reserve lists, not its week-1 ones, so
using them would be hindsight — and it shows: dropping those players from past
seasons' preseason rosters makes the projection *worse*, out-of-sample r 0.765 →
0.721, because it is removing players who were healthy in September on the
strength of an injury in December. The backtest therefore runs with designations
off, and only the live season uses them. That makes the measured accuracy a
floor for the live forecast rather than a flattering estimate — but it also
means the 51% availability cap is the one parameter here that the backtest
cannot check. It is measured directly instead, from every player this league had
injured in a week 1 (n = 145 across five seasons).

## Reproducing

```bash
python scripts/forecast.py --season 2026                        # the table above
python scripts/forecast.py --season 2026 --detail               # depth, age, rookie class
python scripts/forecast.py --season 2026 --model all --seeds    # baselines + seeding
python scripts/forecast.py --season 2026 --sensitivity          # the assumption grid
python scripts/forecast.py --calibration                        # what the projection is worth
python scripts/forecast.py --validate                           # the guards
```

Runs are seeded (`--seed`, default 20260807) and reproduce exactly.
