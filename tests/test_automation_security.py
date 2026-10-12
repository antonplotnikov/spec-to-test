"""Security controls: allowlist, SSRF checks, egress pinning, redaction, destructive actions."""

import zipfile

import pytest

from automation_fakes import FAKE_API_KEY, PUBLIC_IP, config, resolver
from spec_to_test.automation.config import HostRule, load_automation_config, parse_host_rules
from spec_to_test.automation.security import (
    Redactor,
    UrlRejected,
    address_problem,
    build_egress_policy,
    check_navigation,
    destructive_term,
)

# --- Allowlist -------------------------------------------------------------------------------


def test_host_rules_parse_exact_wildcard_and_port_entries():
    rules = parse_host_rules(" Staging.Example.com , *.qa.example.com, localhost:8080 ")
    assert [str(r) for r in rules] == ["staging.example.com", "*.qa.example.com", "localhost:8080"]


@pytest.mark.parametrize("entry", ["*.com", "*", "http://x.com", "user@x.com", "x.com:0", "x.com:99999", "a..b", "x.com/path"])
def test_invalid_or_too_broad_entries_are_ignored(entry):
    assert parse_host_rules(entry) == []


def test_rule_matching_respects_subdomains_and_ports():
    wildcard = HostRule(host="*.qa.example.com")
    assert wildcard.matches("app.qa.example.com", 443)
    assert not wildcard.matches("qa.example.com", 443)  # the wildcard does not include the parent
    assert not wildcard.matches("evilqa.example.com", 443)
    assert not wildcard.matches("app.qa.example.com", 8443)  # only 80/443 without an explicit port
    assert HostRule(host="localhost", port=8080).matches("localhost", 8080)
    assert not HostRule(host="localhost", port=8080).matches("localhost", 80)


def test_config_reads_secrets_by_name_and_is_off_without_allowlist(tmp_path):
    cfg = load_automation_config(
        {"AUTOMATION_SECRET_STAGING_USER": "qa", "AUTOMATION_SECRET_bad name": "x", "AUTOMATION_DATA_DIR": str(tmp_path)}
    )
    assert not cfg.enabled
    assert list(cfg.secrets) == ["STAGING_USER"]
    assert "qa" not in repr(cfg)  # SecretStr keeps values out of logs


def test_numeric_settings_are_clamped(tmp_path):
    cfg = load_automation_config({"AUTOMATION_MAX_TOOL_CALLS": "100000", "AUTOMATION_RUN_TIMEOUT": "x",
                                  "AUTOMATION_DATA_DIR": str(tmp_path)})
    assert cfg.max_tool_calls == 200 and cfg.run_timeout == 240


# --- SSRF --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("ftp://staging.example.com/", "scheme"),
        ("file:///etc/passwd", "scheme"),
        ("javascript:alert(1)", "scheme"),
        ("https://user:pw@staging.example.com/", "credentials"),
        ("https://evil.example.org/", "not_allowed"),
        ("https://staging.example.com.evil.org/", "not_allowed"),
        ("https://staging.example.com:8443/", "not_allowed"),
        ("https://[::1", "invalid"),
        ("https://staging.example.com/" + "a" * 3000, "too_long"),
    ],
)
def test_target_url_rules(tmp_path, url, code):
    with pytest.raises(UrlRejected) as rejected:
        build_egress_policy(url, config(tmp_path), resolver())
    assert rejected.value.code == code


@pytest.mark.parametrize(
    ("address", "code"),
    [("10.0.0.5", "private"), ("127.0.0.1", "private"), ("192.168.1.10", "private"), ("::1", "private"),
     ("169.254.169.254", "metadata"), ("fe80::1", "metadata"), ("::ffff:169.254.169.254", "metadata"),
     ("0.0.0.0", "reserved"), ("224.0.0.1", "reserved")],
)
def test_allowlisted_host_resolving_to_unsafe_address_is_refused(tmp_path, address, code):
    with pytest.raises(UrlRejected) as rejected:
        build_egress_policy("https://staging.example.com/", config(tmp_path), resolver({"staging.example.com": [address]}))
    assert rejected.value.code == code


def test_any_unsafe_address_among_several_is_refused(tmp_path):
    lookup = resolver({"staging.example.com": [PUBLIC_IP, "10.1.2.3"]})
    with pytest.raises(UrlRejected):
        build_egress_policy("https://staging.example.com/", config(tmp_path), lookup)


def test_private_network_needs_opt_in_but_metadata_never_allowed(tmp_path):
    cfg = config(tmp_path, AUTOMATION_ALLOW_PRIVATE_NETWORK="true")
    policy = build_egress_policy("https://staging.example.com/", cfg, resolver({"staging.example.com": ["10.0.0.5"]}))
    assert policy.hosts[0].ip == "10.0.0.5"
    assert address_problem("169.254.169.254", allow_private=True) == "metadata"


def test_dns_failure_is_reported(tmp_path):
    cfg = config(tmp_path, AUTOMATION_ALLOWED_HOSTS="staging.invalid")
    with pytest.raises(UrlRejected) as rejected:
        build_egress_policy("https://staging.invalid/", cfg, resolver())
    assert rejected.value.code == "dns"


def test_policy_pins_hosts_and_blocks_everything_else(tmp_path):
    cfg = config(tmp_path, AUTOMATION_ALLOWED_HOSTS="*.qa.example.com,login.example.com,bad.example.com")
    lookup = resolver({"app.qa.example.com": ["93.184.216.10"], "bad.example.com": ["10.0.0.1"]})
    policy = build_egress_policy("https://app.qa.example.com/start", cfg, lookup)
    assert policy.host_names() == ["app.qa.example.com", "login.example.com"]  # unsafe extra host dropped
    assert policy.resolver_rules() == (
        f"MAP app.qa.example.com 93.184.216.10, MAP login.example.com {PUBLIC_IP}, MAP * ~NOTFOUND"
    )
    assert policy.proxy_bypass() == "app.qa.example.com:443,login.example.com:80,login.example.com:443"
    assert "https://app.qa.example.com" in policy.allowed_origins()
    assert policy.origin == "https://app.qa.example.com"


def test_navigation_check(tmp_path):
    policy = build_egress_policy("https://staging.example.com/app", config(tmp_path), resolver())
    assert check_navigation("/login", policy) == "https://staging.example.com/login"
    assert check_navigation("https://staging.example.com/x", policy) == "https://staging.example.com/x"
    for url in ("//evil.org/x", "https://evil.org/", "http://169.254.169.254/", "data:text/html,hi", "file:///etc/passwd",
                "https://staging.example.com:8443/"):
        with pytest.raises(UrlRejected):
            check_navigation(url, policy)


# --- Redaction ---------------------------------------------------------------------------------


def test_redactor_masks_secrets_keys_and_credentials():
    redact = Redactor({"STAGING_PASSWORD": "Hunter-2-pass", "SHORT": "ab"}, extra=[FAKE_API_KEY])
    text = redact(
        f"typed Hunter-2-pass; key {FAKE_API_KEY}; Authorization: Bearer abc.def.ghi123\n"
        "password=letmein1 and ab stays"
    )
    assert "Hunter-2-pass" not in text and "[redacted:STAGING_PASSWORD]" in text
    assert "sk-ant" not in text and "abc.def.ghi123" not in text and "letmein1" not in text
    assert "ab stays" in text  # values shorter than 3 characters are not masked everywhere
    assert redact.contains_secret('{"value": "Hunter-2-pass"}')


def test_longer_secret_containing_another_is_masked_whole():
    redact = Redactor({"A": "pass", "B": "pass-word-long"})
    assert redact("x pass-word-long y") == "x [redacted:B] y"


def test_trace_zip_text_entries_are_masked(tmp_path):
    trace = tmp_path / "trace.zip"
    with zipfile.ZipFile(trace, "w") as archive:
        archive.writestr("0-trace.trace", '{"method":"fill","params":{"value":"Hunter-2-pass"}}')
        archive.writestr("resources/page.png", b"\x89PNG Hunter-2-pass")
    Redactor({"PW": "Hunter-2-pass"}).redact_zip(trace)
    with zipfile.ZipFile(trace) as archive:
        assert b"Hunter-2-pass" not in archive.read("0-trace.trace")
        assert b"[redacted:PW]" in archive.read("0-trace.trace")
        assert archive.read("resources/page.png").startswith(b"\x89PNG")  # binary entries untouched


# --- Destructive actions -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["Delete account", "Remove item", "Pay now", "Purchase", "Checkout", "Transfer funds", "Cancel subscription",
     "Deactivate user", "Place order", "Видалити", "Оплатити", "Удалить аккаунт", "Купить", "Оформить заказ"],
)
def test_destructive_labels_are_detected(label):
    assert destructive_term(label)


@pytest.mark.parametrize(
    "label",
    ["Display settings", "Reset password", "Cancel", "Save", "Dropdown menu", "Sign in", "Send reset link",
     "Terminal", "Скинути пароль", "Сбросить пароль", "Зберегти"],
)
def test_ordinary_labels_are_not_destructive(label):
    assert destructive_term(label) is None
