/*
    PDF DEEP CLEANUP AI 2026
    Entry point: jsx/worker.jsx  (Illustrator side of the Python orchestrator)

    Responsibility (ONE page per invocation):

        read runtime/current_job.json
            -> validate the request
            -> open the requested PDF page
            -> run the canonical cleanup engine (jsx/cleanup.jsx)
            -> prepare the output AI (copy already made by Python, or .ait -> .ai
               conversion performed by Illustrator itself)
            -> find/create the target layer, transfer the artwork
            -> save the AI, close both documents
            -> write runtime/current_result.json

    It does NOT do: GUI, project folders, page counting, template sorting,
    naming, queue/state, logging orchestration - that is all Python.

    Files (relative to the repository root, derived from $.fileName):
        runtime/current_job.json     request written by Python (atomic rename)
        runtime/current_result.json  result written by this worker (atomic rename)
        runtime/worker.log           append only worker trace, for diagnostics

    Contract: see docs/ARCHITECTURE.md and tests/fixtures/*.json.
      request  : schema, run_id, job_id, pdf, page, template, template_mode,
                 output, layer, clear_layer, overwrite, cleanup
      result   : schema, run_id, job_id, status (OK|ERROR|SKIP), page, output,
                 objects_copied, stats{}, message, error_type
      A result is only valid for Python when job_id AND run_id match.

    Safety:
      * the MASTER template is never written:
          template_mode "copy"   - Python already copied it to output
          template_mode "saveas" - Illustrator opens the template and saves AS
                                   the output (needed for real .ait templates)
      * the source PDF is always closed with DONOTSAVECHANGES
      * overwrite=false is respected even if Python already decided
      * userInteractionLevel is always restored

    ExtendScript: ES3 safe.
*/

#target illustrator

#include "json2.js"
#include "cleanup.jsx"

var SCHEMA_RESULT = "pdf_ai_batch/job_result/v1";

/* ======================================================================
   PATHS (derived from this file, no configuration needed)
   ====================================================================== */

function workerFolder() {
    return new File($.fileName).parent;
}

function repoRootFolder() {
    return workerFolder().parent;
}

function runtimeFolder() {
    var f = new Folder(repoRootFolder().fsName + "/runtime");
    if (!f.exists) {
        try { f.create(); } catch (e) {}
    }
    return f;
}

function requestFile() { return new File(runtimeFolder().fsName + "/current_job.json"); }
function resultFile()  { return new File(runtimeFolder().fsName + "/current_result.json"); }
function logFile()     { return new File(runtimeFolder().fsName + "/worker.log"); }

/* ======================================================================
   SMALL FILE / TEXT HELPERS (independent of the legacy src/ application)
   ====================================================================== */

function readUtf8(fileObj) {
    try {
        if (!fileObj || !fileObj.exists) return "";
        fileObj.encoding = "UTF-8";
        if (!fileObj.open("r")) return "";
        var text = fileObj.read();
        fileObj.close();
        return text;
    } catch (e) {
        try { if (fileObj && fileObj.opened) fileObj.close(); } catch (e2) {}
        return "";
    }
}

function writeUtf8(fileObj, text) {
    try {
        fileObj.encoding = "UTF-8";
        fileObj.lineFeed = "Windows";
        if (!fileObj.open("w")) return false;
        fileObj.write(text);
        fileObj.close();
        return true;
    } catch (e) {
        try { if (fileObj && fileObj.opened) fileObj.close(); } catch (e2) {}
        return false;
    }
}

function removeIfExists(fileObj) {
    try {
        if (fileObj && fileObj.exists) fileObj.remove();
        return true;
    } catch (e) {
        return false;
    }
}

function nowStamp() {
    var d = new Date();
    function z(n) { return (n < 10 ? "0" : "") + n; }
    return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate()) +
           " " + z(d.getHours()) + ":" + z(d.getMinutes()) + ":" + z(d.getSeconds());
}

function logLine(text) {
    try {
        var f = logFile();
        if (f.exists && f.length > 512000) f = null;
        var old = f ? readUtf8(f) : "";
        writeUtf8(f, old + nowStamp() + " | " + text + "\r\n");
    } catch (e) {}
}

function writeResult(resultObj) {
    var target = resultFile();
    var text = JSON.stringify(resultObj) + "\r\n";
    var tmp = new File(target.fsName + ".tmp");
    if (writeUtf8(tmp, text)) {
        removeIfExists(target);
        try {
            if (tmp.rename(target.name)) return true;
        } catch (eRename) {}
    }
    /* fallback: direct write (still complete, only not atomic) */
    removeIfExists(tmp);
    return writeUtf8(target, text);
}

/* ======================================================================
   ERROR HELPERS
   ====================================================================== */

function errMessage(err) {
    if (!err) return "Nezināma kļūda";
    if (err.message) return String(err.message);
    return String(err);
}

function errFile(err) {
    try { if (err && err.fileName) return String(err.fileName); } catch (e) {}
    return "";
}

function errLine(err) {
    try { if (err && err.line !== undefined && err.line !== null) return String(err.line); } catch (e) {}
    return "";
}

function classifyError(err) {
    var m = errMessage(err);
    if (m.indexOf("nav sagatavots") >= 0) return "OUTPUT_MISSING";
    if (m.indexOf("jau eksistē") >= 0) return "OUTPUT_EXISTS";
    if (m.indexOf("nav atrasts") >= 0) return "MISSING_FILE";
    if (m.indexOf("saglabāt") >= 0) return "SAVE_FAILED";
    return "PROCESSING";
}

/* ======================================================================
   REQUEST VALIDATION
   ====================================================================== */

function validateRequest(req) {
    var problems = [];
    if (!req) return ["pieprasījums nav nolasāms"];

    if (!req.job_id) problems.push("job_id");
    if (!req.run_id) problems.push("run_id");
    if (!req.page || req.page < 1) problems.push("page");

    if (!req.pdf) {
        problems.push("pdf");
    } else if (!(new File(req.pdf)).exists) {
        problems.push("pdf nav atrasts: " + req.pdf);
    }

    if (!req.template) {
        problems.push("template");
    } else if (!(new File(req.template)).exists) {
        problems.push("template nav atrasts: " + req.template);
    }

    if (!req.output) problems.push("output");

    var mode = req.template_mode ? req.template_mode : "copy";
    if (mode !== "copy" && mode !== "saveas") problems.push("template_mode: " + mode);

    if (mode === "copy" && req.output && !(new File(req.output)).exists) {
        problems.push("output nav sagatavots (template_mode=copy): " + req.output);
    }

    return problems;
}

function baseResult(req, status, message, errorType) {
    return {
        schema: SCHEMA_RESULT,
        run_id: req && req.run_id ? req.run_id : "",
        job_id: req && req.job_id ? req.job_id : "",
        status: status,
        page: req && req.page ? req.page : 0,
        output: req && req.output ? req.output : "",
        message: message ? message : "",
        error_type: errorType ? errorType : ""
    };
}

/* ======================================================================
   PROCESS ONE JOB
   ====================================================================== */

function processJob(req) {
    var result = baseResult(req, "ERROR", "", "");
    var mode = req.template_mode ? req.template_mode : "copy";
    var outFile = new File(req.output);

    /* overwrite is decided by Python, but never trust it blindly */
    if (req.overwrite !== true && mode === "saveas" && outFile.exists) {
        result.status = "SKIP";
        result.message = "Output jau eksistē un overwrite=false";
        logLine("SKIP " + req.output);
        return result;
    }

    var sourceDoc = null;
    var destDoc = null;
    var oldLevel = app.userInteractionLevel;
    try { app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS; } catch (eLevel) {}

    try {
        logLine("START " + req.job_id + " | page " + req.page + " | " + req.pdf);
        sourceDoc = PDFCleanup.openPdfPage(new File(req.pdf), req.page);
        sourceDoc.activate();

        var stats = PDFCleanup.run(sourceDoc, req.cleanup);

        if (mode === "saveas") {
            destDoc = PDFCleanup.saveAsTemplateCopy(new File(req.template), outFile, req.overwrite === true);
            if (!destDoc) {
                result.status = "SKIP";
                result.message = "Output jau eksistē";
                PDFCleanup.safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
                sourceDoc = null;
                logLine("SKIP " + req.output);
                return result;
            }
        } else {
            destDoc = app.open(outFile);
        }

        destDoc.activate();

        var layerName = req.layer ? req.layer : PDFCleanup.DEFAULT_LAYER_NAME;
        var artworkLayer = PDFCleanup.findOrCreateArtworkLayer(destDoc, layerName);
        if (req.clear_layer !== false) PDFCleanup.clearArtworkLayer(artworkLayer);

        var copied = PDFCleanup.duplicateSourceLayersIntoArtwork(sourceDoc, artworkLayer);

        destDoc.activate();
        destDoc.save();

        PDFCleanup.safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
        sourceDoc = null;
        PDFCleanup.safeClose(destDoc, SaveOptions.SAVECHANGES);
        destDoc = null;

        result.status = "OK";
        result.objects_copied = copied;
        result.stats = PDFCleanup.statsToContract(stats);
        logLine("OK   " + req.job_id + " objects=" + copied + " " + PDFCleanup.summaryLine(stats));

    } catch (err) {
        PDFCleanup.safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
        PDFCleanup.safeClose(destDoc, SaveOptions.DONOTSAVECHANGES);
        result.status = "ERROR";
        result.message = errMessage(err);
        result.error_type = classifyError(err);
        result.error_file = errFile(err);
        result.error_line = errLine(err);
        logLine("ERROR " + req.job_id + " | " + result.error_type + " | " + result.message);
    } finally {
        try { app.userInteractionLevel = oldLevel; } catch (eRestore) {}
    }

    return result;
}

/* ======================================================================
   MAIN - always writes a result, even for a broken request
   ====================================================================== */

function main() {
    var req = null;
    var result = null;

    try {
        var requestText = readUtf8(requestFile());
        if (!requestText) {
            result = baseResult(null, "ERROR", "Nav pieprasījuma faila: " + requestFile().fsName, "NO_REQUEST");
            logLine("ERROR NO_REQUEST " + requestFile().fsName);
        } else {
            req = JSON.parse(requestText);
            var problems = validateRequest(req);
            if (problems.length > 0) {
                result = baseResult(req, "ERROR", "Nederīgs pieprasījums: " + problems.join("; "), "INVALID_REQUEST");
                logLine("ERROR INVALID_REQUEST " + problems.join("; "));
            } else {
                result = processJob(req);
            }
        }
    } catch (fatal) {
        result = baseResult(req, "ERROR", "Worker kļūda: " + errMessage(fatal), "WORKER_FATAL");
        result.error_file = errFile(fatal);
        result.error_line = errLine(fatal);
        logLine("ERROR WORKER_FATAL " + result.message);
    }

    writeResult(result);
}

try {
    main();
} catch (lastResort) {
    try {
        writeResult(baseResult(null, "ERROR", "Neizdevās pat uzrakstīt rezultātu: " + errMessage(lastResort), "WORKER_FATAL"));
    } catch (eFinal) {}
}
