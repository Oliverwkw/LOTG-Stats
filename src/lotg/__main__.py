from __future__ import annotations

import os
from pathlib import Path

import yaml

from .build import build_all


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    cfg = yaml.safe_load((repo_root / "config/league.yaml").read_text())
    league_id = str(cfg["league_id"])
    min_season = cfg.get("min_season")
    max_season = cfg.get("max_season")

    mode = str(os.environ.get("LOTG_MODE", "both")).lower().strip()
    if mode not in {"snapshot", "build", "both"}:
        mode = "both"

    if mode in {"snapshot", "both"}:
        from .snapshot import snapshot_all
        snapshot_all(repo_root, league_id=league_id, min_season=min_season, max_season=max_season)

    if mode in {"build", "both"}:
        build_all(repo_root)


if __name__ == "__main__":
    main()
