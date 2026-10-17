from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Overall font states used by the UI and reports.
STATUS_INSTALLED = "installed"
STATUS_FIXED = "fixed"
STATUS_MISSING = "missing"
STATUS_EMBEDDED = "embedded"
STATUS_DOWNLOADABLE = "downloadable"
STATUS_MANUAL = "manual"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

STATUS_LABELS = {
    STATUS_INSTALLED: "已安装",
    STATUS_FIXED: "已自动安装",
    STATUS_MISSING: "缺失",
    STATUS_EMBEDDED: "预设内置",
    STATUS_DOWNLOADABLE: "可自动下载",
    STATUS_MANUAL: "需手动获取",
    STATUS_SKIPPED: "已跳过",
    STATUS_FAILED: "处理失败",
}

STATUS_COLORS = {
    STATUS_INSTALLED: "#15803d",
    STATUS_FIXED: "#0f766e",
    STATUS_MISSING: "#b91c1c",
    STATUS_EMBEDDED: "#0369a1",
    STATUS_DOWNLOADABLE: "#0f766e",
    STATUS_MANUAL: "#b45309",
    STATUS_SKIPPED: "#6b7280",
    STATUS_FAILED: "#b91c1c",
}

PROBLEM_STATUSES = {
    STATUS_MISSING,
    STATUS_EMBEDDED,
    STATUS_DOWNLOADABLE,
    STATUS_MANUAL,
    STATUS_FAILED,
}


@dataclass(frozen=True)
class FontFace:
    family: str
    subfamily: str = ""
    full_name: str = ""
    postscript_name: str = ""
    aliases: tuple[str, ...] = ()
    path: str | None = None
    face_index: int = 0
    source: str = "system"  # system / user / embedded / downloaded
    is_variable: bool = False
    weight: int = 400
    file_format: str = ""

    def display_name(self) -> str:
        return self.family or self.full_name or self.postscript_name or "未知字体"

    def all_names(self) -> list[str]:
        out = [self.family, self.full_name, self.postscript_name, *self.aliases]
        seen: set[str] = set()
        result: list[str] = []
        for name in out:
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "subfamily": self.subfamily,
            "full_name": self.full_name,
            "postscript_name": self.postscript_name,
            "aliases": list(self.aliases),
            "path": self.path,
            "face_index": self.face_index,
            "source": self.source,
            "is_variable": self.is_variable,
            "weight": self.weight,
            "file_format": self.file_format,
        }


@dataclass
class PresetRef:
    preset: str
    path: str | None = None
    archive: str | None = None
    entry: str | None = None

    def location(self) -> str:
        if self.archive and self.entry:
            return f"{self.archive} :: {self.entry}"
        return self.path or self.preset

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "path": self.path,
            "archive": self.archive,
            "entry": self.entry,
        }


@dataclass(frozen=True)
class FontFile:
    filename: str
    url: str
    size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"filename": self.filename, "url": self.url, "size": self.size}


@dataclass
class FontPackage:
    family: str
    provider: str = "Google Fonts"
    license: str = ""
    version: str = ""
    files: list[FontFile] = field(default_factory=list)
    page_url: str = ""
    source_url: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "provider": self.provider,
            "license": self.license,
            "version": self.version,
            "files": [f.to_dict() for f in self.files],
            "page_url": self.page_url,
            "source_url": self.source_url,
            "note": self.note,
        }


@dataclass
class FontNeed:
    name: str
    key: str
    refs: list[PresetRef] = field(default_factory=list)
    installed_face: FontFace | None = None
    match_kind: str = ""
    embedded_faces: list[FontFace] = field(default_factory=list)
    package: FontPackage | None = None
    status: str = STATUS_MISSING
    detail: str = ""
    downloaded_files: list[str] = field(default_factory=list)
    install_message: str = ""
    manual_url: str = ""
    vendor: str = ""
    priority: int = 0

    @property
    def is_problem(self) -> bool:
        return self.status in PROBLEM_STATUSES

    def preset_labels(self, limit: int = 6) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for ref in self.refs:
            label = ref.preset
            if label not in seen:
                seen.add(label)
                labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "key": self.key,
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "detail": self.detail,
            "match_kind": self.match_kind,
            "installed_face": self.installed_face.to_dict() if self.installed_face else None,
            "embedded_faces": [f.to_dict() for f in self.embedded_faces],
            "package": self.package.to_dict() if self.package else None,
            "downloaded_files": self.downloaded_files,
            "install_message": self.install_message,
            "manual_url": self.manual_url,
            "vendor": self.vendor,
            "preset_count": len(self.refs),
            "presets": [r.to_dict() for r in self.refs],
        }


@dataclass
class ScanReport:
    roots: list[str] = field(default_factory=list)
    preset_count: int = 0
    file_count: int = 0
    archive_count: int = 0
    needs: list[FontNeed] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    embedded_font_count: int = 0
    duration: float = 0.0
    started_at: str = ""
    platform: str = ""
    generated_report: str = ""
    installed_font_count: int = 0
    fixed_count: int = 0

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for need in self.needs:
            counts[need.status] = counts.get(need.status, 0) + 1
        counts["all"] = len(self.needs)
        counts["problems"] = sum(1 for n in self.needs if n.is_problem)
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "started_at": self.started_at,
            "duration_seconds": round(self.duration, 3),
            "roots": self.roots,
            "preset_count": self.preset_count,
            "file_count": self.file_count,
            "archive_count": self.archive_count,
            "embedded_font_count": self.embedded_font_count,
            "installed_font_count": self.installed_font_count,
            "fixed_count": self.fixed_count,
            "counts": self.counts(),
            "errors": self.errors,
            "notes": self.notes,
            "needs": [n.to_dict() for n in self.needs],
            "generated_report": self.generated_report,
        }


@dataclass
class AppSettings:
    extra_roots: list[str] = field(default_factory=list)
    include_builtin: bool = True
    last_report: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "extra_roots": self.extra_roots,
            "include_builtin": self.include_builtin,
            "last_report": self.last_report,
        }
