"""Replay league history (and forecast this season) under a proposed rule change.

A command line over `lotg_support.rules`. Read-only: it prints a report and
writes nothing except a spec file when you pass --save. Nothing in the build
imports it and no workflow runs it. Roster/trade counterfactuals are
`scripts/whatif.py`; this is the same idea for the league's RULES.

    # a saved spec (plan/rule_specs/ has examples), every completed season
    python scripts/rulechange.py plan/rule_specs/te_premium.json

    # specs compose left to right; inline flags compose after them
    python scripts/rulechange.py plan/rule_specs/half_ppr.json plan/rule_specs/six_team_playoffs.json

    # inline only, then save it for the league vote
    python scripts/rulechange.py --add bonus_rec_te=0.5 --slots +FLEX --median \
        --name "TE premium + 3rd flex + median" --save plan/rule_specs/proposal.json

    # this season's odds under it too (same seed both ways)
    python scripts/rulechange.py plan/rule_specs/six_team_playoffs.json --forecast

    # seasons, detail, one lineup variant
    python scripts/rulechange.py --set pass_td=6 --seasons 2023-2025 --variant optimal --brief

Scoring flags take any Sleeper key (`--keys` lists them): --set KEY=V, --scale
KEY=M, --add KEY=D, each applied to every season's OWN table. Lineup: --slots
'+FLEX,-SUPER_FLEX' edits each season's template, --slots 'QB,RB,RB,...'
replaces it. Playoffs: --playoff-teams N, --byes N (checked), --home-bonus P,
--home-bonus-round semifinal|all|none, --median / --no-median, --seeding
record|points, --regular-season-weeks N, --two-week-final / --one-week-final.

Before answering, the guards run on the seasons asked for: an empty spec must
reproduce the real records, PF, playoff bracket and champion, and the optimal
routine must reproduce `team_week.Max PF`. A failure stops the run unless
--skip-guards.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import rules as RC  # noqa: E402


def _pairs(items, what):
    out = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--{what} {item!r}: expected KEY=VALUE")
        k, v = item.split("=", 1)
        try:
            out[k.strip()] = float(v)
        except ValueError:
            raise SystemExit(f"--{what} {item!r}: {v!r} is not a number")
    return out


def inline_spec(args) -> dict:
    blob: dict = {}
    scoring = {op: _pairs(getattr(args, op), op) for op in ("set", "scale", "add")}
    scoring = {k: v for k, v in scoring.items() if v}
    if scoring:
        blob["scoring"] = scoring
    if args.slots:
        lineup: dict = {}
        edits = [s.strip() for part in args.slots for s in part.split(",") if s.strip()]
        if all(s[0] in "+-" for s in edits):
            lineup["add"] = [s[1:] for s in edits if s[0] == "+"]
            lineup["remove"] = [s[1:] for s in edits if s[0] == "-"]
        elif any(s[0] in "+-" for s in edits):
            raise SystemExit("--slots: either all edits (+FLEX,-SUPER_FLEX) or a full template")
        else:
            lineup["slots"] = edits
        blob["lineup"] = lineup
    po = {}
    for key, val in (("teams", args.playoff_teams), ("byes", args.byes),
                     ("home_bonus", args.home_bonus), ("home_bonus_round", args.home_bonus_round),
                     ("median_game", args.median), ("seeding", args.seeding),
                     ("regular_season_weeks", args.regular_season_weeks),
                     ("two_week_final", args.two_week_final)):
        if val is not None:
            po[key] = val
    if po:
        blob["playoffs"] = po
    if args.seasons:
        blob["seasons"] = args.seasons
    return blob


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("specs", nargs="*", help="spec JSON files, composed in order")
    ap.add_argument("--name", help="name for the composed scenario")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=V")
    ap.add_argument("--scale", action="append", default=[], metavar="KEY=M")
    ap.add_argument("--add", action="append", default=[], metavar="KEY=D")
    ap.add_argument("--slots", action="append", default=[], metavar="EDITS",
                    help="'+FLEX,-SUPER_FLEX' or a full template 'QB,RB,RB,WR,WR,WR,TE,FLEX,SUPER_FLEX'")
    ap.add_argument("--playoff-teams", type=int)
    ap.add_argument("--byes", type=int)
    ap.add_argument("--home-bonus", type=float)
    ap.add_argument("--home-bonus-round", choices=RC.HOME_BONUS_ROUNDS)
    ap.add_argument("--median", dest="median", action="store_const", const=True, default=None)
    ap.add_argument("--no-median", dest="median", action="store_const", const=False)
    ap.add_argument("--seeding", choices=RC.SEEDINGS)
    ap.add_argument("--regular-season-weeks", type=int)
    ap.add_argument("--two-week-final", dest="two_week_final", action="store_const", const=True,
                    default=None)
    ap.add_argument("--one-week-final", dest="two_week_final", action="store_const", const=False)
    ap.add_argument("--seasons", help="e.g. 2021-2025 or 2020,2024 (default: every completed season)")
    ap.add_argument("--variant", choices=list(RC.VARIANTS) + ["both"], default="both",
                    help="lineups: the managers' real choices, the optimal ones, or both (default)")
    ap.add_argument("--brief", action="store_true", help="skip the per-season tables")
    ap.add_argument("--forecast", action="store_true",
                    help="also forecast the current season under the scenario")
    ap.add_argument("--sims", type=int, default=5000, help="forecast simulations (default 5000)")
    ap.add_argument("--save", metavar="PATH", help="write the composed spec as JSON")
    ap.add_argument("--show-spec", action="store_true", help="print the composed spec JSON and stop")
    ap.add_argument("--keys", action="store_true", help="list the scoring keys that can change")
    ap.add_argument("--skip-guards", action="store_true")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.keys:
        print("\n".join(RC.supported_scoring_keys()))
        return 0
    try:
        parts = [RC.load_spec(p) for p in args.specs]
        inline = inline_spec(args)
        if inline:
            parts.append(RC.spec_from_dict(inline))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    spec = RC.compose(*parts, name=args.name or "")
    if args.save:
        print(f"saved {RC.save_spec(spec, args.save)}")
    if args.show_spec:
        import json
        print(json.dumps(RC.spec_to_dict(spec), indent=2))
        return 0
    if spec.is_empty:
        raise SystemExit("nothing to change: pass a spec file or a rule flag (see --help)")

    seasons = list(spec.seasons or RC.history_seasons())
    if not args.skip_guards:
        checked = [s for s in seasons if s in RC.history_seasons()]
        problems = RC.validate(checked)
        if problems:
            print("GUARDS FAILED — the real-rules replay does not reproduce the built seasons, "
                  "so a rule change measured off it would not be evidence:\n")
            for line in problems[:20]:
                print(f"  {line}")
            return 1
        print(f"guards OK for {', '.join(map(str, checked))}: the real rules reproduce every record, "
              "PF, bracket and champion, and the optimal routine reproduces Max PF.\n")
    try:
        sim = RC.simulate(spec, seasons)
    except (ValueError, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    variants = RC.VARIANTS if args.variant == "both" else (args.variant,)
    print(RC.render(sim, variants=variants, seasons_detail=not args.brief))
    if args.forecast:
        print()
        try:
            print(RC.render_forecast(RC.forecast(spec, sims=args.sims)))
        except (ValueError, LookupError) as exc:
            print(f"forecast unavailable: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
