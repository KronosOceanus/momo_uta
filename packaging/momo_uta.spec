# -*- mode: python ; coding: utf-8 -*-
"""Build one of three macOS apps:

  MOMO_VARIANT=base  no vocals dependencies
  MOMO_VARIANT=thin  no bundled demucs, external demucs/ffmpeg
  MOMO_VARIANT=full  bundles demucs + torch + ffmpeg
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
VARIANT = os.environ.get("MOMO_VARIANT", "base")
assert VARIANT in ("base", "thin", "full"), VARIANT
NAME = f"momo-uta-{VARIANT}"

datas = [
    (str(ROOT / "config" / "defaults.json"), "config"),
    (str(ROOT / "data" / "tables"), "data/tables"),
    (str(ROOT / "data" / "curated" / "lyrics_exclude.json"), "data/curated"),
    (str(ROOT / "data" / "curated" / "glossary_lyrics.json"), "data/curated"),
    (str(ROOT / "data" / "curated" / "counters.json"), "data/curated"),
    (str(ROOT / "data" / "corpus" / "ndl_reading_stats.json"), "data/corpus"),
    (str(ROOT / "src" / "momo_player" / "static"), "momo_player/static"),
]
datas += collect_data_files("sudachidict_core")
datas += collect_data_files("sudachipy")

excludes = ["tkinter", "pytest", "IPython"]
if VARIANT != "full":
    excludes += ["demucs", "torch", "torchaudio", "torchvision", "torchgen",
                 "functorch", "triton"]

hiddenimports = [
    "webview.platforms.cocoa",
    "AppKit",
    "Foundation",
    "PyObjCTools",
    "mutagen",
    "sudachipy",
    "sudachidict_core",
    "momo_yomi.annotate",
    "momo_player.core.vocals",
]

binaries = []
if VARIANT == "full":
    datas += collect_data_files("demucs")
    hiddenimports += collect_submodules("demucs")
    hiddenimports += ["torch"]
    ffmpeg = Path("/opt/homebrew/bin/ffmpeg")
    if ffmpeg.is_file():
        binaries.append((str(ffmpeg), "bin"))

a = Analysis(
    [str(ROOT / "src" / "momo_uta_app" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "momo-uta-logo.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=NAME,
)

app = BUNDLE(
    coll,
    name=f"{NAME}.app",
    icon=str(ROOT / "assets" / "momo-uta-logo.icns"),
    bundle_identifier=f"local.momo.uta.{VARIANT}",
    info_plist={
        "CFBundleName": "桃歌",
        "CFBundleDisplayName": "桃歌",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
