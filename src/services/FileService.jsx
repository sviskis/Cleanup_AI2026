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
        removeIfExists: removeIfExists,
        safeFileSignature: safeFileSignature,
        isWritableFolder: isWritableFolder,
        writeTextFile: writeTextFile,
        appendTextFile: appendTextFile,
        readTextFile: readTextFile
    };
}()));
