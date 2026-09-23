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
    function detectPdfPageCountFromStructure(pdfFile) {
        if (!pdfFile || !pdfFile.exists) return 0;
        var f = pdfFile;
        var oldEncoding = null;
        var bestPagesCount = 0;
        try {
            oldEncoding = f.encoding;
            f.encoding = "BINARY";
            if (!f.open("r")) return 0;
            var fileLen = 0; try { fileLen = f.length; } catch(eLen) {}
            if (fileLen > 0 && fileLen <= 80 * 1024 * 1024) {
                var all = f.read();
                var reA = /\/Type\s*\/Pages\b[\s\S]{0,2500}?\/Count\s+(\d+)/g;
                var reB = /\/Count\s+(\d+)[\s\S]{0,2500}?\/Type\s*\/Pages\b/g;
                var m;
                while ((m = reA.exec(all)) !== null) {
                    var n1 = parseInt(m[1], 10);
                    if (!isNaN(n1) && n1 > bestPagesCount) bestPagesCount = n1;
                }
                while ((m = reB.exec(all)) !== null) {
                    var n2 = parseInt(m[1], 10);
                    if (!isNaN(n2) && n2 > bestPagesCount) bestPagesCount = n2;
                }
            } else {
                var chunkSize = 2 * 1024 * 1024;
                var overlap = 4096;
                var carry = "";
                var reA2 = /\/Type\s*\/Pages\b[\s\S]{0,2500}?\/Count\s+(\d+)/g;
                var reB2 = /\/Count\s+(\d+)[\s\S]{0,2500}?\/Type\s*\/Pages\b/g;
                while (!f.eof) {
                    var part = f.read(chunkSize);
                    if (!part) break;
                    var merged = carry + part;
                    var m2;
                    while ((m2 = reA2.exec(merged)) !== null) {
                        var n3 = parseInt(m2[1], 10);
                        if (!isNaN(n3) && n3 > bestPagesCount) bestPagesCount = n3;
                    }
                    while ((m2 = reB2.exec(merged)) !== null) {
                        var n4 = parseInt(m2[1], 10);
                        if (!isNaN(n4) && n4 > bestPagesCount) bestPagesCount = n4;
                    }
                    carry = merged.substring(Math.max(0, merged.length - overlap));
                }
            }
            f.close();
            if (oldEncoding !== null) f.encoding = oldEncoding;
        } catch (e) {
            try { if (f.opened) f.close(); } catch(e2) {}
            try { if (oldEncoding !== null) f.encoding = oldEncoding; } catch(e3) {}
            return 0;
        }
        return bestPagesCount > 0 ? bestPagesCount : 0;
    }
    function detectPdfPageCountWithIllustrator(pdfFile) {
        var probeDoc = null;
        var opts = app.preferences.PDFFileOptions;
        var oldInteraction = app.userInteractionLevel;
        var hasRange = false;
        var oldRange = null;
        var hasLinks = false;
        var oldLinks = null;
        var oldPage = 1;

        try { oldPage = opts.pageToOpen; } catch(e0) {}
        try {
            oldRange = opts.pageRangeToOpen;
            opts.pageRangeToOpen = "all";
            hasRange = true;
        } catch(e1) {}

        if (!hasRange) return 0;

        try {
            oldLinks = opts.placeAsLinks;
            opts.placeAsLinks = true;
            hasLinks = true;
        } catch(e2) {}

        try {
            app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
            try { opts.pageToOpen = 1; } catch(e3) {}
            probeDoc = app.open(pdfFile);
            var count = 0;
            try { count = probeDoc.artboards.length; } catch(e4) {}
            PDFCleanup.safeClose(probeDoc, SaveOptions.DONOTSAVECHANGES);
            probeDoc = null;

            try { opts.pageToOpen = oldPage; } catch(e5) {}
            try { opts.pageRangeToOpen = oldRange; } catch(e6) {
                try { opts.pageRangeToOpen = "1"; } catch(e7) {}
            }
            if (hasLinks) try { opts.placeAsLinks = oldLinks; } catch(e8) {}
            app.userInteractionLevel = oldInteraction;
            return count;
        } catch (err) {
            PDFCleanup.safeClose(probeDoc, SaveOptions.DONOTSAVECHANGES);
            probeDoc = null;
            try { opts.pageToOpen = oldPage; } catch(e9) {}
            try { opts.pageRangeToOpen = oldRange; } catch(e10) {
                try { opts.pageRangeToOpen = "1"; } catch(e11) {}
            }
            if (hasLinks) try { opts.placeAsLinks = oldLinks; } catch(e12) {}
            try { app.userInteractionLevel = oldInteraction; } catch(e13) {}
            return 0;
        }
    }
    function detectPdfPageCount(pdfFile) {
        var aiCount = detectPdfPageCountWithIllustrator(pdfFile);
        if (aiCount > 1) return { count: aiCount, method: "Illustrator ALL" };
        var parsed = detectPdfPageCountFromStructure(pdfFile);
        if (parsed > 0) return { count: parsed, method: "PDF /Pages" };
        if (aiCount === 1) return { count: 1, method: "Illustrator" };
        return { count: 1, method: "Fallback 1" };
    }    return {
        detectPdfPageCountFromStructure: detectPdfPageCountFromStructure,
        detectPdfPageCountWithIllustrator: detectPdfPageCountWithIllustrator,
        detectPdfPageCount: detectPdfPageCount
    };
}()));
