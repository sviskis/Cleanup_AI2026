/*
    Cleanup AI 2026
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
        lines.push("Cleanup AI 2026 - DIAGNOSTIKA");
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
