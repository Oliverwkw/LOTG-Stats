# Phase 14 — In-season weekly digest email

Status of this sub-PR: **engine + CLI + tests landed.** Delivery (recipients /
provider) and the cron workflow are the next sub-PRs — see "Remaining" below.

## What shipped in this sub-PR

The delivery-independent **data core** of the Tuesday digest, so it can be
built and verified offline before any email plumbing exists.

- `lib/lotg_support/digest.py` — pure logic:
  - **Rankings.** Curated headline all-time stats for players (`PLAYER_STATS`)
    and teams (`TEAM_STATS`), each declaring which end(s) of the leaderboard to
    watch (`high` / `low`) and its human label. Adding a row is the only change
    needed to extend coverage.
  - **Snapshot.** `build_snapshot()` reads the built CSVs, computes ordered
    rankings (rank = list position), and stamps meta (`season`,
    `weeks_completed`, `captured_at`).
  - **Diff -> narratives.** `diff_snapshots(prev, curr)` detects leaderboard
    *crossings* within the top/bottom-N window of each stat and renders them as
    sentences ("BROsenzweig (305) overtakes shmuel256 for 3rd-highest all-time
    Max PF"). Only entities present in *both* snapshots that actually flipped
    order are reported — new entities never generate a false "pass".
  - **On-pace projections.** `project_end_of_season()` linearly extrapolates a
    team's in-progress cumulative pace (scaled by weeks completed vs the
    full-season horizon learned from completed seasons) and ranks the
    projection against every completed season ("Oliverwkw is on pace for
    4th-highest yearly hardship").
  - **Render.** `render_digest_html()` assembles the three sections into an
    inline-styled HTML body.
- `scripts/build_digest.py` — CLI: reads `exports/` + the prior snapshot,
  writes `exports/raw/weekly_digest.html` and rotates
  `data/digest/ranks_snapshot.json`. Honors the **in-season gate** (skips in the
  offseason so the first in-season run has a clean baseline); `--force` builds
  anyway.
- `tests/test_digest.py` — ranking order, high/low crossing detection, stable
  board = no crossings, new-entity guard, in-season gate, projection ranking,
  HTML render, plus a real-exports smoke test (SKIP-safe with no build).

## Design notes

- **In-season gate = `weeks_completed >= 1`.** `weeks_completed` counts distinct
  `team_week` weeks for the current season. The build only writes a `team_week`
  row once a week is final (Phase 5E freshness gate), so this is a faithful
  "games played" signal. 2026 currently has placeholder `team_year` rows but
  zero `team_week` rows -> correctly reads offseason and skips.
- **Snapshot rotation.** The digest diffs *this* week against *last* week, so
  the snapshot must persist between runs. It lives at
  `data/digest/ranks_snapshot.json` and the CLI rewrites it only on a real
  in-season build (offseason leaves it untouched).
- **Crossing semantics.** For the `high` end, an entity is reported when its
  rank improved and it now sits directly ahead of an entity that used to be
  ahead of it. For the `low` end, the mirror (an entity that fell past a
  neighbour toward the bottom). One sentence per mover per end.
- **Projection horizon** is the max week seen in a completed prior season
  (data-driven, not a hardcoded 14/17), so it adapts to schedule changes and
  the 2020 ESPN 16-week season.

## Remaining (next sub-PRs)

- [ ] **Delivery.** Recipients + provider are TBD (user to specify). A thin send
      step reads `exports/raw/weekly_digest.html` and mails it — no engine
      change. Needs: recipient list, SMTP/provider secret.
- [ ] **Cron workflow** (`weekly_digest.yml`): Tuesday ~10am ET, in-season only,
      `workflow_dispatch` fallback. Runs *after* the build, builds the digest,
      commits the rotated snapshot back (like `build.yml`'s exports commit), and
      sends. Skip weeks with no newly-completed games since the last snapshot.
- [ ] **Weekly automated audit** (separate workflow): run the 3-part audit
      harness against the latest build on a weekly cron; surface UNEXPECTED
      diffs / schema breaks / non-2026 build errors (email or log).
- [ ] **Injury-tracker coverage report** (Phase 12 #41, deferred here) — needs
      2026 in-season data.
- [ ] **3-part audit** (code / results / diff) once delivery + cron are wired
      and a real in-season build exists.
