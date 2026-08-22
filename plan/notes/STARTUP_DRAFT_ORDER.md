# The 2020 startup was numbered by draft slot, not draft order

Found while answering "what % of Oliverwkw's all-time points is Nick Chubb?" —
the answer (5.18%) was fine, but the pick that produced him read `2.01` on the
picks sheet. Oliverwkw held the 1.01 in a **snake** startup, so his round-2 pick
was the *last* of the round: Chubb went **16th overall**, and ESPN's own draft
record calls him **`2.08`**.

## What was wrong

A team's **draft slot** is constant across a draft. The **position it picks
from** is not — a snake reverses every even round, so slot 1 picks 1st in round
1 and 8th in round 2. The two coincide only in a linear draft.

`src/espn_2020.py` kept `round` and `overallPickNumber` when it reshaped ESPN's
picks into Sleeper's form, and **threw `roundPickNumber` away**. The build then
re-derived a number in `src/lotg.py` by taking each team's *round-1* pick as a
constant slot and writing `round.slot`. Every even round came out backwards.

**74 of 152 startup picks were mislabeled** — all 72 even-round picks, plus 2 in
round 5 that moved for the separate reason below.

This is not only cosmetic. The pick-adjustment pass recovers a pick's overall
position straight back out of its number:

```python
_pos = (_R - 1) * _rsize + _S      # src/lotg.py, _window_slots
```

and scores each non-rookie pick against the mean of its **8 nearest neighbours**
by that position. With even rounds reversed, Chubb was compared against a window
centred on real pick 9 instead of real pick 16 — pulling four round-1 picks into
his baseline. Essentially every startup pick moved:

| Column (stat sd) | Picks changed | mean abs Δ | max abs Δ | Chubb: before → after |
|---|---|---|---|---|
| Avg PPG on team adj. by position (4.79) | 141/141 | 1.08 | 3.85 | −3.0463 → **−5.9550** |
| Avg career PPG adj. by position (4.33) | 152/152 | 0.85 | 3.19 | −1.3600 → **−3.9625** |
| Avg points added adj. by position (7.39) | 144/152 | 1.27 | 3.47 | −1.0788 → **−3.5800** |
| Player addition value (23.09) | 141/141 | 4.57 | 14.44 | −17.5513 → **−29.9698** |

Roughly 0.2-0.3 sd on average, and not in a systematic direction: Chubb gets
*worse* because his true neighbourhood is the strong early-round-3 tight ends
(Kittle, Kelce, Andrews) rather than the round-1 busts (Michael Thomas, CEH).

`O-Score` for startup picks is a percentile over the non-rookie pool built from
two of these columns, so it moves too. It cannot be checked offline — KTC is
unreachable there and O-Score is N/A for **every** pick, rookie included.

## The six picks that broke the snake

Six picks did not fit the slot-reversal pattern at all. They are the only ones in
the draft carrying ESPN's **`owningTeamIds`** key — its marker for a pick whose
slot changed hands, where `teamId` is the team that made the selection and
`owningTeamIds` the slot's original owner:

| Overall | Pick | Player | Drafted by | Slot owned by |
|---|---|---|---|---|
| 29 | 4.05 | Mike Evans | LWebs53 | AceMatthew |
| 31 | 4.07 | Kenny Golladay | AceMatthew | LWebs53 |
| 34 | 5.02 | Allen Robinson | AceMatthew | LWebs53 |
| 36 | 5.04 | D.J. Moore | LWebs53 | AceMatthew |
| 61 | 8.05 | Keenan Allen | LWebs53 | AceMatthew |
| 63 | 8.07 | Hunter Henry | AceMatthew | LWebs53 |

It is a clean two-way deal: **LWebs53 and AceMatthew swapped their round 4, 5 and
8 picks with each other**, each round's two picks mirroring exactly. Net movement
is small — LWebs53 moved up two spots in rounds 4 and 8, AceMatthew up two in
round 5.

Three independent things agree:

1. Once the slot follows the pick's **owner** rather than its drafter, the draft
   is a **perfect snake** — zero violations across all 152 picks.
2. `data/espn_2020_raw/email_trades.json` holds exactly one picks-involving trade
   all season, timestamped **2020-09-09T21:45:18Z**, ~6 hours before the draft
   completed (`completeDate` = 2020-09-10T03:30:24Z). Its legs are empty, which
   is why it never produced a `trades.csv` row — the email parser only extracts
   player legs.
3. `plan/notes/espn_2020_backfill.md` already recorded it in prose: *"The one
   on-platform 'pick trade' email is the startup-draft slot swap."* It had simply
   never been modelled in code.

This also retires the premise behind the drafter-attribution special case, which
read the startup's drafter off `Original Team` "because startup picks weren't
tradeable (ESPN)". Six of them were.

## The fix

- `src/espn_2020.py` carries `pick_in_round` (ESPN's `roundPickNumber`),
  `draft_slot` (recovered through the snake) and `original_roster_id`
  (`owningTeamIds`, falling back to the selecting team) into the Sleeper-shaped
  picks.
- `src/lotg.py` numbers startup picks by **true draft order**, matching how the
  rookie/vet ledger already numbers its own picks by pick-order position. The
  pick-adjustment window then reads correct positions with no change of its own.
- `Original Team` is the slot's owner, `Final Team` the drafter — equal on 146
  picks, different on the six above.
- Drafter attribution uses `Final Team` at every draft, startup included.

`Commissioner moved?` stays `False` on the six: it marks an *untracked* hop, and
this one is recorded by the source.

## The swap as a trade

The 2020-09-09 email is the only picks-involving one of the season, and its body
listed no player legs — so it parsed to an empty shell with no teams and no
assets, and produced no `trades.csv` row. The two sources each hold half of the
deal: the **email** knows when it happened and that it involved picks; the
**draft record** knows exactly which slots moved but carries no date. Joining
them gives the shell its two teams, and
`data/commissioner_pick_trades.csv` — the same overlay that fills in the picks
the other 2020 trade emails dropped — hangs the six pick legs off it, keyed
`pick_year 2020` with `orig_owner` = the slot's owner (for a startup pick,
round + slot ↔ round + original owner is one to one).

The join is guarded rather than assumed: it attaches only when there is exactly
one legless picks-involving email **and** exactly two swap partners in the draft.
If either stops holding, it attaches to nothing and the overlay reports its rows
as unmatched, rather than putting the legs on the wrong deal.

Result — two rows, one per side:

```
AceMatthew  recv 2020 4.07(K. Golladay); 2020 5.02(A. Robinson); 2020 8.07(H. Henry)
            sent 2020 4.05(M. Evans);    2020 5.04(D. Moore);    2020 8.05(K. Allen)
LWebs53     the mirror
```

`trades.csv` 504 → 506 rows; both teams +1 trade on the team sheets and 2020 +1
league-wide; `transactions.csv` unchanged. All six pick rows now read
`Number of trades` 1.

### Three "5.0X is a FAAB buy" shortcuts had to learn about the startup

A pick numbered `5.0X` had only ever meant the synthetic 20-FAAB draft-day buy,
so three places skipped them: `pick_lookup` (trade asset labels),
`_pick_to_drafted`, and `_pick_hist_lines`, which routed them to a sentinel
`_R5XX_BASE` ledger key. The 19-round startup's round 5 holds **eight real
picks**, two of them swapped — so before the carve-out the round-5 legs read 0
trades and rendered as a bare `2020 5.??`, while their round-4 and round-8
counterparts *in the same deal* read 1.

The carve-out goes through `_su_row()`, which also closes a trap worth naming:
`_is_startup` is set only on the 152 startup rows, so every other row holds
**NaN — and NaN is truthy**. A bare `bool(row.get("_is_startup"))` reads every
rookie pick as a startup pick, exactly inverting the intent. The seven genuine
5.0X buys (2025/2026) are unchanged and are guarded by their own test.

A fourth site — the chain application at `src/lotg.py:9371` — carries the same
`5.` skip but sits inside an `if False:` block, so it is dead code and was left
alone.

## The boundary the swap landed on

Filing the swap surfaced a third thing: it came out as an **in-season** trade,
because the Offseason / Inseason split anchored on a fixed **Sept 7**. That is
wrong at both ends, and by an amount that moves:

- **Kickoff moves.** NFL week 1 is the Thursday after Labor Day — Sept 4 in
  2025, Sept 10 in 2020 and 2026, six days of spread across the seasons on
  record. A fixed Sept 7 reads everything in the gap as in-season, which is
  exactly where a deal struck the evening before the 2020 draft finished sits.
- **The far end did not exist.** A season ends at its championship, not at New
  Year, so a deal made after the title game counted as in-season until the
  calendar rolled over.

The window is now `(_nfl_kickoff_thursday(season) .. championship Monday)`, the
second from `_finals_weeks()` — both already in the build, just not used here.
On the data as it stands **only the swap actually moves**: every other trade
sits well inside its window, and no trade at all falls after a championship, so
that half is a guard against a case that has not happened rather than a
restatement of one that has.

That in turn exposed the first season's `Offseason trades` being blanked to N/A,
on the premise that there is no offseason before the league's first season.
There is now one. Blanking it left 2020 reading `Offseason N/A + Inseason 4 =
Total 5` and disagreeing with `team_all_time`, which counts the split straight
off the trade dates. Offseason **turnover** stays N/A — there genuinely is no
prior-season roster to diff against. Removing the NaN also lets the column
render as an integer (`1`, not `1.0`) across every season, matching its
`Inseason` / `Total` siblings: a formatting diff on every row, no value change.

Worth keeping straight: the **weekly** bucket is a different rule and was not
touched. An offseason trade within 7 days of kickoff still rolls into week 1 by
design, so "offseason" and "week 1" legitimately co-occur — as they do here.

## Still open

- **It is a pick-only trade**, the league's only one. Any 2020 trade analysis
  that keys on players sees an empty deal.
- **Season is assigned by calendar year.** A trade struck during a championship
  week that falls in January (2022-01-03, 2023-01-02, 2024-01-01) would be
  filed under the *next* season and read as offseason. No such trade exists, and
  this predates the window change — but the window cannot fix it, because the
  season label is decided before it is consulted.
- **Whether any 2020 pick trade is missing entirely.** Off-platform pick trades
  were possible in 2020 (see `espn_2020_backfill.md`) and would leave no
  `owningTeamIds` trace. Only on-platform slot swaps are recoverable this way.
- **Startup `O-Score` is unverified.** It moves with the corrected inputs but
  cannot be computed offline; it needs a look in the post-merge results audit.
