# -*- mode: python ; coding: utf-8 -*-
# Packaged Orbyn desktop app. Build with tools/build_orbyn.ps1 (or
#   py -3.12 -m PyInstaller tools/orbyn.spec --noconfirm
# from the repo root). Produces dist/Orbyn/Orbyn.exe (onedir, windowed).
from PyInstaller.utils.hooks import collect_all

# The HTML page app.py reads from its own folder must ship beside the module.
datas = [("ghostcursor/workspace/app.html", "ghostcursor/workspace")]
datas += [("ghostcursor/workspace/skills", "ghostcursor/workspace/skills")]
binaries = []
# pywin32 / UIA / winsdk and the local Whisper stack are imported dynamically.
hiddenimports = [
    "win32clipboard", "win32gui", "win32process", "win32api", "win32con",
    "comtypes.gen.UIAutomationClient", "winsdk",
]
for pkg in ("faster_whisper", "ctranslate2"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h


a = Analysis(
    ["tools/orbyn_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Orbyn",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed: no console, it is a desktop app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[], name="Orbyn",
)
