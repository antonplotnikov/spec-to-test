"""The four quality dimensions summarize the existing criteria without changing the score."""

from spec_to_test.models import Requirement
from spec_to_test.quality import CRITERIA, DIMENSIONS, average_score, dimension_scores, grade_of, score_all
from spec_to_test.rule_engine import analyze_requirements

REQS = [
    Requirement(id="REQ-1", text="The page should load fast.", has_explicit_id=True),
    Requirement(id="REQ-2", text="The system must send a reset link to the registered email address.", has_explicit_id=True),
]


def scores():
    result = analyze_requirements(REQS)
    return score_all(result.requirements, result.findings)


def test_every_criterion_is_in_exactly_one_dimension():
    criteria = [c for group in DIMENSIONS.values() for c in group]
    assert sorted(criteria) == sorted(CRITERIA) and len(criteria) == len(set(criteria))


def test_dimension_points_add_up_to_the_scores():
    values = list(scores().values())
    dims = dimension_scores(values)
    assert [d.key for d in dims] == ["clarity", "completeness", "testability", "consistency"]
    assert sum(d.points for d in dims) == sum(s.score for s in values)
    assert sum(d.max_points for d in dims) == 100 * len(values)


def test_vague_wording_lowers_clarity_only_where_found():
    by_id = scores()
    clarity = {rid: dimension_scores([s])[0] for rid, s in by_id.items()}
    assert clarity["REQ-1"].percent < 100
    assert clarity["REQ-2"].percent == 100


def test_average_and_grade():
    values = list(scores().values())
    assert average_score(values) == round(sum(s.score for s in values) / 2)
    assert average_score([]) is None
    assert dimension_scores([])[0].percent == 0
    assert (grade_of(80), grade_of(79), grade_of(50), grade_of(49)) == ("good", "fair", "fair", "poor")
