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
_UI_HELPER = re.compile(r"(?:toast|dialog|snack|popup|show_(?:msg|message|error|info|alert)|notify_user)", re.I)
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


def server_strings(source: str) -> list[ServerString]:
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
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                field = _text(key) if key is not None else None
                if field and field.casefold() in COPY_FIELDS:
                    add(value, _text(value), f"payload:{field}")
    out.sort(key=lambda s: s.line)
    return out


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

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_log_call(node):
            collect(node)
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            name = _callee(node.exc)
            if not _user_exception(name):
                collect(node.exc)
    return out
