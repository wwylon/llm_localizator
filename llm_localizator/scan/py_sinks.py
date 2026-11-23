"""People-facing English in Python server code (B3, ADR-134).

The static scanners read front-end files. Text the server writes into a response
(an ``HTTPException`` detail, ``{"error": "…"}``, a flashed message) reaches the screen
through the front end, where the QA crawl sees it as "dynamic" and cannot locate it.
This pass finds those strings in ``[scan] server_dirs`` with the ``ast`` module.

Sinks:

* ``HTTPException(status, "msg")`` / ``HTTPException(detail="msg")`` and the same for
  ``abort(…)`` (Flask) and ``web.HTTP*(text=…/reason=…)`` (aiohttp);
* a dict literal key from ``COPY_FIELDS`` (``detail``, ``error``, ``message`` …) with a
  string value, anywhere (return values, ``JSONResponse``, ``jsonify``);
* ``flash("msg")``.

Only string literals and the literal parts of f-strings count. A value must hold a
word of three or more letters. Strings already passed through ``_()``/``gettext`` are
not literals here, so they are not reported.

Pure: source text in, findings out.
"""

from __future__ import annotations

import ast
import builtins
import functools
import re
from dataclasses import dataclass

from .dynamic_origin import COPY_FIELDS

__all__ = ["ServerString", "server_strings", "dev_strings"]

#: ``ValidationError`` (Django, DRF, marshmallow): its message is shown next to the form field (B15).
_EXC_NAMES = frozenset({"HTTPException", "abort", "HTTPError", "BadRequest", "NotFound", "Forbidden", "ValidationError"})
#: Decorators whose ``description=`` the Django admin shows: ``@admin.action``, ``@admin.display`` (B15).
_ADMIN_DECORATORS = frozenset({"action", "display"})
#: Base classes of CLI commands whose ``help = "…"`` attribute is printed by ``--help`` (B15).
_COMMAND_BASES = frozenset({"BaseCommand", "AppCommand", "LabelCommand"})
_EXC_KWARGS = frozenset({"detail", "description", "desc", "text", "reason", "message", "msg"})
_WORD = re.compile(r"[^\W\d_]{3,}")
#: Config keys whose default value is copy: ``setdefault("TABLE_VIEW_TITLE", "View")``.
_COPY_KEY = re.compile(r"(?:TITLE|LABEL|TEXT|MESSAGE|HEADING|CAPTION|PLACEHOLDER|TOOLTIP|HINT)S?$")
_LOG_OBJECTS = frozenset({"log", "logger", "logging", "_log", "_logger", "LOG", "LOGGER", "warnings"})
_LOG_METHODS = frozenset({
    "debug", "info", "warning", "warn", "error", "exception", "critical", "fatal", "log", "print",
})


@dataclass(frozen=True)
class ServerString:
    line: int
    text: str
    sink: str  # "exception", "payload:<field>", "flash"


#: Chat-bot and desktop-UI helpers whose string arguments are shown to a person (Discord/Telegram bots, Kivy/Tk toasts).
_CHAT_RECEIVER = re.compile(r"(?:ctx|channel|interaction|followup|response|webhook|author|user|member|thread|dm|message|recipient|msg)")
_CHAT_CALLS = frozenset({"send_message", "reply", "respond", "send_modal", "edit_message", "add_field", "set_footer", "set_author"})
_CHAT_KWARGS = frozenset({"content", "title", "description", "name", "value", "text", "message", "footer", "label", "placeholder"})
_UI_HELPER = re.compile(
    r"(?:toast|dialog|snack|popup|show_(?:msg|message|error|info|alert|success|warning|status|notification)|notify_user)", re.I,
)
#: Chat-bot command decorators whose docstring the bot's help command shows (not ``click``: CLI help is judged elsewhere).
_DOC_DECORATOR = re.compile(r"(?:commands\.(?:command|group|hybrid_command|hybrid_group)|app_commands|slash_command|context_menu|\bbot\.(?:command|group)|\btree\.command)")
#: Exception classes whose message a project shows to its users (pool D: ``raise BotError("Bot is not ready yet.")``
#: reaches Discord through ``str(error)``). Builtin and library errors stay developer text.
#: A module of a chat bot: it imports a bot framework (bare ``send(…)`` is then a bound ``ctx.send``).
_CHAT_MODULE = re.compile(
    r"^\s*(?:import|from)\s+(?:discord|nextcord|disnake|hikari|interactions|telegram|aiogram|telebot|slack_bolt)\b",
    re.M,
)
_USER_EXC = re.compile(
    r"^(?:User|Bot|Friendly|Public|Display|Client|Chat)\w*(?:Error|Exception)$|^\w*UserError$|"
    # Web-service errors named after an HTTP status: their message is the API response body (pool E: critiquebrainz).
    r"^(?:InvalidRequest|LimitExceeded|AccessDenied|NotAuthorized|Unauthorized|PermissionDenied|MethodNotAllowed|"
    r"TooManyRequests|Conflict|Gone|UnprocessableEntity|ServiceUnavailable)\w*$"
)


def _user_exception(name: str) -> bool:
    """A raised class whose message reaches a person (HTTP errors, project user-error classes)."""
    return name in _EXC_NAMES or (name.startswith("HTTP") and name[4:5].isupper()) or bool(_USER_EXC.match(name))


def _receiver(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        try:
            return ast.unparse(func.value).lower()
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _callee(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _text(node: ast.AST | None) -> str | None:
    """The literal text of a str constant or f-string (holes as ``{…}``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{…}")
        return "".join(parts)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format"
            and isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)):
        return node.func.value.value   # ``"You already reviewed this {entity}".format(entity=…)``
    return None


#: Keyword arguments that hold text a person reads: Django/Wagtail model and form fields, Discord slash-command
#: descriptions. A literal given to one of them is copy (medium confidence).
_UI_KWARGS = frozenset({
    "verbose_name", "verbose_name_plural", "help_text", "placeholder", "empty_label", "heading", "short_description",
})


def _has_word(text: str) -> bool:
    """A word of three letters or marks, or two in an ideographic script (``保存``, ``저장``)."""
    from ..core.quality import char_script
    from .prose import is_short_label, letter_mark_count

    if letter_mark_count(text) >= 3 or is_short_label(text):
        return True
    if len(text.strip()) == 1 and any(char_script(ch) == "cjk" for ch in text):
        return True  # one ideograph is a whole label
    return letter_mark_count(text) >= 2 and any(char_script(ch) == "cjk" for ch in text)


def _keep(text: str | None) -> bool:
    return bool(text) and _has_word(text) and not text.strip().startswith(("/", "http"))


@functools.lru_cache(maxsize=2)
def _parse(source: str) -> ast.Module | None:
    """One parse per module: ``dev_strings`` and ``server_strings`` both read the same file (M4). Neither changes the
    tree, so sharing it is safe."""
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def server_strings(source: str, *, gui_project: bool = False) -> list[ServerString]:
    """Every people-facing string literal in one Python module."""
    tree = _parse(source)
    if tree is None:
        return []
    out: list[ServerString] = []
    seen: set[tuple[int, str]] = set()
    chat_module = _CHAT_MODULE.search(source) is not None

    def add(node: ast.AST, text: str | None, sink: str) -> None:
        if _keep(text) and (node.lineno, text) not in seen:
            seen.add((node.lineno, text))
            out.append(ServerString(node.lineno, " ".join(text.split()), sink))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _callee(node)
            if _user_exception(name):
                for arg in node.args:
                    text = _text(arg)
                    if text and re.fullmatch(r"[a-z][a-z0-9_]*", text):
                        continue   # ``InvalidRequest('own')``: an error code, not a message
                    add(arg, text, "exception")
                for kw in node.keywords:
                    if kw.arg in _EXC_KWARGS:
                        add(kw.value, _text(kw.value), "exception")
            elif name == "__init__" and {kw.arg for kw in node.keywords} & {"status", "status_code", "http_status"}:
                # ``super().__init__(code="denied", desc="Access denied", status=403)``: a web-service error class.
                for kw in node.keywords:
                    if kw.arg in _EXC_KWARGS:
                        add(kw.value, _text(kw.value), "exception")
            elif name == "flash" and node.args:
                add(node.args[0], _text(node.args[0]), "flash")
            elif name == "setdefault" and len(node.args) >= 2:
                key = _text(node.args[0])
                if key and _COPY_KEY.search(key.upper()):
                    add(node.args[1], _text(node.args[1]), "config-default")
            chat = (name in _CHAT_CALLS or (name == "send" and _CHAT_RECEIVER.search(_receiver(node)))
                    or (name == "send" and isinstance(node.func, ast.Name) and chat_module)
                    or bool(_UI_HELPER.search(name)))
            if chat and not _is_log_call(node):
                for arg in node.args:
                    add(arg, _text(arg), f"chat:{name}")
                for kw in node.keywords:
                    if kw.arg in _CHAT_KWARGS:
                        add(kw.value, _text(kw.value), f"chat:{name}")
            elif name == "Embed":
                for kw in node.keywords:
                    if kw.arg in {"title", "description"}:
                        add(kw.value, _text(kw.value), "chat:Embed")
            for kw in node.keywords:
                if (kw.arg in _UI_KWARGS or name.endswith("describe")) and kw.arg and not _is_log_call(node):
                    add(kw.value, _text(kw.value), f"kwarg:{kw.arg}")
                elif kw.arg == "description" and name in _ADMIN_DECORATORS:
                    add(kw.value, _text(kw.value), "kwarg:description")
                elif kw.arg == "description" and _DOC_DECORATOR.search(ast.unparse(node.func)):
                    add(kw.value, _text(kw.value), "command-help")  # slash-command description in the client's picker
        elif isinstance(node, ast.ClassDef) and _is_qt_backend(node):
            # A QObject that QML binds to (B18): text it stores in ``self.<attr>`` or hands to ``self.<method>(…)`` /
            # ``signal.emit(…)`` is what the QML labels show.
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and any(
                    isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self"
                    for t in sub.targets
                ):
                    _add_if_label(add, sub.value)
                elif isinstance(sub, ast.Call) and not _is_log_call(sub) and isinstance(sub.func, ast.Attribute) and (
                    sub.func.attr == "emit"
                    or (isinstance(sub.func.value, ast.Name) and sub.func.value.id == "self")
                ):
                    for arg in sub.args:
                        _add_if_label(add, arg)
        elif isinstance(node, ast.ClassDef) and any(
            (b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else "") in _COMMAND_BASES
            for b in node.bases
        ):
            # A shipped management command: its ``help`` and argument help are what ``--help`` prints. Argparse help in
            # other scripts (release tooling, dev helpers) is developer text and stays low.
            for stmt in node.body:
                if (isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "help" for t in stmt.targets)):
                    add(stmt.value, _text(stmt.value), "cli-help")
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and _callee(sub) == "add_argument":
                    for kw in sub.keywords:
                        if kw.arg == "help":
                            add(kw.value, _text(kw.value), "cli-help")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and any(_DOC_DECORATOR.search(ast.unparse(d)) for d in node.decorator_list):
                first = node.body[0]
                doc = ast.get_docstring(node, clean=True)
                if doc and isinstance(first, ast.Expr):
                    paragraph = re.split(r"\n\s*\n", doc)[0]
                    add(first, paragraph, "command-help")  # shown by the bot's help command
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2:
            first, second = node.value.elts
            if isinstance(first, ast.Constant) and first.value in (False, None):
                add(second, _text(second), "return-tuple")  # ``return False, "Invalid API token"``
            elif isinstance(first, ast.Constant) and first.value is True and len((_text(second) or "").split()) >= 2:
                add(second, _text(second), "return-tuple")  # ``return True, "Capabilities set successfully"``
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                field = _text(key) if key is not None else None
                if field and field.casefold() in COPY_FIELDS:
                    add(value, _text(value), f"payload:{field}")
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in _MESSAGE_VARS):
            text = _text(node.value)
            if _prose_message(text):
                add(node.value, text, "message-variable")  # ``msg = "Port must be between 1 and 65535"``
    desktop_module = _DESKTOP_MODULE.search(source) is not None
    if desktop_module:
        for node in ast.walk(tree):
            _desktop_strings(node, add)
    if desktop_module or gui_project:
        for node in ast.walk(tree):
            _gui_project_strings(node, add, desktop_module=desktop_module, gui_project=gui_project)
    if gui_project:
        developer = dev_strings(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                text = _text(node)
                if text and _gui_message(text) and (node.lineno, " ".join(text.split())) not in developer:
                    add(node, text, "gui-fstring")  # ``f"Error: {exc}"`` in a desktop app is a status or dialog message
    out.sort(key=lambda s: s.line)
    return out


_GUI_MESSAGE = re.compile(r"\W*[A-Z][a-z]{2,}[\s:,.!]")
_CODE_LIKE = re.compile(r"://|\b(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b|[\\/]\w+\.\w+|--\w|\$\{|\b\w+\(\)")


def _gui_message(text: str) -> bool:
    """A formatted sentence or label (``Error: {x}``, ``Chapters ({x})``): a capitalised word, then more, and a placeholder."""
    if "{" not in text or len(text) > 140 or not _GUI_MESSAGE.match(text) or _CODE_LIKE.search(text):
        return False
    return len(re.findall(r"[^\W\d_]{3,}", re.sub(r"\{[^}]*\}", " ", text))) >= 1


#: A desktop GUI module: it imports Tk, Qt, wx, Kivy or Toga. Only then are the widget calls below read as UI text.
_DESKTOP_MODULE = re.compile(
    r"^\s*(?:import|from)\s+(?:tkinter|Tkinter|customtkinter|PyQt[4-6]|PySide[2-6]|wx|kivy|toga|flet|qt|slicer|ctk)\b", re.M,
)
#: Widget constructors whose first positional argument, or ``text=``/``label=``, is the visible caption.
_DESKTOP_WIDGET = re.compile(
    r"(?:Button|Label|Checkbutton|Radiobutton|CheckBox|RadioButton|GroupBox|LabelFrame|Action|Menu|MenuItem|"
    r"StaticText|ToolButton|Message|Text|Tab|Chip|Tooltip|Option|Banner|SnackBar|Title)$"
)
#: Methods that take the text to show (menu entries, window titles, tooltips, list items, tab names, header labels).
_DESKTOP_SETTERS = frozenset({
    "add_command", "add_cascade", "add_checkbutton", "add_radiobutton", "addAction", "addMenu", "addItem", "addItems",
    "addTab", "insertTab", "setWindowTitle", "setText", "setToolTip", "setPlaceholderText", "setStatusTip",
    "setTitle", "setLabel", "setHeaderLabels", "setHorizontalHeaderLabels", "setVerticalHeaderLabels", "setWhatsThis",
    "SetLabel", "SetTitle", "SetToolTip", "SetStatusText", "showMessage", "setButtonText", "setLabelText",
    "setInformativeText", "title", "wm_title", "addRow",
})
#: Qt dialog statics whose title, label and filter arguments are shown: ``QInputDialog.getText(self, "Add", "Prefix:")``,
#: ``QFileDialog.getSaveFileName(self, "Save as")``. The receiver has to say it is a dialog.
_DIALOG_STATICS = frozenset({
    "getText", "getInt", "getDouble", "getItem", "getMultiLineText", "getOpenFileName", "getOpenFileNames",
    "getSaveFileName", "getExistingDirectory",
})
_DESKTOP_KWARGS = frozenset({
    "text", "label", "title", "tooltip", "tip", "placeholder", "caption", "hint_text", "helper_text", "subtitle",
    "content",
})
#: Keyword arguments that hold visible text on any call in a GUI project (a settings-row or card class of the app's
#: own: ``SettingField(label="Port", tooltip="Default is 7777.")``).
_GUI_TEXT_KWARGS = frozenset({
    "label", "tooltip", "placeholder", "hint", "hint_text", "helper_text", "caption", "subtitle", "title", "description",
})
#: ``front_tooltip=``, ``submit_label=``: a keyword named for what it holds. These need a capitalised value.
_GUI_TEXT_SUFFIXES = ("_tooltip", "_label", "_text", "_title", "_hint", "_caption", "_placeholder")
#: Keyword lists of display strings: ``options=["Relative", "Absolute"]``.
_GUI_LIST_KWARGS = frozenset({"options", "choices", "items", "labels", "headers"})
#: Variables that hold an error or status sentence (``msg = "Port must be between 1 and 65535"``): any Python project.
_MESSAGE_VARS = frozenset({"msg", "message", "error_msg", "error_message", "err_msg", "detail", "reason"})
#: Variables that hold a caption in a GUI module (``desc = "Default is 7777."``, ``tooltip = "..."``).
_CAPTION_VARS = frozenset({"desc", "tooltip", "label", "title", "hint", "caption"})
#: Attributes a GUI module assigns visible text to (``page.title = "Dashboard"``, ``status.value = "Connected"``).
_CAPTION_ATTRS = frozenset({
    "title", "text", "label", "tooltip", "hint_text", "helper_text", "placeholder", "caption", "subtitle", "value",
})


def _capitalised_label(text: str | None) -> bool:
    """A short caption or sentence that starts with a capital letter and holds a word (not a path, id or URL)."""
    if not text or not text[0].isupper() or "/" in text or "\\" in text or "://" in text:
        return False
    return _has_word(text) and len(text) <= 160
#: Calls whose ``description=`` and ``title=`` are documentation, not screen copy.
_NOT_GUI_TEXT_CALLS = frozenset({"Field", "ArgumentParser", "add_parser", "add_argument", "setup", "namedtuple"})
#: Message-box helpers: ``QMessageBox.warning(self, "Title", "text")``, ``messagebox.showerror("Title", "text")``. The
#: receiver has to say it is a message box, so ``logging.warning("...")`` stays out.
_MESSAGEBOX_CALLS = frozenset({
    "critical", "warning", "information", "question", "about", "showinfo", "showwarning", "showerror", "askquestion",
    "askokcancel", "askyesno", "askretrycancel", "askyesnocancel",
})
#: Keyword arguments and dict keys that hold a tuple or list of captions.
_DESKTOP_LISTS = frozenset({"labels", "choices", "headers", "items"})
_DESKTOP_DICT_KEYS = frozenset({"label", "text", "title", "tooltip", "caption"})


def _texts(node: ast.AST | None):
    """The string literals of one argument: a literal, or the literals inside a list or tuple of them."""
    if isinstance(node, (ast.List, ast.Tuple)):
        for element in node.elts:
            yield element, _text(element)
    else:
        yield node, _text(node)


def _desktop_strings(node: ast.AST, add) -> None:
    """Captions a Tk, Qt or wx program shows: widget text, menu entries, window titles, tooltips (idiom-based)."""
    if isinstance(node, ast.Call) and not _is_log_call(node):
        name = _callee(node)
        sink = f"desktop:{name}"
        if _DESKTOP_WIDGET.search(name) and node.args:
            add(node.args[0], _text(node.args[0]), sink)
        if name in _DESKTOP_SETTERS:
            for arg in node.args:
                for element, text in _texts(arg):
                    add(element, text, sink)
        elif (name in _MESSAGEBOX_CALLS and "messagebox" in _receiver(node)) or (
            name in _DIALOG_STATICS and "dialog" in _receiver(node)
        ):
            for arg in node.args:
                add(arg, _text(arg), sink)
        elif name == "translate" and len(node.args) >= 2:
            # Qt (and pyuic-generated code): ``QCoreApplication.translate("Dialog", "Text", None)``; the text is the second argument.
            add(node.args[1], _text(node.args[1]), sink)
        for kw in node.keywords:
            if kw.arg in _DESKTOP_KWARGS and (_DESKTOP_WIDGET.search(name) or name in _DESKTOP_SETTERS):
                add(kw.value, _text(kw.value), sink)
            elif kw.arg in _DESKTOP_LISTS:
                for element, text in _texts(kw.value):
                    add(element, text, sink)
    elif isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            field = _text(key) if key is not None else None
            if field and field.casefold() in _DESKTOP_DICT_KEYS:
                add(value, _text(value), f"desktop:{field}")


#: Status and message helpers of a GUI program: ``self.set_status("Saved")``, ``update_status(...)``, ``show_error(...)``.
_GUI_STATUS_CALL = re.compile(r"^_?(?:set|update|show|display)_\w*(?:status|message|error|success|warning|info)$")
_BUILTIN_NAMES = frozenset(dir(builtins))
_LABEL_KEY = re.compile(r"[a-z0-9_.-]{1,16}")


def _prose_message(text: str | None) -> bool:
    """A sentence a person reads: three words or more, starting with a capital (or a non-Latin letter)."""
    if not text:
        return False
    words = text.split()
    return len(words) >= 3 and (text[0].isupper() or not text[0].isascii()) and _has_word(text)


def _gui_project_strings(node: ast.AST, add, *, desktop_module: bool, gui_project: bool) -> None:
    """Screen copy that only a GUI program has: status helpers, errors raised for the user, code-to-label tables."""
    if isinstance(node, ast.Call) and not _is_log_call(node) and _GUI_STATUS_CALL.match(_callee(node)):
        for arg in node.args:
            add(arg, _text(arg), f"gui-status:{_callee(node)}")
    elif isinstance(node, ast.Call) and not _is_log_call(node) and _callee(node) not in _NOT_GUI_TEXT_CALLS:
        for kw in node.keywords:
            if kw.arg in _GUI_TEXT_KWARGS:
                add(kw.value, _text(kw.value), f"gui-kwarg:{kw.arg}")
            elif kw.arg and kw.arg.endswith(_GUI_TEXT_SUFFIXES) and _capitalised_label(_text(kw.value)):
                add(kw.value, _text(kw.value), f"gui-kwarg:{kw.arg}")
            elif kw.arg in _GUI_LIST_KWARGS and isinstance(kw.value, (ast.List, ast.Tuple)):
                for element in kw.value.elts:
                    if _capitalised_label(_text(element)):
                        add(element, _text(element), f"gui-list:{kw.arg}")
    elif isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        text = _text(node.value)
        if isinstance(target, ast.Name) and target.id in _CAPTION_VARS and _capitalised_label(text):
            add(node.value, text, f"gui-caption:{target.id}")
        elif desktop_module and isinstance(target, ast.Attribute) and target.attr in _CAPTION_ATTRS and _capitalised_label(text):
            add(node.value, text, f"gui-caption:{target.attr}")  # ``page.title = "Dashboard"``
    elif gui_project and isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
        # A project-defined error (``raise M4BError("Cover download failed for this book.")``) travels to a dialog in a
        # desktop app. Builtin errors (ValueError, RuntimeError) stay developer text.
        name = _callee(node.exc)
        if name.endswith(("Error", "Exception")) and name not in _BUILTIN_NAMES and not _user_exception(name):
            arg = node.exc.args[0]
            if _prose_message(_text(arg)):
                add(arg, _text(arg), "gui-exception")
    elif desktop_module and isinstance(node, ast.Dict) and len(node.keys) >= 2:
        # ``{"dol": "App", "thm": "Theme"}``: a code-to-name table whose values fill a list or a button caption.
        keys = [_text(k) if k is not None else None for k in node.keys]
        values = [_text(v) for v in node.values]
        if all(k and _LABEL_KEY.fullmatch(k) for k in keys) and all(
            v and v[0].isupper() and len(v) <= 40 and _has_word(v) and v.strip() == v for v in values
        ):
            for value_node, value in zip(node.values, values):
                add(value_node, value, "gui-labels")


_QT_SIGNAL = frozenset({"Signal", "pyqtSignal"})


def _is_qt_backend(cls: ast.ClassDef) -> bool:
    """A class that declares Qt signals (PySide ``Signal``, PyQt ``pyqtSignal``): a QML-facing backend object."""
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call) and _callee(stmt.value) in _QT_SIGNAL:
            return True
    return False


def _add_if_label(add, node: ast.AST) -> None:
    """Report a literal that reads as a label or message: capitalised or several words, not an id or a path."""
    text = _text(node)
    if not text:
        return
    t = text.strip()
    if t[:1].isupper() or (" " in t and any(ch.isalpha() for ch in t)):
        if not re.search(r"[/\\]|^\w+\.\w+$|^[A-Z0-9_]+$", t):
            add(node, text, "qt-backend")


def _is_log_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "print"
    if not (isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS):
        return False
    owner = func.value  # ``logger.info``, and the same through attributes: ``self._logger.info``, ``func.logger.error``
    name = owner.id if isinstance(owner, ast.Name) else owner.attr if isinstance(owner, ast.Attribute) else ""
    return name in _LOG_OBJECTS or name.lower().endswith("logger")


_REGEX_CALLS = frozenset({"compile", "sub", "subn", "search", "match", "fullmatch", "findall", "finditer", "split"})
_LANGUAGE_KEY = re.compile(r"[a-z]{2,3}(?:[-_][A-Za-z]{2,4})?")


def _is_regex_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr in _REGEX_CALLS and isinstance(func.value, ast.Name) and func.value.id == "re"


def _is_language_catalogue(node: ast.Dict) -> bool:
    """``{"en": {...}, "fa": {...}}``: language codes at the top, one table of screen text under each."""
    if len(node.keys) < 2 or not all(isinstance(v, ast.Dict) for v in node.values):
        return False
    keys = [_text(k) if k is not None else None for k in node.keys]
    return all(k and _LANGUAGE_KEY.fullmatch(k) for k in keys)


def dev_strings(source: str) -> set[tuple[int, str]]:
    """``(line, text)`` of literals only developers see: log/print arguments, non-HTTP ``raise`` messages."""
    tree = _parse(source)
    if tree is None:
        return set()
    out: set[tuple[int, str]] = set()

    def collect(call: ast.Call) -> None:
        for arg in [*call.args, *(kw.value for kw in call.keywords)]:
            for sub in ast.walk(arg):
                text = _text(sub) if isinstance(sub, (ast.Constant, ast.JoinedStr)) else None
                if text:
                    out.add((sub.lineno, " ".join(text.split())))

    def collect_all(root: ast.AST) -> None:
        for sub in ast.walk(root):
            text = _text(sub) if isinstance(sub, (ast.Constant, ast.JoinedStr)) else None
            if text:
                out.add((sub.lineno, " ".join(text.split())))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_log_call(node):
            collect(node)
        elif isinstance(node, ast.Call) and _is_regex_call(node):
            collect(node)  # a pattern is code, whatever script it is written in
        elif isinstance(node, ast.Tuple) and any(isinstance(e, ast.Call) and _is_regex_call(e) for e in node.elts):
            collect_all(node)  # ``(re.compile("a  b"), "a b")``: the replacement belongs to the pattern
        elif isinstance(node, ast.Dict) and _is_language_catalogue(node):
            collect_all(node)  # the project's own ``{"en": {...}, "fa": {...}}`` catalogue, read through its own lookup
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            name = _callee(node.exc)
            if not _user_exception(name):
                collect(node.exc)
    return out
