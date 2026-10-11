# Release checklist — v1.0.0

Tick each item before publishing. Items marked ✅ were verified while
preparing the release (2026-10-11); the rest need the maintainer.

## Code and tests
- [x] ✅ `pytest` passes locally (Python 3.11) — see docs/qa/TEST_SUMMARY_REPORT.md
- [x] ✅ `ruff check .` passes
- [x] ✅ `mypy` passes
- [x] ✅ `pip-audit -r requirements-ai.txt` reports no known vulnerabilities
- [ ] CI is green on GitHub (Python 3.11 and 3.12) after the first push
- [x] ✅ Version is 1.0.0 in `pyproject.toml`, `src/spec_to_test/__init__.py`, and `CHANGELOG.md`

## Repository content
- [x] ✅ README, LICENSE (MIT), CHANGELOG, SECURITY.md, `.env.example`, `.gitignore`
- [ ] Copyright holder in `LICENSE` is correct
- [x] `antonplotnikov` replaced in README.md, CHANGELOG.md, docs/DEPLOYMENT.md
- [ ] Screenshots added to `docs/screenshots/` and placeholders replaced in README
- [ ] `git status` before the first commit shows **no** `.env`, `.venv/`,
      `.spec_to_test_data/`, `.streamlit/secrets.toml`, or cache folders
- [ ] No real customer documents in `examples/` or `tests/fixtures/`

## Manual checks (see docs/qa/TEST_CASES.md)
- [ ] Execute the manual test cases marked "Not executed" and record results
- [ ] Check the app in Chrome, Firefox, and Safari (only a Chromium-based preview was used so far)
- [ ] Import `jira_test_cases.csv` into a Jira test project and `testrail_test_cases.csv`
      into a TestRail test project; confirm field mapping (docs/EXPORTS.md)
- [ ] (If AI is enabled) one real AI run with a test key; confirm consent text and results

## Publish (only after approval)
- [ ] Push to GitHub, wait for CI
- [ ] Tag `v1.0.0` and create the GitHub release (notes: docs/release-notes-v1.0.0.md)
- [ ] Deploy on Streamlit Community Cloud (docs/DEPLOYMENT.md)
- [ ] Run the post-deployment checks in docs/DEPLOYMENT.md
- [ ] Add the live demo URL to the README and repository description
