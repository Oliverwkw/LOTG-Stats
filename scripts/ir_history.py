"""Write plan/notes/ir_spells.csv: every IR run of an NFL QB/RB/WR/TE, 2021-2025.

Reads nflverse's weekly rosters (cached under .cache/) through
`lotg_support.external` and keeps one row per injured-reserve run
(`lotg_support.ir_status._runs_from_rosters`). The forecast reads the committed
file, so it needs no network; re-run this only to add a finished season.

    python scripts/ir_history.py                  # 2021-2025
    python scripts/ir_history.py --seasons 2021 2022 2023 2024 2025 2026
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from lotg_support import ir_status as IR  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seasons", type=int, nargs="+", default=[2021, 2022, 2023, 2024, 2025])
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    df = IR.build_history(a.seasons, a.cache_dir)
    out = Path(a.out) if a.out else IR.history_path()
    df.to_csv(out, index=False)
    ins = df[df.start_week >= 2]
    print(f"{len(df)} IR runs ({len(ins)} in-season, {int((ins.outcome == 'returned').sum())} returned) -> {out}")
    for season, g in ins[ins.outcome == "returned"].groupby("season"):
        print(f"  {season}: shortest return {int(g.games_on_ir.min())} games "
              f"(rule {IR.ir_min_games(int(season))}), {len(g)} returns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
