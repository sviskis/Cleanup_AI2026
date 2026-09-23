/*
    CLEANUP AI 2026
    Module: jsx/json2.js

    A small, dependency free JSON implementation for ExtendScript (ES3).

    Why: ExtendScript has no built in JSON object in most Illustrator versions,
    and the Python <-> JSX contract is JSON. This file provides JSON.stringify
    and JSON.parse when they are missing. If Illustrator already provides a JSON
    object with both methods, this file leaves it untouched.

    Scope (deliberately small and predictable):
      * JSON.parse     - full syntax: objects, arrays, strings with all escapes
                         (\", \\, \/, \b, \f, \n, \r, \t, \uXXXX), numbers,
                         true / false / null, nesting, whitespace. Errors carry
                         the character position.
      * JSON.stringify - objects, arrays, strings, numbers, booleans, null.
                         Functions and undefined are omitted in objects (like the
                         standard) and become null in arrays.
                         No replacer function, no indent parameter: not needed
                         here, and leaving them out avoids surprises.

    Not supported on purpose: cyclic structures (throws), BigInt, Date via
    toJSON, __proto__ tricks.

    ExtendScript: ES3 safe (var, function, try/catch only).
    Included by: jsx/worker.jsx
*/

var PDCJson = (function () {

    var ESCAPABLE = {
        '"': '\\"',
        '\\': '\\\\',
        '\b': '\\b',
        '\f': '\\f',
        '\n': '\\n',
        '\r': '\\r',
        '\t': '\\t'
    };

    function quoteChar(c) {
        var mapped = ESCAPABLE[c];
        if (mapped) return mapped;
        var code = c.charCodeAt(0);
        if (code < 32) {
            var hex = code.toString(16);
            while (hex.length < 4) hex = "0" + hex;
            return "\\u" + hex;
        }
        return c;
    }

    function quoteString(s) {
        var out = ['"'];
        for (var i = 0; i < s.length; i++) out.push(quoteChar(s.charAt(i)));
        out.push('"');
        return out.join("");
    }

    function numberToString(n) {
        if (n !== n || n === Infinity || n === -Infinity) return "null";
        return String(n);
    }

    function stringifyValue(value, stack) {
        if (value === null) return "null";

        var t = typeof value;
        if (t === "undefined" || t === "function") return undefined;
        if (t === "boolean") return value ? "true" : "false";
        if (t === "number") return numberToString(value);
        if (t === "string") return quoteString(value);

        for (var s = 0; s < stack.length; s++) {
            if (stack[s] === value) throw new TypeError("JSON.stringify: cyclic structure");
        }
        stack.push(value);

        var out = [];
        var i;
        if (value instanceof Array) {
            for (i = 0; i < value.length; i++) {
                var item = stringifyValue(value[i], stack);
                out.push(item === undefined ? "null" : item);
            }
            stack.pop();
            return "[" + out.join(",") + "]";
        }

        for (var key in value) {
            if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
            var v = stringifyValue(value[key], stack);
            if (v === undefined) continue;
            out.push(quoteString(key) + ":" + v);
        }
        stack.pop();
        return "{" + out.join(",") + "}";
    }

    function stringify(value) {
        var s = stringifyValue(value, []);
        return (s === undefined) ? undefined : s;
    }

    /* ==================================================================
       JSON.parse
       ================================================================== */

    function parse(text) {
        if (typeof text !== "string") text = String(text);
        var at = 0;
        var len = text.length;

        function fail(message) {
            throw new SyntaxError("JSON.parse: " + message + " (position " + at + ")");
        }

        function charAt(i) { return text.charAt(i); }

        function skipWhitespace() {
            while (at < len) {
                var c = charAt(at);
                if (c === " " || c === "\t" || c === "\n" || c === "\r") { at++; continue; }
                break;
            }
        }

        function parseString() {
            if (charAt(at) !== '"') fail("expected a string");
            at++;
            var out = [];
            while (at < len) {
                var c = charAt(at);
                if (c === '"') { at++; return out.join(""); }
                if (c === "\\") {
                    at++;
                    var esc = charAt(at);
                    if (esc === "u") {
                        var hex = text.substr(at + 1, 4);
                        if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail("bad \\u escape");
                        out.push(String.fromCharCode(parseInt(hex, 16)));
                        at += 5;
                        continue;
                    }
                    var simple = { '"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t' };
                    if (!simple.hasOwnProperty(esc)) fail("bad escape \\" + esc);
                    out.push(simple[esc]);
                    at++;
                    continue;
                }
                if (c < " ") fail("unescaped control character");
                out.push(c);
                at++;
            }
            fail("unterminated string");
        }

        function parseNumber() {
            var start = at;
            if (charAt(at) === "-") at++;
            while (at < len && charAt(at) >= "0" && charAt(at) <= "9") at++;
            if (charAt(at) === ".") {
                at++;
                while (at < len && charAt(at) >= "0" && charAt(at) <= "9") at++;
            }
            if (charAt(at) === "e" || charAt(at) === "E") {
                at++;
                if (charAt(at) === "+" || charAt(at) === "-") at++;
                while (at < len && charAt(at) >= "0" && charAt(at) <= "9") at++;
            }
            var raw = text.substring(start, at);
            if (!/^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$/.test(raw)) fail("bad number '" + raw + "'");
            return Number(raw);
        }

        function parseValue() {
            skipWhitespace();
            var c = charAt(at);
            if (c === "{") return parseObject();
            if (c === "[") return parseArray();
            if (c === '"') return parseString();
            if (c === "-" || (c >= "0" && c <= "9")) return parseNumber();
            if (text.substr(at, 4) === "true") { at += 4; return true; }
            if (text.substr(at, 5) === "false") { at += 5; return false; }
            if (text.substr(at, 4) === "null") { at += 4; return null; }
            if (at >= len) fail("unexpected end of input");
            fail("unexpected character '" + c + "'");
        }

        function parseArray() {
            at++;
            var arr = [];
            skipWhitespace();
            if (charAt(at) === "]") { at++; return arr; }
            while (true) {
                skipWhitespace();
                arr.push(parseValue());
                skipWhitespace();
                var c = charAt(at);
                if (c === ",") { at++; continue; }
                if (c === "]") { at++; return arr; }
                fail("expected ',' or ']'");
            }
        }

        function parseObject() {
            at++;
            var obj = {};
            skipWhitespace();
            if (charAt(at) === "}") { at++; return obj; }
            while (true) {
                skipWhitespace();
                if (charAt(at) !== '"') fail("expected a property name");
                var key = parseString();
                skipWhitespace();
                if (charAt(at) !== ":") fail("expected ':' after property name");
                at++;
                skipWhitespace();
                obj[key] = parseValue();
                skipWhitespace();
                var c = charAt(at);
                if (c === ",") { at++; continue; }
                if (c === "}") { at++; return obj; }
                fail("expected ',' or '}'");
            }
        }

        var value = parseValue();
        skipWhitespace();
        if (at !== len) fail("trailing characters");
        return value;
    }

    return {
        stringify: stringify,
        parse: parse
    };
}());

/* Install only when Illustrator does not already provide a working JSON. */
if (typeof JSON === "undefined" || !JSON || typeof JSON.parse !== "function" || typeof JSON.stringify !== "function") {
    JSON = PDCJson;
}
