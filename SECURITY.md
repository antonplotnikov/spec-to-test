# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 1.1.x | ✅ |
| 1.0.x | ✅ (security fixes only) |
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
- Grill Mode: the session lives only in the user's Streamlit session (never
  shared between visitors, never written to disk). Answers and fields are
  limited to 100,000 characters. AI requests need a fresh consent each time
  and send only the current draft, its linked requirement, and the questions
  already asked; AI output is validated and never treated as confirmed.
- Locally, edits are saved in `.spec_to_test_data/` (git-ignored). On
  Streamlit Community Cloud nothing is written to disk by default.
- Dependencies are checked with `pip-audit` in CI.
