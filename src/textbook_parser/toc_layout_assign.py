"""
将识字表 / 写字表 / 词语表的锚点行与 layout_toc 产出的目录 JSON（entries）对齐。

匹配策略（在真实册别数据上归纳）：
- 跳过 kind 为 section 的分组头，不参与表内学习单位序列。
- 课文行：表内 section（识字/阅读）与目录 unit_subtype 或 group_label（·识字 / ·阅读 / ·汉语拼音）
  一致；课号与目录 lesson.number 相同；自上一匹配位置起向前扫描，可自动跳过表中未收录的目录项。
- 语文园地：有园地序号时与目录 label 的紧凑串一致（语文园地一…）；无序号（版式仅「语文园地」）
  则取扫描方向上第一条 strand 相符的 garden 条目。
- 词语表中园地行以 lesson == \"语文园地\" 标识，按 garden 条目匹配。
"""

from __future__ import annotations

import html
import sys
from typing import Any

from .extractors.layout_toc import _format_toc_entry_markdown_line


def toc_entries_from_layout_result(data: dict[str, Any]) -> list[dict[str, Any]]:
    """从 目录.json 顶层对象取出 entries 列表。"""
    raw = data.get("entries")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def entry_strand(e: dict[str, Any]) -> str | None:
    """推断目录条目所属的「识字 / 阅读 / 汉语拼音」栏，与表内 section 对应。"""
    us = e.get("unit_subtype")
    if isinstance(us, str) and us.strip():
        s = us.strip()
        if s in ("识字", "阅读", "汉语拼音"):
            return s
    gl = str(e.get("group_label") or "")
    if "·汉语拼音" in gl or gl.endswith("汉语拼音"):
        return "汉语拼音"
    if "·识字" in gl or gl.endswith("识字"):
        return "识字"
    if "·阅读" in gl or gl.endswith("阅读"):
        return "阅读"
    return None


def strand_compatible(table_section: str | None, e: dict[str, Any]) -> bool:
    if not table_section:
        return True
    es = entry_strand(e)
    if es is None:
        return True
    if table_section == "阅读":
        return es == "阅读"
    if table_section == "识字":
        return es in ("识字", "汉语拼音")
    return True


def _lesson_number_match(entry: dict[str, Any], lesson_s: str) -> bool:
    num = entry.get("number")
    if num is None:
        return False
    return str(num).strip() == str(lesson_s).strip()


def layout_entry_matches_char_row(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    from .extractors.char_tables import compact_for_match

    k = entry.get("kind")
    sec = row.get("section")

    garden = row.get("garden")
    if garden is not None:
        if k != "garden":
            return False
        if not strand_compatible(sec, entry):
            return False
        label_c = compact_for_match(str(entry.get("label") or ""))
        if garden == "":
            return label_c.startswith("语文园地")
        return label_c == compact_for_match(f"语文园地{garden}")

    lesson = row.get("lesson")
    if lesson is not None:
        if k != "lesson":
            return False
        if not strand_compatible(sec, entry):
            return False
        return _lesson_number_match(entry, str(lesson))

    return False


def layout_entry_matches_word_row(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    k = entry.get("kind")
    sec = row.get("section")
    les = row.get("lesson")
    if les is None:
        return False
    ls = str(les).strip()
    if ls == "语文园地":
        if k != "garden":
            return False
        return strand_compatible(sec, entry)
    if k != "lesson":
        return False
    if not strand_compatible(sec, entry):
        return False
    return _lesson_number_match(entry, ls)


def build_unit_from_layout_entry(entry: dict[str, Any], seq: int) -> dict[str, Any]:
    """生成写入表行 unit 字段的结构（含目录 id），并尽量兼容原 parse_toc_entry 形态。"""
    from .extractors.char_tables import compact_for_match

    k = entry.get("kind")
    tid = entry.get("id")
    if k == "lesson":
        num = str(entry.get("number") or "").strip()
        title = str(entry.get("title") or "").strip()
        sub = (entry.get("sublesson_title") or "").strip()
        label = f"{num} {title}".strip()
        if sub:
            label = f"{label}（{sub}）" if label else f"（{sub}）"
        return {
            "toc_id": tid,
            "toc_kind": k,
            "toc_index": seq,
            "unit_type": "lesson",
            "lesson": num or None,
            "garden_cn": None,
            "title": title or None,
            "label": label or str(tid or ""),
        }
    if k == "garden":
        lb = str(entry.get("label") or "").strip()
        c = compact_for_match(lb)
        gn = c.removeprefix("语文园地") if c.startswith("语文园地") else ""
        return {
            "toc_id": tid,
            "toc_kind": k,
            "toc_index": seq,
            "unit_type": "garden",
            "lesson": None,
            "garden_cn": gn or None,
            "title": None,
            "label": lb,
        }
    if k == "reading_club":
        sub = (entry.get("subtitle") or "").strip()
        st = (entry.get("sublesson_title") or "").strip()
        tail = sub or st
        label = f"快乐读书吧 {tail}".strip() if tail else "快乐读书吧"
        return {
            "toc_id": tid,
            "toc_kind": k,
            "toc_index": seq,
            "unit_type": "reading_club",
            "lesson": None,
            "garden_cn": None,
            "title": tail or None,
            "label": label,
        }
    if k == "block_activity":
        blk = str(entry.get("block") or "").strip()
        ti = str(entry.get("title") or "").strip()
        label = f"{blk} {ti}".strip()
        return {
            "toc_id": tid,
            "toc_kind": k,
            "toc_index": seq,
            "unit_type": "block",
            "lesson": None,
            "garden_cn": None,
            "title": ti or None,
            "label": label,
        }
    if k == "toc_belt":
        lb = str(entry.get("label") or "").strip()
        ti = (entry.get("title") or "").strip()
        label = f"{lb}{ti}" if ti else lb
        return {
            "toc_id": tid,
            "toc_kind": k,
            "toc_index": seq,
            "unit_type": "belt",
            "lesson": None,
            "garden_cn": None,
            "title": ti or None,
            "label": label,
        }
    if k == "sublesson":
        ti = str(entry.get("title") or "").strip()
        return {
            "toc_id": tid,
            "toc_kind": k,
            "toc_index": seq,
            "unit_type": "sublesson",
            "lesson": None,
            "garden_cn": None,
            "title": ti or None,
            "label": ti,
        }
    return {
        "toc_id": tid,
        "toc_kind": k,
        "toc_index": seq,
        "unit_type": str(k or "unknown"),
        "lesson": None,
        "garden_cn": None,
        "title": None,
        "label": str(tid or k or ""),
    }


def assign_units_from_layout_toc(
    rows: list[dict[str, Any]],
    toc_entries: list[dict[str, Any]],
    *,
    log_prefix: str,
    word_table: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not toc_entries:
        warnings.append("目录 entries 为空，无法对齐")
        return rows, warnings

    match_fn = layout_entry_matches_word_row if word_table else layout_entry_matches_char_row

    def is_primary(row: dict[str, Any]) -> bool:
        if "toc_anchor" in row:
            return bool(row["toc_anchor"])
        return row.get("lesson") is not None or row.get("garden") is not None

    out: list[dict[str, Any]] = []
    prev_unit: dict[str, Any] | None = None
    cursor = 0
    seq = 0

    for row in rows:
        if not is_primary(row):
            u = prev_unit
            if u is None:
                msg = "续行但尚无上一单元的目录对应"
                warnings.append(msg)
                print(f"[{log_prefix} TOC] {msg}\n  行: {row.get('hanzi_line', row.get('lines', ''))!r}", file=sys.stderr)
            out.append({**row, "unit": u})
            continue

        found: int | None = None
        j = cursor
        while j < len(toc_entries):
            e = toc_entries[j]
            if e.get("kind") == "section":
                j += 1
                continue
            if match_fn(e, row):
                found = j
                break
            j += 1

        if found is None:
            ref = row.get("hanzi_line", row.get("lines", ""))
            msg = f"未在目录中找到与锚点行匹配的学习单位（自条目 {cursor} 起）: {ref!r}"
            warnings.append(msg)
            print(f"[{log_prefix} TOC] {msg}", file=sys.stderr)
            unit = None
            prev_unit = None
        else:
            unit = build_unit_from_layout_entry(toc_entries[found], seq)
            seq += 1
            cursor = found + 1
            prev_unit = unit

        out.append({**row, "unit": unit})

    return out, warnings


def _is_primary_row(row: dict[str, Any]) -> bool:
    if "toc_anchor" in row:
        return bool(row["toc_anchor"])
    return row.get("lesson") is not None or row.get("garden") is not None


def toc_alignment_report_layout(
    rows: list[dict[str, Any]],
    log_prefix: str,
) -> dict[str, Any]:
    n_primary = sum(1 for r in rows if _is_primary_row(r))
    n_assigned = sum(1 for r in rows if _is_primary_row(r) and r.get("unit") is not None)
    ok = n_primary == n_assigned and n_primary > 0
    if n_primary == 0:
        detail = "无锚点数据组"
    elif ok:
        detail = "锚点全部匹配到目录"
    else:
        detail = f"锚点 {n_primary} 条，成功绑定目录 {n_assigned} 条"
    print(
        f"[{log_prefix}] 目录 JSON 对齐 — {detail}",
        flush=True,
    )
    return {
        "toc_anchor_group_count": n_primary,
        "toc_assigned_count": n_assigned,
        "toc_layout_match_ok": ok,
    }


def toc_catalog_summary(toc_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """便于 JSON 内携带的目录学习单位摘要（不含 section）。"""
    out: list[dict[str, Any]] = []
    for e in toc_entries:
        if e.get("kind") == "section":
            continue
        eid = e.get("id")
        out.append(
            {
                "id": eid,
                "kind": e.get("kind"),
                "line": _format_toc_entry_markdown_line(e).replace("**", "").replace("`", ""),
            }
        )
    return out


_MD_CHAR_FONT = "font-size:18pt"


def _layout_pinyin_line_display(raw: str) -> str:
    """将 pinyin_line 中版式编码音节转为带调空格分词串（与 char_tables 一致）。"""
    from .extractors.char_tables import layout_pinyin_to_tone_marked

    parts = [w for w in raw.split() if w]
    return " ".join(layout_pinyin_to_tone_marked(t) for t in parts)


def _markdown_char_han_pinyin_blocks(row: dict[str, Any]) -> list[str]:
    """识字表/写字表：生字一行、拼音一行，均为 18pt（HTML，便于常见 Markdown 预览器渲染）。"""
    chars = row.get("chars")
    if not isinstance(chars, list) or not chars:
        return []
    han_parts: list[str] = []
    py_tokens: list[str] = []
    for c in chars:
        if isinstance(c, dict):
            han_parts.append(str(c.get("char") or ""))
            p = c.get("pinyin")
            py_tokens.append(p.strip() if isinstance(p, str) and p.strip() else "")
        else:
            han_parts.append(str(c))
            py_tokens.append("")
    han_s = " ".join(han_parts)
    filled = sum(1 for t in py_tokens if t)
    py_s = " ".join(t for t in py_tokens if t)
    pl_raw = row.get("pinyin_line")
    pl_ok = isinstance(pl_raw, str) and pl_raw.strip()
    if filled < len(chars) and pl_ok:
        py_s = _layout_pinyin_line_display(pl_raw.strip())
    elif not py_s.strip() and pl_ok:
        py_s = _layout_pinyin_line_display(pl_raw.strip())
    sty = _MD_CHAR_FONT
    out = [f'<div style="{sty}">{html.escape(han_s)}</div>']
    if py_s.strip():
        out.append(f'<div style="{sty}">{html.escape(py_s)}</div>')
    return out


def _markdown_words_line_block(row: dict[str, Any]) -> list[str]:
    """词语表：与识字表同版式，仅一行 18pt 词语（无拼音数据时不输出第二行）。"""
    words = row.get("words")
    if not isinstance(words, list) or not words:
        return []
    text = " ".join(str(w).strip() for w in words if str(w).strip())
    if not text:
        return []
    sty = _MD_CHAR_FONT
    return [f'<div style="{sty}">{html.escape(text)}</div>']


def render_table_unit_markdown(result: dict[str, Any], *, table_label: str) -> str:
    """根据提取结果生成便于人工核对的 Markdown（按行展示目录 id 与生字/词语）。"""
    book = str(result.get("book_code") or "")
    ext = str(result.get("extractor") or table_label)
    rows = list(result.get("rows") or [])
    src = result.get("toc_layout_source")
    lines: list[str] = [
        f"# {table_label}核对：{book}",
        "",
        f"由 **{ext}** 与目录 JSON 对齐生成；请与教材 PDF 核对。",
        "",
    ]
    if src:
        lines.append(f"- 目录来源：`{src}`")
    if ta := result.get("toc_alignment"):
        lines.append(
            f"- 锚点组数 {ta.get('toc_anchor_group_count', '?')}，"
            f"已绑定 {ta.get('toc_assigned_count', '?')}，"
            f"对齐：{'是' if ta.get('toc_layout_match_ok') else '否'}"
        )
    lines.extend(["", "---", ""])

    for i, row in enumerate(rows):
        unit = row.get("unit")
        uid = (unit or {}).get("toc_id") if unit else None
        ulab = (unit or {}).get("label") if unit else None
        head = f"### [{i + 1}] "
        if uid:
            head += f"`{uid}`"
        else:
            head += "（未绑定目录）"
        if ulab:
            head += f" · {ulab}"
        lines.append(head)

        chars = row.get("chars")
        words = row.get("words")
        if isinstance(chars, list) and chars:
            lines.extend(_markdown_char_han_pinyin_blocks(row))
        elif isinstance(words, list) and words:
            lines.extend(_markdown_words_line_block(row))
        else:
            meta_bits: list[str] = []
            sec = row.get("section")
            if sec:
                meta_bits.append(f"小节 {sec}")
            if row.get("lesson") is not None:
                meta_bits.append(f"课号 {row.get('lesson')}")
            if row.get("garden") is not None and row.get("garden") != "":
                meta_bits.append(f"园地 {row.get('garden')}")
            if meta_bits:
                lines.append("- " + " · ".join(meta_bits))
            hl = row.get("hanzi_line")
            if isinstance(hl, str) and hl.strip():
                lines.append(
                    f"- 汉字行：`{hl.strip()[:120]}{'…' if len(hl.strip()) > 120 else ''}`"
                )
            elif row.get("lines"):
                ln = row["lines"]
                if isinstance(ln, list) and ln:
                    preview = str(ln[0]).strip()[:120]
                    lines.append(
                        f"- 首行：`{preview}{'…' if len(str(ln[0]).strip()) > 120 else ''}`"
                    )
        lines.append("")

    if tw := result.get("toc_warnings"):
        lines.append("---")
        lines.append("")
        lines.append("## 对齐警告")
        for w in tw:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)
