/*
    PDF DEEP CLEANUP AI 2026 - FROZEN WORKING VERSION (v10 baseline)

    This single file was generated automatically by tools/freeze_legacy.ps1.
    It is the frozen, runnable snapshot of the current working Illustrator
    application (the multi module app under src/), inlined in include order.

    Generated : 2026-09-23 16:22:03
    From      : src\Main.jsx
    Git commit: f8528e8
    Modules   : 15

    DO NOT EDIT. Edit src/ and regenerate, or edit nothing and compare against it.
    Run: Illustrator -> File -> Scripts -> Other Script... -> this file
*/

#target illustrator

// ---------------------------------------------------------------------------
// FROZEN FROM: src/utils/Namespace.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/utils/Namespace.jsx

    Purpose:
      Single global namespace object PDC for the whole project. Every module
      attaches itself with PDC.registerModule("Name", api) so that:
        * nothing leaks into the global scope of the Illustrator engine
          (except the one PDC object);
        * modules can talk to each other as PDC.Config / PDC.FileService / ...
        * a typo becomes a clear runtime error instead of a silent undefined.

      This file MUST be included first in src/Main.jsx.

    ExtendScript: ES3 safe.
*/

var PDC = PDC || {};

if (!PDC.MODULES) {
    PDC.MODULES = [];
}

PDC.registerModule = function (name, api) {
    if (PDC[name]) {
        throw new Error("PDC modulis jau ir reģistrēts: " + name);
    }
    PDC[name] = api;
    PDC.MODULES.push(name);
    return api;
};

PDC.moduleList = function () {
    return PDC.MODULES.join(", ");
};

// ---------------------------------------------------------------------------
// FROZEN FROM: src/config/Config.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/config/Config.jsx

    Purpose:
      Every tunable value of the project in one place. The reference script had
      the JOB folder names and the cleanup switches hard coded in several files;
      here they are collected, so a change never needs a code search.

      Nothing in this file touches the filesystem or Illustrator.

    Defaults are the reference behaviour:
      debug        = false  (quiet)
      dryRun       = false  (real batch)
      overwriteExisting = false (never overwrite an existing AI output silently)

    ExtendScript: ES3 safe (no trailing commas, no let/const, no arrow functions).
*/

PDC.CONFIG = {

    projectName: "PDF Deep Cleanup AI 2026",
    appName: "PDF Deep Cleanup → AI Template Batch",
    version: "0.1.0",

    /* --- behaviour switches, plan phases 16 and 17 --- */
    debug: false,
    dryRun: false,
    overwriteExisting: false,
    clearArtworkByDefault: true,

    /* --- Illustrator / workflow values --- */
    artworkLayerName: "ARTWORK",
    visiblePageRows: 9,
    maxPdfScanDepth: 8,
    excludedScanFolders: ["template", "ai_out", "log", "error", "errors", "archive"],

    /* --- JOB folder layout (created on demand inside the chosen JOB folder) --- */
    folders: {
        input: "PDF",
        template: "TEMPLATE",
        config: "CONFIG",
        output: "AI_OUT",
        temp: "TEMP",
        logs: "LOG",
        errors: "ERROR"
    },

    /* --- logging, plan phase 9 --- */
    log: {
        level: "INFO",
        sessionFileName: "project.log",
        jobFilePrefix: "batch",
        errorReportFolder: "errors"
    },

    /* --- PDF Deep Cleanup engine switches, plan phase 12 ---
       The two "preserve" values are intent documentation: the reference engine
       always preserved image and transparency structures through its
       "safe only" tests. They are kept here so a future unsafe mode has a
       switch to read, but changing them has no effect today. */
    cleanup: {
        preserveImageStructures: true,
        preserveTransparencyStructures: true,
        releaseSafeVectorMasks: true,
        deleteCropMarks: true,
        ungroupPasses: 40
    },

    /* --- optional: suggested JOB folder shown by diagnostics ("" = none) --- */
    defaultJobFolder: ""
};

// ---------------------------------------------------------------------------
// FROZEN FROM: src/utils/TextUtils.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/utils/TextUtils.jsx

    Purpose:
      String, file name and timestamp helpers.

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 16-24, 199-203, 344-350).
      The three functions marked "new" below were added for logging and error
      reports and did not exist in the reference script.

    ExtendScript: ES3 safe. No let / const / arrow functions / String.trim.
*/

PDC.registerModule("TextUtils", (function () {
    function baseNameNoExt(fileObj) {
        var n = fileObj.name; var p = n.lastIndexOf(".");
        if (p > 0) n = n.substring(0, p);
        try { return decodeURI(n); } catch (e) { return n; }
    }

    function displayPath(obj) {
        if (!obj) return "";
        try { return decodeURI(obj.fsName); } catch (e) { return obj.fsName; }
    }

    function formatTimestamp() {
        var d = new Date();
        function z(n) { return n < 10 ? "0" + n : n; }
        return d.getFullYear() + z(d.getMonth()+1) + z(d.getDate()) + "_" + z(d.getHours()) + z(d.getMinutes()) + z(d.getSeconds());
    }

    function padPageNumber(pageNo, totalPages) {
        var digits = String(totalPages).length;
        if (digits < 2) digits = 2;
        var s = String(pageNo);
        while (s.length < digits) s = "0" + s;
        return s;
    }
    /* ---- new: log / report timestamps ---- */

    function formatLogTimestamp(dateObj) {
        var d = dateObj ? dateObj : new Date();
        function z(n) { return (n < 10 ? "0" : "") + n; }
        return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate()) +
               " " + z(d.getHours()) + ":" + z(d.getMinutes()) + ":" + z(d.getSeconds());
    }

    function formatFolderTimestamp(dateObj) {
        var d = dateObj ? dateObj : new Date();
        function z(n) { return (n < 10 ? "0" : "") + n; }
        return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate()) +
               "_" + z(d.getHours()) + z(d.getMinutes()) + z(d.getSeconds());
    }

    return {
        baseNameNoExt: baseNameNoExt,
        displayPath: displayPath,
        formatTimestamp: formatTimestamp,
        padPageNumber: padPageNumber,
        formatLogTimestamp: formatLogTimestamp,
        formatFolderTimestamp: formatFolderTimestamp
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/services/FileService.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/services/FileService.jsx

    Purpose:
      All filesystem access in one place: path building, folder creation,
      PDF scanning, file signature, safe document close, free removal helpers.

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 10-15, 25-78, 183-190, 216-221).
      Only two details were adjusted:
        * isExcludedPdfScanFolder() reads CONFIG.excludedScanFolders now
          (same default list: template, ai_out, log, error, errors, archive, .git*);
        * listPdfFilesRecursive() takes its default depth from CONFIG.maxPdfScanDepth
          (same default value 8).

    ExtendScript: ES3 safe.
*/

PDC.registerModule("FileService", (function () {
    // ====================== HELPERS ======================
    function pathJoin(folder, name) { return new File(folder.fsName + "/" + name); }
    function folderJoin(folder, name) { return new Folder(folder.fsName + "/" + name); }
    function ensureFolder(folder) {
        if (!folder.exists) { if (!folder.create()) throw new Error("Nevar izveidot folderi: " + folder.fsName); }
    }

    function sortPdfFiles(files) {
        files.sort(function(a, b) {
            var an = a.fsName.toLowerCase();
            var bn = b.fsName.toLowerCase();
            return an < bn ? -1 : (an > bn ? 1 : 0);
        });
        return files;
    }
    function listPdfFiles(pdfFolder) {
        if (!pdfFolder || !pdfFolder.exists) return [];
        var files = pdfFolder.getFiles(function(f) {
            return (f instanceof File) && /\.pdf$/i.test(f.name);
        });
        return sortPdfFiles(files);
    }
    function isExcludedPdfScanFolder(folderObj) {
        if (!folderObj) return true;
        var n = ""; try { n = decodeURI(folderObj.name).toLowerCase(); } catch(e) { n = folderObj.name.toLowerCase(); }
        return isExcludedByName(n);
    }
    function listPdfFilesRecursive(rootFolder, maxDepth) {
        var result = [];
        if (!rootFolder || !rootFolder.exists) return result;
        if (maxDepth === undefined || maxDepth === null) maxDepth = PDC.CONFIG.maxPdfScanDepth;
        function walk(folderObj, depth) {
            if (!folderObj || !folderObj.exists) return;
            if (depth > maxDepth) return;
            var entries = [];
            try { entries = folderObj.getFiles(); } catch (e0) { return; }
            for (var i = 0; i < entries.length; i++) {
                var entry = entries[i];
                if (entry instanceof File) {
                    try { if (/\.pdf$/i.test(entry.name)) result.push(entry); } catch (e1) {}
                } else if (entry instanceof Folder) {
                    if (isExcludedPdfScanFolder(entry)) continue;
                    walk(entry, depth + 1);
                }
            }
        }
        walk(rootFolder, 0);
        return sortPdfFiles(result);
    }
    function resolvePdfQueue(jobFolder, preferredPdfFolder, manualPdfFolder) {
        if (manualPdfFolder && manualPdfFolder.exists) {
            return { root: manualPdfFolder, files: listPdfFilesRecursive(manualPdfFolder, 8), mode: "MANUAL" };
        }
        if (preferredPdfFolder && preferredPdfFolder.exists) {
            var preferredFiles = listPdfFilesRecursive(preferredPdfFolder, 8);
            if (preferredFiles.length > 0) {
                return { root: preferredPdfFolder, files: preferredFiles, mode: "JOB\\PDF" };
            }
        }
        return { root: jobFolder, files: listPdfFilesRecursive(jobFolder, 8), mode: "AUTO RECURSIVE" };
    }

    function safeClose(doc, saveOption) {
        if (!doc) return;
        try { doc.close(saveOption); } catch(e) {}
    }
    function removeIfExists(fileObj) {
        if (fileObj && fileObj.exists) try { return fileObj.remove(); } catch(e) {}
        return true;
    }

    function safeFileSignature(fileObj) {
        var len = 0, mod = "";
        try { len = fileObj.length; } catch(e0) {}
        try { mod = String(fileObj.modified); } catch(e1) {}
        return String(len) + "|" + mod;
    }
    /* ---- new: config driven scan folder exclusion ---- */

    function isExcludedByName(lowerName) {
        var list = PDC.CONFIG.excludedScanFolders;
        for (var i = 0; i < list.length; i++) {
            if (lowerName === String(list[i]).toLowerCase()) return true;
        }
        return false;
    }

    /* ---- new: write permission test + text file helpers ---- */

    function isWritableFolder(folderObj) {
        var probe = null;
        try {
            if (!folderObj) return false;
            if (!folderObj.exists) return false;
            probe = new File(folderObj.fsName + "/__pdc_write_test.tmp");
            if (!probe.open("w")) return false;
            probe.writeln("write test");
            probe.close();
            try { probe.remove(); } catch (eRemove) {}
            return true;
        } catch (e) {
            try { if (probe && probe.exists) probe.remove(); } catch (eClean) {}
            return false;
        }
    }

    function writeTextFile(fileObj, text, encodingName) {
        try {
            fileObj.encoding = encodingName ? encodingName : "UTF-8";
            fileObj.lineFeed = "Windows";
            if (!fileObj.open("w")) return false;
            fileObj.write(text);
            fileObj.close();
            return true;
        } catch (e) {
            try { if (fileObj.opened) fileObj.close(); } catch (e2) {}
            return false;
        }
    }

    function appendTextFile(fileObj, text, encodingName) {
        var old = "";
        try {
            if (fileObj.exists) {
                fileObj.encoding = encodingName ? encodingName : "UTF-8";
                if (fileObj.open("r")) {
                    old = fileObj.read();
                    fileObj.close();
                }
            }
        } catch (e1) {
            old = "";
        }
        return writeTextFile(fileObj, old + text, encodingName);
    }

    function readTextFile(fileObj) {
        try {
            if (!fileObj || !fileObj.exists) return "";
            fileObj.encoding = "UTF-8";
            if (!fileObj.open("r")) return "";
            var s = fileObj.read();
            fileObj.close();
            return s;
        } catch (e) {
            try { if (fileObj.opened) fileObj.close(); } catch (e2) {}
            return "";
        }
    }

    return {
        pathJoin: pathJoin,
        folderJoin: folderJoin,
        ensureFolder: ensureFolder,
        sortPdfFiles: sortPdfFiles,
        listPdfFiles: listPdfFiles,
        isExcludedPdfScanFolder: isExcludedPdfScanFolder,
        isExcludedByName: isExcludedByName,
        listPdfFilesRecursive: listPdfFilesRecursive,
        resolvePdfQueue: resolvePdfQueue,
        safeClose: safeClose,
        removeIfExists: removeIfExists,
        safeFileSignature: safeFileSignature,
        isWritableFolder: isWritableFolder,
        writeTextFile: writeTextFile,
        appendTextFile: appendTextFile,
        readTextFile: readTextFile
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/utils/Paths.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/utils/Paths.jsx

    Purpose:
      Central path management, plan phase 7.

      Two different worlds are kept apart:
        1. PROJECT paths - always derived from the location of src/Main.jsx via
           $.fileName. Nothing in this project is allowed to hard code a path
           like C:\\Users\\...\\Desktop.
        2. JOB paths - the JOB folder is chosen by the operator in the GUI and
           lives outside the project. They are only ever built as
           <chosenJobFolder>\\<folder name from CONFIG.folders>.

      Windows specifics handled here:
        * forward slashes are used for File()/Folder() construction, which
          ExtendScript accepts on Windows and keeps OneDrive paths, spaces and
          Latvian characters safe;
        * decodeURI() is applied by TextUtils.displayPath() when a path is shown
          to the user, never when it is used on disk.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("Paths", (function () {

    function getScriptFile() {
        var name = "";
        try { name = $.fileName; } catch (e0) { name = ""; }
        if (!name) return null;
        return new File(name);
    }

    function getSrcFolder() {
        var f = getScriptFile();
        if (!f) return new Folder(Folder.current.fsName);
        return f.parent;
    }

    function getProjectRoot() {
        var src = getSrcFolder();
        var root = src.parent;
        if (root && root.exists) return root;
        return src;
    }

    function projectPath(relativePath) {
        return new File(getProjectRoot().fsName + "/" + relativePath);
    }

    function projectFolder(relativePath) {
        return new Folder(getProjectRoot().fsName + "/" + relativePath);
    }

    function getConfigFolder() { return projectFolder("config"); }
    function getLogsFolder()   { return projectFolder("logs"); }

    function getErrorsFolder() {
        return projectFolder("logs/" + PDC.CONFIG.log.errorReportFolder);
    }

    function getTempFolder() { return projectFolder("temp"); }

    /* --- JOB folder layout --- */

    function jobFolders(jobFolder) {
        return {
            root: jobFolder,
            input: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.input),
            template: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.template),
            config: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.config),
            output: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.output),
            temp: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.temp),
            logs: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.logs),
            errors: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.errors)
        };
    }

    function getInputFolder(jobFolder)    { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.input); }
    function getTemplateFolder(jobFolder) { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.template); }
    function getOutputFolder(jobFolder)   { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.output); }
    function getLogsFolderForJob(jobFolder)   { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.logs); }
    function getErrorsFolderForJob(jobFolder) { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.errors); }

    function getSuggestedJobFolder() {
        var configured = PDC.CONFIG.defaultJobFolder;
        if (configured) {
            var f = new Folder(configured);
            if (f.exists) return f;
        }
        return null;
    }

    return {
        getScriptFile: getScriptFile,
        getSrcFolder: getSrcFolder,
        getProjectRoot: getProjectRoot,
        projectPath: projectPath,
        projectFolder: projectFolder,
        getConfigFolder: getConfigFolder,
        getLogsFolder: getLogsFolder,
        getErrorsFolder: getErrorsFolder,
        getTempFolder: getTempFolder,
        jobFolders: jobFolders,
        getInputFolder: getInputFolder,
        getTemplateFolder: getTemplateFolder,
        getOutputFolder: getOutputFolder,
        getLogsFolderForJob: getLogsFolderForJob,
        getErrorsFolderForJob: getErrorsFolderForJob,
        getSuggestedJobFolder: getSuggestedJobFolder
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/services/LogService.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/services/LogService.jsx

    Purpose:
      One logging entry point for the whole project.

      Log line format written to every log file:
        2026-09-23 15:30:10 | INFO | Script started

      Two destinations are used:
        * project session log : <project>/logs/project.log
        * job batch log       : <JOB>/LOG/batch_<timestamp>.txt
          (the job batch log keeps the exact behaviour of the reference script,
           which wrote one text file per batch run into the JOB LOG folder)

    Source:
      writeJobLog() (legacy name writeLogFile) is extracted unchanged from the
      reference script (lines 204-213) except for two adapted call sites:
      ensureFolder -> PDC.FileService.ensureFolder, and the whole writer is
      wrapped in try/catch so a failed log write can never abort a batch.
      logInfo / logWarning / logError / logDebug are new.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("LogService", (function () {

    var LEVELS = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 };

    var sessionStart = null;
    var sessionLines = [];
    function writeLogFile(logFolder, lines) {
        PDC.FileService.ensureFolder(logFolder);
        var f = new File(logFolder.fsName + "/" + PDC.CONFIG.log.jobFilePrefix + "_" + PDC.TextUtils.formatTimestamp() + ".txt");
        f.encoding = "UTF-8";
        f.lineFeed = "Windows";
        if (f.open("w")) {
            for (var i = 0; i < lines.length; i++) f.writeln(lines[i]);
            f.close();
        }
    }    /* ---- new: levelled session logging ---- */

    function startSession() {
        sessionStart = new Date();
        sessionLines = [];
        logInfo("Session started. Version " + PDC.CONFIG.version + " | " + PDC.CONFIG.appName);
    }

    function currentLevel() {
        var name = "INFO";
        try { name = String(PDC.CONFIG.log.level).toUpperCase(); } catch (e) {}
        return (LEVELS[name] !== undefined) ? LEVELS[name] : LEVELS.INFO;
    }

    function logLine(levelName, message) {
        var line = PDC.TextUtils.formatLogTimestamp(new Date()) + " | " + levelName + " | " + message;
        sessionLines.push(line);
        return line;
    }

    function logDebug(message) {
        if (!PDC.CONFIG.debug) return "";
        if (currentLevel() > LEVELS.DEBUG) return "";
        return logLine("DEBUG", message);
    }

    function logInfo(message) {
        if (currentLevel() > LEVELS.INFO) return "";
        return logLine("INFO", message);
    }

    function logWarning(message) {
        if (currentLevel() > LEVELS.WARNING) return "";
        return logLine("WARNING", message);
    }

    function logError(message) {
        return logLine("ERROR", message);
    }

    function getSessionLines() {
        return sessionLines;
    }

    function getSessionLogFile() {
        var logsFolder = PDC.Paths.getLogsFolder();
        PDC.FileService.ensureFolder(logsFolder);
        return new File(logsFolder.fsName + "/" + PDC.CONFIG.log.sessionFileName);
    }

    function flushSessionLog() {
        try {
            var f = getSessionLogFile();
            var block = sessionLines.join("\r\n") + "\r\n";
            return PDC.FileService.appendTextFile(f, block, "UTF-8");
        } catch (e) {
            return false;
        }
    }

    return {
        LEVELS: LEVELS,
        startSession: startSession,
        logDebug: logDebug,
        logInfo: logInfo,
        logWarning: logWarning,
        logError: logError,
        getSessionLines: getSessionLines,
        getSessionLogFile: getSessionLogFile,
        flushSessionLog: flushSessionLog,
        writeJobLog: writeLogFile
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/services/ErrorService.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/services/ErrorService.jsx

    Purpose:
      Central error handling, plan phases 8 and 10.

      One entry point:

        PDC.ErrorService.handleError(err, context, options)

      It always:
        * writes the error into the session log (logs/project.log);
        * creates an error report folder:

             logs/errors/2026-09-23_153510/
                 error.txt     - project, version, message, file, line, stack
                 context.txt   - active document, input file, output file,
                                 config snapshot, current operation

      and, unless options.silent is true, shows one dialog:

             ERROR

             Operation: ...
             Message:   ...
             File:      ...
             Line:      ...

      A screenshot cannot be captured from ExtendScript. The report folder is
      deliberately structured so a future Python helper (win32com / Pillow) can
      drop screenshot.png next to those two files without any change here.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("ErrorService", (function () {

    function textOf(value) {
        if (value === null || value === undefined) return "";
        if (value instanceof File || value instanceof Folder) {
            return PDC.TextUtils.displayPath(value);
        }
        return String(value);
    }

    function errorMessage(error) {
        if (!error) return "Nezināma kļūda (tukšs error objekts).";
        if (error.message) return String(error.message);
        return String(error);
    }

    function errorFile(error) {
        try { if (error && error.fileName) return String(error.fileName); } catch (e) {}
        return "";
    }

    function errorLine(error) {
        try { if (error && error.line !== undefined && error.line !== null) return String(error.line); } catch (e) {}
        return "";
    }

    function errorStack(error) {
        try { if (error && error.stack) return String(error.stack); } catch (e) {}
        return "(ExtendScript nenodrošina stack trace)";
    }

    function activeDocumentName() {
        try {
            if (app.documents.length > 0) return String(app.activeDocument.name);
        } catch (e) {}
        return "(nav atvērta dokumenta)";
    }

    function configSnapshot() {
        var c = PDC.CONFIG;
        var lines = [];
        lines.push("    version: " + c.version);
        lines.push("    debug: " + c.debug);
        lines.push("    dryRun: " + c.dryRun);
        lines.push("    overwriteExisting: " + c.overwriteExisting);
        lines.push("    artworkLayerName: " + c.artworkLayerName);
        lines.push("    cleanup.releaseSafeVectorMasks: " + c.cleanup.releaseSafeVectorMasks);
        lines.push("    cleanup.deleteCropMarks: " + c.cleanup.deleteCropMarks);
        lines.push("    cleanup.ungroupPasses: " + c.cleanup.ungroupPasses);
        return lines.join("\r\n");
    }

    function buildErrorText(error, context) {
        var ctx = context ? context : {};
        var lines = [];
        lines.push("PROJECT:  " + PDC.CONFIG.projectName);
        lines.push("VERSION:  " + PDC.CONFIG.version);
        lines.push("WHEN:     " + PDC.TextUtils.formatLogTimestamp(new Date()));
        lines.push("");
        lines.push("OPERATION:");
        lines.push("  " + textOf(ctx.operation));
        lines.push("");
        lines.push("ERROR:");
        lines.push("  " + (error && error.name ? String(error.name) : "Error"));
        lines.push("");
        lines.push("MESSAGE:");
        lines.push("  " + errorMessage(error));
        lines.push("");
        lines.push("FILE:");
        lines.push("  " + (errorFile(error) || "(nezināms)"));
        lines.push("");
        lines.push("LINE:");
        lines.push("  " + (errorLine(error) || "(nezināma)"));
        lines.push("");
        lines.push("STACK:");
        lines.push("  " + errorStack(error));
        return lines.join("\r\n") + "\r\n";
    }

    function buildContextText(error, context) {
        var ctx = context ? context : {};
        var lines = [];
        lines.push("ACTIVE DOCUMENT:   " + activeDocumentName());
        lines.push("INPUT FILE:        " + (textOf(ctx.inputFile) || "(nav)"));
        lines.push("OUTPUT FILE:       " + (textOf(ctx.outputFile) || "(nav)"));
        lines.push("CURRENT OPERATION: " + (textOf(ctx.operation) || "(nav)"));
        if (ctx.templateFile) lines.push("TEMPLATE FILE:     " + textOf(ctx.templateFile));
        if (ctx.pdfPage) lines.push("PDF PAGE:          " + textOf(ctx.pdfPage));
        if (ctx.jobFolder) lines.push("JOB FOLDER:        " + textOf(ctx.jobFolder));
        lines.push("");
        lines.push("CONFIG:");
        lines.push(configSnapshot());
        if (ctx.extra) {
            lines.push("");
            lines.push("EXTRA:");
            lines.push(textOf(ctx.extra));
        }
        return lines.join("\r\n") + "\r\n";
    }

    function writeErrorReport(error, context) {
        var report = { folder: null, errorFile: null, contextFile: null, ok: false };
        try {
            var stamp = PDC.TextUtils.formatFolderTimestamp(new Date());
            var root = PDC.Paths.getErrorsFolder();
            PDC.FileService.ensureFolder(root);

            var folder = new Folder(root.fsName + "/" + stamp);
            PDC.FileService.ensureFolder(folder);

            report.folder = folder;
            report.errorFile = new File(folder.fsName + "/error.txt");
            report.contextFile = new File(folder.fsName + "/context.txt");

            report.ok =
                PDC.FileService.writeTextFile(report.errorFile, buildErrorText(error, context), "UTF-8") &&
                PDC.FileService.writeTextFile(report.contextFile, buildContextText(error, context), "UTF-8");
        } catch (e) {
            report.ok = false;
        }
        return report;
    }

    function buildDialogText(error, context, report) {
        var ctx = context ? context : {};
        var lines = [];
        lines.push("ERROR");
        lines.push("");
        lines.push("Operation: " + (textOf(ctx.operation) || "(nav)"));
        lines.push("Message:   " + errorMessage(error));
        lines.push("File:      " + (errorFile(error) || "-"));
        lines.push("Line:      " + (errorLine(error) || "-"));
        if (report && report.folder) {
            lines.push("");
            lines.push("Report:    " + PDC.TextUtils.displayPath(report.folder));
        }
        return lines.join("\n");
    }

    function handleError(error, context, options) {
        var opts = options ? options : {};
        var ctx = context ? context : {};
        var message = "[KĻŪDA] " + (textOf(ctx.operation) || "operācija") + ": " + errorMessage(error);

        try { PDC.LogService.logError(message); } catch (eLog) {}

        var report = writeErrorReport(error, ctx);

        if (opts.silent !== true) {
            try { alert(buildDialogText(error, ctx, report)); } catch (eAlert) {}
        }

        return { message: message, report: report };
    }

    return {
        handleError: handleError,
        writeErrorReport: writeErrorReport,
        buildErrorText: buildErrorText,
        buildContextText: buildContextText,
        buildDialogText: buildDialogText,
        errorMessage: errorMessage
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/core/PdfCleanup.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/core/PdfCleanup.jsx

    Purpose:
      The PDF Deep Cleanup v6 engine (APPEARANCE SAFE). This is the core value
      of the project: it removes the technical PDF junk Illustrator brings in
      with a PDF page, without touching the appearance of real artwork.

      Order of operations (identical to the reference script):
        1. unlock all layers and items
        2. ungroup only groups that are provably safe to ungroup
        3. release only vector-only clipping masks
        4. safe ungroup again (mask release can expose new safe groups)
        5. delete crop mark perimeters and short crop marks
        6. restore the saved view state (artboard, zoom, centre point)

      Anything that can carry appearance (raster, placed, mesh, plugin, symbol
      artwork, transparency, opacity, blending, knockout, nested clips) is
      preserved on purpose and only counted in stats.

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 378-771 - the body of the
       original nested runPdfDeepCleanup()). The nested functions were lifted to
       module scope; "stats" became a module level variable with resetStats(),
       which is the same pattern the working v6 GUI script already used.

      Flag mapping (original local scope -> CONFIG):
        RELEASE_SAFE_VECTOR_MASKS        -> CONFIG.cleanup.releaseSafeVectorMasks
        DELETE_CROP_MARKS                -> CONFIG.cleanup.deleteCropMarks
        ungroupSafeGroups(doc, 40)       -> CONFIG.cleanup.ungroupPasses
        PRESERVE_IMAGE_STRUCTURES        -> CONFIG.cleanup.preserveImageStructures
        PRESERVE_TRANSPARENCY_STRUCTURES -> CONFIG.cleanup.preserveTransparencyStructures
        (the last two are intent flags: the reference code enforced the same
         behaviour through the "safe only" tests, not through the flags)

      No alert() and no confirm() is used - the engine is batch safe and returns
      its result through the stats object.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("PdfCleanup", (function () {

    var stats = null;

    function resetStats() {
        stats = {
            safeGroupsUngrouped: 0,
            riskyGroupsPreserved: 0,
            vectorMasksReleased: 0,
            riskyMasksPreserved: 0,
            maskPathsDeleted: 0,
            cropPerimetersDeleted: 0,
            shortCropMarksDeleted: 0
        };
    }

    resetStats();
    // --- view state ---
    function saveViewState(d) {
        var s = { artboardIndex: 0, zoom: null, centerPoint: null };
        try { s.artboardIndex = d.artboards.getActiveArtboardIndex(); } catch(e) {}
        try {
            if (d.views.length > 0) {
                s.zoom = d.views[0].zoom;
                var cp = d.views[0].centerPoint;
                s.centerPoint = [cp[0], cp[1]];
            }
        } catch(e2) {}
        return s;
    }
    function restoreViewState(d, s) {
        if (!s) return;
        try { d.artboards.setActiveArtboardIndex(s.artboardIndex); } catch(e) {}
        try {
            if (d.views.length > 0) {
                if (s.centerPoint) d.views[0].centerPoint = s.centerPoint;
                if (s.zoom !== null) d.views[0].zoom = s.zoom;
            }
        } catch(e2) {}
    }

    // --- unlock ---
    function unlockLayerRecursive(layer) {
        try { layer.locked = false; } catch(e) {}
        for (var i = 0; i < layer.layers.length; i++) unlockLayerRecursive(layer.layers[i]);
    }
    function unlockAll(d) {
        for (var i = 0; i < d.layers.length; i++) unlockLayerRecursive(d.layers[i]);
        for (var j = d.pageItems.length - 1; j >= 0; j--) {
            try { d.pageItems[j].locked = false; } catch(e) {}
        }
    }

    // --- appearance tests ---
    function hasNonDefaultAppearance(item) {
        try { if (item.opacity !== undefined && Math.abs(item.opacity - 100) > 0.001) return true; } catch(e) {}
        try { if (item.blendingMode !== undefined && String(item.blendingMode) !== String(BlendModes.NORMAL)) return true; } catch(e2) {}
        try { if (item.isIsolated === true) return true; } catch(e3) {}
        try {
            var ak = item.artworkKnockout;
            if (ak !== undefined) {
                var s = String(ak);
                if (s !== "KnockoutState.DISABLED" && s !== "KnockoutState.INHERITED" && s !== "0") return true;
            }
        } catch(e4) {}
        return false;
    }
    function containsNonDefaultAppearanceDescendant(group) {
        try {
            for (var i = 0; i < group.pageItems.length; i++) {
                var it = group.pageItems[i];
                if (hasNonDefaultAppearance(it)) return true;
                if (it.typename === "GroupItem" && containsNonDefaultAppearanceDescendant(it)) return true;
            }
        } catch(e) {}
        return false;
    }
    function containsImageLikeArtwork(item) {
        try {
            var t = item.typename;
            if (t === "RasterItem" || t === "PlacedItem" || t === "MeshItem" || t === "PluginItem" || t === "SymbolItem") return true;
            if (t === "GroupItem") {
                for (var i = 0; i < item.pageItems.length; i++) {
                    if (containsImageLikeArtwork(item.pageItems[i])) return true;
                }
            }
        } catch(e) {}
        return false;
    }
    function containsClippedGroupDescendant(group) {
        try {
            for (var i = 0; i < group.pageItems.length; i++) {
                var it = group.pageItems[i];
                if (it.typename === "GroupItem") {
                    try { if (it.clipped) return true; } catch(e) {}
                    if (containsClippedGroupDescendant(it)) return true;
                }
            }
        } catch(e2) {}
        return false;
    }
    function containsNestedClippedGroup(group) {
        try {
            for (var i = 0; i < group.pageItems.length; i++) {
                var it = group.pageItems[i];
                if (it.typename === "GroupItem") {
                    try { if (it !== group && it.clipped) return true; } catch(e) {}
                    if (containsNestedClippedGroup(it)) return true;
                }
            }
        } catch(e2) {}
        return false;
    }

    // --- generic helpers ---
    function isValidPageItem(item) {
        try { return !!item.typename; } catch(e) { return false; }
    }
    function getItemDepth(item) {
        var d = 0;
        var p = null;
        try { p = item.parent; } catch(e) { return d; }
        while (p) {
            try {
                if (p.typename === "GroupItem" || p.typename === "CompoundPathItem") { d++; p = p.parent; }
                else break;
            } catch(e2) { break; }
        }
        return d;
    }
    function pushUnique(arr, obj) {
        for (var i = 0; i < arr.length; i++) { if (arr[i] === obj) return; }
        arr.push(obj);
    }
    function getActiveArtboardBounds(d) {
        try {
            var idx = d.artboards.getActiveArtboardIndex();
            return d.artboards[idx].artboardRect;
        } catch(e) { return null; }
    }
    function safeBounds(it) {
        try { return it.geometricBounds; } catch(e) {
            try { return it.visibleBounds; } catch(e2) { return null; }
        }
    }
    function containsAnyFill(it) {
        try {
            if (it.typename === "PathItem") return !!it.filled;
            if (it.typename === "CompoundPathItem") {
                for (var i = 0; i < it.pathItems.length; i++) if (it.pathItems[i].filled) return true;
                return false;
            }
            if (it.typename === "GroupItem") {
                for (var j = 0; j < it.pageItems.length; j++) if (containsAnyFill(it.pageItems[j])) return true;
                return false;
            }
        } catch(e) {}
        return false;
    }
    function isTechnicalLinework(it) {
        try {
            if (it.typename === "PathItem") return !it.filled;
            if (it.typename === "CompoundPathItem") {
                if (it.pathItems.length === 0) return false;
                for (var i = 0; i < it.pathItems.length; i++) if (it.pathItems[i].filled) return false;
                return true;
            }
            if (it.typename === "GroupItem") {
                if (it.clipped) return false;
                if (it.pageItems.length === 0) return false;
                if (containsImageLikeArtwork(it)) return false;
                for (var j = 0; j < it.pageItems.length; j++) {
                    var c = it.pageItems[j];
                    if (c.typename === "PathItem" && c.filled) return false;
                    if (c.typename === "CompoundPathItem") {
                        for (var k = 0; k < c.pathItems.length; k++) if (c.pathItems[k].filled) return false;
                    }
                }
                return true;
            }
        } catch(e) {}
        return false;
    }
    function hasRiskyAncestor(item) {
        var p = null;
        try { p = item.parent; } catch(e) { return false; }
        while (p) {
            try {
                if (p.typename === "GroupItem") {
                    if (p.clipped) return true;
                    if (containsImageLikeArtwork(p)) return true;
                    if (hasNonDefaultAppearance(p)) return true;
                }
                if (p.typename === "Document" || p.typename === "Layer") break;
                p = p.parent;
            } catch(e2) { break; }
        }
        return false;
    }

    // --- safe ungroup ---
    function isSafeToUngroup(g) {
        try {
            if (g.clipped) return false;
            if (PRESERVE_TRANSPARENCY_STRUCTURES && hasNonDefaultAppearance(g)) return false;
            if (PRESERVE_IMAGE_STRUCTURES && containsImageLikeArtwork(g)) return false;
            if (containsClippedGroupDescendant(g)) return false;
            if (PRESERVE_TRANSPARENCY_STRUCTURES && containsNonDefaultAppearanceDescendant(g)) return false;
            return true;
        } catch(e) { return false; }
    }
    function collectGroupsDeepestFirst(d) {
        var arr = [];
        try {
            for (var i = 0; i < d.groupItems.length; i++) {
                arr.push({ item: d.groupItems[i], depth: getItemDepth(d.groupItems[i]) });
            }
        } catch(e) {}
        arr.sort(function(a, b) { return b.depth - a.depth; });
        var result = [];
        for (var j = 0; j < arr.length; j++) result.push(arr[j].item);
        return result;
    }
    function ungroupSafeGroups(d, maxPasses) {
        for (var pass = 0; pass < maxPasses; pass++) {
            var groups = collectGroupsDeepestFirst(d);
            if (groups.length === 0) break;
            var changed = false;
            for (var i = 0; i < groups.length; i++) {
                var g = groups[i];
                try {
                    if (!isValidPageItem(g)) continue;
                    if (!isSafeToUngroup(g)) { stats.riskyGroupsPreserved++; continue; }
                    app.executeMenuCommand("deselectall");
                    g.selected = true;
                    app.executeMenuCommand("ungroup");
                    stats.safeGroupsUngrouped++;
                    changed = true;
                } catch(e) {}
            }
            if (!changed) break;
        }
        try { app.executeMenuCommand("deselectall"); } catch(e) {}
    }

    // --- safe clipping mask release ---
    function isSafeVectorClippingGroup(g) {
        try {
            if (containsImageLikeArtwork(g)) return false;
            if (containsNestedClippedGroup(g)) return false;
            if (PRESERVE_TRANSPARENCY_STRUCTURES) {
                if (hasNonDefaultAppearance(g)) return false;
                if (containsNonDefaultAppearanceDescendant(g)) return false;
            }
            return true;
        } catch(e) { return false; }
    }
    function collectClippedGroupsDeepestFirst(d) {
        var arr = [];
        try {
            for (var i = 0; i < d.groupItems.length; i++) {
                var g = d.groupItems[i];
                try { if (g.clipped) arr.push({ item: g, depth: getItemDepth(g) }); } catch(e) {}
            }
        } catch(e2) {}
        arr.sort(function(a, b) { return b.depth - a.depth; });
        var result = [];
        for (var j = 0; j < arr.length; j++) result.push(arr[j].item);
        return result;
    }
    function collectExactMaskObjects(group) {
        var result = [];
        try {
            for (var i = 0; i < group.pageItems.length; i++) {
                var it = group.pageItems[i];
                if (it.typename === "PathItem") {
                    try { if (it.clipping) pushUnique(result, it); } catch(e) {}
                } else if (it.typename === "CompoundPathItem") {
                    var isMask = false;
                    try {
                        for (var p = 0; p < it.pathItems.length; p++) {
                            if (it.pathItems[p].clipping) { isMask = true; break; }
                        }
                    } catch(e2) {}
                    if (isMask) pushUnique(result, it);
                }
            }
        } catch(e3) {}
        return result;
    }
    function releaseSafeVectorClippingMasks(d) {
        var guard = 0;
        while (guard < 30) {
            guard++;
            var groups = collectClippedGroupsDeepestFirst(d);
            if (groups.length === 0) break;
            var changed = false;
            for (var i = 0; i < groups.length; i++) {
                var g = groups[i];
                try {
                    if (!isValidPageItem(g)) continue;
                    if (!g.clipped) continue;
                    if (!isSafeVectorClippingGroup(g)) { stats.riskyMasksPreserved++; continue; }
                    var maskObjects = collectExactMaskObjects(g);
                    app.executeMenuCommand("deselectall");
                    g.selected = true;
                    app.executeMenuCommand("releaseMask");
                    stats.vectorMasksReleased++;
                    changed = true;
                    for (var m = maskObjects.length - 1; m >= 0; m--) {
                        try {
                            if (isValidPageItem(maskObjects[m])) {
                                maskObjects[m].remove();
                                stats.maskPathsDeleted++;
                            }
                        } catch(e2) {}
                    }
                } catch(e) {}
            }
            if (!changed) break;
        }
        try { app.executeMenuCommand("deselectall"); } catch(e) {}
    }

    // --- crop marks ---
    function deleteCropPerimeterObjects(d) {
        var ab = getActiveArtboardBounds(d);
        if (!ab) return;
        var left = ab[0], top = ab[1], right = ab[2], bottom = ab[3];
        var aw = Math.abs(right - left), ah = Math.abs(top - bottom);
        var edgeTol = Math.max(6, Math.min(aw, ah) * 0.02);
        var candidates = [];
        for (var i = 0; i < d.pageItems.length; i++) {
            try {
                var t = d.pageItems[i].typename;
                if (t === "PathItem" || t === "CompoundPathItem" || t === "GroupItem") candidates.push(d.pageItems[i]);
            } catch(e) {}
        }
        for (var j = candidates.length - 1; j >= 0; j--) {
            var it = candidates[j];
            try {
                if (!isValidPageItem(it)) continue;
                if (it.typename === "GroupItem") {
                    if (it.clipped) continue;
                    if (containsImageLikeArtwork(it)) continue;
                    if (containsClippedGroupDescendant(it)) continue;
                    if (hasNonDefaultAppearance(it)) continue;
                    if (containsNonDefaultAppearanceDescendant(it)) continue;
                }
                if (containsAnyFill(it)) continue;
                if (!isTechnicalLinework(it)) continue;
                var b = safeBounds(it);
                if (!b) continue;
                var iw = Math.abs(b[2] - b[0]), ih = Math.abs(b[1] - b[3]);
                var nearLeft   = Math.abs(b[0] - left)   <= edgeTol;
                var nearRight  = Math.abs(b[2] - right)  <= edgeTol;
                var nearTop    = Math.abs(b[1] - top)    <= edgeTol;
                var nearBottom = Math.abs(b[3] - bottom) <= edgeTol;
                var spansWidth = iw >= aw * 0.90, spansHeight = ih >= ah * 0.90;
                var edgeHits = (nearLeft?1:0)+(nearRight?1:0)+(nearTop?1:0)+(nearBottom?1:0);
                var strongPerimeter =
                    (spansWidth && (nearTop || nearBottom)) ||
                    (spansHeight && (nearLeft || nearRight)) ||
                    (iw >= aw * 0.90 && ih >= ah * 0.90 && edgeHits >= 2);
                if (!strongPerimeter) continue;
                it.remove();
                stats.cropPerimetersDeleted++;
            } catch(e) {}
        }
    }
    function deleteShortCropMarks(d) {
        var ab = getActiveArtboardBounds(d);
        if (!ab) return;
        var left = ab[0], top = ab[1], right = ab[2], bottom = ab[3];
        var aw = Math.abs(right - left), ah = Math.abs(top - bottom);
        var edgeTol = Math.max(10, Math.min(aw, ah) * 0.03);
        var maxLen  = Math.max(24, Math.min(aw, ah) * 0.08);
        var paths = [];
        for (var i = 0; i < d.pathItems.length; i++) paths.push(d.pathItems[i]);
        for (var j = paths.length - 1; j >= 0; j--) {
            var p = paths[j];
            try {
                if (!isValidPageItem(p)) continue;
                try { if (p.clipping) continue; } catch(e0) {}
                if (hasRiskyAncestor(p)) continue;
                if (p.filled) continue;
                if (!p.stroked) continue;
                if (p.closed) continue;
                if (p.pathPoints.length > 2) continue;
                var b = safeBounds(p);
                if (!b) continue;
                var w = Math.abs(b[2] - b[0]), h = Math.abs(b[1] - b[3]);
                var horizontal = (w > 0 && h <= 1.25 && w <= maxLen);
                var vertical   = (h > 0 && w <= 1.25 && h <= maxLen);
                if (!horizontal && !vertical) continue;
                var cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
                var nearEdge =
                    Math.abs(cx - left)   <= edgeTol ||
                    Math.abs(cx - right)  <= edgeTol ||
                    Math.abs(cy - top)    <= edgeTol ||
                    Math.abs(cy - bottom) <= edgeTol;
                if (!nearEdge) continue;
                var insideX = (cx > left + edgeTol && cx < right - edgeTol);
                var insideY = (cy < top - edgeTol && cy > bottom + edgeTol);
                if (insideX && insideY) continue;
                p.remove();
                stats.shortCropMarksDeleted++;
            } catch(e) {}
        }
    }
    /* ---- run ----
       Original order of operations from the reference script (lines 773-785). */

    function run(doc) {
        if (!doc) throw new Error("PdfCleanup.run: nav dokumenta.");

        var flags = PDC.CONFIG.cleanup;
        var RELEASE_SAFE_VECTOR_MASKS = flags.releaseSafeVectorMasks;
        var DELETE_CROP_MARKS = flags.deleteCropMarks;
        var passes = flags.ungroupPasses;

        resetStats();

        var savedView = saveViewState(doc);

        unlockAll(doc);

        ungroupSafeGroups(doc, passes);

        if (RELEASE_SAFE_VECTOR_MASKS) {
            releaseSafeVectorClippingMasks(doc);
        }

        ungroupSafeGroups(doc, passes);

        if (DELETE_CROP_MARKS) {
            deleteCropPerimeterObjects(doc);
            deleteShortCropMarks(doc);
        }

        try { app.executeMenuCommand("deselectall"); } catch (e) {}
        restoreViewState(doc, savedView);

        return stats;
    }

    function summaryLine(s) {
        if (!s) s = stats;
        return "ungrp=" + s.safeGroupsUngrouped +
               " riskyGrp=" + s.riskyGroupsPreserved +
               " masks=" + s.vectorMasksReleased +
               " riskyMask=" + s.riskyMasksPreserved +
               " maskPaths=" + s.maskPathsDeleted +
               " crop=" + (s.cropPerimetersDeleted + s.shortCropMarksDeleted);
    }

    return {
        run: run,
        resetStats: resetStats,
        getStats: function () { return stats; },
        summaryLine: summaryLine
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/core/PdfPageCount.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/core/PdfPageCount.jsx

    Purpose:
      How many pages does a PDF have?  Two independent strategies:
        1. Illustrator probe - open the PDF with pageRangeToOpen = "all"
           and count artboards (most accurate, slower, needs Illustrator).
        2. Raw PDF structure scan - read the file and look for the PDF
           /Type /Pages ... /Count N dictionary (fast, no document needed,
           works on large files by streaming in 2 MB chunks).

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 222-343).
      Only the safeClose() calls were pointed at PDC.FileService.

    ExtendScript: ES3 safe. Uses File.encoding = "BINARY" for raw PDF reading.
*/

PDC.registerModule("PdfPageCount", (function () {
    function detectPdfPageCountFromStructure(pdfFile) {
        if (!pdfFile || !pdfFile.exists) return 0;
        var f = pdfFile;
        var oldEncoding = null;
        var bestPagesCount = 0;
        try {
            oldEncoding = f.encoding;
            f.encoding = "BINARY";
            if (!f.open("r")) return 0;
            var fileLen = 0; try { fileLen = f.length; } catch(eLen) {}
            if (fileLen > 0 && fileLen <= 80 * 1024 * 1024) {
                var all = f.read();
                var reA = /\/Type\s*\/Pages\b[\s\S]{0,2500}?\/Count\s+(\d+)/g;
                var reB = /\/Count\s+(\d+)[\s\S]{0,2500}?\/Type\s*\/Pages\b/g;
                var m;
                while ((m = reA.exec(all)) !== null) {
                    var n1 = parseInt(m[1], 10);
                    if (!isNaN(n1) && n1 > bestPagesCount) bestPagesCount = n1;
                }
                while ((m = reB.exec(all)) !== null) {
                    var n2 = parseInt(m[1], 10);
                    if (!isNaN(n2) && n2 > bestPagesCount) bestPagesCount = n2;
                }
            } else {
                var chunkSize = 2 * 1024 * 1024;
                var overlap = 4096;
                var carry = "";
                var reA2 = /\/Type\s*\/Pages\b[\s\S]{0,2500}?\/Count\s+(\d+)/g;
                var reB2 = /\/Count\s+(\d+)[\s\S]{0,2500}?\/Type\s*\/Pages\b/g;
                while (!f.eof) {
                    var part = f.read(chunkSize);
                    if (!part) break;
                    var merged = carry + part;
                    var m2;
                    while ((m2 = reA2.exec(merged)) !== null) {
                        var n3 = parseInt(m2[1], 10);
                        if (!isNaN(n3) && n3 > bestPagesCount) bestPagesCount = n3;
                    }
                    while ((m2 = reB2.exec(merged)) !== null) {
                        var n4 = parseInt(m2[1], 10);
                        if (!isNaN(n4) && n4 > bestPagesCount) bestPagesCount = n4;
                    }
                    carry = merged.substring(Math.max(0, merged.length - overlap));
                }
            }
            f.close();
            if (oldEncoding !== null) f.encoding = oldEncoding;
        } catch (e) {
            try { if (f.opened) f.close(); } catch(e2) {}
            try { if (oldEncoding !== null) f.encoding = oldEncoding; } catch(e3) {}
            return 0;
        }
        return bestPagesCount > 0 ? bestPagesCount : 0;
    }
    function detectPdfPageCountWithIllustrator(pdfFile) {
        var probeDoc = null;
        var opts = app.preferences.PDFFileOptions;
        var oldInteraction = app.userInteractionLevel;
        var hasRange = false;
        var oldRange = null;
        var hasLinks = false;
        var oldLinks = null;
        var oldPage = 1;

        try { oldPage = opts.pageToOpen; } catch(e0) {}
        try {
            oldRange = opts.pageRangeToOpen;
            opts.pageRangeToOpen = "all";
            hasRange = true;
        } catch(e1) {}

        if (!hasRange) return 0;

        try {
            oldLinks = opts.placeAsLinks;
            opts.placeAsLinks = true;
            hasLinks = true;
        } catch(e2) {}

        try {
            app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
            try { opts.pageToOpen = 1; } catch(e3) {}
            probeDoc = app.open(pdfFile);
            var count = 0;
            try { count = probeDoc.artboards.length; } catch(e4) {}
            PDC.FileService.safeClose(probeDoc, SaveOptions.DONOTSAVECHANGES);
            probeDoc = null;

            try { opts.pageToOpen = oldPage; } catch(e5) {}
            try { opts.pageRangeToOpen = oldRange; } catch(e6) {
                try { opts.pageRangeToOpen = "1"; } catch(e7) {}
            }
            if (hasLinks) try { opts.placeAsLinks = oldLinks; } catch(e8) {}
            app.userInteractionLevel = oldInteraction;
            return count;
        } catch (err) {
            PDC.FileService.safeClose(probeDoc, SaveOptions.DONOTSAVECHANGES);
            probeDoc = null;
            try { opts.pageToOpen = oldPage; } catch(e9) {}
            try { opts.pageRangeToOpen = oldRange; } catch(e10) {
                try { opts.pageRangeToOpen = "1"; } catch(e11) {}
            }
            if (hasLinks) try { opts.placeAsLinks = oldLinks; } catch(e12) {}
            try { app.userInteractionLevel = oldInteraction; } catch(e13) {}
            return 0;
        }
    }
    function detectPdfPageCount(pdfFile) {
        var aiCount = detectPdfPageCountWithIllustrator(pdfFile);
        if (aiCount > 1) return { count: aiCount, method: "Illustrator ALL" };
        var parsed = detectPdfPageCountFromStructure(pdfFile);
        if (parsed > 0) return { count: parsed, method: "PDF /Pages" };
        if (aiCount === 1) return { count: 1, method: "Illustrator" };
        return { count: 1, method: "Fallback 1" };
    }
    function openPdfPage(pdfFile, pageNo) {
        var opts = app.preferences.PDFFileOptions;
        try { opts.pageToOpen = pageNo; } catch(e0) {}
        try { opts.pageRangeToOpen = String(pageNo); } catch(e1) {}
        try { opts.placeAsLinks = false; } catch(e2) {}
        return app.open(pdfFile);
    }    return {
        detectPdfPageCountFromStructure: detectPdfPageCountFromStructure,
        detectPdfPageCountWithIllustrator: detectPdfPageCountWithIllustrator,
        detectPdfPageCount: detectPdfPageCount,
        openPdfPage: openPdfPage
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/core/TemplateManager.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/core/TemplateManager.jsx

    Purpose:
      Everything about the Illustrator template and the ARTWORK layer:
        * templateScore()  - ranks *.ai / *.ait candidates in TEMPLATE folder
        * detectTemplate() - picks the best template file
        * findOrCreateArtworkLayer() / clearArtworkLayer()
        * duplicateSourceLayersIntoArtwork() - copies the cleaned PDF artwork
          from every source layer into the template ARTWORK layer
          (iterates from bottom to top with PLACEATBEGINNING so stacking order
           is preserved; coordinates are never changed).

      The MASTER template file itself is never modified - the batch always
      copies it to AI_OUT first (see core/OutputManager.jsx).

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 79-182).
      Only ARTWORK_LAYER_NAME now comes from CONFIG.artworkLayerName.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("TemplateManager", (function () {
    function templateScore(f) {
        var n = f.name.toLowerCase();
        var score = 0;
        if (/\.ait$/i.test(n)) score += 100;
        if (n === "master_ai_template.ai") score += 1000;
        if (n === "master_template.ai") score += 900;
        if (n.indexOf("master_ai_template") >= 0) score += 500;
        if (n.indexOf("master_template") >= 0) score += 450;
        if (n.indexOf("template") >= 0) score += 200;
        if (n.indexOf("master") >= 0) score += 100;
        return score;
    }
    function detectTemplate(templateFolder) {
        if (!templateFolder || !templateFolder.exists) return null;
        var files = templateFolder.getFiles(function(f) {
            return (f instanceof File) && /\.(ai|ait)$/i.test(f.name);
        });
        if (!files || files.length === 0) return null;
        files.sort(function(a, b) {
            var sa = templateScore(a);
            var sb = templateScore(b);
            if (sa !== sb) return sb - sa;
            var an = a.name.toLowerCase();
            var bn = b.name.toLowerCase();
            return an < bn ? -1 : (an > bn ? 1 : 0);
        });
        return files[0];
    }
    function findOrCreateArtworkLayer(doc) {
        var lyr = null;
        try { lyr = doc.layers.getByName(PDC.CONFIG.artworkLayerName); } catch(e) {}
        if (!lyr) {
            lyr = doc.layers.add();
            lyr.name = PDC.CONFIG.artworkLayerName;
        }
        try { lyr.visible = true; } catch(e2) {}
        try { lyr.locked = false; } catch(e3) {}
        return lyr;
    }
    function clearArtworkLayer(layer) {
        try {
            for (var i = layer.pageItems.length - 1; i >= 0; i--) {
                var it = layer.pageItems[i];
                try { if (it.parent === layer) it.remove(); } catch(e) {}
            }
        } catch(e2) {}
        try {
            for (var j = layer.layers.length - 1; j >= 0; j--) {
                try { layer.layers[j].remove(); } catch(e3) {}
            }
        } catch(e4) {}
    }
    function duplicateSourceLayersIntoArtwork(sourceDoc, artworkLayer) {
        var count = 0;
        sourceDoc.activate();
        for (var li = sourceDoc.layers.length - 1; li >= 0; li--) {
            var srcLayer = sourceDoc.layers[li];
            try { srcLayer.locked = false; } catch(e0) {}
            try { srcLayer.visible = true; } catch(e1) {}
            var directItems = [];
            try {
                for (var pi = 0; pi < srcLayer.pageItems.length; pi++) {
                    var item = srcLayer.pageItems[pi];
                    if (item.parent === srcLayer) directItems.push(item);
                }
            } catch(e2) {}
            for (var i = directItems.length - 1; i >= 0; i--) {
                var srcItem = directItems[i];
                try {
                    srcItem.duplicate(artworkLayer, ElementPlacement.PLACEATBEGINNING);
                    count++;
                } catch(e4) {}
            }
            count += duplicateNestedLayerItemsIntoArtwork(srcLayer, artworkLayer);
        }
        return count;
    }
    function duplicateNestedLayerItemsIntoArtwork(parentLayer, artworkLayer) {
        var count = 0;
        var childLayers = [];
        try {
            for (var l = 0; l < parentLayer.layers.length; l++) childLayers.push(parentLayer.layers[l]);
        } catch(e0) { return 0; }
        for (var li = childLayers.length - 1; li >= 0; li--) {
            var srcLayer = childLayers[li];
            try { srcLayer.locked = false; } catch(e1) {}
            try { srcLayer.visible = true; } catch(e2) {}
            var directItems = [];
            try {
                for (var pi = 0; pi < srcLayer.pageItems.length; pi++) {
                    var item = srcLayer.pageItems[pi];
                    if (item.parent === srcLayer) directItems.push(item);
                }
            } catch(e3) {}
            for (var i = directItems.length - 1; i >= 0; i--) {
                try {
                    directItems[i].duplicate(artworkLayer, ElementPlacement.PLACEATBEGINNING);
                    count++;
                } catch(e5) {}
            }
            count += duplicateNestedLayerItemsIntoArtwork(srcLayer, artworkLayer);
        }
        return count;
    }    return {
        templateScore: templateScore,
        detectTemplate: detectTemplate,
        findOrCreateArtworkLayer: findOrCreateArtworkLayer,
        clearArtworkLayer: clearArtworkLayer,
        duplicateSourceLayersIntoArtwork: duplicateSourceLayersIntoArtwork,
        duplicateNestedLayerItemsIntoArtwork: duplicateNestedLayerItemsIntoArtwork
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/core/OutputManager.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/core/OutputManager.jsx

    Purpose:
      Everything that writes into AI_OUT:
        * makePageOutputName() - <pdf>_p03.ai style output names (single page
          PDFs keep the plain <pdf>.ai name, exactly like the reference script);
        * pageJobKey()        - stable per page key used for check state/cache;
        * copyTemplateToOutput() - copies the MASTER template to the output file.

      Safety rules (fail safe):
        * the MASTER template file is only ever read, never written;
        * an existing output is never overwritten unless the caller passes
          overwrite = true (GUI checkbox, CONFIG.overwriteExisting = false);
        * CONFIG.dryRun = true logs the planned copy and touches nothing.

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 191-198 and 351-358).
      copyTemplateToOutput() got the dry run guard; overwrite removal now reuses
      PDC.FileService.removeIfExists (same remove() call as before).

    ExtendScript: ES3 safe.
*/

PDC.registerModule("OutputManager", (function () {
    function copyTemplateToOutput(templateFile, outputFile, overwrite) {
        if (outputFile.exists) {
            if (!overwrite) return false;
            if (!PDC.FileService.removeIfExists(outputFile)) throw new Error("Nevar pārrakstīt esošo AI: " + outputFile.fsName);
        }
        if (!templateFile.copy(outputFile.fsName)) throw new Error("Neizdevās nokopēt MASTER template uz: " + outputFile.fsName);
        return true;
    }

    function makePageOutputName(pdfFile, pageNo, totalPages) {
        var base = PDC.TextUtils.baseNameNoExt(pdfFile);
        if (totalPages <= 1) return base + ".ai";
        return base + "_p" + PDC.TextUtils.padPageNumber(pageNo, totalPages) + ".ai";
    }
    function pageJobKey(pdfFile, pageNo) {
        return pdfFile.fsName.toLowerCase() + "|" + String(pageNo);
    }
    return {
        makePageOutputName: makePageOutputName,
        pageJobKey: pageJobKey,
        copyTemplateToOutput: copyTemplateToOutput
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/core/BatchRunner.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/core/BatchRunner.jsx

    Purpose:
      The controller between the ScriptUI view (src/ui/BatchWindow.jsx) and the
      core engines. Plan phases 11 and 12: the window contains only widgets and
      event wiring, every decision is made here.

        BatchWindow (view)  ->  BatchRunner (controller)  ->  core/* , services/*

      The controller never touches a widget directly. It calls the small "view"
      interface that BatchWindow passes in:

        view.addLog(text)                 view.updateFields()
        view.getLogLines()                view.renderPageRows()
        view.setStatusText(text)          view.updatePageSummaryAndStart()
        view.setCurrentText(text)         view.setRunning(bool)
        view.setProgress(percent)         view.resetPageScroll()
        view.clearLog()                   view.update()

    Source:
      scan() / getPageInfo() / rebuildPageJobs() / runSelected() are the GUI logic
      of the reference script (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines
      1017-1103 and the START BATCH handler 1142-1277) moved out of the window
      unchanged, with three additions:
        * CONFIG.dryRun - destructive steps are only planned and logged;
        * errors go through PDC.ErrorService (log + logs/errors/<ts>/ report);
        * the batch log is written even if the operator closes the window
          right after a run.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("BatchRunner", (function () {

    function create(view) {

        var state = {
            jobFolder: null,
            pdfFolder: null,
            manualPdfFolder: null,
            pdfScanMode: "",
            templateFolder: null,
            templateFile: null,
            outputFolder: null,
            logFolder: null,
            errorFolder: null,
            pdfFiles: [],
            running: false
        };

        var pageCountCache = {};
        var pageJobs = [];

        /* ---------------------------------------------------------------- */
        /*  state access                                                     */
        /* ---------------------------------------------------------------- */

        function getState() { return state; }
        function getPageJobs() { return pageJobs; }
        function isRunning() { return state.running; }

        function selectedPageCount() {
            var n = 0;
            for (var i = 0; i < pageJobs.length; i++) if (pageJobs[i].checked) n++;
            return n;
        }

        function setPageChecked(index, value) {
            if (index < 0 || index >= pageJobs.length) return false;
            pageJobs[index].checked = !!value;
            return true;
        }

        function setAllChecks(value) {
            for (var i = 0; i < pageJobs.length; i++) pageJobs[i].checked = value;
            view.renderPageRows();
        }

        function invertAllChecks() {
            for (var i = 0; i < pageJobs.length; i++) pageJobs[i].checked = !pageJobs[i].checked;
            view.renderPageRows();
        }

        function selectedJobs() {
            var list = [];
            for (var i = 0; i < pageJobs.length; i++) if (pageJobs[i].checked) list.push(pageJobs[i]);
            return list;
        }

        /* ---------------------------------------------------------------- */
        /*  folder handling                                                  */
        /* ---------------------------------------------------------------- */

        function ensureJobFolders() {
            var folders = PDC.Paths.jobFolders(state.jobFolder);
            state.templateFolder = folders.template;
            state.outputFolder = state.outputFolder ? state.outputFolder : folders.output;
            state.logFolder = folders.logs;
            state.errorFolder = folders.errors;
            PDC.FileService.ensureFolder(state.templateFolder);
            PDC.FileService.ensureFolder(state.outputFolder);
            PDC.FileService.ensureFolder(state.logFolder);
            PDC.FileService.ensureFolder(state.errorFolder);
            return folders;
        }

        function selectJobFolder(jobFolder) {
            state.jobFolder = jobFolder;
            state.outputFolder = PDC.Paths.getOutputFolder(jobFolder);
            state.manualPdfFolder = null;
            state.templateFile = null;
            view.clearLog();
            view.addLog("JOB: " + PDC.TextUtils.displayPath(jobFolder));
            PDC.LogService.logInfo("JOB folder selected: " + PDC.TextUtils.displayPath(jobFolder));
            return scan(true);
        }

        function setManualPdfFolder(folder) {
            state.manualPdfFolder = folder;
            view.addLog("PDF MANUAL: " + PDC.TextUtils.displayPath(folder));
            PDC.LogService.logInfo("Manual PDF folder: " + PDC.TextUtils.displayPath(folder));
            return scan(true);
        }

        function setTemplateFile(file) {
            state.templateFile = file;
            view.updateFields();
            PDC.LogService.logInfo("Template selected manually: " + PDC.TextUtils.displayPath(file));
            return scan(false);
        }

        function setOutputFolder(folder) {
            state.outputFolder = folder;
            PDC.FileService.ensureFolder(state.outputFolder);
            view.updateFields();
            PDC.LogService.logInfo("Output folder: " + PDC.TextUtils.displayPath(folder));
            return scan(false);
        }

        /* ---------------------------------------------------------------- */
        /*  page count (cached per file signature)                           */
        /* ---------------------------------------------------------------- */

        function getPageInfo(pdfFile, forceRedetect) {
            var k = pdfFile.fsName.toLowerCase();
            var sig = PDC.FileService.safeFileSignature(pdfFile);
            var cached = pageCountCache[k];
            if (!forceRedetect && cached && cached.signature === sig) return cached;
            view.setCurrentText("Skaitu PDF lapas: " + decodeURI(pdfFile.name));
            view.update();
            var info = PDC.PdfPageCount.detectPdfPageCount(pdfFile);
            var result = { signature: sig, count: info.count, method: info.method };
            pageCountCache[k] = result;
            return result;
        }

        function rebuildPageJobs(forceRedetect) {
            var oldChecks = {};
            for (var x = 0; x < pageJobs.length; x++) {
                oldChecks[PDC.OutputManager.pageJobKey(pageJobs[x].pdfFile, pageJobs[x].pageNo)] = pageJobs[x].checked;
            }
            var jobs = [];
            var totalPages = 0;
            for (var i = 0; i < state.pdfFiles.length; i++) {
                var pdfFile = state.pdfFiles[i];
                var info = getPageInfo(pdfFile, forceRedetect);
                var pages = info.count;
                if (!pages || pages < 1) pages = 1;
                totalPages += pages;
                view.addLog("PDF: " + decodeURI(pdfFile.name) + " | lapas=" + pages + " | " + info.method);
                for (var p = 1; p <= pages; p++) {
                    var key = PDC.OutputManager.pageJobKey(pdfFile, p);
                    jobs.push({
                        key: key,
                        pdfFile: pdfFile,
                        pageNo: p,
                        pageCount: pages,
                        checked: (oldChecks[key] !== undefined) ? oldChecks[key] : true,
                        outputName: PDC.OutputManager.makePageOutputName(pdfFile, p, pages)
                    });
                }
            }
            pageJobs = jobs;
            view.resetPageScroll();
            view.setCurrentText("");
            view.renderPageRows();
            return totalPages;
        }

        /* ---------------------------------------------------------------- */
        /*  scan                                                             */
        /* ---------------------------------------------------------------- */

        function scan(forceRedetect) {
            if (!state.jobFolder) return 0;

            var preferredPdfFolder = PDC.Paths.getInputFolder(state.jobFolder);
            ensureJobFolders();

            var pdfResolution = PDC.FileService.resolvePdfQueue(state.jobFolder, preferredPdfFolder, state.manualPdfFolder);
            state.pdfFolder = pdfResolution.root;
            state.pdfFiles = pdfResolution.files;
            state.pdfScanMode = pdfResolution.mode;

            if (!state.templateFile || !state.templateFile.exists) {
                state.templateFile = PDC.TemplateManager.detectTemplate(state.templateFolder);
            }

            view.updateFields();
            view.addLog("");
            view.addLog("PĀRBAUDE");
            view.addLog("PDF faili rindā: " + state.pdfFiles.length);
            view.addLog("PDF režīms: " + state.pdfScanMode);
            view.addLog("PDF avots: " + PDC.TextUtils.displayPath(state.pdfFolder));
            var totalPages = 0;
            if (state.pdfFiles.length > 0) {
                totalPages = rebuildPageJobs(!!forceRedetect);
            } else {
                pageJobs = [];
                view.renderPageRows();
                view.addLog("! PDF nav atrasts.");
            }

            var templateOK = state.templateFile && state.templateFile.exists;
            if (templateOK) view.addLog("Template: " + state.templateFile.name);
            else view.addLog("! Template nav atrasts folderī TEMPLATE.");
            view.addLog("AI OUT: " + PDC.TextUtils.displayPath(state.outputFolder));
            view.addLog("PDF lapas kopā: " + totalPages);
            view.addLog("Atzīmētas apstrādei: " + selectedPageCount());

            view.setStatusText("PDF faili: " + state.pdfFiles.length +
                " | lapas: " + pageJobs.length +
                " | izvēlētas: " + selectedPageCount() +
                " | Template: " + (templateOK ? "OK" : "NAV ATRASTS"));

            view.updatePageSummaryAndStart();

            PDC.LogService.logInfo("Scan done: pdf=" + state.pdfFiles.length +
                " pages=" + totalPages + " selected=" + selectedPageCount() +
                " template=" + (templateOK ? "OK" : "MISSING"));

            return totalPages;
        }

        /* ---------------------------------------------------------------- */
        /*  run                                                              */
        /* ---------------------------------------------------------------- */

        function runSelected(options) {
            var opts = options ? options : {};
            var overwrite = (opts.overwrite === true);
            var clearArtwork = (opts.clearArtwork !== false);

            if (state.running) return null;

            scan(false);

            if (!state.templateFile || !state.templateFile.exists) {
                alert("Template nav atrasts.");
                return null;
            }

            var jobs = selectedJobs();
            if (jobs.length === 0) {
                alert("Nav ieķeksēta neviena PDF lapa.");
                return null;
            }

            state.running = true;
            view.setRunning(true);

            var okCount = 0, errorCount = 0, skipCount = 0, dryCount = 0;
            var total = jobs.length;

            view.addLog("");
            view.addLog("========================================");
            view.addLog("BATCH START" + (PDC.CONFIG.dryRun ? "  (DRY RUN)" : ""));
            view.addLog("Template: " + PDC.TextUtils.displayPath(state.templateFile));
            view.addLog("Izvēlētas PDF lapas: " + total);
            view.addLog("========================================");
            PDC.LogService.logInfo("BATCH START (dryRun=" + PDC.CONFIG.dryRun + ", pages=" + total + ")");

            var oldInteraction = app.userInteractionLevel;
            try { app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS; } catch (eUI0) {}

            for (var i = 0; i < total; i++) {
                var job = jobs[i];
                var pdfFile = job.pdfFile;
                var outputFile = new File(state.outputFolder.fsName + "/" + job.outputName);

                view.setCurrentText((i + 1) + " / " + total + "   " + decodeURI(pdfFile.name) + "   | lapa " + job.pageNo + "/" + job.pageCount);
                view.setProgress(Math.round((i / total) * 100));
                view.update();

                if (outputFile.exists && !overwrite) {
                    view.addLog("SKIP  " + decodeURI(pdfFile.name) + " | lapa " + job.pageNo + " → " + decodeURI(outputFile.name) + " jau eksistē");
                    PDC.LogService.logInfo("SKIP existing output: " + decodeURI(outputFile.name));
                    skipCount++;
                    continue;
                }

                if (PDC.CONFIG.dryRun) {
                    view.addLog("PLĀNS " + decodeURI(pdfFile.name) + " | lapa " + job.pageNo +
                        " → " + decodeURI(outputFile.name) + " (dry run: netiek izpildīts)");
                    PDC.LogService.logInfo("DRY RUN planned: " + decodeURI(pdfFile.name) + " page " + job.pageNo + " -> " + decodeURI(outputFile.name));
                    dryCount++;
                    view.setProgress(Math.round(((i + 1) / total) * 100));
                    view.update();
                    continue;
                }

                var sourceDoc = null;
                var destDoc = null;
                var templateCopied = false;

                try {
                    sourceDoc = PDC.PdfPageCount.openPdfPage(pdfFile, job.pageNo);
                    sourceDoc.activate();

                    /* v6 cleanup - bez alert, tikai stats */
                    var fileStats = PDC.PdfCleanup.run(sourceDoc);

                    templateCopied = PDC.OutputManager.copyTemplateToOutput(state.templateFile, outputFile, overwrite);
                    if (!templateCopied) throw new Error("Output AI jau eksistē.");

                    destDoc = app.open(outputFile);
                    destDoc.activate();

                    var artworkLayer = PDC.TemplateManager.findOrCreateArtworkLayer(destDoc);
                    if (clearArtwork) PDC.TemplateManager.clearArtworkLayer(artworkLayer);

                    var copiedObjects = PDC.TemplateManager.duplicateSourceLayersIntoArtwork(sourceDoc, artworkLayer);

                    destDoc.activate();
                    destDoc.save();

                    PDC.FileService.safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
                    PDC.FileService.safeClose(destDoc, SaveOptions.SAVECHANGES);

                    okCount++;
                    view.addLog("OK    " + decodeURI(pdfFile.name) + " | lapa " + job.pageNo + "/" + job.pageCount +
                        " → " + decodeURI(outputFile.name) +
                        " | obj=" + copiedObjects +
                        " | " + PDC.PdfCleanup.summaryLine(fileStats));
                    PDC.LogService.logInfo("OK " + decodeURI(outputFile.name) +
                        " | objects=" + copiedObjects + " | " + PDC.PdfCleanup.summaryLine(fileStats));

                } catch (err) {
                    errorCount++;
                    PDC.FileService.safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
                    PDC.FileService.safeClose(destDoc, SaveOptions.DONOTSAVECHANGES);
                    if (templateCopied && outputFile.exists) PDC.FileService.removeIfExists(outputFile);
                    view.addLog("ERROR " + decodeURI(pdfFile.name) + " | lapa " + job.pageNo + " | " + err);
                    PDC.ErrorService.handleError(err, {
                        operation: "Batch page processing",
                        inputFile: pdfFile,
                        outputFile: outputFile,
                        templateFile: state.templateFile,
                        pdfPage: job.pageNo,
                        jobFolder: state.jobFolder
                    }, { silent: true });
                }

                view.setProgress(Math.round(((i + 1) / total) * 100));
                view.update();
                try { $.gc(); } catch (eGc) {}
            }

            try { app.userInteractionLevel = oldInteraction; } catch (eUI1) {}

            view.setProgress(100);
            view.setCurrentText("Pabeigts.");

            view.addLog("");
            view.addLog("========================================");
            view.addLog("BATCH DONE");
            view.addLog("OK: " + okCount);
            view.addLog("SKIP: " + skipCount);
            if (PDC.CONFIG.dryRun) view.addLog("PLĀNS (dry run): " + dryCount);
            view.addLog("ERROR: " + errorCount);
            view.addLog("========================================");

            PDC.LogService.logInfo("BATCH DONE ok=" + okCount + " skip=" + skipCount +
                " dry=" + dryCount + " error=" + errorCount);

            finishRun();

            alert("Batch pabeigts." +
                (PDC.CONFIG.dryRun ? " (DRY RUN - nekas netika saglabāts)" : "") +
                "\n\nIzvēlētās lapas: " + total +
                "\nOK: " + okCount +
                "\nSKIP: " + skipCount +
                (PDC.CONFIG.dryRun ? ("\nPLĀNS: " + dryCount) : "") +
                "\nERROR: " + errorCount);

            return { total: total, ok: okCount, skip: skipCount, dry: dryCount, error: errorCount };
        }

        function finishRun() {
            state.running = false;
            view.setRunning(false);

            try {
                PDC.LogService.writeJobLog(state.logFolder, view.getLogLines());
                PDC.LogService.flushSessionLog();
            } catch (eLog) {}

            view.renderPageRows();
        }

        /* ---------------------------------------------------------------- */

        return {
            getState: getState,
            getPageJobs: getPageJobs,
            isRunning: isRunning,
            selectedPageCount: selectedPageCount,
            setPageChecked: setPageChecked,
            setAllChecks: setAllChecks,
            invertAllChecks: invertAllChecks,
            selectJobFolder: selectJobFolder,
            setManualPdfFolder: setManualPdfFolder,
            setTemplateFile: setTemplateFile,
            setOutputFolder: setOutputFolder,
            scan: scan,
            rebuildPageJobs: rebuildPageJobs,
            finishRun: finishRun,
            runSelected: runSelected
        };
    }

    return {
        create: create
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/core/Diagnostics.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/core/Diagnostics.jsx

    Purpose:
      Plan phase 18. runDiagnostics() answers "why is this not working?" before
      a batch is started:

        * which Adobe application and version is running the script;
        * where the project root is and whether the project folders exist;
        * whether logs/ and temp/ are writable;
        * the effective CONFIG values (version, dryRun, debug, overwrite);
        * how many documents are open in Illustrator;
        * for a chosen JOB folder: PDF folder, PDF count, TEMPLATE folder,
          detected template file, AI_OUT / LOG / ERROR write access;
        * whether every expected module was loaded.

      The result can be logged, returned as text, or shown in a small window.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("Diagnostics", (function () {

    var EXPECTED_MODULES = [
        "TextUtils", "FileService", "LogService", "Paths", "ErrorService",
        "PdfCleanup", "PdfPageCount", "TemplateManager", "OutputManager",
        "BatchRunner", "Diagnostics", "BatchWindow"
    ];

    function check(name, value, ok) {
        return { name: name, value: value, ok: (ok === undefined ? true : !!ok) };
    }

    function illustratorInfo() {
        var parts = [];
        try {
            parts.push("Application: " + app.name + " " + app.version);
        } catch (e) {
            parts.push("Application: nav pieejama (skripts nav palaists Illustrator)");
        }
        try { parts.push("Build: " + app.build); } catch (e2) {}
        try { parts.push("Documents open: " + app.documents.length); } catch (e3) {}
        try { parts.push("Interaction level: " + app.userInteractionLevel); } catch (e4) {}
        try { parts.push("ExtendScript engine: " + $.version); } catch (e5) {}
        return parts.join("\r\n");
    }

    function projectChecks() {
        var results = [];
        var root = PDC.Paths.getProjectRoot();
        var logs = PDC.Paths.getLogsFolder();
        var temp = PDC.Paths.getTempFolder();
        var config = PDC.Paths.getConfigFolder();
        var entry = PDC.Paths.getScriptFile();

        results.push(check("Project root", PDC.TextUtils.displayPath(root), root && root.exists));
        results.push(check("Entry point", PDC.TextUtils.displayPath(entry), entry && entry.exists));
        results.push(check("config/ folder", PDC.TextUtils.displayPath(config), config && config.exists));
        results.push(check("logs/ folder", PDC.TextUtils.displayPath(logs), logs && logs.exists));
        results.push(check("logs/ writable", PDC.TextUtils.displayPath(logs), PDC.FileService.isWritableFolder(logs)));
        results.push(check("temp/ folder", PDC.TextUtils.displayPath(temp), temp && temp.exists));
        results.push(check("temp/ writable", PDC.TextUtils.displayPath(temp), PDC.FileService.isWritableFolder(temp)));

        return results;
    }

    function configChecks() {
        var c = PDC.CONFIG;
        var results = [];
        results.push(check("Version", c.version));
        results.push(check("debug", String(c.debug)));
        results.push(check("dryRun", String(c.dryRun)));
        results.push(check("overwriteExisting", String(c.overwriteExisting)));
        results.push(check("artworkLayerName", c.artworkLayerName));
        results.push(check("visiblePageRows", String(c.visiblePageRows)));
        results.push(check("ungroupPasses", String(c.cleanup.ungroupPasses)));
        results.push(check("releaseSafeVectorMasks", String(c.cleanup.releaseSafeVectorMasks)));
        results.push(check("deleteCropMarks", String(c.cleanup.deleteCropMarks)));

        var missing = [];
        for (var i = 0; i < EXPECTED_MODULES.length; i++) {
            if (!PDC[EXPECTED_MODULES[i]]) missing.push(EXPECTED_MODULES[i]);
        }
        results.push(check("Modules loaded", PDC.moduleList(), missing.length === 0));
        if (missing.length > 0) results.push(check("Modules MISSING", missing.join(", "), false));

        return results;
    }

    function jobChecks(jobFolder) {
        var results = [];
        if (!jobFolder) return results;

        var folders = PDC.Paths.jobFolders(jobFolder);
        results.push(check("JOB folder", PDC.TextUtils.displayPath(jobFolder), jobFolder.exists));
        results.push(check("JOB PDF/ folder", PDC.TextUtils.displayPath(folders.input), folders.input.exists));
        results.push(check("JOB TEMPLATE/ folder", PDC.TextUtils.displayPath(folders.template), folders.template.exists));
        results.push(check("JOB AI_OUT/ folder", PDC.TextUtils.displayPath(folders.output), folders.output.exists));
        results.push(check("JOB AI_OUT/ writable", PDC.TextUtils.displayPath(folders.output), PDC.FileService.isWritableFolder(folders.output)));
        results.push(check("JOB LOG/ folder", PDC.TextUtils.displayPath(folders.logs), folders.logs.exists));
        results.push(check("JOB ERROR/ folder", PDC.TextUtils.displayPath(folders.errors), folders.errors.exists));

        var queue = PDC.FileService.resolvePdfQueue(jobFolder, folders.input, null);
        results.push(check("PDF queue files", String(queue.files.length) + " (" + queue.mode + ")", queue.files.length > 0));

        var template = PDC.TemplateManager.detectTemplate(folders.template);
        results.push(check("Template detected", template ? template.name : "(nav)", !!template));

        return results;
    }

    function collect(jobFolder) {
        var results = [];
        results = results.concat(projectChecks());
        results = results.concat(configChecks());
        results = results.concat(jobChecks(jobFolder));
        return results;
    }

    function runText(jobFolder) {
        var results = collect(jobFolder);
        var lines = [];
        lines.push("PDF Deep Cleanup AI 2026 - DIAGNOSTIKA");
        lines.push("========================================");
        lines.push(illustratorInfo());
        lines.push("");
        lines.push("--- pārbaudes ---");
        var problems = 0;
        for (var i = 0; i < results.length; i++) {
            var r = results[i];
            if (!r.ok) problems++;
            lines.push((r.ok ? "[OK]   " : "[FAIL] ") + r.name + ": " + r.value);
        }
        lines.push("");
        lines.push("========================================");
        lines.push(problems === 0 ? "Rezultāts: viss OK" : ("Rezultāts: problēmas (" + problems + ")"));
        return lines.join("\r\n");
    }

    function logResults(jobFolder) {
        var results = collect(jobFolder);
        for (var i = 0; i < results.length; i++) {
            var r = results[i];
            var line = "DIAG " + (r.ok ? "OK  " : "FAIL") + " " + r.name + ": " + r.value;
            if (r.ok) PDC.LogService.logInfo(line);
            else PDC.LogService.logWarning(line);
        }
        return results;
    }

    function showWindow(jobFolder) {
        var w = new Window("dialog", "Diagnostika - " + PDC.CONFIG.projectName);
        w.orientation = "column";
        w.alignChildren = ["fill", "top"];
        w.margins = 12;
        w.spacing = 8;

        var box = w.add("edittext", undefined, runText(jobFolder), { multiline: true, scrolling: true });
        box.preferredSize = [720, 420];

        var buttons = w.add("group");
        buttons.alignment = "right";
        var refreshBtn = buttons.add("button", undefined, "Pārbaudīt vēlreiz");
        var closeBtn = buttons.add("button", undefined, "Aizvērt");

        refreshBtn.onClick = function() {
            box.text = runText(jobFolder);
            w.update();
        };
        closeBtn.onClick = function() { w.close(); };

        w.center();
        w.show();
    }

    return {
        EXPECTED_MODULES: EXPECTED_MODULES,
        collect: collect,
        runText: runText,
        logResults: logResults,
        showWindow: showWindow
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/ui/BatchWindow.jsx
// ---------------------------------------------------------------------------
/*
    PDF Deep Cleanup AI 2026
    Module: src/ui/BatchWindow.jsx

    Purpose:
      ScriptUI view. Builds the batch window and owns every widget.

      This file contains NO business logic: buttons only call functions on the
      controller that lives in src/core/BatchRunner.jsx, and the controller
      talks back to the UI only through the "view" interface object defined at
      the end of open(). That keeps the UI, the controller and the core engines
      separate:

        BatchWindow (view)  ->  BatchRunner (controller)  ->  core/* , services/*

    Source:
      Widget construction is extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 796-927). Everything after
      that line was rewritten as the view/controller glue but keeps the exact
      same labels, layout and behaviour.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("BatchWindow", (function () {

    function open() {    var w = new Window("dialog", PDC.CONFIG.appName);
    w.orientation = "column";
    w.alignChildren = ["fill", "top"];
    w.spacing = 7;
    w.margins = 12;

    var jobPanel = w.add("panel", undefined, "Darba folderis");
    jobPanel.orientation = "row";
    jobPanel.alignChildren = ["fill", "center"];
    jobPanel.margins = 9;
    var jobField = jobPanel.add("edittext", undefined, "");
    jobField.characters = 64;
    jobField.enabled = false;
    var jobBtn = jobPanel.add("button", undefined, "Izvēlēties...");

    var pathsPanel = w.add("panel", undefined, "Batch ceļi");
    pathsPanel.orientation = "column";
    pathsPanel.alignChildren = ["fill", "top"];
    pathsPanel.margins = 9;
    function addPathRow(labelText, withButton) {
        var g = pathsPanel.add("group");
        g.orientation = "row";
        g.alignChildren = ["left", "center"];
        var lbl = g.add("statictext", undefined, labelText);
        lbl.preferredSize.width = 82;
        var fld = g.add("edittext", undefined, "");
        fld.characters = 56;
        fld.enabled = false;
        var btn = null;
        if (withButton) btn = g.add("button", undefined, "Mainīt...");
        return { group: g, field: fld, button: btn };
    }
    var pdfRow = addPathRow("PDF:", true);
    var tplRow = addPathRow("Template:", true);
    var outRow = addPathRow("AI OUT:", true);

    var optionsPanel = w.add("panel", undefined, "Opcijas");
    optionsPanel.orientation = "row";
    optionsPanel.alignChildren = ["left", "center"];
    optionsPanel.margins = 9;
    var overwriteCb = optionsPanel.add("checkbox", undefined, "Pārrakstīt esošos AI");
    overwriteCb.value = PDC.CONFIG.overwriteExisting;
    var clearArtworkCb = optionsPanel.add("checkbox", undefined, 'Iztīrīt template slāni "ARTWORK"');
    clearArtworkCb.value = PDC.CONFIG.clearArtworkByDefault;

    var pagePanel = w.add("panel", undefined, "PDF lapas — ieķeksē, kuras apstrādāt");
    pagePanel.orientation = "column";
    pagePanel.alignChildren = ["fill", "top"];
    pagePanel.margins = 9;

    var pageSummary = pagePanel.add("statictext", undefined, "PDF faili: 0 | Lapas: 0 | Atzīmētas: 0");

    var pageToolbar = pagePanel.add("group");
    pageToolbar.orientation = "row";
    pageToolbar.alignChildren = ["left", "center"];
    var allBtn = pageToolbar.add("button", undefined, "Visas ✓");
    var noneBtn = pageToolbar.add("button", undefined, "Nevienu");
    var invertBtn = pageToolbar.add("button", undefined, "Apgriezt");
    pageToolbar.add("statictext", undefined, "   Ritināšana: labajā malā");

    var pageArea = pagePanel.add("group");
    pageArea.orientation = "row";
    pageArea.alignChildren = ["fill", "top"];

    var rowsGroup = pageArea.add("group");
    rowsGroup.orientation = "column";
    rowsGroup.alignChildren = ["fill", "top"];
    rowsGroup.spacing = 2;

    var header = rowsGroup.add("group");
    header.orientation = "row";
    var h1 = header.add("statictext", undefined, "Apstrādāt / lapa");
    h1.preferredSize.width = 120;
    var h2 = header.add("statictext", undefined, "PDF fails");
    h2.preferredSize.width = 300;
    var h3 = header.add("statictext", undefined, "AI output");
    h3.preferredSize.width = 240;

        var visibleRows = PDC.CONFIG.visiblePageRows;
        var pageRows = [];

    for (var rr = 0; rr < visibleRows; rr++) {
        var rg = rowsGroup.add("group");
        rg.orientation = "row";
        rg.alignChildren = ["left", "center"];
        var cb = rg.add("checkbox", undefined, "Lapa 00");
        cb.preferredSize.width = 120;
        var pdfText = rg.add("statictext", undefined, "");
        pdfText.preferredSize.width = 300;
        var outText = rg.add("statictext", undefined, "");
        outText.preferredSize.width = 240;
        var rowObj = {
            group: rg,
            checkbox: cb,
            pdfText: pdfText,
            outText: outText,
            jobIndex: -1
        };
        // Closure lai fiksētu rowObj katram checkbox
        (function(row) {
            row.checkbox.onClick = function() {
                if (!ctl.setPageChecked(row.jobIndex, row.checkbox.value)) return;
                /* atzīmes stāvokli glabā BatchRunner kontrolleris */
                updatePageSummaryAndStart();
            };
        })(rowObj);
        pageRows.push(rowObj);
    }

    var pageScroll = pageArea.add("scrollbar", undefined, 0, 0, 0);
    pageScroll.preferredSize = [18, 216];

    var statusPanel = w.add("panel", undefined, "Statuss");
    statusPanel.orientation = "column";
    statusPanel.alignChildren = ["fill", "top"];
    statusPanel.margins = 9;
    var statusText = statusPanel.add("statictext", undefined, "Izvēlies darba folderi.");
    var currentText = statusPanel.add("statictext", undefined, "");
    var progress = statusPanel.add("progressbar", undefined, 0, 100);
    progress.preferredSize = [680, 14];

    var logPanel = w.add("panel", undefined, "LOG");
    logPanel.orientation = "column";
    logPanel.alignChildren = ["fill", "fill"];
    logPanel.margins = 9;
    var logBox = logPanel.add("edittext", undefined, "", { multiline: true, scrolling: true });
    logBox.preferredSize = [705, 105];

    var buttons = w.add("group");
    buttons.alignment = "right";
    var refreshBtn = buttons.add("button", undefined, "Pārbaudīt / pārlasīt PDF");
    var startBtn = buttons.add("button", undefined, "START BATCH");
        var diagBtn = buttons.add("button", undefined, "Diagnostika");
    var closeBtn = buttons.add("button", undefined, "Aizvērt");

    startBtn.enabled = false;
        /* ================================================================
           VIEW
           The only place in the project that touches a widget. The
           controller (src/core/BatchRunner.jsx) only calls these methods.
           ================================================================ */

        var logLines = [];
        var busy = false;
        var ctl = null;

        function addLog(s) {
            logLines.push(s);
            if (logBox.text.length > 0) logBox.text += "\r\n";
            logBox.text += s;
            try { logBox.active = true; logBox.selection = [logBox.text.length, logBox.text.length]; } catch(e) {}
            w.update();
        }

        function getLogLines() { return logLines; }

        function clearLog() {
            logLines = [];
            logBox.text = "";
        }

        function updateFields() {
            var state = ctl ? ctl.getState() : null;
            jobField.text = (state && state.jobFolder) ? PDC.TextUtils.displayPath(state.jobFolder) : "";
            pdfRow.field.text = (state && state.pdfFolder) ? PDC.TextUtils.displayPath(state.pdfFolder) : "";
            tplRow.field.text = (state && state.templateFile) ? PDC.TextUtils.displayPath(state.templateFile) : "";
            outRow.field.text = (state && state.outputFolder) ? PDC.TextUtils.displayPath(state.outputFolder) : "";
        }

        function updatePageSummaryAndStart() {
            var state = ctl ? ctl.getState() : null;
            var jobs = ctl ? ctl.getPageJobs() : [];
            var selected = ctl ? ctl.selectedPageCount() : 0;
            pageSummary.text = "PDF faili: " + (state ? state.pdfFiles.length : 0) +
                " | Lapas: " + jobs.length +
                " | Atzīmētas: " + selected;
            var templateOK = !!(state && state.templateFile && state.templateFile.exists);
            startBtn.enabled = (!busy && selected > 0 && templateOK);
        }

        function resetPageScroll() {
            pageScroll.value = 0;
        }

        function renderPageRows() {
            var jobs = ctl ? ctl.getPageJobs() : [];
            var maxOffset = Math.max(0, jobs.length - visibleRows);
            pageScroll.minvalue = 0;
            pageScroll.maxvalue = maxOffset;
            pageScroll.enabled = maxOffset > 0;
            if (pageScroll.value > maxOffset) pageScroll.value = maxOffset;
            if (pageScroll.value < 0) pageScroll.value = 0;
            var offset = Math.round(pageScroll.value);
            for (var r = 0; r < pageRows.length; r++) {
                var row = pageRows[r];
                var idx = offset + r;
                if (idx < jobs.length) {
                    var job = jobs[idx];
                    row.jobIndex = idx;
                    row.group.visible = true;
                    row.checkbox.enabled = !busy;
                    row.checkbox.value = !!job.checked;
                    row.checkbox.text = "Lapa " + PDC.TextUtils.padPageNumber(job.pageNo, job.pageCount);
                    row.pdfText.text = decodeURI(job.pdfFile.name);
                    row.outText.text = job.outputName;
                    row.group.helpTip = PDC.TextUtils.displayPath(job.pdfFile);
                } else {
                    row.jobIndex = -1;
                    row.group.visible = false;
                    row.checkbox.value = false;
                    row.pdfText.text = "";
                    row.outText.text = "";
                }
            }
            updatePageSummaryAndStart();
            w.update();
        }

        function setStatusText(s) { statusText.text = s; }
        function setCurrentText(s) { currentText.text = s; }
        function setProgress(p) { progress.value = p; }
        function update() { w.update(); }

        function setRunning(value) {
            busy = !!value;
            jobBtn.enabled = !busy;
            pdfRow.button.enabled = !busy;
            tplRow.button.enabled = !busy;
            outRow.button.enabled = !busy;
            refreshBtn.enabled = !busy;
            closeBtn.enabled = !busy;
            diagBtn.enabled = !busy;
            allBtn.enabled = !busy;
            noneBtn.enabled = !busy;
            invertBtn.enabled = !busy;
            if (busy) {
                startBtn.enabled = false;
                renderPageRows();
            } else {
                updatePageSummaryAndStart();
            }
        }

        function getOverwriteChoice() { return overwriteCb.value === true; }
        function getClearArtworkChoice() { return clearArtworkCb.value === true; }

        var view = {
            addLog: addLog,
            getLogLines: getLogLines,
            clearLog: clearLog,
            updateFields: updateFields,
            renderPageRows: renderPageRows,
            resetPageScroll: resetPageScroll,
            updatePageSummaryAndStart: updatePageSummaryAndStart,
            setStatusText: setStatusText,
            setCurrentText: setCurrentText,
            setProgress: setProgress,
            setRunning: setRunning,
            update: update
        };

        ctl = PDC.BatchRunner.create(view);

        /* ================================================================
           EVENT WIRING - buttons only call controller functions
           ================================================================ */

        jobBtn.onClick = function() {
            var f = Folder.selectDialog("Izvēlies JOB darba folderi");
            if (!f) return;
            ctl.selectJobFolder(f);
        };

        pdfRow.button.onClick = function() {
            var f = Folder.selectDialog("Izvēlies mapi, kurā meklēt PDF");
            if (!f) return;
            ctl.setManualPdfFolder(f);
        };

        tplRow.button.onClick = function() {
            var f = File.openDialog("Izvēlies Illustrator MASTER template", "Illustrator:*.ai;*.ait", false);
            if (!f) return;
            ctl.setTemplateFile(f);
        };

        outRow.button.onClick = function() {
            var f = Folder.selectDialog("Izvēlies AI output folderi");
            if (!f) return;
            ctl.setOutputFolder(f);
        };

        refreshBtn.onClick = function() { ctl.scan(true); };
        closeBtn.onClick   = function() { if (!busy) w.close(); };
        diagBtn.onClick    = function() { PDC.Diagnostics.showWindow(ctl.getState().jobFolder); };

        allBtn.onClick    = function() { ctl.setAllChecks(true); };
        noneBtn.onClick   = function() { ctl.setAllChecks(false); };
        invertBtn.onClick = function() { ctl.invertAllChecks(); };

        startBtn.onClick = function() {
            var oldLevel = app.userInteractionLevel;
            try {
                ctl.runSelected({
                    overwrite: getOverwriteChoice(),
                    clearArtwork: getClearArtworkChoice()
                });
            } catch (runErr) {
                PDC.ErrorService.handleError(runErr, {
                    operation: "Batch run (view level)",
                    jobFolder: ctl.getState().jobFolder
                });
            } finally {
                /* guarantees that a hard failure can never leave Illustrator in
                   DONTDISPLAYALERTS mode or leave the window locked in "running" */
                try { app.userInteractionLevel = oldLevel; } catch (eLevel) {}
                if (busy) { try { ctl.finishRun(); } catch (eFinish) {} }
            }
        };

        pageScroll.onChanging = function() { renderPageRows(); };
        pageScroll.onChange   = function() { renderPageRows(); };

        /* ================================================================
           INITIAL STATE
           ================================================================ */

        addLog(PDC.CONFIG.appName + " v" + PDC.CONFIG.version);
        addLog("Izvēlies JOB darba folderi.");
        if (PDC.CONFIG.dryRun) addLog("*** DRY RUN: faili netiks rakstīti ***");
        addLog("Projekts: " + PDC.TextUtils.displayPath(PDC.Paths.getProjectRoot()));

        updateFields();
        updatePageSummaryAndStart();

        w.center();
        w.show();
    }

    return {
        open: open
    };
}()));

// ---------------------------------------------------------------------------
// FROZEN FROM: src/Main.jsx
// ---------------------------------------------------------------------------
/*
    PDF DEEP CLEANUP AI 2026
    Version: 0.1.0

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
