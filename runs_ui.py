"""Test runs section of the Test Cases page: start a run from a suite, record each result, see the figures.

A run is kept with the project (see spec_to_test.execution). Forms are handled before the figures
are drawn, so a saved result shows in the same pass without a rerun.
"""

from datetime import UTC, datetime

import streamlit as st

import theme_ui
from spec_to_test.execution import (
    RunError,
    RunStatus,
    RunStore,
    TestRun,
    new_run,
    next_run_id,
    record_result,
    summarize,
)
from spec_to_test.exports import run_csv
from spec_to_test.i18n import t
from spec_to_test.models import Workspace
from spec_to_test.suites import SuiteKind, plan_suites

STATUS_BADGES = {"passed": "✅", "failed": "❌", "blocked": "⛔", "not_run": "⬜"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _start_form(lang: str, ws: Workspace, project_id: str, store: RunStore) -> None:
    plan = plan_suites(ws)
    with st.expander(t("runs.start", lang), icon=":material/play_arrow:"), st.form("start_run_form"):
        name = st.text_input(t("runs.name", lang))
        suite = st.selectbox(t("runs.suite", lang), list(SuiteKind),
                             format_func=lambda k: t(f"suites.{k.value}", lang)) or SuiteKind.SMOKE
        environment = st.text_input(t("runs.environment", lang))
        build = st.text_input(t("runs.build", lang))
        submitted = st.form_submit_button(t("runs.start_button", lang), type="primary")
    if not submitted:
        return
    ids = plan.suites[suite]
    if not name.strip():
        st.error(t("runs.name_required", lang))
    elif not ids:
        st.error(t("runs.empty_suite", lang))
    else:
        try:
            run = store.add_run(project_id, lambda runs: new_run(
                next_run_id(runs), name.strip(), suite.value, environment.strip(), build.strip(),
                ws.document_hash, ids, _now(),
            ))
        except RunError as error:
            st.error(t(f"execution.error.{error.code}", lang))
        except (OSError, ValueError):
            st.error(t("storage.save_failed", lang))
        else:
            st.success(t("runs.started", lang, id=run.id, count=len(run.results)))


def _record_form(lang: str, project_id: str, store: RunStore, run: TestRun, titles: dict[str, str]) -> None:
    with st.expander(t("runs.record", lang), icon=":material/edit:", expanded=True), st.form(f"record_{run.id}"):
        case_id = st.selectbox(
            t("runs.case", lang), [r.test_case_id for r in run.results],
            format_func=lambda i: f"{i} — {titles.get(i, t('runs.removed', lang))}",
        )
        status = st.selectbox(t("runs.status", lang), list(RunStatus),
                              format_func=lambda s: t(f"runs.status.{s.value}", lang)) or RunStatus.NOT_RUN
        comment = st.text_input(t("runs.comment", lang))
        bug_id = st.text_input(t("runs.bug_id", lang))
        submitted = st.form_submit_button(t("runs.save_result", lang), type="primary")
    if not submitted:
        return
    try:
        store.update_run(project_id, run.id, lambda current: record_result(
            current, case_id, status, comment, bug_id, _now(),
        ))
    except RunError as error:
        st.error(t(f"execution.error.{error.code}", lang))
    except (OSError, ValueError):
        st.error(t("storage.save_failed", lang))
    else:
        st.success(t("runs.saved", lang, id=case_id))


def _figures(lang: str, run: TestRun) -> None:
    s = summarize(run)
    cols = st.columns(6)
    cols[0].metric(t("runs.progress", lang), f"{s.progress:g}%", border=True)
    cols[1].metric(t("runs.pass_rate", lang), "—" if s.pass_rate is None else f"{s.pass_rate:g}%", border=True)
    cols[2].metric(f"{STATUS_BADGES['passed']} {t('runs.status.passed', lang)}", s.passed, border=True)
    cols[3].metric(f"{STATUS_BADGES['failed']} {t('runs.status.failed', lang)}", s.failed, border=True)
    cols[4].metric(f"{STATUS_BADGES['blocked']} {t('runs.status.blocked', lang)}", s.blocked, border=True)
    cols[5].metric(f"{STATUS_BADGES['not_run']} {t('runs.status.not_run', lang)}", s.not_run, border=True)


def _results(lang: str, run: TestRun, titles: dict[str, str]) -> None:
    missing = [r.test_case_id for r in run.results if r.test_case_id not in titles]
    if missing:
        st.warning(t("runs.missing_cases", lang, ids=", ".join(missing)), icon="⚠️")
    st.dataframe(
        [
            {
                t("column.test_id", lang): r.test_case_id,
                t("column.title", lang): titles.get(r.test_case_id, t("runs.removed", lang)),
                t("column.status", lang): f"{STATUS_BADGES[r.status.value]} {t(f'runs.status.{r.status.value}', lang)}",
                t("runs.comment", lang): r.comment or "—",
                t("runs.bug_id", lang): r.bug_id or "—",
                t("runs.updated", lang): r.updated_at or "—",
            }
            for r in run.results
        ],
        hide_index=True, width="stretch",
    )


def _history(lang: str, runs: list[TestRun]) -> None:
    suites = {kind.value for kind in SuiteKind}
    rows = []
    for r in sorted(runs, key=lambda r: r.created_at, reverse=True):
        s = summarize(r)
        rows.append({
            t("runs.run", lang): r.id,
            t("runs.name", lang): r.name,
            t("runs.suite", lang): t(f"suites.{r.suite}", lang) if r.suite in suites else r.suite,
            t("runs.created", lang): r.created_at[:16].replace("T", " ") or "—",
            t("runs.environment", lang): r.environment or "—",
            t("runs.build", lang): r.build or "—",
            t("runs.progress", lang): f"{s.progress:g}%",
            t("runs.pass_rate", lang): "—" if s.pass_rate is None else f"{s.pass_rate:g}%",
        })
    with st.expander(t("runs.history", lang), icon=":material/history:"):
        st.dataframe(rows, hide_index=True, width="stretch")


def render_runs(lang: str, ws: Workspace, project_id: str, store: RunStore) -> None:
    """Start runs, record results, and see the figures and the history of this document's runs."""
    st.caption(t("runs.explainer", lang))
    if not ws.test_cases:
        st.info(t("runs.no_test_cases", lang))
        return
    _start_form(lang, ws, project_id, store)
    titles = {tc.id: tc.title for tc in ws.test_cases}
    runs = [r for r in store.runs(project_id) if r.document_hash == ws.document_hash]
    if not runs:
        st.info(t("runs.none", lang))
        return
    by_id = {r.id: r for r in runs}
    run_id = st.selectbox(
        t("runs.select", lang), sorted(by_id, reverse=True),
        format_func=lambda i: f"{i} · {by_id[i].name} · {by_id[i].created_at[:16].replace('T', ' ')}",
        key=f"run_select_{ws.document_hash}",
    )
    run = by_id[run_id]
    _record_form(lang, project_id, store, run, titles)
    run = next(r for r in store.runs(project_id) if r.id == run_id)  # figures after a save on this pass
    with theme_ui.card("runs"):
        theme_ui.section(t("runs.results_heading", lang), ":material/checklist:")
        _figures(lang, run)
        _results(lang, run, titles)
        st.download_button(t("runs.export_csv", lang), run_csv(run, titles, lang).encode("utf-8"),
                           file_name=f"{run.id}_results.csv", mime="text/csv", icon=":material/download:")
    _history(lang, runs)
