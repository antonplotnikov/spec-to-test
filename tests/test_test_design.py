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
    design = design_tests(Requirement(id="R", text="The discount is 10%."))
    assert values(design.boundaries[0]) == [("9", "unspecified"), ("10", "stated"), ("11", "unspecified")]
    assert {p.expectation for p in design.partitions[0].partitions} == {"stated", "unspecified"}


def partitions(analysis):
    return [(p.interval, str(p.representative), p.expectation) for p in analysis.partitions]


@pytest.mark.parametrize("text", [
    "The system must send a password reset link within 60 seconds.",
    "Система повинна надіслати лист протягом 60 секунд.",
    "Система должна отправить письмо в течение 60 секунд.",
])
def test_within_is_a_deadline_that_includes_its_limit(text):
    design = design_tests(Requirement(id="R", text=text))
    assert design.boundaries[0].constraint.timing == "deadline"
    assert values(design.boundaries[0]) == [("59", "in_time"), ("60", "in_time"), ("61", "too_late")]
    assert partitions(design.partitions[0]) == [("≤ 60", "30", "in_time"), ("> 60", "120", "too_late")]


@pytest.mark.parametrize("text", [
    "The reset link expires after 30 minutes.",
    "The reset link must expire 30 minutes after it is generated.",
    "The link expires in 30 minutes.",
    "Сесія завершується через 30 хвилин бездіяльності.",
    "Сессия завершается через 30 минут бездействия.",
])
def test_after_is_a_delay_not_an_equality(text):
    design = design_tests(Requirement(id="R", text=text))
    assert design.boundaries[0].constraint.timing == "delay"
    # 29: the link still works, 31: it has expired; the exact moment is the one the requirement names.
    assert values(design.boundaries[0]) == [("29", "not_yet"), ("30", "stated"), ("31", "happened")]
    assert partitions(design.partitions[0]) == [("< 30", "15", "not_yet"), ("> 30", "60", "happened")]


def test_for_is_a_duration():
    text = "After 5 consecutive failed login attempts, the account must be locked for 15 minutes."
    design = design_tests(Requirement(id="R", text=text))
    assert design.boundaries[0].constraint.timing == "duration"
    assert values(design.boundaries[0]) == [("14", "in_effect"), ("15", "stated"), ("16", "ended")]
    assert partitions(design.partitions[0]) == [("< 15", "8", "in_effect"), ("> 15", "30", "ended")]


def test_attempt_limits_are_inclusive_unless_strict():
    design = design_tests(Requirement(id="R", text="Lock the account after 5 attempts."))
    # The lock happens on the 5th attempt.
    assert values(design.boundaries[0]) == [("4", "not_yet"), ("5", "happened"), ("6", "happened")]
    assert partitions(design.partitions[0]) == [("< 5", "2", "not_yet"), ("≥ 5", "10", "happened")]
    design = design_tests(Requirement(id="R", text="Lock the account after more than 5 attempts."))
    assert design.boundaries[0].constraint.phrase == "more than 5 attempts"
    assert values(design.boundaries[0]) == [("4", "not_yet"), ("5", "not_yet"), ("6", "happened")]
    assert partitions(design.partitions[0]) == [("≤ 5", "2", "not_yet"), ("> 5", "10", "happened")]
    design = design_tests(Requirement(id="R", text="Пользователь может сделать не более 10 попыток входа."))
    assert values(design.boundaries[0]) == [("9", "valid"), ("10", "valid"), ("11", "invalid")]


@pytest.mark.parametrize("text", [
    "Passwords longer than 64 characters are rejected.",
    "Orders over 50 USD ship free.",
    "The page must load in less than 2 seconds.",
])
def test_strict_comparators_without_a_timing_word_stay_exact(text):
    # Which side of "longer than 64" is valid depends on the sentence, so nothing is guessed around it.
    [boundary] = design_tests(Requirement(id="R", text=text)).boundaries
    assert boundary.constraint.timing is None and not boundary.constraint.strict
    assert [e for _, e in values(boundary)] == ["unspecified", "stated", "unspecified"]


@pytest.mark.parametrize("text", [
    "Розмір аватара не повинен перевищувати 1 МБ.",
    "Розмір аватара не повинен перевищувати 1024 КБ.",
    "Размер аватара не должен превышать 1 МБ.",
    "The avatar cannot exceed 1 MB.",
    "The avatar must not exceed 1 MB.",
])
def test_must_not_exceed_is_an_inclusive_upper_limit(text):
    [boundary] = design_tests(Requirement(id="R", text=text)).boundaries
    # 1 MB is probed as 1024 KB: 0 and 2 MB would be too coarse.
    assert boundary.constraint.unit == "kilobytes"
    assert values(boundary) == [("1023", "valid"), ("1024", "valid"), ("1025", "invalid")]


def test_coarse_data_limits_are_probed_in_a_smaller_unit():
    [boundary] = design_tests(Requirement(id="R", text="The file must be at most 2.5 MB.")).boundaries
    assert (boundary.constraint.unit, boundary.constraint.phrase) == ("kilobytes", "at most 2.5 MB")
    assert values(boundary) == [("2559", "valid"), ("2560", "valid"), ("2561", "invalid")]
    [boundary] = design_tests(Requirement(id="R", text="The file must be at most 500 MB.")).boundaries
    assert (boundary.constraint.unit, values(boundary)[0]) == ("megabytes", ("499", "valid"))


def test_correct_ranges_and_units_keep_their_values():
    design = design_tests(Requirement(id="R", text="Пароль має містити від 8 до 64 символів."))
    assert values(design.boundaries[0]) == [
        ("7", "invalid"), ("8", "valid"), ("9", "valid"), ("63", "valid"), ("64", "valid"), ("65", "invalid"),
    ]
    design = design_tests(Requirement(id="R", text="Сумма заказа должна быть не менее 500 рублей."))
    assert values(design.boundaries[0]) == [("499", "invalid"), ("500", "valid"), ("501", "valid")]
    assert design.boundaries[0].constraint.timing is None


def test_decimal_step():
    design = design_tests(Requirement(id="R", text="The response must take at most 2.5 seconds."))
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
