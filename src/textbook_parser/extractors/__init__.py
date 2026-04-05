from __future__ import annotations

from typing import Any, Callable

from . import char_tables, layout_toc, word_table

ExtractorFn = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]

REGISTRY: dict[str, ExtractorFn] = {
    "char_tables": char_tables.extract_char_table,
    "layout_toc": layout_toc.extract_layout_toc,
    "word_table": word_table.extract_word_table,
}


def get_extractor(name: str) -> ExtractorFn:
    if name not in REGISTRY:
        raise KeyError(f"未知提取器模块: {name}，已知: {sorted(REGISTRY)}")
    return REGISTRY[name]
