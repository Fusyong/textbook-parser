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

# 各类空白（半角/全角空格、NBSP、en/em space、零宽等），匹配前一律去掉
_SPACE_LIKE_RE = re.compile(
    r"[\s\u00a0\u2000-\u200b\u202f\u205f\u3000\ufeff]+"
)
# 带圈/带括注释码（如 识字表①）；标志行与其它整行匹配时忽略
_MARKER_ANNOTATION_RE = re.compile(
    "["
    "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳⓪"
    "❶❷❸❹❺❻❼❽❾❿"
    "⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽⑾⑿⒀⒁⒂⒃⒄⒅⒆⒇"
    "⒈⒉⒊⒋⒌⒍⒎⒏⒐⒑⒒⒓⒔⒕⒖⒗⒘⒙⒚⒛"
    "]"
)


def _strip_tabs(s: str) -> str:
    """匹配与解析前去掉制表符（版式里常用 \\t 对齐，不应影响 unit 边界）。"""
    return s.replace("\t", "")


def compact_for_match(line: str) -> str:
    """匹配用：去制表符、各类空白、带圈注释码（如「识 字 表①」→「识字表」）。"""
    s = _strip_tabs(line)
    s = _SPACE_LIKE_RE.sub("", s)
    s = _MARKER_ANNOTATION_RE.sub("", s)
    return s


def _normalize_spaces(s: str) -> str:
    """各类空白（含 NBSP、全角空格、制表符等）规范为单一半角空格。"""
    return _SPACE_LIKE_RE.sub(" ", s).strip()


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


_SECTION_LABELS = frozenset({"识字", "阅读", "写字", "汉语拼音"})


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


def _collapse_spaced_garden_heading(s: str) -> str:
    """版式把标题拉开时：「语　文　园　地　一」→「语文园地一」。"""
    return re.sub(
        r"语\s*文\s*园\s*地\s*([一二三四五六七八九十]+)",
        lambda m: f"语文园地{m.group(1)}",
        s,
    )


def _layout_pinyin_tokens(s: str) -> list[str]:
    return re.findall(r"[a-zA-ZüÜ]+", s)


def _split_wide_gap(line: str) -> tuple[str, str] | None:
    """按行内最宽空白带（≥4）切成左右两栏；左右皆非空才算；无则返回 None。"""
    best: tuple[str, str] | None = None
    best_w = -1
    for m in _SPACE_LIKE_RE.finditer(line):
        w = m.end() - m.start()
        if w < 4:
            continue
        left, right = line[: m.start()].strip(), line[m.end() :].strip()
        # 跳过行首/行尾空白（切完一侧为空）
        if not left or not right:
            continue
        if w > best_w:
            best_w = w
            best = (left, right)
    return best


def _is_lesson_head_line(s: str) -> bool:
    return bool(re.match(r"^\d{1,2}\s+\S", _normalize_spaces(s)))


def _is_section_label_text(s: str) -> bool:
    """单元栏目标题「识字」「阅读」「汉语拼音」等（可出现在双栏一侧）。"""
    return _split_section_label_line(s) is not None


def _split_section_label_line(s: str) -> tuple[str, str] | None:
    """
    栏目标题行：「阅读」或「阅读   wL xiS」（后接纯拼音）。
    返回 (栏目名, 拼音块)；非此类行返回 None。
    """
    norm = _normalize_spaces(s)
    if not norm:
        return None
    for lab in sorted(_SECTION_LABELS, key=len, reverse=True):
        if norm == lab:
            return lab, ""
        if norm.startswith(lab + " "):
            rest = norm[len(lab) :].strip()
            if not rest:
                return lab, ""
            if _CJK_RE.search(rest):
                return None
            toks = _layout_pinyin_tokens(rest)
            if toks and _is_pinyin_line(rest):
                return lab, _normalize_spaces(rest)
            if toks and not re.search(r"[^\s a-zA-ZüÜ]", rest):
                return lab, " ".join(toks)
            return None
    return None


def _is_garden_head_line(s: str) -> bool:
    norm = _collapse_spaced_garden_heading(_normalize_spaces(s))
    if not norm:
        return False
    if norm == _STANDALONE_PLAIN_GARDEN_TITLE:
        return True
    return bool(_GARDEN_RE.match(norm) or _GARDEN_PLAIN_RE.match(norm))


def _is_dual_unit_half(s: str) -> bool:
    """双栏一侧是否为课号行 / 园地标题 / 栏目标题 / 纯拼音。"""
    if _is_section_label_text(s):
        return True
    if _is_pinyin_line(s):
        return True
    if _is_lesson_head_line(s):
        return True
    return _is_garden_head_line(s)


def _split_garden_and_trailing_lesson(line: str) -> tuple[str, str] | None:
    """
    双栏粘连且中间空白不足时：
    「语文园地一  六七八十 8 中五风 立正」→ 园地行 + 课号行。
    """
    s = _collapse_spaced_garden_heading(_normalize_spaces(line))
    m = re.match(
        r"^(语文园地[一二三四五六七八九十]+)\s+(.+)\s+(\d{1,2}\s+\S.*)$",
        s,
    )
    if not m:
        return None
    mid = m.group(2).strip()
    # 中间段须含汉字（生字），避免把「语文园地六 bDn xuR」误切
    if not _CJK_RE.search(mid):
        return None
    left = f"{m.group(1)} {mid}".strip()
    right = m.group(3).strip()
    return left, right


def _split_leading_chars_and_garden(line: str) -> tuple[str, str] | None:
    """
    「女 开 关 先  语文园地八  牛羊爪白」：生字在前、园地标题在后时切开。
    """
    s = _collapse_spaced_garden_heading(_normalize_spaces(line))
    m = re.match(
        r"^(.+?)(语文园地[一二三四五六七八九十]+(?:\s+.*)?)$",
        s,
    )
    if not m:
        return None
    left, right = m.group(1).strip(), m.group(2).strip()
    if not left or not _CJK_RE.search(left):
        return None
    # 左侧不应已是园地/课号标题
    if _is_garden_head_line(left) or _is_lesson_head_line(left):
        return None
    return left, right


def _is_bare_char_half(s: str) -> bool:
    """双栏一侧为无课号/园地标题的纯生字（如「午下」「个去」）。"""
    p = _parse_hanzi_line(s)
    return (
        p is not None
        and bool(p["chars"])
        and p.get("lesson") is None
        and p.get("garden") is None
        and not p.get("embedded_pinyin")
    )


def _is_dual_half(s: str) -> bool:
    return _is_dual_unit_half(s) or _is_bare_char_half(s)


def _dual_hanzi_halves(hanzi_raw: str) -> tuple[str, str] | None:
    """汉字行双栏切分：宽空白，园地+课号粘连，或生字+园地标题粘连。"""
    wide = _split_wide_gap(hanzi_raw)
    # 宽空白左侧误含「生字+园地标题」时优先切开（女开关先|园地八…）
    if wide:
        sub = _split_leading_chars_and_garden(wide[0])
        if sub and _is_dual_half(wide[1]):
            if _is_bare_char_half(wide[1]) and _is_garden_head_line(sub[1]):
                return sub[0], f"{sub[1]} {wide[1]}".strip()
            if _is_garden_head_line(sub[1]) or _is_garden_head_line(wide[1]):
                return sub[0], wide[1] if _is_garden_head_line(wide[1]) else sub[1]
    if wide and _is_dual_half(wide[0]) and _is_dual_half(wide[1]):
        # 「语文园地　　孝喻…」：标题与生字仅被宽空白隔开，应整行解析，勿当左右栏
        left_p = _parse_hanzi_line(wide[0])
        if (
            left_p is not None
            and not left_p["chars"]
            and not left_p.get("embedded_pinyin")
            and (
                left_p.get("garden") is not None
                or left_p.get("lesson") is not None
            )
            and _is_bare_char_half(wide[1])
        ):
            return None
        # 至少一侧是课号/园地/栏目/拼音，避免两段普通正文误切
        if _is_dual_unit_half(wide[0]) or _is_dual_unit_half(wide[1]):
            return wide
    glued = _split_garden_and_trailing_lesson(hanzi_raw)
    if glued:
        return glued
    lead = _split_leading_chars_and_garden(hanzi_raw)
    if lead:
        return lead
    return None


def _parse_hanzi_line(line: str) -> dict[str, Any] | None:
    raw = line.rstrip()
    s = _collapse_spaced_garden_heading(_normalize_spaces(raw))
    if not s or not _CJK_RE.search(s):
        return None
    if _split_section_label_line(raw) is not None or s in _SECTION_LABELS:
        return None

    m = _GARDEN_RE.match(s)
    if m:
        garden, tail = m.group(1), m.group(2).strip()
        chars = _chars_from_garden_tail(tail)
        embedded = ""
        if not chars:
            toks = _layout_pinyin_tokens(tail)
            if toks:
                embedded = " ".join(toks)
        return {
            "lesson": None,
            "garden": garden,
            "chars": chars,
            "raw": raw,
            "embedded_pinyin": embedded or None,
        }

    m = _GARDEN_PLAIN_RE.match(s)
    if m:
        tail = m.group(1).strip()
        chars = _chars_from_garden_tail(tail)
        embedded = ""
        if not chars:
            toks = _layout_pinyin_tokens(tail)
            if toks:
                embedded = " ".join(toks)
        return {
            "lesson": None,
            "garden": "",
            "chars": chars,
            "raw": raw,
            "embedded_pinyin": embedded or None,
        }

    m = _LESSON_RE.match(s)
    if m:
        lesson, tail = m.group(1), m.group(2).strip()
        # 双栏残留：「3 爸妈 4 大马路土」归一化后仍可能粘在同一课号下，由上层按宽空白切开
        chars = _chars_from_garden_tail(tail)
        return {
            "lesson": lesson,
            "garden": None,
            "chars": chars,
            "raw": raw,
            "embedded_pinyin": None,
        }

    if s == _STANDALONE_PLAIN_GARDEN_TITLE:
        return {
            "lesson": None,
            "garden": "",
            "chars": [],
            "raw": raw,
            "embedded_pinyin": None,
        }

    chars = _chars_from_garden_tail(s)
    if chars:
        return {
            "lesson": None,
            "garden": None,
            "chars": chars,
            "raw": raw,
            "embedded_pinyin": None,
        }
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
    from ..toc_layout_assign import reorder_rows_by_toc_order

    return reorder_rows_by_toc_order(out), warnings


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
    if compact in _SECTION_LABELS:
        return compact
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

    # 版式错位：空园地行已带拼音，生字落在后续行（甚至误挂到下一园地标题下）
    if parsed["chars"] and _try_fill_empty_garden(
        rows,
        parsed["chars"],
        pinyin_block,
        hanzi_extra=parsed.get("raw") or hanzi_raw,
        log_prefix=log_prefix,
    ):
        # 当前行若本身是新的园地/课号标题，仍留下空标题行占位
        if parsed.get("garden") is not None or parsed.get("lesson") is not None:
            empty = {
                "lesson": parsed["lesson"],
                "garden": parsed["garden"],
                "chars": [],
                "raw": parsed.get("raw") or hanzi_raw,
                "embedded_pinyin": None,
            }
            # 仅标题、无生字时才追加，避免空课号行
            if parsed.get("garden") is not None and not (
                parsed.get("lesson") is not None
            ):
                rows.append(
                    {
                        "section": section,
                        "lesson": None,
                        "garden": parsed["garden"],
                        "chars": [],
                        "pinyin_line": "",
                        "hanzi_line": empty["raw"],
                        "toc_anchor": True,
                    }
                )
        return

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
        # 纯生字续行：优先填先前空园地，避免并进上一课/园地造成粘连
        if parsed["chars"] and _try_fill_empty_garden(
            rows,
            parsed["chars"],
            pinyin_block,
            hanzi_extra=parsed.get("raw") or hanzi_raw,
            log_prefix=log_prefix,
        ):
            return
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


def _try_fill_empty_garden(
    rows: list[dict[str, Any]],
    chars: list[str],
    pinyin_block: str,
    *,
    hanzi_extra: str,
    log_prefix: str,
) -> bool:
    """
    将生字填入最早的「空园地」行。
    仅当该园地行上已有拼音且分词数与字数一致时回填（避免右栏课文/拼音误填左栏）。
    pinyin_block 若与已有拼音一致可忽略；若园地尚无拼音则不填。
    """
    if not chars:
        return False
    for row in rows:
        if row.get("garden") is None:
            continue
        if row.get("chars"):
            continue
        existing_py = (row.get("pinyin_line") or "").strip()
        if not existing_py:
            continue
        tokens = [t for t in existing_py.split() if t]
        if len(tokens) != len(chars):
            continue
        # 若本次也带拼音，分词数须一致（或为空）
        bring = (pinyin_block or "").strip()
        if bring:
            bring_toks = [t for t in bring.split() if t]
            if len(bring_toks) != len(chars):
                continue
        row["chars"] = _chars_with_pinyin(chars, existing_py, log_prefix=log_prefix)
        extra = (hanzi_extra or "").strip()
        if extra:
            row["hanzi_line"] = (row.get("hanzi_line") or "") + (
                "\n" if row.get("hanzi_line") else ""
            ) + extra
        return True
    return False


def _attach_pinyin_to_empty_garden(rows: list[dict[str, Any]], pinyin_block: str) -> bool:
    """把待配拼音挂到最早仍无拼音的空园地行。"""
    py = (pinyin_block or "").strip()
    if not py:
        return False
    for row in rows:
        if row.get("garden") is None:
            continue
        if row.get("chars"):
            continue
        if (row.get("pinyin_line") or "").strip():
            continue
        row["pinyin_line"] = py
        return True
    return False


def _try_fill_empty_garden_items(
    items: list[dict[str, Any]],
    chars: list[str],
    pinyin_block: str,
    *,
    hanzi_extra: str,
    log_prefix: str,
) -> bool:
    """在双栏缓冲条目中回填空园地（规则同 _try_fill_empty_garden）。"""
    if not chars:
        return False
    for item in items:
        parsed = item.get("parsed") or {}
        if parsed.get("garden") is None:
            continue
        if parsed.get("chars"):
            continue
        existing_py = (item.get("pinyin_block") or "").strip()
        if not existing_py:
            continue
        tokens = [t for t in existing_py.split() if t]
        if len(tokens) != len(chars):
            continue
        bring = (pinyin_block or "").strip()
        if bring:
            bring_toks = [t for t in bring.split() if t]
            if len(bring_toks) != len(chars):
                continue
        parsed["chars"] = list(chars)
        item["pinyin_block"] = existing_py
        extra = (hanzi_extra or "").strip()
        if extra:
            prev = item.get("hanzi_raw") or ""
            item["hanzi_raw"] = prev + ("\n" if prev else "") + extra
        return True
    return False


def _attach_pinyin_to_empty_garden_items(
    items: list[dict[str, Any]], pinyin_block: str
) -> bool:
    py = (pinyin_block or "").strip()
    if not py:
        return False
    for item in items:
        parsed = item.get("parsed") or {}
        if parsed.get("garden") is None:
            continue
        if parsed.get("chars"):
            continue
        if (item.get("pinyin_block") or "").strip():
            continue
        item["pinyin_block"] = py
        return True
    return False


def _is_pinyin_only_half(s: str) -> bool:
    """双栏一侧仅为版式拼音（无汉字）。"""
    return _is_pinyin_line(s)


def _dual_item(
    *,
    section: str | None,
    hanzi_raw: str,
    parsed: dict[str, Any],
    pinyin_block: str,
) -> dict[str, Any]:
    return {
        "section": section,
        "hanzi_raw": hanzi_raw,
        "parsed": parsed,
        "pinyin_block": pinyin_block,
    }


def _flush_dual_columns(
    rows: list[dict[str, Any]],
    dual_lefts: list[dict[str, Any]],
    dual_rights: list[dict[str, Any]],
    *,
    unit_head_compiled: re.Pattern[str] | None,
    log_prefix: str,
) -> None:
    """双栏版式按列输出：先左栏自上而下，再右栏（与目录课序一致）。"""
    for item in dual_lefts + dual_rights:
        _append_char_table_row(
            rows,
            section=item["section"],
            hanzi_raw=item["hanzi_raw"],
            parsed=item["parsed"],
            pinyin_block=item["pinyin_block"],
            unit_head_compiled=unit_head_compiled,
            log_prefix=log_prefix,
        )
    dual_lefts.clear()
    dual_rights.clear()


def _min_lesson_num(items: list[dict[str, Any]]) -> int | None:
    """右栏已缓冲课号的最小值；忽略园地等无课号条目。"""
    nums: list[int] = []
    for it in items:
        les = it["parsed"].get("lesson")
        if les is None:
            continue
        try:
            nums.append(int(les))
        except (TypeError, ValueError):
            continue
    return min(nums) if nums else None


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
    section_left: str | None = None
    section_right: str | None = None
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
    pending_right_pinyin = ""
    # 双栏缓冲：同行左右课号先入队，整页按列冲刷（先左后右，与目录课序一致）
    dual_lefts: list[dict[str, Any]] = []
    dual_rights: list[dict[str, Any]] = []

    def flush_dual() -> None:
        _flush_dual_columns(
            rows,
            dual_lefts,
            dual_rights,
            unit_head_compiled=unit_head_compiled,
            log_prefix=log_prefix,
        )

    def col_section(*, as_right: bool) -> str | None:
        return section_right if as_right else section_left

    def set_col_section(lab: str, *, as_right: bool | None = None) -> None:
        nonlocal section, section_left, section_right
        if as_right is True:
            section_right = lab
        elif as_right is False:
            section_left = lab
        else:
            section_left = lab
            section_right = lab
        section = lab

    def emit_row(
        *,
        hanzi_raw: str,
        parsed: dict[str, Any],
        pinyin_block: str,
        row_section: str | None = None,
    ) -> None:
        """非双栏行：先冲刷双栏缓冲，再写入。"""
        flush_dual()
        _append_char_table_row(
            rows,
            section=section if row_section is None else row_section,
            hanzi_raw=hanzi_raw,
            parsed=parsed,
            pinyin_block=pinyin_block,
            unit_head_compiled=unit_head_compiled,
            log_prefix=log_prefix,
        )

    def attach_pinyin_any(block: str) -> bool:
        """空园地拼音：先已写出的 rows，再双栏缓冲。"""
        if _attach_pinyin_to_empty_garden(rows, block):
            return True
        if _attach_pinyin_to_empty_garden_items(dual_lefts, block):
            return True
        return _attach_pinyin_to_empty_garden_items(dual_rights, block)

    def try_fill_any(chars: list[str], pinyin_block: str, hanzi_extra: str) -> bool:
        if _try_fill_empty_garden(
            rows,
            chars,
            pinyin_block,
            hanzi_extra=hanzi_extra,
            log_prefix=log_prefix,
        ):
            return True
        if _try_fill_empty_garden_items(
            dual_lefts,
            chars,
            pinyin_block,
            hanzi_extra=hanzi_extra,
            log_prefix=log_prefix,
        ):
            return True
        return _try_fill_empty_garden_items(
            dual_rights,
            chars,
            pinyin_block,
            hanzi_extra=hanzi_extra,
            log_prefix=log_prefix,
        )

    def apply_section_half(hz: str, *, as_right: bool) -> str:
        """处理栏目标题侧；若带拼音则挂到空园地或返回之。"""
        sp = _split_section_label_line(hz)
        if sp is None:
            return ""
        set_col_section(sp[0], as_right=as_right)
        extra = sp[1]
        if extra and attach_pinyin_any(extra):
            return ""
        return extra

    def buffer_dual_half(
        hz: str,
        py: str,
        *,
        as_right: bool,
        parsed_h: dict[str, Any] | None = None,
    ) -> None:
        """写入双栏一侧：纯拼音进 pending；生字优先回填空园地，否则入缓冲。"""
        nonlocal pending_pinyin, pending_right_pinyin
        if _is_pinyin_line(hz):
            block = _normalize_spaces(hz)
            if as_right:
                pending_right_pinyin = (
                    f"{pending_right_pinyin} {block}".strip()
                    if pending_right_pinyin
                    else block
                )
            else:
                if not attach_pinyin_any(block):
                    pending_pinyin = (
                        f"{pending_pinyin} {block}".strip() if pending_pinyin else block
                    )
            return
        parsed = parsed_h if parsed_h is not None else _parse_hanzi_line(hz)
        if parsed is None:
            return
        emb = parsed.get("embedded_pinyin") or ""
        py_h = py
        if as_right:
            if pending_right_pinyin and parsed["chars"]:
                py_h = (
                    f"{pending_right_pinyin} {py_h}".strip()
                    if py_h
                    else pending_right_pinyin
                )
                pending_right_pinyin = ""
        else:
            if pending_pinyin and parsed["chars"]:
                py_h = f"{pending_pinyin} {py_h}".strip() if py_h else pending_pinyin
                pending_pinyin = ""
        if emb and not parsed["chars"]:
            # 调用方常已把 embedded_pinyin 传入 py；相同则勿再拼，否则拼音翻倍
            if not py_h:
                py_h = emb
            elif _normalize_spaces(py_h) != _normalize_spaces(emb):
                py_h = f"{py_h} {emb}".strip()
        if parsed["chars"] and try_fill_any(
            parsed["chars"], py_h, parsed.get("raw") or hz
        ):
            # 标题行本身是新园地时仍占位
            if parsed.get("garden") is not None and parsed.get("lesson") is None:
                target = dual_rights if as_right else dual_lefts
                target.append(
                    _dual_item(
                        section=col_section(as_right=as_right),
                        hanzi_raw=hz,
                        parsed={
                            "lesson": None,
                            "garden": parsed["garden"],
                            "chars": [],
                            "raw": parsed.get("raw") or hz,
                            "embedded_pinyin": None,
                        },
                        pinyin_block="",
                    )
                )
            return
        target = dual_rights if as_right else dual_lefts
        target.append(
            _dual_item(
                section=col_section(as_right=as_right),
                hanzi_raw=hz,
                parsed=parsed,
                pinyin_block=py_h,
            )
        )

    def emit_content_half(hz: str, py: str, *, as_right: bool) -> None:
        """双栏一侧：已在双栏区则缓冲；否则单列写出。"""
        if dual_lefts or dual_rights or as_right:
            buffer_dual_half(hz, py, as_right=as_right)
            return
        # 尚未入双栏且为左栏：直接写 rows（兼容单列）
        nonlocal pending_pinyin, pending_right_pinyin
        if _is_pinyin_line(hz):
            block = _normalize_spaces(hz)
            if not attach_pinyin_any(block):
                pending_pinyin = (
                    f"{pending_pinyin} {block}".strip() if pending_pinyin else block
                )
            return
        parsed_h = _parse_hanzi_line(hz)
        if parsed_h is None:
            return
        emb = parsed_h.get("embedded_pinyin") or ""
        py_h = py
        if pending_pinyin and parsed_h["chars"]:
            py_h = f"{pending_pinyin} {py_h}".strip() if py_h else pending_pinyin
            pending_pinyin = ""
        if emb and not parsed_h["chars"]:
            # 与 buffer_dual_half 同：勿把已传入的行内拼音再拼一次
            if not py_h:
                py_h = emb
            elif _normalize_spaces(py_h) != _normalize_spaces(emb):
                py_h = f"{py_h} {emb}".strip()
        emit_row(
            hanzi_raw=hz,
            parsed=parsed_h,
            pinyin_block=py_h,
            row_section=col_section(as_right=False),
        )

    while i < len(lines):
        raw = _strip_tabs(lines[i])
        stripped = raw.strip()
        compact = compact_for_match(raw)

        # discard_line_patterns 优先于 total_pattern，命中则原样打印并抛弃
        if discard_compiled and _fullmatch_any(compact, discard_compiled):
            sec = _section_from_compact(compact)
            if sec is not None:
                set_col_section(sec)
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
            # 保留行内宽空白，供双栏切分；归一化块仅用于单行配对
            pinyin_raw_parts: list[str] = []
            while i < len(lines) and _is_pinyin_line(_strip_tabs(lines[i])):
                pinyin_raw_parts.append(_strip_tabs(lines[i]).rstrip())
                i += 1

            pinyin_block = " ".join(
                _normalize_spaces(p) for p in pinyin_raw_parts if p.strip()
            )

            # 拼音与汉字之间常有空行（新版式）；跳过后再取汉字行
            while i < len(lines) and _noise_category(
                _strip_tabs(lines[i]).strip()
            ) == "空行":
                i += 1

            if i >= len(lines):
                if pinyin_block.strip():
                    pending_pinyin = (
                        f"{pending_pinyin} {pinyin_block}".strip()
                        if pending_pinyin
                        else pinyin_block.strip()
                    )
                break

            hanzi_raw = _strip_tabs(lines[i])

            # 双栏：一行拼音 + 一行汉字（课号/园地/栏目标题）
            py_halves = (
                _split_wide_gap(pinyin_raw_parts[0])
                if len(pinyin_raw_parts) == 1
                else None
            )
            hz_halves = _dual_hanzi_halves(hanzi_raw)
            # 拼音已双栏而汉字粘连时，再尝试园地+课号切开
            if py_halves and hz_halves is None:
                hz_halves = _split_garden_and_trailing_lesson(hanzi_raw)
            if (
                py_halves
                and hz_halves
                and _is_dual_half(hz_halves[0])
                and _is_dual_half(hz_halves[1])
            ):
                left_py = _normalize_spaces(py_halves[0])
                right_py = _normalize_spaces(py_halves[1])
                left_hz, right_hz = hz_halves
                left_is_sec = _split_section_label_line(left_hz) is not None
                right_is_sec = _split_section_label_line(right_hz) is not None
                left_is_py = _is_pinyin_line(left_hz)
                right_is_py = _is_pinyin_line(right_hz)

                if left_is_sec and right_is_sec:
                    # 双栏两侧皆栏目：只更新左右 section，不冲刷（整页按列输出）
                    apply_section_half(left_hz, as_right=False)
                    apply_section_half(right_hz, as_right=True)
                    _log_discard(log_prefix, hanzi_raw, discard_sink=discard_sink)
                    i += 1
                    continue

                # 任一侧为栏目或纯拼音：更新栏目 / 分列缓冲，勿提前冲刷
                if left_is_sec or right_is_sec or left_is_py or right_is_py:
                    if left_is_sec:
                        extra = apply_section_half(left_hz, as_right=False)
                        if extra:
                            pending_pinyin = (
                                f"{pending_pinyin} {extra}".strip()
                                if pending_pinyin
                                else extra
                            )
                    else:
                        py_l = left_py
                        if pending_pinyin and not left_is_py:
                            py_l = (
                                f"{pending_pinyin} {py_l}".strip()
                                if py_l
                                else pending_pinyin
                            )
                            pending_pinyin = ""
                        buffer_dual_half(left_hz, py_l, as_right=False)
                    if right_is_sec:
                        apply_section_half(right_hz, as_right=True)
                    else:
                        py_r = right_py
                        if pending_right_pinyin and not right_is_py:
                            py_r = (
                                f"{pending_right_pinyin} {py_r}".strip()
                                if py_r
                                else pending_right_pinyin
                            )
                            pending_right_pinyin = ""
                        buffer_dual_half(right_hz, py_r, as_right=True)
                    i += 1
                    continue

                left_parsed = _parse_hanzi_line(left_hz)
                right_parsed = _parse_hanzi_line(right_hz)
                if left_parsed is not None and right_parsed is not None:
                    if pending_pinyin:
                        left_py = (
                            f"{pending_pinyin} {left_py}".strip()
                            if left_py
                            else pending_pinyin
                        )
                        pending_pinyin = ""
                    if pending_right_pinyin:
                        right_py = (
                            f"{pending_right_pinyin} {right_py}".strip()
                            if right_py
                            else pending_right_pinyin
                        )
                        pending_right_pinyin = ""
                    buffer_dual_half(
                        left_hz, left_py, as_right=False, parsed_h=left_parsed
                    )
                    buffer_dual_half(
                        right_hz, right_py, as_right=True, parsed_h=right_parsed
                    )
                    i += 1
                    continue
                # 解析失败则退回逐行处理

            parsed = _parse_hanzi_line(hanzi_raw)
            if parsed is None:
                # 无法配对汉字：留给后续汉字行（pending），勿误挂到上一行
                if pinyin_block.strip():
                    pending_pinyin = (
                        f"{pending_pinyin} {pinyin_block}".strip()
                        if pending_pinyin
                        else pinyin_block.strip()
                    )
                _log_discard(log_prefix, hanzi_raw, discard_sink=discard_sink)
                i += 1
                continue

            hanzi_norm = _normalize_spaces(_strip_tabs(hanzi_raw))
            hanzi_norm = _collapse_spaced_garden_heading(hanzi_norm)
            if hanzi_norm == _STANDALONE_PLAIN_GARDEN_TITLE and not parsed["chars"]:
                flush_dual()
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
                    # 空「语文园地」标题不吞拼音 pending
                    pass
                i += 1
                continue

            emb = parsed.get("embedded_pinyin") or ""
            if parsed["chars"]:
                merged_pinyin = pinyin_block
                if pending_pinyin:
                    merged_pinyin = (
                        f"{pending_pinyin} {pinyin_block}".strip()
                        if pinyin_block.strip()
                        else pending_pinyin
                    )
                    pending_pinyin = ""
            else:
                # 空标题不消耗 pending；内嵌拼音写在本行供回填
                merged_pinyin = emb

            # 双栏左栏续行：课号落在右栏最小课号之前
            if (
                dual_rights
                and parsed.get("lesson") is not None
                and parsed.get("garden") is None
            ):
                try:
                    les_n = int(parsed["lesson"])
                except (TypeError, ValueError):
                    les_n = None
                right_min = _min_lesson_num(dual_rights)
                if les_n is not None and right_min is not None and les_n < right_min:
                    buffer_dual_half(
                        hanzi_raw, merged_pinyin, as_right=False, parsed_h=parsed
                    )
                    i += 1
                    continue

            # 双栏进行中的左栏纯生字/园地续行
            if dual_lefts or dual_rights:
                buffer_dual_half(
                    hanzi_raw, merged_pinyin, as_right=False, parsed_h=parsed
                )
                i += 1
                continue

            emit_row(
                hanzi_raw=hanzi_raw,
                parsed=parsed,
                pinyin_block=merged_pinyin,
                row_section=col_section(as_right=False),
            )
            i += 1
            continue

        # 无先行拼音的双栏（含一侧纯拼音）
        hz_only_halves = _dual_hanzi_halves(raw)
        if (
            hz_only_halves
            and _is_dual_half(hz_only_halves[0])
            and _is_dual_half(hz_only_halves[1])
        ):
            left_hz, right_hz = hz_only_halves
            left_is_sec = _split_section_label_line(left_hz) is not None
            right_is_sec = _split_section_label_line(right_hz) is not None
            left_is_py = _is_pinyin_line(left_hz)
            right_is_py = _is_pinyin_line(right_hz)

            if left_is_sec and right_is_sec:
                apply_section_half(left_hz, as_right=False)
                apply_section_half(right_hz, as_right=True)
                _log_discard(log_prefix, raw, discard_sink=discard_sink)
                i += 1
                continue

            if left_is_sec or right_is_sec or left_is_py or right_is_py:
                if left_is_sec:
                    extra = apply_section_half(left_hz, as_right=False)
                    if extra:
                        pending_pinyin = (
                            f"{pending_pinyin} {extra}".strip()
                            if pending_pinyin
                            else extra
                        )
                else:
                    buffer_dual_half(left_hz, "", as_right=False)
                if right_is_sec:
                    apply_section_half(right_hz, as_right=True)
                else:
                    buffer_dual_half(right_hz, "", as_right=True)
                i += 1
                continue

            # 两侧皆课号/园地正文：按列缓冲
            left_parsed = _parse_hanzi_line(left_hz)
            right_parsed = _parse_hanzi_line(right_hz)
            if left_parsed is not None and right_parsed is not None:
                py_l = ""
                if left_parsed["chars"] and pending_pinyin:
                    py_l = pending_pinyin
                    pending_pinyin = ""
                elif not left_parsed["chars"]:
                    emb_l = left_parsed.get("embedded_pinyin") or ""
                    py_l = emb_l
                py_r = ""
                if right_parsed["chars"] and pending_right_pinyin:
                    py_r = pending_right_pinyin
                    pending_right_pinyin = ""
                elif not right_parsed["chars"]:
                    emb_r = right_parsed.get("embedded_pinyin") or ""
                    py_r = emb_r
                buffer_dual_half(left_hz, py_l, as_right=False, parsed_h=left_parsed)
                buffer_dual_half(right_hz, py_r, as_right=True, parsed_h=right_parsed)
                i += 1
                continue

        # 单行栏目标题（可带拼音）
        sec_line = _split_section_label_line(raw)
        if sec_line is not None:
            # 双栏进行中的左栏「阅读」等：不冲刷，只改左栏 section
            if dual_lefts or dual_rights:
                set_col_section(sec_line[0], as_right=False)
                if sec_line[1]:
                    if not attach_pinyin_any(sec_line[1]):
                        pending_pinyin = (
                            f"{pending_pinyin} {sec_line[1]}".strip()
                            if pending_pinyin
                            else sec_line[1]
                        )
            else:
                flush_dual()
                set_col_section(sec_line[0])
                if sec_line[1]:
                    pending_pinyin = (
                        f"{pending_pinyin} {sec_line[1]}".strip()
                        if pending_pinyin
                        else sec_line[1]
                    )
            _log_discard(log_prefix, raw, discard_sink=discard_sink)
            i += 1
            continue

        parsed_only = _parse_hanzi_line(raw)
        if parsed_only is not None:
            emb = parsed_only.get("embedded_pinyin") or ""
            if parsed_only["chars"]:
                if pending_pinyin:
                    py_only = pending_pinyin
                    pending_pinyin = ""
                elif pending_right_pinyin:
                    # 右栏课号独占一行（仅有左缩进）时，用右栏待配拼音
                    py_only = pending_right_pinyin
                    pending_right_pinyin = ""
                else:
                    py_only = ""
            else:
                # 空园地/空标题：拼音写在行上；不消耗 pending
                py_only = emb

            if dual_lefts or dual_rights:
                as_right = False
                if (
                    parsed_only.get("lesson") is not None
                    and parsed_only.get("garden") is None
                    and parsed_only["chars"]
                ):
                    try:
                        les_n = int(parsed_only["lesson"])
                    except (TypeError, ValueError):
                        les_n = None
                    right_min = _min_lesson_num(dual_rights)
                    # 课号 ≥ 右栏最小课号：视为右栏续行
                    if (
                        les_n is not None
                        and right_min is not None
                        and les_n >= right_min
                    ):
                        as_right = True
                buffer_dual_half(raw, py_only, as_right=as_right, parsed_h=parsed_only)
                i += 1
                continue

            emit_row(
                hanzi_raw=raw,
                parsed=parsed_only,
                pinyin_block=py_only,
                row_section=col_section(as_right=False),
            )
            i += 1
            continue

        flush_dual()
        _log_discard(log_prefix, raw, discard_sink=discard_sink)
        i += 1

    flush_dual()
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
