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
