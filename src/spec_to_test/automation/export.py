"""Downloads for the Automation tab.

- job_bundle: the evidence of one validation (test, sandbox config, JSON
  report, screenshots, traces, log), already masked.
- approved_bundle: the approved tests plus a minimal Playwright project, ready
  to copy into a test repository. Credentials stay environment variables.
"""

import io
import json
import re
import zipfile

from spec_to_test.automation.models import AutomationJob
from spec_to_test.automation.store import JobStore
from spec_to_test.models import AutomatedTest

EVIDENCE_KINDS = ("spec", "config", "report", "screenshot", "trace", "log")

PROJECT_CONFIG = """import { defineConfig, devices } from '@playwright/test';

// Set BASE_URL to your staging site, for example: BASE_URL=https://staging.example.com npx playwright test
export default defineConfig({
  testDir: './tests',
  retries: process.env.CI ? 1 : 0,
  reporter: [['html', { open: 'never' }], ['json', { outputFile: 'results.json' }]],
  use: {
    baseURL: process.env.BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
"""

README = """# Automated tests from Spec-to-Test

Each test was generated from an Approved test case, run against staging and
approved by a reviewer. Test titles and tags carry the test case and
requirement IDs (e.g. `@TC-001 @REQ-001`) for traceability.

```bash
npm init -y && npm install -D @playwright/test@{playwright_version}
npx playwright install chromium
BASE_URL=https://staging.example.com {env_line}npx playwright test
```

| Test | Test case | Requirement | Validated against | Approved |
|---|---|---|---|---|
{rows}
"""


def job_bundle(store: JobStore, job: AutomationJob) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in job.artifacts:
            if artifact.kind not in EVIDENCE_KINDS:
                continue
            path = store.artifact_path(job, artifact.path)
            if path is not None:
                archive.write(path, artifact.path)
        summary = job.model_dump(
            mode="json", include={"id", "test_case_id", "requirement_id", "target_url", "model", "status",
                                  "created_at", "finished_at", "reason", "assertion_checks", "runs", "repair_attempted"}
        )
        archive.writestr("job.json", json.dumps(summary, indent=1, ensure_ascii=False))
    return buffer.getvalue()


def _secret_names(code: str) -> list[str]:
    return sorted(set(re.findall(r'secret\("([A-Z][A-Z0-9_]*)"\)', code)))


def approved_bundle(tests: list[AutomatedTest], playwright_version: str = "1.63.0") -> bytes:
    buffer = io.BytesIO()
    names = sorted({name for test in tests for name in _secret_names(test.code)})
    rows = "\n".join(
        f"| tests/{t.file_name} | {t.test_case_id} | {t.requirement_id} | {t.target_url} | {t.approved_at} |"
        for t in tests
    )
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for test in tests:
            archive.writestr(f"tests/{test.file_name}", test.code)
        archive.writestr("playwright.config.ts", PROJECT_CONFIG)
        archive.writestr(
            "README.md",
            README.format(
                playwright_version=playwright_version,
                env_line="".join(f"{name}=... " for name in names),
                rows=rows or "| — | — | — | — | — |",
            ),
        )
    return buffer.getvalue()
