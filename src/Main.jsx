/*
    PDF DEEP CLEANUP AI 2026
    Version: 0.2.0

    Adobe:
    Illustrator (ExtendScript / JSX)

    Entry point:
    src/Main.jsx

    Purpose:
    Batch conversion of PDF pages into Illustrator template documents:
      1. Illustrator opens the selected page of a PDF.
      2. PDF Deep Cleanup (appearance safe) removes PDF technical junk:
         safe groups, safe vector clipping masks, crop marks.
      3. The MASTER template from the JOB TEMPLATE folder is COPIED to AI_OUT
         (the template itself is never modified).
      4. The copy is opened and the cleaned PDF artwork is duplicated into the
         template layer "ARTWORK".
      5. The AI file is saved, the PDF document is closed WITHOUT saving.

    Modules are loaded with ExtendScript #include, in dependency order.
    Hand written modules are documented in docs/ARCHITECTURE.md.

    How to run:
      Illustrator -> File -> Scripts -> Other Script... -> src/Main.jsx
      (or drop src/Main.jsx into the Illustrator Scripts folder)
*/

#target illustrator

#include "utils/Namespace.jsx"
#include "config/Config.jsx"
#include "utils/TextUtils.jsx"
#include "services/FileService.jsx"
#include "utils/Paths.jsx"
#include "services/LogService.jsx"
#include "services/ErrorService.jsx"
#include "../jsx/cleanup.jsx"
#include "core/PdfPageCount.jsx"
#include "core/TemplateManager.jsx"
#include "core/OutputManager.jsx"
#include "core/BatchRunner.jsx"
#include "core/Diagnostics.jsx"
#include "ui/BatchWindow.jsx"
/* ------------------------------------------------------------------ */

function projectVersionFile() {
    try {
        return new File(PDC.Paths.getProjectRoot().fsName + "/VERSION");
    } catch (e) {
        return null;
    }
}

function checkVersionConsistency() {
    try {
        var f = projectVersionFile();
        if (!f || !f.exists) return;
        var text = PDC.FileService.readTextFile(f);
        var tag = String(text).replace(/[\r\n\t ]/g, "");
        if (tag && tag !== PDC.CONFIG.version) {
            PDC.LogService.logWarning("VERSION fails (" + tag + ") nesakrīt ar CONFIG.version (" + PDC.CONFIG.version + ")");
        }
    } catch (e) {}
}

function banner() {
    var lines = [];
    lines.push("PDF Deep Cleanup AI 2026 v" + PDC.CONFIG.version);
    lines.push("Project: " + PDC.TextUtils.displayPath(PDC.Paths.getProjectRoot()));
    lines.push("Modules: " + PDC.moduleList());
    if (PDC.CONFIG.dryRun) lines.push("*** DRY RUN REŽĪMS: faili netiks rakstīti ***");
    if (PDC.CONFIG.debug) lines.push("*** DEBUG režīms ***");
    return lines.join("\r\n");
}

function main() {
    PDC.LogService.startSession();
    PDC.LogService.logInfo("Script started from " + PDC.TextUtils.displayPath(PDC.Paths.getScriptFile()));
    PDC.LogService.logInfo(banner().replace(/\r\n/g, " | "));

    checkVersionConsistency();

    if (PDC.CONFIG.debug) {
        PDC.Diagnostics.logResults(null);
    }

    PDC.BatchWindow.open();

    PDC.LogService.logInfo("Script finished (window closed).");
    PDC.LogService.flushSessionLog();
}

try {
    main();
} catch (err) {
    try {
        PDC.ErrorService.handleError(err, { operation: "Main entry point (src/Main.jsx)" });
        try { PDC.LogService.flushSessionLog(); } catch (e2) {}
    } catch (err2) {
        alert("Kritiska kļūda: " + err + "\n\n(ErrorService nav pieejams: " + err2 + ")");
    }
}
