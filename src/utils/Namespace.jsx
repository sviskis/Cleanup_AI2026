/*
    PDF Deep Cleanup AI 2026
    Module: src/utils/Namespace.jsx

    Purpose:
      Single global namespace object PDC for the whole project. Every module
      attaches itself with PDC.registerModule("Name", api) so that:
        * nothing leaks into the global scope of the Illustrator engine
          (except the one PDC object);
        * modules can talk to each other as PDC.Config / PDC.FileService / ...
        * a typo becomes a clear runtime error instead of a silent undefined.

      This file MUST be included first in src/Main.jsx.

    ExtendScript: ES3 safe.
*/

var PDC = PDC || {};

if (!PDC.MODULES) {
    PDC.MODULES = [];
}

PDC.registerModule = function (name, api) {
    if (PDC[name]) {
        throw new Error("PDC modulis jau ir reģistrēts: " + name);
    }
    PDC[name] = api;
    PDC.MODULES.push(name);
    return api;
};

PDC.moduleList = function () {
    return PDC.MODULES.join(", ");
};
