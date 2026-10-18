"""Bug Report Generator: a product bug described in free text becomes a structured report.

- models:      the report (WWW + QA fields) and its Missing Information checks;
- extract:     the rule-based generator (local, no AI): only text found in the
               description is used, anything else stays empty ("Needs clarification");
- markdown:    the Markdown export;
- store:       saved reports of a project (session or local disk, like projects).
"""
