from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .font_files import read_font_faces_from_file
from .models import FontFace
from .paths import (
    is_linux,
    is_macos,
    is_windows,
    linux_user_fonts_dir,
    mac_user_fonts_dir,
    windows_user_fonts_dir,
)
from .util import sha1_file


ProgressFn = Callable[[int, int, str], None]
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _clean_filename(name: str) -> str:
    cleaned = _INVALID_FILENAME.sub("_", Path(name).name).strip(" .")
    return cleaned or "font.ttf"


def _windows_add_font(path: Path) -> bool:
    try:
        add = ctypes.windll.gdi32.AddFontResourceW
        add.argtypes = [ctypes.c_wchar_p]
        add.restype = ctypes.c_int
        return bool(add(str(path)))
    except Exception:
        return False


def _windows_broadcast_font_change() -> None:
    try:
        hwnd_broadcast = 0xFFFF
        wm_fontchange = 0x001D
        ctypes.windll.user32.SendMessageW(hwnd_broadcast, wm_fontchange, 0, 0)
    except Exception:
        pass


def _windows_register(path: Path, face: FontFace) -> tuple[bool, str]:
    try:
        import winreg
    except ImportError:
        return False, "当前 Python 缺少 winreg 模块"
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
    except OSError as exc:
        return False, f"无法写入字体注册表：{exc}"
    path_text = str(path)
    try:
        existing_names: list[str] = []
        index = 0
        while True:
            try:
                value_name, value_data, _kind = winreg.EnumValue(key, index)
            except OSError:
                break
            index += 1
            if isinstance(value_data, str) and value_data.casefold() == path_text.casefold():
                winreg.CloseKey(key)
                return True, "已注册"
            existing_names.append(value_name)
        base_name = f"{face.full_name or face.family} (TrueType)"
        value_name = base_name
        suffix = 2
        existing_lower = {n.casefold() for n in existing_names}
        while value_name.casefold() in existing_lower:
            value_name = f"{base_name} {suffix}"
            suffix += 1
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, path_text)
        winreg.CloseKey(key)
        return True, "已写入注册表"
    except OSError as exc:
        try:
            winreg.CloseKey(key)
        except OSError:
            pass
        return False, f"写入字体注册表失败：{exc}"


@dataclass
class InstalledFont:
    source: str
    destination: str
    family: str
    face: FontFace | None = None


@dataclass
class InstallResult:
    installed: list[InstalledFont] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    restart_required: bool = True

    @property
    def count(self) -> int:
        return len(self.installed)


class FontInstaller:
    def __init__(self, known_faces: Iterable[FontFace] = ()) -> None:
        self.known: set[tuple[str, str]] = set()
        for face in known_faces:
            self._remember(face)

    def _remember(self, face: FontFace) -> None:
        family = (face.family or "").casefold()
        style = (face.subfamily or "").casefold()
        self.known.add((family, style))
        if face.postscript_name:
            self.known.add(("ps:" + face.postscript_name.casefold(), ""))

    def _already_known(self, face: FontFace) -> bool:
        family = (face.family or "").casefold()
        style = (face.subfamily or "").casefold()
        if (family, style) in self.known:
            return True
        if face.postscript_name and ("ps:" + face.postscript_name.casefold(), "") in self.known:
            return True
        return False

    def install(
        self,
        paths: Iterable[str | Path],
        progress: ProgressFn | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> InstallResult:
        unique_paths: list[Path] = []
        seen_hashes: set[str] = set()
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or path.suffix.lower() not in FONT_SUFFIXES:
                continue
            try:
                digest = sha1_file(path)
            except OSError:
                continue
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            unique_paths.append(path)

        result = InstallResult()
        total = max(1, len(unique_paths))
        for index, source in enumerate(unique_paths, 1):
            if should_stop and should_stop():
                result.failed.append((str(source), "操作已取消"))
                break
            if progress:
                progress(index - 1, total, f"安装 {source.name}")
            faces = read_font_faces_from_file(source, source="downloaded")
            if not faces:
                result.failed.append((str(source), "无法读取字体信息"))
                continue
            face = faces[0]
            if self._already_known(face):
                result.skipped.append((str(source), f"{face.family} 已安装"))
                continue
            try:
                if is_windows():
                    self._install_windows(source, faces, result)
                elif is_macos():
                    self._install_macos(source, faces, result)
                elif is_linux():
                    self._install_linux(source, faces, result)
                else:
                    result.failed.append((str(source), "当前系统不受支持"))
            except Exception as exc:
                result.failed.append((str(source), str(exc)))
        if is_windows() and result.installed:
            _windows_broadcast_font_change()
        if progress:
            progress(total, total, "字体安装完成")
        return result

    def _install_windows(self, source: Path, faces: list[FontFace], result: InstallResult) -> None:
        dest_dir = windows_user_fonts_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        base_name = _clean_filename(source.name)
        dest = dest_dir / base_name
        if dest.exists() and dest.resolve() != source.resolve():
            try:
                if sha1_file(dest) != sha1_file(source):
                    stem, suffix = dest.stem, dest.suffix
                    counter = 2
                    while dest.exists():
                        dest = dest_dir / f"{stem}-{counter}{suffix}"
                        counter += 1
            except OSError:
                pass
        if dest.resolve() != source.resolve():
            shutil.copy2(source, dest)
        registered, message = _windows_register(dest, faces[0])
        if not registered:
            # Do not leave an unregistered copy behind: Windows would not load
            # it after the next sign-in, and the next scan could mistake the
            # file for a working installation.
            try:
                if dest.resolve() != source.resolve():
                    dest.unlink(missing_ok=True)
            except OSError:
                pass
            result.failed.append((str(source), message))
            return
        loaded = _windows_add_font(dest)
        result.installed.append(
            InstalledFont(str(source), str(dest), faces[0].family, faces[0])
        )
        self._remember(faces[0])
        if not loaded:
            # The registry entry is enough after the next sign-in; note it in
            # the result rather than failing the whole installation.
            result.restart_required = True

    def _install_macos(self, source: Path, faces: list[FontFace], result: InstallResult) -> None:
        dest_dir = mac_user_fonts_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = self._unique_dest(dest_dir, source)
        if dest.resolve() != source.resolve():
            shutil.copy2(source, dest)
        result.installed.append(InstalledFont(str(source), str(dest), faces[0].family, faces[0]))
        self._remember(faces[0])

    def _install_linux(self, source: Path, faces: list[FontFace], result: InstallResult) -> None:
        dest_dir = linux_user_fonts_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = self._unique_dest(dest_dir, source)
        if dest.resolve() != source.resolve():
            shutil.copy2(source, dest)
        try:
            subprocess.run(
                ["fc-cache", "-f", str(dest_dir)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        result.installed.append(InstalledFont(str(source), str(dest), faces[0].family, faces[0]))
        self._remember(faces[0])

    @staticmethod
    def _unique_dest(dest_dir: Path, source: Path) -> Path:
        dest = dest_dir / _clean_filename(source.name)
        if dest.exists():
            try:
                if sha1_file(dest) == sha1_file(source):
                    return dest
            except OSError:
                pass
            stem, suffix = dest.stem, dest.suffix
            counter = 2
            while dest.exists():
                dest = dest_dir / f"{stem}-{counter}{suffix}"
                counter += 1
        return dest
