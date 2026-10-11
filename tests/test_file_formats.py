"""End-to-end tests: uploaded file -> text -> requirements -> findings."""

import io

import pytest
from pypdf import PdfReader, PdfWriter

from conftest import make_pdf
from spec_to_test.input_parser import (
    MAX_FILE_SIZE_BYTES,
    MAX_PDF_PAGES,
    MAX_TEXT_CHARS,
    InputError,
    extract_requirements,
    read_uploaded_file,
)
from spec_to_test.models import FindingType, Language
from spec_to_test.rule_engine import analyze_requirements

SPEC = (
    "REQ-1: The system must send a reset link.\n"
    "REQ-2: The page should load fast.\n"
    "REQ-3: The password must be at least 8 characters.\n"
)


def pipeline(filename: str, data: bytes):
    return analyze_requirements(extract_requirements(read_uploaded_file(filename, data)))


def error_code(filename: str, data: bytes) -> str:
    with pytest.raises(InputError) as error:
        read_uploaded_file(filename, data)
    return error.value.code


@pytest.mark.parametrize("filename", ["spec.txt", "spec.md", "SPEC.MD"])
def test_text_files_give_same_result_as_pasted_text(filename):
    from_file = pipeline(filename, SPEC.encode("utf-8"))
    pasted = analyze_requirements(extract_requirements(SPEC))
    assert from_file == pasted
    assert [r.id for r in from_file.requirements] == ["REQ-1", "REQ-2", "REQ-3"]


def test_pdf_gives_same_ids_and_findings_as_text():
    pdf = make_pdf(SPEC.strip().split("\n"))
    result = pipeline("spec.pdf", pdf)
    assert [r.id for r in result.requirements] == ["REQ-1", "REQ-2", "REQ-3"]
    ambiguous = [f.requirement_id for f in result.findings if f.type == FindingType.AMBIGUOUS_WORDING]
    assert ambiguous == ["REQ-2"]


def test_windows_line_endings():
    result = pipeline("spec.txt", SPEC.replace("\n", "\r\n").encode("utf-8"))
    assert [r.text for r in result.requirements][0] == "The system must send a reset link."


def test_old_mac_line_endings():
    result = pipeline("spec.txt", SPEC.replace("\n", "\r").encode("utf-8"))
    assert len(result.requirements) == 3


def test_cyrillic_markdown_file():
    data = "# Вимоги\n\n- ВМ-1: Система повинна надіслати лист.\n- ТР-1: Система должна отправить письмо.\n"
    result = pipeline("вимоги.md", data.encode("utf-8"))
    assert [(r.id, r.language) for r in result.requirements] == [
        ("ВМ-1", Language.UK),
        ("ТР-1", Language.RU),
    ]


def test_file_exactly_at_size_limit_is_accepted():
    line = "REQ-1: The system must save drafts.\n"
    data = (line * (MAX_FILE_SIZE_BYTES // len(line))).encode()
    data += b" " * (MAX_FILE_SIZE_BYTES - len(data))
    assert len(data) == MAX_FILE_SIZE_BYTES
    # Size is fine; the text is then over the character limit.
    assert error_code("spec.txt", data) == "text_too_long"


def test_text_over_character_limit_inside_small_file():
    data = ("x" * (MAX_TEXT_CHARS + 1)).encode()
    assert len(data) < MAX_FILE_SIZE_BYTES
    assert error_code("spec.md", data) == "text_too_long"


def test_encrypted_pdf_is_rejected():
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["REQ-1: The system must save."]))))
    writer.encrypt("secret", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    assert error_code("spec.pdf", buffer.getvalue()) == "encrypted_pdf"


def test_pdf_with_too_many_pages_is_rejected():
    writer = PdfWriter()
    for _ in range(MAX_PDF_PAGES + 1):
        writer.add_blank_page(100, 100)
    buffer = io.BytesIO()
    writer.write(buffer)
    assert error_code("spec.pdf", buffer.getvalue()) == "pdf_too_many_pages"


def test_truncated_pdf_is_rejected_without_crashing():
    pdf = make_pdf(["REQ-1: The system must save."])
    assert error_code("spec.pdf", pdf[: len(pdf) // 2]) in {"invalid_pdf", "pdf_no_text"}


def test_pdf_renamed_to_txt_is_rejected():
    assert error_code("spec.txt", make_pdf(["REQ-1: x"]) + b"\x00") == "binary_content"


def test_text_renamed_to_pdf_is_rejected():
    assert error_code("spec.pdf", SPEC.encode()) == "invalid_pdf"


@pytest.mark.parametrize("filename", ["spec.docx", "spec.html", "spec.exe", "spec.pdf.exe", ".md", "spec."])
def test_unsupported_or_disguised_names_are_rejected(filename):
    assert error_code(filename, b"REQ-1: text") == "unsupported_file_type"


def test_markdown_formatting_is_tolerated():
    data = (
        "# Spec\n\n> Note: draft\n\n```\ncode block\n```\n\n"
        "**REQ-1:** The system **must** save drafts.\n\n---\n\n"
        "| ID | Requirement |\n|----|-------------|\n| REQ-2 | The system must show a list. |\n"
    )
    result = pipeline("spec.md", data.encode())
    assert [(r.id, r.text) for r in result.requirements] == [
        ("REQ-1", "The system must save drafts."),
        ("REQ-2", "The system must show a list."),
    ]


def test_special_characters_are_preserved():
    text = 'REQ-1: The system must display "Ціна: 5 € <b>&amp;</b>" — exactly; 100% ✓.'
    result = pipeline("spec.md", text.encode("utf-8"))
    assert result.requirements[0].text == text.removeprefix("REQ-1: ")
