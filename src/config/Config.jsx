/*
    Cleanup AI 2026
    Module: src/config/Config.jsx

    Purpose:
      Every tunable value of the project in one place. The reference script had
      the JOB folder names and the cleanup switches hard coded in several files;
      here they are collected, so a change never needs a code search.

      Nothing in this file touches the filesystem or Illustrator.

    Defaults are the reference behaviour:
      debug        = false  (quiet)
      dryRun       = false  (real batch)
      overwriteExisting = false (never overwrite an existing AI output silently)

    ExtendScript: ES3 safe (no trailing commas, no let/const, no arrow functions).
*/

PDC.CONFIG = {

    projectName: "Cleanup AI 2026",
    appName: "PDF Deep Cleanup → AI Template Batch",
    version: "0.2.0",

    /* --- behaviour switches, plan phases 16 and 17 --- */
    debug: false,
    dryRun: false,
    overwriteExisting: false,
    clearArtworkByDefault: true,

    /* --- Illustrator / workflow values --- */
    artworkLayerName: "ARTWORK",
    visiblePageRows: 9,
    maxPdfScanDepth: 8,
    excludedScanFolders: ["template", "ai_out", "log", "error", "errors", "archive"],

    /* --- JOB folder layout (created on demand inside the chosen JOB folder) --- */
    folders: {
        input: "PDF",
        template: "TEMPLATE",
        config: "CONFIG",
        output: "AI_OUT",
        temp: "TEMP",
        logs: "LOG",
        errors: "ERROR"
    },

    /* --- logging, plan phase 9 --- */
    log: {
        level: "INFO",
        sessionFileName: "project.log",
        jobFilePrefix: "batch",
        errorReportFolder: "errors"
    },

    /* --- PDF Deep Cleanup engine switches, plan phase 12 ---
       The two "preserve" values are intent documentation: the reference engine
       always preserved image and transparency structures through its
       "safe only" tests. They are kept here so a future unsafe mode has a
       switch to read, but changing them has no effect today. */
    cleanup: {
        preserveImageStructures: true,
        preserveTransparencyStructures: true,
        releaseSafeVectorMasks: true,
        deleteCropMarks: true,
        ungroupPasses: 40
    },

    /* --- optional: suggested JOB folder shown by diagnostics ("" = none) --- */
    defaultJobFolder: ""
};
