"""Final report of an Autonomous QA session, and its export bundle.

The report states only what the session recorded: what discovery saw (with
evidence IDs), how each requirement is supported (observed / inferred /
unknown, confidence, decision, open questions), which cases test it, what the
latest run showed and which bug reports followed, as one traceability chain:

    Website evidence → Requirement → Test case → Execution result → Bug report

The bundle adds the session JSON (no cookies, passwords or tokens are ever
collected; page text was redacted when it was recorded) and the run's own
report bundle (results, bugs, screenshots).
"""

import io
import zipfile
from pathlib import Path

from spec_to_test.i18n import t
from spec_to_test.models import Requirement
from spec_to_test.qa_agent.auto_models import AutoSession, Decision
from spec_to_test.qa_agent.bugs import bug_markdown
from spec_to_test.qa_agent.discovery import path_of
from spec_to_test.qa_agent.models import QARun
from spec_to_test.qa_agent.report import _cell, bundle, reason_text
from spec_to_test.qa_agent.triage import outcomes


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(c) if str(c) else "—" for c in cells) + " |"


def final_report(session: AutoSession, run: QARun | None, lang: str = "en") -> str:

    def tr(key: str, **params: object) -> str:
        return t(f"qaauto.report.{key}", lang, **params)

    approved = [r for r in session.requirements if r.decision == Decision.APPROVED]
    lines = [
        f"# {tr('title')}",
        "",
        f"- {tr('target')}: {session.target_url}",
        f"- {tr('session')}: {session.id} · {tr('started')}: {session.created_at}",
        f"- {tr('discovery')}: {t(f'qaauto.state.{session.state.value}', lang)} · {tr('pages')}: {len(session.pages)}"
        f" · {tr('forms')}: {len(session.forms)} · {tr('evidence')}: {len(session.evidence)}",
        f"- {tr('browser')}: {session.browser or '—'}" + (f" · AI: {session.ai_model}" if session.ai_model else ""),
        f"- {tr('safety')}",
        "",
        f"## {tr('site_map')}",
        "",
        _row(tr('path'), tr('status'), tr('page_title'), tr('heading'), tr('forms'), tr('evidence')),
        "|---|---|---|---|---|---|",
    ]
    for page in session.pages:
        status = t(f"qaauto.page_error.{page.error}", lang) if page.error else str(page.status)
        path = f"{page.redirected_from} → {page.path}" if page.redirected_from else page.path
        lines.append(_row(path, status, page.title, page.h1, ", ".join(page.form_ids), page.evidence_id))
    skipped = [(p, link) for p in session.pages for link in p.links if link.skipped]
    if skipped:
        lines += ["", f"### {tr('not_opened')}", ""]
        for page, link in skipped[:60]:
            lines.append(f"- {page.path}: \"{_cell(link.text or link.url)}\" → {_cell(path_of(link.url))} "
                         f"({t(f'qaauto.skipped.{link.skipped}', lang)})")
    lines += [
        "",
        f"## {tr('requirements')}",
        "",
        _row("ID", tr('description'), tr('basis'), tr('confidence'), tr('decision'), tr('evidence'), tr('questions')),
        "|---|---|---|---|---|---|---|",
    ]
    for req in session.requirements:
        questions = " / ".join(req.questions) if not req.answer else f"{tr('answer')}: {req.answer}"
        lines.append(_row(req.id, req.description, t(f"qaauto.basis.{req.basis.value}", lang), f"{req.confidence}%",
                          t(f"qaauto.decision.{req.decision.value}", lang), ", ".join(req.evidence_ids), questions))
    found = outcomes(run, session) if run is not None else {}
    results = {r.case_id: r for r in run.results} if run is not None else {}
    lines += [
        "",
        f"## {tr('traceability')}",
        "",
        _row(tr('evidence'), tr('requirement'), tr('test_case'), tr('plan_case'), tr('result'), tr('outcome'),
             tr('bugs')),
        "|---|---|---|---|---|---|---|",
    ]
    for req in approved:
        cases = [c for c in session.cases if c.requirement_id == req.id and c.approved]
        if not cases:
            lines.append(_row(", ".join(req.evidence_ids), req.id, "—", "—", "—", "—", "—"))
        for case in cases:
            result = results.get(case.plan_case_id)
            bugs = [b.id for b in run.bugs if b.case_id == case.plan_case_id] if run is not None else []
            status = t(f"qaagent.status.{result.status.value}", lang) if result else "—"
            if result is not None and result.reason:
                status += f" ({reason_text(result.reason, result.reason_params, lang)})"
            outcome = t(f"qaauto.outcome.{found[case.plan_case_id].value}", lang) if case.plan_case_id in found else "—"
            lines.append(_row(", ".join(req.evidence_ids), req.id, f"{case.test_case_id or '—'} ({case.id})",
                              case.plan_case_id or "—", status, outcome, ", ".join(bugs)))
    if run is not None:
        counts = run.counts()
        lines += [
            "",
            f"## {tr('run')}",
            "",
            f"{tr('run_line', id=run.id, state=t(f'qaagent.state.{run.state.value}', lang))}",
            "",
            _row(*(t(f"qaagent.status.{s}", lang) for s in counts)),
            "|---|---|---|---|",
            _row(*counts.values()),
            "",
            f"## {t('qaagent.report.bug_reports', lang)}",
            "",
        ]
        lines += [bug_markdown(bug) for bug in run.bugs] or [t("qaagent.report.no_bugs", lang), ""]
    lines += ["", f"## {tr('limitations')}", "", tr("limitations_body"), ""]
    return "\n".join(lines) + "\n"


def final_bundle(session: AutoSession, run: QARun | None, run_dir: Path | None,
                 requirements: list[Requirement] | None, lang: str = "en") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("autonomous-report.md", final_report(session, run, lang))
        archive.writestr("session.json", session.model_dump_json(indent=2))
        if run is not None and run_dir is not None:
            archive.writestr(f"run-{run.id}.zip", bundle(run, run_dir, requirements, lang))
    return buffer.getvalue()
