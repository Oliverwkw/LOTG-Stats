"""Phase 14 (Phase 12 #41) — injury-tracker coverage report.

The in-house weekly Sleeper injury tracker (data/injury_tracker.csv, captured by
.github/workflows/capture_injuries.yml) is the build's PRIMARY injury/suspension
source, with nflverse as backup (see lib/lotg_support/injury_tracker.py). This
report tells you, at a glance, whether that tracker is actually doing its job:

  * CAPTURE HEALTH — for every captured (season, week): how many rostered players
    were snapshotted, and the injury / suspension / bye / healthy breakdown of
    their Sleeper statuses.
  * WEEK GAPS — in-season weeks that were played (per the built team_week) but
    have NO tracker capture. A gap means the Monday capture job didn't run that
    week, so the build silently fell back to the lagging nflverse feed for it —
    the single most important thing to surface.
  * BUILD CROSS-CHECK — per captured week, how many player_week rows the build
    ultimately flagged Injury? / Suspension? / Bye?, next to how many the tracker
    saw, as a rough reach indicator.

The tracker starts empty (first capture = 2026 week 1), so before the 2026 season
this report cleanly says "no captures yet" and there is nothing to reconcile.

Writes a Markdown report to exports/raw/injury_coverage.md (committed with the
build, so it's downloadable) and prints a one-line summary. Never fails the
build — it's a report.

Usage:
  PYTHONPATH=src:lib python scripts/injury_coverage.py [--exports DIR] [--out PATH]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support.injury_tracker import _INJURY_TERMS, tracker_path  # noqa: E402


def _classify(injury_status: str, status: str) -> str:
    """Bucket a captured Sleeper status the way the build's overlay reads it."""
    s = (str(injury_status or "") + " " + str(status or "")).strip().lower()
    if not s:
        return "healthy"
    if "sus" in s:
        return "suspension"
    if any(t in s for t in _INJURY_TERMS):
        return "injury"
    return "healthy"


def load_captures(root: Path) -> List[dict]:
    path = tracker_path(root)
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def capture_summary(rows: List[dict]) -> Dict[Tuple[int, int], dict]:
    """(season, week) -> capture stats."""
    by_week: Dict[Tuple[int, int], dict] = {}
    grouped: Dict[Tuple[int, int], List[dict]] = defaultdict(list)
    for r in rows:
        s, w = _int(r.get("season")), _int(r.get("week"))
        if s is None or w is None:
            continue
        grouped[(s, w)].append(r)
    for key, rs in grouped.items():
        buckets = defaultdict(int)
        bye = defaultdict(int)
        positions = set()
        for r in rs:
            buckets[_classify(r.get("injury_status"), r.get("status"))] += 1
            b = str(r.get("on_bye") or "").strip().lower()
            bye["true" if b in ("true", "1", "yes")
                else "false" if b in ("false", "0", "no") else "unknown"] += 1
            if r.get("position"):
                positions.add(r["position"])
        by_week[key] = {
            "players": len(rs),
            "injury": buckets["injury"], "suspension": buckets["suspension"],
            "healthy": buckets["healthy"],
            "bye_true": bye["true"], "bye_false": bye["false"], "bye_unknown": bye["unknown"],
            "positions": len(positions),
            "captured_at": max((r.get("captured_at_utc") or "") for r in rs),
        }
    return by_week


def played_weeks(team_week: pd.DataFrame) -> Dict[int, set]:
    """season -> set of weeks that were actually played (have team_week rows)."""
    out: Dict[int, set] = defaultdict(set)
    if team_week.empty or "Year" not in team_week.columns or "Week" not in team_week.columns:
        return out
    yr = pd.to_numeric(team_week["Year"], errors="coerce")
    wk = pd.to_numeric(team_week["Week"], errors="coerce")
    for y, w in zip(yr, wk):
        if pd.notna(y) and pd.notna(w):
            out[int(y)].add(int(w))
    return out


def week_gaps(captured: Dict[Tuple[int, int], dict],
              played: Dict[int, set]) -> Dict[int, List[int]]:
    """Played in-season weeks with no tracker capture, per tracker-active season.
    Only seasons at/after the first captured season are considered (the tracker
    doesn't backfill history)."""
    if not captured:
        return {}
    first_season = min(s for s, _ in captured)
    cap_weeks: Dict[int, set] = defaultdict(set)
    for s, w in captured:
        cap_weeks[s].add(w)
    gaps: Dict[int, List[int]] = {}
    for season, weeks in played.items():
        if season < first_season:
            continue
        missing = sorted(w for w in weeks if w not in cap_weeks.get(season, set()))
        if missing:
            gaps[season] = missing
    return gaps


def build_flag_counts(player_week: pd.DataFrame) -> Dict[Tuple[int, int], dict]:
    """(season, week) -> how many player_week rows the build flagged."""
    out: Dict[Tuple[int, int], dict] = {}
    if player_week.empty or "Year" not in player_week.columns or "Week" not in player_week.columns:
        return out
    yr = pd.to_numeric(player_week["Year"], errors="coerce")
    wk = pd.to_numeric(player_week["Week"], errors="coerce")

    def _truthy(col):
        if col not in player_week.columns:
            return pd.Series(False, index=player_week.index)
        return player_week[col].astype(str).str.strip().str.lower().isin(("true", "1", "yes"))

    inj, sus, bye = _truthy("Injury?"), _truthy("Suspension?"), _truthy("Bye?")
    df = pd.DataFrame({"s": yr, "w": wk, "inj": inj, "sus": sus, "bye": bye}).dropna(subset=["s", "w"])
    for (s, w), g in df.groupby(["s", "w"]):
        out[(int(s), int(w))] = {"injury": int(g["inj"].sum()),
                                 "suspension": int(g["sus"].sum()), "bye": int(g["bye"].sum())}
    return out


def render_report(captures: List[dict], summary: Dict[Tuple[int, int], dict],
                  gaps: Dict[int, List[int]], flags: Dict[Tuple[int, int], dict]) -> Tuple[str, str]:
    """Return (markdown, one_line_summary)."""
    lines = ["# Injury-tracker coverage report\n"]
    if not captures:
        lines.append("_No captures yet._ The weekly Sleeper injury tracker "
                     "(`data/injury_tracker.csv`) is still empty — its first capture is "
                     "**2026 week 1**. Until then the build uses the nflverse / Sleeper-meta "
                     "fallback for every week, and there is no coverage to reconcile.\n")
        return "\n".join(lines), "injury coverage: tracker empty (no captures yet)"

    seasons = sorted({s for s, _ in summary})
    total = sum(v["players"] for v in summary.values())
    lines.append(f"Captured **{len(summary)} week(s)** across seasons "
                 f"{', '.join(map(str, seasons))} — {total} player-snapshots total.\n")

    # Week gaps first — the most actionable signal.
    lines.append("## Week gaps (played but never captured)\n")
    if gaps:
        for season in sorted(gaps):
            wl = ", ".join(map(str, gaps[season]))
            lines.append(f"- ⚠️ **{season}**: weeks {wl} were played but have **no tracker "
                         f"capture** — the build fell back to nflverse for them.")
    else:
        lines.append("- ✅ Every played in-season week (since the tracker began) has a capture.")
    lines.append("")

    # Per-week capture health + build cross-check.
    lines.append("## Capture health by week\n")
    lines.append("| Season | Week | Players | Injury | Suspension | Bye (Y/N/?) | "
                 "Build inj/sus/bye |")
    lines.append("|---|---|---|---|---|---|---|")
    for key in sorted(summary):
        s, w = key
        v = summary[key]
        f = flags.get(key, {})
        fb = f"{f.get('injury', '–')}/{f.get('suspension', '–')}/{f.get('bye', '–')}" if f else "–"
        lines.append(f"| {s} | {w} | {v['players']} | {v['injury']} | {v['suspension']} | "
                     f"{v['bye_true']}/{v['bye_false']}/{v['bye_unknown']} | {fb} |")
    lines.append("")

    n_gap_weeks = sum(len(v) for v in gaps.values())
    one_line = (f"injury coverage: {len(summary)} week(s) captured, "
                f"{total} snapshots, {n_gap_weeks} played-week gap(s)")
    lines.append(f"_{one_line}._")
    return "\n".join(lines), one_line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Injury-tracker coverage report.")
    ap.add_argument("--exports", default=str(_ROOT / "exports"))
    ap.add_argument("--root", default=str(_ROOT), help="repo root (holds data/injury_tracker.csv)")
    ap.add_argument("--out", default=None,
                    help="report path (default: <exports>/raw/injury_coverage.md)")
    args = ap.parse_args(argv)

    root = Path(args.root)
    exports = Path(args.exports)
    out = Path(args.out) if args.out else exports / "raw" / "injury_coverage.md"

    def _read(name):
        p = exports / f"{name}.csv"
        return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()

    captures = load_captures(root)
    summary = capture_summary(captures)
    gaps = week_gaps(summary, played_weeks(_read("team_week")))
    flags = build_flag_counts(_read("player_week"))

    md, one_line = render_report(captures, summary, gaps, flags)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md + "\n")
    print(f"[injury-coverage] {one_line} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
