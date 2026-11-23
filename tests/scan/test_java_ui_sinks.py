"""Java UI sinks: Swing, JavaFX and Vaadin widget constructors and text setters."""

from __future__ import annotations

import pytest

from llm_localizator.scan.ecosystems import _SINKS

SHOWN = [
    'new ModernButton("Create")',
    'new LargeModernLabel("Status")',
    'field.setPlaceholder("Search")',
    'grid.addColumn(Item::name).setHeader("Name")',
    'Notification.show("Saved")',
    'new Span("Hello")',
]
NOT_SHOWN = ['log.info("starting")', 'new Foo("bar")', 'map.put("key", value)']


@pytest.mark.parametrize("line", SHOWN)
def test_widget_constructors_and_setters_are_sinks(line: str) -> None:
    assert _SINKS["java"].search(line)


@pytest.mark.parametrize("line", NOT_SHOWN)
def test_logging_and_plain_objects_are_not_sinks(line: str) -> None:
    assert not _SINKS["java"].search(line)
