// Placeholder tokeniser and renderer (C-039). Loaded before editor.js.
// tokenize() returns [{kind, text}]; kind is "text" or one of
// icu | brace | mustache | printf | html | i18n | named.
// Rendering builds DOM nodes only (never innerHTML) and a click copies the token.
(function (root) {
  "use strict";

  var HTML_RE = /^<\/?[A-Za-z][^<>]*>/;
  var PRINTF_RE = /^%(?:\d+\$)?[-+ 0#]*\d*(?:\.\d+)?(?:ll|l|h)?[sdfiuxXeEgGcpo@]/;
  var I18N_RE = /^\$t\([^)]*\)/;
  var NAMED_RE = /^:[A-Za-z_]\w*/;

  // Index of the "}" closing the "{" at start, or -1 (brace depth aware).
  function closeAt(s, start) {
    var depth = 0;
    for (var i = start; i < s.length; i++) {
      if (s[i] === "{") depth++;
      else if (s[i] === "}") { depth--; if (depth === 0) return i; }
    }
    return -1;
  }

  var DNT_RE = /\btranslate\s*=\s*["']?no\b|\bclass\s*=\s*["'][^"']*\bnotranslate\b/i;

  // Length of a do-not-translate element opening at i (tag included), or 0 (C-034).
  function dntLength(s, i, tag) {
    if (!DNT_RE.test(tag)) return 0;
    if (/\/>$/.test(tag)) return tag.length;
    var name = /^<([A-Za-z][A-Za-z0-9]*)/.exec(tag)[1];
    var re = new RegExp("<(/?)" + name + "\\b[^<>]*?(/?)>", "gi");
    re.lastIndex = i + tag.length;
    var depth = 1, m;
    while ((m = re.exec(s))) {
      if (m[2]) continue;
      depth += m[1] ? -1 : 1;
      if (depth === 0) return m.index + m[0].length - i;
    }
    return 0;
  }

  function tokenize(text) {
    var s = String(text == null ? "" : text);
    var out = [];
    var buf = "";
    var i = 0;
    function flush() { if (buf) { out.push({ kind: "text", text: buf }); buf = ""; } }
    function push(kind, len) { flush(); out.push({ kind: kind, text: s.slice(i, i + len) }); i += len; }
    while (i < s.length) {
      var ch = s[i];
      var rest = s.slice(i);
      var m;
      if (ch === "{") {
        if (s[i + 1] === "{") {
          var end = s.indexOf("}}", i + 2);
          if (end > 0) { push("mustache", end + 2 - i); continue; }
        }
        var close = closeAt(s, i);
        if (close > 0) {
          var body = s.slice(i + 1, close);
          push(body.indexOf(",") >= 0 ? "icu" : "brace", close + 1 - i);
          continue;
        }
      } else if (ch === "<" && (m = HTML_RE.exec(rest))) {
        var dnt = dntLength(s, i, m[0]);
        if (dnt > 0) { push("dnt", dnt); continue; }
        push("html", m[0].length); continue;
      } else if (ch === "%") {
        if (s[i + 1] === "%") { buf += "%%"; i += 2; continue; }
        if ((m = PRINTF_RE.exec(rest))) { push("printf", m[0].length); continue; }
      } else if (ch === "$" && (m = I18N_RE.exec(rest))) {
        push("i18n", m[0].length); continue;
      } else if (ch === ":" && (m = NAMED_RE.exec(rest)) && (i === 0 || !/[\w:]/.test(s[i - 1]))) {
        push("named", m[0].length); continue;
      }
      buf += ch;
      i++;
    }
    flush();
    return out;
  }

  function copyToken(text) {
    try {
      if (root.navigator && root.navigator.clipboard) root.navigator.clipboard.writeText(text);
    } catch (err) { /* clipboard may be blocked; the click is a convenience */ }
  }

  // Append text to `parent` with each placeholder wrapped in <span class="ph ph-KIND">.
  function render(parent, text) {
    tokenize(text).forEach(function (tok) {
      if (tok.kind === "text") {
        parent.appendChild(root.document.createTextNode(tok.text));
        return;
      }
      var span = root.document.createElement("span");
      span.className = "ph ph-" + tok.kind;
      span.textContent = tok.text;
      span.title = (root.uiT || function (k, f) { return f != null ? f : k; })(
        "ph_click_copy",
        "Placeholder: click to copy",
      );
      span.addEventListener("click", function (e) { e.preventDefault(); copyToken(tok.text); });
      parent.appendChild(span);
    });
    return parent;
  }

  var api = { tokenize: tokenize, render: render };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.LLMPlaceholders = api;
})(typeof window !== "undefined" ? window : globalThis);
