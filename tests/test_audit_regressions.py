"""Regression tests for bugs found during the QA audit (one section per bug)."""

import time

from spec_to_test.input_parser import extract_requirements, validate_text
from spec_to_test.models import FindingType, Requirement
from spec_to_test.rule_engine import analyze_requirements


def ids_and_texts(text: str) -> list[tuple[str, str]]:
    return [(r.id, r.text) for r in extract_requirements(text)]


def finding_types(text: str) -> set[FindingType]:
    result = analyze_requirements([Requirement(id="REQ-1", text=text)])
    return {f.type for f in result.findings}


# --- Parsing and IDs -----------------------------------------------------------

def test_multi_segment_ids_are_recognized():
    assert ids_and_texts(
        "FR-AUTH-01: The system must save drafts.\nFR-AUTH-02: The system must show a list."
    ) == [
        ("FR-AUTH-01", "The system must save drafts."),
        ("FR-AUTH-02", "The system must show a list."),
    ]


def test_numeric_sub_ids_keep_their_full_id_and_text():
    # Previously "REQ-1-2: Third" became ID "REQ-1-3" with text "2: Third ...".
    assert ids_and_texts("REQ-1-1: First thing here.\nREQ-1-2: Second thing here.") == [
        ("REQ-1-1", "First thing here."),
        ("REQ-1-2", "Second thing here."),
    ]


def test_duplicate_suffix_never_takes_an_id_used_elsewhere():
    reqs = ids_and_texts(
        "REQ-1: First thing here.\nREQ-1: Second thing here.\nREQ-1-2: Third thing here."
    )
    assert reqs[2] == ("REQ-1-2", "Third thing here.")  # genuine ID is kept
    assert reqs[1][0] not in {"REQ-1", "REQ-1-2"}
    assert len({req_id for req_id, _ in reqs}) == 3


def test_hierarchical_numbering_with_trailing_dot():
    assert ids_and_texts("1.1. The system must save drafts.\n1.2. The system must show a list.") == [
        ("REQ-001", "The system must save drafts."),
        ("REQ-002", "The system must show a list."),
    ]


def test_hierarchical_numbering_without_trailing_dot():
    assert ids_and_texts("1.1 The system must save drafts.\n1.2 The system must show a list.") == [
        ("REQ-001", "The system must save drafts."),
        ("REQ-002", "The system must show a list."),
    ]


def test_decimal_number_at_line_start_is_not_a_list_number():
    reqs = ids_and_texts("REQ-1: The page must load within\n2.5 seconds on 4G networks.")
    assert reqs == [("REQ-1", "The page must load within 2.5 seconds on 4G networks.")]


def test_numbered_list_with_ids_keeps_the_ids():
    assert [r for r, _ in ids_and_texts(
        "1. REQ-1: The system must save drafts.\n2. REQ-2: The system must show a list."
    )] == ["REQ-1", "REQ-2"]


def test_heading_with_id_keeps_id_and_description():
    reqs = ids_and_texts(
        "## REQ-1: Password reset\n\nThe system must send a link.\n\n"
        "## REQ-2: Lockout\nThe system must lock the account.\n\n## Glossary\nLink means URL."
    )
    assert reqs == [
        ("REQ-1", "Password reset The system must send a link."),
        ("REQ-2", "Lockout The system must lock the account."),
    ]


def test_technical_tokens_are_not_mistaken_for_ids():
    reqs = ids_and_texts(
        "UTF-8 encoding must be used for all exports.\n\n"
        "SHA-256 hashing must be used for passwords."
    )
    assert reqs == [
        ("REQ-001", "UTF-8 encoding must be used for all exports."),
        ("REQ-002", "SHA-256 hashing must be used for passwords."),
    ]


def test_invisible_characters_from_copy_paste_do_not_hide_ids():
    reqs = ids_and_texts(
        "﻿REQ-1: The system must save drafts.\n​REQ-2: The system must show a list."
    )
    assert reqs == [("REQ-1", "The system must save drafts."), ("REQ-2", "The system must show a list.")]


def test_input_with_only_invisible_characters_is_empty():
    import pytest

    from spec_to_test.input_parser import InputError

    with pytest.raises(InputError) as error:
        validate_text("​﻿ ⁠")
    assert error.value.code == "empty_input"


def test_word_style_bullets_are_split():
    for bullet in ["–", "—", "·", "▪", "◦"]:
        reqs = ids_and_texts(f"{bullet} The system must save drafts.\n{bullet} The system must show a list.")
        assert len(reqs) == 2, bullet


def test_table_with_extra_columns_uses_description_column():
    table = (
        "| ID | Priority | Description |\n|---|---|---|\n"
        "| REQ-1 | High | The system must send a reset link. |\n"
        "| REQ-2 | Low | The system must log out idle users. |"
    )
    assert ids_and_texts(table) == [
        ("REQ-1", "The system must send a reset link."),
        ("REQ-2", "The system must log out idle users."),
    ]


def test_double_underscores_in_text_are_preserved():
    assert ids_and_texts("REQ-1: The __init__ module must load config.")[0][1] == (
        "The __init__ module must load config."
    )


# --- Misleading findings (false positives) -------------------------------------

def test_nouns_alone_do_not_trigger_missing_error_handling():
    for text in [
        "Passwords must be stored as bcrypt hashes.",
        "The system must log every request.",
        "The system must send a reset link to the registered email address.",
    ]:
        assert FindingType.MISSING_ERROR_HANDLING not in finding_types(text), text


def test_obligation_counts_as_stated_behavior():
    for text in [
        "The system shall encrypt all data at rest using AES-256.",
        "Пароль має містити щонайменше 8 символів.",
        "Пароль должен содержать не менее 8 символов.",
    ]:
        assert FindingType.MISSING_EXPECTED_RESULT not in finding_types(text), text


def test_capability_without_result_is_still_flagged():
    for text in [
        "The user can change the password.",
        "The user must be able to change the password.",
        "Користувач може змінити пароль.",
        "Пользователь может сменить пароль.",
    ]:
        assert FindingType.MISSING_EXPECTED_RESULT in finding_types(text), text


def test_shared_verb_alone_is_not_a_contradiction():
    result = analyze_requirements(
        extract_requirements(
            "REQ-1: The reset link expires after 30 minutes.\nREQ-2: The session expires after 15 minutes."
        )
    )
    assert not [f for f in result.findings if f.type == FindingType.CONTRADICTION]


def test_ukrainian_according_to_is_not_ambiguous():
    assert FindingType.AMBIGUOUS_WORDING not in finding_types("Дані зберігаються відповідно до GDPR.")
    assert FindingType.AMBIGUOUS_WORDING in finding_types("Система має показати відповідне повідомлення.")


# --- Performance -----------------------------------------------------------------

def test_maximum_document_is_analyzed_quickly():
    text = "\n".join(
        f"REQ-{n}: The system must save record number {n} within {n} seconds for group {n}."
        for n in range(1, 501)
    )
    start = time.perf_counter()
    result = analyze_requirements(extract_requirements(text))
    assert len(result.requirements) == 500
    assert time.perf_counter() - start < 5  # was ~15 s before the fix
