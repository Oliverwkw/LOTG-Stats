"""Cross-source + pad-row + phantom-collision guard.

A foreknowledge-free battery that ties each derived player-attribution column
back to the NFLverse aggregate (or trade ledger) it must agree with — the class
of bug the CSV exports alone cannot surface because they drop the internal
"Player ID". Would independently catch, without knowing about them:

  - tx-only pad players showing 0 career/season NFL points (PR #325)
  - "Change in ... from career" left N/A on pad rows despite a real prior
    career (PR #325)
  - name-keyed trade counts / holder-events miscounting or conflating shared
    names (PR #325 / #327) and the Jefferson/Moore/Johnson collision phantoms
  - #326 trade asset-count columns (whole-deal total consistency)

Reads exports/raw/audit_snapshot.json (written by build_all — pid-keyed, so the
exact checks are possible) plus exports/trades.csv. SKIPS cleanly when no build
is present, so it's safe in any checkout.

Run: python tests/test_cross_source_and_pad.py [exports_dir]
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _exports_dir() -> Path:
    return Path(os.environ.get("LOTG_EXPORTS", _ROOT / "exports"))


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except Exception:
        return None


def _isna(v):
    return v in ("", "N/A", None) or (isinstance(v, float) and math.isnan(v))


def audit(exports: Path) -> list:
    """Return a list of (check_name, n_findings, examples). Empty list => no
    snapshot (caller SKIPs). A present-but-clean run returns rows with n=0."""
    snap_p = exports / "raw" / "audit_snapshot.json"
    trades_p = exports / "trades.csv"
    if not snap_p.exists() or not trades_p.exists():
        return []
    s = json.loads(snap_p.read_text())
    pa = s["player_all"]            # [pid, name, pts_career, avg_career, ntrades]
    py = s["player_year"]          # [pid, year, pts_season, avg_season, chg_pts_car, chg_avg_car, ntrades]
    cp = s["career_pts"]; sp = s["season_pts"]; cpb = s["career_pts_before"]

    F = defaultdict(int)      # check -> count
    EX = defaultdict(list)    # check -> up to 5 example strings
    def add(c, m):
        F[c] += 1
        if len(EX[c]) < 5:
            EX[c].append(m)

    # 1 — cross-source: export career pts must be > 0 when NFLverse has career pts
    for pid, name, ptsc, avgc, ntr in pa:
        if cp.get(pid, 0.0) > 1.0 and (ptsc is None or ptsc == 0):
            add("career_zero_but_nflverse_positive", f"{name} pid={pid} export={ptsc} nflverse={cp.get(pid)}")

    # 2 — determinism: export career/season points must equal the NFLverse dict
    #     (catches pad rows that never got the column filled from the aggregate)
    for pid, name, ptsc, avgc, ntr in pa:
        want = round(cp.get(pid, 0.0), 2)
        if abs((ptsc or 0.0) - want) > 0.02:
            add("career_pts_ne_aggregate", f"{name} pid={pid} export={ptsc} agg={want}")
    for pid, yr, ptss, avgs, chgp, chga, ntr in py:
        want = round(sp.get(f"{pid}|{yr}", 0.0), 2)
        if abs((ptss or 0.0) - want) > 0.02:
            add("season_pts_ne_aggregate", f"pid={pid} {yr} export={ptss} agg={want}")

    # 3 — change-from-career must be populated whenever a prior NFL career exists
    for pid, yr, ptss, avgs, chgp, chga, ntr in py:
        if cpb.get(f"{pid}|{yr}", 0.0) > 0.0 and ptss is not None:
            if chgp is None:
                add("change_pts_from_career_blank", f"pid={pid} {yr} prior={cpb.get(f'{pid}|{yr}')}")
            if chga is None:
                add("change_avg_from_career_blank", f"pid={pid} {yr} prior={cpb.get(f'{pid}|{yr}')}")

    # 4 — trade counts must equal count of pid in the trade ledger's received lists
    recv_all = Counter(); recv_yr = Counter()
    for season, pids in s["trades_recv"]:
        for pid in pids:
            recv_all[pid] += 1; recv_yr[(pid, str(season))] += 1
    for pid, name, ptsc, avgc, ntr in pa:
        if int(ntr or 0) != recv_all.get(pid, 0):
            add("trade_count_all_mismatch", f"{name} pid={pid} export={int(ntr or 0)} ledger={recv_all.get(pid, 0)}")
    for pid, yr, ptss, avgs, chgp, chga, ntr in py:
        if int(ntr or 0) != recv_yr.get((pid, str(yr)), 0):
            add("trade_count_year_mismatch", f"pid={pid} {yr} export={int(ntr or 0)} ledger={recv_yr.get((pid, str(yr)), 0)}")

    # 5 — name-collision phantoms: a player NAME resolving to >1 distinct pid,
    #     or a transaction whose pid disagrees with the canonical name for it
    name2pids = defaultdict(set); pid2name = {}
    for pid, name, *_ in pa:
        name2pids[name].add(pid); pid2name[pid] = name
    for added_name, added_pid, dropped_name, dropped_pid in s["tx"]:
        if added_name and added_pid:
            name2pids[added_name].add(added_pid)
        if dropped_name and dropped_pid:
            name2pids[dropped_name].add(dropped_pid)
    for nm, pids in name2pids.items():
        if len(pids) > 1:
            add("name_maps_to_multiple_pids", f"{nm!r} -> {sorted(pids)}")
    for added_name, added_pid, dropped_name, dropped_pid in s["tx"]:
        if added_pid and added_name and added_pid in pid2name and pid2name[added_pid] != added_name:
            add("tx_pid_name_mismatch", f"added={added_name!r} pid={added_pid} canonical={pid2name[added_pid]!r}")
        if dropped_pid and dropped_name and dropped_pid in pid2name and pid2name[dropped_pid] != dropped_name:
            add("tx_pid_name_mismatch", f"dropped={dropped_name!r} pid={dropped_pid} canonical={pid2name[dropped_pid]!r}")

    # 6 — structural: (pid, year) unique; every player_year pid appears in player_all
    seen = set()
    for pid, yr, *_ in py:
        if (pid, yr) in seen:
            add("duplicate_player_year_row", f"pid={pid} year={yr}")
        seen.add((pid, yr))
    pa_pids = {pid for pid, *_ in pa}
    for pid, yr, *_ in py:
        if pid not in pa_pids:
            add("player_year_pid_not_in_player_all", f"pid={pid} year={yr}")

    # 7 — #326 asset counts: whole-deal Total == Σ "received" across the deal's
    #     rows, and constant within a deal
    tr = list(csv.DictReader(open(trades_p)))
    if tr and "Total number of assets in trade" in tr[0]:
        by_deal = defaultdict(list)
        for r in tr:
            by_deal[r.get("Date")].append(r)
        for d, rows in by_deal.items():
            recv_sum = sum(int(_num(r.get("Number of assets received")) or 0) for r in rows)
            tots = {(_num(r.get("Total number of assets in trade")) if not _isna(r.get("Total number of assets in trade")) else None) for r in rows}
            if len(tots) > 1:
                add("trade_total_not_constant_in_deal", f"date={d} totals={tots}")
            t = next(iter(tots))
            if t is not None and int(t) != recv_sum:
                add("trade_total_ne_sum_received", f"date={d} Σreceived={recv_sum} total={int(t)}")

    # 8 — no literal null-ish strings leaked into any exported cell
    for f in exports.glob("*.csv"):
        try:
            rows = list(csv.DictReader(open(f)))
        except Exception:
            continue
        for r in rows:
            bad = [f"{c}={v!r}" for c, v in r.items() if v in ("nan", "NaN", "None", "inf", "-inf", "NAN", "Infinity")]
            if bad:
                add("literal_nullish_cell", f"{f.name}: {bad[0]}")
                break

    checks = [
        "career_zero_but_nflverse_positive", "career_pts_ne_aggregate", "season_pts_ne_aggregate",
        "change_pts_from_career_blank", "change_avg_from_career_blank",
        "trade_count_all_mismatch", "trade_count_year_mismatch",
        "name_maps_to_multiple_pids", "tx_pid_name_mismatch",
        "duplicate_player_year_row", "player_year_pid_not_in_player_all",
        "trade_total_not_constant_in_deal", "trade_total_ne_sum_received",
        "literal_nullish_cell",
    ]
    return [(c, F.get(c, 0), EX.get(c, [])) for c in checks]


def test_cross_source_and_pad():
    import pytest
    results = audit(_exports_dir())
    if not results:
        pytest.skip("no build present (exports/raw/audit_snapshot.json missing)")
    failures = [(c, n, ex) for c, n, ex in results if n]
    assert not failures, "cross-source/pad audit failed:\n" + "\n".join(
        f"  [{c}] {n} findings e.g. {ex}" for c, n, ex in failures
    )


if __name__ == "__main__":
    import sys
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else _exports_dir()
    res = audit(d)
    if not res:
        print("SKIP: no audit_snapshot.json under", d / "raw")
        sys.exit(0)
    total = 0
    for c, n, ex in res:
        total += n
        print(f"[{c}] {'CLEAN' if n == 0 else '*** ' + str(n) + ' FINDINGS ***'}")
        for e in ex:
            print("     ", e)
    print("-" * 50)
    print("TOTAL:", total, "=>", "CLEAN" if total == 0 else "NOT CLEAN")
    sys.exit(1 if total else 0)
