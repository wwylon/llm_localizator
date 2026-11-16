from __future__ import annotations

import re

from llm_localizator.web.marketing import MARKETING_ROUTES, render_public


def test_tools_page_is_local_only() -> None:
    assert MARKETING_ROUTES["/tools"] == "tools"
    html = render_public("tools")
    assert "claude-sonnet-5" in html
    assert 'id="tool-cost"' in html
    script = html[html.index("<script>"):html.index("</script>")]
    assert not re.search(r"fetch\(|XMLHttpRequest|https?://|sendBeacon", script)
