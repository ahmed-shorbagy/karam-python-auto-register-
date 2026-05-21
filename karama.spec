# PyInstaller spec — run: python build_release.py
from PyInstaller.utils.hooks import collect_all

block_cipher = None

playwright_datas, playwright_binaries, playwright_hidden = collect_all("playwright")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=playwright_binaries,
    datas=playwright_datas,
    hiddenimports=playwright_hidden + [
        "aiohttp", "bs4", "app_paths", "notify_format", "config_loader",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KaramaStart",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="KaramaAutomation",
)
