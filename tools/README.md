# Tools

Repository: `sviskis/Cleanup_AI2026` · local folder `Cleanup_AI2026` · display name Cleanup AI 2026

Development tools. None of them runs inside Illustrator; all of them are safe to
run at any time.

## Gates (run before every commit)

| Tool | What it does |
| --- | --- |
| `check_jsx.ps1` | Resolves the `#include` graph of **both** entry points (`src/Main.jsx`, `jsx/worker.jsx`), builds the bundles into `temp/`, compiles each with the Windows Script Host JScript engine (ES3, the same syntax family as ExtendScript), scans all `src/*.jsx` and `jsx/*.jsx` for forbidden ES5+/ES6 syntax, checks every `PDC.<Module>.<member>` reference against the module API, and verifies that every file in `jsx/` is ASCII only, without a BOM and with LF line endings. `JSON.*` is accepted because `jsx/json2.js` provides it. Exit code 1 on any error. |
| `run_tests.ps1` | Builds `temp/test_bundle.js` from `tests/jscript/stubs.js` + the `src` modules + `jsx/cleanup.jsx` + `tests/jscript/run_tests.js` and runs it with `cscript //E:JScript` (79 tests), then runs `tests/jscript/test_json_contract.js` (44 tests) against the shared fixtures. |
| `jscript_parse.js` | Helper used by the gates: compiles a single file with the JScript engine and reports `PARSE_OK` / `PARSE_FAIL`. |

## Migration and maintenance

| Tool | What it does |
| --- | --- |
| `freeze_legacy.ps1` | Builds `legacy/current_working_v10.jsx`: one standalone, ES3-verified, runnable snapshot of the current `src/` application (all `#include`s inlined) plus `legacy/README.md` with the SHA256. This is the behavioural baseline. |
| `migrate_extract_sections.ps1` | Regenerates the modules whose code is **extracted** from `archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx` by line range: `jsx/cleanup.jsx` (the canonical engine) and the legacy `src/` modules that stay extracted. Idempotent; hand written modules are never touched. Needs its UTF-8 BOM to keep Latvian literals intact, and escapes its `jsx/` output to ASCII (`\uXXXX`) so ExtendScript cannot mis-decode it. |
| `normalize_eol.ps1` | Rewrites every project text file to LF line endings (UTF-8, BOM preserved when present), which is the format the reference script and ExtendScript use. Skips `archive/original/` and `logs/`. |
| `make_demo_job.py` | Creates a demo JOB folder with a real multi page PDF (PyMuPDF) and placeholder templates, so the preflight and the one page milestone can be exercised immediately. `--pages N`, `--no-page-templates`. |

## Packaging (milestone 9)

| Tool | What it does |
| --- | --- |
| `build_release.ps1` | **One command** for the production Windows build: runs the three gates (unless `-SkipTests`), deletes `build/` + `dist/`, runs PyInstaller with `cleanup_ai.spec`, copies `jsx/`, `config/`, `docs/` and the top level docs next to the `.exe` (and into `program/`), creates `logs/`, verifies every required asset is present and that no `Illustrator.exe` was bundled, then runs the packaged `--diagnose` as a smoke test. `-Configuration Debug` keeps the console. |
| `cleanup_ai.spec` | The PyInstaller recipe: entry `app.py`, `tkinter`/`pywin32`/PyMuPDF hidden imports, `jsx/`, `config/`, `docs/` as data, a version resource from `VERSION`, `COLLECT` into `dist/Cleanup AI 2026/` with `console=False` in Release. It documents why PyInstaller and never includes Illustrator. |
| `create_shortcut.ps1` | Opt-in desktop shortcut for the built application (`-Target`, `-ShortcutFolder`, `-AllUsers`). Nothing in the application or the build writes to a desktop by itself. |

Full documentation (layout, paths, version, logs, limitations): `docs/PACKAGING.md`.
Packaging requirements: `requirements-packaging.txt`. Acceptance evidence:
`temp/packaged_acceptance_m9.txt`.

## Cheat sheet

```powershell
# gates
powershell -ExecutionPolicy Bypass -File tools\check_jsx.ps1
powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1
.venv\Scripts\python.exe -m pytest

# maintenance / migration
powershell -ExecutionPolicy Bypass -File tools\freeze_legacy.ps1
powershell -ExecutionPolicy Bypass -File tools\migrate_extract_sections.ps1
powershell -ExecutionPolicy Bypass -File tools\normalize_eol.ps1 -WhatIfOnly

# production build (gates + PyInstaller + assets + verification + smoke test)
powershell -ExecutionPolicy Bypass -File tools\build_release.ps1

# optional desktop shortcut for the built application
powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1

# demo job for the first end to end test
.venv\Scripts\python.exe tools\make_demo_job.py --root temp\DEMO_JOB --pages 14
```

## Why JScript for validation

The ExtendScript engine inside Illustrator is an ES3 engine. The Windows Script
Host JScript engine (5.8) is ES3 with a few ES5 extras and ships with every
Windows installation, so `new Function(source)` gives a *real* syntax verdict for
ExtendScript code without starting Illustrator. It cannot check Illustrator DOM
behaviour - that is what the manual checklist in `docs/TESTING.md` is for.

## Encoding rule

PowerShell 5.1 reads `.ps1` files without a BOM as ANSI.
`migrate_extract_sections.ps1` contains Latvian replacement strings, so it must
keep its UTF-8 BOM (it has one - a missing BOM silently writes mojibake into the
generated files). The same applies to `build_release.ps1` and `create_shortcut.ps1`,
which print Latvian progress text - both carry a BOM. Keep new PowerShell tools ASCII
only, or give them a BOM (a missing BOM is a parse error, not just mojibake: the
mojibake byte can break a string literal).

`jsx/*.jsx` and `jsx/*.js` must be **pure ASCII** (write Latvian as `\uXXXX`
escapes), without a BOM and with LF line endings:

* Illustrator decodes a large BOM-less UTF-8 `.jsx` loaded with
  `doJavaScriptFile` as ANSI (Windows codepage), so a raw Latvian literal arrives
  as mojibake inside the running worker and ends up in `runtime/current_result.json`;
* `\uXXXX` escapes survive every decoder, so ASCII sources are the only form that
  is guaranteed to survive.

`tools/check_jsx.ps1` fails the build on a non-ASCII byte in `jsx/`, and
`pdf_ai_batch/tests/test_encoding.py` scans the whole project for cp1252 mojibake.
Python files are UTF-8 (they are read by Python itself), and the legacy `src/`
GUI modules still carry raw Latvian text - converting them is a follow-up item in
`TODO.md`.

