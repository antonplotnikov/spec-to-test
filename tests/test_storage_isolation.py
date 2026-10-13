"""Visitors must never see each other's documents: "session" storage is the default.

Each AppTest instance stands for one browser session (its own session state);
all of them share the same disk, as visitors of one deployment do.
"""

import pytest
from test_app_features import button, new_app, table_with_column
from test_grill_ui import OTHER_DOC, TC_DRAFT, click, confirm, start
from test_grill_ui import analyzed as analyzed_in_grill

from conftest import goto, home
from spec_to_test import storage
from spec_to_test.storage import load_latest, save_workspace


@pytest.fixture
def default_storage(monkeypatch):
    """The product default: no SPEC_TO_TEST_STORAGE at all."""
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)


@pytest.fixture
def no_disk_access(monkeypatch):
    """Fail on any use of the data directory or the workspace files."""
    def forbidden(*args, **kwargs):
        raise AssertionError("disk access in session mode")

    for name in ("data_dir", "_workspace_path", "_write_atomic"):
        monkeypatch.setattr(storage, name, forbidden)


def analyze(at, text):
    home(at).text_area(key="requirements_text").input(text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception, at.exception
    return at


def data_files(tmp_path):
    return sorted(p for p in (tmp_path / "data").rglob("*") if p.is_file()) if (tmp_path / "data").exists() else []


def bugs(at):
    return at.session_state["workspace"].defects


def test_default_mode_keeps_nothing_on_disk(default_storage, no_disk_access, example_text, tmp_path):
    at = new_app()
    assert any("only for this browser session" in c.value for c in at.sidebar.caption)
    analyze(at, example_text)
    button(at, "bug_generate").click().run()
    assert not at.exception
    assert bugs(at)
    assert data_files(tmp_path) == []


def test_old_files_on_disk_are_not_restored(example_text, tmp_path, monkeypatch):
    first = analyze(new_app(), example_text)  # conftest: "local", so this writes files
    button(first, "bug_generate").click().run()
    assert load_latest() is not None
    saved_before = {p: p.read_bytes() for p in data_files(tmp_path)}

    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")
    at = new_app()
    assert "workspace" not in at.session_state
    assert not any("Restored" in info.value for info in at.info)
    analyze(at, example_text)  # same document: still no restore from disk
    assert not bugs(at)
    assert not any("Restored" in info.value for info in at.info)
    assert {p: p.read_bytes() for p in data_files(tmp_path)} == saved_before  # untouched


@pytest.mark.parametrize("second_text", ["same", "other"])
def test_two_sessions_do_not_share_work(default_storage, no_disk_access, example_text, second_text):
    a = analyze(new_app(), example_text)
    button(a, "bug_generate").click().run()
    assert bugs(a)

    b = new_app()
    assert "workspace" not in b.session_state
    analyze(b, example_text if second_text == "same" else OTHER_DOC)
    assert not bugs(b)
    assert not any("Restored" in info.value for info in b.info)

    other_titles = {tc.title for tc in b.session_state["workspace"].test_cases}
    form = next(ti for ti in goto(b, "tests").text_input if ti.label == "Title")
    form.input("Only in B")
    next(x for x in b.button if x.label == "Save").click().run()
    assert not b.exception
    assert any(tc.title == "Only in B" for tc in b.session_state["workspace"].test_cases)
    assert "Only in B" not in {tc.title for tc in a.session_state["workspace"].test_cases}
    assert other_titles  # B really had its own test cases


def test_rerun_and_screen_switch_keep_the_session_state(default_storage, no_disk_access, example_text):
    at = analyze(new_app(), example_text)
    next(ti for ti in goto(at, "tests").text_input if ti.label == "Title").input("Edited in session")
    next(x for x in at.button if x.label == "Save").click().run()
    workspace = at.session_state["workspace"]

    at.run()  # plain rerun
    assert at.session_state["workspace"] == workspace

    at.sidebar.radio(key="app_mode").set_value("grill").run()
    assert not at.exception
    at.sidebar.radio(key="app_mode").set_value("analysis").run()
    assert not at.exception
    assert at.session_state["workspace"] == workspace
    assert table_with_column(at, "Quality score") is not None

    at.selectbox(key="language").select("uk").run()  # language change reruns too
    assert at.session_state["workspace"] == workspace


def test_reanalyzing_the_same_document_keeps_session_edits(default_storage, no_disk_access, example_text):
    at = analyze(new_app(), example_text)
    button(at, "bug_generate").click().run()
    count = len(bugs(at))
    assert count
    home(at).button(key="analyze").click().run()
    assert not at.exception
    assert len(bugs(at)) == count
    notes = [info.value for info in at.info]
    assert any("already open in this session" in n for n in notes)
    assert not any("Restored" in n for n in notes)  # nothing came from disk


def test_grill_result_stays_in_its_session(default_storage, no_disk_access, example_text, tmp_path):
    at = analyzed_in_grill(example_text)
    before = len(at.session_state["workspace"].test_cases)
    at = confirm(start(at, "review", artifact="test_case", text_key="grill_draft_text", text=TC_DRAFT))
    click(at, "grill_add")
    assert len(at.session_state["workspace"].test_cases) == before + 1
    assert data_files(tmp_path) == []

    other = analyze(new_app(), example_text)  # a second visitor, same document
    assert len(other.session_state["workspace"].test_cases) == before
    assert not any(tc.source.value == "user" for tc in other.session_state["workspace"].test_cases)

    at.sidebar.radio(key="app_mode").set_value("analysis").run()  # back to analysis: still there
    assert len(at.session_state["workspace"].test_cases) == before + 1


@pytest.mark.parametrize("value", ["local", "  LOCAL ", "Local"])
def test_explicit_local_still_saves_and_restores(monkeypatch, example_text, value, tmp_path):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", value)
    first = analyze(new_app(), example_text)
    button(first, "bug_generate").click().run()
    assert data_files(tmp_path)
    assert load_latest() == first.session_state["workspace"]

    again = new_app()  # a new session restores the last work
    assert any("Restored" in info.value for info in again.info)
    assert bugs(again)
    assert any("saved automatically" in c.value for c in again.sidebar.caption)


def test_local_reanalyze_keeps_newer_edits_from_another_tab(monkeypatch, example_text):
    """Two tabs on one document: B's Analyze must load A's newer save, not overwrite it."""
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "local")
    a = analyze(new_app(), example_text)
    b = analyze(new_app(), example_text)
    assert not bugs(b)

    button(a, "bug_generate").click().run()  # A saves a bug report
    saved = load_latest()
    assert saved is not None and saved.defects

    home(b).button(key="analyze").click().run()  # B analyzes the same document again
    assert not b.exception
    assert bugs(b) == saved.defects  # B now shows A's bug report
    assert load_latest() == saved  # and did not erase it on disk
    notes = [info.value for info in b.info]
    assert any("Restored" in n for n in notes)
    assert not any("already open in this session" in n for n in notes)


@pytest.mark.parametrize(
    ("value", "expected", "unexpected"),
    [
        (None, "already open in this session", "Restored"),  # default: from this session
        ("local", "Restored", "already open in this session"),  # local: from disk
    ],
)
def test_reanalyze_message_says_where_the_work_came_from(monkeypatch, example_text, value, expected, unexpected):
    if value is None:
        monkeypatch.delenv("SPEC_TO_TEST_STORAGE", raising=False)
    else:
        monkeypatch.setenv("SPEC_TO_TEST_STORAGE", value)
    at = analyze(new_app(), example_text)
    assert not any(expected in info.value for info in at.info)  # first Analyze: nothing kept or restored
    button(at, "bug_generate").click().run()
    count = len(bugs(at))
    assert count

    home(at).button(key="analyze").click().run()
    assert not at.exception
    assert len(bugs(at)) == count
    notes = [info.value for info in at.info]
    assert any(expected in n for n in notes)
    assert not any(unexpected in n for n in notes)


@pytest.mark.parametrize("value", ["", "session", "nonsense", "true"])
def test_unknown_values_behave_like_session(monkeypatch, example_text, value, tmp_path):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", value)
    at = analyze(new_app(), example_text)
    button(at, "bug_generate").click().run()
    assert data_files(tmp_path) == []
    save_workspace(at.session_state["workspace"])
    assert data_files(tmp_path) == []
