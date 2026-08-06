"""Replay a season as if a roster move had gone differently.

A command line over `lotg_support.replay`. Read-only: it prints a report and
writes nothing. Nothing in the build imports it and no workflow runs it.

    # the question that motivated this: does shmuel256 still win 2025 without
    # the Herbert-for-Jackson trade?
    python scripts/whatif.py --season 2025 --undo-trade-player 'Justin Herbert'

    # bracket the lineup assumption with all three models
    python scripts/whatif.py --season 2025 --undo-trade-player 'Justin Herbert' --model all

    # several trades rewound together — a teardown is not one trade, and undoing
    # them one at a time understates the combined effect
    python scripts/whatif.py --season 2024 --model all \
        --undo-trade-id 1090497154780581888 --undo-trade-id 1092268177528127488 \
        --undo-trade-id 1095772841745821696 --undo-trade-id 1117973026936573952 \
        --undo-trade-id 1152469543118536704

    # an arbitrary move: this player on that roster instead, from week 9 on
    python scripts/whatif.py --season 2024 --move '4881:5->8@9'

    # what trades are there to rewind?
    python scripts/inquire.py trades --season 2025

Before answering, the guards run (real lineups legal under the season's slot
template; the ceiling routine reproduces the built `Max PF`; a no-move replay
reproduces the real PF, bracket and champion). A counterfactual whose baseline
cannot reproduce reality is not evidence, so a guard failure stops the run
unless you pass `--skip-guards` deliberately.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import inquiry as Q  # noqa: E402
from lotg_support import replay as R  # noqa: E402

_MOVE_RE = re.compile(r"^\s*(?P<player>[^:]+):(?P<from>\d+)\s*->\s*(?P<to>\d+)(?:@(?P<week>\d+))?\s*$")


def parse_move(text: str, season: int) -> R.Move:
    """'<player>:<from_roster>-><to_roster>[@week]', player as an id or a name."""
    m = _MOVE_RE.match(text)
    if not m:
        raise SystemExit(f"cannot parse --move {text!r}; expected e.g. \"4881:5->8@9\"")
    who = m.group("player").strip()
    try:
        pid = Q.players().resolve(who)
    except (KeyError, FileNotFoundError) as exc:
        raise SystemExit(f"--move {text!r}: {exc}")
    return R.Move(player_id=pid, from_roster=int(m.group("from")),
                  to_roster=int(m.group("to")), from_week=int(m.group("week") or 1))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--undo-trade-player", action="append", default=[], metavar="NAME",
                    help="rewind the completed trade that involved this player (repeatable: "
                         "several are rewound together, which is what a teardown needs)")
    ap.add_argument("--undo-trade-date", metavar="YYYY-MM-DD",
                    help="narrow a single --undo-trade-player (use when a player has several); "
                         "to rewind several trades at once name them by --undo-trade-id")
    ap.add_argument("--undo-trade-id", action="append", default=[], metavar="TXN_ID",
                    help="rewind the trade with this transaction id (repeatable)")
    ap.add_argument("--move", action="append", default=[], metavar="SPEC",
                    help="explicit move '<player>:<from>-><to>[@week]' (repeatable)")
    ap.add_argument("--from-week", type=int, default=1,
                    help="first week an undone trade takes effect (default 1)")
    ap.add_argument("--model", default="anchored",
                    choices=list(R.MODELS) + ["all"],
                    help="lineup model; 'all' runs each and shows where they disagree")
    ap.add_argument("--weekly", action="store_true", help="print every score that moves")
    ap.add_argument("--skip-guards", action="store_true",
                    help="skip the correctness guards (not recommended)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if not args.undo_trade_player and not args.move and not args.undo_trade_id:
        raise SystemExit("nothing to change: pass --undo-trade-player, --undo-trade-id or --move")

    if not args.skip_guards:
        problems = R.validate(args.season)
        if problems:
            print(f"GUARDS FAILED for {args.season} — the baseline replay does not reproduce "
                  "the built season, so a counterfactual off it would not be evidence:\n")
            for line in problems[:20]:
                print(f"  {line}")
            return 1
        print(f"guards OK for {args.season}: real lineups legal, Max PF reproduced, "
              "no-move replay matches the built PF / bracket / champion.\n")

    if args.undo_trade_date and len(args.undo_trade_player) > 1:
        raise SystemExit("--undo-trade-date narrows one --undo-trade-player; with several "
                         "players, name the trades by --undo-trade-id instead")

    try:
        if args.undo_trade_date:
            scenario = R.undo_trade(args.season, player=args.undo_trade_player[0],
                                    date=args.undo_trade_date, from_week=args.from_week)
        elif args.undo_trade_player or args.undo_trade_id:
            scenario = R.undo_trades(args.season, players=args.undo_trade_player,
                                     transaction_ids=args.undo_trade_id,
                                     from_week=args.from_week)
        else:
            scenario = R.Scenario(season=args.season, moves=(), label="custom moves")
        extra = tuple(parse_move(spec, args.season) for spec in args.move)
        if extra:
            scenario = R.Scenario(season=scenario.season, moves=scenario.moves + extra,
                                  model=scenario.model,
                                  label=scenario.label or "custom moves")
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    models = list(R.MODELS) if args.model == "all" else [args.model]
    results = []
    for model in models:
        result = R.replay(scenario.with_model(model))
        results.append(result)
        print(R.render(result, weekly=args.weekly))
        print()

    if len(results) > 1:
        champs = {r.scenario.model: r.bracket.champion for r in results}
        flips = {r.scenario.model: len(r.flips) for r in results}
        print("=" * 78)
        print("MODEL SENSITIVITY")
        print("=" * 78)
        for model in models:
            print(f"  {model:<9} champion {champs[model]:<18} {flips[model]} result(s) flip")
        agree = len(set(champs.values())) == 1
        print(f"\n  the three models {'AGREE' if agree else 'DISAGREE'} on the champion"
              + ("" if agree else " — report the disagreement, do not pick one"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
