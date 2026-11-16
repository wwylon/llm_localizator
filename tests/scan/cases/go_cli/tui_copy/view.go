package tui

import (
	"github.com/charmbracelet/bubbles/key"
	"github.com/charmbracelet/lipgloss"
)

var titleStyle = lipgloss.NewStyle().Bold(true)

var runKey = key.NewBinding(key.WithKeys("e"), key.WithHelp("e", "run with params"))

func header() string {
	return titleStyle.Render("Dangerous command ahead")
}

func empty() string {
	return "No targets found in Makefile."
}

func cacheKey() string {
	return "presets_cache_v2"
}
