/*
    CLEANUP AI 2026
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
    // --- view state ---
    function saveViewState(d) {
        var s = { artboardIndex: 0, zoom: null, centerPoint: null };
        try { s.artboardIndex = d.artboards.getActiveArtboardIndex(); } catch(e) {}
        try {
            if (d.views.length > 0) {
                s.zoom = d.views[0].zoom;
                var cp = d.views[0].centerPoint;
                s.centerPoint = [cp[0], cp[1]];
            }
        } catch(e2) {}
        return s;
    }
    function restoreViewState(d, s) {
        if (!s) return;
        try { d.artboards.setActiveArtboardIndex(s.artboardIndex); } catch(e) {}
        try {
            if (d.views.length > 0) {
                if (s.centerPoint) d.views[0].centerPoint = s.centerPoint;
                if (s.zoom !== null) d.views[0].zoom = s.zoom;
            }
        } catch(e2) {}
    }

    // --- unlock ---
    function unlockLayerRecursive(layer) {
        try { layer.locked = false; } catch(e) {}
        for (var i = 0; i < layer.layers.length; i++) unlockLayerRecursive(layer.layers[i]);
    }
    function unlockAll(d) {
        for (var i = 0; i < d.layers.length; i++) unlockLayerRecursive(d.layers[i]);
        for (var j = d.pageItems.length - 1; j >= 0; j--) {
            try { d.pageItems[j].locked = false; } catch(e) {}
        }
    }

    // --- appearance tests ---
    function hasNonDefaultAppearance(item) {
        try { if (item.opacity !== undefined && Math.abs(item.opacity - 100) > 0.001) return true; } catch(e) {}
        try { if (item.blendingMode !== undefined && String(item.blendingMode) !== String(BlendModes.NORMAL)) return true; } catch(e2) {}
        try { if (item.isIsolated === true) return true; } catch(e3) {}
        try {
            var ak = item.artworkKnockout;
            if (ak !== undefined) {
                var s = String(ak);
                if (s !== "KnockoutState.DISABLED" && s !== "KnockoutState.INHERITED" && s !== "0") return true;
            }
        } catch(e4) {}
        return false;
    }
    function containsNonDefaultAppearanceDescendant(group) {
        try {
            for (var i = 0; i < group.pageItems.length; i++) {
                var it = group.pageItems[i];
                if (hasNonDefaultAppearance(it)) return true;
                if (it.typename === "GroupItem" && containsNonDefaultAppearanceDescendant(it)) return true;
            }
        } catch(e) {}
        return false;
    }
    function containsImageLikeArtwork(item) {
        try {
            var t = item.typename;
            if (t === "RasterItem" || t === "PlacedItem" || t === "MeshItem" || t === "PluginItem" || t === "SymbolItem") return true;
            if (t === "GroupItem") {
                for (var i = 0; i < item.pageItems.length; i++) {
                    if (containsImageLikeArtwork(item.pageItems[i])) return true;
                }
            }
        } catch(e) {}
        return false;
    }
    function containsClippedGroupDescendant(group) {
        try {
            for (var i = 0; i < group.pageItems.length; i++) {
                var it = group.pageItems[i];
                if (it.typename === "GroupItem") {
                    try { if (it.clipped) return true; } catch(e) {}
                    if (containsClippedGroupDescendant(it)) return true;
                }
            }
        } catch(e2) {}
        return false;
    }
    function containsNestedClippedGroup(group) {
        try {
            for (var i = 0; i < group.pageItems.length; i++) {
                var it = group.pageItems[i];
                if (it.typename === "GroupItem") {
                    try { if (it !== group && it.clipped) return true; } catch(e) {}
                    if (containsNestedClippedGroup(it)) return true;
                }
            }
        } catch(e2) {}
        return false;
    }

    // --- generic helpers ---
    function isValidPageItem(item) {
        try { return !!item.typename; } catch(e) { return false; }
    }
    function getItemDepth(item) {
        var d = 0;
        var p = null;
        try { p = item.parent; } catch(e) { return d; }
        while (p) {
            try {
                if (p.typename === "GroupItem" || p.typename === "CompoundPathItem") { d++; p = p.parent; }
                else break;
            } catch(e2) { break; }
        }
        return d;
    }
    function pushUnique(arr, obj) {
        for (var i = 0; i < arr.length; i++) { if (arr[i] === obj) return; }
        arr.push(obj);
    }
    function getActiveArtboardBounds(d) {
        try {
            var idx = d.artboards.getActiveArtboardIndex();
            return d.artboards[idx].artboardRect;
        } catch(e) { return null; }
    }
    function safeBounds(it) {
        try { return it.geometricBounds; } catch(e) {
            try { return it.visibleBounds; } catch(e2) { return null; }
        }
    }
    function containsAnyFill(it) {
        try {
            if (it.typename === "PathItem") return !!it.filled;
            if (it.typename === "CompoundPathItem") {
                for (var i = 0; i < it.pathItems.length; i++) if (it.pathItems[i].filled) return true;
                return false;
            }
            if (it.typename === "GroupItem") {
                for (var j = 0; j < it.pageItems.length; j++) if (containsAnyFill(it.pageItems[j])) return true;
                return false;
            }
        } catch(e) {}
        return false;
    }
    function isTechnicalLinework(it) {
        try {
            if (it.typename === "PathItem") return !it.filled;
            if (it.typename === "CompoundPathItem") {
                if (it.pathItems.length === 0) return false;
                for (var i = 0; i < it.pathItems.length; i++) if (it.pathItems[i].filled) return false;
                return true;
            }
            if (it.typename === "GroupItem") {
                if (it.clipped) return false;
                if (it.pageItems.length === 0) return false;
                if (containsImageLikeArtwork(it)) return false;
                for (var j = 0; j < it.pageItems.length; j++) {
                    var c = it.pageItems[j];
                    if (c.typename === "PathItem" && c.filled) return false;
                    if (c.typename === "CompoundPathItem") {
                        for (var k = 0; k < c.pathItems.length; k++) if (c.pathItems[k].filled) return false;
                    }
                }
                return true;
            }
        } catch(e) {}
        return false;
    }
    function hasRiskyAncestor(item) {
        var p = null;
        try { p = item.parent; } catch(e) { return false; }
        while (p) {
            try {
                if (p.typename === "GroupItem") {
                    if (p.clipped) return true;
                    if (containsImageLikeArtwork(p)) return true;
                    if (hasNonDefaultAppearance(p)) return true;
                }
                if (p.typename === "Document" || p.typename === "Layer") break;
                p = p.parent;
            } catch(e2) { break; }
        }
        return false;
    }

    // --- safe ungroup ---
    function isSafeToUngroup(g) {
        try {
            if (g.clipped) return false;
            if (PRESERVE_TRANSPARENCY_STRUCTURES && hasNonDefaultAppearance(g)) return false;
            if (PRESERVE_IMAGE_STRUCTURES && containsImageLikeArtwork(g)) return false;
            if (containsClippedGroupDescendant(g)) return false;
            if (PRESERVE_TRANSPARENCY_STRUCTURES && containsNonDefaultAppearanceDescendant(g)) return false;
            return true;
        } catch(e) { return false; }
    }
    function collectGroupsDeepestFirst(d) {
        var arr = [];
        try {
            for (var i = 0; i < d.groupItems.length; i++) {
                arr.push({ item: d.groupItems[i], depth: getItemDepth(d.groupItems[i]) });
            }
        } catch(e) {}
        arr.sort(function(a, b) { return b.depth - a.depth; });
        var result = [];
        for (var j = 0; j < arr.length; j++) result.push(arr[j].item);
        return result;
    }
    function ungroupSafeGroups(d, maxPasses) {
        for (var pass = 0; pass < maxPasses; pass++) {
            var groups = collectGroupsDeepestFirst(d);
            if (groups.length === 0) break;
            var changed = false;
            for (var i = 0; i < groups.length; i++) {
                var g = groups[i];
                try {
                    if (!isValidPageItem(g)) continue;
                    if (!isSafeToUngroup(g)) { stats.riskyGroupsPreserved++; continue; }
                    app.executeMenuCommand("deselectall");
                    g.selected = true;
                    app.executeMenuCommand("ungroup");
                    stats.safeGroupsUngrouped++;
                    changed = true;
                } catch(e) {}
            }
            if (!changed) break;
        }
        try { app.executeMenuCommand("deselectall"); } catch(e) {}
    }

    // --- safe clipping mask release ---
    function isSafeVectorClippingGroup(g) {
        try {
            if (containsImageLikeArtwork(g)) return false;
            if (containsNestedClippedGroup(g)) return false;
            if (PRESERVE_TRANSPARENCY_STRUCTURES) {
                if (hasNonDefaultAppearance(g)) return false;
                if (containsNonDefaultAppearanceDescendant(g)) return false;
            }
            return true;
        } catch(e) { return false; }
    }
    function collectClippedGroupsDeepestFirst(d) {
        var arr = [];
        try {
            for (var i = 0; i < d.groupItems.length; i++) {
                var g = d.groupItems[i];
                try { if (g.clipped) arr.push({ item: g, depth: getItemDepth(g) }); } catch(e) {}
            }
        } catch(e2) {}
        arr.sort(function(a, b) { return b.depth - a.depth; });
        var result = [];
        for (var j = 0; j < arr.length; j++) result.push(arr[j].item);
        return result;
    }
    function collectExactMaskObjects(group) {
        var result = [];
        try {
            for (var i = 0; i < group.pageItems.length; i++) {
                var it = group.pageItems[i];
                if (it.typename === "PathItem") {
                    try { if (it.clipping) pushUnique(result, it); } catch(e) {}
                } else if (it.typename === "CompoundPathItem") {
                    var isMask = false;
                    try {
                        for (var p = 0; p < it.pathItems.length; p++) {
                            if (it.pathItems[p].clipping) { isMask = true; break; }
                        }
                    } catch(e2) {}
                    if (isMask) pushUnique(result, it);
                }
            }
        } catch(e3) {}
        return result;
    }
    function releaseSafeVectorClippingMasks(d) {
        var guard = 0;
        while (guard < 30) {
            guard++;
            var groups = collectClippedGroupsDeepestFirst(d);
            if (groups.length === 0) break;
            var changed = false;
            for (var i = 0; i < groups.length; i++) {
                var g = groups[i];
                try {
                    if (!isValidPageItem(g)) continue;
                    if (!g.clipped) continue;
                    if (!isSafeVectorClippingGroup(g)) { stats.riskyMasksPreserved++; continue; }
                    var maskObjects = collectExactMaskObjects(g);
                    app.executeMenuCommand("deselectall");
                    g.selected = true;
                    app.executeMenuCommand("releaseMask");
                    stats.vectorMasksReleased++;
                    changed = true;
                    for (var m = maskObjects.length - 1; m >= 0; m--) {
                        try {
                            if (isValidPageItem(maskObjects[m])) {
                                maskObjects[m].remove();
                                stats.maskPathsDeleted++;
                            }
                        } catch(e2) {}
                    }
                } catch(e) {}
            }
            if (!changed) break;
        }
        try { app.executeMenuCommand("deselectall"); } catch(e) {}
    }

    // --- crop marks ---
    function deleteCropPerimeterObjects(d) {
        var ab = getActiveArtboardBounds(d);
        if (!ab) return;
        var left = ab[0], top = ab[1], right = ab[2], bottom = ab[3];
        var aw = Math.abs(right - left), ah = Math.abs(top - bottom);
        var edgeTol = Math.max(6, Math.min(aw, ah) * 0.02);
        var candidates = [];
        for (var i = 0; i < d.pageItems.length; i++) {
            try {
                var t = d.pageItems[i].typename;
                if (t === "PathItem" || t === "CompoundPathItem" || t === "GroupItem") candidates.push(d.pageItems[i]);
            } catch(e) {}
        }
        for (var j = candidates.length - 1; j >= 0; j--) {
            var it = candidates[j];
            try {
                if (!isValidPageItem(it)) continue;
                if (it.typename === "GroupItem") {
                    if (it.clipped) continue;
                    if (containsImageLikeArtwork(it)) continue;
                    if (containsClippedGroupDescendant(it)) continue;
                    if (hasNonDefaultAppearance(it)) continue;
                    if (containsNonDefaultAppearanceDescendant(it)) continue;
                }
                if (containsAnyFill(it)) continue;
                if (!isTechnicalLinework(it)) continue;
                var b = safeBounds(it);
                if (!b) continue;
                var iw = Math.abs(b[2] - b[0]), ih = Math.abs(b[1] - b[3]);
                var nearLeft   = Math.abs(b[0] - left)   <= edgeTol;
                var nearRight  = Math.abs(b[2] - right)  <= edgeTol;
                var nearTop    = Math.abs(b[1] - top)    <= edgeTol;
                var nearBottom = Math.abs(b[3] - bottom) <= edgeTol;
                var spansWidth = iw >= aw * 0.90, spansHeight = ih >= ah * 0.90;
                var edgeHits = (nearLeft?1:0)+(nearRight?1:0)+(nearTop?1:0)+(nearBottom?1:0);
                var strongPerimeter =
                    (spansWidth && (nearTop || nearBottom)) ||
                    (spansHeight && (nearLeft || nearRight)) ||
                    (iw >= aw * 0.90 && ih >= ah * 0.90 && edgeHits >= 2);
                if (!strongPerimeter) continue;
                it.remove();
                stats.cropPerimetersDeleted++;
            } catch(e) {}
        }
    }
    function deleteShortCropMarks(d) {
        var ab = getActiveArtboardBounds(d);
        if (!ab) return;
        var left = ab[0], top = ab[1], right = ab[2], bottom = ab[3];
        var aw = Math.abs(right - left), ah = Math.abs(top - bottom);
        var edgeTol = Math.max(10, Math.min(aw, ah) * 0.03);
        var maxLen  = Math.max(24, Math.min(aw, ah) * 0.08);
        var paths = [];
        for (var i = 0; i < d.pathItems.length; i++) paths.push(d.pathItems[i]);
        for (var j = paths.length - 1; j >= 0; j--) {
            var p = paths[j];
            try {
                if (!isValidPageItem(p)) continue;
                try { if (p.clipping) continue; } catch(e0) {}
                if (hasRiskyAncestor(p)) continue;
                if (p.filled) continue;
                if (!p.stroked) continue;
                if (p.closed) continue;
                if (p.pathPoints.length > 2) continue;
                var b = safeBounds(p);
                if (!b) continue;
                var w = Math.abs(b[2] - b[0]), h = Math.abs(b[1] - b[3]);
                var horizontal = (w > 0 && h <= 1.25 && w <= maxLen);
                var vertical   = (h > 0 && w <= 1.25 && h <= maxLen);
                if (!horizontal && !vertical) continue;
                var cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
                var nearEdge =
                    Math.abs(cx - left)   <= edgeTol ||
                    Math.abs(cx - right)  <= edgeTol ||
                    Math.abs(cy - top)    <= edgeTol ||
                    Math.abs(cy - bottom) <= edgeTol;
                if (!nearEdge) continue;
                var insideX = (cx > left + edgeTol && cx < right - edgeTol);
                var insideY = (cy < top - edgeTol && cy > bottom + edgeTol);
                if (insideX && insideY) continue;
                p.remove();
                stats.shortCropMarksDeleted++;
            } catch(e) {}
        }
    }
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
            if (!outputFile.remove()) throw new Error("Nevar pÄrrakstÄ«t esoÅ¡o AI: " + outputFile.fsName);
        }
        if (!templateFile.copy(outputFile.fsName)) throw new Error("NeizdevÄs nokopÄ“t MASTER template uz: " + outputFile.fsName);
        return true;
    }

    /* .ait (or .ai) template -> real .ai output, converted BY ILLUSTRATOR.
       Returns the document, which is already saved as the output file. */
    function saveAsTemplateCopy(templateFile, outputFile, overwrite) {
        var out = new File(outputFile);
        if (out.exists) {
            if (!overwrite) return null;
            if (!out.remove()) throw new Error("Nevar pÄrrakstÄ«t esoÅ¡o AI: " + out.fsName);
        }
        var templateDoc = app.open(templateFile);
        try {
            templateDoc.saveAs(out);
        } catch (eSave) {
            safeClose(templateDoc, SaveOptions.DONOTSAVECHANGES);
            throw new Error("NeizdevÄs saglabÄt template kÄ AI: " + out.fsName + " (" + eSave + ")");
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
