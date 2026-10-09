"""Read every sheet of an XLS or XLSX attachment as labeled rows."""

from pathlib import Path

import pandas as pd


def parse_excel(path: Path) -> str:
    sections: list[str] = []
    with pd.ExcelFile(path) as workbook:
        for sheet_name in workbook.sheet_names:
            frame = pd.read_excel(workbook, sheet_name=sheet_name, header=None, dtype=str, keep_default_na=False)
            rows = []
            for row in frame.itertuples(index=False, name=None):
                values = [str(value).strip() for value in row]
                if any(values):
                    rows.append(" | ".join(values))
            if rows:
                sections.append(f"工作表：{sheet_name}\n" + "\n".join(rows))
    return "\n\n".join(sections)
