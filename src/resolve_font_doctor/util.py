from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


_SAFE_FILE_RE = re.compile(r"[^0-9A-Za-z._\-]+")


def safe_filename(name: str, fallback: str = "font", max_len: int = 120) -> str:
    name = name.strip().replace("\x00", "")
    cleaned = _SAFE_FILE_RE.sub("_", name).strip(" ._")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_len]


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sha1_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def human_size(num: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def open_path(path: str | Path) -> None:
    """Open a file/folder with the platform's default handler."""
    p = str(path)
    if os.name == "nt":
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


def is_process_running(executable_names: list[str]) -> bool:
    """Best-effort check without third-party dependencies."""
    names = {n.casefold() for n in executable_names}
    try:
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            out = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=5,
                startupinfo=startupinfo,
            ).stdout
            for line in out.splitlines():
                first = line.split(",", 1)[0].strip().strip('"').casefold()
                if first in names:
                    return True
            return False
        out = subprocess.run(
            ["ps", "-A", "-o", "comm="],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
        ).stdout
        for line in out.splitlines():
            if Path(line.strip()).name.casefold() in names:
                return True
    except Exception:
        pass
    return False


def resolve_resolve_process() -> bool:
    if os.name == "nt":
        return is_process_running(["Resolve.exe"])
    if sys.platform == "darwin":
        return is_process_running(["DaVinci Resolve", "Resolve"])
    return is_process_running(["resolve", "davinci-resolve"])
