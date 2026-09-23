/*
    PDF Deep Cleanup AI 2026
    Module: src/utils/Paths.jsx

    Purpose:
      Central path management, plan phase 7.

      Two different worlds are kept apart:
        1. PROJECT paths - always derived from the location of src/Main.jsx via
           $.fileName. Nothing in this project is allowed to hard code a path
           like C:\\Users\\...\\Desktop.
        2. JOB paths - the JOB folder is chosen by the operator in the GUI and
           lives outside the project. They are only ever built as
           <chosenJobFolder>\\<folder name from CONFIG.folders>.

      Windows specifics handled here:
        * forward slashes are used for File()/Folder() construction, which
          ExtendScript accepts on Windows and keeps OneDrive paths, spaces and
          Latvian characters safe;
        * decodeURI() is applied by TextUtils.displayPath() when a path is shown
          to the user, never when it is used on disk.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("Paths", (function () {

    function getScriptFile() {
        var name = "";
        try { name = $.fileName; } catch (e0) { name = ""; }
        if (!name) return null;
        return new File(name);
    }

    function getSrcFolder() {
        var f = getScriptFile();
        if (!f) return new Folder(Folder.current.fsName);
        return f.parent;
    }

    function getProjectRoot() {
        var src = getSrcFolder();
        var root = src.parent;
        if (root && root.exists) return root;
        return src;
    }

    function projectPath(relativePath) {
        return new File(getProjectRoot().fsName + "/" + relativePath);
    }

    function projectFolder(relativePath) {
        return new Folder(getProjectRoot().fsName + "/" + relativePath);
    }

    function getConfigFolder() { return projectFolder("config"); }
    function getLogsFolder()   { return projectFolder("logs"); }

    function getErrorsFolder() {
        return projectFolder("logs/" + PDC.CONFIG.log.errorReportFolder);
    }

    function getTempFolder() { return projectFolder("temp"); }

    /* --- JOB folder layout --- */

    function jobFolders(jobFolder) {
        return {
            root: jobFolder,
            input: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.input),
            template: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.template),
            config: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.config),
            output: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.output),
            temp: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.temp),
            logs: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.logs),
            errors: PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.errors)
        };
    }

    function getInputFolder(jobFolder)    { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.input); }
    function getTemplateFolder(jobFolder) { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.template); }
    function getOutputFolder(jobFolder)   { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.output); }
    function getLogsFolderForJob(jobFolder)   { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.logs); }
    function getErrorsFolderForJob(jobFolder) { return PDC.FileService.folderJoin(jobFolder, PDC.CONFIG.folders.errors); }

    function getSuggestedJobFolder() {
        var configured = PDC.CONFIG.defaultJobFolder;
        if (configured) {
            var f = new Folder(configured);
            if (f.exists) return f;
        }
        return null;
    }

    return {
        getScriptFile: getScriptFile,
        getSrcFolder: getSrcFolder,
        getProjectRoot: getProjectRoot,
        projectPath: projectPath,
        projectFolder: projectFolder,
        getConfigFolder: getConfigFolder,
        getLogsFolder: getLogsFolder,
        getErrorsFolder: getErrorsFolder,
        getTempFolder: getTempFolder,
        jobFolders: jobFolders,
        getInputFolder: getInputFolder,
        getTemplateFolder: getTemplateFolder,
        getOutputFolder: getOutputFolder,
        getLogsFolderForJob: getLogsFolderForJob,
        getErrorsFolderForJob: getErrorsFolderForJob,
        getSuggestedJobFolder: getSuggestedJobFolder
    };
}()));
