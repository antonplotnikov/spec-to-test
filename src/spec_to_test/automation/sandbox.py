"""Process isolation shared by the test runner and the Playwright MCP server.

Child processes get:
- a minimal environment (no API keys, no server settings, only the secrets
  this run needs) with a private HOME and TMPDIR inside the job folder,
- resource limits (CPU seconds, largest file, open files), applied by a tiny
  exec wrapper because `preexec_fn` is not safe in a multi-threaded server,
- their own process group, so a timeout or Cancel stops Chromium too.
Chromium's own sandbox stays on unless the deployment runs in a container
that is the sandbox (AUTOMATION_CHROMIUM_SANDBOX=false, see Dockerfile).
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from spec_to_test.automation.config import AutomationConfig

MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_OPEN_FILES = 4096
_PASS_THROUGH = ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT")

_LIMITS_WRAPPER = """
import os, resource, sys
for name, value in ((resource.RLIMIT_CPU, int(sys.argv[1])), (resource.RLIMIT_FSIZE, int(sys.argv[2])),
                    (resource.RLIMIT_NOFILE, int(sys.argv[3]))):
    soft, hard = resource.getrlimit(name)
    value = value if hard == resource.RLIM_INFINITY else min(value, hard)
    try:
        resource.setrlimit(name, (value, hard))
    except (ValueError, OSError):
        pass
os.execv(sys.argv[4], sys.argv[4:])
"""


def browsers_path() -> str:
    """Where Playwright keeps its browsers (needed because HOME is replaced)."""
    if configured := os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return configured
    home = Path.home()
    if sys.platform == "darwin":
        return str(home / "Library" / "Caches" / "ms-playwright")
    if sys.platform == "win32":
        return str(Path(os.environ.get("LOCALAPPDATA", home)) / "ms-playwright")
    return str(Path(os.environ.get("XDG_CACHE_HOME", home / ".cache")) / "ms-playwright")


PRIVATE_PREFIX = "stt-"


def _private_root() -> str | None:
    return "/tmp" if os.name == "posix" and os.path.isdir("/tmp") else None  # noqa: S108 - mkdtemp: 0700, random


def prune_private_dirs(max_age_seconds: float) -> int:
    """Remove this user's private folders left behind by a killed server.

    A job removes its folder when it ends, but a force-quit leaves it (with the
    MCP config that holds secret values). Anything older than the longest
    possible job cannot belong to a running one.
    """
    root = Path(_private_root() or tempfile.gettempdir())
    cutoff = time.time() - max_age_seconds
    removed = 0
    for path in root.glob(f"{PRIVATE_PREFIX}*"):
        try:
            info = path.lstat()
        except OSError:
            continue
        if path.is_dir() and not path.is_symlink() and info.st_uid == os.getuid() and info.st_mtime < cutoff:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def private_dir(prefix: str = PRIVATE_PREFIX) -> Path:
    """A fresh owner-only folder with a short path.

    Short matters: Chromium and Playwright put Unix sockets under TMPDIR, and
    Playwright refuses socket paths longer than about 80 bytes, so a folder deep inside the job
    directory does not work. The caller removes it when the process is done.
    """
    return Path(tempfile.mkdtemp(prefix=prefix, dir=_private_root()))


def sandbox_env(private_dir: Path, secrets: dict[str, str] | None = None) -> dict[str, str]:
    home = private_dir / "home"
    tmp = private_dir / "tmp"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = {key: os.environ[key] for key in _PASS_THROUGH if key in os.environ}
    env.update(
        {
            "HOME": str(home),
            "TMPDIR": str(tmp),
            "PLAYWRIGHT_BROWSERS_PATH": browsers_path(),
            "CI": "1",
            "FORCE_COLOR": "0",
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        }
    )
    env.update(secrets or {})
    return env


def limited_command(command: list[str], cpu_seconds: int) -> list[str]:
    """Prefix a command so it runs with resource limits (POSIX only)."""
    if sys.platform == "win32":
        return command
    return [
        sys.executable, "-I", "-c", _LIMITS_WRAPPER,
        str(cpu_seconds), str(MAX_FILE_BYTES), str(MAX_OPEN_FILES), *command,
    ]


def kill_tree(process: subprocess.Popen[bytes], grace: float = 5.0) -> None:
    """Stop a process and everything it started (it leads its own session)."""
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace)
    except (ProcessLookupError, PermissionError):
        return
    except subprocess.TimeoutExpired:
        try:
            if sys.platform == "win32":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        process.wait(timeout=grace)


def node_command(config: AutomationConfig, script: Path, *args: str) -> list[str]:
    node = config.node
    if node is None:
        raise FileNotFoundError("node")
    return [node, str(script), *args]
