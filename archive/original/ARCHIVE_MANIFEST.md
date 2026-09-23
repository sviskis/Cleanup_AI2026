# Archive manifest - original reference script

These files are **verbatim copies** of the working scripts that existed before the
project was restructured. They are the reference for every behaviour in `src/`.

**Rule: never edit a file in this folder.** They are kept byte identical so that
any future refactoring step can be compared against the proven working version.

## Files

| File | Lines | Bytes | SHA256 | Role |
| --- | --- | --- | --- | --- |
| `PDF_Deep_Cleanup_AI_Template_BATCH.jsx` | 1283 | 50918 | `9913F8F7FF7B01C0EE755871DB0E7558BAEA068DEF3211B642C15C25DB3AD323` | **Primary reference** - PDF Deep Cleanup v6 + AI Template Batch v4 PAGE PICKER (ScriptUI, batch, page checkboxes). All `src/` modules were extracted from this file. |
| `PDF_Deep_Cleanup_12_MENESI_GUI_v6.jsx` | 2433 | 75095 | `87BE0DFAF877C45F1C321F5890EB1498D4EF79D27E757B3BCBBB9D00D9486ACD` | Predecessor - 12 month project GUI (JOB folder structure, `project_info.json`, three template modes, month layers). Cleanup engine of this file is the same appearance-safe v6 engine. Kept for reference; not yet part of the new project (see `TODO.md` P2). |
| `PDF_Deep_Cleanup_AI2026.jsx` | 842 | 22000 | `AD54EFA7C707236B76D10B783FD3CD83EF0057BFE0A238650F8CB8AC39587059` | Predecessor - standalone cleanup on the active document, no GUI. Oldest version of the cleanup engine. |

## Provenance

| Archive file | Original location |
| --- | --- |
| `PDF_Deep_Cleanup_AI_Template_BATCH.jsx` | `<project root>\PDF_Deep_Cleanup_AI_Template_BATCH.jsx` |
| `PDF_Deep_Cleanup_12_MENESI_GUI_v6.jsx` | `<project root>\PDF_Deep_Cleanup_AI_Template_BATCH\PDF_Deep_Cleanup_12_MENESI_GUI_v6.jsx` |
| `PDF_Deep_Cleanup_AI2026.jsx` | `<project root>\PDF_Deep_Cleanup_AI_Template_BATCH\PDF_Deep_Cleanup_AI2026.jsx` |

The two files in the `PDF_Deep_Cleanup_AI_Template_BATCH\` sub folder were byte
identical duplicates of files in the parallel working folder
`..\PDF_Deep_Cleanup_AI_Template_BATCH\` at the time of the archive
(SHA256 verified before copying).

## File format of the originals

* UTF-8 **without** BOM
* LF line endings (no CR)
* `#target illustrator`

`src/` follows exactly the same format. `tools/normalize_eol.ps1` enforces it.

## Technical notes worth remembering

* The reference script drives Illustrator through `app.preferences.PDFFileOptions`
  (`pageToOpen`, `pageRangeToOpen`, `placeAsLinks`) and `app.open(File)`.
* Page counting uses two strategies: an Illustrator probe (open with
  `pageRangeToOpen = "all"` and count artboards) and a raw PDF `/Type /Pages`
  `/Count` scan that reads the file in 2 MB chunks with `File.encoding = "BINARY"`.
* Destructive Illustrator operations used: `app.executeMenuCommand("ungroup")`,
  `app.executeMenuCommand("releaseMask")`, `item.remove()`, `document.close()`,
  `document.save()`, `File.remove()`.
* No absolute user paths were hard coded in the reference scripts - the JOB
  folder is always chosen in the GUI. This is preserved in `src/`.
