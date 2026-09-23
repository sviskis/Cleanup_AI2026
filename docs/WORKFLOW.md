# Workflow

Repository: `sviskis/Cleanup_AI2026` · display name: Cleanup AI 2026

## 1. Install (nothing to install)

1. Copy or clone the project folder anywhere (OneDrive, a network share, a USB
   drive - no configuration needed, see `docs/ARCHITECTURE.md` §4).
2. Keep the folder structure intact: `src/Main.jsx` finds everything else
   relative to itself.

Optional: put a shortcut to `src/Main.jsx` into the Illustrator scripts folder so
it shows up in *File > Scripts*.

## 2. Run

```text
Illustrator
  File -> Scripts -> Other Script...   ->  <project>\src\Main.jsx
```

The batch window appears. Nothing is written before you press **START BATCH**.

## 3. Operating the window

| Control | What it does |
| --- | --- |
| **Darba folderis / Izvēlēties...** | choose the JOB folder. `PDF`, `TEMPLATE`, `AI_OUT`, `LOG`, `ERROR` are created inside it |
| **PDF: Mainīt...** | point the scan at a completely different folder (manual override) |
| **Template: Mainīt...** | pick a specific `*.ai` / `*.ait` template file directly |
| **AI OUT: Mainīt...** | write the outputs somewhere else than `JOB\AI_OUT` |
| **Pārrakstīt esošos AI** | default **off**. Off = existing outputs are skipped and reported as `SKIP` |
| **Iztīrīt template slāni "ARTWORK"** | default **on**. Clears placeholders in the copy before the artwork is inserted |
| **Visas ✓ / Nevienu / Apgriezt** | page list helpers |
| **Pārbaudīt / pārlasīt PDF** | rescan folders and page counts (forces a fresh page detection) |
| **START BATCH** | process every ticked page |
| **Diagnostika** | environment/preflight report (Illustrator version, folders, write access, template, config, modules) |
| **Aizvērt** | close the window (also writes the JOB log) |

## 4. The first run on a new job

1. Prepare the JOB folder:

   ```text
   JOB_xxx\PDF\...            your PDFs
   JOB_xxx\TEMPLATE\...       exactly one MASTER_AI_TEMPLATE.ai (with a layer "ARTWORK")
   ```

2. Start the script, choose the JOB folder.
3. Press **Diagnostika** - all checks should be `[OK]`. Fix anything that is not
   before continuing.
4. Tick only **one page** of one PDF and press **START BATCH**. Check the result in
   Illustrator: artwork present, template elements intact, layer `ARTWORK` used.
5. Now tick the remaining pages and run the real batch.

## 5. Dry run (safe planning)

Set in `src/config/Config.jsx`:

```javascript
dryRun: true,
```

What changes:

* no file is copied, opened, saved or deleted;
* every planned page is written to the log panel and the session log as
  `PLĀNS <pdf> | lapa <n> → <output> (dry run: netiek izpildīts)`;
* the final dialog reports `DRY RUN` and the number of planned pages;
* the window shows `*** DRY RUN: faili netiks rakstīti ***`.

Switch it back to `false` for real work. This is the recommended way to verify
that folder detection, page counting and output naming are correct before a large
job.

## 6. What happens to each page

```text
PDF page (ticked)          TEMPLATE\MASTER_AI_TEMPLATE.ai
        |                              |
        | 1. app.open(pdf, page)       | 3. copy
        v                              v
   PDF document  --- 2. cleanup --->  AI_OUT\<name>_p03.ai
        |                                  |
        | 4. duplicate all layers into     | 5. open, find/create layer ARTWORK,
        |    layer "ARTWORK"               |    save
        v                                  v
   close WITHOUT saving            saved AI document
```

Naming: `leaflets.pdf` single page -> `leaflets.ai`,
`leaflets.pdf` page 3 of 12 -> `leaflets_p03.ai`.

## 7. Reading the result

* Window log + `JOB\LOG\batch_<timestamp>.txt`: one line per page
  (`OK`, `SKIP`, `PLĀNS`, `ERROR`) with object counts and cleanup statistics
  (`ungrp=`, `masks=`, `crop=`).
* `logs/project.log`: the same events with timestamps, appended over sessions.
* `logs/errors/<timestamp>/`: only when something failed.

## 8. Troubleshooting

| Symptom | Look at |
| --- | --- |
| "Template nav atrasts" | is there exactly one `*.ai` / `*.ait` in `TEMPLATE`? Name it `MASTER_AI_TEMPLATE.ai` to be unambiguous |
| page count looks wrong | open the PDF in Illustrator to confirm; the count comes from either the Illustrator probe or the raw PDF `/Pages /Count` scan |
| everything is `SKIP` | the outputs already exist and "Pārrakstīt esošos AI" is off |
| `ERROR` on every page | check `logs/errors/<timestamp>/context.txt` - the report records the input file, output file, template and the effective config |
| artwork missing in the AI | template has no `ARTWORK` layer and "Iztīrīt template slāni" removed placeholders - check the template |
| Illustrator becomes quiet / no dialogs afterwards | should not happen any more; the run restores `userInteractionLevel` in a `finally` block |

## 9. Development workflow

```powershell
# 1. check the project (must be green)
powershell -ExecutionPolicy Bypass -File tools\check_jsx.ps1
powershell -ExecutionPolicy Bypass -File tools\run_tests.ps1

# 2. work in src/ (see .clinerules)

# 3. re-check, then commit
git add -A
git commit -m "refactor: ..."
```

Extracted legacy code is regenerated, never hand edited:

```powershell
powershell -ExecutionPolicy Bypass -File tools\migrate_extract_sections.ps1
powershell -ExecutionPolicy Bypass -File tools\normalize_eol.ps1
```

### Branch strategy

| Branch | Use |
| --- | --- |
| `main` | always working, green checks |
| `feature/<name>` | new capability (e.g. `feature/pdf-page-detection`) |
| `fix/<name>` | bug fix (e.g. `fix/clipping-mask-release`) |
| `refactor/<name>` | internal change without behaviour change |

### Before a real batch

Test with a small JOB (1 PDF, 2-3 pages) after any change to
`core/PdfCleanup.jsx`, `core/TemplateManager.jsx` or `core/BatchRunner.jsx`. The
script itself is checked automatically, the *visual* result is not - see
`docs/TESTING.md`.
