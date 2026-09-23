#target illustrator

/*
    PDF Deep Cleanup AI 2026 — v6 APPEARANCE SAFE
    ==========================================================
    Mērķis:
      - atslēgt objektus;
      - atārdīt tikai DROŠAS grupas;
      - release tikai DROŠAS vector-only clipping maskas;
      - noņemt crop/perimeter marks;
      - NEMAINĪT PDF vizuālo izskatu.

    Kāpēc v5 dažos PDF varēja mainīt izskatu:
      parasta GroupItem var saturēt rasteri, clipping grupu,
      transparency/blend/opacity struktūru. Ungroup šādai grupai
      var mainīt kompozīciju pat tad, ja pati grupa nav "clipped".

    v6 princips:
      SKIP jebkuru grupu, kas ir vizuāli riskanta.
*/

if (app.documents.length === 0) {
    alert("Nav atvērta dokumenta!");
    exit();
}

var doc = app.activeDocument;

// ------------------------------------------------------------
// SETTINGS
// ------------------------------------------------------------

// Ieteicams TRUE.
var PRESERVE_IMAGE_STRUCTURES = true;

// Ieteicams TRUE.
var PRESERVE_TRANSPARENCY_STRUCTURES = true;

// Vector-only plain clipping maskas drīkst release.
var RELEASE_SAFE_VECTOR_MASKS = true;

// Crop marks dzēšana.
var DELETE_CROP_MARKS = true;

// ------------------------------------------------------------

var stats = {
    safeGroupsUngrouped: 0,
    riskyGroupsPreserved: 0,
    vectorMasksReleased: 0,
    riskyMasksPreserved: 0,
    maskPathsDeleted: 0,
    cropPerimetersDeleted: 0,
    shortCropMarksDeleted: 0
};

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

alert(
    "PDF Deep Cleanup v6 APPEARANCE SAFE pabeigts.\n\n" +
    "Safe groups ungrouped: " + stats.safeGroupsUngrouped + "\n" +
    "Risky groups preserved: " + stats.riskyGroupsPreserved + "\n" +
    "Safe vector masks released: " + stats.vectorMasksReleased + "\n" +
    "Risky masks preserved: " + stats.riskyMasksPreserved + "\n" +
    "Released mask paths deleted: " + stats.maskPathsDeleted + "\n" +
    "Crop/perimeter objects deleted: " + stats.cropPerimetersDeleted + "\n" +
    "Short crop marks deleted: " + stats.shortCropMarksDeleted
);


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
