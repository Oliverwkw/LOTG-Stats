"""Ask what a real-world NFL contract predicts about fantasy production.

A thin command line over `lotg_support.contracts`. It reads Over The Cap's
contract history (via nflverse) and the build's own nflverse weekly stats,
prints, and changes nothing: no export, no workflow, no build output. The only
thing it writes is the nflverse download cache under `.cache/`.

    # the answer: big signings vs matched players who did not get paid
    python scripts/contract_study.py study
    python scripts/contract_study.py study --top-n 3 --min-years 3

    # the misleading version everyone quotes: signers against themselves
    python scripts/contract_study.py raw

    # is it rate or role? does a bigger deal say more? does it hold every year?
    python scripts/contract_study.py decompose
    python scripts/contract_study.py dose
    python scripts/contract_study.py years

    # who the big deals actually were
    python scripts/contract_study.py signings --year 2025
    python scripts/contract_study.py signings --position WR --top-n 5

    # the guards that tie this to numbers the build already published
    python scripts/contract_study.py validate

Needs `pyarrow` (the maintained contracts asset is parquet; the csv on that
release has been frozen since 2022) and network access on first run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from lotg_support import contracts as C  # noqa: E402


def _study(args) -> C.ContractStudy:
    return C.study(top_n=args.top_n, rank_from=args.rank_from,
                   first_year=args.first_year, last_year=args.last_year,
                   scoring=args.scoring, k=args.k, caliper_sd=args.caliper,
                   age_caliper=(None if args.no_age else args.age_caliper),
                   min_baseline_games=args.min_games, min_years=args.min_years,
                   seed=args.seed)


def cmd_study(args) -> None:
    result = _study(args)
    print(result.describe(outcomes=("y0_points", "y1_points", "two_year_points")))
    if args.all_outcomes:
        print()
        print(result.summary.to_string(index=False))
    print()
    print("gap = signer minus the mean of his matched controls; positive means the "
          "contract said something last season's stat line had not.")
    if len(result.unmatched):
        print(f"\nunmatched signings ({len(result.unmatched)}) — reported, not hidden; "
              f"they skew to the very top of the market, where nobody comparable "
              f"went unpaid:")
        print(result.unmatched.nlargest(min(10, len(result.unmatched)),
                                        "base_points").to_string(index=False))


def cmd_raw(args) -> None:
    print("signers against THEMSELVES — no control group, so this is mostly "
          "regression to the mean:")
    print(C.raw_before_after(top_n=args.top_n, first_year=args.first_year,
                             last_year=args.last_year, scoring=args.scoring
                             ).to_string(index=False))


def cmd_decompose(args) -> None:
    result = _study(args)
    keep = ("y0_games", "y1_games", "y0_ppg", "y1_ppg",
            "y0_startable", "y1_startable")
    print("did the contract buy games or points per game?")
    print(result.summary[result.summary["outcome"].isin(keep)].to_string(index=False))


def cmd_dose(args) -> None:
    result = _study(args)
    print("two-year gap by how big the deal was within its position-year:")
    print(C.dose_response(result.matched).to_string(index=False))


def cmd_years(args) -> None:
    result = _study(args)
    table = C.by_signing_year(result.matched)
    print("two-year gap, one signing class at a time (a pooled gap carried by two "
          "classes is not a finding):")
    print(table.to_string())
    print()
    print("share of signing years with a positive gap:")
    print((table > 0).mean().round(2).to_string())


def cmd_signings(args) -> None:
    frame = C.signings(first_year=args.first_year, last_year=args.last_year)
    frame = frame[frame["rank_in_position_year"] <= args.top_n]
    if args.position:
        frame = frame[frame["position"] == args.position.upper()]
    if args.year:
        frame = frame[frame["year_signed"] == args.year]
    columns = ["player", "position", "team", "year_signed", "years", "apy",
               "apy_cap_pct", "guaranteed", "rank_in_position_year"]
    frame = frame.sort_values(["year_signed", "position", "rank_in_position_year"])
    print(frame[columns].to_string(index=False))


def cmd_validate(args) -> None:
    problems = C.validate()
    if not problems:
        print("all guards pass: re-scored points reproduce the build's own season "
              "totals, the big signings join to real seasons, and the matched "
              "cohorts are balanced at baseline")
        return
    for p in problems:
        print(f"FAIL {p}")
    sys.exit(1)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-n", type=int, default=C.BIG_CONTRACT_TOP_N,
                        help="'big' = top N deals at the position that year")
    parser.add_argument("--rank-from", type=int, default=1,
                        help="lowest rank to include (6 with --top-n 10 = the second tier)")
    parser.add_argument("--first-year", type=int, default=C.FIRST_SIGNING_YEAR)
    parser.add_argument("--last-year", type=int, default=None)
    parser.add_argument("--scoring", choices=list(C.SCORING), default="lotg")
    parser.add_argument("-k", type=int, default=C.MATCH_K, help="controls per signer")
    parser.add_argument("--caliper", type=float, default=C.MATCH_CALIPER_SD,
                        help="control's prior points must be within this many sd")
    parser.add_argument("--age-caliper", type=float, default=C.MATCH_AGE_CALIPER)
    parser.add_argument("--no-age", action="store_true",
                        help="match on production alone, ignoring age")
    parser.add_argument("--min-games", type=int, default=C.MIN_BASELINE_GAMES)
    parser.add_argument("--min-years", type=float, default=None,
                        help="drop deals shorter than this (3 = no tags/prove-it years)")
    parser.add_argument("--position", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--all-outcomes", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("study", cmd_study), ("raw", cmd_raw),
                     ("decompose", cmd_decompose), ("dose", cmd_dose),
                     ("years", cmd_years), ("signings", cmd_signings),
                     ("validate", cmd_validate)):
        sub.add_parser(name, help=fn.__doc__).set_defaults(func=fn)
    args = parser.parse_args(argv)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 400)
    args.func(args)


if __name__ == "__main__":
    main()
