"""LLM settings text in English, Ukrainian and Russian.

Merged into spec_to_test.i18n.TRANSLATIONS, so use `t()` as everywhere else.
"""

LLM_TRANSLATIONS: dict[str, dict[str, str]] = {
    "llm.heading": {"en": "AI settings", "uk": "Налаштування ШІ", "ru": "Настройки ИИ"},
    "llm.not_configured": {
        "en": "AI is off. To enable it, set AI_PROVIDER (anthropic, openai or ollama) and the provider's key in the environment, Streamlit secrets or a local .env file. Keys are never entered on this page.",
        "uk": "ШІ вимкнено. Щоб увімкнути, задайте AI_PROVIDER (anthropic, openai або ollama) і ключ провайдера в оточенні, секретах Streamlit або локальному файлі .env. Ключі ніколи не вводяться на цій сторінці.",
        "ru": "ИИ выключен. Чтобы включить, задайте AI_PROVIDER (anthropic, openai или ollama) и ключ провайдера в окружении, секретах Streamlit или локальном файле .env. Ключи никогда не вводятся на этой странице.",
    },
    "llm.enabled": {"en": "Use AI features", "uk": "Використовувати функції ШІ", "ru": "Использовать функции ИИ"},
    "llm.enabled_help": {
        "en": "Off = rule-based mode for this browser session: every feature that does not need AI keeps working and nothing is sent anywhere.",
        "uk": "Вимкнено = режим на основі правил для цієї сесії браузера: усе, що не потребує ШІ, працює, і нічого нікуди не надсилається.",
        "ru": "Выключено = режим на основе правил для этой сессии браузера: всё, что не требует ИИ, работает, и ничего никуда не отправляется.",
    },
    "llm.fallback": {
        "en": "Rule-based mode: AI is off for this browser session and nothing is sent to any AI provider.",
        "uk": "Режим на основі правил: ШІ вимкнено для цієї сесії браузера, і нічого не надсилається жодному провайдеру ШІ.",
        "ru": "Режим на основе правил: ИИ выключен для этой сессии браузера, и ничего не отправляется ни одному провайдеру ИИ.",
    },
    "llm.locked": {
        "en": "Provider and model are fixed by the administrator (AI_LOCK_SETTINGS).",
        "uk": "Провайдера й модель зафіксовано адміністратором (AI_LOCK_SETTINGS).",
        "ru": "Провайдер и модель зафиксированы администратором (AI_LOCK_SETTINGS).",
    },
    "llm.default_unusable": {
        "en": "The default provider ({provider}) cannot be used. Check its settings below.",
        "uk": "Провайдер за замовчуванням ({provider}) недоступний. Перевірте його налаштування нижче.",
        "ru": "Провайдер по умолчанию ({provider}) недоступен. Проверьте его настройки ниже.",
    },
    "llm.provider": {"en": "Provider", "uk": "Провайдер", "ru": "Провайдер"},
    "llm.model": {"en": "Model", "uk": "Модель", "ru": "Модель"},
    "llm.model_help": {
        "en": "Model ID as the provider writes it. Configured default: {model}.",
        "uk": "ID моделі так, як його пише провайдер. За замовчуванням: {model}.",
        "ru": "ID модели так, как его пишет провайдер. По умолчанию: {model}.",
    },
    "llm.model_invalid": {
        "en": "This does not look like a model ID, so {model} is used.",
        "uk": "Це не схоже на ID моделі, тому використовується {model}.",
        "ru": "Это не похоже на ID модели, поэтому используется {model}.",
    },
    "llm.status.key_set": {"en": "key set ({variable})", "uk": "ключ задано ({variable})", "ru": "ключ задан ({variable})"},
    "llm.status.server": {"en": "server {url}", "uk": "сервер {url}", "ru": "сервер {url}"},
    "llm.status.sdk_missing": {
        "en": "SDK not installed (pip install -r requirements-ai.txt)",
        "uk": "SDK не встановлено (pip install -r requirements-ai.txt)",
        "ru": "SDK не установлен (pip install -r requirements-ai.txt)",
    },
    "llm.status.off": {"en": "not configured", "uk": "не налаштовано", "ru": "не настроен"},
    "llm.problem.key_missing": {"en": "key missing ({variable})", "uk": "бракує ключа ({variable})", "ru": "нет ключа ({variable})"},
    "llm.problem.invalid_url": {
        "en": "invalid address ({variable})",
        "uk": "неправильна адреса ({variable})",
        "ru": "неверный адрес ({variable})",
    },
    "llm.problem.unknown_provider": {
        "en": "unknown provider in {variable}",
        "uk": "невідомий провайдер у {variable}",
        "ru": "неизвестный провайдер в {variable}",
    },
    "llm.test": {"en": "Test connection", "uk": "Перевірити з'єднання", "ru": "Проверить соединение"},
    "llm.test_help": {
        "en": "Sends one tiny request with no document data.",
        "uk": "Надсилає один крихітний запит без даних документа.",
        "ru": "Отправляет один крошечный запрос без данных документа.",
    },
    "llm.testing": {"en": "Contacting the provider…", "uk": "З'єднання з провайдером…", "ru": "Соединение с провайдером…"},
    "llm.test_ok": {"en": "Connected: {model} answered.", "uk": "З'єднано: {model} відповіла.", "ru": "Соединение есть: {model} ответила."},
    # --- New AI error codes (the rest live in spec_to_test.i18n) -----------------
    "ai.error.model_not_found": {
        "en": "The AI provider does not know this model. Check the model name (for Ollama, run: ollama pull <model>).",
        "uk": "Провайдер ШІ не знає цієї моделі. Перевірте назву моделі (для Ollama виконайте: ollama pull <model>).",
        "ru": "Провайдер ИИ не знает эту модель. Проверьте название модели (для Ollama выполните: ollama pull <model>).",
    },
    "ai.error.unsupported_provider": {
        "en": "This AI provider is not supported. Use anthropic, openai or ollama.",
        "uk": "Цей провайдер ШІ не підтримується. Використовуйте anthropic, openai або ollama.",
        "ru": "Этот провайдер ИИ не поддерживается. Используйте anthropic, openai или ollama.",
    },
}
