/*
    PDF Deep Cleanup AI 2026
    Tool: tools/jscript_parse.js

    Purpose:
      Real syntax validation of ExtendScript .jsx code without starting
      Illustrator. The Windows Script Host JScript engine (5.8) is the closest
      thing to the ExtendScript engine that ships with every Windows machine:
      it accepts ES3 and rejects ES5+/ES6 syntax, exactly like Illustrator.

    Usage (normally called by tools/check_jsx.ps1):
      cscript //nologo //E:JScript tools\jscript_parse.js <file.js>

    Output:
      PARSE_OK <file>
      PARSE_FAIL <file>: <message>      (exit code 1)

    The input file must already have its ExtendScript preprocessor directives
    (#target, #include, #targetengine) replaced or commented out, because WSH
    JScript does not understand them.
*/

var fso = new ActiveXObject("Scripting.FileSystemObject");

if (WScript.Arguments.length < 1) {
    WScript.Echo("USAGE: cscript //nologo //E:JScript tools\\jscript_parse.js <file.js>");
    WScript.Quit(2);
}

var path = WScript.Arguments(0);

if (!fso.FileExists(path)) {
    WScript.Echo("PARSE_FAIL " + path + ": file not found");
    WScript.Quit(2);
}

var stream = new ActiveXObject("ADODB.Stream");
stream.Type = 2;
stream.Charset = "utf-8";
stream.Open();
stream.LoadFromFile(path);
var text = stream.ReadText();
stream.Close();

if (text.charCodeAt(0) === 0xFEFF) {
    text = text.substring(1);
}

/* WSH JScript does not know the ExtendScript preprocessor. */
text = text.replace(/^[ \t]*#(target|targetengine|include|script|strict)\b[^\n]*$/gm, "/* preprocessor */");

try {
    var compiled = new Function(text);
    if (typeof compiled !== "function") {
        throw new Error("compile returned " + typeof compiled);
    }
    WScript.Echo("PARSE_OK " + path);
} catch (e) {
    WScript.Echo("PARSE_FAIL " + path + ": " + e.message);
    WScript.Quit(1);
}
