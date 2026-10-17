from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
import tkinter as tk

from . import APP_NAME_ZH, __version__
from .manual_sources import find_manual_source
from .models import (
    STATUS_COLORS,
    STATUS_DOWNLOADABLE,
    STATUS_EMBEDDED,
    STATUS_FAILED,
    STATUS_FIXED,
    STATUS_INSTALLED,
    STATUS_LABELS,
    STATUS_MANUAL,
    STATUS_MISSING,
    ScanReport,
)
from .paths import (
    is_windows,
    log_path,
    manual_fonts_dir,
    platform_label,
)
from .service import FontDoctorService, load_settings, save_settings
from .util import open_path, resolve_resolve_process


# Palette: a calm light workspace with a teal accent.
BG = "#F4F6F8"
CARD = "#FFFFFF"
INK = "#111827"
MUTED = "#6B7280"
LINE = "#E5E7EB"
BRAND = "#0F766E"
BRAND_DARK = "#115E59"
BRAND_SOFT = "#E6F4F1"
DANGER = "#B91C1C"
WARN = "#B45309"
OK = "#15803D"


def _enable_dpi_awareness() -> None:
    if not is_windows():
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative


def _short_path(path: str) -> str:
    """Keep full paths useful without exposing the account name in screenshots."""
    text = str(path)
    for variable in ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES", "WINDIR"):
        base = os.environ.get(variable)
        if base and text.casefold().startswith(base.casefold()):
            return f"%{variable}%" + text[len(base):]
    home = str(Path.home())
    if text.casefold().startswith(home.casefold()):
        return "~" + text[len(home):]
    return text


def _setup_logging() -> None:
    try:
        logging.basicConfig(
            filename=str(log_path()),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            encoding="utf-8",
        )
    except Exception:
        logging.basicConfig(level=logging.INFO)


def _apply_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Card.TLabel", background=CARD, foreground=INK)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("", 9))
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=("", 9))
    style.configure("Title.TLabel", background=BG, foreground=INK, font=("", 22, "bold"))
    style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("", 10))
    style.configure("TButton", font=("", 9), padding=(12, 7))
    style.configure(
        "Treeview",
        background=CARD,
        fieldbackground=CARD,
        foreground=INK,
        borderwidth=0,
        rowheight=35,
        font=("", 10),
    )
    style.configure(
        "Treeview.Heading",
        background="#F8FAFC",
        foreground=MUTED,
        font=("", 9, "bold"),
        relief="flat",
        padding=(8, 8),
    )
    style.map(
        "Treeview",
        background=[("selected", "#DDF3EF")],
        foreground=[("selected", INK)],
    )
    style.configure("TProgressbar", thickness=5, troughcolor="#E8ECEF", background=BRAND)
    style.configure("TCheckbutton", background=BG, foreground=MUTED, font=("", 9))
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("TEntry", fieldbackground=CARD, foreground=INK, padding=6)
    style.configure("TCombobox", padding=5)


class FontDoctorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = load_settings()
        self.service = FontDoctorService()
        self.report: ScanReport | None = None
        self.needs = []
        self.selected_key: str | None = None
        self.busy = False
        self.closing = False
        self.queue: queue.Queue = queue.Queue()
        self._build()
        self._bind()
        self._poll_queue()
        self.root.after(420, self.scan_async)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        self.root.title(f"{APP_NAME_ZH} — DaVinci Resolve 预设字体修复")
        self.root.configure(bg=BG)
        self.root.geometry(self._center_geometry(1180, 790))
        self.root.minsize(980, 680)

        families = set(tkfont.families(self.root))
        for candidate in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans SC", "Segoe UI"):
            if candidate in families:
                self.ui_font = candidate
                break
        else:
            self.ui_font = "TkDefaultFont"
        self.root.option_add("*Font", (self.ui_font, 10))
        try:
            self.root.option_add("*TCombobox*Listbox.font", (self.ui_font, 10))
        except tk.TclError:
            pass

        icon = resource_path("assets/font-doctor.ico")
        if icon.exists():
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:
                pass

        self._build_header()
        self._build_cards()
        self._build_toolbar()
        self._build_statusbar()
        self._build_body()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center_geometry(self, width: int, height: int) -> str:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(20, (screen_w - width) // 2)
        y = max(20, (screen_h - height) // 2 - 18)
        return f"{width}x{height}+{x}+{y}"

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=26, pady=(20, 8))
        left = tk.Frame(header, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(
            left,
            text=APP_NAME_ZH,
            bg=BG,
            fg=INK,
            font=(self.ui_font, 22, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            left,
            text="自动找出 DaVinci Resolve 预设使用的全部字体，补齐缺失字体，让标题和模板正常显示。",
            bg=BG,
            fg=MUTED,
            font=(self.ui_font, 9),
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))
        right = tk.Frame(header, bg=BG)
        right.pack(side="right", anchor="e")
        tk.Label(
            right,
            text=platform_label(),
            bg=BG,
            fg=MUTED,
            font=(self.ui_font, 9),
            anchor="e",
        ).pack(anchor="e")
        tk.Label(
            right,
            text=f"v{__version__}  ·  字体安装到当前用户",
            bg=BG,
            fg="#9CA3AF",
            font=(self.ui_font, 8),
            anchor="e",
        ).pack(anchor="e", pady=(2, 0))

    def _build_cards(self) -> None:
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="x", padx=26, pady=(8, 8))
        for col in range(4):
            frame.grid_columnconfigure(col, weight=1, uniform="card")
        specs = [
            ("packs", "预设包", "DRFX / ZIP 文件"),
            ("presets", "预设文件", "Setting / Comp"),
            ("fonts", "使用字体", "去重后的字体"),
            ("missing", "待处理", "缺失或需手动"),
        ]
        self.card_values: dict[str, tk.StringVar] = {}
        self.card_value_labels: dict[str, tk.Label] = {}
        for col, (key, label, hint) in enumerate(specs):
            card = tk.Frame(
                frame,
                bg=CARD,
                highlightbackground=LINE,
                highlightthickness=1,
                bd=0,
            )
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
            inner = tk.Frame(card, bg=CARD)
            inner.pack(fill="both", expand=True, padx=16, pady=12)
            value_var = tk.StringVar(value="—")
            self.card_values[key] = value_var
            value_label = tk.Label(
                inner,
                textvariable=value_var,
                bg=CARD,
                fg=INK,
                font=(self.ui_font, 23, "bold"),
                anchor="w",
            )
            value_label.pack(anchor="w")
            self.card_value_labels[key] = value_label
            tk.Label(
                inner,
                text=label,
                bg=CARD,
                fg=INK,
                font=(self.ui_font, 9),
                anchor="w",
            ).pack(anchor="w")
            tk.Label(
                inner,
                text=hint,
                bg=CARD,
                fg="#9CA3AF",
                font=(self.ui_font, 8),
                anchor="w",
            ).pack(anchor="w", pady=(2, 0))

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=26, pady=(4, 8))
        self.repair_btn = tk.Button(
            bar,
            text="一键检测并修复",
            command=self.repair_async,
            bg=BRAND,
            fg="white",
            activebackground=BRAND_DARK,
            activeforeground="white",
            disabledforeground="#D1D5DB",
            relief="flat",
            bd=0,
            padx=18,
            pady=9,
            font=(self.ui_font, 10, "bold"),
            cursor="hand2",
            state="disabled",
        )
        self.repair_btn.pack(side="left")
        self.scan_btn = tk.Button(
            bar,
            text="重新扫描",
            command=self.scan_async,
            bg=CARD,
            fg=INK,
            activebackground="#F9FAFB",
            activeforeground=INK,
            relief="flat",
            bd=0,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=13,
            pady=8,
            font=(self.ui_font, 9),
            cursor="hand2",
        )
        self.scan_btn.pack(side="left", padx=(8, 0))
        self.add_btn = tk.Button(
            bar,
            text="添加文件夹",
            command=self.add_folder,
            bg=CARD,
            fg=INK,
            activebackground="#F9FAFB",
            activeforeground=INK,
            relief="flat",
            bd=0,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=13,
            pady=8,
            font=(self.ui_font, 9),
            cursor="hand2",
        )
        self.add_btn.pack(side="left", padx=(8, 0))
        self.import_btn = tk.Button(
            bar,
            text="导入本地字体",
            command=self.import_fonts,
            bg=CARD,
            fg=INK,
            activebackground="#F9FAFB",
            activeforeground=INK,
            relief="flat",
            bd=0,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=13,
            pady=8,
            font=(self.ui_font, 9),
            cursor="hand2",
        )
        self.import_btn.pack(side="left", padx=(8, 0))
        self.report_btn = tk.Button(
            bar,
            text="打开报告",
            command=self.open_report,
            bg=CARD,
            fg=INK,
            activebackground="#F9FAFB",
            activeforeground=INK,
            relief="flat",
            bd=0,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=13,
            pady=8,
            font=(self.ui_font, 9),
            cursor="hand2",
        )
        self.report_btn.pack(side="left", padx=(8, 0))

        self.builtin_var = tk.BooleanVar(value=self.settings.include_builtin)
        self.builtin_check = ttk.Checkbutton(
            bar,
            text="包含内置预设",
            variable=self.builtin_var,
            command=self._builtin_changed,
        )
        self.builtin_check.pack(side="left", padx=(14, 0))

        right = tk.Frame(bar, bg=BG)
        right.pack(side="right")
        tk.Label(right, text="筛选", bg=BG, fg=MUTED, font=(self.ui_font, 9)).pack(side="left", padx=(0, 6))
        self.filter_var = tk.StringVar(value="全部")
        self.filter_box = ttk.Combobox(
            right,
            textvariable=self.filter_var,
            values=["全部", "待处理", "可下载", "需手动", "已安装"],
            state="readonly",
            width=8,
        )
        self.filter_box.pack(side="left")
        self.filter_box.bind("<<ComboboxSelected>>", lambda _e: self._refresh_tree())
        tk.Label(right, text="搜索", bg=BG, fg=MUTED, font=(self.ui_font, 9)).pack(side="left", padx=(14, 6))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(right, textvariable=self.search_var, width=18)
        self.search_entry.pack(side="left")
        self.search_var.trace_add("write", lambda *_: self._refresh_tree())

    def _build_body(self) -> None:
        self.paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill="both", expand=True, padx=26, pady=(2, 6))

        left = tk.Frame(self.paned, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        self.paned.add(left, weight=4)
        left_header = tk.Frame(left, bg=CARD)
        left_header.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(
            left_header,
            text="字体清单",
            bg=CARD,
            fg=INK,
            font=(self.ui_font, 11, "bold"),
        ).pack(side="left")
        self.count_label = tk.Label(
            left_header,
            text="尚未检测",
            bg=CARD,
            fg=MUTED,
            font=(self.ui_font, 8),
        )
        self.count_label.pack(side="right")

        tree_wrap = tk.Frame(left, bg=CARD)
        tree_wrap.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        columns = ("font", "status", "count", "source")
        self.tree = ttk.Treeview(
            tree_wrap,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Treeview",
        )
        headings = {
            "font": ("字体名称", 250, "w"),
            "status": ("状态", 92, "w"),
            "count": ("使用", 56, "center"),
            "source": ("来源 / 处理", 210, "w"),
        }
        for key, (label, width, anchor) in headings.items():
            self.tree.heading(key, text=label, anchor=anchor)
            self.tree.column(key, width=width, minwidth=45, anchor=anchor, stretch=(key in ("font", "source")))
        scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("problem", background="#FFF8F8")
        self.tree.tag_configure("manual", background="#FFFCF2")
        self.tree.tag_configure("ok", background=CARD)

        right = tk.Frame(self.paned, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        self.paned.add(right, weight=2)
        detail_head = tk.Frame(right, bg=CARD)
        detail_head.pack(fill="x", padx=16, pady=(12, 0))
        self.detail_title = tk.Label(
            detail_head,
            text="选择一个字体",
            bg=CARD,
            fg=INK,
            font=(self.ui_font, 13, "bold"),
            anchor="w",
        )
        self.detail_title.pack(anchor="w")
        self.detail_status = tk.Label(
            detail_head,
            text="检测结果会显示在这里",
            bg=CARD,
            fg=MUTED,
            font=(self.ui_font, 8),
            anchor="w",
        )
        self.detail_status.pack(anchor="w", pady=(3, 0))

        text_wrap = tk.Frame(right, bg=CARD)
        text_wrap.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        self.detail_text = tk.Text(
            text_wrap,
            wrap="word",
            bg="#FBFCFD",
            fg="#374151",
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            font=(self.ui_font, 9),
            spacing1=2,
            spacing3=2,
            state="disabled",
            cursor="arrow",
        )
        detail_scroll = ttk.Scrollbar(text_wrap, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        self.detail_text.tag_configure("h", font=(self.ui_font, 9, "bold"), foreground=INK, spacing1=9)
        self.detail_text.tag_configure("muted", foreground=MUTED)
        self.detail_text.tag_configure("bad", foreground=DANGER)
        self.detail_text.tag_configure("good", foreground=OK)
        self.detail_text.tag_configure("warn", foreground=WARN)

        actions = tk.Frame(right, bg=CARD)
        actions.pack(fill="x", padx=12, pady=(8, 12))
        self.source_btn = ttk.Button(actions, text="打开获取页面", command=self.open_source)
        self.source_btn.pack(side="left")
        self.folder_btn = ttk.Button(actions, text="打开预设位置", command=self.open_preset_folder)
        self.folder_btn.pack(side="left", padx=(6, 0))
        self.copy_btn = ttk.Button(actions, text="复制名称", command=self.copy_name)
        self.copy_btn.pack(side="left", padx=(6, 0))
        self._set_detail_buttons(False, False, False)

    def _build_statusbar(self) -> None:
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(side="bottom", fill="x", padx=26, pady=(0, 12))
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x")
        row = tk.Frame(outer, bg=BG)
        row.pack(fill="x", pady=(6, 0))
        self.status_var = tk.StringVar(value="准备就绪")
        tk.Label(
            row,
            textvariable=self.status_var,
            bg=BG,
            fg=MUTED,
            font=(self.ui_font, 8),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        for text, command in (
            ("手动字体文件夹", self.open_manual_folder),
            ("查看日志", self.open_log),
        ):
            button = tk.Button(
                row,
                text=text,
                command=command,
                bg=BG,
                fg=MUTED,
                activebackground=BG,
                activeforeground=BRAND,
                relief="flat",
                bd=0,
                font=(self.ui_font, 8, "underline"),
                cursor="hand2",
                padx=4,
            )
            button.pack(side="right")

    def _bind(self) -> None:
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        self.tree.bind("<Double-1>", lambda _e: self.open_preset_folder())
        self.root.bind("<F5>", lambda _e: self.scan_async())
        self.root.bind("<Control-f>", lambda _e: self.search_entry.focus_set())
        self.root.bind("<Escape>", lambda _e: self.search_var.set(""))
        self.root.after(400, lambda: self.paned.sashpos(0, 765))

    # ------------------------------------------------------------- actions
    def scan_async(self, *_args) -> None:
        if self.busy or self.closing:
            return
        self.settings.include_builtin = bool(self.builtin_var.get())
        save_settings(self.settings)
        self._set_busy(True)
        self._set_progress(0, "准备扫描预设…")
        include_builtin = self.builtin_var.get()
        extra = list(self.settings.extra_roots)

        def work() -> None:
            try:
                report = self.service.scan(
                    include_builtin=include_builtin,
                    extra_roots=extra,
                    online=True,
                    progress=lambda pct, _total, msg: self.queue.put(("progress", pct, msg)),
                )
                self.service.write_report(report)
                self.queue.put(("scan_done", report))
            except Exception:
                self.queue.put(("error", traceback.format_exc()))

        threading.Thread(target=work, daemon=True, name="scan").start()

    def repair_async(self, *_args) -> None:
        if self.busy or self.closing or self.report is None:
            return
        has_problems = any(need.is_problem for need in self.report.needs)
        if has_problems and resolve_resolve_process():
            if not messagebox.askyesno(
                "DaVinci Resolve 正在运行",
                "检测到 DaVinci Resolve 正在运行。\n\n"
                "字体可以现在安装，但需要完全退出并重新启动 Resolve 后才能生效。\n\n"
                "仍要继续吗？",
                parent=self.root,
            ):
                return
        self._set_busy(True)
        self._set_progress(1, "准备修复…")
        report = self.report

        def work() -> None:
            try:
                self.service.repair(
                    report,
                    progress=lambda pct, _total, msg: self.queue.put(("progress", pct, msg)),
                )
                self.queue.put(("repair_done", report))
            except Exception:
                self.queue.put(("error", traceback.format_exc()))

        threading.Thread(target=work, daemon=True, name="repair").start()

    def import_fonts(self) -> None:
        if self.busy:
            return
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="选择要安装的字体文件",
            filetypes=[("字体文件", "*.ttf *.otf *.ttc *.otc"), ("所有文件", "*.*")],
        )
        if not paths:
            return
        self._set_busy(True)
        self._set_progress(4, "安装本地字体…")

        def work() -> None:
            try:
                result, _index = self.service.install_local(list(paths))
                self.queue.put(("local_done", result))
            except Exception:
                self.queue.put(("error", traceback.format_exc()))

        threading.Thread(target=work, daemon=True, name="local-install").start()

    def add_folder(self) -> None:
        if self.busy:
            return
        folder = filedialog.askdirectory(parent=self.root, title="选择包含预设的文件夹")
        if not folder:
            return
        if folder not in self.settings.extra_roots:
            self.settings.extra_roots.append(folder)
            save_settings(self.settings)
        self.scan_async()

    def _builtin_changed(self) -> None:
        self.settings.include_builtin = bool(self.builtin_var.get())
        save_settings(self.settings)
        if not self.busy:
            self.scan_async()

    def open_report(self) -> None:
        if self.report is None:
            messagebox.showinfo("还没有报告", "请先完成一次扫描。", parent=self.root)
            return
        path = self.report.generated_report
        if not path or not Path(path).exists():
            path = self.service.write_report(self.report)
        open_path(path)

    def open_manual_folder(self) -> None:
        folder = manual_fonts_dir()
        open_path(folder)
        self.status_var.set(f"手动字体文件夹：{folder}  ·  放入字体后点击“导入本地字体”")

    def open_log(self) -> None:
        path = log_path()
        if path.exists():
            open_path(path)
        else:
            messagebox.showinfo("暂无日志", "当前还没有生成日志。", parent=self.root)

    def open_source(self) -> None:
        need = self._selected_need()
        if need is None:
            return
        url = need.manual_url or (need.package.page_url if need.package else "")
        if url:
            open_path(url)
        else:
            messagebox.showinfo("没有链接", "这个字体没有可用的在线获取页面。", parent=self.root)

    def open_preset_folder(self) -> None:
        need = self._selected_need()
        if need is None or not need.refs:
            return
        ref = need.refs[0]
        target = Path(ref.path) if ref.path else None
        if target is None:
            return
        folder = target.parent if target.is_file() else target
        if folder.exists():
            open_path(folder)
        else:
            messagebox.showwarning("找不到位置", f"路径不存在：\n{folder}", parent=self.root)

    def copy_name(self) -> None:
        need = self._selected_need()
        if need:
            self.root.clipboard_clear()
            self.root.clipboard_append(need.name)
            self.status_var.set(f"已复制字体名称：{need.name}")

    # -------------------------------------------------------------- updates
    def _apply_report(self, report: ScanReport, repaired: bool = False) -> None:
        self.report = report
        self.needs = list(report.needs)
        counts = report.counts()
        self.card_values["packs"].set(str(report.archive_count))
        self.card_values["presets"].set(str(report.preset_count))
        self.card_values["fonts"].set(str(len(report.needs)))
        self.card_values["missing"].set(str(counts.get("problems", 0)))
        self.card_value_labels["missing"].configure(
            fg=DANGER if counts.get("problems", 0) else OK
        )
        self.count_label.configure(text=f"共 {len(report.needs)} 个字体 · {report.preset_count} 个预设文件")
        self._refresh_tree()
        self.repair_btn.configure(state="normal")
        self._set_busy(False)
        problems = counts.get("problems", 0)
        if not report.roots:
            self.status_var.set("未找到 DaVinci Resolve 预设目录。请点击“添加文件夹”选择预设所在位置。")
        elif report.preset_count == 0:
            self.status_var.set("预设目录中没有发现 .setting、.comp 或 .drfx 文件。")
        elif problems:
            self.status_var.set(f"发现 {problems} 个待处理字体。点击“一键检测并修复”自动下载并安装。")
        else:
            self.status_var.set("全部字体已就绪。重新启动 DaVinci Resolve 后即可使用预设。")
        first = next((n for n in self.needs if n.is_problem), self.needs[0] if self.needs else None)
        if first:
            try:
                self.tree.selection_set(first.key)
                self.tree.focus(first.key)
            except tk.TclError:
                pass
        self._show_details()
        self.settings.last_report = report.generated_report
        save_settings(self.settings)
        if repaired:
            fixed = report.fixed_count
            if fixed:
                messagebox.showinfo(
                    "修复完成",
                    f"已自动安装 {fixed} 个字体。\n\n"
                    "请完全退出 DaVinci Resolve，然后重新启动，新的字体才会出现在字体列表中。",
                    parent=self.root,
                )
            else:
                messagebox.showinfo(
                    "检测完成",
                    "没有需要自动安装的字体。\n"
                    "如果仍有字体缺失，请查看报告中的“需手动获取”说明。",
                    parent=self.root,
                )

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not self.needs:
            return
        query = self.search_var.get().strip().casefold()
        filter_value = self.filter_var.get()
        shown = 0
        for need in self._sorted_needs():
            if not self._matches(need, query, filter_value):
                continue
            tag = "ok"
            if need.status == STATUS_MANUAL:
                tag = "manual"
            elif need.is_problem:
                tag = "problem"
            self.tree.insert(
                "",
                "end",
                iid=need.key,
                values=(
                    need.name,
                    STATUS_LABELS.get(need.status, need.status),
                    len(need.refs),
                    self._source_label(need),
                ),
                tags=(tag,),
            )
            shown += 1
        if self.selected_key and self.tree.exists(self.selected_key):
            self.tree.selection_set(self.selected_key)
        self.count_label.configure(
            text=f"显示 {shown} / {len(self.needs)} 个字体 · {self.report.preset_count if self.report else 0} 个预设文件"
        )

    def _sorted_needs(self):
        def key(need):
            if need.is_problem:
                group = 0
            elif need.status == STATUS_FIXED:
                group = 1
            else:
                group = 2
            return (group, -len(need.refs), need.name.casefold())

        return sorted(self.needs, key=key)

    def _matches(self, need, query: str, filter_value: str) -> bool:
        if query:
            haystack = " ".join(
                [need.name, need.detail, need.vendor, *(ref.preset for ref in need.refs[:5])]
            ).casefold()
            if query not in haystack:
                return False
        if filter_value == "待处理":
            return need.is_problem
        if filter_value == "可下载":
            return need.status in (STATUS_DOWNLOADABLE, STATUS_EMBEDDED)
        if filter_value == "需手动":
            return need.status in (STATUS_MANUAL, STATUS_FAILED)
        if filter_value == "已安装":
            return need.status in (STATUS_INSTALLED, STATUS_FIXED)
        return True

    def _source_label(self, need) -> str:
        if need.status == STATUS_INSTALLED:
            return "本机已安装"
        if need.status == STATUS_FIXED:
            return "本次已自动安装"
        if need.status == STATUS_DOWNLOADABLE:
            return "Google Fonts"
        if need.status == STATUS_EMBEDDED:
            return "预设包内置"
        if need.status == STATUS_MANUAL:
            return need.vendor or "需手动获取"
        if need.status == STATUS_FAILED:
            return "处理失败"
        if need.status == STATUS_MISSING:
            return "待检查下载源"
        return ""

    def _on_select(self) -> None:
        selection = self.tree.selection()
        self.selected_key = selection[0] if selection else None
        self._show_details()

    def _show_details(self) -> None:
        need = self._selected_need()
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        if need is None:
            self.detail_title.configure(text="选择一个字体")
            self.detail_status.configure(text="检测结果会显示在这里")
            self.detail_text.insert("end", "左侧会列出预设使用的全部字体。\n\n选择字体后可查看使用位置、来源和获取方式。", "muted")
            self.detail_text.configure(state="disabled")
            self._set_detail_buttons(False, False, False)
            return
        color = STATUS_COLORS.get(need.status, MUTED)
        self.detail_title.configure(text=need.name)
        self.detail_status.configure(
            text=f"{STATUS_LABELS.get(need.status, need.status)}  ·  {len(need.refs)} 个预设使用",
            fg=color,
        )
        text = self.detail_text
        text.insert("end", "状态\n", "h")
        text.insert("end", f"{STATUS_LABELS.get(need.status, need.status)}\n", "good" if need.status in (STATUS_INSTALLED, STATUS_FIXED) else "bad")
        if need.detail:
            text.insert("end", "说明\n", "h")
            text.insert("end", need.detail + "\n")
        if need.installed_face:
            face = need.installed_face
            text.insert("end", "本机字体\n", "h")
            detail = f"{face.family}"
            if face.subfamily:
                detail += f" / {face.subfamily}"
            if face.path:
                detail += f"\n{_short_path(face.path)}"
            text.insert("end", detail + "\n", "muted")
        if need.package:
            text.insert("end", "下载来源\n", "h")
            package = need.package
            text.insert("end", f"{package.provider} · {package.license or '开源'}")
            if package.files:
                text.insert("end", f" · {len(package.files)} 个字体文件", "muted")
            text.insert("end", "\n")
        if need.embedded_faces:
            text.insert("end", "预设内置字体\n", "h")
            text.insert("end", f"{len(need.embedded_faces)} 个字体文件，修复时自动安装\n", "good")
        if need.manual_url:
            text.insert("end", "获取方式\n", "h")
            text.insert("end", f"{need.vendor or '官方页面'}\n", "warn")
        if need.install_message:
            text.insert("end", "安装结果\n", "h")
            text.insert("end", need.install_message + "\n", "good")
        text.insert("end", "使用此字体的预设\n", "h")
        for index, ref in enumerate(need.refs[:40], 1):
            text.insert("end", f"{index}. {ref.preset}\n")
        if len(need.refs) > 40:
            text.insert("end", f"…… 另有 {len(need.refs) - 40} 个预设\n", "muted")
        text.configure(state="disabled")
        self._set_detail_buttons(
            bool(need.manual_url or (need.package and need.package.page_url)),
            bool(need.refs and need.refs[0].path),
            True,
        )

    def _set_detail_buttons(self, source: bool, folder: bool, copy: bool) -> None:
        self.source_btn.configure(state="normal" if source else "disabled")
        self.folder_btn.configure(state="normal" if folder else "disabled")
        self.copy_btn.configure(state="normal" if copy else "disabled")

    def _selected_need(self):
        if not self.selected_key:
            return None
        for need in self.needs:
            if need.key == self.selected_key:
                return need
        return None

    # --------------------------------------------------------------- queue
    def _poll_queue(self) -> None:
        if self.closing:
            return
        try:
            while True:
                message = self.queue.get_nowait()
                kind = message[0]
                if kind == "progress":
                    self._set_progress(message[1], message[2])
                elif kind == "scan_done":
                    self._apply_report(message[1], repaired=False)
                elif kind == "repair_done":
                    self._apply_report(message[1], repaired=True)
                elif kind == "local_done":
                    self._on_local_done(message[1])
                elif kind == "error":
                    self._on_worker_error(message[1])
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _on_local_done(self, result) -> None:
        self._set_busy(False)
        self._set_progress(100, "本地字体安装完成")
        parts = []
        if result.installed:
            parts.append(f"已安装 {len(result.installed)} 个字体文件")
        if result.skipped:
            parts.append(f"跳过 {len(result.skipped)} 个已存在文件")
        if result.failed:
            parts.append(f"{len(result.failed)} 个文件失败")
        summary = "；".join(parts) or "没有安装任何文件"
        if result.failed:
            details = "\n".join(f"{Path(p).name}: {msg}" for p, msg in result.failed[:5])
            messagebox.showwarning("安装完成，但有失败项", f"{summary}\n\n{details}", parent=self.root)
        else:
            messagebox.showinfo("安装完成", summary + "\n\n请重新启动 DaVinci Resolve 后使用。", parent=self.root)
        self.scan_async()

    def _on_worker_error(self, trace: str) -> None:
        logging.error("worker failed:\n%s", trace)
        self._set_busy(False)
        self._set_progress(0, "操作失败")
        messagebox.showerror(
            "操作失败",
            "处理时发生错误，详细信息已写入日志。\n\n" + trace.strip().splitlines()[-1][:300],
            parent=self.root,
        )

    def _set_progress(self, percent: int, message: str) -> None:
        self.progress["value"] = max(0, min(100, int(percent)))
        self.status_var.set(message)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.scan_btn.configure(state=state)
        self.add_btn.configure(state=state)
        self.import_btn.configure(state=state)
        self.report_btn.configure(state=state)
        self.repair_btn.configure(state=state if self.report is not None else "disabled")
        if busy:
            self.root.configure(cursor="watch")
        else:
            self.root.configure(cursor="")

    def _on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno(
                "任务正在进行",
                "扫描或安装正在进行，确定要退出吗？",
                parent=self.root,
            ):
                return
        self.closing = True
        save_settings(self.settings)
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def main(argv: list[str] | None = None) -> int:
    _enable_dpi_awareness()
    _setup_logging()
    root = tk.Tk()
    try:
        scaling = root.winfo_fpixels("1i") / 72.0
        if scaling > 0:
            root.tk.call("tk", "scaling", scaling)
    except Exception:
        pass
    _apply_theme(root)
    FontDoctorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
