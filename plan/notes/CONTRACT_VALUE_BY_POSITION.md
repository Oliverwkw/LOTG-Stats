# Does a big NFL contract mean immediate fantasy improvement? By position

**Question.** How much is a big real-world contract an indication of *immediate*
improved fantasy success in the near term (the next two seasons), split by
position?

**Short answer: as a predictor of improvement, almost none — but as a predictor
of not collapsing, quite a lot.** Big-contract players score *fewer* fantasy
points after signing than before, at every position. What the contract buys you
is relative: against players who put up the same numbers last season and did not
get paid, signers deliver **+18% to +25% more fantasy points over the next two
seasons**, and most of that edge is *availability and role*, not a better per-game
player. The edge is clearest at **WR and TE**, largest in raw points at **QB**,
and weakest and least stable at **RB**.

This is not an abstract question for this league: 39 of the 40 top-five deals
signed in 2024 and 2025 have been on an LOTG roster.

---

## The two numbers, and why only one of them means anything

Top-five deals at each position, 2011-2024 signings, league scoring, season
fantasy points (regular season):

**Raw — signers against their own prior season (n=261 with a baseline):**

| position | prior season | year Y | year Y+1 | change Y | change Y+1 | beat prior year in Y |
|---|---|---|---|---|---|---|
| QB | 265.0 | 235.5 | 226.8 | **−29.5** | **−38.2** | 39% |
| RB | 228.2 | 175.6 | 151.0 | **−52.6** | **−77.2** | 26% |
| WR | 244.1 | 214.4 | 198.0 | **−29.7** | **−46.1** | 39% |
| TE | 145.5 | 133.9 | 107.4 | **−11.6** | **−38.1** | 46% |

Every position goes down. Roughly three in five signers fail to match their own
prior season in year one, and it gets worse in year two. Taken alone this says
"a big contract is a sell signal", and that reading is wrong — the contract
arrives *because* of a career year, so this table is mostly regression to the
mean plus aging, and any player coming off that season would have declined.

**Matched — the same signers against comparable players who did not get paid**
(same position, same season, prior-season points within 0.25 sd, age within 2
years, up to 5 controls each):

| position | n | signer, 2 seasons | control, 2 seasons | gap | vs control | p | q |
|---|---|---|---|---|---|---|---|
| QB | 47 | 458.5 | 381.9 | **+76.6** | **+20.0%** | 0.010 | 0.057 |
| WR | 50 | 392.2 | 323.0 | **+69.2** | **+21.4%** | 0.004 | 0.057 |
| RB | 45 | 314.6 | 266.4 | **+48.2** | **+18.1%** | 0.083 | 0.157 |
| TE | 48 | 223.2 | 178.6 | **+44.6** | **+25.0%** | 0.018 | 0.072 |

`q` is a Benjamini-Hochberg q-value over the whole 36-test family (4 positions ×
9 outcomes) — no single row's p-value should be quoted on its own. On that
standard, QB / WR / TE clear a 10% false-discovery rate and **RB does not**.

So the honest phrasing of "how much": a big contract at WR, TE or QB is worth
about **a fifth of a season's production over two years, relative to an
identical-looking player who didn't sign one** — and it is still consistent with
that player scoring less than he did last year.

---

## Per position

Ordered by how much the contract actually tells you.

### WR — the most reliable signal, and the only one that survives into year two as *rate*

+69 points over two seasons (+21%), the lowest p-value in the table, positive in
79% of the fourteen signing classes. Year Y is a role story (+1.5 games,
+39 points); year Y+1 is the one place where a signer is genuinely a *better*
per-game player than his match (**+2.05 ppg, p=0.008**), i.e. the offense has
been rebuilt around him. Startable-rate (top-24) also moves: 58% vs 40% in Y.
The top-two deals at the position are worth roughly double the 3-5 deals
(+99 vs +52), and the second tier (ranks 6-10) is worth nothing (+15, p=0.52).

### QB — the biggest raw gap, but it is bought playing time, not better play

+77 points over two seasons (+20%), and almost all of it is **games**: +2.2 in Y
and +2.4 in Y+1, both significant, while the rate edge is +1.9 ppg in Y and
**zero in Y+1** (+0.18, p=0.83). A paid quarterback is a starter for two years;
a comparable unpaid one is a bridge who gets benched. Notably the *startable*
rate (top-12 QB) does **not** move (45% vs 37% in Y, p=0.44) — this is
superflex-relevant: the contract buys you a QB2 who keeps taking snaps, not a
QB1 finish. Dose-response is flat inside the top five, and the second tier
(6-10) is worth nothing (+28, p=0.45).

### TE — the biggest gap *relative to what the position produces*

+45 points over two seasons on a base of 179 — **+25%, the largest proportional
edge of any position**, and the only position where the rate edge is positive in
both years (+1.09 and +1.43 ppg). TEs are also the position where the raw
before/after looks least damning (−11.6 in Y) simply because they had less to
give back. Same shape as WR at the tier level: nothing left by ranks 6-10 (+9,
p=0.61).

### RB — the weakest and least stable, and the position where the raw decline is brutal

+48 points over two seasons (+18%) but **p=0.083, q=0.16** — it does not clear
the family-wise bar, and the signing-year breakdown swings from +284 (2024) to
−175 (2022). No component is individually significant: not games (+1.3, p=0.12),
not rate (+0.94 ppg, p=0.26). Meanwhile the raw decline is by far the worst of
any position (−53 in year Y, −77 in year Y+1; only 26% beat their prior season).
The one RB-specific oddity that *is* strong: the second tier of RB deals (ranks
6-10) carries **+62, p=0.003** — bigger than the top five — which is the opposite
of every other position and reads as "the RB market pays its very best players
right before the cliff, and pays its useful starters about right."

---

## What the contract actually buys: role, not a better player

Signer-minus-control, both outcome years:

| position | games Y | games Y+1 | ppg Y | ppg Y+1 |
|---|---|---|---|---|
| QB | **+2.23** (p=0.009) | **+2.38** (p=0.011) | +1.87 (p=0.028) | +0.18 (p=0.83) |
| RB | +1.26 (p=0.12) | +0.89 (p=0.34) | +0.94 (p=0.26) | +1.37 (p=0.17) |
| WR | +1.50 (p=0.034) | +0.73 (p=0.36) | +1.13 (p=0.10) | **+2.05** (p=0.008) |
| TE | **+2.16** (p=0.005) | +0.90 (p=0.34) | +1.09 (p=0.032) | +1.43 (p=0.028) |

The strongest, most consistent effects are in the games column. That is the
mechanism to keep in mind when using this: a big contract is mostly evidence
that a team has committed the snaps, the targets and the goal-line work to this
player and will keep doing so through a bad stretch. It is much weaker evidence
that he is about to be better on a per-play basis, and at QB in year two it is
no evidence at all.

The same thing in the plainest form — share who beat their own prior season:

| position | signer, Y | control, Y | signer, Y+1 | control, Y+1 |
|---|---|---|---|---|
| QB | 45% | 30% | 43% | 15% |
| RB | 31% | 27% | 31% | 9% |
| WR | 46% | 12% | 34% | 14% |
| TE | 52% | 21% | 40% | 15% |

Even the signers mostly decline. They just decline far less often than the
players they are matched against, and the difference widens in year two.

---

## Does a bigger deal say more?

Two-year gap by rank within the position-year:

| position | ranks 1-2 | ranks 3-5 | ranks 6-10 |
|---|---|---|---|
| QB | +67 | +81 | +28 (p=0.45) |
| RB | +82 | +35 | +62 (p=0.003) |
| WR | +99 | +52 | +15 (p=0.52) |
| TE | +40 | +46 | +9 (p=0.61) |

At WR and RB the very top of the market carries the most information. At QB and
TE it is flat inside the top five. Below the top five the signal disappears at
every position except RB. **A "big" contract has to be genuinely top-of-market
for its position to mean anything** — the eighth-largest WR deal of a year tells
you nothing.

---

## Sensitivity — the answer does not depend on the choices

Two-year gap, every spec run:

| spec | QB | RB | WR | TE |
|---|---|---|---|---|
| primary | +77 (n=47, p=0.010) | +48 (n=45, p=0.083) | +69 (n=50, p=0.004) | +45 (n=48, p=0.018) |
| no age caliper | +37 (n=64, p=0.112) | +32 (n=55, p=0.164) | +60 (n=58, p=0.008) | +34 (n=60, p=0.030) |
| caliper 0.5 sd | +71 (n=59, p=0.012) | +31 (n=55, p=0.214) | +70 (n=56, p=0.002) | +34 (n=54, p=0.071) |
| k=10 controls | +77 (n=47, p=0.010) | +51 (n=45, p=0.064) | +72 (n=50, p=0.003) | +45 (n=48, p=0.018) |
| multi-year deals only (≥3y) | +91 (n=40, p=0.005) | +63 (n=34, p=0.024) | +69 (n=41, p=0.009) | +51 (n=38, p=0.015) |
| top 3 only | +108 (n=26, p=0.007) | +56 (n=23, p=0.124) | +86 (n=30, p=0.002) | +40 (n=27, p=0.159) |
| ranks 6-10 | +28 (n=30, p=0.453) | +62 (n=63, p=0.003) | +15 (n=57, p=0.518) | +9 (n=60, p=0.608) |
| 2018+ signings only | +109 (n=24, p=0.012) | +52 (n=20, p=0.306) | +33 (n=20, p=0.427) | +58 (n=22, p=0.024)  |
| standard PPR scoring | +85 (n=48, p=0.006) | +47 (n=47, p=0.070) | +69 (n=50, p=0.004) | +49 (n=47, p=0.012) |
| baseline ≥10 games | +67 (n=36, p=0.068) | +44 (n=45, p=0.110) | +68 (n=44, p=0.006) | +41 (n=44, p=0.030) |
| controls exclude top 5 only | +75 (n=47, p=0.009) | +47 (n=48, p=0.063) | +67 (n=51, p=0.003) | +49 (n=53, p=0.005) |

The gap is positive in every position under every spec. Two readings worth
pulling out:

* **Dropping one-year deals makes it stronger everywhere** (+91/+63/+69/+51).
  Franchise tags and prove-it years clear the money bar while being the opposite
  of a long-term commitment; when the team actually commits years, the signal
  gets cleaner. This is the single most useful refinement in the table.
* **Age matching matters and cuts both ways.** Without it the gap roughly halves
  at QB and RB, because the untouched comparison players at the same production
  level skew younger (still on rookie deals) and improve on their own. With it,
  the comparison is like-for-like but 30% of signings drop out.

---

## Stability: the pooled number is not carried by one class

Two-year gap by signing year (n is 3-5 per cell, so read the sign, not the size):

| year | QB | RB | TE | WR |
|---|---|---|---|---|
| 2011 | −0.9 | +171.8 | +1.1 | +49.1 |
| 2012 | +33.5 | +66.0 | −79.7 | +63.0 |
| 2013 | +28.9 | −99.7 | +97.1 | +20.2 |
| 2014 | −96.4 | +2.3 | +43.5 | +68.5 |
| 2015 | +304.8 | +165.5 | +51.1 | +99.3 |
| 2016 | +115.7 | +28.1 | +113.3 | +174.9 |
| 2017 | −33.5 | +43.7 | −47.1 | +160.4 |
| 2018 | +154.0 | −157.0 | +164.4 | −1.6 |
| 2019 | +76.6 | +39.3 | +141.6 | −75.4 |
| 2020 | +276.9 | +172.7 | −28.8 | +116.4 |
| 2021 | +46.2 | −11.1 | +32.7 | +58.0 |
| 2022 | +93.2 | −174.9 | −61.6 | +255.5 |
| 2023 | +42.7 | +247.9 | +73.2 | +55.0 |
| 2024 | +88.6 | +283.7 | +82.9 | −145.8 |
| **positive share** | **79%** | **71%** | **71%** | **79%** |

No position is carried by a single class, but no position is close to reliable
either: a manager acting on this in any one offseason is playing a 70-80% coin.

---

## Follow-up: FPTS per $1M per year — computable, and mostly not usable

Yes, it can be computed, three ways, all from the same contracts file. Every
contract row carries the player's whole career cap table (`cols`), so alongside
APY there is **what he was actually charged against the cap that season**
(`cap_number`), his share of that year's cap (`cap_percent`), and the cash he
banked (`cash_paid`). 91% of fantasy-relevant player-seasons 2011-2025 carry
one. The three denominators rank players almost identically (ρ = 0.93-0.98), so
the choice between them is not where the risk lives.

Median points per $1M of cap hit, and the same with inflation removed:

| position | n | FPTS per $1M | FPTS per 1% of cap | mean/median |
|---|---|---|---|---|
| QB | 1,066 | 15.4 | 27.5 | 2.59 |
| RB | 1,967 | 50.1 | 90.5 | 1.65 |
| TE | 1,742 | 22.7 | 42.2 | 1.94 |
| WR | 2,991 | 37.1 | 68.5 | 1.80 |

**Four things break it**, in descending order of severity:

1. **Raw dollars are not comparable across seasons.** The median fell from 48.1
   FPTS/$1M in 2011 to 20.4 in 2025 — **−58%**, entirely cap inflation. The same
   series measured per 1% of the cap is flat (58.2 → 59.0, **+1%**). Any ranking
   that pools seasons in dollars is ranking by year. Use `points_per_cap_pct`.
2. **It is mostly a rookie-contract detector.** 75-91% of the top decile of
   FPTS/$1M is a season played on a draft-slotted deal. Median RB on a rookie
   contract: 63.5, versus 34.0 for veterans — on *half* the points (43.4 vs
   81.2), purely because the denominator is a third of the size.
3. **The ratio is far noisier than either of its parts.** Year-over-year rank
   correlation, within position and season:

   | metric | QB | RB | WR | TE |
   |---|---|---|---|---|
   | cap hit | 0.83 | 0.74 | 0.79 | 0.82 |
   | fantasy points | 0.71 | 0.64 | 0.70 | 0.70 |
   | **FPTS per 1% of cap** | **0.34** | **0.41** | **0.44** | **0.40** |

   Both inputs persist at 0.64-0.83; the ratio of them persists at 0.34-0.44.
   Worse, inside the big-contract cohort — where cost is roughly held fixed —
   year Y efficiency predicts year Y+1 efficiency at **+0.24 / +0.13 / +0.01 /
   +0.34** (QB/RB/WR/TE) while points alone predict points at +0.28 / +0.30 /
   +0.39 / +0.57. On a single signing it is close to a coin flip.
4. **Cross-position comparison measures the market, not value.** RB 90.5 points
   per 1% of cap against QB 27.5 does not mean RBs are three times the fantasy
   bargain; it means the NFL pays quarterbacks for things fantasy does not score
   and has stopped paying running backs at all. Comparing positions on this
   metric mostly recovers the NFL's positional pay scale.

The failure mode is visible in the leaderboard. Best big deals by FPTS per $1M of
APY: Darren Sproles 2014 (45.3), Reggie Bush 2011 (43.3), Martellus Bennett 2013
(38.3) — i.e. the *cheapest* deals that still cleared the top five at their
position. Worst: Jerick McKinnon 2018 and Dustin Keller 2013 at 0.0 (never
played a snap on the deal), then Brandon Aiyuk 2024 (1.0) and Deshaun Watson 2022
(1.8). It ranks contracts by size with production as a tiebreak.

**Where it is usable**: as a descriptive, *within one position and one season*,
on cap share rather than dollars, with rookie deals separated out — "who gave
this league the most fantasy points per unit of NFL money in 2024". Not as a
cross-era, cross-position, or single-signing judgement.

**What to use instead** for "was this contract good for fantasy": points above a
positional replacement level per 1% of cap (which removes the cheap-backup
inflation), or the matched-control gap in the body of this note, which asks the
question the ratio is trying to ask but holds prior production constant instead
of dividing by money.

```bash
python scripts/contract_study.py value      # all four diagnostics above
```

## Method

* **Contracts**: nflverse's republication of Over The Cap's `historical_contracts`.
  Veteran deals only (a contract signed in the player's draft year is slotted by
  draft position and carries no information), one row per player-year keeping the
  larger deal, ranked on **APY as a share of that year's salary cap** *within
  position and signing year* — the fifth-biggest QB deal is ~15% of the cap and
  the fifth-biggest RB deal ~5%, so "big" is only meaningful against the
  position's own market. "Big" = top five at the position that year.
* **Production**: player-season fantasy points rebuilt from the build's own
  nflverse weekly stats, regular season only, **scored with this league's
  settings** (`contracts.lotg_points`). Season `Y` is the first season on the
  deal; `Y+1` the second; the baseline is season `Y−1`, requiring ≥6 games. A
  season a player never played is a real zero for points (that is what a roster
  got) but contributes no points-per-game.
* **Comparison**: each signer is matched to up to 5 non-signers of the same
  position and season whose prior-season points are within 0.25 sd of his and
  whose age is within 2 years, drawn from a pool that excludes anyone who signed
  a top-15 deal at his own position that year. The statistic is the paired
  signer-minus-control gap, tested with a deterministic two-sided sign-flip
  randomisation test (20,000 draws) and reported with a BH q-value across the
  whole family.

Everything above is `lib/lotg_support/contracts.py`; every choice named here is a
parameter with a default, which is what the sensitivity table varies.

## Guards

`python scripts/contract_study.py validate` — all three pass:

1. **The production panel reproduces a number the build already published.**
   Re-scoring nflverse weekly stats into league settings must reproduce
   `player_year["Points (full season)"]`: it matches **exactly for 77%** of
   joined player-seasons and **within 1 point for 92%**, 2021-2025. The residual
   is return specialists, whose return touchdowns the build scores from Sleeper's
   own keys and this reconstruction does not — so the guard asserts rates, not
   equality.
2. **Every top-five signing joins to a real player-season** (id join via
   `gsis_id`, not names).
3. **The matched cohorts start level** — signers and controls enter season Y
   within 5 points of each other in prior-season production (actual: ≤2 at every
   position; ages 29.2 vs 28.8, 26.8 vs 26.7, 27.2 vs 27.2, 27.4 vs 27.2).

## Caveats, classified

*(House rule: flag every borderline item, then classify it.)*

* **The elite are censored — `needs-human-judgment`, and it is the big one.**
  90 of 280 signings could not be matched: 19 had no qualifying prior season, and
  71 had nobody within the caliper. The unmatched skew *high* — mean prior season
  280 points vs 197 for the matched — because when a player puts up a top-three
  season at his position, **nobody comparable goes unpaid**, so no control
  exists. Christian McCaffrey (2020, 2024), Cooper Kupp (2022), CeeDee Lamb
  (2024), Joe Burrow (2023), Calvin Johnson (2012) and Drew Brees (2012) are all
  in that group. This answer is therefore about the payable middle and upper
  middle of the market; it cannot speak to what a Ja'Marr Chase extension
  predicts, and the raw table (where those players *are* included, and decline)
  is the only evidence on offer there.
* **"Contract" is not "new team" — `by-design`.** OTC's history does not separate
  an extension from free agency, and a change of team is not reliably recoverable
  from the `team` field, so both are pooled. An extension keeps the situation
  constant while free agency changes everything around the player; splitting them
  would probably sharpen the WR/TE result and is the obvious next question.
* **In-season extensions are stamped with the calendar year — `by-design`.** A
  handful of "year Y" outcomes were partly earned before the deal was signed.
  There is no signing date in the data to filter on; this pushes the year-Y gap
  toward zero, so the reported effect is if anything conservative.
* **Contract size is not modelled continuously — `by-design`.** The study asks
  "top five or not", with the rank tiers as the dose-response check. A regression
  of the gap on `apy_cap_pct` would use more of the data; the tier table already
  shows the relationship is not monotone (QB and TE are flat inside the top five).
* **Trades and holdouts are invisible — `by-design`.** A player who signs and is
  traded, or who sits out, is scored on whatever he produced. That is the right
  answer for a fantasy manager and the wrong one for "did the contract change the
  player".
* **The p-values are randomisation tests, not proof — `by-design`.** With 45-50
  pairs per position and a two-season outcome whose sd is 120-190 points, this
  study can see a 20% effect and cannot see a 5% one. Absence of a significant
  RB effect is not evidence that RB contracts mean nothing.
* **2026 signings cannot be evaluated yet — `by-design`.** `last_year` stops at
  the newest signing year with two completed seasons behind it (2024 as of this
  writing), so the 2025 class (Chase, Allen, Barkley, McBride, …) is excluded
  from every number above; its year Y is in the data, its Y+1 is the season in
  progress.
* **Coverage before 2011 thins out — `by-design`.** OTC's mid-tier coverage is
  sparse in the 2000s, so the study starts at 2011 signings. `--first-year`
  varies it; `2018+ only` is in the sensitivity table.
* **Games counts weeks with a stat line — `by-design`.** A healthy scratch, a
  benching and an injury are the same thing here, deliberately: they are the same
  thing to a fantasy roster.

## What this changes for a manager here

* Do not buy a player because he just got paid, expecting more than last year —
  at every position the central expectation is **less** than last year.
* Do treat a genuine top-of-market, multi-year deal as real evidence that the
  floor is safe for two seasons, especially at **WR and TE**, and as evidence of
  *snaps* rather than efficiency at **QB** (which in a superflex league is worth
  something in itself).
* Treat a big **RB** deal as close to no information, and note the second-tier
  RB deals carry more signal than the top ones.
* Deals outside the top five at a position, and one-year deals of any size,
  carry nothing.

## Reproduce

```bash
python scripts/contract_study.py study                 # the matched answer
python scripts/contract_study.py raw                   # signers vs themselves
python scripts/contract_study.py decompose             # games vs points per game
python scripts/contract_study.py dose                  # by size of deal
python scripts/contract_study.py years                 # by signing class
python scripts/contract_study.py study --min-years 3   # drop tags and prove-it years
python scripts/contract_study.py signings --year 2025  # who the big deals were
python scripts/contract_study.py validate              # the three guards
```

Needs `pyarrow` and network access on first run (the contracts file is cached
into `.cache/` alongside the build's other nflverse pulls). Nothing here reads or
writes `exports/`, `data/`, or any workflow.
