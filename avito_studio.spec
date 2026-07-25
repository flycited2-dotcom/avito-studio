# -*- mode: python ; coding: utf-8 -*-

import subprocess
from pathlib import Path

bridge_root = (Path(SPECPATH).parent / "avito-bridge").resolve()
studio_root = Path(SPECPATH).resolve()
bridge_lock = studio_root / "bridge.lock"
bridge_revision = bridge_lock.read_text(encoding="ascii").strip()
if len(bridge_revision) != 40 or any(
    character not in "0123456789abcdef" for character in bridge_revision
):
    raise SystemExit("bridge.lock must contain exactly one lowercase 40-character commit hash")
required_bridge_dirs = (
    "config",
    "profiles",
    "avito-descriptions",
    "src/avito_bridge",
)
missing_bridge_dirs = [
    name for name in required_bridge_dirs if not (bridge_root / name).is_dir()
]
if missing_bridge_dirs:
    raise SystemExit(
        "Cannot build a functional Studio executable: "
        f"Bridge checkout is missing at {bridge_root} "
        f"(required directories: {', '.join(missing_bridge_dirs)})"
    )
try:
    bridge_head = subprocess.check_output(
        ["git", "-C", str(bridge_root), "rev-parse", "HEAD"],
        text=True,
        encoding="utf-8",
    ).strip()
except (OSError, subprocess.CalledProcessError) as exc:
    raise SystemExit(f"Cannot verify paired Bridge checkout: {exc}") from exc
if bridge_head != bridge_revision:
    raise SystemExit(
        "Cannot build a reproducible Studio executable: "
        f"bridge.lock requires {bridge_revision}, checkout is {bridge_head}"
    )
bridge_status = subprocess.check_output(
    [
        "git",
        "-C",
        str(bridge_root),
        "status",
        "--porcelain",
        "--untracked-files=normal",
    ],
    text=True,
    encoding="utf-8",
).strip()
if bridge_status:
    raise SystemExit(
        "Cannot build a reproducible Studio executable: "
        "the paired Bridge checkout contains uncommitted or untracked files"
    )
bridge_datas = []
for folder in ("config", "profiles", "avito-descriptions"):
    source = bridge_root / folder
    if source.exists():
        bridge_datas.append((str(source), f"bridge-template/{folder}"))
bridge_datas.append((str(bridge_lock), "build-metadata"))

a = Analysis(
    ['src\\avito_studio\\app.py'],
    # Put the verified neighbouring checkout ahead of any globally/editably
    # installed avito_bridge.  The executable code and bundled templates now
    # come from the same exact, clean bridge.lock revision.
    pathex=[
        str(studio_root / "src"),
        str(bridge_root / "src"),
    ],
    binaries=[],
    datas=bridge_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AvitoContentStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(studio_root / "packaging" / "windows_version_info.txt"),
)
