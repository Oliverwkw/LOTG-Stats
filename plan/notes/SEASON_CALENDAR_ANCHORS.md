# The build had seventeen copies of "the season starts September 7"

Follow-up to `STARTUP_DRAFT_ORDER.md`, which fixed the Offseason/Inseason split
to use the season's real window. That fix touched one of the seventeen places
the flat **Sept 7** anchor appeared; this one retires the rest.

## Why a flat anchor is wrong

NFL week 1 is the **Thursday after Labor Day**, and it moves six days across the
seasons on record:

| season | real kickoff | drift vs Sept 7 |
|---|---|---|
| 2020 | Sept 10 | +3 |
| 2021 | Sept 9 | +2 |
| 2022 | Sept 8 | +1 |
| 2023 | Sept 7 | 0 |
| 2024 | Sept 5 | −2 |
| 2025 | Sept 4 | −3 |
| 2026 | Sept 10 | +3 |

Fantasy weeks are 7 days wide, so a ±3-day anchor error puts any date within
three days of a week boundary in the wrong week. Measured on the committed data:
**26 of 268 distinct trades (10%)** were bucketed into a neighbouring fantasy
week — 2020×12, 2021×4, 2022×10, 2024×8, 2025×19 rows.

Transactions were never affected: they take their week from Sleeper's own bucket
for 2021+ and ESPN's `scoringPeriodId` for 2020. Only **trades** re-derived the
week from a calendar guess, which is the odd part — the platform knew the answer
and the build recomputed it anyway.

## What changed

Two helpers replace all seventeen sites:

- `_week_thursday(season, week)` — the date a fantasy week opens.
- `_season_week_of(date, season)` — the week a date falls in, `0` for the deep
  offseason (an offseason move still rolls into week 1 if it lands within 7 days
  of kickoff, which is the existing Phase 5C rule, now stated once).

Four near-identical copies of that second rule had accumulated — three in
`lotg.py` (`_trade_week_for_date`, `_trade_wk`, and the two tanking variants)
and one in `espn_2020.py` (`_calendar_trade_wk`) — each with its own flat
anchor. Any fix that touched fewer than all four would have left them
disagreeing with each other. The tanking pair keep their own quirk (a
deep-offseason move clamps to week 1 rather than dropping out), now visible as
`max(1, _season_week_of(...))` instead of a silently different copy.

## Also in this pass

- **The Formulas sheet said two things that stopped being true.** "Award/
  non-tradeable picks (2020 startup, …) count 0" and "Startup picks weren't
  tradeable, so the drafter is the pick's Original Team". Both were retired by
  the startup fix, and this sheet is the league's own documentation.
- **152 lines of dead code deleted.** A legacy pick-chain mutator sat behind
  `if False:`, which still parses and so reads as live to anyone grepping — it
  carried its own copy of the "5.0X is a FAAB buy" skip that the startup fix
  had to chase through four other places. Git history keeps it.
- **`_R5XX_BASE`'s comment claimed "real drafts are 4 rounds, so these never
  collide".** The sentinel arithmetic is still safe (500+), but the premise is
  false — the startup has real rounds 5-19 — and it is what licensed the
  string-based `startswith("5.")` checks that broke.
- **The draft-value round-5 remap is now asserted, not assumed.** Folding
  "round 5" into "round 4 slot 8" is only safe because startup rows are dropped
  from that frame 60 lines earlier, with nothing tying the two together. A real
  round-6+ pick reaching it now fails loudly instead of inflating Draft Value.

## Which SEASON a move belongs to — done, see below

Shipped separately (same sweep, own PR). The spec, kept here because the
investigation moved it twice:

**The rule is `season = year - 1 if month == 1 else year`.** It reproduces every
non-January label exactly and fixes both ends:

- **January.** 55 transactions and 14 trades are labelled with the new calendar
  year when they belong to the season that just ended.
- **December 31.** 15 rows sit the other way round — labelled with the *next*
  season (14 on 2020-12-31, the synthesized ESPN→Sleeper migration drops, and
  one on 2025-12-31). These were not in the original finding; they turned up
  while checking that non-January rows already matched their calendar year.

84 of 2096 rows in total. Note what the current behaviour actually is: **not**
calendar year, as the sweep first reported, but Sleeper's own league rollover,
which lands on a different date each year — which is why 3 of the 7 January
groups are already right and 4 are not.

Two corrections to how that was first written up, both worth keeping:

- **The accumulators do have the date.** The claim that one of the loops has no
  timestamp in scope was wrong — it came from a backward search that stopped
  short of the assignment. `created_dt` is set at the top of the same loop the
  accumulators sit in, which is what made this tractable.
- **The rule has to read the LEAGUE clock, not UTC.** Timestamps are UTC
  internally and the Date column is rendered America/New_York at write time, so
  2021-01-01 00:00 UTC displays as 2020-12-31 19:00. Deriving the season from
  the UTC month labels a row from a date that appears nowhere on the sheet —
  the same representation mismatch that produced the startup-draft bug. It is
  not hypothetical: it is exactly the boundary the fourteen migration drops sit
  on.

**What still is not covered.** `team_week` / `team_year` "Number of
transactions" and "Number of trades" stay league-week scoped — a January move is
still counted in the league week Sleeper filed it under, and `team_year` sums
`team_week` rather than reading the records. So 84 moves are counted in a
team-week row belonging to a different season than their own `Season` label.
Closing that means crediting a move across a season boundary the loops do not
share, and a post-championship move has no honest week in the season it belongs
to (the build's own convention for that case is week 0, which is not a valid
team_week key). Left as a known, bounded gap rather than papered over with an
invented week.
