#!/usr/bin/env python3
"""Phase 7 (Trades) 3-part audit harness.

Runs in CI *after* `python -m lotg` has produced exports/*.csv, where the
Sleeper / nflverse / KTC data is reachable. Prints a structured PASS / FAIL /
INFO report to stdout (captured in the job log) covering:

  * CODE/SCHEMA  — trades.csv & transactions.csv columns match the catalog.
  * RESULTS      — >=5 spec-derived verification cases per Phase 7 item,
                   expressed as data invariants so they pass/fail on the
                   real build without hand-picked ground truth.
  * DIFF SWEEP   — every sheet diffed (sorted by canonical keys) against the
                   pre-Phase-7 baseline build, classifying each changed sheet
                   as EXPECTED (touched by Phase 7) or UNEXPECTED.

Env:
  EXPORTS_DIR   (default: exports)        current build CSV dir
  BASELINE_DIR  (default: "")             pre-Phase-7 build CSV dir (diff skipped if empty)
  CATALOG       (default: plan/stats_catalog.json)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

EXPORTS_DIR = Path(os.environ.get("EXPORTS_DIR", "exports"))
BASELINE_DIR = os.environ.get("BASELINE_DIR", "").strip()
CATALOG = Path(os.environ.get("CATALOG", "plan/stats_catalog.json"))

PASS, FAIL, INFO = "PASS", "FAIL", "INFO"
_counts = {PASS: 0, FAIL: 0, INFO: 0}
_fails: list[str] = []


def check(tag: str, name: str, detail: str = "") -> None:
    _counts[tag] = _counts.get(tag, 0) + 1
    line = f"  [{tag}] {name}"
    if detail:
        line += f"  ::  {detail}"
    print(line)
    if tag == FAIL:
        _fails.append(name)


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def load(name: str, base: Path = EXPORTS_DIR) -> pd.DataFrame | None:
    p = base / name
    if not p.exists():
        return None
    # keep_default_na=False so a literal "N/A" stays distinct from an empty cell
    return pd.read_csv(p, dtype=str, keep_default_na=False)


def is_blank(s) -> bool:
    return s is None or (isinstance(s, str) and s.strip() == "")


def to_float(s):
    try:
        if is_blank(s) or str(s).strip().upper() == "N/A":
            return None
        return float(str(s).replace(",", ""))
    except Exception:
        return None


def split_assets(cell: str) -> list[str]:
    if is_blank(cell):
        return []
    return [t.strip() for t in str(cell).split(";") if t.strip()]


_PICK_RE = re.compile(r"^\d{4}\b")


def asset_kind(a: str) -> str:
    a = a.strip()
    if not a or a.upper() == "N/A":
        return "na"
    if a.endswith("FAAB"):
        return "faab"
    if _PICK_RE.match(a):
        return "pick"
    return "player"


# ---------------------------------------------------------------------------
section("LOAD")
tx = load("transactions.csv")
tr = load("trades.csv")
if tx is None or tr is None:
    print("FATAL: transactions.csv or trades.csv missing from", EXPORTS_DIR)
    sys.exit(2)
print(f"transactions.csv: {tx.shape[0]} rows x {tx.shape[1]} cols")
print(f"trades.csv:       {tr.shape[0]} rows x {tr.shape[1]} cols")

catalog = json.loads(CATALOG.read_text())


# ---------------------------------------------------------------------------
section("PART 1 — CODE / SCHEMA AUDIT")

import csv as _csv


def raw_header(name: str) -> list[str]:
    """Read the literal header row (pandas renames duplicate names with .1)."""
    with (EXPORTS_DIR / name).open(newline="") as fh:
        return next(_csv.reader(fh))


def dedup(seq):
    seen, out = set(), []
    for c in seq:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


for key, fname in (("transactions", "transactions.csv"), ("trades", "trades.csv")):
    want = list(catalog[key])
    want_distinct = dedup(want)
    got = raw_header(fname)
    if got == want:
        check(PASS, f"{key}: header matches catalog exactly ({len(got)})")
    elif got == want_distinct:
        n_dup = len(want) - len(want_distinct)
        check(PASS, f"{key}: header matches catalog's distinct columns ({len(got)})",
              f"catalog lists {len(want)} entries incl {n_dup} self-duplicate(s); "
              f"output carries the {len(got)} distinct cols in catalog order")
    else:
        check(FAIL, f"{key}: column mismatch", f"want {len(want)} got {len(got)}")
        missing = [c for c in want_distinct if c not in got]
        extra = [c for c in got if c not in want_distinct]
        if missing:
            print("        missing:", missing)
        if extra:
            print("        extra  :", extra)
        shared_want = [c for c in want_distinct if c in got]
        shared_got = [c for c in got if c in want_distinct]
        if shared_want != shared_got:
            print("        order differs among shared columns")

# Catalog self-check: duplicate column names
for key in ("transactions", "trades"):
    cols = list(catalog[key])
    dups = sorted({c for c in cols if cols.count(c) > 1})
    if dups:
        check(INFO, f"{key}: catalog has DUPLICATE column name(s)", str(dups))


# ---------------------------------------------------------------------------
section("PART 2 — RESULTS AUDIT (spec-derived invariants)")

# ---- 7A: FAAB-as-asset + net-zero swaps deleted + both-blank fixed ----
print("\n-- 7A: FAAB capture / net-zero deletion / both-blank --")
both_blank = tr[tr["Assets received"].map(is_blank) & tr["Assets sent"].map(is_blank)]
check(PASS if both_blank.empty else FAIL,
      "no trade row blank on BOTH received and sent",
      f"{len(both_blank)} offending rows")

faab_recv = tr["Assets received"].map(lambda c: any(k == "faab" for k in map(asset_kind, split_assets(c))))
faab_sent = tr["Assets sent"].map(lambda c: any(k == "faab" for k in map(asset_kind, split_assets(c))))
n_faab_rows = int((faab_recv | faab_sent).sum())
check(PASS if n_faab_rows > 0 else FAIL,
      "FAAB captured as '$N FAAB' assets",
      f"{n_faab_rows} trade rows carry a FAAB asset")

# net-zero swap residue: a trade group whose ONLY assets are FAAB and whose
# received FAAB total equals sent FAAB total across the whole group.
def faab_total(cells) -> int:
    tot = 0
    for c in cells:
        for a in split_assets(c):
            if asset_kind(a) == "faab":
                m = re.search(r"\$(\d+)", a)
                if m:
                    tot += int(m.group(1))
    return tot

netzero_residue = 0
for date, grp in tr.groupby("Date"):
    kinds = {asset_kind(a) for c in grp["Assets received"] for a in split_assets(c)}
    kinds |= {asset_kind(a) for c in grp["Assets sent"] for a in split_assets(c)}
    kinds.discard("na")
    if not (kinds and kinds <= {"faab"}):
        continue
    # net-zero swap = FAAB-only AND every roster (row) nets zero:
    # received FAAB == sent FAAB for that row. A legitimate one-way
    # transfer (A +$5 / -$0, B +$0 / -$5) is NOT net-zero.
    if all(faab_total([r["Assets received"]]) == faab_total([r["Assets sent"]])
           for _, r in grp.iterrows()):
        netzero_residue += 1
check(PASS if netzero_residue == 0 else FAIL,
      "no residual net-zero FAAB-only swap groups",
      f"{netzero_residue} suspect groups")

# ---- do-now: 3+ team trades — sent must equal received across the deal ----
print("\n-- do-now: 3+ team trade asset conservation --")
multi = tr[pd.to_numeric(tr["Number of teams involved"], errors="coerce") >= 3]
n_multi_groups = multi["Date"].nunique() if not multi.empty else 0
print(f"   {len(multi)} rows across {n_multi_groups} multi-team (3+) trade groups")
from collections import Counter
# The do-now fix is specifically about players & picks no longer being
# double-counted on the sent side of 3+ team trades. Test those as an exact
# multiset; test FAAB separately by dollars (the receiver side lumps FAAB
# summed-per-receiver, the sender side is per-sender, so in a multi-sender
# deal the *strings* legitimately differ even though the dollars conserve).
pp_bad = []     # player/pick multiset mismatch  -> the real double-count test
faab_bad = []   # FAAB dollar-sum mismatch per group
faab_lump = []  # FAAB strings asymmetric but dollars conserve (cosmetic)
for date, grp in tr.groupby("Date"):
    recv_pp = Counter(a for c in grp["Assets received"] for a in split_assets(c) if asset_kind(a) in ("player", "pick"))
    sent_pp = Counter(a for c in grp["Assets sent"] for a in split_assets(c) if asset_kind(a) in ("player", "pick"))
    if recv_pp != sent_pp:
        pp_bad.append((date, len(grp), list((recv_pp - sent_pp).elements()), list((sent_pp - recv_pp).elements())))
    rf, sf = faab_total(grp["Assets received"]), faab_total(grp["Assets sent"])
    if rf != sf:
        faab_bad.append((date, rf, sf))
    else:
        recv_f = Counter(a for c in grp["Assets received"] for a in split_assets(c) if asset_kind(a) == "faab")
        sent_f = Counter(a for c in grp["Assets sent"] for a in split_assets(c) if asset_kind(a) == "faab")
        if recv_f != sent_f:
            faab_lump.append((date, list((recv_f - sent_f).elements()), list((sent_f - recv_f).elements())))

check(PASS if not pp_bad else FAIL,
      "players & picks conserve across each trade group (no 3+ team double-count)",
      f"{len(pp_bad)} groups violate")
for date, n, only_recv, only_sent in pp_bad[:5]:
    print(f"        group {date} ({n} rows): recv-only={only_recv} sent-only={only_sent}")
check(PASS if not faab_bad else FAIL,
      "FAAB dollars conserve across each trade group",
      f"{len(faab_bad)} groups violate")
for date, rf, sf in faab_bad[:5]:
    print(f"        group {date}: received ${rf} vs sent ${sf}")
if faab_lump:
    check(INFO, "FAAB string lumping asymmetric in multi-sender trades (dollars still conserve)",
          f"{len(faab_lump)} group(s); e.g. {faab_lump[0]}")

# ---- 7B: Number of teams involved + per-asset link alignment ----
print("\n-- 7B: # teams involved + per-asset link alignment --")
nteams = pd.to_numeric(tr["Number of teams involved"], errors="coerce")
check(PASS if nteams.notna().all() and (nteams >= 2).all() else FAIL,
      "Number of teams involved is an integer >= 2 on every row",
      f"min={nteams.min()} max={nteams.max()} nulls={int(nteams.isna().sum())}")
# per-group: the value equals distinct (Team + counterparties)
nteams_bad = 0
for date, grp in tr.groupby("Date"):
    teams = set(grp["Team"]) | {x for c in grp["Team's traded with"] for x in split_assets(c)}
    teams = {t for t in teams if not is_blank(t)}
    for v in pd.to_numeric(grp["Number of teams involved"], errors="coerce"):
        if not pd.isna(v) and int(v) != len(teams):
            nteams_bad += 1
            break
check(PASS if nteams_bad == 0 else INFO,
      "Number of teams involved == distinct teams in the group",
      f"{nteams_bad} groups differ (date-collision proxy may explain)")

# per-asset link list aligns 1:1 with non-N/A received assets
align_bad = 0
faab_pick_link_bad = 0
for _, r in tr.iterrows():
    assets = [a for a in split_assets(r["Assets received"]) if asset_kind(a) != "na"]
    for col in ("Link to next transaction per asset", "Link to previous transaction per asset"):
        links = split_assets(r[col])
        if assets and links and len(links) != len(assets):
            align_bad += 1
        # FAAB/pick slots should be N/A in aligned position
        for a, lk in zip(assets, links):
            if asset_kind(a) == "faab" and lk.upper() != "N/A":
                faab_pick_link_bad += 1
check(PASS if align_bad == 0 else FAIL,
      "per-asset link list aligns 1:1 with received assets",
      f"{align_bad} misaligned cells")
check(PASS if faab_pick_link_bad == 0 else FAIL,
      "FAAB received assets carry N/A in the aligned link slot",
      f"{faab_pick_link_bad} FAAB slots non-N/A")

# link tokens are well-formed and in range. Valid refs:
#   #N    -> transactions.csv row N      (1..len(tx))
#   T#N   -> trades.csv row N            (1..len(tr))
#   PH#N  -> pick_history.csv row N      (1..len(ph)) — draft-row bridge (#194/#195)
ph = load("pick_history.csv")
n_ph = len(ph) if ph is not None else None
REF_RES = {
    "tx": (re.compile(r"^#(\d+)$"), len(tx)),
    "tr": (re.compile(r"^T#(\d+)$"), len(tr)),
    "ph": (re.compile(r"^PH#(\d+)$"), n_ph),
}


def classify_tokens(series, examples):
    bad = oor = 0
    for cell in series:
        for tok in split_assets(cell):
            t = tok.strip()
            if not t or t.upper() == "N/A":
                continue
            matched = False
            for _re, _n in REF_RES.values():
                m = _re.match(t)
                if m:
                    matched = True
                    if _n is None or not (1 <= int(m.group(1)) <= _n):
                        oor += 1
                    break
            if not matched:
                bad += 1
                if len(examples) < 8:
                    examples.append(t)
    return bad, oor


tr_ex: list[str] = []
tr_bad = tr_oor = 0
for col in ("Link to next transaction per asset", "Link to previous transaction per asset"):
    b, o = classify_tokens(tr[col], tr_ex)
    tr_bad += b
    tr_oor += o
check(PASS if tr_bad == 0 else FAIL, "trade link tokens are '#N' / 'T#N' / 'PH#N' / 'N/A'",
      f"{tr_bad} malformed" + (f"; e.g. {tr_ex}" if tr_ex else ""))
check(PASS if tr_oor == 0 else FAIL, "trade link refs point in-range", f"{tr_oor} out of range")

tx_link_cols = [c for c in tx.columns if c.startswith("Link to ")]
tx_ex: list[str] = []
tx_bad = tx_oor = 0
for col in tx_link_cols:
    b, o = classify_tokens(tx[col], tx_ex)
    tx_bad += b
    tx_oor += o
check(PASS if tx_bad == 0 else FAIL, "transaction link tokens well-formed",
      f"{tx_bad} malformed" + (f"; e.g. {tx_ex}" if tx_ex else ""))
check(PASS if tx_oor == 0 else FAIL, "transaction link refs in range", f"{tx_oor} out of range")

# ---- 7C: Trade addition value & Asset age difference never blank; picks in retained/away ----
print("\n-- 7C: never-blank columns + picks in retained/traded-away --")
for col in ("Trade addition value", "Asset difference in average age"):
    n_blank = int(tr[col].map(is_blank).sum())
    check(PASS if n_blank == 0 else FAIL, f"trades '{col}' never blank", f"{n_blank} blanks")

ret_has_pick = tr["Assets retained now"].map(lambda c: any(asset_kind(a) == "pick" for a in split_assets(c))).sum()
away_has_pick = tr["Assets traded away"].map(lambda c: any(asset_kind(a) == "pick" for a in split_assets(c))).sum()
check(PASS if ret_has_pick > 0 else INFO, "picks flow into 'Assets retained now'", f"{int(ret_has_pick)} rows")
check(PASS if away_has_pick > 0 else INFO, "picks flow into 'Assets traded away'", f"{int(away_has_pick)} rows")
fa_has_pick = tr["Assets dropped to FA"].map(lambda c: any(asset_kind(a) == "pick" for a in split_assets(c))).sum()
check(PASS if fa_has_pick == 0 else FAIL, "'Assets dropped to FA' is player-only (no picks)", f"{int(fa_has_pick)} rows with picks")

# ---- #200: Points Added/Lost/Net arithmetic (transactions + trades) ----
print("\n-- #200: Points arithmetic --")
def net_arith(df, added, lost, net, label):
    bad = 0
    checked = 0
    for _, r in df.iterrows():
        a, l, n = to_float(r[added]), to_float(r[lost]), to_float(r[net])
        if a is None or l is None or n is None:
            continue
        checked += 1
        if abs((a - l) - n) > 0.05:
            bad += 1
    check(PASS if bad == 0 else FAIL, f"{label}: net == added - lost", f"{bad}/{checked} rows off")

net_arith(tx, "Points Added", "Points Lost", "Net points", "transactions points")
net_arith(tx, "Avg points added", "Avg points lost", "Avg net points", "transactions avg points")
net_arith(tr, "Points added", "Points lost", "Net points", "trades points")
net_arith(tr, "Avg points added", "Avg points lost", "Avg net points", "trades avg points")

# ---- position-adjusted points columns: present + arithmetic ----
print("\n-- 6 position-adjusted points-avg columns --")
tx_padj = ["Avg points added adjusted by position", "Avg points lost adjusted by position", "Avg net points adjusted by position"]
tr_padj = tx_padj
check(PASS if all(c in tx.columns for c in tx_padj) else FAIL, "transactions has 3 position-adjusted avg cols")
check(PASS if all(c in tr.columns for c in tr_padj) else FAIL, "trades has 3 position-adjusted avg cols")
net_arith(tx, tx_padj[0], tx_padj[1], tx_padj[2], "transactions pos-adj avg")
net_arith(tr, tr_padj[0], tr_padj[1], tr_padj[2], "trades pos-adj avg")

# ---- do-now: Length of tenure on team column ----
print("\n-- do-now: Length of tenure on team --")
check(PASS if "Length of tenure on team" in tx.columns else FAIL, "transactions has 'Length of tenure on team'")
# link columns at the END of each sheet
check(PASS if all(c.startswith("Link to ") for c in list(tx.columns)[-4:]) else FAIL,
      "transactions: last 4 columns are the Link columns", str(list(tx.columns)[-4:]))
check(PASS if all(c.startswith("Link to ") for c in list(tr.columns)[-2:]) else FAIL,
      "trades: last 2 columns are the Link columns", str(list(tr.columns)[-2:]))

# ---- Ridley / NFL sentinel ----
print("\n-- Ridley / weekly rosters / 'NFL' sentinel --")
pw = load("player_week.csv")
if pw is not None:
    team_col = next((c for c in pw.columns if c.strip().lower() in ("nfl team", "nfl_team")), None)
    if team_col is None:
        check(INFO, "player_week has no 'NFL team' column to check sentinel on", str([c for c in pw.columns if 'team' in c.lower()]))
    else:
        nfl_rows = int((pw[team_col].str.strip() == "NFL").sum())
        frac = 100 * nfl_rows / max(len(pw), 1)
        check(INFO, f"'NFL' sentinel usage in player_week['{team_col}']",
              f"{nfl_rows} rows / {len(pw)} ({frac:.1f}%)")
        # spec: sentinel is for true FA/retired only -> a minority; IR/PUP/susp keep real team
        check(PASS if 0 <= nfl_rows < 0.5 * len(pw) else FAIL,
              "'NFL' sentinel is a minority (true FA/retired only)", f"{frac:.1f}% of rows")

# ---- Cuff / V2 trade addition value plausibility ----
print("\n-- Cuff column + V2 trade addition value plausibility --")
if "Cuff at time of pickup?" in tx.columns:
    vals = set(str(v).strip() for v in tx["Cuff at time of pickup?"].unique())
    check(INFO, "transactions 'Cuff at time of pickup?' distinct values", str(sorted(vals))[:120])
tav = tx["Player addition value"].map(to_float).dropna() if "Player addition value" in tx.columns else pd.Series([], dtype=float)
trav = tr["Trade addition value"].map(to_float).dropna()
check(INFO, "Trade addition value range", f"min={trav.min() if len(trav) else 'NA'} max={trav.max() if len(trav) else 'NA'}")


# ---------------------------------------------------------------------------
section("PART 3 — DIFF SWEEP vs pre-Phase-7 baseline")

SHEETS = [
    "player_week.csv", "player_year.csv", "player_all_time.csv",
    "team_week.csv", "team_year.csv", "team_all_time.csv",
    "league_week.csv", "league_year.csv", "league_all_time.csv",
    "transactions.csv", "trades.csv", "pick_history.csv",
]
# sheets Phase 7 is EXPECTED to touch
EXPECTED_CHANGED = {
    "transactions.csv", "trades.csv",
    # Ridley/weekly-roster + 'NFL' sentinel re-resolve player team across sheets
    "player_week.csv", "player_year.csv", "player_all_time.csv",
    "team_week.csv", "team_year.csv", "team_all_time.csv",
}

def resolve_baseline(root: str) -> Path | None:
    """The uploaded artifact's zip root is the least-common-ancestor of its
    paths (often `exports/`), so the CSVs may sit at <root>/ or <root>/exports/
    or one level deeper. Find the dir that actually contains the sheets."""
    if not root:
        return None
    rp = Path(root)
    if not rp.exists():
        return None
    for cand in [rp, rp / "exports"]:
        if (cand / "transactions.csv").exists() or (cand / "player_week.csv").exists():
            return cand
    # last resort: search
    hits = list(rp.rglob("transactions.csv"))
    return hits[0].parent if hits else None


base = resolve_baseline(BASELINE_DIR)
if base is None:
    print(f"BASELINE_DIR ({BASELINE_DIR!r}) has no recognizable CSVs — diff sweep skipped.")
else:
    print("baseline:", base)
    for name in SHEETS:
        cur = load(name)
        old = load(name, base)
        if cur is None and old is None:
            continue
        if cur is None or old is None:
            check(INFO, f"{name}: present in only one build",
                  f"cur={cur is not None} base={old is not None}")
            continue
        # column set diff
        cur_cols, old_cols = list(cur.columns), list(old.columns)
        added_cols = [c for c in cur_cols if c not in old_cols]
        removed_cols = [c for c in old_cols if c not in cur_cols]
        shared = [c for c in cur_cols if c in old_cols]
        # align row order by sorting on all shared columns (canonical-ish)
        try:
            c2 = cur[shared].sort_values(shared).reset_index(drop=True)
            o2 = old[shared].sort_values(shared).reset_index(drop=True)
        except Exception:
            c2, o2 = cur[shared], old[shared]
        rows_changed = "n/a"
        if c2.shape == o2.shape:
            rows_changed = int((c2.fillna("") != o2.fillna("")).any(axis=1).sum())
        changed = bool(added_cols or removed_cols or cur.shape[0] != old.shape[0] or (rows_changed not in (0, "n/a")))
        status = "CHANGED" if changed else "identical"
        expected = name in EXPECTED_CHANGED
        tag = INFO
        if changed and not expected:
            tag = FAIL  # unexpected diff
        elif changed and expected:
            tag = PASS  # expected diff present
        detail = (f"rows {old.shape[0]}->{cur.shape[0]}, cols {len(old_cols)}->{len(cur_cols)}"
                  f", changed_rows={rows_changed}")
        if added_cols:
            detail += f", +cols={added_cols}"
        if removed_cols:
            detail += f", -cols={removed_cols}"
        label = f"{name}: {status}" + ("" if expected else " (UNEXPECTED if changed)")
        check(tag, label, detail)


# ---------------------------------------------------------------------------
section("SUMMARY")
print(f"PASS={_counts[PASS]}  FAIL={_counts[FAIL]}  INFO={_counts[INFO]}")
if _fails:
    print("FAILURES:")
    for f in _fails:
        print("  -", f)
# never exit non-zero: we want the whole report regardless
print("AUDIT-DONE")
