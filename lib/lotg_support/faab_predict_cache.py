"""A persistent cache of the frozen base's model predictions, keyed on each row's exact inputs.

A tree model's prediction for a row is a function of that row's feature values only (the same in any batch, at any
thread count), so a row whose features are byte-for-byte what they were last week gets last week's prediction back
without walking the trees again. Most of the grid's 900k rows are past dates whose features do not change from one
weekly rebuild to the next, so most predictions are lookups.

Keys: each row is hashed twice (pandas' hash_pandas_object under two hash keys, 128 bits in all) over exactly the
columns the model reads, in order; the cache is per model (`key`, e.g. ("t", bag, fold)), and the whole store is
tagged with the frozen base's identity, the columns and the library versions, so a new base, a changed column list
or a new scikit-learn starts from empty. A row whose hash is not stored (or is stored twice with different values, which
128 bits make practically impossible) is predicted. Each save keeps only the entries this run used (bounded size).

Not a fit and no value changes: a hit returns the float the model returned for that row before."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

K1, K2 = "lotg-faab-pc-k1!", "lotg-faab-pc-k2?"          # pandas hash keys (16 characters each)


def row_hashes(X):
    """two independent 64-bit hashes per row of X (its values in column order; the index is ignored)"""
    X = X.reset_index(drop=True)
    return (pd.util.hash_pandas_object(X, index=False, hash_key=K1).to_numpy(np.uint64),
            pd.util.hash_pandas_object(X, index=False, hash_key=K2).to_numpy(np.uint64))


def _mix(x):
    """splitmix64's finaliser (a bijection of 64-bit words that spreads every input bit over the output)"""
    x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return x ^ (x >> np.uint64(31))


def combine(ha, hb):
    """the key of rows whose columns are A's then B's, from each part's row_hashes (two 64-bit words per row each)"""
    with np.errstate(over="ignore"):
        return (_mix(ha[0] ^ _mix(hb[0] + np.uint64(0x9E3779B97F4A7C15))),
                _mix(ha[1] ^ _mix(hb[1] + np.uint64(0xD1B54A32D192ED03))))


class PredictCache:
    def __init__(self, path=None, tag=""):
        self.path = Path(path) if path else None
        self.tag = tag
        self.old = {}            # key -> (h1 sorted, h2, value)
        self.new = {}            # key -> list of (h1, h2, value) arrays predicted in this process
        self.used = {}           # key -> list of positions in old[key] read back in this process
        self.hits = self.misses = 0
        self.discard_parts()
        if self.path and (self.path / "meta.json").exists():
            try:
                meta = json.loads((self.path / "meta.json").read_text())
                if meta.get("tag") == tag:
                    with np.load(self.path / "store.npz") as z:
                        for name in meta["keys"]:
                            self.old[_key(name)] = (z[name + ".h1"], z[name + ".h2"], z[name + ".v"])
            except Exception:    # a broken store is just a cold cache
                self.old = {}

    def predict(self, key, fn, X, h=None):
        """fn(X) row by row, from the store where the row's hashes are there (`h`: X's row_hashes, when already taken)"""
        if h is None:
            if callable(X): X = X()
            h = row_hashes(X)
        h1, h2 = h; n = len(h1)
        if n == 0: return np.asarray(fn(X() if callable(X) else X), dtype=float)
        out = np.empty(n); hit = np.zeros(n, bool)
        st = self.old.get(key)
        if st is not None and len(st[0]):
            s1, s2, sv = st
            j = np.searchsorted(s1, h1)
            jc = np.minimum(j, len(s1) - 1)
            hit = (s1[jc] == h1) & (s2[jc] == h2)
            out[hit] = sv[jc[hit]]
            if hit.any(): self.used.setdefault(key, []).append(jc[hit])
        miss = ~hit
        if miss.any():
            if callable(X): X = X()
            out[miss] = np.asarray(fn(X.iloc[np.flatnonzero(miss)] if not miss.all() else X), dtype=float)
            self.new.setdefault(key, []).append((h1[miss], h2[miss], out[miss]))
        self.hits += int(hit.sum()); self.misses += int(miss.sum())
        return out

    def take_new(self):
        """this process's new entries and the stored ones it read, cleared. With a folder they go to a part file there
        (a child process writes its own, so the parent never holds them all); returns (entries or None, hits, misses)"""
        out = {k: tuple(np.concatenate([e[i] for e in v]) for i in range(3)) for k, v in self.new.items()}
        used = {k: np.unique(np.concatenate(v)) for k, v in self.used.items()}
        self.new, self.used = {}, {}; h, m = self.hits, self.misses; self.hits = self.misses = 0
        if self.path is None:
            return (out, used), h, m
        if out or used:
            import os
            import uuid
            d = self.path / "parts"; d.mkdir(parents=True, exist_ok=True)
            arrs = {}
            for k, (a1, a2, v) in out.items():
                n = _name(k); arrs[n + ".h1"], arrs[n + ".h2"], arrs[n + ".v"] = a1, a2, v
            for k, u in used.items(): arrs[_name(k) + ".u"] = u
            np.savez(d / f"{os.getpid()}-{uuid.uuid4().hex}.npz", **arrs)
        return None, h, m

    def add(self, entries):
        """(new, used) from take_new without a folder (in memory)"""
        if entries is None: return
        new, used = entries
        for k, e in new.items(): self.new.setdefault(k, []).append(e)
        for k, u in used.items(): self.used.setdefault(k, []).append(u)

    def save(self):
        """keep exactly the entries used in this run: the stored ones read back plus the new ones (one per row hash)"""
        if not self.path: return
        self.take_new()                       # this process's own, to a part file like the children's
        d = self.path / "parts"
        parts = [np.load(f) for f in sorted(d.glob("*.npz"))] if d.exists() else []
        keys = sorted({f.rsplit(".", 1)[0] for z in parts for f in z.files})
        arrs = {}
        for name in keys:
            k = _key(name); pieces = []
            us = [z[name + ".u"] for z in parts if name + ".u" in z.files]
            if us and k in self.old:
                u = np.unique(np.concatenate(us)); pieces.append(tuple(a[u] for a in self.old[k]))
            pieces += [(z[name + ".h1"], z[name + ".h2"], z[name + ".v"]) for z in parts if name + ".h1" in z.files]
            h1, h2, v = (np.concatenate([p_[i] for p_ in pieces]) for i in range(3))
            o = np.lexsort((h2, h1)); h1, h2, v = h1[o], h2[o], v[o]
            keep = np.r_[True, (h1[1:] != h1[:-1]) | (h2[1:] != h2[:-1])]
            h1, h2, v = h1[keep], h2[keep], v[keep]
            dup = np.r_[h1[1:] == h1[:-1], False] | np.r_[False, h1[1:] == h1[:-1]]    # one h1 twice: drop both
            arrs[name + ".h1"], arrs[name + ".h2"], arrs[name + ".v"] = h1[~dup], h2[~dup], v[~dup]
        for z in parts: z.close()
        self.old = {}
        tmp = self.path / "store.tmp.npz"
        np.savez(tmp, **arrs)
        tmp.replace(self.path / "store.npz")
        (self.path / "meta.json").write_text(json.dumps(dict(tag=self.tag, keys=keys)))
        for f in d.glob("*.npz"): f.unlink()

    def discard_parts(self):
        """drop part files left by an earlier run that stopped before saving"""
        d = self.path / "parts" if self.path else None
        if d is not None and d.exists():
            for f in d.glob("*.npz"): f.unlink()


def _name(key):
    return "-".join(str(x) for x in key)


def _key(name):
    a = name.split("-")
    return tuple([a[0]] + [int(x) for x in a[1:]])


def code_id(f):
    """a function's compiled code (bytecode, constants, names; nested code too), not its file or line numbers: an
    edit to what it does changes the id, moving it in the file does not"""
    def walk(c):
        h.update(c.co_code); h.update(repr(c.co_names).encode()); h.update(repr(c.co_varnames).encode())
        for k in c.co_consts:
            if hasattr(k, "co_code"): walk(k)
            elif isinstance(k, frozenset): h.update(repr(sorted(map(repr, k))).encode())     # set order varies by run
            else: h.update(repr(k).encode())
    h = hashlib.sha256(); walk(f.__code__)
    return h.hexdigest()


def tag_for(meta, extra=""):
    """the store's identity: the frozen base's manifest, the model inputs' column lists and the library versions"""
    import sklearn
    h = hashlib.sha256(json.dumps(meta, sort_keys=True, default=str).encode())
    h.update(f"{sklearn.__version__}|{np.__version__}|{pd.__version__}|{extra}".encode())
    return h.hexdigest()
