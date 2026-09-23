/*
    Cleanup AI 2026
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
