# Luck rework — design draft (Phase 4.5)

Status: **DRAFT for discussion.** Nothing implemented yet. Goal is to agree the
structure + weights here, then land it as one PR and tune via the
`_LUCK_*` constants.

## Goals (from you)
1. **Capture the luck involved in any win.** Luck is fundamentally about your
   *result* vs what you deserved.
2. **Monotonic with outcome:** it should be *rare* for a team to post higher
   weekly Luck than a team they **lost** to — *barring extreme pregame
   mismatches*.
3. **Weekly stat reads as:** "how much did I surprise / outperform, and how much
   was I held back by injuries, byes, etc."
4. **Extra hit** for Brosenzweigs (LOSS while 2nd-highest scorer = brutal bad
   beat); **boost** for Sisenzweigs (WIN while 2nd-lowest scorer = stole one).

## Why the current formula misses
Current weekly Luck (additive base, then 3 multipliers):
```
base = 1/6·(1−H/L_H) + 1/6·(1−SA/L_SA) + 1/4·WinVar − 1/10·Bros + 1/3·Eff
Luck = base × (oppYTDavg/oppThisWk) × (1.5−oppEff)            [× win% at year/all-time]
```
Problems vs the goals:
- **WinVar is realized-PF-percentile, not pregame.** It rewards "scored well for
  my week," which can be high for a high-scoring *loser* → can outrank a
  low-scoring *winner*. Breaks goal 2.
- **Own Efficiency (1/3 weight) is the single biggest term** and it's mostly
  *skill* (you started your best guys), not luck.
- **Multipliers are volatile.** `oppYTDavg/oppThisWk` blows up when an opponent
  scores very low; multiplying a *negative* base flips its sign. Hard to reason
  about and works against monotonicity.
- No explicit pregame-expectation anchor, so "barring extreme pregame
  mismatches" can't be expressed.

## Available variables (team_week)
| Variable | Meaning | Natural luck sign |
|---|---|---|
| `Win?` (1/0.5/0) | result | core |
| `Pregame avg MaxPF`, `Difference in pregame avg max PF from opponent` | pregame strength vs opp (season-to-date, excl. this wk) | sets expectation |
| `PF`, `Points against`, `Margin` | realized scoring | surprise |
| `Max PF`, `Efficiency` | ceiling, lineup optimality | mostly skill |
| `Hardship`, `Starter-adjusted Hardship` | points lost to injury/susp of (starting) players | held back (−) |
| `Number of players on bye`, `Number of Injuries`, `Number of suspensions` | availability hits | held back (−) |
| `Brosenzweig` (loss, 2nd-highest), `Sisenzweig` (win, 2nd-lowest) | luck extremes | −/+ accents |
| `UPST` | win while own pregame Max PF < opp's (upset win) | + |
| opp PF YTD avg, opp Efficiency (derived) | opponent context | accent |

## Proposed structure — three groups + accents, all ADDITIVE & normalized

Everything is put on a comparable ~[−1, +1] scale and **added** (no multipliers).
The **Outcome** group is weighted to dominate, which is what guarantees goal 2.

```
WeeklyLuck =
    W_OUT  · OUTCOME        # result vs pregame expectation   (dominant)
  + W_SURP · SURPRISE       # did you/opp beat your own norms  (small)
  − W_ADV  · ADVERSITY      # held back: hardship + byes       (misfortune)
  + W_SIS  · Sisenzweig     # lucky-win accent
  − W_BROS · Brosenzweig    # bad-beat accent
```

### 1. OUTCOME (dominant — drives winner > loser)
```
p   = pregame win prob from the pregame Max-PF matchup
      e.g. p = logistic( Difference in pregame avg max PF from opponent / SCALE )
OUTCOME = Win?(1/0.5/0) − p          # range ≈ [−1, +1]
```
- Underdog who wins → big +; favorite who loses → big −.
- **In any single matchup, winner's OUTCOME − loser's OUTCOME = 2·(1−p) ≥ 0**,
  so on this term alone the winner *always* ranks ≥ the loser. The other groups
  are sized so they only flip it in extreme-mismatch games — exactly your
  caveat. (Worked numbers below.)
- This replaces realized-PF WinVar with a *pregame* anchor, which is the whole
  point of "barring extreme **pregame** mismatches."

### 2. SURPRISE (small — "how much did I outperform")
```
SURPRISE = z(PF − myPregameExpectedPF) − z(oppPF − oppPregameExpectedPF)
```
- You beat your own scoring norm and/or held the opponent below theirs → +.
- Kept **small** so a high-scoring *loser* (lots of positive SURPRISE) still
  can't outrank a winner — their large negative OUTCOME + Brosenzweig dominate.

### 3. ADVERSITY (held back — misfortune)
```
ADVERSITY = z(Hardship + Starter-adjusted Hardship) + k·z(players on bye)
```
- Being short-handed is bad luck → subtract it. (Same direction as today's
  hardship terms, but as a clean normalized subtraction rather than 1−H/avg.)
- **Open question (sign):** should adversity *always* subtract (you were
  unlucky to be hurt), or only count when you **won despite it** (overcame
  adversity = extra lucky)? Draft assumes "always subtract." See Q3.

### Accents
- `+ W_SIS · Sisenzweig`, `− W_BROS · Brosenzweig`. These are already the
  extreme corners of OUTCOME, so the accent weights are small top-ups to make
  the corners pop, per your "extra hit / boost."
- **Drop own `Efficiency` from Luck** (it's skill). Optionally fold opponent
  efficiency into SURPRISE (you held a max-ceiling opponent down) — small.

## Worked examples (illustrative weights: W_OUT 0.5, W_SURP 0.15, W_ADV 0.2, W_SIS 0.1, W_BROS 0.1)
1. **Even game, underdog wins** (p=0.4): winner OUT=+0.6→+0.30; loser OUT=−0.6→−0.30. Winner clearly higher. ✓
2. **Sisenzweig** (win, 2nd-lowest, p≈0.45): OUT=+0.55→+0.275, +Sis 0.1 = **+0.375**. Very lucky. ✓
3. **Brosenzweig** (loss, 2nd-highest, p≈0.6): OUT=−0.6→−0.30, −Bros 0.1, but +SURP for big score (~+0.10) → **≈ −0.40**. Extra-unlucky even though they scored a ton. ✓ (matches "extra hit")
4. **Extreme mismatch** (heavy favorite p=0.95 wins): OUT=+0.05→+0.025. The underdog who lost: OUT=−0.95→−0.475. Winner still higher — *unless* the favorite also had heavy ADVERSITY (injuries); with W_ADV 0.2 a max adversity (~−0.2) could pull the healthy-underdog-loss above the hobbled-favorite-win. **This is the intended "barring extreme pregame mismatches" exception.**

## Open questions for you
1. **Pregame win-prob source:** OK to derive `p` from `Difference in pregame avg
   max PF from opponent` via a logistic (with a tunable SCALE)? Or do you have a
   preferred mapping (e.g., from projected PF, or KTC roster value)?
2. **Weights:** start at W_OUT 0.5 / W_SURP 0.15 / W_ADV 0.2 / W_SIS 0.1 / W_BROS
   0.1 and tune? Any hard ordering you want (e.g., OUTCOME must be ≥ 2× any
   other)?
3. **Adversity sign:** always subtract (unlucky to be hurt), or only when you
   won despite it (overcame adversity)? Or split: subtract when you lost,
   reward when you won?
4. **Drop own Efficiency** from Luck entirely — agreed?
5. **Multipliers:** retire the `oppYTDavg/oppThisWk` and `1.5−oppEff` multipliers
   in favour of the additive SURPRISE term? (Recommended — kills the blow-ups.)
6. **Year / all-time:** keep `Σ weekly × (0.5 + 0.5·win%)`, or — since OUTCOME
   already bakes in winning — drop the win% blend and just sum (optionally mean
   for all-time)? 
7. Any variables above you specifically want IN or OUT, or new ones (margin
   size, schedule strength, KTC)?

## Normalization note
`z(·)` = within-(Year,Week) standardization (subtract league weekly mean,
divide by league weekly std), clipped to ±2 then /2 → ~[−1,1]. Keeps every term
on the same scale regardless of season scoring inflation, and makes the weights
mean what they say.

---

# Experiment findings (run on build 26702996514)

All models additive & standardized (no multipliers). Scored on: (a) winner>loser
consistency, (b) **magnitude** vs known scenarios, (c) season behavior.

## Weekly model that works
```
WeeklyLuck = 0.45·(Win − pregame_p)  + 0.25·OppAbnormal_z  − 0.20·Adversity_z  + 0.18·Efficiency_z
```
- `pregame_p` = logistic(blend of standardized [MaxPF diff, PF diff, win% diff]); tested to-date / full-season / 50-50 mix.
- `OppAbnormal_z` = −z(oppPF − opp season-avg PF)  → opponent collapsing vs their norm = you got lucky; opponent erupting = you got robbed. **This captures Brosenzweig/Sisenzweig continuously** (those flags are now optional small accents).
- `Adversity_z` = z(Hardship + SA-Hardship + 3·byes), **always subtracted**.
- `Efficiency_z` = z(Efficiency) — start/sit fortune, kept.

### Validation
- **winner>loser: 0.95–0.97** (all > 75% floor). Every one of the 14 violations is a **heavy pregame favorite** (p>0.7) and/or a **high-adversity winner** — i.e. exactly the "barring extreme pregame mismatches / I was hurt" exceptions. Nothing spurious.
- **Magnitude (the real test):**
  - plehv79 (worst team, 109 avgPF) beating champion shmuel256 (167 avgPF) in wk6 & wk13 → **#1 and #3 luckiest games in the whole dataset** (100th pctile). shmuel's wk6 loss = **single unluckiest game** (0th pctile). Neither is a Bros/Sis flag — captured purely by outcome+opp-abnormal. ✓
  - Scenario means: underdog-win **+0.43**, favorite-loss **−0.46**, but favorite-win **+0.17** and underdog-loss **−0.16** (expected results stay mild). ✓ "First plays last twice, last usually loses" → those expected losses are mild, the upset is extreme.
- Current shipped formula scored only **0.815** winner>loser for comparison.

### Expectation-basis tradeoff
- **Full-season** quality (hindsight) gives the biggest marquee magnitudes (knows shmuel is a juggernaut even in wk6) → plehv +0.9 / shmuel −0.74.
- **To-date** (pregame, fair) is smaller early but "honest."
- **50-50 mix** ≈ full strength on magnitude, keeps some pregame honesty. Recommended default.

## Season model — open tension
Summing/averaging weekly luck still correlates **+0.46 with win%** (champion ends up 2nd-luckiest) — violates "if you're winning you aren't that lucky."
- **Win Variance** (finish vs PF/MaxPF rank) is the right season signal and you already wanted it: corr with win% only +0.285, and it flags the right teams (plehv79 2025 WV +3.0 = overperformed talent = luckiest; stevenb123 2025 scored 2nd-most but finished 3rd = unluckiest).
- Candidate: `SeasonLuck = z(WinVariance) + z(season-mean of the *uncontrollable* weekly parts: opp-abnormal − adversity + efficiency)` + a **playoff over/under-seed** term (TBD). Drops the raw win-accumulation that inflates the win% correlation.
- Lucky championships surface correctly (stevenb123 2024 won it with WV +3.0 = lucky title; LWebs 2022 likewise), while a high-scoring champion is only mildly positive.

## Decisions needed
1. Expectation basis: **to-date / full-season / mix**? (mix recommended)
2. Weights — happy with 0.45 / 0.25 / 0.20 / 0.18, or shift (e.g. more opp-abnormal)?
3. Keep Bros/Sis as small accents, or rely on the continuous opp-abnormal term that already captures them?
4. Season formula: Win-Variance-centric (above) + playoff seed heuristic — agree on shape, then pick the playoff term.
5. Weekly and Season are *different* formulas (weekly = per-game outcome surprise; season = record-vs-deserved). OK?

---

# ★ FINAL MODEL (selected: "G2") — math in current columns

All inputs are existing team_week columns. Two standardizers:
- `z_wk(x)` = standardize x **within each (Year, Week)**, clip ±2.5, ÷2.5 → ~[−1,1].
- `z_all(x)` = standardize x over all rows.

### Per-(Team,Year) season strength (from columns)
```
FS_pf    = mean(PF)        FS_maxpf = mean(Max PF)        FS_win = mean(Win)
```
`Win` = Win? → {win 1.0, tie 0.5, loss 0.0}. `opp_*` = same value for the row's `Opponent`.

### Pregame win probability (blend of 3 talent signals, calibrated)
```
dblend   = ( z_all(FS_maxpf − opp_FS_maxpf) + z_all(FS_pf − opp_FS_pf) + z_all(FS_win − opp_FS_win) ) / 3
pregame_p = 1 / (1 + exp(−1.5 · dblend))
```
(Scale 1.5 chosen so that **Σ of the OUTCOME term has ~0 correlation with win%** and +0.79 with Win Variance — i.e. winning to your talent ≈ zero luck.)

### Components (all from columns)
```
OUT   = Win − pregame_p
OPP   = z_wk( −(Points against − opp_FS_pf) )          # opponent scored below their norm → you got lucky
OWN   = z_wk(  PF − FS_pf )                             # your studs popped vs your norm
ADV   = z_wk(  Hardship + Starter-adjusted Hardship + 3·(Number of players on bye) )
EFF   = z_wk(  Efficiency )
CLOSE = sign(Margin) · max(0, 1 − |Margin|/8)          # nail-biter bonus to winner / penalty to loser
GATE  = 1 / (1 + |Margin|/15)                           # scoring-variance only counts when it decided a close game
POST  = 1 if Week Name ∈ {Final, Semifinal, 3rd Place} else 0
SIS   = Sisenzweig (0/1)     BROS = Brosenzweig (0/1)
```

### Weekly Luck
```
WeeklyLuck =  ( 0.27·OUT + 0.14·SIS − 0.14·BROS ) · (1.8 if POST else 1.0)
            + ( 0.36·OPP + 0.10·OWN ) · GATE
            − 0.36·ADV
            + 0.12·EFF
            + 0.16·CLOSE
```
- The **result-surprise** bracket (outcome + Bros/Sis) is what the **postseason ×1.8** amplifies — so postseason *upsets* cost more, but postseason *blowouts* don't.
- The **scoring-variance** bracket (opp/own) is **gated by closeness** — an opponent collapsing is only "luck" if it swung a close game.
- **Adversity always subtracts**, heavily (0.36) → very high adversity = very bad luck.

### Season / all-time Luck
```
SeasonLuck = Σ WeeklyLuck   (no win% multiplier — winning is already netted out in OUT)
```

### Scorecard (build 26702996514)
| metric | value | target |
|---|---|---|
| winner > loser | **0.88** | 0.80–0.90 ✓ |
| corr(Σweekly, win%) | **+0.18** | ~0 (winning≠lucky) ✓ |
| corr(Σweekly, Win Variance) | **+0.56** | high + ✓ |
| corr(luck, adversity) | **−0.48** | strong − ✓ |
| top-decile adversity → mean luck pctile | **0.23** | low ✓ |
| plehv79 2025 vs shmuel256 | **99th pctile** | outlier ✓ |
| Brosenzweig / Sisenzweig mean pctile | **0.12 / 0.85** | low / high ✓ |
| close-win vs blowout-win pctile | **0.72 / 0.71** | close ≥ blowout ✓ |
| postseason |luck| / regular | **1.55×** | >1 ✓ |
| distribution | mean 0.00, sd 0.25, [−0.67, 0.73] | centered ✓ |

Luckiest games = plehv's nail-biter upsets (incl. both wins over the champion); unluckiest = high-scoring close losses & collapses. Weights live as tunable constants.
