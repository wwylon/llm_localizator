"""Where each ecosystem puts text in front of a person (UI sinks).

The shared literal detector reports any prose string at low confidence. A literal handed to one of these calls is
known to be shown to a user, so it is reported at medium (high when it reads as prose). Routed calls (already
translated) and log calls are handled in ``literals.py``.

Add an ecosystem by adding one regex: it is matched against the part of the statement before the literal.
"""

from __future__ import annotations

import re

__all__ = ["ui_sink_before"]

_SINKS: dict[str, re.Pattern[str]] = {
    "java": re.compile(
        r"JOptionPane\.\w+\(|\.set(?:Text|Title|ToolTipText|Message|Label|ContentText|HeaderText)\(|Toast\.makeText\(|"
        r"new\s+(?:JLabel|JButton|JMenuItem|JMenu|Label|Button|MenuItem|Alert|Tooltip)\(|Snackbar\.make\(|"
        # Swing, JavaFX and Vaadin: any widget class named for what it shows (``new ModernButton("Create")``), and the
        # setters that give a field its placeholder, header or helper text.
        r"new\s+\w*(?:Label|Button|MenuItem|CheckBox|Checkbox|RadioButton|TextField|Tab|Span|Paragraph|Notification)\(|"
        r"\.set(?:Placeholder|PromptText|Header|HelperText|ErrorMessage|Caption|HelpText|ButtonText|DialogTitle)\(|Notification\.show\(|"
        # Status and error helpers named for what they show, file-chooser filters and titled borders (first argument).
        r"\b(?:update|show|set)(?:Status|StatusText|Error|ErrorDialog|Warning|Info|Message|Notification)\(|\bsendError\(|"
        # A project's own output-pane helpers (``appendProgress("Building…")``) and alert/dialog helpers.
        r"\bappend(?:Progress|Output|Console|Status|Message|Result)s?\(|\bshow(?:Alert|Dialog|Confirm|Toast|Popup|Prompt)\w*\(|"
        r"new\s+[\w.]*(?:ExtensionFilter|FileFilter)\(|new\s+\w*(?:Titled|Labeled)Border\(|createTitledBorder\(|"
        # An enum constant with a display name (``NONE("None", "Don't compress"),``), widget-factory helpers
        # (``getDirectorySelectWidget(dir, "Choose folder")``) and progress-monitor task names.
        r"^\s*[A-Z][A-Z0-9_]+\(|\b(?:get|make|create|build)\w+(?:Widget|Container|Header)\(|"
        r"\b(?:beginTask|subTask)\(|\bmonitor\.begin\(|"
        r"\.(?:addMessage|addFlashAttribute|rejectValue)\(|"
        r"\.set(?:ContentTitle|ContentText|ContentInfo|SubText|Ticker|BigText)\(|new\s+NotificationChannel\("
    ),
    "kotlin": re.compile(
        r"Toast\.makeText\(|Snackbar\.make\(|\bText\(|\.text\s*=|\.set(?:Text|Title|Message)\(|contentDescription\s*=|"
        r"\b(?:label|title|text|hint|placeholder|channelName|channelDescription|description)\s*=|"
        r"\.(?:setTitle|setMessage|setContentTitle|setContentText|setContentInfo|setSubText)\(|\bNotificationChannel\("
    ),
    "swift": re.compile(
        r"\b(?:Text|Button|Label|TextField|SecureField|Section|Toggle|Picker|Link|Menu|CommandMenu|CommandGroup|Stepper|"
        r"Slider|GroupBox|DisclosureGroup|TabItem|NavigationLink|\w+Picker|\w+Button|\w+Menu|\w+Toggle|\w+Field)\(|"
        r"\.(?:text|title|placeholder|subtitle|messageText|informativeText|stringValue)\s*=|"
        r"\.set(?:Title|AttributedTitle)\(|UIAlertController\(|"
        r"\.(?:alert|navigationTitle|navigationBarTitle|confirmationDialog|help|badge|accessibilityLabel|accessibilityHint|"
        r"accessibilityValue|tabItem|navigationSubtitle|searchable|prompt|toolbarTitle|"
        # WidgetKit / App Intents: the widget gallery shows these (B20).
        r"configurationDisplayName|description)\(|"
        r"\b(?:title|message|subtitle|placeholder|prompt|description|informativeText|messageText|buttonTitles?|"
        r"headline|detail|summary)\s*:|"
        r"\berrorDescription\b"
    ),
    "csharp": re.compile(
        r"MessageBox\.Show\(|DisplayAlert\(|(?:\.|\b)\w*(?:Text|Title|Content|Header|ToolTip|Caption|Label|Message|Description)\s*=(?!=)|"
        r"\b(?:SetBusy|ShowMessage|ShowError|ShowDialog|Notify|ShowToast|Growl\.\w+)\(|"
        r"new\s+(?:Label|Button|MenuItem|ToolStripMenuItem)\(|AddModelError\(|TempData\[|ViewBag\.\w+\s*=|"
        # B24: enum labels shown in pickers, WPF validation results, and progress/status event args the UI displays.
        r"\[(?:Description|Display(?:Name)?)\(\s*(?:Name\s*=\s*)?|new\s+ValidationResult\(\s*false\s*,\s*|"
        r"new\s+\w*(?:Progress|Status|Message|Notification)\w*(?:Args|EventArgs)\("
    ),
    "dart": re.compile(
        r"\b(?:Text|SnackBar|AlertDialog|ElevatedButton|TextButton|Tooltip|Chip)\(|"
        r"\b(?:hintText|labelText|helperText|errorText|title|tooltip|content|label|semanticLabel|text|message|description|subtitle)\s*:|"
        # Pool D: notification/status named args, and switch arms that map an enum or id to its label.
        r"\b(?:body|detail|headline|caption|barrierLabel|emptyText)\s*:|^\s*(?:\w+\.\w+|'[\w-]+')\s*=>\s*|"
        # A text constant named for what it is: ``static const String agenda_text = "Agenda"``.
        r"\b(?:static\s+)?(?:const|final)\s+(?:String\s+)?\w*(?:_text|Text|_title|Title|_label|Label)\s*=\s*|"
        r"\bGButton\(|\bthrow\s+(?:Exception\()?"
    ),
    "go": re.compile(
        r"http\.Error\(|fmt\.Fprint(?:f|ln)?\(\s*w\b|\.(?:JSON|String|HTML|AbortWithStatusJSON)\(|"
        r"\"(?:error|message|msg|detail)\"\s*:|\bNew\w*Error\(|"
        # CLI help: cobra.Command / urfave cli fields and flag usage strings (pflag, stdlib flag, urfave Flag structs).
        r"\b(?:Short|Long|Example|Usage|UsageText|ArgsUsage|Description|Deprecated)\s*:\s*|"
        r"\b\w*(?:[mM]sg|Message|[uU]sage|Help)\w*\s*:?=\s*$|"   # const msgWelcome = `…` (the literal is the whole value)
        # Terminal UIs (pool D): lipgloss/bubbletea render calls, key help, termui/tview widget text, struct labels.
        r"\.Render\(|\bkey\.WithHelp\(|\.SetErrorString\(|\bWriteString\(\s*&?\w+\s*,\s*|"
        r"\.(?:Title|Header|Labels|Placeholder|Prompt|Text|EmptyText)\s*=\s*(?:\[\]string\{)?|"
        r"\b(?:Label|Title|Placeholder|Prompt)\s*:\s*|\b\w*(?:[hH]elp|[eE]mpty)Text\s*:?=\s*|"
        r"\b(?:flags?|\w*Flags\(\))\.(?:String|Bool|Int|Int32|Int64|Uint|Float64|Duration|Count|StringSlice|StringArray|IntSlice)(?:Var)?P?\("
    ),
    "cpp": re.compile(
        r"QMessageBox::\w+\(|\.?set(?:Text|WindowTitle|ToolTip|PlaceholderText|StatusTip|Title|Label)\(|"
        r"\bQ(?:Label|PushButton|Action|CheckBox|RadioButton|GroupBox)\(|\bwx(?:MessageBox|StaticText|Button)\(|"
        r"\.addAction\(|fl_message\(|MessageBox\w*\("
    ),
    "ruby": re.compile(
        r"flash(?:\.now)?\[:\w+\]\s*=|\brender\s+(?:json|plain|html):|\bnotice:|\balert:|\.errors\.add\(|\bputs\b|"
        r"\b(?:message|error|title|label|placeholder):|\berrors\.add\(|"
        r"\b(?:description|short_description)\s*(?:\(\s*)?(?:<<[~-]?\w+)?\s*$|"
        # Rails view helpers (templates hand their code lines to this pass): the text argument is the label.
        r"\b(?:link_to(?:_if|_unless)?|button_to|button_tag|submit_tag|label_tag|mail_to|content_tag)\b|"
        r"\.(?:submit|label|button)\b|\b(?:confirm|prompt|include_blank|disable_with|hint):"
    ),
    "rust": re.compile(
        r"\b(?:println|eprintln|print)!\(|\b(?:Label|Button|Text|CheckButton|MenuItem)::new\(|"
        r"\.set_(?:label|text|title|tooltip_text|placeholder_text)\(|\bMessageDialog\w*|\.title\(|"
        r"\bSpan::(?:styled|raw)\(|\bLine::(?:from|raw|styled)\(|\bParagraph::new\(|\bCell::from\(|\bListItem::new\(|"
        r"\bTitle::from\(|\bRow::new\(|\bCell::new\(|\bheader\b|\bErr\(|\banyhow!\(|\bbail!\(|\beyre!\(|\.wrap_err\(|\.with_context\(|\.context\(|\berr_title\s*="
    ),
    "scala": re.compile(r"\b(?:Ok|BadRequest|NotFound|Forbidden)\(|\.flashing\(|\bflash\(|println\("),
    "gdscript": re.compile(
        # Control text (``label.text = "…"``, ``$Title.text = …``), window titles, dialogs, tooltips, rich text.
        r"\.\w*(?:[tT]ext|[tT]itle|[lL]abel|[mM]essage)\w*\s*\+?=(?!=)\s*|"
        r"\b(?:set_text|set_title|set_tooltip_text|append_text|add_text|push_notification|add_item|add_tab|"
        r"set_item_text|add_check_item|add_radio_check_item|popup_dialog|show_message|notify)\(|"
        r"\b(?:text|title|tooltip_text|placeholder_text|dialog_text|window_title)\s*=\s*$"
    ),
    "lua": re.compile(r"\bprint\(|\.text\s*=|\bnotify\(|\bsetText\(|\bmessage\("),
    "elixir": re.compile(r"\bput_flash\(|\bIO\.puts\(|\bsend_resp\(|\bjson\(|\b(?:message|error|title|label):"),
    "php": re.compile(
        r"\becho\b|\bprint\b|->(?:with|flash|error|warning|success|info|setFlash|addFlash)\(|\babort\(|"
        r"->json\(|Session::flash\(|['\"](?:message|error|status_message)['\"]\s*=>"
    ),
}

#: Readable names of the calls and properties each sink table covers (help pages). A test checks that the table
#: matches every name here, so the list cannot drift from the regex.
SINK_LABELS: dict[str, tuple[str, ...]] = {
    "java": ("JOptionPane.showMessageDialog(", "Toast.makeText(", "Snackbar.make(", ".setText(", ".setTitle(", ".setToolTipText(",
             "new JLabel(", "new JButton(", ".setContentTitle("),
    "kotlin": ("Toast.makeText(", "Snackbar.make(", "Text(", ".setText(", "contentDescription =", "label =", "hint =",
               ".setContentTitle("),
    "swift": ("Text(", "Button(", "Label(", "TextField(", "Toggle(", ".navigationTitle(", ".alert(", "UIAlertController(",
              "title:", "message:", "placeholder:", ".text ="),
    "csharp": ("MessageBox.Show(", "DisplayAlert(", "Title =", "Text =", "Content =", "ToolTip =", "AddModelError("),
    "dart": ("Text(", "SnackBar(", "AlertDialog(", "Tooltip(", "hintText:", "labelText:", "title:", "message:"),
    "go": ("http.Error(", "c.JSON(", "\"error\":", "\"message\":", ".Render(", "key.WithHelp(", ".Title =", "Label:"),
    "cpp": ("QMessageBox::warning(", ".setText(", "setWindowTitle(", "setToolTip(", "QLabel(", "QPushButton(", "wxMessageBox("),
    "ruby": ("flash[:notice] =", "render json:", ".errors.add(", "notice:", "alert:"),
    "rust": ("println!(", "Label::new(", "Button::new(", ".set_label(", "Paragraph::new(", "bail!(", "anyhow!("),
    "php": ("echo", "->with(", "->flash(", "abort(", "->json(", "'message' =>"),
    "gdscript": (".text =", ".title =", ".tooltip_text =", "set_text(", "add_item("),
}


#: A language that shares an ecosystem table with another.
_ALIASES = {"objc": "swift"}


def ui_sink_before(lang_id: str, line: str, literal: str) -> str | None:
    """The sink call that precedes *literal* on its line, or None."""
    pattern = _SINKS.get(_ALIASES.get(lang_id, lang_id))
    if pattern is None:
        return None
    first = literal.split("\n", 1)[0] if literal else ""
    pos = line.find(literal if "\n" not in literal else first) if first else -1  # a raw string spans lines
    if "\n" in (literal or "") and not first.strip() and line.rstrip()[-1:] in ("`", '"', "'"):
        pos = len(line.rstrip())   # ``msg = `\n…``: the literal opens at the end of the line
    if pos > 0 and line[pos - 1] in "`\"'":
        pos -= 1
    prefix = line[:pos] if pos > 0 else line
    # The innermost sink is the one nearest the literal: ``Text(viewModel.title(for: "Save"))`` → ``title``-less
    # ``Text(`` is too far out when a closer one exists (M2: the first match on the line won).
    match = None
    for match in pattern.finditer(prefix):
        pass
    return match.group(0).rstrip("(= :") if match else None
