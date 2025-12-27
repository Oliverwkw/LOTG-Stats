from __future__ import annotations
from pathlib import Path
from typing import Dict, List
import pandas as pd

def load_plan_catalog(plan_csv: Path) -> Dict[str, List[str]]:
    df = pd.read_csv(plan_csv)
    out = {}
    for col in df.columns:
        vals=[]
        seen=set()
        for v in df[col].dropna().astype(str):
            v=v.strip()
            if not v or v.lower()=="nan":
                continue
            if v not in seen:
                vals.append(v)
                seen.add(v)
        out[col]=vals
    return out

def require_columns(df: pd.DataFrame, cols: List[str], table_name: str) -> None:
    missing=[c for c in cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"{table_name}: missing columns: {missing}")
