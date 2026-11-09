"""FAAB-unit player values from stats — a thin command line over `lotg_support.faab_value` / `faab_votes`.

Read-only unless a command says it writes. Nothing here touches exports/ or the build.

    python scripts/faab_value.py board -n 40                    # today's board (the inputs' as-of date)
    python scripts/faab_value.py value "bucky irving" "Jaxon Dart"   # current value + rank, any spelling
    python scripts/faab_value.py explain "Bucky Irving" "Bhayshul Tuten"   # every rule's multiplier, stage by stage
    python scripts/faab_value.py calls                          # which league calls the board passes / misses
    python scripts/faab_value.py votes                          # votes vs the board: agreement, and the rules behind each disagreement
    python scripts/faab_value.py publish                        # WRITES docs/rate/board.json + questions.json (the rating page)
    python scripts/faab_value.py fit --out data/faab_value/params.json   # WRITES refitted rule strengths (votes included, capped)
    python scripts/faab_value.py try-rule "vet_floor=0.8" "vet_floor=0.8 F.VET_FLOOR_PPG=8"   # each change vs the current params: the noise bar's numbers
    python scripts/faab_value.py pull-votes URL                 # WRITES data/votes/responses.csv from the form's published CSV

Votes are a signal for the fit's general rules, never a per-player edit; `fit` is run deliberately and its
params diff reviewed in a PR (see lib/lotg_support/faab_votes.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))

from lotg_support import faab_calls as LC  # noqa: E402
from lotg_support import faab_value as F  # noqa: E402
from lotg_support import faab_votes as FV  # noqa: E402

PAGE = ROOT / "docs" / "rate"
REF = F.DATA / f"reviewed_board_{LC.CALLS_DATE}.csv"


def _setup(params=None):
    R = F.load_inputs(); p = F.load_params(params)
    return R, p, F.board(R, p)


def cmd_board(a):
    _, _, T = _setup(a.params)
    print(f"as of {T.date.iloc[0]} | {len(T)} players | values in league FAAB $ (100-budget scale x the league's own prices)")
    print(T[["rank", "name", "pos", "age", "injury", "V"]].head(a.n).round({"age": 1, "V": 0}).to_string(index=False))


def cmd_value(a):
    _, _, T = _setup(a.params)
    B = T.set_index("name")
    print(f"as of {T.date.iloc[0]} | {len(T)} players | league FAAB $")
    for q in a.names:
        hit = F.match_names(T.name, q)
        if not hit: print(f"{q}: not on the board (no close name)")
        for n in hit:
            r = B.loc[n]; inj = f", {r.injury}" if r.injury else ""
            print(f"{q} -> {n} ({r.pos}, {r.age:.1f}{inj}): ${r.V:,.0f}  rank {r['rank']}")


def cmd_explain(a):
    R, p, T = _setup(a.params)
    for r in F.explain(R[R.date == T.date.iloc[0]], p, a.names):
        st = " -> ".join(f"{k[1:]} {v:,}" for k, v in r.items() if k.startswith("$"))
        print(f"{r['name']}: {st}")
        print("   " + ", ".join(f"{k} x{v:.2f}" for k, v in r["rules"].items()))
    miss = set(a.names) - set(T.name)
    for q in sorted(miss):
        near = F.match_names(T.name, q)
        print(f"not on the board: {q}" + (f" (did you mean: {', '.join(near)}?)" if near else ""))


def cmd_calls(a):
    p = F.load_params(a.params); ev = F.Evidence.load()
    v = F.call_values(ev, p); ref = pd.read_csv(REF).set_index("name").V
    first = ev.Ts[ev.call_boards[LC.CALL_DATES[0]]]
    t = LC.calls(v, ref, set(first.name[first.pos == "QB"]))
    bad = [(n, x) for n, x in t if x > 0]
    on = ", ".join(f"{d} on the {gd} board" for d, gd in ev.call_boards.items())
    print(f"{len(t) - len(bad)}/{len(t)} calls pass; each group judged on the board of the day it was made ({on})")
    for n, x in sorted(bad, key=lambda z: -z[1]): print(f"  MISS {x:.3f}  {n}")


def cmd_try(a):
    """each argument is one change (space-separated name=value; F.NAME=value sets a faab_value constant), scored
    against the current params on the committed inputs: the numbers a rule PR shows (lotg_support.faab_trials)"""
    from lotg_support import faab_trials as FT
    p = F.load_params(a.params); ev = F.Evidence.load(a.data) if a.data else F.Evidence.load()
    ref = pd.read_csv(REF).set_index("name").V; obj = F.objective(ev, ref, _vote_term(ev))
    base_p, base_c = FT.parse_overrides(a.base.split()) if a.base else ({}, {})
    with FT.constants(base_c):
        p = dict(p, **base_p)
        for ch in a.changes:
            ps, cs = FT.parse_overrides(ch.split())
            unknown = [k for k in ps if k not in F.P0]
            if unknown: print(f"unknown params (not in P0): {unknown}"); continue
            print(FT.report(FT.trial(ev, obj, p, dict(p, **ps), cs), ch))


def _vote_term(ev):
    return FV.VoteTerm(FV.read_responses(FV.RESPONSES) if FV.RESPONSES.exists() else FV.read_responses(""), ev.as_of, ev.vote_dates)


def cmd_votes(a):
    p = F.load_params(a.params); ev = F.Evidence.load()
    v, terms, _ = F.apply_rules(ev.VR, p, explain=True)
    V = ev.vote_values(v)
    T = {}
    for i, (sid, d) in enumerate(zip(ev.VR.sid.values, ev.VR.date.values)):
        T.setdefault(d, {})[sid] = {k: float(x[i]) for k, x in terms.items()}
    tk = {(bd, sid): t for bd, gd in ev.vote_dates.items() for sid, t in T.get(gd, {}).items()}
    names = dict(zip(ev.VR.sid, ev.VR.name))
    lines = FV.report(_vote_term(ev), V, names, tk)
    text = "\n".join(lines) + "\n"
    if a.report: Path(a.report).write_text(text); print("wrote", a.report)
    else: print(text)


def cmd_publish(a):
    R, p, T = _setup(a.params)
    _, _, stages = F.apply_rules(T, p, explain=True)
    as_of = T.date.iloc[0]
    snap = ROOT / "exports" / "snapshot"
    season = max(int(d.name.split("_")[1]) for d in snap.glob("season_*"))
    owners = FV.owners_from_snapshot(snap / f"season_{season}")
    info = json.load(open(snap / "sleeper_players_nfl.json"))
    PAGE.mkdir(parents=True, exist_ok=True)
    picks = FV.slot_values(ROOT / "exports", as_of)
    (PAGE / "board.json").write_text(json.dumps(FV.page_board(T, owners, as_of, info, picks), separators=(",", ":")) + "\n")
    Q = FV.questions(T, stages, as_of)
    (PAGE / "questions.json").write_text(json.dumps(dict(as_of=as_of, questions=Q), separators=(",", ":")) + "\n")
    print(f"wrote {PAGE / 'board.json'} ({len(T)} players) and questions.json ({len(Q)} questions) for {as_of}")


def cmd_fit(a):
    ev = F.Evidence.load(); ref = pd.read_csv(REF).set_index("name").V
    votes = None if a.no_votes else _vote_term(ev)
    if votes is not None: print(f"votes: {len(votes.used)} answers on {votes.as_of}, term weight {votes.weight:.2f} (max {FV.VOTE_MAX})")
    obj = F.objective(ev, ref, votes)
    starts = [dict(F.P0), F.load_params(a.params)]
    p = F.fit(obj, starts, restarts=1 if a.quick else 8, passes=1 if a.quick else 3, polish=1 if a.quick else 4)
    Path(a.out).write_text(json.dumps(p, indent=1) + "\n"); print("wrote", a.out)


def cmd_pull(a):
    with urllib.request.urlopen(a.url, timeout=60) as r:
        text = r.read().decode("utf-8-sig")
    out = FV.normalise(text)
    FV.RESPONSES.parent.mkdir(parents=True, exist_ok=True)
    FV.RESPONSES.write_text(out)
    print(f"wrote {FV.RESPONSES} ({max(out.count(chr(10)) - 1, 0)} answers)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", help="rule strengths (default data/faab_value/params.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("board"); s.add_argument("-n", type=int, default=50); s.set_defaults(f=cmd_board)
    s = sub.add_parser("value"); s.add_argument("names", nargs="+"); s.set_defaults(f=cmd_value)
    s = sub.add_parser("explain"); s.add_argument("names", nargs="+"); s.set_defaults(f=cmd_explain)
    s = sub.add_parser("calls"); s.set_defaults(f=cmd_calls)
    s = sub.add_parser("votes"); s.add_argument("--report"); s.set_defaults(f=cmd_votes)
    s = sub.add_parser("publish"); s.set_defaults(f=cmd_publish)
    s = sub.add_parser("fit"); s.add_argument("--out", required=True); s.add_argument("--quick", action="store_true")
    s.add_argument("--no-votes", action="store_true"); s.set_defaults(f=cmd_fit)
    s = sub.add_parser("try-rule"); s.add_argument("changes", nargs="+"); s.add_argument("--base", default="", help="overrides applied to both sides first")
    s.add_argument("--data", help="an inputs folder other than data/faab_value"); s.set_defaults(f=cmd_try)
    s = sub.add_parser("pull-votes"); s.add_argument("url"); s.set_defaults(f=cmd_pull)
    a = ap.parse_args(argv); a.f(a)


if __name__ == "__main__":
    main()
