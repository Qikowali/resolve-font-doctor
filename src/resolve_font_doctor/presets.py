from __future__ import annotations

import os
import re
import time
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

from .font_files import read_font_faces_from_bytes
from .font_names import is_plausible_font_name, is_skip_name, normalize_name, pretty_family
from .models import FontFace, FontNeed, PresetRef, ScanReport
from .paths import embedded_dir, is_linux, is_macos, is_windows, platform_label
from .util import safe_filename, sha1_bytes


ProgressFn = Callable[[int, int, str], None]

SETTING_SUFFIXES = {".setting", ".comp"}
ARCHIVE_SUFFIXES = {".drfx", ".zip"}
TEXT_ENTRY_SUFFIXES = {".setting", ".comp", ".txt", ".xml", ".json", ".html", ".htm"}
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}

MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_FONT_BYTES = 80 * 1024 * 1024
MAX_ERRORS = 40


_FONT_INPUT_RE = re.compile(
    r"""(?ix)
    \b(Font|FontName|FontFamily|Typeface|FontFace|SubtitleFont)\s*=\s*
    Input\s*\{\s*
    (?:[^{}]{0,600}?\bValue\s*=\s*)?
    ["']([^"'\r\n]{1,120})["']
    """
)
_FONT_DIRECT_RE = re.compile(
    r"""(?ix)
    \b(Font|FontName|FontFamily|Typeface|FontFace|SubtitleFont)\s*=\s*
    ["']([^"'\r\n]{1,120})["']
    """
)
_CSS_FONT_RE = re.compile(
    r"""(?ix)
    font-family\s*:\s*["']?([^;"'}\r\n]{1,120})
    """
)


@dataclass(frozen=True)
class PresetRoot:
    path: Path
    label: str
    builtin: bool = False


def _env_path(*parts: str) -> Path:
    return Path(os.path.expandvars(os.path.join(*parts)))


def discover_roots(include_builtin: bool = True, extra_roots: Iterable[str] = ()) -> list[PresetRoot]:
    raw: list[PresetRoot] = []
    if is_windows():
        appdata = os.environ.get("APPDATA", "")
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        programfiles = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        raw.extend(
            [
                PresetRoot(Path(appdata) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Templates", "当前用户预设"),
                PresetRoot(Path(appdata) / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Templates", "当前用户预设"),
                PresetRoot(Path(programdata) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Templates", "公共预设"),
                PresetRoot(Path(programdata) / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Templates", "公共预设"),
                PresetRoot(Path(programfiles) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Templates", "达芬奇内置", True),
                PresetRoot(Path(programfiles) / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Templates", "达芬奇内置", True),
            ]
        )
    elif is_macos():
        home = Path.home()
        app_support = "/Library/Application Support/Blackmagic Design/DaVinci Resolve"
        raw.extend(
            [
                PresetRoot(home / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Support/Fusion/Templates", "当前用户预设"),
                PresetRoot(Path(app_support) / "Fusion" / "Templates", "公共预设"),
                PresetRoot(Path(app_support) / "Support" / "Fusion" / "Templates", "公共预设"),
                PresetRoot(Path("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Resources/Fusion/Templates"), "达芬奇内置", True),
                PresetRoot(Path("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Resources/Support/Fusion/Templates"), "达芬奇内置", True),
            ]
        )
    elif is_linux():
        home = Path.home()
        raw.extend(
            [
                PresetRoot(home / ".local/share/DaVinciResolve/Fusion/Templates", "当前用户预设"),
                PresetRoot(home / ".local/share/DaVinciResolve/Support/Fusion/Templates", "当前用户预设"),
                PresetRoot(Path("/opt/resolve/Fusion/Templates"), "公共预设"),
                PresetRoot(Path("/opt/resolve/Support/Fusion/Templates"), "达芬奇内置", True),
            ]
        )
    for value in extra_roots:
        if value and value.strip():
            raw.append(PresetRoot(Path(value).expanduser(), "自定义文件夹"))
    out: list[PresetRoot] = []
    seen: set[str] = set()
    for root in raw:
        if root.builtin and not include_builtin:
            continue
        if not root.path.is_dir():
            continue
        try:
            key = str(root.path.resolve()).casefold()
        except OSError:
            key = str(root.path).casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def _decode_text(data: bytes) -> str:
    if not data:
        return ""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for encoding in ("utf-8", "gb18030", "cp1252"):
        try:
            text = data.decode(encoding)
            if encoding != "utf-8" or text.count("\ufffd") <= max(2, len(text) // 500):
                return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def extract_font_names(text: str) -> list[str]:
    found: dict[str, str] = {}
    for regex in (_FONT_INPUT_RE, _FONT_DIRECT_RE):
        for match in regex.finditer(text):
            value = (match.group(2) or "").strip()
            if not is_plausible_font_name(value) or is_skip_name(value):
                continue
            key = normalize_name(value)
            if key and key not in found:
                found[key] = pretty_family(value)
    for match in _CSS_FONT_RE.finditer(text):
        value = (match.group(1) or "").strip().strip("'\"")
        # font-family can be a comma-separated fallback list; only the first
        # entry is the intended preset font.
        value = value.split(",", 1)[0].strip()
        if not is_plausible_font_name(value) or is_skip_name(value):
            continue
        key = normalize_name(value)
        if key and key not in found:
            found[key] = pretty_family(value)
    return list(found.values())


def _preset_label(root: PresetRoot, path: Path) -> str:
    try:
        rel = path.relative_to(root.path)
    except ValueError:
        rel = Path(path.name)
    label = root.label
    if label == "自定义文件夹":
        label = root.path.name
    return f"{label} / {rel.as_posix()}"


def _iter_disk_files(root: PresetRoot) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {"__MACOSX", ".git", "CacheClip", ".DS_Store"}
    try:
        for dirpath, dirnames, filenames in os.walk(root.path):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
            for filename in filenames:
                if filename.startswith("."):
                    continue
                suffix = Path(filename).suffix.lower()
                if suffix in SETTING_SUFFIXES or suffix in ARCHIVE_SUFFIXES:
                    files.append(Path(dirpath) / filename)
    except OSError:
        pass
    return files


def _looks_like_font_archive(names: list[str]) -> bool:
    return any(Path(n).suffix.lower() in TEXT_ENTRY_SUFFIXES for n in names)


def _extract_embedded(entry_name: str, data: bytes) -> tuple[str | None, list[FontFace]]:
    digest = sha1_bytes(data)
    suffix = Path(entry_name).suffix.lower()
    filename = safe_filename(f"{Path(entry_name).stem}-{digest[:10]}", "embedded") + suffix
    target = embedded_dir() / filename
    try:
        if not target.exists() or target.stat().st_size != len(data):
            target.write_bytes(data)
    except OSError:
        return None, []
    faces = read_font_faces_from_bytes(data, source="embedded", label=entry_name)
    if not faces:
        return str(target), []
    updated = [
        replace(face, path=str(target), source="embedded", file_format=suffix.lstrip("."))
        for face in faces
    ]
    return str(target), updated


def scan_presets(
    roots: list[PresetRoot],
    progress: ProgressFn | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ScanReport:
    started = time.time()
    report = ScanReport(
        roots=[str(r.path) for r in roots],
        platform=platform_label(),
        started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    needs: dict[str, FontNeed] = {}
    embedded_faces: dict[str, FontFace] = {}
    work: list[tuple[PresetRoot, Path]] = []
    for root in roots:
        work.extend((root, path) for path in _iter_disk_files(root))
    total = max(1, len(work))

    def add_usage(root: PresetRoot, label: str, font_name: str, ref: PresetRef) -> None:
        key = normalize_name(font_name)
        if not key:
            return
        need = needs.get(key)
        if need is None:
            need = FontNeed(name=pretty_family(font_name), key=key)
            needs[key] = need
        if not any(
            r.preset == ref.preset and r.path == ref.path and r.archive == ref.archive and r.entry == ref.entry
            for r in need.refs
        ):
            need.refs.append(ref)

    def process_text(
        root: PresetRoot,
        text: str,
        label: str,
        path: str | None,
        archive: str | None,
        entry: str | None,
        is_preset: bool = True,
    ) -> None:
        ref = PresetRef(preset=label, path=path, archive=archive, entry=entry)
        if is_preset:
            report.preset_count += 1
        for font_name in extract_font_names(text):
            add_usage(root, label, font_name, ref)

    for i, (root, path) in enumerate(work, 1):
        if should_stop and should_stop():
            report.errors.append("扫描已取消")
            break
        if progress:
            progress(i - 1, total, f"扫描 {path.name}")
        report.file_count += 1
        suffix = path.suffix.lower()
        if suffix in SETTING_SUFFIXES:
            try:
                data = path.read_bytes()
                if len(data) > MAX_TEXT_BYTES:
                    raise ValueError("文件过大")
                process_text(root, _decode_text(data), _preset_label(root, path), str(path), None, None)
            except Exception as exc:
                if len(report.errors) < MAX_ERRORS:
                    report.errors.append(f"{path}: {exc}")
            continue

        if suffix in ARCHIVE_SUFFIXES:
            report.archive_count += 1
            try:
                with zipfile.ZipFile(path) as zf:
                    infos = zf.infolist()
                    for info in infos:
                        if should_stop and should_stop():
                            break
                        if info.is_dir() or info.filename.startswith("__MACOSX/"):
                            continue
                        entry_suffix = Path(info.filename).suffix.lower()
                        if entry_suffix in FONT_SUFFIXES:
                            if info.file_size <= MAX_FONT_BYTES:
                                try:
                                    font_data = zf.read(info)
                                    font_path, faces = _extract_embedded(info.filename, font_data)
                                    for face in faces:
                                        key = (face.path or "", face.face_index, face.full_name)
                                        embedded_faces[str(key)] = face
                                    if font_path and faces:
                                        report.embedded_font_count = len(embedded_faces)
                                except Exception:
                                    pass
                            continue
                        if entry_suffix not in TEXT_ENTRY_SUFFIXES:
                            continue
                        if info.file_size > MAX_TEXT_BYTES:
                            continue
                        try:
                            raw = zf.read(info)
                        except Exception as exc:
                            if len(report.errors) < MAX_ERRORS:
                                report.errors.append(f"{path.name}::{info.filename}: {exc}")
                            continue
                        label = f"{path.stem} / {info.filename}"
                        process_text(
                            root,
                            _decode_text(raw),
                            label,
                            str(path),
                            str(path),
                            info.filename,
                            is_preset=entry_suffix in SETTING_SUFFIXES,
                        )
            except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
                if len(report.errors) < MAX_ERRORS:
                    report.errors.append(f"{path}: {exc}")
            continue

    report.duration = time.time() - started
    report.needs = sorted(needs.values(), key=lambda n: (-len(n.refs), n.name.casefold()))
    # Attach embedded fonts that match a requested family.
    for need in report.needs:
        for face in embedded_faces.values():
            if _face_matches(face, need.name):
                need.embedded_faces.append(face)
    if progress:
        progress(total, total, "扫描完成")
    return report


def _face_matches(face: FontFace, requested: str) -> bool:
    from .font_names import candidate_variants

    variants = set(candidate_variants(requested, include_width=False))
    for name in face.all_names():
        if variants.intersection(candidate_variants(name, include_width=False)):
            return True
    return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False
