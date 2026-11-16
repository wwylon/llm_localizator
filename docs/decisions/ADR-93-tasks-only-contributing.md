# ADR-93: Tasks-only contributing is enforced in the permission layer (C-029)

`[tasks] contribute_in_tasks_only = true` limits a Translator to keys that a task assigns to
them: the task must list the key and name the person for that locale (ADR-92). The rule is one
function, `ops.permissions.task_scope_denied`, called by the web save, verify and revert routes
and by `dispatch_op` for `draft accept` (the one op a Translator can run that writes text), so
the editor UI is not the only guard. Admin, Supervisor and Developer are unaffected, and a
Translator session without a user name (token) gets nothing. The check runs after the normal
role and locale checks and adds a refusal only; it never grants access.

Rejected: locking every other key in the state store (it would touch the frozen state format,
ADR-7, and persist a policy as data) and hiding keys in the editor (not enforcement). Reads are
unchanged: a Translator can still see every key. The default stays off, so existing projects
behave as before.
