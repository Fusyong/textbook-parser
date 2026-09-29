"""学期批次发现、册次关键词匹配、成套错位拼装。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 学习序列：一上 … 六下
SLOT_CODES: list[str] = [
    "b11",
    "b12",
    "b21",
    "b22",
    "b31",
    "b32",
    "b41",
    "b42",
    "b51",
    "b52",
    "b61",
    "b62",
]

_GRADE_CN = ("一", "二", "三", "四", "五", "六")
_TERM_CN = ("上", "下")

SLOT_KEYWORDS: dict[str, str] = {
    f"b{g}{t}": f"{_GRADE_CN[g - 1]}年级{_TERM_CN[t - 1]}册"
    for g in range(1, 7)
    for t in (1, 2)
}

SLOT_SHORT_LABELS: dict[str, str] = {
    f"b{g}{t}": f"{_GRADE_CN[g - 1]}{_TERM_CN[t - 1]}"
    for g in range(1, 7)
    for t in (1, 2)
}

# 批次目录名：YYYY-MM 或 YYYY-MM-DD
_BATCH_DIR_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")


def slot_index(code: str) -> int:
    try:
        return SLOT_CODES.index(str(code))
    except ValueError as e:
        raise KeyError(f"未知册码 «{code}»") from e


def keyword_for_slot(code: str) -> str:
    kw = SLOT_KEYWORDS.get(str(code))
    if not kw:
        raise KeyError(f"未知册码 «{code}»")
    return kw


def is_batch_dir_name(name: str) -> bool:
    return bool(_BATCH_DIR_RE.match(name))


def parse_batch_sort_key(batch_id: str) -> tuple[int, int, int]:
    m = _BATCH_DIR_RE.match(batch_id)
    if not m:
        raise ValueError(f"非法批次 ID（须为 YYYY-MM 或 YYYY-MM-DD）: {batch_id}")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return (y, mo, d)


def material_dir(root: Path) -> Path:
    return root / "material"


def batch_material_dir(root: Path, batch_id: str) -> Path:
    return material_dir(root) / batch_id


def batch_output_dir(root: Path, batch_id: str, output_base: str | Path = "output") -> Path:
    base = Path(output_base)
    if not base.is_absolute():
        base = root / base
    return base / batch_id


def _load_batches_yaml(root: Path) -> dict[str, Any] | None:
    path = root / "configs" / "batches.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def discover_batch_ids(root: Path) -> list[str]:
    """
    发现可用批次 ID（按日期升序）。
    若存在 configs/batches.yaml 的 batches 列表，以其顺序与启用状态为准；
    否则扫描 material/ 下符合日期命名的子目录。
    """
    cfg = _load_batches_yaml(root)
    if cfg and isinstance(cfg.get("batches"), list) and cfg["batches"]:
        ids: list[str] = []
        for item in cfg["batches"]:
            if isinstance(item, str):
                bid = item.strip()
                enabled = True
            elif isinstance(item, dict):
                bid = str(item.get("id") or "").strip()
                enabled = bool(item.get("enabled", True))
            else:
                continue
            if not bid or not enabled:
                continue
            if not is_batch_dir_name(bid):
                raise ValueError(f"configs/batches.yaml 中非法批次 id: {bid}")
            ids.append(bid)
        # 保持 YAML 顺序；若未写全，可再补扫描到的未列出目录
        listed = set(ids)
        for p in material_dir(root).iterdir() if material_dir(root).is_dir() else []:
            if p.is_dir() and is_batch_dir_name(p.name) and p.name not in listed:
                ids.append(p.name)
        return sorted(ids, key=parse_batch_sort_key)

    found: list[str] = []
    mat = material_dir(root)
    if mat.is_dir():
        for p in mat.iterdir():
            if p.is_dir() and is_batch_dir_name(p.name):
                found.append(p.name)
    return sorted(found, key=parse_batch_sort_key)


def latest_batch(root: Path) -> str:
    ids = discover_batch_ids(root)
    if not ids:
        raise FileNotFoundError(
            f"未找到学期批次目录（material/YYYY-MM 或 YYYY-MM-DD）；"
            f"也可在 configs/batches.yaml 中登记"
        )
    return ids[-1]


def resolve_batch_id(root: Path, batch: str | None) -> str:
    """batch 为 None / '' / 'latest' 时取最新一批。"""
    if batch is None or not str(batch).strip() or str(batch).strip().lower() == "latest":
        return latest_batch(root)
    bid = str(batch).strip()
    if not is_batch_dir_name(bid):
        raise ValueError(f"非法批次 ID: {bid}")
    return bid


def find_slot_files(batch_dir: Path, book_code: str, *, suffix: str) -> list[Path]:
    """在批次目录中按「×年级×册」关键词查找文件（后缀如 .md / .pdf）。"""
    kw = keyword_for_slot(book_code)
    if not batch_dir.is_dir():
        return []
    suf = suffix if suffix.startswith(".") else f".{suffix}"
    hits: list[Path] = []
    for p in batch_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() != suf.lower():
            continue
        if kw in p.name:
            hits.append(p)
    return sorted(hits, key=lambda x: x.name)


def resolve_slot_file(
    batch_dir: Path,
    book_code: str,
    *,
    suffix: str,
    preferred_name: str | None = None,
) -> Path | None:
    """
    解析某册在批次目录中的文件。
    preferred_name 若给出且存在则优先；否则按关键词匹配（恰好一则返回，多则优先 stem 匹配 preferred）。
    """
    if preferred_name:
        pref = batch_dir / preferred_name
        if pref.is_file():
            return pref
        # 允许只给 stem
        if not preferred_name.lower().endswith(suffix.lower()):
            alt = batch_dir / f"{Path(preferred_name).stem}{suffix if suffix.startswith('.') else '.' + suffix}"
            if alt.is_file():
                return alt

    hits = find_slot_files(batch_dir, book_code, suffix=suffix)
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    if preferred_name:
        stem = Path(preferred_name).stem
        for h in hits:
            if h.stem == stem:
                return h
    # 多个命中：优先文件名更短者（通常无额外前缀的较少；修订版往往更长——取含关键词的唯一逻辑）
    # 稳定选择：按名称排序后取第一个，并依赖调用方日志
    return hits[0]


def list_slots_in_batch(root: Path, batch_id: str) -> list[str]:
    """返回该批 material 中能匹配到版式 .md 或 .pdf 的册码（按学习顺序）。"""
    bdir = batch_material_dir(root, batch_id)
    found: list[str] = []
    for code in SLOT_CODES:
        md = resolve_slot_file(bdir, code, suffix=".md")
        pdf = resolve_slot_file(bdir, code, suffix=".pdf")
        if md or pdf:
            found.append(code)
    return found


def batch_year_month(batch_id: str) -> tuple[int, int]:
    y, mo, _ = parse_batch_sort_key(batch_id)
    return y, mo


def set_display_label(batch_id: str, book_code: str, *, disambiguate: bool = False) -> str:
    y, mo = batch_year_month(batch_id)
    short = SLOT_SHORT_LABELS[book_code]
    if disambiguate:
        return f"{y}-{mo:02d}{short}"
    return f"{y}{short}"


@dataclass
class SlotRef:
    batch: str
    code: str


@dataclass
class SetAssembly:
    id: str
    label: str
    anchor_batch: str
    anchor_code: str
    slots: list[SlotRef | None]  # 长度 12，后面不足为 None
    substitutions: list[dict[str, str]]


def _batch_has_slot(inventory: dict[str, set[str]], batch_id: str, code: str) -> bool:
    return code in inventory.get(batch_id, set())


def _borrow_slot(
    batch_ids: list[str],
    inventory: dict[str, set[str]],
    code: str,
    k: int,
    i: int,
    j: int,
) -> tuple[SlotRef | None, str]:
    """从前一套或更早批次借入某槽；返回 (SlotRef|None, fromSetId)。"""
    for j2 in range(j - 1, -1, -1):
        for i2 in range(i, -1, -1):
            if not _batch_has_slot(inventory, batch_ids[i2], SLOT_CODES[j2]):
                continue
            need2 = i2 - (j2 - k)
            if need2 < 0:
                continue
            bid2 = batch_ids[need2]
            if _batch_has_slot(inventory, bid2, code):
                return (
                    SlotRef(batch=bid2, code=code),
                    f"{batch_ids[i2]}/{SLOT_CODES[j2]}",
                )
    for i2 in range(min(i, len(batch_ids) - 1), -1, -1):
        bid2 = batch_ids[i2]
        if _batch_has_slot(inventory, bid2, code):
            return SlotRef(batch=bid2, code=code), f"{bid2}/{code}"
    return None, ""


def assemble_set(
    batch_ids: list[str],
    inventory: dict[str, set[str]],
    anchor_batch: str,
    anchor_code: str,
    *,
    label: str | None = None,
) -> SetAssembly:
    """
    错位成套：锚定 (Bi, Sj) 时，槽 Sk(k≤j) 取自 B[i-(j-k)]；
    缺历史批或该册时，向锚定更早的可用套借入并记入 substitutions。
    """
    if anchor_batch not in batch_ids:
        raise KeyError(f"锚定批次不在列表中: {anchor_batch}")
    j = slot_index(anchor_code)
    i = batch_ids.index(anchor_batch)
    set_id = f"{anchor_batch}/{anchor_code}"
    disp = label or set_display_label(anchor_batch, anchor_code)

    slots: list[SlotRef | None] = [None] * len(SLOT_CODES)
    substitutions: list[dict[str, str]] = []

    for k in range(j + 1):
        code = SLOT_CODES[k]
        needed = i - (j - k)
        if needed >= 0:
            bid = batch_ids[needed]
            if _batch_has_slot(inventory, bid, code):
                slots[k] = SlotRef(batch=bid, code=code)
                continue
            # 应有之批缺少该册 → 顶替并提示
            borrowed, from_set = _borrow_slot(
                batch_ids, inventory, code, k, i, j
            )
            if borrowed is not None:
                slots[k] = borrowed
                short = SLOT_SHORT_LABELS[code]
                substitutions.append(
                    {
                        "code": code,
                        "fromSet": from_set,
                        "fromBatch": borrowed.batch,
                        "message": f"{SLOT_KEYWORDS[code]}（{short}）借自批次 {borrowed.batch}",
                    }
                )
            continue

        # needed < 0：尚无更早批次，用最早可用批中该册填入（本套固有前序，不提示）
        for i2 in range(0, i + 1):
            bid2 = batch_ids[i2]
            if _batch_has_slot(inventory, bid2, code):
                slots[k] = SlotRef(batch=bid2, code=code)
                break

    return SetAssembly(
        id=set_id,
        label=disp,
        anchor_batch=anchor_batch,
        anchor_code=anchor_code,
        slots=slots,
        substitutions=substitutions,
    )


def build_all_sets(
    root: Path,
    batch_ids: list[str] | None = None,
    *,
    inventory: dict[str, set[str]] | None = None,
) -> list[SetAssembly]:
    """为每个（批次, 该批有数据的册）生成锚定套；同年同标签冲突时加月份消歧。"""
    ids = batch_ids if batch_ids is not None else discover_batch_ids(root)
    if inventory is None:
        inventory = {b: set(list_slots_in_batch(root, b)) for b in ids}

    raw: list[SetAssembly] = []
    label_counts: dict[str, int] = {}
    for bid in ids:
        for code in SLOT_CODES:
            if code not in inventory.get(bid, set()):
                continue
            lab = set_display_label(bid, code, disambiguate=False)
            label_counts[lab] = label_counts.get(lab, 0) + 1

    for bid in ids:
        for code in SLOT_CODES:
            if code not in inventory.get(bid, set()):
                continue
            base = set_display_label(bid, code, disambiguate=False)
            lab = (
                set_display_label(bid, code, disambiguate=True)
                if label_counts.get(base, 0) > 1
                else base
            )
            raw.append(
                assemble_set(ids, inventory, bid, code, label=lab)
            )
    return raw


def set_assembly_to_dict(s: SetAssembly) -> dict[str, Any]:
    return {
        "id": s.id,
        "label": s.label,
        "anchorBatch": s.anchor_batch,
        "anchorCode": s.anchor_code,
        "slots": [
            ({"batch": r.batch, "code": r.code} if r is not None else None)
            for r in s.slots
        ],
        "substitutions": list(s.substitutions),
    }
