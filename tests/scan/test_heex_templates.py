"""Phoenix HEEx/EEx templates are scanned: tags like ERB plus ``{expr}`` interpolation."""

from __future__ import annotations

from llm_localizator.scan.source import SourceScanner

TEMPLATE = """<h1>Winners</h1>
<%!-- an internal note, not copy --%>
<p>Won by {@winner.name}</p>
<.button phx-click="draw">Draw prizes</.button>
<%= for user <- @users do %>
  <span class="name">{user.name}</span>
<% end %>
<input placeholder="Your name" />
"""


def test_visible_text_and_placeholders_are_found_and_comments_are_not(tmp_path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "show.html.heex").write_text(TEMPLATE, encoding="utf-8")
    result = SourceScanner(tmp_path, ["lib"]).scan()
    texts = {hit.text for hit in result.hardcoded}
    assert {"Won by {x}", "Draw prizes", "Your name"} <= texts
    assert not any("internal note" in text for text in texts)
    assert not result.skipped
