# ============================================================================
#  PDF Deep Cleanup AI 2026 - module extraction tool
# ----------------------------------------------------------------------------
#  Purpose:
#    Rebuilds the src/ modules that contain UNCHANGED logic from the reference
#    script. Working ExtendScript code is never retyped by hand: it is sliced
#    byte-faithfully out of archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx
#    and wrapped in an ExtendScript safe module closure.
#
#  Input  : archive/original/PDF_Deep_Cleanup_AI_Template_BATCH.jsx
#  Output : src/utils/*.jsx, src/services/*.jsx, src/core/*.jsx, src/ui/BatchWindow.jsx
#
#  File format: UTF-8 without BOM, LF line endings (same as the reference script,
#               which is what Illustrator ExtendScript reads).
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File tools/migrate_extract_sections.ps1
#
#  NOTE: run this only when the reference script or the line mapping changes.
#        Hand written modules (Config, Namespace, Paths, Diagnostics, BatchRunner,
#        ErrorService, Main) are NOT produced here and must never be overwritten.
# ============================================================================

[CmdletBinding()]
param(
    [string]$LegacyFile,
    [string]$OutRoot
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $LegacyFile) { $LegacyFile = Join-Path $scriptDir '..\archive\original\PDF_Deep_Cleanup_AI_Template_BATCH.jsx' }
if (-not $OutRoot)    { $OutRoot    = Join-Path $scriptDir '..\src' }
$LegacyFile = [System.IO.Path]::GetFullPath($LegacyFile)
$OutRoot    = [System.IO.Path]::GetFullPath($OutRoot)
$RepoRoot   = [System.IO.Path]::GetFullPath((Join-Path $OutRoot '..'))
$enc = New-Object System.Text.UTF8Encoding($false)

Write-Host ("Reference : " + $LegacyFile)
Write-Host ("Output    : " + $OutRoot)
Write-Host ("Repo root : " + $RepoRoot)

if (-not (Test-Path -LiteralPath $LegacyFile)) {
    throw "Reference script not found: $LegacyFile"
}

$text = [System.IO.File]::ReadAllText($LegacyFile) -replace "`r`n", "`n"
$LINES = $text.Split("`n")
Write-Host ("Reference script lines: " + $LINES.Length)

function Slice([int]$from, [int]$to) {
    if ($from -lt 1 -or $to -gt $LINES.Length -or $to -lt $from) {
        throw "Bad slice range: $from..$to"
    }
    return $LINES[($from - 1)..($to - 1)]
}

function Indent4([string[]]$body) {
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($l in $body) {
        if ($l.Length -eq 0) { $out.Add('') } else { $out.Add('    ' + $l) }
    }
    return $out.ToArray()
}

function Write-Module {
    param(
        [string]$RelativePath,
        [string]$Header,
        [string[]]$Body,
        [string]$Footer,
        [string]$Root
    )
    if (-not $Root) { $Root = $OutRoot }
    $full = Join-Path $Root $RelativePath
    $dir = Split-Path -Parent $full
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $joined = $Header + ($Body -join "`n") + $Footer
    # the authored here-strings in this script may arrive with CRLF, the sliced
    # legacy lines never do: normalise everything back to LF (reference format)
    $joined = $joined -replace "`r`n", "`n"
    $joined = $joined -replace "`r", "`n"
    if ($joined -notmatch "`n$") { $joined = $joined + "`n" }
    [System.IO.File]::WriteAllText($full, $joined, $enc)
    Write-Host ("WROTE " + $RelativePath + "  <- legacy lines " + $Body.Count)
}

function Join-Body {
    param([object[]]$Parts)
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($p in $Parts) {
        foreach ($l in $p) { $out.Add($l) }
        $out.Add('')
    }
    return $out.ToArray()
}

function Replace-InBody {
    param(
        [string[]]$Body,
        [hashtable]$Map
    )
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($l in $Body) {
        $n = $l
        foreach ($k in $Map.Keys) { $n = $n.Replace($k, $Map[$k]) }
        $out.Add($n)
    }
    return $out.ToArray()
}

function Insert-Before {
    param(
        [string[]]$Body,
        [string]$Match,
        [string[]]$Insert
    )
    $out = New-Object System.Collections.Generic.List[string]
    $done = $false
    foreach ($l in $Body) {
        if (-not $done -and $l.IndexOf($Match) -ge 0) {
            foreach ($i in $Insert) { $out.Add($i) }
            $done = $true
        }
        $out.Add($l)
    }
    if (-not $done) { throw "Insert-Before: match not found: $Match" }
    return $out.ToArray()
}

# ============================================================================
#  1. src/utils/TextUtils.jsx
# ============================================================================
$header = @'
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

'@
$footer = @'
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
'@
# formatTimestamp (199-203) and padPageNumber (344-350) belong to this module as well
$body = Join-Body @(
    (Indent4 (Slice 16 20)),
    (Indent4 (Slice 21 24)),
    (Indent4 (Slice 199 203)),
    (Indent4 (Slice 344 350))
)
Write-Module -RelativePath 'utils\TextUtils.jsx' -Header $header -Body $body -Footer $footer

# ============================================================================
#  2. src/services/FileService.jsx
# ============================================================================
$header = @'
/*
    PDF Deep Cleanup AI 2026
    Module: src/services/FileService.jsx

    Purpose:
      All filesystem access in one place: path building, folder creation,
      PDF scanning, file signature, safe document close, free removal helpers.

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 10-15, 25-78, 187-190, 216-221).
      Only two details were adjusted:
        * isExcludedPdfScanFolder() reads CONFIG.excludedScanFolders now
          (same default list: template, ai_out, log, error, errors, archive, .git*);
        * listPdfFilesRecursive() takes its default depth from CONFIG.maxPdfScanDepth
          (same default value 8).

      safeClose() and openPdfPage() moved to the CANONICAL Illustrator document
      engine jsx/cleanup.jsx (PDFCleanup.*) so that document handling exists
      exactly once in the project.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("FileService", (function () {

'@
$body = Replace-InBody -Body (Join-Body @( (Indent4 (Slice 10 15)), (Indent4 (Slice 25 78)), (Indent4 (Slice 187 190)), (Indent4 (Slice 216 221)) )) -Map @{
    'return (n === "template" || n === "ai_out" || n === "log" || n === "error" || n === "errors" || n === "archive" || n.indexOf(".git") === 0);' = 'return isExcludedByName(n);'
    'if (maxDepth === undefined || maxDepth === null) maxDepth = 8;' = 'if (maxDepth === undefined || maxDepth === null) maxDepth = PDC.CONFIG.maxPdfScanDepth;'
}
$footer = @'
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
        removeIfExists: removeIfExists,
        safeFileSignature: safeFileSignature,
        isWritableFolder: isWritableFolder,
        writeTextFile: writeTextFile,
        appendTextFile: appendTextFile,
        readTextFile: readTextFile
    };
}()));
'@
Write-Module -RelativePath 'services\FileService.jsx' -Header $header -Body $body -Footer $footer

# ============================================================================
#  3. src/services/LogService.jsx
# ============================================================================
$header = @'
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

'@
$body = Replace-InBody -Body (Indent4 (Slice 204 213)) -Map @{
    'ensureFolder(logFolder);' = 'PDC.FileService.ensureFolder(logFolder);'
    'logFolder.fsName + "/batch_" + formatTimestamp() + ".txt"' = 'logFolder.fsName + "/" + PDC.CONFIG.log.jobFilePrefix + "_" + PDC.TextUtils.formatTimestamp() + ".txt"'
}
$footer = @'
    /* ---- new: levelled session logging ---- */

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
'@
Write-Module -RelativePath 'services\LogService.jsx' -Header $header -Body $body -Footer $footer


# ============================================================================
#  4. src/core/PdfPageCount.jsx
# ============================================================================
$header = @'
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
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 222-336).
      Only the safeClose() calls were pointed at PDFCleanup.safeClose.

      This module contains the LEGACY page count strategy. In the Python + JSX
      worker architecture Python is authoritative for page counts (PyMuPDF,
      pypdf fallback); this code stays for the legacy application in src/.

    ExtendScript: ES3 safe. Uses File.encoding = "BINARY" for raw PDF reading.
*/

PDC.registerModule("PdfPageCount", (function () {

'@
$body = Replace-InBody -Body (Indent4 (Slice 222 336)) -Map @{
    'safeClose(' = 'PDFCleanup.safeClose('
}
$footer = @'
    return {
        detectPdfPageCountFromStructure: detectPdfPageCountFromStructure,
        detectPdfPageCountWithIllustrator: detectPdfPageCountWithIllustrator,
        detectPdfPageCount: detectPdfPageCount
    };
}()));
'@
Write-Module -RelativePath 'core\PdfPageCount.jsx' -Header $header -Body $body -Footer $footer

# ============================================================================
#  5. src/core/TemplateManager.jsx
# ============================================================================
$header = @'
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

    About:
      This module now owns ONLY template file discovery and ranking (legacy
      application support). The ARTWORK layer handling and the artwork
      duplication moved to the CANONICAL Illustrator document engine
      jsx/cleanup.jsx (PDFCleanup.findOrCreateArtworkLayer / clearArtworkLayer /
      duplicateSourceLayersIntoArtwork) so that Illustrator DOM code exists
      exactly once.

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 79-106).

    ExtendScript: ES3 safe.
*/

PDC.registerModule("TemplateManager", (function () {

'@
$body = Replace-InBody -Body (Indent4 (Slice 79 106)) -Map @{
    'ARTWORK_LAYER_NAME' = 'PDC.CONFIG.artworkLayerName'
}
$footer = @'
    return {
        templateScore: templateScore,
        detectTemplate: detectTemplate
    };
}()));
'@
Write-Module -RelativePath 'core\TemplateManager.jsx' -Header $header -Body $body -Footer $footer


# ============================================================================
#  6. src/core/OutputManager.jsx
# ============================================================================
$header = @'
/*
    PDF Deep Cleanup AI 2026
    Module: src/core/OutputManager.jsx

    Purpose:
      Legacy naming for the src/ application:
        * makePageOutputName() - <pdf>_p03.ai style output names (single page
          PDFs keep the plain <pdf>.ai name, exactly like the reference script);
        * pageJobKey()        - stable per page key used for check state/cache.

      The MASTER template copy (copyTemplateToOutput) and the .ait -> .ai
      conversion moved to the CANONICAL Illustrator document engine
      jsx/cleanup.jsx (PDFCleanup.copyTemplateToOutput / saveAsTemplateCopy).

      In the Python + JSX worker architecture the output name is produced by
      Python (pdf_ai_batch/core/naming.py) and passed to the worker; this module
      stays for the legacy application in src/ and for regression comparison.

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 351-358).

    ExtendScript: ES3 safe.
*/

PDC.registerModule("OutputManager", (function () {

'@
$body = Replace-InBody -Body (Indent4 (Slice 351 358)) -Map @{
    'baseNameNoExt(pdfFile)' = 'PDC.TextUtils.baseNameNoExt(pdfFile)'
    'padPageNumber(pageNo, totalPages)' = 'PDC.TextUtils.padPageNumber(pageNo, totalPages)'
}
$footer = @'
    return {
        makePageOutputName: makePageOutputName,
        pageJobKey: pageJobKey
    };
}()));
'@
Write-Module -RelativePath 'core\OutputManager.jsx' -Header $header -Body $body -Footer $footer

# ============================================================================
#  7. jsx/cleanup.jsx  - THE CANONICAL ILLUSTRATOR ENGINE
# ============================================================================
$header = @'
/*
    PDF DEEP CLEANUP AI 2026
    Module: jsx/cleanup.jsx

    SINGLE SOURCE OF TRUTH for Illustrator document handling in this project.

    Both consumers use this file, nothing else defines these functions:
      * jsx/worker.jsx                - the one-page worker for the Python
                                        orchestrator (uses the global PDFCleanup)
      * src/Main.jsx                  - the legacy ScriptUI application (includes
                                        this file; it registers itself into the
                                        PDC namespace, so PDC.PdfCleanup.* works)

    Contents
      1. the PDF Deep Cleanup v6 engine (APPEARANCE SAFE) - verbatim
      2. Illustrator document helpers: open a PDF page, safe close, MASTER
         template copy / .ait -> .ai conversion, ARTWORK layer handling,
         artwork duplication
      3. the run() entry point plus the stats contract mapping

    Appearance safety (unchanged from the reference implementation):
      Anything that can carry appearance (raster, placed, mesh, plugin, symbol
      artwork, transparency, opacity, blending, knockout, nested clips) is
      preserved on purpose and only counted in stats.

    Order of operations (identical to the reference script):
      1. unlock all layers and items
      2. ungroup only groups that are provably safe to ungroup
      3. release only vector-only clipping masks
      4. safe ungroup again (mask release can expose new safe groups)
      5. delete crop mark perimeters and short crop marks
      6. restore the saved view state (artboard, zoom, centre point)

    Source of the engine body:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 378-771 - the body of the
       original nested runPdfDeepCleanup()). Nested functions were lifted to
       module scope; "stats" became a module level variable with resetStats().
      The document helpers come from the same reference script:
        openPdfPage                      lines 337-343
        safeClose, removeIfExists        lines 183-190
        findOrCreateArtworkLayer         lines 107-117
        clearArtworkLayer                lines 118-130
        duplicateSourceLayersIntoArtwork lines 131-155
        duplicateNestedLayerItems...     lines 156-182
        copyTemplateToOutput             lines 191-198

    Flags: run(doc, options) accepts
        { releaseSafeVectorMasks, deleteCropMarks, ungroupPasses }
      with the reference defaults (true, true, 40). No CONFIG dependency, so the
      file works stand-alone inside the worker.

    ExtendScript: ES3 safe. No alert(), no confirm(), batch safe.
*/

var PDFCleanup = (function () {

    var DEFAULT_LAYER_NAME = "ARTWORK";

    var DEFAULT_OPTIONS = {
        releaseSafeVectorMasks: true,
        deleteCropMarks: true,
        ungroupPasses: 40
    };

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

'@
$body = Slice 378 771
$footer = @'
    /* ======================================================================
       RUN
       Original order of operations from the reference script (lines 773-785).
       ====================================================================== */

    function normalizeOptions(options) {
        var o = options ? options : {};
        var out = {};
        out.releaseSafeVectorMasks = (o.releaseSafeVectorMasks === undefined)
            ? DEFAULT_OPTIONS.releaseSafeVectorMasks : (o.releaseSafeVectorMasks === true);
        out.deleteCropMarks = (o.deleteCropMarks === undefined)
            ? DEFAULT_OPTIONS.deleteCropMarks : (o.deleteCropMarks === true);
        out.ungroupPasses = (o.ungroupPasses === undefined)
            ? DEFAULT_OPTIONS.ungroupPasses : o.ungroupPasses;
        return out;
    }

    function run(doc, options) {
        if (!doc) throw new Error("PdfCleanup.run: nav dokumenta.");

        var flags = normalizeOptions(options);

        resetStats();

        var savedView = saveViewState(doc);

        unlockAll(doc);

        ungroupSafeGroups(doc, flags.ungroupPasses);

        if (flags.releaseSafeVectorMasks) {
            releaseSafeVectorClippingMasks(doc);
        }

        ungroupSafeGroups(doc, flags.ungroupPasses);

        if (flags.deleteCropMarks) {
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

    /* ======================================================================
       DOCUMENT / TEMPLATE / ARTWORK HELPERS
       Extracted from the same reference script (line numbers in the header).
       These are the ONLY definitions of this behaviour in the project.
       ====================================================================== */

    function openPdfPage(pdfFile, pageNo) {
        var opts = app.preferences.PDFFileOptions;
        try { opts.pageToOpen = pageNo; } catch(e0) {}
        try { opts.pageRangeToOpen = String(pageNo); } catch(e1) {}
        try { opts.placeAsLinks = false; } catch(e2) {}
        return app.open(pdfFile);
    }

    function safeClose(doc, saveOption) {
        if (!doc) return;
        try { doc.close(saveOption); } catch(e) {}
    }

    function findOrCreateArtworkLayer(doc, layerName) {
        var name = layerName ? layerName : DEFAULT_LAYER_NAME;
        var lyr = null;
        try { lyr = doc.layers.getByName(name); } catch(e) {}
        if (!lyr) {
            lyr = doc.layers.add();
            lyr.name = name;
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
    }

    function copyTemplateToOutput(templateFile, outputFile, overwrite) {
        if (outputFile.exists) {
            if (!overwrite) return false;
            if (!outputFile.remove()) throw new Error("Nevar pārrakstīt esošo AI: " + outputFile.fsName);
        }
        if (!templateFile.copy(outputFile.fsName)) throw new Error("Neizdevās nokopēt MASTER template uz: " + outputFile.fsName);
        return true;
    }

    /* .ait (or .ai) template -> real .ai output, converted BY ILLUSTRATOR.
       Returns the document, which is already saved as the output file. */
    function saveAsTemplateCopy(templateFile, outputFile, overwrite) {
        var out = new File(outputFile);
        if (out.exists) {
            if (!overwrite) return null;
            if (!out.remove()) throw new Error("Nevar pārrakstīt esošo AI: " + out.fsName);
        }
        var templateDoc = app.open(templateFile);
        try {
            templateDoc.saveAs(out);
        } catch (eSave) {
            safeClose(templateDoc, SaveOptions.DONOTSAVECHANGES);
            throw new Error("Neizdevās saglabāt template kā AI: " + out.fsName + " (" + eSave + ")");
        }
        return templateDoc;
    }

    /* ======================================================================
       BATCH FILE CONTRACT (stats -> JSON) - single source of truth
       ====================================================================== */

    function statsToContract(s) {
        var st = s ? s : stats;
        return {
            safe_groups_ungrouped: st.safeGroupsUngrouped,
            risky_groups_preserved: st.riskyGroupsPreserved,
            vector_masks_released: st.vectorMasksReleased,
            risky_masks_preserved: st.riskyMasksPreserved,
            mask_paths_deleted: st.maskPathsDeleted,
            crop_perimeters_deleted: st.cropPerimetersDeleted,
            short_crop_marks_deleted: st.shortCropMarksDeleted,
            crop_objects_deleted: st.cropPerimetersDeleted + st.shortCropMarksDeleted
        };
    }

    return {
        run: run,
        resetStats: resetStats,
        getStats: function () { return stats; },
        summaryLine: summaryLine,
        statsToContract: statsToContract,
        openPdfPage: openPdfPage,
        safeClose: safeClose,
        findOrCreateArtworkLayer: findOrCreateArtworkLayer,
        clearArtworkLayer: clearArtworkLayer,
        duplicateSourceLayersIntoArtwork: duplicateSourceLayersIntoArtwork,
        duplicateNestedLayerItemsIntoArtwork: duplicateNestedLayerItemsIntoArtwork,
        copyTemplateToOutput: copyTemplateToOutput,
        saveAsTemplateCopy: saveAsTemplateCopy,
        DEFAULT_LAYER_NAME: DEFAULT_LAYER_NAME
    };
}());

/* The legacy ScriptUI application (src/Main.jsx) includes this file after
   Namespace.jsx, so it registers into the PDC namespace and keeps using
   PDC.PdfCleanup.*. The Python worker uses the plain global PDFCleanup and has
   no PDC object at all. */
if (typeof PDC !== "undefined" && PDC && PDC.registerModule) {
    PDC.registerModule("PdfCleanup", PDFCleanup);
}
'@
Write-Module -RelativePath 'jsx\cleanup.jsx' -Header $header -Body $body -Footer $footer -Root $RepoRoot


# ============================================================================
#  8. src/ui/BatchWindow.jsx
# ============================================================================
$header = @'
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

    function open() {
'@
$body = Replace-InBody -Body (Slice 796 927) -Map @{
    'BATCH_APP_NAME' = 'PDC.CONFIG.appName'
    'VISIBLE_PAGE_ROWS' = 'visibleRows'
    'overwriteCb.value = false;' = 'overwriteCb.value = PDC.CONFIG.overwriteExisting;'
    'clearArtworkCb.value = true;' = 'clearArtworkCb.value = PDC.CONFIG.clearArtworkByDefault;'
    '                if (row.jobIndex < 0 || row.jobIndex >= pageJobs.length) return;' = '                if (!ctl.setPageChecked(row.jobIndex, row.checkbox.value)) return;'
    '                pageJobs[row.jobIndex].checked = row.checkbox.value;' = '                /* atzīmes stāvokli glabā BatchRunner kontrolleris */'
}
$body = Insert-Before -Body $body -Match 'for (var rr = 0; rr < visibleRows; rr++) {' -Insert @(
    '        var visibleRows = PDC.CONFIG.visiblePageRows;',
    '        var pageRows = [];',
    ''
)
$body = Insert-Before -Body $body -Match 'var closeBtn = buttons.add(' -Insert @(
    '        var diagBtn = buttons.add("button", undefined, "Diagnostika");'
)
$footer = @'

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
'@
Write-Module -RelativePath 'ui\BatchWindow.jsx' -Header $header -Body $body -Footer $footer

Write-Host ''
Write-Host 'Extraction finished.'
Write-Host 'Next: hand written modules (src/config/Config.jsx, src/utils/Namespace.jsx,'
Write-Host 'src/utils/Paths.jsx, src/services/ErrorService.jsx, src/core/BatchRunner.jsx,'
Write-Host 'src/core/Diagnostics.jsx, src/Main.jsx) are not generated by this tool.'

