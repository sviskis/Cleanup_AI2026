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
