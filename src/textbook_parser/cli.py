from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import (
    effective_book_config,
    iter_book_codes,
    load_config,
    project_root_from_config,
)
from .extractors import get_extractor
from .extractors.layout_toc import render_layout_toc_markdown
from .pdftotext import run_pdftotext
from .run_logging import install_run_logging
from .toc_csv import toc_units_for_column
from .toc_layout_assign import render_table_unit_markdown, toc_entries_from_layout_result
from .toc_text_chunk import render_toc_chunk_markdown, run_toc_text_chunk

_MODULES_USING_TOC_LAYOUT_JSON = frozenset({"char_tables", "word_table"})


def _log_header_lines(
    command: str,
    *,
    book_code: str,
    log_path: Path,
    extra: dict[str, str] | None = None,
) -> list[str]:
    lines = [
        f"# textbook-parser {command}",
        f"# time: {datetime.now().isoformat(timespec='seconds')}",
        f"# argv: {' '.join(sys.argv)}",
        f"# book_code: {book_code}",
        f"# log_file: {log_path}",
        "# 以下 stdout/stderr 均写入本日志（含警告、错误与提取器提示）。",
    ]
    if extra:
        for k, v in extra.items():
            lines.append(f"# {k}: {v}")
    lines.append("")
    return [ln + "\n" for ln in lines]


def _project_root_for_book_mode(args: argparse.Namespace) -> Path:
    root = Path(args.project_root).resolve() if args.project_root else Path.cwd()
    if not (root / "configs" / "books.yaml").is_file():
        print(
            f"未找到 {root / 'configs' / 'books.yaml'}；请用 --project-root 指定项目根",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return root


def _load_effective_cfg(args: argparse.Namespace) -> tuple[Path, dict[str, Any], Path | None]:
    """
    返回 (项目根, 已 resolve 的配置, 单书 YAML 路径或 None)。
    配置 = defaults.yaml 深度合并单册 YAML（若有），再套用 books.yaml。
    """
    if getattr(args, "book", None):
        root = _project_root_for_book_mode(args)
        cfg = effective_book_config(root, str(args.book).strip(), file_overlay=None)
        return root, cfg, None
    cfg_path = Path(args.config).resolve()
    root = project_root_from_config(cfg_path)
    overlay = load_config(cfg_path)
    code = overlay.get("book_code")
    if not code:
        print("YAML 配置须包含 book_code", file=sys.stderr)
        raise SystemExit(1)
    cfg = effective_book_config(root, str(code), file_overlay=overlay)
    return root, cfg, cfg_path


def _cmd_convert(args: argparse.Namespace) -> int:
    root, cfg, cfg_path = _load_effective_cfg(args)
    book_code = str(cfg["book_code"])
    out = (root / cfg["layout_text"]).resolve()
    log_path = out.parent / f"{out.stem}.convert.log"
    restore = install_run_logging(
        log_path,
        header_lines=_log_header_lines(
            "convert",
            book_code=book_code,
            log_path=log_path,
            extra={"config": str(cfg_path) if cfg_path else "(--book)", "project_root": str(root)},
        ),
    )
    try:
        pdf = root / cfg["source_pdf"]
        pt = cfg.get("pdftotext") or {}
        run_pdftotext(
            pdf,
            out,
            enc=str(pt.get("enc", "UTF-8")),
            layout=bool(pt.get("layout", True)),
            extra_args=list(pt.get("extra_args") or []),
        )
        print(f"已写入: {out}")
        return 0
    finally:
        print(f"控制台输出已同步写入日志: {log_path}")
        restore()


def _cmd_extract(args: argparse.Namespace) -> int:
    root, cfg, cfg_path = _load_effective_cfg(args)
    book_code = str(cfg["book_code"])
    out_dir = (root / (args.output or "output")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ext_only = getattr(args, "extractor", None)
    ext_s = str(ext_only).strip() if ext_only else ""
    if ext_s:
        log_path = out_dir / f"{book_code}_{ext_s}.log"
    else:
        log_path = out_dir / f"{book_code}_extract.log"
    extra: dict[str, str] = {"project_root": str(root)}
    if cfg_path:
        extra["config"] = str(cfg_path)
    else:
        extra["config"] = "(--book)"
    if ext_s:
        extra["extractor_only"] = ext_s
    restore = install_run_logging(
        log_path,
        header_lines=_log_header_lines(
            "extract",
            book_code=book_code,
            log_path=log_path,
            extra=extra,
        ),
    )
    try:
        text_path = root / cfg["layout_text"]
        if not text_path.is_file():
            print(f"缺少版式文本，请先 convert: {text_path}", file=sys.stderr)
            return 1
        full_text = text_path.read_text(encoding="utf-8")
        return _cmd_extract_core(
            args, root, cfg, book_code, out_dir, cfg_path, full_text=full_text
        )
    finally:
        print(f"控制台输出已同步写入日志: {log_path}")
        restore()


def _cmd_extract_core(
    args: argparse.Namespace,
    root: Path,
    cfg: dict[str, Any],
    book_code: str,
    out_dir: Path,
    cfg_path: Path | None = None,
    *,
    full_text: str | None = None,
) -> int:
    text_path = root / cfg["layout_text"]
    if full_text is None:
        if not text_path.is_file():
            print(f"缺少版式文本，请先 convert: {text_path}", file=sys.stderr)
            return 1
        full_text = text_path.read_text(encoding="utf-8")
    extractors_cfg = cfg.get("extractors") or {}
    names = (
        [args.extractor]
        if args.extractor
        else list(extractors_cfg.keys())
    )

    for name in names:
        block = extractors_cfg.get(name)
        if not block:
            print(f"配置中无提取器: {name}", file=sys.stderr)
            return 1

        module = block.get("module")
        if not module:
            print(f"提取器 {name} 缺少 module 字段", file=sys.stderr)
            return 1

        fn = get_extractor(str(module))
        block_opts = dict(block)
        block_opts.pop("module", None)
        inner = dict(block_opts.pop("options", None) or {})
        inner.update(block_opts)

        mod = str(module)
        omit_toc_md = bool(inner.pop("omit_toc_markdown", False))
        if mod in _MODULES_USING_TOC_LAYOUT_JSON:
            toc_json = out_dir / f"{book_code}_目录.json"
            if not toc_json.is_file():
                print(
                    f"缺少目录 JSON，请先对本书运行 extract 目录: {toc_json}",
                    file=sys.stderr,
                )
                return 1
            try:
                toc_data = json.loads(toc_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"无法读取目录 JSON {toc_json}: {e}", file=sys.stderr)
                return 1
            entries = toc_entries_from_layout_result(toc_data)
            if not entries:
                print(f"目录 JSON 无有效 entries: {toc_json}", file=sys.stderr)
                return 1
            inner["TOC_layout_entries"] = entries
            try:
                inner["TOC_layout_json_path"] = str(toc_json.relative_to(root))
            except ValueError:
                inner["TOC_layout_json_path"] = str(toc_json)
        elif cfg.get("toc_csv"):
            tcsv = cfg.get("toc_csv")
            tpath = Path(str(tcsv))
            if not tpath.is_absolute():
                tpath = root / tpath
            if tpath.is_file():
                col = inner.pop("toc_column", None) or name
                try:
                    inner["TOC_of_unit"] = toc_units_for_column(tpath, col)
                except KeyError as e:
                    print(f"TOC CSV: {e}", file=sys.stderr)
                    return 1

        out_base = f"{book_code}_{name}"
        discard_path = out_dir / f"{out_base}.discard.log"

        discard_fp = open(discard_path, "w", encoding="utf-8", newline="\n")
        discard_fp.write(f"# book_code: {book_code}\n# extractor: {name}\n\n")

        def discard_sink(line: str) -> None:
            discard_fp.write(line + "\n")
            discard_fp.flush()

        try:
            meta: dict[str, Any] = {
                "book_code": book_code,
                "extractor": name,
                "discard_sink": discard_sink,
            }
            result = fn(full_text, inner, meta)
            result.pop("discard_sink", None)
            result["discard_log"] = str(discard_path)

            out_path = out_dir / f"{out_base}.json"
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if "rows" in result:
                nrows = len(result.get("rows", []))
                bits: list[str] = [f"行数 {nrows}"]
                if (cc := result.get("char_count_computed")) is not None:
                    bits.append(f"字数合计 {cc}")
                if (wc := result.get("word_count_computed")) is not None:
                    bits.append(f"词语合计 {wc}")
                print(f"{name}: " + "，".join(bits))
            else:
                n = result.get("entry_count")
                if n is None and "entries" in result:
                    n = len(result["entries"])
                fc = result.get("flat_count")
                sfx = f"，扁平 {fc} 条" if fc is not None else ""
                gc = result.get("group_count")
                gs = f"，分组 {gc}" if gc is not None else ""
                print(f"{name}: 条目 {n}{sfx}{gs}")
            if w := result.get("char_count_warning"):
                print(f"  提示: {w}", file=sys.stderr)
            if w := result.get("word_count_warning"):
                print(f"  提示: {w}", file=sys.stderr)
            if ta := result.get("toc_alignment"):
                layout_ok = ta.get("toc_layout_match_ok")
                legacy_ok = ta.get("toc_one_to_one_ok")
                show = False
                if layout_ok is False and (ta.get("toc_anchor_group_count") or 0) > 0:
                    show = True
                elif legacy_ok is False:
                    show = True
                if show:
                    print(f"[{name} 目录对齐] 核对未通过: {ta}", file=sys.stderr)
            print(f"已写入: {out_path}")
            if mod == "layout_toc" and not omit_toc_md:
                md_path = out_path.with_suffix(".md")
                md_path.write_text(
                    render_layout_toc_markdown(result),
                    encoding="utf-8",
                )
                print(f"已写入: {md_path}")
            if mod in _MODULES_USING_TOC_LAYOUT_JSON and not omit_toc_md:
                md_path = out_path.with_suffix(".md")
                md_path.write_text(
                    render_table_unit_markdown(result, table_label=name),
                    encoding="utf-8",
                )
                print(f"已写入: {md_path}")
            print(f"抛弃行日志: {discard_path}")
        finally:
            discard_fp.close()

    return 0


def _parse_book_list(arg: str | None, root: Path) -> list[str]:
    if not arg or not str(arg).strip():
        return iter_book_codes(root)
    return [x.strip() for x in str(arg).split(",") if x.strip()]


def _cmd_extract_all(args: argparse.Namespace) -> int:
    root = _project_root_for_book_mode(args)
    codes = _parse_book_list(args.books, root)
    ext_name = args.extractor.strip()
    if not ext_name:
        print("须指定 --extractor", file=sys.stderr)
        return 1
    out_dir = (root / (args.output or "output")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"extract-all_{ext_name}.log"
    restore = install_run_logging(
        log_path,
        header_lines=_log_header_lines(
            "extract-all",
            book_code=",".join(codes) if len(codes) <= 8 else f"{len(codes)}_books",
            log_path=log_path,
            extra={
                "extractor": ext_name,
                "project_root": str(root),
                "books_arg": (args.books or "").strip() or "(全部书目)",
            },
        ),
    )
    fail = 0
    any_ran = False
    try:
        for code in codes:
            print(f"--- {code} ---")
            try:
                cfg = effective_book_config(root, code, file_overlay=None)
            except KeyError as e:
                print(f"{code}: {e}", file=sys.stderr)
                fail += 1
                if not args.continue_on_error:
                    return 1
                continue
            extractors_cfg = cfg.get("extractors") or {}
            if ext_name not in extractors_cfg:
                print(
                    f"{code}: 跳过（本册未配置 «{ext_name}»，多为 extractors_drop）",
                    file=sys.stderr,
                )
                continue
            any_ran = True
            sub = argparse.Namespace(
                extractor=ext_name,
                output=args.output,
            )
            rc = _cmd_extract_core(sub, root, cfg, code, out_dir, None, full_text=None)
            if rc != 0:
                fail += 1
                if not args.continue_on_error:
                    return rc
        if not any_ran:
            print(
                "没有任何书目运行该提取器（名称错误或全部被 extractors_drop）。",
                file=sys.stderr,
            )
            return 1
        return 1 if fail else 0
    finally:
        print(f"控制台输出已同步写入日志: {log_path}")
        restore()


def _cmd_convert_all(args: argparse.Namespace) -> int:
    root = _project_root_for_book_mode(args)
    codes = _parse_book_list(args.books, root)
    out_dir = (root / "output").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "convert-all.log"
    restore = install_run_logging(
        log_path,
        header_lines=_log_header_lines(
            "convert-all",
            book_code=",".join(codes) if len(codes) <= 8 else f"{len(codes)}_books",
            log_path=log_path,
            extra={
                "project_root": str(root),
                "books_arg": (args.books or "").strip() or "(全部书目)",
            },
        ),
    )
    fail = 0
    try:
        for code in codes:
            print(f"--- {code} ---")
            try:
                cfg = effective_book_config(root, code, file_overlay=None)
            except KeyError as e:
                print(f"{code}: {e}", file=sys.stderr)
                fail += 1
                if not args.continue_on_error:
                    return 1
                continue
            sub = argparse.Namespace()
            rc = _run_convert_core(root, cfg, code, sub)
            if rc != 0:
                fail += 1
                if not args.continue_on_error:
                    return rc
        return 1 if fail else 0
    finally:
        print(f"控制台输出已同步写入日志: {log_path}")
        restore()


def _run_convert_core(root: Path, cfg: dict[str, Any], book_code: str, args: argparse.Namespace) -> int:
    out = (root / cfg["layout_text"]).resolve()
    log_path = out.parent / f"{out.stem}.convert.log"
    restore = install_run_logging(
        log_path,
        header_lines=_log_header_lines(
            "convert",
            book_code=book_code,
            log_path=log_path,
            extra={"config": "(extract-all/convert-all)", "project_root": str(root)},
        ),
    )
    try:
        pdf = root / cfg["source_pdf"]
        if not pdf.is_file():
            print(f"缺少 PDF: {pdf}", file=sys.stderr)
            return 1
        pt = cfg.get("pdftotext") or {}
        run_pdftotext(
            pdf,
            out,
            enc=str(pt.get("enc", "UTF-8")),
            layout=bool(pt.get("layout", True)),
            extra_args=list(pt.get("extra_args") or []),
        )
        print(f"已写入: {out}")
        return 0
    finally:
        print(f"控制台输出已同步写入日志: {log_path}")
        restore()


def _run_toc_chunk_single(
    root: Path,
    book_code: str,
    out_dir: Path,
    body_start_line: int | None,
) -> int:
    """单册正文分块；各册独立日志 `{book}_正文分块.log`。"""
    cfg = effective_book_config(root, book_code, file_overlay=None)
    book_code = str(cfg["book_code"])
    text_path = (root / cfg["layout_text"]).resolve()
    toc_path = out_dir / f"{book_code}_目录.json"
    log_path = out_dir / f"{book_code}_正文分块.log"

    restore = install_run_logging(
        log_path,
        header_lines=_log_header_lines(
            "toc-chunk",
            book_code=book_code,
            log_path=log_path,
            extra={"project_root": str(root), "output": str(out_dir)},
        ),
    )
    try:
        if not text_path.is_file():
            print(f"缺少版式文本: {text_path}", file=sys.stderr)
            return 1
        if not toc_path.is_file():
            print(f"缺少目录 JSON，请先 extract 目录: {toc_path}", file=sys.stderr)
            return 1
        toc_data = json.loads(toc_path.read_text(encoding="utf-8"))
        entries = toc_entries_from_layout_result(toc_data)
        if not entries:
            print(f"目录 JSON 无 entries: {toc_path}", file=sys.stderr)
            return 1
        full_text = text_path.read_text(encoding="utf-8")
        try:
            layout_src = str(text_path.relative_to(root))
        except ValueError:
            layout_src = str(text_path)
        try:
            toc_src = str(toc_path.relative_to(root))
        except ValueError:
            toc_src = str(toc_path)

        result = run_toc_text_chunk(
            book_code,
            full_text,
            entries,
            layout_source=layout_src,
            toc_source=toc_src,
            body_start_override=body_start_line,
        )

        out_json = out_dir / f"{book_code}_正文分块.json"
        out_md = out_dir / f"{book_code}_正文分块.md"
        out_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        out_md.write_text(render_toc_chunk_markdown(result), encoding="utf-8")

        print(
            f"正文分块: 条目 {result.get('chunk_entry_count')}, "
            f"命中 {result.get('chunk_matched_count')}, "
            f"未命中 {result.get('chunk_unmatched_count')}"
        )
        for w in result.get("warnings") or []:
            print(f"  [问题] {w}", file=sys.stderr)
        print(f"已写入: {out_json}")
        print(f"已写入: {out_md}")
        return 0
    finally:
        print(f"控制台输出已同步写入日志: {log_path}")
        restore()


def _cmd_toc_chunk(args: argparse.Namespace) -> int:
    """按目录 JSON 为版式正文估计分块；`--book` 单册或 `--books` 多册/全表。"""
    root = _project_root_for_book_mode(args)
    out_dir = (root / (args.output or "output")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    one = getattr(args, "book", None)
    one_s = str(one).strip() if one else ""
    books_mode = getattr(args, "books", None)

    if one_s and books_mode is not None:
        print("请勿同时指定 --book 与 --books", file=sys.stderr)
        return 1
    if not one_s and books_mode is None:
        print("须指定 --book <code> 或 --books [列表]", file=sys.stderr)
        return 1

    if one_s:
        codes = [one_s]
    else:
        codes = _parse_book_list(books_mode if books_mode != "" else None, root)

    body_start = getattr(args, "body_start_line", None)
    cont = bool(getattr(args, "continue_on_error", False))
    fail = 0
    for code in codes:
        print(f"--- {code} ---")
        try:
            effective_book_config(root, code, file_overlay=None)
        except KeyError as e:
            print(f"{code}: {e}", file=sys.stderr)
            fail += 1
            if not cont:
                return 1
            continue
        rc = _run_toc_chunk_single(root, code, out_dir, body_start)
        if rc != 0:
            fail += 1
            if not cont:
                return rc
    return 1 if fail else 0


def _add_project_root(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--project-root",
        default=None,
        help="项目根目录（含 configs/books.yaml；使用 --book 时默认当前工作目录）",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="教材 PDF → pdftotext 版式文本 → 结构化提取")
    sub = parser.add_subparsers(dest="command", required=True)

    p_conv = sub.add_parser("convert", help="pdftotext -enc UTF-8 -layout 生成版式文本")
    cx = p_conv.add_mutually_exclusive_group(required=True)
    cx.add_argument("--config", help="单册 YAML（可与 defaults.yaml 合并）")
    cx.add_argument("--book", help="book_code，等价于仅含该代码的合并配置")
    _add_project_root(p_conv)
    p_conv.set_defaults(func=_cmd_convert)

    p_ext = sub.add_parser("extract", help="按配置从版式文本提取 JSON")
    ex = p_ext.add_mutually_exclusive_group(required=True)
    ex.add_argument("--config", help="单册 YAML（可与 defaults.yaml 合并）")
    ex.add_argument("--book", help="book_code")
    _add_project_root(p_ext)
    p_ext.add_argument(
        "--extractor",
        help="只运行某一提取器（默认运行配置中的全部）",
    )
    p_ext.add_argument(
        "--output",
        default="output",
        help="JSON 输出目录（相对项目根，默认 output）",
    )
    p_ext.set_defaults(func=_cmd_extract)

    p_all = sub.add_parser(
        "extract-all",
        help="对书目表中全部（或指定）图书只运行某一种提取器",
    )
    _add_project_root(p_all)
    p_all.add_argument(
        "--extractor",
        required=True,
        help="提取器名称，如 目录、识字表、写字表、词语表",
    )
    p_all.add_argument(
        "--books",
        help="逗号分隔 book_code，省略则处理 books.yaml 中全部书目",
    )
    p_all.add_argument("--output", default="output", help="JSON 输出目录（相对项目根）")
    p_all.add_argument(
        "--continue-on-error",
        action="store_true",
        help="某一册失败时继续处理其余书目",
    )
    p_all.set_defaults(func=_cmd_extract_all)

    p_c_all = sub.add_parser(
        "convert-all",
        help="对书目表中全部（或指定）图书批量 pdftotext",
    )
    _add_project_root(p_c_all)
    p_c_all.add_argument(
        "--books",
        help="逗号分隔 book_code，省略则处理 books.yaml 中全部书目",
    )
    p_c_all.add_argument(
        "--continue-on-error",
        action="store_true",
        help="某一册失败时继续处理其余书目",
    )
    p_c_all.set_defaults(func=_cmd_convert_all)

    p_chunk = sub.add_parser(
        "toc-chunk",
        help="按目录 JSON 将版式正文分块，写出 JSON / Markdown / 日志",
    )
    p_chunk.add_argument(
        "--book",
        default=None,
        help="单册 book_code（与 --books 二选一）",
    )
    p_chunk.add_argument(
        "--books",
        nargs="?",
        const="",
        default=None,
        metavar="LIST",
        help="逗号分隔多册 book_code；仅写 --books 不写值则处理 books.yaml 中全部书目（与 --book 二选一）",
    )
    _add_project_root(p_chunk)
    p_chunk.add_argument(
        "--output",
        default="output",
        help="输出目录（相对项目根，默认 output）",
    )
    p_chunk.add_argument(
        "--body-start-line",
        type=int,
        default=None,
        help="强制指定正文起始行号（0 基 splitlines）；省略则用「独占一行的第×单元」启发式",
    )
    p_chunk.add_argument(
        "--continue-on-error",
        action="store_true",
        help="使用 --books 批量时，某一册失败则继续其余书目",
    )
    p_chunk.set_defaults(func=_cmd_toc_chunk)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
