/*
    Cleanup AI 2026
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
