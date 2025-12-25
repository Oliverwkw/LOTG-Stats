from __future__ import annotations

import os
from typing import Dict

import pandas as pd


def _best_fit_width(series: pd.Series) -> int:
    max_len = max(
        [len(str(x)) for x in series.astype(str).fillna("")]
        + [len(series.name or "")]
    )
    return min(60, max(10, max_len + 2))


def _write_sheet(writer: pd.ExcelWriter, name: str, df: pd.DataFrame) -> None:
    df.to_excel(writer, sheet_name=name, index=False)
    worksheet = writer.sheets[name]
    worksheet.freeze_panes(1, 4)

    if not df.empty:
        worksheet.autofilter(0, 0, df.shape[0], df.shape[1] - 1)

    for idx, col in enumerate(df.columns):
        width = _best_fit_width(df[col])
        worksheet.set_column(idx, idx, width)


def write_workbook(tables: Dict[str, pd.DataFrame], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        for name, df in tables.items():
            _write_sheet(writer, name, df)
