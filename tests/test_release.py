"""Release consistency: versions, dependencies, and repository files."""

import re
import tomllib

from conftest import PROJECT_ROOT
from spec_to_test import __version__


def read(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def test_version_is_consistent():
    pyproject = tomllib.loads(read("pyproject.toml"))
    assert pyproject["project"]["version"] == __version__
    assert f"## [{__version__}]" in read("CHANGELOG.md")


def test_required_repository_files_exist():
    for name in [
        "README.md", "LICENSE", "CHANGELOG.md", "SECURITY.md", ".gitignore", ".env.example",
        ".streamlit/config.toml", ".streamlit/secrets.toml.example", ".github/workflows/ci.yml",
        "docs/EXPORTS.md", "docs/DEPLOYMENT.md", "docs/RELEASE_CHECKLIST.md",
        "docs/qa/TEST_PLAN.md", "docs/qa/TEST_CASES.md", "docs/qa/BUG_REPORTS.md",
        "docs/qa/RTM.md", "docs/qa/TEST_SUMMARY_REPORT.md",
    ]:
        assert (PROJECT_ROOT / name).is_file(), name
    assert "MIT License" in read("LICENSE")


def test_runtime_dependencies_exclude_vulnerable_versions():
    requirements = read("requirements.txt")
    assert re.search(r"^pypdf>=6\.(19|[2-9]\d)", requirements, re.M)
    assert re.search(r"^streamlit>=1\.(6[5-9]|[7-9]\d)", requirements, re.M)
    assert re.search(r"^pandas>=", requirements, re.M)  # imported directly by app.py
    assert "anthropic" not in requirements  # AI stays optional


def test_local_data_and_tooling_are_ignored():
    ignored = read(".gitignore").splitlines()
    for entry in [".spec_to_test_data/", ".venv/", ".env", ".streamlit/secrets.toml", ".mypy_cache/"]:
        assert entry in ignored


def test_secrets_template_has_no_values():
    for line in read(".streamlit/secrets.toml.example").splitlines():
        if "KEY" in line and not line.lstrip().startswith("#"):
            assert line.split("=", 1)[1].strip() in ('""', "")


def test_ci_runs_lint_tests_and_audit():
    ci = read(".github/workflows/ci.yml")
    for command in ("ruff check .", "mypy", "pytest", "pip-audit"):
        assert command in ci
    assert "pull_request" in ci and "push" in ci


def test_qa_documents_reference_existing_tests():
    """Every `test_file.py::test_name` mentioned in docs/qa must exist."""
    references = set()
    for doc in (PROJECT_ROOT / "docs" / "qa").glob("*.md"):
        text = doc.read_text(encoding="utf-8")
        for file_name, rest in re.findall(r"(test_\w+\.py)((?:,?\s*::test_\w+|::test_\w+)*)", text):
            assert (PROJECT_ROOT / "tests" / file_name).is_file(), f"{doc.name}: {file_name}"
            references |= {(file_name, name) for name in re.findall(r"::(test_\w+)", rest)}
    assert references
    for file_name, name in references:
        source = (PROJECT_ROOT / "tests" / file_name).read_text(encoding="utf-8")
        assert f"def {name}(" in source, f"{file_name}::{name}"
