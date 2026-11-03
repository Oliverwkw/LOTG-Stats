# Reproducibility, size and speed (2026-11-03: PRs #548-#551, the snapshot-JSON PR, the history rewrite)

Every change below was proven output-identical: each branch build's 15 export CSVs, 6 raw CSVs
and digest HTML were byte-identical to a same-day main-code build. The xlsx differed only in its
`docProps/core.xml` timestamp. Each PR had a post-merge main build and a 3-part audit against the
last pre-merge main run (#548 vs run 812, #549 vs 41724219832, #550 vs 41726205019, #551 vs
41729646657): all CSVs identical, 0 failed tests, 0 build errors.

## Before / after

| | Before | After |
|---|---|---|
| Packages that can float in CI | 25 of 31, in all 10 workflows that install | 0. `requirements.lock` is every workflow's constraints file; `tests/test_environment.py` fails CI on any drift or unlocked package |
| pandas 2 vs 3 dtype traps | caught by luck (memory `ci-runs-pandas3`) | `tests/test_dtype_checks.py` bans new `dtype == object` checks |
| What a build ran on | unknown | `raw/pip_freeze.txt` and `raw/inputs_manifest.json` (sha256 of ~430 inputs) in every artifact |
| Reproduce a past build | by hand | `scripts/reproduce_exports.py --run ID / --commit REF / --date D [--rebuild] / --diff A B` |
| Offline harness scope | folklore | docstring + `tests/test_offline_scope.py` |
| Clone / pack | 765 MiB, 1 min 49 s | **84 MiB, 5.9 s** (history rewrite, below) |
| Repo growth per month | ~106 MB, 66 MB of it the player dictionary | ~40 MB. The dictionary is ~0.1 MB/month, and every snapshot JSON is key-sorted, so a file changes only when its data does (48 past weeks' files used to churn on each export commit) |
| Binary blobs on main | 7 ffopportunity `.gz` (guard red since run 812) | 0. Cached as plain CSV |
| Branch-run artifacts | 90 days (9.3 GB across 324 `LOTG_outputs`) | 14 days; main keeps 90 |
| `snapshot_all` network | 39 s in the cProfile; the same 255 GETs = 43.3 s measured | 1.7 s measured (keep-alive + seasons in parallel), identical responses |
| Build step | median 353 s (31 runs, Oct 23 - Nov 3) | 373-413 s on the evening of Nov 3 for builds both before and after #551 (slow runners). The ~40 s network saving is measured directly; CI wall time can't show it under that noise |
| Test step | median 317 s | 348-399 s the same evening; no CI-visible change (the BLAS pin is output-identical but not proven faster) |

## Where the time goes (cProfile, run 41670756117)

Build: boldness expectations ~102 s, `write_outputs` 99 s (Excel save 40 s), Wins added 54 s,
network 43 s (~20 s of it TLS handshakes: fixed), `snapshot_all` 39 s (fixed), and pandas-3
Arrow-string element access spread through the boldness loops (~43 s). That last one is the
next lever if the build needs more speed; prove it equal per memory `build-speed-levers`.

Tests: ~930 s of test time over 4 xdist workers, already balanced by worksteal. The only lever
left is CPU per test: boldness 152 s, forecast 144 s, expectation recheck 120 s.

Inquiry CLIs (local): `fast.py` 1.4-1.9 s; `advise.py startsit` 10.8 s cold, 4.5 s warm. All are
inside CLAUDE.md's targets.

## Drift vs nondeterminism

Three builds of the same code within 35 minutes wrote byte-identical CSVs. The variation left is
legitimate:
- upstream data: Sleeper live, nflverse revisions, KTC quotes. These are now attributable with
  `reproduce_exports.py --diff`.
- the clock: tenure, KTC anniversaries, the workbook timestamp.

Avoidable churn found and removed: Sleeper reorders the keys inside records between fetches (the
player dictionary, plus transactions' and matchups' nested dicts). The snapshot writer now
sorts keys; lists keep Sleeper's order.

Sleeper now returns `drops = None` on every failed waiver claim. The cached 2021-25 copies kept
190 of those intended drops. No stat uses them, so the user decided to leave it.

## History rewrite (done with the user's go-ahead)

Done 2026-11-03 ~23:30 UTC, in a window with no workflow running and no open PR. `git filter-repo`
ran on all 34 branches:
- dropped the retired `exports/LOTG_Exports.zip`, `exports/LOTG_Stats.xlsx` and
  `LOTG_Cloud_Tracker_v28.zip` (484 MB of history, gitignored since #420/#428);
- re-wrote every old `exports/snapshot/sleeper_players_nfl.json` in the canonical field order
  (same values, same player order).

Verified before the force-push:
- main's tree hash is unchanged (`d549092b2588`), so every file at HEAD is byte-identical;
- on all 34 branch tips, every other file is identical and the dictionary is deep-equal in the
  same order;
- `git fsck` is clean;
- main went from 1010 to 1009 commits (one commit that only touched the zip became empty).

Pack: 757 -> 71 MiB locally, 84 MiB as GitHub serves it; clone 1 min 49 s -> 5.9 s. The
post-rewrite main build (41738338421) committed its exports onto the new history normally.
GitHub's own `diskUsage` figure keeps the old objects until GitHub garbage-collects them, because
closed PRs' `refs/pull/*` still point at old commits. Clones never fetch those.

Every commit SHA changed. `plan/notes/history_rewrite_2026-11-03_commit_map.txt` maps old -> new,
for translating SHAs quoted in notes, memory, PR bodies and `built_from_commit`. A checkout made
before the rewrite must re-sync: `git fetch origin`, then `git reset --hard origin/main` on a
clean main, and re-create any other branch from `origin/<name>`.
