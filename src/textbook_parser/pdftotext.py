from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def find_pdftotext() -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise FileNotFoundError(
            "未在 PATH 中找到 pdftotext，请安装 Poppler 并将其 bin 加入 PATH。"
        )
    return exe


def run_pdftotext(
    pdf: Path,
    out_txt: Path,
    *,
    enc: str = "UTF-8",
    layout: bool = True,
    extra_args: list[str] | None = None,
) -> None:
    pdf = pdf.resolve()
    out_txt = out_txt.resolve()
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF 不存在: {pdf}")

    cmd = [find_pdftotext(), "-enc", enc]
    if layout:
        cmd.append("-layout")
    if extra_args:
        cmd.extend(extra_args)
    cmd.extend([str(pdf), str(out_txt)])

    subprocess.run(cmd, check=True)
