"""LLM settings: the Settings page, the header's quick switcher and the AI status.

The operator decides which providers exist (environment, Streamlit secrets or
.env; see `spec_to_test.llm.config`). Each browser session may then turn AI
off (rule-based mode: nothing is sent anywhere), pick one of the configured
providers and change the model. API keys are never entered or shown here; the
page only says whether a key is set and where it is read from.

The choice lives in this browser session's `st.session_state`, so visitors
never change each other's settings. AI_LOCK_SETTINGS=true shows the settings
without letting anyone change them.

The controls appear on one page at a time (Settings, or the header popover on
the other pages), so `keep_state()` keeps their values while they are not on
screen, and `resolve()` reads the configuration without drawing anything.
The status only says "connected" after a connection test of exactly the
provider and model in use.
"""

import importlib.util
from dataclasses import dataclass

import streamlit as st

from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.llm.config import (
    KEY_VARIABLES,
    MODEL_VARIABLES,
    PROVIDER_NAMES,
    PROVIDERS,
    SDK_MODULES,
    URL_VARIABLES,
    AIConfig,
    LLMSettings,
    choose,
    valid_model,
)
from spec_to_test.llm.providers import AIError, check_connection
from spec_to_test.llm.usage import Budget, UsageLedger, shared_ledger

ENABLED = "llm_enabled"
PROVIDER = "llm_provider"
MODEL_PREFIX = "llm_model_"
RESULT = "llm_check"  # (provider, model, error code or "") of the last connection test


def sdk_installed(provider: str) -> bool:
    module = SDK_MODULES.get(provider)
    return module is None or importlib.util.find_spec(module) is not None


def keep_state() -> None:
    """Keep the AI choices while their widgets are on another page (call before any widget)."""
    for key in list(st.session_state.keys()):
        if key in (ENABLED, PROVIDER) or str(key).startswith(MODEL_PREFIX):
            st.session_state[key] = st.session_state[key]


def usage_ledger(budget: Budget) -> UsageLedger:
    """The usage ledger of the running app: one for every browser session (see spec_to_test.llm.usage)."""
    return shared_ledger(budget)


def render_usage(lang: str, usage: UsageLedger) -> None:
    """Sidebar: the running app's tokens and estimated cost against the operator's limits.

    Cost is shown only for requests with a configured price; an unpriced cost is never shown as 0.
    """
    budget = usage.budget
    totals = usage.totals()
    if budget.problem:
        st.sidebar.warning(t("ai.usage.invalid", lang), icon=":material/rule:")
    if not totals.requests and budget.token_limit is None and budget.cost_limit is None:
        return
    with st.sidebar.container(border=True):
        st.markdown(f"**{t('ai.usage.title', lang)}**")
        st.caption(t("ai.usage.line", lang, requests=totals.requests, tokens=f"{totals.tokens:,}",
                     input=f"{totals.input_tokens:,}", output=f"{totals.output_tokens:,}"))
        if totals.requests:
            if totals.unpriced_requests == totals.requests:
                st.caption(t("ai.usage.cost_unknown", lang))
            else:
                st.caption(t("ai.usage.cost", lang, cost=f"{totals.cost_usd:.4f}"))
            if totals.unpriced_requests and totals.unpriced_requests != totals.requests:
                st.caption(t("ai.usage.unpriced", lang, count=totals.unpriced_requests))
        if totals.unknown_token_requests:
            st.caption(t("ai.usage.unknown_tokens", lang, count=totals.unknown_token_requests))
        by_model = usage.by_model()
        if by_model:
            with st.expander(t("ai.usage.by_model", lang)):
                for key, part in by_model.items():
                    cost = t("ai.usage.cost_na", lang) if part.unpriced_requests == part.requests \
                        else f"${part.cost_usd:.4f}"
                    st.caption(f"{escape_markdown(key)}: {part.requests} · {part.tokens:,} tokens · {cost}")
        if budget.token_limit is not None:
            st.caption(t("ai.usage.limit_tokens", lang, used=f"{totals.tokens:,}", limit=f"{budget.token_limit:,}"))
        if budget.cost_limit is not None:
            st.caption(t("ai.usage.limit_cost", lang, used=f"{totals.cost_usd:.4f}", limit=f"{budget.cost_limit:g}"))
    st.sidebar.caption(t("ai.usage.reset_note", lang))
    if budget.cost_limit is not None and totals.unpriced_requests:
        st.sidebar.caption(t("ai.usage.cost_partial", lang))
    if usage.exceeded():
        st.sidebar.error(t("ai.usage.exceeded", lang), icon=":material/block:")
    elif kind := usage.warning():
        st.sidebar.warning(t(f"ai.usage.warn_{kind}", lang), icon=":material/speed:")


def resolve(settings: LLMSettings) -> AIConfig | None:
    """The configuration this session uses (None = rule-based only), from its stored choices."""
    if not settings.enabled or not st.session_state.get(ENABLED, True):
        return None
    if settings.locked:
        return choose(settings)
    providers = list(settings.configs)
    if st.session_state.get(PROVIDER) not in providers:
        st.session_state.pop(PROVIDER, None)  # a provider the operator has since removed
    provider = st.session_state.get(PROVIDER, providers[0])
    model = st.session_state.get(f"{MODEL_PREFIX}{provider}", settings.configs[provider].model)
    return choose(settings, provider=provider, model=str(model))


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Status:
    tone: str  # theme_ui tone: success, warning, danger, neutral, info
    icon: str
    label: str  # short, for the header and the sidebar
    detail: str  # one sentence: what it means / what to do


def status(lang: str, settings: LLMSettings, config: AIConfig | None) -> Status:
    if not settings.enabled:
        return Status("neutral", ":material/rule:", t("ui.ai.rule_based", lang), t("ui.ai.not_configured", lang))
    if config is None:
        if not st.session_state.get(ENABLED, True):
            return Status("neutral", ":material/rule:", t("ui.ai.rule_based", lang), t("llm.fallback", lang))
        name = PROVIDER_NAMES.get(settings.default_provider, "—")
        return Status("warning", ":material/warning:", t("ui.ai.unavailable", lang),
                      t("llm.default_unusable", lang, provider=name))
    name = config.provider_name
    if not sdk_installed(config.provider):
        return Status("warning", ":material/warning:", t("ui.ai.sdk_missing", lang, provider=name),
                      t("llm.status.sdk_missing", lang))
    result = st.session_state.get(RESULT)
    if result and result[:2] == (config.provider, config.model):
        if result[2]:
            return Status("danger", ":material/error:", t("ui.ai.failed", lang, provider=name),
                          t(f"ai.error.{result[2]}", lang))
        return Status("success", ":material/check_circle:", t("ui.ai.connected", lang, provider=name),
                      t("llm.test_ok", lang, model=escape_markdown(config.model)))
    return Status("info", ":material/radio_button_checked:", t("ui.ai.ready", lang, provider=name),
                  t("ui.ai.not_tested", lang))


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

def render_controls(lang: str, settings: LLMSettings) -> None:
    """On/off, provider and model. Draw them in exactly one place per page."""
    if not settings.enabled:
        st.caption(t("llm.not_configured", lang))
        return
    st.session_state.setdefault(ENABLED, True)
    enabled = st.toggle(t("llm.enabled", lang), key=ENABLED, help=t("llm.enabled_help", lang))
    if not enabled:
        st.caption(t("llm.fallback", lang))
        return
    if settings.locked:
        st.caption(t("llm.locked", lang))
        return
    providers = list(settings.configs)
    if st.session_state.get(PROVIDER) not in providers:
        st.session_state.pop(PROVIDER, None)
    provider = st.selectbox(
        t("llm.provider", lang), providers, key=PROVIDER, format_func=lambda p: PROVIDER_NAMES.get(p, p),
    )
    base = settings.configs[provider]
    model_key = f"{MODEL_PREFIX}{provider}"
    st.session_state.setdefault(model_key, base.model)
    model = st.text_input(
        t("llm.model", lang), key=model_key, max_chars=100, help=t("llm.model_help", lang, model=base.model),
    )
    if model.strip() and not valid_model(model):
        st.warning(t("llm.model_invalid", lang, model=base.model))


def render_settings(lang: str, settings: LLMSettings, config: AIConfig | None) -> None:
    """The Settings page's AI section: controls, what is configured, connection test."""
    render_controls(lang, settings)
    if settings.enabled and st.session_state.get(ENABLED, True) and config is None:
        st.warning(t("llm.default_unusable", lang, provider=PROVIDER_NAMES.get(settings.default_provider, "—")))
    st.markdown(f"**{t('ui.settings.providers', lang)}**")
    _provider_lines(lang, settings)
    if config is not None:
        _connection_test(lang, config)


def _provider_lines(lang: str, settings: LLMSettings) -> None:
    """One line per provider: ready, why not, or not configured. Keys are never shown."""
    lines = []
    for provider in PROVIDERS:
        name = PROVIDER_NAMES[provider]
        config = settings.configs.get(provider)
        if config is not None:
            if provider == "ollama":
                detail = t("llm.status.server", lang, url=config.base_url)
            elif provider == "openai_compatible":
                key = config.api_key.get_secret_value()
                detail = t("llm.status.server", lang, url=config.base_url) + " · " + (
                    t("llm.status.key_set", lang, variable=KEY_VARIABLES[provider]) if key
                    else t("llm.status.no_key", lang)
                )
            else:
                detail = t("llm.status.key_set", lang, variable=KEY_VARIABLES[provider])
            if not sdk_installed(provider):
                detail += " · " + t("llm.status.sdk_missing", lang)
            lines.append(f"✅ **{name}** — {detail}")
        elif problem := settings.problems.get(provider):
            variables = {"key_missing": KEY_VARIABLES, "model_missing": MODEL_VARIABLES}.get(problem, URL_VARIABLES)
            variable = variables.get(provider, "AI_PROVIDER")
            lines.append(f"⚠️ **{name}** — {t(f'llm.problem.{problem}', lang, variable=variable)}")
        else:
            lines.append(f"▫️ **{name}** — {t('llm.status.off', lang)}")
    for provider, problem in settings.problems.items():
        if provider not in PROVIDERS:
            lines.append(f"⚠️ {t(f'llm.problem.{problem}', lang, variable='AI_PROVIDER')}: `{escape_markdown(provider)}`")
    st.caption("  \n".join(lines))


def _connection_test(lang: str, config: AIConfig) -> None:
    if st.button(t("llm.test", lang), key="llm_test", icon=":material/network_check:", help=t("llm.test_help", lang)):
        try:
            with st.spinner(t("llm.testing", lang)):
                check_connection(config)
            st.session_state[RESULT] = (config.provider, config.model, "")
        except AIError as error:
            st.session_state[RESULT] = (config.provider, config.model, error.code)
        st.rerun()  # the header and the sidebar show the status, and they are drawn first
    result = st.session_state.get(RESULT)
    if result and result[:2] == (config.provider, config.model):  # only for what is selected now
        if result[2]:
            st.error(t(f"ai.error.{result[2]}", lang))
        else:
            st.success(t("llm.test_ok", lang, model=escape_markdown(config.model)))
