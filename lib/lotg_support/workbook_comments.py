"""The build workbook's asset-history hover comments, read straight from the .xlsx.

The build (src/lotg.py, "i5 (#15)") writes each player's and each draft pick's
full history (draft, every add, drop and trade with the whole deal) only as a
hover comment on column A of `player_all_time`, `rookie_picks` and
`non_rookie_picks` in exports/LOTG_Stats.xlsx. The workbook is not committed;
every build uploads it in the LOTG_outputs artifact. This reads those comments
without openpyxl, which takes about a minute to load the whole workbook: it
parses only the comment parts and column A of the three sheets.

`histories(path)` -> {sheet: [(row_index, column_A_value, text), ...]}, where
row_index is the 0-based data row (row 2 of the sheet is row 0, matching the
CSV), so a caller can check column A against its own copy of the sheet.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

HISTORY_SHEETS = ("player_all_time", "rookie_picks", "non_rookie_picks")

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
_M = "{%s}" % _NS["m"]
_COMMENTS_REL = re.compile(r'<Relationship[^>]*Type="[^"]*/comments"[^>]*>')
_TARGET = re.compile(r'Target="([^"]+)"')
_REF = re.compile(r"^([A-Z]+)(\d+)$")


def _resolve(base: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(_M + "t"))


def _sheet_paths(z: zipfile.ZipFile) -> Dict[str, str]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels.findall("p:Relationship", _NS)}
    out = {}
    for s in wb.iter(_M + "sheet"):
        rid = s.get("{%s}id" % _NS["r"])
        if rid in target:
            out[s.get("name")] = _resolve("xl/workbook.xml", target[rid])
    return out


def _shared_strings(z: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    out = []
    with z.open("xl/sharedStrings.xml") as fh:
        for _ev, el in ET.iterparse(fh):
            if el.tag == _M + "si":
                out.append(_text(el))
                el.clear()
    return out


def _column_a(z: zipfile.ZipFile, sheet_path: str, strings: List[str]) -> Dict[int, str]:
    """{sheet row number: column A's displayed value}."""
    out: Dict[int, str] = {}
    with z.open(sheet_path) as fh:
        for _ev, el in ET.iterparse(fh):
            if el.tag == _M + "c":
                m = _REF.match(el.get("r") or "")
                if m and m.group(1) == "A":
                    v = el.find(_M + "v")
                    t = el.get("t")
                    if t == "s" and v is not None:
                        out[int(m.group(2))] = strings[int(v.text)]
                    elif t == "inlineStr":
                        out[int(m.group(2))] = _text(el)
                    elif v is not None:
                        out[int(m.group(2))] = v.text
                el.clear()
            elif el.tag == _M + "row":
                el.clear()
    return out


def _comments(z: zipfile.ZipFile, sheet_path: str) -> Dict[int, str]:
    """{sheet row number: comment text} for column A."""
    rels_path = posixpath.join(posixpath.dirname(sheet_path), "_rels",
                               posixpath.basename(sheet_path) + ".rels")
    if rels_path not in z.namelist():
        return {}
    # sheet rels can run to megabytes of hyperlinks: find the comments part by regex
    rel = _COMMENTS_REL.search(z.read(rels_path).decode("utf-8", "ignore"))
    if not rel:
        return {}
    path = _resolve(sheet_path, _TARGET.search(rel.group(0)).group(1))
    out: Dict[int, str] = {}
    with z.open(path) as fh:
        for _ev, el in ET.iterparse(fh):
            if el.tag == _M + "comment":
                m = _REF.match(el.get("ref") or "")
                if m and m.group(1) == "A":
                    out[int(m.group(2))] = _text(el).strip()
                el.clear()
    return out


def histories(path, sheets=HISTORY_SHEETS) -> Optional[Dict[str, List[Tuple[int, str, str]]]]:
    """None when there is no workbook (a local build); else every column-A
    history on `sheets`, data rows only (the header's tooltip is skipped)."""
    path = Path(path)
    if not path.exists():
        return None
    with zipfile.ZipFile(path) as z:
        paths = _sheet_paths(z)
        strings = None
        out: Dict[str, List[Tuple[int, str, str]]] = {}
        for sheet in sheets:
            if sheet not in paths:
                continue
            notes = {r: t for r, t in _comments(z, paths[sheet]).items() if r >= 2 and t}
            if not notes:
                out[sheet] = []
                continue
            if strings is None:
                strings = _shared_strings(z)
            col_a = _column_a(z, paths[sheet], strings)
            out[sheet] = [(r - 2, col_a.get(r, ""), t) for r, t in sorted(notes.items())]
        return out
