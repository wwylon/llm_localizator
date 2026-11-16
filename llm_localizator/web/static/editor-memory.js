/* Editor memory-tab helpers (split from editor.js — Wave 2).
 *
 * Loaded before editor.js. Exposes window.LLMEditorMemory for paint helpers
 * that the main editor binds once the row pane is ready. Keeping concordance
 * UI here caps editor.js growth.
 */
(function (global) {
  "use strict";

  function uiT(key, fallback) {
    return (global.uiT && global.uiT(key, fallback)) || fallback || key;
  }

  global.LLMEditorMemory = {
    /** Placeholder — editor.js still owns paintTm until a follow-up moves the DOM. */
    ready: true,
    label: function () {
      return uiT("ed_memory", "Memory");
    },
  };
})(window);
