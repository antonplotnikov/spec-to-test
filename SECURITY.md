# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | ✅ |
| < 1.0 | ❌ |

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
private vulnerability reporting (repository → Security → Report a
vulnerability) or contact the maintainer through the email on their GitHub
profile. You should receive a reply within 7 days.

## How the app handles data

- Uploaded files are treated as untrusted and validated (type, size, encoding,
  PDF page count, encryption, binary content).
- User text is escaped before it is displayed, and CSV exports neutralise
  spreadsheet formulas.
- Documents are sent to an AI provider only when AI is configured **and** the
  user consents for that specific run. API keys are never displayed or logged.
- Locally, edits are saved in `.spec_to_test_data/` (git-ignored). On
  Streamlit Community Cloud nothing is written to disk by default.
- Dependencies are checked with `pip-audit` in CI.
