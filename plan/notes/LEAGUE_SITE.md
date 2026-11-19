# League website

A static site for league-mates, published on GitHub Pages at
`https://oliverwkw.github.io/LOTG-Stats/`, next to the rating page (`/rate/`, unchanged).

| Page | Route | Data |
|---|---|---|
| Home: standings, title/final/playoff odds, this week's results, the digest's items | `#/` | `data/home.json` |
| Teams table | `#/teams` | `data/team/*.json` |
| Record watch (home): every weekly stat the page can recompute from Sleeper's live player points (`Site.WATCH_TEAM_STATS` / `WATCH_GAME_STATS`, player points by role and position, 75 stats) on its league board and filtered versions (in a win / in a loss; rookies for player points). Regular-season, this-season, franchise and career versions were tried and dropped as too much (user, 2026-11-17). Also on it (user, 2026-11-17): the **Sleeper-projection** stats (Sleeper Projection, points above it, difference from the opponent, Sleeper Lineup Boldness, pre-week win % and win % overcome, Comeback / Choke size on the Sleeper set) from Sleeper's projections fetched live and scored with the league's settings — they count until every game they depend on kicks off, then lock; the **comeback** stage stats (margin entering SNF / Monday / last game, margin and points overcome, … per `lotg_support.gametime`); and the **streaks** (team: win/loss, award and 150+ streaks; player: of-the-week, team high/low, captain, 10+-50+), each last week's count from the exports + 1 if it keeps going (shown only when the exports run through last week). Not live: the Claude / Enhanced projection sets and Lineup Boldness (the build computes those projections only for finished weeks), standings-leader, quiet and win-vs-this-opponent streaks. Each mark is one entry per stat, end and team / player / game, listing every board version it could make (unfiltered first); lineup counts sit below the top 15. The simulation centres each player on his Sleeper projection (blended rate where none) with the spread real starts have had around it (sd = min(9.5, 3 + 0.35 × projection); a team ±25, a margin ±34 vs Sleeper's projected difference, 2020-26) — a Sleeper-projection stat's unfiltered line shows its rank as projected now, never a chance, and nothing still counting reads "certain" (99%+ at most; user, 2026-11-17) — and then **win chances are Sleeper's** (user, 2026-11-17): the simulated weeks are tallied by which side won each matchup and reweighted so each matchup's win chance equals the app-style win % (points so far + Sleeper projections left), so every in a win / in a loss chance, win/loss streak and projected average uses Sleeper's win %. Checked on 2026 week 9: comeback margins match exactly; Sleeper Projection matches where no player's injury status has changed since (the page uses the build's statuses). The rest of the week is simulated 2,000 times in the browser, **seeded from the live scores and a 10-minute clock**, so the same scores give everyone the same odds on every reload. Top 5 follows the digest tie rule; an outright record and a tie are counted apart. Three views by where each mark stands — **Not started** (no game it depends on has kicked off), **Counting**, **Finished** (every game it depends on is over: his, his team's, or both teams' for a result-filtered or game mark) — each previewing its top 20 by chance of a top-5 place (Finished: records first); the rest, and near-certain lineup counts, sit in the "Every other board" dropdown | `#/` | `data/live_watch.json` (`stats`, `boards`, `rows_t`, `rows_p`, `prev`), Sleeper live |
| Team: all-time tiles, head to head, roster age vs league by position, this season, seasons, current roster, trades, rookie picks | `#/team/<team>` | `data/team/<team>.json` |
| Player: career tiles (incl. career xFP, points minus xFP), career by team, every acquisition (player_additions), seasons, usage per season (snaps, targets, carries, red-zone looks, xFP), trades | `#/player/<key>` | `data/player/<key>.json` |
| Record book: top/bottom 5 of **every** numeric column on 13 sheets, the digest's board rule (shared places "T2", a tie that does not fit the 5 left off); week sheets split all / regular season / playoffs (semis, final) / 3rd place game / toilet bowl / toilet losers game, matching the build's team records; one row per trade, zero-sum trade columns show only the top | `#/records/<sheet>` | `data/records/<sheet>.json` |
| Head-to-head matrix (all / regular season / playoffs / 3rd place game / toilet bowl / toilet losers game) | `#/h2h` | `data/h2h.json` |
| Trade history with each side's KTC difference at the deal, season end, +1 and +2 years, impact score, wins added, net points | `#/trades` | `data/trades.json` |
| Draft history (rookie; startup & vet picks) | `#/draft` | `data/draft.json` |
| FAAB values: the current board (filter by position / owner / free agents), roster value by team = players + **every rookie pick held for the next 5 drafts** (by position, by pick year), rookie-pick values, each value as rookie-pick equivalents; links to the rating page and embeds it | `#/faab` | `rate/board.json` (fetched live from docs/rate/) |
| Data: **every sheet in exports/, every row and column** (filter any cell or one column, sort, choose columns, definitions from formulas.csv, CSV download) | `#/data/<sheet>?c=<col>&v=<value>` | `data/sheets/<sheet>/<chunk>.json`, `downloads/<sheet>.csv` |
| Matchup: both lineups by slot, bench, max PF | `#/game/<year>/<week>/<team>` | `data/week/<year>-<week>.json` |
| Week: every matchup that week | `#/week/<year>/<week>` | same |
| Pick: the pick's stats and its full history | `#/pick/<sheet>/<row>` | `data/draft.json`, `data/pick_history.json` |
| Search (players, teams; links into the record book and the Data page) | `#/search/<q>` | `data/search.json` |
| Weeks: every week of a season with the league's totals (league_week), a points-per-week chart, season tabs; previous / next week links on week and matchup pages come from the same rows | `#/weeks/<year>` | `data/sheets/league_week/*.json` |
| Compare: two players or two teams, every career / all-time stat side by side; teams add their head-to-head | `#/compare?a=<t\|p>:<key>&b=…` | `data/team/*.json` or `data/player/*.json`, `data/h2h.json` |
| Trade calculator: two teams, tap players and future picks each sends; an "Every angle" table (FAAB value, KTC superflex value and its month trend, projected points a week, rest of the regular season, this season's points a week, starting-lineup change, value-weighted age, picks); season odds before → after from the Predictions simulation (`predict(…, {headless: true})`, players moved); values on the FAAB board's scale (picks by the FAAB pick rule), verdict with the gap as rookie-pick equivalents, the closest assets to even it up, roster value / rank / positional value / projected points a week before → after, and a link that opens Predictions with the players moved | `#/calc?a=<team>&b=<team>&sa=<p<id>,k<y>-<r>-<orig>…>&sb=…` | `rate/board.json`, `data/picks.json`, `data/live_watch.json`, `data/ktc.json` (dynasty-daddy's directory at build time: the browser can't read it, no CORS; picks mapped onto KTC's 12-team quarters), `data/season_players.json`, the forecast sims, Sleeper live |
| My team: opens the team the reader picked in the ☰ menu (kept in their browser), or asks which | `#/mine` | — |
| Predictions: pick winners and move players. It replays the home page's forecast seasons (`data/forecast_sims.bin`: int16 tenths of a point, sims x `forecast.sim.weeks` x `forecast.sim.teams`, raw points, no +5), so with no changes its odds ARE the home page's: both are counted from the same rounded scores by the same rules (`league_site.replay_sims` / app.js `simulateFull`, line for line, in integer hundredths; tests `test_replay_sims_follows_the_rules`, `test_site_forecast_is_its_own_odds`). A pick puts the picked side's score on top in that game; a roster move shifts the team's simulated weeks by `forecast.sim.slope` x the change in its best fielded lineup (`forecast.sim.rates` = the forecast's own player rates; who can play each week from `forecast.avail`, hashed per player/week so two rosters share draws); a week Sleeper finished since the build uses its real scores, and the week in progress live points + what is left once it has started. An older home.json without `forecast.sim` falls back to the old lighter simulation (best lineup by blended rate, ±0.65 x rate per player) | `#/predict` | `data/home.json`, `data/forecast_sims.bin`, `data/live_watch.json`, Sleeper live |

**Shell conventions (UX pass, 2026-11-18; full list in `SITE_UX_OVERHAUL_2026-11.md`):**
- A page's filters live in the URL (`setQuery`, replaceState): a copied link reproduces the view. New filters should do the same.
- Every table goes through `table()` / `dataTable()`: keyboard sort with `aria-sort`, a row filter + Copy + CSV once it has 16+ rows, "Show all" past 150 rows, `teamOf` to highlight the reader's team, `rowLink` to open a row.
- Team names go through `teamLink` (avatar + link); players through `playerLink`, positions through `posBadge`.
- The reader's settings (their team, theme, density, page size, recent pages) and Sleeper's team avatars / fantasy names / league logo are in localStorage under `lotg:*`; nothing is sent anywhere.
- Tables mark the best and worst value in each numeric column (`extremesOf`): lower is better where the column name says so (`X_LOW`), identifiers and neutral counts are skipped (`X_SKIP`), and on one-row-per-season tables the season still being played is left out.
- Shared links have no "#": `?to=<route>` (chat apps, Sleeper's included, often won't make a `#/…` URL tappable); the page turns it back into `#/<route>` on open.
- Colours follow Sleeper (2026-11-19): navy app bar, mint accent, dark by default; Light and "match the device" are in the ☰ menu.
- Team avatars, fantasy team names and the league logo come from Sleeper's `users` and `league` endpoints, read with the rosters on page open.

**"Still counting"** on the record boards is decided per cell (`Counting`, `column_clock` in league_site.py). Each column of a move sheet runs on its own clock, read from its definition in formulas.csv:

| Clock | Counts while | Examples |
|---|---|---|
| fixed | never | the digest's `LOCKED_AT_MOVE`, a used pick's trade count, cuff flags |
| held | the player or the received assets are still on that team | points added, on-team PPG, tenure, starts |
| first_start | held and he hasn't started yet | weeks between pickup and first start |
| team_now | he's on that team now | "(all stints)" totals |
| sent | the received side is held (4 years if no player came back) | a trade's sent side "over the same time" |
| draft | a received pick's draft hasn't happened yet | change in pick value at draft time |
| career | he's active in the NFL | a pick's career PPG |
| next17 | about a year after the drop | the dropped player's next 17 games |
| checkpoint | until its date | KTC at season end, N years later/after |
| always | always | wins added, impact score, O-Score, pick-adjusted figures, % of all-time team points, points above expectation |

Season rows count while the season is in progress, and career rows while the player is rostered. Week rows are final. Team and league all-time totals move every week, so the board says so instead of tagging each row. Pick boards lead with the pick: "2025 3.08 · AceMatthew → Jalen Milroe".

**Every row opens its details.** Record-board rows, Data rows (the › column), draft tables, home results, team weeks and head-to-head meetings link to the trade, matchup, week, player, pick or team they describe. The record boards' links come from `Site.row_link`, and the Data page's from `rowLink` in app.js, which mirrors it. A test checks that every board link resolves.

**Asset histories.** Each player's and each pick's full history (draft, every add, drop and trade with the whole deal) exists only as a hover comment in the build's `LOTG_Stats.xlsx`. The site workflow downloads that workbook from the triggering build's `LOTG_outputs` artifact, or from the latest successful main build. `lotg_support.workbook_comments` reads the comments without openpyxl, in under a second. A comment is used only where its row's column A still matches the committed CSV. Trade lines link to the trade. Without the workbook, as in a local build without `--workbook`, those sections say they are pending.

## Live rosters (on page open)

Stats come from the last main build: the site redeploys after every successful one, and the footer names the build run. Rosters and pick ownership are read **straight from Sleeper by the browser** whenever a team, player or FAAB page opens. That takes three small requests, `rosters`, `users` and `traded_picks` (about 40 KB together, 0.04–0.2 s), so a trade made since the last build already shows. The page draws at once from the build's data, then redraws with Sleeper's.

- **Team page:** the current roster as it is on Sleeper, with each player's lineup role now. Players new since the build are tagged "new since the build", and the players who left are listed.
- **Player page:** which team he is on now.
- **FAAB page:** roster value by team, using live owners.
- **Picks held:** every pick Sleeper shows moved *since the build* is applied on top of the build's ownership. `picks.json` carries `sleeper_at_build`, so the commissioner overlay's off-platform moves aren't undone.

If Sleeper fails, or takes longer than 4 s, the page keeps the build's rosters and says "Sleeper unreachable". `data/nfl_players.json` maps Sleeper ids to name, position, NFL team and this season's age. Tested on 2026-11-03 with the Mahomes ↔ Lamar Jackson trade, which wasn't in the exports yet.

## How it is built

- `lib/lotg_support/league_site.py` reads `exports/*.csv` (in CI, `site.yml` first replaces them with the latest
  successful main build's sheets from its `LOTG_outputs` artifact, because the build commits `exports/` only on a
  roster change, the Tuesday run or the 6-day cadence; a new column used to stay blank until then), `data/digest/last_digest.html`
  and (through `lotg_support.forecast`) the snapshot; writes JSON. `scripts/build_site.py` is the CLI.
  `site/` holds the hand-written shell (index.html, app.js, style.css): no framework, no build step.
- Numbers are shipped raw with each column's workbook format (`number_format.col_number_format`), and
  the page prints them to the workbook's decimals. Column names go through the digest's `display_column`.
- Player page keys are name slugs today (namesakes get `-2`). When the Player ID column lands in
  `player_all_time`, keys switch to the ID automatically (`Site._player_slugs`).
- `.github/workflows/site.yml` runs after every main run of "Build LOTG Stats" and "Rebuild FAAB values",
  on pushes to main touching `docs/`, `site/` or the generator, and by hand. It copies `docs/` in, runs
  the privacy scan (`tests/test_league_site.py --check-dir`), and deploys with `actions/deploy-pages`.
  **Nothing generated is committed**, so the repo does not grow with the site.
- The main build is untouched (separate workflow).

## Numbers (2026-10-29, through 2026 week 7)

- Output: 42.7 MB on disk, **7.1 MB gzipped**: page JSON 5.3 MB; the Data page's full sheets
  20.4 MB (player_week split by season, up to 2.8 MB each, ~0.4 MB gzipped); CSV downloads 16 MB.
  Pages serves gzip. A page view loads `meta.json` + `search.json` (~70 KB) plus that page's file.
- Build time: ~20 s without the forecast, ~60 s with it (20,000 sims) on an idle laptop.
- The FAAB page reads `rate/board.json` itself, so it is always the board the rating page shows; the
  FAAB rebuild that republishes it triggers a redeploy.

## Future picks held

`Site.held_picks` (`data/picks.json`) gives the current owner of every rookie pick in the next 5 drafts, rounds 1-4, worked out the way the build's `_future_picks_owned` does it:
- every pick starts with its original team;
- the trades sheet's pick legs, replayed in date order, move it. Those legs already include the commissioner overlay's off-platform moves.
- a pick that no trade moved, but that Sleeper's `traded_picks` shows with another team, belongs to that team.

The test checks the result against `team_year`'s "Future draft capital" for the current season, team by team. It matched all 8 teams exactly on 2026-11-02.

The page values each pick with the FAAB model's own rule (`faab_inputs` value): the round's average slot value on the board, minus 5% for each draft past the next one; rounds 5+ are $20.

## Keeping it complete (user rule, 2026-11-02)

Every change or addition to the exports, the FAAB values or other league-facing data also goes on the site, in the same PR.

**Automatic:**
- a new CSV in `exports/`, or a new column on any sheet, reaches the Data page (with a download) and the record book. `tests/test_league_site.py` fails if any sheet, row or column is missing.
- a new `docs/rate/board.json` reaches the FAAB page. The FAAB rebuild triggers a redeploy.

**By hand, in the same PR:**
- a new column holding player or team names: add it to the link lists in `site/app.js` (data() `cell`, records() `lab`).
- a column that deserves a headline spot: add it to `FEATURED`, `SEASON_COLUMNS`, `TEAM_SUMMARY_COLUMNS`, `PLAYER_SUMMARY_COLUMNS` and so on.
- a new FAAB output (explanations, value history, vote results): add a section to `faab()` and data to the generator.
- a new league-facing data file outside `exports/`: add it to `INPUTS` and give it a page. Run the privacy scan.
- the workflow: if a new workflow commits league data, add its name to `site.yml`'s `workflow_run` list.

**Never:** DMs or chat exports (`plan/notes/sleeper-chat-*`, `data/faab_value/chat_evidence.csv`), manager profiles, negotiation notes, credentials.

## Privacy

Inputs are an allow-list: the exports (already public in this repo), the digest email the league
already receives, the forecast, and docs/rate/ (already published). `data/faab_value/` is not read
(its chat_evidence.csv comes from the league chat). Nothing under `plan/`, no memory file, no DM / chat export, no
credential is read. The workflow fails the deploy if the output carries any private marker.

## Turning it on (repo owner)

Pages currently deploys `main:/docs` the legacy way. Until the source is switched, the workflow builds
the site and keeps it as a run artifact (`github-pages`) but skips the deploy.

1. Merge the PR.
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**. (The rating page keeps working:
   the workflow publishes `docs/` with the site, so `/rate/` and its Google Form votes are unchanged.)
3. Actions → League site → Run workflow (or wait for the next build).
4. Open `https://oliverwkw.github.io/LOTG-Stats/` and `/rate/`.

To roll back: set the source back to "Deploy from a branch" → `main` / `/docs`.
