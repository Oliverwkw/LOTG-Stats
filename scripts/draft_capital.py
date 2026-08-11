"""What a draft slot returns, who gets it, and what moving up costs.

A command line over `lotg_support.draft_capital`. Read-only: it prints and
writes nothing. Nothing in the build imports it and no workflow runs it.

    # what has each slot's whole draft returned? (1.01 owns 2.01/3.01/4.01 too)
    python scripts/draft_capital.py haul
    python scripts/draft_capital.py slots --statistic bust_rate

    # the question tanking actually turns on: is pushing from 4th-worst to
    # worst worth anything, given you are already picking in the bottom four?
    python scripts/draft_capital.py cohorts
    python scripts/draft_capital.py cohorts --metric rate

    # who gets which slot, under each rule — the 2026 draft changed the rule
    python scripts/draft_capital.py order --draft 2026
    python scripts/draft_capital.py order --all

    # under the ceiling rule you cannot buy draft position with losses. what
    # would Oliverwkw have had to shed to hold 1.01 in 2026?
    python scripts/draft_capital.py cost --draft 2026 --team Oliverwkw
    python scripts/draft_capital.py cost --season 2025 --team Oliverwkw --target 2041.12 --regular-season

    # the guards behind all of it
    python scripts/draft_capital.py validate

The guards matter more here than usual, because both halves of this rest on
reproducing the build: `Max PF` recomputed from the snapshot must equal the
built column exactly (it is what the draft order is now set by), and the
ordering rule must reproduce `picks."Original Team"` for every draft that has
happened. A stripping cost computed off a baseline that cannot reproduce the
league's own table is not evidence.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import draft_capital as D  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_METRICS = {"total": D.TOTAL_METRIC, "rate": D.RATE_METRIC}


def _print_frame(df) -> None:
    print(df.to_string())


def cmd_slots(args) -> int:
    metric = _METRICS.get(args.metric, args.metric)
    if args.statistic == "hit_rate":
        table = D.hit_rate(threshold=args.threshold, metric=metric, rounds=args.rounds)
        print(f"share of picks returning more than {args.threshold:g} {metric!r}, by round x slot")
    else:
        table = D.slot_table(metric=metric, rounds=args.rounds, statistic=args.statistic)
        print(f"{args.statistic} of {metric!r}, by round x slot")
    _print_frame(table.round(3))
    for w in D.rookie_picks().warnings:
        print(f"warning: {w}")
    print(f"excluded: {D.rookie_picks().describe_exclusions()}")
    return 0


def cmd_haul(args) -> int:
    metric = _METRICS.get(args.metric, args.metric)
    table = D.haul_table(metric=metric, rounds=args.rounds)
    print(f"mean {metric!r} per pick, by slot x round, with the slot's whole-draft total")
    _print_frame(table.round(1))
    print("\nread TOTAL as what owning a draft position has been worth across all "
          f"{args.rounds} rounds — not the first round alone")
    return 0


def cmd_cohorts(args) -> int:
    metric = _METRICS.get(args.metric, args.metric)
    result = D.slot_cohorts(metric=metric, rounds=args.rounds,
                            permutations=args.permutations, aggregate=args.aggregate)
    print(result.describe())
    return 0


def cmd_order(args) -> int:
    drafts = D.checkable_drafts() if args.all else [args.draft]
    for draft_year in drafts:
        print(f"=== {draft_year} draft (rule in force: {D.order_rule(draft_year)}) ===")
        _print_frame(D.order_comparison(draft_year))
        print(f"  observed slots 1.01-1.04: {D.observed_order(draft_year)[:D.BOTTOM]}")
        print(f"  playoff block 1.05-1.08 (observed, not modelled): {D.playoff_block(draft_year)}")
        problems = D.check_bottom_four_order_matches_picks(draft_year)
        print("  guard: " + ("OK" if not problems else "; ".join(problems)))
        print()
    return 0


def cmd_cost(args) -> int:
    weeks = (list(range(1, Q.season_meta(args.season or args.draft - 1).regular_season_weeks + 1))
             if args.regular_season else None)
    if args.target is not None:
        season = args.season or args.draft - 1
        result = D.ceiling_cost(season, args.team, target=args.target,
                                max_steps=args.max_steps, weeks=weeks)
    else:
        result = D.cost_to_pick_first(args.draft, args.team,
                                      weeks=weeks, max_steps=args.max_steps)
    print(result.describe())
    return 0


def cmd_validate(args) -> int:
    results = D.validate(seasons=[args.season] if args.season else None)
    failures = 0
    for name, problems in results.items():
        if problems:
            failures += 1
            print(f"FAIL {name}")
            for p in problems[:10]:
                print(f"       {p}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(results) - failures}/{len(results)} guards clean")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("slots", help="round x slot table of what picks returned")
    p.add_argument("--metric", default="total", help="total | rate | any picks column")
    p.add_argument("--rounds", type=int, default=D.HAUL_ROUNDS)
    p.add_argument("--statistic", default="mean",
                   help="mean | median | bust_rate | hit_rate")
    p.add_argument("--threshold", type=float, default=300.0, help="for --statistic hit_rate")
    p.set_defaults(func=cmd_slots)

    p = sub.add_parser("haul", help="what a slot's WHOLE draft returned, all rounds")
    p.add_argument("--metric", default="total")
    p.add_argument("--rounds", type=int, default=D.HAUL_ROUNDS)
    p.set_defaults(func=cmd_haul)

    p = sub.add_parser("cohorts", help="bottom-four vs playoff, and pushed vs already-bottom")
    p.add_argument("--metric", default="total", help="total | rate | any picks column")
    p.add_argument("--rounds", type=int, default=D.HAUL_ROUNDS)
    p.add_argument("--permutations", type=int, default=20000)
    p.add_argument("--aggregate", default="auto", choices=["auto", "haul", "pick"],
                   help="unit of observation; a rate column must use 'pick'")
    p.set_defaults(func=cmd_cohorts)

    p = sub.add_parser("order", help="bottom-four draft order under each rule")
    p.add_argument("--draft", type=int, default=max(D.checkable_drafts()))
    p.add_argument("--all", action="store_true", help="every draft on record")
    p.set_defaults(func=cmd_order)

    p = sub.add_parser("cost", help="what a roster must shed to reach a target Max PF")
    p.add_argument("--team", required=True)
    p.add_argument("--draft", type=int, default=max(D.checkable_drafts()),
                   help="target defaults to whoever actually held 1.01 in this draft")
    p.add_argument("--season", type=int, help="season whose roster is stripped (default: draft - 1)")
    p.add_argument("--target", type=float, help="explicit Max PF target instead")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--regular-season", action="store_true",
                   help="regular-season weeks only (the default is the full season, "
                        "matching the built Max PF column)")
    p.set_defaults(func=cmd_cost)

    p = sub.add_parser("validate", help="run every guard")
    p.add_argument("--season", type=int)
    p.set_defaults(func=cmd_validate)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
