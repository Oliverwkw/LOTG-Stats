# What if shmuel256 had never traded Herbert for Lamar Jackson?

**Answer: he still wins 2025 — and, if anything, more comfortably.** Undoing the
trade turns his 12-3 regular season into 13-2, and he still takes the semifinal
and the final. In pure 2025 scoring the trade bought him very little: under the
headline model, reversing it is worth **+13.88 points across the regular season
and +42.34 across all 17 weeks**.

Reproduce with:

```
python scripts/whatif_herbert_trade_2025.py            # headline model
python scripts/whatif_herbert_trade_2025.py --scenarios # + two sensitivity runs
```

## The trade

2025-08-06, preseason — before a snap was played, so it colours the whole year.

| shmuel256 sent | shmuel256 received |
| --- | --- |
| Justin Herbert, Tre' Harris, $35 FAAB, 2026 1st, 2026 3rd, 2027 1st, 2027 2nd | Lamar Jackson, Chris Godwin |

The picks are all 2026/2027, so they cannot touch 2025. No later 2025
transaction moved any of the four players — the swap holds clean for all 17
weeks, on both sides.

## Method

Only two rosters change, so the other six teams' weekly scores are untouched.
What moves is shmuel256's and plehv79's weekly totals, the results of the games
those two played, and therefore the standings and the bracket.

The lineup model is documented in the script's module docstring. In short: it
replays each real lineup, swaps the traded players in and out, and resolves the
knock-on decisions with information the manager actually had (prior-form PPG,
plus the build's bye/injury/suspension flags) rather than with hindsight. An
arriving player is started only if his real manager started him that week —
which is why Herbert (started all 17 weeks) plays every week for shmuel256, and
why Lamar Jackson does not play for plehv79 in the weeks he was hurt.

Two sensitivity variants (`--scenarios`) bracket that judgement call:
`strict` (arrival only ever fills the exact slot the departing player used) and
`ceiling` (each score moves by the change in the roster's max-PF lineup — its
optimal_points() reproduces the build's Max PF column exactly for all 8 teams
across all 17 weeks of 2025). The three disagree on how many points shmuel256
gains or loses, and agree on every *result*:

| Model | shmuel256 PF change, wk 1-15 | Record | Title |
| --- | --: | :-: | --- |
| anchored (headline) | +13.88 | 13-2 | Shmuel256 |
| strict | −40.14 | 13-2 | Shmuel256 |
| ceiling | +16.70 | 13-2 | Shmuel256 |

`strict` is the interesting one: it forbids shmuel256 from starting Herbert in
the five weeks Lamar sat, so he *loses* 40 points on the year — and still goes
13-2, because the week-6 flip is driven mostly by plehv79 losing Herbert rather
than by shmuel256 gaining him.

## shmuel256, week by week (headline model)

| Wk | Opponent | Real PF | What-if PF | Δ | Opp PF | Real | What-if |
| --: | --- | --: | --: | --: | --: | :-: | :-: |
| 1 | LWebs53 | 173.88 | 172.44 | −1.44 | 95.98 | W | W |
| 2 | AceMatthew | 194.10 | 185.58 | −8.52 | 147.78 | W | W |
| 3 | BROsenzweig | 174.28 | 162.86 | −11.42 | 138.74 | W | W |
| 4 | stevenb123 | 174.48 | 176.32 | +1.84 | 158.78 | W | W |
| 5 | Oliverwkw | 195.32 | 184.04 | −11.28 | 113.82 | W | W |
| 6 | plehv79 | 119.94 | **133.80** | +13.86 | 114.38 | L | **W** |
| 7 | JacobRosenzweig | 134.62 | 158.48 | +23.86 | 132.66 | W | W |
| 8 | LWebs53 | 151.46 | 162.44 | +10.98 | 125.02 | W | W |
| 9 | AceMatthew | 185.50 | 187.64 | +2.14 | 188.76 | L | L |
| 10 | BROsenzweig | 181.24 | 180.30 | −0.94 | 108.56 | W | W |
| 11 | stevenb123 | 163.72 | 162.34 | −1.38 | 138.22 | W | W |
| 12 | Oliverwkw | 149.34 | 156.32 | +6.98 | 87.00 | W | W |
| 13 | plehv79 | 95.86 | 102.16 | +6.30 | 108.88 | L | L |
| 14 | JacobRosenzweig | 161.80 | 147.90 | −13.90 | 135.66 | W | W |
| 15 | LWebs53 | 216.22 | 213.02 | −3.20 | 131.90 | W | W |
| 16 (SF) | stevenb123 | 205.82 | 230.28 | +24.46 | 163.32 | W | W |
| 17 (F) | AceMatthew | 164.70 | 168.70 | +4.00 | 141.54 | W | W |

Exactly two head-to-head results change all season:

- **Week 6** — shmuel256 beats plehv79 133.80–114.38 instead of losing
  119.94–132.04. Both sides move: Herbert (18.76) replaces a benched, injured
  Lamar for shmuel256, and plehv79 loses Herbert from its superflex slot.
- **Week 8** — JacobRosenzweig beats plehv79 166.76–153.90 instead of losing by
  0.88. plehv79 had won that game on Herbert's 25.28; Lamar was hurt and would
  not have played.

## Standings and bracket

| | Real | What-if |
| --- | --- | --- |
| 1 | Shmuel256 12-3 | **Shmuel256 13-2** |
| 2 | AceMatthew 11-4 | AceMatthew 11-4 |
| 3 | BROsenzweig 11-4 | BROsenzweig 11-4 |
| 4 | stevenb123 8-7 | stevenb123 8-7 |
| 5 | plehv79 6-9 | JacobRosenzweig 6-9 |
| 6 | JacobRosenzweig 5-10 | LWebs53 4-11 |
| 7 | LWebs53 4-11 | plehv79 4-11 |
| 8 | Oliverwkw 3-12 | Oliverwkw 3-12 |

Seeding is unchanged at the top, so the bracket is unchanged:

- SF: Shmuel256 **230.28** def. stevenb123 163.32 (real: 205.82–163.32)
- SF: AceMatthew 180.86 def. BROsenzweig 111.88 (unchanged)
- F: Shmuel256 **168.70** def. AceMatthew 141.54 (real: 164.70–141.54)

## Why the trade did not decide the title

Lamar Jackson missed weeks 5–8 and week 17; Herbert started all 17. Over the
weeks both played, Lamar was the better fantasy asset (weeks 1–3 alone are worth
−21.4 to the what-if shmuel256). But the four weeks Lamar sat plus the week-16
gap (Herbert 29.2, Lamar 4.74) more than pay that back, and every one of the
weeks where Lamar beat Herbert was a game shmuel256 won comfortably anyway.

The margins were never in danger:

- Closest what-if game: week 9, a **1.12-point** loss to AceMatthew (it was a
  3.26-point loss in reality) — and even flipping it only makes him 14-1.
- Championship cushion: **+27.16** in the headline model, **+23.16** under the
  most conservative `strict` variant.

## Caveats

- **FAAB.** Reversing the trade leaves shmuel256 $35 richer and plehv79 $35
  poorer. plehv79 spent aggressively in week 1 ($120 on Jacory Croskey-Merritt,
  $46 each on Tahj Brooks and Tory Horton); with $35 less, one of those claims
  could plausibly have gone elsewhere. Waiver activity is held constant.
- **Second-order behaviour.** A manager holding a different roster makes
  different later trades, starts, and pickups. Nothing downstream is re-derived
  beyond the four players themselves.
- **Lineup judgement.** Steps 3–5 of the model are an assumption, not a fact.
  The `--scenarios` runs exist precisely to show the conclusion survives the
  alternatives.
