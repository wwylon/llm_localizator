"""Workflow routing rules (ADR-62) and block scripts (ADR-63): pure parsing,
validation and evaluation.

ADR-62: a workflow is an ordered list of ``IF field op value THEN action``
rules; the first match wins and anything unmatched falls to ``ELSE`` (a review
ticket). A table with only ``high`` / ``low`` is the classic three-band router
and is expanded to the two canonical score rules.

ADR-63: a workflow is a *script* — a tree of blocks the operator orders. Legacy
``rules`` / ``high`` / ``low`` tables load into the equivalent script.
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = [
    "ACTIONS",
    "FIELDS",
    "ELSE_ACTION",
    "NOTIFY_MODES",
    "WORKFLOW_KEYS",
    "MAX_LOOPS",
    "DEFAULT_HIGH",
    "DEFAULT_LOW",
    "canonical_rules",
    "is_canonical",
    "normalize_workflow",
    "evaluate_rules",
    "BLOCK_TYPES",
    "LLM_BLOCKS",
    "TERMINAL_BLOCKS",
    "MAX_DEPTH",
    "MAX_BLOCKS",
    "legacy_script",
    "default_script",
    "is_legacy_script",
    "legacy_thresholds",
    "normalize_script",
    "eval_cond",
    "script_warnings",
    "walk_script",
    "block_at",
    "next_position",
]

FIELD_SCORE = "score"
FIELD_HARDCODED = "hardcoded"
FIELD_FINDINGS = "findings"  # 1 when the last validate block flagged this key
FIELDS = (FIELD_SCORE, FIELD_HARDCODED, FIELD_FINDINGS, "status", "locale", "namespace")
OPS_BY_FIELD = {
    FIELD_SCORE: ("ge", "le"),
    FIELD_HARDCODED: ("ge", "le"),
    FIELD_FINDINGS: ("ge", "le"),
    "status": ("is", "is_not"),
    "locale": ("is", "is_not"),
    "namespace": ("is", "is_not"),
}
ACTIONS = ("verify", "review", "llm_review", "improve", "flag")
ELSE_ACTION = "review"
NOTIFY_MODES = ("none", "webhook")
WORKFLOW_KEYS = frozenset({
    "high", "low", "rules", "script", "max_improve_loops", "notify", "locales",
})
MAX_LOOPS = 5
DEFAULT_LOOPS = 2
DEFAULT_HIGH = 0.80
DEFAULT_LOW = 0.55

#: Blocks that call an LLM op on the keys that reach them (async under taskqueue).
LLM_BLOCKS = ("translate", "rescore", "improve", "llm_review")
#: Blocks after which the keys leave the flow.
TERMINAL_BLOCKS = ("verify", "review_ticket", "stop")
#: Read-only check of the scope (placeholder, ICU and other validation findings); keys pass through.
CHECK_BLOCKS = ("validate",)
BLOCK_TYPES = (*LLM_BLOCKS, *CHECK_BLOCKS, "if", "flag", "notify", *TERMINAL_BLOCKS)
MAX_DEPTH = 6
MAX_BLOCKS = 100
_RULE_BLOCK = {
    "verify": "verify",
    "review": "review_ticket",
    "llm_review": "llm_review",
    "improve": "improve",
    "flag": "flag",
}


def canonical_rules(high: float, low: float) -> list[dict[str, Any]]:
    return [
        {"field": FIELD_SCORE, "op": "ge", "value": high, "action": "verify"},
        {"field": FIELD_SCORE, "op": "le", "value": low, "action": "improve"},
    ]


def is_canonical(rules: list[dict[str, Any]], high: float, low: float) -> bool:
    return rules == canonical_rules(high, low)


def _cond(raw: Mapping[str, Any], where: str) -> dict[str, Any]:
    field = str(raw.get("field", ""))
    if field not in FIELDS:
        raise ValueError(f"{where}: field must be one of {', '.join(FIELDS)}")
    op = str(raw.get("op", ""))
    if op not in OPS_BY_FIELD[field]:
        raise ValueError(
            f"{where}: op {op!r} is not valid for {field} "
            f"(use {', '.join(OPS_BY_FIELD[field])})"
        )
    value = raw.get("value")
    if field == FIELD_SCORE:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: score value must be a number") from None
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{where}: score value must be within 0..1")
    else:
        value = str(value if value is not None else "").strip()
        if not value:
            raise ValueError(f"{where}: {field} value must not be empty")
    return {"field": field, "op": op, "value": value}


def _rule(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where}: each rule must be a table")
    unknown = set(raw) - {"field", "op", "value", "action"}
    if unknown:
        raise ValueError(f"{where}: unknown rule keys {sorted(unknown)}")
    cond = _cond(raw, where)
    action = str(raw.get("action", ""))
    if action not in ACTIONS:
        raise ValueError(f"{where}: action must be one of {', '.join(ACTIONS)}")
    return {**cond, "action": action}


# --- ADR-63 block scripts ---------------------------------------------------


def _block(kind: str) -> dict[str, Any]:
    return {"type": kind}


def legacy_script(rules: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Script equivalent of an ADR-62 table: translate, rescore, then first match
    wins as nested if/else with a review ticket as the final ELSE."""
    tail: list[dict[str, Any]] = [_block("review_ticket")]
    for rule in reversed(rules):
        tail = [{
            "type": "if",
            "field": rule["field"],
            "op": rule["op"],
            "value": rule["value"],
            "then": [_block(_RULE_BLOCK[rule["action"]])],
            "else": tail,
        }]
    return [_block("translate"), _block("rescore"), *tail]


def default_script(high: float = DEFAULT_HIGH, low: float = DEFAULT_LOW) -> list[dict[str, Any]]:
    """The default workflow (used when none is configured, and by "Default pipeline"):

    translate → rescore → if score ≥ 0.80: verify
                          else if score ≤ 0.55: improve
                          else: human review ticket
    """
    return legacy_script(canonical_rules(high, low))


def _preset_pipeline() -> list[dict[str, Any]]:
    return default_script()


def _preset_tm_llm_validate() -> list[dict[str, Any]]:
    # translate consults the translation memory before the model, so TM → LLM is one block.
    return [
        _block("translate"), _block("validate"), _block("rescore"),
        {"type": "if", "field": "score", "op": "ge", "value": 0.8,
         "then": [_block("verify")], "else": [_block("review_ticket")]},
    ]


def _preset_reroute() -> list[dict[str, Any]]:
    return [{"type": "if", "field": "score", "op": "ge", "value": 0.8,
             "then": [_block("verify")], "else": [_block("review_ticket")]}]


def _preset_approve() -> list[dict[str, Any]]:
    return [{"type": "if", "field": "score", "op": "ge", "value": 0.9,
             "then": [_block("verify")], "else": []}]


#: id -> (English label, builder). Builders return fresh trees; each is checked by
#: :func:`normalize_script` when read through :func:`presets`.
PRESETS: dict[str, tuple[str, Any]] = {
    "pipeline": ("Default pipeline (translate → score → route)", _preset_pipeline),
    "tm_llm_validate": ("TM → LLM → validate → route", _preset_tm_llm_validate),
    "reroute": ("Re-route existing scores", _preset_reroute),
    "approve": ("Auto-approve only", _preset_approve),
    "blank": ("Blank", list),
}


def presets() -> list[dict[str, Any]]:
    """Validated presets as ``{id, label, script}`` rows, in display order."""
    return [
        {"id": pid, "label": label, "script": normalize_script(build(), f"preset {pid}")}
        for pid, (label, build) in PRESETS.items()
    ]


def is_legacy_script(script: list[dict[str, Any]], high: float, low: float) -> bool:
    return script == legacy_script(canonical_rules(high, low))


def legacy_thresholds(script: list[dict[str, Any]]) -> tuple[float, float] | None:
    """``(high, low)`` when ``script`` is exactly the classic three-band pipeline."""
    try:
        high = script[2]["value"]
        low = script[2]["else"][0]["value"]
    except (IndexError, KeyError, TypeError):
        return None
    if not (isinstance(high, float) and isinstance(low, float) and 0.0 <= low <= high <= 1.0):
        return None
    return (high, low) if is_legacy_script(script, high, low) else None


def _stack(raw: Any, where: str, depth: int, budget: list[int]) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{where}: must be an array of blocks")
    if depth > MAX_DEPTH:
        raise ValueError(f"{where}: blocks are nested deeper than {MAX_DEPTH}")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        here = f"{where}[{i}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{here}: each block must be a table")
        kind = str(item.get("type", ""))
        if kind not in BLOCK_TYPES:
            raise ValueError(f"{here}: type must be one of {', '.join(BLOCK_TYPES)}")
        budget[0] += 1
        if budget[0] > MAX_BLOCKS:
            raise ValueError(f"{where}: a script may hold at most {MAX_BLOCKS} blocks")
        if kind == "if":
            unknown = set(item) - {"type", "field", "op", "value", "then", "else"}
            if unknown:
                raise ValueError(f"{here}: unknown keys {sorted(unknown)}")
            block = {
                "type": "if",
                **_cond(item, here),
                "then": _stack(item.get("then"), f"{here}.then", depth + 1, budget),
                "else": _stack(item.get("else"), f"{here}.else", depth + 1, budget),
            }
        else:
            allowed = {"type", "max_loops"} if kind == "improve" else {"type"}
            unknown = set(item) - allowed
            if unknown:
                raise ValueError(f"{here}: unknown keys {sorted(unknown)}")
            block = _block(kind)
            if kind == "improve" and item.get("max_loops") is not None:
                try:
                    loops = int(item["max_loops"])
                except (TypeError, ValueError):
                    raise ValueError(f"{here}: max_loops must be an integer") from None
                if not 0 <= loops <= MAX_LOOPS:
                    raise ValueError(f"{here}: max_loops must be within 0..{MAX_LOOPS}")
                block["max_loops"] = loops
        out.append(block)
    return out


def normalize_script(raw: Any, where: str = "script") -> list[dict[str, Any]]:
    """Validate a block tree; fresh dicts, every ``if`` carries ``then`` and ``else``."""
    return _stack(raw, where, 1, [0])


def walk_script(script: list[dict[str, Any]], prefix: tuple = ()):
    """Yield ``(position, block)`` depth-first; a position looks like ``(2, "then", 0)``."""
    for i, block in enumerate(script):
        pos = (*prefix, i)
        yield pos, block
        if block["type"] == "if":
            yield from walk_script(block.get("then") or [], (*pos, "then"))
            yield from walk_script(block.get("else") or [], (*pos, "else"))


def _stack_at(script: list[dict[str, Any]], parent: list) -> list[dict[str, Any]]:
    """The block list a position lives in (``parent`` = position minus its index)."""
    stack = script
    block: dict[str, Any] = {}
    for part in parent:
        if isinstance(part, int):
            block = stack[part]
        else:
            stack = block.get(part) or []
    return stack


def block_at(script: list[dict[str, Any]], pos: tuple | list) -> dict[str, Any]:
    pos = list(pos)
    return _stack_at(script, pos[:-1])[pos[-1]]


def next_position(script: list[dict[str, Any]], pos: tuple | list) -> tuple | None:
    """Position run after ``pos`` finishes (climbing out of C-blocks), or ``None``."""
    cur = list(pos)
    while cur:
        idx, parent = cur[-1], cur[:-1]
        if idx + 1 < len(_stack_at(script, parent)):
            return tuple([*parent, idx + 1])
        if not parent:
            return None
        cur = parent[:-1]  # drop the branch name: now at the enclosing `if`
    return None


def script_warnings(script: list[dict[str, Any]]) -> list[str]:
    """Soft hints for the editor (stable codes, never blocking)."""
    out: list[str] = []
    rescored = False
    for pos, block in walk_script(script):
        kind = block["type"]
        if kind == "rescore":
            rescored = True
        if kind == "if":
            if block["field"] == FIELD_SCORE and not rescored:
                out.append("score_before_rescore")
            if not block["then"] and not block["else"]:
                out.append("empty_branch")
        if kind == "stop":
            if pos[-1] + 1 < len(_stack_at(script, list(pos[:-1]))):
                out.append("unreachable_after_stop")
    return list(dict.fromkeys(out))


def normalize_workflow(table: Mapping[str, Any], where: str = "workflow") -> dict[str, Any]:
    """Validate one ``[workflows.<name>]`` table and return the normalised dict.

    Result keys: ``high``, ``low`` (derived from the score rules), ``rules``,
    ``script`` (explicit, or derived from the rules), ``max_improve_loops``,
    ``notify`` and ``locales`` (list or ``None``).
    Raises ``ValueError`` with a message prefixed by ``where``.
    """
    unknown = set(table) - WORKFLOW_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    try:
        high = float(table.get("high", DEFAULT_HIGH))
        low = float(table.get("low", DEFAULT_LOW))
    except (TypeError, ValueError):
        raise ValueError(f"{where}: high/low must be numbers") from None

    raw_rules = table.get("rules")
    raw_script = table.get("script")
    if raw_script is not None and raw_rules is not None:
        raise ValueError(f"{where}: use either rules or script, not both")
    if raw_rules is None:
        rules = canonical_rules(high, low)
    else:
        if not isinstance(raw_rules, (list, tuple)):
            raise ValueError(f"{where}: rules must be an array")
        rules = [_rule(r, f"{where}.rules[{i}]") for i, r in enumerate(raw_rules)]
        high = next(
            (r["value"] for r in rules if r["field"] == FIELD_SCORE and r["op"] == "ge"),
            high,
        )
        low = next(
            (r["value"] for r in rules if r["field"] == FIELD_SCORE and r["op"] == "le"),
            low,
        )
    if not (0.0 <= low <= high <= 1.0):
        raise ValueError(f"{where}: requires 0 <= low <= high <= 1")

    if raw_script is not None:
        script = normalize_script(raw_script, f"{where}.script")
        classic = legacy_thresholds(script)
        if classic:
            high, low = classic
            rules = canonical_rules(high, low)
    else:
        script = legacy_script(rules)

    try:
        loops = int(table.get("max_improve_loops", DEFAULT_LOOPS))
    except (TypeError, ValueError):
        raise ValueError(f"{where}: max_improve_loops must be an integer") from None
    if not 0 <= loops <= MAX_LOOPS:
        raise ValueError(f"{where}: max_improve_loops must be within 0..{MAX_LOOPS}")

    notify = str(table.get("notify", "none"))
    if notify not in NOTIFY_MODES:
        raise ValueError(f"{where}: notify must be one of {', '.join(NOTIFY_MODES)}")

    locales_raw = table.get("locales")
    locales: list[str] | None
    if locales_raw is None:
        locales = None
    else:
        if not isinstance(locales_raw, (list, tuple)) or not all(
            isinstance(x, str) and x.strip() for x in locales_raw
        ):
            raise ValueError(f"{where}: locales must be an array of locale codes")
        locales = [str(x).strip() for x in locales_raw] or None

    return {
        "high": high,
        "low": low,
        "rules": rules,
        "script": script,
        "max_improve_loops": loops,
        "notify": notify,
        "locales": locales,
    }


def _matches(rule: Mapping[str, Any], ctx: Mapping[str, Any]) -> bool:
    field, op, want = rule["field"], rule["op"], rule["value"]
    have = ctx.get(field)
    if field in (FIELD_SCORE, FIELD_HARDCODED, FIELD_FINDINGS):
        if have is None:
            return False
        return float(have) >= float(want) if op == "ge" else float(have) <= float(want)
    equal = str(have if have is not None else "") == str(want)
    return equal if op == "is" else not equal


def eval_cond(cond: Mapping[str, Any], ctx: Mapping[str, Any]) -> bool:
    return _matches(cond, ctx)


def evaluate_rules(rules: list[Mapping[str, Any]], ctx: Mapping[str, Any]) -> str:
    """First matching rule's action, else :data:`ELSE_ACTION`."""
    for rule in rules:
        if _matches(rule, ctx):
            return str(rule["action"])
    return ELSE_ACTION
