"""QA Agent memory: confirmed project rules and explicit feedback, per project."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test import storage
from spec_to_test.models import Project, Workspace
from spec_to_test.qa_agent import memory
from spec_to_test.qa_agent.memory import (
    DiskMemoryStore,
    MemoryEntry,
    MemoryEntryError,
    SessionMemoryStore,
    edited,
    new_feedback,
    new_rule,
    open_memory_store,
    relevant,
)
from spec_to_test.qa_agent.tasks import AgentPlan, AgentResult, StepResult

APP_PATH = str(PROJECT_ROOT / "app.py")


def rule(text: str = "Smoke must cover checkout", tools: tuple[str, ...] = ("suites",)) -> MemoryEntry:
    return new_rule(text, list(tools), confirmed=True)


def result(*tools: str, task: str = "plan a smoke suite") -> AgentResult:
    return AgentResult(task=task, status="done", plan=AgentPlan(tools=list(tools)),
                       steps=[StepResult(tool=tool) for tool in tools])


@pytest.fixture(params=["session", "disk"])
def store(request):
    return SessionMemoryStore() if request.param == "session" else DiskMemoryStore()


# --- Only confirmed rules and explicit ratings ----------------------------------------

def test_rule_needs_confirmation_text_and_tools():
    with pytest.raises(MemoryEntryError, match="not_confirmed"):
        new_rule("Smoke must cover checkout", ["suites"], confirmed=False)
    with pytest.raises(MemoryEntryError, match="text_required"):
        new_rule("   ", ["suites"], confirmed=True)
    with pytest.raises(MemoryEntryError, match="no_tools"):
        new_rule("Smoke must cover checkout", ["unknown_tool"], confirmed=True)
    with pytest.raises(MemoryEntryError, match="text_too_long"):
        new_rule("x" * (memory.MAX_TEXT_LENGTH + 1), ["suites"], confirmed=True)
    entry = new_rule("  Smoke   must cover\ncheckout ", ["suites", "critic"], confirmed=True)
    assert (entry.kind, entry.text, entry.tools) == ("rule", "Smoke must cover checkout", ["critic", "suites"])


def test_feedback_keeps_the_rating_not_the_agent_answer():
    answered = result("coverage", "suites")
    answered.steps[0].problems = []
    answered.steps[1].status = "error"
    entry = new_feedback(answered, "not_useful", "missed REQ-2")
    assert entry.model_dump(include={"kind", "rating", "text", "task", "tools"}) == {
        "kind": "feedback", "rating": "not_useful", "text": "missed REQ-2", "task": "plan a smoke suite",
        "tools": ["coverage"],  # the failed tool is not credited
    }
    assert set(MemoryEntry.model_fields) == {"id", "kind", "text", "tools", "rating", "task", "created_at", "updated_at"}
    with pytest.raises(MemoryEntryError, match="nothing_to_rate"):
        new_feedback(AgentResult(task="write a poem", status="unsupported"), "useful")


def test_edited_entry_is_validated_again():
    entry = rule()
    fixed = edited(entry, "Smoke must cover checkout and login", ["suites", "coverage"])
    assert (fixed.id, fixed.text, fixed.tools) == (entry.id, "Smoke must cover checkout and login", ["coverage", "suites"])
    with pytest.raises(MemoryEntryError, match="text_required"):
        edited(entry, "", ["suites"])
    feedback = new_feedback(result("suites"), "useful")
    assert edited(feedback, "", ["suites"], "not_useful").rating == "not_useful"


# --- Relevance ------------------------------------------------------------------------

def test_only_entries_of_the_same_tools_and_ids_are_relevant():
    suites = rule("Smoke must cover checkout", ("suites",))
    req2 = rule("REQ-2 boundaries apply to admins only", ("coverage",))
    req5 = rule("REQ-5 is out of scope this release", ("coverage",))
    feedback = new_feedback(result("coverage"), "useful")
    entries = [feedback, suites, req2, req5]

    assert relevant(entries, AgentPlan(tools=["critic"])) == []
    assert relevant(entries, None) == []
    assert relevant(entries, AgentPlan(tools=["suites"])) == [suites]
    # The whole document: every coverage entry; rules first.
    assert relevant(entries, AgentPlan(tools=["coverage"]))[-1] == feedback
    assert set(map(id, relevant(entries, AgentPlan(tools=["coverage"])))) == {id(req2), id(req5), id(feedback)}
    # Scoped to REQ-2: a rule about REQ-5 is not relevant, one without IDs is.
    scoped = relevant(entries, AgentPlan(tools=["coverage"], requirement_ids=["REQ-2"]))
    assert req5 not in scoped and req2 in scoped and feedback in scoped
    assert len(relevant([rule(f"rule {n}", ("suites",)) for n in range(9)], AgentPlan(tools=["suites"]))) == \
        memory.MAX_RELEVANT


# --- Saving, correcting, deleting, project isolation -----------------------------------

def test_add_update_delete(store):
    entry = rule()
    store.add("default", entry)
    assert [e.id for e in store.entries("default")] == [entry.id]
    store.update("default", edited(entry, "Smoke must cover login", ["suites"]))
    assert store.entries("default")[0].text == "Smoke must cover login"
    store.delete("default", entry.id)
    assert store.entries("default") == []
    with pytest.raises(MemoryEntryError, match="missing"):
        store.update("default", entry)


def test_projects_are_isolated(store):
    store.add("alpha1", rule("Alpha rule"))
    store.add("beta22", rule("Beta rule"))
    assert [e.text for e in store.entries("alpha1")] == ["Alpha rule"]
    assert [e.text for e in store.entries("beta22")] == ["Beta rule"]
    store.delete("alpha1", store.entries("beta22")[0].id)  # another project's id deletes nothing
    assert len(store.entries("beta22")) == 1
    store.delete_project("alpha1")
    assert store.entries("alpha1") == []
    assert [e.text for e in store.entries("beta22")] == ["Beta rule"]


def test_memory_is_limited(store, monkeypatch):
    monkeypatch.setattr(memory, "MAX_ENTRIES", 2)
    store.add("default", rule("one"))
    store.add("default", rule("two"))
    with pytest.raises(MemoryEntryError, match="full"):
        store.add("default", rule("three"))


def test_disk_memory_lives_in_the_project_folder_and_survives_a_new_store():
    DiskMemoryStore().add("default", rule("Default rule"))
    DiskMemoryStore().add("abc123", rule("Project rule"))
    assert (storage.data_dir() / "qa_memory.json").is_file()
    assert (storage.data_dir() / "projects" / "abc123" / "qa_memory.json").is_file()
    assert [e.text for e in DiskMemoryStore().entries("abc123")] == ["Project rule"]


def test_deleting_a_project_deletes_its_memory():
    storage.save_project(Project(id="abc123", name="Shop"))
    store = DiskMemoryStore()
    store.add("abc123", rule("Shop rule"))
    store.add("default", rule("Default rule"))
    store.add("def456", rule("Other rule"))
    storage.delete_project("abc123")
    storage.delete_project("default")
    assert store.entries("abc123") == []
    assert store.entries("default") == []
    assert [e.text for e in store.entries("def456")] == ["Other rule"]


def test_invalid_files_and_entries_are_not_trusted():
    path = storage.data_dir() / "qa_memory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    good = rule().model_dump(mode="json")
    path.write_text(json.dumps({"format": memory.FORMAT, "format_version": 1, "entries": [
        good,
        {**good, "id": "0" * 12, "kind": "rule", "text": ""},  # a rule without text
        {**good, "id": "1" * 12, "kind": "feedback"},  # feedback without a rating
        {**good, "id": "../../etc"},
        "not an entry",
    ]}), encoding="utf-8")
    assert [e.id for e in DiskMemoryStore().entries("default")] == [good["id"]]
    path.write_text("{broken", encoding="utf-8")
    assert DiskMemoryStore().entries("default") == []
    path.write_text(json.dumps({"format": "other", "entries": [good]}), encoding="utf-8")
    assert DiskMemoryStore().entries("default") == []
    assert DiskMemoryStore().entries("../x") == []
    with pytest.raises(ValueError):
        DiskMemoryStore().add("../x", rule())


def test_session_mode_writes_nothing_to_disk(monkeypatch):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "session")
    state: dict = {}
    store = open_memory_store(state)
    assert isinstance(store, SessionMemoryStore) and open_memory_store(state) is store
    store.add("default", rule())
    assert not storage.data_dir().exists()
    assert open_memory_store({}).entries("default") == []  # another browser session
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "local")
    assert isinstance(open_memory_store(state), DiskMemoryStore)


# --- Page ---------------------------------------------------------------------------

def _task_mode(example_text: str) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    goto(at, "qa_agent")
    at.segmented_control(key="qa_mode").set_value("task").run()
    assert not at.exception
    return at


def _button(at: AppTest, key: str):
    return next(b for b in at.button if b.key == key)


def _run(at: AppTest, task: str) -> AppTest:
    at.text_area(key="qa_task_text").input(task).run()
    _button(at, "qa_task_run").click().run()
    assert not at.exception
    return at


def test_page_saves_rules_and_feedback_and_shows_them_when_relevant(example_text):
    at = _task_mode(example_text)
    # A rule is saved only after the confirmation.
    at.text_area(key="qa_memory_rule_text").input("Smoke must include REQ-1")
    at.multiselect(key="qa_memory_rule_tools").select("suites").run()
    assert _button(at, "qa_memory_add").disabled
    at.checkbox(key="qa_memory_rule_confirm").check().run()
    _button(at, "qa_memory_add").click().run()
    assert any("Rule saved" in s.value for s in at.success)
    assert [e.text for e in DiskMemoryStore().entries("default")] == ["Smoke must include REQ-1"]

    # Not shown with an unrelated check, shown with the Suite Planner.
    _run(at, "check coverage")
    assert not any("From project memory" in i.value for i in at.info)
    _run(at, "plan a smoke suite")
    assert any("Smoke must include REQ-1" in i.value for i in at.info)

    # Running a task saves nothing; rating it does.
    assert len(DiskMemoryStore().entries("default")) == 1
    at.text_input(key="qa_task_feedback_comment").input("missed the login flow")
    _button(at, "qa_feedback_not_useful").click().run()
    assert not at.exception
    feedback = [e for e in DiskMemoryStore().entries("default") if e.kind == "feedback"]
    assert [(e.rating, e.text, e.task, e.tools) for e in feedback] == [
        ("not_useful", "missed the login flow", "plan a smoke suite", ["suites"]),
    ]
    assert not any(b.key == "qa_feedback_useful" for b in at.button)  # rated once


def test_page_corrects_and_deletes_entries(example_text):
    entry = rule("Smoke must include REQ-1")
    DiskMemoryStore().add("default", entry)
    at = _task_mode(example_text)
    at.selectbox(key="qa_memory_pick").set_value(entry.id).run()
    at.text_area(key=f"qa_memory_text_{entry.id}").input("Smoke must include REQ-1 and REQ-2")
    _button(at, f"qa_memory_save_{entry.id}").click().run()
    assert not at.exception
    assert DiskMemoryStore().entries("default")[0].text == "Smoke must include REQ-1 and REQ-2"

    assert _button(at, f"qa_memory_delete_{entry.id}").disabled
    at.checkbox(key=f"qa_memory_delete_confirm_{entry.id}").check().run()
    _button(at, f"qa_memory_delete_{entry.id}").click().run()
    assert not at.exception
    assert DiskMemoryStore().entries("default") == []
    assert any("Entry deleted" in s.value for s in at.success)


def test_running_a_task_does_not_depend_on_memory():
    """Memory is shown beside results; the analysis itself never reads it."""
    from spec_to_test.qa_agent import tasks

    ws = Workspace(document_hash="doc")
    DiskMemoryStore().add("default", rule("Smoke must include REQ-1"))
    assert tasks.run_task("plan a smoke suite", ws) == tasks.run_task("plan a smoke suite", ws.model_copy())
    assert "memory" not in tasks.__dict__
