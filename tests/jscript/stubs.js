/*
    Cleanup AI 2026
    Test support: tests/jscript/stubs.js

    Purpose:
      Minimal stand-ins for the ExtendScript host (File, Folder, app, $,
      UserInteractionLevel, SaveOptions, ...) so that the pure logic of the
      project can be executed and asserted OUTSIDE Illustrator with the Windows
      Script Host JScript engine (cscript //E:JScript).

      This is not an Illustrator emulator. It only implements what the tested
      functions touch: an in-memory filesystem, the paths and a few app
      properties.

    Priority of the stubs: LOW - they exist to test unit level behaviour.
    Real end to end behaviour is verified with the manual checklist in
    docs/TESTING.md.
*/

var __FS = { files: {}, dirs: {} };

function __safeKey(p) {
    return String(p).replace(/\\/g, "/").toLowerCase();
}

function __baseName(p) {
    var s = String(p).replace(/\\/g, "/");
    var i = s.lastIndexOf("/");
    return (i >= 0) ? s.substring(i + 1) : s;
}

function __parentPath(p) {
    var s = String(p).replace(/\\/g, "/");
    var i = s.lastIndexOf("/");
    return (i > 0) ? s.substring(0, i) : s;
}

function __stubDir(path) {
    var key = __safeKey(path);
    __FS.dirs[key] = true;
    return key;
}

function __stubFile(path, content) {
    var key = __safeKey(path);
    __FS.files[key] = (content === undefined) ? "" : String(content);
    return key;
}

/* parent folder without infinite recursion at filesystem roots */
function __mkParent(path) {
    var p = __parentPath(path);
    if (__safeKey(p) === __safeKey(path)) return null;
    return new Folder(p);
}

/* ------------------------------------------------------------------ File */

function File(path) {
    this.fsName = String(path);
    this.path = String(path);
    this.name = __baseName(path);
    this.encoding = "UTF-8";
    this.lineFeed = "Windows";
    this.opened = false;
    this.eof = true;
    this._key = __safeKey(path);
    this._mode = "";
    this._pos = 0;
    this.parent = __mkParent(path);
    this.__sync();
}

File.prototype.__sync = function () {
    this.exists = (__FS.files[this._key] !== undefined);
    this.length = this.exists ? __FS.files[this._key].length : 0;
    this.modified = new Date();
};

File.prototype.open = function (mode) {
    this._mode = String(mode);
    this._truncated = false;
    if (this._mode === "r") {
        if (!this.exists) return false;
        this._pos = 0;
        this.eof = false;
    } else {
        if (!this.exists) { __FS.files[this._key] = ""; }
        this._pos = 0;
        if (this._mode === "w") { this._truncated = true; __FS.files[this._key] = ""; }
    }
    this.opened = true;
    this.__sync();
    return true;
};

File.prototype.write = function (s) {
    if (!this.opened) return false;
    if (this._mode === "r") return false;
    var cur = __FS.files[this._key];
    __FS.files[this._key] = cur + String(s);
    this._pos = __FS.files[this._key].length;
    this.__sync();
    return true;
};

File.prototype.writeln = function (s) {
    return this.write((s === undefined ? "" : String(s)) + "\n");
};

File.prototype.read = function (chars) {
    if (!this.opened) return "";
    var all = __FS.files[this._key];
    if (chars === undefined) {
        var rest = all.substring(this._pos);
        this._pos = all.length;
        this.eof = true;
        return rest;
    }
    var part = all.substring(this._pos, this._pos + chars);
    this._pos += part.length;
    this.eof = (this._pos >= all.length);
    return part;
};

File.prototype.close = function () {
    this.opened = false;
    this.eof = true;
    this.__sync();
    return true;
};

File.prototype.remove = function () {
    if (this.exists) { delete __FS.files[this._key]; }
    this.__sync();
    return true;
};

File.prototype.copy = function (target) {
    var src = this;
    if (!src.exists) return false;
    var tk = __safeKey(target);
    __FS.files[tk] = __FS.files[src._key];
    var copy = new File(target);
    copy.__sync();
    return copy;
};

File.openDialog = function () { return null; };

/* ---------------------------------------------------------------- Folder */

function Folder(path) {
    this.fsName = String(path);
    this.path = String(path);
    this.name = __baseName(path);
    this._key = __safeKey(path);
    this.exists = (__FS.dirs[this._key] === true);
    this.parent = __mkParent(path);
}

Folder.prototype.create = function () {
    __FS.dirs[this._key] = true;
    this.exists = true;
    return true;
};

Folder.prototype.remove = function () {
    delete __FS.dirs[this._key];
    this.exists = false;
    return true;
};

Folder.prototype.getFiles = function (mask) {
    var self = this;
    var out = [];
    for (var k in __FS.files) {
        if (k.indexOf(self._key + "/") === 0 && k.substring(self._key.length + 1).indexOf("/") < 0) {
            out.push(new File(k));
        }
    }
    if (typeof mask === "function") {
        var filtered = [];
        for (var i = 0; i < out.length; i++) { if (mask(out[i])) filtered.push(out[i]); }
        return filtered;
    }
    return out;
};

Folder.current = new Folder("C:/stub");
Folder.selectDialog = function () { return null; };

/* ------------------------------------------------------- host objects */

var app = {
    name: "Adobe Illustrator",
    version: "28.0.0",
    build: "stub",
    documents: [],
    userInteractionLevel: 1,
    preferences: {
        PDFFileOptions: { pageToOpen: 1, pageRangeToOpen: "1", placeAsLinks: true }
    },
    redraw: function () {},
    executeMenuCommand: function () {}
};

var $ = { fileName: "C:/stub/src/Main.jsx", version: "4.0.0" };

var UserInteractionLevel = { DONTDISPLAYALERTS: 0, DISPLAYALERTS: 1 };
var SaveOptions = { SAVECHANGES: 1, DONOTSAVECHANGES: 2, PROMPTTOSAVECHANGES: 3 };
var ElementPlacement = { PLACEATBEGINNING: 0, PLACEATEND: 1, PLACEBEFORE: 2, PLACEAFTER: 3 };
var BlendModes = { NORMAL: 0 };
var KnockoutState = { DISABLED: 0, INHERITED: 1, ENABLED: 2 };

var __alerts = [];
function alert(s) { __alerts.push(String(s)); }

/* a couple of folders that must exist for the diagnostics test */
__stubDir("C:/stub");
__stubDir("C:/stub/logs");
__stubDir("C:/stub/temp");
__stubDir("C:/stub/config");
