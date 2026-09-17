# Health email 2026-09-16 — "1 breakage, 2 changed rows, all of it one column, Top Team"

**Verdict: the build is not reproducible, and this is the whole finding.** Neither
player changed hands between the two builds. The wall clock moved, and `Top Team`
is an argmax over durations that are measured to it.

Audited: weekly dataset-health run **#9** (2026-09-16 18:22–18:50 UTC), which
rebuilt from live upstream and diffed against the exports committed by **build run
511** (2026-09-16 01:34–01:43 UTC, commit `6a73141`).

```
[audit-email] lede: All of it is one column, Top Team (2 changed rows). None of the
changes shown are blanks, zeroes or sign flips. NFLverse changed 79 values,
explaining 62 rows of ours.
[audit-email] ⚠️ LOTG dataset health — 1 breakage (2026-09-16)
```

## The two rows

| Player | sheet / row | committed (01:38 UTC) | rebuild (18:35 UTC) | crossed at |
|---|---|---|---|---|
| Ray Davis | `player_year` 2026 | `shmuel256` | `plehv79` | 2026-09-16 **09:01:52** UTC |
| Tre Tucker | `player_year` 2026 | `shmuel256` | `AceMatthew` | 2026-09-16 **10:16:10** UTC |

Both crossings fall inside the 17 hours between the two builds. Both players are
2026 rows — an in-progress season — and neither has a transaction after
2026-09-09.

## Root cause

`src/lotg.py` builds a tenure ledger from the add/drop, trade and draft events,
then ranks teams by how long each held the player:

* a tenure that has not ended has no end date, so it was measured to
  `datetime.now(timezone.utc)` (`_now_dt`, four readers);
* `tenure_inseason_time_team_fy` accumulates the part of each tenure inside the
  fantasy year's in-season window (Sept 1 → Feb 1), and `Top Team` is
  `max(...)` over it — as is `Top team` on `player_all_time`, via
  `tenure_inseason_time_team_all`.

So for the CURRENT season the current holder's total grows in real time while
every closed spell is fixed, and the answer flips the moment the two cross. Both
rows here are the same shape: `shmuel256` held the player from the window opening
until he dropped him on 2026-09-07, and the 2026-09-09 waiver run gave him to the
team that has held him since.

```
Ray Davis   shmuel256  Sep 1 00:00:00 → Sep  7 13:43:09   = 6d 13:43:09  (fixed)
            plehv79    Sep 9 19:18:43 → now               = 6d 06:19:17 at the build
                                                            6d 23:16:17 at the rebuild
Tre Tucker  shmuel256  Sep 1 00:00:00 → Sep  7 13:44:57   = 6d 13:44:57  (fixed)
            AceMatthew Sep 9 20:31:13 → now               = 6d 05:06:47 / 6d 22:03:47
```

This is the same class of defect as the `_has_played_week` gate added after the
2026-09-02 run (Mason Taylor, 25 flipped rows): ownership ranked on a window whose
far edge is an accident of when the build ran. That fix moved the NEAR edge of the
problem; this is the far one.

## How the rows were identified

The health email's artifact (`weekly-health-9`) could not be downloaded in this
session — the egress policy denies `productionresultssa1.blob.core.windows.net`,
so both the GitHub API redirect and the direct blob URL fail with a 403 CONNECT.
The two rows were recovered instead by rebuilding the FY2026 in-season ownership
ledger from `exports/snapshot/season_2026` (rosters rolled back through the 120
completed transactions to the Sept 1 window opening, pid-exact) and evaluating the
argmax at each build's clock.

That model is validated rather than assumed: of the twelve 2026 players who were
on more than one roster inside the window, it reproduces the shipped `Top Team`
for **every one of the nine** that the build ranks on the in-season ledger, and the
two it disagrees with (Jalen Royals, Kyle Williams) are exactly the two with no
played 2026 week, which `_has_played_week` sends to the full-FY ledger instead.
Scanning that model over the 17-hour window returns **exactly two** flips — the two
the email reported, and no others.

## The fix (this PR)

`_tenure_as_of` replaces the wall clock for open tenures with one that advances
with the data:

* the completion cutoff of the most recent fantasy week whose games are final
  (`_week_complete_cutoff`, Tuesday 08:00 UTC — pure calendar arithmetic, so two
  builds inside one fantasy week agree); or
* the latest tenure event on record when that is later — the offseason, where no
  week has been final since January but roster moves keep happening.

Never ahead of `now`, and with neither available it falls back to the wall clock,
i.e. the old behaviour. For both builds above it resolves to 2026-09-15 14:23:21
UTC (the last transaction either could see), so both rank `shmuel256` — which is
what the committed exports already ship, so no shipped value changes on this data.
The ranking still moves, on the football calendar: `plehv79` takes Ray Davis's 2026
`Top Team` once week 2 is final.

## What else was checked

* **Completed seasons are unaffected, and measured to be.** A local rebuild ~23 h
  after the committed one reproduces `Top Team`, `Last team` and `Number of teams`
  exactly across all 1,859 player-seasons ≤ 2025 (0 diffs). By construction: a past
  fantasy year's in-season window closed before `now`, so the clip is inert.
* **Nothing else was flagged.** Health run #9: 420/420 tests passed, no sheet lost
  or renamed a pinned column, no build errors, injury coverage 0 played-week gaps.
  The rest of the diff (62 rows) was attributed to the 79 NFLverse revisions.
* **It is about to get worse.** Scanning the same model forward, four more 2026
  rows cross on the wall clock within a week of the rebuild — Jonathon Brooks,
  Jonah Coleman and Javonte Williams on 2026-09-18, Dontayvion Wicks on 09-23 —
  none of which involve a roster move.

## Still outstanding

The mandatory 3-part audit's diff sweep needs the `LOTG_outputs` artifacts from
the post-merge CI build and its baseline run, which this session cannot download
for the reason above. `scripts/offline_build.py` is explicitly not a substitute
(it targets the 2025 league with KTC unreachable). The targeted ≤2025 tenure check
above is offline-build evidence for the blast radius of THIS change only, not the
audit.
