/*
    Cleanup AI 2026
    Test: tests/jscript/test_json_contract.js

    Verifies the JSON layer that the Python orchestrator and the Illustrator
    worker share (jsx/json2.js) against the SAME fixtures the Python test suite
    uses, so both sides of the contract are proven to agree:

        tests/fixtures/request_sample.json
        tests/fixtures/result_sample.json

    Runs with the Windows Script Host JScript engine (no Illustrator needed):
        cscript //nologo //E:JScript tests\jscript\test_json_contract.js

    Executed automatically by tools/run_tests.ps1.
*/

var fso = new ActiveXObject("Scripting.FileSystemObject");
var scriptFull = fso.GetAbsolutePathName(WScript.ScriptFullName);
var testsDir = fso.GetParentFolderName(fso.GetParentFolderName(scriptFull));
var repoRoot = fso.GetParentFolderName(testsDir);

var __pass = 0;
var __fail = 0;

function ok(name, condition, detail) {
    if (condition) { __pass++; WScript.Echo("  PASS  " + name); }
    else { __fail++; WScript.Echo("  FAIL  " + name + (detail ? ("   -> " + detail) : "")); }
}

function eq(name, actual, expected) {
    ok(name, String(actual) === String(expected), "expected [" + expected + "] got [" + actual + "]");
}

function readUtf8(path) {
    var stream = new ActiveXObject("ADODB.Stream");
    stream.Type = 2;
    stream.Charset = "utf-8";
    stream.Open();
    stream.LoadFromFile(path);
    var text = stream.ReadText();
    stream.Close();
    if (text.charCodeAt(0) === 0xFEFF) text = text.substring(1);
    return text;
}

function runFile(path) {
    return readUtf8(path);
}

WScript.Echo("");
WScript.Echo("== JSON contract (jsx/json2.js) ==");

/* eval at script top level so json2.js defines its globals */
var json2Source = runFile(repoRoot + "\\jsx\\json2.js");
eval(json2Source);

ok("json2 loaded", typeof PDCJson === "object");
ok("JSON.parse available", typeof JSON.parse === "function");
ok("JSON.stringify available", typeof JSON.stringify === "function");

/* ---------------- request fixture ---------------- */

var requestText = readUtf8(repoRoot + "\\tests\\fixtures\\request_sample.json");
var request = JSON.parse(requestText);

eq("schema", request.schema, "pdf_ai_batch/job_request/v1");
eq("run_id", request.run_id, "20260923-160000-abc123");
eq("job_id", request.job_id, "manual_p017");
eq("pdf", request.pdf, "C:/JOB/PDF/manual.pdf");
eq("page is a number", typeof request.page, "number");
eq("page", request.page, 17);
eq("template", request.template, "C:/JOB/TEMPLATE/017.ai");
eq("template_mode", request.template_mode, "copy");
eq("output", request.output, "C:/JOB/AI_OUT/manual__017.ai");
eq("layer", request.layer, "ARTWORK");
eq("clear_layer", request.clear_layer, true);
eq("overwrite", request.overwrite, false);
eq("cleanup.ungroupPasses", request.cleanup.ungroupPasses, 40);
eq("cleanup.releaseSafeVectorMasks", request.cleanup.releaseSafeVectorMasks, true);

var requiredRequestKeys = ["schema", "run_id", "job_id", "pdf", "page", "template", "template_mode", "output", "layer", "clear_layer", "overwrite"];
var missingRequest = [];
for (var i = 0; i < requiredRequestKeys.length; i++) {
    if (request[requiredRequestKeys[i]] === undefined) missingRequest.push(requiredRequestKeys[i]);
}
ok("all required request keys present", missingRequest.length === 0, missingRequest.join(","));

/* ---------------- result fixture ---------------- */

var resultText = readUtf8(repoRoot + "\\tests\\fixtures\\result_sample.json");
var result = JSON.parse(resultText);

eq("result status", result.status, "OK");
eq("result page", result.page, 17);
eq("result job_id", result.job_id, "manual_p017");
eq("objects_copied", result.objects_copied, 241);
eq("stats.safe_groups_ungrouped", result.stats.safe_groups_ungrouped, 19);
eq("stats.crop_perimeters_deleted", result.stats.crop_perimeters_deleted, 6);
eq("stats.short_crop_marks_deleted", result.stats.short_crop_marks_deleted, 2);
eq("stats.crop_objects_deleted is the sum", result.stats.crop_objects_deleted,
   result.stats.crop_perimeters_deleted + result.stats.short_crop_marks_deleted);

var expectedStatKeys = ["safe_groups_ungrouped", "risky_groups_preserved", "vector_masks_released",
    "risky_masks_preserved", "mask_paths_deleted", "crop_perimeters_deleted",
    "short_crop_marks_deleted", "crop_objects_deleted"];
var missingStats = [];
for (var s = 0; s < expectedStatKeys.length; s++) {
    if (result.stats[expectedStatKeys[s]] === undefined) missingStats.push(expectedStatKeys[s]);
}
ok("all contract stat keys present", missingStats.length === 0, missingStats.join(","));

/* ---------------- round trip ---------------- */

var roundTrip = JSON.parse(JSON.stringify(result));
eq("round trip status", roundTrip.status, result.status);
eq("round trip nested stat", roundTrip.stats.crop_objects_deleted, 8);
eq("round trip page number", roundTrip.page, 17);

var reparsed = JSON.parse(JSON.stringify(request));
eq("request round trip job_id", reparsed.job_id, request.job_id);
eq("request round trip page", reparsed.page, request.page);
eq("request round trip cleanup flag", reparsed.cleanup.deleteCropMarks, true);

/* ---------------- escaping / edge cases ---------------- */

eq("stringify escaping", JSON.stringify({ a: "x\"y\\z\n" }), "{\"a\":\"x\\\"y\\\\z\\n\"}");
eq("parse unicode escape", JSON.parse("\"\\u0101\""), "\u0101");
eq("stringify latvian round trip", JSON.parse(JSON.stringify({ n: "Maijs \u0100\u0101 \u010c\u010d" })).n, "Maijs \u0100\u0101 \u010c\u010d");
eq("stringify null", JSON.stringify(null), "null");
eq("stringify array", JSON.stringify([1, true, null, "a"]), "[1,true,null,\"a\"]");
eq("parse negative exponent number", JSON.parse("-12.5e2"), -1250);
eq("parse empty object", JSON.stringify(JSON.parse("{}")), "{}");
eq("parse empty array", JSON.stringify(JSON.parse("[]")), "[]");
eq("parse whitespace tolerated", JSON.parse("  \n\t{\"a\" : 1 }  ").a, 1);

var threwOnBadJson = false;
try { JSON.parse("{ bad }"); } catch (eBad) { threwOnBadJson = (String(eBad.message).indexOf("JSON.parse") >= 0); }
ok("invalid JSON throws a positioned error", threwOnBadJson);

var threwOnCycle = false;
try {
    var cyclic = {};
    cyclic.self = cyclic;
    JSON.stringify(cyclic);
} catch (eCycle) { threwOnCycle = true; }
ok("cyclic structure throws", threwOnCycle);

WScript.Echo("");
WScript.Echo("========================================");
WScript.Echo("PASSED: " + __pass + "   FAILED: " + __fail);
if (__fail > 0) {
    WScript.Quit(1);
}
WScript.Echo("JSON CONTRACT TESTS PASSED");
WScript.Quit(0);
