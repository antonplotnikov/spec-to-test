"""UI of the Test runs tab: start a run from a suite, record a result, and see Execution in the RTM."""

from streamlit.testing.v1 import AppTest

from conftest import PROJECT_ROOT, goto, home
from spec_to_test.storage import data_dir

APP_PATH = str(PROJECT_ROOT / "app.py")


def analyzed_app(example_text) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    home(at).text_area(key="requirements_text").input(example_text).run()
    home(at).button(key="analyze").click().run()
    assert not at.exception
    return at


def test_a_run_is_started_a_result_recorded_and_execution_shows_in_the_rtm(example_text):
    at = goto(analyzed_app(example_text), "tests")
    next(ti for ti in at.text_input if ti.label == "Run name").input("Smoke on Chrome")
    next(s for s in at.selectbox if s.label == "Run suite").select("Full")  # Smoke is empty until cases are approved
    next(b for b in at.button if b.label == "Start run").click().run()
    assert not at.exception
    assert any("started" in s.value for s in at.success)

    assert (data_dir() / "test_runs.json").exists()  # the run lives in its own file

    next(s for s in at.selectbox if s.label == "Result").select("Failed")
    next(b for b in at.button if b.label == "Save result").click().run()
    assert not at.exception
    assert any("Saved:" in s.value for s in at.success)

    labels = {m.label: m.value for m in goto(at, "rtm").metric}
    assert labels["Execution"] == "11.1%"  # one of the nine requirements has an executed case
    assert labels["Review"] == "0%"  # a failed result is not an approval


def test_without_runs_the_rtm_says_execution_is_not_tracked(example_text):
    at = goto(analyzed_app(example_text), "rtm")
    labels = {m.label: m.value for m in at.metric}
    assert labels["Execution"] == "Not tracked"
