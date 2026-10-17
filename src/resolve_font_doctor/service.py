from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from .font_names import normalize_name
from .google_fonts import GoogleFontsProvider
from .installer import FontInstaller, InstallResult
from .manual_sources import find_manual_source, search_url
from .models import (
    AppSettings,
    FontNeed,
    ScanReport,
    STATUS_DOWNLOADABLE,
    STATUS_EMBEDDED,
    STATUS_FAILED,
    STATUS_FIXED,
    STATUS_INSTALLED,
    STATUS_MANUAL,
    STATUS_MISSING,
)
from .paths import settings_path
from .presets import PresetRoot, discover_roots, scan_presets
from .report import write_reports
from .system_fonts import FontIndex
from .util import timestamp


ProgressFn = Callable[[int, int, str], None]
StopFn = Callable[[], bool]


def load_settings() -> AppSettings:
    path = settings_path()
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, dict):
            roots = data.get("extra_roots", [])
            return AppSettings(
                extra_roots=[str(x) for x in roots if isinstance(x, str)],
                include_builtin=bool(data.get("include_builtin", True)),
                last_report=str(data.get("last_report", "")),
            )
    except (OSError, ValueError):
        pass
    return AppSettings()


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


class FontDoctorService:
    def __init__(self, provider: GoogleFontsProvider | None = None) -> None:
        self.provider = provider or GoogleFontsProvider()

    def scan(
        self,
        include_builtin: bool = True,
        extra_roots: list[str] | None = None,
        online: bool = True,
        progress: ProgressFn | None = None,
        should_stop: StopFn | None = None,
    ) -> ScanReport:
        roots = discover_roots(include_builtin=include_builtin, extra_roots=extra_roots or [])
        scan_total_weight = 0.72

        def scan_progress(done: int, total: int, message: str) -> None:
            if progress:
                percent = int(scan_total_weight * 100 * done / max(1, total))
                progress(percent, 100, message)

        report = scan_presets(roots, progress=scan_progress, should_stop=should_stop)
        if progress:
            progress(74, 100, "读取本机已安装字体…")
        index = FontIndex.build()
        report.installed_font_count = len(index)
        if should_stop and should_stop():
            report.errors.append("操作已取消")
            return report
        self.analyze(report, index, online=online, progress=progress, should_stop=should_stop)
        return report

    def analyze(
        self,
        report: ScanReport,
        index: FontIndex,
        online: bool = True,
        progress: ProgressFn | None = None,
        should_stop: StopFn | None = None,
    ) -> None:
        pending = [n for n in report.needs if n.status not in (STATUS_INSTALLED, STATUS_FIXED)]
        total = max(1, len(pending))
        for i, need in enumerate(pending, 1):
            if should_stop and should_stop():
                return
            if progress:
                progress(76 + int(24 * (i - 1) / total), 100, f"检查字体 {need.name}")
            self._evaluate_need(need, index, online=online)
        if progress:
            progress(100, 100, "检测完成")

    def _evaluate_need(self, need: FontNeed, index: FontIndex, online: bool) -> None:
        match = index.find(need.name)
        if match is not None:
            need.installed_face = match.face
            need.match_kind = match.kind
            need.status = STATUS_INSTALLED
            suffix = f" / {match.face.subfamily}" if match.face.subfamily else ""
            need.detail = f"已安装：{match.face.family}{suffix}"
            if match.kind != "exact":
                need.detail += "（按别名匹配）"
            return

        if need.embedded_faces:
            need.status = STATUS_EMBEDDED
            need.detail = f"预设包内含 {len(need.embedded_faces)} 个字体文件，修复时会自动安装"
            return

        if not online:
            need.status = STATUS_MISSING
            need.detail = "尚未检查下载源"
            return

        result = self.provider.lookup(need.name)
        if result.package:
            need.package = result.package
            need.status = STATUS_DOWNLOADABLE
            count = len(result.package.files)
            license_text = result.package.license or "开源"
            need.detail = f"{result.package.provider} · {license_text} · {count} 个字体文件"
            return

        need.status = STATUS_MISSING if result.offline else STATUS_MANUAL
        if result.offline:
            need.detail = "无法连接 Google Fonts，请检查网络后重试"
        else:
            need.detail = "未找到可自动下载的开源字体"
        self._attach_manual(need)

    def _attach_manual(self, need: FontNeed) -> None:
        source = find_manual_source(need.name)
        if source:
            need.manual_url = source.url
            need.vendor = source.vendor
            if source.note:
                need.detail = f"{need.detail}；{source.note}" if need.detail else source.note
        else:
            need.manual_url = search_url(need.name)
            need.vendor = "浏览器搜索"

    def repair(
        self,
        report: ScanReport,
        progress: ProgressFn | None = None,
        should_stop: StopFn | None = None,
    ) -> ScanReport:
        if progress:
            progress(1, 100, "重新检查已安装字体…")
        index = FontIndex.build()
        report.installed_font_count = len(index)
        self.analyze(report, index, online=True, progress=None, should_stop=should_stop)
        initial_problems = {n.key for n in report.needs if n.is_problem}
        problems = [n for n in report.needs if n.is_problem]
        total = max(1, len(problems) + 2)
        installer = FontInstaller(index.faces)
        downloaded_any = False

        for i, need in enumerate(problems, 1):
            if should_stop and should_stop():
                break
            if progress:
                progress(i, total, f"处理 {need.name}")
            if need.embedded_faces:
                paths = [f.path for f in need.embedded_faces if f.path]
                if paths:
                    install_result = installer.install(paths, should_stop=should_stop)
                    need.install_message = self._install_message(install_result)
                    downloaded_any = downloaded_any or install_result.count > 0
                continue
            if need.package is None:
                result = self.provider.lookup(need.name)
                if result.package:
                    need.package = result.package
                    need.status = STATUS_DOWNLOADABLE
                    need.detail = f"{result.package.provider} · {result.package.license or '开源'}"
                else:
                    need.status = STATUS_MISSING if result.offline else STATUS_MANUAL
                    need.detail = (
                        "无法连接 Google Fonts，请检查网络后重试"
                        if result.offline
                        else "未找到可自动下载的开源字体"
                    )
                    self._attach_manual(need)
                    continue
            if not need.package:
                continue

            def dl_progress(done: int, count: int, message: str) -> None:
                if progress:
                    fraction = done / max(1, count)
                    percent = int(((i - 1) + fraction) / total * 100)
                    progress(percent, 100, f"{message}（{done}/{count}）")

            paths, errors = self.provider.download(
                need.package, progress=dl_progress, should_stop=should_stop
            )
            need.downloaded_files = paths
            if not paths:
                need.status = STATUS_FAILED
                need.detail = "字体下载失败：" + ("；".join(errors[:2]) if errors else "未知错误")
                self._attach_manual(need)
                continue
            downloaded_any = True
            install_result = installer.install(paths, should_stop=should_stop)
            need.install_message = self._install_message(install_result)
            if install_result.failed and not install_result.installed:
                need.status = STATUS_FAILED
                need.detail = "字体安装失败：" + "；".join(msg for _, msg in install_result.failed[:2])
                continue
            if progress:
                progress(i, total, f"已安装 {need.name}")

        if progress:
            progress(total - 1, total, "刷新字体列表…")
        new_index = FontIndex.build()
        report.installed_font_count = len(new_index)
        fixed = 0
        for need in report.needs:
            match = new_index.find(need.name)
            if match is not None:
                need.installed_face = match.face
                if need.key in initial_problems:
                    need.status = STATUS_FIXED
                    fixed += 1
                    if need.package:
                        provider = need.package.provider
                        license_text = f"，{need.package.license}" if need.package.license else ""
                        need.detail = f"已自动下载并安装（{provider}{license_text}）"
                    elif need.embedded_faces:
                        need.detail = "已从预设包自动安装"
                    elif not need.detail:
                        need.detail = "已自动安装"
                    need.install_message = need.install_message or "安装成功"
                else:
                    need.status = STATUS_INSTALLED
                continue
            if need.key in initial_problems:
                if need.status != STATUS_FAILED:
                    if need.embedded_faces:
                        need.status = STATUS_EMBEDDED
                    elif need.package:
                        need.status = STATUS_FAILED
                    else:
                        need.status = STATUS_MANUAL
        report.fixed_count = fixed
        if downloaded_any and fixed:
            report.notes.append(f"已安装 {fixed} 个字体，请重新启动 DaVinci Resolve 后使用预设。")
        if progress:
            progress(total, total, "生成报告…")
        html_path, _json_path, _csv_path = write_reports(report)
        report.generated_report = str(html_path)
        if progress:
            progress(100, 100, "完成")
        return report

    @staticmethod
    def _install_message(result: InstallResult) -> str:
        bits: list[str] = []
        if result.installed:
            bits.append(f"已安装 {len(result.installed)} 个文件")
        if result.skipped:
            bits.append(f"跳过 {len(result.skipped)} 个已存在文件")
        if result.failed:
            bits.append(f"失败 {len(result.failed)} 个")
        return "；".join(bits) or "没有需要安装的文件"

    def install_local(self, paths: list[str]) -> tuple[InstallResult, FontIndex]:
        index = FontIndex.build()
        installer = FontInstaller(index.faces)
        result = installer.install(paths)
        return result, FontIndex.build()

    def write_report(self, report: ScanReport) -> str:
        html_path, _json_path, _csv_path = write_reports(report)
        report.generated_report = str(html_path)
        return str(html_path)


def roots_preview(include_builtin: bool = True, extra_roots: list[str] | None = None) -> list[PresetRoot]:
    return discover_roots(include_builtin=include_builtin, extra_roots=extra_roots or [])
