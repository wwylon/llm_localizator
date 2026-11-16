# Consumer localization checklist

The ordered path to localize an app with llm-localizator. This page is the map. The
detail lives in:
- the operator guide (`llm-localizator help human`) for decisions and reading results;
- the agent guide (`llm-localizator help agent`) for wiring rules and the loop;
- [web-runtime.md](web-runtime.md) for the browser runtime;
- [scanners.md](scanners.md) for how detection works.

## 1. Start: config and approach

- [ ] `llm-localizator onboard <app> --targets pl --frozen zh,ar` does the steps below in one go, or:
- [ ] `llm-localizator init` writes `.llm-localize.toml` (`[project]`, `[catalog]`,
      `[locales] targets`, `[prompt] domain`) and asks **how you want to localize**.
- [ ] `llm-localizator approach <project>` shows the options with a recommendation
      (local, cloud, agent, human, hybrid). Record one with `--set <id>`;
      `llm-localizator guide` adapts the next steps to it.
- [ ] Languages: shipped targets vs **frozen** layout checks (zh, ar). Frozen
      languages are skipped by default runs.
- [ ] `[scan] adapter` is a real scanner (`raw-js`, `source`, `next-intl`,
      `react-intl`), and `[scan] src_dirs` points at UI source, not docs or tests.
- [ ] `llm-localizator doctor <name>` shows the right root and data home (ADR-112).
- [ ] Local or hybrid on a GPU host: `llm-localizator init --taskqueue` + `tq sync`.

## 2. Wire the app

- [ ] Plain JS/HTML without an i18n library: set `[web] runtime_path`, then
      `llm-localizator runtime install <project>`. Load `i18n.config.js` before
      `i18n.js` ([web-runtime.md](web-runtime.md)).
- [ ] Framework i18n (next-intl, i18next, gettext…): keep it; llm-localizator
      translates its catalogues.
- [ ] Wire with the rules in `llm-localizator help agent` § 3: literal keys,
      `data-i18n*`, ICU for counts, whole sentences, what stays literal.
- [ ] `llm-localizator check-keys <project>` exits 0: every used key exists in the
      source catalogue.

## 3. Find what is still hardcoded

Static scan:

```bash
llm-localizator agent-hardcoded <project> --status   # readiness and next steps (JSON)
llm-localizator agent-hardcoded <project> --refresh  # prompt of hardcoded strings to wire
llm-localizator scan-decide <project> ignore --ids <id> --note "why"   # noise, with a reason
```

Painted English, en-XX. Describe the app once in `[qa]`
([configuration.md](configuration.md#qa)), then:

```bash
llm-localizator pseudo <project> --locale en-XX     # marker catalogue (refresh after en grows)
llm-localizator hardcoded-hunt <project> --serve    # starts the app from [qa] start; crawls
```

- **Where the report goes:** `~/.llm_localize/data/<name>/qa/<ts>/`, never into the
  app repo.
- **`leftovers.json`:** visible English. Rows with `file`/`line` are source
  literals: wire them.
- **`dynamic_text.json`:** text found nowhere in the source (server, API or user
  data). Fix it at the producer.
- **`layout.json` and screenshots:** RTL direction and clipped text for ar, plus
  zh layout.
- **The marker locale:** never add `en-XX` to `[locales] targets`. It is
  URL-only (`?lang=en-XX` or `/en-XX/…`).

## 4. Translate

- [ ] Follow the chosen approach. `llm-localizator guide` names the next command:
      `translate` (queued), `estimate-cost` (cloud), `agent-backlog` (agent), or
      `export` / `import` (human).
- [ ] Never hand-write targets without stamps. Out-of-band edits get `adopt`, then
      `validate` (ADR-19).
- [ ] Held drafts (under `[quality] write_floor`, or not better than the current
      text): review them in the editor.

## 5. Review and ship

- [ ] `llm-localizator validate` has no errors in shipped languages; V46/V47/V48
      are explained in `llm-localizator help human` § 4.
- [ ] Review short labels and buttons in each shipped language. Scores miss
      one-word errors.
- [ ] CI: `validate`, `check-keys`, and `runtime check` (when the runtime is
      installed).
- [ ] No QA locale in the production language picker.
- [ ] Commit catalogues and, if installed, `i18n.js`. State lives in the data home.
