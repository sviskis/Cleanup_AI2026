# Testing

Two levels:

1. **Automated** (no Illustrator needed) - run before every commit.
2. **Manual in Illustrator** - run before a real job, because the appearance of
   cleaned artwork can only be judged visually.

## 1. Automated checks

```powershell
powershell -ExecutionPolicy Bypass -File tools\check_jsx.ps1
powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1
```

### `tools/check_jsx.ps1`

| Check | What it proves |
| --- | --- |
| include resolution | every `#include` in `src/Main.jsx` exists, every `src` module is reachable, no orphan module |
| bundle compile | the concatenated bundle (`temp/verify_bundle.js`) is compiled by the **WSH JScript 5.8 engine**, the same ES3 syntax family as ExtendScript |
| ES3 scan | no `let`, `const`, arrow functions, `async`/`await`, `class`, `import`/`export`, `Promise`, template literals, spread/rest, optional chaining. Comments and string literals are ignored, so documentation text about those keywords does not trigger it |
| ES5+ helpers (warning) | flags `forEach`, `map`, `filter`, `reduce`, `Object.keys`, `JSON.*`, `String.trim`, `startsWith`, `endsWith`, `includes` if they ever appear |
| API wiring | every `PDC.<Module>.<member>` reference in the project must exist in that module's exported API |

Exit code 0 = green. This is the gate described in `.clinerules`.

### `tools/run_tests.ps1`

Builds `temp/test_bundle.js` from `tests/jscript/stubs.js` (a fake `File`,
`Folder`, `app`, `$` host with an in-memory filesystem), all `src` modules except
the entry point, and `tests/jscript/run_tests.js`. It runs with
`cscript //E:JScript`, which also re-proves ES3 syntax of the tested code.

Current result: **79 passed, 0 failed**. Coverage:

| Area | Examples |
| --- | --- |
| module wiring | 12 modules registered, `EXPECTED_MODULES` all present |
| config defaults | `dryRun`/`debug`/`overwriteExisting` false, `ARTWORK`, 9 rows, depth 8, 40 ungroup passes, excluded folder list |
| naming | `baseNameNoExt` edge cases, `padPageNumber` (1/1, 3/9, 3/12, 12/120), `makePageOutputName` (`a.ai`, `a_p03.ai`, `a_p007.ai`), `pageJobKey` |
| scan rules | excluded folders (`log`, `ai_out`, `errors`) vs kept (`pdf`, `artwork`), write test on a missing folder |
| text IO | `writeTextFile` / `readTextFile` / `appendTextFile` round trip |
| logging | level format `| INFO |`, warning, error always written, debug suppressed when `debug = false` |
| errors | `error.txt` content, `context.txt` content, dialog text, `errorMessage(null)` |
| diagnostics | all checks have `name`/`value`/`ok`, report text |
| cleanup stats | `summaryLine()` counters and reset, `run(null)` raises |
| template | `templateScore` ranking, empty folder returns `null` |
| paths | project root, config/logs/errors folders, JOB folder layout, no hard coded suggestion |

What the automated level **cannot** cover: Illustrator DOM behaviour
(`app.open`, `executeMenuCommand`, `duplicate`, artboard geometry), real PDF page
counting, and the visual result of the cleanup.

## 2. Manual checklist in Illustrator

Run this after any change to `core/`, and at least once per release. Keep a
throwaway JOB folder with 1 PDF (2-3 pages) and 1 template.

### Smoke

| # | Step | Expected |
| --- | --- | --- |
| S1 | File > Scripts > Other Script... > `src/Main.jsx` | window opens, log shows `PDF Deep Cleanup → AI Template Batch v0.1.0` and the project path |
| S2 | press **Aizvērt** right away | window closes, `logs/project.log` was appended |
| S3 | press **Diagnostika** | report opens, `logs/` and `temp/` are `[OK]`, the template line names the template file |
| S4 | press **Izvēlēties...** and cancel the dialog | nothing changes, no error, window still usable |
| S5 | press **START BATCH** with no JOB folder chosen | nothing happens (no crash) |

### Functional

| # | Step | Expected |
| --- | --- | --- |
| F1 | choose the test JOB folder | log block, PDF count, page list filled, status line with template `OK` |
| F2 | tick one page, **START BATCH** | `OK` line with `obj=`, `ungrp=`, `masks=`, `crop=`; `AI_OUT` contains the named AI file |
| F3 | open the produced AI | template elements intact, PDF artwork inside layer `ARTWORK` |
| F4 | compare the AI with the PDF visually | no missing shapes, no shifted objects, no leftover crop marks |
| F5 | run the same page again | `SKIP`, file untouched |
| F6 | tick "Pārrakstīt esošos AI", run again | `OK`, file replaced |
| F7 | untick "Iztīrīt template slāni ARTWORK", process a fresh page | old layer content stays, new artwork is added |
| F8 | 12 page PDF | output names `_p01` ... `_p12`, count matches the Illustrator page count |
| F9 | PDF with Latvian characters and spaces in the name | same name in `AI_OUT`, no mojibake in the log |
| F10 | **Pārbaudīt / pārlasīt PDF** | page counts and tick state are preserved |

### Error handling

| # | Step | Expected |
| --- | --- | --- |
| E1 | empty `PDF` folder | `! PDF nav atrasts.`, START BATCH disabled |
| E2 | no template in `TEMPLATE` | `! Template nav atrasts...`, START BATCH disabled |
| E3 | password protected PDF | `ERROR` for that page, batch continues, report in `logs/errors/<ts>/` |
| E4 | 0 byte PDF file | `ERROR` (or the 1 page fallback), batch continues |
| E5 | read-only `AI_OUT` folder | the page fails with a clear error, batch continues, report written |
| E6 | try to close the window during a run | not possible, the button is disabled |
| E7 | `CONFIG.dryRun = true`, run 3 pages | three `PLĀNS` lines, `AI_OUT` unchanged, final dialog says `DRY RUN` |
| E8 | after E3..E5 | Illustrator still shows normal dialogs, the window is usable, **Aizvērt** works |

### Regression against the reference script

`archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx` must produce the same
result as `src/Main.jsx` for the same JOB and the same ticked pages. Run both and
compare:

| # | Compare | How |
| --- | --- | --- |
| R1 | output file names | directory listing of `AI_OUT` |
| R2 | cleanup statistics | `ungrp=`, `masks=`, `crop=` values in the log lines |
| R3 | artwork placement | overlay both AI files in Illustrator and check the bounding box |
| R4 | page count detection | same `lapas=<n> | <method>` lines |
| R5 | skip behaviour | same `SKIP` lines |

If R1-R5 match, the refactor is behaviour neutral. Any difference must be recorded
in `CHANGELOG.md` with a reason.

## 3. Regression test assets

Keep them outside the repository (they are real work files and `.gitignore` blocks
`*.pdf`): a JOB folder with a 3 page PDF, a 12 page PDF, a PDF with Latvian
characters in the name, and a MASTER template containing an `ARTWORK` layer with
placeholder objects.

## 4. Future automation ideas

* Extend `tests/jscript/stubs.js` with a fake document model to unit test
  `duplicateSourceLayersIntoArtwork` layer ordering.
* Python + win32com harness: open a test PDF in Illustrator through COM, run
  `src/Main.jsx` with `dryRun = true`, then assert on `logs/project.log` - this
  would let the batch loop be tested end to end automatically.
* Golden file comparison of `AI_OUT` bounding boxes through COM.
