"""Automation settings, read from the process environment only.

Like the storage mode, these are never read from a .env file, so a stray file
cannot widen the host allowlist of a shared deployment. On Streamlit Cloud
(or with .streamlit/secrets.toml) root-level secrets become environment
variables, which works too.

AUTOMATION_ALLOWED_HOSTS          comma-separated staging hosts: "staging.example.com",
                                  "*.qa.example.com" or "localhost:8080". Without a port
                                  only 80/443 are allowed. Empty = Automation is off.
AUTOMATION_ALLOW_PRIVATE_NETWORK  "true" to allow hosts that resolve to private or
                                  loopback addresses (internal staging). Link-local and
                                  cloud metadata addresses are always blocked.
AUTOMATION_SECRET_<NAME>          a credential the test may type, e.g.
                                  AUTOMATION_SECRET_STAGING_PASSWORD. Claude only sees
                                  the name; values are masked in every output.
AUTOMATION_RUNNER_DIR             folder with the pinned Node toolchain (automation/runner).
AUTOMATION_NODE                   path to the node binary, when it is not on PATH
                                  (the macOS app sets it: apps start with a minimal PATH).
AUTOMATION_DATA_DIR               where job folders (code, reports, traces) are kept.
AUTOMATION_MAX_TOOL_CALLS         browser actions per exploration (default 40).
AUTOMATION_RUN_TIMEOUT            seconds for one Playwright run (default 240).
AUTOMATION_JOB_TIMEOUT            seconds for a whole job (default 1200).
AUTOMATION_MAX_JOBS               jobs running at the same time in this server (default 2).
AUTOMATION_CHROMIUM_SANDBOX       "false" only inside a container that is itself the
                                  sandbox (see Dockerfile). Default "true".
AUTOMATION_IGNORE_HTTPS_ERRORS    "true" for staging with self-signed certificates.
"""

import importlib.util
import os
import re
import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr

from spec_to_test.storage import data_dir, persistence_enabled

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNNER_DIR = REPO_ROOT / "automation" / "runner"
SECRET_PREFIX = "AUTOMATION_SECRET_"
SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_TRUE = {"1", "true", "yes", "on"}


class HostRule(BaseModel):
    """One allowlist entry. `host` is lower-case; a leading "*." allows subdomains."""

    host: str
    port: int | None = None

    @property
    def wildcard(self) -> bool:
        return self.host.startswith("*.")

    def matches(self, host: str, port: int) -> bool:
        host = host.lower().rstrip(".")
        if self.wildcard:
            suffix = self.host[1:]  # ".qa.example.com"
            host_ok = host.endswith(suffix) and len(host) > len(suffix)
        else:
            host_ok = host == self.host
        if not host_ok:
            return False
        return port == self.port if self.port is not None else port in (80, 443)

    def __str__(self) -> str:
        return f"{self.host}:{self.port}" if self.port is not None else self.host


class AutomationConfig(BaseModel):
    allowed_hosts: list[HostRule] = Field(default_factory=list)
    allow_private_network: bool = False
    secrets: dict[str, SecretStr] = Field(default_factory=dict)
    runner_dir: Path = DEFAULT_RUNNER_DIR
    node_path: str = ""
    artifacts_dir: Path
    max_tool_calls: int = 40
    run_timeout: int = 240
    job_timeout: int = 1200
    max_jobs: int = 2
    chromium_sandbox: bool = True
    ignore_https_errors: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.allowed_hosts)

    def secret_values(self) -> dict[str, str]:
        return {name: value.get_secret_value() for name, value in self.secrets.items()}

    @property
    def node(self) -> str | None:
        if self.node_path and Path(self.node_path).is_file() and os.access(self.node_path, os.X_OK):
            return self.node_path
        return shutil.which("node")

    @property
    def playwright_cli(self) -> Path:
        return self.runner_dir / "node_modules" / "@playwright" / "test" / "cli.js"

    @property
    def mcp_cli(self) -> Path:
        return self.runner_dir / "node_modules" / "@playwright" / "mcp" / "cli.js"


def parse_host_rules(raw: str) -> list[HostRule]:
    """Parse AUTOMATION_ALLOWED_HOSTS. Invalid entries are skipped, never widened."""
    rules: list[HostRule] = []
    for entry in raw.split(","):
        entry = entry.strip().lower().rstrip(".")
        if not entry or "/" in entry or "@" in entry:
            continue
        host, port = entry, None
        if entry.count(":") == 1:
            host, _, port_text = entry.partition(":")
            if not port_text.isdigit() or not 0 < int(port_text) < 65536:
                continue
            port = int(port_text)
        label = host[2:] if host.startswith("*.") else host
        # A wildcard must keep at least two labels ("*.com" would allow a whole TLD).
        if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*", label):
            continue
        if host.startswith("*.") and "." not in label:
            continue
        rules.append(HostRule(host=host, port=port))
    return rules


def _int(environ: dict[str, str], key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(environ.get(key, "").strip() or default)
    except ValueError:
        return default
    return max(low, min(high, value))


def _flag(environ: dict[str, str], key: str, default: bool) -> bool:
    raw = environ.get(key, "").strip().lower()
    return default if not raw else raw in _TRUE


_session_dir: Path | None = None


def default_artifacts_dir() -> Path:
    """Job folders: next to saved workspaces in "local" mode, else a private temp folder.

    In "session" mode nothing of the user's documents is written to disk, but a
    test run needs files (code, report, trace). They go to a folder only this
    server process uses (mode 0700), named per job with an unguessable id.
    """
    global _session_dir
    if persistence_enabled():
        return data_dir() / "automation"
    if _session_dir is None or not _session_dir.is_dir():
        _session_dir = Path(tempfile.mkdtemp(prefix="spec-to-test-automation-"))
    return _session_dir


def load_automation_config(environ: dict[str, str] | None = None) -> AutomationConfig:
    env = dict(os.environ if environ is None else environ)
    secrets = {
        key[len(SECRET_PREFIX):]: SecretStr(value)
        for key, value in env.items()
        if key.startswith(SECRET_PREFIX) and value and SECRET_NAME.match(key[len(SECRET_PREFIX):])
    }
    runner = env.get("AUTOMATION_RUNNER_DIR", "").strip()
    artifacts = env.get("AUTOMATION_DATA_DIR", "").strip()
    return AutomationConfig(
        allowed_hosts=parse_host_rules(env.get("AUTOMATION_ALLOWED_HOSTS", "")),
        allow_private_network=_flag(env, "AUTOMATION_ALLOW_PRIVATE_NETWORK", False),
        secrets=dict(sorted(secrets.items())),
        runner_dir=Path(runner) if runner else DEFAULT_RUNNER_DIR,
        node_path=env.get("AUTOMATION_NODE", "").strip(),
        artifacts_dir=Path(artifacts) if artifacts else default_artifacts_dir(),
        max_tool_calls=_int(env, "AUTOMATION_MAX_TOOL_CALLS", 40, 5, 200),
        run_timeout=_int(env, "AUTOMATION_RUN_TIMEOUT", 240, 30, 1800),
        job_timeout=_int(env, "AUTOMATION_JOB_TIMEOUT", 1200, 120, 7200),
        max_jobs=_int(env, "AUTOMATION_MAX_JOBS", 2, 1, 8),
        chromium_sandbox=_flag(env, "AUTOMATION_CHROMIUM_SANDBOX", True),
        ignore_https_errors=_flag(env, "AUTOMATION_IGNORE_HTTPS_ERRORS", False),
    )


def missing_prerequisites(config: AutomationConfig) -> list[str]:
    """What is still needed before a job can run, as automation.missing.<code> keys."""
    missing = []
    if not config.enabled:
        missing.append("allowlist")
    if config.node is None:
        missing.append("node")
    if not config.playwright_cli.is_file() or not config.mcp_cli.is_file():
        missing.append("runner")
    if importlib.util.find_spec("mcp") is None:
        missing.append("mcp_sdk")
    if importlib.util.find_spec("anthropic") is None:
        missing.append("anthropic_sdk")
    return missing
