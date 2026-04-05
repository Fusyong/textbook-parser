from __future__ import annotations

import re
import sys
from collections.abc import Callable
from typing import Any

from .char_tables import (
    _compile_fullmatch,
    _fullmatch_any,
    _log_discard,
    _noise_category,
    _normalize_spaces,
    _section_from_compact,
    _strip_internal_keys,
    _strip_tabs,
    _toc_alignment_report,
    assign_toc_units,
    compact_for_match,
    parse_toc_entry,
    slice_region,
)

# 词语行：课次号 + 若干词语（空格分隔，含多字词）
_WORD_LESSON_RE = re.compile(r"^\s*(\d{1,2})\s+(.+)$")
# 三年级起常见：整行以「语文园地」起首，后接词语（无课次号）
_GARDEN_WORDS_RE = re.compile(r"^\s*语文园地\s+(.+)$")
_CJK_TOKEN = re.compile(r"[\u4e00-\u9fff·]")


def _tokens_from_tail(tail: str) -> list[str]:
    s = _normalize_spaces(tail)
    return [w for w in s.split() if w and _CJK_TOKEN.search(w)]


def _parse_word_lesson_line(raw: str) -> tuple[str, list[str], str] | None:
    line = _strip_tabs(raw).replace("\f", "").replace("\r", "")
    s = _normalize_spaces(line)
    if not s:
        return None
    m = _WORD_LESSON_RE.match(s)
    if m:
        lesson, tail = m.group(1), m.group(2)
        words = _tokens_from_tail(tail)
        return (lesson, words, raw.rstrip())
    gm = _GARDEN_WORDS_RE.match(s)
    if gm:
        words = _tokens_from_tail(gm.group(1))
        return ("语文园地", words, raw.rstrip())
    return None


def _continuation_words(raw: str) -> list[str] | None:
    line = _strip_tabs(raw).replace("\f", "").replace("\r", "")
    s = _normalize_spaces(line)
    if not s or _WORD_LESSON_RE.match(s) or _GARDEN_WORDS_RE.match(s):
        return None
    words = _tokens_from_tail(s)
    return words if words else None


def parse_word_table_body(
    body: str,
    *,
    total_pattern: str | None,
    closing_line: str,
    discard_compiled: list[re.Pattern[str]],
    log_prefix: str,
    discard_sink: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines = body.splitlines()
    section: str | None = None
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {"total_note": None, "word_count_computed": 0}

    total_c = None
    if total_pattern:
        try:
            total_c = re.compile(total_pattern)
        except re.error as e:
            raise ValueError(f"无效正则 (total_pattern): {total_pattern!r} — {e}") from e

    if total_c and closing_line.strip():
        cc = compact_for_match(closing_line)
        if total_c.fullmatch(cc):
            meta["total_note"] = closing_line.strip()

    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = _strip_tabs(raw).replace("\f", "").replace("\r", "").strip()
        compact = compact_for_match(raw)

        if discard_compiled and compact and _fullmatch_any(compact, discard_compiled):
            sec = _section_from_compact(compact)
            if sec is not None:
                section = sec
            _log_discard(log_prefix, raw, discard_sink=discard_sink)
            i += 1
            continue

        if total_c and compact and total_c.fullmatch(compact):
            meta["total_note"] = stripped
            _log_discard(log_prefix, raw, discard_sink=discard_sink)
            i += 1
            continue

        noise = _noise_category(stripped)
        if noise is not None:
            if noise != "空行":
                _log_discard(log_prefix, raw, discard_sink=discard_sink)
            i += 1
            continue

        parsed = _parse_word_lesson_line(raw)
        if parsed is not None:
            lesson, words, hanzi_line = parsed
            rows.append(
                {
                    "section": section,
                    "lesson": lesson,
                    "words": list(words),
                    "lines": [hanzi_line],
                    "toc_anchor": True,
                }
            )
            i += 1
            continue

        cont = _continuation_words(raw)
        if cont is not None and rows:
            rows[-1]["words"].extend(cont)
            rows[-1]["lines"].append(raw.rstrip())
            i += 1
            continue

        _log_discard(log_prefix, raw, discard_sink=discard_sink)
        i += 1

    meta["word_count_computed"] = sum(len(r["words"]) for r in rows)
    return rows, meta


def extract_word_table(
    full_text: str,
    options: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    discard_sink = meta.pop("discard_sink", None)
    log_prefix = str(
        meta.get("log_prefix") or f'{meta.get("book_code", "?")}/{meta.get("extractor", "?")}'
    )

    body, closing = slice_region(full_text, options)

    discard_raw = options.get("discard_line_patterns")
    discard_list = (
        [discard_raw] if isinstance(discard_raw, str) else list(discard_raw or [])
    )
    discard_compiled = _compile_fullmatch(discard_list, "discard_line_patterns")

    total_pattern = options.get("total_pattern")
    tp: str | None = total_pattern if isinstance(total_pattern, str) else None

    rows, tmeta = parse_word_table_body(
        body,
        total_pattern=tp,
        closing_line=closing,
        discard_compiled=discard_compiled,
        log_prefix=log_prefix,
        discard_sink=discard_sink,
    )

    layout_entries = options.get("TOC_layout_entries")
    toc_raw = options.get("TOC_of_unit")
    toc_list = [toc_raw] if isinstance(toc_raw, str) else list(toc_raw or [])
    toc_alignment: dict[str, Any] | None = None
    toc_warnings: list[str] = []
    if isinstance(layout_entries, list) and layout_entries:
        from ..toc_layout_assign import (
            assign_units_from_layout_toc,
            toc_alignment_report_layout,
            toc_catalog_summary,
        )

        rows, toc_warnings = assign_units_from_layout_toc(
            rows, layout_entries, log_prefix=log_prefix, word_table=True
        )
        toc_alignment = toc_alignment_report_layout(rows, log_prefix)
        _strip_internal_keys(rows)
    elif toc_list:
        rows, toc_warnings = assign_toc_units(rows, toc_list, log_prefix)
        toc_alignment = _toc_alignment_report(rows, toc_list, log_prefix)
        _strip_internal_keys(rows)
    else:
        for r in rows:
            r.pop("toc_anchor", None)

    word_count = tmeta["word_count_computed"]
    all_words = [w for r in rows for w in r["words"]]
    out: dict[str, Any] = {
        **meta,
        "rows": rows,
        "all_words": all_words,
        "total_note": tmeta.get("total_note"),
        "word_count_computed": word_count,
    }
    if isinstance(layout_entries, list) and layout_entries:
        out["units_from_toc"] = toc_catalog_summary(layout_entries)
        jp = options.get("TOC_layout_json_path")
        if isinstance(jp, str) and jp.strip():
            out["toc_layout_source"] = jp.strip()
    elif toc_list:
        out["units_from_toc"] = [parse_toc_entry(x, i) for i, x in enumerate(toc_list)]
    if toc_alignment is not None:
        out["toc_alignment"] = toc_alignment
    if toc_warnings:
        out["toc_warnings"] = toc_warnings

    expected = options.get("expected_word_count")
    if isinstance(expected, int) and expected != word_count:
        out["word_count_warning"] = (
            f"合计词语数 {word_count} 与 expected_word_count={expected} 不一致"
        )

    note = out.get("total_note")
    if isinstance(note, str):
        m = re.search(r"(\d+)\s*个词", note.replace(" ", ""))
        if m:
            stated = int(m.group(1))
            if stated != word_count:
                print(
                    f"[{log_prefix}] 提示: 文末标称 {stated} 个词，解析合计 {word_count} 个",
                    file=sys.stderr,
                    flush=True,
                )
                out["total_word_count_stated"] = stated
                out["word_count_matches_stated"] = False
            else:
                out["word_count_matches_stated"] = True

    return out
