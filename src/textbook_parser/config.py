from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"配置文件应为映射: {path}")
    return data


def project_root_from_config(config_path: Path) -> Path:
    return config_path.resolve().parent.parent


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in overlay.items():
        if (
            k in out
            and isinstance(out[k], dict)
            and isinstance(v, dict)
            and not isinstance(v, type(None))
        ):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _read_books_yaml(root: Path) -> dict[str, Any]:
    path = root / "configs" / "books.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"缺少书目注册表: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    reg = data.get("book_code") if isinstance(data, dict) else None
    if not isinstance(reg, dict):
        raise ValueError("configs/books.yaml 须包含顶层键 book_code")
    return reg


def _parse_registry_row(code: str, value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {
            "pdf": value,
            "toc_csv": None,
            "toc_columns": 2,
            "extractors_drop": [],
            "extractors_patch": {},
            "toc_content_width_han": None,
        }
    if isinstance(value, dict):
        pdf = value.get("pdf")
        if not pdf:
            raise ValueError(f"configs/books.yaml 中 «{code}» 缺少 pdf 字段")
        tc = value.get("toc_columns", 2)
        drop = value.get("extractors_drop") or []
        if not isinstance(drop, list):
            raise ValueError(f"configs/books.yaml «{code}» 的 extractors_drop 须为列表")
        patch = value.get("extractors_patch") or {}
        if patch and not isinstance(patch, dict):
            raise ValueError(f"configs/books.yaml «{code}» 的 extractors_patch 须为映射")
        tch = value.get("toc_content_width_han")
        return {
            "pdf": str(pdf),
            "toc_csv": value.get("toc_csv"),
            "toc_columns": int(tc),
            "extractors_drop": [str(x) for x in drop],
            "extractors_patch": dict(patch),
            "toc_content_width_han": int(tch) if tch is not None else None,
        }
    raise ValueError(f"configs/books.yaml 中 «{code}» 取值类型无效: {type(value)!r}")


def load_books_registry(root: Path) -> dict[str, str]:
    """book_code → PDF 文件名（与 books.yaml 一致）。"""
    reg = _read_books_yaml(root)
    return {str(k): _parse_registry_row(str(k), v)["pdf"] for k, v in reg.items()}


def load_book_entry(root: Path, book_code: str) -> dict[str, Any]:
    reg = _read_books_yaml(root)
    code = str(book_code)
    if code not in reg:
        raise KeyError(f"未知 book_code «{code}»，请在 configs/books.yaml 的 book_code 下登记")
    row = _parse_registry_row(code, reg[code])
    if not row.get("toc_csv"):
        row["toc_csv"] = f"configs/tocs/{code}_toc.csv"
    return row


def iter_book_codes(root: Path) -> list[str]:
    reg = _read_books_yaml(root)
    return [str(k) for k in reg.keys()]


def load_defaults(root: Path) -> dict[str, Any]:
    path = root / "configs" / "defaults.yaml"
    if not path.is_file():
        return {}
    return load_config(path)


def apply_toc_column_layout(cfg: dict[str, Any], toc_columns: int) -> None:
    """一年级等单栏目录：去掉 column_number；双栏则保证为 2。"""
    ext = cfg.get("extractors")
    if not isinstance(ext, dict):
        return
    toc = ext.get("目录")
    if not isinstance(toc, dict):
        return
    if toc_columns <= 1:
        toc.pop("column_number", None)
    else:
        toc["column_number"] = 2


def effective_book_config(
    root: Path,
    book_code: str,
    *,
    file_overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    defaults.yaml 与可选单册 YAML 深度合并，再套用 books.yaml 中的 toc_csv / 目录栏数。
    file_overlay 中已写字段优先于注册表默认值。
    """
    entry = load_book_entry(root, book_code)
    overlay = dict(file_overlay or {})
    merged = deep_merge(load_defaults(root), overlay)
    merged["book_code"] = str(book_code)
    if "toc_csv" not in overlay:
        merged.setdefault("toc_csv", str(entry["toc_csv"]))
    epatch = entry.get("extractors_patch") or {}
    if epatch:
        merged["extractors"] = deep_merge(merged.get("extractors") or {}, epatch)
    apply_toc_column_layout(merged, int(entry.get("toc_columns", 2)))
    tch = entry.get("toc_content_width_han")
    if tch is not None:
        ext = merged.setdefault("extractors", {})
        toc_blk = ext.setdefault("目录", {})
        if isinstance(toc_blk, dict):
            toc_blk["toc_content_width_han"] = int(tch)
    for name in entry.get("extractors_drop") or []:
        if isinstance(merged.get("extractors"), dict):
            merged["extractors"].pop(name, None)
    return resolve_book_paths(merged, root)


def resolve_book_paths(cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    """根据 book_code 与 configs/books.yaml 补全 source_pdf、layout_text（未手写时）。"""
    out = dict(cfg)
    code = out.get("book_code")
    if not code:
        raise ValueError(
            "单书配置须设置 book_code，且须在 configs/books.yaml 的 book_code 下登记对应 PDF 文件名"
        )
    code = str(code)
    books = load_books_registry(root)
    if code not in books:
        raise KeyError(
            f"未知 book_code «{code}»，请在 configs/books.yaml 的 book_code 下添加该键"
        )
    pdf_name = books[code]
    stem = Path(pdf_name).stem
    out.setdefault("source_pdf", f"material/{pdf_name}")
    out.setdefault("layout_text", f"material/text-by-layout/{stem}.md")
    return out
