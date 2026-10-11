"""Analysis quality against a reference specification with known findings.

Expected findings were written from the requirement wording, not copied from
program output. Clear requirements must produce no findings (false-positive
check); flawed ones must produce exactly the listed finding types.
"""

import pytest

from conftest import PROJECT_ROOT
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import FindingType as F
from spec_to_test.rule_engine import analyze_requirements

SPEC_PATH = PROJECT_ROOT / "tests" / "fixtures" / "reference_spec.md"

EXPECTED: dict[str, set[F]] = {
    # Clear requirements: concrete behavior, limits and error rules.
    "REF-01": set(),
    "REF-02": set(),
    "REF-03": set(),
    "REF-04": set(),
    "REF-05": set(),
    "REF-06": set(),
    "REF-15": set(),
    "REF-18": set(),
    # Flawed requirements.
    "REF-07": {F.AMBIGUOUS_WORDING},
    "REF-08": {F.MISSING_EXPECTED_RESULT},
    "REF-09": {F.MISSING_BOUNDARY},
    "REF-10": {F.MISSING_EXPECTED_RESULT, F.MISSING_ERROR_HANDLING},
    "REF-11": {F.CONTRADICTION},
    "REF-12": {F.CONTRADICTION},
    "REF-13": {F.CONTRADICTION, F.MISSING_EXPECTED_RESULT},
    "REF-14": {F.CONTRADICTION},
    "REF-16": {F.AMBIGUOUS_WORDING},
    "REF-17": {F.MISSING_EXPECTED_RESULT, F.MISSING_ERROR_HANDLING},
    "REF-19": {F.MISSING_BOUNDARY, F.MISSING_EXPECTED_RESULT},
    "REF-20": {F.MISSING_EXPECTED_RESULT, F.MISSING_ERROR_HANDLING},
}
CONTRADICTION_PAIRS = {"REF-11": "REF-12", "REF-12": "REF-11", "REF-13": "REF-14", "REF-14": "REF-13"}


@pytest.fixture(scope="module")
def result():
    return analyze_requirements(extract_requirements(SPEC_PATH.read_text(encoding="utf-8")))


def found_types(result) -> dict[str, set[F]]:
    found: dict[str, set[F]] = {req.id: set() for req in result.requirements}
    for finding in result.findings:
        found[finding.requirement_id].add(finding.type)
    return found


def test_all_reference_requirements_are_extracted_with_their_ids(result):
    assert [r.id for r in result.requirements] == sorted(EXPECTED)


@pytest.mark.parametrize("req_id", sorted(EXPECTED))
def test_expected_findings_per_requirement(result, req_id):
    assert found_types(result)[req_id] == EXPECTED[req_id]


def test_clear_requirements_have_no_false_positives(result):
    clear = [req_id for req_id, kinds in EXPECTED.items() if not kinds]
    found = found_types(result)
    assert {req_id: found[req_id] for req_id in clear} == {req_id: set() for req_id in clear}


def test_precision_and_recall_are_perfect_on_reference(result):
    expected = {(req_id, kind) for req_id, kinds in EXPECTED.items() for kind in kinds}
    found = {(f.requirement_id, f.type) for f in result.findings}
    true_positives = expected & found
    assert len(true_positives) / len(found) == 1.0  # precision
    assert len(true_positives) / len(expected) == 1.0  # recall


def test_contradictions_point_to_the_conflicting_requirement(result):
    links = {
        f.requirement_id: f.related_requirement_ids
        for f in result.findings
        if f.type == F.CONTRADICTION
    }
    assert links == {req_id: [other] for req_id, other in CONTRADICTION_PAIRS.items()}


def test_every_finding_references_an_extracted_requirement(result):
    ids = {r.id for r in result.requirements}
    texts = {r.id: r.text for r in result.requirements}
    for finding in result.findings:
        assert finding.requirement_id in ids
        # Matched terms must come from that requirement's own text.
        if finding.type != F.CONTRADICTION:
            for term in finding.matched_terms:
                assert term in texts[finding.requirement_id]
