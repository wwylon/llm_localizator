/* Accessibility helpers shared by every page: a polite live region for status messages, column scopes on table
   headers, and window.LLMA11y.announce(text) for scripts that want to say something to a screen reader. */
(function () {
  "use strict";
  if (typeof document === "undefined") return;

  var live = null;
  var lastText = "";
  var lastAt = 0;

  function region() {
    if (live) return live;
    live = document.createElement("div");
    live.id = "a11y-live";
    live.className = "sr-only";
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");
    live.setAttribute("aria-atomic", "true");
    document.body.appendChild(live);
    return live;
  }

  function announce(text) {
    text = String(text || "").replace(/\s+/g, " ").trim().slice(0, 200);
    if (!text) return;
    var now = Date.now();
    if (text === lastText && now - lastAt < 1500) return;
    lastText = text;
    lastAt = now;
    var node = region();
    node.textContent = "";
    window.setTimeout(function () { node.textContent = text; }, 30);
  }

  var STATUS = '[role="alert"], [role="status"]:not(#a11y-live), .error, .err, .pc-status, [class*="status"], ' +
    '[class*="-err"], [class*="-msg"]';

  function scopeHeaders(root) {
    var heads = root.querySelectorAll ? root.querySelectorAll("th:not([scope])") : [];
    for (var i = 0; i < heads.length; i++) {
      var th = heads[i];
      var cells = th.parentNode ? th.parentNode.querySelectorAll("td").length : 0;
      th.setAttribute("scope", th.closest("thead") || !cells ? "col" : "row");
    }
  }

  function onAdded(node) {
    if (node.nodeType !== 1) return;
    if (node.id === "a11y-live" || node.closest("#a11y-live")) return;
    if (node.matches && node.matches(STATUS)) announce(node.textContent);
    scopeHeaders(node);
  }

  function start() {
    scopeHeaders(document);
    if (typeof MutationObserver === "undefined") return;
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var added = records[i].addedNodes;
        for (var j = 0; j < added.length; j++) onAdded(added[j]);
      }
    }).observe(document.body, { childList: true, subtree: true });
  }

  window.LLMA11y = { announce: announce };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
