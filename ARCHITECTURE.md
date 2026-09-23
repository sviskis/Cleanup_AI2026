# ARCHITECTURE

The full architecture document is **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
This file is a one screen summary for quick orientation.

## Layers

```text
ui/BatchWindow.jsx        VIEW        ScriptUI widgets + event wiring only
        |
        v  view interface (addLog, renderPageRows, setProgress, setRunning, ...)
core/BatchRunner.jsx      CONTROLLER  state, scan, page jobs, batch loop
        |
        v
core/*  engines           PdfCleanup, PdfPageCount, TemplateManager,
                          OutputManager, Diagnostics
services/*                FileService (File/Folder), LogService, ErrorService
        |
        v
Illustrator DOM + filesystem
```

## Hard rules

1. `src/Main.jsx` is the only entry point; modules load through `#include`.
2. Every module registers itself: `PDC.registerModule("Name", (function () { ... }()))`.
3. ES3 syntax only - `var`, `function`, `try/catch`. No `let`, `const`, arrows,
   `class`, `import`/`export`, `Promise`, template literals.
4. The view never makes decisions; the controller never touches widgets.
5. The MASTER template is only ever read.
6. `CONFIG.dryRun` and `overwriteExisting = false` are the safety defaults.
7. `logs/project.log` + `logs/errors/<timestamp>/` are the trace of what happened.

## Related documents

| Document | Content |
| --- | --- |
| [docs/CODE_ANALYSIS.md](docs/CODE_ANALYSIS.md) | what the reference script did, function by function, risks and the mapping to the new modules |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | layering, module responsibilities, `#include` order, config, logging, error handling, fail safe rules, extension points |
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | how to run the tool, dry run, first run on a new job, troubleshooting, branch strategy |
| [docs/TESTING.md](docs/TESTING.md) | automated checks + the manual Illustrator checklist |
| [tests/TEST_PLAN.md](tests/TEST_PLAN.md) | test strategy, levels, case index, entry/exit criteria |
| [archive/original/ARCHIVE_MANIFEST.md](archive/original/ARCHIVE_MANIFEST.md) | the untouched reference scripts with SHA256 hashes |
| [tools/README.md](tools/README.md) | the development tools and what they verify |
