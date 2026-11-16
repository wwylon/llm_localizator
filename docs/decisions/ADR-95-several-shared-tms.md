# ADR-95: Several read-only shared TMs and one optional write target (C-030)

`[prompt] tm_shared` now takes a path or a list of paths, the read set (ADR-42). Lookup order is
the project TM, then each shared memory in the order given; the first exact hit wins and `near`
merges all of them without duplicates. A new `[prompt] tm_write` names one extra memory: when a
human-approved text is recorded (`TranslationMemory.approve`), it is appended there as well as to
the project store. Machine output (`record`) never goes to the write target, so one client's TM
only receives reviewed text. The shared read memories stay read-only, which keeps ADR-42's
guarantee; the write target is the single, explicit exception and is off by default. Existing
projects with one `tm_shared` path or none behave exactly as before.

`ProjectConfig.open_tm()` replaces the eight places that built a `TranslationMemory` by hand, so
the read set and write target apply everywhere (translate, improve, validate, console, web edits).
The project-config web form takes comma-separated shared paths plus the write target. Named memories
are paths; there is no registry (rejected in ADR-42). Scope cut: no per-command CLI flags; the
config file and the web setting are the interface.
