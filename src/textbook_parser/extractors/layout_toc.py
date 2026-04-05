from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .char_tables import _strip_tabs, compact_for_match

# 目录行「版心/空白」宽度计量（半角单位）：1 全角汉字 = 2；1 个 \t = 2 个汉字宽。
_TOC_HAN_WIDTH_EMU = 2
_TOC_TAB_WIDTH_EMU_DEFAULT = 2 * _TOC_HAN_WIDTH_EMU
# PDF/转写常见零宽：isspace() 为 False，会打断「连续空白」扫描，须跳过且宽度计 0
_TOC_LEADING_IGNORE_NO_WIDTH_ORDS: frozenset[int] = frozenset(
    {
        0x200B,
        0x200C,
        0x200D,
        0xFEFF,
        0x2060,
        0x2061,
        0x2062,
        0x2063,
    }
)

_SECTION_RE = re.compile(
    r"^第[一二三四五六七八九十百千万]+单元·(阅读|识字|汉语拼音)$"
)
# 双栏同一行 compact 后「单元·…」后还会接右栏文字，仅用前缀判断「新单元起头」
_SECTION_PREFIX_RE = re.compile(
    r"^第[一二三四五六七八九十百千万]+单元·(?:阅读|识字|汉语拼音)"
)
# 一年级「入学教育」等：整行标题即分组头（非「第×单元」形式）
_SECTION_EXTRA_RE = re.compile(r"^我上学了$")
# 六年级下册等：目录右栏「古诗词诵读」块（非单元），其后篇目独立成组
_SECTION_ANCIENT_POETRY_RECITATION_RE = re.compile(r"^(?:古诗词诵读|古诗诵读)$")
_SECTION_ANCIENT_POETRY_LABEL = "古诗词诵读"
# 三年级等：「第一单元」后可有「…………页码」也可无（compact 后点线仍保留）
_SECTION_UNIT_COMPACT_RE = re.compile(
    r"^第[一二三四五六七八九十百千万]+单元(?:\.+\d+)?$"
)
_SECTION_UNIT_LABEL_ONLY_RE = re.compile(r"^第[一二三四五六七八九十百千万]+单元$")
# 课次后可有 * / ＊（略读课文）；组 1 为数字，组 2 为星号（可空），组 3 标题，组 4 页码
_LESSON_RE = re.compile(
    r"^(\d{1,2})([\*＊]?)\s+(.+?)\s*\.{2,}\s*(\d+)\s*$"
)
# 一年级等：标题与页码之间为多空格，无点线 …
_LESSON_SPACE_RE = re.compile(
    r"^(\d{1,2})([\*＊]?)\s+(.+?)\s{2,}(\d{1,4})\s*$"
)
# 课次 + 标题，无点线页码（须排在带点线/空格页码的课文规则之后）
_LESSON_NO_PAGE_RE = re.compile(r"^(\d{1,2})([\*＊]?)\s+(.+)$")
# 「语文园地」后可跟「一、二…」也可无（三年级等仅「语文园地…………页码」）
_GARDEN_RE = re.compile(
    r"^[◎○]?\s*(语文园地(?:[一二三四五六七八九十]+)?)(?:\s*\.{2,}\s*(\d+))?\s*$"
)
_GARDEN_SPACE_RE = re.compile(
    r"^[◎○]?\s*(语文园地(?:[一二三四五六七八九十]+)?)(?:\s{2,}(\d{1,4}))?\s*$"
)
# 高年级目录常见「◎ 口语交际：标题 …」「◎ 习作：…」；◎/○ 与冒号均可选，与旧版「口语交际 标题」并存
_TOC_BELT_PREFIX = r"(?:[◎○]\s*)?"
_TOC_BLOCK_AFTER_HEAD = r"\s*[:：]?\s*"
# 栏块类型：「习作例文」须排在「习作」前，避免 re 前缀误把「习作例文」当成「习作」
_TOC_BLOCK_KIND_GROUP = r"(口语交际|习作例文|习作)"
# 独占一格：口语交际 / 习作例文 / 习作 块标记（「阅读」为版式栏头，默认即课文·阅读，不抽成条目）
_TOC_BELT_COMPACT_RE = re.compile(
    rf"^{_TOC_BELT_PREFIX}(口语交际|习作例文|习作|综合性学习)[:：]?$"
)
# 同格：口语交际/习作例文/习作 + 标题 + 点线或空格 + 页码（独立学习单位，非课文子目）
# 栏头与标题间允许零宽空白（部分 PDF 紧贴）；点线可为半角 . 或全角 ．
_BLOCK_ACTIVITY_DOT_RE = re.compile(
    rf"^{_TOC_BELT_PREFIX}{_TOC_BLOCK_KIND_GROUP}{_TOC_BLOCK_AFTER_HEAD}(.+?)\s*(?:(?:\.|．)\s*){{2,}}\s*(\d+)\s*$"
)
_BLOCK_ACTIVITY_SPACE_RE = re.compile(
    rf"^{_TOC_BELT_PREFIX}{_TOC_BLOCK_KIND_GROUP}{_TOC_BLOCK_AFTER_HEAD}(.+?)\s{{1,}}(\d{{1,4}})\s*$"
)
# 三年级下册等：专题学习活动 + 标题 + 点线/空格 + 页码（同 block_activity）
_SPECIAL_TOPIC_DOT_RE = re.compile(
    r"^(?:[◎○]\s*)?专题学习活动\s*[:：]?\s*(.+?)\s*(?:(?:\.|．)\s*){2,}\s*(\d+)\s*$"
)
_SPECIAL_TOPIC_SPACE_RE = re.compile(
    r"^(?:[◎○]\s*)?专题学习活动\s*[:：]?\s*(.+?)\s{1,}(\d{1,4})\s*$"
)
# 四年级下册等：综合性学习 + 副标题 + 点线/空格 + 页码（同 block_activity）
_COMPREHENSIVE_STUDY_DOT_RE = re.compile(
    r"^(?:[◎○]\s*)?综合性学习\s*[:：]?\s*(.+?)\s*(?:(?:\.|．)\s*){2,}\s*(\d+)\s*$"
)
_COMPREHENSIVE_STUDY_SPACE_RE = re.compile(
    r"^(?:[◎○]\s*)?综合性学习\s*[:：]?\s*(.+?)\s{1,}(\d{1,4})\s*$"
)
# compact 串是否以栏块头起首（含可选 ◎ 与专题），供孤儿行排除等
_COMPACT_BLOCK_OR_TOPIC_HEAD_RE = re.compile(
    r"^(?:[◎○])?(?:口语交际|习作例文|习作|综合性学习|专题学习活动)"
)
# 高年级常见「◎ 快乐读书吧：」独占一行，副标题在下一行缩进（与口语交际/习作冒号体例一致）
_READING_BAR_RE = re.compile(r"^[◎○]?\s*快乐读书吧\s*[:：]?\s*$")
_READING_BAR_SPACE_RE = re.compile(
    r"^[◎○]?\s*快乐读书吧\s*[:：]?\s*(.+?)\s{2,}(\d{1,4})\s*$"
)
# 高年级双栏目录常见：副标题与页码之间为点线（与 _READING_BAR_SPACE_RE 互斥）
_READING_BAR_DOTS_RE = re.compile(
    r"^[◎○]?\s*快乐读书吧\s*[:：]?\s*(.+?)\s*\.{2,}\s*(\d+)\s*$"
)
_SUB_INDENT_RE = re.compile(r"^\s{4,}(.+?)\s*\.{2,}\s*(\d+)\s*$")
_SUB_INDENT_SPACE_RE = re.compile(r"^\s{4,}(.+?)\s{2,}(\d{1,4})\s*$")
_ORPHAN_TITLE_PAGE_RE = re.compile(r"^(.+?)\s*\.{2,}\s*(\d+)\s*$")
_ORPHAN_TITLE_SPACE_PAGE_RE = re.compile(r"^(.+?)\s{2,}(\d{1,4})\s*$")
# 目录末尾附录行（与识字表/写字表同类），勿当作课文子目挂入最后一单元
_SKIP_CELL_PREFIXES = (
    "识字表",
    "写字表",
    "词语表",
    "笔画名称表",
    "常用偏旁名称表",
)

# 点线目录 + 空格页码目录（用于一行多块的切分扫描）
_LESSON_CHUNK_RE = re.compile(
    r"(?<!\d)(?:\d{1,2}[\*＊]?\s+.+?\.{2,}\s*\d+)|(?<!\d)(?:\d{1,2}[\*＊]?\s+.+?\s{2,}\d+)"
)

_NARROW_LESSON_GAP_RE = re.compile(r"^[\s\u00a0]{1,12}$")


def _narrow_two_lesson_cells(line: str) -> tuple[str, str] | None:
    t = line.strip()
    lessons = list(_LESSON_CHUNK_RE.finditer(t))
    if len(lessons) != 2:
        return None
    m0, m1 = lessons[0], lessons[1]
    mid = t[m0.end() : m1.start()]
    if not _NARROW_LESSON_GAP_RE.match(mid):
        return None
    return (m0.group(0).strip(), m1.group(0).strip())


def _narrow_lesson_and_garden_cells(line: str) -> tuple[str, str] | None:
    t = line.strip()
    ms = list(_LESSON_CHUNK_RE.finditer(t))
    if len(ms) != 1:
        return None
    m0 = ms[0]
    trail = t[m0.end() :].strip()
    if trail and (_GARDEN_RE.match(trail) or _GARDEN_SPACE_RE.match(trail)):
        return (m0.group(0).strip(), trail)
    return None


_RIGHT_ONLY_LESSON_RE = re.compile(
    r"^\s{12,}((?<!\d)\d{1,2}[\*＊]?\s+.+)$"
)


def _right_only_lesson_cell(raw_line: str) -> str | None:
    s = raw_line.rstrip()
    m = _RIGHT_ONLY_LESSON_RE.match(s)
    if not m:
        return None
    return m.group(1).strip()


def _left_only_single_lesson_row(line: str) -> bool:
    t = line.strip()
    ms = list(_LESSON_CHUNK_RE.finditer(t))
    if len(ms) != 1:
        return False
    m0 = ms[0]
    return not t[m0.end() :].strip()


def _column_number(options: dict[str, Any]) -> int | None:
    n = options.get("column_number")
    if n is None:
        return None
    return int(n)


def _leading_blank_prefix_scan(line: str, options: dict[str, Any]) -> tuple[int, int]:
    """
    扫描行首「版式缩进」前缀，供左栏是否为空判定与剥除行首空白。

    含：str.isspace() 为 True 的字符（宽度按 _char_display_width_emu）；
    以及 _TOC_LEADING_IGNORE_NO_WIDTH_ORDS（零宽，不计宽）。
    返回 (前缀结束下标, 前缀总宽度 emu)。
    """
    tw = _tab_width_emu(options)
    i = 0
    total = 0
    lim = len(line)
    while i < lim:
        c = line[i]
        o = ord(c)
        if c.isspace():
            total += _char_display_width_emu(c, tab_width_emu=tw)
            i += 1
            continue
        if o in _TOC_LEADING_IGNORE_NO_WIDTH_ORDS:
            i += 1
            continue
        break
    return i, total


def _char_display_width_emu(ch: str, *, tab_width_emu: int) -> int:
    """
    宽度计量（半角单位）：1 全角汉字 = 2；半角空格/拉丁/数字/半角标点 = 1；\t 宽度由 tab_width_emu 给定（默认同 2 汉字）。
    与版心宽度 toc_content_width_han（全角当量）配合：整行容量 = width_han * 2（emu）。
    """
    if ch == "\t":
        return max(1, tab_width_emu)
    o = ord(ch)
    if o == 0x3000:
        return _TOC_HAN_WIDTH_EMU
    # east_asian_width 常为 N，版式上约一格汉字宽
    if o in (0x2003, 0x2001):
        return _TOC_HAN_WIDTH_EMU
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ("F", "W"):
        return _TOC_HAN_WIDTH_EMU
    return 1


def _tab_width_emu(options: dict[str, Any]) -> int:
    """行首 \\t 折合的半角单位；未配置时 = 2 个全角汉字宽。"""
    t = options.get("toc_tab_width_emu")
    if t is not None:
        return max(1, int(t))
    return _TOC_TAB_WIDTH_EMU_DEFAULT


def _leading_blank_width_emu(line: str, options: dict[str, Any]) -> int:
    """行首版式缩进前缀的宽度，半角单位（见 _leading_blank_prefix_scan）。"""
    _, w = _leading_blank_prefix_scan(line, options)
    return w


def _line_display_width_emu(s: str, options: dict[str, Any]) -> int:
    """整行可视宽度（半角 emu），与行首宽度计量一致。"""
    tw = _tab_width_emu(options)
    return sum(_char_display_width_emu(c, tab_width_emu=tw) for c in s)


def _line_qualifies_as_narrow_left_only(raw: str, options: dict[str, Any], *, line_cap: int) -> bool:
    """
    整行可视宽度不超过单列版心，且行内不存在「双栏缝」级连续空白（几何）→ 判为整行仅占左栏。
    若虽短但含行内大空白，仍走后续按空白切双栏。
    """
    if _line_display_width_emu(raw, options) > line_cap:
        return False
    min_sp = _min_space_run_for_split(options)
    sp_re = re.compile(rf"[\s\u00a0]{{{min_sp},}}")
    for mm in sp_re.finditer(raw):
        if mm.start() > 0:
            return False
    return True


def _leading_indent_requests_right_only_column(raw: str, options: dict[str, Any]) -> bool:
    """
    行首连续空白达到版心比例时，判为「左栏无正文、本行正文仅占右栏」（纯几何，不读具体汉字栏头）。

    - 严：lead×3 > 版心全宽（与 _dual_column_left_is_blank 一致）；
    - 宽：lead×3 ≥ ⌊版心全宽×2/3⌋，覆盖略低于严阈值但仍明显右缩进的版式行。
    """
    w = options.get("toc_content_width_han")
    if w is None or int(w) <= 0:
        return False
    line_cap = int(w) * _TOC_HAN_WIDTH_EMU
    lead = _leading_blank_width_emu(raw, options)
    if lead * 3 > line_cap:
        return True
    if lead * 3 >= (line_cap * 2) // 3:
        return True
    return False


def _dual_column_left_is_blank(raw: str, options: dict[str, Any]) -> bool:
    """
    双栏分列：行首连续空白宽度（半角单位 emu）**严格大于**版心全宽的 1/3 时，视为左栏无正文、整段归右栏。

    - 版心全宽（emu）= toc_content_width_han × 2（1 全角汉字 = 2 emu；半角空格/拉丁等 = 1 emu；\\t 默认 = 4 emu = 2 汉字）。
    - 阈值 = 版心全宽 / 3；判定等价于 lead_emu × 3 > 版心全宽（整数、无浮点）。
    未配置 toc_content_width_han（或 ≤0）时不做此项判定（返回 False）。
    """
    w = options.get("toc_content_width_han")
    if w is None or int(w) <= 0:
        return False
    line_cap_emu = int(w) * _TOC_HAN_WIDTH_EMU
    lead = _leading_blank_width_emu(raw, options)
    return lead * 3 > line_cap_emu


def _min_dot_run_for_split(options: dict[str, Any]) -> int:
    d = options.get("toc_min_dot_run_for_split")
    if d is not None:
        return max(3, int(d))
    return 3


def _min_space_run_for_split(options: dict[str, Any]) -> int:
    s = options.get("toc_min_space_run_for_split")
    if s is not None:
        return max(1, int(s))
    return 5


def _split_line_two_columns_rule(line: str, options: dict[str, Any]) -> tuple[str, str]:
    """
    固定 2 栏分列（column_number==2）。**一律先做版式几何判定，再切双栏**，不依据口语交际/习作等特定文字。

    顺序（与纸质「先判单栏占位，再判双栏缝」一致）：

    1. 空行 → (\"\", \"\")。
    2. **仅右栏**：行首连续空白宽度达到版心阈值（见 `_leading_indent_requests_right_only_column`）→ 左空、剥除行首空白后的正文归右栏。
    3. **仅左栏**：整行宽度 ≤ 单列版心且行内无双栏缝级空白（见 `_line_qualifies_as_narrow_left_only`）→ 整行归左栏。
    4. **点线 + 页码**：首段点列及页码之后切开（双栏行间常见）。
    5. **最长连续空白**（长度 ≥ min_space_run，且不在行首）切开。
    6. 默认整行归左栏（保留行首缩进供子目等规则）。
    """
    raw = line.rstrip()
    if not raw.strip():
        return ("", "")

    wopt = options.get("toc_content_width_han")
    line_cap = int(wopt) * _TOC_HAN_WIDTH_EMU if wopt is not None and int(wopt) > 0 else 0

    if line_cap > 0 and _leading_indent_requests_right_only_column(raw, options):
        end, _ = _leading_blank_prefix_scan(raw, options)
        return ("", raw[end:].strip())

    if line_cap > 0 and _line_qualifies_as_narrow_left_only(raw, options, line_cap=line_cap):
        return (raw.rstrip(), "")

    nd = _min_dot_run_for_split(options)
    dot_page = re.compile(rf"(?:\.\s*){{{nd},}}\s*\d+")
    dpm = list(dot_page.finditer(raw))
    use_b = False
    m0 = None
    if len(dpm) >= 2:
        use_b = True
        m0 = dpm[0]
    elif len(dpm) == 1:
        m0 = dpm[0]
        if raw[m0.end() :].strip():
            use_b = True
    if use_b and m0 is not None:
        end = m0.end()
        while end < len(raw) and raw[end] in " \t\u00a0":
            end += 1
        left = raw[:end].strip()
        right = raw[end:].strip()
        return (left, right)

    min_sp = _min_space_run_for_split(options)
    sp_re = re.compile(rf"[\s\u00a0]{{{min_sp},}}")
    best_len = 0
    best_start = -1
    for mm in sp_re.finditer(raw):
        if mm.start() == 0:
            continue
        ln = mm.end() - mm.start()
        if ln > best_len:
            best_len = ln
            best_start = mm.start()
    if best_start >= 0:
        left = raw[:best_start].rstrip()
        right = raw[best_start + best_len :].strip()
        return (left, right)

    return (raw.rstrip(), "")


# 未设 column_number 时，旧版按「连续空格 ≥ n」分列；默认值写在代码里，不必在 YAML 配置
_DEFAULT_LEGACY_MIN_COLUMN_GAP = 10


def _min_gap(options: dict[str, Any]) -> int:
    g = options.get("min_column_gap")
    if g is None:
        return _DEFAULT_LEGACY_MIN_COLUMN_GAP
    return max(4, int(g))


def _split_single_or_double_columns_legacy(line: str, min_gap: int) -> list[str]:
    s = line.rstrip()
    if not s.strip():
        return []
    parts = re.split(rf" {{{min_gap},}}", s)
    chunks = [p.strip() for p in parts if p.strip()]
    if len(chunks) <= 2:
        return chunks
    return [chunks[0], chunks[1]]


def _clean_title(title: str) -> str:
    return re.sub(r"\s*\.+\s*$", "", title).strip().rstrip(".").strip()


def _should_skip_cell(cell: str) -> bool:
    c = compact_for_match(cell)
    if c == "阅读":
        return True
    return any(c.startswith(p) for p in _SKIP_CELL_PREFIXES)


# 行内零宽字符（PDF/转写常见）：\s 不匹配 U+200B 等，会打断「语文园地……63」等紧贴规则
_TOC_ZERO_WIDTH_STRIP_RE = re.compile(
    r"[\u200b\u200c\u200d\u2060\ufeff\u200e\u200f]"
)


def _strip_toc_zero_width_joiners(s: str) -> str:
    return _TOC_ZERO_WIDTH_STRIP_RE.sub("", s)


def _parse_one_cell(cell: str) -> list[dict[str, Any]]:
    if not cell:
        return []
    raw = _strip_toc_zero_width_joiners(cell.rstrip("\r\n"))
    cell = raw.strip()
    if not cell or _should_skip_cell(cell):
        return []
    out: list[dict[str, Any]] = []

    c0 = compact_for_match(cell)
    if _SECTION_RE.match(c0):
        out.append({"kind": "section", "label": c0})
        return out
    if _SECTION_EXTRA_RE.match(c0):
        out.append({"kind": "section", "label": c0})
        return out
    if _SECTION_ANCIENT_POETRY_RECITATION_RE.fullmatch(c0):
        out.append({"kind": "section", "label": _SECTION_ANCIENT_POETRY_LABEL})
        return out
    if _SECTION_UNIT_COMPACT_RE.fullmatch(c0):
        m_lb = re.match(r"^(第[一二三四五六七八九十百千万]+单元)", c0)
        out.append(
            {"kind": "section", "label": m_lb.group(1) if m_lb else c0.split(".")[0]}
        )
        return out

    m_belt = _TOC_BELT_COMPACT_RE.fullmatch(c0)
    if m_belt:
        out.append({"kind": "toc_belt", "label": m_belt.group(1)})
        return out

    m = _GARDEN_RE.match(cell)
    if m:
        g: dict[str, Any] = {"kind": "garden", "label": m.group(1)}
        if m.group(2) is not None:
            g["page"] = int(m.group(2))
        out.append(g)
        return out
    m = _GARDEN_SPACE_RE.match(cell)
    if m:
        g2: dict[str, Any] = {"kind": "garden", "label": m.group(1)}
        if m.group(2) is not None:
            g2["page"] = int(m.group(2))
        out.append(g2)
        return out

    if _READING_BAR_RE.match(cell):
        out.append({"kind": "reading_club", "title": "快乐读书吧"})
        return out
    m = _READING_BAR_SPACE_RE.match(cell)
    if m:
        sub = _clean_title(m.group(1))
        out.append(
            {
                "kind": "reading_club",
                "title": "快乐读书吧",
                "subtitle": sub,
                "page": int(m.group(2)),
            }
        )
        return out
    m = _READING_BAR_DOTS_RE.match(cell)
    if m:
        sub = _clean_title(m.group(1))
        out.append(
            {
                "kind": "reading_club",
                "title": "快乐读书吧",
                "subtitle": sub,
                "page": int(m.group(2)),
            }
        )
        return out

    m = _BLOCK_ACTIVITY_DOT_RE.match(cell)
    if m:
        out.append(
            {
                "kind": "block_activity",
                "block": m.group(1),
                "title": _clean_title(m.group(2)),
                "page": int(m.group(3)),
            }
        )
        return out
    m = _BLOCK_ACTIVITY_SPACE_RE.match(cell)
    if m:
        out.append(
            {
                "kind": "block_activity",
                "block": m.group(1),
                "title": _clean_title(m.group(2)),
                "page": int(m.group(3)),
            }
        )
        return out

    m = _SPECIAL_TOPIC_DOT_RE.match(cell)
    if m:
        out.append(
            {
                "kind": "block_activity",
                "block": "专题学习活动",
                "title": _clean_title(m.group(1)),
                "page": int(m.group(2)),
            }
        )
        return out
    m = _SPECIAL_TOPIC_SPACE_RE.match(cell)
    if m:
        out.append(
            {
                "kind": "block_activity",
                "block": "专题学习活动",
                "title": _clean_title(m.group(1)),
                "page": int(m.group(2)),
            }
        )
        return out

    m = _COMPREHENSIVE_STUDY_DOT_RE.match(cell)
    if m:
        out.append(
            {
                "kind": "block_activity",
                "block": "综合性学习",
                "title": _clean_title(m.group(1)),
                "page": int(m.group(2)),
            }
        )
        return out
    m = _COMPREHENSIVE_STUDY_SPACE_RE.match(cell)
    if m:
        out.append(
            {
                "kind": "block_activity",
                "block": "综合性学习",
                "title": _clean_title(m.group(1)),
                "page": int(m.group(2)),
            }
        )
        return out

    m = _LESSON_RE.match(cell)
    if m:
        out.append(
            {
                "kind": "lesson",
                "number": m.group(1),
                "title": _clean_title(m.group(3)),
                "page": int(m.group(4)),
                "optional_reading": bool(m.group(2)),
            }
        )
        return out
    m = _LESSON_SPACE_RE.match(cell)
    if m:
        out.append(
            {
                "kind": "lesson",
                "number": m.group(1),
                "title": _clean_title(m.group(3)),
                "page": int(m.group(4)),
                "optional_reading": bool(m.group(2)),
            }
        )
        return out
    if not re.search(r"\.{2,}", cell) and not re.search(
        r"\s{2,}\d{1,4}\s*$", cell.rstrip()
    ):
        m = _LESSON_NO_PAGE_RE.match(cell)
        if m:
            tit = _clean_title(m.group(3))
            if tit:
                out.append(
                    {
                        "kind": "lesson",
                        "number": m.group(1),
                        "title": tit,
                        "optional_reading": bool(m.group(2)),
                    }
                )
                return out

    m = _SUB_INDENT_RE.match(raw)
    if m:
        out.append(
            {
                "kind": "sublesson",
                "title": _clean_title(m.group(1)),
                "page": int(m.group(2)),
            }
        )
        return out
    m = _SUB_INDENT_SPACE_RE.match(raw)
    if m:
        t = _clean_title(m.group(1))
        if t:
            out.append({"kind": "sublesson", "title": t, "page": int(m.group(2))})
        return out

    m = _ORPHAN_TITLE_PAGE_RE.match(cell)
    if m and not re.match(r"^\d", m.group(1).strip()):
        t = _clean_title(m.group(1))
        tc = compact_for_match(t)
        if (
            t
            and not t.startswith("语文园地")
            and "单元·" not in t
            and "快乐读书吧" not in t
            and not _SECTION_UNIT_LABEL_ONLY_RE.fullmatch(tc)
            and not _COMPACT_BLOCK_OR_TOPIC_HEAD_RE.match(tc)
        ):
            out.append({"kind": "sublesson", "title": t, "page": int(m.group(2))})
        return out

    m = _ORPHAN_TITLE_SPACE_PAGE_RE.match(cell)
    if m and not re.match(r"^\d", m.group(1).strip()):
        t = _clean_title(m.group(1))
        tc = compact_for_match(t)
        if (
            t
            and not t.startswith("语文园地")
            and "单元·" not in t
            and "快乐读书吧" not in t
            and not _SECTION_RE.match(tc)
            and not _SECTION_EXTRA_RE.match(tc)
            and not _SECTION_UNIT_LABEL_ONLY_RE.fullmatch(tc)
            and not _COMPACT_BLOCK_OR_TOPIC_HEAD_RE.match(tc)
        ):
            out.append({"kind": "sublesson", "title": t, "page": int(m.group(2))})
        return out

    return []


def _try_parse_whole_line_before_column_split(line: str) -> list[dict[str, Any]] | None:
    """
    在 legacy「≥min_gap 空格分列」之前尝试整行解析。
    避免一年级等「标题与页码间仅多空格、无点线」被切成两栏后丢失课条。
    """
    raw = line.rstrip()
    if not raw.strip() or _should_skip_cell(raw.strip()):
        return None
    if _SUB_INDENT_RE.match(raw) or _SUB_INDENT_SPACE_RE.match(raw):
        hit = _parse_one_cell(raw)
        return hit if hit else None
    st = raw.strip()
    if (
        _LESSON_SPACE_RE.match(st)
        or _LESSON_RE.match(st)
        or _GARDEN_SPACE_RE.match(st)
        or _GARDEN_RE.match(st)
        or _READING_BAR_RE.match(st)
        or _READING_BAR_SPACE_RE.match(st)
        or _READING_BAR_DOTS_RE.match(st)
        or _SECTION_RE.match(compact_for_match(st))
        or _SECTION_EXTRA_RE.match(compact_for_match(st))
        or _SECTION_ANCIENT_POETRY_RECITATION_RE.fullmatch(compact_for_match(st))
        or _SECTION_UNIT_COMPACT_RE.fullmatch(compact_for_match(st))
        or _TOC_BELT_COMPACT_RE.fullmatch(compact_for_match(st))
        or bool(_BLOCK_ACTIVITY_DOT_RE.match(st))
        or bool(_BLOCK_ACTIVITY_SPACE_RE.match(st))
        or bool(_SPECIAL_TOPIC_DOT_RE.match(st))
        or bool(_SPECIAL_TOPIC_SPACE_RE.match(st))
        or bool(_COMPREHENSIVE_STUDY_DOT_RE.match(st))
        or bool(_COMPREHENSIVE_STUDY_SPACE_RE.match(st))
    ):
        hit = _parse_one_cell(st)
        return hit if hit else None
    if not re.match(r"^\d", st):
        if _ORPHAN_TITLE_SPACE_PAGE_RE.match(st):
            hit = _parse_one_cell(st)
            return hit if hit else None
    return None


def _parse_fragment_text(frag: str, options: dict[str, Any]) -> list[dict[str, Any]]:
    frag = frag.strip()
    if not frag or _should_skip_cell(frag):
        return []
    if _column_number(options) == 2:
        le, ri = _split_line_two_columns_rule(frag, options)
        acc: list[dict[str, Any]] = []
        if le.strip():
            acc.extend(_parse_physical_line(le, options))
        if ri.strip():
            acc.extend(_parse_physical_line(ri, options))
        return acc
    min_gap = _min_gap(options)
    cols = _split_single_or_double_columns_legacy(frag, min_gap)
    if len(cols) >= 2:
        acc2: list[dict[str, Any]] = []
        for c in cols:
            acc2.extend(_parse_physical_line(c, options))
        return acc2
    return _parse_one_cell(frag)


def _parse_physical_line(raw_line: str, options: dict[str, Any]) -> list[dict[str, Any]]:
    if not raw_line.strip():
        return []
    tail = raw_line.rstrip()

    if _column_number(options) == 2:
        le, ri = _split_line_two_columns_rule(tail, options)
        acc: list[dict[str, Any]] = []
        if le.strip():
            acc.extend(_parse_one_column_content(le, options))
        if ri.strip():
            acc.extend(_parse_one_column_content(ri, options))
        return acc

    min_gap = _min_gap(options)
    cols = _split_single_or_double_columns_legacy(tail, min_gap)
    if len(cols) >= 2:
        acc3: list[dict[str, Any]] = []
        for c in cols:
            acc3.extend(_parse_physical_line(c, options))
        return acc3

    return _parse_one_column_content(tail, options)


def _parse_physical_line_logged(
    raw_line: str,
    options: dict[str, Any],
    discard_sink: Callable[[str], None] | None,
) -> list[dict[str, Any]]:
    """顶层物理行：未解析出任何条目且非空行时记入抛弃日志（仅原文）。"""
    items = _parse_physical_line(raw_line, options)
    if (
        not items
        and raw_line.strip()
        and discard_sink
        and not _should_skip_cell(raw_line.strip())
    ):
        discard_sink(raw_line.rstrip("\r"))
    return items


# 目录区结束行：一律对 compact 后整串 fullmatch（避免双栏行内「…识字表…」误命中）
_DEFAULT_TOC_END_LINE_PATTERNS: tuple[str, ...] = (
    r"识字表.*",
    r"写字表.*",
    r"第[一二三四五六七八九十]单元",
    # 园地后紧跟点线（非「语文园地一」之「一」），且同行为写字表——与高年级版式一致，且不误伤「语文园地六…写字表」双栏行
    r"◎.*语文园地\.{2,}.*写字表.*",
)
# 换页后单独成行的「第N单元·阅读」为正文首页标题；目录内的单元行通常不带行首换页符
_RE_TOC_END_BODY_UNIT_READ_LINE = re.compile(
    r"^第[一二三四五六七八九十百千万]+单元·阅读$"
)
# 版式正文常见：拼音片段大小写混杂（如 xiAo、kE），目录行极少出现
_RE_TOC_BODY_PINYINISH = re.compile(r"[a-z]{1,3}[A-Z][a-z]+|[a-z][A-Za-z]*[A-Z][a-z]")


def _compact_line_matches_toc_end_pattern(pat_str: str, cc: str) -> bool:
    try:
        cre = re.compile(pat_str)
    except re.error as e:
        raise ValueError(f"无效 end_line_patterns 项: {pat_str!r} — {e}") from e
    return cre.fullmatch(cc) is not None


def _end_pattern_is_table_appendix_row(pat_str: str) -> bool:
    """识字表 / 写字表 等「附录表头」整行，易与正文识字表章节首行撞型，需限在目录后若干行内。"""
    p = pat_str.strip()
    if p.startswith("^"):
        p = p[1:]
    return p.startswith("识字表") or p.startswith("写字表")


# 三年级等：双栏目录右栏「识字表/写字表」单独成行后仍可有「第七单元」等，不得在此处截断目录区
_RE_TOC_LOOKAHEAD_UNIT_HEADER = re.compile(r"^第[一二三四五六七八九十百千万]+单元")


def _toc_more_unit_headers_follow(
    lines: list[str],
    after_i: int,
    max_look: int,
) -> bool:
    """在 after_i 之后 max_look 行内（含）是否出现新的「第N单元」目录行。"""
    end = min(after_i + 1 + max(0, max_look), len(lines))
    for k in range(after_i + 1, end):
        cc = compact_for_match(_strip_tabs(lines[k])).replace("\f", "")
        if not cc.strip():
            continue
        if _RE_TOC_LOOKAHEAD_UNIT_HEADER.match(cc):
            return True
    return False


def _line_looks_like_layout_pinyin_body(raw_line: str) -> bool:
    s = raw_line.strip()
    if len(s) < 12:
        return False
    return _RE_TOC_BODY_PINYINISH.search(s) is not None


def _parse_one_column_content(s: str, options: dict[str, Any]) -> list[dict[str, Any]]:
    """单列字符串：按课文块扫描 + 片段递归。"""
    st = s.strip()
    if not st:
        return []
    lessons = list(_LESSON_CHUNK_RE.finditer(st))
    if not lessons:
        return _parse_one_cell(s)

    out: list[dict[str, Any]] = []
    last = 0
    for m in lessons:
        if m.start() > last:
            out.extend(_parse_fragment_text(st[last : m.start()], options))
        out.extend(_parse_one_cell(m.group(0)))
        last = m.end()
    if last < len(st):
        out.extend(_parse_fragment_text(st[last:], options))
    return out


def _toc_region_line_bounds(full_text: str, inner: dict[str, Any]) -> tuple[int, int]:
    """目录正文在 splitlines() 中的闭区间 [start_idx+1, end_idx]（均含）；不含「目录」标题行与任一停止行。"""
    lines = full_text.splitlines()
    start_raw = inner.get("start_line_pattern") or ["目录"]
    start_list = [start_raw] if isinstance(start_raw, str) else list(start_raw)
    start_c = []
    for p in start_list:
        try:
            start_c.append(re.compile(p))
        except re.error as e:
            raise ValueError(f"无效 start_line_pattern: {p!r} — {e}") from e

    patterns_raw = inner.get("end_line_patterns")
    end_subs_raw = inner.get("end_line_substrings")
    end_patterns: list[str] | None = None
    end_subs: list[str] | None = None
    if patterns_raw is not None and len(patterns_raw) > 0:
        end_patterns = [str(p) for p in patterns_raw]
    elif end_subs_raw is not None and len(end_subs_raw) > 0:
        end_subs = [str(s) for s in end_subs_raw]
    else:
        end_patterns = list(_DEFAULT_TOC_END_LINE_PATTERNS)

    win_raw = inner.get("end_appendix_fullmatch_within_lines")
    win_n = int(win_raw) if win_raw is not None else 250
    min_after_raw = inner.get("end_line_min_lines_after_start")
    min_depth = max(0, int(min_after_raw)) if min_after_raw is not None else 20

    start_idx: int | None = None
    end_idx: int | None = None

    for i, line in enumerate(lines):
        c = compact_for_match(_strip_tabs(line))
        if start_idx is None and any(p.fullmatch(c) for p in start_c):
            start_idx = i
            continue
        if start_idx is not None and end_idx is None:
            depth = i - start_idx
            if depth < min_depth:
                continue
            cc = compact_for_match(_strip_tabs(line))
            if "\f" in line and _RE_TOC_END_BODY_UNIT_READ_LINE.fullmatch(cc):
                end_idx = i - 1
                break
            if end_patterns is not None:
                hit_pat = False
                for p in end_patterns:
                    if _end_pattern_is_table_appendix_row(p) and depth > win_n:
                        continue
                    if _compact_line_matches_toc_end_pattern(p, cc):
                        if _end_pattern_is_table_appendix_row(p):
                            lk_raw = inner.get(
                                "toc_appendix_ignore_if_unit_within_lines"
                            )
                            look_n = int(lk_raw) if lk_raw is not None else 20
                            if look_n > 0 and _toc_more_unit_headers_follow(
                                lines, i, look_n
                            ):
                                continue
                        end_idx = i - 1
                        hit_pat = True
                        break
                if hit_pat:
                    break
            elif end_subs is not None and any(sub in cc for sub in end_subs):
                end_idx = i - 1
                break
            if _line_looks_like_layout_pinyin_body(line):
                end_idx = i - 1
                break

    if start_idx is None:
        raise ValueError(f"未找到目录起始行: {start_list}")
    if end_idx is None:
        end_desc = end_patterns if end_patterns is not None else end_subs
        raise ValueError(f"未找到目录结束: {end_desc}")
    if end_idx < start_idx + 1:
        raise ValueError(
            "目录正文为空：停止行紧跟在「目录」标题之后，或停止行下标异常"
        )

    extend_patterns: list[re.Pattern[str]] = []
    for p in inner.get("extend_slice_while") or []:
        try:
            extend_patterns.append(re.compile(str(p)))
        except re.error as e:
            raise ValueError(f"无效 extend_slice_while: {p!r} — {e}") from e

    stop_ff = bool(inner.get("extend_stop_at_form_feed", True))

    j = end_idx
    if extend_patterns:
        while j + 1 < len(lines):
            raw_nxt = lines[j + 1]
            if stop_ff and "\f" in raw_nxt:
                break
            nxt = _strip_tabs(raw_nxt).replace("\f", "").strip()
            if not nxt:
                break
            if not any(rx.search(nxt) for rx in extend_patterns):
                break
            j += 1
        end_idx = j

    return start_idx, end_idx


def slice_toc_region(full_text: str, inner: dict[str, Any]) -> list[str]:
    start_idx, end_idx = _toc_region_line_bounds(full_text, inner)
    lines = full_text.splitlines()
    return lines[start_idx + 1 : end_idx + 1]


def slice_toc_region_pages(full_text: str, inner: dict[str, Any]) -> list[list[str]]:
    """
    按换页符 \\f 将目录正文切成多「页」，每页内再分列。
    splitlines() 会吞掉行界 \\f，故从原文截取子串后按 \\f 分割才能保留分页。
    """
    start_idx, end_idx = _toc_region_line_bounds(full_text, inner)
    lines_ke = full_text.splitlines(keepends=True)
    off_b = sum(len(lines_ke[i]) for i in range(start_idx + 1))
    off_e = sum(len(lines_ke[i]) for i in range(end_idx + 1))
    raw = full_text[off_b:off_e]
    pages: list[list[str]] = []
    for chunk in re.split(r"\f+", raw):
        pg = [ln.rstrip("\r") for ln in chunk.splitlines()]
        if any(x.strip() for x in pg):
            pages.append(pg)
    return pages if pages else [[]]


def _catalog_line_for_unit_rules(e: dict[str, Any]) -> str:
    """与目录行等价的紧凑串，供 unit_type_rules（keyword 或 match）匹配。"""
    k = e.get("kind")
    if k == "lesson":
        num = str(e.get("number") or "")
        title = (e.get("title") or "").strip()
        sub_t = (e.get("sublesson_title") or "").strip()
        extra = f"（{sub_t}）" if sub_t else ""
        if e.get("optional_reading"):
            return compact_for_match(f"{num}*{title}{extra}")
        return compact_for_match(f"{num} {title}{extra}")
    if k == "garden":
        return compact_for_match(e.get("label") or "")
    if k == "reading_club":
        sub = e.get("subtitle")
        st = (e.get("sublesson_title") or "").strip()
        base = "快乐读书吧"
        if sub:
            return compact_for_match(f"{base} {sub}")
        if st:
            return compact_for_match(f"{base} {st}")
        return compact_for_match(base)
    if k == "block_activity":
        blk = str(e.get("block") or "")
        return compact_for_match(f"{blk}{e.get('title') or ''}")
    if k == "sublesson":
        return compact_for_match(e.get("title") or "")
    if k == "toc_belt":
        lb = str(e.get("label") or "")
        ti = (e.get("title") or "").strip()
        if ti:
            return compact_for_match(f"{lb}{ti}")
        return compact_for_match(lb)
    if k == "section":
        return compact_for_match(e.get("label") or "")
    return ""


def _group_is_enrollment_education(group_label: str | None) -> bool:
    """「我上学了」分组下的学习单位属入学教育，非普通课文。"""
    if not group_label:
        return False
    return bool(_SECTION_EXTRA_RE.match(compact_for_match(group_label)))


def _group_is_ancient_poetry_recitation(group_label: str | None) -> bool:
    """「古诗词诵读」分组下的篇目为诵读类，非普通单元课文。"""
    if not group_label:
        return False
    c = compact_for_match(group_label)
    return c in ("古诗词诵读", "古诗诵读")


def _group_reading_mode(group_label: str | None) -> str | None:
    """从「第×单元·阅读/识字/汉语拼音」组头推断默认课文小类。"""
    if not group_label:
        return None
    c = compact_for_match(group_label)
    if c.endswith("单元·识字") or "单元·识字" in c:
        return "识字"
    if c.endswith("单元·阅读") or "单元·阅读" in c:
        return "阅读"
    if c.endswith("单元·汉语拼音") or "单元·汉语拼音" in c:
        return "汉语拼音"
    if _SECTION_UNIT_LABEL_ONLY_RE.fullmatch(c):
        return "阅读"
    return None


def _unit_type_rule_pattern_from_keyword(keyword: str) -> str:
    """
    由用户配置的「关键词」生成用于 compact 串的匹配正则（前缀命中）。

    兼容：行首可选 ◎/○、关键词后的可选全角/半角冒号（如 compact 后仍为「◎口语交际：…」）；
    关键词本身 re.escape，避免特殊字符误作语法。
    """
    kw = str(keyword).strip()
    if not kw:
        raise ValueError("unit_type_rules 的 keyword 不能为空")
    e = re.escape(kw)
    return rf"^(?:[◎○])?{e}(?:[:：])?"


def _compile_unit_type_rules(
    rules: list[Any],
) -> list[tuple[re.Pattern[str], dict[str, Any]]]:
    """
    每条规则可为：
    - **keyword**：仅填关键词，由代码生成兼容多种目录记号的正则；
    - **match**：手写正则（高级或与旧配置兼容）。若同时存在 keyword 与 match，以 keyword 为准。
    """
    out: list[tuple[re.Pattern[str], dict[str, Any]]] = []
    for raw in rules:
        if not isinstance(raw, dict):
            continue
        pat: str | None = None
        kw = raw.get("keyword")
        if kw is not None and str(kw).strip():
            try:
                pat = _unit_type_rule_pattern_from_keyword(str(kw))
            except ValueError as e:
                raise ValueError(f"无效 unit_type_rules 项: {raw!r} — {e}") from e
        else:
            m = raw.get("match")
            if m:
                pat = str(m)
        if not pat:
            continue
        try:
            rx = re.compile(pat)
        except re.error as e:
            raise ValueError(f"无效 unit_type_rules 匹配式: {pat!r} — {e}") from e
        out.append((rx, dict(raw)))
    return out


def _default_unit_type_subtype(
    e: dict[str, Any],
    group_label: str | None,
    strand: str | None = None,
) -> tuple[str, str | None]:
    k = e.get("kind")
    if k == "toc_belt":
        lab = str(e.get("label") or "").strip()
        if lab == "口语交际":
            return "口语交际", None
        if lab == "习作例文":
            return "习作", "习作例文"
        if lab == "习作":
            return "习作", None
        if lab == "综合性学习":
            return "综合性学习", None
        return "未分类", None

    if k == "block_activity":
        blk = str(e.get("block") or "")
        if blk == "口语交际":
            return "口语交际", None
        if blk == "习作例文":
            return "习作", "习作例文"
        if blk == "习作":
            return "习作", None
        if blk == "综合性学习":
            return "综合性学习", None
        if blk == "专题学习活动":
            return "专题学习活动", None
        return "未分类", None

    theme = _group_reading_mode(group_label)
    if k == "garden":
        return "语文园地", None
    if k == "reading_club":
        return "快乐读书吧", None
    if k == "lesson":
        if strand == "口语交际":
            return "口语交际", None
        if strand == "习作":
            return "习作", None
        if strand == "综合性学习":
            return "综合性学习", None
        if _group_is_enrollment_education(group_label):
            return "入学教育", None
        if _group_is_ancient_poetry_recitation(group_label):
            return "古诗词诵读", None
        return "课文", theme
    if k == "sublesson":
        if strand == "口语交际":
            return "口语交际", None
        if strand == "习作":
            return "习作", None
        if strand == "综合性学习":
            return "综合性学习", None
        if _group_is_enrollment_education(group_label):
            return "入学教育", None
        if _group_is_ancient_poetry_recitation(group_label):
            return "古诗词诵读", None
        return "课文", theme
    if k == "section":
        lb = compact_for_match(str(e.get("label") or ""))
        if _SECTION_EXTRA_RE.match(lb):
            return "分组", "入学教育"
        if lb == compact_for_match(_SECTION_ANCIENT_POETRY_LABEL):
            return "古诗词诵读", None
        return "分组", None
    return "未分类", None


def _apply_unit_type_rules_patch(
    line_compact: str,
    rules: list[tuple[re.Pattern[str], dict[str, Any]]],
) -> dict[str, Any]:
    """命中第一条规则时返回 YAML 中出现的字段子集（可仅含 unit_type 或 unit_subtype）。"""
    for rx, spec in rules:
        if rx.search(line_compact):
            p: dict[str, Any] = {}
            if "unit_type" in spec:
                p["unit_type"] = spec["unit_type"]
            if "unit_subtype" in spec:
                p["unit_subtype"] = spec["unit_subtype"]
            return p
    return {}


def build_toc_groups_tree(
    entries_plain: list[dict[str, Any]],
    rules_raw: list[Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    第一层 group（单元；见分组头 section），第二层 unit（学习单位）。
    返回 (展平条目（含 unit_type / unit_subtype / group_label）, groups 树)。
    """
    rules = _compile_unit_type_rules(list(rules_raw or []))
    flat_out: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    current_label: str | None = None
    current_units: list[dict[str, Any]] = []
    strand: str | None = None

    def flush_group() -> None:
        if current_units or current_label is not None:
            groups.append(
                {
                    "group_id": len(groups) + 1,
                    "group_label": current_label,
                    "units": list(current_units),
                }
            )
        current_units.clear()

    for e in entries_plain:
        if e.get("kind") == "section":
            strand = None
            flush_group()
            current_label = str(e.get("label") or "")
            line_c = _catalog_line_for_unit_rules(e)
            sec_patch = _apply_unit_type_rules_patch(line_c, rules)
            ut_sec, us_sec = _default_unit_type_subtype(e, None)
            flat_out.append(
                {
                    **e,
                    "unit_type": sec_patch.get("unit_type", ut_sec),
                    "unit_subtype": sec_patch["unit_subtype"]
                    if "unit_subtype" in sec_patch
                    else us_sec,
                    "group_label": current_label,
                }
            )
            continue

        if e.get("kind") == "toc_belt":
            strand = str(e.get("label") or "").strip()
            line_c = _catalog_line_for_unit_rules(e)
            patch = _apply_unit_type_rules_patch(line_c, rules)
            ut_def, us_def = _default_unit_type_subtype(e, current_label)
            ut = patch["unit_type"] if "unit_type" in patch else ut_def
            us = patch["unit_subtype"] if "unit_subtype" in patch else us_def
            ue = {
                **e,
                "unit_type": ut,
                "unit_subtype": us,
                "group_label": current_label,
            }
            flat_out.append(ue)
            current_units.append(ue)
            continue

        if e.get("kind") in ("garden", "reading_club", "block_activity"):
            strand = None

        line_c = _catalog_line_for_unit_rules(e)
        ut_def, us_def = _default_unit_type_subtype(e, current_label, strand)
        patch = _apply_unit_type_rules_patch(line_c, rules)
        ut = patch["unit_type"] if "unit_type" in patch else ut_def
        us = patch["unit_subtype"] if "unit_subtype" in patch else us_def
        ue = {
            **e,
            "unit_type": ut,
            "unit_subtype": us,
            "group_label": current_label,
        }
        flat_out.append(ue)
        current_units.append(ue)

    flush_group()
    return flat_out, groups


_MERGE_SKIP_PARENT_KINDS = frozenset({"sublesson", "section"})


def _merge_parent_single_sublesson(
    parent: dict[str, Any],
    child: dict[str, Any],
) -> dict[str, Any]:
    """子目并入父目：字段以父为准（重合键覆盖子），并尽量保留子的独立标题。"""
    merged = dict(child)
    merged.update(parent)
    pt = parent.get("title")
    ct = child.get("title")
    ps = (str(pt).strip() if pt is not None else "")
    cs = (str(ct).strip() if ct is not None else "")
    if ps and cs and compact_for_match(ps) != compact_for_match(cs):
        merged["sublesson_title"] = cs
    return merged


def _collapse_single_sublessons(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """紧随父目且仅一条子目（sublesson）时合并为一项；多条子目保持原层级。"""
    out: list[dict[str, Any]] = []
    i = 0
    n = len(items)
    while i < n:
        e = items[i]
        k = e.get("kind")
        if k == "sublesson":
            out.append(e)
            i += 1
            continue
        j = i + 1
        while j < n and items[j].get("kind") == "sublesson":
            j += 1
        n_sub = j - i - 1
        if n_sub == 0:
            if (
                k == "toc_belt"
                and i + 1 < n
                and items[i + 1].get("kind") == "block_activity"
            ):
                out.append(_merge_parent_single_sublesson(e, items[i + 1]))
                i += 2
            else:
                out.append(e)
                i += 1
        elif k not in _MERGE_SKIP_PARENT_KINDS and n_sub == 1:
            out.append(_merge_parent_single_sublesson(e, items[i + 1]))
            i = j
        else:
            out.append(e)
            for t in range(i + 1, j):
                out.append(items[t])
            i = j
    return out


def _groups_from_collapsed_entries(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """与 build_toc_groups_tree 相同的分组边界，用于折叠子目后重建 groups。"""
    groups: list[dict[str, Any]] = []
    current_label: str | None = None
    current_units: list[dict[str, Any]] = []

    def flush() -> None:
        if current_units or current_label is not None:
            groups.append(
                {
                    "group_id": len(groups) + 1,
                    "group_label": current_label,
                    "units": list(current_units),
                }
            )
        current_units.clear()

    for e in entries:
        if e.get("kind") == "section":
            flush()
            current_label = str(e.get("label") or "")
        else:
            current_units.append(e)
    flush()
    return groups


def _toc_md_page(pg: Any) -> str:
    """Markdown 核对行中的页码；无页码时占位为 p.???。"""
    if pg is None:
        return "p.???"
    return f"p.{pg}"


def _toc_md_missing_text(val: Any) -> str:
    """Markdown 核对行：缺省的正文类字段用 ???。"""
    if val is None:
        return "???"
    s = str(val).strip()
    return s if s else "???"


def _format_toc_entry_markdown_line(e: dict[str, Any]) -> str:
    """单行展示一条目录解析结果（分组 / 学习单位）。"""
    eid = e.get("id", "")
    kind = str(e.get("kind") or "")
    ut = e.get("unit_type") or ""
    us = e.get("unit_subtype")
    parts = [x for x in (ut, us) if x]
    type_s = " / ".join(parts) if parts else ""

    if kind == "section":
        lb = _toc_md_missing_text(e.get("label"))
        return f"**[Group]** {lb} · `{eid}`" + (f" · {type_s}" if type_s else "")
    if kind == "toc_belt":
        lb = _toc_md_missing_text(e.get("label"))
        ti = (e.get("title") or "").strip()
        pg_s = f"{_toc_md_page(e.get('page'))} · "
        if ti:
            return (
                f"**【{lb}】** {ti} · {pg_s}`{eid}`" + (f" · {type_s}" if type_s else "")
            )
        return f"**【{lb}】** · {pg_s}`{eid}`" + (f" · {type_s}" if type_s else "")
    if kind == "lesson":
        n = _toc_md_missing_text(e.get("number"))
        title = _toc_md_missing_text(e.get("title"))
        sub_t = (e.get("sublesson_title") or "").strip()
        if e.get("optional_reading"):
            # 略读 * 与加粗分界用空格隔开，避免写 \\* 脱义
            head = f"**{n}** * {title}"
        else:
            head = f"**{n}** {title}"
        if sub_t:
            head += f"（{sub_t}）"
        pg_s = f"{_toc_md_page(e.get('page'))} · "
        tail = f"{pg_s}`{eid}`"
        return f"{head} · {tail}" + (f" · {type_s}" if type_s else "")
    if kind == "garden":
        lb = _toc_md_missing_text(e.get("label"))
        pg_s = f"{_toc_md_page(e.get('page'))} · "
        return f"**{lb}** · {pg_s}`{eid}`" + (f" · {type_s}" if type_s else "")
    if kind == "reading_club":
        sub = e.get("subtitle")
        st = (e.get("sublesson_title") or "").strip()
        bits = "**快乐读书吧**"
        if sub:
            bits += f"（{sub}）"
        elif st:
            bits += f"（{st}）"
        bits += f" · {_toc_md_page(e.get('page'))}"
        return f"{bits} · `{eid}`" + (f" · {type_s}" if type_s else "")
    if kind == "block_activity":
        blk = _toc_md_missing_text(e.get("block"))
        ti = _toc_md_missing_text((e.get("title") or "").strip())
        pg_s = f"{_toc_md_page(e.get('page'))} · "
        return (
            f"**【{blk}】** {ti} · {pg_s}`{eid}`" + (f" · {type_s}" if type_s else "")
        )
    if kind == "sublesson":
        ti = _toc_md_missing_text(e.get("title"))
        pg_s = f"{_toc_md_page(e.get('page'))} · "
        return f"{ti} · {pg_s}`{eid}`" + (f" · {type_s}" if type_s else "")
    if kind == "reading_pick":
        ti = _toc_md_missing_text(e.get("title"))
        return f"**篇目** {ti} · `{eid}`" + (f" · {type_s}" if type_s else "")
    return f"`{eid}` · `{kind}`" + (f" · {type_s}" if type_s else "")


def _toc_markdown_unordered_nested(items: list[dict[str, Any]]) -> list[str]:
    """子目 (sublesson) 缩进一级，从属于紧邻上一行非子目条目。"""
    out: list[str] = []
    i = 0
    while i < len(items):
        e = items[i]
        if e.get("kind") == "sublesson":
            out.append(f"- {_format_toc_entry_markdown_line(e)}")
            i += 1
            continue
        j = i + 1
        while j < len(items) and items[j].get("kind") == "sublesson":
            j += 1
        out.append(f"- {_format_toc_entry_markdown_line(e)}")
        for k in range(i + 1, j):
            out.append(f"  - {_format_toc_entry_markdown_line(items[k])}")
        i = j
    return out


def render_layout_toc_markdown(result: dict[str, Any]) -> str:
    """
    由 layout_toc 的 JSON 结果生成便于人工核对的 Markdown（层级：分组 → 学习单位）。
    """
    book = str(result.get("book_code") or "")
    ext = str(result.get("extractor") or "目录")
    groups = list(result.get("groups") or [])
    entries = list(result.get("entries") or [])
    lines: list[str] = [
        f"# 目录核对：{book}",
        "",
        f"由 **{ext}** 抽取结果生成，便于与教材 PDF 目录对照。",
        "",
    ]
    if dl := result.get("discard_log"):
        log_name = Path(str(dl)).name
        lines.extend(
            [
                f"> **核对提示：** 请查看同目录下的 [抛弃行日志]({log_name})，其中为解析时未纳入条目的正文行。",
                "",
            ]
        )
    lines.extend(
        [
            f"- Groups: {result.get('group_count', len(groups))}",
            f"- 条目数：{result.get('entry_count', len(entries))}",
        ]
    )
    if (fc := result.get("flat_count")) is not None:
        lines.append(f"- 可对应识字/写字等目录串条数：{fc}")
    lines.extend(["", "---", ""])

    for g in groups:
        gid = g.get("group_id", "")
        glabel = g.get("group_label")
        label_s = glabel if glabel else "(unnamed group)"
        lines.append(f"### [Group {gid}] {label_s}")
        lines.append("")
        units = list(g.get("units") or [])
        if not units:
            lines.append("*（本组下无学习单位条目）*")
            lines.append("")
            continue
        lines.extend(_toc_markdown_unordered_nested(units))
        lines.append("")

    return "\n".join(lines)


def _entries_to_flat_strings(entries: list[dict[str, Any]]) -> list[str]:
    flat: list[str] = []
    for e in entries:
        k = e.get("kind")
        if k == "lesson":
            num = e["number"]
            title = e["title"]
            sub_t = (e.get("sublesson_title") or "").strip()
            extra = f"（{sub_t}）" if sub_t else ""
            if e.get("optional_reading"):
                flat.append(f"{num}* {title}{extra}")
            else:
                flat.append(f"{num} {title}{extra}")
        elif k == "garden":
            flat.append(e["label"])
        elif k == "reading_club":
            sub = e.get("subtitle")
            st = (e.get("sublesson_title") or "").strip()
            if sub:
                flat.append(f"快乐读书吧 {sub}")
            elif st:
                flat.append(f"快乐读书吧 {st}")
            else:
                flat.append("快乐读书吧")
        elif k == "toc_belt":
            lb = str(e.get("label") or "")
            ti = (e.get("title") or "").strip()
            flat.append(f"{lb}{ti}" if ti else lb)
        elif k == "block_activity":
            flat.append(f"{e['block']} {e['title']}")
        elif k == "sublesson":
            flat.append(e["title"])
        elif k == "reading_pick":
            flat.append(e["title"])
    return flat


def _next_nonempty_line(
    body_lines: list[str],
    start: int,
) -> str | None:
    for k in range(start, len(body_lines)):
        t = _strip_tabs(body_lines[k]).replace("\f", "").replace("\r", "").strip()
        if t:
            return t
    return None


def _line_starts_section(line: str) -> bool:
    c0 = compact_for_match(line.strip())
    return bool(
        _SECTION_PREFIX_RE.match(c0)
        or _SECTION_EXTRA_RE.match(c0)
        or _SECTION_ANCIENT_POETRY_RECITATION_RE.fullmatch(c0)
        or _SECTION_UNIT_COMPACT_RE.fullmatch(c0)
    )


def _append_dual_column_row_from_split(
    dual_left: list[str],
    dual_right: list[str],
    le: str,
    ri: str,
) -> None:
    """
    同一页双栏暂存：将本行分列得到的 *左栏格*、*右栏格* 写入 `dual_left[i]`、`dual_right[i]`（同索引成对）。
    仅去 \\t（`_strip_tabs`），不交换左右；若只有一侧有正文，另一侧为空串，仍按方向写入。
    """
    _append_dual_column_pair(dual_left, dual_right, _strip_tabs(le), _strip_tabs(ri))


def _append_dual_column_pair(
    dual_left: list[str],
    dual_right: list[str],
    le: str,
    ri: str,
) -> None:
    """
    列优先缓冲：若与上一行分列结果 (le,ri) 完全相同，视为重复粘贴的版式行，不再追加。
    （否则仅首条会被 _apply_dual_right_only_block_reposition 等修正，后续重复条仍落在流后部、分组错乱。）
    """
    if (
        dual_left
        and dual_right
        and dual_left[-1] == le
        and dual_right[-1] == ri
    ):
        return
    dual_left.append(le)
    dual_right.append(ri)


def _flush_dual_column_buffers(
    left_cells: list[str],
    right_cells: list[str],
    options: dict[str, Any],
    discard_sink: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """双栏连续行：先左栏自上而下全部条目，再右栏自上而下（与教材目录「先读完左栏再右栏」一致）。

    对同行「左格空、右格有文」解析出的条目打上 *toc_dual_right_only_row*（内部用，输出前剔除），
    供 _apply_dual_right_only_block_reposition 按栏块类型纠偏顺序，不依赖具体课题标题。
    """
    out: list[dict[str, Any]] = []
    for c in left_cells:
        if c.strip():
            out.extend(_parse_physical_line_logged(c, options, discard_sink))
    n_left = len(left_cells)
    for i, c in enumerate(right_cells):
        if not c.strip():
            continue
        left_empty = not (i < n_left and left_cells[i].strip())
        parsed = _parse_physical_line_logged(c, options, discard_sink)
        for e in parsed:
            if left_empty:
                e["toc_dual_right_only_row"] = True
            out.append(e)
    left_cells.clear()
    right_cells.clear()
    return out


def _dual_right_only_move_block_labels(options: dict[str, Any]) -> frozenset[str]:
    raw = options.get("toc_dual_right_only_move_blocks")
    if raw is None:
        return frozenset({"口语交际"})
    if isinstance(raw, str):
        s = raw.strip()
        return frozenset({s}) if s else frozenset()
    out: set[str] = set()
    for b in raw:
        t = str(b).strip()
        if t:
            out.add(t)
    return frozenset(out)


def _apply_dual_right_only_block_reposition(
    entries: list[dict[str, Any]], options: dict[str, Any]
) -> None:
    """
    列优先冲刷时，「左空右实」行的栏块活动会排在整页左栏条目之后，可能误挂在后续单元；
    将首个落在指定分组头 *之后*、且带 *toc_dual_right_only_row*、栏块类型在配置集合内的条目，
    挪到该分组头之前（与纸质「先左栏该单元头、再右栏附属栏块」一致）。

    选项：toc_dual_right_only_move_before_section（null/false/\"\" 关闭）、toc_dual_right_only_move_blocks。
    """
    raw = options.get("toc_dual_right_only_move_before_section", "第六单元")
    if raw is None or raw is False:
        return
    section_label = str(raw).strip()
    if not section_label:
        return
    block_labels = _dual_right_only_move_block_labels(options)
    if not block_labels:
        return
    i_sec = next(
        (
            i
            for i, e in enumerate(entries)
            if e.get("kind") == "section"
            and str(e.get("label") or "").strip() == section_label
        ),
        None,
    )
    if i_sec is None:
        return
    io = next(
        (
            i
            for i, e in enumerate(entries)
            if i > i_sec
            and e.get("kind") == "block_activity"
            and str(e.get("block") or "").strip() in block_labels
            and e.get("toc_dual_right_only_row")
        ),
        None,
    )
    if io is None:
        return
    block_e = entries.pop(io)
    block_e.pop("toc_dual_right_only_row", None)
    entries.insert(i_sec, block_e)


def extract_layout_toc(
    full_text: str,
    options: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    discard_sink = meta.pop("discard_sink", None)
    column_major = str(options.get("dual_column_entry_order", "column")).lower() != "row"
    cn = _column_number(options)
    # 列优先时按换页 \\f 分段，避免跨页把左栏与右栏拼成一大块
    if column_major:
        pages = slice_toc_region_pages(full_text, options)
    else:
        pages = [slice_toc_region(full_text, options)]
    body_lines_flat = [ln for pg in pages for ln in pg]

    entries: list[dict[str, Any]] = []

    for page in pages:
        dual_left: list[str] = []
        dual_right: list[str] = []
        prev_lr_row: tuple[str, str] | None = None

        for i, raw_line in enumerate(page):
            # —— 分列前行文（与行首宽度计量有关）——
            # 1) slice_toc_region_pages：每行仅 rstrip("\\r")，不删行首空白、不删 \\t
            # 2) line_no_ff：去掉行内 \\f、\\r；不 lstrip，分列必须用此串（保留 \\t）
            # 3) line = _strip_tabs(line_no_ff)：仅用于「是否空行」与非双栏分支；分列输入勿用 line
            # 4) _split_line_two_columns_rule(line_no_ff.rstrip())：仅去掉行尾 Unicode 空白，不影响行首宽度
            line_no_ff = raw_line.replace("\f", "").replace("\r", "")
            line = _strip_tabs(line_no_ff)
            if not line.strip():
                nxt = _next_nonempty_line(page, i + 1)
                if (
                    column_major
                    and dual_left
                    and nxt
                    and _line_starts_section(nxt)
                ):
                    entries.extend(
                        _flush_dual_column_buffers(
                            dual_left, dual_right, options, discard_sink
                        )
                    )
                continue

            if cn == 2:
                le, ri = _split_line_two_columns_rule(line_no_ff.rstrip(), options)
                if column_major:
                    _append_dual_column_row_from_split(dual_left, dual_right, le, ri)
                else:
                    le_t, ri_t = _strip_tabs(le), _strip_tabs(ri)
                    pair = (le_t, ri_t)
                    if prev_lr_row == pair:
                        continue
                    prev_lr_row = pair
                    if le_t.strip():
                        entries.extend(
                            _parse_physical_line_logged(le_t, options, discard_sink)
                        )
                    if ri_t.strip():
                        entries.extend(
                            _parse_physical_line_logged(ri_t, options, discard_sink)
                        )
                continue

            whole = _try_parse_whole_line_before_column_split(line.rstrip())
            if whole is not None:
                if column_major and dual_left:
                    entries.extend(
                        _flush_dual_column_buffers(
                            dual_left, dual_right, options, discard_sink
                        )
                    )
                entries.extend(whole)
                continue

            # --- legacy：min_gap + 窄行启发 ---
            min_gap = _min_gap(options)
            cols = _split_single_or_double_columns_legacy(line.rstrip(), min_gap)
            if column_major and len(cols) == 2:
                dual_left.append(cols[0])
                dual_right.append(cols[1])
                continue

            pair = _narrow_two_lesson_cells(line) if column_major else None
            if pair:
                dual_left.append(pair[0])
                dual_right.append(pair[1])
                continue

            lg = _narrow_lesson_and_garden_cells(line) if column_major else None
            if lg:
                dual_left.append(lg[0])
                dual_right.append(lg[1])
                continue

            if column_major and dual_left:
                roc = _right_only_lesson_cell(raw_line)
                if roc and len(dual_left) >= 2:
                    dual_left.append("")
                    dual_right.append(roc)
                    continue
                if _left_only_single_lesson_row(line) and len(dual_left) >= 2:
                    dual_left.append(line.strip())
                    dual_right.append("")
                    continue

            if column_major and dual_left:
                entries.extend(
                    _flush_dual_column_buffers(
                        dual_left, dual_right, options, discard_sink
                    )
                )

            entries.extend(
                _parse_physical_line_logged(line, options, discard_sink)
            )

        if column_major:
            entries.extend(
                _flush_dual_column_buffers(
                    dual_left, dual_right, options, discard_sink
                )
            )
        elif dual_left or dual_right:
            entries.extend(
                _flush_dual_column_buffers(
                    dual_left, dual_right, options, discard_sink
                )
            )

    _apply_dual_right_only_block_reposition(entries, options)
    for e in entries:
        e.pop("toc_dual_right_only_row", None)

    rules_raw = options.get("unit_type_rules")
    entries, groups = build_toc_groups_tree(entries, rules_raw)
    entries = _collapse_single_sublessons(entries)
    groups = _groups_from_collapsed_entries(entries)

    book = str(meta.get("book_code") or "book")
    for i, e in enumerate(entries):
        e["id"] = f"{book}-toc-{i + 1:04d}"

    flat = _entries_to_flat_strings(entries)
    out: dict[str, Any] = {
        **meta,
        "entries": entries,
        "groups": groups,
        "toc_unit_strings": flat,
        "entry_count": len(entries),
        "flat_count": len(flat),
        "group_count": len(groups),
    }
    if not options.get("omit_source_lines"):
        out["source_lines"] = list(body_lines_flat)
        out["source_text"] = "\n".join(body_lines_flat)
    return out
