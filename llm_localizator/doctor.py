"""Environment and project health checks for ``llm-localizator doctor``."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

from . import __version__

__all__ = ["Check", "run_doctor", "package_info", "ui_digest"]


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


# PyPI distribution name; older checkouts were installed as "llm-localizator".
DISTRIBUTION_NAMES = ("llm_localizator", "llm-localizator", "llmlocalize", "llm-localize")


def _distribution_name() -> str:
    """The installed distribution that provides this package, or ''."""
    for name in DISTRIBUTION_NAMES:
        try:
            pkg_version(name)
        except PackageNotFoundError:
            continue
        return name
    return ""


def package_info() -> dict[str, str]:
    """Installed package location and version."""
    import llm_localizator

    root = Path(llm_localizator.__file__).resolve().parent
    info: dict[str, str] = {
        "version": __version__,
        "packagePath": str(root),
        "python": sys.version.split()[0],
    }
    dist_name = _distribution_name()
    try:
        dist_ver = pkg_version(dist_name) if dist_name else ""
        info["distributionVersion"] = dist_ver or "(not installed)"
    except PackageNotFoundError:
        info["distributionVersion"] = "(not installed)"
    try:
        import importlib.metadata as im

        dist = im.distribution(dist_name)
        editable = dist.read_text("direct_url.json")
        if editable and "dir_info" in editable:
            info["installMode"] = "editable"
        else:
            info["installMode"] = "site-packages"
    except Exception:
        info["installMode"] = "unknown"
    return info


def ui_digest(page: str | None = None) -> str:
    if page is None:
        from .web.assets import ui_source

        page = ui_source()
    return hashlib.sha256(page.encode("utf-8")).hexdigest()[:12]


def _loopback_closed(url: str) -> bool:
    """True when *url* is on this machine and nothing listens on its port.

    M5: on Windows a refused loopback connection is reported only after the client's retries, about 2 s, so every
    probe of a stopped server cost the full timeout. A local listener accepts in milliseconds; 0.3 s is plenty.
    """
    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.hostname not in ("127.0.0.1", "localhost", "::1"):
        return False
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname, port), timeout=0.3):
            return False
    except OSError:
        return True


def _fetch_json(url: str, timeout: float):
    """GET *url* and parse the JSON body (raises on any network or parse error)."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def _ping_ollama(url: str) -> Check:
    if _loopback_closed(url):
        return Check("ollama", "warn", f"not reachable at {url}: connection refused")
    try:
        data = _fetch_json(f"{url.rstrip('/')}/api/tags", 3)
        models = [m.get("name", "") for m in data.get("models", [])]
        return Check("ollama", "ok", f"{len(models)} model(s) at {url}")
    except Exception as exc:
        return Check("ollama", "warn", f"not reachable at {url}: {exc}")


def _check_web(port: int, expected_digest: str, expected_version: str) -> Check:
    base = f"http://127.0.0.1:{port}"
    if _loopback_closed(base):
        return Check("web", "ok", f"no server on :{port}")
    try:
        data = _fetch_json(f"{base}/api/version", 2)
        running_ver = data.get("version", "?")
        running_digest = data.get("uiDigest", "")
        if running_ver != expected_version or running_digest != expected_digest:
            return Check(
                "web",
                "warn",
                f"running server is stale (server v{running_ver} ui={running_digest}; "
                f"installed v{expected_version} ui={expected_digest}) — restart "
                f"`llm-localizator web`",
            )
        return Check("web", "ok", f"server on :{port} matches installed package")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return Check(
                "web",
                "warn",
                f"server on :{port} has no /api/version — restart `llm-localizator web` "
                "to pick up current UI",
            )
        return Check("web", "warn", f"server on :{port} returned HTTP {exc.code}")
    except urllib.error.URLError:
        return Check("web", "ok", f"no server on :{port}")
    except Exception as exc:
        return Check("web", "warn", f"could not probe :{port}: {exc}")


def _pid_listening_on(port: int) -> int | None:
    if sys.platform != "win32":
        return None
    import subprocess

    try:
        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace")
    except Exception:
        return None
    for line in out.splitlines():
        if f":{port}" not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if parts:
            try:
                return int(parts[-1])
            except ValueError:
                continue
    return None


_KEY_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "deepl": "DEEPL_AUTH_KEY",
    "openai_compat": "OPENAI_COMPAT_API_KEY",
}


def _dependency_checks() -> list[Check]:
    """Packages the tool needs. Say what is missing instead of failing with a stack trace."""
    import importlib.util

    missing = [name for name, module in (("pyyaml", "yaml"), ("tomlkit", "tomlkit"))
               if importlib.util.find_spec(module) is None]
    if not missing:
        return []
    return [Check(
        "dependencies", "fail",
        f"missing: {', '.join(missing)}. Install the package (`pip install llm-localizator`, "
        "`uv tool install llm-localizator`) or run it from a checkout with `uv run`.",
    )]


def _key_checks(cfg) -> list[Check]:
    """Whether a cloud provider has a key. Reports the variable's name, never its value."""
    from .providers.keys import candidate_vars, key_source

    provider = getattr(cfg, "provider", None)
    kind = (getattr(provider, "kind", "") or "").lower()
    vendor_var = _KEY_VARS.get(kind)
    if not vendor_var:
        return []
    env = getattr(provider, "api_key_env", None)
    found = key_source(vendor_var, env)
    if found:
        return [Check("api-key", "ok", f"{kind}: key read from ${found}")]
    return [Check(
        "api-key", "warn",
        f"{kind}: no key found; set one of {', '.join('$' + n for n in candidate_vars(vendor_var, env))} "
        "(see docs/configuration.md, Setting an API key)",
    )]


def run_doctor(
    cfg=None,
    *,
    web_port: int = 8770,
    skip_ollama: bool = False,
) -> list[Check]:
    """Run health checks; ``cfg`` is optional ``ProjectConfig``."""
    checks: list[Check] = []
    checks.extend(_dependency_checks())
    pinfo = package_info()
    digest = ui_digest()

    checks.append(Check(
        "package",
        "ok",
        f"v{pinfo['version']} ({pinfo['installMode']}) at {pinfo['packagePath']}",
    ))
    if pinfo.get("distributionVersion") not in (pinfo["version"], "(not installed)"):
        checks.append(Check(
            "package",
            "warn",
            f"distribution metadata says {pinfo['distributionVersion']}",
        ))

    web_check = _check_web(web_port, digest, __version__)
    if "no server" not in web_check.detail:
        checks.append(web_check)
    if "no server" in web_check.detail:
        pid = _pid_listening_on(web_port)
        if pid:
            checks.append(Check(
                "web-port",
                "warn",
                f"PID {pid} is listening on :{web_port} but it is not llm-localizator",
            ))

    if shutil.which("tq"):
        checks.append(Check("taskqueue", "ok", "tq found on PATH"))
    else:
        checks.append(Check("taskqueue", "warn", "tq not on PATH (submit commands need it)"))

    if cfg is not None:
        checks.append(Check("config", "ok", str(cfg.config_path or cfg.root)))
        checks.extend(_key_checks(cfg))
        try:
            catalog = __import__(
                "llm_localizator.catalog", fromlist=["build_catalog"]
            ).build_catalog(
                cfg.catalog_format, cfg.root, cfg.catalog_path, cfg.source_locale,
            )
            namespaces = cfg.namespaces_for(catalog)
            keys = sum(len(catalog.load(cfg.source_locale, ns)) for ns in namespaces)
            checks.append(Check(
                "catalog", "ok", f"{len(namespaces)} namespace(s), {keys} source key(s)",
            ))
            if keys == 0:
                checks.append(Check(
                    "source", "fail",
                    f"no {cfg.source_locale} strings found at {cfg.catalog_path} — "
                    "add your source strings, or fix [catalog] path in the config",
                ))
        except Exception as exc:
            checks.append(Check("catalog", "fail", str(exc)))

        try:
            from .catalog.store_metadata import store_metadata_gaps

            for gap in store_metadata_gaps(cfg.root, cfg.source_locale):
                files = list(gap.missing)
                example = files[0]
                checks.append(Check(
                    "store-text", "warn",
                    f"{gap.folder}: {len(files)} store file(s) only in {gap.source}, e.g. {example} "
                    f"(missing in {', '.join(gap.missing[example][:4])})",
                ))
        except OSError:
            pass

        checks.extend(scan_checks(cfg))

        if not cfg.targets:
            checks.append(Check(
                "targets", "warn",
                "no target languages yet — add one: llm-localizator add-locale --locale pl",
            ))
        else:
            try:
                for locale in cfg.targets:
                    cfg.model_for(locale)
            except ValueError as exc:
                checks.append(Check("model", "fail", str(exc)))

        state_root = cfg.state_root()
        checks.append(Check(
            "data-home",
            "ok",
            f"{cfg.data_home} → {cfg.data_root()}",
        ))
        if state_root.exists():
            writable = os_access_writable(state_root)
            checks.append(Check(
                "state",
                "ok" if writable else "warn",
                f"{state_root}" + ("" if writable else " (not writable)"),
            ))
        else:
            checks.append(Check(
                "state", "ok", f"{state_root} (created on the first translation)",
            ))
        from .catalog.flush_journal import flush_block_message

        blocked = flush_block_message(state_root)
        if blocked:
            checks.append(Check("flush", "warn", blocked))

        try:
            from .catalog import StateStore

            changed = StateStore(state_root).integrity_issues() if state_root.is_dir() else []
        except Exception as exc:
            changed = []
            checks.append(Check("state-integrity", "warn", f"could not check state: {exc}"))
        if changed:
            checks.append(Check(
                "state-integrity", "warn",
                f"state edited outside llm-localizator: {', '.join(changed)} (run adopt, then any write reseals)",
            ))

        if cfg.context_dir:
            from .projects.context import context_json_errors

            errors = context_json_errors(cfg.context_dir)
            if errors:
                checks.append(Check("context", "fail", "; ".join(errors)))
            elif cfg.context_dir.is_dir():
                checks.append(Check("context", "ok", str(cfg.context_dir)))
            else:
                checks.append(Check("context", "warn", f"missing: {cfg.context_dir}"))

        if not skip_ollama:
            ollama_check = _ping_ollama(cfg.provider.url)
            if ollama_check.status == "warn" and (cfg.provider.kind or "ollama") == "ollama":
                # The project translates with Ollama, so say how to start it. It stays a
                # warning: doctor is also run where no model server is up (CI, a fresh
                # checkout). ``doctor --strict`` turns this warning into a failure.
                from .providers.ollama import ollama_unreachable_message

                ollama_check = Check(
                    "ollama", "warn",
                    ollama_unreachable_message(cfg.provider.url),
                )
            checks.append(ollama_check)
            if ollama_check.status == "ok" and (cfg.provider.kind or "ollama") == "ollama":
                from .providers.ollama import OllamaProvider
                from .providers.preflight import (
                    configured_model_pins,
                    missing_configured_models,
                )

                provider = OllamaProvider(url=cfg.provider.url)
                installed = provider.available_models()
                missing = missing_configured_models(cfg, installed)
                if missing:
                    checks.append(Check(
                        "models",
                        "warn",
                        "configured but not installed: "
                        + ", ".join(missing)
                        + f" — run `ollama pull {' '.join(missing[:1])}`"
                        + (" …" if len(missing) > 1 else ""),
                    ))
                elif configured_model_pins(cfg):
                    checks.append(Check(
                        "models",
                        "ok",
                        f"{len(configured_model_pins(cfg))} configured pin(s) present locally",
                    ))
    elif not skip_ollama:
        checks.append(_ping_ollama("http://127.0.0.1:11434"))

    if cfg is not None:
        checks.extend(consumer_checks(cfg))
    return checks


def scan_checks(cfg) -> list[Check]:
    """``[scan]`` warnings (M6): missing folders, file types no scanner reads, Xcode targets without the catalogue."""
    checks: list[Check] = []
    if not cfg.scan_adapter and not cfg.scan_src_dirs:
        return checks   # the project does not use the hardcoded-string scanner
    root = Path(cfg.root)
    missing = [d for d in cfg.scan_src_dirs if d not in (".", "") and not (root / d).is_dir()]
    if missing:
        checks.append(Check(
            "scan", "warn", f"[scan] src_dirs not found: {', '.join(missing)} — fix the paths or remove them",
        ))
    try:
        from .scan import scanner_from_config
        from .scan.base import count_unsupported

        scanner = scanner_from_config(cfg)
        unsupported = count_unsupported(scanner)
    except (ValueError, OSError) as exc:
        checks.append(Check("scan", "warn", f"[scan] cannot build the scanner: {exc}"))
        return checks
    if unsupported:
        listed = ", ".join(f"{ext} ({n})" for ext, n in list(unsupported.items())[:6])
        checks.append(Check(
            "scan", "warn",
            f"NOT scanned: {listed} — no scanner reads these file types; check them by hand or [scan] exclude them",
        ))
    checks.extend(_xcode_catalogue_checks(root))
    if not checks:
        checks.append(Check("scan", "ok", f"[scan] {cfg.scan_adapter or 'source'}: {', '.join(cfg.scan_src_dirs) or '.'}"))
    return checks


def _xcode_catalogue_checks(root: Path) -> list[Check]:
    """B20: a target that compiles Swift but does not ship ``Localizable`` shows its ``Text("…")`` untranslated."""
    if not any(root.glob("*.xcodeproj")) and not any(root.glob("*/*.xcodeproj")):
        return []
    from .scan.project_index import ProjectIndex

    index = ProjectIndex(root)
    if not index.apple_keys:
        return []
    compiled = set().union(*index.apple_sources.values()) if index.apple_sources else set()
    lacking = sorted(compiled - index.apple_catalogue_targets)
    if not lacking:
        return []
    return [Check(
        "scan", "warn",
        f"Xcode target(s) {', '.join(lacking[:4])} compile Swift but do not ship Localizable.strings/.xcstrings: "
        "their Text(\"…\") stays English — add the catalogue to the target's Copy Bundle Resources",
    )]


def consumer_checks(cfg) -> list[Check]:
    """Runtime drift, key wiring, en-XX freshness, QA crawl reachability, approach (P5)."""
    out: list[Check] = []
    if not getattr(cfg, "translate_approach", ""):
        out.append(Check("approach", "warn",
                         "no approach chosen; see `llm-localizator approach` (ADR-123)"))
    if getattr(cfg, "web_runtime_path", ""):
        from .ops.web_runtime import op_runtime

        r = op_runtime(cfg, "check")
        out.append(Check("runtime", "ok" if r.ok else "warn", r.summary))
    if getattr(cfg, "scan_src_dirs", None):
        try:
            from .ops.web_runtime import op_check_keys

            r = op_check_keys(cfg)
            out.append(Check("keys", "ok" if r.ok else "warn", r.summary))
        except Exception as exc:  # noqa: BLE001 - a doctor never crashes
            out.append(Check("keys", "warn", f"check-keys failed: {exc}"))
    try:  # C3 (ADR-136): an installed agent skill older than the packaged guide misleads agents
        from .ops.skill import op_skill

        sk = op_skill(cfg, "check")
        state = (sk.data or {}).get("state")
        if state == "outdated":
            out.append(Check("skill", "warn", sk.summary))
        elif state == "current":
            out.append(Check("skill", "ok", sk.summary))
    except Exception as exc:  # noqa: BLE001 - a doctor never crashes
        out.append(Check("skill", "warn", f"skill check failed: {exc}"))
    qa = getattr(cfg, "qa", None)
    if qa is not None:
        import urllib.error
        import urllib.request

        try:
            if _loopback_closed(qa.base_url):
                raise urllib.error.URLError("connection refused")
            urllib.request.urlopen(qa.base_url + "/", timeout=2)
            out.append(Check("qa", "ok", f"{qa.base_url} answers"))
        except urllib.error.HTTPError:
            out.append(Check("qa", "ok", f"{qa.base_url} answers"))
        except (urllib.error.URLError, OSError, TimeoutError):
            hint = "`hardcoded-hunt --serve` can start it" if qa.start else "start the app before a crawl"
            out.append(Check("qa", "warn", f"{qa.base_url} is not running; {hint}"))
    return out


def os_access_writable(path: Path) -> bool:
    try:
        test = path / ".llm_localize_write_test"
        test.write_text("", encoding="utf-8")
        test.unlink(missing_ok=True)
        return True
    except OSError:
        return False
