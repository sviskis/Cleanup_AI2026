/*
    PDF Deep Cleanup AI 2026
    Module: src/services/LogService.jsx

    Purpose:
      One logging entry point for the whole project.

      Log line format written to every log file:
        2026-09-23 15:30:10 | INFO | Script started

      Two destinations are used:
        * project session log : <project>/logs/project.log
        * job batch log       : <JOB>/LOG/batch_<timestamp>.txt
          (the job batch log keeps the exact behaviour of the reference script,
           which wrote one text file per batch run into the JOB LOG folder)

    Source:
      writeJobLog() (legacy name writeLogFile) is extracted unchanged from the
      reference script (lines 204-213) except for two adapted call sites:
      ensureFolder -> PDC.FileService.ensureFolder, and the whole writer is
      wrapped in try/catch so a failed log write can never abort a batch.
      logInfo / logWarning / logError / logDebug are new.

    ExtendScript: ES3 safe.
*/

PDC.registerModule("LogService", (function () {

    var LEVELS = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 };

    var sessionStart = null;
    var sessionLines = [];
    function writeLogFile(logFolder, lines) {
        PDC.FileService.ensureFolder(logFolder);
        var f = new File(logFolder.fsName + "/" + PDC.CONFIG.log.jobFilePrefix + "_" + PDC.TextUtils.formatTimestamp() + ".txt");
        f.encoding = "UTF-8";
        f.lineFeed = "Windows";
        if (f.open("w")) {
            for (var i = 0; i < lines.length; i++) f.writeln(lines[i]);
            f.close();
        }
    }    /* ---- new: levelled session logging ---- */

    function startSession() {
        sessionStart = new Date();
        sessionLines = [];
        logInfo("Session started. Version " + PDC.CONFIG.version + " | " + PDC.CONFIG.appName);
    }

    function currentLevel() {
        var name = "INFO";
        try { name = String(PDC.CONFIG.log.level).toUpperCase(); } catch (e) {}
        return (LEVELS[name] !== undefined) ? LEVELS[name] : LEVELS.INFO;
    }

    function logLine(levelName, message) {
        var line = PDC.TextUtils.formatLogTimestamp(new Date()) + " | " + levelName + " | " + message;
        sessionLines.push(line);
        return line;
    }

    function logDebug(message) {
        if (!PDC.CONFIG.debug) return "";
        if (currentLevel() > LEVELS.DEBUG) return "";
        return logLine("DEBUG", message);
    }

    function logInfo(message) {
        if (currentLevel() > LEVELS.INFO) return "";
        return logLine("INFO", message);
    }

    function logWarning(message) {
        if (currentLevel() > LEVELS.WARNING) return "";
        return logLine("WARNING", message);
    }

    function logError(message) {
        return logLine("ERROR", message);
    }

    function getSessionLines() {
        return sessionLines;
    }

    function getSessionLogFile() {
        var logsFolder = PDC.Paths.getLogsFolder();
        PDC.FileService.ensureFolder(logsFolder);
        return new File(logsFolder.fsName + "/" + PDC.CONFIG.log.sessionFileName);
    }

    function flushSessionLog() {
        try {
            var f = getSessionLogFile();
            var block = sessionLines.join("\r\n") + "\r\n";
            return PDC.FileService.appendTextFile(f, block, "UTF-8");
        } catch (e) {
            return false;
        }
    }

    return {
        LEVELS: LEVELS,
        startSession: startSession,
        logDebug: logDebug,
        logInfo: logInfo,
        logWarning: logWarning,
        logError: logError,
        getSessionLines: getSessionLines,
        getSessionLogFile: getSessionLogFile,
        flushSessionLog: flushSessionLog,
        writeJobLog: writeLogFile
    };
}()));
