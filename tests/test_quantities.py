"""Numbers with units (EN/RU/UK), context-aware contradictions and relevance of rule questions."""

from decimal import Decimal

import pytest

from spec_to_test.grill.rules import compare_limits, numbers_in
from spec_to_test.models import FindingType, Requirement
from spec_to_test.quantities import disagree, find_ranges, limits, parse_number
from spec_to_test.rule_engine import (
    analyze_requirements,
    boundary_terms,
    different_context,
    input_terms,
)
from spec_to_test.test_design import extract_constraints


def one(text: str) -> tuple[str, str, Decimal]:
    [quantity] = limits(text)
    return quantity.unit, quantity.comparator, quantity.value


@pytest.mark.parametrize(("text", "expected"), [
    ("at least $500", ("usd", "min", Decimal(500))),
    ("не менее 1 000 рублей", ("rub", "min", Decimal(1000))),
    ("свыше 5000 ₽", ("rub", "gt", Decimal(5000))),
    ("понад 200 грн", ("uah", "gt", Decimal(200))),
    ("не більше 300 гривень", ("uah", "max", Decimal(300))),
    ("1,000.50 USD", ("usd", "exact", Decimal("1000.50"))),
    ("2,5 секунды", ("seconds", "exact", Decimal("2.5"))),
    ("up to 5MB", ("megabytes", "max", Decimal(5))),
    ("must not exceed 2 GB", ("gigabytes", "max", Decimal(2))),
    ("не дольше 3 секунд", ("seconds", "max", Decimal(3))),
    ("не пізніше ніж за 30 секунд", ("seconds", "max", Decimal(30))),
    ("more than 3 attempts", ("attempts", "gt", Decimal(3))),
    ("менее 10 символов", ("characters", "lt", Decimal(10))),
    ("до 50 товаров", ("items", "max", Decimal(50))),
    ("10%", ("percent", "exact", Decimal(10))),
    ("€ 20", ("eur", "exact", Decimal(20))),
])
def test_quantities_in_three_languages(text, expected):
    assert one(text) == expected


@pytest.mark.parametrize("text", [
    "between 8 and 64 characters", "8–64 chars", "від 8 до 64 символів", "от 8 до 64 символов",
])
def test_ranges_become_a_min_and_a_max(text):
    found = limits(text)
    assert [(q.comparator, q.value) for q in found] == [("min", Decimal(8)), ("max", Decimal(64))]
    assert {q.unit for q in found} == {"characters"}


def test_ranges_need_one_unit_and_a_real_interval():
    assert [(r.low, r.high) for r in find_ranges("from $10 to $50")] == [(Decimal(10), Decimal(50))]
    assert not find_ranges("5 MB - 1 GB")  # two units: not one range
    assert not find_ranges("at least 2 digits and 10 characters")  # "digits" is not the range's unit
    assert not find_ranges("64 to 8 characters")  # low must be below high


def test_numbers_without_units_are_ignored():
    assert limits("REQ-12 refers to step 3") == []
    assert parse_number("1 000") == 1000 and parse_number("1,000") == 1000 and parse_number("2,5") == Decimal("2.5")
    assert numbers_in("1 000 рублей, 2,5 сек, REQ-12") == {"1000", "2.5", "12"}


def test_units_convert_within_a_dimension_only():
    [minutes], [seconds] = limits("2 minutes"), limits("120 seconds")
    assert not disagree(minutes, seconds)
    [gigabyte], [megabytes] = limits("at most 1 GB"), limits("at most 1024 MB")
    assert not disagree(gigabyte, megabytes)
    [dollars], [rubles] = limits("over 50 USD"), limits("over 3000 руб.")
    assert not disagree(dollars, rubles)  # no exchange rate is ever assumed
    [lower], [upper] = limits("at least 10 characters"), limits("at most 8 characters")
    assert disagree(lower, upper)  # no value satisfies both
    [expires], [cap] = limits("after 30 minutes"), limits("at most 60 minutes")
    assert not disagree(expires, cap)


def test_test_design_keeps_its_behavior_for_strict_comparators():
    [constraint] = extract_constraints("Lock the account after more than 5 attempts.")
    assert (constraint.kind, constraint.phrase) == ("exact", "5 attempts")
    [price] = extract_constraints("The order total must be at least 500 рублей.")
    assert (price.unit, price.kind, price.low) == ("rub", "min", Decimal(500))


def contradictions(*texts: str) -> list[tuple[str, ...]]:
    requirements = [Requirement(id=f"REQ-{n}", text=text) for n, text in enumerate(texts, 1)]
    return sorted({
        tuple(sorted([f.requirement_id, *f.related_requirement_ids]))
        for f in analyze_requirements(requirements).findings if f.type == FindingType.CONTRADICTION
    })


@pytest.mark.parametrize(("first", "second"), [
    ("Orders over 50 USD get free shipping.", "Orders over $75 get free shipping."),
    ("Сумма заказа должна быть не менее 500 ₽.", "Сумма заказа должна быть не менее 1 000 рублей."),
    ("Сума замовлення має бути не менше 200 грн.", "Сума замовлення має бути не менше 500 гривень."),
    ("The search API must respond within 500 ms.", "The search API must respond within 2 seconds."),
    ("The username must be between 3 and 20 characters.", "The username must be at least 5 characters long."),
    ("Пароль має містити від 8 до 64 символів.", "Пароль має містити щонайменше 10 символів."),
    ("The password must be at least 10 characters long.", "The password must be at most 8 characters long."),
])
def test_real_numeric_contradictions(first, second):
    assert contradictions(first, second) == [("REQ-1", "REQ-2")]


@pytest.mark.parametrize(("first", "second"), [
    ("Orders over 50 USD get free shipping.", "International orders over 100 USD get free shipping."),
    ("Сумма заказа должна быть не менее 500 рублей.", "Для оптовых покупателей сумма заказа должна быть не менее 10 000 рублей."),
    ("Сесія завершується через 15 хвилин бездіяльності.", "Сесія адміністратора завершується через 5 хвилин бездіяльності."),
    ("Free shipping applies to orders over 100 USD.", "Free shipping applies to orders over 50 USD if the address is abroad."),
    ("The session expires after 30 minutes of inactivity.", "The session expires after 1800 seconds of inactivity."),
    ("Uploaded files must not exceed 2 GB.", "Uploaded files must not exceed 2048 MB."),
    ("Доставка бесплатна для заказов свыше 3000 руб.", "Доставка бесплатна для заказов свыше 50 USD."),
])
def test_other_contexts_units_or_currencies_are_not_contradictions(first, second):
    assert contradictions(first, second) == []


def test_context_comes_from_qualifiers_and_conditions():
    assert different_context("Orders over 50 USD ship free.", "Premium orders over 50 USD ship free.")
    assert different_context("Orders ship free.", "Orders ship free if the address is abroad.")
    assert not different_context("The password must have 8 characters.", "The password must have 10 characters.")


def test_contradictions_only_name_real_requirements():
    texts = ["The PIN must be at least 4 characters.", "The PIN must be at least 6 characters.", "Logs are kept."]
    requirements = [Requirement(id=f"R{n}", text=t) for n, t in enumerate(texts)]
    ids = {r.id for r in requirements}
    for finding in analyze_requirements(requirements).findings:
        assert {finding.requirement_id, *finding.related_requirement_ids} <= ids


@pytest.mark.parametrize(("text", "expected"), [
    ("Uploaded photos should appear in the gallery within 3 seconds.", []),
    ("Uploaded files must not exceed 2 GB.", ["Uploaded"]),  # a limit on what the user submits
    ("After login, the dashboard shows the account type and the last login date.", []),
    ("The invoice is generated in the form of a PDF document.", []),
    ("Enterprise customers see a support number.", []),
    ("The user types the code into the field.", ["types", "field"]),
    ("The registration form has a required email field.", ["form", "field"]),
    ("Страница каталога должна загружаться быстро.", []),
    ("Загруженные фото отображаются в профиле.", []),
    ("Пользователь загружает фото профиля.", ["загружает"]),
    ("Отчёт формируется в формате PDF.", []),
    ("Пользователь прикрепляет файл к письму.", ["прикрепляет"]),
    ("Сторінка каталогу має завантажуватися швидко.", []),
    ("Завантажені фото відображаються в профілі.", []),
    ("Пароль має бути введений користувачем.", ["введений"]),
    ("Форма входу має бути зручною.", []),
])
def test_input_words_count_only_for_real_input(text, expected):
    assert input_terms(text) == expected


def test_event_bound_expiry_needs_no_number():
    assert boundary_terms("The session expires when the user logs out.") == []
    assert boundary_terms("Сессия истекает при выходе.") == []
    assert boundary_terms("The confirmation link expires.") == ["expires"]


def findings_of(text: str) -> set[FindingType]:
    return {f.type for f in analyze_requirements([Requirement(id="REQ-1", text=text)]).findings}


@pytest.mark.parametrize("text", [
    "Orders over 50 USD get free standard shipping.",
    "Подписка стоит 900 рублей в месяц.",
    "Enterprise customers see a dedicated support phone number.",
    "После входа в систему пользователь видит список своих заказов.",
    "Звіт формується у форматі PDF.",
])
def test_stated_values_and_visible_outcomes_need_no_expected_result_question(text):
    assert FindingType.MISSING_EXPECTED_RESULT not in findings_of(text)


def test_quoted_labels_and_inflected_vague_words():
    assert FindingType.AMBIGUOUS_WORDING not in findings_of('The "Quick pay" button is shown on the cart page.')
    assert FindingType.AMBIGUOUS_WORDING not in findings_of("Кнопка «Быстрая оплата» отображается в корзине.")
    assert FindingType.AMBIGUOUS_WORDING in findings_of("Интерфейс должен быть простым.")
    assert FindingType.AMBIGUOUS_WORDING in findings_of("Після кількох невдалих спроб обліковий запис блокується.")


def test_answer_limits_compare_in_base_units_and_context():
    requirement = Requirement(id="REQ-1", text="The session expires after 2 minutes of inactivity.")
    assert compare_limits("It expires after 120 seconds.", requirement, include_exact=True) == []
    password = Requirement(id="REQ-2", text="The password must be at least 8 characters.")
    [(verdict, _, _)] = compare_limits("It must be at least 10 characters.", password)
    assert verdict == "conflict"
    [(verdict, _, _)] = compare_limits("For admin accounts it must be at least 12 characters.", password)
    assert verdict == "new"  # another scope: a new rule, not a conflict
    [(verdict, _, _)] = compare_limits(
        "If the password is shorter, an error is shown; it must be at least 10 characters.", password)
    assert verdict == "conflict"  # a condition describing the failure path is no other scope
