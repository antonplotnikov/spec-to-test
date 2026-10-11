"""Security checks: no secrets in the repo, no network use, safe defaults."""

import re
import socket

import pytest

from conftest import PROJECT_ROOT
from spec_to_test.input_parser import extract_requirements
from spec_to_test.rule_engine import analyze_requirements

SOURCE_FILES = [
    p
    for p in PROJECT_ROOT.rglob("*")
    if p.is_file()
    and not {".venv", "__pycache__", ".pytest_cache", ".git"} & set(p.parts)
    and p.suffix in {".py", ".toml", ".yml", ".yaml", ".md", ".txt", ".example", ""}
]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),  # OpenAI / Anthropic style keys
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),  # GitHub token
    re.compile(r"(?i)(api_key|secret|token)\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}"),
]


@pytest.fixture
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


def test_no_secrets_committed():
    assert SOURCE_FILES
    for path in SOURCE_FILES:
        content = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(content), f"possible secret in {path.name}"


def test_env_example_has_no_real_values():
    for line in (PROJECT_ROOT / ".env.example").read_text().splitlines():
        if "KEY" in line and "=" in line and not line.lstrip().startswith("#"):
            assert line.split("=", 1)[1].strip() == ""


def test_secret_files_are_git_ignored():
    ignored = (PROJECT_ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in ignored
    assert ".streamlit/secrets.toml" in ignored


def test_analysis_makes_no_network_calls(no_network, example_text):
    result = analyze_requirements(extract_requirements(example_text))
    assert result.requirements


def test_app_makes_no_network_calls(no_network, example_text):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30)
    at.run()
    at.text_area[0].input(example_text).run()
    at.button[0].click().run()
    assert not at.exception


def test_usage_stats_are_disabled():
    config = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text()
    assert "gatherUsageStats = false" in config


def test_upload_limit_matches_parser_limit():
    from spec_to_test.input_parser import MAX_FILE_SIZE_BYTES

    config = (PROJECT_ROOT / ".streamlit" / "config.toml").read_text()
    assert f"maxUploadSize = {MAX_FILE_SIZE_BYTES // (1024 * 1024)}" in config


def test_hostile_text_is_kept_as_plain_data():
    payload = "REQ-1: <script>alert(1)</script> {{7*7}} ${env:HOME} ' OR 1=1 -- must be shown."
    req = extract_requirements(payload)[0]
    assert req.text == payload.removeprefix("REQ-1: ")


def test_pathological_input_does_not_hang():
    import time

    start = time.perf_counter()
    for text in ["REQ-" + "1." * 20000 + "x", "A-" * 40000 + "x", "[" * 50000, "-" * 90000 + " x", "1." * 45000]:
        try:
            extract_requirements(text)
        except Exception as exc:  # only InputError is acceptable
            assert type(exc).__name__ == "InputError"
    assert time.perf_counter() - start < 5
