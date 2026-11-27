/* Shared fetch / DOM helpers for the review UI (Waves 3 / B1). */
(function (global) {
  "use strict";

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "className") node.className = attrs[key];
        else if (key === "text") node.textContent = attrs[key];
        else if (key.slice(0, 2) === "on" && typeof attrs[key] === "function") {
          node.addEventListener(key.slice(2).toLowerCase(), attrs[key]);
        } else if (attrs[key] != null) node.setAttribute(key, attrs[key]);
      });
    }
    (children || []).forEach(function (child) {
      if (child == null) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function project() {
    var sel = document.getElementById("project-select");
    return (sel && sel.value) || (global.__LLM_PROJECT || "");
  }

  function authHeaders(extra) {
    var headers = { "Content-Type": "application/json" };
    if (global.__LLM_TOKEN) headers["X-LLM-Token"] = global.__LLM_TOKEN;
    if (extra) {
      Object.keys(extra).forEach(function (k) { headers[k] = extra[k]; });
    }
    return headers;
  }

  function params(obj) {
    return Object.keys(obj || {})
      .filter(function (k) { return obj[k] != null && obj[k] !== ""; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]); })
      .join("&");
  }

  function readJson(r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (!r.ok && data && typeof data === "object") {
        if (!data.error) data.error = "HTTP " + r.status;
        data.status = r.status;
        if (r.status === 401 || r.status === 403) {
          data.authError = true;
          try {
            if (global.LLMChrome && typeof global.LLMChrome.toast === "function") {
              global.LLMChrome.toast(
                r.status === 401
                  ? (global.uiT
                    ? global.uiT("api_sign_in_required", "Sign in required (session expired or missing token).")
                    : "Sign in required (session expired or missing token).")
                  : (global.uiT
                    ? global.uiT("api_not_allowed", "Not allowed for this account or locale.")
                    : "Not allowed for this account or locale."),
                "warn"
              );
            }
          } catch (err) { /* ignore */ }
        }
      }
      return data;
    });
  }

  function withSignal(init, signal) {
    init = init || {};
    if (signal) init.signal = signal;
    return init;
  }

  function apiGet(path, query, opts) {
    opts = opts || {};
    var qs = params(query);
    return fetch(
      path + (qs ? "?" + qs : ""),
      withSignal({ headers: authHeaders(opts.headers) }, opts.signal)
    ).then(readJson);
  }

  function apiPost(path, body, opts) {
    opts = opts || {};
    return fetch(path, withSignal({
      method: "POST",
      headers: authHeaders(opts.headers),
      body: JSON.stringify(body || {}),
    }, opts.signal)).then(readJson);
  }

  function apiBlob(path, query, opts) {
    opts = opts || {};
    var qs = params(query);
    return fetch(
      path + (qs ? "?" + qs : ""),
      withSignal({ headers: authHeaders(opts.headers) }, opts.signal)
    ).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          var err = new Error((data && data.error) || ("HTTP " + r.status));
          err.status = r.status;
          throw err;
        });
      }
      return r.blob();
    });
  }

  /**
   * POST with streaming response body (SSE / NDJSON). ``onChunk(text)`` gets
   * each decoded chunk; resolves with the Response when the stream ends.
   */
  function apiStream(path, body, onChunk, opts) {
    opts = opts || {};
    return fetch(path, withSignal({
      method: "POST",
      headers: authHeaders(opts.headers),
      body: JSON.stringify(body || {}),
    }, opts.signal)).then(function (r) {
      if (!r.ok || !r.body || !r.body.getReader) {
        return readJson(r).then(function (data) {
          if (data && data.error) throw new Error(data.error);
          return data;
        });
      }
      var reader = r.body.getReader();
      var decoder = new TextDecoder();
      function pump() {
        return reader.read().then(function (result) {
          if (result.done) {
            var tail = decoder.decode();  // flush a split multi-byte char
            if (tail && onChunk) onChunk(tail);
            return r;
          }
          if (onChunk) onChunk(decoder.decode(result.value, { stream: true }));
          return pump();
        });
      }
      return pump();
    });
  }

  function onProjectReady(fn) {
    var last = null;
    function run() {
      var name = project();
      if (!name || name === last) return;
      last = name;
      fn(name);
    }
    var sel = document.getElementById("project-select");
    if (sel) sel.addEventListener("change", run);
    run();
  }

  /**
   * Per-page load generation: bump on project change / remount so stale
   * responses from a prior project are ignored.
   */
  function requestScope() {
    var gen = 0;
    var controller = null;
    return {
      next: function () {
        gen += 1;
        if (controller) {
          try { controller.abort(); } catch (err) { /* ignore */ }
        }
        controller = typeof AbortController !== "undefined" ? new AbortController() : null;
        return { gen: gen, signal: controller && controller.signal };
      },
      isCurrent: function (token) {
        return token && token.gen === gen;
      },
      signal: function () {
        return controller && controller.signal;
      },
    };
  }

  global.LLMApi = {
    el: el,
    project: project,
    authHeaders: authHeaders,
    params: params,
    apiGet: apiGet,
    apiPost: apiPost,
    apiBlob: apiBlob,
    apiStream: apiStream,
    onProjectReady: onProjectReady,
    requestScope: requestScope,
  };
})(window);
