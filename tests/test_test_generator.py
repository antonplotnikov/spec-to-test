import pytest

from spec_to_test.i18n import UNIT_FORMS, t
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import ReviewStatus, Source, TestType, Workspace
from spec_to_test.rule_engine import analyze_requirements
from spec_to_test.test_generator import generate_test_cases, next_test_case_id


def workspace_for(text: str) -> Workspace:
    result = analyze_requirements(extract_requirements(text))
    return Workspace(requirements=result.requirements, findings=result.findings)


def test_every_requirement_gets_draft_test_cases(example_text):
    ws = workspace_for(example_text)
    cases = generate_test_cases(ws)
    assert {tc.requirement_id for tc in cases} == {r.id for r in ws.requirements}
    assert all(tc.review_status == ReviewStatus.DRAFT and tc.source == Source.RULE for tc in cases)
    ids = [tc.id for tc in cases]
    assert len(ids) == len(set(ids))
    assert ids[0] == "TC-001"


def test_positive_case_quotes_requirement():
    ws = workspace_for("REQ-1: The system must send a reset link to the registered email address.")
    [case] = generate_test_cases(ws)
    assert case.test_type == TestType.POSITIVE
    assert "The system must send a reset link to the registered email address." in case.expected_result
    assert case.clarification_questions == []


def test_open_findings_become_questions_and_assumptions():
    ws = workspace_for("REQ-1: The reset page should load fast.")
    [case] = generate_test_cases(ws)
    assert any('"fast"' in q for q in case.clarification_questions)
    assert case.assumptions


def test_boundary_and_equivalence_cases_from_numbers():
    ws = workspace_for("REQ-1: The new password must be at least 8 characters long.")
    types = [tc.test_type for tc in generate_test_cases(ws)]
    assert types == [TestType.POSITIVE, TestType.BOUNDARY, TestType.EQUIVALENCE]
    boundary = generate_test_cases(ws)[1]
    assert "7 characters → rejected (invalid)" in boundary.expected_result


PARTIAL_CHECK = (
    "Partial check: only “at least 8 characters” is varied. REQ-1 also states other conditions that this case "
    "does not check; each test value must meet them, otherwise the expected result does not apply."
)


def test_length_with_another_condition_is_marked_as_a_partial_check():
    ws = workspace_for("REQ-1: The new password must be at least 8 characters long and contain one digit.")
    _, boundary, equivalence = generate_test_cases(ws)
    # Before: "8 characters → accepted (valid)" with no caveat, so "abcdefgh" (no digit) passed as valid.
    assert "8 characters → accepted (valid)" in boundary.expected_result
    assert boundary.assumptions == equivalence.assumptions == [PARTIAL_CHECK]
    assert boundary.clarification_questions == equivalence.clarification_questions == []


@pytest.mark.parametrize("text", [
    "REQ-1: The new password must be at least 8 characters long.",
    "REQ-1: The new password must be at least 8 characters and at most 64 characters.",  # one range
    "REQ-1: The new password must be between 8 and 64 characters.",
])
def test_plain_numeric_requirement_is_not_marked_partial(text):
    ws = workspace_for(text)
    _, boundary, equivalence = generate_test_cases(ws)
    assert "8 characters → accepted (valid)" in boundary.expected_result
    assert boundary.assumptions == equivalence.assumptions == []


def test_or_more_lower_limit_gets_concrete_boundary_outcomes():
    ws = workspace_for("REQ-1: The new password must contain 8 characters or more.")
    _, boundary, equivalence = generate_test_cases(ws)
    # Before: "boundary values for “8 characters”" with 7 and 9 "not specified — needs clarification".
    assert boundary.title == "REQ-1: boundary values for “8 characters or more”"
    assert boundary.expected_result == (
        "7 characters → rejected (invalid)\n8 characters → accepted (valid)\n9 characters → accepted (valid)"
    )
    assert equivalence.expected_result == "4 characters → rejected (invalid)\n16 characters → accepted (valid)"
    assert boundary.clarification_questions == equivalence.clarification_questions == []


def test_or_more_on_the_rejected_side_keeps_its_clarification_question():
    ws = workspace_for("REQ-1: Passwords of 65 or more characters are rejected.")
    _, boundary, _ = generate_test_cases(ws)
    assert "64 characters → not specified — needs clarification" in boundary.expected_result
    assert "65 characters → as stated in the requirement" in boundary.expected_result
    assert boundary.clarification_questions == [
        "What should happen just before and just after “65 or more characters”?"
    ]


def test_decision_table_cases_only_for_specified_outcomes():
    ws = workspace_for("REQ-8: If the email address is not registered, the system shows a generic message.")
    cases = generate_test_cases(ws)
    assert [tc.test_type for tc in cases] == [TestType.DECISION_TABLE]
    assert cases[0].expected_result == "the system shows a generic message"
    assert any("1" in q for q in cases[0].clarification_questions)  # one unspecified combination


def test_generated_text_follows_language():
    ws = workspace_for("REQ-1: The system must save drafts.")
    [case] = generate_test_cases(ws, "uk")
    assert "Система поводиться" in case.expected_result


def test_user_capability_step_quotes_the_action():
    ws = workspace_for(
        "REQ-1: The user can request a password reset from the login page by entering their email address."
    )
    [case] = generate_test_cases(ws)
    # Before: the generic "Perform the action described in the requirement."
    assert t("tc.step_perform") not in case.steps
    assert case.steps == [
        t("tc.step_prepare", req="REQ-1"),
        "Perform the action stated in REQ-1: “request a password reset from the login page by entering their "
        "email address”.",
        t("tc.step_observe"),
    ]
    assert "“The user can request a password reset" in case.expected_result  # expected result is unchanged


@pytest.mark.parametrize(
    ("text", "lang", "action"),
    [
        ("REQ-9: The user is able to set a new password.", "en", "set a new password"),
        ("REQ-1: Registered users can export reports as CSV.", "en", "export reports as CSV"),
        ("REQ-1: Пользователь может удалить черновик.", "ru", "удалить черновик"),
        ("REQ-1: Користувач може змінити email.", "uk", "змінити email"),
    ],
)
def test_user_capability_action_in_each_language(text, lang, action):
    [case] = generate_test_cases(workspace_for(text), lang)
    assert case.steps[1] == t("tc.step_perform_stated", lang, req=text[:5], action=action)


@pytest.mark.parametrize(
    "text",
    [
        "REQ-1: The system can send a reminder email.",  # the actor is not a user
        "REQ-1: The user is not able to delete the account.",  # negated
        "REQ-1: The user may not change the email address.",
        "REQ-1: Пользователь не может удалить чужой комментарий.",
        "REQ-1: The user cannot export reports.",
        "REQ-1: When logged in, the user can export reports.",  # condition before the actor
        "REQ-1: The system must send a reset link to the registered email address.",  # no capability
    ],
)
def test_other_requirements_keep_the_generic_step(text):
    cases = generate_test_cases(workspace_for(text))
    positive = [tc for tc in cases if tc.test_type == TestType.POSITIVE]
    assert all(t("tc.step_perform") in tc.steps for tc in positive)
    assert not any("stated in" in step for tc in cases for step in tc.steps)


def test_next_id_continues_after_existing():
    ws = workspace_for("REQ-1: The system must save drafts.")
    ws.test_cases = generate_test_cases(ws)
    assert next_test_case_id(ws.test_cases) == "TC-002"
    ws.test_cases[0].id = "TC-041"
    assert next_test_case_id(ws.test_cases) == "TC-042"


def test_currency_units_are_translated():
    for text, phrases in [
        ("The price must be at least 0.5 USD.",
         {"en": ["0.5 USD"], "uk": ["0.5 долара США"], "ru": ["0.5 доллара США"]}),
        ("The fee must not exceed 100 UAH.",
         {"en": ["100 UAH"], "uk": ["100 гривень", "101 гривня"], "ru": ["100 гривен", "101 гривна"]}),
    ]:
        for lang, expected in phrases.items():
            cases = generate_test_cases(workspace_for(text), lang)
            written = "\n".join(
                line for c in cases if c.test_type == TestType.BOUNDARY for line in [*c.steps, c.expected_result]
            )
            assert "unit." not in written and all(phrase in written for phrase in expected), (lang, written)


UNIT_REQUIREMENTS = {
    "milliseconds": "The response time must be at most 500 ms.",
    "weeks": "The trial period must be at most 2 weeks.",
    "months": "The subscription must last at most 6 months.",
    "years": "The user must be at least 18 years old.",
    "kilobytes": "The avatar must be at most 512 KB.",
    "gigabytes": "The upload must be at most 200 GB.",  # 2 GB is probed in MB
    "percent": "The discount must be at most 50%.",
    "items": "The cart must contain at most 10 items.",
}


@pytest.mark.parametrize("lang", ["en", "uk", "ru"])
@pytest.mark.parametrize("unit", sorted(UNIT_REQUIREMENTS))
def test_designed_cases_name_the_unit(unit, lang):
    cases = generate_test_cases(workspace_for(UNIT_REQUIREMENTS[unit]), lang)
    designed = [c for c in cases if c.test_type in (TestType.BOUNDARY, TestType.EQUIVALENCE)]
    assert designed
    for case in designed:
        written = "\n".join([*case.steps, case.expected_result])
        forms = {t(f"unit.{unit}", lang), *UNIT_FORMS.get(unit, {}).get(lang, ())}
        assert "unit." not in written and any(form in written for form in forms), written


def test_partition_step_keeps_the_unit_in_the_number_form():
    ws = workspace_for("The trial period must be at most 2 weeks.")
    steps = [s for c in generate_test_cases(ws, "ru") if c.test_type == TestType.EQUIVALENCE for s in c.steps]
    assert steps == ["Класс ≤ 2: используйте значение 1 неделя.", "Класс > 2: используйте значение 4 недели."]
    steps = [s for c in generate_test_cases(ws, "uk") if c.test_type == TestType.EQUIVALENCE for s in c.steps]
    assert steps == ["Клас ≤ 2: використайте значення 1 тиждень.", "Клас > 2: використайте значення 4 тижні."]
