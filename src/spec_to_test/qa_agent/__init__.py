"""QA Agent: plan, run and report browser tests against an authorized web app.

models    plans, runs, results and bug reports
steps     the declarative step language and the converter for written test steps
planner   plans from the document's test cases; editing and approval
safety    limits and the checks made before a case runs
executor  the Playwright interpreter (Python, Chromium, headless)
service   starting a run: authorization, SSRF checks, one run at a time
bugs      bug reports for failed cases
report    coverage by requirement and exports
store     where plans and runs are kept
ai        optional: LLM-proposed steps (data, reviewed before use)
"""
