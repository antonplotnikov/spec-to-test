from spec_to_test.bug_reports import generate_defects, next_defect_id
from spec_to_test.input_parser import extract_requirements
from spec_to_test.models import ClarificationStatus, Severity, Source, Workspace
from spec_to_test.rule_engine import analyze_requirements


def make_workspace(text: str) -> Workspace:
    result = analyze_requirements(extract_requirements(text))
    return Workspace(requirements=result.requirements, findings=result.findings)


def test_one_report_per_open_finding_with_required_fields(example_text):
    ws = make_workspace(example_text)
    defects = generate_defects(ws)
    contradictions = [f for f in ws.findings if f.type.value == "contradiction"]
    assert len(defects) == len(ws.findings) - len(contradictions) // 2
    for d in defects:
        assert d.id.startswith("BUG-")
        assert d.requirement_id in {r.id for r in ws.requirements}
        assert d.title and d.description and d.expected_behavior and d.reproduction_context
        assert d.source == Source.RULE
    assert [d.id for d in defects][:2] == ["BUG-001", "BUG-002"]


def test_contradiction_report_mentions_both_requirements(example_text):
    ws = make_workspace(example_text)
    report = next(d for d in generate_defects(ws) if "contradict" in d.description)
    assert "REQ-4" in report.reproduction_context and "REQ-7" in report.reproduction_context
    assert report.severity == Severity.HIGH


def test_context_contains_source_line_and_quote():
    ws = make_workspace("REQ-1: The page should load fast.")
    [report] = generate_defects(ws)
    assert "The page should load fast." in report.reproduction_context
    assert '"fast"' in report.reproduction_context
    assert "line" in report.reproduction_context.lower()


def test_generation_does_not_duplicate_or_overwrite_edits(example_text):
    ws = make_workspace(example_text)
    ws.defects = generate_defects(ws)
    ws.defects[0].title = "Edited by me"
    assert generate_defects(ws) == []
    assert ws.defects[0].title == "Edited by me"


def test_resolved_findings_are_skipped():
    ws = make_workspace("REQ-1: The page should load fast.")
    ws.findings[0].status = ClarificationStatus.RESOLVED
    assert generate_defects(ws) == []


def test_reports_are_localized():
    ws = make_workspace("REQ-1: The page should load fast.")
    [report] = generate_defects(ws, "ru")
    assert "Неоднозначная формулировка" in report.title


def test_next_defect_id():
    ws = make_workspace("REQ-1: The page should load fast.")
    assert next_defect_id(generate_defects(ws)) == "BUG-002"
