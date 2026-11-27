# Coding agents

The guide for AI agents is packaged with llm-localizator so it is the same everywhere:

- `llm-localizator help agent` prints it. The source is [`llm_localizator/help/agent.md`](../llm_localizator/help/agent.md).
- MCP clients read the resource `llm-localizator://help/agent`. The tools `check_keys`,
  `hardcoded_status` and `list_approaches` sit next to the older ones.
- `llm-localizator skill install <project>` writes a set of short Claude skills into the
  project under `.claude/skills/` (ADR-162). Run it only when the project's owner agrees.
  `skill check` reports drift per skill.

  | Skill | Use when |
  |---|---|
  | `llm-localizator` | Always: the hard rules (ask-first, stamps, cost) and which task skill to use |
  | `l10n-wire-strings` | UI text was added or changed: find hardcoded strings, wire keys, `check-keys` |
  | `l10n-add-language` | A new language, or filling gaps: approach, dry run and cost first, then translate |
  | `l10n-review` | Translations need a human check: `review-risk`, `set --by human`, `glossary-learn` |
  | `l10n-release` | Before shipping: read-only checks and a go / no-go summary |

  Each skill is under 60 lines, with exact commands and a "done when". Skills point to
  `help agent` for the full guide instead of copying it. Sources:
  [`llm_localizator/help/skills/`](../llm_localizator/help/skills/).

It covers:
- the hard rules, including when to ask before touching a consumer repository;
- the approaches (`llm-localizator approach`);
- how to wire UI text and what stays literal;
- the hardcoded-text loop with exit codes;
- the translation checks;
- how to fix one string with the right provenance stamps.

The human operator's guide is `llm-localizator help human` ([source](../llm_localizator/help/human.md)).
