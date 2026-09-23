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
    function templateScore(f) {
        var n = f.name.toLowerCase();
        var score = 0;
        if (/\.ait$/i.test(n)) score += 100;
        if (n === "master_ai_template.ai") score += 1000;
        if (n === "master_template.ai") score += 900;
        if (n.indexOf("master_ai_template") >= 0) score += 500;
        if (n.indexOf("master_template") >= 0) score += 450;
        if (n.indexOf("template") >= 0) score += 200;
        if (n.indexOf("master") >= 0) score += 100;
        return score;
    }
    function detectTemplate(templateFolder) {
        if (!templateFolder || !templateFolder.exists) return null;
        var files = templateFolder.getFiles(function(f) {
            return (f instanceof File) && /\.(ai|ait)$/i.test(f.name);
        });
        if (!files || files.length === 0) return null;
        files.sort(function(a, b) {
            var sa = templateScore(a);
            var sb = templateScore(b);
            if (sa !== sb) return sb - sa;
            var an = a.name.toLowerCase();
            var bn = b.name.toLowerCase();
            return an < bn ? -1 : (an > bn ? 1 : 0);
        });
        return files[0];
    }    return {
        templateScore: templateScore,
        detectTemplate: detectTemplate
    };
}()));
