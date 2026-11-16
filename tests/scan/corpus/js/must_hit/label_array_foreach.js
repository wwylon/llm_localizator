// Flat header labels painted via forEach — activity table FN.
["Translator", "Changes", "By trigger", "Last activity"].forEach(function (label) {
  hr.appendChild(el("th", "", label));
});

// API-id + visible label tuples (not catalogue keys).
[["user", "By translator"], ["locale", "By locale"]].forEach(function (pair) {
  var a = el("a", "btn", pair[1]);
});

// Multiline el() third-arg concat (was invisible to the line regex).
tableWrap.appendChild(el(
  "div",
  "users-section-label",
  "Translators — " + count
));
