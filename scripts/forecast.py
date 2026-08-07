"""Championship odds for a season that has not finished yet.

A command line over `lotg_support.forecast`. Read-only: it prints a report and
writes nothing. Nothing in the build imports it and no workflow runs it.

    # the question that motivated this: % chance of each team winning this year
    python scripts/forecast.py --season 2026

    # what injuries, depth, age and this rookie class are actually doing
    python scripts/forecast.py --season 2026 --detail

    # how much of that is the model and how much is the method?
    python scripts/forecast.py --season 2026 --model all

    # vary every assumption — including the injury and depth ones
    python scripts/forecast.py --season 2026 --sensitivity

    # what the projection is actually worth, season by season
    python scripts/forecast.py --calibration

    # has it ever been right? rewind every finished season and score it
    python scripts/forecast.py --backtest
    python scripts/forecast.py --backtest --as-of-weeks 0,4,8,12
    python scripts/forecast.py --validate

Three strength models are available and `--model all` runs each:

  roster   the calibrated roster projection: each player's rate from his last
           two seasons in this league, recency-weighted and age-adjusted; each
           rookie priced from his draft-day KTC against what past classes
           returned; taxi players and unsigned free agents removed from the
           startable pool; preseason injury flags ignored as stale and replaced
           by dated, sourced outside reporting; then availability simulated week
           by week with the lineup refilled from whoever is left, so depth is
           worth something;
  history  each team's own previous-season scoring, regressed. What you would
           say knowing only last year's table;
  uniform  every team identical: the no-information floor. If `roster` is not
           well clear of this, the projection is not telling you anything.

Before answering, the guards run: the scores -> standings -> champion path must
reproduce every completed season's real bracket, and forecasting a season that
is already over must return 100% for the team the build calls champion. A
forecast whose machinery cannot reproduce a season that happened is not
evidence, so a guard failure stops the run unless you pass `--skip-guards`.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import forecast as F  # noqa: E402
from lotg_support import inquiry as Q  # noqa: E402

_MODELS = ("roster", "history", "uniform")


def _replace(obj, **kw):
    return dataclasses.replace(obj, **kw)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, help="season to forecast (default: the newest snapshot)")
    ap.add_argument("--sims", type=int, default=20000, help="Monte-Carlo runs (default 20,000)")
    ap.add_argument("--seed", type=int, default=20260807, help="RNG seed; the run is reproducible")
    ap.add_argument("--model", default="roster", choices=list(_MODELS) + ["all"],
                    help="team-strength model; 'all' runs each and compares")
    ap.add_argument("--seeds", action="store_true", help="also print the seed distribution")
    ap.add_argument("--detail", action="store_true",
                    help="show what injuries, depth, age and the rookie class are doing")
    ap.add_argument("--sensitivity", action="store_true",
                    help="re-run under alternative rate assumptions and show the spread")
    ap.add_argument("--calibration", action="store_true",
                    help="print what the projection is worth and stop")
    ap.add_argument("--backtest", action="store_true",
                    help="rewind every completed season and score the forecast against what "
                         "actually happened, then stop")
    ap.add_argument("--as-of-weeks", default="0",
                    help="comma-separated weeks to rewind to for --backtest (0 = preseason)")
    ap.add_argument("--validate", action="store_true", help="run the guards and stop")
    ap.add_argument("--skip-guards", action="store_true",
                    help="skip the correctness guards (not recommended)")
    ap.add_argument("--csv", action="store_true", help="machine-readable output")
    return ap


def _default_season() -> int:
    seasons = Q.snapshot_seasons()
    if not seasons:
        raise SystemExit("no snapshot seasons found under exports/snapshot/")
    live = [y for y in seasons if not Q.season_meta(y).is_complete]
    return max(live) if live else max(seasons)


def _print_calibration(calib: F.Calibration) -> None:
    print("what the roster projection is worth")
    print(f"  fitted on {', '.join(str(y) for y in calib.seasons)} "
          f"({calib.n} team-seasons)")
    print(f"  realised weekly PF = {calib.slope:.3f} x projection "
          f"(both centred on their season's league mean)")
    print(f"  correlation           in-sample {calib.corr:.3f}   "
          f"leave-one-season-out {calib.corr_oos:.3f}")
    print(f"  out-of-sample RMSE    {calib.rmse_oos:.2f} points per week")
    print(f"  residual sd           {calib.sd_resid:.2f}  = team strength {calib.sd_true:.2f} "
          f"+ a {int(round(calib.n / max(len(calib.seasons), 1)))}-team season of week noise")
    print(f"  week-to-week sd       {calib.sd_week:.2f} (one team around its own level)")
    print(f"  league-wide week sd   {calib.sd_league_week:.2f} (every team up or down together; "
          "cancels head-to-head)")
    print("  per season:")
    for year, corr in calib.per_season_corr:
        note = "  <- only the 2020 ESPN backfill to project from" if year == 2021 else ""
        print(f"    {year}  r = {corr:+.3f}{note}")


def _csv(fc: F.Forecast) -> None:
    print("team,champion_pct,finals_pct,playoff_pct,expected_wins,expected_pf,projection")
    for o in fc.by_champion():
        print(f"{o.team},{o.champion:.2f},{o.finals:.2f},{o.playoffs:.2f},"
              f"{o.expected_wins:.3f},{o.expected_pf:.2f},{o.projection:.2f}")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    season = args.season or _default_season()

    if args.validate or not args.skip_guards:
        problems = F.validate()
        if problems:
            print("GUARDS FAILED — the forecast machinery does not reproduce seasons that "
                  "actually happened, so its odds would not be evidence:\n")
            for line in problems[:20]:
                print(f"  {line}")
            return 1
        completed = ", ".join(str(y) for y in Q.completed_seasons())
        print(f"guards OK for {completed}: the scores -> standings -> champion path "
              "reproduces every built bracket, and a finished season forecasts at 100%.\n")
    if args.validate:
        return 0

    if args.backtest:
        weeks = tuple(int(w) for w in str(args.as_of_weeks).split(",") if w.strip())
        bt = F.backtest(as_of_weeks=weeks, sims=max(args.sims // 4, 2000), seed=args.seed)
        print(F.render_backtest(bt))
        print()
        print("PLAYOFF PROBABILITY CALIBRATION — does 75% mean three times in four?")
        print(bt.calibration("roster", as_of_week=weeks[0]).to_string(index=False))
        return 0

    calib = F.calibrate()
    if args.calibration:
        _print_calibration(calib)
        return 0

    models = list(_MODELS) if args.model == "all" else [args.model]
    runs = []
    for model in models:
        fc = F.forecast(season, sims=args.sims, calibration=calib, seed=args.seed,
                        strength_model=model)
        runs.append(fc)
        if args.csv:
            _csv(fc)
        else:
            print(F.render(fc, seeds=args.seeds, detail=args.detail))
            print()

    if len(runs) > 1 and not args.csv:
        print("=" * 78)
        print("MODEL SENSITIVITY — championship %")
        print("=" * 78)
        header = f"{'team':<18}" + "".join(f"{m:>12}" for m in models)
        print(header)
        order = runs[0].by_champion()
        for o in order:
            row = f"{o.team:<18}"
            for fc in runs:
                match = next(x for x in fc.odds if x.team == o.team)
                row += f"{match.champion:>12.1f}"
            print(row)
        print("\n  'uniform' is the no-information floor "
              f"({100 / len(order):.1f}% each). A model only earns its odds by the "
              "distance it puts between itself and that.")

    if args.sensitivity and not args.csv:
        print()
        print("=" * 78)
        print("ASSUMPTION SENSITIVITY — championship %, roster model")
        print("=" * 78)
        base_rate, base_avail = F.RateModel(), F.AvailabilityModel()
        variants = {
            # (rate model, availability model)
            "default": (base_rate, base_avail),
            "no depth/injury": (base_rate, _replace(base_avail, exclude_taxi=False,
                                                    research=False, designations="never",
                                                    unsigned_availability=1.0,
                                                    shrink_weeks=10 ** 6)),
            # research overrides a designation for anyone it names, so these
            # comparisons only mean anything with research off
            "no research": (base_rate, _replace(base_avail, research=False)),
            "stale IR instead": (base_rate, _replace(base_avail, research=False,
                                                     designations="always")),
            "unsigned play on": (base_rate, _replace(base_avail, research=False,
                                                     unsigned_availability=1.0)),
            "no age curve": (_replace(base_rate, age_adjust=False), base_avail),
            "no recency": (_replace(base_rate, halflife=None), base_avail),
            "rookies by slot": (_replace(base_rate, rookie_pricing="slot"), base_avail),
            "last season only": (_replace(base_rate, weights=(1.0,)), base_avail),
            "3 seasons": (_replace(base_rate, weights=(0.5, 0.3, 0.2)), base_avail),
            "light shrink k=3": (_replace(base_rate, shrink_games=3.0), base_avail),
            "heavy shrink k=12": (_replace(base_rate, shrink_games=12.0), base_avail),
        }
        table = {}
        for name, (rate, avail) in variants.items():
            fc = F.forecast(season, sims=max(args.sims // 4, 2000), model=rate,
                            availability=avail, seed=args.seed, strength_model="roster")
            table[name] = {o.team: o.champion for o in fc.odds}
        names = list(variants)
        print(f"{'team':<18}" + "".join(f"{n[:13]:>15}" for n in names))
        base = table["default"]
        for team in sorted(base, key=lambda t: -base[t]):
            print(f"{team:<18}" + "".join(f"{table[n][team]:>15.1f}" for n in names))
        spread = {t: max(table[n][t] for n in names) - min(table[n][t] for n in names)
                  for t in base}
        worst = max(spread, key=spread.get)
        print(f"\n  widest spread across assumptions: {worst} "
              f"({spread[worst]:.1f} points of championship probability)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
