/*
    Cleanup AI 2026
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
                /* atzÄ«mes stÄvokli glabÄ BatchRunner kontrolleris */
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
                " | AtzÄ«mÄ“tas: " + selected;
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
            var f = Folder.selectDialog("IzvÄ“lies JOB darba folderi");
            if (!f) return;
            ctl.selectJobFolder(f);
        };

        pdfRow.button.onClick = function() {
            var f = Folder.selectDialog("IzvÄ“lies mapi, kurÄ meklÄ“t PDF");
            if (!f) return;
            ctl.setManualPdfFolder(f);
        };

        tplRow.button.onClick = function() {
            var f = File.openDialog("IzvÄ“lies Illustrator MASTER template", "Illustrator:*.ai;*.ait", false);
            if (!f) return;
            ctl.setTemplateFile(f);
        };

        outRow.button.onClick = function() {
            var f = Folder.selectDialog("IzvÄ“lies AI output folderi");
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
        addLog("IzvÄ“lies JOB darba folderi.");
        if (PDC.CONFIG.dryRun) addLog("*** DRY RUN: faili netiks rakstÄ«ti ***");
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
