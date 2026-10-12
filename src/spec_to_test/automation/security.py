"""Security controls for browser automation.

- Target URLs must be http(s), on an allowlisted host and port, without
  credentials, and every address the host resolves to must be public (or
  private when the operator allows internal staging). Link-local and cloud
  metadata addresses are always refused (SSRF protection).
- The browser can only reach vetted hosts: each one is pinned to the address
  that was checked (no DNS rebinding), every other host name fails to resolve,
  and everything not on the bypass list (including bare IP addresses) is sent
  to a proxy that does not exist. This holds for redirects and for requests
  made by page scripts, which origin filters alone do not cover.
- Secret values and API keys are masked in every text that is stored, shown,
  or sent to the model, including the text files inside Playwright traces.
- Actions that look destructive are refused unless the user allowed them.
"""

import ipaddress
import re
import socket
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel

from spec_to_test.automation.config import AutomationConfig, HostRule

Resolver = Callable[..., list[tuple]]
MAX_URL_LENGTH = 2048
# Unresolvable on purpose: traffic that is not on the bypass list goes nowhere.
BLOCKING_PROXY = "http://egress-blocked.invalid:9"
METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),  # AWS, GCP, Azure, OpenStack
    ipaddress.ip_address("169.254.170.2"),  # AWS ECS task metadata
    ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud
    ipaddress.ip_address("fd00:ec2::254"),  # AWS IPv6
}


class UrlRejected(Exception):
    """A URL that may not be opened. `code` maps to automation.url.<code>."""

    def __init__(self, code: str, **params: str) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


class PinnedHost(BaseModel):
    host: str
    ip: str
    ports: list[int]


class EgressPolicy(BaseModel):
    """Where the browser may connect during one job."""

    base_url: str
    origin: str
    hosts: list[PinnedHost]

    def host_names(self) -> list[str]:
        return [h.host for h in self.hosts]

    def resolver_rules(self) -> str:
        rules = [f"MAP {h.host} {h.ip}" for h in self.hosts]
        return ", ".join([*rules, "MAP * ~NOTFOUND"])

    def proxy_bypass(self) -> str:
        """Direct connections only to vetted host:port pairs; the rest hits the dead proxy."""
        entries = []
        for h in self.hosts:
            host = f"[{h.host}]" if ":" in h.host else h.host
            entries += [f"{host}:{port}" for port in h.ports]
        return ",".join(entries)

    def allowed_origins(self) -> list[str]:
        origins = []
        for h in self.hosts:
            host = f"[{h.host}]" if ":" in h.host else h.host
            for port in h.ports:
                scheme = "http" if port == 80 else "https" if port == 443 else None
                if scheme:
                    origins.append(f"{scheme}://{host}")
                else:
                    origins += [f"http://{host}:{port}", f"https://{host}:{port}"]
        return origins

    def browser_args(self) -> list[str]:
        return [f"--host-resolver-rules={self.resolver_rules()}"]

    def allows(self, url: str) -> bool:
        try:
            scheme, host, port = _split(url)
        except UrlRejected:
            return False
        return scheme in ("http", "https") and any(h.host == host and port in h.ports for h in self.hosts)


def _split(url: str) -> tuple[str, str, int]:
    if len(url) > MAX_URL_LENGTH:
        raise UrlRejected("too_long")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise UrlRejected("invalid") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UrlRejected("scheme")
    if parts.username is not None or parts.password is not None:
        raise UrlRejected("credentials")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UrlRejected("invalid")
    if not _is_ip(host):
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise UrlRejected("invalid") from None
    return scheme, host, port or (443 if scheme == "https" else 80)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def address_problem(ip_text: str, allow_private: bool) -> str | None:
    """Return why an address may not be contacted, or None when it is fine."""
    ip = ipaddress.ip_address(ip_text.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip in METADATA_ADDRESSES or ip.is_link_local:
        return "metadata"
    # 0.0.0.0 reaches the local machine on Linux: never allowed, even for internal staging.
    if ip.is_multicast or ip.is_unspecified:
        return "reserved"
    if ip.is_loopback or ip.is_private:  # checked before is_reserved: ::1 is both
        return None if allow_private else "private"
    if ip.is_reserved:
        return "reserved"
    if not ip.is_global:
        return None if allow_private else "private"
    return None


def resolve(host: str, port: int, resolver: Resolver = socket.getaddrinfo) -> list[str]:
    if _is_ip(host):
        return [host]
    try:
        infos = resolver(host, port, 0, socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise UrlRejected("dns", host=host) from None
    addresses = list(dict.fromkeys(str(info[4][0]) for info in infos))
    if not addresses:
        raise UrlRejected("dns", host=host)
    return addresses


def _vet(host: str, port: int, config: AutomationConfig, resolver: Resolver) -> str:
    """Resolve a host and check every address; return the address to pin."""
    addresses = resolve(host, port, resolver)
    for address in addresses:
        if problem := address_problem(address, config.allow_private_network):
            raise UrlRejected(problem, host=host)
    return addresses[0]


def matching_rule(host: str, port: int, rules: Iterable[HostRule]) -> HostRule | None:
    return next((rule for rule in rules if rule.matches(host, port)), None)


def build_egress_policy(
    url: str, config: AutomationConfig, resolver: Resolver = socket.getaddrinfo
) -> EgressPolicy:
    """Validate the target URL and pin every host the browser may contact."""
    scheme, host, port = _split(url)
    if matching_rule(host, port, config.allowed_hosts) is None:
        raise UrlRejected("not_allowed", host=host)
    pinned = {host: PinnedHost(host=host, ip=_vet(host, port, config, resolver), ports=[port])}
    # Other exact allowlist entries (e.g. a staging login server) are reachable too,
    # if they pass the same checks. Wildcard entries only ever admit the target itself.
    for rule in config.allowed_hosts:
        if rule.wildcard or rule.host in pinned:
            if rule.host in pinned and rule.port is not None and rule.port not in pinned[rule.host].ports:
                pinned[rule.host].ports.append(rule.port)
            continue
        ports = [rule.port] if rule.port is not None else [80, 443]
        try:
            pinned[rule.host] = PinnedHost(host=rule.host, ip=_vet(rule.host, ports[0], config, resolver), ports=ports)
        except UrlRejected:
            continue  # unreachable or unsafe extra hosts are simply not allowed
    origin = f"{scheme}://{host}" + ("" if port in (80, 443) else f":{port}")
    return EgressPolicy(base_url=url.strip(), origin=origin, hosts=list(pinned.values()))


def check_navigation(url: str, policy: EgressPolicy) -> str:
    """Absolute URL for a navigation, or UrlRejected. Relative paths use the target origin."""
    url = url.strip()
    if url.startswith("/") and not url.startswith("//"):
        url = policy.origin + url
    if not policy.allows(url):
        try:
            _, host, _ = _split(url)
        except UrlRejected as exc:
            raise exc from None
        raise UrlRejected("not_allowed", host=host)
    return url


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_GENERIC_SECRETS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)\b(authorization|cookie|set-cookie|x-api-key)\s*[:=]\s*[^\r\n]+"),
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)(\"?\s*[:=]\s*\"?)[^\s\"',;&]{3,}"),
]


class Redactor:
    """Masks configured secret values and well-known credential formats."""

    def __init__(self, secrets: dict[str, str] | None = None, extra: Iterable[str] = ()) -> None:
        pairs = [(value, f"[redacted:{name}]") for name, value in (secrets or {}).items()]
        pairs += [(value, "[redacted]") for value in extra]
        # Longest first, so a secret that contains another is masked whole.
        self._pairs = sorted(((v, r) for v, r in pairs if v and len(v) >= 3), key=lambda p: -len(p[0]))

    def __call__(self, text: str) -> str:
        if not text:
            return text
        for value, replacement in self._pairs:
            text = text.replace(value, replacement)
        for pattern in _GENERIC_SECRETS:
            text = pattern.sub(_mask, text)
        return text

    def contains_secret(self, text: str) -> bool:
        return any(value in text for value, _ in self._pairs)

    def redact_file(self, path: Path) -> None:
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        cleaned = self(original)
        if cleaned != original:
            path.write_text(cleaned, encoding="utf-8")

    def redact_zip(self, path: Path) -> None:
        """Mask secrets in the text entries of a Playwright trace (actions, network log)."""
        if not self._pairs:
            return
        tmp = path.with_suffix(".redacting")
        try:
            with zipfile.ZipFile(path) as source, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as target:
                for info in source.infolist():
                    data = source.read(info)
                    if info.filename.endswith((".trace", ".network", ".stacks", ".json", ".txt", ".html")):
                        text = data.decode("utf-8", errors="surrogateescape")
                        for value, replacement in self._pairs:
                            text = text.replace(value, replacement)
                        data = text.encode("utf-8", errors="surrogateescape")
                    target.writestr(info, data)
            tmp.replace(path)
        except (OSError, zipfile.BadZipFile):
            tmp.unlink(missing_ok=True)


def _mask(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 2:  # keep "password=" and mask the value
        return f"{match.group(1)}{match.group(2)}[redacted]"
    if match.lastindex == 1:
        return f"{match.group(1)} [redacted]"
    return "[redacted]"


# ---------------------------------------------------------------------------
# Destructive actions
# ---------------------------------------------------------------------------

# Word starts in English, Ukrainian and Russian. "Cancel" or "reset" alone are not
# on the list: closing a dialog or resetting a password is ordinary test work.
DESTRUCTIVE_TERMS = (
    r"delet", r"remov", r"destroy", r"erase", r"purg", r"wipe", r"drop\b", r"truncat",
    r"deactivat", r"terminat", r"revok", r"unsubscrib", r"close (my )?account",
    r"cancel (my |the )?(subscription|order|booking|account|plan)",
    r"pay\b", r"payment", r"purchas", r"buy\b", r"checkout", r"check out",
    r"(place|submit|confirm) (the )?order", r"transfer", r"send money", r"withdraw", r"refund",
    r"factory reset", r"reset all", r"permanent",
    r"видал", r"вилуч", r"знищ", r"стерт", r"оплат", r"купи", r"придба", r"переказ", r"скасувати замовлення",
    r"удал", r"уничтож", r"стере", r"перевест", r"отменить заказ", r"оформить заказ", r"безвозврат",
)
_DESTRUCTIVE = re.compile(r"(?<!\w)(?:" + "|".join(DESTRUCTIVE_TERMS) + r")\w*")


def destructive_term(text: str) -> str | None:
    """The first destructive word found in `text` (case-insensitive), or None."""
    match = _DESTRUCTIVE.search(" ".join(text.casefold().split()))
    return match.group(0) if match else None
