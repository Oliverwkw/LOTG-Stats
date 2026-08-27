# CLAUDE.md

Orientation for a session working in this repo.

## What this is

A cloud-only pipeline that pulls the league's history from Sleeper (plus an ESPN
backfill for 2020) and exports it as the CSV/Excel tables described in
`plan/LOTG Plan - Sheet1.csv`. It runs on GitHub Actions; there is no local
setup. `python -m lotg` (`src/lotg.py`) is the build; `lib/lotg_support/` holds
its supporting modules; `exports/` holds the committed outputs and the raw
Sleeper snapshot they are built from.

## Two kinds of work — know which one you are doing

**Build changes** — anything that alters what `python -m lotg` produces. These
follow the phase workflow and the mandatory 3-part audit in
`plan/MASTER_TODO.md`. Read that before changing build code.

**Inquiries** — questions answered *from* the committed data ("who has the most
X", "would Y still have won without that trade"). These are read-only: they must
not change `exports/`, `data/`, the workflows, or any build output.

**An inquiry is answered in chat, fast — then you ask.** Target under 3 minutes
to the number itself, scratch script and all. The note in `plan/notes/`, the new
helper in `lib/`, the tests and the PR are a *second phase* that starts only
when the asker says they want it. Do not open a PR for a question. (`pip install
pandas` is the one setup step; skip `requirements.txt`, it pulls ortools.)

**The 3 minutes is a target; accuracy is the constraint.** They rarely conflict
— the playbook's accuracy floor (read the trap list, reconcile against a build
number where one exists, state what is unverified, keep the caveats) costs
seconds, because what's expensive is *proving* an answer to the next reader, not
getting it right. Where they do conflict, take the extra minute and say why.

**Start an inquiry at `plan/INQUIRY_PLAYBOOK.md`.** It documents the tools that
exist for exactly this — `scripts/inquire.py` for finding/filtering/ranking
across the thirteen export sheets and the raw snapshot (including over-inclusive
sweeps that rank on every column rather than a curated few), `lotg_support.analysis`
for the joins a judgement question needs (position attached to any sheet, roster
depth, lineup composition, cohort tests, positional scarcity, spend vs return),
and `scripts/whatif.py` for counterfactual seasons — and it lists the data traps
that have cost time before (the +5 semifinal bonus baked into `PF`, 2020 having no snapshot, the
lineup template and playoff calendar changing between seasons, position drift in
Sleeper's current-only player dictionary). Do not hand-roll a loader over
`exports/` or `exports/snapshot/` before reading it.

## Conventions

- Answers and analyses are written up as notes in `plan/notes/` **once asked
  for**. Reusable logic goes in `lib/lotg_support/` with a test in `tests/`; a
  script in `scripts/` is a thin CLI over it.
- **If an inquiry needs a helper that does not exist yet, offer to add it** —
  answer the question first, then build it if they want it, as its own PR,
  additive only, changing no build output. `plan/INQUIRY_PLAYBOOK.md` has the
  rules and the pre-PR checklist ("When the helper you need does not exist").
  Once you are building it, put it in `lib/`, not in a throwaway script the next
  session cannot find.
- **Report over-inclusively**: flag every borderline item and classify it
  (by-design / needs-human-judgment / defect) rather than filtering quietly.
  This is the standing rule for the audits, the weekly digest and inquiries
  alike.
- Tests are plain functions runnable both under `pytest tests/` (what CI runs)
  and directly as `python tests/test_x.py`. Data-dependent tests skip cleanly
  when `exports/` is absent and assert only against **completed** seasons.
- Never commit regenerated `exports/` from a local run — CI owns those. The
  offline build (`scripts/offline_build.py`) is a smoke test, not a source of
  truth (see the warning at the top of `plan/MASTER_TODO.md`).
