## 达芬奇字体管家 v1.0.0

自动检测 DaVinci Resolve / Fusion 预设使用的字体，检查本机安装情况，并自动下载、安装缺失的开源字体，让标题、转场和模板正常显示。

### 下载

- **ResolveFontDoctor.exe**：Windows 单文件 GUI，双击运行
- **ResolveFontDoctor-v1.0.0-Windows.zip**：GUI + CLI + README + 截图
- **ResolveFontDoctor-CLI.exe**：命令行版，适合批处理

### 功能

- 扫描 `.drfx`、`.zip`、`.setting`、`.comp`，包括达芬奇内置 `Templates.drfx`
- 解析 Fusion 的 `Font` / `FontName` / `SubtitleFont` 和 `font-family`
- 读取 TTF/OTF/TTC 内部名称表，不依赖文件名猜测
- 自动安装预设包内嵌字体
- 从 Google Fonts 下载 OFL/Apache/UFL 开源字体，支持镜像回退
- 字体安装到当前用户，无需管理员权限
- 输出 HTML / JSON / CSV 报告
- 商业字体和系统专属字体只提供官方获取入口，不进行未授权下载

### 实测

扫描 10 个预设包、4316 个预设文件、20 个唯一字体；自动补齐 Fahkwang（Google Fonts，12 个样式），当前待处理 0。

### 说明

- 修复后请**完全退出 DaVinci Resolve 并重新启动**，字体才会出现在字体列表中。
- 程序未做商业代码签名，首次运行可能触发 Windows SmartScreen，点击“更多信息 → 仍要运行”即可。
- 系统要求：Windows 10/11；源码同时保留 macOS / Linux 支持。

### 校验

```text
SHA256 (ResolveFontDoctor.exe) = 21D48AA124F4818A8D855E6C55AC26024FE8566023B70922682108743FACBA52
SHA256 (ResolveFontDoctor-v1.0.0-Windows.zip) = 5EBD13F035B92F5811E5AA2998B81FCA1253BE305462EDAF2423F946D4B5B794
```

源码与使用说明见仓库 README。
