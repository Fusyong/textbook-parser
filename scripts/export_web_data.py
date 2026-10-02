"""
将 output/{batch}/ 下的识字表、写字表、词语表、正文分块与版式正文合并导出为
web/generated/data.js，供静态网页按「成套教材」切换使用。

- 标准库即可完成表数据与分块元数据；
- 组词用正文预分词列表（需 jieba）：
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

# 保证可从项目根直接运行脚本
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from textbook_parser.batch import (  # noqa: E402
    SLOT_CODES,
    SLOT_KEYWORDS,
    build_all_sets,
    discover_batch_ids,
    list_slots_in_batch,
    set_assembly_to_dict,
)


def _root() -> Path:
    return _ROOT


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_book_codes(out_dir: Path) -> list[str]:
    codes: set[str] = set()
    for pat in ("*_识字表.json", "*_写字表.json", "*_正文分块.json", "*_词语表.json", "*_目录.json"):
        for p in out_dir.glob(pat):
            stem = p.name
            if "_" not in stem:
                continue
            codes.add(stem.split("_", 1)[0])
    order = {c: i for i, c in enumerate(SLOT_CODES)}
    return sorted(codes, key=lambda c: order.get(c, 999))


def _discover_output_batches(root: Path) -> list[str]:
    """有解析产物的批次（与 material 批次求交，按日期升序）。"""
    out = root / "output"
    material_batches = discover_batch_ids(root)
    found: list[str] = []
    if out.is_dir():
        for p in out.iterdir():
            if p.is_dir() and p.name in set(material_batches):
                if _discover_book_codes(p):
                    found.append(p.name)
    # 保持 material 顺序
    return [b for b in material_batches if b in set(found)]


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
        return blk or t or str(e.get("id") or "")
    if k == "reading_club":
        t = str(e.get("title") or "").strip()
        st = str(e.get("subtitle") or "").strip()
        if t and st:
            return f"{t} · {st}"
        return t or st or str(e.get("id") or "")
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
    return [
        {"id": c["id"], "label": c["label"], "ok": c["ok"]}
        for c in chunks_with_text
    ]


def _is_pure_ascii_alpha_token(s: str) -> bool:
    return bool(s) and s.isascii() and s.isalpha()


def _is_pure_digit_token(s: str) -> bool:
    return bool(s) and all(ch.isdigit() for ch in s)


def _is_pure_punctuation_token(s: str) -> bool:
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


def _export_one_batch(
    root: Path,
    batch_id: str,
    jieba_cut,
    jieba_ok: bool,
) -> tuple[dict, list[str]]:
    """导出单批；返回 (batchPayload, warnings)。"""
    out_dir = root / "output" / batch_id
    warnings: list[str] = []
    books_meta: list[dict] = []
    char_by_book: dict[str, dict] = {}
    word_by_book: dict[str, dict] = {}
    chunks_meta_by_book: dict[str, list] = {}
    chunk_tokens_by_book: dict[str, list] = {}
    toc_by_book: dict[str, list] = {}

    for code in _discover_book_codes(out_dir):
        layout_path, title = _layout_path(root, out_dir, code)
        display_title = SLOT_KEYWORDS.get(code, title)
        books_meta.append(
            {
                "code": code,
                "title": display_title,
                "fileTitle": title,
            }
        )

        shizi = _load_json(out_dir / f"{code}_识字表.json")
        xiezi = _load_json(out_dir / f"{code}_写字表.json")
        ciyi = _load_json(out_dir / f"{code}_词语表.json")
        chunk_j = _load_json(out_dir / f"{code}_正文分块.json")
        toc_j = _load_json(out_dir / f"{code}_目录.json")
        toc_by_book[code] = _toc_entries_web(toc_j)
        if not toc_by_book[code]:
            warnings.append(f"{batch_id}/{code}: 缺少或空的 目录.json")

        char_by_book[code] = {
            "识字表": _char_rows(shizi),
            "写字表": _char_rows(xiezi),
        }
        word_by_book[code] = {"词语表": _word_rows(ciyi)}

        chunks_raw, w = _chunk_records(chunk_j, layout_path)
        for x in w:
            warnings.append(f"{batch_id}/{code}: {x}")

        chunks_meta_by_book[code] = _public_chunks_meta(chunks_raw)

        if jieba_ok and jieba_cut:
            chunk_tokens_by_book[code] = _tokenize_chunks(
                f"{batch_id}/{code}", chunks_raw, jieba_cut
            )
        else:
            chunk_tokens_by_book[code] = [[] for _ in chunks_raw]

    return {
        "id": batch_id,
        "books": books_meta,
        "tocByBook": toc_by_book,
        "charByBook": char_by_book,
        "wordByBook": word_by_book,
        "chunksByBook": chunks_meta_by_book,
        "chunkTokensByBook": chunk_tokens_by_book,
    }, warnings


def _inventory_from_batches(batch_payloads: dict[str, dict]) -> dict[str, set[str]]:
    inv: dict[str, set[str]] = {}
    for bid, payload in batch_payloads.items():
        codes = {b["code"] for b in payload.get("books") or [] if b.get("code")}
        inv[bid] = codes
    return inv


def _assemble_set_view(
    set_dict: dict,
    batch_payloads: dict[str, dict],
) -> dict:
    """
    将成套 slots 展平为与旧版兼容的视图字段：
    books / tocByBook / charByBook / … / wordFreq
    """
    books: list[dict] = []
    toc_by_book: dict[str, list] = {}
    char_by_book: dict[str, dict] = {}
    word_by_book: dict[str, dict] = {}
    chunks_by_book: dict[str, list] = {}
    chunk_tokens_by_book: dict[str, list] = {}
    sources: dict[str, dict] = {}

    for ref in set_dict.get("slots") or []:
        if not ref:
            continue
        bid = ref.get("batch")
        code = ref.get("code")
        if not bid or not code:
            continue
        bp = batch_payloads.get(bid) or {}
        # 书目元数据
        meta = next((b for b in (bp.get("books") or []) if b.get("code") == code), None)
        title = (meta or {}).get("title") or SLOT_KEYWORDS.get(code, code)
        books.append({"code": code, "title": title, "batch": bid})
        sources[code] = {"batch": bid}

        toc_by_book[code] = (bp.get("tocByBook") or {}).get(code) or []
        char_by_book[code] = (bp.get("charByBook") or {}).get(code) or {
            "识字表": [],
            "写字表": [],
        }
        word_by_book[code] = (bp.get("wordByBook") or {}).get(code) or {"词语表": []}
        chunks_by_book[code] = (bp.get("chunksByBook") or {}).get(code) or []
        chunk_tokens_by_book[code] = (bp.get("chunkTokensByBook") or {}).get(code) or []

    word_freq = _build_word_freq(chunk_tokens_by_book, word_by_book)

    return {
        "books": books,
        "tocByBook": toc_by_book,
        "charByBook": char_by_book,
        "wordByBook": word_by_book,
        "chunksByBook": chunks_by_book,
        "chunkTokensByBook": chunk_tokens_by_book,
        "wordFreq": word_freq,
        "bookSources": sources,
    }


def build_payload(root: Path) -> dict:
    try:
        import jieba

        jieba_cut = lambda s: list(jieba.cut(s, cut_all=False))
        jieba_ok = True
    except ImportError:
        jieba_cut = None
        jieba_ok = False

    all_warnings: list[str] = []
    if not jieba_ok:
        all_warnings.append(
            "未安装 jieba，已跳过正文预分词（chunkTokensByBook 将为空列表）；"
            "请执行: pip install jieba 或 pip install -e \".[web]\" 后重新导出。",
        )

    batch_ids = _discover_output_batches(root)
    if not batch_ids:
        raise FileNotFoundError(
            f"未在 {root / 'output'} 下找到任何批次解析结果（output/YYYY-MM…/）"
        )

    # 成套错位按 material 全部批次回溯；界面锚点仅最新一批（见 build_all_sets）
    material_batches = discover_batch_ids(root)
    if not material_batches:
        material_batches = list(batch_ids)

    batch_payloads: dict[str, dict] = {}
    batches_meta: list[dict] = []
    for bid in batch_ids:
        payload, warns = _export_one_batch(root, bid, jieba_cut, jieba_ok)
        batch_payloads[bid] = payload
        batches_meta.append({"id": bid, "label": bid})
        all_warnings.extend(warns)

    # 拼装清单以 material 为准（避免 output 残留错册污染错位）
    inventory: dict[str, set[str]] = {
        b: set(list_slots_in_batch(root, b)) for b in material_batches
    }

    latest_material = material_batches[-1]
    assemblies = build_all_sets(
        root,
        material_batches,
        inventory=inventory,
        anchor_batch=latest_material,
    )

    sets_out: list[dict] = []
    for asm in assemblies:
        sd = set_assembly_to_dict(asm)
        view = _assemble_set_view(sd, batch_payloads)
        # 槽位有 material 但无 output 时提示
        for ref in sd.get("slots") or []:
            if not ref:
                continue
            bid, code = ref.get("batch"), ref.get("code")
            if bid and code and bid not in batch_payloads:
                all_warnings.append(
                    f"成套 {sd['id']}: {code} 依赖批次 {bid}，但尚无 output/{bid}/，请先解析该批"
                )
            elif bid and code and code not in {
                b["code"] for b in (batch_payloads.get(bid) or {}).get("books") or []
            }:
                all_warnings.append(
                    f"成套 {sd['id']}: {bid}/{code} 缺少解析产物"
                )
        sd["view"] = view
        sets_out.append(sd)

    # 默认套：最新一批中学习序列第一册（一年级）
    default_set_id = sets_out[0]["id"] if sets_out else None
    latest_codes = [c for c in SLOT_CODES if c in inventory.get(latest_material, set())]
    if latest_codes:
        want = f"{latest_material}/{latest_codes[0]}"
        if any(s["id"] == want for s in sets_out):
            default_set_id = want
    # 兼容旧前端：顶层仍提供默认套的展平字段
    default_view = next(
        (s["view"] for s in sets_out if s["id"] == default_set_id),
        sets_out[-1]["view"] if sets_out else {},
    )

    return {
        "version": 9,
        "batches": batches_meta,
        "booksByBatch": {
            bid: {
                "books": batch_payloads[bid]["books"],
                "tocByBook": batch_payloads[bid]["tocByBook"],
                "charByBook": batch_payloads[bid]["charByBook"],
                "wordByBook": batch_payloads[bid]["wordByBook"],
                "chunksByBook": batch_payloads[bid]["chunksByBook"],
                "chunkTokensByBook": batch_payloads[bid]["chunkTokensByBook"],
            }
            for bid in batch_ids
        },
        "sets": sets_out,
        "defaultSetId": default_set_id,
        # 旧字段 = 默认套视图（首屏无需选套也能用）
        "books": default_view.get("books") or [],
        "tocByBook": default_view.get("tocByBook") or {},
        "charByBook": default_view.get("charByBook") or {},
        "wordByBook": default_view.get("wordByBook") or {},
        "chunksByBook": default_view.get("chunksByBook") or {},
        "chunkTokensByBook": default_view.get("chunkTokensByBook") or {},
        "wordFreq": default_view.get("wordFreq") or {},
        "exportWarnings": all_warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="导出静态网页用 data.js（多批次成套）")
    ap.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出路径（默认 web/generated/data.js）",
    )
    args = ap.parse_args()
    root = _root()
    dest = (args.output or (root / "web" / "generated" / "data.js")).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        payload = build_payload(root)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    js = (
        "// AUTO-GENERATED by scripts/export_web_data.py — 请勿手改\n"
        "window.TEXTBOOK_WEB_DATA = "
        + json.dumps(payload, ensure_ascii=False)
        + ";\n"
    )
    dest.write_text(js, encoding="utf-8")

    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"已写入: {dest}（约 {size_mb:.2f} MB）")
    print(
        f"批次 {len(payload.get('batches') or [])}，"
        f"成套 {len(payload.get('sets') or [])}，"
        f"默认套 {payload.get('defaultSetId')}"
    )
    warns = payload.get("exportWarnings") or []
    if warns:
        print("提示:", file=sys.stderr)
        for w in warns[:20]:
            print(f"  - {w}", file=sys.stderr)
        if len(warns) > 20:
            print(f"  …共 {len(warns)} 条", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
