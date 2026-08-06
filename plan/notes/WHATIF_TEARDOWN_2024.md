# Could Oliverwkw have competed in 2024 without the teardown? Was the tank right?

**Question.** "If I hadn't made that massive CMC trade and the other teardown
trades a few years ago, could I have competed that year? Was the teardown + tank
the right choice?"

**Short answer.** You'd have been an 8-7 bubble team that misses the playoffs on
a points tiebreak in the median reading — not a contender. The direction was
right; the pricing was not. You sold quantity over quality, and the one pick in
the haul that was worth a star (2024 1.07 → Brock Bowers) you flipped six weeks
later for Jordan Addison. The buyer, shmuel256, turned McCaffrey into the
league's top scorer and the 2025 championship.

---

## The trades

Five moves make up the teardown, all in 2024 — four in the offseason, one at the
deadline. `python scripts/inquire.py timeline --team Oliverwkw --season 2024`.

| Date | Out | In | Txn id |
|---|---|---|---|
| 2024-04-30 | George Kittle, 2025 4.01, 2024 2.05 | Wan'Dale Robinson, 2024 2.03, 2024 2.08, $10 | `1090497154780581888` |
| 2024-05-07 | **McCaffrey, Kupp, Herbert, Kirk, Thielen**, 2024 4.04 | **15 picks** (1×1st, 2×2nd, 8×3rd in 2024; 2025 1.07, 2×2025 2nd; 2026 2.05, 4.07) | `1092268177528127488` |
| 2024-05-13 | Hopkins, Pittman, Pierce, 2025 3.08, 2025 4.05 | Michael Wilson, 2025 1.05, 2025 2.02 | `1095772841745821696` |
| 2024-07-13 | Ekeler, 2025 2.08, 2024 2.05 | 2024 2.02, 2024 4.02 | `1117973026936573952` |
| 2024-10-17 | Terry McLaurin, 2027 3rd, $6 | Jameson Williams, 2027 4th | `1152469543118536704` |

Rewinding only the headline trade is not the question asked — it leaves the rest
of the roster sold off. All five are rewound together:

```bash
python scripts/whatif.py --season 2024 --model all \
    --undo-trade-id 1090497154780581888 --undo-trade-id 1092268177528127488 \
    --undo-trade-id 1095772841745821696 --undo-trade-id 1117973026936573952 \
    --undo-trade-id 1152469543118536704
```

Guards pass first: real lineups legal under the 2024 template, `Max PF`
reproduced, and a no-move replay reproducing the built PF, bracket and champion.

## 1. Could you have competed in 2024?

Real: **3-12** regular season (5-12 with the toilet bracket), 7th, 1986.56 PF.

| Model | Oliverwkw | Seed | Champion |
|---|---|---|---|
| anchored | 3-12 → **8-7**, 2174.20 PF | **5th** — misses the 4th seed on the PF tiebreak | stevenb123 (unchanged) |
| strict | 3-12 → 3-12, 1907.66 PF | 8th | stevenb123 (unchanged) |
| ceiling | 3-12 → **8-7**, 2342.94 PF | **2nd** | **Oliverwkw** |

The models disagree on the champion, so both ends get reported.

**Read `strict` as an artefact, not a result.** Strict lets an arriving player
occupy only the slot the departing player vacated — and Oliverwkw's side of these
trades was almost entirely *picks*. There is no departing player to slot
McCaffrey into, so the returning stars mostly sit, and PF actually *falls*
(1986.56 → 1907.66) because Wan'Dale Robinson, Michael Wilson and Jameson
Williams leave with nothing replacing them. Strict is the right conservative
model for a player-for-player swap and the wrong one for a player-for-picks sale.

That leaves anchored and ceiling, and they agree on the record: **8-7**. In 2024
the 4th and last playoff seed was 8-7. So the honest answer is that not tearing
down would have left you *exactly on the bubble*, with the berth decided by
regular-season PF — which anchored says you lose (2174.20 against plehv79's
2287.86 and AceMatthew's 2334.52) and ceiling says you win, and then win the
whole thing.

**Why not more?** The assets you sold had a dreadful 2024 —
`python scripts/inquire.py rows player_year --where Year=2024 …`:

| Player | 2024 points | Weeks lost to injury |
|---|---|---|
| Christian McCaffrey | **47.8** | **12** |
| Christian Kirk | 70.9 | 8 |
| Austin Ekeler | 124.1 | 5 |
| Adam Thielen | 130.1 | 7 |
| DeAndre Hopkins | 146.0 | 1 |
| Michael Pittman | 152.6 | 1 |
| Cooper Kupp | 174.0 | 4 |
| George Kittle | 231.9 | 2 |
| Terry McLaurin | 247.6 | 0 |
| Justin Herbert | 253.4 (QB) | 0 |

The headline name in the headline trade produced **47.8 points**. Undoing the
McCaffrey trade *alone* moves you 3-12 → 5-10 — the other four trades are
collectively worth as much as the big one. Kittle, Herbert and McLaurin are what
the counterfactual actually runs on.

## 2. Was the teardown the right call?

### For

- **The roster was genuinely bad, not unlucky.** 2024 all-play win % 0.3277
  (2nd-lowest); Luck +0.13, i.e. neutral. `Max PF` 2841.62, 2nd-lowest in the
  league — the *ceiling* was near the bottom, not just the lineup calls.
- **It was executed, not half-done.** Highest Tanking (0.5748) and Draft Value
  (2.86) in the league, youngest roster (24.23), most picks made (12), highest
  offseason starter turnover (13). [All four are build-volatile columns.]
- **The one big hit was very big.** 2024 3.01 → **Bo Nix**: 534.3 points added,
  pick-adjusted +3404 KTC, and still the starting QB in 2026.
- **The 2025 1.05 line paid too.** From the Hopkins/Pittman trade: TreVeyon
  Henderson (134.1 points added), and that trade's 2025 2.02 (Colston Loveland)
  became Harold Fannin + Tetairoa McMillan in January 2026.
- **The 2026 starting ten it produced** — Nix, Achane, Chase Brown, Nico Collins,
  Rashee Rice, McMillan, Fannin, Breece Hall, Henderson, Purdy — is a
  contender's lineup, with the pivot back to buying already made (2027 and 2028
  firsts spent in July 2026 on Collins and Hall).

### Against

- **You sold into quantity.** Nine of the fifteen picks were 2024 thirds or the
  2025 1.07. Points added by every pick made directly from that haul:

  | Pick | Player | Points added |
  |---|---|---|
  | 2024 3.01 | Bo Nix | 534.3 |
  | 2024 3.04 | Troy Franklin | 98.4 |
  | 2024 3.02 | Michael Penix | 35.9 |
  | 2025 1.07 | Matthew Golden | 16.6 |
  | 2024 3.03 / 3.05 / 3.06 / 3.07 / 3.08 | Mitchell, Corum, Wright, Sinnott, Burton | **0.0 each** |
  | | **Total** | **685.2** |

  Take Nix out and the entire 15-pick haul returned 150.9 points. Five of the
  nine picks you actually used returned nothing at all.

  **`Points added` is cumulative, so rank on the rate columns, not this one.**
  It accrues over a player's whole tenure and stops at his next transaction, so
  it flatters whoever has been on the roster longest. The pick-adjusted rate is
  what compares two picks fairly, and it reorders them:

  | Pick | Player | /start | pos-adj | vs slot | Tenure |
  |---|---|---|---|---|---|
  | 2024 3.01 | Bo Nix | 18.42 | 15.28 | **+10.02** | 754d |
  | 2025 1.05 | TreVeyon Henderson | 14.90 | 14.36 | **+5.16** | 382d |
  | 2025 2.02 | Colston Loveland | 9.50 | 11.70 | +2.96 | 177d |
  | 2024 2.02 | Xavier Worthy | 10.86 | 11.46 | +2.72 | 703d |
  | 2025 1.07 | Matthew Golden | 8.30 | 9.01 | +1.21 | 382d |
  | 2024 2.03 | J.J. McCarthy | 10.71 | 8.88 | −0.80 | 754d |
  | 2025 1.02 | Travis Hunter | 7.97 | 8.64 | −2.94 | 382d |

  On cumulative points Worthy (184.7) looks like the second-best asset of the
  rebuild; on rate he is fourth, and Henderson is second in half the tenure.
- **The single clearest loss.** The 2024 1.07 in that haul became **Brock
  Bowers**. Six weeks later (2024-06-29) you flipped it, with 2026 2.05, 2026
  4.07 and 2025 4.06, for **Jordan Addison**. Bowers: 247.7 then 176.2. Addison:
  211.5 then 133.3, and off your starting lineup by 2026.
- **The second-clearest.** Kittle (231.9 points in 2024) bought the 2024 2.03,
  which became J.J. McCarthy — 3 starts, −0.80 vs slot.
- **What is *not* on this list.** Two conversions that the pick sheet scores as
  failures were wins once the asset is followed (see the caveat below):
  Judkins → Zay Flowers, and Loveland → Fannin + McMillan. There is no general
  "sold every maturing asset early" pattern; the damage is concentrated in the
  two conversions above.
- **It cost two seasons, not one.** 2025 was also 5-12 (8th).
- **The buyer cashed it.** McCaffrey scored **402.9 in 2025 — the highest of any
  player in the league** — for shmuel256, who won the title.

### The 2025 check

Bounded sensitivity run — hand McCaffrey and Kittle back for free in 2025, with
Oliverwkw *keeping* everything the teardown bought (Nix, Henderson, Hunter,
Golden). This is deliberately generous to the no-teardown case: no cost is paid.

```bash
python scripts/whatif.py --season 2025 --move '4034:8->7' --move '4217:8->7' --model all
```

| Model | Oliverwkw | Champion |
|---|---|---|
| anchored | 3-12 → 5-10 | shmuel256 → **stevenb123** |
| strict | 3-12 → 3-12 | shmuel256 → **stevenb123** |
| ceiling | 3-12 → 6-9 | shmuel256 (unchanged) |

The 4th seed in 2025 was 8-7. Even as a free gift those two could not have made
you competitive — but in two of three models they cost shmuel256 the
championship. **Those assets could not have won you 2025; they did win shmuel256
2025.** Since this run charges nothing for them, the real "no teardown" 2025 can
only be worse than the 5-10 shown.

### Verdict

Right direction, wrong price. Selling a 28-year-old McCaffrey off a bottom-two
roster is what that roster should do, and 2024 vindicated the timing brutally —
he played four weeks and scored 47.8. But the return was fifteen lottery tickets
where two or three real assets were available, and the one lottery ticket that
was a real asset (1.07 / Bowers) got spent on a WR3 before the season started.
The rebuild has still worked — the 2026 roster is the best you have fielded — but
Bo Nix is carrying almost all of it, and the counterfactual answer to "could I
have competed" is 8-7 and out on a tiebreak, which is the treadmill the teardown
existed to escape.

The mistakes are **narrower than the pick sheet first suggests**, though. Once
converted picks are priced by following the asset rather than by their `picks`
row, the losses reduce to two conversions — 1.07/Bowers → Addison, and
Kittle → the 2.03/McCarthy — plus ordinary draft variance on Golden and Hunter
(and Hunter is the *tank's* own pick, not the teardown's, which is the sharper
indictment of the second 5-12 season). Judkins → Flowers and
Loveland → Fannin + McMillan both went the other way. So the execution was
closer to average than the raw returns imply, and the case against the teardown
rests on its **structure** — fifteen tickets instead of two or three assets —
rather than on a pattern of bad follow-up trades.

---

## Caveats, over-inclusively

Classified by-design / needs-human-judgment / defect.

- **[needs-human-judgment] The counterfactual flatters the no-teardown case.**
  Undoing the trades leaves you holding **Jordan Addison** (211.5 points, 13
  starts) and **Xavier Worthy** (187.2, 12 starts) — both bought with picks from
  the very haul being rewound. So the 8-7 counterfactual keeps the stars *and*
  the players you only had because you sold them. A true "none of this happened"
  2024 is worse than 8-7, which strengthens the answer rather than weakening it.
- **[by-design] Second-order behaviour is held constant.** FAAB, waivers and
  in-season trades run exactly as they really did; a contending 2024 team would
  have spent differently. Draft picks are not re-drafted.
- **[defect in the reading, not the data] `picks` cannot price a pick that was
  traded**, and using it to judge a trade gets the answer backwards. Every
  return column stops at the pick's *next transaction*, so a pick flipped before
  its player suited up scores 0 points added no matter what came back. 2025 1.08
  (Judkins) reads 0.0 / −8.08 vs slot, which looks like the worst pick of the
  rebuild; follow the asset instead and it is a win — Judkins (159.7 starter
  points elsewhere) plus Deebo Samuel (49.9 *as a starter*, 5 starts) became
  **Zay Flowers, 213.5 points on 16 starts**, still rostered in 2026. Judge a
  converted pick with `timeline` and `player_year`, never with `picks` alone.
- **[by-design] Trades are not priced.** `trades` stores its assets as free text,
  so `spend_by_position()` cannot value the deal itself. Pick-level KTC from
  `picks` is the closest available and is what is quoted.
- **[by-design] Three-way trades cannot be rewound.** 3 of 2024's 67 trades have
  more than two sides; `undo_trade` and `compose` both refuse rather than guess
  the routing (`replay.three_way_trades`). None of the five teardown trades is
  one, so this does not touch the answer.
- **[by-design] Build-volatile columns quoted:** Tanking, Draft Value, Future
  draft capital, Drafting/Trading skill. They legitimately move between builds
  (`lotg_support.volatile_columns`); none is load-bearing here.
- **[by-design] Replay warning surfaced:** week 1, Alec Pierce was on nobody's
  roster, so no score is available and he is counted as 0.00 for that week.
- **[needs-human-judgment] 2026 has not been played.** The "the rebuild worked"
  half of the verdict is a roster judgement, not a result.
- **[by-design] `strict` is degenerate for player-for-picks trades** — see above.
  It is reported rather than dropped, but should not be read as a low estimate of
  the counterfactual.

## Reproduce

```bash
python scripts/inquire.py validate --season 2024
python scripts/whatif.py --season 2024 --model all \
    --undo-trade-id 1090497154780581888 --undo-trade-id 1092268177528127488 \
    --undo-trade-id 1095772841745821696 --undo-trade-id 1117973026936573952 \
    --undo-trade-id 1152469543118536704
python scripts/whatif.py --season 2025 --move '4034:8->7' --move '4217:8->7' --model all
python scripts/inquire.py sweep team_year --where Team=Oliverwkw --where Year=2024 \
    --within Year=2024 --window 2
python scripts/inquire.py timeline --team Oliverwkw --season 2024
python tests/test_replay_compose.py
```

The multi-trade rewind this note needed did not exist before it; it was added as
`replay.compose` / `replay.undo_trades`, guarded by `replay.check_compose` and
`tests/test_replay_compose.py`. Nothing the build produces changed.
