import pytest

from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import (
    ClarificationStatus,
    FindingType,
    Requirement,
    RequirementStatus,
    Source,
)
from spec_to_test.rule_engine import analyze_requirements


def types_for(text: str) -> set[FindingType]:
    result = analyze_requirements([Requirement(id="REQ-1", text=text)])
    return {f.type for f in result.findings}


def findings_of(text: str, kind: FindingType):
    result = analyze_requirements([Requirement(id="REQ-1", text=text)])
    return [f for f in result.findings if f.type == kind]


# --- Ambiguous wording -----------------------------------------------------

@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("The page must load fast.", "fast"),
        ("The form should be user-friendly.", "user-friendly"),
        ("Сторінка повинна завантажуватися швидко.", "швидко"),
        ("Интерфейс должен быть удобным.", "удобным"),
        ("Поддерживаются PDF, DOCX и т.д.", "и т.д."),
    ],
)
def test_ambiguous_terms_are_detected(text, term):
    findings = findings_of(text, FindingType.AMBIGUOUS_WORDING)
    assert findings and term in findings[0].matched_terms


def test_ambiguous_terms_match_whole_words_only():
    # "breakfast" contains "fast" but is not ambiguous wording.
    assert FindingType.AMBIGUOUS_WORDING not in types_for("The system must display the breakfast menu.")


# --- Missing expected result -----------------------------------------------

def test_missing_expected_result_is_detected():
    assert FindingType.MISSING_EXPECTED_RESULT in types_for("The user is able to set a new password.")


@pytest.mark.parametrize(
    "text",
    [
        "The system displays a confirmation message.",
        "Система надсилає лист із посиланням.",
        "Система отправляет письмо со ссылкой.",
        "The password must be hashed.",
    ],
)
def test_requirements_with_outcomes_pass(text):
    assert FindingType.MISSING_EXPECTED_RESULT not in types_for(text)


@pytest.mark.parametrize(
    "text",
    [
        # QA Agent eval, qa_demo REQ-5: "delete" is what the user does, not its result.
        "A signed-in user must be able to delete their account from the account page.",
        "Admins can block other users.",
        "Користувач може видалити обліковий запис.",
        "Пользователь может удалить аккаунт.",
    ],
)
def test_the_action_a_capability_grants_is_not_its_result(text):
    assert FindingType.MISSING_EXPECTED_RESULT in types_for(text)


@pytest.mark.parametrize(
    "text",
    [
        # QA Agent eval, qa_demo REQ-1 / REQ-2: short, but the result is concrete.
        'The home page must show the heading "Demo Shop".',
        'A registered user must be able to sign in with a valid email and password and see "Welcome, Demo User" '
        "on the dashboard.",
        'The user can delete the account; the system then shows the message "Account deleted".',
        "The user can see the order history.",
        "The user can receive notifications.",
        "Пользователь может получить чек на email.",
        "The system deletes inactive accounts after 30 days.",
    ],
)
def test_a_capability_with_an_observable_result_passes(text):
    assert FindingType.MISSING_EXPECTED_RESULT not in types_for(text)


# --- Missing boundary conditions -------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "After too many failed attempts, the account is locked.",
        "Пароль повинен мати достатню довжину.",
        "Количество попыток ограничено.",
    ],
)
def test_missing_boundary_is_detected(text):
    assert FindingType.MISSING_BOUNDARY in types_for(text)


@pytest.mark.parametrize(
    "text",
    [
        "After 5 failed attempts, the account is locked.",
        "After five failed attempts, the account is locked.",
        "Після п'яти спроб акаунт блокується на 15 хвилин.",
    ],
)
def test_boundary_with_numbers_passes(text):
    assert FindingType.MISSING_BOUNDARY not in types_for(text)


# --- Missing error handling ------------------------------------------------

def test_missing_error_handling_is_detected():
    findings = findings_of("The user enters an email address.", FindingType.MISSING_ERROR_HANDLING)
    assert findings
    assert findings[0].matched_terms == ["enters"]


@pytest.mark.parametrize(
    "text",
    [
        "If the email is invalid, an error message is shown.",
        "Якщо пароль невірний, система показує помилку.",
        "Если пароль неверный, система показывает ошибку.",
        "If the email address is not registered, a generic message is shown.",
    ],
)
def test_error_handling_present_passes(text):
    assert FindingType.MISSING_ERROR_HANDLING not in types_for(text)


def test_requirement_without_user_input_needs_no_error_rule():
    assert FindingType.MISSING_ERROR_HANDLING not in types_for("Reports are generated every night.")


# --- Contradictions --------------------------------------------------------

def test_conflicting_numeric_limits_are_contradictions():
    result = analyze_requirements(
        extract_requirements(
            "REQ-1: The password must be at least 8 characters.\n"
            "REQ-2: The password must be at least 10 characters.\n"
            "REQ-3: The reset link expires after 30 minutes."
        )
    )
    contradictions = [f for f in result.findings if f.type == FindingType.CONTRADICTION]
    assert {f.requirement_id for f in contradictions} == {"REQ-1", "REQ-2"}
    first = next(f for f in contradictions if f.requirement_id == "REQ-1")
    assert first.related_requirement_ids == ["REQ-2"]
    assert first.matched_terms == ["at least 8 characters", "at least 10 characters"]


def test_different_topics_with_same_unit_are_not_contradictions():
    result = analyze_requirements(
        extract_requirements(
            "REQ-1: The reset link expires after 30 minutes.\n"
            "REQ-2: Idle sessions are closed after 15 minutes."
        )
    )
    assert not [f for f in result.findings if f.type == FindingType.CONTRADICTION]


def test_min_and_max_limits_are_not_contradictions():
    result = analyze_requirements(
        extract_requirements(
            "REQ-1: The password must be at least 8 characters.\n"
            "REQ-2: The password must be no more than 64 characters."
        )
    )
    assert not [f for f in result.findings if f.type == FindingType.CONTRADICTION]


def test_must_versus_must_not_is_a_contradiction():
    result = analyze_requirements(
        extract_requirements(
            "REQ-1: Guests can download the monthly report.\n"
            "REQ-2: Guests cannot download the monthly report."
        )
    )
    contradictions = [f for f in result.findings if f.type == FindingType.CONTRADICTION]
    assert len(contradictions) == 2


def test_contradiction_in_ukrainian():
    result = analyze_requirements(
        extract_requirements(
            "1. Пароль має містити щонайменше 8 символів.\n"
            "2. Пароль має містити щонайменше 12 символів."
        )
    )
    assert any(f.type == FindingType.CONTRADICTION for f in result.findings)


# --- General rules -----------------------------------------------------------

def test_all_findings_are_rule_based_and_need_clarification(example_text):
    result = analyze_requirements(extract_requirements(example_text))
    assert result.findings
    assert all(f.source == Source.RULE for f in result.findings)
    assert all(f.status == ClarificationStatus.NEEDS_CLARIFICATION for f in result.findings)


def test_example_document_findings(example_text):
    result = analyze_requirements(extract_requirements(example_text))
    by_req = {}
    for f in result.findings:
        by_req.setdefault(f.requirement_id, set()).add(f.type)

    assert FindingType.AMBIGUOUS_WORDING in by_req["REQ-5"]
    assert FindingType.MISSING_BOUNDARY in by_req["REQ-6"]
    assert FindingType.CONTRADICTION in by_req["REQ-4"]
    assert FindingType.CONTRADICTION in by_req["REQ-7"]
    assert FindingType.MISSING_EXPECTED_RESULT in by_req["REQ-9"]
    assert "REQ-3" not in by_req  # "expires after 30 minutes" is clear


def test_original_text_is_not_modified(example_text):
    requirements = extract_requirements(example_text)
    original = [r.text for r in requirements]
    result = analyze_requirements(requirements)
    assert [r.text for r in result.requirements] == original


def test_findings_follow_requirement_order(example_text):
    result = analyze_requirements(extract_requirements(example_text))
    order = [r.id for r in result.requirements]
    positions = [order.index(f.requirement_id) for f in result.findings]
    assert positions == sorted(positions)


def test_clear_requirement_has_clear_status():
    result = analyze_requirements(
        [Requirement(id="REQ-1", text="The reset link expires after 30 minutes.")]
    )
    assert result.findings == []
    assert result.status_of("REQ-1") == RequirementStatus.CLEAR
