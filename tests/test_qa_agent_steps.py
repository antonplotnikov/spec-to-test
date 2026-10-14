"""QA Agent step language and the converter for written test steps."""

import pytest

from spec_to_test.qa_agent.models import PlanStep, StepAction
from spec_to_test.qa_agent.steps import (
    EMPTY,
    Locator,
    StepError,
    assertions_from_expected,
    format_steps,
    parse_line,
    parse_locator,
    parse_steps,
    step_from_sentence,
    steps_from_test_case,
)

PLAN_TEXT = """# sign in
goto /login
fill label=Email | demo@example.com
fill label=Password | {{secret:DEMO_PASSWORD}}
click role=button[name=Sign in]
press Enter
expect_text Welcome, Demo User
expect_text role=alert | Invalid email
expect_url /dashboard
expect_title Dashboard
expect_value #email | demo@example.com
expect_visible testid=menu
"""


def test_parse_and_format_round_trip():
    steps = parse_steps(PLAN_TEXT)
    assert [s.action for s in steps][:4] == [StepAction.GOTO, StepAction.FILL, StepAction.FILL, StepAction.CLICK]
    assert steps[1] == PlanStep(action=StepAction.FILL, target="label=Email", value="demo@example.com")
    assert steps[5] == PlanStep(action=StepAction.EXPECT_TEXT, value="Welcome, Demo User")
    assert steps[6].target == "role=alert"
    assert parse_steps(format_steps(steps)) == steps


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ("open /login", "action"),
        ("fill label=Email", "target_value"),
        ("click", "target"),
        ("goto", "value"),
        ("click role=wizard[name=x]", "role"),
        ("press Enter; rm -rf /", "key"),
        ("expect_text {{secret:PASSWORD}}", "secret"),
        ("fill label=Email | prefix {{secret:PASSWORD}}", "secret"),
        ("click label=", "target"),
    ],
)
def test_invalid_lines_are_rejected_with_a_code(line, code):
    with pytest.raises(StepError) as error:
        parse_steps(f"goto /\n{line}")
    assert error.value.code == code
    assert error.value.line == 2


def test_locators():
    assert parse_locator("label=Email") == Locator("label", "Email")
    assert parse_locator("role=button[name=Sign in]") == Locator("role", "button", "Sign in")
    assert parse_locator('role=link[name="Read more"]') == Locator("role", "link", "Read more")
    assert parse_locator("role=heading") == Locator("role", "heading", "")
    assert parse_locator("#email") == Locator("css", "#email")
    assert parse_locator("css=form > button") == Locator("css", "form > button")
    with pytest.raises(StepError):
        parse_locator("x" * 400)


def test_comments_and_blank_lines_are_ignored():
    assert parse_line("   ") is None
    assert parse_line("# note") is None


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Open /login", PlanStep(action=StepAction.GOTO, value="/login")),
        ("1. Navigate to the page /contact.", PlanStep(action=StepAction.GOTO, value="/contact")),
        ('Enter "demo@example.com" in the "Email" field',
         PlanStep(action=StepAction.FILL, target="label=Email", value="demo@example.com")),
        ('Type "Alex" into Name', PlanStep(action=StepAction.FILL, target="label=Name", value="Alex")),
        ('Fill in the "Message" field with "Hello"',
         PlanStep(action=StepAction.FILL, target="label=Message", value="Hello")),
        ("Leave the Email field empty", PlanStep(action=StepAction.FILL, target="label=Email", value=EMPTY)),
        ('Click the "Sign in" button', PlanStep(action=StepAction.CLICK, target="role=button[name=Sign in]")),
        ('Click "Contact" link', PlanStep(action=StepAction.CLICK, target="role=link[name=Contact]")),
        ("Click “Details”", PlanStep(action=StepAction.CLICK, target="text=Details")),
        ('Select "Ukraine" from the "Country" list',
         PlanStep(action=StepAction.SELECT, target="label=Country", value="Ukraine")),
        ('Check the "Remember me" checkbox', PlanStep(action=StepAction.CHECK, target="label=Remember me")),
        ("Press Enter", PlanStep(action=StepAction.PRESS, value="Enter")),
        ("press the arrowdown key", PlanStep(action=StepAction.PRESS, value="ArrowDown")),
        ("fill #email | x@y.z", PlanStep(action=StepAction.FILL, target="#email", value="x@y.z")),
    ],
)
def test_written_steps_are_converted(sentence, expected):
    assert step_from_sentence(sentence) == [expected]


@pytest.mark.parametrize(
    "sentence",
    [
        "Perform the action described in the requirement.",
        "Set up the conditions described in REQ-1.",
        "Click Save",  # no quotes: which element is meant is not certain
        "Log in as an administrator",
        "Open the settings",
    ],
)
def test_vague_steps_are_not_guessed(sentence):
    assert step_from_sentence(sentence) is None


def test_expected_result_becomes_checks():
    steps = assertions_from_expected(
        'The user is redirected to /dashboard. The page shows "Welcome, Demo User" and does not show "Error". '
        'The page title is "Dashboard".'
    )
    assert PlanStep(action=StepAction.EXPECT_URL, value="/dashboard") in steps
    assert PlanStep(action=StepAction.EXPECT_TEXT, value="Welcome, Demo User") in steps
    assert PlanStep(action=StepAction.EXPECT_NO_TEXT, value="Error") in steps
    assert PlanStep(action=StepAction.EXPECT_TITLE, value="Dashboard") in steps
    assert assertions_from_expected("The system behaves as stated in the requirement.") == []


def test_a_test_case_with_one_unreadable_step_gets_no_steps():
    converted = steps_from_test_case(
        [], ["Open /login", "Do something clever"], 'The page shows "Welcome"')
    assert converted.steps == []
    assert converted.unparsed == ["Do something clever"]


def test_a_test_case_without_a_check_gets_no_steps():
    converted = steps_from_test_case([], ["Open /login"], "It works.")
    assert converted.steps == [] and converted.unparsed == []


def test_a_concrete_test_case_is_fully_converted():
    converted = steps_from_test_case(
        ["A registered user exists"],
        ["Open /login", 'Enter "demo@example.com" in the "Email" field', 'Click the "Sign in" button'],
        'The user lands on /dashboard and sees "Welcome".',
    )
    actions = [s.action for s in converted.steps]
    assert actions == [StepAction.GOTO, StepAction.FILL, StepAction.CLICK, StepAction.EXPECT_URL, StepAction.EXPECT_TEXT]
    assert converted.unparsed == []
