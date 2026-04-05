"""
按目录对版式正文分块：设计说明与匹配原语（基于人教版语文 pdftotext -layout 样本实勘）。

## 实勘结论（三年级上册、一年级上册等）

1. **版式分页**  
   常见 `\\f`（换页）与单独成行页码（如 `2`、`12`），页码多为 1–3 位数字，不与标题同一行，或贴在行尾。

2. **课文起头形态**  
   - 类型 A：栏头「阅 读」+ 课次 `1` + 带圈注码 `①` + 下一行大标题「大青树下的小学」（标题与课次可分两行）。  
   - 类型 B：课次、略读星号与 `①` 同在一行，标题在下一行（如 `3     *            ①` 后是「不懂就要问」）。  
   - 类型 C（低年级）：`3   口耳目手足` 课次与标题同一行，字距大。

3. **干扰项**  
   - 全半角空格、制表符、零宽字符 → 与目录一致地做 compact。  
   - 带圈数字 `①②…`：多为脚注/作者简介，**不是**课题名的一部分；匹配前应剥离或整行标为「注码行」跳过。  
   - 短行：单独「阅读」「识字」、纯页码、单字行，不宜当标题。  
   - 目录中的 `*` 略读标记在正文中可能是 `*` 或 `＊`，与课次同现。

4. **目录 JSON 可用字段**  
   - `kind` / `number` / `title` / `optional_reading` / `page` / `label`（园地）  
   - `page` 可与正文中的孤立页码做**弱校验**（允许 ±1 页漂移）。  
   - `sublesson` 需用 `title` 在「古诗三首」类块内二次锚定。

## 推荐流程（匹配前 → 锚定 → 分块）

1. **归一化**  
   对每一行：`strip` → 去 tab → `compact`（与 char_tables 一致：删空白），得到 `c`。  
   注码行：`^[①-⑳⓪…]+` 开头且剩余很短 → 标记为脚注行，不参与标题命中。

2. **噪声过滤**  
   - `len(c) <= 2` 且无非汉字或仅为数字 → 噪声。  
   - `c` 整行匹配纯数字 1–3 位 → 页码候选。  
   - `c` 为 `阅读|识字|…` 等栏头 → 噪声。  
   - 标题候选：`c` 以汉字为主，`len(c) >= 3`，且不在噪声集合内。

3. **标题键**  
   从目录项生成：`title_c = compact(title)`；课文再生成 `f"{number}{title_c}"`、`f"{number}*{title_c}"`（略读）等变体。

4. **扫描策略**  
   自上一锚点行号之后线性向前：  
   - 优先：`c == title_c` 且行宽接近标题（`|c| <= |title_c| + 小阈值`），减少误命中正文中的子串。  
   - 次优：窗口 2–3 行内合并 compact，匹配「数字 + 可选 * + 标题」或「上一行课次、下一行标题」。  
   - 可选：在命中行附近 ±15 行内查找孤立页码，与 `toc.page` 比对作置信度加权。

5. **分块边界**  
   第 i 个学习单位块为 `[anchor_i, anchor_{i+1})`（行号半开区间）；`section` 仅作分组标签，一般不产生正文锚点。

## 局限

双栏混行、标题折行跨页、目录与正文标题用字不一致时，需人工或二次规则；本模块只提供**原语与浅层试探**，不保证全册自动正确。
"""

from __future__ import annotations

import re
from typing import Any

from .extractors.char_tables import compact_for_match

# 带圈数字（常见脚注标记）；可扩展至 UNICODE 带圈
_CIRCLED_HEAD_RE = re.compile(
    r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]+"
)
# 略读星号（目录 * 与正文）
_STAR_CHARS = frozenset("*＊")

_COL_HEAD_COMPACT = frozenset(
    {
        "阅读",
        "识字",
        "写字",
        "汉语拼音",
        "口语交际",
        "习作",
        "语文园地",
        "快乐读书吧",
        "日积月累",
        "词句段运用",
        "书写提示",
        "我的发现",
        "交流平台",
    }
)


def line_compact(line: str) -> str:
    """与表类提取器一致的紧凑串（用于与目录标题比对）。"""
    return compact_for_match(line)


def strip_leading_circled(s_compact: str) -> str:
    """去掉 compact 串前缀的带圈数字（脚注标记）。"""
    return _CIRCLED_HEAD_RE.sub("", s_compact)


def is_page_number_line(c: str) -> bool:
    """单独成行的阿拉伯页码（1–3 位）。"""
    return bool(re.fullmatch(r"\d{1,3}", c))


def is_column_head_line(c: str) -> bool:
    """栏头短行（阅读/识字等）。"""
    return c in _COL_HEAD_COMPACT


def is_noise_short_line(c: str, *, max_len: int = 2) -> bool:
    """
    极短 compact 行：多为版式碎片，一般不是标题。
    max_len=2 时过滤单字、两字纯符号等；课次单独成行「1」「2」长度为 1，也会被滤掉（由数字行规则另判）。
    """
    if not c:
        return True
    if len(c) <= max_len:
        return True
    return False


def is_footnote_author_line(c: str) -> bool:
    """以带圈数字开头的作者简介/注释行。"""
    if not c:
        return False
    if _CIRCLED_HEAD_RE.match(c):
        return True
    # 部分 PDF 「1 本文作者…」无圈
    if "本文作者" in c or "选作课文" in c or "选自" in c:
        return len(c) < 40
    return False


def toc_title_keys(entry: dict[str, Any]) -> list[str]:
    """
    由目录条目生成用于正文扫描的 compact 键（去重保序）。
    覆盖课文标题、略读变体、园地 label 等。
    """
    keys: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        t = strip_leading_circled(compact_for_match(s))
        if len(t) < 2 or t in seen:
            return
        seen.add(t)
        keys.append(t)

    kind = entry.get("kind")
    if kind == "lesson":
        title = entry.get("title")
        num = entry.get("number")
        if title:
            add(str(title))
            if num is not None:
                ns = str(num).strip()
                add(f"{ns}{str(title).strip()}")
                if entry.get("optional_reading"):
                    add(f"{ns}*{str(title).strip()}")
                    add(f"{ns}＊{str(title).strip()}")
        return keys
    if kind == "sublesson":
        t = entry.get("title")
        if t:
            add(str(t))
        return keys
    if kind == "garden":
        lb = entry.get("label")
        if lb:
            add(str(lb))
        return keys
    if kind == "reading_club":
        add("快乐读书吧")
        st = entry.get("subtitle")
        if st:
            add(str(st))
        return keys
    if kind == "block_activity":
        blk = entry.get("block")
        ti = entry.get("title")
        if blk and ti:
            add(f"{blk}{ti}")
        elif ti:
            add(str(ti))
        return keys
    if kind == "toc_belt":
        lb = entry.get("label")
        ti = entry.get("title")
        if lb and ti:
            add(f"{lb}{ti}")
        elif ti:
            add(str(ti))
        return keys
    return keys


def _title_like_score(c: str) -> int:
    """粗粒度：越长且含汉字越多越像标题；用于排序候选。"""
    if not c:
        return 0
    han = sum(1 for ch in c if "\u4e00" <= ch <= "\u9fff")
    return han * 10 + min(len(c), 40)


def find_forward_title_line(
    lines: list[str],
    keys: list[str],
    *,
    start: int = 0,
    title_slack: int = 6,
) -> int | None:
    """
    从 start 起向前扫描，找第一行其 compact（去带圈前缀后）等于某一 key，
    且 |line| <= |key| + title_slack，以降低正文子串误匹配。
    """
    for i in range(max(0, start), len(lines)):
        raw = lines[i]
        c0 = line_compact(raw)
        c = strip_leading_circled(c0)
        if is_page_number_line(c) or is_column_head_line(c):
            continue
        if is_footnote_author_line(c):
            continue
        if is_noise_short_line(c, max_len=1):
            continue
        for key in keys:
            if not key:
                continue
            if c == key and len(c) <= len(key) + title_slack:
                return i
    return None


def find_forward_title_multiline(
    lines: list[str],
    keys: list[str],
    *,
    start: int = 0,
    window: int = 3,
    title_slack: int = 8,
) -> int | None:
    """
    在 window 行滑动窗口内拼接 compact（忽略空行）后尝试匹配 keys；
    用于「课次行 + 标题行」分裂的情况。返回命中窗口内**最后一行**索引作为展示锚点。
    """
    n = len(lines)
    for i in range(max(0, start), n):
        parts: list[str] = []
        line_idxs: list[int] = []
        for j in range(i, min(i + window, n)):
            cj = strip_leading_circled(line_compact(lines[j]))
            if not cj:
                continue
            if is_page_number_line(cj) and len(parts) == 0:
                continue
            if is_column_head_line(cj) and len(parts) == 0:
                continue
            parts.append(cj)
            line_idxs.append(j)
            merged = "".join(parts)
            for key in keys:
                if key in merged and len(merged) <= len(key) + title_slack + 4:
                    if merged == key or merged.endswith(key) or key == merged[-len(key) :]:
                        return line_idxs[-1]
    return None


def propose_chunk_line_spans(
    full_text: str,
    toc_entries: list[dict[str, Any]],
    *,
    body_start_line: int = 0,
    use_multiline: bool = True,
) -> list[dict[str, Any]]:
    """
    为目录中可锚定的条目估计 [start_line, end_line)（行号基于 full_text.splitlines()）。

    - body_start_line：正文起始行（可跳过扉页、目录页；默认 0 表示整文件）。
    - 返回每项含：id, kind, keys_tried, start_line, end_line, match_mode。
    """
    lines = full_text.splitlines()
    n = len(lines)
    anchorable_kinds = frozenset(
        {
            "lesson",
            "sublesson",
            "garden",
            "reading_club",
            "block_activity",
            "toc_belt",
        }
    )
    anchors: list[dict[str, Any]] = []
    cursor = max(0, body_start_line)

    for e in toc_entries:
        kind = e.get("kind")
        if kind not in anchorable_kinds:
            continue
        keys = toc_title_keys(e)
        if not keys:
            continue
        idx = find_forward_title_line(lines, keys, start=cursor)
        mode = "single"
        if idx is None and use_multiline:
            idx = find_forward_title_multiline(lines, keys, start=cursor)
            mode = "window"
        eid = e.get("id", "")
        if idx is None:
            anchors.append(
                {
                    "id": eid,
                    "kind": kind,
                    "keys_tried": keys,
                    "start_line": None,
                    "end_line": None,
                    "match_mode": None,
                    "ok": False,
                }
            )
            continue
        anchors.append(
            {
                "id": eid,
                "kind": kind,
                "keys_tried": keys,
                "start_line": idx,
                "end_line": None,
                "match_mode": mode,
                "ok": True,
            }
        )
        cursor = idx + 1

    for i, a in enumerate(anchors):
        if not a.get("ok") or a.get("start_line") is None:
            continue
        start = a["start_line"]
        end = n
        for j in range(i + 1, len(anchors)):
            if anchors[j].get("ok") and anchors[j].get("start_line") is not None:
                end = anchors[j]["start_line"]
                break
        a["end_line"] = end

    return anchors


def suggest_body_start_line(lines: list[str], *, scan_limit: int = 500) -> int:
    """
    启发式：在文件前若干行内找**独占一行**的「第×单元」分组头（compact 全串即单元名），
    以跳过双栏目录里同一行含多个「第×单元」的目录行。
    若未找到则返回 0。
    """
    unit_only = re.compile(r"^第[一二三四五六七八九十百千万]+单元$")
    for i, ln in enumerate(lines[:scan_limit]):
        c = line_compact(ln)
        if unit_only.match(c):
            return i
    return 0


def _toc_entry_display_label(e: dict[str, Any]) -> str:
    """目录条目的简短可读标签（用于 Markdown）。"""
    k = e.get("kind")
    if k == "lesson":
        n = e.get("number")
        t = e.get("title")
        star = "*" if e.get("optional_reading") else ""
        return f"{n}{star} {t}".strip() if t else str(n or "")
    if k == "sublesson":
        return str(e.get("title") or "")
    if k == "garden":
        return str(e.get("label") or "")
    if k == "reading_club":
        sub = e.get("subtitle")
        return f"快乐读书吧（{sub}）" if sub else "快乐读书吧"
    if k == "block_activity":
        blk, ti = e.get("block"), e.get("title")
        return f"{blk} {ti}".strip() if blk and ti else str(ti or blk or "")
    if k == "toc_belt":
        lb, ti = e.get("label"), e.get("title")
        return f"{lb} {ti}".strip() if lb and ti else str(ti or lb or "")
    return str(e.get("id") or k or "")


def _toc_entry_snapshot(e: dict[str, Any]) -> dict[str, Any]:
    """写入 JSON 的目录字段快照（避免整份条目过大）。"""
    keys = (
        "kind",
        "id",
        "number",
        "title",
        "label",
        "page",
        "optional_reading",
        "subtitle",
        "block",
        "unit_type",
        "unit_subtype",
        "group_label",
    )
    return {k: e.get(k) for k in keys}


def run_toc_text_chunk(
    book_code: str,
    full_text: str,
    toc_entries: list[dict[str, Any]],
    *,
    layout_source: str | None = None,
    toc_source: str | None = None,
    body_start_override: int | None = None,
    use_multiline: bool = True,
) -> dict[str, Any]:
    """
    执行分块，返回可 JSON 序列化的完整结果（含 enriched chunks）。
    """
    lines = full_text.splitlines()
    n = len(lines)
    if body_start_override is not None:
        body_start = max(0, min(body_start_override, max(0, n - 1)))
    else:
        body_start = suggest_body_start_line(lines)

    by_id: dict[str, dict[str, Any]] = {}
    for e in toc_entries:
        eid = e.get("id")
        if eid:
            by_id[str(eid)] = e

    spans = propose_chunk_line_spans(
        full_text,
        toc_entries,
        body_start_line=body_start,
        use_multiline=use_multiline,
    )

    chunks_out: list[dict[str, Any]] = []
    warnings: list[str] = []
    for sp in spans:
        eid = str(sp.get("id") or "")
        entry = by_id.get(eid, {})
        row: dict[str, Any] = {
            **sp,
            "toc_label": _toc_entry_display_label(entry),
            "toc_snapshot": _toc_entry_snapshot(entry) if entry else {},
        }
        sl = sp.get("start_line")
        el = sp.get("end_line")
        if isinstance(sl, int) and 0 <= sl < n:
            raw = lines[sl]
            row["start_line_text"] = raw[:200] + ("…" if len(raw) > 200 else "")
        if sp.get("ok") and isinstance(el, int) and isinstance(sl, int) and el > sl + 1:
            tail_ln = lines[el - 1] if el - 1 < n else ""
            row["chunk_tail_preview"] = tail_ln[:120] + ("…" if len(tail_ln) > 120 else "")
        if not sp.get("ok"):
            keys = sp.get("keys_tried") or []
            warnings.append(f"未命中锚点: {eid} {_toc_entry_display_label(entry)} keys={keys[:3]}")
        chunks_out.append(row)

    matched = sum(1 for c in chunks_out if c.get("ok"))
    return {
        "book_code": book_code,
        "extractor": "正文分块",
        "layout_source": layout_source,
        "toc_source": toc_source,
        "body_start_line": body_start,
        "body_start_line_note": "启发式：首个独占一行的「第×单元」；可用 body_start_override 覆盖",
        "line_count": n,
        "chunk_entry_count": len(chunks_out),
        "chunk_matched_count": matched,
        "chunk_unmatched_count": len(chunks_out) - matched,
        "chunks": chunks_out,
        "warnings": warnings,
    }


def render_toc_chunk_markdown(result: dict[str, Any]) -> str:
    """生成便于人工核对的分块 Markdown。"""
    book = str(result.get("book_code") or "")
    lines_out: list[str] = [
        f"# 正文分块核对：{book}",
        "",
        "由 **正文分块**（目录标题锚点）生成，行号为 `splitlines()` 的 0 基索引，区间为半开 `[start, end)`。",
        "",
    ]
    if ls := result.get("layout_source"):
        lines_out.append(f"- 版式文本：`{ls}`")
    if ts := result.get("toc_source"):
        lines_out.append(f"- 目录 JSON：`{ts}`")
    lines_out.append(f"- 正文起始行（启发式）：`{result.get('body_start_line', 0)}`")
    lines_out.append(
        f"- 锚点条目 {result.get('chunk_entry_count', 0)}，"
        f"命中 {result.get('chunk_matched_count', 0)}，"
        f"未命中 {result.get('chunk_unmatched_count', 0)}"
    )
    lines_out.extend(["", "---", ""])

    for i, ch in enumerate(result.get("chunks") or []):
        eid = ch.get("id", "")
        label = ch.get("toc_label") or eid
        head = f"### [{i + 1}] "
        if ch.get("ok"):
            head += f"`{eid}` · {label}"
        else:
            head += f"（未命中）`{eid}` · {label}"
        lines_out.append(head)
        if ch.get("ok"):
            sl, el = ch.get("start_line"), ch.get("end_line")
            mode = ch.get("match_mode") or "?"
            lines_out.append(f"- 行范围：`[{sl}, {el})` · 共 `{el - sl if isinstance(sl, int) and isinstance(el, int) else '?'}` 行 · 匹配：`{mode}`")
            if pg := (ch.get("toc_snapshot") or {}).get("page"):
                lines_out.append(f"- 目录页码：p.{pg}")
            if pv := ch.get("start_line_text"):
                lines_out.append(f"- 锚点行预览：`{pv}`")
        else:
            kt = ch.get("keys_tried") or []
            lines_out.append(f"- 尝试键：`{', '.join(str(x) for x in kt[:6])}{'…' if len(kt) > 6 else ''}`")
        lines_out.append("")

    if w := result.get("warnings"):
        lines_out.extend(["---", "", "## 问题摘要（须核对）", ""])
        for x in w:
            lines_out.append(f"- {x}")
        lines_out.append("")

    return "\n".join(lines_out)
