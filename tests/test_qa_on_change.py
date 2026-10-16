"""QA agent automation: one run per changed requirements document, journaled, repeat-safe,
writing to the project only with --allow-write."""

import json
import os
import subprocess
import sys
import time

import pytest

from conftest import PROJECT_ROOT
from spec_to_test import storage
from spec_to_test.i18n import t
from spec_to_test.models import ReviewStatus
from spec_to_test.qa_agent import on_change
from spec_to_test.qa_agent.on_change import Journal, Request, RunLocked, build_workspace, main, run_on_change
from spec_to_test.qa_agent.tasks import AgentResult, Item, ProposedAction, StepResult
from spec_to_test.test_critic import critique

EXAMPLE = PROJECT_ROOT / "examples" / "password_reset.md"


@pytest.fixture
def docs(tmp_path):
    old = tmp_path / "spec_v1.md"
    new = tmp_path / "spec.md"
    text = EXAMPLE.read_text(encoding="utf-8")
    old.write_text(text, encoding="utf-8")
    new.write_text(text.replace("at least 8 characters", "at least 10 characters"), encoding="utf-8")
    return old, new


@pytest.fixture
def out(tmp_path):
    return tmp_path / "runs"


def _journal(out):
    return [json.loads(line) for line in (out / on_change.JOURNAL_FILE).read_text(encoding="utf-8").splitlines()]


def _saved(new, project_id="default"):
    """Save the document in the project as the app would, and return its workspace."""
    text = new.read_text(encoding="utf-8")
    workspace = build_workspace(text, new.name, "en")
    storage.save_workspace(workspace, project_id)
    return workspace


def _clean_test_case(workspace):
    return next(tc.id for tc in workspace.test_cases if not [i for i in critique(tc, workspace) if not i.unknown])


def _flagged_test_case(workspace):
    return next(tc.id for tc in workspace.test_cases if [i for i in critique(tc, workspace) if not i.unknown])


# --- Analysis, report and journal ----------------------------------------------

def test_a_changed_document_is_analyzed_reported_and_journaled(docs, out, capsys):
    old, new = docs
    assert main(["--document", str(new), "--previous", str(old), "--out", str(out)]) == 0
    [entry] = _journal(out)
    assert entry["status"] == "done"
    assert entry["trigger"] == "document_changed"
    assert entry["previous_hash"] == storage.document_hash(old.read_text(encoding="utf-8").strip())
    assert entry["problems"] > 0 and entry["action"] == "none"
    report = (out / "runs" / entry["run_id"] / "report.md").read_text(encoding="utf-8")
    assert "Change Impact" in report and "1 modified" in report
    assert "Previous version: spec\\_v1.md" in report
    result = json.loads((out / "runs" / entry["run_id"] / "result.json").read_text(encoding="utf-8"))
    assert [s["tool"] for s in result["steps"]] == [
        "requirements", "critic", "coverage", "impact", "traceability", "suites",
    ]
    assert "Report:" in capsys.readouterr().out
    # Analysis alone writes nothing outside --out.
    assert not storage.data_dir().exists()
    assert not (out / on_change.LOCK_FILE).exists()


def test_the_report_uses_the_chosen_language(docs, out):
    _, new = docs
    entry = run_on_change(Request(document=new, out=out, lang="ru"))
    assert "## Выводы" in (out / "runs" / entry.run_id / "report.md").read_text(encoding="utf-8")


def test_a_rerun_after_a_fix_shows_what_was_resolved(docs, out, capsys):
    _, new = docs
    assert main(["--document", str(new), "--out", str(out)]) == 0
    first_report = (out / "runs" / _journal(out)[0]["run_id"] / "report.md").read_text(encoding="utf-8")
    assert "Since the previous run" not in first_report  # nothing to compare with
    new.write_text(new.read_text(encoding="utf-8").replace(
        "should load fast and be user-friendly", "loads within 2 seconds"), encoding="utf-8")
    # Another task is another question: not compared.
    run_on_change(Request(document=new, out=out, task="Check the quality of the test cases"))
    capsys.readouterr()

    assert main(["--document", str(new), "--out", str(out)]) == 0
    first, _, rerun = _journal(out)
    assert rerun["compared_with"] == first["run_id"]
    # REQ-5 got two more test cases, which moves the later IDs: they are not reported as new.
    # Its own test case TC-009 was regenerated under a new title: renamed or replaced is unknown,
    # so its old problem is not reported as resolved.
    assert (rerun["resolved"], rerun["new_problems"], rerun["unmatched_before"], rerun["unmatched_now"]) == (1, 0, 1, 1)
    assert f"since run {first['run_id']}: resolved 1, still open {rerun['still_open']}, new 0, " \
           "not comparable 1 before / 1 now" in capsys.readouterr().out
    report = (out / "runs" / rerun["run_id"] / "report.md").read_text(encoding="utf-8")
    section = report.split("## Since the previous run")[1].split("## Problems")[0]
    assert "counted separately: resolved 1, still open" in section and "### New" not in section
    assert "### Resolved (1)\n\n- **REQ-5 · Ambiguous wording**: vague wording: fast, user-friendly\n" in section
    assert f"### Could not be compared (1 in run {first['run_id']}, 1 now)" in section
    assert f"TC-009 in run {first['run_id']}: “REQ-5: The reset page should load fast" in section
    assert "TC-009 now: “REQ-5: The reset page loads within 2 seconds" in section
    assert "_Not compared: Change Impact._" in section


def test_a_repeat_with_the_same_inputs_is_skipped_unless_forced(docs, out, capsys):
    old, new = docs
    args = ["--document", str(new), "--previous", str(old), "--out", str(out)]
    assert main(args) == 0
    assert main(args) == 0
    assert "same inputs as run" in capsys.readouterr().out
    assert main([*args, "--force"]) == 0
    first, repeat, forced = _journal(out)
    assert repeat["status"] == "skipped" and repeat["duplicate_of"] == first["run_id"]
    assert not (out / "runs" / repeat["run_id"]).exists()
    assert forced["status"] == "done"


def test_other_inputs_are_not_a_repeat(docs, out):
    old, new = docs
    run_on_change(Request(document=new, previous=old, out=out))
    assert run_on_change(Request(document=new, out=out)).status == "done"  # no previous version
    assert run_on_change(Request(document=new, out=out, task="Show traceability gaps")).status == "done"
    new.write_text(new.read_text(encoding="utf-8") + "\n- REQ-10: The page shows a help link.\n", encoding="utf-8")
    assert run_on_change(Request(document=new, out=out)).status == "done"


def test_a_failed_analysis_can_be_repeated(docs, out, monkeypatch):
    _, new = docs
    original = on_change.run_task

    def partial(task, workspace):
        result = original(task, workspace)
        result.status = "partial"
        return result

    monkeypatch.setattr(on_change, "run_task", partial)
    assert main(["--document", str(new), "--out", str(out)]) == 1
    monkeypatch.setattr(on_change, "run_task", original)
    assert main(["--document", str(new), "--out", str(out)]) == 0
    assert [e["status"] for e in _journal(out)] == ["partial", "done"]


def test_an_unsupported_task_is_journaled_without_running_tools(docs, out):
    _, new = docs
    entry = run_on_change(Request(document=new, out=out, task="delete everything"))
    assert entry.status == "unsupported"
    assert t("qatask.unsupported", "en") in (out / "runs" / entry.run_id / "report.md").read_text(encoding="utf-8")


# --- Errors ------------------------------------------------------------------------

@pytest.mark.parametrize(("name", "content", "code"), [
    ("missing.md", None, "not_found"),
    ("spec.docx", b"x", "unsupported_file_type"),
    ("empty.md", b"", "empty_file"),
])
def test_input_errors_are_journaled_with_exit_code_2(tmp_path, out, name, content, code):
    path = tmp_path / name
    if content is not None:
        path.write_bytes(content)
    assert main(["--document", str(path), "--out", str(out)]) == 2
    [entry] = _journal(out)
    assert (entry["status"], entry["error"]) == ("input_error", code)


def test_an_unexpected_error_is_journaled_as_crashed(docs, out, monkeypatch):
    _, new = docs

    def broken(_request):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(on_change, "load_document", broken)
    assert main(["--document", str(new), "--out", str(out)]) == 1
    [entry] = _journal(out)
    assert (entry["status"], entry["error"]) == ("crashed", "RuntimeError")
    assert "secret detail" not in (out / on_change.JOURNAL_FILE).read_text(encoding="utf-8")


def test_project_mode_needs_local_storage_and_a_known_project(docs, out, monkeypatch):
    _, new = docs
    assert run_on_change(Request(document=new, project_id="nosuchproject", out=out)).error == "unknown_project"
    assert run_on_change(Request(document=new, project_id="../x", out=out)).error == "invalid_project"
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")
    assert run_on_change(Request(document=new, project_id="default", out=out)).error == "storage_disabled"


def test_damaged_journal_lines_are_ignored(docs, out):
    _, new = docs
    out.mkdir()
    (out / on_change.JOURNAL_FILE).write_text("not json\n{\"run_id\": 1}\n", encoding="utf-8")
    assert run_on_change(Request(document=new, out=out)).status == "done"
    assert run_on_change(Request(document=new, out=out)).status == "skipped"
    assert len(Journal(out).entries()) == 2


def test_one_run_at_a_time_per_out_folder(docs, out, capsys):
    _, new = docs
    out.mkdir()
    (out / on_change.LOCK_FILE).write_text("123", encoding="utf-8")
    with pytest.raises(RunLocked):
        run_on_change(Request(document=new, out=out))
    assert main(["--document", str(new), "--out", str(out)]) == 2
    assert "Another run is in progress" in capsys.readouterr().err
    assert not (out / on_change.JOURNAL_FILE).exists()


def _finished_pid():
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _old_lock(out, pid):
    out.mkdir(exist_ok=True)
    lock = out / on_change.LOCK_FILE
    lock.write_text(f"{pid} 2026-01-01T00:00:00\n", encoding="utf-8")
    old = time.time() - on_change.STALE_LOCK_SECONDS - 60
    os.utime(lock, (old, old))
    return lock


def test_a_left_over_lock_is_replaced(docs, out):
    _, new = docs
    lock = _old_lock(out, _finished_pid())
    assert run_on_change(Request(document=new, out=out)).status == "done"
    assert not lock.exists()


def test_an_old_lock_of_a_running_process_is_kept(docs, out):
    _, new = docs
    lock = _old_lock(out, os.getpid())  # a run still working after 15 minutes
    with pytest.raises(RunLocked):
        run_on_change(Request(document=new, out=out))
    assert lock.read_text(encoding="utf-8").startswith(f"{os.getpid()} ")
    assert not (out / on_change.JOURNAL_FILE).exists()


def test_a_run_whose_lock_was_taken_over_leaves_the_new_lock(out):
    out.mkdir()
    lock = out / on_change.LOCK_FILE
    with on_change.run_lock(out):
        lock.write_text(f"{_finished_pid()} later run\n", encoding="utf-8")  # took over meanwhile
    assert lock.read_text(encoding="utf-8").endswith("later run\n")


# --- Permissions: the project changes only with --allow-write ------------------------

def test_a_status_change_stays_pending_without_permission(docs, out):
    _, new = docs
    saved = _saved(new)
    tc_id = _clean_test_case(saved)
    assert main(["--document", str(new), "--project", "default", "--task", f"approve {tc_id}", "--out", str(out)]) == 0
    [entry] = _journal(out)
    assert entry["action"] == "pending_approval"
    assert entry["action_test_case_ids"] == [tc_id] and entry["action_status"] == "approved"
    assert "Pending approval" in (out / "runs" / entry["run_id"] / "report.md").read_text(encoding="utf-8")
    stored = storage.load_workspace(saved.document_hash)
    assert all(tc.review_status == ReviewStatus.DRAFT for tc in stored.test_cases)


def test_allow_write_needs_a_project(docs, out, capsys):
    _, new = docs
    assert main(["--document", str(new), "--task", "approve TC-001", "--allow-write", "--out", str(out)]) == 2
    assert "--project" in capsys.readouterr().err
    assert not out.exists()


def test_allow_write_applies_the_change_to_the_saved_document(docs, out):
    old, new = docs
    _saved(old)  # opened last in the app
    saved = _saved(new)
    storage.save_pointer("default", storage.document_hash(old.read_text(encoding="utf-8").strip()))
    tc_id = _clean_test_case(saved)
    args = ["--document", str(new), "--project", "default", "--task", f"approve {tc_id}", "--allow-write",
            "--out", str(out)]
    assert main(args) == 0
    [entry] = _journal(out)
    assert entry["action"] == "applied" and entry["changed_test_case_ids"] == [tc_id]
    stored = storage.load_workspace(saved.document_hash)
    assert [tc.id for tc in stored.test_cases if tc.review_status == ReviewStatus.APPROVED] == [tc_id]
    # The app keeps its last opened document.
    assert storage.load_pointer()[1] == storage.document_hash(old.read_text(encoding="utf-8").strip())
    # The saved document changed, so this is not a repeat; the change is already there.
    assert main(args) == 0
    assert _journal(out)[-1]["action"] == "unchanged"


def test_allow_write_does_not_overwrite_an_edit_saved_meanwhile(docs, out, monkeypatch):
    _, new = docs
    saved = _saved(new)
    tc_id = _clean_test_case(saved)
    real_apply = on_change.apply_action

    def app_saves_meanwhile(workspace, action):
        app_copy = storage.load_workspace(saved.document_hash)
        app_copy.test_cases[-1].title = "Edited in the app"
        storage.save_workspace(app_copy)
        return real_apply(workspace, action)

    monkeypatch.setattr(on_change, "apply_action", app_saves_meanwhile)
    entry = run_on_change(Request(document=new, project_id="default", task=f"approve {tc_id}", out=out,
                                  allow_write=True))
    assert (entry.action, entry.action_reason) == ("failed", "WorkspaceConflict")
    assert on_change.exit_code(entry) == 1
    stored = storage.load_workspace(saved.document_hash)
    assert stored.test_cases[-1].title == "Edited in the app"
    assert all(tc.review_status == ReviewStatus.DRAFT for tc in stored.test_cases)


def test_an_older_app_copy_does_not_overwrite_the_applied_change(docs, out):
    _, new = docs
    saved = _saved(new)
    app_copy = storage.load_workspace(saved.document_hash)  # open in the app during the run
    tc_id = _clean_test_case(saved)
    entry = run_on_change(Request(document=new, project_id="default", task=f"approve {tc_id}", out=out,
                                  allow_write=True))
    assert entry.action == "applied"
    app_copy.test_cases[-1].title = "Edited in the app"
    with pytest.raises(storage.WorkspaceConflict):
        storage.save_workspace(app_copy)
    stored = storage.load_workspace(saved.document_hash)
    assert next(tc for tc in stored.test_cases if tc.id == tc_id).review_status == ReviewStatus.APPROVED


def test_allow_write_refuses_test_cases_the_critic_flags(docs, out):
    _, new = docs
    saved = _saved(new)
    tc_id = _flagged_test_case(saved)
    request = Request(document=new, project_id="default", task=f"approve {tc_id}", out=out, allow_write=True)
    entry = run_on_change(request)
    assert (entry.action, entry.action_reason) == ("refused", "critic_problems")
    assert on_change.exit_code(entry) == 1
    assert all(tc.review_status == ReviewStatus.DRAFT for tc in storage.load_workspace(saved.document_hash).test_cases)


def test_allow_write_does_not_approve_conflicting_test_cases(docs, out):
    old, _ = docs  # REQ-4 (at least 8) and REQ-7 (at least 10) contradict each other
    saved = _saved(old)
    entry = run_on_change(Request(document=old, project_id="default", task="approve TC-007 and TC-012", out=out,
                                  allow_write=True))
    assert entry.action == "none" and entry.changed_test_case_ids == []
    report = (out / "runs" / entry.run_id / "report.md").read_text(encoding="utf-8")
    assert t("qatask.action_conflicts", "en", ids="TC-007, TC-012") in report
    assert all(tc.review_status == ReviewStatus.DRAFT for tc in storage.load_workspace(saved.document_hash).test_cases)


def test_a_merged_critic_line_still_holds_back_both_test_cases(docs, out):
    # The mirror line of a conflict is merged away: TC-012 is named only by TC-007's line.
    conflict = Item(key="critic.expectation_conflict", params={"ids": "TC-012", "values": "9"}, ref="TC-007")
    result = AgentResult(task="t", status="done", steps=[StepResult(tool="critic", problems=[conflict])],
                         action=ProposedAction(test_case_ids=["TC-012"], status=ReviewStatus.APPROVED))
    request = Request(document=docs[1], project_id="default", task="t", out=out, allow_write=True)
    assert on_change.handle_action(request, result, saved=True) == ("refused", "critic_problems", [])


def test_the_report_keeps_not_approved_apart_from_the_problems(docs, out):
    _, new = docs
    entry = run_on_change(Request(document=new, task="Full check", out=out))
    report = (out / "runs" / entry.run_id / "report.md").read_text(encoding="utf-8")
    problems, approval = report.split(f"## {t('qatask.heading.approval', 'en')}")
    assert "has test cases, but none is Approved" not in problems
    assert "of 15 test cases are not Approved yet" in approval
    assert "**TC-002, TC-003, " in problems  # the same remark on several test cases: one line
    # TC-001 and TC-015 quote the user's action in step 2, so their remark names only steps 1 and 3.
    assert "**TC-001, TC-015 · Steps**" in problems
    # Under a problem: what the requirement it names says, and where it is in the document.
    assert "\n  - REQ-6 (line 14): “After too many failed attempts, the account is locked.”" in problems
    assert "\n  - **Next step:** ask the document author: “What measurable criteria replace: many?”" in problems


def test_allow_write_refuses_a_document_not_saved_in_the_project(docs, out):
    _, new = docs
    entry = run_on_change(Request(document=new, project_id="default", task="approve TC-004", out=out,
                                  allow_write=True))
    assert (entry.action, entry.action_reason) == ("refused", "not_saved")
    assert storage.list_documents("default") == []  # the new version is not saved either


def test_project_mode_compares_with_the_previous_version_of_the_same_title(docs, out, tmp_path):
    old, new = docs
    same_name = tmp_path / "v1" / new.name
    same_name.parent.mkdir()
    same_name.write_text(old.read_text(encoding="utf-8"), encoding="utf-8")
    previous = _saved(same_name)
    entry = run_on_change(Request(document=new, project_id="default", out=out))
    assert entry.status == "done" and entry.previous_hash == previous.document_hash
    assert [d.document_hash for d in storage.list_documents("default")] == [previous.document_hash]
