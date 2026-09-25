# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置：ManboHakimi-Harp 单文件 EXE
# 用法： pyinstaller --noconfirm ManboHakimi-Harp.spec
from pathlib import Path
import sys

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('scores/*.json', 'scores'), ('assets/icon.ico', 'assets')],
    hiddenimports=['harpguide'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 仅打包当前 Python / 虚拟环境中的 DLL。开发机 PATH 可能含别的软件附带的
# 同名 DLL（例如 ICU）；PyInstaller 若把它们捎进 EXE，Qt 会加载到错误版本。
_binary_roots = (Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
a.binaries = [entry for entry in a.binaries
              if any(Path(entry[1]).resolve().is_relative_to(root)
                     for root in _binary_roots)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ManboHakimi-Harp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                 # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    version='version_info.txt',    # Windows 文件属性中的版本号/版权信息
)
