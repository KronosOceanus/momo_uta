# -*- mode: python ; coding: utf-8 -*-
"""Build one of three macOS apps:

  MOMO_VARIANT=thin  no bundled demucs, external demucs/ffmpeg
  MOMO_VARIANT=full  bundles demucs + torch + ffmpeg
"""
import os
import shutil
import subprocess
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
VARIANT = os.environ.get("MOMO_VARIANT", "thin")
assert VARIANT in ("thin", "full"), VARIANT
NAME = f"momo-uta-{VARIANT}"

datas = [
    (str(ROOT / "config" / "defaults.json"), "config"),
    (str(ROOT / "data" / "tables"), "data/tables"),
    (str(ROOT / "data" / "curated" / "lyrics_exclude.json"), "data/curated"),
    (str(ROOT / "data" / "curated" / "glossary_lyrics.json"), "data/curated"),
    (str(ROOT / "data" / "curated" / "counters.json"), "data/curated"),
    (str(ROOT / "data" / "corpus" / "ndl_reading_stats.json"), "data/corpus"),
    (str(ROOT / "src" / "momo_player" / "static"), "momo_player/static"),
    (str(ROOT / "packaging" / "licenses"), "licenses"),
]
datas += collect_data_files("sudachidict_core")
datas += collect_data_files("sudachipy")

excludes = ["tkinter", "pytest", "IPython"]
if VARIANT == "thin":
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

def _find_tool(name: str, env: str, extra: list[str]) -> Path | None:
    candidates = []
    value = os.environ.get(env)
    if value:
        candidates.append(Path(value))
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    candidates += [Path(x) for x in extra]
    for path in candidates:
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return path
        except OSError:
            pass
    return None


def _find_ffmpeg() -> Path | None:
    return _find_tool("ffmpeg", "MOMO_FFMPEG",
                      ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"])


def _soundtouch_lib(stretch: Path) -> Path | None:
    value = os.environ.get("MOMO_SOUNDTOUCH_LIB")
    if value:
        p = Path(value)
        if p.is_file():
            return p
    try:
        out = subprocess.check_output(["otool", "-L", str(stretch)], text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in out.splitlines()[1:]:
        part = line.strip().split(" ", 1)[0]
        if "libSoundTouch" in part:
            p = Path(part)
            if p.is_file():
                return p
    return None


# soundstretch + libSoundTouch 在 thin / full 都随包。
soundstretch = _find_tool("soundstretch", "MOMO_SOUNDSTRETCH",
                          ["/opt/homebrew/bin/soundstretch",
                           "/usr/local/bin/soundstretch"])
if soundstretch is None:
    raise SystemExit("构建需要 soundstretch（brew install sound-touch）")
touch_lib = _soundtouch_lib(soundstretch)
if touch_lib is None:
    raise SystemExit("找不到 libSoundTouch.1.dylib，可设置 MOMO_SOUNDTOUCH_LIB")
tools_dir = ROOT / "build" / "bundle-tools"
tools_dir.mkdir(parents=True, exist_ok=True)
st_copy = tools_dir / "soundstretch"
lib_copy = tools_dir / touch_lib.name
for dest in (st_copy, lib_copy):
    try:
        dest.chmod(0o644)
    except OSError:
        pass
shutil.copy2(soundstretch, st_copy)
shutil.copy2(touch_lib, lib_copy)
st_copy.chmod(0o755)
subprocess.run(["install_name_tool", "-change", str(touch_lib),
                "@executable_path/" + touch_lib.name, str(st_copy)], check=True)
binaries = [(str(st_copy), "bin"), (str(lib_copy), "bin")]


if VARIANT == "full":
    datas += collect_data_files("demucs")
    hiddenimports += collect_submodules("demucs")
    hiddenimports += ["torch"]
    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        raise SystemExit(
            "full 构建需要 ffmpeg；请安装后确保在 PATH，"
            "或设置 MOMO_FFMPEG=/path/to/ffmpeg")
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
        "CFBundleShortVersionString": "1.0.1",
        "CFBundleVersion": "1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
