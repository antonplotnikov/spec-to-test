"""Evaluation cases: a requirements document, gold labels, a scripted author and scripted model replies.

A case file (JSON, see fixtures/) holds:
- `requirements`: the document text (parsed with the app's own input parser);
- `gold.issues`: what a good interviewer must ask about, judged by a person:
  the requirement(s) concerned, acceptable question categories (rule finding
  types, "contradiction", "clarity", "boundary") and keywords any acceptable
  question would contain;
- `gold.contradictions`: requirement pairs that really contradict each other;
  `gold.non_contradictions`: pairs that look alike but must not be flagged
  (another scope or condition, equal values in other units, other currencies);
- `gold.must_not_ask`: questions a good interviewer would not ask (same shape
  as an issue): asking one is a false positive;
- `settled`: rule questions whose findings were already resolved before the
  interview (they must not be asked again);
- `steps`: finding status changes in the document during the interview
  (after N answers, resolve or reopen rule questions), to test the reactive queue;
- `answers`: how the scripted author answers, by question ID or by a phrase in
  the question; anything else is answered "unknown" (the author never invents);
- `ai`: the scripted model replies, in call order, per request type
  ("interview", "questions", "review", "test_cases"). A reply may be
  {"error": "<code>"} to simulate an API failure. Live runs ignore `ai`.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from spec_to_test.grill.models import AnswerStatus

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class GoldIssue(BaseModel):
    requirement_ids: list[str] = Field(min_length=1)
    # Question categories that address the issue (grill.insights.question_category values).
    topics: list[str] = Field(default_factory=list)
    # Lower-case phrases; a question containing one addresses the issue.
    keywords: list[str] = Field(default_factory=list)
    note: str = ""


class Gold(BaseModel):
    issues: list[GoldIssue] = Field(default_factory=list)
    contradictions: list[list[str]] = Field(default_factory=list)
    non_contradictions: list[list[str]] = Field(default_factory=list)
    must_not_ask: list[GoldIssue] = Field(default_factory=list)


class Step(BaseModel):
    """A finding status change in the analyzed document, after `after` answers."""

    after: int = Field(ge=0)
    resolve: list[str] = Field(default_factory=list)
    reopen: list[str] = Field(default_factory=list)


class ScriptedAnswer(BaseModel):
    status: AnswerStatus = AnswerStatus.UNKNOWN
    value: str = ""
    # Matched against the question text (lower case) when no ID entry applies.
    contains: str = ""


class EvalCase(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    language: str = "en"
    requirements: str = Field(min_length=1)
    gold: Gold = Field(default_factory=Gold)
    settled: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    # Question ID -> answer.
    answers: dict[str, ScriptedAnswer] = Field(default_factory=dict)
    # Answers chosen by a phrase in the question (checked in order).
    answers_by_text: list[ScriptedAnswer] = Field(default_factory=list)
    ai: dict[str, list[dict]] = Field(default_factory=dict)

    def answer_for(self, question_id: str, prompt: str) -> ScriptedAnswer:
        if question_id in self.answers:
            return self.answers[question_id]
        text = prompt.casefold()
        for answer in self.answers_by_text:
            if answer.contains and answer.contains.casefold() in text:
                return answer
        return ScriptedAnswer()


def load_cases(directory: Path = FIXTURES_DIR) -> list[EvalCase]:
    """Every case in the folder, by file name (deterministic order)."""
    return [
        EvalCase.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]
