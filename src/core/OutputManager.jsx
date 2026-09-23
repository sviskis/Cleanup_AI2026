/*
    Cleanup AI 2026
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
    function makePageOutputName(pdfFile, pageNo, totalPages) {
        var base = PDC.TextUtils.baseNameNoExt(pdfFile);
        if (totalPages <= 1) return base + ".ai";
        return base + "_p" + PDC.TextUtils.padPageNumber(pageNo, totalPages) + ".ai";
    }
    function pageJobKey(pdfFile, pageNo) {
        return pdfFile.fsName.toLowerCase() + "|" + String(pageNo);
    }    return {
        makePageOutputName: makePageOutputName,
        pageJobKey: pageJobKey
    };
}()));
