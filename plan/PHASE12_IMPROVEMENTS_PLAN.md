# Phase 12 — Selected improvements: scoped PR plan

17 user-selected improvements + 4 infra, plus the picks-column cleanup. Each PR
gets a periodic 3-part audit; after they all land, re-run the full 9-part audit
until clean. **Order: foundation → new columns → data quality → visual/UX last**
(styling after the columns settle, mirroring Phase 11).

## i0 — Picks column cleanup ✅ (#265, open)
Trade 11+ now contiguous after Trade 10; blank `etc` spacer removed.

## i1 — Infra foundation (42, 43, 45, 49) — do FIRST
Foundational so the rest is auto-audited + deterministic.
- **42 Round all float outputs** at write time (generalize the Luck `round(6)` to every numeric column) → kills residual float-noise diffs.
- **43 Promote audit battery to committed tests**: sanity-range suite (win% ∈ [0,1], efficiency ≤ 1, no negative counts, plausible ages, Σ ≥ component), N/A-vs-0 suite (every `_preserve_na` col renders N/A on no-data / 0 on real zero), edge-case suite (multi-team, byes, 2026 gates).
- **45 Build-time data-quality log**: emit the sanity-range / anomaly summary into `build_debug.log` every run.
- **49 CI test step**: run coverage + reconciliation + freshness + the new suites on every build (the test job that's been manual).
Likely 2 PRs: (42+45) output/log, (43+49) tests/CI.

## i2 — Clutch index (9) — team_all_time only
Regular-season vs playoff PF & win% delta per manager (how much better/worse in the postseason). N/A for teams with no playoff games.

## i3 — Consistency rank (10) — player_year + player_all_time
Position-adjusted league-wide **percentile** of each player's scoring volatility / floor / ceiling (already have the raw volatility/floor/ceiling from PR C; this adds the ranked percentile vs same-position peers). N/A for never-started.

## i4 — 3-year retention rate (16) — team_year + team_all_time
% of a team's drafted capital (picks they made) **still on roster after N=3 years**, measured at **start-of-year**, **excluding returners**. Walk pick→player→tenure at the +3yr anchor.

## i5 — Trade lineage string (15)
One readable chain per current asset: `2021 1.04 → … → 2026 1st`. Built from the pick/player chains already computed; a display string column (picks and/or trades sheet). Decide host sheet during build.

## i6 — Data quality (35–41) — batch, mostly checks/flags
- **35 Backfill missing birth_dates** from a secondary source (finish the Age coverage started by Bug #2).
- **36 Position-switcher audit** (Taysom Hill etc.) — verify weekly position is right; fix or flag.
- **37 NFL-team-per-week validation** vs schedule for traded players.
- **38 Dedup near-identical name variants** ("AJ" vs "A.J.") across sources.
- **39 KTC confidence flag** for values sourced from sparse pre-2021 history.
- **40 Sleeper-vs-nflverse points cross-check** — effectively folded into Bug #5; **confirm + close** (likely no new column).
- **41 Injury-tracker coverage report** — deferred until 2026 in-season data lands (note; revisit Phase 14).
Split: 35/38 (identity/data), 36/37 (position/team validation), 39 (flag). 40/41 are confirm/defer.

## i7 — Visual / xlsx UX (26–34) — LAST (styling after columns settle)
- **27 Hyperlink team names → team_all_time** — opponent / counterparty cells only.
- **28 Hyperlink pick labels in trades → picks sheet.**
- **32 Header tooltips/comments** pulling the Formulas-sheet definition.
- **30 Conditional highlight** of all-time records (highs/lows) in their cells.
- **33 Color "In Progress" streak cells** subtly so active runs stand out.
- **34 Subtle two-tone bands** within topic groups on wide sheets.
- **26 Sparklines** for weekly PF / player PPG trends.
Batch into ~2–3 styling PRs (hyperlinks; conditional-format/color; sparklines).

## After all land
Re-run the full **9-part audit** (`plan/AUDIT_PHASE12.md`) until every part is clean.
