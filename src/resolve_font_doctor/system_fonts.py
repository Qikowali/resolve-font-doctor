from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path

from .font_files import read_font_faces_from_file
from .font_names import (
    candidate_variants,
    normalize_name,
    similarity,
    strip_style,
    strip_style_and_noise,
    strip_width,
)
from .models import FontFace
from .paths import is_macos, is_windows, system_font_dirs, windows_fonts_dir


FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}
_REG_SUFFIX_RE = re.compile(
    r"\s*\((?:TrueType|OpenType|Type\s*1|All\s*Res|PostScript).*?\)\s*$", re.IGNORECASE
)


def _resolve_registry_path(value: str) -> Path | None:
    value = value.strip().strip('"')
    if not value:
        return None
    p = Path(value)
    if not p.is_absolute():
        p = windows_fonts_dir() / value
    # Some entries are comma separated lists.
    if not p.exists() and "," in value:
        p = windows_fonts_dir() / value.split(",", 1)[0].strip()
    return p


def _windows_registry_entries() -> list[tuple[Path, str, str]]:
    if not is_windows():
        return []
    try:
        import winreg
    except ImportError:
        return []
    entries: list[tuple[Path, str, str]] = []
    locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts", "system"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts", "user"),
    ]
    for hive, subkey, source in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                index = 0
                while True:
                    try:
                        display_name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if not isinstance(value, str):
                        continue
                    path = _resolve_registry_path(value)
                    if not path:
                        continue
                    cleaned = _REG_SUFFIX_RE.sub("", display_name).strip()
                    if cleaned:
                        entries.append((path, cleaned, source))
        except OSError:
            continue
    return entries


class FontMatch:
    __slots__ = ("face", "kind", "score")

    def __init__(self, face: FontFace, kind: str, score: float = 1.0) -> None:
        self.face = face
        self.kind = kind
        self.score = score

    def __repr__(self) -> str:
        return f"FontMatch({self.face.family!r}, {self.kind!r})"


class FontIndex:
    """Index of fonts installed for the current user (system + per-user)."""

    def __init__(self, faces: list[FontFace] | None = None) -> None:
        self.faces: list[FontFace] = []
        self._by_key: dict[str, list[FontFace]] = {}
        self._by_key_widthless: dict[str, list[FontFace]] = {}
        self._seen: set[tuple[str, int, str]] = set()
        for face in faces or []:
            self.add(face)
        self._rebuild()

    @classmethod
    def build(cls) -> "FontIndex":
        index = cls()
        registry_entries = _windows_registry_entries()
        registered_paths: set[str] = set()
        for path, _display_name, _source in registry_entries:
            try:
                registered_paths.add(str(path.resolve()).casefold())
            except OSError:
                registered_paths.add(str(path).casefold())

        seen_paths: set[str] = set()
        for directory, source in system_font_dirs():
            try:
                iterator = os.scandir(directory)
            except OSError:
                continue
            with iterator:
                for entry in iterator:
                    try:
                        if not entry.is_file(follow_symlinks=True):
                            continue
                    except OSError:
                        continue
                    suffix = Path(entry.name).suffix.lower()
                    if suffix not in FONT_SUFFIXES:
                        continue
                    try:
                        real = str(Path(entry.path).resolve()).casefold()
                    except OSError:
                        real = entry.path.casefold()
                    if real in seen_paths:
                        continue
                    # A file merely copied into the per-user font folder is not
                    # loaded by Windows unless it is also registered. Do not
                    # report such files as installed.
                    if is_windows() and source == "user" and real not in registered_paths:
                        continue
                    seen_paths.add(real)
                    for face in read_font_faces_from_file(entry.path, source=source):
                        index.add(face)

        registry_aliases: dict[tuple[str, int], list[str]] = {}
        for path, display_name, source in registry_entries:
            if not path.exists() or path.suffix.lower() not in FONT_SUFFIXES:
                continue
            try:
                real = str(path.resolve()).casefold()
            except OSError:
                real = str(path).casefold()
            faces = read_font_faces_from_file(path, source=source)
            for face in faces:
                index.add(face)
                registry_aliases.setdefault((real, face.face_index), []).append(display_name)

        if registry_aliases:
            updated: list[FontFace] = []
            for face in index.faces:
                try:
                    real = str(Path(face.path).resolve()).casefold() if face.path else ""
                except OSError:
                    real = (face.path or "").casefold()
                aliases = registry_aliases.get((real, face.face_index), [])
                if aliases:
                    merged = list(face.aliases)
                    for alias in aliases:
                        if alias and alias not in merged and alias != face.family:
                            merged.append(alias)
                    face = replace(face, aliases=tuple(merged))
                updated.append(face)
            index.faces = []
            index._seen.clear()
            for face in updated:
                index.add(face)
            index._rebuild()
        return index

    def add(self, face: FontFace) -> None:
        key = (face.path or face.full_name or face.family, face.face_index, face.full_name)
        if key in self._seen:
            return
        self._seen.add(key)
        self.faces.append(face)

    def _rebuild(self) -> None:
        self._by_key = {}
        self._by_key_widthless = {}
        for face in self.faces:
            names = face.all_names()
            for name in names:
                if not name:
                    continue
                for key in (normalize_name(name), strip_style(name), strip_style_and_noise(name)):
                    if not key:
                        continue
                    bucket = self._by_key.setdefault(key, [])
                    if face not in bucket:
                        bucket.append(face)
                # Width descriptors are a last-resort variant for suggestions.
                widthless = strip_width(name)
                if widthless:
                    bucket = self._by_key_widthless.setdefault(widthless, [])
                    if face not in bucket:
                        bucket.append(face)
        for bucket in self._by_key.values():
            bucket.sort(key=lambda f: (
                f.source != "user",
                0 if (f.subfamily or "").casefold() in ("regular", "book", "normal", "") else 1,
                abs((f.weight or 400) - 400),
                not f.is_variable,
                f.family.casefold(),
            ))
        for bucket in self._by_key_widthless.values():
            bucket.sort(key=lambda f: (
                f.source != "user",
                0 if (f.subfamily or "").casefold() in ("regular", "book", "normal", "") else 1,
                abs((f.weight or 400) - 400),
                f.family.casefold(),
            ))

    def find(self, requested: str) -> FontMatch | None:
        for idx, key in enumerate(candidate_variants(requested, include_width=False)):
            bucket = self._by_key.get(key)
            if bucket:
                kind = "exact" if idx == 0 else "alias"
                return FontMatch(bucket[0], kind, 1.0)
        return None

    def suggest(self, requested: str) -> FontMatch | None:
        keys = candidate_variants(requested, include_width=True)
        for idx, key in enumerate(keys):
            bucket = self._by_key_widthless.get(key)
            if bucket and bucket[0].family.casefold() != requested.casefold():
                return FontMatch(bucket[0], "near", 0.8 if idx == len(keys) - 1 else 0.9)
        req_key = normalize_name(requested)
        best: FontFace | None = None
        best_score = 0.0
        for face in self.faces:
            score = similarity(req_key, normalize_name(face.family))
            if score > best_score:
                best_score = score
                best = face
        if best is not None and best_score >= 0.9 and len(req_key) >= 5:
            return FontMatch(best, "fuzzy", best_score)
        return None

    def all_families(self) -> list[str]:
        names = {face.family for face in self.faces if face.family}
        return sorted(names, key=str.casefold)

    def __len__(self) -> int:
        return len(self.faces)
