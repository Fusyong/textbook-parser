from __future__ import annotations

import re
import sys
from collections.abc import Callable
from typing import Any

_CJK_RE = re.compile(r"[\u4e00-\u9fff·]")
# 版式拼音：ASCII 字母 + 教材/转写中常见的 ü（如 lüè）；不含汉字
_PINYIN_TOKEN_RE = re.compile(r"^[a-zA-ZüÜ]+$")
_GARDEN_RE = re.compile(r"^\s*语文园地([一二三四五六七八九十]+)\s*(.*)$")
# 三年级起版式常见「语文园地」后无「一、二…」，直接接生字（可与标题粘连、可空格分隔或连成一串）
_GARDEN_PLAIN_RE = re.compile(r"^\s*语文园地\s*(.+)$")
_LESSON_RE = re.compile(r"^\s*(\d+)\s+(.+)$")
_TOC_GARDEN_FULL = re.compile(r"^语文园地[一二三四五六七八九十]+$")
# 三年级起常见：标题「语文园地」独占一行，生字在下一行；上一行可能是该块的拼音（版式错位）
_STANDALONE_PLAIN_GARDEN_TITLE = "语文园地"


def _strip_tabs(s: str) -> str:
    """匹配与解析前去掉制表符（版式里常用 \\t 对齐，不应影响 unit 边界）。"""
    return s.replace("\t", "")


def compact_for_match(line: str) -> str:
    """匹配用：先删 \\t，再去掉其余空白（空格、换页等）。"""
    s = _strip_tabs(line)
    return re.sub(r"\s+", "", s)


def _normalize_spaces(s: str) -> str:
    """各类空白（含 NBSP、全角空格、制表符等）规范为单一半角空格。"""
    return re.sub(r"[\s\u00a0\u2000-\u200b\u202f\u205f\u3000\ufeff]+", " ", s).strip()


# 版式文本中 QWERTY 大写字母表示韵母及声调（与教材 PDF 一致）
_LAYOUT_TONE_MAP: dict[str, str] = {
    "Q": "ā",
    "W": "á",
    "A": "ǎ",
    "S": "à",
    "T": "ō",
    "Y": "ó",
    "G": "ǒ",
    "H": "ò",
    "E": "ē",
    "R": "é",
    "D": "ě",
    "F": "è",
    "U": "ī",
    "I": "í",
    "J": "ǐ",
    "K": "ì",
    "O": "ū",
    "P": "ú",
    "L": "ǔ",
    "M": "ù",
    "N": "ǖ",
    "B": "ǘ",
    "V": "ǚ",
    "C": "ǜ",
}


def layout_pinyin_to_tone_marked(token: str) -> str:
    """将单个拼音词从版式编码转为带调形式；无表内大写字母则仅小写化。"""
    if not token:
        return ""
    parts: list[str] = []
    for c in token:
        if c in _LAYOUT_TONE_MAP:
            parts.append(_LAYOUT_TONE_MAP[c])
        elif c.isupper():
            parts.append(c.lower())
        else:
            parts.append(c)
    return "".join(parts)


# 成对引号（开、闭）：ASCII 直引号、弯引号、日式引号；用于判断拉丁字母连写是否处于引号内
_LAYOUT_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("'", "'"),
    ("\u201c", "\u201d"),
    ("\u2018", "\u2019"),
    ("\u300c", "\u300d"),
    ("\u300e", "\u300f"),
)


def _layout_quoted_interior_spans(line: str) -> list[tuple[int, int]]:
    """
    返回若干半开区间 [qs, qe)，为成对引号之间的内容（不含引号字符本身）。
    自左向右贪心配对；与嵌套或英文缩写内撇号可能不完全一致。
    """
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(line)
    while i < n:
        matched = False
        for open_ch, close_ch in _LAYOUT_QUOTE_PAIRS:
            if line[i] == open_ch:
                j = line.find(close_ch, i + 1)
                if j != -1:
                    spans.append((i + 1, j))
                    i = j + 1
                    matched = True
                    break
        if not matched:
            i += 1
    return spans


def _letter_run_inside_pair_quotes(line: str, start: int, end: int) -> bool:
    """半开区间 [start, end) 是否完全落在某一成对引号的内容区内。"""
    for qs, qe in _layout_quoted_interior_spans(line):
        if qs <= start and end <= qe:
            return True
    return False


def _should_apply_layout_tone_map_token(
    token: str,
    *,
    line: str,
    match_start: int,
    match_end: int,
) -> bool:
    """
    是否对该拉丁连写做 _LAYOUT_TONE_MAP 转写。
    仅一种情况不转写：一个或多个字母的整段匹配完全落在成对引号（单/双及常见弯引号、直角引号）内。
    """
    if not token:
        return False
    if _letter_run_inside_pair_quotes(line, match_start, match_end):
        return False
    return True


def transcribe_layout_line_pinyin(line: str) -> str:
    """
    行内连续 [a-zA-ZüÜ]+：默认按 layout_pinyin_to_tone_marked（_LAYOUT_TONE_MAP）转写；
    完全处于成对引号内的字母连写保持原样。
    """

    def repl(m: re.Match[str]) -> str:
        token = m.group(0)
        s, e = m.span()
        if not _should_apply_layout_tone_map_token(
            token, line=line, match_start=s, match_end=e
        ):
            return token
        return layout_pinyin_to_tone_marked(token)

    return re.sub(r"[a-zA-ZüÜ]+", repl, line)


def _chars_with_pinyin(
    char_list: list[str],
    pinyin_block: str,
    *,
    log_prefix: str,
) -> list[dict[str, Any]]:
    """
    将汉字列表与拼音行按位置一一对齐。
    pinyin_line（整行）保持版式原文；每项 pinyin 为带调形式。
    """
    tokens = [t for t in pinyin_block.split() if t]
    n_c, n_p = len(char_list), len(tokens)
    if n_c != n_p and pinyin_block.strip():
        print(
            f"[{log_prefix}] 提示: 汉字与拼音不能一一对应 — 汉字 {n_c} 个, 拼音分词 {n_p} 个",
            file=sys.stderr,
            flush=True,
        )

    out: list[dict[str, Any]] = []
    for i, ch in enumerate(char_list):
        py_raw: str | None = tokens[i] if i < len(tokens) else None
        py_marked = layout_pinyin_to_tone_marked(py_raw) if py_raw else ""
        out.append(
            {
                "char": ch,
                "pinyin": py_marked if py_raw else None,
                "polyphone": False,
            }
        )
    return out


def _compile_fullmatch(patterns: list[str] | None, label: str) -> list[re.Pattern[str]]:
    if not patterns:
        return []
    out: list[re.Pattern[str]] = []
    for p in patterns:
        try:
            out.append(re.compile(p))
        except re.error as e:
            raise ValueError(f"无效正则 ({label}): {p!r} — {e}") from e
    return out


def _fullmatch_any(compact: str, compiled: list[re.Pattern[str]]) -> bool:
    return any(p.fullmatch(compact) for p in compiled)


def _log_discard(
    prefix: str,
    raw_line: str,
    *,
    discard_sink: Callable[[str], None] | None = None,
) -> None:
    """抛弃行：写入 discard_sink 时仅为原文一行（无类型说明）；stderr 保留带前缀提示。"""
    text = raw_line.rstrip("\r\n")
    if discard_sink and text.strip():
        discard_sink(text)
    print(f"[{prefix} 抛弃] {raw_line}", file=sys.stderr, flush=True)


def _is_pinyin_line(line: str) -> bool:
    s = _normalize_spaces(_strip_tabs(line))
    if not s or _CJK_RE.search(s):
        return False
    if not re.search(r"[a-zA-ZüÜ]", s):
        return False
    for w in s.split():
        if not w:
            continue
        if not _PINYIN_TOKEN_RE.match(w):
            return False
    return True


def _noise_category(stripped: str) -> str | None:
    if not stripped:
        return "空行"
    if "仅供个人" in stripped:
        return "版权声明"
    if stripped.startswith("①") and "识字表" in stripped:
        return "脚注①"
    if re.fullmatch(r"\d{1,3}", stripped):
        return "页码"
    if stripped == "①":
        return "单独圆圈①"
    if set(stripped) <= {" ", "\t", ""}:
        return "仅空白"
    return None


def _chars_from_garden_tail(tail: str) -> list[str]:
    """课号行 / 园地标题后的生字区：按空白分词，每词内逐字拆开（「负责 讶恼」→ 负责讶恼 各一字）。"""
    tail = tail.strip()
    if not tail:
        return []
    chars: list[str] = []
    for part in tail.split():
        for ch in part:
            if _CJK_RE.match(ch):
                chars.append(ch)
    return chars


def _parse_hanzi_line(line: str) -> dict[str, Any] | None:
    raw = line.rstrip()
    s = _normalize_spaces(raw)
    if not s or not _CJK_RE.search(s):
        return None
    if s in ("识字", "阅读", "写字"):
        return None

    m = _GARDEN_RE.match(s)
    if m:
        garden, tail = m.group(1), m.group(2).strip()
        chars = _chars_from_garden_tail(tail)
        return {"lesson": None, "garden": garden, "chars": chars, "raw": raw}

    m = _GARDEN_PLAIN_RE.match(s)
    if m:
        tail = m.group(1).strip()
        chars = _chars_from_garden_tail(tail)
        return {"lesson": None, "garden": "", "chars": chars, "raw": raw}

    m = _LESSON_RE.match(s)
    if m:
        lesson, tail = m.group(1), m.group(2).strip()
        chars = _chars_from_garden_tail(tail)
        return {"lesson": lesson, "garden": None, "chars": chars, "raw": raw}

    if s == _STANDALONE_PLAIN_GARDEN_TITLE:
        return {"lesson": None, "garden": "", "chars": [], "raw": raw}

    chars = _chars_from_garden_tail(s)
    if chars:
        return {"lesson": None, "garden": None, "chars": chars, "raw": raw}
    return None


def parse_toc_entry(raw: Any, index: int) -> dict[str, Any]:
    """将配置里的一条 TOC 解析为结构化课文元数据。"""
    s = str(raw).strip()
    c = compact_for_match(s)
    if _TOC_GARDEN_FULL.match(c):
        gn = c.removeprefix("语文园地")
        return {
            "toc_index": index,
            "unit_type": "garden",
            "garden_cn": gn,
            "lesson": None,
            "title": None,
            "label": s,
        }
    m = re.match(r"^(\d{1,2})\s+(.+)$", s)
    if m:
        title = m.group(2).strip()
        return {
            "toc_index": index,
            "unit_type": "lesson",
            "lesson": m.group(1),
            "garden_cn": None,
            "title": title,
            "label": f"{m.group(1)} {title}",
        }
    return {
        "toc_index": index,
        "unit_type": "unknown",
        "lesson": None,
        "garden_cn": None,
        "title": s,
        "label": s,
    }


def assign_toc_units(
    rows: list[dict[str, Any]],
    toc_raw: list[Any] | None,
    log_prefix: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    `toc_anchor` 为真（汉字行以 unit_head_pattern 开头）时消费 TOC 一条；否则沿用上一单元的 TOC。
    若无 `toc_anchor` 字段则回退为「lesson 或 garden 非空」判定（兼容旧数据）。
    """
    warnings: list[str] = []
    if not toc_raw:
        return rows, warnings

    entries = [parse_toc_entry(x, i) for i, x in enumerate(toc_raw)]
    ti = 0
    prev_unit: dict[str, Any] | None = None
    out: list[dict[str, Any]] = []

    for row in rows:
        if "toc_anchor" in row:
            is_primary = bool(row["toc_anchor"])
        else:
            is_primary = row.get("lesson") is not None or row.get("garden") is not None
        if is_primary:
            if ti >= len(entries):
                msg = f"TOC 条目已用尽，仍出现 toc_anchor 主行 hanzi_line={row.get('hanzi_line', '')!r}"
                warnings.append(msg)
                print(f"[{log_prefix} TOC] {msg}", file=sys.stderr)
                unit = None
            else:
                unit = entries[ti]
                ti += 1
            prev_unit = unit
        else:
            unit = prev_unit
            if unit is None:
                msg = "续行（无课号/园地）但尚无上一单元，无法对应 TOC"
                warnings.append(msg)
                print(f"[{log_prefix} TOC] {msg}\n  行: {row.get('hanzi_line', '')!r}", file=sys.stderr)

        out.append({**row, "unit": unit})

    if ti < len(entries):
        msg = f"TOC 尚有 {len(entries) - ti} 条未与主行对应（已消费 {ti}/{len(entries)}）"
        warnings.append(msg)
        print(f"[{log_prefix} TOC] {msg}", file=sys.stderr)
    return out, warnings


def _toc_alignment_report(
    rows: list[dict[str, Any]],
    toc_list: list[Any],
    log_prefix: str,
) -> dict[str, Any] | None:
    """
    一项解析结束时：比较 TOC 条数与 toc_anchor 数据组条数，打印并返回结构化结果。
    """
    if not toc_list:
        return None
    n_toc = len(toc_list)
    n_anchor = sum(1 for r in rows if r.get("toc_anchor"))
    ok = n_toc == n_anchor
    if ok:
        detail = "一一对应: 是"
    elif n_anchor < n_toc:
        detail = f"一一对应: 否（锚点数据组比目录少 {n_toc - n_anchor} 个）"
    else:
        detail = f"一一对应: 否（锚点数据组比目录多 {n_anchor - n_toc} 个）"
    print(
        f"[{log_prefix}] unit 目录核对 — 目录 {n_toc} 条, 锚点数据组 {n_anchor} 条, {detail}",
        flush=True,
    )
    return {
        "toc_catalog_count": n_toc,
        "toc_anchor_group_count": n_anchor,
        "toc_one_to_one_ok": ok,
    }


def _section_from_compact(compact: str) -> str | None:
    if compact == "识字":
        return "识字"
    if compact == "阅读":
        return "阅读"
    if compact == "写字":
        return "写字"
    return None


def slice_region(
    full_text: str,
    inner: dict[str, Any],
) -> tuple[str, str]:
    """
    返回 (正文区文本, 结束标记所在行的原文)。
    正文区不含起始行与结束行。
    """
    lines = full_text.splitlines()
    start_raw = inner.get("start_line_pattern")
    end_raw = inner.get("end_line_pattern")
    legacy_start = inner.get("start_markers")
    legacy_end = inner.get("end_markers")

    if start_raw is not None and end_raw is not None:
        start_list = [start_raw] if isinstance(start_raw, str) else list(start_raw)
        end_list = [end_raw] if isinstance(end_raw, str) else list(end_raw)
        start_c = _compile_fullmatch(start_list, "start_line_pattern")
        end_c = _compile_fullmatch(end_list, "end_line_pattern")
        start_idx: int | None = None
        end_idx: int | None = None
        for i, line in enumerate(lines):
            c = compact_for_match(line)
            if start_idx is None and _fullmatch_any(c, start_c):
                start_idx = i
                continue
            if start_idx is not None and _fullmatch_any(c, end_c):
                end_idx = i
                break
        if start_idx is None:
            raise ValueError(f"未找到起始行（整行匹配）: {start_list}")
        if end_idx is None:
            raise ValueError(f"未找到结束行（整行匹配）: {end_list}")
        body = "\n".join(lines[start_idx + 1 : end_idx])
        closing = lines[end_idx]
        return body, closing

    if legacy_start and legacy_end:
        sm = [legacy_start] if isinstance(legacy_start, str) else list(legacy_start)
        em = [legacy_end] if isinstance(legacy_end, str) else list(legacy_end)
        start_idx = None
        end_idx = None
        for i, line in enumerate(lines):
            if start_idx is None and any(m in line for m in sm):
                start_idx = i
                continue
            if start_idx is not None and any(m in line for m in em):
                end_idx = i
                break
        if start_idx is None:
            raise ValueError(f"未找到起始标记: {sm}")
        if end_idx is None:
            raise ValueError(f"未找到结束标记: {em}")
        body = "\n".join(lines[start_idx + 1 : end_idx])
        closing = lines[end_idx]
        return body, closing

    raise ValueError(
        "需要 start_line_pattern + end_line_pattern，或旧版 start_markers + end_markers"
    )


def _append_char_table_row(
    rows: list[dict[str, Any]],
    *,
    section: str | None,
    hanzi_raw: str,
    parsed: dict[str, Any],
    pinyin_block: str,
    unit_head_compiled: re.Pattern[str] | None,
    log_prefix: str,
) -> None:
    """将一条生字行（可有或可无拼音块）并入 rows：续行合并或新起一行。"""
    compact_hanzi = compact_for_match(hanzi_raw)
    toc_anchor = _toc_anchor_row(compact_hanzi, unit_head_compiled)
    # 版式常见：先独占一行「语文园地」，下一行又是「语文园地 + 生字」；第二行也会命中 unit_head，需并回上一条空标题行以免多计 TOC 锚点
    if (
        rows
        and parsed["chars"]
        and not rows[-1]["chars"]
        and compact_hanzi.startswith("语文园地")
        and len(compact_hanzi) > len("语文园地")
    ):
        prev = rows[-1]
        last_seg = prev.get("hanzi_line", "").split("\n")[-1]
        if _normalize_spaces(_strip_tabs(last_seg)) == _STANDALONE_PLAIN_GARDEN_TITLE:
            prev["chars"].extend(
                _chars_with_pinyin(
                    parsed["chars"], pinyin_block, log_prefix=log_prefix
                )
            )
            if pinyin_block.strip():
                prev["pinyin_line"] = (
                    prev["pinyin_line"] + " " + pinyin_block
                ).strip()
            prev["hanzi_line"] = prev["hanzi_line"] + "\n" + parsed["raw"]
            return
    if not toc_anchor and rows:
        prev = rows[-1]
        prev["chars"].extend(
            _chars_with_pinyin(parsed["chars"], pinyin_block, log_prefix=log_prefix)
        )
        if pinyin_block.strip():
            prev["pinyin_line"] = (prev["pinyin_line"] + " " + pinyin_block).strip()
        prev["hanzi_line"] = prev["hanzi_line"] + "\n" + parsed["raw"]
        return
    if not toc_anchor and not rows:
        toc_anchor = True
    rows.append(
        {
            "section": section,
            "lesson": parsed["lesson"],
            "garden": parsed["garden"],
            "chars": _chars_with_pinyin(
                parsed["chars"], pinyin_block, log_prefix=log_prefix
            ),
            "pinyin_line": pinyin_block,
            "hanzi_line": parsed["raw"],
            "toc_anchor": toc_anchor,
        }
    )


def parse_char_table_body(
    body: str,
    *,
    total_pattern: str | None,
    closing_line: str,
    discard_compiled: list[re.Pattern[str]],
    unit_head_originals: list[str] | None,
    unit_head_compiled: re.Pattern[str] | None,
    log_prefix: str,
    discard_sink: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lines = body.splitlines()
    section: str | None = None
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {"total_note": None, "char_count_computed": 0}

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
    pending_pinyin = ""
    while i < len(lines):
        raw = _strip_tabs(lines[i])
        stripped = raw.strip()
        compact = compact_for_match(raw)

        # discard_line_patterns 优先于 total_pattern，命中则原样打印并抛弃
        if discard_compiled and _fullmatch_any(compact, discard_compiled):
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

        if _is_pinyin_line(raw):
            pinyin_parts: list[str] = []
            while i < len(lines) and _is_pinyin_line(_strip_tabs(lines[i])):
                pinyin_parts.append(_normalize_spaces(_strip_tabs(lines[i])))
                i += 1

            pinyin_block = " ".join(p for p in pinyin_parts if p)

            if i >= len(lines):
                if pinyin_block and rows:
                    prev = rows[-1]
                    prev["pinyin_line"] = (prev["pinyin_line"] + " " + pinyin_block).strip()
                break

            hanzi_raw = _strip_tabs(lines[i])
            parsed = _parse_hanzi_line(hanzi_raw)
            if parsed is None:
                if pinyin_block and rows:
                    rows[-1]["pinyin_line"] = (
                        rows[-1]["pinyin_line"] + " " + pinyin_block
                    ).strip()
                _log_discard(log_prefix, hanzi_raw, discard_sink=discard_sink)
                i += 1
                continue

            hanzi_norm = _normalize_spaces(_strip_tabs(hanzi_raw))
            if hanzi_norm == _STANDALONE_PLAIN_GARDEN_TITLE and not parsed["chars"]:
                toc_a = _toc_anchor_row(
                    compact_for_match(hanzi_raw), unit_head_compiled
                )
                if not toc_a and not rows:
                    toc_a = True
                rows.append(
                    {
                        "section": section,
                        "lesson": parsed["lesson"],
                        "garden": parsed["garden"],
                        "chars": [],
                        "pinyin_line": "",
                        "hanzi_line": hanzi_raw,
                        "toc_anchor": toc_a,
                    }
                )
                if pinyin_block.strip():
                    pending_pinyin = (
                        f"{pending_pinyin} {pinyin_block}".strip()
                        if pending_pinyin
                        else pinyin_block.strip()
                    )
                i += 1
                continue

            merged_pinyin = pinyin_block
            if pending_pinyin:
                merged_pinyin = (
                    f"{pending_pinyin} {pinyin_block}".strip()
                    if pinyin_block.strip()
                    else pending_pinyin
                )
                pending_pinyin = ""

            _append_char_table_row(
                rows,
                section=section,
                hanzi_raw=hanzi_raw,
                parsed=parsed,
                pinyin_block=merged_pinyin,
                unit_head_compiled=unit_head_compiled,
                log_prefix=log_prefix,
            )
            i += 1
            continue

        parsed_only = _parse_hanzi_line(raw)
        if parsed_only is not None:
            py_only = pending_pinyin
            if pending_pinyin:
                pending_pinyin = ""
            _append_char_table_row(
                rows,
                section=section,
                hanzi_raw=raw,
                parsed=parsed_only,
                pinyin_block=py_only,
                unit_head_compiled=unit_head_compiled,
                log_prefix=log_prefix,
            )
            i += 1
            continue

        _log_discard(log_prefix, raw, discard_sink=discard_sink)
        i += 1

    meta["char_count_computed"] = sum(len(r["chars"]) for r in rows)
    return rows, meta


def _toc_anchor_row(
    compact_hanzi: str,
    unit_head_compiled: re.Pattern[str] | None,
) -> bool:
    """是否视为新表块起点（消费一条 TOC）；无 unit_head 配置时默认每行都是起点。"""
    if unit_head_compiled is None:
        return True
    return bool(unit_head_compiled.match(compact_hanzi))


def _carry_forward_lesson_garden(rows: list[dict[str, Any]]) -> None:
    """续行 lesson、garden 与上一数据行一致（便于下游按课/园地筛选）。"""
    for i in range(1, len(rows)):
        row = rows[i]
        if row.get("lesson") is not None or row.get("garden") is not None:
            continue
        prev = rows[i - 1]
        row["lesson"] = prev.get("lesson")
        row["garden"] = prev.get("garden")


def _strip_internal_keys(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row.pop("toc_anchor", None)


def _build_unit_head_pattern(originals: list[str] | None) -> tuple[re.Pattern[str] | None, list[str] | None]:
    if not originals:
        return None, None
    parts = [f"(?:{p})" for p in originals]
    combined = "^(" + "|".join(parts) + ")"
    try:
        return re.compile(combined), originals
    except re.error as e:
        raise ValueError(f"无效正则 (unit_head_pattern): {originals!r} — {e}") from e


def extract_char_table(
    full_text: str,
    options: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    discard_sink = meta.pop("discard_sink", None)
    log_prefix = str(meta.get("log_prefix") or f'{meta.get("book_code", "?")}/{meta.get("extractor", "?")}')

    body, closing = slice_region(full_text, options)

    discard_raw = options.get("discard_line_patterns")
    discard_list = (
        [discard_raw] if isinstance(discard_raw, str) else list(discard_raw or [])
    )
    discard_compiled = _compile_fullmatch(discard_list, "discard_line_patterns")

    unit_raw = options.get("unit_head_pattern")
    unit_list = [unit_raw] if isinstance(unit_raw, str) else list(unit_raw or [])
    unit_compiled, unit_originals = _build_unit_head_pattern(unit_list if unit_list else None)

    total_pattern = options.get("total_pattern")
    if isinstance(total_pattern, str):
        tp: str | None = total_pattern
    else:
        tp = None

    rows, tmeta = parse_char_table_body(
        body,
        total_pattern=tp,
        closing_line=closing,
        discard_compiled=discard_compiled,
        unit_head_originals=unit_originals,
        unit_head_compiled=unit_compiled,
        log_prefix=log_prefix,
        discard_sink=discard_sink,
    )

    layout_entries = options.get("TOC_layout_entries")
    toc_raw = options.get("TOC_of_unit")
    toc_list = [toc_raw] if isinstance(toc_raw, str) else list(toc_raw or [])
    toc_warnings: list[str] = []
    toc_alignment: dict[str, Any] | None = None

    if isinstance(layout_entries, list) and layout_entries:
        from ..toc_layout_assign import (
            assign_units_from_layout_toc,
            toc_alignment_report_layout,
            toc_catalog_summary,
        )

        rows, toc_warnings = assign_units_from_layout_toc(
            rows, layout_entries, log_prefix=log_prefix, word_table=False
        )
        toc_alignment = toc_alignment_report_layout(rows, log_prefix)
    elif toc_list:
        rows, toc_warnings = assign_toc_units(rows, toc_list, log_prefix)
        toc_alignment = _toc_alignment_report(rows, toc_list, log_prefix)
    else:
        for r in rows:
            r.pop("toc_anchor", None)

    _carry_forward_lesson_garden(rows)
    _strip_internal_keys(rows)

    char_count_computed = tmeta["char_count_computed"]
    out: dict[str, Any] = {
        **meta,
        "rows": rows,
        "total_note": tmeta.get("total_note"),
        "char_count_computed": char_count_computed,
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
    expected = options.get("expected_char_count")
    if isinstance(expected, int) and expected != char_count_computed:
        out["char_count_warning"] = (
            f"合计字数 {char_count_computed} 与 expected_char_count={expected} 不一致"
        )
    return out
