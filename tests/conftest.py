"""Shared test helpers."""

import socket
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_pdf(lines: list[str]) -> bytes:
    """Build a tiny one-page PDF with ASCII text, without extra libraries."""
    commands = " ".join(f"({line}) Tj 0 -16 Td" for line in lines)
    content = f"BT /F1 12 Tf 72 720 Td {commands} ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref_start = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode()
    pdf += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    ).encode()
    return pdf


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Keep saved workspaces in a temp folder and AI switched off by default.

    Storage is "local" here so the persistence tests keep working; the product
    default is "session" and is covered by tests that delete this variable.
    """
    monkeypatch.setenv("SPEC_TO_TEST_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "local")
    monkeypatch.setenv("AI_PROVIDER", "none")
    # No provider settings from the developer's shell leak into a test.
    for name in (
        "AI_MODEL", "AI_LOCK_SETTINGS", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
        "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "OLLAMA_HOST", "OLLAMA_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def example_text() -> str:
    return (PROJECT_ROOT / "examples" / "password_reset.md").read_text(encoding="utf-8")


@pytest.fixture
def no_network(monkeypatch):
    """Fail the test on any attempt to open a network connection."""
    def blocked(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


# --- Navigating the app in AppTest ---------------------------------------------

def goto(at, page: str):
    """Open a page from the sidebar navigation ("home", "analysis", "grill", "tests",
    "qa_agent", "rtm", "dashboard", "export" or "settings")."""
    at.sidebar.radio(key="app_mode").set_value(page).run()
    return at


def home(at):
    """Home holds the requirements input and the Analyze button."""
    if not any(area.key == "requirements_text" for area in at.text_area):
        goto(at, "home")
    return at
