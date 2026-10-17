from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from . import APP_NAME_ZH, __version__
from .models import (
    STATUS_COLORS,
    STATUS_FIXED,
    STATUS_INSTALLED,
    STATUS_LABELS,
    ScanReport,
)
from .paths import reports_dir
from .util import timestamp, timestamp_slug


def _badge(status: str) -> str:
    label = STATUS_LABELS.get(status, status)
    color = STATUS_COLORS.get(status, "#6b7280")
    return f'<span class="badge" style="--badge:{color}">{html.escape(label)}</span>'


def _need_detail(need) -> str:
    parts: list[str] = []
    if need.detail:
        parts.append(html.escape(need.detail))
    if need.package:
        parts.append(
            f'<a href="{html.escape(need.package.page_url)}" target="_blank">'
            f"{html.escape(need.package.provider)}</a>"
        )
    if need.manual_url:
        vendor = html.escape(need.vendor or "官方页面")
        parts.append(
            f'<a class="manual" href="{html.escape(need.manual_url)}" target="_blank">'
            f"前往{vendor}</a>"
        )
    return "<br>".join(parts)


def generate_html(report: ScanReport) -> str:
    counts = report.counts()
    categories = [
        ("预设包", report.archive_count, "DRFX / ZIP"),
        ("预设文件", report.preset_count, "Setting / Comp"),
        ("使用字体", len(report.needs), "去重后"),
        ("待处理", counts.get("problems", 0), "缺失或需手动"),
    ]
    cards = "".join(
        f'<div class="card"><div class="num">{value}</div><div class="label">{label}</div><div class="hint">{hint}</div></div>'
        for label, value, hint in categories
    )

    rows: list[str] = []
    for need in report.needs:
        presets = need.refs
        detail_list = "".join(
            f"<li>{html.escape(ref.preset)}</li>" for ref in presets[:30]
        )
        if len(presets) > 30:
            detail_list += f"<li>…… 另有 {len(presets) - 30} 处</li>"
        rows.append(
            "<tr>"
            f'<td class="font">{html.escape(need.name)}</td>'
            f"<td>{_badge(need.status)}</td>"
            f'<td class="count">{len(need.refs)}</td>'
            f'<td class="detail">{_need_detail(need)}</td>'
            f'<td><details><summary>{len(need.refs)} 个预设</summary><ul>{detail_list}</ul></details></td>'
            "</tr>"
        )

    error_block = ""
    if report.errors:
        error_block += (
            '<section class="panel"><h2>扫描提示</h2><ul class="errors">'
            + "".join(f"<li>{html.escape(e)}</li>" for e in report.errors)
            + "</ul></section>"
        )
    if report.notes:
        error_block += (
            '<section class="panel"><h2>处理结果</h2><ul class="notes">'
            + "".join(f"<li>{html.escape(e)}</li>" for e in report.notes)
            + "</ul></section>"
        )
    root_block = "".join(f"<li>{html.escape(root)}</li>" for root in report.roots)
    generated = timestamp()
    status_note = (
        f"已自动安装 {report.fixed_count} 个字体。"
        if report.fixed_count
        else "没有自动安装新字体。"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{APP_NAME_ZH} - 字体检测报告</title>
<style>
:root {{
  --ink:#111827; --muted:#6b7280; --line:#e5e7eb; --paper:#ffffff; --bg:#f4f6f8;
  --brand:#0f766e; --brand-soft:#ccfbf1; --warn:#b45309; --danger:#b91c1c;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:32px; background:var(--bg); color:var(--ink);
  font-family:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif; }}
.wrap {{ max-width:1180px; margin:0 auto; }}
header {{ display:flex; justify-content:space-between; align-items:flex-end; gap:20px; margin-bottom:22px; }}
h1 {{ margin:0 0 6px; font-size:28px; letter-spacing:-.5px; }}
.sub {{ color:var(--muted); font-size:14px; }}
.brand {{ color:var(--brand); font-weight:700; }}
.cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:20px 0; }}
.card {{ background:var(--paper); border:1px solid var(--line); border-radius:14px; padding:18px 20px;
  box-shadow:0 4px 18px rgba(15,23,42,.04); }}
.num {{ font-size:30px; font-weight:750; letter-spacing:-1px; }}
.label {{ font-size:14px; margin-top:2px; }}
.hint {{ color:var(--muted); font-size:12px; margin-top:6px; }}
.panel {{ background:var(--paper); border:1px solid var(--line); border-radius:14px;
  padding:20px; margin:16px 0; box-shadow:0 4px 18px rgba(15,23,42,.04); }}
.panel h2 {{ font-size:16px; margin:0 0 12px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{ text-align:left; color:var(--muted); font-weight:600; font-size:12px; letter-spacing:.04em;
  text-transform:uppercase; border-bottom:1px solid var(--line); padding:10px 8px; }}
td {{ border-bottom:1px solid #f0f2f4; padding:13px 8px; vertical-align:top; }}
tr:last-child td {{ border-bottom:0; }}
.font {{ font-weight:650; min-width:170px; }}
.count {{ width:70px; color:var(--muted); }}
.detail {{ color:#374151; line-height:1.55; }}
.badge {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:12px; font-weight:650;
  color:var(--badge); background:color-mix(in srgb, var(--badge) 11%, white);
  border:1px solid color-mix(in srgb, var(--badge) 20%, white); white-space:nowrap; }}
a {{ color:var(--brand); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
a.manual {{ color:var(--warn); }}
details summary {{ cursor:pointer; color:var(--muted); font-size:12px; white-space:nowrap; }}
details ul {{ margin:8px 0 0; padding-left:18px; color:#4b5563; font-size:12px; line-height:1.7; }}
.notice {{ border-left:3px solid var(--brand); background:var(--brand-soft); padding:12px 16px;
  border-radius:0 10px 10px 0; font-size:13px; line-height:1.7; margin:18px 0; }}
.errors {{ color:var(--warn); font-size:13px; line-height:1.7; }}
.notes {{ color:var(--brand); font-size:13px; line-height:1.7; }}
footer {{ color:var(--muted); font-size:12px; margin:26px 0 8px; display:flex; justify-content:space-between; gap:20px; }}
@media(max-width:820px) {{ body {{ padding:16px; }} .cards {{ grid-template-columns:repeat(2,1fr); }}
  header {{ display:block; }} table {{ font-size:13px; }} .hide-sm {{ display:none; }} }}
</style>
</head>
<body><div class="wrap">
<header>
  <div>
    <h1>{APP_NAME_ZH} <span class="brand">字体检测报告</span></h1>
    <div class="sub">生成时间 {generated} · {html.escape(report.platform)} · 耗时 {report.duration:.1f} 秒</div>
  </div>
  <div class="sub">{status_note}</div>
</header>
<div class="cards">{cards}</div>
<div class="notice">
  本工具只自动下载开源字体（优先 Google Fonts）。商业字体、演示版字体和系统专属字体不会进行未授权下载，
  报告会给出官方获取入口；取得字体后可放入“手动添加字体”文件夹，再点击“安装本地字体”。
</div>
<section class="panel">
  <h2>字体清单</h2>
  <table>
    <thead><tr><th>字体</th><th>状态</th><th>使用次数</th><th>说明 / 来源</th><th class="hide-sm">预设位置</th></tr></thead>
    <tbody>{''.join(rows) or '<tr><td colspan="5">没有检测到字体引用。</td></tr>'}</tbody>
  </table>
</section>
{error_block}
<section class="panel">
  <h2>扫描范围</h2>
  <ul class="errors" style="color:#4b5563">{root_block}</ul>
</section>
<footer>
  <span>{APP_NAME_ZH} v{__version__} · 报告仅保存在本机</span>
  <span>安装字体后请重新启动 DaVinci Resolve</span>
</footer>
</div></body></html>"""


def write_reports(report: ScanReport) -> tuple[Path, Path, Path]:
    folder = reports_dir()
    stem = f"字体检测报告-{timestamp_slug()}"
    html_path = folder / f"{stem}.html"
    json_path = folder / f"{stem}.json"
    csv_path = folder / f"{stem}.csv"
    report.generated_report = str(html_path)
    html_path.write_text(generate_html(report), "utf-8")
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), "utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["字体", "状态", "使用次数", "说明", "来源", "官方链接", "预设示例"])
        for need in report.needs:
            writer.writerow(
                [
                    need.name,
                    STATUS_LABELS.get(need.status, need.status),
                    len(need.refs),
                    need.detail,
                    need.package.provider if need.package else "",
                    need.manual_url,
                    " | ".join(ref.preset for ref in need.refs[:5]),
                ]
            )
    report.generated_report = str(html_path)
    return html_path, json_path, csv_path
