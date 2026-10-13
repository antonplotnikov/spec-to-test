"""Website discovery for Autonomous QA: a read-only crawl of an authorized site.

What discovery does (Python Playwright, Chromium, headless):
- opens the start page and follows links on the allowed hosts, breadth first,
  within QA_DISCOVERY_MAX_PAGES / _MAX_DEPTH / _TIMEOUT;
- reads each page with one fixed extraction script (title, headings, links,
  forms with their fields and buttons) and records every fact as Evidence.

What it never does:
- type, click, submit or open anything other than plain GET links. Requests
  other than GET/HEAD (for example a page script posting data) are aborted;
- open a link whose text or address contains a destructive or consequential
  word (delete, pay, ...) or signs out;
- leave the allowed hosts: the same egress policy as test runs (pinned DNS,
  dead proxy for everything else, every main-frame navigation and redirect
  checked) applies, so a redirect elsewhere is recorded and stopped;
- read field values, cookies or storage. Page text is untrusted data: it is
  clipped, redacted and stored as text, never followed as an instruction.

`ingest` turns one page snapshot into records without a browser, so the rules
are tested directly; `Discoverer` drives the browser.
"""

import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from spec_to_test.automation.security import (
    BLOCKING_PROXY,
    EgressPolicy,
    Redactor,
    UrlRejected,
    check_navigation,
    destructive_term,
)
from spec_to_test.qa_agent.auto_models import (
    MAX_SNIPPET,
    AutoSession,
    DiscoveryState,
    Evidence,
    EvidenceKind,
    FieldInfo,
    FormInfo,
    FormKind,
    LinkInfo,
    PageInfo,
    QueueItem,
)
from spec_to_test.qa_agent.executor import INTERNAL_SCHEMES, clean_error, now
from spec_to_test.qa_agent.safety import QASettings
from spec_to_test.qa_agent.steps import StepError, parse_locator

MAX_LINKS_KEPT = 60
MAX_FORMS_PER_PAGE = 10
MAX_FIELDS_PER_FORM = 25
MAX_BLOCKED = 20
# The extraction script also limits these, but a page can tamper with the JavaScript
# built-ins it uses: the Python side never trusts the sizes it receives.
MAX_LINKS_READ = 1000
MAX_BUTTONS_READ = 50
MAX_HEADINGS_READ = 100
MAX_EVIDENCE = 3000
CSS_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,80}$")
CSS_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,80}$")
# Links that end a session or change state, even though they are plain links.
SIGN_OUT = re.compile(r"(?<!\w)(log ?out|sign ?out|log ?off|вийти|выйти|выход|вихід)(?!\w)", re.I)
ROLE_NAME_UNSAFE = re.compile(r"[\]\"'\n]")
SEARCH_WORDS = re.compile(r"(?<!\w)(search|find|query|пошук|знайти|поиск|найти)", re.I)

# The only script discovery runs in a page. It reads structure, never values.
EXTRACT_JS = """(max) => {
  const clip = (s, n) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, n || 200);
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const labelOf = el => {
    if (el.labels && el.labels.length) return clip(el.labels[0].innerText);
    const aria = el.getAttribute('aria-label');
    if (aria) return clip(aria);
    const by = el.getAttribute('aria-labelledby');
    const ref = by && document.getElementById(by.split(' ')[0]);
    return ref ? clip(ref.innerText) : '';
  };
  const skip = ['hidden', 'submit', 'button', 'image', 'reset', 'file'];
  const fieldOf = e => ({
    tag: e.tagName.toLowerCase(), type: (e.type || '').toLowerCase(), name: clip(e.name, 80), id: clip(e.id, 80),
    label: labelOf(e), placeholder: clip(e.getAttribute('placeholder')), required: !!e.required,
    maxlength: e.maxLength > 0 ? e.maxLength : null, minlength: e.minLength > 0 ? e.minLength : null,
    options: e.tagName === 'SELECT' ? [...e.options].slice(0, 20).map(o => clip(o.text, 80)) : [],
  });
  const buttonName = b => clip(b.innerText || b.value || b.getAttribute('aria-label') || b.title);
  const headings = [...document.querySelectorAll('h1, h2, h3')].filter(visible).slice(0, max)
    .map(h => ({level: Number(h.tagName[1]), text: clip(h.innerText)}));
  const links = [...document.querySelectorAll('a[href]')].filter(visible).slice(0, max).map(a => ({
    text: clip(a.innerText || a.getAttribute('aria-label') || a.title), href: a.href,
    nav: !!a.closest('nav, [role=navigation]'),
  }));
  const forms = [...document.forms].filter(visible).slice(0, 10).map(f => ({
    name: clip(f.getAttribute('aria-label') || f.getAttribute('name') || f.id, 80),
    action: f.action, method: (f.getAttribute('method') || 'get').toLowerCase(),
    search: f.getAttribute('role') === 'search' || !!f.closest('[role=search]'),
    fields: [...f.elements].filter(e => ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.tagName)
      && !skip.includes((e.type || '').toLowerCase()) && visible(e)).slice(0, 25).map(fieldOf),
    submits: [...f.querySelectorAll('button:not([type=button]):not([type=reset]), input[type=submit]')]
      .filter(visible).map(buttonName),
  }));
  const buttons = [...document.querySelectorAll('button, [role=button], input[type=button]')]
    .filter(b => !b.form && visible(b)).slice(0, 50).map(buttonName);
  return {title: clip(document.title), headings, links, forms, buttons};
}"""


def path_of(url: str) -> str:
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def normalize(url: str) -> str:
    """Without the fragment; "" when it is not an http(s) URL."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, limit: int = MAX_SNIPPET) -> str:
    return " ".join(str(value or "")[: limit * 4].split())[:limit]


def role_locator(role: str, name: str) -> str:
    """`role=<role>[name=<name>]`, or "" when the name cannot be written safely."""
    if not name or ROLE_NAME_UNSAFE.search(name) or len(name) > 120:
        return ""
    locator = f"role={role}[name={name}]"
    try:
        parse_locator(locator)
    except StepError:
        return ""
    return locator


def _field_locator(field: dict[str, Any], counts: dict[str, int]) -> str:
    """A locator that should find exactly this field, preferring what a person sees."""
    label, placeholder = _text(field.get("label"), 120), _text(field.get("placeholder"), 120)
    candidates = []
    if label and counts.get(f"label:{label}", 0) == 1:
        candidates.append(f"label={label}")
    if placeholder and counts.get(f"placeholder:{placeholder}", 0) == 1:
        candidates.append(f"placeholder={placeholder}")
    if CSS_ID.match(field.get("id") or ""):
        candidates.append(f"#{field['id']}")
    name = field.get("name") or ""
    if CSS_NAME.match(name) and counts.get(f"name:{name}", 0) == 1:
        candidates.append(f"[name=\"{name}\"]")
    for candidate in candidates:
        try:
            parse_locator(candidate)
        except StepError:
            continue
        return candidate
    return ""


def form_kind(fields: list[FieldInfo], search_marked: bool, method: str, name: str, submit: str) -> FormKind:
    passwords = sum(f.type == "password" for f in fields)
    if passwords == 1:
        return FormKind.LOGIN
    if passwords > 1:
        return FormKind.ACCOUNT
    texts = [f for f in fields if f.tag != "select" and f.type not in ("checkbox", "radio")]
    if search_marked or any(f.type == "search" for f in fields) or (
        method == "get" and len(texts) == 1 and SEARCH_WORDS.search(f"{name} {submit} {texts[0].display}")
    ):
        return FormKind.SEARCH
    return FormKind.GENERIC


class Recorder:
    """Adds pages, forms, evidence and queued links to a session, numbering them."""

    def __init__(self, session: AutoSession, policy: EgressPolicy, redact: Callable[[str], str], max_pages: int,
                 max_depth: int) -> None:
        self.session = session
        self.policy = policy
        self.redact = redact
        self.max_pages = max_pages
        self.max_depth = max_depth

    def evidence(self, kind: EvidenceKind, url: str, text: str = "", locator: str = "", **detail: str) -> str:
        """The new evidence ID, or "" once the session holds MAX_EVIDENCE items."""
        if len(self.session.evidence) >= MAX_EVIDENCE:
            return ""
        evidence_id = f"EV-{len(self.session.evidence) + 1:03d}"
        self.session.evidence.append(Evidence(
            id=evidence_id, kind=kind, url=self.redact(url)[:2048], text=self.redact(_text(text)),
            locator=locator[:MAX_SNIPPET], detail={k: self.redact(_text(v)) for k, v in detail.items()},
        ))
        return evidence_id

    def known(self, url: str) -> bool:
        return any(p.url == url or p.final_url == url for p in self.session.pages) or any(
            q.url == url for q in self.session.queue
        )

    def enqueue(self, url: str, depth: int, linked_from: str = "", link_text: str = "") -> str:
        """"" when queued; otherwise why not (a LinkInfo.skipped code)."""
        if self.known(url):
            return ""
        if depth > self.max_depth:
            return "depth"
        if len(self.session.pages) + len(self.session.queue) >= self.max_pages:
            return "limit"
        self.session.queue.append(QueueItem(url=url, depth=depth, linked_from=linked_from, link_text=link_text))
        return ""

    def blocked_page(self, item: QueueItem, error: str, target: str = "") -> PageInfo:
        page = PageInfo(url=item.url, path=path_of(item.url), depth=item.depth, error=error,
                        linked_from=item.linked_from, link_text=_text(item.link_text, 120))
        page.evidence_id = self.evidence(EvidenceKind.BLOCKED, item.url, item.link_text, reason=error,
                                         target=target, linked_from=item.linked_from)
        self.session.pages.append(page)
        return page

    def ingest(self, item: QueueItem, status: int, final_url: str, snapshot: dict[str, Any],
               redirected_from: str = "", console: list[str] | None = None,
               blocked: list[str] | None = None) -> PageInfo:
        """Record one page read by EXTRACT_JS."""
        redact = self.redact
        final_url = normalize(final_url) or item.url
        title = redact(_text(snapshot.get("title"), 200))
        headings = [h for h in _list(snapshot.get("headings"))[:MAX_HEADINGS_READ] if isinstance(h, dict)]
        h1 = next((redact(_text(h.get("text"), 200)) for h in headings if h.get("level") == 1), "")
        page = PageInfo(
            url=item.url, final_url=redact(final_url), path=path_of(final_url), depth=item.depth, status=status,
            title=title, h1=h1, headings=[redact(_text(h.get("text"), 200)) for h in headings][:30],
            redirected_from=redact(redirected_from), linked_from=item.linked_from,
            link_text=_text(item.link_text, 120), console_errors=[redact(c)[:300] for c in console or []][:20],
            blocked_requests=[redact(b)[:300] for b in blocked or []][:MAX_BLOCKED],
        )
        page.evidence_id = self.evidence(EvidenceKind.PAGE, final_url, title, status=str(status), path=page.path,
                                         requested=item.url if redirected_from else "")
        if redirected_from:
            self.evidence(EvidenceKind.REDIRECT, final_url, "", source=redirected_from, target=page.path)
        if h1:
            self.evidence(EvidenceKind.HEADING, final_url, h1, role_locator("heading", h1), level="1")
        self.session.pages.append(page)  # before its links, so a link back to this page is not queued
        self._links(page, _list(snapshot.get("links"))[:MAX_LINKS_READ], item.depth)
        forms = [f for f in _list(snapshot.get("forms"))[:MAX_FORMS_PER_PAGE] if isinstance(f, dict)]
        page.has_password = any(isinstance(field, dict) and field.get("type") == "password"
                                for form in forms for field in _list(form.get("fields"))[:MAX_FIELDS_PER_FORM])
        self._forms(page, forms)
        for button in _list(snapshot.get("buttons"))[:MAX_BUTTONS_READ]:
            name = redact(_text(button, 120))
            if name and name not in page.buttons:
                page.buttons.append(name)
                if term := destructive_term(name):
                    self.evidence(EvidenceKind.BUTTON, final_url, name, role_locator("button", name),
                                  destructive=term)
        return page

    def _links(self, page: PageInfo, links: list[Any], depth: int) -> None:
        nav: list[str] = []
        seen: set[str] = set()
        for raw in links:
            if not isinstance(raw, dict):
                continue
            text = self.redact(_text(raw.get("text"), 120))
            url = normalize(str(raw.get("href") or ""))
            if not url:
                continue  # mailto:, tel:, javascript: ... are never opened
            if url in seen:
                continue
            seen.add(url)
            link = LinkInfo(text=text, url=self.redact(url), in_nav=bool(raw.get("nav")))
            if not self.policy.allows(url):
                link.skipped = "external"
            elif (term := destructive_term(f"{text} {path_of(url).replace('/', ' ').replace('-', ' ')}")) or (
                SIGN_OUT.search(f"{text} {path_of(url).replace('-', ' ')}")
            ):
                link.skipped = "destructive"
                self.evidence(EvidenceKind.LINK, page.final_url, text, role_locator("link", text),
                              href=path_of(url), destructive=term or "sign out")
            else:
                link.skipped = self.enqueue(url, depth + 1, page.final_url, text)
            if link.in_nav and text:
                nav.append(f"{text} → {path_of(url) if link.skipped != 'external' else url}")
            if len(page.links) < MAX_LINKS_KEPT:
                page.links.append(link)
        if nav:
            self.evidence(EvidenceKind.NAVIGATION, page.final_url, "; ".join(nav))

    def _forms(self, page: PageInfo, forms: list[Any]) -> None:
        raw_forms = [f for f in forms if isinstance(f, dict)][:MAX_FORMS_PER_PAGE]
        counts: dict[str, int] = {}
        for raw in raw_forms:
            for field in _list(raw.get("fields"))[:MAX_FIELDS_PER_FORM]:
                if not isinstance(field, dict):
                    continue
                for key in ("label", "placeholder", "name"):
                    if value := _text(field.get(key), 120):
                        counts[f"{key}:{value}"] = counts.get(f"{key}:{value}", 0) + 1
        submit_counts: dict[str, int] = {}
        for raw in raw_forms:
            for name in _list(raw.get("submits"))[:MAX_BUTTONS_READ]:
                submit_counts[_text(name, 120)] = submit_counts.get(_text(name, 120), 0) + 1
        for name in page.buttons:
            submit_counts[name] = submit_counts.get(name, 0) + 1
        for raw in raw_forms:
            # A form without its own name is named after the page heading when it is the page's only form.
            fallback = page.h1 if len(raw_forms) == 1 else ""
            self._form(page, raw, counts, submit_counts, fallback)

    def _form(self, page: PageInfo, raw: dict[str, Any], counts: dict[str, int], submit_counts: dict[str, int],
              fallback_name: str = "") -> None:
        redact = self.redact
        fields = []
        for field in _list(raw.get("fields"))[:MAX_FIELDS_PER_FORM]:
            if not isinstance(field, dict):
                continue
            info = FieldInfo(
                tag=_text(field.get("tag"), 20) or "input", type=_text(field.get("type"), 20),
                name=redact(_text(field.get("name"), 80)), label=redact(_text(field.get("label"), 120)),
                placeholder=redact(_text(field.get("placeholder"), 120)), required=bool(field.get("required")),
                maxlength=field["maxlength"] if isinstance(field.get("maxlength"), int) else None,
                minlength=field["minlength"] if isinstance(field.get("minlength"), int) else None,
                options=[redact(_text(o, 80)) for o in _list(field.get("options"))[:20]],
                locator=_field_locator(field, counts),
            )
            fields.append(info)
        submits = [_text(s, 120) for s in _list(raw.get("submits"))[:MAX_BUTTONS_READ] if _text(s, 120)]
        submit = redact(submits[0]) if submits else ""
        action = normalize(str(raw.get("action") or "")) or page.final_url
        method = "post" if str(raw.get("method")).lower() == "post" else "get"
        name = redact(_text(raw.get("name"), 80)) or fallback_name[:80]
        signature = (path_of(action), method, tuple(f.name or f.display for f in fields), submit)
        for existing in self.session.forms:  # the same form on several pages (a header search box)
            if (path_of(existing.action), existing.method, tuple(f.name or f.display for f in existing.fields),
                    existing.submit_label) == signature:
                page.form_ids.append(existing.id)
                return
        form = FormInfo(
            id=f"F-{len(self.session.forms) + 1:03d}", page_url=page.final_url, name=name,
            action=redact(action), method=method, fields=fields, submit_label=submit,
            submit_locator=role_locator("button", submit) if submit_counts.get(submit, 0) == 1 else "",
            destructive_term=destructive_term(f"{submit} {name}") or "",
        )
        form.kind = form_kind(fields, bool(raw.get("search")), method, name, submit)
        form.evidence_id = self.evidence(
            EvidenceKind.FORM, page.final_url, form.display, form.submit_locator, method=method,
            action=path_of(action), fields=", ".join(f.display for f in fields), submit=submit, form_kind=form.kind.value,
        )
        for field in fields:
            attributes = {"type": field.type or field.tag, "required": "yes" if field.required else "no"}
            if field.maxlength is not None:
                attributes["maxlength"] = str(field.maxlength)
            if field.minlength is not None:
                attributes["minlength"] = str(field.minlength)
            field.evidence_id = self.evidence(EvidenceKind.FIELD, page.final_url, field.display, field.locator,
                                              form=form.id, **attributes)
        self.session.forms.append(form)
        page.form_ids.append(form.id)


class Discoverer:
    """Opens the queued pages of a session in a headless browser and records them."""

    def __init__(self, settings: QASettings, policy: EgressPolicy, clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        self.limits = settings.limits
        self.policy = policy
        self.redact: Redactor = settings.redactor()
        self.clock = clock
        self._pw: Any = None
        self._browser: Any = None

    def _launch(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=self.policy.browser_args(),
            proxy={"server": BLOCKING_PROXY, "bypass": ",".join(["<-loopback>", self.policy.proxy_bypass()])},
            chromium_sandbox=self.settings.automation.chromium_sandbox,
            timeout=60_000,
        )

    def close(self) -> None:
        for closer in (lambda: self._browser and self._browser.close(), lambda: self._pw and self._pw.stop()):
            try:
                closer()
            except Exception:  # noqa: BLE001, S110 - cleanup must not hide the result
                pass
        self._browser = self._pw = None

    def recorder(self, session: AutoSession) -> Recorder:
        return Recorder(session, self.policy, self.redact, self.limits.discovery_max_pages,
                        self.limits.discovery_max_depth)

    def run(self, session: AutoSession, on_page: Callable[[AutoSession, PageInfo], None] | None = None) -> AutoSession:
        """Crawl until the queue is empty or a limit is reached. Keeps what was found on any error."""
        recorder = self.recorder(session)
        if not session.pages and not session.queue:
            recorder.enqueue(self.policy.base_url, 0)
        deadline = self.clock() + self.limits.discovery_timeout_s
        session.state = DiscoveryState.RUNNING
        try:
            self._launch()
            session.browser = f"Chromium {self._browser.version}"
            context = self._browser.new_context(
                accept_downloads=False, service_workers="block", java_script_enabled=True,
                ignore_https_errors=self.settings.automation.ignore_https_errors,
                viewport={"width": 1280, "height": 800}, locale="en-US",
            )
            context.set_default_timeout(self.limits.step_timeout_ms)
            context.set_default_navigation_timeout(self.limits.nav_timeout_ms)
            blocked: list[str] = []

            def guard(route: Any) -> None:
                request = route.request
                url = request.url
                internal = url.startswith(INTERNAL_SCHEMES)
                if (internal or self.policy.allows(url)) and request.method in ("GET", "HEAD"):
                    route.continue_()
                    return
                if len(blocked) < MAX_BLOCKED:
                    blocked.append(f"{request.method} {self.redact(url)[:300]}")
                route.abort("blockedbyclient")

            context.route("**/*", guard)
            while session.queue:
                if len(session.pages) >= self.limits.discovery_max_pages:
                    self._left_over(session)  # the page limit is reached
                    break
                if self.clock() >= deadline:
                    session.state = DiscoveryState.INTERRUPTED  # resumable: the queue is kept
                    session.error = "timeout"
                    return session
                item = session.queue[0]
                blocked.clear()
                page = self._visit(context, recorder, item, blocked)
                session.queue.pop(0)
                if on_page:
                    on_page(session, page)
            session.state = DiscoveryState.COMPLETED
            session.error = ""
        except Exception as exc:  # noqa: BLE001 - keep the pages found so far; resumable
            session.state = DiscoveryState.INTERRUPTED if session.pages else DiscoveryState.FAILED
            session.error = clean_error(str(exc), self.redact)
        finally:
            self.close()
            session.updated_at = now()
        return session

    @staticmethod
    def _left_over(session: AutoSession) -> None:
        """Mark the links still queued as not opened because of the page limit."""
        left = {item.url for item in session.queue}
        for page in session.pages:
            for link in page.links:
                if link.url in left and not link.skipped:
                    link.skipped = "limit"
        session.queue.clear()

    def _visit(self, context: Any, recorder: Recorder, item: QueueItem, blocked: list[str]) -> PageInfo:
        from playwright.sync_api import Error as PlaywrightError

        try:
            url = check_navigation(item.url, self.policy)
        except UrlRejected as rejected:
            return recorder.blocked_page(item, "url_blocked", rejected.code)
        page = context.new_page()
        off_policy: list[str] = []
        console: list[str] = []

        def on_request(request: Any) -> None:
            if request.is_navigation_request() and request.frame == page.main_frame:
                target = request.url
                if not target.startswith(INTERNAL_SCHEMES) and not self.policy.allows(target):
                    off_policy.append(target)

        page.on("request", on_request)
        page.on("console", lambda m: console.append(m.text) if m.type == "error" and len(console) < 20 else None)
        page.on("pageerror", lambda e: console.append(str(e)) if len(console) < 20 else None)
        page.on("dialog", lambda dialog: dialog.dismiss())
        try:
            try:
                response = page.goto(url, wait_until="load")
            except PlaywrightError as exc:
                if off_policy:
                    return recorder.blocked_page(item, "redirect_blocked", self.redact(off_policy[0])[:300])
                return recorder.blocked_page(item, "load_failed", clean_error(str(exc), self.redact)[:300])
            if off_policy or not self.policy.allows(page.url):
                return recorder.blocked_page(item, "redirect_blocked", self.redact(off_policy[0] if off_policy else page.url))
            status = response.status if response is not None else 0
            redirected_from = path_of(item.url) if normalize(page.url) != normalize(url) else ""
            snapshot = page.evaluate(EXTRACT_JS, self.limits.discovery_max_elements)
            return recorder.ingest(item, status, page.url, snapshot if isinstance(snapshot, dict) else {},
                                   redirected_from, console, blocked)
        finally:
            try:
                page.close()
            except PlaywrightError:
                pass
