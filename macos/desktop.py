"""Run Spec-to-Test in its own window on macOS.

Starts the Streamlit server as a child process on 127.0.0.1 and shows it in a
native window (pywebview, WebKit). Closing the window stops the server; the
server also exits by itself if the window process dies.

Started by macos/start.sh; macos/build_app.sh wraps it in Spec-to-Test.app.

Settings (AI key, Automation hosts and credentials) come from
~/Library/Application Support/Spec-to-Test/settings.env, a private file
(mode 600) created with commented examples on first launch. An app opened
from Finder gets no shell environment, so this file is where they go.
"""

from __future__ import annotations

import atexit
import html
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "Spec-to-Test"
ROOT = Path(__file__).resolve().parents[1]
SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
LOG_FILE = Path.home() / "Library" / "Logs" / APP_NAME / "server.log"
SETTINGS_FILE = SUPPORT_DIR / "settings.env"
# Only these settings are taken from the file; anything else in it is ignored.
SETTING_KEYS = (
    "AI_PROVIDER", "AI_MODEL", "AI_LOCK_SETTINGS", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "OLLAMA_HOST", "OLLAMA_MODEL",
)
SETTING_PREFIX = "AUTOMATION_"
SETTINGS_TEMPLATE = """# Spec-to-Test settings for this Mac. Only your macOS user can read this file.
# Remove the "# " in front of a line to use it, then restart Spec-to-Test.

# AI (AI analysis, Grill Mode AI interviewer, Automation). AI_PROVIDER is the default
# provider: anthropic, openai or ollama. Every provider with a key can be picked in
# the app's "AI settings"; Automation always uses Claude.
# AI_PROVIDER=anthropic
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# Local models with Ollama (no key; data stays on this Mac):
# OLLAMA_HOST=http://localhost:11434
# OLLAMA_MODEL=llama3.1
# Optional model override for the default provider:
# AI_MODEL=claude-opus-5-5

# Automation: staging hosts the browser may open (e.g. staging.example.com,
# *.qa.example.com or localhost:3000). Empty = the Automation tab stays off.
# AUTOMATION_ALLOWED_HOSTS=
# Needed for hosts on your own machine or a private network (localhost, 10.x, 192.168.x):
# AUTOMATION_ALLOW_PRIVATE_NETWORK=true
# Credentials a test may type, referenced by name (here: STAGING_PASSWORD):
# AUTOMATION_SECRET_STAGING_PASSWORD=
"""
PREFERRED_PORT = 8501
START_TIMEOUT_S = 90

# Colors from .streamlit/config.toml, so the loading screen matches the app.
PAGE_STYLE = """
body { margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center;
       background: #F7F8FC; color: #1E1B3A; font: 15px -apple-system, BlinkMacSystemFont, sans-serif; }
main { max-width: 640px; padding: 24px; text-align: center; }
h1 { font-size: 20px; font-weight: 600; margin: 16px 0 8px; }
p { color: #5B5876; margin: 4px 0; }
pre { text-align: left; background: #EEF0F8; border-radius: 12px; padding: 12px; font-size: 12px;
      white-space: pre-wrap; max-height: 40vh; overflow: auto; }
.spinner { width: 36px; height: 36px; margin: auto; border: 4px solid #E2E5F0;
           border-top-color: #4F46E5; border-radius: 50%; animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
"""


def page(body: str) -> str:
    return f"<!doctype html><html><head><style>{PAGE_STYLE}</style></head><body><main>{body}</main></body></html>"


LOADING_PAGE = page(f'<div class="spinner"></div><h1>Starting {APP_NAME}…</h1><p>This takes a few seconds.</p>')


def error_page() -> str:
    try:
        tail = "".join(LOG_FILE.read_text(errors="replace").splitlines(keepends=True)[-20:])
    except OSError:
        tail = ""
    return page(
        f"<h1>{APP_NAME} could not start</h1>"
        f"<p>Full log: {html.escape(str(LOG_FILE))}</p>"
        f"<pre>{html.escape(tail) or 'The log is empty.'}</pre>"
    )


def read_settings(path: Path) -> dict[str, str]:
    """KEY=VALUE lines from the settings file (known keys only; quotes stripped)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    settings: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key in SETTING_KEYS or key.startswith(SETTING_PREFIX):
            settings[key] = value.strip("'\"")
    return settings


def ensure_settings_file(path: Path) -> None:
    """Create the private settings file with commented examples (never overwrites)."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(SETTINGS_TEMPLATE)


def server_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment of the Streamlit server: settings file < process environment < app rules."""
    base = dict(os.environ if base is None else base)
    env = {**read_settings(SETTINGS_FILE), **base}
    # build_app.sh records where node is: apps opened from Finder have a minimal PATH.
    if base.get("SPEC_TO_TEST_NODE") and not env.get("AUTOMATION_NODE"):
        env["AUTOMATION_NODE"] = base["SPEC_TO_TEST_NODE"]
    # Single-user desktop: keep work between launches.
    env["SPEC_TO_TEST_STORAGE"] = "local"
    env["SPEC_TO_TEST_DATA_DIR"] = str(SUPPORT_DIR / "data")
    return env


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def pick_port() -> int:
    """Prefer 8501 (stable origin keeps theme/zoom settings); skip busy ports."""
    for port in range(PREFERRED_PORT, PREFERRED_PORT + 50):
        if port_is_free(port):
            return port
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(port: str) -> None:
    """Child process: run Streamlit, and exit as soon as the window process is gone."""
    parent = os.getppid()

    def watch_parent() -> None:
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)

    threading.Thread(target=watch_parent, daemon=True).start()

    from streamlit.web import cli

    sys.argv = [
        "streamlit",
        "run",
        str(ROOT / "app.py"),
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--browser.gatherUsageStats=false",
        "--client.toolbarMode=minimal",
    ]
    cli.main(prog_name="streamlit")


class Server:
    def __init__(self) -> None:
        self.port = pick_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        (SUPPORT_DIR / "data").mkdir(parents=True, exist_ok=True)
        try:
            ensure_settings_file(SETTINGS_FILE)
        except OSError:
            pass  # the app works without it
        env = server_env()
        with open(LOG_FILE, "ab") as log:
            # Run from the repo root so .streamlit/config.toml and .env are picked up.
            self.proc = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--serve", str(self.port)],
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

    def wait_ready(self) -> bool:
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self.proc is None or self.proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(f"{self.url}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        return True
            except OSError:
                pass
            time.sleep(0.3)
        return False

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def name_process() -> None:
    """Show "Spec-to-Test" in the menu bar even when run by a plain python."""
    try:
        from Foundation import NSBundle

        NSBundle.mainBundle().infoDictionary()["CFBundleName"] = APP_NAME
    except Exception:
        pass


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--serve":
        serve(sys.argv[2])
        return

    name_process()
    import webview

    # Exports use download links; show a Save dialog for them.
    webview.settings["ALLOW_DOWNLOADS"] = True

    server = Server()
    atexit.register(server.stop)
    window = webview.create_window(
        APP_NAME,
        html=LOADING_PAGE,
        width=1280,
        height=860,
        min_size=(900, 600),
        background_color="#F7F8FC",
        text_select=True,
        zoomable=True,
    )
    assert window is not None
    window.events.closed += server.stop

    def boot() -> None:
        server.start()
        if server.wait_ready():
            window.load_url(server.url)
        else:
            server.stop()
            window.load_html(error_page())

    webview.start(
        boot,
        private_mode=False,
        storage_path=str(SUPPORT_DIR / "webview"),
        icon=os.environ.get("SPEC_TO_TEST_ICON"),
    )
    server.stop()


if __name__ == "__main__":
    main()
