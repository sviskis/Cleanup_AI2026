# Example: the JOB folder structure

The tool does not care **where** the JOB folder is (OneDrive, a network share, an
external disk). It only cares about the layout **inside** it, which the script
creates on demand and which is kept identical to the reference script.

```text
<parent folder chosen in the GUI>
└── JOB_2026_KALENDARS\            <- "JOB folder" (chosen with "Izvēlēties...")
    ├── PDF\                        <- input: the PDF files (recursive scan)
    │   ├── calendars.pdf
    │   └── leaflets.pdf
    ├── TEMPLATE\                   <- the MASTER Illustrator template
    │   └── MASTER_AI_TEMPLATE.ai
    ├── AI_OUT\                     <- output: cleaned template copies
    │   ├── calendars_p01.ai
    │   └── calendars_p02.ai
    ├── LOG\                        <- one log file per batch run
    │   └── batch_20260923_153010.txt
    └── ERROR\                      <- reserved (per job error material)
```

## Rules of the layout

* **PDF** is scanned recursively. Folders named `template`, `ai_out`, `log`,
  `error`, `errors`, `archive` (and any `.git*` folder) are skipped, so putting a
  PDF into `AI_OUT` can never feed it back into the queue.
  The scan depth limit is `CONFIG.maxPdfScanDepth` (8) and can be changed with the
  "PDF: Mainīt..." button to point at a completely different folder.
* **TEMPLATE** must contain exactly one intended template. If several
  `*.ai` / `*.ait` files are there, the best match is picked:
  `master_ai_template.ai` (1000 points) > `master_template.ai` (900) >
  name contains `master_ai_template` (500) > `master_template` (450) >
  `template` (200) > `master` (100) > `*.ait` (+100).
  The template is only ever *read*: every output is a copy in **AI_OUT**.
* **AI_OUT** receives one AI file per processed PDF page:
  * single page PDF `leaflets.pdf` -> `leaflets.ai`
  * multi page PDF `leaflets.pdf` page 3 of 12 -> `leaflets_p03.ai`
    (padding follows the page count: `_p007` for 120 pages)
* **LOG** receives one `batch_<timestamp>.txt` file per run plus the project wide
  session log in the project folder (`logs/project.log`).

## Minimum test job

```text
JOB_TEST\
├── PDF\
│   └── one.pdf          (2-3 pages)
├── TEMPLATE\
│   └── MASTER_AI_TEMPLATE.ai   (must contain a layer named ARTWORK)
└── (AI_OUT, LOG, ERROR are created automatically)
```

Start with this before running a real batch, and keep `CONFIG.dryRun = true` for
the first pass when experimenting (see `docs/WORKFLOW.md`).
