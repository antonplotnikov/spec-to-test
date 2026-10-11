"""Regression tests: findings must reference the correct original requirement ID.

Bug: lines like "REQ-013 text" (no separator) were not recognized as IDs, so
generated IDs were used instead. One multi-sentence requirement shifted every
later ID by one (findings for REQ-013 appeared under REQ-014). ID-only lines
("REQ-020:") were also merged into the previous requirement.
"""

import pytest

from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import FindingType
from spec_to_test.rule_engine import analyze_requirements


def sequential_document(separator: str = " ") -> str:
    lines = [f"REQ-{n:03d}{separator}The system must save record {n}." for n in range(1, 23)]
    lines[4] = f"REQ-005{separator}The system must log in the user. A session is created."
    lines[12] = f"REQ-013{separator}Response time should be reasonable."
    lines[19] = f"REQ-020{separator}The search must respond quickly for many users."
    return "\n".join(lines)


def ambiguous_by_requirement(text: str) -> dict[str, list[str]]:
    result = analyze_requirements(extract_requirements(text))
    return {
        f.requirement_id: f.matched_terms
        for f in result.findings
        if f.type == FindingType.AMBIGUOUS_WORDING
    }


# --- Sequential IDs ----------------------------------------------------------

@pytest.mark.parametrize("separator", [" ", ": ", ". ", " - ", " — "])
def test_sequential_ids_are_kept_for_every_separator(separator):
    reqs = extract_requirements(sequential_document(separator))
    assert [r.id for r in reqs] == [f"REQ-{n:03d}" for n in range(1, 23)]
    assert all(r.has_explicit_id for r in reqs)


def test_multi_sentence_requirement_does_not_shift_later_ids():
    reqs = {r.id: r.text for r in extract_requirements(sequential_document())}
    assert reqs["REQ-005"] == "The system must log in the user. A session is created."
    assert reqs["REQ-013"] == "Response time should be reasonable."
    assert reqs["REQ-020"] == "The search must respond quickly for many users."


def test_findings_reference_original_ids_in_sequential_document():
    ambiguous = ambiguous_by_requirement(sequential_document())
    assert ambiguous == {"REQ-013": ["reasonable"], "REQ-020": ["quickly", "many"]}


def test_mixed_id_formats_in_one_document():
    reqs = extract_requirements(
        "REQ-1: First requirement text.\n"
        "REQ-2 - Second requirement text.\n"
        "REQ-3 Third requirement text.\n"
        "[REQ-4] Fourth requirement text.\n"
        "- REQ-5 Fifth requirement text."
    )
    assert [r.id for r in reqs] == ["REQ-1", "REQ-2", "REQ-3", "REQ-4", "REQ-5"]
    assert [r.text.split()[0] for r in reqs] == ["First", "Second", "Third", "Fourth", "Fifth"]


def test_contradiction_links_use_original_ids():
    result = analyze_requirements(
        extract_requirements(
            "REQ-010 The password must be at least 8 characters.\n"
            "REQ-011 The user must confirm the email. A link is sent.\n"
            "REQ-012 The password must be at least 10 characters."
        )
    )
    links = {
        f.requirement_id: f.related_requirement_ids
        for f in result.findings
        if f.type == FindingType.CONTRADICTION
    }
    assert links == {"REQ-010": ["REQ-012"], "REQ-012": ["REQ-010"]}


# --- Missing requirement descriptions ----------------------------------------

def test_id_without_description_is_not_merged_into_previous_requirement():
    reqs = extract_requirements(
        "REQ-019: The system must save the draft.\n"
        "REQ-020:\n"
        "REQ-021: The search must respond quickly for many users."
    )
    texts = {r.id: r.text for r in reqs}
    assert texts["REQ-019"] == "The system must save the draft."
    assert texts["REQ-021"] == "The search must respond quickly for many users."
    assert "REQ-020" not in texts  # nothing to analyze


def test_id_without_description_at_end_of_document():
    reqs = extract_requirements("REQ-1: The system must save the draft.\nREQ-2")
    assert [(r.id, r.text) for r in reqs] == [("REQ-1", "The system must save the draft.")]


def test_findings_skip_over_id_without_description():
    ambiguous = ambiguous_by_requirement(
        "REQ-019: The system must save the draft quickly.\n"
        "REQ-020:\n"
        "REQ-021: The page must be user-friendly."
    )
    assert ambiguous == {"REQ-019": ["quickly"], "REQ-021": ["user-friendly"]}


@pytest.mark.parametrize("gap", ["\n", "\n\n"])
def test_description_on_line_after_id(gap):
    reqs = extract_requirements(
        f"REQ-013{gap}Response time should be reasonable.\n\n"
        f"REQ-014:{gap}The system must display the dashboard."
    )
    assert [(r.id, r.text) for r in reqs] == [
        ("REQ-013", "Response time should be reasonable."),
        ("REQ-014", "The system must display the dashboard."),
    ]


# --- Findings near requirement boundaries ------------------------------------

def test_terms_at_end_and_start_of_adjacent_requirements():
    ambiguous = ambiguous_by_requirement(
        "REQ-1: The page must load fast\nREQ-2: Many users must be supported at once."
    )
    assert ambiguous == {"REQ-1": ["fast"], "REQ-2": ["Many"]}


def test_term_on_continuation_line_belongs_to_its_requirement():
    ambiguous = ambiguous_by_requirement(
        "REQ-1: The system must send a confirmation email\n"
        "  as soon as possible.\n"
        "REQ-2: The system must display the order total."
    )
    assert ambiguous == {"REQ-1": ["as soon as possible"]}


def test_every_finding_references_an_existing_requirement():
    result = analyze_requirements(extract_requirements(sequential_document()))
    ids = {r.id for r in result.requirements}
    for finding in result.findings:
        assert finding.requirement_id in ids
        assert set(finding.related_requirement_ids) <= ids


def test_uppercase_word_with_digit_is_still_not_an_id():
    reqs = extract_requirements(
        "REQ-1 Audio must play.\nREQ-2 Video must play.\nMP3 files must be playable."
    )
    assert [r.id for r in reqs] == ["REQ-1", "REQ-2"]
    assert reqs[1].text == "Video must play. MP3 files must be playable."
