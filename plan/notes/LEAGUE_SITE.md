# League website

A static site for league-mates, published on GitHub Pages at
`https://oliverwkw.github.io/LOTG-Stats/`, next to the rating page (`/rate/`, unchanged).

| Page | Route | Data |
|---|---|---|
| Home: standings, title/final/playoff odds, this week's results, the digest's items | `#/` | `data/home.json` |
| Teams table | `#/teams` | `data/team/*.json` |
| Team: all-time tiles, head to head, roster age vs league by position, this season, seasons, current roster, trades, rookie picks | `#/team/<team>` | `data/team/<team>.json` |
| Player: career tiles, career by team, every acquisition (player_additions), seasons, trades | `#/player/<key>` | `data/player/<key>.json` |
| Record book: top/bottom 10 of **every** numeric column on 12 sheets, filterable | `#/records/<sheet>` | `data/records/<sheet>.json` |
| Head-to-head matrix (all / regular season / postseason) | `#/h2h` | `data/h2h.json` |
| Trade history with each side's KTC difference at the deal, season end, +1 and +2 years, impact score, wins added, net points | `#/trades` | `data/trades.json` |
| Draft history (rookie; startup & vet picks) | `#/draft` | `data/draft.json` |
| Search (players, teams; links into the record book for stat names) | `#/search/<q>` | `data/search.json` |

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

- Output: 733 JSON files, 5.3 MB raw (6.5 MB on disk with docs/ and the shell); 0.6 MB gzipped.
  Pages serves gzip. A page view loads `meta.json` + `search.json` (~70 KB) plus that page's file;
  the largest single file is `records/team_week.json` (449 KB raw).
- Build time: ~14 s without the forecast, ~60 s with it (20,000 sims) on an idle laptop.

## Privacy

Inputs are an allow-list: the exports (already public in this repo), the digest email the league
already receives, and the forecast. Nothing under `plan/`, no memory file, no DM / chat export, no
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
