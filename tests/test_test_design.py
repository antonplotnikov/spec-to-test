from decimal import Decimal

import pytest

from spec_to_test.models import Requirement
from spec_to_test.test_design import (
    decision_table,
    design_tests,
    extract_constraints,
)


def values(analysis):
    return [(str(v.value), v.expectation) for v in analysis.values]


def test_min_constraint_boundaries():
    design = design_tests(Requirement(id="R", text="The password must be at least 8 characters long."))
    assert values(design.boundaries[0]) == [("7", "invalid"), ("8", "valid"), ("9", "valid")]
    parts = design.partitions[0].partitions
    assert [(p.interval, p.expectation) for p in parts] == [("< 8", "invalid"), ("≥ 8", "valid")]


def test_max_constraint_boundaries():
    design = design_tests(Requirement(id="R", text="The comment must be no more than 200 characters."))
    assert values(design.boundaries[0]) == [("199", "valid"), ("200", "valid"), ("201", "invalid")]


@pytest.mark.parametrize(
    "text",
    [
        "Username must be between 3 and 20 characters.",
        "Username must be from 3 to 20 characters.",
        "Ім'я користувача має містити від 3 до 20 символів.",
        "Имя пользователя должно содержать от 3 до 20 символов.",
        "Username must be at least 3 characters and no more than 20 characters.",
    ],
)
def test_ranges_in_all_languages(text):
    [constraint] = extract_constraints(text)
    assert constraint.kind == "range"
    assert (constraint.low, constraint.high) == (Decimal(3), Decimal(20))
    design = design_tests(Requirement(id="R", text=text))
    assert values(design.boundaries[0]) == [
        ("2", "invalid"), ("3", "valid"), ("4", "valid"),
        ("19", "valid"), ("20", "valid"), ("21", "invalid"),
    ]
    assert [p.name for p in design.partitions[0].partitions] == ["below", "inside", "above"]


def test_exact_value_does_not_invent_neighbour_behavior():
    design = design_tests(Requirement(id="R", text="The reset link expires after 30 minutes."))
    assert values(design.boundaries[0]) == [("29", "unspecified"), ("30", "stated"), ("31", "unspecified")]
    assert {p.expectation for p in design.partitions[0].partitions} == {"stated", "unspecified"}


def test_decimal_step():
    design = design_tests(Requirement(id="R", text="The file must be at most 2.5 MB."))
    assert values(design.boundaries[0]) == [("2.4", "valid"), ("2.5", "valid"), ("2.6", "invalid")]


def test_no_numbers_means_no_boundaries():
    design = design_tests(Requirement(id="R", text="The password must be long enough."))
    assert design.boundaries == [] and design.partitions == []


def test_negative_values_are_not_generated():
    design = design_tests(Requirement(id="R", text="The retry delay must be at least 0 seconds."))
    assert all(v.value >= 0 for v in design.boundaries[0].values)
    assert [p.name for p in design.partitions[0].partitions] == ["inside"]


def test_decision_table_single_condition_leaves_else_unspecified():
    table = decision_table("If the email address is not registered, the system shows a generic message.")
    assert table.conditions == ["the email address is not registered"]
    assert [(r.values, r.outcome) for r in table.rules] == [
        ([True], "the system shows a generic message"),
        ([False], None),
    ]


def test_decision_table_and_with_otherwise():
    table = decision_table(
        "If the user is logged in and the cart is not empty, the checkout button is shown. "
        "Otherwise the button is hidden."
    )
    assert table.connector == "and"
    assert len(table.rules) == 4
    assert table.rules[0].outcome == "the checkout button is shown"
    assert {r.outcome for r in table.rules[1:]} == {"the button is hidden"}


def test_decision_table_or_conditions():
    table = decision_table("If the token is expired or the token is revoked, the API returns 401.")
    assert table.connector == "or"
    outcomes = {tuple(r.values): r.outcome for r in table.rules}
    assert outcomes[(False, False)] is None
    assert outcomes[(True, False)] == "the API returns 401"


def test_decision_table_trailing_condition_and_cyrillic():
    assert decision_table("The account is locked when the user enters a wrong password 5 times.").action == (
        "The account is locked"
    )
    assert decision_table("Якщо пароль невірний, система показує помилку.").conditions == ["пароль невірний"]
    assert decision_table("Если пароль неверный, система показывает ошибку.").action == "система показывает ошибку"


def test_short_and_phrases_are_not_split():
    table = decision_table("If email and password are valid, the user is logged in.")
    assert table.conditions == ["email and password are valid"]


def test_mixed_and_or_is_not_guessed():
    assert decision_table("If A is set and B is set or C is set, the flag is shown.") is None


def test_no_condition_no_table():
    assert decision_table("The system must send a reset link to the registered email.") is None
