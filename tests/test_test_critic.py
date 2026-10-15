from spec_to_test.i18n import t
from spec_to_test.models import Finding, FindingType, Requirement, Severity, TestCase, TestType, Workspace
from spec_to_test.test_critic import critique
from spec_to_test.test_generator import generate_test_cases

REQ = Requirement(id="REQ-1", text="The password must be at least 8 characters long.")
GOOD_STEPS = ["Open the registration form.", "Enter a password of 8 characters and submit."]


def tc(n: int = 1, steps=None, expected="The account is created.", test_type=TestType.POSITIVE,
       requirement_id="REQ-1") -> TestCase:
    return TestCase(id=f"TC-{n}", requirement_id=requirement_id, title="Valid password", test_type=test_type,
                    steps=steps or GOOD_STEPS, expected_result=expected)


def codes(case: TestCase, *others: TestCase, findings=()) -> dict[str, bool]:
    ws = Workspace(requirements=[REQ], test_cases=[case, *others], findings=list(findings))
    return {i.code: i.unknown for i in critique(case, ws)}


def test_concrete_test_case_has_no_issues():
    assert codes(tc()) == {}


def test_steps_must_be_concrete():
    assert "step_placeholder" in codes(tc(steps=[t("tests.new_step", "ru"), *GOOD_STEPS]))
    assert "step_vague" in codes(tc(steps=["Enter an appropriate password.", *GOOD_STEPS]))
    assert "step_too_short" in codes(tc(steps=["Submit", *GOOD_STEPS]))
    generic = [t("tc.step_prepare", req="REQ-1"), t("tc.step_perform"), t("tc.step_observe")]
    ws = Workspace(requirements=[REQ], test_cases=[tc(steps=generic)])
    [issue] = [i for i in critique(ws.test_cases[0], ws) if i.criterion == "steps"]
    assert issue.code == "step_generic" and issue.params == {"steps": "1, 2, 3"}


def test_expected_result_must_be_checkable():
    assert "expected_placeholder" in codes(tc(expected=t("tests.new_expected")))
    assert "expected_vague" in codes(tc(expected="The form works properly."))
    assert "expected_not_observable" in codes(tc(expected="Everything is fine."))


def test_open_outcomes_and_missing_data_are_unknown():
    assert codes(tc(expected=f"7 characters → {t('design.unspecified')}", test_type=TestType.BOUNDARY)) == {
        "expected_unspecified": True
    }
    assert codes(tc(requirement_id="REQ-9"))["requirement_missing"] is True
    finding = Finding(requirement_id="REQ-1", type=FindingType.MISSING_EXPECTED_RESULT, severity=Severity.HIGH)
    assert codes(tc(), findings=[finding])["requirement_no_expected"] is True


def test_test_case_about_something_else_is_flagged():
    other = TestCase(id="TC-1", requirement_id="REQ-1", title="Export report", test_type=TestType.POSITIVE,
                     steps=["Open the reports page.", "Click Export."], expected_result="A PDF file is downloaded.")
    assert "requirement_mismatch" in codes(other)


def test_duplicates_are_reported_with_ids():
    ws = Workspace(requirements=[REQ], test_cases=[tc(1), tc(2), tc(3, expected="The account is not created.")])
    [issue] = critique(ws.test_cases[0], ws)
    assert issue.code == "duplicate" and issue.params == {"ids": "TC-2"}


def test_invented_values_and_messages_are_flagged():
    result = codes(tc(expected="The account is created within 5 seconds and “Welcome!” is shown."))
    assert set(result) == {"invented_value", "invented_text"}
    # Probe values of a boundary test are derived by the test design, not invented.
    assert codes(tc(expected="7 characters → rejected", test_type=TestType.BOUNDARY)) == {}


def test_generated_cases_only_get_honest_findings():
    ws = Workspace(requirements=[REQ])
    ws.test_cases = generate_test_cases(ws)
    for case in ws.test_cases:
        found = {i.code for i in critique(case, ws)}
        assert found <= {"step_generic", "expected_unspecified"}, (case.id, found)


def test_probe_values_differing_by_sign_or_comparator_are_not_duplicates():
    def case(n: int, step: str) -> TestCase:
        return TestCase(id=f"TC-{n}", requirement_id="REQ-1", title="Temperature", test_type=TestType.BOUNDARY,
                        steps=[step], expected_result="The value is rejected.")

    for a, b in [("Set the temperature to -6 degrees.", "Set the temperature to 6 degrees."),
                 ("Enter a temperature > 5 degrees.", "Enter a temperature < 5 degrees.")]:
        assert "duplicate" not in codes(case(1, a), case(2, b))
    assert "duplicate" in codes(case(1, "Set the temperature to −6 degrees."), case(2, "Set the temperature to -6 degrees."))


def test_generated_cases_quoting_the_requirement_match_it():
    for text in ("The upload size must not exceed 10 MB.", "The order total must be at most 1,000 USD."):
        ws = Workspace(requirements=[Requirement(id="REQ-1", text=text)])
        ws.test_cases = generate_test_cases(ws)
        for case in ws.test_cases:
            assert "requirement_mismatch" not in {i.code for i in critique(case, ws)}, (text, case.title)


def test_hidden_is_an_observable_expected_result():
    for text in ("If the user is an administrator, the system must show the Delete button, "
                 "otherwise the button must be hidden.",
                 "Если пользователь администратор, система должна показать кнопку удаления, "
                 "иначе кнопка должна быть скрыта.",
                 "Якщо користувач адміністратор, система повинна показати кнопку видалення, "
                 "інакше кнопка має бути прихована."):
        ws = Workspace(requirements=[Requirement(id="REQ-1", text=text)])
        ws.test_cases = generate_test_cases(ws)
        assert [c.test_type for c in ws.test_cases] == [TestType.DECISION_TABLE] * 2
        for case in ws.test_cases:
            assert "expected_not_observable" not in {i.code for i in critique(case, ws)}, case.expected_result
    assert "expected_not_observable" in codes(tc(expected="Everything is fine."))
