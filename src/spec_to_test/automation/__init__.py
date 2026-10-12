"""Automation: turn an Approved test case into a validated Playwright test.

Claude explores the staging UI through the Playwright MCP server, submits a
structured test script, and Spec-to-Test renders it to TypeScript, runs it in
a sandboxed Chromium and reports the result. Nothing here imports Streamlit;
the page lives in automation_ui.py. Optional: needs AI, an allowlist and the
Node toolchain in automation/runner (see README).
"""
