from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


APP_DIR_NAME = "ResolveFontDoctor"


def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def app_data_dir() -> Path:
    """Writable per-user application directory."""
    if is_windows():
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif is_macos():
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    p = base / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = app_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def downloads_dir() -> Path:
    p = cache_dir() / "fonts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def embedded_dir() -> Path:
    p = cache_dir() / "embedded"
    p.mkdir(parents=True, exist_ok=True)
    return p


def reports_dir() -> Path:
    p = app_data_dir() / "reports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def manual_fonts_dir() -> Path:
    p = app_data_dir() / "手动添加字体"
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def log_path() -> Path:
    return app_data_dir() / "font-doctor.log"


def windows_fonts_dir() -> Path:
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def windows_user_fonts_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "Microsoft" / "Windows" / "Fonts"


def mac_user_fonts_dir() -> Path:
    return Path.home() / "Library" / "Fonts"


def linux_user_fonts_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "fonts" / APP_DIR_NAME


def system_font_dirs() -> list[tuple[Path, str]]:
    """Return (directory, source label) pairs that exist on this machine."""
    candidates: list[tuple[Path, str]] = []
    if is_windows():
        candidates.append((windows_fonts_dir(), "system"))
        candidates.append((windows_user_fonts_dir(), "user"))
    elif is_macos():
        candidates.extend(
            [
                (Path("/System/Library/Fonts"), "system"),
                (Path("/System/Library/Fonts/Supplemental"), "system"),
                (Path("/Library/Fonts"), "system"),
                (mac_user_fonts_dir(), "user"),
            ]
        )
    else:
        candidates.extend(
            [
                (Path.home() / ".fonts", "user"),
                (Path.home() / ".local" / "share" / "fonts", "user"),
                (Path("/usr/local/share/fonts"), "system"),
                (Path("/usr/share/fonts"), "system"),
            ]
        )
    seen: set[str] = set()
    out: list[tuple[Path, str]] = []
    for path, source in candidates:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        out.append((path, source))
    return out


def platform_label() -> str:
    if is_windows():
        return f"Windows {platform.release()}"
    if is_macos():
        return f"macOS {platform.mac_ver()[0]}"
    return f"Linux {platform.release()}"
