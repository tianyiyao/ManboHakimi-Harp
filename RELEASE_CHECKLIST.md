# 交付检查清单

自动检查通过后，才生成可供候选测试的 EXE；公开发布还需要实机验收。

## 自动检查

- [x] `python -m ruff check --select F821,F822,F823 .` 本地通过。
- [x] `python -m unittest discover -s tests -v` 本地 16/16 通过。
- [x] `python main.py --selftest` 本地输出 `SELFTEST PASSED`。
- [x] `python -m PyInstaller --noconfirm ManboHakimi-Harp.spec` 本地构建成功。
- [x] 打包后的 `dist/ManboHakimi-Harp.exe --selftest` 本地退出码为 0。
- [ ] GitHub Actions Windows 工作流通过，下载其 EXE 再复核一次。

运行 `build.bat` 会执行本地前五项。

本地候选构建记录（2026-09-25，Windows 10，Python 3.14.5）：
`dist/ManboHakimi-Harp.exe`，46,373,922 字节，文件版本 0.15.3，
SHA-256 `649A1F4A8938D7BB2E27D5613C736F64C3CA442C490813D36D6B0B05A282FE60`，未签名。
源码或依赖变化后必须重新执行检查并更新这条记录。

## Windows 实机验收

- [ ] Windows 10 和 11 上分别完成首次启动、风险确认、退出和重启。
- [ ] 检查托盘图标与菜单、浮窗显隐、悬浮球、鼠标穿透及退出热键。
- [ ] 100%、125%、150% 缩放和双显示器间拖动后，核对琴键校准与窗口位置。
- [ ] 实测短按、长按、漏音、A-B 循环、整曲循环、变速和判定偏移。
- [ ] 编辑并保存带歌词的曲目，重启后确认音符、歌词、节拍和曲名仍在。
- [ ] 手工修改曲目 JSON 后刷新曲库；删除其他曲目时当前播放不被打断。
- [ ] 用普通用户账户从只读位置运行 EXE，确认配置回退目录可用。
- [ ] 在游戏训练场验证显示和被动按键反馈；记录游戏版本与反作弊兼容结果。

## 发布材料

- [ ] 记录内置曲谱的授权方、再分发范围和署名要求，并在公开仓库附上相应说明。
- [ ] 核对随 EXE 分发的 PySide6、Qt 等第三方组件许可与通知要求，附上相应文本。
- [ ] 核对名称、图标、截图和文案的使用权及游戏官方最新政策。
- [ ] 确定新版本号，同步 `harpguide/__init__.py`、`version_info.txt` 和 README。
- [ ] 用最终 EXE 计算 SHA-256，更新下载页的文件名、大小和校验值。
- [ ] 在干净的 Windows 虚拟机上测试最终下载文件；检查杀毒软件及 SmartScreen 提示。
- [ ] 保留最终构建记录与测试结果，再上传 Release；大规模发布前先进行小范围试用。
