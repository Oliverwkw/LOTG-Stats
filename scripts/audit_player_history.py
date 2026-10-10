"""Audit player-history continuity (roster lineage).

Every player's Sleeper-style history (the hover-comment built in lotg.py and
surfaced on the player_all_time / picks sheets) should be an unbroken chain of
roster events: a player can only be *dropped* or *traded away* by a team that
currently holds them, and can only be *added off free agency / waivers* when no
team holds them. A break in that chain means a step is missing — the player
"teleports" onto or off of a roster.

This script reconstructs each player's holder timeline from the history text
embedded as cell comments in `exports/LOTG_Stats.xlsx` and reports every break:

  MISSING_ARRIVAL_BEFORE_DROP  dropped by a team that wasn't holding the player
  MISSING_ARRIVAL_BEFORE_TRADE traded away a player the team didn't hold
  MISSING_DROP                 picked up off FA while another team still held them

Exit code is non-zero when any break is found, so it can gate CI.

Usage: python3 scripts/audit_player_history.py [path/to/LOTG_Stats.xlsx]

The workbook is NOT committed (see .gitignore) — it is a build output. Pass the
path to one you built yourself, or to the copy inside the LOTG_outputs artifact
of the run you want to audit. With no argument this still looks in `exports/`,
which is where a local `python -m lotg` puts it.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_RE_ADD = re.compile(r"^(\d{4}-\d{2}-\d{2}): added by (\S+) \((?:free agent|waiver \$\d+)")
_RE_TRADE = re.compile(r"^(\d{4}-\d{2}-\d{2}): traded to (\S+) \(.*\)$")
_RE_DROP = re.compile(r"^(\d{4}-\d{2}-\d{2}): (?:dropped|released) by (\S+)")
# Draft-arrival line. Matches the plain "YYYY Draft:"/"YYYY draft:" form and any
# draft-descriptor prefix before "draft:" — e.g. "YYYY supplemental veteran draft:"
# (the 2021 vet draft) and the legacy "YYYY startup (vet) draft:" wording.
_RE_DRAFT = re.compile(r"^(\d{4}) (?:[\w() ]+ )?[Dd]raft: (\S+) ")
_RE_HDR = re.compile(r"^(\d{4}).* — originally (\S+)'s pick")
_RE_CMOVE = re.compile(r"^(\d{4}): Commissioner moved to (\S+)$")
_RE_PICKHOP = re.compile(r"^(\d{4}-\d{2}-\d{2}): pick traded to ")


_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_DOCREL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKGREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _ooxml_text(node) -> str:
    """openpyxl's `Text.content`: the plain <t> then every run's <t>, joined."""
    parts = []
    t = node.find(f"{_MAIN}t")
    if t is not None and t.text is not None:
        parts.append(t.text)
    for r in node.findall(f"{_MAIN}r"):
        rt = r.find(f"{_MAIN}t")
        if rt is not None and rt.text is not None:
            parts.append(rt.text)
    return "".join(parts)


def load_history_comments(xlsx_path: Path) -> dict[str, str]:
    """{"<sheet>:<column-A value>": comment text} for the history sheets, read
    straight from the workbook's XML parts. openpyxl.load_workbook parsed all 15
    sheets with their styles to reach these comments — ~2.5 minutes of every
    CI test run. Same answer as `_load_history_comments_openpyxl` (kept as the
    reference): values cast as openpyxl casts them, comment text as its
    `Text.content` joins it, the first row seen kept."""
    import posixpath
    import zipfile
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(xlsx_path) as z:
        names = set(z.namelist())
        rels = {r.get("Id"): r.get("Target") for r in
                ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(f"{_PKGREL}Relationship")}

        def part(base: str, target: str) -> str:
            return target.lstrip("/") if target.startswith("/") else \
                posixpath.normpath(posixpath.join(posixpath.dirname(base), target))
        sheets = {sh.get("name"): part("xl/workbook.xml", rels[sh.get(f"{_DOCREL}id")])
                  for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{_MAIN}sheet")}
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = [_ooxml_text(si).replace("x005F_", "") for si in
                      ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{_MAIN}si")]
        out: dict[str, str] = {}
        for sheet in ("player_all_time", "non_rookie_picks", "rookie_picks"):
            sp = sheets.get(sheet)
            if sp is None:
                continue
            rp = posixpath.join(posixpath.dirname(sp), "_rels", posixpath.basename(sp) + ".rels")
            if rp not in names:
                continue
            cp = next((part(sp, r.get("Target")) for r in ET.fromstring(z.read(rp)).iter(f"{_PKGREL}Relationship")
                       if r.get("Type", "").endswith("/comments")), None)
            if cp is None:
                continue
            by_row: dict[int, str] = {}
            for c in ET.fromstring(z.read(cp)).iter(f"{_MAIN}comment"):
                m = re.fullmatch(r"([A-Z]+)(\d+)", c.get("ref", ""))
                if m and m.group(1) == "A":
                    by_row[int(m.group(2))] = _ooxml_text(c.find(f"{_MAIN}text"))
            vals: dict[int, object] = {}
            for _, el in ET.iterparse(z.open(sp)):
                if el.tag == f"{_MAIN}c":
                    m = re.fullmatch(r"A(\d+)", el.get("r", ""))
                    if m and int(m.group(1)) in by_row:
                        kind, v = el.get("t", "n"), el.find(f"{_MAIN}v")
                        raw = v.text if v is not None else None
                        if kind == "inlineStr":
                            is_ = el.find(f"{_MAIN}is")
                            val = _ooxml_text(is_) if is_ is not None else None
                        elif raw is None:
                            val = None
                        elif kind == "s":
                            val = shared[int(raw)]
                        elif kind == "n":
                            val = float(raw) if any(ch in raw for ch in ".Ee") else int(raw)
                        elif kind == "b":
                            val = bool(int(raw))
                        else:
                            val = raw
                        vals[int(m.group(1))] = val
                elif el.tag == f"{_MAIN}row":
                    el.clear()
            for row in sorted(by_row):
                out.setdefault(f"{sheet}:{vals.get(row)}", by_row[row])
    return out


def _load_history_comments_openpyxl(xlsx_path: Path) -> dict[str, str]:
    """The reference reader `load_history_comments` replaced (slow: loads the
    whole workbook). Kept for the equivalence check."""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=False)
    out: dict[str, str] = {}
    for sheet in ("player_all_time", "non_rookie_picks", "rookie_picks"):
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        for row in ws.iter_rows():
            for c in row:
                if c.comment and c.column == 1:
                    key = str(c.value)
                    # player_all_time keys by player name; keep the first seen.
                    out.setdefault(f"{sheet}:{key}", c.comment.text)
    return out


def audit_text(name: str, txt: str) -> list[tuple]:
    """Return a list of (name, date, kind, detail, line) breaks for one history."""
    breaks = []
    holder = None
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _RE_ADD.match(line)
        if m:
            d, team = m.group(1), m.group(2)
            if holder is not None and holder != team:
                breaks.append((name, d, "MISSING_DROP",
                               f"FA/waiver add by {team} while still held by {holder}", line))
            holder = team
            continue
        m = _RE_TRADE.match(line)
        if m:
            d, team = m.groups()
            if holder is None:
                breaks.append((name, d, "MISSING_ARRIVAL_BEFORE_TRADE",
                               f"traded to {team} but not on any roster", line))
            holder = team
            continue
        m = _RE_DROP.match(line)
        if m:
            d, team = m.group(1), m.group(2)
            if holder != team:
                breaks.append((name, d, "MISSING_ARRIVAL_BEFORE_DROP",
                               f"dropped by {team} but held by {holder}", line))
            holder = None
            continue
        m = _RE_DRAFT.match(line)
        if m:
            d, team = m.groups()
            holder = team
            continue
        if _RE_HDR.match(line) or _RE_CMOVE.match(line) or _RE_PICKHOP.match(line):
            continue
        # Unrecognized line — surface so the parser stays honest as text evolves.
        breaks.append((name, "", "UNPARSED", "history line not recognized", line))
    return breaks


def main() -> int:
    xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else (REPO / "exports" / "LOTG_Stats.xlsx")
    if not xlsx.exists():
        print(f"no xlsx at {xlsx}", file=sys.stderr)
        return 2
    comments = load_history_comments(xlsx)
    # De-dup: the same player appears on both player_all_time and (as a drafted
    # pick) picks — audit the player_all_time copy, fall back to picks.
    seen_player: dict[str, str] = {}
    for k, v in comments.items():
        sheet, name = k.split(":", 1)
        if sheet == "player_all_time":
            seen_player[name] = v
    for k, v in comments.items():
        sheet, name = k.split(":", 1)
        if sheet in ("non_rookie_picks", "rookie_picks"):
            seen_player.setdefault(name, v)

    all_breaks = []
    for name, txt in seen_player.items():
        all_breaks.extend(audit_text(name, txt))

    real = [b for b in all_breaks if b[2] != "UNPARSED"]
    unparsed = [b for b in all_breaks if b[2] == "UNPARSED"]

    print(f"players audited: {len(seen_player)}")
    print(f"continuity breaks: {len(real)}  {dict(Counter(b[2] for b in real))}")
    if unparsed:
        print(f"unparsed lines: {len(unparsed)} (parser may need updating)")
    print("=" * 70)
    for b in sorted(real):
        print(f"{b[0]:26} {b[1]} {b[2]:30} | {b[4]}")

    return 1 if real else 0


if __name__ == "__main__":
    sys.exit(main())
