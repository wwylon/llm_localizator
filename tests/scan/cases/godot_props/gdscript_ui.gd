extends Control

@onready var score_label: Label = $Score

func _on_score_changed(score: int) -> void:
	score_label.text = "Score: " + str(score)

func _ready() -> void:
	$Window.title_text = "Settings Menu"
	$Popup.add_item("Rename file")
	print("loaded settings scene in debug mode")
	var node_name := "SettingsPanel"
