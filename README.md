# ManboHakimi-Harp 🐱🎹

> 曼波哈基米，启动！

一个悬浮在《三角洲行动》画面上的**纯视觉乐谱提示工具**。
在口风琴界面显示音符瀑布流和高亮琴键，帮你按正确节奏手动演奏。

**航天清图后卖艺要饭的来！！！**

---

## ⚠️ 风险声明（请先阅读）

本项目为**纯视觉辅助工具**，但《三角洲行动》官方使用内核级反作弊系统（ACE），对第三方工具持严格态度。

**本工具的设计边界：**

| 行为 | 是否涉及 |
|------|----------|
| 模拟键鼠输入 | ❌ 否 |
| 读取游戏画面 | ❌ 否 |
| 读取游戏内存 | ❌ 否 |
| 注入游戏进程 | ❌ 否 |
| 与游戏服务器通信 | ❌ 否 |
| 悬浮窗视觉提示 | ✅ 是 |

**但仍需注意：**
- ACE 可能对任何第三方 Overlay 进行扫描，**不排除被误判的可能性**
- 官方未明确表态 Overlay 类工具的合规边界
- 使用本工具的风险由用户自行承担
- 建议首次使用在**训练场**测试，观察是否触发反作弊
- 如官方明确禁止此类工具，请立即停止使用

**如果你不接受上述风险，请不要使用本工具。**

---

## ✨ 功能特性

### 核心功能
- 🎵 **音符瀑布流**：音符从顶部落下，落至判定线时提示
- 🎹 **琴键高亮**：与游戏内 8 键位一一对齐，当前应弹键带外发光
- ⏱️ **长按/短按区分**：音符块长度 = 时值，进度环显示按住时长
- 📖 **多曲目管理**：内置曲目 + 导入自定义乐谱
- 🎯 **校准向导**：三步对齐游戏内键位，适配不同分辨率
- 🪟 **悬浮球模式**：可折叠为小圆球，不遮挡游戏画面

### 视觉设计
- 暗色科技风，主色 `#00E5FF`
- 音高映射：低音蓝 → 中音青 → 高音绿
- 动效克制，不干扰游戏体验
- 所有 UI 矢量可编辑

### 热键
| 热键 | 功能 |
|------|------|
| `F1` | 开始 / 暂停提示 |
| `F2` | 重置到曲目开头 |
| `F3` | 显示 / 隐藏浮窗 |
| `F4` | 切换悬浮球 / 完整模式 |
| `Ctrl+Shift+C` | 进入校准模式 |
| `Ctrl+Shift+Q` | 退出程序 |

---

## 📸 截图

> 截图待补充。设计稿已完成，开发中。

| 主浮窗 | 设置面板 | 悬浮球 |
|--------|----------|--------|
| ![](docs/images/main.png) | ![](docs/images/settings.png) | ![](docs/images/ball.png) |

| 校准向导 | 风险声明 |
|----------|----------|
| ![](docs/images/calibration.png) | ![](docs/images/risk.png) |

---

## 🚀 快速开始

### 系统要求
- Windows 10 / 11（64 位）
- 无边框窗口模式运行游戏（全屏独占模式下 Overlay 可能不显示）
- 无需安装 .NET 运行时（单文件发布）

### 安装
1. 从 [Releases](https://github.com/yourname/ManboHakimi-Harp/releases) 下载最新版 `ManboHakimi-Harp.exe`
2. 放到任意目录，双击运行
3. 首次启动阅读风险声明并确认
4. 进入校准向导，对齐游戏内键位
5. 打开游戏口风琴界面，按 `F1` 开始

### 使用流程
```
启动程序
  ↓
确认风险声明
  ↓
校准向导（首次）
  ↓
选择曲目
  ↓
进入游戏口风琴界面
  ↓
按 F1 开始提示
  ↓
跟随瀑布流和琴键高亮手动弹奏
```

---

## 🎼 乐谱格式

### JSON 格式

```json
{
  "version": "1.0",
  "id": "sky_city",
  "name": "天空之城",
  "author": "久石让",
  "bpm": 80,
  "timeSignature": "4/4",
  "keyMap": ["Z", "X", "C", "V", "B", "N", "M", ","],
  "notes": [
    { "key": "Z", "duration": 1.0, "beat": 0 },
    { "key": "X", "duration": 0.5, "beat": 1.0 },
    { "key": "C", "duration": 0.5, "beat": 1.5 },
    { "key": "rest", "duration": 0.5, "beat": 2.0 },
    { "key": "V", "duration": 2.0, "beat": 2.5 }
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| version | string | 是 | 格式版本，当前为 "1.0" |
| id | string | 是 | 曲目唯一标识 |
| name | string | 是 | 曲目名称 |
| bpm | number | 是 | 每分钟节拍数，范围 30-300 |
| keyMap | array | 是 | 键位映射，默认 `["Z","X","C","V","B","N","M",","]` |
| notes | array | 是 | 音符序列 |
| notes[].key | string | 是 | 键位标识（Z/X/C/V/B/N/M/,）或 "rest" 表示休止 |
| notes[].duration | number | 是 | 时值，单位为拍。0.25=十六分，0.5=八分，1=四分，2=二分 |
| notes[].beat | number | 是 | 起始拍数 |

### 时值对照

| 时值 | 含义 | 瀑布流块宽 |
|------|------|-----------|
| 0.25 | 十六分音符 | 12px |
| 0.5 | 八分音符 | 24px |
| 1.0 | 四分音符（一拍） | 48px |
| 2.0 | 二分音符 | 96px |
| 4.0 | 全音符 | 192px |

### 简谱导入

支持将数字简谱转换为 JSON：

```
6 7 1 / 7 1 2 // 3 3 2
```

转换规则：

| 简谱符号 | 含义 | 转换结果 |
|----------|------|----------|
| 1-7 | 中音区 | Z X C V B N M |
| 0 | 休止符 | rest |
| / | 半拍停顿 | duration=0.5 |
| // | 一拍停顿 | duration=1.0 |
| - | 延长一拍 | duration+1 |

---

## 🎹 游戏内键位

《三角洲行动》口风琴共 8 个键位：

| 简谱 | 键盘键 | 说明 |
|------|--------|------|
| 低音1 | Z | 数字下方带圆点 |
| 低音2 | X | |
| 低音3 | C | |
| 低音4 | V | |
| 低音5 | B | |
| 低音6 | N | |
| 低音7 | M | |
| 高音1 | ,（逗号） | 数字上方带圆点 |

底部有「降调 / 半音 / 升调」三个状态按钮，半音为默认激活态。

---

## 🛠️ 开发

### 技术栈
- C# (.NET 8)
- WPF + XAML
- WindowChrome + WS_EX_LAYERED + WS_EX_TRANSPARENT
- CompositionTarget.Rendering（60fps）

### 项目结构
```
ManboHakimi-Harp/
├── src/
│   ├── ManboHakimiHarp.sln
│   ├── ManboHakimiHarp/
│   │   ├── App.xaml
│   │   ├── MainWindow.xaml
│   │   ├── Views/
│   │   ├── ViewModels/
│   │   ├── Models/
│   │   ├── Services/
│   │   ├── Controls/
│   │   └── Assets/
│   └── ManboHakimiHarp.Tests/
├── scores/
│   ├── builtin/
│   └── user/
├── config/
├── logs/
├── themes/
├── docs/
│   ├── README.md
│   ├── CHANGELOG.md
│   ├── RISK.md
│   └── SCORE_FORMAT.md
└── README.md
```

### 构建
```bash
# 克隆
git clone https://github.com/yourname/ManboHakimi-Harp.git
cd ManboHakimi-Harp

# 构建
dotnet build

# 运行
dotnet run --project src/ManboHakimiHarp

# 发布单文件
dotnet publish src/ManboHakimiHarp -c Release -r win-x64 \
  --self-contained true \
  -p:PublishSingleFile=true \
  -p:IncludeNativeLibrariesForSelfExtract=true
```

### 贡献
欢迎提交 Issue 和 PR。请先阅读 [CONTRIBUTING.md](docs/CONTRIBUTING.md)。

---

## 🗺️ 路线图

| 版本 | 功能 | 状态 |
|------|------|------|
| v0.1 | 浮窗框架 + 静态琴键提示 | 🚧 开发中 |
| v0.2 | 手动切换音符 + 基础热键 | ⬜ 计划中 |
| v0.3 | 音符瀑布流 + BPM 驱动 | ⬜ 计划中 |
| v0.4 | 长按/短按区分 + 进度环 | ⬜ 计划中 |
| v0.5 | 校准向导 + 配置持久化 | ⬜ 计划中 |
| v0.6 | 曲目管理 + 设置面板 | ⬜ 计划中 |
| v0.7 | 悬浮球模式 + 动效优化 | ⬜ 计划中 |
| v0.8 | 乐谱编辑器 | ⬜ 计划中 |
| v1.0 | 完整测试 + 单文件打包 | ⬜ 计划中 |

---

## ❓ 常见问题

**Q：会被封号吗？**
A：本工具不模拟输入、不读取游戏、不注入进程，但 ACE 可能对任何第三方 Overlay 进行扫描。使用风险由你自行承担。建议先在训练场测试。

**Q：全屏模式下浮窗不显示？**
A：请将游戏设置为**无边框窗口模式**。全屏独占模式下 Overlay 可能被游戏覆盖。

**Q：键位对不上？**
A：进入校准模式（`Ctrl+Shift+C`），按向导逐个对齐游戏内键位。

**Q：怎么导入自己的乐谱？**
A：将 JSON 文件放到 `scores/user/` 目录，或在设置面板点击"导入"。

**Q：支持其他游戏吗？**
A：核心逻辑通用，但校准和键位映射需针对不同游戏调整。

**Q：为什么叫 ManboHakimi-Harp？**
A：Manbo（曼波）+ Hakimi（哈基米）是网络热梗，Harp 是口琴。名字自带传播力，也希望这个工具能像梗一样被大家喜欢。

---

## 📄 许可证

[MIT License](LICENSE)

---

## 🙏 致谢

- 灵感来源：三角洲行动玩家社区的"鼠鼠文化"
- 命名灵感：Flymouse-format
- 设计参考：Arcaea / Phigros 的音符可视化
- 技术参考：WPF 高性能透明窗口方案

---

## ⭐ Star History

如果这个项目对你有帮助，欢迎点个 Star ⭐

---

> **ManboHakimi-Harp** · 曼波哈基米，启动！
>
> 手残也能弹口风琴。
