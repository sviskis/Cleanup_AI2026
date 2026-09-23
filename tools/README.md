# Tools

Development tools. None of them runs inside Illustrator; all of them are safe to
run at any time.

| Tool | What it does |
| --- | --- |
| `check_jsx.ps1` | **The gate before every commit.** Resolves the `#include` graph of `src/Main.jsx`, builds `temp/verify_bundle.js`, compiles it with the Windows Script Host JScript engine (ES3, the same syntax family as ExtendScript), scans all `src/*.jsx` for forbidden ES5+/ES6 syntax, and checks every `PDC.<Module>.<member>` reference against the API that module exports. Exit code 1 on any error. |
| `run_tests.ps1` | Builds `temp/test_bundle.js` from `tests/jscript/stubs.js` + all `src` modules (entry point excluded) + `tests/jscript/run_tests.js` and runs it with `cscript //E:JScript`. 79 unit tests, no Illustrator needed. |
| `jscript_parse.js` | Helper used by `check_jsx.ps1`: compiles a single file with the JScript engine and reports `PARSE_OK` / `PARSE_FAIL`. |
| `migrate_extract_sections.ps1` | Regenerates the eight modules whose code is **extracted** from `archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx` by line range. Idempotent, does not touch hand written modules. Needs its UTF-8 BOM to keep Latvian literals intact. |
| `normalize_eol.ps1` | Rewrites every text file of the project to LF line endings (UTF-8, BOM preserved when present), which is the format the reference script and ExtendScript use. |

## Cheat sheet

```powershell
powershell -ExecutionPolicy Bypass -File tools\check_jsx.ps1
powershell -ExecutionPolicy Bypass -File tools\check_jsx.ps1 -SkipParse
powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1
powershell -ExecutionPolicy Bypass -File tools\normalize_eol.ps1 -WhatIfOnly
powershell -ExecutionPolicy Bypass -File tools\migrate_extract_sections.ps1
```

## Why JScript for validation

The ExtendScript engine inside Illustrator is an ES3 engine. The Windows Script
Host JScript engine (5.8) is ES3 with a few ES5 extras and ships with every
Windows installation, so `new Function(source)` gives a *real* syntax verdict for
ExtendScript code without starting Illustrator. It cannot check Illustrator DOM
behaviour - that is what the manual checklist in `docs/TESTING.md` is for.

## Encoding rule

PowerShell 5.1 reads `.ps1` files without a BOM as ANSI. `migrate_extract_sections.ps1`
contains Latvian replacement strings, so it must keep its UTF-8 BOM (it has one).
Keep new PowerShell tools ASCII only, or give them a BOM.
