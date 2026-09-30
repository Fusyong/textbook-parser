from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Literal

# Xpdf / Poppler 共用的文本抽取模式。
# layout：保留物理版式（现有 material/*.md 默认）；
# raw：按 PDF 内容流顺序（双栏表常呈「先整左栏、再整右栏」）；
# default：不传版式开关，尽量按阅读顺序「拆栏」。
TextMode = Literal["layout", "raw", "default", "simple", "simple2", "table"]

_MODE_FLAGS: dict[str, list[str]] = {
    "layout": ["-layout"],
    "raw": ["-raw"],
    "default": [],
    "simple": ["-simple"],
    "simple2": ["-simple2"],
    "table": ["-table"],
}


def find_pdftotext() -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise FileNotFoundError(
            "未在 PATH 中找到 pdftotext，请安装 Poppler/Xpdf 并将其 bin 加入 PATH。"
        )
    return exe


def run_pdftotext(
    pdf: Path,
    out_txt: Path,
    *,
    enc: str = "UTF-8",
    layout: bool | None = None,
    text_mode: TextMode | str | None = None,
    first_page: int | None = None,
    last_page: int | None = None,
    extra_args: list[str] | None = None,
) -> None:
    """
    调用 pdftotext。

    text_mode 优先；未指定时 layout=True→layout，layout=False→default（兼容旧调用）。
    """
    pdf = pdf.resolve()
    out_txt = out_txt.resolve()
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF 不存在: {pdf}")

    if text_mode is None:
        mode: str = "layout" if (layout is None or layout) else "default"
    else:
        mode = str(text_mode).strip().lower()
    if mode not in _MODE_FLAGS:
        raise ValueError(
            f"未知 text_mode={mode!r}，可选: {', '.join(sorted(_MODE_FLAGS))}"
        )

    cmd = [find_pdftotext(), "-enc", enc, "-q"]
    cmd.extend(_MODE_FLAGS[mode])
    if first_page is not None:
        cmd.extend(["-f", str(int(first_page))])
    if last_page is not None:
        cmd.extend(["-l", str(int(last_page))])
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend([str(pdf), str(out_txt)])

    subprocess.run(cmd, check=True)


def sidecar_path_for_mode(layout_text: Path, text_mode: str) -> Path:
    """
    非 layout 模式的旁路输出路径，永不指向正式 layout .md。
    例：…/一年级上册.md + raw → …/一年级上册.raw.txt
    """
    mode = str(text_mode).strip().lower()
    if mode in ("", "layout"):
        return layout_text
    stem = layout_text.name
    if stem.lower().endswith(".md"):
        stem = stem[:-3]
    elif stem.lower().endswith(".txt"):
        stem = stem[:-4]
    return layout_text.with_name(f"{stem}.{mode}.txt")
