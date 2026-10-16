"""LLM settings text in English, Ukrainian and Russian.

Merged into spec_to_test.i18n.TRANSLATIONS, so use `t()` as everywhere else.
"""

LLM_TRANSLATIONS: dict[str, dict[str, str]] = {
    "llm.heading": {"en": "AI settings", "uk": "Налаштування ШІ", "ru": "Настройки ИИ"},
    "llm.not_configured": {
        "en": "AI is off. To enable it, set AI_PROVIDER (anthropic, openai, openai_compatible or ollama) and the provider's key or server address in the environment, Streamlit secrets or a local .env file. Keys are never entered on this page.",
        "uk": "ШІ вимкнено. Щоб увімкнути, задайте AI_PROVIDER (anthropic, openai, openai_compatible або ollama) і ключ або адресу сервера провайдера в оточенні, секретах Streamlit або локальному файлі .env. Ключі ніколи не вводяться на цій сторінці.",
        "ru": "ИИ выключен. Чтобы включить, задайте AI_PROVIDER (anthropic, openai, openai_compatible или ollama) и ключ или адрес сервера провайдера в окружении, секретах Streamlit или локальном файле .env. Ключи никогда не вводятся на этой странице.",
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
    "llm.status.no_key": {"en": "no key", "uk": "без ключа", "ru": "без ключа"},
    "llm.status.off": {"en": "not configured", "uk": "не налаштовано", "ru": "не настроен"},
    "llm.problem.key_missing": {"en": "key missing ({variable})", "uk": "бракує ключа ({variable})", "ru": "нет ключа ({variable})"},
    "llm.problem.invalid_url": {
        "en": "invalid address ({variable})",
        "uk": "неправильна адреса ({variable})",
        "ru": "неверный адрес ({variable})",
    },
    "llm.problem.url_missing": {
        "en": "server address missing ({variable})",
        "uk": "бракує адреси сервера ({variable})",
        "ru": "нет адреса сервера ({variable})",
    },
    "llm.problem.model_missing": {
        "en": "model missing or invalid ({variable})",
        "uk": "модель не задано або вона неправильна ({variable})",
        "ru": "модель не задана или неверна ({variable})",
    },
    "llm.problem.insecure_url": {
        "en": "the key would be sent unencrypted: use https in {variable} (plain http only to localhost)",
        "uk": "ключ було б надіслано без шифрування: використовуйте https у {variable} (http лише до localhost)",
        "ru": "ключ ушёл бы без шифрования: используйте https в {variable} (http только для localhost)",
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
        "en": "This AI provider is not supported. Use anthropic, openai, openai_compatible or ollama.",
        "uk": "Цей провайдер ШІ не підтримується. Використовуйте anthropic, openai, openai_compatible або ollama.",
        "ru": "Этот провайдер ИИ не поддерживается. Используйте anthropic, openai, openai_compatible или ollama.",
    },
    "ai.error.not_configured": {
        "en": "AI is not configured. Set AI_PROVIDER (anthropic, openai, openai_compatible or ollama) and the provider's key or server address in the environment or a local .env file.",
        "uk": "ШІ не налаштовано. Задайте AI_PROVIDER (anthropic, openai, openai_compatible або ollama) і ключ або адресу сервера провайдера в оточенні чи локальному файлі .env.",
        "ru": "ИИ не настроен. Задайте AI_PROVIDER (anthropic, openai, openai_compatible или ollama) и ключ или адрес сервера провайдера в окружении или локальном файле .env.",
    },
    "ai.error.key_missing": {
        "en": "The API key of the AI_PROVIDER provider is not set (ANTHROPIC_API_KEY or OPENAI_API_KEY).",
        "uk": "API-ключ провайдера AI_PROVIDER не задано (ANTHROPIC_API_KEY або OPENAI_API_KEY).",
        "ru": "API-ключ провайдера AI_PROVIDER не задан (ANTHROPIC_API_KEY или OPENAI_API_KEY).",
    },
    "ai.error.url_missing": {
        "en": "The server address is not set: OPENAI_COMPATIBLE_BASE_URL (e.g. http://localhost:1234/v1).",
        "uk": "Адресу сервера не задано: OPENAI_COMPATIBLE_BASE_URL (напр. http://localhost:1234/v1).",
        "ru": "Адрес сервера не задан: OPENAI_COMPATIBLE_BASE_URL (напр. http://localhost:1234/v1).",
    },
    "ai.error.model_missing": {
        "en": "The model is not set or not a model ID: OPENAI_COMPATIBLE_MODEL (or AI_MODEL).",
        "uk": "Модель не задано або це не ID моделі: OPENAI_COMPATIBLE_MODEL (або AI_MODEL).",
        "ru": "Модель не задана или это не ID модели: OPENAI_COMPATIBLE_MODEL (или AI_MODEL).",
    },
    "ai.error.invalid_url": {
        "en": "The provider's server address is not a valid http(s) URL (OPENAI_COMPATIBLE_BASE_URL, OPENAI_BASE_URL or OLLAMA_HOST).",
        "uk": "Адреса сервера провайдера не є коректною http(s)-адресою (OPENAI_COMPATIBLE_BASE_URL, OPENAI_BASE_URL або OLLAMA_HOST).",
        "ru": "Адрес сервера провайдера не является корректным http(s)-адресом (OPENAI_COMPATIBLE_BASE_URL, OPENAI_BASE_URL или OLLAMA_HOST).",
    },
    "ai.error.insecure_url": {
        "en": "An API key is sent only over https or to this machine (localhost). Change the server address or remove the key.",
        "uk": "API-ключ надсилається лише через https або на цей комп'ютер (localhost). Змініть адресу сервера або приберіть ключ.",
        "ru": "API-ключ отправляется только по https или на этот компьютер (localhost). Измените адрес сервера или уберите ключ.",
    },
    "ai.error.input_too_large": {
        "en": "The document is too large for one AI request. Nothing was sent.",
        "uk": "Документ завеликий для одного запиту до ШІ. Нічого не надіслано.",
        "ru": "Документ слишком большой для одного запроса к ИИ. Ничего не отправлено.",
    },
}
