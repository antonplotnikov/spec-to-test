"""Background jobs, ownership, approval, persistence, sandbox environment and exports."""

import io
import os
import threading
import zipfile

import pytest
from pydantic import SecretStr

from automation_fakes import (
    FAKE_API_KEY,
    REQ,
    SECRET_VALUE,
    TC,
    FakeAgent,
    FakeRunner,
    browser_factory,
    config,
    failed_run,
    good_script,
    passed_run,
    resolver,
    tool_use,
)
from spec_to_test.ai_analysis import AIConfig
from spec_to_test.automation import config as config_module
from spec_to_test.automation.export import approved_bundle, job_bundle
from spec_to_test.automation.models import AutomationJob, JobStatus
from spec_to_test.automation.sandbox import limited_command, sandbox_env
from spec_to_test.automation.service import AutomationError, AutomationService, JobStore, new_owner_id
from spec_to_test.models import ReviewStatus, Workspace

AI = AIConfig(provider="anthropic", model="claude-opus-5-5", api_key=SecretStr(FAKE_API_KEY))


def service(tmp_path, *agents, runner=None, **settings):
    queue = list(agents)
    return AutomationService(
        config(tmp_path, **settings),
        agent_factory=lambda ai: queue.pop(0),
        browser_factory=browser_factory(),
        runner_factory=lambda cfg: runner or FakeRunner(passed_run()),
        resolver=resolver(),
        check_prerequisites=False,
    )


def passing_agent():
    return FakeAgent([tool_use("a", "submit_test_script", **good_script())])


def submit(svc, owner="alice", tc=TC, **options):
    params = dict(target_url="https://staging.example.com/", ai_config=AI, consent=True)
    params.update(options)
    return svc.submit(owner, tc, REQ, **params)


def test_job_runs_in_the_background_and_is_persisted(tmp_path):
    svc = service(tmp_path, passing_agent())
    job = submit(svc)
    assert job.status == JobStatus.QUEUED and len(job.id) == 16
    svc.wait(job.id, timeout=10)
    done = svc.job("alice", job.id)
    assert done is not None and done.status == JobStatus.PASSED
    stored = JobStore(svc.config.artifacts_dir).load(job.id)
    assert stored is not None and stored.status == JobStatus.PASSED and stored.code


@pytest.mark.parametrize(
    ("options", "code"),
    [({"consent": False}, "consent_required"), ({"ai_config": None}, "ai_not_configured")],
)
def test_submit_requires_consent_and_ai(tmp_path, options, code):
    with pytest.raises(AutomationError) as error:
        submit(service(tmp_path), **options)
    assert error.value.code == code


def test_submit_requires_allowlist_and_approved_test_case(tmp_path):
    with pytest.raises(AutomationError) as error:
        submit(service(tmp_path, AUTOMATION_ALLOWED_HOSTS=""))
    assert error.value.code == "not_configured"
    with pytest.raises(AutomationError) as error:
        submit(service(tmp_path), tc=TC.model_copy(update={"review_status": ReviewStatus.DRAFT}))
    assert error.value.code == "not_approved"


def test_one_active_job_per_owner_and_owners_are_isolated(tmp_path):
    hold = threading.Event()
    svc = service(tmp_path, FakeAgent(delay=hold, error=RuntimeError("stop")), passing_agent())
    first = submit(svc, owner="alice")
    with pytest.raises(AutomationError) as error:
        submit(svc, owner="alice")
    assert error.value.code == "busy"
    other = submit(svc, owner="bob")  # someone else is not blocked
    assert svc.job("bob", first.id) is None and svc.cancel("bob", first.id) is False
    assert [j.id for j in svc.jobs("alice")] == [first.id]
    hold.set()
    svc.wait(first.id, timeout=10)
    svc.wait(other.id, timeout=10)


def test_cancel_stops_a_running_job(tmp_path):
    hold = threading.Event()
    svc = service(tmp_path, FakeAgent(delay=hold))
    job = submit(svc)
    assert svc.cancel("alice", job.id)
    svc.wait(job.id, timeout=10)
    hold.set()
    assert svc.job("alice", job.id).status == JobStatus.CANCELLED


def test_approve_adds_the_validated_test_to_the_workspace(tmp_path):
    svc = service(tmp_path, passing_agent(), passing_agent())
    workspace = Workspace(requirements=[REQ], test_cases=[TC])
    job = submit(svc)
    svc.wait(job.id, timeout=10)
    record = svc.approve("alice", job.id, workspace)
    assert record.id == "AT-001" and record.test_case_id == "TC-001" and record.requirement_id == "REQ-001"
    assert record.code == svc.job("alice", job.id).code and record.file_name == "tc-001.spec.ts"
    assert svc.job("alice", job.id).approved
    again = submit(svc)  # a newer validation replaces the older one for the same test case
    svc.wait(again.id, timeout=10)
    assert svc.approve("alice", again.id, workspace).id == "AT-001" and len(workspace.automated_tests) == 1


def test_only_passed_jobs_of_approved_test_cases_can_be_approved(tmp_path):
    agent = FakeAgent([tool_use("a", "submit_test_script", **good_script())], [tool_use("b", "submit_test_script", **good_script())])
    svc = service(tmp_path, agent, runner=FakeRunner(failed_run(), failed_run()))
    job = submit(svc)
    svc.wait(job.id, timeout=10)
    assert svc.job("alice", job.id).status == JobStatus.FAILED
    with pytest.raises(AutomationError) as error:
        svc.approve("alice", job.id, Workspace(test_cases=[TC]))
    assert error.value.code == "not_passed"
    with pytest.raises(AutomationError):
        svc.approve("mallory", job.id, Workspace(test_cases=[TC]))


def test_jobs_left_running_by_a_restart_are_marked_interrupted(tmp_path):
    cfg = config(tmp_path)
    store = JobStore(cfg.artifacts_dir)
    stale = AutomationJob(id="00000000000000aa", owner="local", test_case_id="TC-001", requirement_id="REQ-001",
                          target_url="https://staging.example.com/", status=JobStatus.EXPLORING)
    store.save(stale)
    jobs = service(tmp_path).jobs("local")
    assert jobs[0].status == JobStatus.BLOCKED and jobs[0].reason == "interrupted"
    assert store.load(stale.id).reason == "interrupted"


def test_artifact_paths_cannot_leave_the_job_folder(tmp_path):
    store = JobStore(tmp_path)
    job = AutomationJob(id="00000000000000bb", owner="o", test_case_id="T", requirement_id="R", target_url="x")
    folder = store.job_dir(job.id)
    folder.mkdir(parents=True)
    (folder / "run.log").write_text("ok")
    (tmp_path / "secret.txt").write_text("no")
    assert store.artifact_path(job, "run.log") == (folder / "run.log").resolve()
    assert store.artifact_path(job, "../../secret.txt") is None
    assert store.artifact_path(job, "/etc/passwd") is None
    with pytest.raises(ValueError):
        store.job_dir("../x")


def test_owner_is_shared_only_in_local_mode(monkeypatch):
    monkeypatch.setenv("SPEC_TO_TEST_STORAGE", "local")
    assert new_owner_id() == "local"
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")
    assert new_owner_id() != new_owner_id()


def test_session_mode_keeps_job_files_in_a_private_temp_folder(monkeypatch):
    monkeypatch.delenv("SPEC_TO_TEST_STORAGE")
    monkeypatch.setattr(config_module, "_session_dir", None)
    folder = config_module.default_artifacts_dir()
    assert folder.is_dir() and oct(folder.stat().st_mode)[-3:] == "700"
    assert "spec-to-test-automation-" in folder.name


def test_missing_prerequisites_lists_what_is_needed(tmp_path):
    cfg = config(tmp_path, AUTOMATION_ALLOWED_HOSTS="", AUTOMATION_RUNNER_DIR=str(tmp_path / "none"))
    missing = config_module.missing_prerequisites(cfg)
    assert "allowlist" in missing and "runner" in missing


# --- Sandbox -----------------------------------------------------------------------------------


def test_sandbox_environment_has_no_server_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_API_KEY)
    monkeypatch.setenv("AUTOMATION_SECRET_OTHER", "other-value")
    env = sandbox_env(tmp_path / "p", {"STAGING_PASSWORD": SECRET_VALUE})
    assert "ANTHROPIC_API_KEY" not in env and "AUTOMATION_SECRET_OTHER" not in env
    assert env["STAGING_PASSWORD"] == SECRET_VALUE
    assert env["HOME"].startswith(str(tmp_path)) and env["TMPDIR"].startswith(str(tmp_path))
    assert env["PLAYWRIGHT_BROWSERS_PATH"]


@pytest.mark.skipif(os.name != "posix", reason="resource limits are POSIX only")
def test_limited_command_applies_resource_limits():
    import subprocess
    import sys

    command = limited_command([sys.executable, "-c", "import resource; print(resource.getrlimit(resource.RLIMIT_CPU)[0])"], 7)
    assert subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip() == "7"


# --- Exports -----------------------------------------------------------------------------------


def test_job_bundle_contains_the_evidence(tmp_path):
    svc = service(tmp_path, passing_agent())
    job = submit(svc)
    svc.wait(job.id, timeout=10)
    done = svc.job("alice", job.id)
    with zipfile.ZipFile(io.BytesIO(job_bundle(svc.store, done))) as archive:
        names = set(archive.namelist())
        assert {"tests/tc-001.spec.ts", "playwright.config.ts", "report/results.json", "job.json"} <= names
        assert SECRET_VALUE not in "".join(archive.read(n).decode(errors="ignore") for n in names)


def test_approved_bundle_is_a_runnable_playwright_project(tmp_path):
    svc = service(tmp_path, passing_agent())
    workspace = Workspace(requirements=[REQ], test_cases=[TC])
    job = submit(svc)
    svc.wait(job.id, timeout=10)
    svc.approve("alice", job.id, workspace)
    with zipfile.ZipFile(io.BytesIO(approved_bundle(workspace.automated_tests))) as archive:
        assert set(archive.namelist()) == {"tests/tc-001.spec.ts", "playwright.config.ts", "README.md"}
        readme = archive.read("README.md").decode()
        assert "STAGING_PASSWORD=..." in readme and "TC-001" in readme and SECRET_VALUE not in readme
        assert "process.env.BASE_URL" in archive.read("playwright.config.ts").decode()


def test_workspace_without_automated_tests_still_loads():
    old = '{"document_hash": "abc", "requirements": [], "test_cases": []}'
    assert Workspace.model_validate_json(old).automated_tests == []


def test_node_can_be_configured_when_it_is_not_on_path(tmp_path, monkeypatch):
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\n")
    node.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert config(tmp_path).node is None
    assert config(tmp_path, AUTOMATION_NODE=str(node)).node == str(node)
    assert config(tmp_path, AUTOMATION_NODE=str(tmp_path / "missing")).node is None


@pytest.mark.skipif(os.name != "posix", reason="POSIX temp layout")
def test_private_folders_left_by_a_killed_server_are_removed():
    import time

    from spec_to_test.automation.sandbox import private_dir, prune_private_dirs

    stale, fresh = private_dir(), private_dir()
    (stale / "mcp-config.json").write_text("{}")
    old = time.time() - 10_000
    os.utime(stale, (old, old))
    try:
        prune_private_dirs(3600)
        assert not stale.exists() and fresh.exists()
    finally:
        import shutil

        shutil.rmtree(stale, ignore_errors=True)
        shutil.rmtree(fresh, ignore_errors=True)
