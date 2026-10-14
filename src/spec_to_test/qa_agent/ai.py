"""Optional: ask the configured LLM to propose executable steps for one plan case.

The model returns steps as data (action, target, value) in a fixed schema;
each step is validated by the same rules as hand-written steps, and the case
must still be reviewed and approved by a person before it can run. Nothing
the model returns is executed as code. The model sees the requirement, the
test case text, the target URL and the names (never the values) of the
configured secrets; it sees no page content.
"""

from pydantic import BaseModel, Field, ValidationError

from spec_to_test.llm.config import AIConfig
from spec_to_test.llm.providers import AIError, ClientFactory, default_client_factory, request_structured
from spec_to_test.qa_agent.models import PlanCase, PlanStep, StepAction
from spec_to_test.qa_agent.steps import StepError, format_steps, validate_step

MAX_AI_STEPS = 30


class _Step(BaseModel):
    action: str
    target: str = ""
    value: str = ""


class StepSuggestion(BaseModel):
    steps: list[_Step] = Field(default_factory=list)


SYSTEM = f"""You turn a manual web test case into steps for a fixed browser test interpreter.
Return JSON only. Each step has: action, target, value.
Actions: {", ".join(a.value for a in StepAction)}.
- goto/expect_url: value is a path starting with "/" on the target site. expect_title: value is title text.
- fill/select/expect_value: target is a locator, value is the text/option.
- click/check/uncheck/wait_for/expect_visible/expect_hidden: target is a locator, value is "".
- expect_text/expect_no_text: value is visible text; target optional.
- press: value is a key name such as Enter.
Locators: label=<field label>, role=<role>[name=<accessible name>], text=<text>, placeholder=<text>, testid=<id>.
To type a configured secret use value {{{{secret:NAME}}}} with one of the given secret names.
Use only information in the test case; do not invent URLs, fields or texts it does not mention.
End with at least one expect_* check that verifies the expected result. At most {MAX_AI_STEPS} steps."""


def suggest_steps(
    config: AIConfig,
    case: PlanCase,
    requirement_text: str,
    source_steps: list[str],
    target_url: str,
    secret_names: list[str],
    client_factory: ClientFactory = default_client_factory,
) -> list[PlanStep]:
    """Validated steps. Raises AIError when the request fails or any returned step is invalid.

    One invalid step rejects the whole suggestion: dropping or repairing it
    would silently change the test the model described.
    """
    user = (
        f"Target site: {target_url or '(not set)'}\n"
        f"Secret names: {', '.join(secret_names) or '(none)'}\n"
        f"Requirement {case.requirement_id}: {requirement_text}\n"
        f"Test case: {case.title}\n"
        "Written steps:\n" + "\n".join(f"- {s}" for s in source_steps or case.unparsed or ["(none)"]) + "\n"
        f"Expected result: {case.expected_result or '(none)'}\n"
        f"Current steps:\n{format_steps(case.steps) or '(none)'}"
    )
    suggestion = request_structured(config, SYSTEM, user, StepSuggestion, client_factory, max_tokens=4000)
    steps: list[PlanStep] = []
    for raw in suggestion.steps[:MAX_AI_STEPS]:
        try:
            step = PlanStep(action=StepAction(raw.action.strip().lower()), target=raw.target.strip(),
                            value=raw.value.strip())
            validate_step(step)
        except (ValueError, ValidationError, StepError):
            raise AIError("invalid_response") from None
        steps.append(step)
    if not steps:
        raise AIError("invalid_response")
    return steps
