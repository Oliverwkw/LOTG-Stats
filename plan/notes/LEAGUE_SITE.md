# League website

A static site for league-mates, published on GitHub Pages at
`https://oliverwkw.github.io/LOTG-Stats/`, next to the rating page (`/rate/`, unchanged).

| Page | Route | Data |
|---|---|---|
| Home: standings, title/final/playoff odds, this week's results, the digest's items | `#/` | `data/home.json` |
| Teams table | `#/teams` | `data/team/*.json` |
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

**"Still counting"** on the record boards is decided per cell (`Counting` in league_site.py). It needs both:
- **an open row:** the season is in progress (season sheets); the stint has no "Date dropped/traded" yet (pickups, add/drops); the drafted player is still with the drafting team, or the pick isn't used yet (picks); the team still holds a received asset (trades); or the player is still rostered (player careers);
- **a column that can still move.**

A column is fixed if it's in the digest's `LOCKED_AT_MOVE` list, or it's a used pick's trade count or cuff flag. A KTC checkpoint ("at end of season", "N years later/after") counts until its date passes, whatever the row. The dropped player's next-17-games columns count for a year after the drop. Week rows are final. Team and league all-time totals move every week, so the board says so rather than tagging every row. Pick boards lead with the pick: "2025 3.08 · AceMatthew → Jalen Milroe".

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

- `lib/lotg_support/league_site.py` reads the committed `exports/*.csv`, `data/digest/last_digest.html`
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
