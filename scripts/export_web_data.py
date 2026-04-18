"""
将 output/ 下的识字表、写字表、词语表、正文分块与版式正文合并导出为
web/generated/data.js，供静态网页使用。

- 标准库即可完成表数据与分块元数据；
- 组词用正文预分词列表 chunkTokensByBook（与分块一一对齐，需安装 jieba；
  丢弃仅 ASCII 字母、仅数字、仅标点（含全角/半角）的词形，各分块内去重后按 Unicode 排序）：
    pip install -e ".[web]"
  或: pip install jieba

用法（在项目根目录）:
  python scripts/export_web_data.py
  python scripts/export_web_data.py --output web/generated/data.js
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_book_codes(out_dir: Path) -> list[str]:
    codes: set[str] = set()
    for pat in ("*_识字表.json", "*_写字表.json", "*_正文分块.json", "*_词语表.json"):
        for p in out_dir.glob(pat):
            stem = p.name
            if "_" not in stem:
                continue
            codes.add(stem.split("_", 1)[0])
    return sorted(codes)


def _layout_path(root: Path, out_dir: Path, book_code: str) -> tuple[Path | None, str]:
    chunk = _load_json(out_dir / f"{book_code}_正文分块.json")
    if chunk:
        rel = chunk.get("layout_source")
        if isinstance(rel, str) and rel.strip():
            normalized = rel.replace("\\", "/")
            path = (root / normalized).resolve()
            title = Path(normalized).stem
            return path, title
    return None, book_code


def _row_label(row: dict) -> str:
    u = row.get("unit") or {}
    if isinstance(u, dict):
        lab = u.get("label")
        if lab:
            return str(lab)
        t = u.get("title")
        if t:
            return str(t)
    ls = row.get("lesson")
    gs = row.get("garden")
    if gs:
        return f"园地{gs}"
    if ls is not None:
        return f"课{ls}"
    return ""


def _unit_toc_id(row: dict) -> str | None:
    u = row.get("unit") or {}
    if not isinstance(u, dict):
        return None
    tid = u.get("toc_id")
    return str(tid) if tid else None


def _toc_entry_label(e: dict) -> str:
    """与网页下拉框展示一致的目录项短标签。"""
    k = e.get("kind")
    if k == "lesson":
        num = str(e.get("number") or "").strip()
        t = str(e.get("title") or "").strip()
        s = f"{num} {t}".strip()
        return s or str(e.get("id") or "")
    if k == "sublesson":
        return str(e.get("title") or "").strip() or str(e.get("id") or "")
    if k in ("garden", "section"):
        return str(e.get("label") or "").strip() or str(e.get("id") or "")
    if k == "block_activity":
        blk = str(e.get("block") or "").strip()
        t = str(e.get("title") or "").strip()
        if blk and t:
            return f"{blk} · {t}"
        return (blk or t or str(e.get("id") or ""))
    if k == "reading_club":
        t = str(e.get("title") or "").strip()
        st = str(e.get("subtitle") or "").strip()
        if t and st:
            return f"{t} · {st}"
        return (t or st or str(e.get("id") or ""))
    if k == "toc_belt":
        return str(e.get("label") or e.get("title") or "").strip() or str(e.get("id") or "")
    return str(e.get("label") or e.get("title") or e.get("id") or "")


def _toc_entries_web(toc_json: dict | None) -> list[dict]:
    if not toc_json:
        return []
    raw = toc_json.get("entries") or []
    out: list[dict] = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        eid = e.get("id")
        if not eid:
            continue
        out.append(
            {
                "id": str(eid),
                "label": _toc_entry_label(e),
                "kind": str(e.get("kind") or ""),
            }
        )
    return out


def _char_rows(table_json: dict | None) -> list[dict]:
    if not table_json:
        return []
    rows = table_json.get("rows") or []
    out: list[dict] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        char_items: list[dict[str, str]] = []
        for item in row.get("chars") or []:
            if not isinstance(item, dict) or not item.get("char"):
                continue
            ch = str(item["char"])
            py_raw = item.get("pinyin")
            py = str(py_raw).strip() if py_raw else ""
            char_items.append({"char": ch, "pinyin": py})
        chars = [x["char"] for x in char_items]
        out.append(
            {
                "i": i,
                "label": _row_label(row),
                "chars": chars,
                "charItems": char_items,
                "tocId": _unit_toc_id(row),
            }
        )
    return out


def _word_items_from_row(row: dict) -> list[dict[str, str]]:
    """词语表行：仅使用 JSON 中已有的拼音（若有）；否则 pinyin 为空字符串。"""
    raw = row.get("words") or []
    out: list[dict[str, str]] = []
    for w in raw:
        if isinstance(w, dict):
            word = str(w.get("word") or w.get("w") or "").strip()
            py_raw = w.get("pinyin")
            py = str(py_raw).strip() if py_raw else ""
            if word:
                out.append({"word": word, "pinyin": py})
            continue
        s = str(w).strip()
        if s:
            out.append({"word": s, "pinyin": ""})
    return out


def _word_rows(word_json: dict | None) -> list[dict]:
    if not word_json:
        return []
    rows = word_json.get("rows") or []
    out: list[dict] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        word_items = _word_items_from_row(row)
        words = [x["word"] for x in word_items]
        out.append(
            {
                "i": i,
                "label": _row_label(row),
                "words": words,
                "wordItems": word_items,
                "tocId": _unit_toc_id(row),
            }
        )
    return out


def _chunk_records(
    chunk_json: dict | None,
    layout_path: Path | None,
) -> tuple[list[dict], list[str]]:
    """返回带 text 的完整分块（仅导出流程内部使用），warnings 供写入 payload。"""
    warnings: list[str] = []
    if not chunk_json:
        return [], warnings
    if not layout_path or not layout_path.is_file():
        warnings.append(
            f"缺少版式正文，跳过分块正文: {layout_path or '(无 layout_source)'}",
        )
        return [], warnings
    lines = layout_path.read_text(encoding="utf-8").splitlines()
    n = len(lines)
    chunks_out: list[dict] = []
    for ch in chunk_json.get("chunks") or []:
        if not isinstance(ch, dict):
            continue
        sl = ch.get("start_line")
        el = ch.get("end_line")
        cid = str(ch.get("id") or "")
        label = str(ch.get("toc_label") or cid)
        ok = bool(ch.get("ok"))
        text = ""
        if isinstance(sl, int) and isinstance(el, int) and 0 <= sl < n and el > sl:
            text = "\n".join(lines[sl:el])
        chunks_out.append(
            {
                "id": cid,
                "label": label,
                "ok": ok,
                "text": text,
            }
        )
    return chunks_out, warnings


def _public_chunks_meta(chunks_with_text: list[dict]) -> list[dict]:
    """写入 JS：不含正文，仅保留检索过滤所需字段。"""
    return [
        {"id": c["id"], "label": c["label"], "ok": c["ok"]}
        for c in chunks_with_text
    ]


def _is_pure_ascii_alpha_token(s: str) -> bool:
    """仅由 ASCII 拉丁字母构成（无数字、空格、符号）。"""
    return bool(s) and s.isascii() and s.isalpha()


def _is_pure_digit_token(s: str) -> bool:
    """仅由 Unicode 十进制数字字符构成（如 12、３４）。"""
    return bool(s) and all(ch.isdigit() for ch in s)


def _is_pure_punctuation_token(s: str) -> bool:
    """仅由标点构成（Unicode 大类 P：含中文全角标点、ASCII 半角标点等）。"""
    if not s:
        return False
    return all(unicodedata.category(ch).startswith("P") for ch in s)


def _keep_segment_token(tok: str) -> bool:
    if not tok:
        return False
    if _is_pure_ascii_alpha_token(tok):
        return False
    if _is_pure_digit_token(tok):
        return False
    if _is_pure_punctuation_token(tok):
        return False
    return True


def _tokenize_chunks(
    book_code: str,
    chunks: list[dict],
    jieba_cut,
) -> list[list[str]]:
    """与 chunks 等长的分词结果列表；无正文则为空列表。

    各分块：去掉纯英文（ASCII 字母）、纯数字、纯标点（全角/半角）词形，去重后
    按 Unicode 码点排序（不保留原文出现顺序）。
    """
    out: list[list[str]] = []
    for ci, ch in enumerate(chunks):
        text = (ch.get("text") or "").strip()
        if not text:
            out.append([])
            continue
        try:
            raw = jieba_cut(text)
        except Exception as e:
            sys.stderr.write(f"{book_code} 分块 {ci} 分词失败: {e}\n")
            out.append([])
            continue
        kept: set[str] = set()
        for t in raw:
            tok = str(t).strip()
            if not _keep_segment_token(tok):
                continue
            kept.add(tok)
        out.append(sorted(kept))
    return out


def _build_word_freq(
    chunk_tokens_by_book: dict[str, list],
    word_by_book: dict[str, dict],
) -> dict[str, int]:
    """全套教材：正文分词 + 词语表词形，出现次数合计（词频）。"""
    freq: dict[str, int] = defaultdict(int)
    for _code, rows in chunk_tokens_by_book.items():
        for row in rows:
            if not isinstance(row, list):
                continue
            for tok in row:
                t = str(tok).strip()
                if t:
                    freq[t] += 1
    for _code, pack in word_by_book.items():
        if not isinstance(pack, dict):
            continue
        for wrow in pack.get("词语表") or []:
            if not isinstance(wrow, dict):
                continue
            for w in wrow.get("words") or []:
                s = str(w).strip()
                if s:
                    freq[s] += 1
    return dict(freq)


def build_payload(root: Path, out_dir: Path) -> dict:
    try:
        import jieba

        jieba_cut = lambda s: list(jieba.cut(s, cut_all=False))
        jieba_ok = True
    except ImportError:
        jieba_cut = None
        jieba_ok = False

    books_meta: list[dict] = []
    char_by_book: dict[str, dict] = {}
    word_by_book: dict[str, dict] = {}
    chunks_meta_by_book: dict[str, list] = {}
    chunk_tokens_by_book: dict[str, list] = {}
    toc_by_book: dict[str, list] = {}
    all_warnings: list[str] = []

    if not jieba_ok:
        all_warnings.append(
            "未安装 jieba，已跳过正文预分词（chunkTokensByBook 将为空列表）；请执行: pip install jieba 或 pip install -e \".[web]\" 后重新导出。",
        )

    for code in _discover_book_codes(out_dir):
        layout_path, title = _layout_path(root, out_dir, code)
        books_meta.append({"code": code, "title": title})

        shizi = _load_json(out_dir / f"{code}_识字表.json")
        xiezi = _load_json(out_dir / f"{code}_写字表.json")
        ciyi = _load_json(out_dir / f"{code}_词语表.json")
        chunk_j = _load_json(out_dir / f"{code}_正文分块.json")
        toc_j = _load_json(out_dir / f"{code}_目录.json")
        toc_by_book[code] = _toc_entries_web(toc_j)
        if not toc_by_book[code]:
            all_warnings.append(f"{code}: 缺少或空的 目录.json，无法按「课」筛选范围")

        char_by_book[code] = {
            "识字表": _char_rows(shizi),
            "写字表": _char_rows(xiezi),
        }
        word_rows = _word_rows(ciyi)
        word_by_book[code] = {"词语表": word_rows}

        chunks_raw, w = _chunk_records(chunk_j, layout_path)
        for x in w:
            all_warnings.append(f"{code}: {x}")

        chunks_meta_by_book[code] = _public_chunks_meta(chunks_raw)

        if jieba_ok and jieba_cut:
            chunk_tokens_by_book[code] = _tokenize_chunks(code, chunks_raw, jieba_cut)
        else:
            chunk_tokens_by_book[code] = [[] for _ in chunks_raw]

    word_freq = _build_word_freq(chunk_tokens_by_book, word_by_book)

    return {
        "version": 8,
        "books": books_meta,
        "tocByBook": toc_by_book,
        "charByBook": char_by_book,
        "wordByBook": word_by_book,
        "chunksByBook": chunks_meta_by_book,
        "chunkTokensByBook": chunk_tokens_by_book,
        "wordFreq": word_freq,
        "exportWarnings": all_warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="导出静态网页用 data.js")
    ap.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出路径（默认 web/generated/data.js）",
    )
    args = ap.parse_args()
    root = _root()
    out_dir = root / "output"
    dest = (args.output or (root / "web" / "generated" / "data.js")).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    if not out_dir.is_dir():
        print(f"缺少目录: {out_dir}", file=sys.stderr)
        return 1

    payload = build_payload(root, out_dir)
    js = (
        "// AUTO-GENERATED by scripts/export_web_data.py — 请勿手改\n"
        "window.TEXTBOOK_WEB_DATA = "
        + json.dumps(payload, ensure_ascii=False)
        + ";\n"
    )
    dest.write_text(js, encoding="utf-8")

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"已写入: {dest}（约 {size_mb:.2f} MB）")
    warns = payload.get("exportWarnings") or []
    if warns:
        print("提示:", file=sys.stderr)
        for w in warns:
            print(f"  - {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
