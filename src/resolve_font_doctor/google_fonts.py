from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import __version__
from .font_files import read_font_faces_from_file
from .font_names import normalize_name, pretty_family, slug_for_google, strip_style_and_noise
from .models import FontFile, FontPackage
from .paths import cache_dir, downloads_dir
from .util import safe_filename


ProgressFn = Callable[[int, int, str], None]
USER_AGENT = f"ResolveFontDoctor/{__version__} (+https://github.com/; font manager)"
META_TTL = 7 * 24 * 3600
MAX_FILE_BYTES = 90 * 1024 * 1024
MAX_TOTAL_BYTES = 320 * 1024 * 1024

RAW_BASES = (
    "https://cdn.jsdelivr.net/gh/google/fonts@main",
    "https://raw.githubusercontent.com/google/fonts/main",
)
GOOGLE_DIRS = ("ofl", "apache", "ufl")
CSS_URLS = (
    "https://fonts.googleapis.com/css2?family=",
    "https://fonts.font.im/css?family=",
    "https://fonts.loli.net/css?family=",
)


@dataclass
class LookupResult:
    package: FontPackage | None = None
    error: str = ""
    cached: bool = False
    offline: bool = False


class DownloadError(RuntimeError):
    pass


def _http_get(url: str, timeout: float = 30.0, max_bytes: int | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise DownloadError(f"HTTP {response.status}")
            if max_bytes is not None:
                length = response.headers.get("content-length")
                if length and int(length) > max_bytes:
                    raise DownloadError("文件过大")
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise DownloadError("文件过大")
                return data
            return response.read()
    except urllib.error.HTTPError as exc:
        raise DownloadError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DownloadError(f"网络连接失败：{exc.reason}") from exc
    except TimeoutError as exc:
        raise DownloadError("请求超时") from exc
    except OSError as exc:
        raise DownloadError(f"网络连接失败：{exc}") from exc


def _meta_cache_path(slug: str) -> Path:
    p = cache_dir() / "google_meta"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{safe_filename(slug)}.json"


def _read_cached_meta(slug: str) -> dict | None:
    path = _meta_cache_path(slug)
    try:
        if time.time() - path.stat().st_mtime > META_TTL:
            return None
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _write_cached_meta(slug: str, payload: dict) -> None:
    path = _meta_cache_path(slug)
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    except OSError:
        pass


def _field(block: str, name: str) -> str:
    match = re.search(rf'(?mi)^\s*{re.escape(name)}\s*:\s*"([^"]*)"', block)
    return match.group(1) if match else ""


def _clean_text(value: str) -> str:
    # Google Fonts metadata is UTF-8 and may contain escaped newlines.
    return value.replace("\\n", " ").replace("\\\"", '"').strip()


def parse_metadata(text: str) -> dict:
    top = text.split("fonts {", 1)[0]
    name = _clean_text(_field(top, "name"))
    license_name = _clean_text(_field(top, "license"))
    blocks = re.findall(r"(?s)fonts\s*\{(.*?)\}", text)
    fonts: list[dict] = []
    for block in blocks:
        filename = _clean_text(_field(block, "filename"))
        if not filename:
            continue
        fonts.append(
            {
                "name": _clean_text(_field(block, "name")) or name,
                "style": _clean_text(_field(block, "style")),
                "weight": _clean_text(_field(block, "weight")),
                "filename": filename,
                "post_script_name": _clean_text(_field(block, "post_script_name")),
            }
        )
    return {"name": name, "license": license_name, "fonts": fonts}


class GoogleFontsProvider:
    def __init__(self) -> None:
        self._lookup_cache: dict[str, LookupResult] = {}

    def lookup(self, family: str, use_cache: bool = True) -> LookupResult:
        key = normalize_name(family)
        if use_cache and key in self._lookup_cache:
            return self._lookup_cache[key]
        slug = slug_for_google(family)
        if not slug:
            result = LookupResult(error="字体名称无法用于在线检索")
            self._lookup_cache[key] = result
            return result

        cached = _read_cached_meta(slug) if use_cache else None
        if cached:
            package = self._package_from_meta(cached, slug, family)
            if package:
                result = LookupResult(package=package, cached=True)
                self._lookup_cache[key] = result
                return result

        errors: list[str] = []
        network_error = False
        for directory in GOOGLE_DIRS:
            for base in RAW_BASES:
                meta_url = f"{base}/{directory}/{slug}/METADATA.pb"
                try:
                    raw = _http_get(meta_url, timeout=20, max_bytes=2 * 1024 * 1024)
                    text = raw.decode("utf-8", errors="replace")
                    meta = parse_metadata(text)
                    if not meta.get("fonts"):
                        continue
                    meta["_directory"] = directory
                    meta["_slug"] = slug
                    _write_cached_meta(slug, meta)
                    package = self._package_from_meta(meta, slug, family)
                    if package:
                        result = LookupResult(package=package)
                        self._lookup_cache[key] = result
                        return result
                except DownloadError as exc:
                    message = str(exc)
                    if message.startswith("网络") or "超时" in message:
                        network_error = True
                    if message not in errors:
                        errors.append(f"{directory}: {message}")
                    continue

        # Metadata is sometimes unavailable or the family lives in a different
        # directory. The CSS endpoint is a useful second source for small,
        # single-file Latin families.
        css_package = self._lookup_css(family)
        if css_package:
            result = LookupResult(package=css_package)
            self._lookup_cache[key] = result
            return result

        detail = "；".join(errors[-2:]) if errors else "Google Fonts 中未找到该字体"
        result = LookupResult(error=detail, offline=network_error)
        return result

    def _package_from_meta(self, meta: dict, slug: str, family: str) -> FontPackage | None:
        meta_name = meta.get("name") or family
        if normalize_name(meta_name) != normalize_name(family):
            # Allow metadata names that only differ in a style suffix.
            if strip_style_and_noise(meta_name) != strip_style_and_noise(family):
                return None
        directory = meta.get("_directory", "ofl")
        files: list[FontFile] = []
        seen: set[str] = set()
        for item in meta.get("fonts", []):
            filename = item.get("filename", "")
            if not filename or "/" in filename or "\\" in filename:
                continue
            if filename in seen:
                continue
            suffix = Path(filename).suffix.lower()
            if suffix not in (".ttf", ".otf"):
                continue
            seen.add(filename)
            quoted = urllib.parse.quote(filename, safe="[]")
            url = f"{RAW_BASES[0]}/{directory}/{slug}/{quoted}"
            files.append(FontFile(filename=filename, url=url))
        if not files:
            return None
        return FontPackage(
            family=pretty_family(meta_name),
            provider="Google Fonts",
            license=meta.get("license", ""),
            files=files,
            page_url=f"https://fonts.google.com/specimen/{urllib.parse.quote(meta_name)}",
            source_url=f"https://github.com/google/fonts/tree/main/{directory}/{slug}",
            note="开源字体，可自动下载",
        )

    def _lookup_css(self, family: str) -> FontPackage | None:
        css = ""
        for base in CSS_URLS:
            url = base + urllib.parse.quote_plus(family)
            try:
                css = _http_get(url, timeout=20, max_bytes=1024 * 1024).decode("utf-8", errors="replace")
                if css:
                    break
            except DownloadError:
                continue
        if not css:
            return None
        blocks = re.findall(r"(?s)@font-face\s*\{(.*?)\}", css)
        if not blocks or len(blocks) > 8:
            return None
        files: list[FontFile] = []
        for index, block in enumerate(blocks, 1):
            if re.search(r"unicode-range\s*:", block):
                # A family split into unicode ranges cannot be installed as one
                # usable Windows font; skip CJK subset delivery.
                return None
            match = re.search(r"url\((https?://[^)]+)\)\s*format\(['\"]?truetype", block)
            if not match:
                continue
            weight = re.search(r"font-weight\s*:\s*([0-9]+)", block)
            weight_text = weight.group(1) if weight else str(index)
            suffix = ".ttf"
            filename = f"{safe_filename(family)}-{weight_text}{suffix}"
            files.append(FontFile(filename=filename, url=match.group(1)))
        if not files:
            return None
        return FontPackage(
            family=pretty_family(family),
            provider="Google Fonts",
            license="OFL",
            files=files,
            page_url=f"https://fonts.google.com/specimen/{urllib.parse.quote(family)}",
            source_url="https://fonts.google.com/",
            note="通过 Google Fonts CSS 获取",
        )

    def download(
        self,
        package: FontPackage,
        progress: ProgressFn | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[list[str], list[str]]:
        folder = downloads_dir() / safe_filename(package.family, "google-font")
        folder.mkdir(parents=True, exist_ok=True)
        local_paths: list[str] = []
        errors: list[str] = []
        total_bytes = 0
        total = max(1, len(package.files))
        for index, font_file in enumerate(package.files, 1):
            if should_stop and should_stop():
                errors.append("下载已取消")
                break
            if progress:
                progress(index - 1, total, f"下载 {package.family} / {font_file.filename}")
            target = folder / safe_filename(font_file.filename, f"font-{index}.ttf")
            if target.exists() and target.stat().st_size > 1024:
                if read_font_faces_from_file(target):
                    local_paths.append(str(target))
                    continue
                try:
                    target.unlink()
                except OSError:
                    pass
            data: bytes | None = None
            last_error = ""
            for base in (font_file.url, self._mirror_url(font_file.url)):
                if not base:
                    continue
                try:
                    data = _http_get(base, timeout=90, max_bytes=MAX_FILE_BYTES)
                    break
                except DownloadError as exc:
                    last_error = str(exc)
            if data is None:
                errors.append(f"{font_file.filename}: {last_error or '下载失败'}")
                continue
            total_bytes += len(data)
            if total_bytes > MAX_TOTAL_BYTES:
                errors.append("该字体包超过下载体积上限，已停止")
                break
            tmp = target.with_suffix(target.suffix + ".part")
            try:
                tmp.write_bytes(data)
                os.replace(tmp, target)
            except OSError as exc:
                errors.append(f"{font_file.filename}: 保存失败 {exc}")
                continue
            if not read_font_faces_from_file(target):
                errors.append(f"{font_file.filename}: 下载内容不是有效字体")
                try:
                    target.unlink()
                except OSError:
                    pass
                continue
            local_paths.append(str(target))
        self._save_license(package, folder)
        return local_paths, errors

    @staticmethod
    def _mirror_url(url: str) -> str:
        marker = "cdn.jsdelivr.net/gh/google/fonts@main/"
        if marker in url:
            return url.replace("https://cdn.jsdelivr.net/gh/google/fonts@main/", "https://raw.githubusercontent.com/google/fonts/main/")
        marker = "raw.githubusercontent.com/google/fonts/main/"
        if marker in url:
            return url.replace("https://raw.githubusercontent.com/google/fonts/main/", "https://cdn.jsdelivr.net/gh/google/fonts@main/")
        return ""

    def _save_license(self, package: FontPackage, folder: Path) -> None:
        license_name = "OFL.txt" if package.license.upper() == "OFL" else "LICENSE.txt"
        target = folder / license_name
        if target.exists():
            return
        source = package.source_url.replace("https://github.com/google/fonts/tree/main/", "https://raw.githubusercontent.com/google/fonts/main/")
        if not source.startswith("https://raw.githubusercontent.com/"):
            return
        for name in ("OFL.txt", "LICENSE.txt", "APACHE.txt", "UFL.txt"):
            try:
                data = _http_get(f"{source}/{name}", timeout=15, max_bytes=256 * 1024)
                target.write_bytes(data)
                return
            except (DownloadError, OSError):
                continue
