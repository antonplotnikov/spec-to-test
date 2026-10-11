# Release checklist — v1.1.0

Tick each item before publishing. Items marked ✅ were verified while
preparing the release (2026-10-11); the rest need the maintainer.
The v1.0.0 items about repository setup are already done (repository public,
CI configured).

## Code and tests
- [x] ✅ `pytest` passes locally (Python 3.11): 1211 passed, also in a clean
      venv with and without the `anthropic` SDK — see docs/qa/TEST_SUMMARY_REPORT.md
- [x] ✅ `ruff check .` passes
- [x] ✅ `mypy` passes (28 source files)
- [x] ✅ `pip-audit` on `requirements-ai.txt` and `requirements-dev.txt`: no known vulnerabilities
- [x] ✅ App starts headless without AI configuration (`/_stcore/health` → ok)
- [x] ✅ CI is green on GitHub (Python 3.11 and 3.12) for commit a962e6e
- [x] ✅ Version is 1.1.0 in `pyproject.toml`, `src/spec_to_test/__init__.py`, and `CHANGELOG.md`

## Documentation
- [x] ✅ README: Grill Mode usage, AI privacy, limitations, project status
- [x] ✅ CHANGELOG 1.1.0, SECURITY.md, docs/EXPORTS.md, docs/DEPLOYMENT.md
- [x] ✅ docs/qa: test plan, test cases (TC-023 … TC-030), RTM (PR-18 … PR-21), BUG-008, summary report
- [ ] Screenshot of Grill Mode in `docs/screenshots/` (optional)

## Manual checks (see docs/qa/TEST_CASES.md)
- [ ] Execute TC-023 … TC-030 (Grill Mode) in a browser and record results
- [ ] Download a Grill result as Markdown in a browser and open the file
- [ ] (If AI is enabled) one real Grill AI request with a test key; confirm consent text and labels
- [ ] Import a Grill-added test case and bug report into Jira / TestRail (docs/EXPORTS.md)

## Publish (only after approval)
- [ ] Push `feature/grill-mode`, wait for CI, merge PR #1 into `main`
- [ ] Tag `v1.1.0` and create the GitHub release (notes: docs/release-notes-v1.1.0.md)
- [ ] Deploy on Streamlit Community Cloud (docs/DEPLOYMENT.md) and run the post-deployment checks
