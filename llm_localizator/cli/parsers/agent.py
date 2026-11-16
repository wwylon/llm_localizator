"""Argparse builders: hard-keys, adopt, agent-backlog, agent-hardcoded, scan-decide, patch, apply, migrate-state, guide, init and help family."""

from __future__ import annotations

import argparse

from .common import _csv, add_project_args


def _add_hard_keys(sub: argparse._SubParsersAction) -> None:
    """Subcommands: hard-keys."""
    hk = sub.add_parser(
        "hard-keys",
        help="Cross-locale score report — source-hard vs locale-hard keys (no LLM)",
    )
    add_project_args(hk)
    hk.add_argument("--locales", type=_csv, default=None)
    hk.add_argument("--namespace", default=None)
    hk.add_argument("--threshold", type=float, default=0.7,
                    help="Score below which a locale counts as low (default 0.7)")
    hk.add_argument("--min-locales", type=int, default=4,
                    help="Minimum locales with scores per key (default 4)")
    hk.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")
    hk.add_argument("--dry-run", action="store_true",
                    help="Report only; do not write _reports JSON")


def _add_adopt(sub: argparse._SubParsersAction) -> None:
    """Subcommands: adopt."""
    ad = sub.add_parser(
        "adopt",
        help="Stamp catalogue strings missing from state as agent provenance (no LLM)",
        description="For keys already present in the target catalogue but absent "
                    "from .state — typical after manual/AI catalogue edits. "
                    "Does not rewrite catalogue files or refresh stale keys.",
    )
    add_project_args(ad)
    ad.add_argument("--locales", type=_csv, default=None,
                    help="Locales to adopt (default: all targets, including frozen)")
    ad.add_argument("--namespace", default=None, help="Restrict to one namespace")
    ad.add_argument("--limit", type=int, default=None, help="Max keys to adopt")
    ad.add_argument("--dry-run", action="store_true", help="Report without writing")
    ad.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")
    ad.add_argument("--model", default="cursor-agent",
                    help="State model stamp (default: cursor-agent)")
    ad.add_argument("--provider", default="agent",
                    help="State provider stamp (default: agent)")
    ad.add_argument("--verified-by", default="cursor-agent",
                    help="verified_by stamp (default: cursor-agent)")


def _add_agent_backlog(sub: argparse._SubParsersAction) -> None:
    """Subcommands: agent-backlog."""
    ab = sub.add_parser(
        "agent-backlog",
        help="List keys an AI agent should still translate (prompt or JSON, no LLM)",
        description="Emits missing / empty / no_state / stale keys with English "
                    "source text, ready to paste into Cursor.",
    )
    add_project_args(ab)
    ab.add_argument("--locales", type=_csv, default=None,
                    help="Locales to include (default: all targets, including frozen)")
    ab.add_argument("--namespace", default=None, help="Restrict to one namespace")
    ab.add_argument("--limit", type=int, default=None, help="Max keys in the backlog")
    ab.add_argument(
        "--reasons",
        default=None,
        help="Comma-separated: missing,empty,no_state,stale,external_edit (default: all)",
    )
    ab.add_argument(
        "--format", dest="fmt", choices=["prompt", "json"], default="prompt",
        help="prompt = paste-ready markdown (default); json = machine-readable",
    )
    ab.add_argument(
        "--include-existing",
        action="store_true",
        help="Include current target text for empty/stale/no_state rows",
    )
    ab.add_argument("--split", choices=["locale", "namespace"], default=None,
                    help="Write one part file per locale or namespace instead of one document")
    ab.add_argument("--out-dir", dest="out_dir", default=None, help="Directory for --split parts")
    ab.add_argument("--budget-tokens", dest="budget_tokens", type=int, default=15000,
                    help="Max estimated tokens per part (default 15000)")

    def _add_agent_hardcoded(parser: argparse.ArgumentParser) -> None:
        add_project_args(parser)
        parser.add_argument("--adapter", default=None, help="Scan adapter (default: [scan] adapter)")
        parser.add_argument("--limit", "--max-files", dest="limit", type=int, default=None,
                            help="Max source files to read")
        parser.add_argument(
            "--format", dest="fmt", choices=["prompt", "json"], default="prompt",
            help="prompt = paste-ready markdown (default); json = machine-readable",
        )
        parser.add_argument("--split", choices=["auto"], default=None,
                            help="Write agent-sized parts plus index.md instead of one document")
        parser.add_argument("--budget-tokens", type=int, default=15000,
                            help="Target size per part (chars/4 estimate)")
        parser.add_argument("--max-hits", type=int, default=150, help="Max hits per part")
        parser.add_argument("--out-dir", default=None,
                            help="Where --split writes (default: <root>/reports/hardcoded)")
        parser.add_argument(
            "--llm", action="store_true",
            help="Second pass with the local model (slow). Off by default. Dry-run lists files only.",
        )
        parser.add_argument("--dry-run", action="store_true", help="List files; do not call the model")
        parser.add_argument(
            "--refresh", action="store_true",
            help="Rescan even when no source file changed since the last report",
        )
        parser.add_argument(
            "--show-ignored", action="store_true",
            help="Also list hits you marked ignored with scan-decide",
        )
        parser.add_argument(
            "--show-low", action="store_true",
            help="Include low-confidence hits (default: high and medium only)",
        )
        parser.add_argument(
            "--status", action="store_true",
            help="Print scan-cache / en-XX readiness JSON (no rescan); includes next[] hints",
        )

    ah = sub.add_parser(
        "agent-hardcoded",
        help="Report hardcoded product strings for an agent to fix in source (writes nothing)",
    )
    _add_agent_hardcoded(ah)
    ah.add_argument("--no-catalogue-audit", dest="catalogue_audit", action="store_false",
                    help="Skip the catalogue-gap section of the report")
    rah = sub.add_parser(
        "run-agent-hardcoded",
        help="Execute the hardcoded-string model pass (invoked by taskqueue)",
    )
    _add_agent_hardcoded(rah)
    rah.add_argument("--no-catalogue-audit", dest="catalogue_audit", action="store_false",
                     help="Skip the catalogue-gap section of the report")


def _add_explain_scan(sub: argparse._SubParsersAction) -> None:
    """Subcommands: explain-scan."""
    ex = sub.add_parser(
        "explain-scan",
        help="Why the hardcoded-string scanner did or did not report FILE:LINE (skip rules, filters, sink, tier)",
    )
    add_project_args(ex)
    ex.add_argument("target", help="path:line relative to the project root (path alone lists the file's hits)")
    ex.add_argument("--adapter", default=None, help="Scan adapter (default: [scan] adapter)")
    ex.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")


def _add_scan_decide(sub: argparse._SubParsersAction) -> None:
    """Subcommands: scan-decide."""
    sd = sub.add_parser(
        "scan-decide",
        help="Accept or ignore scan results; what apply then writes follows [apply] mode",
    )
    add_project_args(sd)
    sd.add_argument("action", choices=["accept", "ignore", "reset", "status"], nargs="?", default="status")
    sd.add_argument("--kind", choices=["hit", "collection"], default="hit")
    sd.add_argument("--ids", type=_csv, default=None, help="Comma list of ids from the report")
    sd.add_argument("--confidence", choices=["high", "medium", "low"], default=None,
                    help="Select every pending hit of this confidence")
    sd.add_argument("--file", default=None, help="Select pending hits in files matching this glob")
    sd.add_argument("--all-pending", action="store_true", help="Select every pending item")
    sd.add_argument("--key", default=None, help="Catalogue key for one accepted hit")
    sd.add_argument("--note", default="", help="Reason, stored with the decision")
    sd.add_argument("--by", default="", help="Who decided (default: cli)")
    sd.add_argument("--adapter", default=None, help="Scan adapter (default: [scan] adapter)")
    sd.add_argument("--limit", type=int, default=None, help="Max source files to scan")
    sd.add_argument("--format", dest="fmt", choices=["text", "json"], default="text")


def _add_patch(sub: argparse._SubParsersAction) -> None:
    """Subcommands: patch."""
    pt = sub.add_parser(
        "patch",
        help="Generate a structured changeset (hardcoded strings + catalogue gaps). Writes nothing.",
    )
    add_project_args(pt)
    pt.add_argument("--adapter", default=None, help="Scan adapter (default: [scan] adapter)")
    pt.add_argument("--limit", type=int, default=None, help="Max source files to scan")
    pt.add_argument(
        "--out-dir", default=None,
        help="Write patch.json and patch.md here (default: print only)",
    )
    pt.add_argument(
        "--format", dest="fmt", choices=["json", "text"], default="text",
        help="Output format (default: text)",
    )


def _add_apply(sub: argparse._SubParsersAction) -> None:
    """Subcommands: apply."""
    ap = sub.add_parser(
        "apply",
        help="Apply catalogue additions from scan (writes catalogue files, not source files)",
    )
    add_project_args(ap)
    ap.add_argument("--adapter", default=None, help="Scan adapter (default: [scan] adapter)")
    ap.add_argument("--limit", type=int, default=None, help="Max source files to scan")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change; write nothing")
    ap.add_argument("--confirm", action="store_true",
                    help="Required to actually write (unless --dry-run)")
    ap.add_argument("--no-enqueue-translate", dest="enqueue_translate", action="store_false",
                    help="Do not enqueue a translate task after writing new keys")


def _add_migrate_state(sub: argparse._SubParsersAction) -> None:
    """Subcommands: migrate-state."""
    mg = sub.add_parser(
        "migrate-state",
        help="Recompute derived state fields after a signature-format change (no LLM)",
        description="Rewrites structure_sig from the current source. Leaves "
                    "src_sha, translated_at, model, and status untouched, so no "
                    "translation is invalidated.",
    )
    add_project_args(mg)
    mg.add_argument("--locales", type=_csv, default=None)
    mg.add_argument("--dry-run", action="store_true", help="Report without writing")
    mg.add_argument(
        "--stamp-provider",
        action="store_true",
        help="Write inferred provider (ADR-19) onto state entries that lack one",
    )


def _add_guide(sub: argparse._SubParsersAction) -> None:
    """Subcommands: guide."""
    gd = sub.add_parser(
        "guide",
        help="Show what to do next, step by step, from an empty folder to translations",
        description="A checklist of the steps to localize a project, with the exact "
                    "command for the next one. Reads your project; changes nothing "
                    "unless you pass --smoke-test.",
    )
    add_project_args(gd)
    gd.add_argument("--dir", default=None, dest="directory", metavar="PATH",
                    help="Folder to inspect when there is no config yet (default: cwd)")
    gd.add_argument("--smoke-test", action="store_true", dest="smoke_test",
                    help="Translate one short string with the configured model to confirm it works")
    gd.add_argument("--skip-provider", action="store_true", dest="skip_provider",
                    help="Do not contact Ollama or any provider")
    gd.add_argument("--yes", action="store_true",
                    help="Allow --smoke-test to send one string to a paid cloud provider")
    gd.add_argument("--json", action="store_true", help="Machine-readable output")
    gd.add_argument("--no-input", action="store_true", dest="no_input",
                    help="Only print the checklist; do not offer to run the next step")


def _add_init(sub: argparse._SubParsersAction) -> None:
    """Subcommands: init."""
    i = sub.add_parser("init", help="Detect the catalogue layout and write a config file")
    i.add_argument("directory", nargs="?", default=None, help="Project root (default: cwd)")
    i.add_argument("--name", default=None, help="Project name (default: directory name)")
    i.add_argument("--source-locale", default="en")
    i.add_argument("--format", default=None, dest="catalog_format",
                   help="Catalogue format (json-flat, json-nested, po, yaml, arb, android-xml). "
                        "Bypasses auto-detection. Requires --path.")
    i.add_argument("--path", default=None, dest="catalog_path",
                   help="Path template, e.g. 'taskqueue/static/locales/{locale}.json'. "
                        "Required when --format is given.")
    i.add_argument("--taskqueue", action="store_true",
                   help="Also generate the taskqueue blueprint(s)")
    i.add_argument("--no-register", action="store_true",
                   help="Skip adding an entry to ~/.llm_localize/projects.yaml")
    i.add_argument("--force", action="store_true", help="Overwrite an existing config")
    i.add_argument("--targets", type=_csv, default=None, metavar="LIST",
                   help="Comma-separated languages to translate into, e.g. pl,de,ar")
    i.add_argument("--model", default=None,
                   help="Model that translates (default: llama3.2)")
    i.add_argument("--domain", default=None,
                   help="One sentence describing your product (goes into every prompt)")
    i.add_argument("--provider", default=None,
                   help="Provider kind (default: ollama, which runs on your machine)")
    i.add_argument("--approach", default=None, choices=["local", "cloud", "agent", "human", "hybrid"],
                   help="How the project is localized (see `llm-localizator approach`)")
    i.add_argument("--yes", action="store_true",
                   help="Do not ask questions; use detected values and the defaults")

    cp = sub.add_parser("context-propose",
                        help="Suggest translator notes for short placeholder frames (read-only)")
    add_project_args(cp)
    cp.add_argument("--write", action="store_true", help="Write the proposed notes")
    sc = sub.add_parser("server-copy",
                        help="People-facing English in Python server code ([scan] server_dirs)")
    add_project_args(sc)
    sc.add_argument("--format", dest="fmt", choices=("text", "json"), default="text")
    gl = sub.add_parser("glossary-learn",
                        help="Propose glossary terms from repeated manual corrections (read-only)")
    add_project_args(gl)
    gl.add_argument("--locale", required=True)
    gl.add_argument("--write", action="store_true",
                    help="Save the proposals in the data home for a person to confirm")
    ir = sub.add_parser("import-review",
                        help="Apply the decision column of a review-risk CSV through set --by human")
    add_project_args(ir)
    ir.add_argument("csv_path", metavar="CSV")
    ir.add_argument("--locale", required=True)
    ir.add_argument("--dry-run", action="store_true")
    cn = sub.add_parser("context-note", help="Write one per-key translator note")
    add_project_args(cn)
    cn.add_argument("--key", required=True)
    cn.add_argument("--note", default=None)
    cn.add_argument("--approve", action="append", default=[], metavar="LOCALE=TEXT",
                    help="A translation a person approved for this key; used before the model (ADR-137)")

    ob = sub.add_parser(
        "onboard",
        help="Set up a project in one step: init, approach, frozen locales, runtime path, tq check",
    )
    ob.add_argument("directory", nargs="?", default=None, help="App root (default: cwd)")
    ob.add_argument("--targets", type=_csv, default=None, help="Languages to ship, e.g. pl,de")
    ob.add_argument("--frozen", type=_csv, default=None, help="Layout-check languages, e.g. zh,ar")
    ob.add_argument("--approach", default=None, choices=["local", "cloud", "agent", "human", "hybrid"])
    ob.add_argument("--runtime-path", default=None, help="[web] runtime_path for plain JS apps")
    ob.add_argument("--install-runtime", action="store_true", help="Also write i18n.js into the app")
    ob.add_argument("--no-register", action="store_true")

    cy = sub.add_parser(
        "cycle",
        help="One pass: check keys, validate, status (queue translate), review risk, hardcoded; one report",
    )
    add_project_args(cy)
    cy.add_argument("--locales", default=None, help="Comma-separated (default: active targets)")
    cy.add_argument("--translate", action="store_true", help="Queue due strings through taskqueue")
    cy.add_argument("--repair", action="store_true",
                    help="Queue a forced retranslation of keys failing V03/V04/V43/V46/V47")
    cy.add_argument("--follow", action="store_true",
                    help="With --repair: wait for the queued repair, revalidate those keys, retry once, list the stuck ones")
    cy.add_argument("--follow-timeout", type=float, default=3600.0, help="Seconds to wait per attempt")
    cy.add_argument("--review-limit", type=int, default=15)

    rr = sub.add_parser(
        "review-risk",
        help="Rank a locale's translations by how much a person should read them (read-only)",
    )
    add_project_args(rr)
    rr.add_argument("--locale", required=True)
    rr.add_argument("--limit", type=int, default=50)
    rr.add_argument("--format", dest="fmt", choices=["text", "json", "csv"], default="text")

    st = sub.add_parser(
        "set",
        help="Write one translation through the candidate gate, with provenance stamps",
        description="Runs the normalizer and hard checks on TEXT, writes it to the catalogue "
                    "and records state/history. --by agent (default) or human.",
    )
    add_project_args(st)
    st.add_argument("--locale", required=True)
    st.add_argument("--key", required=True, help="namespace.key, or the flat key")
    st.add_argument("--text", required=True)
    st.add_argument("--by", choices=["agent", "human"], default="agent")
    st.add_argument("--model", default=None, help="Model or agent id recorded with the edit")
    st.add_argument("--force", action="store_true", help="Write even if the gate rejects it")

    hp = sub.add_parser(
        "help",
        help="Print the guide for people (human) or for AI agents (agent)",
        description="The packaged guides (llm_localizator/help/*.md). --path prints the file path.",
    )
    hp.add_argument("guide", nargs="?", choices=["human", "agent"])
    hp.add_argument("--path", action="store_true", help="Print the file path instead of the text")
    hp.add_argument("--code", metavar="TOPIC",
                    help="Page for one programming ecosystem (android, swift, js-ts, ...); see --topics")
    hp.add_argument("--lang", metavar="CODE",
                    help="Page for one human language (ar, pl, th, zh, ...): plurals, typography, grammar, practice")
    hp.add_argument("--topics", action="store_true", help="List the --code and --lang topics")
    hp.add_argument("--regenerate", action="store_true",
                    help="Rewrite the generated tables in both guides (repository checkout only)")

    sk = sub.add_parser(
        "skill",
        help="Install or check the agent guide as a Claude skill in the project",
        description="Writes .claude/skills/llm-localizator/SKILL.md (the agent guide) into the "
                    "project. check exits 1 when it is missing, edited or outdated.",
    )
    sk.add_argument("action", choices=["install", "check"])
    add_project_args(sk)
    sk.add_argument("--force", action="store_true",
                    help="Replace a SKILL.md that llm-localizator did not write")

    en = sub.add_parser(
        "engine",
        help="Pick the engine (provider + model for every pipeline role): Claude, DeepSeek, OpenAI or local by VRAM",
        description="list: the engines and whether this machine can run them. recommend: the best fit (API keys "
                    "present, GPU size). show ID: what an engine sets. apply ID: write [engine] id and remove the "
                    "project keys that would hide it; [privacy] and [budget] are never written (ADR-156).",
    )
    en.add_argument("action", nargs="?", default="list", choices=["list", "show", "recommend", "apply", "fetch"])
    en.add_argument("engine_id", nargs="?", default=None, help="Engine id for show / apply")
    add_project_args(en)
    en.add_argument("--accept-unbenchmarked", action="store_true",
                    help="Apply an engine without benchmark evidence (ADR-12)")
    en.add_argument("--vram", type=float, default=None, help="GPU memory in GB, when nvidia-smi cannot tell")
    en.add_argument("--gpu-busy", action="store_true", help="Recommend only engines that leave the GPU free")
    en.add_argument("--from", dest="url", default=None,
                    help="fetch: base URL holding index.json (default https://llm-localizator.dev/engines/)")
    en.add_argument("--write", action="store_true", help="fetch: save new or updated engines (default: dry run)")
    en.add_argument("--accept-unverified", action="store_true",
                    help="fetch: also save engines this release did not ship (read them first)")
    en.add_argument("--json", action="store_true", help="Print the result as JSON")

    qe = sub.add_parser(
        "queue-engine",
        help="Rewrite the project's existing taskqueue blueprints for one engine (never creates a blueprint)",
        description="Regenerates only the experiments/operator_queue blueprints that already exist, with "
                    "--engine ID baked into args and the GPU reservation sized for that engine, and prints a "
                    "before/after table (task, model, VRAM, lane). The project config is not changed.",
    )
    qe.add_argument("engine_id", help="Engine id (see `llm-localizator engine list`)")
    add_project_args(qe)
    qe.add_argument("--dry-run", action="store_true", help="Print the table; write nothing")

    ap = sub.add_parser(
        "approach",
        help="Show how this project can be localized (local, cloud, agent, human, hybrid)",
        description="Lists who can write the translations, what each needs and costs, and a "
                    "recommendation for this machine. --set records the choice as "
                    "[translate] approach; the guide adapts its next steps to it.",
    )
    add_project_args(ap)
    ap.add_argument("--set", dest="set_to", default=None,
                    choices=["local", "cloud", "agent", "human", "hybrid"],
                    help="Record this approach in .llm-localize.toml")
    ap.add_argument("--json", action="store_true", help="Print the options as JSON")
