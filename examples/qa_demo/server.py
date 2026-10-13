"""Demo Shop: a tiny local web app for trying the QA Agent (standard library only).

    python examples/qa_demo/server.py            # http://127.0.0.1:8765
    python examples/qa_demo/server.py --port 9000

It has one deliberate bug, so a run shows a real FAIL: the contact form
accepts an empty email (REQ-4 in requirements.md says it must show
"Email is required"). /account has a "Delete account" button, which the QA
Agent refuses to click unless destructive actions are allowed, and
/go-elsewhere redirects (and /leak makes a page script call) to another local
port, which the egress policy blocks. /broken answers HTTP 500.

The home page links to all of these, so Autonomous QA discovery finds them:
the dashboard (sign-in required), the account page (destructive form, never
submitted), order history (/broken, a server error) and partner offers (the
off-site redirect, stopped). The contact form's Name field has maxlength=40.

The sign-in password is DEMO_PASSWORD (default "demo-pass-123"). Give the QA
Agent the same value as AUTOMATION_SECRET_DEMO_PASSWORD so it is typed from the
environment and never stored in the plan.
"""

import argparse
import html
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

USER_EMAIL = "demo@example.com"
USER_NAME = "Demo User"
SESSIONS: set[str] = set()
MAX_BODY = 10_000

STYLE = """<style>
body{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#1f2937}
nav a{margin-right:12px} label{display:block;margin-top:12px} input,textarea{width:100%;padding:6px}
button{margin-top:16px;padding:8px 16px} .error{color:#b91c1c} .success{color:#047857}
</style>"""


def page(title: str, body: str) -> bytes:
    nav = '<nav><a href="/">Home</a><a href="/login">Sign in</a><a href="/contact">Contact</a></nav>'
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{html.escape(title)}</title>{STYLE}"
            f"</head><body>{nav}{body}</body></html>").encode()


def login_form(error: str = "") -> bytes:
    message = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    return page("Sign in · Demo Shop", f"""<h1>Sign in</h1>{message}
<form method="post" action="/login">
<label for="email">Email</label><input id="email" name="email" type="email" autocomplete="username">
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password">
<button type="submit">Sign in</button></form>""")


def contact_form() -> bytes:
    return page("Contact · Demo Shop", """<h1>Contact us</h1>
<form method="post" action="/contact">
<label for="name">Name</label><input id="name" name="name" maxlength="40">
<label for="email">Email</label><input id="email" name="email" type="text">
<label for="message">Message</label><textarea id="message" name="message"></textarea>
<button type="submit">Send</button></form>""")


class Handler(BaseHTTPRequestHandler):
    server_version = "DemoShop/1.0"
    password = "demo-pass-123"
    other_port = 1

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - quiet test output
        return

    def _send(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, cookie: str = "") -> None:
        headers = {"Location": location}
        if cookie:
            headers["Set-Cookie"] = cookie
        self._send(b"", HTTPStatus.SEE_OTHER, headers)

    def _signed_in(self) -> bool:
        cookies = dict(
            part.strip().split("=", 1) for part in self.headers.get("Cookie", "").split(";") if "=" in part
        )
        return cookies.get("session", "") in SESSIONS

    def _form(self) -> dict[str, str]:
        length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
        data = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"), keep_blank_values=True)
        return {key: values[0] for key, values in data.items()}

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = urlsplit(self.path).path
        if path == "/":
            self._send(page("Demo Shop", "<h1>Demo Shop</h1><p>Welcome to the demo store.</p>"
                            '<ul><li><a href="/dashboard">Your dashboard</a></li>'
                            '<li><a href="/account">Account settings</a></li>'
                            '<li><a href="/broken">Order history</a></li>'
                            '<li><a href="/go-elsewhere">Partner offers</a></li></ul>'))
        elif path == "/login":
            self._send(login_form())
        elif path == "/dashboard":
            if not self._signed_in():
                self._redirect("/login")
                return
            self._send(page("Dashboard · Demo Shop", f"<h1>Dashboard</h1><p>Welcome, {USER_NAME}</p>"
                            '<p><a href="/account">Account settings</a></p>'))
        elif path == "/contact":
            self._send(contact_form())
        elif path == "/account":
            self._send(page("Account · Demo Shop", '<h1>Account</h1><form method="post" action="/account/delete">'
                            '<button type="submit" id="danger">Delete account</button></form>'))
        elif path == "/go-elsewhere":
            self._redirect(f"http://127.0.0.1:{self.other_port}/")
        elif path == "/leak":
            # A page script and an image that try to reach another local service (blocked by the egress policy).
            target = f"http://127.0.0.1:{self.other_port}/steal"
            self._send(page("Leak test · Demo Shop", f'<h1>Leak test</h1><img src="{target}.png" alt="">'
                            f"<script>fetch('{target}').catch(() => {{}});</script>"))
        elif path == "/broken":
            self._send(page("Error", "<h1>Internal error</h1>"), HTTPStatus.INTERNAL_SERVER_ERROR)
        else:
            self._send(page("Not found", "<h1>Not found</h1>"), HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        path = urlsplit(self.path).path
        form = self._form()
        if path == "/login":
            if form.get("email") == USER_EMAIL and secrets.compare_digest(form.get("password", ""), self.password):
                token = secrets.token_hex(16)
                SESSIONS.add(token)
                self._redirect("/dashboard", f"session={token}; HttpOnly; SameSite=Lax; Path=/")
            else:
                self._send(login_form("Invalid email or password"), HTTPStatus.UNAUTHORIZED)
        elif path == "/contact":
            name = form.get("name", "").strip() or "friend"
            # BUG (deliberate): the email is not validated. REQ-4 requires "Email is required" when it is empty.
            self._send(page("Contact · Demo Shop", f'<h1>Contact us</h1><p class="success" role="status">'
                            f"Thanks, {html.escape(name)}! We will reply soon.</p>"))
        elif path == "/account/delete":
            self._send(page("Account deleted", "<h1>Your account was deleted</h1>"))
        else:
            self._send(page("Not found", "<h1>Not found</h1>"), HTTPStatus.NOT_FOUND)


def make_server(port: int = 8765, host: str = "127.0.0.1", password: str | None = None,
                other_port: int = 1) -> ThreadingHTTPServer:
    handler = type("DemoHandler", (Handler,), {
        "password": password or os.environ.get("DEMO_PASSWORD") or Handler.password,
        "other_port": other_port,
    })
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = make_server(args.port, args.host)
    print(f"Demo Shop on http://{args.host}:{args.port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
