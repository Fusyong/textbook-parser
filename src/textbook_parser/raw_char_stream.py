"""
将 pdftotext -raw（内容流顺序）的识字表/写字表文本，折叠为接近 -layout 的
「拼音行 + 汉字课号/园地行」块，供现有 char_tables 解析器复用。

raw 双栏页常见顺序：先整页左栏自上而下，再右栏——比 -layout 并排更易对齐目录。
每字常独占一行、下一行为拼音；园地/课号标题行可能已带首字。
"""

from __future__ import annotations

import re
from typing import Iterable

from .extractors.char_tables import (
    _CJK_RE,
    _SPACE_LIKE_RE,
    _is_pinyin_line,
    _layout_pinyin_tokens,
    _normalize_spaces,
    compact_for_match,
)

_SECTION_LABELS = frozenset({"识字", "阅读", "汉语拼音"})
_GARDEN_HEAD = re.compile(
    r"^(语文园地[一二三四五六七八九十]*)(?:\s*(.*))?$"
)
_LESSON_HEAD = re.compile(r"^(\d{1,2})\s*(.*)$")
# 单字行（可含少量空白）；排除明显多字课文
_SINGLE_CJK = re.compile(r"^[\s\u2002\u3000]*([\u4e00-\u9fff])[\s\u2002\u3000]*$")


def looks_like_raw_char_stream(text: str) -> bool:
    """启发式：大量「单字行 / 单拼音行」交错 → 视为 raw 字表流。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 20:
        return False
    sample = lines[: min(200, len(lines))]
    single_cjk = 0
    single_py = 0
    for ln in sample:
        if _SINGLE_CJK.match(ln):
            single_cjk += 1
        elif _is_pinyin_line(ln) and len(_layout_pinyin_tokens(ln)) == 1:
            single_py += 1
    return (single_cjk + single_py) >= max(12, len(sample) // 3)


def normalize_raw_char_stream(text: str) -> str:
    """
    将 raw 交错字/拼音折叠为 layout 风格行块；若已不像 raw 则原样返回。
    """
    if not looks_like_raw_char_stream(text):
        return text
    return "\n".join(_emit_normalized_lines(_iter_raw_tokens(text)))


def _iter_raw_tokens(text: str) -> Iterable[str]:
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        # 分页符已随 splitlines 去掉；页码、纯数字脚注跳过
        if re.fullmatch(r"\d{1,3}", s):
            continue
        yield s


def _split_leading_cjk_run(tail: str) -> tuple[list[str], str]:
    """标题行尾部连续汉字拆成单字列表，其余（拼音）留下。"""
    t = _normalize_spaces(tail)
    if not t:
        return [], ""
    chars: list[str] = []
    i = 0
    while i < len(t):
        ch = t[i]
        if _CJK_RE.match(ch):
            chars.append(ch)
            i += 1
            while i < len(t) and t[i] in " \t\u2002\u3000":
                i += 1
            continue
        break
    rest = t[i:].strip()
    return chars, rest


def _emit_normalized_lines(tokens: Iterable[str]) -> list[str]:
    out: list[str] = []
    pending_label: str | None = None  # 「2」或「语文园地二」
    chars: list[str] = []
    pys: list[str] = []
    expect_py = False  # 上一枚举为汉字，下一枚应为拼音

    def flush() -> None:
        nonlocal pending_label, chars, pys, expect_py
        if pending_label is None and not chars:
            expect_py = False
            return
        label = pending_label or ""
        # 拼音行在前、汉字行在后（与现有版式配对习惯一致）
        if pys:
            out.append(" ".join(pys))
        if label or chars:
            han = "".join(chars)
            if label and han:
                # 园地/课号与生字之间留空，便于 _parse_hanzi_line
                if label.startswith("语文园地"):
                    out.append(f"{label} {han}")
                else:
                    out.append(f"{label} {han}")
            elif label:
                out.append(label)
            else:
                out.append(han)
        pending_label = None
        chars = []
        pys = []
        expect_py = False

    for tok in tokens:
        c = compact_for_match(tok)

        # 结束标记：保留给 slice_region
        if re.fullmatch(r"[（(]共\d+个(?:生)?字[）)]", c):
            flush()
            out.append(tok)
            continue

        if c in _SECTION_LABELS:
            flush()
            out.append(c)
            continue

        # 表头（写字表/识字表）原样，供起始匹配
        if c in ("写字表", "识字表") or c.startswith("识字表") and len(c) <= 8:
            flush()
            out.append(tok)
            continue

        gm = _GARDEN_HEAD.match(_normalize_spaces(_SPACE_LIKE_RE.sub(" ", tok)))
        # 宽松：compact 后以语文园地开头
        if gm or c.startswith("语文园地"):
            flush()
            if gm:
                gname, tail = gm.group(1), (gm.group(2) or "").strip()
            else:
                # compact 名 + 从原文取尾
                m2 = re.match(r"^(语文园地[一二三四五六七八九十]*)(.*)$", c)
                gname = m2.group(1) if m2 else c
                tail = (m2.group(2) if m2 else "") or ""
            pending_label = gname
            lead, rest = _split_leading_cjk_run(tail)
            chars.extend(lead)
            if rest and _is_pinyin_line(rest):
                pys.extend(_layout_pinyin_tokens(rest))
                expect_py = False
            else:
                expect_py = bool(lead)
            continue

        lm = _LESSON_HEAD.match(_normalize_spaces(tok))
        if lm and (lm.group(2).strip() == "" or _CJK_RE.search(lm.group(2))):
            # 纯课号或课号+汉字；排除「10 白菜…」中夹拼音的误判由上层 raw 结构保证
            flush()
            pending_label = lm.group(1)
            lead, rest = _split_leading_cjk_run(lm.group(2))
            chars.extend(lead)
            if rest and _is_pinyin_line(rest):
                pys.extend(_layout_pinyin_tokens(rest))
                expect_py = False
            else:
                expect_py = bool(lead)
            continue

        sm = _SINGLE_CJK.match(tok)
        if sm:
            if expect_py:
                # 缺拼音，直接收下一字
                expect_py = False
            chars.append(sm.group(1))
            expect_py = True
            continue

        if _is_pinyin_line(tok):
            toks = _layout_pinyin_tokens(tok)
            if expect_py and len(toks) == 1:
                pys.append(toks[0])
                expect_py = False
            elif not expect_py and chars and len(toks) == len(chars) - len(pys):
                pys.extend(toks)
            else:
                # 独立拼音块：先冲刷再挂 pending 意义不大，并入当前或新开
                if pending_label is None and not chars:
                    out.append(" ".join(toks) if toks else tok)
                else:
                    pys.extend(toks)
                    expect_py = False
            continue

        # 其它（脚注、说明）：冲刷后原样
        flush()
        out.append(tok)

    flush()
    return out
