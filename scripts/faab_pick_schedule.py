"""Design-time refit of the fixed FAAB pick schedule (lotg_support.faab_pick_schedule). Reads KTC's pick history, which
is the only place KTC enters; the committed CSVs are what the values read. A refit is a reviewed PR.

    python scripts/faab_pick_schedule.py fit            # refit the weekly shape from KTC + freeze today's slot prices
    python scripts/faab_pick_schedule.py show [SLOT]    # the schedule by week for a slot (default 1.01)
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import pandas as pd  # noqa: E402

from lotg_support import faab_pick_schedule as PS  # noqa: E402


def cmd_fit(a):
    from lotg_support import ktc, faab_inputs as I
    rows = []
    for y in range(2021, pd.Timestamp.today().year + 4):
        for t in ("early", "mid", "late"):
            for r, sfx in ((1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th")):
                for x in ktc.load_history(ROOT, f"{y}{t}{sfx}pi"):
                    if x.get("sf_trade_value") and x.get("date"):
                        rows.append((y, t, r, x["date"][:10], float(x["sf_trade_value"])))
    if not rows:
        sys.exit("no KTC pick history (dynasty-daddy unreachable?)")
    K = PS.ktc_pick_frame(rows)
    F = PS.fit_shape(K)
    out = Path(a.out or PS.DATA)
    F.to_csv(out / PS.WEEKS_CSV, index=False)
    if not a.keep_base:
        sv = I.Picks(I.player_additions_sid()).slot_values(pd.Timestamp.today())
        b = pd.DataFrame(dict(slot=sv.index.astype(str), price=sv.values.round(3)))
        b = b[b.slot.str.fullmatch(r"[1-4]\.\d\d")]
        b.to_csv(out / PS.BASE_CSV, index=False)
    print(f"{len(K)} KTC pick quotes, classes {K.cls.min()}-{K.cls.max()}; wrote {out / PS.WEEKS_CSV}"
          + ("" if a.keep_base else f" and {out / PS.BASE_CSV}"))


def cmd_show(a):
    S = PS.load()
    slot = a.slot or "1.01"
    ov = PS.overall(slot)
    rows = []
    for w in list(range(-156, -52, 13)) + list(range(-52, 21, 4)):
        rows.append((w, round(S.base[slot] * __import__("math").exp(S.shape(ov, w)), 1)))
    print(pd.DataFrame(rows, columns=["weeks to NFL draft", f"{slot} price"]).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit"); f.add_argument("--out"); f.add_argument("--keep-base", action="store_true")
    f.set_defaults(fn=cmd_fit)
    s = sub.add_parser("show"); s.add_argument("slot", nargs="?"); s.set_defaults(fn=cmd_show)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
