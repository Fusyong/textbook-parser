"""当前解析工作区：限制正式 convert / extract / toc-chunk 只动白名单内的教材文件。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .batch import (
    SLOT_CODES,
    SLOT_KEYWORDS,
    batch_output_dir,
    is_batch_dir_name,
    list_slots_in_batch,
    resolve_batch_id,
)

_CONFIG_NAME = "active_sources.yaml"
_DEFAULT_SCRATCH = "tmp/parse-scratch"


class ActiveSourcesError(RuntimeError):
    """当前工作区不允许该操作。"""


@dataclass
class ActiveWorkspace:
    """configs/active_sources.yaml 解析结果。"""

    enabled: bool = False
    scratch_dir: str = _DEFAULT_SCRATCH
    # 允许正式写入的 (batch_id, book_code)
    allowed_slots: set[tuple[str, str]] = field(default_factory=set)
    # 配置中的原始条目（便于展示）
    raw_sources: list[Any] = field(default_factory=list)
    config_path: Path | None = None

    def allows_slot(self, batch_id: str, book_code: str) -> bool:
        if not self.enabled:
            return True
        return (str(batch_id), str(book_code)) in self.allowed_slots

    def scratch_path(self, root: Path, batch_id: str) -> Path:
        return (root / self.scratch_dir / batch_id).resolve()

    def slots_for_batch(self, batch_id: str) -> list[str]:
        """本批在白名单中的册码（学习顺序）。"""
        bid = str(batch_id)
        return [c for c in SLOT_CODES if (bid, c) in self.allowed_slots]


def active_config_path(root: Path) -> Path:
    return root / "configs" / _CONFIG_NAME


def load_active_workspace(root: Path) -> ActiveWorkspace:
    path = active_config_path(root)
    if not path.is_file():
        return ActiveWorkspace(enabled=False, config_path=path)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return ActiveWorkspace(enabled=False, config_path=path)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 须为映射")

    enabled = bool(data.get("enabled", False))
    scratch = str(data.get("scratch_dir") or _DEFAULT_SCRATCH).strip() or _DEFAULT_SCRATCH
    sources = data.get("sources")
    if sources is None:
        sources = []
    if not isinstance(sources, list):
        raise ValueError(f"{path} 的 sources 须为列表")

    ws = ActiveWorkspace(
        enabled=enabled,
        scratch_dir=scratch.replace("\\", "/"),
        raw_sources=list(sources),
        config_path=path,
    )
    if enabled:
        ws.allowed_slots = _resolve_sources(root, sources)
    return ws


def _rel_posix(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _slot_code_from_filename(name: str) -> str | None:
    """文件名含「×年级×册」时返回册码；多关键词时取最长匹配。"""
    best: str | None = None
    best_len = -1
    for code, kw in SLOT_KEYWORDS.items():
        if kw in name and len(kw) > best_len:
            best = code
            best_len = len(kw)
    return best


def _add_file(root: Path, allowed: set[tuple[str, str]], path: Path) -> None:
    if not path.is_file():
        return
    if path.suffix.lower() not in {".md", ".pdf", ".txt"}:
        return
    # material/{batch}/file
    try:
        rel = path.resolve().relative_to((root / "material").resolve())
    except ValueError:
        return
    parts = rel.parts
    if len(parts) < 2:
        return
    batch_id = parts[0]
    if not is_batch_dir_name(batch_id):
        return
    code = _slot_code_from_filename(path.name)
    if code:
        allowed.add((batch_id, code))


def _add_batch_code(
    root: Path, allowed: set[tuple[str, str]], batch_id: str, code: str
) -> None:
    bid = resolve_batch_id(root, batch_id)
    code = str(code)
    if code not in SLOT_KEYWORDS:
        raise ValueError(f"未知册码 «{code}»")
    # 仅当 material 中确有该册时加入（避免空占位）
    if code in list_slots_in_batch(root, bid):
        allowed.add((bid, code))
    else:
        # 仍登记：允许「即将放入」的规划；convert/extract 时再报缺文件
        allowed.add((bid, code))


def _resolve_sources(root: Path, sources: list[Any]) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    root = root.resolve()
    for item in sources:
        if isinstance(item, str):
            raw = item.strip().replace("\\", "/")
            if not raw or raw.startswith("#"):
                continue
            # batch:code 简写
            if ":" in raw and not raw.startswith("material/") and "/" not in raw.split(":", 1)[0]:
                bid, code = raw.split(":", 1)
                _add_batch_code(root, allowed, bid.strip(), code.strip())
                continue
            path = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
            if path.is_dir():
                # 批次目录或任意子目录
                for p in sorted(path.rglob("*")):
                    _add_file(root, allowed, p)
                # 若是 material/{batch}/ 空目录，仍可按批登记全部已有册——上面 rglob 即可
                continue
            if any(ch in raw for ch in "*?["):
                for p in sorted(root.glob(raw)):
                    if p.is_dir():
                        for q in p.rglob("*"):
                            _add_file(root, allowed, q)
                    else:
                        _add_file(root, allowed, p)
                continue
            _add_file(root, allowed, path)
            continue

        if isinstance(item, dict):
            bid = item.get("batch")
            if not bid:
                raise ValueError(f"sources 映射项须含 batch: {item!r}")
            codes = item.get("codes") or item.get("books") or item.get("code")
            if codes is None:
                # 整批
                bid_r = resolve_batch_id(root, str(bid))
                for code in list_slots_in_batch(root, bid_r):
                    allowed.add((bid_r, code))
                continue
            if isinstance(codes, str):
                codes = [codes]
            if not isinstance(codes, list):
                raise ValueError(f"sources.codes 须为字符串或列表: {item!r}")
            for code in codes:
                _add_batch_code(root, allowed, str(bid), str(code))
            continue

        raise ValueError(f"sources 项类型无效: {type(item)!r}")

    return allowed


def is_official_output_dir(root: Path, batch_id: str, out_dir: Path) -> bool:
    """是否正写入正式 output/{batch}/（兼容性测试应避开此处）。"""
    official = batch_output_dir(root, batch_id, "output").resolve()
    target = out_dir.resolve()
    return target == official or official in target.parents


def filter_codes_for_active(
    ws: ActiveWorkspace,
    batch_id: str,
    codes: list[str],
    *,
    official_write: bool,
) -> tuple[list[str], list[str]]:
    """
    返回 (保留的册码, 因白名单跳过的册码)。
    非正式写入或未启用时全部保留。
    """
    if not ws.enabled or not official_write:
        return list(codes), []
    keep: list[str] = []
    skip: list[str] = []
    for c in codes:
        if ws.allows_slot(batch_id, c):
            keep.append(c)
        else:
            skip.append(c)
    return keep, skip


def ensure_slot_allowed(
    ws: ActiveWorkspace,
    batch_id: str,
    book_code: str,
    *,
    official_write: bool,
    action: str,
) -> None:
    """正式写入且不在白名单时抛 ActiveSourcesError。"""
    if not ws.enabled or not official_write:
        return
    if ws.allows_slot(batch_id, book_code):
        return
    cfg = ws.config_path or Path(f"configs/{_CONFIG_NAME}")
    raise ActiveSourcesError(
        f"已启用当前解析白名单，拒绝{action} «{batch_id}/{book_code}» "
        f"（不在 {cfg.as_posix()} 的 sources 中）。\n"
        f"  · 将该册加入 sources 后重试；或\n"
        f"  · 使用 --scratch，把结果写到临时目录 {ws.scratch_dir}/{{batch}}/（不覆盖已核数据）；或\n"
        f"  · 临时设置 enabled: false（不推荐）。"
    )


def format_workspace_status(root: Path, ws: ActiveWorkspace) -> str:
    lines = [
        f"配置: {ws.config_path or active_config_path(root)}",
        f"启用: {'是' if ws.enabled else '否（不限制）'}",
        f"临时输出目录: {ws.scratch_dir}/{{batch}}/",
    ]
    if not ws.enabled:
        return "\n".join(lines)
    if not ws.allowed_slots:
        lines.append("白名单: （空 — 将拒绝一切正式解析写入）")
        return "\n".join(lines)
    lines.append(f"白名单册数: {len(ws.allowed_slots)}")
    by_batch: dict[str, list[str]] = {}
    for bid, code in sorted(
        ws.allowed_slots, key=lambda t: (t[0], SLOT_CODES.index(t[1]) if t[1] in SLOT_CODES else 99)
    ):
        by_batch.setdefault(bid, []).append(code)
    for bid, codes in by_batch.items():
        lines.append(f"  {bid}: {', '.join(codes)}")
    return "\n".join(lines)
