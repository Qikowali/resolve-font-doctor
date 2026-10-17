from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from .font_names import normalize_name


@dataclass(frozen=True)
class ManualSource:
    name: str
    vendor: str
    url: str
    note: str
    paid: bool = False


_CATALOG: dict[str, ManualSource] = {
    "gilroy": ManualSource(
        "Gilroy",
        "Tinkov Type / Fontspring",
        "https://www.fontspring.com/fonts/radomir-tinkov/gilroy",
        "个人免费版可用于非商业测试；商业项目需购买授权。",
        True,
    ),
    "helvetica now display": ManualSource(
        "Helvetica Now Display",
        "Monotype",
        "https://www.monotype.com/fonts/helvetica-now",
        "Monotype 商业字体，需购买授权后安装。",
        True,
    ),
    "uni sans demo": ManualSource(
        "Uni Sans",
        "Fontfabric",
        "https://www.fontfabric.com/fonts/uni-sans/",
        "Fontfabric 提供演示版；商业使用需购买完整授权。",
        True,
    ),
    "monument extended": ManualSource(
        "Monument Extended",
        "Pangram Pangram",
        "https://pangrampangram.com/products/monument-extended",
        "提供个人/试用版本；商业使用需购买授权。",
        True,
    ),
    "kenyan coffee": ManualSource(
        "Kenyan Coffee",
        "Typodermic Fonts",
        "https://typodermicfonts.com/freshly-brewed-kenyan-coffee/",
        "Typodermic 字体，按官网授权方式获取。",
        True,
    ),
    "chunkfive": ManualSource(
        "ChunkFive",
        "The League of Moveable Type",
        "https://www.theleagueofmoveabletype.com/chunkfive",
        "开源字体（SIL OFL），可从官方项目免费获取。",
        False,
    ),
    "kozuka gothic pr6n": ManualSource(
        "Kozuka Gothic Pr6N",
        "Adobe Fonts",
        "https://fonts.adobe.com/fonts/kozuka-gothic-pr6n",
        "Adobe Fonts 字体，需要 Creative Cloud 订阅并在 Adobe Fonts 中启用。",
        True,
    ),
    "pingfang sc": ManualSource(
        "PingFang SC",
        "Apple",
        "https://www.apple.com/cn/macos/",
        "macOS 系统字体，Apple 未授权单独分发；Windows 上请使用合法授权版本。",
        True,
    ),
    "open sans condensed": ManualSource(
        "Open Sans Condensed",
        "Google Fonts",
        "https://fonts.google.com/specimen/Open+Sans",
        "Google Fonts 已将 Open Sans Condensed 合并进 Open Sans 可变字体；旧预设需要旧版字体文件。",
        False,
    ),
    "verdana": ManualSource(
        "Verdana",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/verdana",
        "Windows 系统字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
    "arial": ManualSource(
        "Arial",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/arial",
        "Windows 系统字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
    "times new roman": ManualSource(
        "Times New Roman",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/times-new-roman",
        "Windows 系统字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
    "courier new": ManualSource(
        "Courier New",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/courier-new",
        "Windows 系统字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
    "calibri": ManualSource(
        "Calibri",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/calibri",
        "Windows 系统字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
    "microsoft yahei": ManualSource(
        "Microsoft YaHei",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/microsoft-yahei",
        "Windows 中文字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
    "微软雅黑": ManualSource(
        "Microsoft YaHei",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/microsoft-yahei",
        "Windows 中文字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
    "simsun": ManualSource(
        "SimSun / 宋体",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/simsun",
        "Windows 中文字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
    "宋体": ManualSource(
        "SimSun / 宋体",
        "Microsoft",
        "https://learn.microsoft.com/typography/font-list/simsun",
        "Windows 中文字体；若缺失，请通过系统组件或合法授权恢复。",
        True,
    ),
}


_CATALOG_NORMALIZED = {normalize_name(key): value for key, value in _CATALOG.items()}


def find_manual_source(name: str) -> ManualSource | None:
    return _CATALOG_NORMALIZED.get(normalize_name(name))


def search_url(name: str) -> str:
    return "https://cn.bing.com/search?q=" + urllib.parse.quote_plus(f"{name} 字体 官方 下载")
