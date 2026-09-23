# Tools

Repository: `sviskis/Cleanup_AI2026` · local folder `Cleanup_AI2026` · display name Cleanup AI 2026

Development tools. None of them runs inside Illustrator; all of them are safe to
run at any time.

## Gates (run before every commit)

| Tool | What it does |
| --- | --- |
| `check_jsx.ps1` | Resolves the `#include` graph of **both** entry points (`src/Main.jsx`, `jsx/worker.jsx`), builds the bundles into `temp/`, compiles each with the Windows Script Host JScript engine (ES3, the same syntax family as ExtendScript), scans all `src/*.jsx` and `jsx/*.jsx` for forbidden ES5+/ES6 syntax and checks every `PDC.<Module>.<member>` reference against the module API. `JSON.*` is accepted because `jsx/json2.js` provides it. Exit code 1 on any error. |
| `run_tests.ps1` | Builds `temp/test_bundle.js` from `tests/jscript/stubs.js` + the `src` modules + `jsx/cleanup.jsx` + `tests/jscript/run_tests.js` and runs it with `cscript //E:JScript` (79 tests), then runs `tests/jscript/test_json_contract.js` (44 tests) against the shared fixtures. |
| `jscript_parse.js` | Helper used by the gates: compiles a single file with the JScript engine and reports `PARSE_OK` / `PARSE_FAIL`. |

## Migration and maintenance

| Tool | What it does |
| --- | --- |
| `freeze_legacy.ps1` | Builds `legacy/current_working_v10.jsx`: one standalone, ES3-verified, runnable snapshot of the current `src/` application (all `#include`s inlined) plus `legacy/README.md` with the SHA256. This is the behavioural baseline. |
| `migrate_extract_sections.ps1` | Regenerates the modules whose code is **extracted** from `archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx` by line range: `jsx/cleanup.jsx` (the canonical engine) and the legacy `src/` modules that stay extracted. Idempotent; hand written modules are never touched. Needs its UTF-8 BOM to keep Latvian literals intact. |
| `normalize_eol.ps1` | Rewrites every project text file to LF line endings (UTF-8, BOM preserved when present), which is the format the reference script and ExtendScript use. Skips `archive/original/` and `logs/`. |
| `make_demo_job.py` | Creates a demo JOB folder with a real multi page PDF (PyMuPDF) and placeholder templates, so the preflight and the one page milestone can be exercised immediately. `--pages N`, `--no-page-templates`. |

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
keep its UTF-8 BOM (it has one). Keep new PowerShell tools ASCII only, or give
them a BOM.

