"""No new `dtype == object` text checks.

CI runs pandas 3, which reads CSV text as the `str` dtype, not `object`; pandas 2
(an older local install) reads it as `object`. A check written `dtype == object`
is therefore true on one and false on the other. It broke the digest's running
totals in every real email while the local run looked right (memory
ci-runs-pandas3). Use `pd.api.types.is_string_dtype` / `is_numeric_dtype`.

The lines below are the reviewed exceptions: each either ORs in the pandas-3
spelling or casts on purpose. A new match fails until it is fixed or listed here
with its reason.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_PATTERN = re.compile(
    r"dtype\s*(==|!=|\bis\b)\s*(object\b|np\.object_|['\"]O['\"]|['\"]object['\"])"
    r"|\.kind\s*(==|in)\s*\(?\s*['\"]O"
    r"|select_dtypes\(\s*include\s*=\s*\[?\s*['\"]?object"
    r"|is_object_dtype\(")

# (file, the matching line's code, why it is safe on both pandas versions)
ALLOWED = {
    ("lib/lotg_support/db.py", "return col.dtype == object or pd.api.types.is_string_dtype(col)"):
        "ORs in the pandas-3 str dtype",
    ("lib/lotg_support/fast.py", "if not (col.dtype == object or pd.api.types.is_string_dtype(col)):"):
        "ORs in the pandas-3 str dtype",
    ("lib/lotg_support/external.py", "if df[col].dtype != object:"):
        "deliberate cast to object before writing position labels; a no-op on object",
    ("lib/lotg_support/digest.py",
     "text_cols = [c for c in df.columns if df[c].dtype == object or str(df[c].dtype) in (\"str\", \"string\")]"):
        "ORs in the pandas-3 str dtype",
}


def _matches():
    for top in ("src", "lib", "scripts"):
        for p in sorted((_ROOT / top).rglob("*.py")):
            rel = p.relative_to(_ROOT).as_posix()
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                code = line.split("#", 1)[0]
                if _PATTERN.search(code):
                    yield rel, i, code.strip()


def test_no_new_object_dtype_checks():
    bad = [f"{rel}:{i}: {code}" for rel, i, code in _matches() if (rel, code) not in ALLOWED]
    assert not bad, ("dtype checks that differ between pandas 2 and 3 (use "
                     "pd.api.types.is_string_dtype):\n  " + "\n  ".join(bad))


def test_the_allowlist_has_no_stale_entries():
    seen = {(rel, code) for rel, _i, code in _matches()}
    stale = [k for k in ALLOWED if k not in seen]
    assert not stale, f"ALLOWED lists lines that no longer exist: {stale}"


def test_the_pattern_catches_the_spellings():
    for s in ("df.x.dtype == object", "s.dtype != 'O'", 'col.dtype == "object"', "a.dtype.kind == 'O'",
              "df.select_dtypes(include=['object'])", "pd.api.types.is_object_dtype(s)"):
        assert _PATTERN.search(s), s
    assert not _PATTERN.search("pd.api.types.is_string_dtype(s)")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
