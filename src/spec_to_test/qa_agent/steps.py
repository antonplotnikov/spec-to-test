"""The step language of QA Agent plans: one declarative step per line.

    goto /login
    fill label=Email | demo@example.com
    fill label=Password | {{secret:DEMO_PASSWORD}}
    click role=button[name=Sign in]
    expect_text Welcome, Demo User
    expect_url /dashboard

Steps are data. The executor maps each action to one fixed Playwright call;
nothing in a plan is ever evaluated as code.

Locators: label=, text=, placeholder=, testid=, role=<role>[name=<name>],
css=<selector>; anything else is a CSS selector.

`steps_from_test_case` turns concrete, human-written test steps ("Enter
"demo@example.com" in the "Email" field", "Click the "Sign in" button") into
steps. A step it cannot read is reported as unparsed, never guessed.
"""

import re
from dataclasses import dataclass

from pydantic import ValidationError

from spec_to_test.qa_agent.models import (
    MAX_TARGET,
    OPTIONAL_TARGET,
    TARGET_AND_VALUE,
    TARGET_ONLY,
    VALUE_ONLY,
    PlanStep,
    StepAction,
)

SECRET = re.compile(r"^\{\{secret:([A-Z][A-Z0-9_]{0,63})\}\}$")
KEY_NAME = re.compile(r"^[A-Za-z0-9]+(\+[A-Za-z0-9]+)*$")
ROLE = re.compile(r"^role=([a-z]+)(?:\[name=(?:\"([^\"]*)\"|'([^']*)'|([^\]]*))\])?$")
LOCATOR_KINDS = ("label", "text", "placeholder", "testid", "css")
# ARIA roles Playwright's get_by_role accepts that make sense in a test step.
ROLES = frozenset({
    "alert", "alertdialog", "button", "checkbox", "combobox", "dialog", "heading", "img", "link", "list",
    "listitem", "menu", "menuitem", "navigation", "option", "progressbar", "radio", "row", "searchbox",
    "slider", "spinbutton", "status", "switch", "tab", "table", "tabpanel", "textbox", "main", "form",
    "banner", "region", "cell", "columnheader", "grid", "group", "tooltip", "tree", "treeitem",
})
MAX_STEPS_TEXT = 20_000
# `fill <target> | {{empty}}` clears a field (a step value cannot be blank).
EMPTY = "{{empty}}"
KEYS = {k.lower(): k for k in ("Enter", "Tab", "Escape", "Space", "ArrowDown", "ArrowUp")}


class StepError(ValueError):
    """A line that is not a valid step. `code` maps to qaagent.step_error.<code>."""

    def __init__(self, code: str, line: int = 0, text: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.line = line
        self.text = text


@dataclass(frozen=True)
class Locator:
    kind: str  # label | text | placeholder | testid | css | role
    value: str
    name: str = ""  # accessible name, for role locators


def parse_locator(target: str) -> Locator:
    target = target.strip()
    if not target or len(target) > MAX_TARGET:
        raise StepError("target")
    if target.startswith("role="):
        match = ROLE.match(target)
        if not match or match.group(1) not in ROLES:
            raise StepError("role")
        name = next((g for g in match.groups()[1:] if g is not None), "")
        return Locator("role", match.group(1), name.strip())
    kind, sep, value = target.partition("=")
    if sep and kind in LOCATOR_KINDS:
        if not value.strip():
            raise StepError("target")
        return Locator(kind, value.strip())
    return Locator("css", target)


def secret_name(value: str) -> str | None:
    match = SECRET.match(value.strip())
    return match.group(1) if match else None


def validate_step(step: PlanStep) -> None:
    """Raise StepError when the step lacks what its action needs."""
    action, target, value = step.action, step.target.strip(), step.value
    if action in VALUE_ONLY:
        if not value.strip() or target:
            raise StepError("value")
    elif action in TARGET_ONLY:
        if not target or value:
            raise StepError("target")
    elif action in TARGET_AND_VALUE:
        if not target or not value:
            raise StepError("target_value")
    elif action in OPTIONAL_TARGET and not value:
        raise StepError("value")
    if target:
        parse_locator(target)
    if action == StepAction.PRESS and not KEY_NAME.match(value.strip()):
        raise StepError("key")
    if "{{secret:" in value and (action != StepAction.FILL or secret_name(value) is None):
        raise StepError("secret")


def parse_line(line: str, number: int = 0) -> PlanStep | None:
    """One step, or None for a blank/comment line."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    word, _, rest = text.partition(" ")
    try:
        action = StepAction(word.lower())
    except ValueError:
        raise StepError("action", number, text) from None
    rest = rest.strip()
    target, value = "", ""
    if action in VALUE_ONLY:
        value = rest
    elif action in TARGET_ONLY:
        target = rest
    elif " | " in rest:
        target, _, value = rest.partition(" | ")
    elif action in TARGET_AND_VALUE:
        raise StepError("target_value", number, text)
    else:
        value = rest
    try:
        step = PlanStep(action=action, target=target.strip(), value=value.strip())
        validate_step(step)
    except StepError as error:
        raise StepError(error.code, number, text) from None
    except ValidationError:
        raise StepError("too_long", number, text) from None
    return step


def parse_steps(text: str) -> list[PlanStep]:
    """Every step of a text block; raises StepError for the first invalid line."""
    if len(text) > MAX_STEPS_TEXT:
        raise StepError("too_long")
    steps = []
    for number, line in enumerate(text.splitlines(), start=1):
        if (step := parse_line(line, number)) is not None:
            steps.append(step)
    return steps


def format_step(step: PlanStep) -> str:
    action = step.action.value
    if step.action in VALUE_ONLY:
        return f"{action} {step.value}"
    if step.action in TARGET_ONLY:
        return f"{action} {step.target}"
    if step.target:
        return f"{action} {step.target} | {step.value}"
    return f"{action} {step.value}"


def format_steps(steps: list[PlanStep]) -> str:
    return "\n".join(format_step(s) for s in steps)


def shown_value(value: str) -> str:
    """The value as it may be displayed: secrets by name only."""
    name = secret_name(value)
    return f"[secret:{name}]" if name else value


def describe_locator(target: str) -> str:
    try:
        loc = parse_locator(target)
    except StepError:
        return target
    if loc.kind == "role":
        return f"{loc.value} \"{loc.name}\"" if loc.name else loc.value
    if loc.kind == "css":
        return loc.value
    return f"\"{loc.value}\""


# ---------------------------------------------------------------------------
# Natural-language test steps -> plan steps (deterministic, English)
# ---------------------------------------------------------------------------

_Q = r"[\"“”'‘’«»]"  # any quote mark
_QUOTED = rf"{_Q}(?P<{{name}}>[^\"“”'‘’«»]+){_Q}"


def _quoted(name: str) -> str:
    return _QUOTED.format(name=name)


_URL = r"(?P<url>(?:https?://\S+|/\S*))"
_FIELD = rf"(?:the\s+)?(?:{_quoted('field')}|(?P<bare>[A-Za-z][\w -]{{0,40}}?))(?:\s+(?:field|input|box|textbox|text box))?"
_NL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"^(?:open|go to|navigate to|visit|load)\s+(?:the\s+)?(?:page\s+|url\s+)?{_Q}?{_URL}{_Q}?(?:\s+page)?$", re.I), "goto"),
    (re.compile(rf"^(?:enter|type|input|fill in|fill)\s+{_quoted('value')}\s+(?:in|into)\s+{_FIELD}$", re.I), "fill"),
    (re.compile(rf"^(?:fill in|fill|set)\s+{_FIELD}\s+(?:with|to)\s+{_quoted('value')}$", re.I), "fill"),
    (re.compile(rf"^(?:leave|keep)\s+{_FIELD}\s+empty$", re.I), "clear"),
    (re.compile(rf"^(?:select|choose|pick)\s+{_quoted('value')}\s+(?:in|from)\s+{_FIELD}(?:\s+(?:list|dropdown|menu))?$", re.I), "select"),
    (re.compile(rf"^(?:check|tick|enable)\s+{_FIELD}(?:\s+checkbox)?$", re.I), "check"),
    (re.compile(rf"^(?:uncheck|untick|disable)\s+{_FIELD}(?:\s+checkbox)?$", re.I), "uncheck"),
    (re.compile(rf"^press\s+(?:the\s+)?{_Q}?(?P<key>Enter|Tab|Escape|Space|ArrowDown|ArrowUp)\b{_Q}?(?:\s+key)?$", re.I), "press"),
    (re.compile(rf"^(?:click|press|tap|submit)\s+(?:on\s+)?(?:the\s+)?{_quoted('name')}(?:\s+(?P<kind>button|link|tab|checkbox))?$", re.I), "click"),
    (re.compile(rf"^(?:click|press|tap)\s+(?:on\s+)?(?:the\s+)?(?P<kind>button|link)\s+{_quoted('name')}$", re.I), "click"),
]
_EXPECT_URL = re.compile(rf"(?:redirected to|navigates? to|lands? on|url (?:is|becomes|contains)|taken to|opens?)\s+(?:the\s+)?{_Q}?(?P<url>/[^\s\"“”'‘’«».,;]*){_Q}?", re.I)
_EXPECT_TITLE = re.compile(rf"(?:page\s+)?title\s+(?:is|becomes|equals|contains)\s+{_quoted('text')}", re.I)
_NEGATED = re.compile(r"\b(?:not|no|never|without|doesn't|does not|isn't|is not)\b[^\"“”'‘’«»]*$", re.I)
_QUOTE_ANY = re.compile(_quoted("text"))


def _field_target(match: re.Match[str]) -> str:
    field = (match.group("field") or match.group("bare") or "").strip()
    return f"label={field}" if field else ""


def _looks_like_dsl(text: str) -> bool:
    """A line in the step language: lower-case action word and, when it names an element, an explicit locator.

    "Click Save" is an English sentence, not `click` on the CSS selector "Save".
    """
    word, _, rest = text.partition(" ")
    if word not in StepAction._value2member_map_:
        return False
    action = StepAction(word)
    if action in VALUE_ONLY:
        return True
    target = rest.partition(" | ")[0].strip() if action not in TARGET_ONLY else rest.strip()
    if action in OPTIONAL_TARGET and " | " not in rest:
        return True
    return target.startswith(("#", ".", "[", "role=", *(f"{k}=" for k in LOCATOR_KINDS)))


def step_from_sentence(sentence: str) -> list[PlanStep] | None:
    """Steps for one written test step, or None when it is not understood."""
    text = sentence.strip().rstrip(".;").strip()
    text = re.sub(r"^\d+[.)]\s*", "", text)
    if not text:
        return []
    if _looks_like_dsl(text):
        try:  # already written in the step language
            step = parse_line(text)
            return [step] if step else []
        except StepError:
            pass
    for pattern, kind in _NL_RULES:
        if not (match := pattern.match(text)):
            continue
        groups = match.groupdict()
        if kind == "goto":
            return [PlanStep(action=StepAction.GOTO, value=groups["url"])]
        if kind == "fill":
            return [PlanStep(action=StepAction.FILL, target=_field_target(match), value=groups["value"])]
        if kind == "clear":
            # "Leave Email empty" = make sure the field is empty, so a later submit sends nothing.
            return [PlanStep(action=StepAction.FILL, target=_field_target(match), value="{{empty}}")]
        if kind == "select":
            return [PlanStep(action=StepAction.SELECT, target=_field_target(match), value=groups["value"])]
        if kind in ("check", "uncheck"):
            return [PlanStep(action=StepAction(kind), target=_field_target(match))]
        if kind == "press":
            return [PlanStep(action=StepAction.PRESS, value=KEYS[groups["key"].lower()])]
        if kind == "click":
            role = (groups.get("kind") or "").lower()
            name = groups["name"]
            target = f"role={role}[name={name}]" if role in ("button", "link", "tab", "checkbox") else f"text={name}"
            return [PlanStep(action=StepAction.CLICK, target=target)]
    return None


def assertions_from_expected(expected: str) -> list[PlanStep]:
    """Checks for an expected result: quoted text shown (or not), URL and title. May be empty."""
    steps: list[PlanStep] = []
    for sentence in re.split(r"(?<=[.;])\s+|\n", expected):
        if not sentence.strip():
            continue
        if match := _EXPECT_TITLE.search(sentence):
            steps.append(PlanStep(action=StepAction.EXPECT_TITLE, value=match.group("text")))
            sentence = sentence.replace(match.group(0), " ")
        if match := _EXPECT_URL.search(sentence):
            steps.append(PlanStep(action=StepAction.EXPECT_URL, value=match.group("url")))
        for quoted in _QUOTE_ANY.finditer(sentence):
            before = sentence[: quoted.start()]
            negated = bool(_NEGATED.search(before))
            action = StepAction.EXPECT_NO_TEXT if negated else StepAction.EXPECT_TEXT
            steps.append(PlanStep(action=action, value=quoted.group("text")))
    return steps


@dataclass
class Conversion:
    steps: list[PlanStep]
    unparsed: list[str]


def steps_from_test_case(preconditions: list[str], steps: list[str], expected_result: str) -> Conversion:
    """Executable steps for a written test case. Any unreadable step empties the result.

    A partly converted case would run a different test than the one written,
    so the case is kept without steps and the unreadable text is reported.
    Preconditions that are not steps (e.g. "A user account exists") are ignored.
    """
    result: list[PlanStep] = []
    unparsed: list[str] = []
    for text in preconditions:
        converted = step_from_sentence(text)
        if converted:
            result += converted
    for text in steps:
        converted = step_from_sentence(text)
        if converted is None:
            unparsed.append(text)
        else:
            result += converted
    assertions = assertions_from_expected(expected_result)
    if unparsed or not assertions:
        return Conversion([], unparsed)
    return Conversion(result + assertions, [])

