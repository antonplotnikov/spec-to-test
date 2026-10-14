"""Draft requirements from discovery evidence, without AI.

Each rule turns something discovery observed into a requirement and labels
how well the evidence supports it:

OBSERVED (confidence 80-95) the page itself shows it: a page opens with its
    title and heading, navigation links lead to their pages, a form has these
    fields, a field carries `required`, `type=email` or `maxlength`, a page
    sends a visitor to the sign-in page.
INFERRED (confidence 35-60) common practice, not stated by the site: a
    sign-in with wrong credentials is rejected, an email field of a contact
    form should not be accepted empty, a linked page should not answer with a
    server error. Each comes with a question for the reviewer.
UNKNOWN (confidence 0-20) the site does not show it: what a form does after
    a successful submission, what a destructive action does, where an
    external link should lead, how a sign-in succeeds. These are questions,
    not rules; an answer from the reviewer can make them testable.

No rule invents a business rule: every description names only what was
seen (labels, texts, addresses) and every requirement lists its evidence IDs.
IDs (WEB-001, ...) are stable: drafting again keeps existing requirements,
their decisions and edits, and only adds what is new.
"""

import json

from spec_to_test.i18n import t
from spec_to_test.qa_agent.auto_models import (
    AutoSession,
    Basis,
    DraftRequirement,
    EvidenceKind,
    FieldInfo,
    FormInfo,
    FormKind,
    PageInfo,
    ReqOrigin,
)
from spec_to_test.qa_agent.discovery import path_of, role_locator

MAX_REQUIREMENTS = 120
MAX_NAV_LINKS = 8
EMAIL_WORDS = ("email", "e-mail", "пошт", "почт")


def _q(value: str) -> str:
    return f"\"{value}\""


def is_email_like(field: FieldInfo) -> bool:
    text = f"{field.type} {field.name} {field.label} {field.placeholder}".casefold()
    return field.type == "email" or any(word in text for word in EMAIL_WORDS)


def nav_links(session: AutoSession, page: PageInfo) -> list[tuple[str, str]]:
    """(text, path) of navigation links that lead to a page discovery opened successfully."""
    ok = {p.url: p for p in session.pages if not p.error and 200 <= p.status < 400}
    names = [link.text for link in page.links]
    found: list[tuple[str, str]] = []
    for link in page.links:
        target = ok.get(link.url)
        if (link.in_nav and target is not None and link.text and names.count(link.text) == 1
                and role_locator("link", link.text) and not target.redirected_from):
            found.append((link.text, target.path))
    return found[:MAX_NAV_LINKS]


class Drafter:
    def __init__(self, session: AutoSession, lang: str) -> None:
        self.session = session
        self.lang = lang
        self.keys = {r.key for r in session.requirements}

    def add(self, key: str, basis: Basis, confidence: int, url: str, evidence: list[str], template: str,
            text_key: str, questions: list[str] | None = None, /, **params: str) -> None:
        if key in self.keys or len(self.session.requirements) >= MAX_REQUIREMENTS or not any(evidence):
            return  # no requirement without evidence
        numbers = [int(r.id.split("-")[1]) for r in self.session.requirements]
        description = t(f"qaauto.req.{text_key}", self.lang, **params)[:1000]
        self.session.requirements.append(DraftRequirement(
            id=f"WEB-{max(numbers, default=0) + 1:03d}", key=key[:400], description=description,
            original_description=description, basis=basis, confidence=confidence, url=url,
            evidence_ids=[e for e in evidence if e], questions=questions or [], origin=ReqOrigin.RULE,
            template=template, params={k: v for k, v in params.items()},
        ))
        self.keys.add(key)

    def question(self, key: str, **params: str) -> str:
        return t(f"qaauto.q.{key}", self.lang, **params)

    # --- Pages ---------------------------------------------------------------------

    def pages(self) -> None:
        for page in self.session.pages:
            link = _q(page.link_text) if page.link_text else page.path
            if page.error == "redirect_blocked":
                target = next((e.detail.get("target", "") for e in self.session.evidence
                               if e.id == page.evidence_id), "")
                self.add(f"external:{page.path}", Basis.UNKNOWN, 10, page.linked_from, [page.evidence_id], "",
                         "external", [self.question("external", link=link)], link=link, path=page.path,
                         target=target or "—")
                continue
            if page.error:
                continue
            if page.status >= 500:
                self.add(f"server_error:{page.path}", Basis.INFERRED, 60, page.final_url, [page.evidence_id],
                         "server_error", "server_error", [self.question("server_error", path=page.path)],
                         path=page.path, status=str(page.status), link=link)
                continue
            if page.status >= 400:
                self.add(f"broken:{page.path}", Basis.UNKNOWN, 20, page.final_url, [page.evidence_id], "",
                         "broken", [self.question("broken", link=link, status=str(page.status))],
                         path=page.path, status=str(page.status), link=link)
                continue
            if page.redirected_from and page.has_password:
                source = page.redirected_from
                self.add(f"auth:{source}", Basis.OBSERVED, 85, page.final_url, [page.evidence_id], "auth_redirect",
                         "auth_redirect", path=source, target=page.path)
                continue
            if page.redirected_from:
                continue  # the page itself is recorded under its own address
            heading = page.h1 if role_locator("heading", page.h1) else ""
            evidence = [page.evidence_id] + [e.id for e in self.session.evidence
                                             if e.kind == EvidenceKind.HEADING and e.url == page.final_url]
            if page.title and heading:
                text_key = "page_title_heading"
            elif page.title:
                text_key = "page_title"
            elif heading:
                text_key = "page_heading"
            else:
                text_key = "page_opens"
            self.add(f"page:{page.path}", Basis.OBSERVED, 90, page.final_url, evidence, "page", text_key,
                     path=page.path, title=page.title, heading=heading)
        for page in self.session.pages:
            if page.error or not (200 <= page.status < 400) or page.redirected_from:
                continue
            links = nav_links(self.session, page)
            if len(links) >= 2 and not any(r.key.startswith("nav:") for r in self.session.requirements):
                evidence = [e.id for e in self.session.evidence
                            if e.kind == EvidenceKind.NAVIGATION and e.url == page.final_url]
                self.add(f"nav:{page.path}", Basis.OBSERVED, 85, page.final_url, evidence, "nav", "nav",
                         path=page.path, links=", ".join(_q(text) for text, _ in links),
                         targets=json.dumps(links, ensure_ascii=False))
        self._destructive_actions()

    def _destructive_actions(self) -> None:
        for evidence in self.session.evidence:
            if evidence.kind not in (EvidenceKind.LINK, EvidenceKind.BUTTON) or not evidence.text:
                continue
            path = path_of(evidence.url)
            label = _q(evidence.text)
            self.add(f"destructive:{path}:{evidence.text}", Basis.UNKNOWN, 0, evidence.url, [evidence.id], "",
                     "destructive", [self.question("destructive", label=label)], label=label, path=path)

    # --- Forms ---------------------------------------------------------------------

    def forms(self) -> None:
        for form in self.session.forms:
            page = path_of(form.page_url)
            name = _q(form.display)
            usable = [f for f in form.fields if f.locator]
            evidence = [form.evidence_id] + [f.evidence_id for f in usable]
            if usable and form.submit_locator:
                self.add(f"form:{form.id}", Basis.OBSERVED, 90, form.page_url, evidence, "form_fields", "form_fields",
                         form=name, path=page, fields=", ".join(_q(f.display) for f in usable),
                         button=form.submit_label, form_id=form.id)
            if form.destructive_term:
                label = _q(form.submit_label or form.display)
                self.add(f"destructive_form:{form.id}", Basis.UNKNOWN, 0, form.page_url, [form.evidence_id], "",
                         "destructive", [self.question("destructive", label=label)], label=label, path=page)
                continue
            for field in usable:
                self._field_rules(form, field, name, page)
            self._form_behaviour(form, name, page)

    def _submittable(self, form: FormInfo, skip: FieldInfo | None = None) -> bool:
        """Every required field (other than `skip`) can be found, and so can the submit button."""
        return bool(form.submit_locator) and all(
            f.locator for f in form.fields if f.required and f is not skip and f.type != "password"
        )

    def _field_rules(self, form: FormInfo, field: FieldInfo, name: str, page: str) -> None:
        label = _q(field.display)
        common = {"form": name, "field": label, "path": page, "form_id": form.id, "field_locator": field.locator}
        evidence = [form.evidence_id, field.evidence_id]
        if form.kind == FormKind.SEARCH:
            return
        if field.maxlength is not None and field.maxlength < 1000 and field.tag != "select":
            self.add(f"maxlength:{form.id}:{field.locator}", Basis.OBSERVED, 90, form.page_url, evidence,
                     "maxlength", "maxlength", max=str(field.maxlength), **common)
        if form.kind != FormKind.GENERIC or not self._submittable(form, field):
            return
        if field.required and field.type not in ("checkbox", "radio"):
            self.add(f"required:{form.id}:{field.locator}", Basis.OBSERVED, 85, form.page_url, evidence,
                     "required", "required", **common)
        elif not field.required and is_email_like(field) and field.type not in ("checkbox", "radio"):
            self.add(f"required_inferred:{form.id}:{field.locator}", Basis.INFERRED, 40, form.page_url, evidence,
                     "required_inferred", "required_inferred",
                     [self.question("required_inferred", field=label, form=name)], **common)
        if field.type == "email":
            self.add(f"email:{form.id}:{field.locator}", Basis.OBSERVED, 80, form.page_url, evidence,
                     "email_format", "email_format", **common)

    def _form_behaviour(self, form: FormInfo, name: str, page: str) -> None:
        evidence = [form.evidence_id]
        if form.kind == FormKind.LOGIN:
            password = next((f for f in form.fields if f.type == "password"), None)
            user = next((f for f in form.fields if f.type != "password" and f.locator), None)
            if password and password.locator and user and form.submit_locator:
                self.add(f"login:{form.id}", Basis.INFERRED, 55, form.page_url, evidence, "login_rejects",
                         "login_rejects", [self.question("login")], path=page, form=name, form_id=form.id)
            self.add(f"signin:{form.id}", Basis.UNKNOWN, 10, form.page_url, evidence, "", "signin",
                     [self.question("signin")], path=page, form=name)
        elif form.kind in (FormKind.GENERIC, FormKind.ACCOUNT) and self._submittable(form):
            template = "submit_outcome" if form.kind == FormKind.GENERIC else ""
            self.add(f"submit:{form.id}", Basis.UNKNOWN, 15, form.page_url, evidence, template, "submit",
                     [self.question("submit", form=name)], path=page, form=name, form_id=form.id)


def draft_requirements(session: AutoSession, lang: str) -> int:
    """Add requirements for what discovery found; returns how many were added."""
    before = len(session.requirements)
    drafter = Drafter(session, lang)
    drafter.pages()
    drafter.forms()
    return len(session.requirements) - before
