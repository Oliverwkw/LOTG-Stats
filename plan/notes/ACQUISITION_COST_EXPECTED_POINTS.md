# Expected weekly points from acquisition cost and tenure

**Question.** Can we estimate the expected points of a player in a given week
from what his team gave up to get him — draft pick (startup/vet separate from
rookie), FAAB, or trade assets — plus how long he has been on that team?

**Answer.** Yes, and most of it already exists. The league already computes
`E[stat | draft slot]` for picks; that is exactly what the pick adjustment is.
The work is (a) putting the other two channels on the same price scale, (b)
deciding how a trade package's price splits across the players it brought back,
and (c) being honest that tenure is a selection variable, not a treatment.

This note is the design and the evidence for it. Nothing here has been built
yet; the last section lists the one primitive that is missing and the guard that
should back it.

---

## 1. The pick adjustment is already an expected-value model

`Pick-adjusted Difference in <stat>` on `picks` is

```
stat(this pick) − mean(stat over the comparison window around this slot)
```

with the window being the 3 neighbouring slots by overall draft position, plus a
synthetic 4th built from the two outer slots from pick 1.05 on (`src/lotg.py`
~10222). The subtracted term **is** `E[stat | slot]`, estimated by local
averaging rather than by fitting a curve. The exported column is the residual.

So the generalisation is not a new idea, it is the same idea with `slot`
replaced by a channel-agnostic price:

```
expected      = E[adjusted points | cost, channel, tenure]
residual      = actual − expected        ← the thing worth reporting
```

Keeping the local-averaging form (rather than jumping to OLS) also keeps the new
numbers commensurable with the pick-adjusted columns already in the sheets.

## 2. Startup/vet really must be separate — the data says so

The build already keeps the 2020 startup and the 2021 vet draft in their own
pick-adjustment universe (an 8-nearest-neighbour baseline, with the window
clamped at the startup/vet seam so the last startup pick and vet 1.01 never
enter each other's window). Pooling them destroys the signal:

| pool | n | corr(overall slot, `Avg PPG on team adjusted by position`) |
|---|---|---|
| all non-vet picks pooled | 290 | **−0.04** |
| rookie picks only (rounds 1–4) | 174 | **−0.38** |
| 2020 startup only (rounds 5–19) | 116 | −0.21 |

Rookie-only, the round means fall cleanly and monotonically:

| round | n | mean adj PPG on team |
|---|---|---|
| 1 | 47 | 13.09 |
| 2 | 45 | 11.04 |
| 3 | 44 | 8.97 |
| 4 | 38 | 7.88 |

A pooled model would have concluded draft slot does not predict production. It
does; the pooling was the bug. Any cost model inherits this rule.

## 3. One price scale across all three channels

KTC (superflex) is the common currency, and the build has already committed to
it. `lotg_support.ktc.asset_value_at()` prices a player, a draft pick, or — via
the build's conversion — FAAB, at any date.

| channel | cost at acquisition |
|---|---|
| rookie pick | KTC of the **pick slot** on draft day |
| startup / vet pick | no KTC pick quote exists — use the slot's own 8-nearest non-rookie baseline, as the build already does |
| FAAB / waiver | `$ bid × 100` KTC (the build's fixed rate) |
| free-agent add | genuinely **0** — keep these, they anchor the low end |
| trade | allocated share of the depth-adjusted **sent-side** KTC (§4) |

Three deliberate choices to carry forward, each of which should be a documented
parameter with a default rather than a constant:

- **Use the slot's price, not the player's.** `picks.KTC on draft day` is the
  *drafted player's* value, which is already post-selection — a 3rd-rounder who
  went on to be good was worth more on draft day partly because he was good.
  For a cost variable you want what the slot cost, which is
  `asset_value_at("2024 1.03", …)`. Using the player's KTC leaks outcome into
  the predictor (its correlation with production is +0.60, vs −0.38 for slot —
  that gap is mostly leakage, not skill).
- **FAAB → KTC = 100/$** is a chosen constant. The data-derived median from
  clean FAAB-for-asset trades was ~329; the build overrides to a flat 100 as the
  conservative call (`src/lotg.py` ~8960). A cost model inherits that choice and
  should report sensitivity across, say, 100 / 200 / 329.
- **Depth tax factor 0.6** (best asset full, each next × 0.6ⁱ) likewise.

Superflex is settled, not a judgement call: the league is superflex in every
season and the build always takes `sf_trade_value` (`src/lotg.py` ~8760). One
cosmetic snag — `ktc.build_index`'s own default is `value_col="trade_value"`
with a docstring saying "the user's league is 1QB". The build overrides it every
time so no shipped number is wrong, but a new caller that forgets to pass
`value_col` would silently get 1QB values and read QBs far too low.
**Classification: needs-human-judgment (stale default in a library the build
always overrides).**

## 4. Trades — the sticking point

### It is smaller than it looks

Across all 544 trade sides:

| received side | sides | share |
|---|---|---|
| exactly 1 player, no picks | 268 | 49% |
| 0 players (pick-only haul) | 127 | 23% |
| more than 1 player | 149 | 27% |

Half the trades need **no allocation at all** — the whole price attaches to the
one player who came back. The pick-only hauls are not a problem either; they are
a cost basis waiting to be inherited (§4.3). Genuine allocation is needed for
27% of sides.

The asset text is also well-structured, so parsing is not the hard part:

```
RECV: DJ Moore; James Robinson; 2022 2.07(T. Allgeier); 2023 2.08(S. LaPorta)
SENT: Joe Mixon; 2024 3.08(J. Burton)
```

Semicolon-separated; picks match `^\d{4}\s+\d+\.\d+\(`.

### The allocation rule

1. Price every asset on both sides at the deal date (KTC, superflex).
2. **Price paid** = depth-adjusted total of the *sent* side (the build's
   `_depth_adjusted_value`).
3. Allocate that price across *received* assets in proportion to each asset's
   own deal-date KTC share.
4. Received **picks absorb their share**. This is the load-bearing step: it
   stops a player carrying the whole bill for a package that also brought back
   draft capital.
5. One received player and no picks → full price, no allocation. Exact for 49%
   of sides.

Report the sensitivity rather than defending one rule — proportional share vs
winner-takes-all (whole price to the best received asset) vs equal split. If
they agree, say so; that is the strongest form the answer takes, and it matches
how `whatif.py` reports its three lineup models.

### 4.3 Cost basis has to chain

A received pick that later becomes a player should pass its allocated cost on to
that player, and a player who is re-traded carries a new cost basis from that
date. This is the same trap the playbook already flags for `picks`: every return
column stops at the pick's *next* transaction, so 2025 1.08 (Judkins) scores 0
despite actually becoming Zay Flowers. `analysis.timeline()` already merges
picks, adds/drops and trades into one chronological log per entity, so the chain
is walkable — it just has not been walked for this purpose.

### 4.4 What is actually missing

`trades` exports only the **side difference** (`KTC value difference at deal
time`, populated on 544/544 sides — coverage is not the issue). It does not
export per-asset values, and the difference cannot be decomposed: for a 1-for-1,
`sent = received − diff`, and `received` is the acquired player's own KTC, which
is not exported either.

So the missing primitive is a **per-asset deal-date price**. The build computes
exactly this internally (`_side_values` / `_depth_adjusted_value`, `src/lotg.py`
~8901) and simply discards the breakdown. An inquiry-side helper should reuse
`lotg_support.ktc` rather than reimplement it — a second implementation of a
build rule is a second answer to the same question.

Cost of doing so: `ktc.build_index` fetches per-player histories from
dynasty-daddy over the network (cached under `data/ktc_cache/`, which is not
committed; only the pre-2021 `data/ktc_backfill/` is). So this helper is not
purely offline on first run, unlike every other inquiry tool. That is a real
departure from the read-only-over-committed-data norm and should be a conscious
decision, not a side effect.

## 5. Tenure is a selection variable, not a treatment

`player_week.Number of weeks on team` is the ready-made regressor. Over 7,531
starter weeks the gradient is clean and monotonic:

| weeks on team | starter weeks | mean points |
|---|---|---|
| 1–4 | 1,004 | 14.05 |
| 5–8 | 913 | 14.04 |
| 9–17 | 1,716 | 14.59 |
| 18–34 | 2,142 | 15.11 |
| 35–51 | 1,019 | 15.94 |
| 52–85 | 663 | 16.37 |
| 86+ | 74 | 17.85 |

corr = 0.09; the spread is +3.8 PPG end to end.

**This is mostly survivorship, not development.** You keep good players and cut
bad ones, so long tenure is partly a *consequence* of scoring well. Which means
the right treatment depends on what the estimate is for:

- **Descriptive** ("what do players of this cost and tenure actually score") →
  include tenure.
- **A fair benchmark to judge a manager against** → exclude it, or the benchmark
  absorbs the manager's own retention skill and grades them against themselves.

Recommend fitting `E[pts | cost, channel]` first and reporting tenure as a
separate, explicitly-confounded term.

## 6. The survivorship trap in the target

This is the largest threat to the whole exercise and it is easy to walk into.

Of 516 non-vet picks:

- 160 name no player at all (unexercised future picks — correctly excluded)
- of the 356 made picks, 66 have no `Avg PPG on team`
- 143 made picks recorded **0 starts** before the drafted player's next
  transaction

So 44% of non-vet picks have no production row, and the missing share is *higher
in later rounds* (51% in round 1 rising to 60% in round 4). Fit on production
rows only and you are estimating `E[points | cost, the player survived]`, which
is biased **upward for cheap acquisitions** — precisely the comparison the whole
model exists to make.

Recommendation: model **rostered** weeks, not starter weeks, and let a
zero-production week be a zero. Better still, a two-part model —
`P(started | cost, tenure) × E[points | started, cost, tenure]` — because
acquisition cost plainly predicts both, and collapsing them hides which one is
moving. Report both the conditional and unconditional forms.

## 7. Proposed shape

An additive, inquiry-only module (`lib/lotg_support/acquisition.py`), per the
playbook's "when the helper you need does not exist — add it":

| function | returns |
|---|---|
| `asset_prices(season=None)` | per trade side, per asset, deal-date KTC |
| `acquisition_cost(...)` | one row per (player, team, acquisition event): `channel`, `cost_ktc`, `cost_native`, `acquired_on`, allocation method + share |
| `player_week_costed(...)` | `player_week` joined to the acquisition in force that week, with `weeks_on_team` |
| `expected_points(...)` | fitted baseline + residual |

`expected_points` should emit its residual under a name that matches the idiom
the sheets already speak — `Cost-adjusted Difference in <stat>`, mirroring
`Pick-adjusted Difference in <stat>` — so the output reads as a sibling of the
existing columns rather than a new vocabulary.

**The guard**, and the reason this is safe to trust: allocated per-asset prices
must reproduce the number the build already published. For every trade side,

```
depth_adjusted(received asset prices) − depth_adjusted(sent asset prices)
    == trades["KTC value difference at deal time"]
```

That is a `check_*` function plus a test over all 544 sides, tying the new
primitive to a build-computed number exactly as `check_identity` and
`check_max_pf` do. If it does not reconcile, the pricing is wrong and no
downstream expectation is worth quoting.

## 8. Borderline items, classified

Per the house rule — flagged rather than filtered.

| item | classification |
|---|---|
| Startup/vet pooled with rookie picks kills the slot signal (−0.04 vs −0.38) | **by-design** — the build already separates them; the model must too |
| `picks.KTC on draft day` is the player's value, not the slot's | **defect if used as cost** — outcome leakage; use the slot quote |
| 44% of non-vet picks have no production row, worse in late rounds | **needs-human-judgment** — drives the starter-weeks vs rostered-weeks choice |
| Tenure gradient is confounded by retention | **needs-human-judgment** — depends whether the estimate is descriptive or a benchmark |
| FAAB→KTC fixed at 100/$ (data-derived median ~329) | **by-design** — conservative build choice; make it a parameter and report sensitivity |
| Depth tax factor 0.6 | **by-design** — same treatment |
| 1,289 of 1,545 transactions have $0 FAAB | **by-design** — genuine zero cost, not missing data; keep them |
| `ktc.build_index` defaults to 1QB `trade_value` | **needs-human-judgment** — build always overrides; a new caller could silently get 1QB |
| Per-asset trade pricing needs a network fetch on first run | **needs-human-judgment** — departs from the offline-inquiry norm |
| 2020 has exports but no snapshot | **by-design** — trade asset resolution there comes from the ESPN backfill |

The `+5` semifinal home-field bonus does **not** apply here: it is baked into
team `PF`, not into player points, and this model is built on `player_week`.
