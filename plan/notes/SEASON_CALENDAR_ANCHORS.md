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
investigation moved it four times before it settled:

**A season runs from kickoff week 1 to the end of its championship game, and
everything after that championship belongs to the NEXT season — its offseason —
through to that season's kickoff.** Which reduces to one comparison:

> A move belongs to the **first season whose championship has not happened yet.**

That settles both edges at once, and both really occur here, because the
championship date moves (2020's final was Dec 28; 2021's ran to Jan 3):

- A move in January **before** its season's final is still the old season — the
  season is still being played.
- A move in late December **after** its season's final is already the new one,
  even though the calendar has not turned.

So a listed year can differ from its date in **either** direction, and the
league calendar decides which — not the month. 17 rows differ: fourteen on
2020-12-31 (past the Dec 28 final, so 2021), one 2025-12-30 (past Dec 29, so
2026), one 2022-01-02 and one 2023-01-01 (both before their season's final).

**Only two rows change from what the build produced before.** The old label came
from Sleeper's league rollover, which happened to agree with the real league
calendar almost everywhere:

| date | team | player | was | now |
|---|---|---|---|---|
| 2025-01-01 | Oliverwkw | John Metchie | 2024 | **2025** — 2024's final was Dec 30 |
| 2025-12-30 | stevenb123 | Noah Gray | 2025 | **2026** — 2025's final was Dec 29 |

Three corrections the investigation had to make on the way, all worth keeping:

- **It is not a month rule.** A first cut rolled all of January back (84 rows);
  a second rolled back only to championship Monday but let December keep its own
  year (16 rows). Both miss half the seam: the boundary is the championship, and
  it falls on either side of New Year depending on the year.
- **The accumulators do have the date.** The claim that one loop has no
  timestamp in scope was wrong — it came from a backward search that stopped
  short of the assignment. `created_dt` is set at the top of the same loop.
- **The rule has to read the LEAGUE clock, not UTC.** Timestamps are UTC
  internally and the Date column is rendered America/New_York at write time, so
  2021-01-01 00:00 UTC displays as 2020-12-31 19:00. Deriving from the UTC date
  labels a row from a day that appears nowhere on the sheet — the same
  representation mismatch that produced the startup-draft bug.

`_season_window` (the Offseason/Inseason split) and `_move_season` (the label)
both read `_season_end_monday`, so a row is in-season exactly when its own date
falls inside its own season's window. They cannot drift apart.

**Now covered too: the weekly counters.** `team_week` / `team_year`
"Number of transactions", "Number of trades" and "Amount of FAAB spent" used to
reach `team_year` by summing `team_week`, which silently filed a
post-championship move under the season that had just finished — `team_week`
has no bucket for it, because in the season it belongs to it is *offseason* and
has no week at all.

Loop 1 (the weekly counters) now resolves each move's season with the **same
timestamp rule Loop 2 uses** — `status_updated` for a waiver, `created`
otherwise — and credits two places: the weekly counter only when the move's
season is this one, and a season-scoped counter always. `team_year` reads the
latter; `team_all_time` and `league_year` already roll up from `team_year`, so
they follow; `league_all_time` sums the same counters instead of the weeks.
`league_week` still sums weeks, which is right — it *is* a week.

Both waivers, which is why the timestamp rule mattered: resolving a waiver from
`created` in one loop and `status_updated` in the other would have let the two
disagree about the season, recreating the defect in a new place.

Two things this turned up:

- **The manual-transactions overlay bypassed the counters entirely.** It
  increments `team_week` directly, so shmuel256's hand-entered 2023 Puka Nacua
  pickup appeared in a week but in no season total. It is season-scoped now.
- **A third flat date anchor, `Sept 5`,** in that same overlay — a variant the
  earlier sweep missed because it was not one of the `Sept 7` ones. It now uses
  `_season_week_of` like everything else.

What moves: exactly the two rows named above, out of the old season's week 17
and into the new season's total. `Oliverwkw 2024` week 17 goes 1 -> 0 and the
season 33 -> 32; `stevenb123 2025` week 17 goes 2 -> 1 and the season 59 -> 58.

**One reconciliation deliberately does not hold offline.** `league_all_time`
counts the 2026 credit; the 2025-league offline build has no `team_year` row for
2026 to hold it, so the two differ by exactly 1 there. CI builds 2026 and both
sides include it.
