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
| reliance on KTC | only where unavoidable: trade prices, and the FAAB display of draft slots |

## Evidence (prototype on the committed exports, 2020 – 2026 wk3)

Rebuilt week-by-week X matched the build's rostered points on all 1,971
additions; the never-cut series equals X on all 22,101 held weeks.

**Trade split** (trade rows, 5-fold grouped CV; calibration = n-weighted RMS of
mean X−Y over price quintile × elapsed band):

| split of the sent side's depth-taxed KTC | MAE | calibration | Spearman |
|---|---|---|---|
| **depth-taxed share (chosen)** | 115.2 | **12.7** | 0.553 |
| Shapley over the depth-taxed value | 116.9 | 20.0 | 0.567 |
| plain KTC share | 117.7 | 25.4 | 0.565 |
| plain share of the untaxed sent total | 117.0 | 17.5 | 0.558 |
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
