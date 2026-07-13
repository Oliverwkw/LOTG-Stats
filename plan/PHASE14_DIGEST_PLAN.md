# Phase 14 — In-season weekly digest email

Status: **engine + delivery + scheduling landed.** SMTP secrets are the only
thing left before real emails go out. Weekly automated audit is the next sub-PR.

## Behaviour

Two scheduled runs on `build.yml` (Phase 14 owns the canonical weekly pipeline):

- **Tuesday 14:00 UTC (~10am ET)** — build → digest → **email** → rotate the
  ranks snapshot. This is also the weekly exports refresh.
- **Thursday 16:00 UTC (~12pm ET)** — pregame build (fresh rosters/stats before
  TNF). Builds the digest preview but **no email** and **no snapshot rotation**.

Both self-gate to in-season (nothing emails in the offseason). `workflow_dispatch`
has a `send_email` toggle for a manual send.

The digest is **over-inclusive**: it auto-discovers *every* numeric column across
the ranked sheets — no hand-curated "headline" list — and reports two kinds of
change:

1. **All-time crossings** (`player_all_time`, `team_all_time`). For every numeric
   column, watch the top/bottom `WINDOW` (=5) of the leaderboard and report when
   an entity crosses another there, by diffing this week's snapshot vs last
   week's. *"Kyler Murray passes JJ McCarthy for 4th-lowest Points all-time (-0.4)."*
2. **Yearly on-pace** (`player_year`, `team_year`, `league_year`). For every
   numeric column, project the in-progress season to a full-season pace and rank
   it against every completed season. Cumulative stats scale by weeks played;
   rate/level stats carry as-is. *"Oliverwkw is on pace for 4th-highest Hardship
   this season (128)."* **Withheld until week 3** (too little signal earlier).

**Only changes are reported.** All-time crossings are inherently sparse (all-time
values barely move week to week). On-pace standings ARE also diffed week over
week — a team that's still "on pace for 3rd" is silent; only entrants and rank
moves print. That's what keeps an over-inclusive digest readable: a realistic
week is ~a few dozen lines, not the ~900 standings tracked. The first week that
carries on-pace data baselines silently.

## Files

- `lib/lotg_support/digest.py` — pure engine: `discover_numeric_columns`,
  `rank_column`, `build_snapshot`, `diff_snapshots` (crossings),
  `project_on_pace` + `pace_rank_map` + `diff_pace` (on-pace changes),
  `phrasing_catalog`, `render_digest_html`. No network / email.
- `scripts/build_digest.py` — CLI: reads `exports/` + prior snapshot, writes
  `exports/raw/weekly_digest.html`, rotates `data/digest/ranks_snapshot.json`;
  in-season gate; `--force`; `--phrasing-csv PATH`.
- `scripts/send_digest.py` — SMTP send from `config/digest.yaml` recipients +
  `SMTP_USERNAME`/`SMTP_PASSWORD` env. Safe no-op when HTML is missing, the
  digest is empty (`--skip-empty`), or creds are absent.
- `config/digest.yaml` — recipients (`okeimweiss@gmail.com`, extensible) +
  non-secret sender settings.
- `plan/phase14_phrasing.csv` — the "how every stat is phrased if it changes"
  catalog (431 stats: sheet, scope, scale, rise/fall phrasing). Regenerate with
  `build_digest.py --phrasing-csv`.
- `tests/test_digest.py` — discovery, both-end crossings, small-board window cap,
  week-3 gate, projection ranking (cumulative vs rate), pace-diff, phrasing,
  render, real-exports smoke.

## Design notes

- **In-season gate = `weeks_completed >= 1`**, counted from distinct `team_week`
  weeks (the build only writes a `team_week` row once a week is final).
- **Window cap** = `min(WINDOW, n//2)` so the top/bottom ends never overlap on
  the 8-team league (a mid-table swap would otherwise report at both ends).
- **Snapshot rotation** commits `data/digest/ranks_snapshot.json` only on the
  Tuesday send run, so consecutive emails diff exactly one week apart. Thursday
  rebuilds it locally but never commits it.
- **Rate vs cumulative** classification (`is_rate_stat`) drives projection
  scaling and is surfaced per-column in the phrasing CSV so edge calls (e.g.
  "Tanking") can be reviewed and corrected.

## Setup required before emails send

- Add repo secrets `SMTP_USERNAME` + `SMTP_PASSWORD` (a Gmail account + app
  password, or another SMTP provider — override host/port via `SMTP_HOST`/`PORT`
  env or `config/digest.yaml`). Until then the send step logs a skip and the
  pipeline stays green.

## Remaining (next sub-PRs)

- [ ] **Weekly automated 3-part audit** workflow (surface UNEXPECTED diffs /
      schema breaks / non-2026 build errors on a weekly cron).
- [ ] **Injury-tracker coverage report** (Phase 12 #41) — needs 2026 in-season data.
- [ ] Review `plan/phase14_phrasing.csv` and prune / reword any stats whose
      change-phrasing isn't wanted (e.g. adjust the rate/cumulative call).
- [ ] **3-part audit** once a real in-season build + email round-trip exists.
