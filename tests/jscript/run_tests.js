/*
    Cleanup AI 2026
    Test suite: tests/jscript/run_tests.js

    Purpose:
      Unit tests for the host independent logic (naming, config, logging,
      error reports, diagnostics, module wiring). Runs with the Windows Script
      Host JScript engine, so it also proves that the tested code keeps ES3
      syntax:

        powershell -ExecutionPolicy Bypass -File tools/run_tests.ps1

      Scope limits: anything that needs real Illustrator documents (cleanup,
      page counting through Illustrator, the batch loop with app.open) cannot
      be executed here - that part is covered by the manual checklist in
      docs/TESTING.md.
*/

var __pass = 0;
var __fail = 0;
var __failures = [];

function ok(name, condition, detail) {
    if (condition) {
        __pass++;
        WScript.Echo("  PASS  " + name);
    } else {
        __fail++;
        __failures.push(name);
        WScript.Echo("  FAIL  " + name + (detail ? ("   -> " + detail) : ""));
    }
}

function eq(name, actual, expected) {
    ok(name, String(actual) === String(expected), "expected [" + expected + "] got [" + actual + "]");
}

function section(title) {
    WScript.Echo("");
    WScript.Echo("== " + title + " ==");
}

section("module wiring");

ok("PDC exists", typeof PDC === "object");
eq("module count", PDC.MODULES.length, 12);
ok("moduleList text", PDC.moduleList().indexOf("PdfCleanup") >= 0);

var expectedModules = PDC.Diagnostics.EXPECTED_MODULES;
var missingModules = [];
for (var mi = 0; mi < expectedModules.length; mi++) {
    if (!PDC[expectedModules[mi]]) missingModules.push(expectedModules[mi]);
}
ok("all expected modules registered", missingModules.length === 0, missingModules.join(","));

section("config defaults (reference behaviour)");

eq("version", PDC.CONFIG.version, "0.2.0");
eq("dryRun", PDC.CONFIG.dryRun, false);
eq("debug", PDC.CONFIG.debug, false);
eq("overwriteExisting", PDC.CONFIG.overwriteExisting, false);
eq("artworkLayerName", PDC.CONFIG.artworkLayerName, "ARTWORK");
eq("visiblePageRows", PDC.CONFIG.visiblePageRows, 9);
eq("maxPdfScanDepth", PDC.CONFIG.maxPdfScanDepth, 8);
eq("ungroupPasses", PDC.CONFIG.cleanup.ungroupPasses, 40);
eq("releaseSafeVectorMasks", PDC.CONFIG.cleanup.releaseSafeVectorMasks, true);
eq("deleteCropMarks", PDC.CONFIG.cleanup.deleteCropMarks, true);
eq("folder input", PDC.CONFIG.folders.input, "PDF");
eq("folder output", PDC.CONFIG.folders.output, "AI_OUT");
eq("excluded folder count", PDC.CONFIG.excludedScanFolders.length, 6);

section("TextUtils (reference functions)");

eq("baseNameNoExt pdf", PDC.TextUtils.baseNameNoExt(new File("C:/JOB/PDF/leaflet.pdf")), "leaflet");
eq("baseNameNoExt upper", PDC.TextUtils.baseNameNoExt(new File("C:/JOB/PDF/LEAFLET.PDF")), "LEAFLET");
eq("baseNameNoExt dotted", PDC.TextUtils.baseNameNoExt(new File("C:/JOB/PDF/plan.v2.pdf")), "plan.v2");
eq("baseNameNoExt noext", PDC.TextUtils.baseNameNoExt(new File("C:/JOB/PDF/noext")), "noext");

eq("padPageNumber 3/12", PDC.TextUtils.padPageNumber(3, 12), "03");
eq("padPageNumber 3/9", PDC.TextUtils.padPageNumber(3, 9), "03");
eq("padPageNumber 12/120", PDC.TextUtils.padPageNumber(12, 120), "012");
eq("padPageNumber 1/1", PDC.TextUtils.padPageNumber(1, 1), "01");

ok("formatTimestamp shape", /^\d{8}_\d{6}$/.test(PDC.TextUtils.formatTimestamp(new Date())));
ok("formatLogTimestamp shape", /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(PDC.TextUtils.formatLogTimestamp(new Date())));
ok("formatFolderTimestamp shape", /^\d{4}-\d{2}-\d{2}_\d{6}$/.test(PDC.TextUtils.formatFolderTimestamp(new Date())));

eq("displayPath", PDC.TextUtils.displayPath(new File("C:/JOB/a.pdf")), "C:/JOB/a.pdf");

section("OutputManager naming (reference behaviour)");

eq("single page output", PDC.OutputManager.makePageOutputName(new File("C:/JOB/PDF/a.pdf"), 1, 1), "a.ai");
eq("multi page output", PDC.OutputManager.makePageOutputName(new File("C:/JOB/PDF/a.pdf"), 3, 12), "a_p03.ai");
eq("3 digit output", PDC.OutputManager.makePageOutputName(new File("C:/JOB/PDF/a.pdf"), 7, 120), "a_p007.ai");
eq("pageJobKey", PDC.OutputManager.pageJobKey(new File("C:/JOB/PDF/A.PDF"), 2), "c:/job/pdf/a.pdf|2");
eq("no template in empty folder", String(PDC.TemplateManager.detectTemplate(new Folder("C:/stub/missing"))), "null");

section("FileService scan rules");

eq("exclude log", PDC.FileService.isExcludedByName("log"), true);
eq("exclude ai_out", PDC.FileService.isExcludedByName("ai_out"), true);
eq("exclude errors", PDC.FileService.isExcludedByName("errors"), true);
eq("keep pdf", PDC.FileService.isExcludedByName("pdf"), false);
eq("keep artwork", PDC.FileService.isExcludedByName("artwork"), false);

ok("writable folder stub", PDC.FileService.isWritableFolder(new Folder("C:/stub/logs")));
ok("missing folder is not writable", !PDC.FileService.isWritableFolder(new Folder("C:/stub/missing")));

var tf = new File("C:/stub/logs/probe.txt");
ok("writeTextFile", PDC.FileService.writeTextFile(tf, "hello\n", "UTF-8"));
eq("readTextFile roundtrip", PDC.FileService.readTextFile(tf), "hello\n");
ok("appendTextFile", PDC.FileService.appendTextFile(tf, "world\n", "UTF-8"));
eq("appended content", PDC.FileService.readTextFile(tf), "hello\nworld\n");

section("LogService");

PDC.LogService.startSession();
PDC.LogService.logInfo("unit test info");
PDC.LogService.logWarning("unit test warning");
PDC.LogService.logError("unit test error");
var session = PDC.LogService.getSessionLines().join("\n");
ok("info logged", session.indexOf("| INFO | unit test info") >= 0);
ok("warning logged", session.indexOf("| WARNING | unit test warning") >= 0);
ok("error logged", session.indexOf("| ERROR | unit test error") >= 0);
ok("session start logged", session.indexOf("Session started") >= 0);
ok("debug suppressed when debug=false", PDC.LogService.logDebug("should not appear") === "");

PDC.LogService.writeJobLog(new Folder("C:/stub/logs"), ["line one", "line two"]);
ok("job log written", PDC.LogService.flushSessionLog());

section("ErrorService report building");

var err = new Error("Neizdevās atvērt PDF");
err.fileName = "src/core/PdfPageCount.jsx";
err.line = 42;

var errorText = PDC.ErrorService.buildErrorText(err, { operation: "Unit test" });
ok("error.txt has PROJECT", errorText.indexOf("PROJECT:") >= 0);
ok("error.txt has message", errorText.indexOf("Neizdevās atvērt PDF") >= 0);
ok("error.txt has file", errorText.indexOf("PdfPageCount.jsx") >= 0);
ok("error.txt has line", errorText.indexOf("42") >= 0);

var ctxText = PDC.ErrorService.buildContextText(err, { operation: "Unit test", inputFile: new File("C:/JOB/PDF/a.pdf") });
ok("context.txt has CONFIG", ctxText.indexOf("CONFIG:") >= 0);
ok("context.txt has input file", ctxText.indexOf("a.pdf") >= 0);
ok("context.txt has operation", ctxText.indexOf("Unit test") >= 0);
eq("messageless error handled", PDC.ErrorService.errorMessage(null).indexOf("Nezināma kļūda") >= 0, true);

var dialogText = PDC.ErrorService.buildDialogText(err, { operation: "Unit test" }, null);
ok("dialog has Operation", dialogText.indexOf("Operation: Unit test") >= 0);
ok("dialog has Message", dialogText.indexOf("Message:") >= 0);

section("Diagnostics");

var results = PDC.Diagnostics.collect(null);
ok("diagnostics returns checks", results.length >= 12);
var badShape = 0;
for (var ri = 0; ri < results.length; ri++) {
    var r = results[ri];
    if (!r.name || r.value === undefined || r.ok === undefined) badShape++;
}
eq("every check has name/value/ok", badShape, 0);

var text = PDC.Diagnostics.runText(null);
ok("diagnostics text has header", text.indexOf("DIAGNOSTIKA") >= 0);
ok("diagnostics reports result line", text.indexOf("Rezultāts:") >= 0);

section("PdfCleanup stats");

PDC.PdfCleanup.resetStats();
eq("summary of fresh stats", PDC.PdfCleanup.summaryLine(), "ungrp=0 riskyGrp=0 masks=0 riskyMask=0 maskPaths=0 crop=0");

var stats = PDC.PdfCleanup.getStats();
stats.safeGroupsUngrouped = 4;
stats.cropPerimetersDeleted = 2;
stats.shortCropMarksDeleted = 1;
eq("summary reflects counters", PDC.PdfCleanup.summaryLine(stats), "ungrp=4 riskyGrp=0 masks=0 riskyMask=0 maskPaths=0 crop=3");

PDC.PdfCleanup.resetStats();
eq("reset works", PDC.PdfCleanup.summaryLine(), "ungrp=0 riskyGrp=0 masks=0 riskyMask=0 maskPaths=0 crop=0");

var runFailed = false;
try {
    PDC.PdfCleanup.run(null);
} catch (eRun) {
    runFailed = true;
}
ok("run(null) raises a clear error", runFailed);

section("TemplateManager scoring");

ok("ait template ranks higher", PDC.TemplateManager.templateScore(new File("C:/JOB/TEMPLATE/master_ai_template.ait")) >
   PDC.TemplateManager.templateScore(new File("C:/JOB/TEMPLATE/other.ai")));
ok("master_ai_template.ai wins", PDC.TemplateManager.templateScore(new File("C:/JOB/TEMPLATE/master_ai_template.ai")) >= 1000);

section("Paths");

eq("project root from script path", PDC.Paths.getProjectRoot().fsName, "C:/stub");
eq("config folder", PDC.Paths.getConfigFolder().fsName, "C:/stub/config");
eq("logs folder", PDC.Paths.getLogsFolder().fsName, "C:/stub/logs");
eq("errors folder", PDC.Paths.getErrorsFolder().fsName, "C:/stub/logs/errors");
eq("job input folder", PDC.Paths.getInputFolder(new Folder("C:/JOB")).fsName, "C:/JOB/PDF");
eq("job output folder", PDC.Paths.getOutputFolder(new Folder("C:/JOB")).fsName, "C:/JOB/AI_OUT");
eq("job log folder", PDC.Paths.getLogsFolderForJob(new Folder("C:/JOB")).fsName, "C:/JOB/LOG");
eq("no hard coded job suggestion", String(PDC.Paths.getSuggestedJobFolder()), "null");

WScript.Echo("");
WScript.Echo("========================================");
WScript.Echo("PASSED: " + __pass + "   FAILED: " + __fail);
if (__fail > 0) {
    for (var fi = 0; fi < __failures.length; fi++) {
        WScript.Echo("  failed: " + __failures[fi]);
    }
    WScript.Quit(1);
}
WScript.Echo("ALL TESTS PASSED");
WScript.Quit(0);
