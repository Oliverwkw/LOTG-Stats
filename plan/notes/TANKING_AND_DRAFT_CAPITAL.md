# Is blowing it all up for the first pick worth it? And what the 2026 rule change did to the answer

**Questions.** "Is blowing it all up to get the first pick ever worth it?" — then
"it's not just 1.01, it's also 2.01, 3.01. If you're already likely bottom four,
is pushing for the bottom 1-2 worth it?" — then "it's now Max PF for the bottom
four, does that change anything?" — then "compare Peter's and Luke's recent
teardowns to Oliver's, Jacob's and Steve's past tanks."

**Short answer.** The cliff is at the playoff line, not at the top of the draft.
Missing the playoffs is worth a large, real amount of draft capital (+416 points,
p=0.002). Moving from 4th-worst to worst is worth nothing detectable (−155,
p=0.53) — and the 2026 rule change made that worthless step cost five real
players instead of three meaningless losses. **Get to bottom four and stop.**

---

## 1. What the 1.01 has returned

`python scripts/draft_capital.py slots` / `haul`

| Draft | 1.01 | Pts added | Rank in class | Rank within its own R1 |
|---|---|---|---|---|
| 2021 | Najee Harris | 591.5 | 3rd of 32 | 2nd of 8 |
| 2022 | Breece Hall | 748.7 | **1st of 32** | 1st |
| 2023 | Bijan Robinson | 528.6 | 3rd of 32 | 2nd |
| 2024 | Marvin Harrison | 163.9 | 11th of 33 | **8th of 8** |
| 2025 | Ashton Jeanty | 191.9 | 2nd of 40 | 2nd |

Mean finish of the 1.01 inside its own first round: **3.0 of 8**. Once in five
drafts was it the best player in its class. The best asset of the class came from
outside 1.01 four times, and three of those from outside round one entirely
(Amon-Ra St. Brown 3.03, De'Von Achane 2.03, Bo Nix 3.01).

No champion has ever been carried by one. Najee was 11.2% of Steve's 2021 title
team's starter points; Marvin Harrison was **5.0%** of the 2024 one and not in
its top eight scorers.

## 2. The left column is the weak part of the case, not the strong part

Owning 1.01 means owning 2.01, 3.01 and 4.01. Every `x.01` ever made:

| | Picks | Combined | Concentration |
|---|---|---|---|
| **1.01** | Najee 591.5, Breece 748.7, Bijan 528.6, Harrison 163.9, Jeanty 191.9 | 2,224.6 | spread |
| **2.01** | Fields 0, Pickens 36.4, **Stroud 365.2**, Brooks 0, Egbuka 0 | 401.6 | **91% one pick** |
| **3.01** | Mac Jones 0, Dotson 106.6, Mingo 0, **Bo Nix 534.3**, Tre' Harris 0 | 640.9 | **83% one pick** |
| **4.01** | R. Moore 17.8, Ridder 13.8, Downs 79.1, Sanders 0, Blue 0 | 110.7 | — |

The whole non-1.01 left column across five drafts returned **1,153 points, 78% of
it from two picks**, and one of those two (2024 3.01, Bo Nix) was not the
slot-1 team's pick — Oliver acquired it in the teardown haul. Eleven of the
fifteen returned **zero**. Round means: R1 274, R2 97, R3 79, R4 17, with bust
rates 12% / 31% / 65% / 68%.

The slot-1 premium *within* a round is positive only in round 1 (+112.9 over
x.02-x.04); it is −108.5 in round 2 and −13.1 in round 4.

## 3. The decisive test

`python scripts/draft_capital.py cohorts`

Whole four-round haul per slot-draft, 2021-2025:

| Cohort | Mean | Median | Rate/start |
|---|---|---|---|
| Slots 1-2 — "pushed for it" | 602.8 | 634.1 | 8.66 |
| Slots 3-4 — already bottom four | 758.0 | 500.0 | 8.13 |
| Slots 5-8 — playoff teams | 264.4 | 210.1 | 5.83 |

* **Bottom four vs playoff teams: +416.03, d=+1.01, permutation p=0.002**
  (per-pick rate: +2.56, p=0.023). Real, and positive in all five drafts.
* **Slots 1-2 vs slots 3-4: −155.20, d=−0.29, p=0.527** (rate: +0.53, p=0.743).
  Nothing, and the sign is against the push. The per-draft breakdown flips
  three times, which is what a null looks like.

There *is* a slot gradient across the whole draft (pooled Spearman rho=−0.217,
p=0.008, n=160) — but it lives in the step across the playoff line, not inside
the bottom four.

## 4. What the market charges for the difference

Draft-day KTC for the full four-round haul: slot 1 **19,182**, slot 2 16,023,
slot 3 16,102, slot 4 15,120, slot 8 13,399. The slot-1 haul is priced **+3,080
over slot 3** and **+4,061 over slot 4** — the largest premium in the draft, for
a realised return the data cannot distinguish from zero.

The 1.01 is also the only first-round slot whose market value falls after you use
it: −4% at one year and −10% at two, against +27% / +31% for 1.07. Five of the
six 1.01s ever were running backs.

## 5. The rule change

`python scripts/draft_capital.py order --all`

Through the 2025 draft the bottom four picked in **reverse final placement**.
From the 2026 draft they pick in **ascending Max PF** — the roster's ceiling,
not its record. Verified: the 2026 slots are the 2025 non-playoff teams sorted by
Max PF, all four in order.

| 2025 team | Record / finish | Max PF | Placement rule | Max PF rule | Moved |
|---|---|---|---|---|---|
| **Peter** (plehv79) | 6-9, **5th** | 2312.36 | 1.04 | **1.01** | **+3** |
| **Luke** (LWebs53) | 4-11, 7th | 2618.40 | 1.02 | 1.02 | — |
| **Oliver** (Oliverwkw) | 3-12, **8th** | 2913.62 | **1.01** | 1.03 | **−2** |
| Jacob | 5-10, 6th | 3083.74 | 1.03 | 1.04 | −1 |

Run retroactively the rule moves the 1.01 in **four of six** drafts (2021, 2022,
2023, 2026). Jacob's 2022 1.01 — Breece Hall, the best pick in league history —
would have been Matt's.

Playoff teams (slots 1.05-1.08) are *not* modelled: their order is reverse
placement through the 2022 draft and swaps 3rd/4th from the 2023 draft on, with
no rule the data can pin down. `playoff_block()` returns what was observed
rather than guessing. No tanking question depends on it.

### What it changes

Max PF is the roster's *optimal* lineup, so it cannot be lowered by benching
people, losing games, or bad luck. The only way down is to have less scoring
talent.

`python scripts/draft_capital.py cost --draft 2026 --team Oliverwkw --regular-season`

**Oliver (1.03) chasing Peter's 1.01 — 2525.64 → 2041.12:**

| Drop | Max PF after | That player's 2025 points |
|---|---|---|
| De'Von Achane | 2366.14 | 289.6 |
| Bo Nix | 2242.10 | 257.6 |
| Jameson Williams | 2137.40 | 188.8 |
| Rashee Rice | 2045.20 | 148.1 |
| Chase Brown | 1950.20 | 199.6 |

**Five players, 1,083.7 points of production** — and four of them are the 2026
starting lineup the teardown was run to acquire. **Jacob** needs five too:
Smith-Njigba, Pickens, Javonte Williams, **Jeanty** and **Breece Hall** — the
2025 1.01 and the 2022 1.01. The tank is self-consuming: the price of the next
1.01 is the last two.

The **exchange rate is 1.88 points of production per 1 point of ceiling**,
because removing a starter only costs the optimal lineup his margin over the
next-best legal option. You must strip depth as well as stars. Both weeks bases
(full season and regular season only) agree on five players.

### Three new hazards

1. **A working rebuild is punished.** Jacob had the highest ceiling of the bottom
   four on the 4th-most points in the league, went 5-10 on bad luck, and got
   1.04. The stage where young talent starts scoring but the record lags is now
   the worst place in the league.
2. **Injuries decide draft order.** An injured star contributes nothing to the
   optimal lineup, so a hurt roster reads as a bad roster.
3. **The 1.01 lands on the team least able to use it** — by construction, the
   lowest ceiling in the league. Peter holds the 2026 1.01 and projects last.

### Three things that get better

1. **No more coin flips.** In 2023 Jacob went 3-12, won two toilet-bowl games
   (which counted toward placement through the 2024 draft, `src/lotg.py:14907`),
   and lost the 1.01 to a 5-10 team by **1.92 points of PF**. Impossible now: the
   2025 Max PF gaps were 237 / 247 / 211.
2. **You no longer have to lose games.** Peter went 6-9 and picked first.
3. **For a team already selling, the slot is free** — the sale lowers Max PF as a
   byproduct.

## 6. The five teardowns compared

`finish / ceiling-rank`, ceiling-rank 1 = worst roster in the league:

| | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|
| **Peter** | 4/5 | 3/5 | 7/**1** | 2/4 | 4/4 | 5/**1** |
| **Luke** | 3/7 | 2/8 | **1**/8 | **1**/8 | 6/3 | 7/2 |
| **Oliver** | 2/4 | 4/6 | 3/5 | 3/5 | 7/2 | 8/3 |
| **Jacob** | 7/**1** | 8/4 | 8/2 | 7/2 | 8/**1** | 6/4 |
| **Steve** | 8/2 | **1**/7 | 2/6 | 8/**1** | **1**/5 | 3/8 |

KTC ledger (`trades."KTC value difference at deal time"`, positive = won the
deal, depth-adjusted so a quantity package is taxed):

| Teardown | Trades | At deal | 1 year later |
|---|---|---|---|
| **Peter 2025** | 21 | **+11,688** | +6,218 |
| **Luke 2024** | 17 | +419 | +2,342 |
| **Luke 2025** | 15 | −415 | −2,223 |
| **Oliver 2024** | 17 | **−7,850** | −7,479 |
| **Oliver 2025** | 14 | −3,621 | −2,776 |
| **Jacob 2023** | 8 | +9,950 | +16,377 |
| **Steve 2020** | 3 | +1,328 | +2,627 |
| **Steve 2023** | 23 | −1,093 | +1,405 |

**Peter** — the first ceiling-era teardown, executed cleanly. Sold Bijan (the
1.01 he bought in 2023), Smith-Njigba, A.J. Brown, Lamar Jackson, Godwin,
Davante Adams. Ceiling 3158 → 2312 in one season. Best single-season trade
ledger on record. Got 1.01 without finishing last; under the old rule the same
season is 1.04.

**Luke** — sold a two-time champion core (Jefferson, Hill, Kelce, Keenan Allen,
Henry, Waddle, Mixon, Conner) in three days in May 2024, and sold into
**quality**: Jayden Daniels (432.0) and Brian Thomas (397.6) immediately, plus
the 2025 1.03 and 2.05. Roughly fair value at the time, positive a year on. The
risk is duration, not price — ceiling 3071 → 2903 → 2618 and still selling in
2026 (Nico Collins, Olave, Tua, Pacheco).

**Oliver** — ran the record-era playbook perfectly (3-12 twice) and the rule
moved underneath him. Worst KTC ledger in the data. His ceiling *rose* while his
record stayed 3-12, which is exactly what the new rule penalises. First-round
returns from the whole teardown: Worthy 184.7, McCarthy 32.1, Hunter 23.9,
Henderson 134.1, Golden 16.6, Judkins 0.0 — the one real hit was a third
(Bo Nix). In May 2026 he traded up 1.03 → 1.02, paying volume for the one step
this note says is worth nothing.

**Jacob** — the control group. Five bottom-two seasons, 22 picks, three 1.01s,
the best trade ledger over the full window, **zero playoff appearances in six
seasons**. Neither losses nor picks nor trade acumen is the binding constraint.

**Steve** — the only pattern that has won anything. Both tanks were genuinely bad
rosters (ceiling rank 2, then rank 1) but each lasted **one season**, and the
ceiling came back in a single offseason: 2442 → 2980, then 2677 → 3218. Two
championships. Made only 3 and 4 picks respectively. Under the new rule his 2020
tank yields 1.02, not 1.01 — Najee goes to Jacob.

## Verdict

The discriminator was never how hard you tanked or how well you traded. **It is
how fast the ceiling comes back** — one offseason for Steve, twice; never for
Jacob. The new rule prices draft position in the exact number you have to
reverse in order to use it, which means the moment a rebuild starts working it
costs you draft slots.

* Getting into the bottom four is worth +416 points and is still paid for in
  losses, which are cheap once you are eliminated.
* Moving up inside the bottom four now costs five real players for a return
  indistinguishable from zero. It was a bad bet under the old rule and is a
  worse one under this one.
* The one free version is a team already selling on the merits — Peter's 1.01
  cost him nothing extra. Take the slot as a byproduct, never as the reason.
* If your ceiling is climbing while your record lags (Jacob's exact position),
  you are in the worst spot the rule creates: no playoffs *and* the worst pick
  of the losers.

2026 forecast as the current scoreboard: Steve 28.0%, Oliver 11.6%, Jacob 4.7%,
Luke 0.3%, Peter 0.2%, against 12.5% uniform.

---

## Caveats, over-inclusively

Classified by-design / needs-human-judgment / defect.

- **[needs-human-judgment] The 2026 ordering rule is confirmed by its effect,
  not by a written rule.** `bottom_four_order` reproduces `picks."Original
  Team"` for all six drafts and the guard enforces it, but nothing in the repo
  states the rule, so how it handles ties, mid-season trades, or a low-ceiling
  team that sneaks into the playoffs is unknown. `MAX_PF_RULE_FROM_DRAFT` is a
  named constant so a future change is one edit.
- **[by-design] n is small.** Five completed drafts, 40 first-round picks, 10
  slot-drafts per cohort. The null result on the push means "no detectable
  difference", not "proven identical"; an effect of ~1 point per start would be
  invisible at this sample size — but so would the effect the tank is priced for.
- **[by-design] `Points added` is cumulative and stops at the pick's next
  transaction.** It is the only column that sums across a draft, so `haul_table`
  uses it, but it is tenure-biased and scores a flipped pick at 0. `RATE_METRIC`
  is the fair per-pick ranking and `slot_cohorts --metric rate` runs the same
  tests on it; both agree on both conclusions.
- **[by-design] The stripping cost removes players without replacement.** A real
  sale returns assets and waivers refill the roster, both of which raise Max PF
  back. Five players is a **floor**, and the module says so in `warnings`.
- **[by-design] Greedy removal is not a proven minimum set.** Read it as "about
  this many players, about this much production".
- **[by-design] Hindsight.** The stripping simulation knows each player's
  realised season; in-season you would be selling on expectation.
- **[by-design] Toilet-bowl reward picks (2.09) are excluded from the cohorts and
  counted.** They belong to a *non-playoff* team, so leaving them in files them
  under "playoff teams' slots" and inflates the bottom-four gap from +416.03 to
  +440.07. Kept in `rookie_picks` and `slot_table`, flagged in both paths.
- **[by-design] The playoff block's ordering is not modelled** — see §5.
- **[by-design] Build-volatile columns quoted:** Tanking, Draft Value, Future
  draft capital, and the KTC-difference family. None is load-bearing.
- **[by-design] KTC ledgers cover every trade in a season**, not only the
  teardown ones, and the 2-year horizon is structurally empty for 2025-2026
  trades.
- **[needs-human-judgment] "You weren't making the playoffs anyway" is a
  judgement, not a computed counterfactual.** A 5th-place team pushing to 8th
  does forfeit a small live playoff chance; `whatif.py` could price it.
- **[needs-human-judgment] Peter's teardown has zero realised return.** Every
  judgement about it is process and price, not outcome — Oliver's process looked
  defensible in mid-2024 too.
- **[possible drift, not this note's finding] The +5 semifinal bonus.**
  `plan/INQUIRY_PLAYBOOK.md` says it affects "exactly eight rows across
  2021-2025" and that 2020 is gated out. Reconciling starter points against `PF`
  finds **12 rows: 10 across 2021-2025 (2 per season, as the rule implies) and 2
  in 2020** (plehv79 and shmuel256, Week 15 Semifinal). Either the note is stale
  or the 2020 gate is not holding. It does not touch any number here — no pick
  or draft-order figure depends on it — but it wants a look.

## Reproduce

```bash
python scripts/draft_capital.py validate
python scripts/draft_capital.py haul
python scripts/draft_capital.py slots --statistic bust_rate
python scripts/draft_capital.py cohorts
python scripts/draft_capital.py cohorts --metric rate
python scripts/draft_capital.py order --all
python scripts/draft_capital.py cost --draft 2026 --team Oliverwkw --regular-season
python scripts/draft_capital.py cost --draft 2026 --team JacobRosenzweig --regular-season
python scripts/forecast.py --season 2026
python tests/test_draft_capital.py
```

The primitives this note needed did not exist before it and were added as
`lotg_support.draft_capital`, guarded by `check_max_pf_matches_build`,
`check_bottom_four_order_matches_picks` and `check_haul_table_reconciles`, with
`tests/test_draft_capital.py`. Nothing the build produces changed.
