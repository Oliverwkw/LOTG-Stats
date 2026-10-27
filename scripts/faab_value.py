"""FAAB-unit player values from stats — a thin command line over `lotg_support.faab_value` / `faab_votes`.

Read-only unless a command says it writes. Nothing here touches exports/ or the build.

    python scripts/faab_value.py board -n 40                    # today's board (the inputs' as-of date)
    python scripts/faab_value.py explain "Bucky Irving" "Bhayshul Tuten"   # every rule's multiplier, stage by stage
    python scripts/faab_value.py calls                          # which league calls the board passes / misses
    python scripts/faab_value.py votes                          # votes vs the board: agreement, and the rules behind each disagreement
    python scripts/faab_value.py publish                        # WRITES docs/rate/board.json + questions.json (the rating page)
    python scripts/faab_value.py fit --out data/faab_value/params.json   # WRITES refitted rule strengths (votes included, capped)
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


def cmd_explain(a):
    R, p, T = _setup(a.params)
    for r in F.explain(R[R.date == T.date.iloc[0]], p, a.names):
        st = " -> ".join(f"{k[1:]} {v:,}" for k, v in r.items() if k.startswith("$"))
        print(f"{r['name']}: {st}")
        print("   " + ", ".join(f"{k} x{v:.2f}" for k, v in r["rules"].items()))
    miss = set(a.names) - set(T.name)
    if miss: print("not on the board:", ", ".join(sorted(miss)))


def cmd_calls(a):
    R, p, _ = _setup(a.params)
    T = F.board(R, p, as_of=json.load(open(F.DATA / "evidence.json")).get("calls_date") or R.date.max())
    v = T.set_index("name").V; ref = pd.read_csv(REF).set_index("name").V
    t = LC.calls(v, ref, set(T.name[T.pos == "QB"]))
    bad = [(n, x) for n, x in t if x > 0]
    print(f"{len(t) - len(bad)}/{len(t)} calls pass on the {T.date.iloc[0]} board (calls made about the {LC.CALLS_DATE} board)")
    for n, x in sorted(bad, key=lambda z: -z[1]): print(f"  MISS {x:.3f}  {n}")


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
    s = sub.add_parser("explain"); s.add_argument("names", nargs="+"); s.set_defaults(f=cmd_explain)
    s = sub.add_parser("calls"); s.set_defaults(f=cmd_calls)
    s = sub.add_parser("votes"); s.add_argument("--report"); s.set_defaults(f=cmd_votes)
    s = sub.add_parser("publish"); s.set_defaults(f=cmd_publish)
    s = sub.add_parser("fit"); s.add_argument("--out", required=True); s.add_argument("--quick", action="store_true")
    s.add_argument("--no-votes", action="store_true"); s.set_defaults(f=cmd_fit)
    s = sub.add_parser("pull-votes"); s.add_argument("url"); s.set_defaults(f=cmd_pull)
    a = ap.parse_args(argv); a.f(a)


if __name__ == "__main__":
    main()
