from __future__ import annotations

import csv
from pathlib import Path

# 单元格视为「收集」：1、y、yes、true、x、是、√ 等（不区分大小写）
_TRUTHY = frozenset(
    {
        "1",
        "y",
        "yes",
        "true",
        "x",
        "是",
        "√",
        "✓",
        "*",
    }
)

# 首列允许表头名（不区分大小写）
_UNIT_HEADER_ALIASES = frozenset({"unit", "课文", "课文目录", "label"})


def _cell_truthy(raw: str) -> bool:
    v = raw.strip().lower()
    if not v:
        return False
    return v in _TRUTHY


def _normalize_fieldnames(fieldnames: list[str]) -> tuple[str, list[str]]:
    """首列视为课文目录列，返回 (unit_key, 其余列名列表)。"""
    if not fieldnames:
        raise ValueError("TOC CSV 表头为空")
    u0 = fieldnames[0].strip()
    if u0.lower() not in {x.lower() for x in _UNIT_HEADER_ALIASES} and fieldnames[0]:
        # 仍允许任意首列名：固定第 0 列为 unit
        unit_key = fieldnames[0]
    else:
        unit_key = fieldnames[0]
    rest = list(fieldnames[1:])
    return unit_key, rest


def load_toc_csv(path: Path) -> tuple[str, list[str], list[dict[str, str]]]:
    """
    读取 TOC CSV。
    返回 (unit 列名, 标志列名列表, 行字典列表；每行含 unit 列与各标志列原文)。
    """
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"TOC CSV 为空: {path}")
    reader = csv.DictReader(lines)
    if not reader.fieldnames:
        raise ValueError(f"TOC CSV 无表头: {path}")
    fn = [f.strip() for f in reader.fieldnames if f is not None and f.strip()]
    if not fn:
        raise ValueError(f"TOC CSV 表头无效: {path}")
    unit_key, flag_keys = _normalize_fieldnames(fn)
    rows_out: list[dict[str, str]] = []
    for row in reader:
        if row is None:
            continue
        unit_val = (row.get(unit_key) or "").strip()
        if not unit_val:
            continue
        clean: dict[str, str] = {unit_key: unit_val}
        for k in flag_keys:
            clean[k] = (row.get(k) or "").strip()
        rows_out.append(clean)
    return unit_key, flag_keys, rows_out


def toc_units_for_column(path: Path, column: str) -> list[str]:
    """
    按列名筛选「收集」为真的行，保持 CSV 自上而下顺序，返回课文目录字符串列表。
    """
    unit_key, flag_keys, rows = load_toc_csv(path)
    if column not in flag_keys:
        raise KeyError(
            f"TOC CSV {path} 中无列 «{column}»，现有列: {flag_keys}"
        )
    out: list[str] = []
    for row in rows:
        if _cell_truthy(row.get(column, "")):
            out.append(row[unit_key].strip())
    return out
