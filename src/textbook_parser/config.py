from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .batch import (
    batch_material_dir,
    resolve_batch_id,
    resolve_slot_file,
)


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
    if value is None:
        value = {}
    if isinstance(value, str):
        # 兼容旧写法：仅写 PDF 文件名
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
        tc = value.get("toc_columns", 2)
        drop = value.get("extractors_drop") or []
        if not isinstance(drop, list):
            raise ValueError(f"configs/books.yaml «{code}» 的 extractors_drop 须为列表")
        patch = value.get("extractors_patch") or {}
        if patch and not isinstance(patch, dict):
            raise ValueError(f"configs/books.yaml «{code}» 的 extractors_patch 须为映射")
        tch = value.get("toc_content_width_han")
        return {
            "pdf": str(pdf) if pdf else None,
            "toc_csv": value.get("toc_csv"),
            "toc_columns": int(tc),
            "extractors_drop": [str(x) for x in drop],
            "extractors_patch": dict(patch),
            "toc_content_width_han": int(tch) if tch is not None else None,
        }
    raise ValueError(f"configs/books.yaml 中 «{code}» 取值类型无效: {type(value)!r}")


def load_books_registry(root: Path) -> dict[str, str | None]:
    """book_code → 可选的优先 PDF 文件名。"""
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
    batch: str | None = None,
) -> dict[str, Any]:
    """
    defaults.yaml 与可选单册 YAML 深度合并，再套用 books.yaml 中的 toc_csv / 目录栏数。
    file_overlay 中已写字段优先于注册表默认值。
    batch: 学期批次 ID，None/'latest' 表示最新一批。
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
    if "batch" in overlay and overlay["batch"] is not None:
        batch = str(overlay["batch"])
    return resolve_book_paths(merged, root, batch=batch, preferred_pdf=entry.get("pdf"))


def resolve_book_paths(
    cfg: dict[str, Any],
    root: Path,
    *,
    batch: str | None = None,
    preferred_pdf: str | None = None,
) -> dict[str, Any]:
    """根据 book_code 与批次目录补全 source_pdf、layout_text、batch（未手写时）。"""
    out = dict(cfg)
    code = out.get("book_code")
    if not code:
        raise ValueError(
            "单书配置须设置 book_code，且须在 configs/books.yaml 的 book_code 下登记"
        )
    code = str(code)
    reg = _read_books_yaml(root)
    if code not in reg:
        raise KeyError(
            f"未知 book_code «{code}»，请在 configs/books.yaml 的 book_code 下添加该键"
        )

    if out.get("batch"):
        batch_id = resolve_batch_id(root, str(out["batch"]))
    else:
        batch_id = resolve_batch_id(root, batch)
    out["batch"] = batch_id

    bdir = batch_material_dir(root, batch_id)
    pref = preferred_pdf or out.get("pdf")
    pref_s = str(pref) if pref else None

    if "source_pdf" not in out:
        pdf_path = resolve_slot_file(bdir, code, suffix=".pdf", preferred_name=pref_s)
        if pdf_path is not None:
            try:
                out["source_pdf"] = str(pdf_path.relative_to(root)).replace("\\", "/")
            except ValueError:
                out["source_pdf"] = str(pdf_path)
        else:
            # 占位路径，便于报错信息指向预期位置
            hint = pref_s or f"（含「{_slot_kw(code)}」的 PDF）"
            out["source_pdf"] = f"material/{batch_id}/{hint}"

    if "layout_text" not in out:
        md_path = resolve_slot_file(bdir, code, suffix=".md", preferred_name=pref_s)
        if md_path is not None:
            try:
                out["layout_text"] = str(md_path.relative_to(root)).replace("\\", "/")
            except ValueError:
                out["layout_text"] = str(md_path)
        else:
            stem_hint = Path(pref_s).stem if pref_s else f"（含「{_slot_kw(code)}」）"
            out["layout_text"] = f"material/{batch_id}/{stem_hint}.md"

    return out


def _slot_kw(code: str) -> str:
    from .batch import keyword_for_slot

    try:
        return keyword_for_slot(code)
    except KeyError:
        return code
