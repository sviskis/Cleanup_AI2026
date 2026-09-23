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

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 79-182).
      Only ARTWORK_LAYER_NAME now comes from CONFIG.artworkLayerName.

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
    }
    function findOrCreateArtworkLayer(doc) {
        var lyr = null;
        try { lyr = doc.layers.getByName(PDC.CONFIG.artworkLayerName); } catch(e) {}
        if (!lyr) {
            lyr = doc.layers.add();
            lyr.name = PDC.CONFIG.artworkLayerName;
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
    }    return {
        templateScore: templateScore,
        detectTemplate: detectTemplate,
        findOrCreateArtworkLayer: findOrCreateArtworkLayer,
        clearArtworkLayer: clearArtworkLayer,
        duplicateSourceLayersIntoArtwork: duplicateSourceLayersIntoArtwork,
        duplicateNestedLayerItemsIntoArtwork: duplicateNestedLayerItemsIntoArtwork
    };
}()));
