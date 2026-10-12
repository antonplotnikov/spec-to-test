"""LLM settings in the sidebar.

The operator decides which providers exist (environment, Streamlit secrets or
.env; see `spec_to_test.llm.config`). Each browser session may then turn AI
off (rule-based mode: nothing is sent anywhere), pick one of the configured
providers and change the model. API keys are never entered or shown here; the
page only says whether a key is set and where it is read from.

The choice lives in this browser session's `st.session_state`, so visitors
never change each other's settings. AI_LOCK_SETTINGS=true shows the settings
without letting anyone change them.
"""

import importlib.util

import streamlit as st

from spec_to_test.formatting import escape_markdown
from spec_to_test.i18n import t
from spec_to_test.llm.config import (
    KEY_VARIABLES,
    PROVIDER_NAMES,
    PROVIDERS,
    SDK_MODULES,
    AIConfig,
    LLMSettings,
    choose,
    valid_model,
)
from spec_to_test.llm.providers import AIError, check_connection

ENABLED = "llm_enabled"
PROVIDER = "llm_provider"
RESULT = "llm_check"  # (provider, model, error code or "") of the last connection test


def sdk_installed(provider: str) -> bool:
    module = SDK_MODULES.get(provider)
    return module is None or importlib.util.find_spec(module) is not None


def render_llm_settings(lang: str, settings: LLMSettings) -> AIConfig | None:
    """Show the settings; return the configuration this session uses (None = no AI)."""
    with st.sidebar.expander(t("llm.heading", lang), icon=":material/tune:"):
        if not settings.enabled:
            st.caption(t("llm.not_configured", lang))
            _status(lang, settings)
            return None
        enabled = st.toggle(t("llm.enabled", lang), value=True, key=ENABLED, help=t("llm.enabled_help", lang))
        if not enabled:
            st.caption(t("llm.fallback", lang))
            return None
        if settings.locked:
            config = choose(settings)
            st.caption(t("llm.locked", lang))
        else:
            config = _choose(lang, settings)
        if config is None:
            st.warning(t("llm.default_unusable", lang, provider=PROVIDER_NAMES.get(settings.default_provider, "—")))
        _status(lang, settings)
        if config is not None:
            _connection_test(lang, config)
    return config


def _choose(lang: str, settings: LLMSettings) -> AIConfig | None:
    providers = list(settings.configs)
    if st.session_state.get(PROVIDER) not in providers:
        st.session_state.pop(PROVIDER, None)  # a provider the operator has since removed
    provider = st.selectbox(
        t("llm.provider", lang), providers, key=PROVIDER, format_func=lambda p: PROVIDER_NAMES.get(p, p),
    )
    base = settings.configs[provider]
    model = st.text_input(
        t("llm.model", lang), value=base.model, key=f"llm_model_{provider}", max_chars=100,
        help=t("llm.model_help", lang, model=base.model),
    )
    if model.strip() and not valid_model(model):
        st.warning(t("llm.model_invalid", lang, model=base.model))
    return choose(settings, provider=provider, model=model)


def _status(lang: str, settings: LLMSettings) -> None:
    """One line per provider: ready, why not, or not configured. Keys are never shown."""
    lines = []
    for provider in PROVIDERS:
        name = PROVIDER_NAMES[provider]
        config = settings.configs.get(provider)
        if config is not None:
            if provider == "ollama":
                detail = t("llm.status.server", lang, url=config.base_url)
            else:
                detail = t("llm.status.key_set", lang, variable=KEY_VARIABLES[provider])
            if not sdk_installed(provider):
                detail += " · " + t("llm.status.sdk_missing", lang)
            lines.append(f"✅ **{name}** — {detail}")
        elif problem := settings.problems.get(provider):
            variable = KEY_VARIABLES.get(provider, "OLLAMA_HOST" if provider == "ollama" else "OPENAI_BASE_URL")
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
    result = st.session_state.get(RESULT)
    if result and result[:2] == (config.provider, config.model):  # only for what is selected now
        if result[2]:
            st.error(t(f"ai.error.{result[2]}", lang))
        else:
            st.success(t("llm.test_ok", lang, model=escape_markdown(config.model)))
