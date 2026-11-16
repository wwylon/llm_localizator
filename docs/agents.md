# Coding agents

The guide for AI agents is packaged with llm-localizator so it is the same everywhere:

- `llm-localizator help agent` prints it. The source is [`llm_localizator/help/agent.md`](../llm_localizator/help/agent.md).
- MCP clients read the resource `llm-localizator://help/agent`. The tools `check_keys`,
  `hardcoded_status` and `list_approaches` sit next to the older ones.
- `llm-localizator skill install <project>` writes it into a project as a Claude skill
  (`.claude/skills/llm-localizator/SKILL.md`). Run it only when the project's owner
  agrees. `skill check` reports drift.

It covers:
- the hard rules, including when to ask before touching a consumer repository;
- the approaches (`llm-localizator approach`);
- how to wire UI text and what stays literal;
- the hardcoded-text loop with exit codes;
- the translation checks;
- how to fix one string with the right provenance stamps.

The human operator's guide is `llm-localizator help human` ([source](../llm_localizator/help/human.md)).
