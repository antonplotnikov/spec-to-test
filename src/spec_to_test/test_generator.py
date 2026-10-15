"""Generate draft test cases from requirements (rule-based, offline).

Generated cases are drafts: they start in "Draft" status and must be reviewed.
Expected results quote the requirement instead of inventing behavior. When the
requirement leaves something open, the case gets a clarification question
rather than a guessed answer.
"""

import re

from spec_to_test.i18n import clarification_question, t, unit_for
from spec_to_test.models import (
    Finding,
    Requirement,
    ReviewStatus,
    Source,
    TestCase,
    TestType,
    Workspace,
)
from spec_to_test.test_design import TestDesign, design_tests, format_value

TITLE_TEXT_CHARS = 70


def _short(text: str, limit: int = TITLE_TEXT_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def next_test_case_id(existing: list[TestCase]) -> str:
    numbers = [int(m.group(1)) for tc in existing if (m := re.fullmatch(r"TC-(\d+)", tc.id))]
    return f"TC-{max(numbers, default=0) + 1:03d}"


def _value_line(value: str, unit: str, expectation: str, lang: str) -> str:
    return t(
        "tc.value_expectation",
        lang,
        value=value,
        unit=unit_for(unit, value, lang),
        expectation=t(f"design.{expectation}", lang),
    )


def _cases_for(
    req: Requirement, findings: list[Finding], design: TestDesign, lang: str
) -> list[dict]:
    """Return test case fields (without IDs) for one requirement."""
    questions = [clarification_question(f, lang) for f in findings]
    assumptions = [t("tc.assumption_open_findings", lang)] if findings else []
    reference = t("tc.pre_reference", lang, req=req.id)
    cases: list[dict] = []

    table = design.decision_table
    if table is None:
        cases.append(
            {
                "title": t("tc.title_positive", lang, req=req.id, text=_short(req.text)),
                "test_type": TestType.POSITIVE,
                "preconditions": [reference],
                "steps": [
                    t("tc.step_prepare", lang, req=req.id),
                    t("tc.step_perform", lang),
                    t("tc.step_observe", lang),
                ],
                "expected_result": t("tc.expected_quote", lang, text=req.text),
                "assumptions": assumptions,
                "clarification_questions": questions,
            }
        )
    else:
        unspecified = [rule for rule in table.rules if rule.outcome is None]
        table_questions = list(questions)
        if unspecified:
            table_questions.append(t("tc.question_unspecified_rules", lang, count=len(unspecified)))
        for index, rule in enumerate(table.rules, start=1):
            if rule.outcome is None:
                continue
            conditions = [
                t("tc.step_condition", lang, condition=cond, value=t(f"design.{str(value).lower()}", lang))
                for cond, value in zip(table.conditions, rule.values, strict=True)
            ]
            cases.append(
                {
                    "title": t("tc.title_decision", lang, req=req.id, rule=index),
                    "test_type": TestType.DECISION_TABLE,
                    "preconditions": [reference],
                    "steps": [*conditions, t("tc.step_perform", lang), t("tc.step_observe", lang)],
                    "expected_result": rule.outcome,
                    "assumptions": assumptions,
                    "clarification_questions": table_questions,
                }
            )

    for analysis in design.boundaries:
        unit = analysis.constraint.unit
        has_unspecified = any(v.expectation == "unspecified" for v in analysis.values)
        cases.append(
            {
                "title": t("tc.title_boundary", lang, req=req.id, phrase=analysis.constraint.phrase),
                "test_type": TestType.BOUNDARY,
                "preconditions": [reference],
                "steps": [
                    t("tc.step_try_value", lang, value=(value := format_value(v.value)),
                      unit=unit_for(unit, value, lang))
                    for v in analysis.values
                ],
                "expected_result": "\n".join(
                    _value_line(format_value(v.value), unit, v.expectation, lang) for v in analysis.values
                ),
                "assumptions": assumptions,
                "clarification_questions": questions
                + ([t("tc.question_exact_value", lang, phrase=analysis.constraint.phrase)] if has_unspecified else []),
            }
        )

    for classes in design.partitions:
        unit = classes.constraint.unit
        has_unspecified = any(p.expectation == "unspecified" for p in classes.partitions)
        cases.append(
            {
                "title": t("tc.title_equivalence", lang, req=req.id, phrase=classes.constraint.phrase),
                "test_type": TestType.EQUIVALENCE,
                "preconditions": [reference],
                "steps": [
                    t(
                        "tc.step_partition",
                        lang,
                        interval=p.interval,
                        value=format_value(p.representative),
                        unit=unit_for(unit, format_value(p.representative), lang),
                    )
                    for p in classes.partitions
                ],
                "expected_result": "\n".join(
                    _value_line(format_value(p.representative), unit, p.expectation, lang)
                    for p in classes.partitions
                ),
                "assumptions": assumptions,
                "clarification_questions": questions
                + ([t("tc.question_exact_value", lang, phrase=classes.constraint.phrase)] if has_unspecified else []),
            }
        )
    return cases


def generate_test_cases(workspace: Workspace, lang: str = "en") -> list[TestCase]:
    """Generate draft test cases for every requirement in the workspace."""
    generated: list[TestCase] = []
    for req in workspace.requirements:
        findings = workspace.open_findings_for(req.id)
        for fields in _cases_for(req, findings, design_tests(req), lang):
            generated.append(
                TestCase(
                    id=next_test_case_id(workspace.test_cases + generated),
                    requirement_id=req.id,
                    source=Source.RULE,
                    review_status=ReviewStatus.DRAFT,
                    **fields,
                )
            )
    return generated
