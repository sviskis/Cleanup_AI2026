# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Cleanup AI 2026 desktop application.

Build it with the one supported command (it cleans first, copies the assets and
verifies the result):

    powershell -ExecutionPolicy Bypass -File tools\\build_release.ps1

or directly:

    .venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean tools\\cleanup_ai.spec

Layout of the produced distribution (`dist/Cleanup AI 2026/`):

    Cleanup AI 2026.exe      the application (windowed: no console window)
    program/                 Python, libraries and the application package
    program/jsx/             the JSX worker copied in by the build script
    program/config/          default_config.json
    program/VERSION          the version file (single source of truth)
    jsx/                     worker.jsx, cleanup.jsx, json2.js (readable, next to the exe)
    config/                  default_config.json
    logs/                    application diagnostics (JOB logs stay in JOB/LOG)
    docs/, README.md, VERSION

PyInstaller is used because the application is pure Python plus pywin32, tkinter,
customtkinter (the dark theme, pure Python with JSON theme assets that the
pyinstaller-hooks-contrib `hook-customtkinter` collects) and PyMuPDF: PyInstaller has
first class hooks for exactly those (tkinter, pywin32 COM, Pillow-free PyMuPDF), builds
a real folder distribution with no code changes, and keeps `python app.py` working
unchanged. It never bundles Illustrator - the .exe talks to the installed Illustrator
through COM.
"""

import os
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()  # noqa: F821 - provided by PyInstaller
REPO = SPEC_DIR.parent

APP_NAME = "Cleanup AI 2026"
ENTRY_SCRIPT = REPO / "app.py"
VERSION_FILE = REPO / "VERSION"
ICON_FILE = REPO / "assets" / "app.ico"
JSX_NAMES = ("worker.jsx", "cleanup.jsx", "json2.js")
CONFIG_NAMES = ("default_config.json",)
DATA_DIRS = ("jsx", "config", "docs")


def _version_tuple(text):
    parts = []
    for chunk in str(text).strip().split("."):
        digits = "".join(character for character in chunk if character.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


VERSION = _version_tuple(VERSION_FILE.read_text(encoding="utf-8") if VERSION_FILE.is_file() else "0.0.0")
VERSION_TEXT = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "0.0.0"

#: Release (default) is windowed: no Python console in production. A Debug build
#: (CLEANUP_AI_DEBUG=1, set by tools/build_release.ps1 -Configuration Debug) keeps the
#: console so a traceback is visible while troubleshooting.
CONSOLE = os.environ.get("CLEANUP_AI_DEBUG") == "1"

#: the in-bundle copies, so the .exe can find its assets no matter where it is started
datas = [(str(VERSION_FILE), ".")]
for folder in DATA_DIRS:
    path = REPO / folder
    if not path.is_dir():
        continue
    for item in path.rglob("*"):
        if item.is_file() and ".git" not in item.parts:
            datas.append((str(item), str(Path(folder) / item.relative_to(path).parent)))

hiddenimports = [
    "win32com",
    "win32com.client",
    "win32com.client.dynamic",
    "pythoncom",
    "pywintypes",
    "win32timezone",
    "win32api",
    "win32con",
    "pymupdf",
    "fitz",
    "pypdf",
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.font",
    "customtkinter",  # the dark theme (its hook collects assets/themes/*.json)
    "darkdetect",     # customtkinter's "system" appearance mode
    "xml.etree.ElementTree",
]

excludes = [
    "pytest",
    "_pytest",
    "numpy",
    "PIL",
    "matplotlib",
    "IPython",
    "pandas",
    "scipy",
    "setuptools",
    "pkg_resources",
    "test",
    "unittest",
]

version_resource = None
try:
    from PyInstaller.utils.win32.versioninfo import (  # type: ignore[import-not-found]
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    version_resource = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=VERSION,
            prodvers=VERSION,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "Cleanup AI 2026"),
                            StringStruct("FileDescription", "Cleanup AI 2026"),
                            StringStruct("FileVersion", VERSION_TEXT),
                            StringStruct("InternalName", APP_NAME),
                            StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                            StringStruct("ProductName", "Cleanup AI 2026"),
                            StringStruct("ProductVersion", VERSION_TEXT),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
except Exception:  # noqa: BLE001 - metadata is nice to have, never a build blocker
    version_resource = None

a = Analysis(  # noqa: F821 - PyInstaller globals
    [str(ENTRY_SCRIPT)],
    pathex=[str(REPO)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,  # production: windowed, no Python console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE) if ICON_FILE.is_file() else None,
    version=version_resource,
    contents_directory="program",  # the documented layout: exe + program/
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
