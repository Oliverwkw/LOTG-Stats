# Points above expectation — how the model was chosen

Follow-up to #389 (expected points from acquisition cost). Three new
`player_additions` columns, `lotg_support.acquisition`:

- **Price paid (FAAB)** — what the team gave up, in FAAB dollars (100 KTC = $1,
  the rate trades already use).
- **Points above expectation (total)** — X − Y over the weeks he was rostered.
- **Points above expectation (rate)** — the total ÷ weeks rostered.

X = his points for this team during the tenure, started and benched, position-
and season-scaled. Y = what an average player bought through the same channel at
the same price, at the same position, **actually scored** over the same weeks
since acquisition, assuming nobody is ever cut or traded (a peer's week off the
roster counts what he scored elsewhere; 0 if he did not play). User definition,
2026-10-03.

## Decisions (user, 2026-10-02 / 03)

| question | decision |
|---|---|
| comparable to what | same channel, same price, same position — never across channels |
| which weeks | the weeks he was rostered here; a never-rostered add is 0 (an earlier draft charged weeks to today — wrong) |
| peers who were cut | count what they scored after (not 0, and not dropped from the average) |
| rate | total ÷ weeks rostered (one expectation, not a second model); 0 with no rostered week, like the total |
| $0 waivers | pooled with free agency |
| 2021 vet draft | continues the startup board (#153+) |
| market-relative board | every pick is its draft-day KTC ÷ that draft day's anchor (2021: 5,324 … 2026: 5,442), priced at that ratio × the trade/draft date's anchor; the board half of the curve reads assets relative to the anchor too. Without it the 2021 1.06 priced $562 on 2020-11-29 (anchor 5,865): a board built at ~5,100 read as 0.86 of the anchor, vs ~0.98 on draft days. With it: $929, Luke's package for Cook $6,045 → Cook $5,930 (0.95 discount kept; 0.98 was considered) |
| thin-coverage line | KTC's daily data covers only ~195–200 league players mid-2021 to early 2022, under the 184–208 cutoff; the replacement line then comes from the nearest covered date as a fraction of the anchor |
| replacement (players) | a player is priced above the replacement line — the field's player at the league's last rostered spot that day: roster spots × 8 (taxi, IR not counted), less 8 from 2025 for the supertaxi long shot → 168 (2020), 184 (2021–23), 208 (2024), 200 (2025–26). Faded (softplus, scale = line price ÷ 2.5), not a hard floor: league opinion and KTC don't always agree. Today: Kupp $17 → ~$3.50, Hodgins $5 → ~$1.60, Herbert $1,005 → ~$968. Picks keep their board price. (User chose "A" over counting taxi as rostered, which would give 224 in 2024–26.) |
| market curve (final) | the field's 49th player = $1,000 each day (a mid first's average rank, 30–77 over 65 month-ends: mid firsts float); above, $1,000 × 2.619^(standing over the top 10) — best player averages $3,500; below, HALF the market effect: geometric mean of $1,000 × 8.26^(standing vs the 100th player) and the board curve rescaled to $1,000 at the anchor (user: "the market view matters lower down too", "half as strong"). Today: Badie $8, Hunter Henry $26, Tre' Harris $53, JCM $91, 2027 late 2nd $244, 2027 mid 1st $1,159, J. Taylor $1,468, 2027 1.01 $2,019, JSN / Josh Allen $3,650 (tied at KTC's cap) |
| top of the market (superseded) | **option D**: at or above a mid first, price = $1,000 × G^height, height = (KTC − mid first) ÷ (day's top-10 mean − mid first), G = 2.577 so the best player averages $3,500 over 73 month-ends 2020–26 (range $3,124–$4,616). User: "the best player is normally worth 3-4 FRPs", "not always 3,500 — sometimes more, sometimes less". KTC's 9,999 cap still bunches the top 3-4 on days they all sit there (2020 startup 1.01 vs 1.04 ≈ $580 apart, via the board's pooling) |
| traded picks | priced on the board, never by KTC: the slot's price, or the round's average when the slot is unset, × 0.95 per draft beyond the next (user: a small discount; the league's pick-for-pick trades fit 0.79 on 14 cross-year deals, bootstrap 80% 0.59–1.00, mostly draft-day swaps — rejected as far too steep). Replaces the KTC estimate for the price; the estimate stays in the trades sheet's KTC columns |
| price scale (supersedes the two rows below) | **option B, the money curve**: KTC only places an asset on the rookie draft board; dollars rise exponentially up the board, 4.08 = its KTC/100, a mid first = $1,000, KTC/100 below the 4.08, the 1.01→1.02 step above the rookie 1.01. Trades sum dollars (FAAB as dollars) and split by dollars; rookie picks 75% pooled / 25% own class (own class alone swung a 1.04 $476–$1,528). Fixes both the depth tax (Cook $101) and flat face value (Skattebo $199 > Jefferson $183) — "FAAB scales logarithmically with player value" (user) |
| trade price (superseded) | the sent side at face value, split by KTC share — no depth tax. The tax is `KTC value difference`'s fairness comparison (how KTC judges a trade), not a per-asset price: Luke's 12-asset package (five firsts) for Dalvin Cook kept 31% of its KTC under it and priced Cook at $101; untaxed ≈ $329. Overrules the slightly better-calibrated taxed split on principle. |
| reliance on KTC | only where unavoidable: trade prices, and the FAAB display of draft slots |
| rookie round-5 picks (5.0X FAAB buys) | locked at $20 (not the 2020 startup's real round 5) |
| draft slot price | draft-day KTC vs overall pick, isotonic (an earlier pick never costs less); not the leave-one-out pick-adjustment baseline, which priced the 2020 1.04 (Cook) above the 1.01 (CMC) |

## Evidence (prototype on the committed exports, 2020 – 2026 wk3)

Rebuilt week-by-week X matched the build's rostered points on all 1,971
additions; the never-cut series equals X on all 22,101 held weeks.

**Trade split** (trade rows, 5-fold grouped CV; calibration = n-weighted RMS of
mean X−Y over price quintile × elapsed band):

| split of the sent side's KTC (prototype) | MAE | calibration | Spearman |
|---|---|---|---|
| depth-taxed share (first choice, overruled) | 115.2 | **12.7** | 0.553 |
| Shapley over the depth-taxed value | 116.9 | 20.0 | 0.567 |
| plain KTC share | 117.7 | 25.4 | 0.565 |
| **plain KTC share of the untaxed sent total (chosen)** | 117.0 | 17.5 | 0.558 |
| equal split | 121.5 | 19.6 | 0.511 |
| no split (whole package per player) | 122.0 | 23.9 | 0.489 |
| *player's own KTC (market value, not price)* | *102.6* | *35.0* | *0.631* |

**Expectation model** (all channels, grouped CV / season holdout):

| model | calibration (ch × price × elapsed) | season holdout | note |
|---|---|---|---|
| channel × week only | 77 | 98 | price matters |
| nonparametric cells | 16.1 | 67.7 | thin cells |
| spline, extended as fitted | 13.3 | 18.2 | tail explodes (a 1.01 "eventually" 8,600) |
| spline + constrained price ramps | 13.9 | 16.9 | worst wrong-way price bump < 2 pts |
| plain log-price (no ramps) | 24.4 | 26.0 | monotone but miscalibrated |

Position is essential (calibration by channel × position 3.3 with it, 33.5
without). An era trend and acquisition timing did not help out of sample.

**Rejected Y definitions:** counting peers at 0 after they were cut made long
holds win by construction (corr of X−Y with weeks held 0.71); a per-held-week
rate fitted only on weeks players were still held penalised long holds of decent
players (late weeks averaged over the survivors). The never-cut Y avoids both:
corr 0.43 with weeks held, which is the intended reward for keeping a player who
keeps producing.

## Known limits

- The model refits every build; every row moves slightly each week
  (`volatile_columns`).
- League totals are positive (teams keep players who outperform); the rate
  averages near 0 on short holds.
- A peer's off-roster weeks need nflverse; 5 of 1,805 scoring player-seasons
  had no nflverse games in the prototype (name ambiguity — the build bridges by
  Sleeper id).
- Late-2020 trades of 2021+ picks predate KTC's pick quotes. An unquoted pick
  (sent or received) is estimated from the same pick one to three classes later at the
  same lead time before its draft, averaged (user, 2026-10-03; each estimate is
  logged as `pick KTC estimated: …`). Branch run 37148919888 before this: 9
  rows on 5 trade sides unpriced, all such picks. The margin guard checks the
  values the build exports, which now carry the same estimate: the trades
  sheet used to leave those picks out of its KTC columns entirely (user:
  extend the estimate there too).
