"""The league website generator (`lotg_support.league_site`).

- numbers carry the workbook's format (decimals, fraction vs 0-100 percent);
- the digest email parses into its sections, edits flagged;
- a full build (no forecast) writes valid JSON for every page, and it
  reconciles with the exports: every trades row lands on exactly one trade
  side, the head-to-head matrix is antisymmetric and matches team_week, the
  standings' games equal the regular-season weeks played, every team and
  every player has a page and player keys are unique;
- the Data page holds every sheet of exports/ whole (rows, columns, cells) and
  its downloads are the committed CSVs;
- privacy: nothing in the output carries a private marker (DM/chat exports,
  negotiation notes, manager profiles, credentials), and the shell never
  shadows docs/rate/ (the rating page and its vote collection).

`python tests/test_league_site.py --check-dir DIR` runs only the privacy scan
on a built site (the Pages workflow does this before uploading).
Skips cleanly without `exports/`. Run: python tests/test_league_site.py
"""
from __future__ import annotations

import functools
import json
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "lib"))

from lotg_support import league_site as S  # noqa: E402

_HAVE_EXPORTS = (_ROOT / "exports" / "team_week.csv").exists()

# Anything that would mean private material reached the public site.
PRIVATE_MARKERS = re.compile(
    r"negotiation[-_ ]styles|manager[-_ ]profiles|sleeper[-_]chat|direct message|"
    r"smtp|app[-_ ]password|DIGEST_(?:SMTP|PASS|KEY)|BEGIN (?:RSA|OPENSSH) PRIVATE|"
    r"\bghp_[A-Za-z0-9]{20,}|okeimweiss@", re.I)


def _skip(reason: str) -> bool:
    print(f"  SKIP — {reason}")
    return True


@functools.lru_cache(maxsize=1)
def _built() -> Path:
    out = Path(tempfile.mkdtemp(prefix="lotg_site_")) / "site"
    S.build(out, forecast=False)
    return out


def _load(rel: str):
    return json.loads((_built() / "data" / rel).read_text(encoding="utf-8"))


def privacy_problems(site_dir: Path) -> list:
    problems = []
    for f in Path(site_dir).rglob("*"):
        if not f.is_file() or f.suffix not in (".json", ".html", ".js", ".css", ".txt", ".md", ".csv"):
            continue
        if any(part in ("rate",) for part in f.relative_to(site_dir).parts[:1]):
            continue        # docs/rate/ is published today already; it is not generated here
        m = PRIVATE_MARKERS.search(f.read_text(encoding="utf-8", errors="ignore"))
        if m:
            problems.append(f"{f.relative_to(site_dir)}: {m.group(0)!r}")
    return problems


# ---------------------------------------------------------------- pure logic

def test_column_format_follows_the_workbook():
    assert S.column_format("Win %") == {"d": 2, "p": "x"}
    assert S.column_format("Tanking") == {"d": 4}
    assert S.column_format("Number of trades") == {"d": 0}
    assert S.column_format("PF") == {"d": 2}
    assert S.column_format("Starter boom %") == {"d": 2, "p": "%"}
    assert S.column_format("Date") == {}


def test_clean_is_json_safe():
    import numpy as np
    assert S._clean(float("nan")) is None
    assert S._clean(np.int64(3)) == 3
    assert S._clean(np.float64(2.0)) == 2
    assert S._clean("N/A") is None
    assert S._clean(np.bool_(True)) is True


def test_digest_parser_reads_sections_and_flags_edits():
    html = """<h1>LOTG weekly digest — 2026 season, week 7</h1>
    <p>Rate the board: x</p><p>The lede &amp; more.</p>
    <h2>Records</h2><h3>Single-week records (this week)</h3>
    <ul><li>A: <ul><li>one</li><li>two</li></ul></li><li>B did it.</li></ul>
    <h2>Changes from edits, not new data</h2><h3>Trades</h3><ul><li>C moved.</li></ul>"""
    p = S._DigestParser()
    p.feed(html)
    p._flush()
    assert p.title.startswith("LOTG weekly digest")
    assert p.lede == "The lede & more."
    secs = [s for s in p.sections if s["items"]]
    assert secs[0]["title"] == "Single-week records (this week)" and secs[0]["group"] == "Records"
    assert secs[0]["items"] == ["A: · one · two", "B did it."]
    assert secs[-1]["edits"] is True and not secs[0]["edits"]


def test_shell_does_not_shadow_the_rating_page():
    names = {f.name for f in S.SHELL.iterdir()}
    assert {"index.html", "app.js", "style.css"} <= names
    assert "rate" not in names and "data" not in names
    assert (_ROOT / "docs" / "rate" / "index.html").exists()


# ---------------------------------------------------------------- a real build

def _build_writes_every_page():
    meta = _load("meta.json")
    assert meta["teams"] and meta["season"] >= 2026
    for team in meta["teams"]:
        t = _load(f"team/{S.slug(team)}.json")
        assert t["team"] == team and t["seasons"]["rows"]
    for rel in ("home.json", "h2h.json", "trades.json", "draft.json", "search.json"):
        assert _load(rel) is not None
    for sheet in S.RECORD_SHEETS:
        r = _load(f"records/{sheet}.json")
        assert r["columns"], sheet


def _every_trade_row_is_one_side():
    rows = pd.read_csv(_ROOT / "exports" / "trades.csv")
    trades = _load("trades.json")["trades"]
    sides = [(s["team"], t["season"]) for t in trades for s in t["sides"]]
    assert len(sides) == len(rows)
    ids = [t["id"] for t in trades]
    assert len(set(ids)) == len(ids)
    for t in trades:
        assert len({s["team"] for s in t["sides"]}) == len(t["sides"]) >= 2, t["id"]


def _head_to_head_matches_team_week():
    m = _load("h2h.json")
    tw = pd.read_csv(_ROOT / "exports" / "team_week.csv", low_memory=False).dropna(subset=["Opponent"])
    win = tw["Win?"].astype(str).str.lower().eq("true")
    for key, c in m["cells"].items():
        a, b = key.split("|")
        other = m["cells"][f"{b}|{a}"]
        assert (c["w"], c["l"]) == (other["l"], other["w"]), (a, b)
        mask = (tw.Team == a) & (tw.Opponent == b)
        assert c["w"] == int(win[mask].sum()) and c["w"] + c["l"] == int(mask.sum())
        assert c["rw"] + c["pw"] == c["w"]


def _standings_count_regular_season_games():
    meta, home = _load("meta.json"), _load("home.json")
    tw = pd.read_csv(_ROOT / "exports" / "team_week.csv", low_memory=False)
    cur = tw[(pd.to_numeric(tw.Year, errors="coerce") == meta["season"])
             & tw["Week Name"].astype(str).str.startswith("Week ")]
    games = cur.groupby("Team").size()
    for r in home["standings"]:
        assert r["w"] + r["l"] == games[r["team"]]
    assert sorted(r["rank"] for r in home["standings"]) == list(range(1, len(games) + 1))


def _players_have_unique_pages():
    idx = _load("search.json")
    keys = [r[1] for r in idx if r[0] == "p"]
    assert len(keys) == len(set(keys))
    pa = pd.read_csv(_ROOT / "exports" / "player_all_time.csv")
    names = {r[2] for r in idx if r[0] == "p"}
    assert set(pa.Player.dropna()) <= names
    files = {f.stem for f in (_built() / "data" / "player").iterdir()}
    assert set(keys) == files


def _every_export_cell_is_on_the_site():
    """The Data page carries every sheet in exports/, every row and every column,
    and the downloads are the committed CSVs byte for byte."""
    import filecmp
    ix = _load("sheets/index.json")["sheets"]
    sheets = sorted(p.stem for p in (_ROOT / "exports").glob("*.csv"))
    assert [m["sheet"] for m in ix] == sheets
    for m in ix:
        csv = _ROOT / "exports" / f"{m['sheet']}.csv"
        df = pd.read_csv(csv, low_memory=False)
        assert m["cols"] == [str(c) for c in df.columns], m["sheet"]
        rows = [r for _, key, _n in m["chunks"] for r in _load(f"sheets/{m['sheet']}/{key}.json")["rows"]]
        assert len(rows) == len(df) == m["rows"], m["sheet"]
        assert all(len(r) == len(m["cols"]) for r in rows), m["sheet"]
        # every non-empty cell survives (numbers to the workbook's places and beyond)
        filled = int(df.notna().sum().sum())
        kept = sum(1 for r in rows for v in r if v is not None)
        assert kept >= filled - int((df.astype(str) == "N/A").sum().sum()), m["sheet"]
        assert filecmp.cmp(csv, _built() / m["csv"], shallow=False), m["sheet"]


def _output_has_nothing_private():
    assert privacy_problems(_built()) == []
    # the generator names no private source in its code (docstrings aside)
    import ast
    tree = ast.parse(Path(S.__file__).read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    assert "plan" not in strings
    assert not [x for x in strings if re.search(r"plan/|memory|sleeper-chat|negotiation|\.claude", x, re.I)]


def test_built_site_reconciles():
    """One build (about 15 s), every reconciliation on it. One test, so pytest-xdist
    workers do not each build the site again."""
    if not _HAVE_EXPORTS:
        return _skip("no exports/")
    for check in (_build_writes_every_page, _every_trade_row_is_one_side,
                  _head_to_head_matches_team_week, _standings_count_regular_season_games,
                  _players_have_unique_pages, _every_export_cell_is_on_the_site,
                  _output_has_nothing_private):
        check()


def test_privacy_scan_catches_a_leak():
    d = Path(tempfile.mkdtemp(prefix="lotg_leak_"))
    (d / "data").mkdir()
    (d / "data" / "x.json").write_text('{"note": "see negotiation-styles.md"}')
    assert privacy_problems(d)


TESTS = [
    test_column_format_follows_the_workbook,
    test_clean_is_json_safe,
    test_digest_parser_reads_sections_and_flags_edits,
    test_shell_does_not_shadow_the_rating_page,
    test_built_site_reconciles,
    test_privacy_scan_catches_a_leak,
]


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check-dir":
        bad = privacy_problems(Path(sys.argv[2]))
        for b in bad:
            print("PRIVATE:", b)
        sys.exit(1 if bad else 0)
    for fn in TESTS:
        print(f"{fn.__name__}:")
        fn()
        print("  ok")
    print("\nall league-site checks passed")
