# Packaging Cleanup AI 2026 for Windows (milestone 9)

The production build is a folder distribution with one executable:

    dist/
      Cleanup AI 2026/
        Cleanup AI 2026.exe     the application (windowed: no console window)
        program/                Python, libraries and the application package
        program/jsx/            the worker, bundled so the exe finds it anywhere
        program/config/         default_config.json
        program/VERSION
        jsx/                    worker.jsx, cleanup.jsx, json2.js (readable copies)
        config/                 default_config.json
        logs/                   application diagnostics (created by the build)
        docs/                   the documentation you are reading
        README.md VERSION CHANGELOG.md ARCHITECTURE.md STATUS.md

Development is untouched: `python app.py` keeps working exactly as before, and the
tests do not know about packaging.

## Which tool, and why

**PyInstaller 6.22** (see `requirements-packaging.txt` and `tools/cleanup_ai.spec`):

* the application is pure Python plus `pywin32` (COM), `tkinter` and `PyMuPDF` -
  PyInstaller ships first class hooks for exactly those, so there is no code change
  and no frozen-only branch anywhere in the product;
* it produces a real folder distribution (`COLLECT`), which keeps the JSX assets
  readable next to the .exe - the worker must be a normal file on disk for
  Illustrator, not something inside a one-file archive;
* a windowed build (`console=False`) gives the "no Python console" production
  experience, and `-Configuration Debug` keeps the console for troubleshooting.

Alternatives and why not: `cx_Freeze` has fewer maintained hooks for tkinter/COM on
Python 3.14 today; `Nuitka` compiles everything (slow builds, extra work for
pywin32/tkinter) for a speed gain we do not need - the heavy work happens inside
Illustrator; an embeddable Python plus a launcher script is not an EXE and forces the
user to think about Python.

**Illustrator is never bundled.** The .exe talks to the Illustrator that is installed
on the machine through COM (`adapters/illustrator.py`, the only COM code).

## Build (one command)

```powershell
# gates (check_jsx + run_tests + pytest), clean build/, build, copy assets, verify, smoke test
powershell -ExecutionPolicy Bypass -File tools\build_release.ps1

# same without the gates, or with a console for troubleshooting
powershell -ExecutionPolicy Bypass -File tools\build_release.ps1 -SkipTests
powershell -ExecutionPolicy Bypass -File tools\build_release.ps1 -Configuration Debug
```

The script

1. runs the three gates (unless `-SkipTests`),
2. deletes `build/` and `dist/`,
3. runs PyInstaller with `tools/cleanup_ai.spec`,
4. copies `jsx/`, `config/`, `docs/` plus the top level docs next to the .exe (and into
   `program/`), creates `logs/`,
5. **verifies** the result: `Cleanup AI 2026.exe`, `program/python3*.dll`, the JSX
   files and `default_config.json` both next to the exe and inside `program/`, and that
   no `Illustrator.exe` slipped in,
6. runs the packaged executable once with `--diagnose` and fails the build when the
   exit code is not 0.

## Paths, version and logs

* `pdf_ai_batch/paths.py` resolves everything from the executable (frozen) or the
  repository (source) - never from the current working directory, because Illustrator
  runs the worker with its own cwd. An installed app can be moved anywhere;
  `PDF_AI_BATCH_HOME` overrides the install folder (portable use), and
  `PDF_AI_BATCH_ROOT` stays the development/test override.
* Writable folders fall back to `%LOCALAPPDATA%\Cleanup AI 2026\...` when the install
  folder is read only, so **nothing ever has to be written into Program Files**.
* `VERSION` is the single source of truth: it reaches the GUI status bar,
  `--diagnose`, the executable's version resource (ProductVersion `0.9.0`), the logs
  and every job report (`app_version`).
* Application logs: `<install>\logs\app.log` (or the per user folder). Job logs stay
  where they always were: `JOB\LOG\app.log`, `JOB\LOG\batch_<stamp>.log`,
  `JOB\LOG\reports\`.

## Startup diagnostics

`Cleanup AI 2026.exe --diagnose` prints paths plus the production diagnostics: version,
frozen/source, Python and architecture, PyInstaller/bundle, pywin32 availability, the
JSX assets with their paths, `default_config.json`, the writable runtime/log folders,
whether Illustrator is installed (registry ProgID + Adobe folders, **without launching
it**), Illustrator reachability only with `--with-illustrator`, and the working
directory. Exit code 1 when a required resource is missing.

A windowed build has no console: the diagnostics attach to the console you launched it
from (so `--diagnose` works from cmd), otherwise the text goes to
`<install>\logs\console.log`. When the packaged GUI starts it verifies its own assets
and, if something is missing, shows a message box with the reason instead of failing
later with a traceback.

## Desktop shortcut (opt-in)

```powershell
powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1
powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1 -Target "D:\Apps\Cleanup AI 2026"
```

Neither the application nor the build ever writes to the desktop on its own.

## Icon

`assets/app.ico` is used when it exists; the repository has no branding artwork, so the
Release build currently has the default Windows icon. Drop a `.ico` there and rebuild -
no code change is needed.

## Packaged acceptance (real Illustrator)

`temp/run_packaged_acceptance_m9.py` proves the distribution, not the source tree
(evidence `temp/packaged_acceptance_m9.txt`): layout and size, PE subsystem 2 (GUI, no
console), ProductVersion `0.9.0`, `--version`/`--diagnose` from a different working
directory, `--preflight-project` -> READY, `--run-all` of 7 real pages through
Illustrator (state.json + an immutable report written by the packaged app, counts
agreeing), a Latvian project path with spaces, the GUI opening and closing cleanly
(`temp/gui_m9_window.png`), the shortcut tool writing only into an explicit folder, and
`Illustrator Documents.Count == 0` at the end.

## Known limitations

* Windows only (PyInstaller builds for the platform it runs on; no cross compile).
* The distribution is not signed - Windows SmartScreen may warn on first start.
* The documentation `docs/` copy inside the distribution is optional; delete it if the
  install should stay minimal.
* No installer exists yet (copy the folder, optionally create a shortcut). An MSI/Inno
  Setup package is out of scope for v1.0.

