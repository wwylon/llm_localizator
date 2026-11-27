# Adopting a project that already has translations

Your catalogues already contain translations made by hand, by another tool or by an agent,
but llm-localizator has never recorded them. This page gets the engine to keep them instead
of treating them as missing.

## What the engine sees first

Until a key has a state record, the engine knows nothing about who wrote its value or which
source text it matches. `translate` handles that safely:

- A key with a target value and no state record is **left as is**. The run says
  `left as is: pl 1834 existing translation(s) with no state record; run adopt to record
  them, or --force / --keys to retranslate`.
- `status` and `agent-backlog` list these keys with the reason `no_state`.

Nothing is overwritten unless you pass `--force` or name the keys with `--keys`.

## Steps

1. **Look first.**
   ```bash
   llm-localizator status myapp --missing
   llm-localizator adopt myapp --locales pl --dry-run
   ```
2. **Record what is there.**
   ```bash
   llm-localizator adopt myapp --locales pl
   ```
   `adopt` writes state, scores and history only. It never rewrites catalogue files.
   Values are stamped `provider=agent` (ADR-19); pass `--provider human` if people wrote them.
3. **Translate only the real gaps.**
   ```bash
   llm-localizator translate myapp --locales pl --only-missing
   ```
4. **Check quality where it matters.**
   ```bash
   llm-localizator rescore myapp --locales pl      # score the adopted values
   llm-localizator review-risk myapp --locale pl   # lowest-confidence keys first
   ```
   Improve or hand-fix what scores low. Keys you mark verified in the web editor are never
   overwritten without `--force`.

## Retranslating a chosen set

To replace specific adopted values, name them:

```bash
llm-localizator translate myapp --locales pl --keys auth.login,auth.logout
llm-localizator translate myapp --locales pl --keys-file keys.txt   # one ns.key per line
```

`--keys-file` avoids command-line length limits (Windows) on large lists.

## After the first run

Later edits made outside the engine (an agent, a teammate, a merge) show as
`external_edit` or `no_state`. Run `adopt` again to record them.
