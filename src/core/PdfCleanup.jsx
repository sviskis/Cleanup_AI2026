/*
    PDF Deep Cleanup AI 2026
    Module: src/core/PdfCleanup.jsx

    Purpose:
      The PDF Deep Cleanup v6 engine (APPEARANCE SAFE). This is the core value
      of the project: it removes the technical PDF junk Illustrator brings in
      with a PDF page, without touching the appearance of real artwork.

      Order of operations (identical to the reference script):
        1. unlock all layers and items
        2. ungroup only groups that are provably safe to ungroup
        3. release only vector-only clipping masks
        4. safe ungroup again (mask release can expose new safe groups)
        5. delete crop mark perimeters and short crop marks
        6. restore the saved view state (artboard, zoom, centre point)

      Anything that can carry appearance (raster, placed, mesh, plugin, symbol
      artwork, transparency, opacity, blending, knockout, nested clips) is
      preserved on purpose and only counted in stats.

    Source:
      Extracted unchanged from the reference script
      (PDF_Deep_Cleanup_AI_Template_BATCH.jsx lines 378-771 - the body of the
       original nested runPdfDeepCleanup()). The nested functions were lifted to
       module scope; "stats" became a module level variable with resetStats(),
       which is the same pattern the working v6 GUI script already used.

      Flag mapping (original local scope -> CONFIG):
        RELEASE_SAFE_VECTOR_MASKS        -> CONFIG.cleanup.releaseSafeVectorMasks
        DELETE_CROP_MARKS                -> CONFIG.cleanup.deleteCropMarks
        ungroupSafeGroups(doc, 40)       -> CONFIG.cleanup.ungroupPasses
        PRESERVE_IMAGE_STRUCTURES        -> CONFIG.cleanup.preserveImageStructures
        PRESERVE_TRANSPARENCY_STRUCTURES -> CONFIG.cleanup.preserveTransparencyStructures
        (the last two are intent flags: the reference code enforced the same
         behaviour through the "safe only" tests, not through the flags)

      No alert() and no confirm() is used - the engine is batch safe and returns
      its result through the stats object.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("PdfCleanup", (function () {

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
    /* ---- run ----
       Original order of operations from the reference script (lines 773-785). */

    function run(doc) {
        if (!doc) throw new Error("PdfCleanup.run: nav dokumenta.");

        var flags = PDC.CONFIG.cleanup;
        var RELEASE_SAFE_VECTOR_MASKS = flags.releaseSafeVectorMasks;
        var DELETE_CROP_MARKS = flags.deleteCropMarks;
        var passes = flags.ungroupPasses;

        resetStats();

        var savedView = saveViewState(doc);

        unlockAll(doc);

        ungroupSafeGroups(doc, passes);

        if (RELEASE_SAFE_VECTOR_MASKS) {
            releaseSafeVectorClippingMasks(doc);
        }

        ungroupSafeGroups(doc, passes);

        if (DELETE_CROP_MARKS) {
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

    return {
        run: run,
        resetStats: resetStats,
        getStats: function () { return stats; },
        summaryLine: summaryLine
    };
}()));
