# FAAB value system and the rating page

What every QB/RB/WR/TE is worth in the league's own FAAB dollars on a date. The values come from stats only and
use only what was known that day, the way the league values players. A 1.05 rookie pick is about $1,050.

## How a value is made

1. **Base value (walk-forward)**:
   - Production value: projected points above superflex replacement, aged by position curves.
   - A stats translator: stats in, never KTC in. It is fitted to the KTC history only as a training scale.
   - A league-price model fitted to LOTG drafts, trades and waivers.
   - Every model is refit at each quarterly snapshot, on data dated before that snapshot. Values are then smoothed causally across dates.
2. **General rules** (`lib/lotg_support/faab_value.py`): about 45 characteristics, such as:
   - usage (expected points), team share, availability, a sustained elite record, QB passing quality;
   - early-career draft and college pedigree, efficiency, volatility and TD dependence, age cliffs;
   - injury status, off-field events, the replacement line (vets ranked below the line are worth about 0).
   - QBs (#531): draft capital fading over four seasons; an established starter (usage over the line, 2+ top-12
     seasons, fading 30-34); an opening (a QB who has played well, ahead only of an aging backup holding the
     snaps). On IR, a player's usage and availability read his seasons before the injury, since the IR rule already
     charges for this one.

   Each characteristic's strength is one number, used the same way on every date and for every player. There
   are no names and no pins. Sign locks keep each rule pointing the only plausible way: an injury can only lower
   a value, an award can only raise it.
3. **Fit**: all strengths are fitted jointly. Trades and cuts count for more than one person's calls.

   | Term | Weight |
   |---|---|
   | Completed trades (both sides valued the day before) | 3 |
   | Cuts (worth under ~$100 the day before) | 3 |
   | The league's calls (`faab_calls.py`, tests on the 2026-10-24 board) | 1 |
   | Rating-page votes, capped (below) | ≤ 1.5 |
   | Pull of every strength toward 0 | small |

Results on 2026-10-24:

| | Rules off | Fitted |
|---|---|---|
| Trade error (median + mean \|log side ratio\|) | higher | 1.125 |
| Cuts valued over $100 | 8.7% | 5.6% |
| League calls passing | – | 89 / 116 |

The remaining misses are mostly young mid-tier receivers the league likes more than the stats do: Ladd,
P. Washington, Coker, J. Price. Addison and Jamo are also on the list.

## Commands

```bash
python scripts/faab_value.py board -n 40
python scripts/faab_value.py explain "Bucky Irving" "Bhayshul Tuten"   # every rule's multiplier
python scripts/faab_value.py calls
python scripts/faab_value.py votes                                     # votes vs the board
python scripts/faab_value.py fit --out data/faab_value/params.json     # deliberate refit, reviewed in a PR
python scripts/faab_value.py publish                                   # rewrite the page's board/questions
```

## How the inputs are rebuilt (self-sustaining)

`scripts/faab_rebuild.py` (`lotg_support.faab_pipeline`) rebuilds `data/faab_value/inputs.csv` and `evidence.json`
from public data and the repo's own exports. `.github/workflows/faab_rebuild.yml` runs it weekly (Wednesdays) and
commits the inputs and the page data. It never refits the rule strengths.

| Stage | Module | What it does |
|---|---|---|
| Downloads | `faab_data` | nflverse / ffopportunity / college stats / Wikipedia awards / dynasty-daddy KTC histories into `.cache/` (git-ignored) |
| Features | `faab_features` | dated `e_x_*` stats, each counted from when it was known |
| Frame | `faab_frame` | per (player, date) stats frame (the KTC-proxy feature builder, moved into lib) |
| Inputs | `faab_inputs` | Sleeper ids, trades, cuts, pick prices, KTC training panel, valuation grid, evidence |
| Base | `faab_base` | the walk-forward base: one model set per quarterly snapshot, fit only on data before it |
| Formula | `faab_formula` | base -> `V_raw` on any date (floors, legacy, breakout, rookie slot, injuries, offseason blend) |

Finished quarterly snapshots never change, so the weekly run reuses their cached blocks and refits only the current
quarter (`--full` refits all, about 2–3 hours).

The port reproduces the research run exactly: every feature table, the base at two snapshots, and `V_raw` on five
dates, all with zero difference. Two research-era behaviours changed on purpose (`faab_base.REPRO` restores them for
reproduction):

- **Aging curve:** it kept seasons ≤ 2024 regardless of the snapshot. That counted the last complete season as all
  drop-offs at the 2021–23 snapshots, and would have frozen the curve from 2027. It now uses seasons before the
  last complete one.
- **Folds:** players outside the stored fold map were assigned folds with Python's `hash()`, which changes between
  runs. Folds are now a stable hash of the Sleeper id.

Points over expected also count only the best game's excess at half, the definition the rules already used.

**Committed data the pipeline reads:**

- `chat_evidence.csv`: the league chat's valuations (player, date, log price, weight, kind), with no names or text;
- `offfield_events.csv`: retirements, legal and left-the-team events, dated;
- `awards.csv`: the parsed awards, the fallback when Wikipedia is not cached;
- `../suspensions.csv`.

**Votes and calls keep their dates.** The inputs keep the 2026-10-24 board, which the league's calls are judged on,
and every player a vote was about, on the board he was shown on (`evidence.json` `vote_dates`).

## The rating page

`docs/rate/` is a static page on GitHub Pages. Every question shows two players the board values about the
same, each with its board value and the nearest useful rookie-pick comparison. A comparison is either one
slot ("about the 2.03") or, for players worth more than the 1.01, a package ("about the 1.01 + 1.03 + 1.05").
Slot prices are the league's median draft prices for each slot, from drafts held before the board date.
Every part of an answer is optional, and nothing advances until Submit:

- which player is worth more, or "too close to call";
- for each player: too high / about right / too low;
- for each player: what you would pay;
- why.

One submission therefore gives up to three signals: the pick, plus a price check on each player. The pairs are
aimed where they teach the rules the most:

- close calls across positions;
- each player the rules moved most, against his nearest neighbour;
- pairs the rules pulled in opposite directions;
- random near pairs.

Every answer records:

- the voter's **team** (people value their own players more, so own-player answers count half; non-members count a quarter);
- the **board date** and the **values shown**, so an answer is judged against what was known then;
- the client time.

**Votes are signals, not edits.** They never set or move a player's value. They enter the fit as one capped
term, so they can only change how much a general rule weighs:

- its weight = 1.5 × min(1, teams answering / 4) × n / (n + 100);
- one team alone reaches at most a quarter of that;
- one team's share of the vote weight is capped at 35%;
- the term is always below the trades and cuts terms.

**How a price answer is scored** (#531): "too low" / "too high" only say the value shown is not right in that
direction, with no cap and no minimum (any higher / lower value agrees). "About right" is within 15% of the
value shown. A typed amount is a target, within 15%. Each answer is scored on its own; none is turned into a
point estimate (before #531 a bare "too low" counted as exactly x4/3, which held Jaxson Dart near $375 when
every voter said he was worth far more).

`votes` lists where the board and the votes disagree, and which rule terms put each side where it is, followed
by every "why" note. Those are the leads for a missing characteristic. Uneven participation is expected and handled by the caps.

### One-time setup (owner)

1. **Google Form** (forms.google.com), titled "LOTG value check".
   - Settings: *do not collect email addresses*, no sign-in required, allow more than one response. The repo is
     public, and the responses become a public CSV.
   - Add 17 **Short answer** questions, none required, titled exactly:
     `team`, `question_id`, `kind`, `board_date`, `player_a`, `player_b`, `shown_a`, `shown_b`, `answer`,
     `verdict_a`, `verdict_b`, `amount_a`, `amount_b`, `why`, `own`, `client_time`, `page_version`.
     `why` can be Short answer too; it holds a sentence or two.
2. **Entry ids**: ⋮ → *Get pre-filled link*.
   - Type each question's own title into its box, then *Get link* → copy.
   - The link holds `entry.NNNN=team&entry.MMMM=question_id…`. Put those ids into `docs/rate/config.json`.
   - Set `form_action` to the form URL with `viewform` replaced by `formResponse`.
3. **Responses sheet**: Responses → *Link to Sheets*.
   - In the sheet: File → Share → *Publish to web* → the responses tab → **CSV** → Publish → copy the URL.
   - Add it as the repo **variable** (Settings → Secrets and variables → Actions → Variables) `FAAB_VOTES_CSV_URL`.
4. **Pages**: Settings → Pages → *Deploy from a branch* → `main` / `/docs`. The page is then at
   `https://oliverwkw.github.io/LOTG-Stats/rate/`.

`.github/workflows/faab_votes.yml` runs daily (and on demand). It pulls the sheet into
`data/votes/responses.csv` and writes `data/votes/report.md`. It never refits.
