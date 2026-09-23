#target illustrator

/*
    PDF Deep Cleanup → 12 mēneši → AI Template GUI v6
    =========================================
    Standalone Illustrator ExtendScript / JSX.

    Folderu struktūra:
        JOB\
          PDF\
          TEMPLATE\
            MASTER_AI_TEMPLATE.ai
          CONFIG\
            project_info.json
          AI_OUT\
          LOG\
          ERROR\

    Darbplūsma katram PDF:
      1. Illustrator atver PDF.
      2. Palaiž PDF Deep Cleanup.
      3. MASTER template tiek KOPĒTS uz AI_OUT\<pdf_name>.ai.
      4. Template kopija tiek atvērta.
      5. PDF source slāņi tiek dublēti zem "ARTWORK".
      6. AI tiek saglabāts.
      7. Source PDF tiek aizvērts BEZ saglabāšanas.

    MASTER template netiek pārrakstīts.
*/


// ============================================================
// PDF DEEP CLEANUP SETTINGS
// ============================================================
var PRESERVE_IMAGE_STRUCTURES = true;
var PRESERVE_TRANSPARENCY_STRUCTURES = true;
var RELEASE_SAFE_VECTOR_MASKS = true;
var DELETE_CROP_MARKS = true;

var stats = null;

function resetCleanupStats() {
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

function runPdfDeepCleanup(doc) {
    resetCleanupStats();

    var savedView = saveViewState(doc);

    unlockAll(doc);

    // 1) Ungroup tikai pilnīgi drošas grupas.
    ungroupSafeGroups(doc, 40);

    // 2) Release tikai drošas vector-only clipping maskas.
    if (RELEASE_SAFE_VECTOR_MASKS) {
        releaseSafeVectorClippingMasks(doc);
    }

    // 3) Pēc masku release vēlreiz drošais ungroup.
    ungroupSafeGroups(doc, 40);

    // 4) Crop marks.
    if (DELETE_CROP_MARKS) {
        deleteCropPerimeterObjects(doc);
        deleteShortCropMarks(doc);
    }

    try { app.executeMenuCommand("deselectall"); } catch (e) {}
    restoreViewState(doc, savedView);
    app.redraw();

    return stats;
}

// ============================================================
// VIEW STATE
// ============================================================

function saveViewState(doc) {
    var s = {
        artboardIndex: 0,
        zoom: null,
        centerPoint: null
    };

    try {
        s.artboardIndex = doc.artboards.getActiveArtboardIndex();
    } catch (e) {}

    try {
        if (doc.views.length > 0) {
            s.zoom = doc.views[0].zoom;
            var cp = doc.views[0].centerPoint;
            s.centerPoint = [cp[0], cp[1]];
        }
    } catch (e2) {}

    return s;
}

function restoreViewState(doc, s) {
    if (!s) return;

    try {
        doc.artboards.setActiveArtboardIndex(s.artboardIndex);
    } catch (e) {}

    try {
        if (doc.views.length > 0) {
            if (s.centerPoint) doc.views[0].centerPoint = s.centerPoint;
            if (s.zoom !== null) doc.views[0].zoom = s.zoom;
        }
    } catch (e2) {}
}


// ============================================================
// UNLOCK
// ============================================================

function unlockAll(doc) {
    for (var i = 0; i < doc.layers.length; i++) {
        unlockLayerRecursive(doc.layers[i]);
    }

    for (var j = doc.pageItems.length - 1; j >= 0; j--) {
        try { doc.pageItems[j].locked = false; } catch (e) {}
        // hidden statusu nemainām
    }
}

function unlockLayerRecursive(layer) {
    try { layer.locked = false; } catch (e) {}

    for (var i = 0; i < layer.layers.length; i++) {
        unlockLayerRecursive(layer.layers[i]);
    }
}


// ============================================================
// SAFE UNGROUP
// ============================================================

function ungroupSafeGroups(doc, maxPasses) {
    for (var pass = 0; pass < maxPasses; pass++) {

        var groups = collectGroupsDeepestFirst(doc);
        if (groups.length === 0) break;

        var changed = false;

        for (var i = 0; i < groups.length; i++) {
            var g = groups[i];

            try {
                if (!isValidPageItem(g)) continue;

                if (!isSafeToUngroup(g)) {
                    stats.riskyGroupsPreserved++;
                    continue;
                }

                app.executeMenuCommand("deselectall");
                g.selected = true;
                app.executeMenuCommand("ungroup");

                stats.safeGroupsUngrouped++;
                changed = true;

            } catch (e) {}
        }

        if (!changed) break;
    }

    try { app.executeMenuCommand("deselectall"); } catch (e) {}
}

function isSafeToUngroup(g) {
    try {
        // Clipping group nekad netiek ungroupota tieši.
        if (g.clipped) return false;

        // Ja pašai grupai ir transparency/blend/opacity īpašības, saglabājam.
        if (PRESERVE_TRANSPARENCY_STRUCTURES && hasNonDefaultAppearance(g)) {
            return false;
        }

        // Ļoti svarīgi: ja grupā ir raster/placed/mesh/symbol/plugin,
        // saglabājam grupas struktūru.
        if (PRESERVE_IMAGE_STRUCTURES && containsImageLikeArtwork(g)) {
            return false;
        }

        // Ja iekšpusē ir clipping group, outer group arī saglabājam.
        // Tā var būt daļa no PDF compositing/transparency struktūras.
        if (containsClippedGroupDescendant(g)) {
            return false;
        }

        // Ja jebkuram child ir opacity/blend/effect-like stāvoklis,
        // parent grupu labāk neatārdīt.
        if (PRESERVE_TRANSPARENCY_STRUCTURES && containsNonDefaultAppearanceDescendant(g)) {
            return false;
        }

        return true;

    } catch (e) {
        return false;
    }
}

function collectGroupsDeepestFirst(doc) {
    var arr = [];

    try {
        for (var i = 0; i < doc.groupItems.length; i++) {
            var g = doc.groupItems[i];

            arr.push({
                item: g,
                depth: getItemDepth(g)
            });
        }
    } catch (e) {}

    arr.sort(function(a, b) {
        return b.depth - a.depth;
    });

    var result = [];
    for (var j = 0; j < arr.length; j++) {
        result.push(arr[j].item);
    }

    return result;
}


// ============================================================
// SAFE VECTOR CLIPPING RELEASE
// ============================================================

function releaseSafeVectorClippingMasks(doc) {
    var guard = 0;

    while (guard < 30) {
        guard++;

        var groups = collectClippedGroupsDeepestFirst(doc);
        if (groups.length === 0) break;

        var changed = false;

        for (var i = 0; i < groups.length; i++) {
            var g = groups[i];

            try {
                if (!isValidPageItem(g)) continue;
                if (!g.clipped) continue;

                if (!isSafeVectorClippingGroup(g)) {
                    stats.riskyMasksPreserved++;
                    continue;
                }

                var maskObjects = collectExactMaskObjects(g);

                app.executeMenuCommand("deselectall");
                g.selected = true;
                app.executeMenuCommand("releaseMask");

                stats.vectorMasksReleased++;
                changed = true;

                // Dzēšam tikai precīzi identificēto maskas ceļu.
                for (var m = maskObjects.length - 1; m >= 0; m--) {
                    try {
                        if (isValidPageItem(maskObjects[m])) {
                            maskObjects[m].remove();
                            stats.maskPathsDeleted++;
                        }
                    } catch (e2) {}
                }

            } catch (e) {}
        }

        if (!changed) break;
    }

    try { app.executeMenuCommand("deselectall"); } catch (e) {}
}

function isSafeVectorClippingGroup(g) {
    try {
        // Nekādu image-like objektu.
        if (containsImageLikeArtwork(g)) return false;

        // Nekādu nested clipped groups.
        if (containsNestedClippedGroup(g)) return false;

        // Nekādu transparency/blend/opacity struktūru.
        if (PRESERVE_TRANSPARENCY_STRUCTURES) {
            if (hasNonDefaultAppearance(g)) return false;
            if (containsNonDefaultAppearanceDescendant(g)) return false;
        }

        return true;

    } catch (e) {
        return false;
    }
}


// ============================================================
// APPEARANCE / STRUCTURE TESTS
// ============================================================

function hasNonDefaultAppearance(item) {
    try {
        if (item.opacity !== undefined && Math.abs(item.opacity - 100) > 0.001) {
            return true;
        }
    } catch (e) {}

    try {
        if (item.blendingMode !== undefined) {
            if (String(item.blendingMode) !== String(BlendModes.NORMAL)) {
                return true;
            }
        }
    } catch (e2) {}

    try {
        if (item.isIsolated === true) return true;
    } catch (e3) {}

    // artworkKnockout dažādās Illustrator versijās var uzvesties citādi,
    // tāpēc jebkuru aktīvu/non-default stāvokli uztveram kā riskantu.
    try {
        var ak = item.artworkKnockout;
        if (ak !== undefined) {
            var s = String(ak);
            if (s !== "KnockoutState.DISABLED" &&
                s !== "KnockoutState.INHERITED" &&
                s !== "0") {
                return true;
            }
        }
    } catch (e4) {}

    return false;
}

function containsNonDefaultAppearanceDescendant(group) {
    try {
        for (var i = 0; i < group.pageItems.length; i++) {
            var it = group.pageItems[i];

            if (hasNonDefaultAppearance(it)) return true;

            if (it.typename === "GroupItem") {
                if (containsNonDefaultAppearanceDescendant(it)) return true;
            }
        }
    } catch (e) {}

    return false;
}

function containsImageLikeArtwork(item) {
    try {
        var t = item.typename;

        if (
            t === "RasterItem" ||
            t === "PlacedItem" ||
            t === "MeshItem" ||
            t === "PluginItem" ||
            t === "SymbolItem"
        ) {
            return true;
        }

        if (t === "GroupItem") {
            for (var i = 0; i < item.pageItems.length; i++) {
                if (containsImageLikeArtwork(item.pageItems[i])) return true;
            }
        }
    } catch (e) {}

    return false;
}

function containsClippedGroupDescendant(group) {
    try {
        for (var i = 0; i < group.pageItems.length; i++) {
            var it = group.pageItems[i];

            if (it.typename === "GroupItem") {
                try {
                    if (it.clipped) return true;
                } catch (e) {}

                if (containsClippedGroupDescendant(it)) return true;
            }
        }
    } catch (e2) {}

    return false;
}

function containsNestedClippedGroup(group) {
    try {
        for (var i = 0; i < group.pageItems.length; i++) {
            var it = group.pageItems[i];

            if (it.typename === "GroupItem") {
                try {
                    if (it !== group && it.clipped) return true;
                } catch (e) {}

                if (containsNestedClippedGroup(it)) return true;
            }
        }
    } catch (e2) {}

    return false;
}


// ============================================================
// CLIPPING MASK HELPERS
// ============================================================

function collectClippedGroupsDeepestFirst(doc) {
    var arr = [];

    try {
        for (var i = 0; i < doc.groupItems.length; i++) {
            var g = doc.groupItems[i];

            try {
                if (g.clipped) {
                    arr.push({
                        item: g,
                        depth: getItemDepth(g)
                    });
                }
            } catch (e) {}
        }
    } catch (e2) {}

    arr.sort(function(a, b) {
        return b.depth - a.depth;
    });

    var result = [];
    for (var j = 0; j < arr.length; j++) {
        result.push(arr[j].item);
    }

    return result;
}

function collectExactMaskObjects(group) {
    var result = [];

    try {
        for (var i = 0; i < group.pageItems.length; i++) {
            var it = group.pageItems[i];

            if (it.typename === "PathItem") {
                try {
                    if (it.clipping) pushUnique(result, it);
                } catch (e) {}

            } else if (it.typename === "CompoundPathItem") {
                var isMaskCompound = false;

                try {
                    for (var p = 0; p < it.pathItems.length; p++) {
                        if (it.pathItems[p].clipping) {
                            isMaskCompound = true;
                            break;
                        }
                    }
                } catch (e2) {}

                if (isMaskCompound) {
                    pushUnique(result, it);
                }
            }
        }
    } catch (e3) {}

    return result;
}


// ============================================================
// CROP / PERIMETER CLEANUP
// ============================================================

function deleteCropPerimeterObjects(doc) {
    var ab = getActiveArtboardBounds(doc);
    if (!ab) return;

    var left   = ab[0];
    var top    = ab[1];
    var right  = ab[2];
    var bottom = ab[3];

    var aw = Math.abs(right - left);
    var ah = Math.abs(top - bottom);

    var edgeTol = Math.max(6, Math.min(aw, ah) * 0.02);

    var candidates = [];

    for (var i = 0; i < doc.pageItems.length; i++) {
        try {
            if (isCandidateVectorItem(doc.pageItems[i])) {
                candidates.push(doc.pageItems[i]);
            }
        } catch (e) {}
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

            var iw = Math.abs(b[2] - b[0]);
            var ih = Math.abs(b[1] - b[3]);

            var nearLeft   = Math.abs(b[0] - left)   <= edgeTol;
            var nearRight  = Math.abs(b[2] - right)  <= edgeTol;
            var nearTop    = Math.abs(b[1] - top)    <= edgeTol;
            var nearBottom = Math.abs(b[3] - bottom) <= edgeTol;

            var spansWidth  = iw >= aw * 0.90;
            var spansHeight = ih >= ah * 0.90;

            var edgeHits =
                (nearLeft ? 1 : 0) +
                (nearRight ? 1 : 0) +
                (nearTop ? 1 : 0) +
                (nearBottom ? 1 : 0);

            var strongPerimeter =
                (spansWidth && (nearTop || nearBottom)) ||
                (spansHeight && (nearLeft || nearRight)) ||
                (iw >= aw * 0.90 && ih >= ah * 0.90 && edgeHits >= 2);

            if (!strongPerimeter) continue;

            it.remove();
            stats.cropPerimetersDeleted++;

        } catch (e) {}
    }
}

function deleteShortCropMarks(doc) {
    var ab = getActiveArtboardBounds(doc);
    if (!ab) return;

    var left   = ab[0];
    var top    = ab[1];
    var right  = ab[2];
    var bottom = ab[3];

    var aw = Math.abs(right - left);
    var ah = Math.abs(top - bottom);

    var edgeTol = Math.max(10, Math.min(aw, ah) * 0.03);
    var maxLen  = Math.max(24, Math.min(aw, ah) * 0.08);

    var paths = [];

    for (var i = 0; i < doc.pathItems.length; i++) {
        paths.push(doc.pathItems[i]);
    }

    for (var j = paths.length - 1; j >= 0; j--) {
        var p = paths[j];

        try {
            if (!isValidPageItem(p)) continue;

            // Clipping ceļu nekad nedzēšam kā crop mark.
            try {
                if (p.clipping) continue;
            } catch (e0) {}

            // Ja path dzīvo clipped/risky struktūrā, neaiztiekam.
            if (hasRiskyAncestor(p)) continue;

            if (p.filled) continue;
            if (!p.stroked) continue;
            if (p.closed) continue;
            if (p.pathPoints.length > 2) continue;

            var b = safeBounds(p);
            if (!b) continue;

            var w = Math.abs(b[2] - b[0]);
            var h = Math.abs(b[1] - b[3]);

            var horizontal = (w > 0 && h <= 1.25 && w <= maxLen);
            var vertical   = (h > 0 && w <= 1.25 && h <= maxLen);

            if (!horizontal && !vertical) continue;

            var cx = (b[0] + b[2]) / 2;
            var cy = (b[1] + b[3]) / 2;

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

        } catch (e) {}
    }
}

function hasRiskyAncestor(item) {
    var p = null;

    try { p = item.parent; } catch (e) { return false; }

    while (p) {
        try {
            if (p.typename === "GroupItem") {
                if (p.clipped) return true;
                if (containsImageLikeArtwork(p)) return true;
                if (hasNonDefaultAppearance(p)) return true;
            }

            if (p.typename === "Document" || p.typename === "Layer") {
                break;
            }

            p = p.parent;

        } catch (e2) {
            break;
        }
    }

    return false;
}


// ============================================================
// GENERIC HELPERS
// ============================================================

function getItemDepth(item) {
    var d = 0;
    var p = null;

    try { p = item.parent; } catch (e) { return d; }

    while (p) {
        try {
            if (p.typename === "GroupItem" || p.typename === "CompoundPathItem") {
                d++;
                p = p.parent;
            } else {
                break;
            }
        } catch (e2) {
            break;
        }
    }

    return d;
}

function pushUnique(arr, obj) {
    for (var i = 0; i < arr.length; i++) {
        if (arr[i] === obj) return;
    }
    arr.push(obj);
}

function isValidPageItem(item) {
    try {
        return !!item.typename;
    } catch (e) {
        return false;
    }
}

function getActiveArtboardBounds(doc) {
    try {
        var idx = doc.artboards.getActiveArtboardIndex();
        return doc.artboards[idx].artboardRect;
    } catch (e) {
        return null;
    }
}

function safeBounds(it) {
    try {
        return it.geometricBounds;
    } catch (e) {
        try {
            return it.visibleBounds;
        } catch (e2) {
            return null;
        }
    }
}

function isCandidateVectorItem(it) {
    try {
        return (
            it.typename === "PathItem" ||
            it.typename === "CompoundPathItem" ||
            it.typename === "GroupItem"
        );
    } catch (e) {
        return false;
    }
}

function containsAnyFill(it) {
    try {
        if (it.typename === "PathItem") {
            return !!it.filled;
        }

        if (it.typename === "CompoundPathItem") {
            for (var i = 0; i < it.pathItems.length; i++) {
                if (it.pathItems[i].filled) return true;
            }
            return false;
        }

        if (it.typename === "GroupItem") {
            for (var j = 0; j < it.pageItems.length; j++) {
                if (containsAnyFill(it.pageItems[j])) return true;
            }
            return false;
        }
    } catch (e) {}

    return false;
}

function isTechnicalLinework(it) {
    try {
        if (it.typename === "PathItem") {
            return !it.filled;
        }

        if (it.typename === "CompoundPathItem") {
            if (it.pathItems.length === 0) return false;

            for (var i = 0; i < it.pathItems.length; i++) {
                if (it.pathItems[i].filled) return false;
            }
            return true;
        }

        if (it.typename === "GroupItem") {
            if (it.clipped) return false;
            if (it.pageItems.length === 0) return false;
            if (containsImageLikeArtwork(it)) return false;

            for (var j = 0; j < it.pageItems.length; j++) {
                var c = it.pageItems[j];

                if (c.typename === "PathItem" && c.filled) {
                    return false;
                }

                if (c.typename === "CompoundPathItem") {
                    for (var k = 0; k < c.pathItems.length; k++) {
                        if (c.pathItems[k].filled) return false;
                    }
                }
            }

            return true;
        }
    } catch (e) {}

    return false;
}


// ============================================================
// 12 MONTH PAGE GUI / TEMPLATE PIPELINE
// ============================================================

var BATCH_APP_NAME = "PDF Deep Cleanup → AI Template Batch";
var ARTWORK_LAYER_NAME = "ARTWORK";

function pathJoin(folder, name) {
    return new File(folder.fsName + "/" + name);
}

function folderJoin(folder, name) {
    return new Folder(folder.fsName + "/" + name);
}

function ensureFolder(folder) {
    if (!folder.exists) {
        if (!folder.create()) {
            throw new Error("Nevar izveidot folderi: " + folder.fsName);
        }
    }
}

function baseNameNoExt(fileObj) {
    var n = fileObj.name;
    var p = n.lastIndexOf(".");
    if (p > 0) n = n.substring(0, p);
    try { return decodeURI(n); } catch (e) { return n; }
}

function displayPath(obj) {
    if (!obj) return "";
    try { return decodeURI(obj.fsName); } catch (e) { return obj.fsName; }
}

function listPdfFiles(pdfFolder) {
    if (!pdfFolder || !pdfFolder.exists) return [];

    var files = pdfFolder.getFiles(function(f) {
        return (f instanceof File) && /\.pdf$/i.test(f.name);
    });

    files.sort(function(a, b) {
        var an = a.name.toLowerCase();
        var bn = b.name.toLowerCase();
        if (an < bn) return -1;
        if (an > bn) return 1;
        return 0;
    });

    return files;
}

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
        if (an < bn) return -1;
        if (an > bn) return 1;
        return 0;
    });

    return files[0];
}

function findOrCreateArtworkLayer(doc) {
    var lyr = null;

    try {
        lyr = doc.layers.getByName(ARTWORK_LAYER_NAME);
    } catch (e) {}

    if (!lyr) {
        lyr = doc.layers.add();
        lyr.name = ARTWORK_LAYER_NAME;
    }

    try { lyr.visible = true; } catch (e2) {}
    try { lyr.locked = false; } catch (e3) {}

    return lyr;
}

function clearArtworkLayer(layer) {
    // Ja MASTER template ARTWORK slānī ir placeholders, batch tos izņem.
    // Static template saturs jāglabā citos slāņos.
    try {
        for (var i = layer.pageItems.length - 1; i >= 0; i--) {
            var it = layer.pageItems[i];
            try {
                if (it.parent === layer) it.remove();
            } catch (e) {}
        }
    } catch (e2) {}

    try {
        for (var j = layer.layers.length - 1; j >= 0; j--) {
            try { layer.layers[j].remove(); } catch (e3) {}
        }
    } catch (e4) {}
}

function duplicateSourceLayersIntoArtwork(sourceDoc, artworkLayer) {
    var count = 0;

    /*
        Illustrator ExtendScript Layer objektam nav uzticamas duplicate()
        metodes. Tāpēc dublējam TOP-LEVEL pageItems no katra source slāņa
        uz template ARTWORK slāni.

        Svarīgi:
        - tiek dublēts viss top-level objekts (GroupItem u.c.) kā viena vienība;
        - bērni grupās netiek dublēti vēlreiz;
        - ejam no apakšas uz augšu + PLACEATBEGINNING, lai pēc iespējas
          saglabātu stacking secību;
        - koordinātas netiek mainītas.
    */

    sourceDoc.activate();

    for (var li = sourceDoc.layers.length - 1; li >= 0; li--) {
        var srcLayer = sourceDoc.layers[li];

        try { srcLayer.locked = false; } catch (e0) {}
        try { srcLayer.visible = true; } catch (e1) {}

        var directItems = [];

        /*
            Layer.pageItems var saturēt arī objektus dziļākās struktūrās.
            Mums vajag tikai tos, kuru tiešais parent ir pats srcLayer.
        */
        try {
            for (var pi = 0; pi < srcLayer.pageItems.length; pi++) {
                var item = srcLayer.pageItems[pi];

                try {
                    if (item.parent === srcLayer) {
                        directItems.push(item);
                    }
                } catch (e2) {}
            }
        } catch (e3) {}

        for (var i = directItems.length - 1; i >= 0; i--) {
            var srcItem = directItems[i];

            try {
                srcItem.duplicate(
                    artworkLayer,
                    ElementPlacement.PLACEATBEGINNING
                );
                count++;

            } catch (e4) {
                var typeName = "";
                var itemName = "";

                try { typeName = srcItem.typename; } catch (e5) {}
                try { itemName = srcItem.name; } catch (e6) {}

                throw new Error(
                    "Neizdevās dublēt objektu no source slāņa '" +
                    srcLayer.name +
                    "' [" + typeName +
                    (itemName ? (": " + itemName) : "") +
                    "]: " + e4
                );
            }
        }

        /*
            Ja source slānim ir sublayers, kopējam arī to tiešos top-level
            pageItems uz to pašu ARTWORK slāni. PDF failiem tas parasti nav
            vajadzīgs, bet batch nedrīkst zaudēt saturu.
        */
        count += duplicateNestedLayerItemsIntoArtwork(srcLayer, artworkLayer);
    }

    if (count === 0) {
        throw new Error("PDF dokumentā nav kopējama top-level artwork satura.");
    }

    return count;
}

function duplicateNestedLayerItemsIntoArtwork(parentLayer, artworkLayer) {
    var count = 0;

    if (!parentLayer) return 0;

    var childLayers = [];

    try {
        for (var l = 0; l < parentLayer.layers.length; l++) {
            childLayers.push(parentLayer.layers[l]);
        }
    } catch (e0) {
        return 0;
    }

    for (var li = childLayers.length - 1; li >= 0; li--) {
        var srcLayer = childLayers[li];

        try { srcLayer.locked = false; } catch (e1) {}
        try { srcLayer.visible = true; } catch (e2) {}

        var directItems = [];

        try {
            for (var pi = 0; pi < srcLayer.pageItems.length; pi++) {
                var item = srcLayer.pageItems[pi];

                try {
                    if (item.parent === srcLayer) {
                        directItems.push(item);
                    }
                } catch (e3) {}
            }
        } catch (e4) {}

        for (var i = directItems.length - 1; i >= 0; i--) {
            try {
                directItems[i].duplicate(
                    artworkLayer,
                    ElementPlacement.PLACEATBEGINNING
                );
                count++;
            } catch (e5) {
                var typeName = "";
                var itemName = "";

                try { typeName = directItems[i].typename; } catch (e6) {}
                try { itemName = directItems[i].name; } catch (e7) {}

                throw new Error(
                    "Neizdevās dublēt objektu no nested source slāņa '" +
                    srcLayer.name +
                    "' [" + typeName +
                    (itemName ? (": " + itemName) : "") +
                    "]: " + e5
                );
            }
        }

        count += duplicateNestedLayerItemsIntoArtwork(
            srcLayer,
            artworkLayer
        );
    }

    return count;
}

function safeClose(doc, saveOption) {
    if (!doc) return;
    try { doc.close(saveOption); } catch (e) {}
}

function removeIfExists(fileObj) {
    if (fileObj && fileObj.exists) {
        try { return fileObj.remove(); } catch (e) {}
    }
    return true;
}

function copyTemplateToOutput(templateFile, outputFile, overwrite) {
    if (outputFile.exists) {
        if (!overwrite) return false;

        if (!outputFile.remove()) {
            throw new Error(
                "Nevar pārrakstīt esošo AI: " + outputFile.fsName
            );
        }
    }

    if (!templateFile.copy(outputFile.fsName)) {
        throw new Error(
            "Neizdevās nokopēt MASTER template uz: " + outputFile.fsName
        );
    }

    return true;
}

function formatTimestamp() {
    var d = new Date();

    function z(n) {
        return (n < 10 ? "0" : "") + n;
    }

    return (
        d.getFullYear() +
        z(d.getMonth() + 1) +
        z(d.getDate()) + "_" +
        z(d.getHours()) +
        z(d.getMinutes()) +
        z(d.getSeconds())
    );
}

function writeLogFile(logFolder, lines) {
    try {
        ensureFolder(logFolder);

        var f = new File(
            logFolder.fsName +
            "/batch_" + formatTimestamp() + ".txt"
        );

        f.encoding = "UTF-8";
        f.lineFeed = "Windows";

        if (f.open("w")) {
            for (var i = 0; i < lines.length; i++) {
                f.writeln(lines[i]);
            }
            f.close();
        }
    } catch (e) {}
}

function makeBatchWindow() {
    var MONTHS = [
        { page: 1,  code: "01_Janvaris",   label: "01  Janvāris",   shortName: "Janvaris" },
        { page: 2,  code: "02_Februaris",  label: "02  Februāris",  shortName: "Februaris" },
        { page: 3,  code: "03_Marts",      label: "03  Marts",      shortName: "Marts" },
        { page: 4,  code: "04_Aprilis",    label: "04  Aprīlis",    shortName: "Aprilis" },
        { page: 5,  code: "05_Maijs",      label: "05  Maijs",      shortName: "Maijs" },
        { page: 6,  code: "06_Junijs",     label: "06  Jūnijs",     shortName: "Junijs" },
        { page: 7,  code: "07_Julijs",     label: "07  Jūlijs",     shortName: "Julijs" },
        { page: 8,  code: "08_Augusts",    label: "08  Augusts",    shortName: "Augusts" },
        { page: 9,  code: "09_Septembris", label: "09  Septembris", shortName: "Septembris" },
        { page: 10, code: "10_Oktobris",   label: "10  Oktobris",   shortName: "Oktobris" },
        { page: 11, code: "11_Novembris",  label: "11  Novembris",  shortName: "Novembris" },
        { page: 12, code: "12_Decembris",  label: "12  Decembris",  shortName: "Decembris" }
    ];

    var w = new Window("dialog", "PDF Deep Cleanup → 12 mēneši → AI Template v6");
    w.orientation = "column";
    w.alignChildren = ["fill", "top"];
    w.spacing = 8;
    w.margins = 14;

    // ========================================================
    // STATE
    // ========================================================
    var state = {
        parentFolder: null,
        jobFolder: null,
        pdfFolder: null,
        templateFolder: null,
        configFolder: null,
        outputFolder: null,
        logFolder: null,
        errorFolder: null,
        templateFile: null,
        pdfFiles: [],
        running: false,
        logLines: []
    };

    // ========================================================
    // PROJECT SETUP
    // ========================================================
    var projectPanel = w.add("panel", undefined, "Projekts");
    projectPanel.orientation = "column";
    projectPanel.alignChildren = ["fill", "top"];
    projectPanel.margins = 10;

    var parentRow = projectPanel.add("group");
    parentRow.orientation = "row";
    parentRow.alignChildren = ["left", "center"];

    var parentLbl = parentRow.add("statictext", undefined, "Parent:");
    parentLbl.preferredSize.width = 85;

    var parentField = parentRow.add("edittext", undefined, "");
    parentField.characters = 57;
    parentField.enabled = false;

    var parentBtn = parentRow.add("button", undefined, "Izvēlēties...");

    var nameRow = projectPanel.add("group");
    nameRow.orientation = "row";
    nameRow.alignChildren = ["left", "center"];

    var nameLbl = nameRow.add("statictext", undefined, "Projekta vārds:");
    nameLbl.preferredSize.width = 85;

    var projectNameField = nameRow.add("edittext", undefined, "");
    projectNameField.characters = 32;

    var projectBtnRow = projectPanel.add("group");
    projectBtnRow.orientation = "row";
    projectBtnRow.alignChildren = ["left", "center"];

    var createProjectBtn = projectBtnRow.add("button", undefined, "IZVEIDOT JAUNU PROJEKTU");
    var openJobBtn = projectBtnRow.add("button", undefined, "ATVĒRT ESOŠU JOB");
    var organizeRootBtn = projectBtnRow.add("button", undefined, "SAKĀRTOT JOB SAKNI");
    organizeRootBtn.enabled = false;

    // ========================================================
    // PATHS
    // ========================================================
    var pathPanel = w.add("panel", undefined, "Darba ceļi");
    pathPanel.orientation = "column";
    pathPanel.alignChildren = ["fill", "top"];
    pathPanel.margins = 10;

    function addPathRow(labelText, withButton) {
        var g = pathPanel.add("group");
        g.orientation = "row";
        g.alignChildren = ["left", "center"];

        var lbl = g.add("statictext", undefined, labelText);
        lbl.preferredSize.width = 85;

        var fld = g.add("edittext", undefined, "");
        fld.characters = 58;
        fld.enabled = false;

        var btn = null;
        if (withButton) {
            btn = g.add("button", undefined, "Mainīt...");
        }

        return { group: g, field: fld, button: btn };
    }

    var jobRow = addPathRow("JOB:", false);
    var pdfRow = addPathRow("PDF:", false);
    var tplRow = addPathRow("Template:", true);
    var cfgRow = addPathRow("CONFIG:", false);
    var outRow = addPathRow("AI OUT:", true);

    // ========================================================
    // PROJECT TOOLS
    // ========================================================
    var toolsPanel = w.add("panel", undefined, "Projekta darbības");
    toolsPanel.orientation = "row";
    toolsPanel.alignChildren = ["left", "center"];
    toolsPanel.margins = 10;

    var addPdfsBtn = toolsPanel.add("button", undefined, "Pievienot PDF");
    var addTemplatesBtn = toolsPanel.add("button", undefined, "Pievienot Templates");
    var saveCfgBtn = toolsPanel.add("button", undefined, "Saglabāt CONFIG");
    addPdfsBtn.enabled = false;
    addTemplatesBtn.enabled = false;
    saveCfgBtn.enabled = false;

    // ========================================================
    // TEMPLATE MODE
    // ========================================================
    var modePanel = w.add("panel", undefined, "Template režīms");
    modePanel.orientation = "column";
    modePanel.alignChildren = ["fill", "top"];
    modePanel.margins = 10;

    var modeRow = modePanel.add("group");
    modeRow.orientation = "row";
    modeRow.alignChildren = ["left", "center"];

    var modeLabel = modeRow.add("statictext", undefined, "Režīms:");
    modeLabel.preferredSize.width = 85;

    var modeDropdown = modeRow.add("dropdownlist", undefined, []);
    modeDropdown.preferredSize.width = 420;
    modeDropdown.add("item", "BASIC — viens template + ARTWORK layer");
    modeDropdown.add("item", "MĒNEŠA TEMPLATE — katram mēnesim savs template");
    modeDropdown.add("item", "MĒNEŠA SLĀNIS — viens template, savs layer katram mēnesim");
    modeDropdown.selection = 0;

    var modeInfo = modePanel.add(
        "statictext",
        undefined,
        "Noklusēti tiek izmantots BASIC režīms."
    );

    // ========================================================
    // PDF + MONTH
    // ========================================================
    var pagePanel = w.add("panel", undefined, "PDF lapa / mēnesis");
    pagePanel.orientation = "column";
    pagePanel.alignChildren = ["fill", "top"];
    pagePanel.margins = 10;

    var pdfSelectGroup = pagePanel.add("group");
    pdfSelectGroup.orientation = "row";
    pdfSelectGroup.alignChildren = ["left", "center"];

    var pdfSelectLabel = pdfSelectGroup.add("statictext", undefined, "PDF:");
    pdfSelectLabel.preferredSize.width = 85;

    var pdfDropdown = pdfSelectGroup.add("dropdownlist", undefined, []);
    pdfDropdown.preferredSize.width = 510;

    var monthSelectGroup = pagePanel.add("group");
    monthSelectGroup.orientation = "row";
    monthSelectGroup.alignChildren = ["left", "center"];

    var monthLabel = monthSelectGroup.add("statictext", undefined, "Mēnesis:");
    monthLabel.preferredSize.width = 85;

    var monthDropdown = monthSelectGroup.add("dropdownlist", undefined, []);
    monthDropdown.preferredSize.width = 245;

    for (var mi = 0; mi < MONTHS.length; mi++) {
        monthDropdown.add(
            "item",
            MONTHS[mi].label + "   (PDF lapa " + MONTHS[mi].page + ")"
        );
    }
    monthDropdown.selection = 0;

    pagePanel.add(
        "statictext",
        undefined,
        "Poga 1: viens mēnesis manuāli. Poga 2: visi atzīmētie mēneši automātiski."
    );

    // ========================================================
    // MONTH CHECKBOXES
    // ========================================================
    var monthCheckPanel = w.add("panel", undefined, "Automātiski apstrādājamie mēneši");
    monthCheckPanel.orientation = "column";
    monthCheckPanel.alignChildren = ["fill", "top"];
    monthCheckPanel.margins = 10;

    var monthChecks = [];
    var gridHolder = monthCheckPanel.add("group");
    gridHolder.orientation = "row";
    gridHolder.alignChildren = ["left", "top"];

    var col1 = gridHolder.add("group"); col1.orientation = "column"; col1.alignChildren = ["left", "top"];
    var col2 = gridHolder.add("group"); col2.orientation = "column"; col2.alignChildren = ["left", "top"];
    var col3 = gridHolder.add("group"); col3.orientation = "column"; col3.alignChildren = ["left", "top"];

    for (var mc = 0; mc < MONTHS.length; mc++) {
        var targetCol = (mc < 4) ? col1 : ((mc < 8) ? col2 : col3);
        var cb = targetCol.add("checkbox", undefined, MONTHS[mc].label);
        cb.value = true;
        monthChecks.push(cb);
    }

    var monthCheckButtons = monthCheckPanel.add("group");
    monthCheckButtons.orientation = "row";
    monthCheckButtons.alignChildren = ["left", "center"];

    var checkAllBtn = monthCheckButtons.add("button", undefined, "Atzīmēt visus");
    var checkNoneBtn = monthCheckButtons.add("button", undefined, "Noņemt visus");
    var checkCurrentBtn = monthCheckButtons.add("button", undefined, "Atzīmēt tikai izvēlēto");

    // ========================================================
    // OPTIONS
    // ========================================================
    var optionsPanel = w.add("panel", undefined, "Opcijas");
    optionsPanel.orientation = "column";
    optionsPanel.alignChildren = ["left", "top"];
    optionsPanel.margins = 10;

    var optionsRow1 = optionsPanel.add("group");
    optionsRow1.orientation = "row";
    optionsRow1.alignChildren = ["left", "center"];

    var overwriteCb = optionsRow1.add("checkbox", undefined, "Pārrakstīt esošo mēneša AI");
    overwriteCb.value = false;

    var clearArtworkCb = optionsRow1.add("checkbox", undefined, 'Iztīrīt mērķa slāni pirms ielikšanas');
    clearArtworkCb.value = true;

    var nextMonthCb = optionsRow1.add("checkbox", undefined, "Pēc manuālā OK pāriet uz nākamo mēnesi");
    nextMonthCb.value = true;

    var optionsRow2 = optionsPanel.add("group");
    optionsRow2.orientation = "row";
    optionsRow2.alignChildren = ["left", "center"];

    var createMonthLayerCb = optionsRow2.add("checkbox", undefined, 'Mēneša slāņa režīmā, ja nav slāņa — izveidot automātiski');
    createMonthLayerCb.value = true;

    // ========================================================
    // STATUS
    // ========================================================
    var statusPanel = w.add("panel", undefined, "Statuss");
    statusPanel.orientation = "column";
    statusPanel.alignChildren = ["fill", "top"];
    statusPanel.margins = 10;

    var statusText = statusPanel.add("statictext", undefined, "Izvēlies parent folderi un izveido projektu.");
    var currentText = statusPanel.add("statictext", undefined, "");
    var progress = statusPanel.add("progressbar", undefined, 0, 12);
    progress.preferredSize = [600, 16];

    // ========================================================
    // LOG
    // ========================================================
    var logPanel = w.add("panel", undefined, "LOG");
    logPanel.orientation = "column";
    logPanel.alignChildren = ["fill", "fill"];
    logPanel.margins = 10;

    var logBox = logPanel.add("edittext", undefined, "", { multiline: true, scrolling: true });
    logBox.preferredSize = [700, 210];

    // ========================================================
    // BUTTONS
    // ========================================================
    var buttons = w.add("group");
    buttons.alignment = "right";

    var refreshBtn = buttons.add("button", undefined, "Pārbaudīt");
    var processBtn = buttons.add("button", undefined, "APSTRĀDĀ MĒNESI");
    var autoBtn = buttons.add("button", undefined, "VISUS ATZĪMĒTOS AUTOMĀTISKI");
    var closeBtn = buttons.add("button", undefined, "Aizvērt");

    processBtn.enabled = false;
    autoBtn.enabled = false;

    // ========================================================
    // HELPERS
    // ========================================================
    function addLog(s) {
        state.logLines.push(s);

        if (logBox.text.length > 0) logBox.text += "\r\n";
        logBox.text += s;

        try {
            logBox.active = true;
            logBox.selection = [logBox.text.length, logBox.text.length];
        } catch (e) {}

        w.update();
    }

    function clearDropdown(dd) {
        try {
            while (dd.items.length > 0) dd.remove(dd.items[0]);
        } catch (e) {}
    }

    function normalizeFiles(sel) {
        if (!sel) return [];
        if (sel instanceof Array) return sel;
        return [sel];
    }

    function fileExt(name) {
        var p = name.lastIndexOf(".");
        if (p < 0) return "";
        return name.substring(p).toLowerCase();
    }

    function splitNameExt(name) {
        var p = name.lastIndexOf(".");
        if (p < 0) return { base: name, ext: "" };
        return { base: name.substring(0, p), ext: name.substring(p) };
    }

    function uniqueFileInFolder(folder, desiredName) {
        var parts = splitNameExt(desiredName);
        var candidate = new File(folder.fsName + "/" + desiredName);
        var n = 2;

        while (candidate.exists) {
            candidate = new File(folder.fsName + "/" + parts.base + "_" + n + parts.ext);
            n++;
        }
        return candidate;
    }

    function copyFilesToFolder(files, targetFolder) {
        ensureFolder(targetFolder);

        var list = normalizeFiles(files);
        var copied = 0;

        for (var i = 0; i < list.length; i++) {
            var src = list[i];
            if (!(src instanceof File)) continue;

            var dst = new File(targetFolder.fsName + "/" + src.name);
            if (dst.exists) {
                dst = uniqueFileInFolder(targetFolder, src.name);
            }

            if (src.copy(dst.fsName)) {
                copied++;
                addLog("KOPĒTS: " + decodeURI(src.name) + " → " + decodeURI(dst.name));
            } else {
                addLog("! Neizdevās kopēt: " + decodeURI(src.name));
            }
        }

        return copied;
    }

    function moveFileToFolder(src, targetFolder) {
        ensureFolder(targetFolder);

        var dst = new File(targetFolder.fsName + "/" + src.name);
        if (dst.exists) {
            dst = uniqueFileInFolder(targetFolder, src.name);
        }

        if (src.copy(dst.fsName)) {
            try { src.remove(); } catch (e) {}
            return dst;
        }

        return null;
    }

    function selectedPdfFile() {
        if (!pdfDropdown.selection) return null;
        var idx = pdfDropdown.selection.index;
        if (idx < 0 || idx >= state.pdfFiles.length) return null;
        return state.pdfFiles[idx];
    }

    function selectedMonth() {
        if (!monthDropdown.selection) return MONTHS[0];
        var idx = monthDropdown.selection.index;
        if (idx < 0 || idx >= MONTHS.length) idx = 0;
        return MONTHS[idx];
    }

    function selectedCheckedMonths() {
        var arr = [];
        for (var i = 0; i < MONTHS.length; i++) {
            if (monthChecks[i].value) arr.push(MONTHS[i]);
        }
        return arr;
    }

    function templateModeKey() {
        if (!modeDropdown.selection) return "basic";
        if (modeDropdown.selection.index === 1) return "monthTemplate";
        if (modeDropdown.selection.index === 2) return "monthLayer";
        return "basic";
    }

    function updateModeInfo() {
        var key = templateModeKey();

        if (key === "basic") {
            modeInfo.text = 'BASIC: visiem mēnešiem viens template, saturs iet slānī "ARTWORK".';
        } else if (key === "monthTemplate") {
            modeInfo.text = "MĒNEŠA TEMPLATE: katram mēnesim meklē savu template failu mapē TEMPLATE.";
        } else {
            modeInfo.text = "MĒNEŠA SLĀNIS: viens template, bet saturs tiek likts mēneša slānī.";
        }
    }

    function outputFileFor(pdfFile, month) {
        return new File(
            state.outputFolder.fsName +
            "/" +
            baseNameNoExt(pdfFile) +
            "__" +
            month.code +
            ".ai"
        );
    }

    function completedCount(pdfFile) {
        if (!pdfFile || !state.outputFolder || !state.outputFolder.exists) return 0;

        var count = 0;
        for (var i = 0; i < MONTHS.length; i++) {
            if (outputFileFor(pdfFile, MONTHS[i]).exists) count++;
        }
        return count;
    }

    function jsonEscape(s) {
        if (s === null || s === undefined) return "";
        s = String(s);
        s = s.replace(/\\/g, "\\\\");
        s = s.replace(/"/g, '\\"');
        s = s.replace(/\r/g, "\\r");
        s = s.replace(/\n/g, "\\n");
        return s;
    }

    function createProjectStructure(jobFolder) {
        ensureFolder(jobFolder);
        ensureFolder(folderJoin(jobFolder, "PDF"));
        ensureFolder(folderJoin(jobFolder, "TEMPLATE"));
        ensureFolder(folderJoin(jobFolder, "CONFIG"));
        ensureFolder(folderJoin(jobFolder, "AI_OUT"));
        ensureFolder(folderJoin(jobFolder, "LOG"));
        ensureFolder(folderJoin(jobFolder, "ERROR"));
    }

    function applyJobFolder(jobFolder) {
        state.jobFolder = jobFolder;
        state.parentFolder = jobFolder.parent;
        state.pdfFolder = folderJoin(jobFolder, "PDF");
        state.templateFolder = folderJoin(jobFolder, "TEMPLATE");
        state.configFolder = folderJoin(jobFolder, "CONFIG");
        state.outputFolder = folderJoin(jobFolder, "AI_OUT");
        state.logFolder = folderJoin(jobFolder, "LOG");
        state.errorFolder = folderJoin(jobFolder, "ERROR");

        createProjectStructure(jobFolder);

        try { parentField.text = displayPath(state.parentFolder); } catch (e1) {}
        try { projectNameField.text = decodeURI(jobFolder.name); } catch (e2) {}

        if (!state.templateFile || !state.templateFile.exists) {
            state.templateFile = detectTemplate(state.templateFolder);
        }

        organizeRootBtn.enabled = true;
        addPdfsBtn.enabled = true;
        addTemplatesBtn.enabled = true;
        saveCfgBtn.enabled = true;
    }

    function writeProjectConfig() {
        if (!state.configFolder || !state.jobFolder) return;

        try {
            ensureFolder(state.configFolder);

            var selectedPdf = selectedPdfFile();
            var checked = selectedCheckedMonths();
            var checkedNames = [];
            for (var i = 0; i < checked.length; i++) checkedNames.push('"' + jsonEscape(checked[i].code) + '"');

            var lines = [];
            lines.push("{");
            lines.push('  "job_name": "' + jsonEscape(state.jobFolder.name) + '",');
            lines.push('  "job_path": "' + jsonEscape(displayPath(state.jobFolder)) + '",');
            lines.push('  "pdf_folder": "' + jsonEscape(displayPath(state.pdfFolder)) + '",');
            lines.push('  "template_folder": "' + jsonEscape(displayPath(state.templateFolder)) + '",');
            lines.push('  "config_folder": "' + jsonEscape(displayPath(state.configFolder)) + '",');
            lines.push('  "ai_out_folder": "' + jsonEscape(displayPath(state.outputFolder)) + '",');
            lines.push('  "log_folder": "' + jsonEscape(displayPath(state.logFolder)) + '",');
            lines.push('  "error_folder": "' + jsonEscape(displayPath(state.errorFolder)) + '",');
            lines.push('  "template_mode": "' + jsonEscape(templateModeKey()) + '",');
            lines.push('  "base_template": "' + jsonEscape(state.templateFile ? state.templateFile.name : "") + '",');
            lines.push('  "selected_pdf": "' + jsonEscape(selectedPdf ? selectedPdf.name : "") + '",');
            lines.push('  "checked_months": [' + checkedNames.join(", ") + '],');
            lines.push('  "overwrite": ' + (overwriteCb.value ? "true" : "false") + ',');
            lines.push('  "clear_target_layer": ' + (clearArtworkCb.value ? "true" : "false") + ',');
            lines.push('  "auto_next_month": ' + (nextMonthCb.value ? "true" : "false") + ',');
            lines.push('  "auto_create_month_layer": ' + (createMonthLayerCb.value ? "true" : "false"));
            lines.push("}");

            var f = new File(state.configFolder.fsName + "/project_info.json");
            f.encoding = "UTF-8";
            f.lineFeed = "Windows";
            if (f.open("w")) {
                for (var li = 0; li < lines.length; li++) f.writeln(lines[li]);
                f.close();
            }

            return true;
        } catch (e) {
            addLog("! CONFIG saglabāšana neizdevās: " + e);
            return false;
        }
    }

    function updateProgress() {
        var pdfFile = selectedPdfFile();
        var done = completedCount(pdfFile);
        var checkedCount = selectedCheckedMonths().length;
        progress.value = done;

        if (pdfFile) {
            statusText.text =
                "PDF: " + decodeURI(pdfFile.name) +
                "    |    Gatavi mēneši: " + done + " / 12" +
                "    |    Atzīmēti auto režīmam: " + checkedCount +
                "    |    Template: " +
                ((state.templateFile && state.templateFile.exists) ? "OK" : "NAV ATRASTS");
        } else if (state.jobFolder) {
            statusText.text =
                "JOB: " + decodeURI(state.jobFolder.name) +
                "    |    PDF faili: " + state.pdfFiles.length +
                "    |    Template: " +
                ((state.templateFile && state.templateFile.exists) ? "OK" : "NAV ATRASTS");
        }
    }

    function updateFields() {
        parentField.text = state.parentFolder ? displayPath(state.parentFolder) : "";
        jobRow.field.text = state.jobFolder ? displayPath(state.jobFolder) : "";
        pdfRow.field.text = state.pdfFolder ? displayPath(state.pdfFolder) : "";
        tplRow.field.text = state.templateFile ? displayPath(state.templateFile) : "";
        cfgRow.field.text = state.configFolder ? displayPath(state.configFolder) : "";
        outRow.field.text = state.outputFolder ? displayPath(state.outputFolder) : "";
    }

    function refreshPdfDropdown(oldName) {
        clearDropdown(pdfDropdown);

        for (var i = 0; i < state.pdfFiles.length; i++) {
            pdfDropdown.add("item", decodeURI(state.pdfFiles[i].name));
        }

        if (state.pdfFiles.length === 0) {
            pdfDropdown.selection = null;
            return;
        }

        var selectIndex = 0;
        if (oldName) {
            for (var j = 0; j < state.pdfFiles.length; j++) {
                if (state.pdfFiles[j].name === oldName) {
                    selectIndex = j;
                    break;
                }
            }
        }
        pdfDropdown.selection = selectIndex;
    }

    function canProcess() {
        return (
            !state.running &&
            state.pdfFiles.length > 0 &&
            state.templateFile &&
            state.templateFile.exists
        );
    }

    function scanJob() {
        if (!state.jobFolder) {
            processBtn.enabled = false;
            autoBtn.enabled = false;
            return;
        }

        var oldPdf = selectedPdfFile();
        var oldPdfName = oldPdf ? oldPdf.name : null;

        applyJobFolder(state.jobFolder);

        if (!state.templateFile || !state.templateFile.exists) {
            state.templateFile = detectTemplate(state.templateFolder);
        }

        state.pdfFiles = listPdfFiles(state.pdfFolder);

        refreshPdfDropdown(oldPdfName);
        updateFields();
        updateModeInfo();
        updateProgress();

        processBtn.enabled = canProcess();
        autoBtn.enabled = canProcess();

        addLog("");
        addLog("PĀRBAUDE");
        addLog("JOB: " + displayPath(state.jobFolder));
        addLog("PDF faili: " + state.pdfFiles.length);
        addLog("Template režīms: " + templateModeKey());

        if (state.templateFile && state.templateFile.exists) {
            addLog("Template (basic bāze): " + state.templateFile.name);
        } else {
            addLog("! Template nav atrasts folderī TEMPLATE.");
        }

        addLog("AI OUT: " + displayPath(state.outputFolder));
        writeProjectConfig();
    }

    function setControlsEnabled(enabled) {
        parentBtn.enabled = enabled;
        createProjectBtn.enabled = enabled;
        openJobBtn.enabled = enabled;
        organizeRootBtn.enabled = enabled && !!state.jobFolder;

        tplRow.button.enabled = enabled && !!state.jobFolder;
        outRow.button.enabled = enabled && !!state.jobFolder;

        addPdfsBtn.enabled = enabled && !!state.jobFolder;
        addTemplatesBtn.enabled = enabled && !!state.jobFolder;
        saveCfgBtn.enabled = enabled && !!state.jobFolder;

        refreshBtn.enabled = enabled;
        closeBtn.enabled = enabled;
        pdfDropdown.enabled = enabled;
        monthDropdown.enabled = enabled;
        modeDropdown.enabled = enabled;
        overwriteCb.enabled = enabled;
        clearArtworkCb.enabled = enabled;
        nextMonthCb.enabled = enabled;
        createMonthLayerCb.enabled = enabled;
        checkAllBtn.enabled = enabled;
        checkNoneBtn.enabled = enabled;
        checkCurrentBtn.enabled = enabled;

        for (var i = 0; i < monthChecks.length; i++) monthChecks[i].enabled = enabled;

        processBtn.enabled = enabled && canProcess();
        autoBtn.enabled = enabled && canProcess();
    }

    function findLayerRecursive(layerContainer, nameList) {
        var i, j, lyr, inner;

        try {
            for (i = 0; i < layerContainer.layers.length; i++) {
                lyr = layerContainer.layers[i];

                for (j = 0; j < nameList.length; j++) {
                    if (lyr.name === nameList[j]) return lyr;
                }

                inner = findLayerRecursive(lyr, nameList);
                if (inner) return inner;
            }
        } catch (e) {}

        return null;
    }

    function monthLayerNameCandidates(month) {
        var cleanLabel = month.label.replace(/\s+/g, " ");
        var monthOnly = cleanLabel.replace(/^\d+\s+/, "");

        return [
            month.code,
            month.shortName,
            monthOnly,
            month.page + "_" + month.shortName,
            (month.page < 10 ? "0" + month.page : "" + month.page) + "_" + month.shortName,
            "ARTWORK_" + month.shortName,
            "ARTWORK_" + month.code
        ];
    }

    function resolveTemplateForMonth(month) {
        var key = templateModeKey();

        if (key === "basic" || key === "monthLayer") {
            if (!state.templateFile || !state.templateFile.exists) {
                throw new Error("Bāzes template nav atrasts.");
            }
            return state.templateFile;
        }

        var candidates = [];
        var directMonthFolder = folderJoin(state.templateFolder, month.code);
        var monthSubFolder = folderJoin(folderJoin(state.templateFolder, "MONTHS"), month.code);

        if (directMonthFolder.exists) {
            var t1 = detectTemplate(directMonthFolder);
            if (t1) return t1;
        }

        if (monthSubFolder.exists) {
            var t2 = detectTemplate(monthSubFolder);
            if (t2) return t2;
        }

        try {
            candidates = state.templateFolder.getFiles(function(f) {
                if (!(f instanceof File)) return false;
                if (!/\.(ai|ait)$/i.test(f.name)) return false;

                var n = f.name.toLowerCase();
                var c1 = month.code.toLowerCase();
                var c2 = month.shortName.toLowerCase();

                return (n.indexOf(c1) >= 0 || n.indexOf(c2) >= 0);
            });
        } catch (e) {
            candidates = [];
        }

        if (candidates.length > 0) {
            candidates.sort(function(a, b) {
                var sa = templateScore(a);
                var sb = templateScore(b);
                if (sa !== sb) return sb - sa;
                return a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1;
            });
            return candidates[0];
        }

        throw new Error(
            "Mēneša template nav atrasts: " + month.code +
            ". Meklēju TEMPLATE\\" + month.code +
            " vai failu ar šo mēneša nosaukumu."
        );
    }

    function resolveTargetLayer(destDoc, month) {
        var key = templateModeKey();

        if (key === "basic" || key === "monthTemplate") {
            return findOrCreateArtworkLayer(destDoc);
        }

        var names = monthLayerNameCandidates(month);
        var lyr = findLayerRecursive(destDoc, names);

        if (!lyr && createMonthLayerCb.value) {
            lyr = destDoc.layers.add();
            lyr.name = month.code;
        }

        if (!lyr) {
            throw new Error("Mēneša slānis nav atrasts template dokumentā: " + names.join(", "));
        }

        try { lyr.visible = true; } catch (e1) {}
        try { lyr.locked = false; } catch (e2) {}
        return lyr;
    }

    function organizeJobRoot() {
        if (!state.jobFolder) {
            alert("Vispirms izvēlies vai izveido JOB projektu.");
            return;
        }

        var files = state.jobFolder.getFiles(function(f) {
            return (f instanceof File);
        });

        var moved = 0;
        for (var i = 0; i < files.length; i++) {
            var f = files[i];
            var ext = fileExt(f.name);
            var target = null;

            if (ext === ".pdf") target = state.pdfFolder;
            else if (ext === ".ai" || ext === ".ait") target = state.templateFolder;
            else if (ext === ".json" || ext === ".csv") target = state.configFolder;

            if (target) {
                var movedFile = moveFileToFolder(f, target);
                if (movedFile) {
                    moved++;
                    addLog("PĀRVIETOTS: " + decodeURI(f.name) + " → " + displayPath(target));
                }
            }
        }

        addLog("JOB saknes sakārtošana pabeigta. Pārvietoti faili: " + moved);
        scanJob();
    }

    function executeMonth(pdfFile, month, isAutoMode, advanceSelection) {
        var outputFile = outputFileFor(pdfFile, month);

        if (outputFile.exists && !overwriteCb.value) {
            addLog("SKIP  " + month.label + " | " + decodeURI(outputFile.name) + " jau eksistē.");
            currentText.text = month.label + " netika pārrakstīts.";
            updateProgress();

            return { status: "skip", month: month, outputFile: outputFile, message: "AI jau eksistē" };
        }

        var sourceDoc = null;
        var destDoc = null;
        var templateCopied = false;
        var oldInteraction = null;
        var oldPageToOpen = 1;
        var templateForThisMonth = null;

        currentText.text = "Apstrādā: " + month.label + " | PDF lapa " + month.page;

        addLog("");
        addLog("----------------------------------------");
        addLog("START " + month.label + " | PDF lapa " + month.page);

        try {
            templateForThisMonth = resolveTemplateForMonth(month);
            addLog("Template šim mēnesim: " + decodeURI(templateForThisMonth.name));

            var pdfOptions = app.preferences.PDFFileOptions;
            try { oldPageToOpen = pdfOptions.pageToOpen; } catch (eOldPage) {}
            pdfOptions.pageToOpen = month.page;

            try {
                oldInteraction = app.userInteractionLevel;
                app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;
            } catch (eUI1) {}

            sourceDoc = app.open(pdfFile);

            try {
                if (oldInteraction !== null) app.userInteractionLevel = oldInteraction;
                else app.userInteractionLevel = UserInteractionLevel.DISPLAYALERTS;
            } catch (eUI2) {}

            sourceDoc.activate();

            var fileStats = runPdfDeepCleanup(sourceDoc);

            templateCopied = copyTemplateToOutput(templateForThisMonth, outputFile, overwriteCb.value);
            if (!templateCopied) throw new Error("Output AI jau eksistē.");

            destDoc = app.open(outputFile);
            destDoc.activate();

            var targetLayer = resolveTargetLayer(destDoc, month);
            if (clearArtworkCb.value) clearArtworkLayer(targetLayer);

            var copiedObjects = duplicateSourceLayersIntoArtwork(sourceDoc, targetLayer);

            destDoc.activate();
            destDoc.save();

            safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
            sourceDoc = null;

            safeClose(destDoc, SaveOptions.SAVECHANGES);
            destDoc = null;

            addLog(
                "OK    " +
                month.label +
                " | page=" + month.page +
                " → " +
                decodeURI(outputFile.name) +
                " | mode=" + templateModeKey() +
                " | objects=" + copiedObjects +
                " | ungroup=" + fileStats.safeGroupsUngrouped +
                " | masks=" + fileStats.vectorMasksReleased +
                " | crop=" +
                (fileStats.cropPerimetersDeleted + fileStats.shortCropMarksDeleted)
            );

            currentText.text = "GATAVS: " + month.label + " → " + decodeURI(outputFile.name);

            if (advanceSelection && monthDropdown.selection && monthDropdown.selection.index < MONTHS.length - 1) {
                monthDropdown.selection = monthDropdown.selection.index + 1;
            }

            try { app.preferences.PDFFileOptions.pageToOpen = oldPageToOpen; } catch (eRestorePage1) {}
            try { $.gc(); } catch (eGc1) {}

            updateProgress();
            writeLogFile(state.logFolder, state.logLines);
            writeProjectConfig();
            w.update();

            return { status: "ok", month: month, outputFile: outputFile, message: "OK" };

        } catch (err) {
            try {
                if (oldInteraction !== null) app.userInteractionLevel = oldInteraction;
                else app.userInteractionLevel = UserInteractionLevel.DISPLAYALERTS;
            } catch (eUI3) {}

            safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
            sourceDoc = null;

            safeClose(destDoc, SaveOptions.DONOTSAVECHANGES);
            destDoc = null;

            if (templateCopied && outputFile.exists) removeIfExists(outputFile);

            addLog("ERROR " + month.label + " | PDF lapa " + month.page + " | " + err);
            currentText.text = "KĻŪDA: " + month.label;

            try { app.preferences.PDFFileOptions.pageToOpen = oldPageToOpen; } catch (eRestorePage2) {}
            try { $.gc(); } catch (eGc2) {}

            updateProgress();
            writeLogFile(state.logFolder, state.logLines);
            writeProjectConfig();
            w.update();

            if (!isAutoMode) {
                alert("Kļūda apstrādājot " + month.label + " (PDF lapa " + month.page + "):\n\n" + err);
            }

            return { status: "error", month: month, outputFile: outputFile, message: String(err) };
        }
    }

    function processSelectedMonth() {
        if (state.running) return;

        var pdfFile = selectedPdfFile();
        var month = selectedMonth();

        if (!pdfFile) {
            alert("Nav izvēlēts PDF fails.");
            return;
        }

        if (!state.templateFile || !state.templateFile.exists) {
            alert("Template nav atrasts.");
            return;
        }

        state.running = true;
        setControlsEnabled(false);
        executeMonth(pdfFile, month, false, nextMonthCb.value);
        state.running = false;
        setControlsEnabled(true);
        w.update();
    }

    function processCheckedMonths() {
        if (state.running) return;

        var pdfFile = selectedPdfFile();
        var monthsToDo = selectedCheckedMonths();

        if (!pdfFile) {
            alert("Nav izvēlēts PDF fails.");
            return;
        }

        if (!state.templateFile || !state.templateFile.exists) {
            alert("Template nav atrasts.");
            return;
        }

        if (monthsToDo.length === 0) {
            alert("Nav atzīmēts neviens mēnesis.");
            return;
        }

        state.running = true;
        setControlsEnabled(false);

        var okCount = 0, skipCount = 0, errorCount = 0;

        addLog("");
        addLog("========================================");
        addLog("AUTO ATZĪMĒTIE MĒNEŠI START");
        addLog("PDF: " + decodeURI(pdfFile.name));
        addLog("Template režīms: " + templateModeKey());
        addLog("Mēneši: " + monthsToDo.length);
        addLog("========================================");

        for (var i = 0; i < monthsToDo.length; i++) {
            var month = monthsToDo[i];
            monthDropdown.selection = month.page - 1;
            w.update();

            var res = executeMonth(pdfFile, month, true, false);

            if (res.status === "ok") okCount++;
            else if (res.status === "skip") skipCount++;
            else if (res.status === "error") errorCount++;
        }

        addLog("");
        addLog("========================================");
        addLog("AUTO ATZĪMĒTIE MĒNEŠI DONE");
        addLog("OK: " + okCount);
        addLog("SKIP: " + skipCount);
        addLog("ERROR: " + errorCount);
        addLog("========================================");

        writeLogFile(state.logFolder, state.logLines);
        writeProjectConfig();

        currentText.text = "AUTO PABEIGTS | OK: " + okCount + " | SKIP: " + skipCount + " | ERROR: " + errorCount;

        state.running = false;
        setControlsEnabled(true);
        updateProgress();
        w.update();

        alert(
            "Automātiskā atzīmēto mēnešu apstrāde pabeigta.\n\n" +
            "OK: " + okCount + "\n" +
            "SKIP: " + skipCount + "\n" +
            "ERROR: " + errorCount
        );
    }

    // ========================================================
    // EVENTS
    // ========================================================
    parentBtn.onClick = function() {
        var f = Folder.selectDialog("Izvēlies parent folderi jaunam projektam");
        if (!f) return;
        state.parentFolder = f;
        parentField.text = displayPath(f);
    };

    createProjectBtn.onClick = function() {
        var projectName = projectNameField.text.replace(/^\s+|\s+$/g, "");
        if (!projectName) {
            alert("Ieraksti projekta vārdu.");
            return;
        }

        if (!state.parentFolder) {
            alert("Vispirms izvēlies parent folderi.");
            return;
        }

        var jobFolder = folderJoin(state.parentFolder, projectName);
        if (!jobFolder.exists) {
            ensureFolder(jobFolder);
        }

        applyJobFolder(jobFolder);
        state.templateFile = detectTemplate(state.templateFolder);
        addLog("IZVEIDOTS/ATVĒRTS PROJEKTS: " + displayPath(jobFolder));
        scanJob();
    };

    openJobBtn.onClick = function() {
        var f = Folder.selectDialog("Izvēlies esošu JOB folderi");
        if (!f) return;

        applyJobFolder(f);
        state.templateFile = detectTemplate(state.templateFolder);
        state.logLines = [];
        logBox.text = "";
        addLog("ATVĒRTS JOB: " + displayPath(f));
        scanJob();
    };

    organizeRootBtn.onClick = function() {
        organizeJobRoot();
    };

    addPdfsBtn.onClick = function() {
        if (!state.jobFolder) {
            alert("Vispirms izvēlies vai izveido JOB projektu.");
            return;
        }

        var files = File.openDialog("Izvēlies vienu vai vairākus PDF", "PDF:*.pdf", true);
        if (!files) return;

        var copied = copyFilesToFolder(files, state.pdfFolder);
        addLog("PDF kopēšana pabeigta. Pievienoti faili: " + copied);
        scanJob();
    };

    addTemplatesBtn.onClick = function() {
        if (!state.jobFolder) {
            alert("Vispirms izvēlies vai izveido JOB projektu.");
            return;
        }

        var files = File.openDialog("Izvēlies vienu vai vairākus template failus", "Illustrator:*.ai;*.ait", true);
        if (!files) return;

        var copied = copyFilesToFolder(files, state.templateFolder);
        addLog("Template kopēšana pabeigta. Pievienoti faili: " + copied);
        state.templateFile = detectTemplate(state.templateFolder);
        scanJob();
    };

    saveCfgBtn.onClick = function() {
        if (!state.jobFolder) return;
        if (writeProjectConfig()) {
            addLog("CONFIG saglabāts: " + displayPath(new File(state.configFolder.fsName + "/project_info.json")));
        }
    };

    tplRow.button.onClick = function() {
        if (!state.jobFolder) {
            alert("Vispirms izvēlies vai izveido JOB projektu.");
            return;
        }

        var f = File.openDialog("Izvēlies Illustrator MASTER template", "Illustrator:*.ai;*.ait", false);
        if (!f) return;

        var copied = copyFilesToFolder([f], state.templateFolder);
        if (copied > 0) {
            state.templateFile = detectTemplate(state.templateFolder);
        } else {
            state.templateFile = f;
        }

        updateFields();
        scanJob();
    };

    outRow.button.onClick = function() {
        if (!state.jobFolder) {
            alert("Vispirms izvēlies vai izveido JOB projektu.");
            return;
        }

        var f = Folder.selectDialog("Izvēlies AI output folderi");
        if (!f) return;

        state.outputFolder = f;
        ensureFolder(state.outputFolder);

        updateFields();
        scanJob();
    };

    pdfDropdown.onChange = function() { updateProgress(); };

    monthDropdown.onChange = function() {
        var month = selectedMonth();
        var pdfFile = selectedPdfFile();

        if (pdfFile) {
            var out = outputFileFor(pdfFile, month);
            currentText.text = month.label + " | PDF lapa " + month.page + " | → " + decodeURI(out.name);
        }
    };

    modeDropdown.onChange = function() {
        updateModeInfo();
        updateProgress();
        writeProjectConfig();
    };

    refreshBtn.onClick = function() { scanJob(); };
    processBtn.onClick = function() { processSelectedMonth(); };
    autoBtn.onClick = function() { processCheckedMonths(); };

    checkAllBtn.onClick = function() {
        for (var i = 0; i < monthChecks.length; i++) monthChecks[i].value = true;
        updateProgress();
        writeProjectConfig();
    };

    checkNoneBtn.onClick = function() {
        for (var i = 0; i < monthChecks.length; i++) monthChecks[i].value = false;
        updateProgress();
        writeProjectConfig();
    };

    checkCurrentBtn.onClick = function() {
        var idx = monthDropdown.selection ? monthDropdown.selection.index : 0;
        for (var i = 0; i < monthChecks.length; i++) monthChecks[i].value = (i === idx);
        updateProgress();
        writeProjectConfig();
    };

    for (var cbi = 0; cbi < monthChecks.length; cbi++) {
        monthChecks[cbi].onClick = function() {
            updateProgress();
            writeProjectConfig();
        };
    }

    closeBtn.onClick = function() {
        if (!state.running) {
            writeLogFile(state.logFolder, state.logLines);
            writeProjectConfig();
            w.close();
        }
    };

    updateModeInfo();
    updateFields();
    w.center();
    w.show();
}


// ============================================================
// START GUI
// ============================================================
makeBatchWindow();
