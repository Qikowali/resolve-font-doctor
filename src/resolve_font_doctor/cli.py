from __future__ import annotations

import argparse
import os
import sys

from . import APP_NAME_ZH, __version__
from .models import STATUS_LABELS
from .service import FontDoctorService, load_settings, save_settings
from .util import open_path


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _print_report(report, verbose: bool = False) -> None:
    counts = report.counts()
    print()
    print(f"{APP_NAME_ZH} v{__version__}")
    print("=" * 64)
    print(f"预设包：{report.archive_count}    预设文件：{report.preset_count}    使用字体：{len(report.needs)}")
    if not report.roots:
        print("未找到 DaVinci Resolve 预设目录，请使用 --root 指定预设文件夹。")
    print(
        f"已安装：{counts.get('installed', 0)}    "
        f"本次修复：{counts.get('fixed', 0)}    "
        f"可下载：{counts.get('downloadable', 0)}    "
        f"预设内置：{counts.get('embedded', 0)}    "
        f"需手动：{counts.get('manual', 0)}    "
        f"失败：{counts.get('failed', 0)}"
    )
    print("-" * 64)
    for need in report.needs:
        if need.status == "installed" and not verbose:
            continue
        label = STATUS_LABELS.get(need.status, need.status)
        print(f"[{label}] {need.name}  ({len(need.refs)} 处)")
        if need.detail:
            print(f"    {need.detail}")
        if need.manual_url and need.status in ("manual", "missing", "failed"):
            print(f"    {need.manual_url}")
    installed = [n for n in report.needs if n.status == "installed"]
    if installed and not verbose:
        names = "、".join(n.name for n in installed)
        print(f"\n已就绪：{names}")
    if report.errors:
        print("\n提示：")
        for error in report.errors[:10]:
            print(f"  - {error}")
    if report.notes:
        print("\n处理结果：")
        for note in report.notes:
            print(f"  - {note}")
    if report.generated_report:
        print(f"\n报告：{report.generated_report}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ResolveFontDoctor",
        description="检测 DaVinci Resolve 预设使用的字体，自动下载并安装缺失的开源字体。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--install", action="store_true", help="下载并安装缺失字体")
    parser.add_argument("--offline", action="store_true", help="只扫描本机，不联网检查下载源")
    parser.add_argument("--no-builtin", action="store_true", help="不扫描达芬奇内置预设")
    parser.add_argument("--root", action="append", default=[], help="额外的预设文件夹，可重复使用")
    parser.add_argument("--verbose", action="store_true", help="同时列出已安装字体")
    parser.add_argument("--open-report", action="store_true", help="完成后打开 HTML 报告")
    parser.add_argument("--no-report", action="store_true", help="不生成报告文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)
    settings = load_settings()
    extra_roots = list(dict.fromkeys([*settings.extra_roots, *args.root]))
    service = FontDoctorService()
    last_percent = -1
    last_message = ""

    def progress(done: int, total: int, message: str) -> None:
        nonlocal last_percent, last_message
        percent = int(done * 100 / max(1, total))
        if percent != last_percent or message != last_message:
            print(f"\r[{percent:3d}%] {message[:70]:<70}", end="", flush=True)
            last_percent = percent
            last_message = message

    try:
        report = service.scan(
            include_builtin=not args.no_builtin,
            extra_roots=extra_roots,
            online=not args.offline,
            progress=progress,
        )
        print("\r" + " " * 82 + "\r", end="")
        if args.install:
            report = service.repair(report, progress=progress)
            print("\r" + " " * 82 + "\r", end="")
        elif not args.no_report:
            service.write_report(report)
        _print_report(report, verbose=args.verbose)
        if args.open_report and report.generated_report:
            open_path(report.generated_report)
        return 0 if not any(n.is_problem for n in report.needs) else 1
    except KeyboardInterrupt:
        print("\n已取消。")
        return 130
    except Exception as exc:
        print(f"\n发生错误：{exc}", file=sys.stderr)
        if os.environ.get("RESOLVE_FONT_DOCTOR_DEBUG"):
            raise
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
