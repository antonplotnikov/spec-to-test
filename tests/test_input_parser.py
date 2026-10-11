import pytest

from conftest import make_pdf
from spec_to_test.input_parser import (
    MAX_FILE_SIZE_BYTES,
    MAX_TEXT_CHARS,
    InputError,
    detect_language,
    extract_requirements,
    read_uploaded_file,
    validate_text,
)
from spec_to_test.models import Language

# --- validate_text ---------------------------------------------------------

@pytest.mark.parametrize("value", [None, "", "   ", "\n\t\n"])
def test_empty_input_is_rejected(value):
    with pytest.raises(InputError) as error:
        validate_text(value)
    assert error.value.code == "empty_input"


def test_too_long_input_is_rejected():
    with pytest.raises(InputError) as error:
        validate_text("a" * (MAX_TEXT_CHARS + 1))
    assert error.value.code == "text_too_long"
    assert error.value.params == {"max_chars": MAX_TEXT_CHARS}


def test_control_characters_are_removed_and_newlines_normalized():
    assert validate_text("  a\x00b\r\nc\x07  ") == "ab\nc"


# --- read_uploaded_file ----------------------------------------------------

@pytest.mark.parametrize("name", ["spec.docx", "spec.exe", "spec", "spec.md.exe"])
def test_unsupported_file_types_are_rejected(name):
    with pytest.raises(InputError) as error:
        read_uploaded_file(name, b"REQ-1: text")
    assert error.value.code == "unsupported_file_type"


def test_extension_check_is_case_insensitive():
    assert read_uploaded_file("SPEC.TXT", b"REQ-1: text") == "REQ-1: text"


def test_empty_file_is_rejected():
    with pytest.raises(InputError) as error:
        read_uploaded_file("spec.txt", b"")
    assert error.value.code == "empty_file"


def test_too_large_file_is_rejected():
    with pytest.raises(InputError) as error:
        read_uploaded_file("spec.txt", b"a" * (MAX_FILE_SIZE_BYTES + 1))
    assert error.value.code == "file_too_large"


def test_binary_content_in_text_file_is_rejected():
    with pytest.raises(InputError) as error:
        read_uploaded_file("spec.txt", b"\x89PNG\x00\x00binary")
    assert error.value.code == "binary_content"


def test_non_utf8_text_is_rejected():
    with pytest.raises(InputError) as error:
        read_uploaded_file("spec.txt", "Пароль".encode("cp1251"))
    assert error.value.code == "encoding_error"


def test_utf8_with_bom_is_accepted():
    data = "﻿REQ-1: Пароль".encode()
    assert read_uploaded_file("spec.md", data) == "REQ-1: Пароль"


def test_whitespace_only_file_is_rejected():
    with pytest.raises(InputError) as error:
        read_uploaded_file("spec.txt", b"   \n  ")
    assert error.value.code == "empty_input"


def test_valid_pdf_text_is_extracted():
    pdf = make_pdf(["REQ-1: The system must send an email.", "REQ-2: Lock after 5 attempts."])
    text = read_uploaded_file("spec.pdf", pdf)
    assert "REQ-1: The system must send an email." in text
    assert "REQ-2" in text


def test_fake_pdf_is_rejected():
    with pytest.raises(InputError) as error:
        read_uploaded_file("spec.pdf", b"This is not a PDF")
    assert error.value.code == "invalid_pdf"


def test_corrupted_pdf_is_rejected():
    with pytest.raises(InputError) as error:
        read_uploaded_file("spec.pdf", b"%PDF-1.4\ngarbage garbage")
    assert error.value.code in {"invalid_pdf", "pdf_no_text"}


def test_pdf_without_text_is_rejected():
    with pytest.raises(InputError) as error:
        read_uploaded_file("spec.pdf", make_pdf([]))
    assert error.value.code == "pdf_no_text"


# --- detect_language -------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The user must reset the password.", Language.EN),
        ("Користувач повинен мати змогу змінити пароль.", Language.UK),
        ("Користувач вводить email у поле форми.", Language.UK),
        ("Пользователь должен иметь возможность сменить пароль.", Language.RU),
        ("Система отправляет письмо, если email существует.", Language.RU),
    ],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


# --- extract_requirements --------------------------------------------------

def test_explicit_ids_are_kept_and_text_preserved():
    reqs = extract_requirements(
        "REQ-1: The user must log in.\n- FR-02. Data is saved.\n[US-3] Reports are exported."
    )
    assert [r.id for r in reqs] == ["REQ-1", "FR-02", "US-3"]
    assert reqs[0].text == "The user must log in."
    assert all(r.has_explicit_id for r in reqs)


def test_bullets_and_numbers_get_generated_ids():
    reqs = extract_requirements("- First requirement here\n2) Second requirement here")
    assert [r.id for r in reqs] == ["REQ-001", "REQ-002"]
    assert reqs[1].text == "Second requirement here"
    assert not reqs[0].has_explicit_id


def test_plain_paragraph_is_split_into_sentences():
    reqs = extract_requirements(
        "Система должна быть удобной. Пользователь вводит пароль. Количество попыток ограничено."
    )
    assert len(reqs) == 3
    assert reqs[2].text == "Количество попыток ограничено."


def test_intro_text_is_skipped_in_structured_documents(example_text):
    reqs = extract_requirements(example_text)
    assert [r.id for r in reqs] == [f"REQ-{n}" for n in range(1, 10)]
    assert not any("This document describes" in r.text for r in reqs)


def test_continuation_lines_are_joined_to_previous_item():
    reqs = extract_requirements("REQ-1: The system must send\n  a confirmation email.")
    assert reqs[0].text == "The system must send a confirmation email."


def test_markdown_table_rows_are_parsed():
    table = (
        "| ID | Requirement |\n"
        "|----|-------------|\n"
        "| REQ-10 | The password must be hashed. |\n"
        "| REQ-11 | Sessions expire after 15 minutes. |"
    )
    reqs = extract_requirements(table)
    assert [(r.id, r.text) for r in reqs] == [
        ("REQ-10", "The password must be hashed."),
        ("REQ-11", "Sessions expire after 15 minutes."),
    ]


def test_bold_ids_are_recognized():
    reqs = extract_requirements("**REQ-5:** The user must confirm the email.")
    assert reqs[0].id == "REQ-5"


def test_uppercase_word_with_digit_is_not_mistaken_for_an_id():
    reqs = extract_requirements("MP3 files must be playable in the browser.")
    assert reqs[0].id == "REQ-001"
    assert reqs[0].text == "MP3 files must be playable in the browser."


def test_cyrillic_ids_are_supported():
    reqs = extract_requirements("ВМ-1: Користувач повинен отримати лист.")
    assert reqs[0].id == "ВМ-1"
    assert reqs[0].language == Language.UK


def test_duplicate_ids_are_made_unique():
    reqs = extract_requirements("REQ-1: First thing here.\nREQ-1: Second thing here.")
    assert [r.id for r in reqs] == ["REQ-1", "REQ-1-2"]


def test_generated_ids_do_not_collide_with_explicit_ones():
    reqs = extract_requirements("REQ-001: Explicit requirement.\n- Unnumbered requirement.")
    assert [r.id for r in reqs] == ["REQ-001", "REQ-002"]


def test_source_line_numbers_are_recorded():
    reqs = extract_requirements("# Title\n\nREQ-1: Something to do.\n\nREQ-2: Another thing.")
    assert [r.source_line for r in reqs] == [3, 5]


def test_too_short_fragments_are_ignored():
    with pytest.raises(InputError) as error:
        extract_requirements("- ok\n- yes")
    assert error.value.code == "no_requirements_found"


def test_headings_only_produce_no_requirements():
    with pytest.raises(InputError) as error:
        extract_requirements("# Title\n## Section\n---")
    assert error.value.code == "no_requirements_found"


def test_mixed_language_document():
    reqs = extract_requirements(
        "REQ-1: The user must log in.\n"
        "REQ-2: Користувач повинен отримати лист.\n"
        "REQ-3: Пользователь должен получить письмо."
    )
    assert [r.language for r in reqs] == [Language.EN, Language.UK, Language.RU]
