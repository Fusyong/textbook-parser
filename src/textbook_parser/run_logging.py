from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import IO, TextIO


class _TeeStream:
    """同时写入控制台与日志文件（与 sys.stdout/sys.stderr 兼容的最小接口）。"""

    __slots__ = ("_primary", "_log")

    def __init__(self, primary: TextIO, log: TextIO) -> None:
        self._primary = primary
        self._log = log

    def write(self, s: str) -> int:
        n = len(s)
        try:
            self._primary.write(s)
            self._primary.flush()
        except BrokenPipeError:
            raise
        except OSError:
            pass
        try:
            self._log.write(s)
            self._log.flush()
        except OSError:
            pass
        return n

    def flush(self) -> None:
        try:
            self._primary.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            self._log.flush()
        except OSError:
            pass

    def isatty(self) -> bool:
        try:
            return self._primary.isatty()
        except Exception:
            return False

    @property
    def encoding(self) -> str:
        enc = getattr(self._primary, "encoding", None)
        return str(enc) if enc else "utf-8"

    def __getattr__(self, item: str):
        return getattr(self._primary, item)


def install_run_logging(
    log_path: Path,
    *,
    header_lines: Iterable[str] | None = None,
) -> Callable[[], None]:
    """
    将 sys.stdout / sys.stderr 重定向为「控制台 + 日志文件」双写。
    返回的函数须在结束时调用（通常在 finally 中），以关闭文件并还原标准流。
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f: IO[str] = open(log_path, "w", encoding="utf-8", newline="")

    if header_lines:
        for line in header_lines:
            log_f.write(line)
            if not line.endswith("\n"):
                log_f.write("\n")
        log_f.flush()

    saved_out = sys.stdout
    saved_err = sys.stderr
    sys.stdout = _TeeStream(saved_out, log_f)
    sys.stderr = _TeeStream(saved_err, log_f)

    def _restore() -> None:
        sys.stdout = saved_out
        sys.stderr = saved_err
        try:
            log_f.close()
        except OSError:
            pass

    return _restore
