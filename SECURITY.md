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
- Storage defaults to `session` in every environment: documents, edits and
  Grill results live only in the visitor's Streamlit session, and nothing is
  read from or written to disk. Disk storage exists only when
  `SPEC_TO_TEST_STORAGE=local` is set explicitly (exact value, case and
  surrounding spaces ignored; any other value means `session`) in the process
  environment or Streamlit secrets. A `.env` file cannot change it. In `local`
  mode edits go to `.spec_to_test_data/` (git-ignored) and are shared by
  everyone who uses that server, so use it only on a single-user machine.
  The old detection of Streamlit Cloud by the `/mount/src` path was removed.
- Automation (optional): runs only with AI configured, a host allowlist
  (`AUTOMATION_ALLOWED_HOSTS`) and a per-run consent. Target hosts must resolve
  to public addresses (private ones only with
  `AUTOMATION_ALLOW_PRIVATE_NETWORK=true`; link-local/metadata never). The
  browser can reach only the vetted host:port pairs (pinned DNS, everything
  else sent to a non-existent proxy), cannot run arbitrary JavaScript or touch
  files, and refuses destructive actions unless the user allows them.
  Credentials are configured as `AUTOMATION_SECRET_<NAME>`, referenced by name
  and masked in every stored or displayed output, including traces. Browser
  and test processes run with a minimal environment (no API key), resource
  limits and timeouts; in Docker the container is the sandbox (non-root, no
  capabilities, read-only root file system).
- Dependencies are checked with `pip-audit` and `npm audit` in CI.
