"""macOS desktop launcher (macos/desktop.py): port choice and the error page."""

import importlib.util
import socket

import pytest

from conftest import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("desktop", PROJECT_ROOT / "macos" / "desktop.py")
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def test_pick_port_skips_a_busy_port(monkeypatch):
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        monkeypatch.setattr(desktop, "PREFERRED_PORT", port)
        assert not desktop.port_is_free(port)
        assert desktop.pick_port() != port


def test_error_page_escapes_the_log(tmp_path, monkeypatch):
    log = tmp_path / "server.log"
    log.write_text("ok\n<script>alert(1)</script>\n")
    monkeypatch.setattr(desktop, "LOG_FILE", log)
    page = desktop.error_page()
    assert "<script>alert" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_error_page_without_a_log(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "LOG_FILE", tmp_path / "missing.log")
    assert "The log is empty." in desktop.error_page()


@pytest.mark.parametrize("option", ["--server.address=127.0.0.1", "--server.headless=true"])
def test_server_is_local_and_headless(option):
    source = (PROJECT_ROOT / "macos" / "desktop.py").read_text()
    assert f'"{option}"' in source


def test_settings_file_is_private_and_never_overwritten(tmp_path):
    path = tmp_path / "support" / "settings.env"
    desktop.ensure_settings_file(path)
    assert oct(path.stat().st_mode)[-3:] == "600"
    assert "AUTOMATION_ALLOWED_HOSTS" in path.read_text()
    assert desktop.read_settings(path) == {}  # the template is all comments
    path.write_text("AI_PROVIDER=anthropic\n")
    desktop.ensure_settings_file(path)
    assert path.read_text() == "AI_PROVIDER=anthropic\n"


def test_settings_keep_known_keys_and_environment_wins(tmp_path, monkeypatch):
    path = tmp_path / "settings.env"
    path.write_text(
        "# comment\nAI_PROVIDER = anthropic\nANTHROPIC_API_KEY='abc'\nAUTOMATION_ALLOWED_HOSTS=localhost:3000\n"
        "QA_MAX_CASES=5\nPATH=/evil\nSPEC_TO_TEST_STORAGE=session\nnot a setting\n"
    )
    monkeypatch.setattr(desktop, "SETTINGS_FILE", path)
    assert desktop.read_settings(path) == {
        "AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "abc", "AUTOMATION_ALLOWED_HOSTS": "localhost:3000",
        "QA_MAX_CASES": "5",
    }
    env = desktop.server_env({"PATH": "/usr/bin", "AI_PROVIDER": "none", "SPEC_TO_TEST_NODE": "/opt/node/bin/node"})
    assert env["PATH"] == "/usr/bin" and env["AI_PROVIDER"] == "none"  # the real environment wins
    assert env["ANTHROPIC_API_KEY"] == "abc" and env["AUTOMATION_NODE"] == "/opt/node/bin/node"
    assert env["SPEC_TO_TEST_STORAGE"] == "local"  # the app's own rules win over everything


def test_settings_template_and_start_script_cover_the_qa_agent():
    assert "AUTOMATION_SECRET_DEMO_PASSWORD" in desktop.SETTINGS_TEMPLATE
    assert "QA_MAX_CASES" in desktop.SETTINGS_TEMPLATE
    start = (PROJECT_ROOT / "macos" / "start.sh").read_text(encoding="utf-8")
    assert "requirements-qa.txt" in start and "playwright install chromium" in start
