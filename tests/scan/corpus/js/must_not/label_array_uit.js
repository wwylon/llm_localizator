// Catalogue key + English fallback — body routes through uiT; do not FN-flag.
[
  ["act_col_translator", "Translator"],
  ["act_col_changes", "Changes"],
].forEach(function (row) {
  hr.appendChild(el("th", "", uiT(row[0], row[1])));
});

// Multiline el already routed.
wrap.appendChild(el(
  "div",
  "users-section-label",
  uiT("act_translators_count", "Translators — {n}").replace("{n}", "0"),
));
