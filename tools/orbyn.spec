# -*- mode: python ; coding: utf-8 -*-
# Packaged Orbyn desktop app. Build with tools/build_orbyn.ps1 (or
#   py -3.12 -m PyInstaller tools/orbyn.spec --noconfirm
# from the repo root). Produces dist/Orbyn/Orbyn.exe (onedir, windowed).
import os

from PyInstaller.utils.hooks import collect_all

# Relative paths in a .spec resolve against the spec's own directory (tools/),
# not the repo root, so anchor everything to the repo root explicitly.
_ROOT = os.path.dirname(SPECPATH)  # SPECPATH = <repo>/tools ; _ROOT = <repo>

# The HTML page app.py reads from its own folder must ship beside the module.
datas = [(os.path.join(_ROOT, "ghostcursor", "workspace", "app.html"), "ghostcursor/workspace")]
datas += [(os.path.join(_ROOT, "ghostcursor", "workspace", "skills"), "ghostcursor/workspace/skills")]
binaries = []
# pywin32 / UIA / winsdk and the local Whisper stack are imported dynamically.
hiddenimports = [
    "win32clipboard", "win32gui", "win32process", "win32api", "win32con",
    "comtypes.gen.UIAutomationClient", "winsdk",
]

# Voice (faster_whisper/ctranslate2) is an OPTIONAL extra (requirements-voice.txt)
# and is imported lazily by /voice and /dictate. Bundling it drags in a broken
# tensorflow hook ("Failed to read tensorflow.__version__") that fails the build,
# so the packaged app ships core-only; install the voice extras into the running
# Python to use voice. Build with ORBYN_BUNDLE_VOICE=1 to attempt bundling it.
if os.environ.get("ORBYN_BUNDLE_VOICE") == "1":
    for pkg in ("faster_whisper", "ctranslate2"):
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    _VOICE_EXCLUDES = []
else:
    _VOICE_EXCLUDES = ["faster_whisper", "ctranslate2", "tensorflow"]


a = Analysis(
    [os.path.join(_ROOT, "tools", "orbyn_app.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", *_VOICE_EXCLUDES],
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
