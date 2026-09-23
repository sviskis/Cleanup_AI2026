#target illustrator

// ========================================================
// PDF Deep Cleanup v6 APPEARANCE SAFE + AI Template Batch v4 PAGE PICKER
// ========================================================

var BATCH_APP_NAME = "PDF Deep Cleanup → AI Template Batch v4 PAGE PICKER";
var ARTWORK_LAYER_NAME = "ARTWORK";

// ====================== HELPERS ======================
function pathJoin(folder, name) { return new File(folder.fsName + "/" + name); }
function folderJoin(folder, name) { return new Folder(folder.fsName + "/" + name); }
function ensureFolder(folder) {
    if (!folder.exists) { if (!folder.create()) throw new Error("Nevar izveidot folderi: " + folder.fsName); }
}
function baseNameNoExt(fileObj) {
    var n = fileObj.name; var p = n.lastIndexOf(".");
    if (p > 0) n = n.substring(0, p);
    try { return decodeURI(n); } catch (e) { return n; }
}
function displayPath(obj) {
    if (!obj) return "";
    try { return decodeURI(obj.fsName); } catch (e) { return obj.fsName; }
}
function sortPdfFiles(files) {
    files.sort(function(a, b) {
        var an = a.fsName.toLowerCase();
        var bn = b.fsName.toLowerCase();
        return an < bn ? -1 : (an > bn ? 1 : 0);
    });
    return files;
}
function listPdfFiles(pdfFolder) {
    if (!pdfFolder || !pdfFolder.exists) return [];
    var files = pdfFolder.getFiles(function(f) {
        return (f instanceof File) && /\.pdf$/i.test(f.name);
    });
    return sortPdfFiles(files);
}
function isExcludedPdfScanFolder(folderObj) {
    if (!folderObj) return true;
    var n = ""; try { n = decodeURI(folderObj.name).toLowerCase(); } catch(e) { n = folderObj.name.toLowerCase(); }
    return (n === "template" || n === "ai_out" || n === "log" || n === "error" || n === "errors" || n === "archive" || n.indexOf(".git") === 0);
}
function listPdfFilesRecursive(rootFolder, maxDepth) {
    var result = [];
    if (!rootFolder || !rootFolder.exists) return result;
    if (maxDepth === undefined || maxDepth === null) maxDepth = 8;
    function walk(folderObj, depth) {
        if (!folderObj || !folderObj.exists) return;
        if (depth > maxDepth) return;
        var entries = [];
        try { entries = folderObj.getFiles(); } catch (e0) { return; }
        for (var i = 0; i < entries.length; i++) {
            var entry = entries[i];
            if (entry instanceof File) {
                try { if (/\.pdf$/i.test(entry.name)) result.push(entry); } catch (e1) {}
            } else if (entry instanceof Folder) {
                if (isExcludedPdfScanFolder(entry)) continue;
                walk(entry, depth + 1);
            }
        }
    }
    walk(rootFolder, 0);
    return sortPdfFiles(result);
}
function resolvePdfQueue(jobFolder, preferredPdfFolder, manualPdfFolder) {
    if (manualPdfFolder && manualPdfFolder.exists) {
        return { root: manualPdfFolder, files: listPdfFilesRecursive(manualPdfFolder, 8), mode: "MANUAL" };
    }
    if (preferredPdfFolder && preferredPdfFolder.exists) {
        var preferredFiles = listPdfFilesRecursive(preferredPdfFolder, 8);
        if (preferredFiles.length > 0) {
            return { root: preferredPdfFolder, files: preferredFiles, mode: "JOB\\PDF" };
        }
    }
    return { root: jobFolder, files: listPdfFilesRecursive(jobFolder, 8), mode: "AUTO RECURSIVE" };
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
        return an < bn ? -1 : (an > bn ? 1 : 0);
    });
    return files[0];
}
function findOrCreateArtworkLayer(doc) {
    var lyr = null;
    try { lyr = doc.layers.getByName(ARTWORK_LAYER_NAME); } catch(e) {}
    if (!lyr) {
        lyr = doc.layers.add();
        lyr.name = ARTWORK_LAYER_NAME;
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
function safeClose(doc, saveOption) {
    if (!doc) return;
    try { doc.close(saveOption); } catch(e) {}
}
function removeIfExists(fileObj) {
    if (fileObj && fileObj.exists) try { return fileObj.remove(); } catch(e) {}
    return true;
}
function copyTemplateToOutput(templateFile, outputFile, overwrite) {
    if (outputFile.exists) {
        if (!overwrite) return false;
        if (!outputFile.remove()) throw new Error("Nevar pārrakstīt esošo AI: " + outputFile.fsName);
    }
    if (!templateFile.copy(outputFile.fsName)) throw new Error("Neizdevās nokopēt MASTER template uz: " + outputFile.fsName);
    return true;
}
function formatTimestamp() {
    var d = new Date();
    function z(n) { return n < 10 ? "0" + n : n; }
    return d.getFullYear() + z(d.getMonth()+1) + z(d.getDate()) + "_" + z(d.getHours()) + z(d.getMinutes()) + z(d.getSeconds());
}
function writeLogFile(logFolder, lines) {
    ensureFolder(logFolder);
    var f = new File(logFolder.fsName + "/batch_" + formatTimestamp() + ".txt");
    f.encoding = "UTF-8";
    f.lineFeed = "Windows";
    if (f.open("w")) {
        for (var i = 0; i < lines.length; i++) f.writeln(lines[i]);
        f.close();
    }
}

// ====================== PDF PAGE COUNT ======================
function safeFileSignature(fileObj) {
    var len = 0, mod = "";
    try { len = fileObj.length; } catch(e0) {}
    try { mod = String(fileObj.modified); } catch(e1) {}
    return String(len) + "|" + mod;
}
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
        safeClose(probeDoc, SaveOptions.DONOTSAVECHANGES);
        probeDoc = null;

        try { opts.pageToOpen = oldPage; } catch(e5) {}
        try { opts.pageRangeToOpen = oldRange; } catch(e6) {
            try { opts.pageRangeToOpen = "1"; } catch(e7) {}
        }
        if (hasLinks) try { opts.placeAsLinks = oldLinks; } catch(e8) {}
        app.userInteractionLevel = oldInteraction;
        return count;
    } catch (err) {
        safeClose(probeDoc, SaveOptions.DONOTSAVECHANGES);
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
}
function openPdfPage(pdfFile, pageNo) {
    var opts = app.preferences.PDFFileOptions;
    try { opts.pageToOpen = pageNo; } catch(e0) {}
    try { opts.pageRangeToOpen = String(pageNo); } catch(e1) {}
    try { opts.placeAsLinks = false; } catch(e2) {}
    return app.open(pdfFile);
}
function padPageNumber(pageNo, totalPages) {
    var digits = String(totalPages).length;
    if (digits < 2) digits = 2;
    var s = String(pageNo);
    while (s.length < digits) s = "0" + s;
    return s;
}
function makePageOutputName(pdfFile, pageNo, totalPages) {
    var base = baseNameNoExt(pdfFile);
    if (totalPages <= 1) return base + ".ai";
    return base + "_p" + padPageNumber(pageNo, totalPages) + ".ai";
}
function pageJobKey(pdfFile, pageNo) {
    return pdfFile.fsName.toLowerCase() + "|" + String(pageNo);
}

// ====================== PDF DEEP CLEANUP v6 ======================

function runPdfDeepCleanup(doc) {
    var PRESERVE_IMAGE_STRUCTURES = true;
    var PRESERVE_TRANSPARENCY_STRUCTURES = true;
    var RELEASE_SAFE_VECTOR_MASKS = true;
    var DELETE_CROP_MARKS = true;

    var stats = {
        safeGroupsUngrouped: 0,
        riskyGroupsPreserved: 0,
        vectorMasksReleased: 0,
        riskyMasksPreserved: 0,
        maskPathsDeleted: 0,
        cropPerimetersDeleted: 0,
        shortCropMarksDeleted: 0
    };

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

    // --- RUN ---
    var savedView = saveViewState(doc);
    unlockAll(doc);
    ungroupSafeGroups(doc, 40);
    if (RELEASE_SAFE_VECTOR_MASKS) releaseSafeVectorClippingMasks(doc);
    ungroupSafeGroups(doc, 40);
    if (DELETE_CROP_MARKS) {
        deleteCropPerimeterObjects(doc);
        deleteShortCropMarks(doc);
    }
    try { app.executeMenuCommand("deselectall"); } catch(e) {}
    restoreViewState(doc, savedView);

    return stats;
}

// ====================== GUI ======================
var pageCountCache = {};
var pageJobs = [];
var running = false;
var pageRows = [];
var VISIBLE_PAGE_ROWS = 9;

function makeBatchWindow() {
    var w = new Window("dialog", BATCH_APP_NAME);
    w.orientation = "column";
    w.alignChildren = ["fill", "top"];
    w.spacing = 7;
    w.margins = 12;

    var jobPanel = w.add("panel", undefined, "Darba folderis");
    jobPanel.orientation = "row";
    jobPanel.alignChildren = ["fill", "center"];
    jobPanel.margins = 9;
    var jobField = jobPanel.add("edittext", undefined, "");
    jobField.characters = 64;
    jobField.enabled = false;
    var jobBtn = jobPanel.add("button", undefined, "Izvēlēties...");

    var pathsPanel = w.add("panel", undefined, "Batch ceļi");
    pathsPanel.orientation = "column";
    pathsPanel.alignChildren = ["fill", "top"];
    pathsPanel.margins = 9;
    function addPathRow(labelText, withButton) {
        var g = pathsPanel.add("group");
        g.orientation = "row";
        g.alignChildren = ["left", "center"];
        var lbl = g.add("statictext", undefined, labelText);
        lbl.preferredSize.width = 82;
        var fld = g.add("edittext", undefined, "");
        fld.characters = 56;
        fld.enabled = false;
        var btn = null;
        if (withButton) btn = g.add("button", undefined, "Mainīt...");
        return { group: g, field: fld, button: btn };
    }
    var pdfRow = addPathRow("PDF:", true);
    var tplRow = addPathRow("Template:", true);
    var outRow = addPathRow("AI OUT:", true);

    var optionsPanel = w.add("panel", undefined, "Opcijas");
    optionsPanel.orientation = "row";
    optionsPanel.alignChildren = ["left", "center"];
    optionsPanel.margins = 9;
    var overwriteCb = optionsPanel.add("checkbox", undefined, "Pārrakstīt esošos AI");
    overwriteCb.value = false;
    var clearArtworkCb = optionsPanel.add("checkbox", undefined, 'Iztīrīt template slāni "ARTWORK"');
    clearArtworkCb.value = true;

    var pagePanel = w.add("panel", undefined, "PDF lapas — ieķeksē, kuras apstrādāt");
    pagePanel.orientation = "column";
    pagePanel.alignChildren = ["fill", "top"];
    pagePanel.margins = 9;

    var pageSummary = pagePanel.add("statictext", undefined, "PDF faili: 0 | Lapas: 0 | Atzīmētas: 0");

    var pageToolbar = pagePanel.add("group");
    pageToolbar.orientation = "row";
    pageToolbar.alignChildren = ["left", "center"];
    var allBtn = pageToolbar.add("button", undefined, "Visas ✓");
    var noneBtn = pageToolbar.add("button", undefined, "Nevienu");
    var invertBtn = pageToolbar.add("button", undefined, "Apgriezt");
    pageToolbar.add("statictext", undefined, "   Ritināšana: labajā malā");

    var pageArea = pagePanel.add("group");
    pageArea.orientation = "row";
    pageArea.alignChildren = ["fill", "top"];

    var rowsGroup = pageArea.add("group");
    rowsGroup.orientation = "column";
    rowsGroup.alignChildren = ["fill", "top"];
    rowsGroup.spacing = 2;

    var header = rowsGroup.add("group");
    header.orientation = "row";
    var h1 = header.add("statictext", undefined, "Apstrādāt / lapa");
    h1.preferredSize.width = 120;
    var h2 = header.add("statictext", undefined, "PDF fails");
    h2.preferredSize.width = 300;
    var h3 = header.add("statictext", undefined, "AI output");
    h3.preferredSize.width = 240;

    for (var rr = 0; rr < VISIBLE_PAGE_ROWS; rr++) {
        var rg = rowsGroup.add("group");
        rg.orientation = "row";
        rg.alignChildren = ["left", "center"];
        var cb = rg.add("checkbox", undefined, "Lapa 00");
        cb.preferredSize.width = 120;
        var pdfText = rg.add("statictext", undefined, "");
        pdfText.preferredSize.width = 300;
        var outText = rg.add("statictext", undefined, "");
        outText.preferredSize.width = 240;
        var rowObj = {
            group: rg,
            checkbox: cb,
            pdfText: pdfText,
            outText: outText,
            jobIndex: -1
        };
        // Closure lai fiksētu rowObj katram checkbox
        (function(row) {
            row.checkbox.onClick = function() {
                if (row.jobIndex < 0 || row.jobIndex >= pageJobs.length) return;
                pageJobs[row.jobIndex].checked = row.checkbox.value;
                updatePageSummaryAndStart();
            };
        })(rowObj);
        pageRows.push(rowObj);
    }

    var pageScroll = pageArea.add("scrollbar", undefined, 0, 0, 0);
    pageScroll.preferredSize = [18, 216];

    var statusPanel = w.add("panel", undefined, "Statuss");
    statusPanel.orientation = "column";
    statusPanel.alignChildren = ["fill", "top"];
    statusPanel.margins = 9;
    var statusText = statusPanel.add("statictext", undefined, "Izvēlies darba folderi.");
    var currentText = statusPanel.add("statictext", undefined, "");
    var progress = statusPanel.add("progressbar", undefined, 0, 100);
    progress.preferredSize = [680, 14];

    var logPanel = w.add("panel", undefined, "LOG");
    logPanel.orientation = "column";
    logPanel.alignChildren = ["fill", "fill"];
    logPanel.margins = 9;
    var logBox = logPanel.add("edittext", undefined, "", { multiline: true, scrolling: true });
    logBox.preferredSize = [705, 105];

    var buttons = w.add("group");
    buttons.alignment = "right";
    var refreshBtn = buttons.add("button", undefined, "Pārbaudīt / pārlasīt PDF");
    var startBtn = buttons.add("button", undefined, "START BATCH");
    var closeBtn = buttons.add("button", undefined, "Aizvērt");

    startBtn.enabled = false;

    var state = {
        jobFolder: null,
        pdfFolder: null,
        manualPdfFolder: null,
        pdfScanMode: "",
        templateFolder: null,
        templateFile: null,
        outputFolder: null,
        logFolder: null,
        errorFolder: null,
        pdfFiles: [],
        logLines: []
    };

    function addLog(s) {
        state.logLines.push(s);
        if (logBox.text.length > 0) logBox.text += "\r\n";
        logBox.text += s;
        try { logBox.active = true; logBox.selection = [logBox.text.length, logBox.text.length]; } catch(e) {}
        w.update();
    }

    function selectedPageCount() {
        var n = 0;
        for (var i = 0; i < pageJobs.length; i++) if (pageJobs[i].checked) n++;
        return n;
    }

    function updateFields() {
        jobField.text = state.jobFolder ? displayPath(state.jobFolder) : "";
        pdfRow.field.text = state.pdfFolder ? displayPath(state.pdfFolder) : "";
        tplRow.field.text = state.templateFile ? displayPath(state.templateFile) : "";
        outRow.field.text = state.outputFolder ? displayPath(state.outputFolder) : "";
    }

    function updatePageSummaryAndStart() {
        var selected = selectedPageCount();
        pageSummary.text = "PDF faili: " + state.pdfFiles.length + " | Lapas: " + pageJobs.length + " | Atzīmētas: " + selected;
        startBtn.enabled = (!running && selected > 0 && !!state.templateFile && state.templateFile.exists);
    }

    function renderPageRows() {
        var maxOffset = Math.max(0, pageJobs.length - VISIBLE_PAGE_ROWS);
        pageScroll.minvalue = 0;
        pageScroll.maxvalue = maxOffset;
        pageScroll.enabled = maxOffset > 0;
        if (pageScroll.value > maxOffset) pageScroll.value = maxOffset;
        if (pageScroll.value < 0) pageScroll.value = 0;
        var offset = Math.round(pageScroll.value);
        for (var r = 0; r < pageRows.length; r++) {
            var row = pageRows[r];
            var idx = offset + r;
            if (idx < pageJobs.length) {
                var job = pageJobs[idx];
                row.jobIndex = idx;
                row.group.visible = true;
                row.checkbox.enabled = !running;
                row.checkbox.value = !!job.checked;
                row.checkbox.text = "Lapa " + padPageNumber(job.pageNo, job.pageCount);
                row.pdfText.text = decodeURI(job.pdfFile.name);
                row.outText.text = job.outputName;
                row.group.helpTip = displayPath(job.pdfFile);
            } else {
                row.jobIndex = -1;
                row.group.visible = false;
                row.checkbox.value = false;
                row.pdfText.text = "";
                row.outText.text = "";
            }
        }
        updatePageSummaryAndStart();
        w.update();
    }

    pageScroll.onChanging = function() { renderPageRows(); };
    pageScroll.onChange  = function() { renderPageRows(); };

    function setAllChecks(v) {
        for (var i = 0; i < pageJobs.length; i++) pageJobs[i].checked = v;
        renderPageRows();
    }
    allBtn.onClick    = function() { setAllChecks(true); };
    noneBtn.onClick   = function() { setAllChecks(false); };
    invertBtn.onClick = function() {
        for (var i = 0; i < pageJobs.length; i++) pageJobs[i].checked = !pageJobs[i].checked;
        renderPageRows();
    };

    function getCachedPageInfo(pdfFile, forceRedetect) {
        var k = pdfFile.fsName.toLowerCase();
        var sig = safeFileSignature(pdfFile);
        var cached = pageCountCache[k];
        if (!forceRedetect && cached && cached.signature === sig) return cached;
        currentText.text = "Skaitu PDF lapas: " + decodeURI(pdfFile.name);
        w.update();
        var info = detectPdfPageCount(pdfFile);
        var result = { signature: sig, count: info.count, method: info.method };
        pageCountCache[k] = result;
        return result;
    }

    function rebuildPageJobs(forceRedetect) {
        var oldChecks = {};
        for (var x = 0; x < pageJobs.length; x++) {
            oldChecks[pageJobKey(pageJobs[x].pdfFile, pageJobs[x].pageNo)] = pageJobs[x].checked;
        }
        var jobs = [];
        var totalPages = 0;
        for (var i = 0; i < state.pdfFiles.length; i++) {
            var pdfFile = state.pdfFiles[i];
            var info = getCachedPageInfo(pdfFile, forceRedetect);
            var pages = info.count;
            if (!pages || pages < 1) pages = 1;
            totalPages += pages;
            addLog("PDF: " + decodeURI(pdfFile.name) + " | lapas=" + pages + " | " + info.method);
            for (var p = 1; p <= pages; p++) {
                var key = pageJobKey(pdfFile, p);
                jobs.push({
                    key: key,
                    pdfFile: pdfFile,
                    pageNo: p,
                    pageCount: pages,
                    checked: (oldChecks[key] !== undefined) ? oldChecks[key] : true,
                    outputName: makePageOutputName(pdfFile, p, pages)
                });
            }
        }
        pageJobs = jobs;
        pageScroll.value = 0;
        currentText.text = "";
        renderPageRows();
        return totalPages;
    }

    function scanJob(forceRedetect) {
        if (!state.jobFolder) return;
        var preferredPdfFolder = folderJoin(state.jobFolder, "PDF");
        state.templateFolder = folderJoin(state.jobFolder, "TEMPLATE");
        state.outputFolder = state.outputFolder || folderJoin(state.jobFolder, "AI_OUT");
        state.logFolder    = folderJoin(state.jobFolder, "LOG");
        state.errorFolder  = folderJoin(state.jobFolder, "ERROR");
        ensureFolder(state.templateFolder);
        ensureFolder(state.outputFolder);
        ensureFolder(state.logFolder);
        ensureFolder(state.errorFolder);
        var pdfResolution = resolvePdfQueue(state.jobFolder, preferredPdfFolder, state.manualPdfFolder);
        state.pdfFolder  = pdfResolution.root;
        state.pdfFiles   = pdfResolution.files;
        state.pdfScanMode = pdfResolution.mode;
        if (!state.templateFile || !state.templateFile.exists) {
            state.templateFile = detectTemplate(state.templateFolder);
        }
        updateFields();
        addLog("");
        addLog("PĀRBAUDE");
        addLog("PDF faili rindā: " + state.pdfFiles.length);
        addLog("PDF režīms: " + state.pdfScanMode);
        addLog("PDF avots: " + displayPath(state.pdfFolder));
        var totalPages = 0;
        if (state.pdfFiles.length > 0) {
            totalPages = rebuildPageJobs(!!forceRedetect);
        } else {
            pageJobs = [];
            renderPageRows();
            addLog("! PDF nav atrasts.");
        }
        var templateOK = state.templateFile && state.templateFile.exists;
        if (templateOK) addLog("Template: " + state.templateFile.name);
        else addLog("! Template nav atrasts folderī TEMPLATE.");
        addLog("AI OUT: " + displayPath(state.outputFolder));
        addLog("PDF lapas kopā: " + totalPages);
        addLog("Atzīmētas apstrādei: " + selectedPageCount());
        statusText.text = "PDF faili: " + state.pdfFiles.length + " | lapas: " + pageJobs.length + " | izvēlētas: " + selectedPageCount() + " | Template: " + (templateOK ? "OK" : "NAV ATRASTS");
        updatePageSummaryAndStart();
    }

    jobBtn.onClick = function() {
        var f = Folder.selectDialog("Izvēlies JOB darba folderi");
        if (!f) return;
        state.jobFolder = f;
        state.outputFolder = folderJoin(f, "AI_OUT");
        state.manualPdfFolder = null;
        state.templateFile = null;
        state.logLines = [];
        logBox.text = "";
        addLog("JOB: " + displayPath(f));
        scanJob(true);
    };
    pdfRow.button.onClick = function() {
        var f = Folder.selectDialog("Izvēlies mapi, kurā meklēt PDF");
        if (!f) return;
        state.manualPdfFolder = f;
        addLog("PDF MANUAL: " + displayPath(f));
        scanJob(true);
    };
    tplRow.button.onClick = function() {
        var f = File.openDialog("Izvēlies Illustrator MASTER template", "Illustrator:*.ai;*.ait", false);
        if (!f) return;
        state.templateFile = f;
        updateFields();
        scanJob(false);
    };
    outRow.button.onClick = function() {
        var f = Folder.selectDialog("Izvēlies AI output folderi");
        if (!f) return;
        state.outputFolder = f;
        ensureFolder(state.outputFolder);
        updateFields();
        scanJob(false);
    };
    refreshBtn.onClick = function() { scanJob(true); };
    closeBtn.onClick   = function() { if (!running) w.close(); };

    startBtn.onClick = function() {
        if (running) return;

        scanJob(false);

        if (!state.templateFile || !state.templateFile.exists) {
            alert("Template nav atrasts."); return;
        }

        var selectedJobs = [];
        for (var sj = 0; sj < pageJobs.length; sj++) {
            if (pageJobs[sj].checked) selectedJobs.push(pageJobs[sj]);
        }
        if (selectedJobs.length === 0) {
            alert("Nav ieķeksēta neviena PDF lapa."); return;
        }

        running = true;
        jobBtn.enabled = false;
        pdfRow.button.enabled = false;
        tplRow.button.enabled = false;
        outRow.button.enabled = false;
        refreshBtn.enabled = false;
        startBtn.enabled = false;
        closeBtn.enabled = false;
        allBtn.enabled = false;
        noneBtn.enabled = false;
        invertBtn.enabled = false;
        renderPageRows();

        var okCount = 0, errorCount = 0, skipCount = 0;
        var total = selectedJobs.length;

        addLog("");
        addLog("========================================");
        addLog("BATCH START");
        addLog("Template: " + displayPath(state.templateFile));
        addLog("Izvēlētas PDF lapas: " + total);
        addLog("========================================");

        var oldInteraction = app.userInteractionLevel;
        try { app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS; } catch(eUI0) {}

        for (var i = 0; i < total; i++) {
            var job = selectedJobs[i];
            var pdfFile = job.pdfFile;
            var outputFile = new File(state.outputFolder.fsName + "/" + job.outputName);

            currentText.text = (i + 1) + " / " + total + "   " + decodeURI(pdfFile.name) + "   | lapa " + job.pageNo + "/" + job.pageCount;
            progress.value = Math.round((i / total) * 100);
            w.update();

            if (outputFile.exists && !overwriteCb.value) {
                addLog("SKIP  " + decodeURI(pdfFile.name) + " | lapa " + job.pageNo + " → " + decodeURI(outputFile.name) + " jau eksistē");
                skipCount++;
                continue;
            }

            var sourceDoc = null;
            var destDoc = null;
            var templateCopied = false;

            try {
                sourceDoc = openPdfPage(pdfFile, job.pageNo);
                sourceDoc.activate();

                // v6 cleanup — bez alert, tikai stats
                var fileStats = runPdfDeepCleanup(sourceDoc);

                templateCopied = copyTemplateToOutput(state.templateFile, outputFile, overwriteCb.value);
                if (!templateCopied) throw new Error("Output AI jau eksistē.");

                destDoc = app.open(outputFile);
                destDoc.activate();

                var artworkLayer = findOrCreateArtworkLayer(destDoc);
                if (clearArtworkCb.value) clearArtworkLayer(artworkLayer);

                var copiedObjects = duplicateSourceLayersIntoArtwork(sourceDoc, artworkLayer);

                destDoc.activate();
                destDoc.save();

                safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
                safeClose(destDoc, SaveOptions.SAVECHANGES);

                okCount++;
                addLog("OK    " + decodeURI(pdfFile.name) + " | lapa " + job.pageNo + "/" + job.pageCount +
                    " → " + decodeURI(outputFile.name) +
                    " | obj=" + copiedObjects +
                    " | ungrp=" + fileStats.safeGroupsUngrouped +
                    " | masks=" + fileStats.vectorMasksReleased +
                    " | crop=" + (fileStats.cropPerimetersDeleted + fileStats.shortCropMarksDeleted));

            } catch(err) {
                errorCount++;
                safeClose(sourceDoc, SaveOptions.DONOTSAVECHANGES);
                safeClose(destDoc, SaveOptions.DONOTSAVECHANGES);
                if (templateCopied && outputFile.exists) removeIfExists(outputFile);
                addLog("ERROR " + decodeURI(pdfFile.name) + " | lapa " + job.pageNo + " | " + err);
            }

            progress.value = Math.round(((i + 1) / total) * 100);
            w.update();
            try { $.gc(); } catch(eGc) {}
        }

        try { app.userInteractionLevel = oldInteraction; } catch(eUI1) {}

        progress.value = 100;
        currentText.text = "Pabeigts.";

        addLog("");
        addLog("========================================");
        addLog("BATCH DONE");
        addLog("OK: " + okCount);
        addLog("SKIP: " + skipCount);
        addLog("ERROR: " + errorCount);
        addLog("========================================");

        writeLogFile(state.logFolder, state.logLines);

        running = false;
        jobBtn.enabled = true;
        pdfRow.button.enabled = true;
        tplRow.button.enabled = true;
        outRow.button.enabled = true;
        refreshBtn.enabled = true;
        closeBtn.enabled = true;
        allBtn.enabled = true;
        noneBtn.enabled = true;
        invertBtn.enabled = true;
        renderPageRows();

        alert("Batch pabeigts.\n\nIzvēlētās lapas: " + total + "\nOK: " + okCount + "\nSKIP: " + skipCount + "\nERROR: " + errorCount);
    };

    w.center();
    w.show();
}

makeBatchWindow();
