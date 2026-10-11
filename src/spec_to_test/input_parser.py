"""Read, validate, and split requirement documents.

All input is treated as untrusted: file types, sizes, encodings and page
counts are checked before any text is processed. Errors are raised as
`InputError` with a code that the UI translates via `i18n`.
"""

import io
import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

from spec_to_test.models import Language, Requirement

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_TEXT_CHARS = 100_000
MAX_PDF_PAGES = 50
MAX_REQUIREMENTS = 500
MIN_REQUIREMENT_CHARS = 8
ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf")


class InputError(ValueError):
    """Invalid user input. `code` maps to an `error.<code>` translation key."""

    def __init__(self, code: str, **params: object) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


# ---------------------------------------------------------------------------
# Validation and file reading
# ---------------------------------------------------------------------------

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Zero-width space, word joiner and BOM often come from copy-pasting web pages.
_INVISIBLE_CHARS = re.compile("[\u200b\u2060\ufeff]")


def validate_text(text: str | None) -> str:
    """Return cleaned text or raise InputError if it is empty or too long."""
    if text is None or not text.strip():
        raise InputError("empty_input")
    if len(text) > MAX_TEXT_CHARS:
        raise InputError("text_too_long", max_chars=MAX_TEXT_CHARS)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE_CHARS.sub("", _CONTROL_CHARS.sub("", text))
    if not text.strip():
        raise InputError("empty_input")
    return text.strip()


def read_uploaded_file(filename: str, data: bytes) -> str:
    """Validate an uploaded file and return its text content."""
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise InputError(
            "unsupported_file_type",
            extension=extension or "?",
            allowed=", ".join(ALLOWED_EXTENSIONS),
        )
    if not data:
        raise InputError("empty_file")
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise InputError("file_too_large", max_mb=MAX_FILE_SIZE_BYTES // (1024 * 1024))

    text = _read_pdf(data) if extension == ".pdf" else _decode_text(data)
    return validate_text(text)


def _decode_text(data: bytes) -> str:
    if b"\x00" in data:
        raise InputError("binary_content")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError("encoding_error") from exc


def _read_pdf(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise InputError("invalid_pdf")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise InputError("encrypted_pdf")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise InputError("pdf_too_many_pages", max_pages=MAX_PDF_PAGES)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except InputError:
        raise
    except Exception as exc:  # pypdf raises many different error types
        raise InputError("invalid_pdf") from exc
    if not text.strip():
        raise InputError("pdf_no_text")
    return text


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_UK_WORDS = {
    "і", "та", "у", "що", "якщо", "або", "це", "бути", "повинен", "повинна",
    "має", "буде", "користувач", "користувача", "користувачі",
}
_RU_WORDS = {"и", "что", "если", "или", "это", "быть", "должен", "должна", "будет", "не"}


def detect_language(text: str) -> Language:
    """Guess whether text is English, Ukrainian or Russian."""
    lower = text.lower()
    cyrillic = len(re.findall(r"[а-яёіїєґ]", lower))
    latin = len(re.findall(r"[a-z]", lower))
    if cyrillic <= latin:
        return Language.EN

    words = re.findall(r"\w+", lower)
    uk_score = len(re.findall(r"[іїєґ]", lower)) + sum(w in _UK_WORDS for w in words)
    ru_score = len(re.findall(r"[ыэъё]", lower)) + sum(w in _RU_WORDS for w in words)
    return Language.UK if uk_score > ru_score else Language.RU


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------

_LETTERS = "A-ZА-ЯЁІЇЄҐ"
# IDs like REQ-1, FR02, REQ-1.2, REQ-1-2, FR-AUTH-01
_PREFIX = rf"[{_LETTERS}]{{1,10}}(?:[-_][{_LETTERS}]{{1,10}})*"
_ID = rf"{_PREFIX}[-_]?\d+(?:[.\-_]\d+)*"
_HYPHENATED_ID = rf"{_PREFIX}[-_]\d+(?:[.\-_]\d+)*"
# "-", "*", "•", "–" bullets and "1.", "2)", "1.1." numbering
_BULLET = r"(?:[-*+•–—·▪◦‣]|\d+(?:\.\d+)*[.)])"
# "REQ-1: text", "- FR-02. text", "[US-3] text", "1. REQ-1: text", "REQ-013 text".
# The text may be empty ("REQ-020:" or "REQ-013" alone); then the
# description is taken from the following line, if any.
_ID_LINE = re.compile(
    rf"^\s*(?:{_BULLET}\s+)?"
    rf"(?:\[(?P<bracket_id>{_ID})\]\s*[:.)\-–—]?"
    rf"|(?P<id>{_ID})\s*[:.)\-–—]"
    rf"|(?P<plain_id>{_HYPHENATED_ID})(?=\s|$))"
    r"\s*(?P<text>.*)$"
)
# "- text", "1. text", "2) text", "1.1. text", "1.1 Text"
_LIST_ITEM = re.compile(
    rf"^\s*(?:{_BULLET}|\d+(?:\.\d+)+(?=\s+[{_LETTERS}]))\s+(?P<text>\S.*)$"
)
_HEADING = re.compile(r"^\s*#{1,6}\s+(?P<title>.*)$")
_SEPARATOR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,}|`{3,}.*)\s*$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_ID_ONLY = re.compile(rf"^\[?{_ID}\]?$")
_SENTENCE_SPLIT = re.compile(rf"(?<=[.!?])\s+(?=[{_LETTERS}\"«])")
# Words that make a free-text sentence look like a requirement.
_MODAL = re.compile(
    r"(?<!\w)(must|shall|should|will|can|повин\w*|має|мають|може|можуть|"
    r"долж\w*|может|могут|необхідно|необходимо|потрібно|нужно)(?!\w)",
    re.IGNORECASE,
)


def _clean(line: str) -> str:
    """Remove markdown bold markers; keep the wording itself unchanged."""
    return line.replace("**", "")


def _prefix(req_id: str) -> str:
    """Letter part of an ID: "FR-AUTH-01" -> "FR-AUTH"."""
    match = re.match(_PREFIX, req_id)
    return match.group(0) if match else req_id


def _id_prefix_counts(lines: list[str]) -> Counter[str]:
    """Count how often each ID prefix (e.g. "REQ") starts a line."""
    counts: Counter[str] = Counter()
    for line in lines:
        line = _clean(line)
        if heading := _HEADING.match(line):
            line = heading.group("title")
        if match := _ID_LINE.match(line):
            groups = match.groupdict()
            counts[_prefix(groups["bracket_id"] or groups["id"] or groups["plain_id"])] += 1
    return counts


def _match_id_line(line: str, prefix_counts: Counter[str]) -> tuple[str, str] | None:
    """Return (id, text) if the line starts with a requirement ID."""
    match = _ID_LINE.match(line)
    if not match:
        return None
    groups = match.groupdict()
    if groups["plain_id"]:
        # Without a separator, "UTF-8 encoding ..." or "SHA-256 hashing ..."
        # look like IDs. Only trust the form when the prefix repeats.
        if prefix_counts[_prefix(groups["plain_id"])] < 2:
            return None
        return groups["plain_id"], match.group("text").strip()
    return groups["bracket_id"] or groups["id"], match.group("text").strip()


def _table_row(line: str) -> tuple[str, str] | None:
    """Return (id, text) for rows like '| REQ-1 | text |'."""
    if not line.lstrip().startswith("|") or _TABLE_DIVIDER.match(line):
        return None
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) >= 2 and _ID_ONLY.match(cells[0]):
        # Extra columns such as Priority are short; the description is
        # the longest remaining cell.
        text = max(cells[1:], key=len)
        if text:
            return cells[0].strip("[]"), text
    return None


def extract_requirements(text: str) -> list[Requirement]:
    """Split a document into requirement statements.

    Supported formats: lines with explicit IDs (REQ-1: ...), markdown
    headings with IDs, markdown tables with an ID column, bullet/numbered
    lists, and plain sentences. Requirements without an ID get one like
    REQ-001.
    """
    lines = validate_text(text).split("\n")
    prefix_counts = _id_prefix_counts(lines)

    # Each item: [explicit_id or None, text, line_number]
    items: list[list] = []
    free_sentences: list[tuple[str, int]] = []
    paragraph: list[str] = []
    paragraph_start = 0
    current: int | None = None  # index of item that may continue on next line
    current_is_section = False  # heading items continue across blank lines

    def flush_paragraph() -> None:
        if paragraph:
            joined = " ".join(paragraph)
            for sentence in _SENTENCE_SPLIT.split(joined):
                free_sentences.append((sentence.strip(), paragraph_start))
            paragraph.clear()

    def start_item(explicit_id: str | None, item_text: str, number: int) -> None:
        nonlocal current, current_is_section
        flush_paragraph()
        items.append([explicit_id, item_text, number])
        current = len(items) - 1
        current_is_section = False

    for number, raw_line in enumerate(lines, start=1):
        line = _clean(raw_line)
        stripped = line.strip()

        if not stripped and current is not None and (current_is_section or not items[current][1]):
            continue  # description may follow after a blank line
        if heading := _HEADING.match(line):
            if found := _match_id_line(heading.group("title"), prefix_counts):
                start_item(*found, number)
                current_is_section = True
                continue
        if not stripped or heading or _SEPARATOR.match(line):
            flush_paragraph()
            current = None
            continue

        if row := _table_row(line):
            start_item(*row, number)
            current = None
            continue
        if line.lstrip().startswith("|"):
            current = None  # table header or divider
            continue

        if found := _match_id_line(line, prefix_counts):
            start_item(*found, number)
            continue
        if match := _LIST_ITEM.match(line):
            start_item(None, match.group("text").strip(), number)
            continue

        if current is not None:
            # A plain line right after a list item continues that item.
            items[current][1] = f"{items[current][1]} {stripped}".strip()
            continue

        if not paragraph:
            paragraph_start = number
        paragraph.append(stripped)

    flush_paragraph()

    # In structured documents, free text is usually intro or context, so only
    # keep sentences that read like requirements.
    structured = bool(items)
    for sentence, number in free_sentences:
        if not structured or _MODAL.search(sentence):
            items.append([None, sentence, number])
    items.sort(key=lambda item: item[2])

    items = [item for item in items if len(item[1]) >= MIN_REQUIREMENT_CHARS]
    if len(items) > MAX_REQUIREMENTS:
        raise InputError("too_many_requirements", max_count=MAX_REQUIREMENTS)
    if not items:
        raise InputError("no_requirements_found")

    return _build_requirements(items)


def _build_requirements(items: list[list]) -> list[Requirement]:
    used_ids = {item[0].upper() for item in items if item[0]}
    seen: set[str] = set()
    auto_number = 0
    requirements: list[Requirement] = []

    for explicit_id, text, number in items:
        if explicit_id:
            req_id = explicit_id.upper()
            suffix = 2
            while req_id in seen or (req_id != explicit_id.upper() and req_id in used_ids):
                # duplicate explicit IDs get a suffix that is not used elsewhere
                req_id = f"{explicit_id.upper()}-{suffix}"
                suffix += 1
        else:
            auto_number += 1
            req_id = f"REQ-{auto_number:03d}"
            while req_id in used_ids or req_id in seen:
                auto_number += 1
                req_id = f"REQ-{auto_number:03d}"
        seen.add(req_id)
        requirements.append(
            Requirement(
                id=req_id,
                text=text,
                language=detect_language(text),
                source_line=number,
                has_explicit_id=explicit_id is not None,
            )
        )
    return requirements
