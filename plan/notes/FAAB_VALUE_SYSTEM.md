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

## What is in the repo now, and what is not yet (phase B)

`data/faab_value/` holds the rule layer's inputs as plain text:

- `inputs.csv`: the 2026-10-24 board rows, plus the day-before row of every trade side and cut.
- `evidence.json`: the trades and cuts.
- `params.json`: the fitted rule strengths.
- `reviewed_board_2026-10-24.csv`: the board the calls were made about.

Everything after the base value runs and is tested here: the rules, the fit, the calls, the votes and the page.

**Not here yet:** the base value and the dated stats features (`e_x_*`). These are:

- nflverse expected points, participation, NGS, PFR, rosters and injuries;
- combine, draft and college usage;
- awards (from Wikipedia);
- team strength;
- off-field events.

They were built in a research scratchpad: about 30 modules, a ~1 GB intermediate, and about 2 hours to run the
quarterly walk-forward. Phase B ports them into `lib/` with a scheduled job, so the board regenerates on its
own. Until then the board is the 2026-10-24 one.

## The rating page

`docs/rate/` is a static page on GitHub Pages. It asks short questions:

- **pair**: "who would you rather have". Values are hidden, so they don't anchor the answer.
- **price check**: "the board says $X: too high / about right / too low / what would you pay".

The questions are aimed where they teach the rules the most:

- close calls across positions;
- pairs the rules pulled apart;
- the players the rules moved most;
- a spread across value tiers.

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

`votes` lists where the board and the votes disagree, and which rule terms put each side where it is. Those are
the leads for a missing characteristic. Uneven participation is expected and handled by the caps.

### One-time setup (owner)

1. **Google Form** (forms.google.com), titled "LOTG value check".
   - Settings: *do not collect email addresses*, no sign-in required, allow more than one response. The repo is
     public, and the responses become a public CSV.
   - Add 13 **Short answer** questions, none required, titled exactly:
     `team`, `question_id`, `kind`, `board_date`, `player_a`, `player_b`, `shown_a`, `shown_b`, `answer`,
     `amount`, `own`, `client_time`, `page_version`.
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
