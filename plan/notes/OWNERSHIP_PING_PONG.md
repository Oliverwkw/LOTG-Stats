# Two rosters, three trades: is Kamara alone?

**Question.** "Is there any other player like Kamara that has only been on two
teams but has been traded 3+ times?"

**Answer. No — Alvin Kamara is the only one, and it is not close.** He is the
sole player in league history with three or more trades and only two career
rosters. Data as of the committed exports (through the completed 2025 season;
the 2025-11-02 trade is included).

```
player        spells  trades  teams  boomerangs  path
Alvin Kamara       4       3      2           2  shmuel256 > stevenb123 > shmuel256 > stevenb123
```

A pure ping-pong: drafted by shmuel256 in the startup at 2.08, to stevenb123 in
the 2021 Patterson/Gainwell package, back to shmuel256 in May 2023 with Mike
Williams and Kyler Murray, back to stevenb123 in November 2025 for a 2026
fourth. He never touched the other six rosters.

## The near misses

Nobody else with 3+ trades has fewer than three rosters. The whole three-team
tier, over-inclusively:

| Player | Trades | Teams | Path |
|---|---|---|---|
| Calvin Ridley | 5 | 3 | Oliverwkw > shmuel256 > stevenb123 > shmuel256 > Oliverwkw > shmuel256 |
| Derek Carr | 3 | 3 | AceMatthew > AceMatthew > shmuel256 > stevenb123 > AceMatthew |
| Brian Robinson | 3 | 3 | AceMatthew > BROsenzweig > shmuel256 > AceMatthew |
| Tua Tagovailoa | 3 | 3 | LWebs53 > BROsenzweig > LWebs53 > Oliverwkw |

Ridley is the real near-miss: five trades while never leaving three rosters,
acquired by shmuel256 on three separate occasions.

**Kamara's uniqueness sits one trade above a crowded tier.** Drop the threshold
to two trades and seven more two-roster players appear — Amari Cooper, DeVonta
Smith, Joe Mixon, Isiah Pacheco, Justin Fields, Elic Ayomanor, Mason Taylor. The
claim is exact but narrow, and worth stating as "three trades, two rosters"
rather than as "uniquely immobile".

## Method

```bash
python scripts/inquire.py ownership --min-trades 3 --max-teams 2
```

The first pass was a two-column filter on `player_all_time`
(`Number of teams = 2`, `Number of trades >= 3`), which returns the same single
row. That was not enough on its own for two reasons, and both are why the
`ownership_ledger()` primitive exists:

- **`Number of teams` is build-volatile** (`lib/lotg_support/volatile_columns.py`),
  so it can move between builds. A claim of uniqueness resting on one volatile
  column wants an independent derivation.
- **The two columns mean subtly different things.** `Number of teams` is
  tenure-based — every roster that ever held him, waiver pickups included —
  while a trade-only reconstruction counts just the rosters involved in a trade
  of him. For Kamara they coincide (0 non-trade transactions: he was never added
  or dropped off waivers), but that had to be checked, not assumed.

The ledger rebuilds ownership from the raw record: one row per acquisition
(draft, waiver add, trade) for every player, snapshot-derived and pid-exact for
2021-2026, name-matched from the exported sheet for 2020 (the ESPN backfill has
no snapshot). Both derivations, and the `player_all_time` filter, agree.

## What backs it

- `check_trade_counts_match_build` — the ledger's trade rows, counted per
  player, equal `player_all_time."Number of trades"` for **all 651 players**,
  exactly. The build counts trades from Sleeper pids off `_recv_player_ids`;
  the ledger counts events. Two independent paths, no drift.
- `check_ledger_chains` — every one of the **464** trade hand-offs takes the
  player from exactly the roster the ledger last had him on. This is the
  stronger guard: it tests ordering, sender attribution and the snapshot/sheet
  merge at once, and it caught two real ordering defects while being written.
- `tests/test_ownership.py` — both guards, plus the trap cases below.

## Traps this ran into

Three, all now in `plan/INQUIRY_PLAYBOOK.md` and handled in code:

1. **A traded pick is not a traded player.** `trades.Assets received` writes a
   pick as `2021 1.06(T. Etienne)`; splitting the cell on `;` invents a 2020
   trade for a player who entered the league in 2021. `analysis.split_assets()`.
2. **Sleeper can record one exchange twice.** On 2021-08-29 LWebs53 and
   shmuel256 traded 2021 2.08 for 3.06 plus two fourths, *and* separately
   swapped the two players those picks became (Michael Carter for Rhamondre
   Stevenson) — one deal, two transactions, timestamped inside the draft
   window. Counting both moves each player twice.
   `analysis.DUPLICATE_TRADE_TRANSACTIONS` holds the id; the build already
   deduplicates it, which is why the count guard reconciles.
3. **The sheets and the snapshot are on different clocks.** The exported `Date`
   is Sleeper's `created` rendered in US Eastern (524 of 548 `trades` rows match
   a snapshot trade to within two seconds under that zone; 2 under UTC), while
   the snapshot's own date is day-precision. Ordering the two by printed text
   put a waiver add *after* the same-day trade that moved the player out, and
   ordered a trade and its same-day reversal by luck. `EXPORT_TIMEZONE` and the
   epoch sort key fix it.

## Caveats

- Rosters are named as the sheets spell them; the ledger uses `canonical_team`
  spelling throughout.
- The ledger records acquisitions, not departures — a spell ends at the next
  acquisition, and the last spell is open. "Two teams" therefore means "two
  distinct rosters acquired him", which is the right reading of the question but
  not the only possible one.
- 2020 trades are name-matched, so a 2020-era rename would be invisible to
  them. No 2020 trade involves a player who has since been renamed in Sleeper's
  dictionary, and the count guard covers those rows too.
- Two players in Sleeper's dictionary share the name "Michael Carter" (the RB
  and the CB). Only the RB was ever traded here, so no count is conflated, but
  the ledger carries `player_id` precisely so this is checkable rather than
  assumed.
