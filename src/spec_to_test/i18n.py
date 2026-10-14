"""All user-facing text in English, Ukrainian and Russian.

Use `t(key, lang, **params)` to get a translated string. Placeholders like
{max_mb} are filled from params. Missing translations fall back to English.
"""

from spec_to_test.automation.translations import AUTOMATION_TRANSLATIONS
from spec_to_test.grill.translations import GRILL_TRANSLATIONS
from spec_to_test.history_translations import HISTORY_TRANSLATIONS
from spec_to_test.llm.translations import LLM_TRANSLATIONS
from spec_to_test.models import Finding
from spec_to_test.qa_agent.auto_translations import AUTO_TRANSLATIONS
from spec_to_test.qa_agent.translations import QA_AGENT_TRANSLATIONS
from spec_to_test.ui_translations import UI_TRANSLATIONS

DEFAULT_LANGUAGE = "en"

# Shown in the language selector in each language's own name.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "uk": "Українська",
    "ru": "Русский",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    # --- App shell -------------------------------------------------------
    "app.title": {
        "en": "Spec-to-Test",
        "uk": "Spec-to-Test",
        "ru": "Spec-to-Test",
    },
    "app.subtitle": {
        "en": "Find ambiguities and missing rules in software requirements.",
        "uk": "Пошук неоднозначностей і пропущених правил у вимогах до ПЗ.",
        "ru": "Поиск неоднозначностей и пропущенных правил в требованиях к ПО.",
    },
    "app.badges": {
        "en": "Rule-based · Runs locally · EN / UK / RU",
        "uk": "На основі правил · Працює локально · EN / UK / RU",
        "ru": "На основе правил · Работает локально · EN / UK / RU",
    },
    "sidebar.language": {
        "en": "Interface language",
        "uk": "Мова інтерфейсу",
        "ru": "Язык интерфейса",
    },
    "sidebar.privacy": {
        "en": "AI is off. Your documents are processed locally by rule-based checks and are not sent anywhere.",
        "uk": "ШІ вимкнено. Документи обробляються локально перевірками на основі правил і нікуди не надсилаються.",
        "ru": "ИИ выключен. Документы обрабатываются локально проверками на основе правил и никуда не отправляются.",
    },
    # --- Input -----------------------------------------------------------
    "input.text_heading": {
        "en": "✍️ Text",
        "uk": "✍️ Текст",
        "ru": "✍️ Текст",
    },
    "input.file_heading": {
        "en": "📄 File",
        "uk": "📄 Файл",
        "ru": "📄 Файл",
    },
    "input.text_label": {
        "en": "Paste requirements",
        "uk": "Вставте вимоги",
        "ru": "Вставьте требования",
    },
    "input.text_placeholder": {
        "en": "REQ-1: The user must be able to reset the password via email.",
        "uk": "REQ-1: Користувач повинен мати змогу скинути пароль через email.",
        "ru": "REQ-1: Пользователь должен иметь возможность сбросить пароль через email.",
    },
    "input.file_label": {
        "en": "Or upload a file (TXT, MD, PDF, up to {max_mb} MB)",
        "uk": "Або завантажте файл (TXT, MD, PDF, до {max_mb} МБ)",
        "ru": "Или загрузите файл (TXT, MD, PDF, до {max_mb} МБ)",
    },
    "input.file_used": {
        "en": "Analyzing the uploaded file. The text field is ignored.",
        "uk": "Аналізується завантажений файл. Текстове поле ігнорується.",
        "ru": "Анализируется загруженный файл. Текстовое поле игнорируется.",
    },
    "input.analyze_button": {
        "en": "Analyze",
        "uk": "Аналізувати",
        "ru": "Анализировать",
    },
    "input.empty_state": {
        "en": "Paste requirements or upload a file, then click Analyze.",
        "uk": "Вставте вимоги або завантажте файл і натисніть «Аналізувати».",
        "ru": "Вставьте требования или загрузите файл и нажмите «Анализировать».",
    },
    # --- Errors ------------------------------------------------------------
    "error.empty_input": {
        "en": "The input is empty. Please enter some requirements.",
        "uk": "Поле порожнє. Будь ласка, введіть вимоги.",
        "ru": "Поле пустое. Пожалуйста, введите требования.",
    },
    "error.text_too_long": {
        "en": "The text is too long (maximum {max_chars} characters).",
        "uk": "Текст задовгий (максимум {max_chars} символів).",
        "ru": "Текст слишком длинный (максимум {max_chars} символов).",
    },
    "error.unsupported_file_type": {
        "en": "Unsupported file type \"{extension}\". Allowed: {allowed}.",
        "uk": "Непідтримуваний тип файлу «{extension}». Дозволено: {allowed}.",
        "ru": "Неподдерживаемый тип файла «{extension}». Разрешено: {allowed}.",
    },
    "error.empty_file": {
        "en": "The uploaded file is empty.",
        "uk": "Завантажений файл порожній.",
        "ru": "Загруженный файл пуст.",
    },
    "error.file_too_large": {
        "en": "The file is too large (maximum {max_mb} MB).",
        "uk": "Файл завеликий (максимум {max_mb} МБ).",
        "ru": "Файл слишком большой (максимум {max_mb} МБ).",
    },
    "error.binary_content": {
        "en": "The file looks like binary data, not text.",
        "uk": "Файл схожий на двійкові дані, а не на текст.",
        "ru": "Файл похож на двоичные данные, а не на текст.",
    },
    "error.encoding_error": {
        "en": "Could not read the file. Please save it as UTF-8 text.",
        "uk": "Не вдалося прочитати файл. Збережіть його як текст у кодуванні UTF-8.",
        "ru": "Не удалось прочитать файл. Сохраните его как текст в кодировке UTF-8.",
    },
    "error.invalid_pdf": {
        "en": "The file is not a valid PDF.",
        "uk": "Файл не є коректним PDF.",
        "ru": "Файл не является корректным PDF.",
    },
    "error.encrypted_pdf": {
        "en": "Password-protected PDFs are not supported.",
        "uk": "PDF, захищені паролем, не підтримуються.",
        "ru": "PDF, защищённые паролем, не поддерживаются.",
    },
    "error.pdf_too_many_pages": {
        "en": "The PDF has too many pages (maximum {max_pages}).",
        "uk": "У PDF забагато сторінок (максимум {max_pages}).",
        "ru": "В PDF слишком много страниц (максимум {max_pages}).",
    },
    "error.pdf_no_text": {
        "en": "No text found in the PDF. Scanned documents are not supported.",
        "uk": "У PDF не знайдено тексту. Скановані документи не підтримуються.",
        "ru": "В PDF не найден текст. Отсканированные документы не поддерживаются.",
    },
    "error.no_requirements_found": {
        "en": "No requirement statements were found in the text.",
        "uk": "У тексті не знайдено жодної вимоги.",
        "ru": "В тексте не найдено ни одного требования.",
    },
    "error.too_many_requirements": {
        "en": "Too many requirements (maximum {max_count}). Please split the document.",
        "uk": "Забагато вимог (максимум {max_count}). Розділіть документ на частини.",
        "ru": "Слишком много требований (максимум {max_count}). Разделите документ на части.",
    },
    # --- Results -----------------------------------------------------------
    "results.heading": {
        "en": "Results",
        "uk": "Результати",
        "ru": "Результаты",
    },
    "results.requirements_count": {
        "en": "Requirements",
        "uk": "Вимоги",
        "ru": "Требования",
    },
    "results.findings_count": {
        "en": "Possible issues",
        "uk": "Можливі проблеми",
        "ru": "Возможные проблемы",
    },
    "results.needs_clarification_count": {
        "en": "Need clarification",
        "uk": "Потребують уточнення",
        "ru": "Требуют уточнения",
    },
    "results.tab_requirements": {
        "en": "Requirements",
        "uk": "Вимоги",
        "ru": "Требования",
    },
    "results.tab_findings": {
        "en": "Findings",
        "uk": "Знахідки",
        "ru": "Находки",
    },
    "results.rule_disclaimer": {
        "en": "Findings are produced by rule-based heuristics. They are possible issues, not confirmed defects — please review each one.",
        "uk": "Знахідки створено евристиками на основі правил. Це можливі проблеми, а не підтверджені дефекти — перевірте кожну.",
        "ru": "Находки созданы эвристиками на основе правил. Это возможные проблемы, а не подтверждённые дефекты — проверьте каждую.",
    },
    "results.no_findings": {
        "en": "No issues detected by the rules. This does not guarantee the requirements are complete.",
        "uk": "Правила не виявили проблем. Це не гарантує, що вимоги повні.",
        "ru": "Правила не выявили проблем. Это не гарантирует, что требования полны.",
    },
    "column.id": {"en": "ID", "uk": "ID", "ru": "ID"},
    "column.requirement": {"en": "Requirement", "uk": "Вимога", "ru": "Требование"},
    "column.language": {"en": "Language", "uk": "Мова", "ru": "Язык"},
    "column.status": {"en": "Status", "uk": "Статус", "ru": "Статус"},
    "column.issue": {"en": "Issue", "uk": "Проблема", "ru": "Проблема"},
    "column.severity": {"en": "Severity", "uk": "Важливість", "ru": "Важность"},
    "column.source": {"en": "Source", "uk": "Джерело", "ru": "Источник"},
    "column.matched": {"en": "Matched text", "uk": "Знайдений текст", "ru": "Найденный текст"},
    "column.question": {
        "en": "Clarification question",
        "uk": "Уточнювальне питання",
        "ru": "Уточняющий вопрос",
    },
    # --- Enum labels -------------------------------------------------------
    "status.clear": {"en": "Clear", "uk": "Зрозуміло", "ru": "Понятно"},
    "status.needs_clarification": {
        "en": "Needs clarification",
        "uk": "Потребує уточнення",
        "ru": "Требует уточнения",
    },
    "status.resolved": {"en": "Resolved", "uk": "Вирішено", "ru": "Решено"},
    "severity.low": {"en": "Low", "uk": "Низька", "ru": "Низкая"},
    "severity.medium": {"en": "Medium", "uk": "Середня", "ru": "Средняя"},
    "severity.high": {"en": "High", "uk": "Висока", "ru": "Высокая"},
    "source.rule": {"en": "Rule-based", "uk": "На основі правил", "ru": "На основе правил"},
    "source.ai": {"en": "AI suggestion", "uk": "Пропозиція ШІ", "ru": "Предложение ИИ"},
    "source.user": {"en": "User-provided", "uk": "Від користувача", "ru": "От пользователя"},
    "language.en": {"en": "English", "uk": "Англійська", "ru": "Английский"},
    "language.uk": {"en": "Ukrainian", "uk": "Українська", "ru": "Украинский"},
    "language.ru": {"en": "Russian", "uk": "Російська", "ru": "Русский"},
    # --- Finding types -----------------------------------------------------
    "finding.ambiguous_wording": {
        "en": "Ambiguous wording",
        "uk": "Неоднозначне формулювання",
        "ru": "Неоднозначная формулировка",
    },
    "finding.missing_expected_result": {
        "en": "Missing expected result",
        "uk": "Відсутній очікуваний результат",
        "ru": "Отсутствует ожидаемый результат",
    },
    "finding.missing_boundary": {
        "en": "Missing boundary conditions",
        "uk": "Відсутні граничні умови",
        "ru": "Отсутствуют граничные условия",
    },
    "finding.missing_error_handling": {
        "en": "Missing error handling",
        "uk": "Відсутня обробка помилок",
        "ru": "Отсутствует обработка ошибок",
    },
    "finding.contradiction": {
        "en": "Possible contradiction",
        "uk": "Можлива суперечність",
        "ru": "Возможное противоречие",
    },
    # --- Clarification questions (one per finding type) --------------------
    "question.ambiguous_wording": {
        "en": "What measurable criteria replace: {terms}?",
        "uk": "Якими вимірюваними критеріями замінити: {terms}?",
        "ru": "Какими измеримыми критериями заменить: {terms}?",
    },
    "question.missing_expected_result": {
        "en": "What exactly should the user or system observe when this requirement is met?",
        "uk": "Що саме має побачити користувач або система, коли вимогу виконано?",
        "ru": "Что именно должен увидеть пользователь или система, когда требование выполнено?",
    },
    "question.missing_boundary": {
        "en": "What are the exact limits or values for: {terms}?",
        "uk": "Які точні межі або значення для: {terms}?",
        "ru": "Каковы точные границы или значения для: {terms}?",
    },
    "question.missing_error_handling": {
        "en": "The requirement involves user input ({terms}). What should happen when the input is invalid or missing, or the action fails?",
        "uk": "Вимога стосується введення даних ({terms}). Що має статися, якщо дані некоректні чи відсутні або дія не вдалася?",
        "ru": "Требование касается ввода данных ({terms}). Что должно произойти, если данные некорректны или отсутствуют либо действие не удалось?",
    },
    "question.contradiction": {
        "en": "This conflicts with {related} ({terms}). Which rule is correct?",
        "uk": "Це суперечить {related} ({terms}). Яке правило правильне?",
        "ru": "Это противоречит {related} ({terms}). Какое правило верное?",
    },
    # =====================================================================
    # QA features: dashboard, RTM, quality, test cases, design, bugs, AI
    # =====================================================================
    "sidebar.privacy_ai": {
        "en": "AI is configured but sends nothing until you start an AI action and agree to send the data it needs. Everything else runs locally. Turn AI off in “AI settings”.",
        "uk": "ШІ налаштовано, але він нічого не надсилає, доки ви не запустите дію ШІ і не погодитеся надіслати потрібні їй дані. Усе інше працює локально. Вимкнути ШІ можна в «Налаштуваннях ШІ».",
        "ru": "ИИ настроен, но ничего не отправляет, пока вы не запустите действие ИИ и не согласитесь отправить нужные ему данные. Всё остальное работает локально. Выключить ИИ можно в «Настройках ИИ».",
    },
    "sidebar.storage": {
        "en": "Your edits are saved automatically on this computer.",
        "uk": "Ваші зміни автоматично зберігаються на цьому комп'ютері.",
        "ru": "Ваши изменения автоматически сохраняются на этом компьютере.",
    },
    "storage.restored": {
        "en": "Restored your saved work for this document (test cases, reviews and bug reports).",
        "uk": "Відновлено збережену роботу для цього документа (тест-кейси, рев'ю та баг-репорти).",
        "ru": "Восстановлена сохранённая работа для этого документа (тест-кейсы, ревью и баг-репорты).",
    },
    "storage.kept_in_session": {
        "en": "This document is already open in this session, so your edits (test cases, reviews and bug reports) are kept.",
        "uk": "Цей документ уже відкрито в цій сесії, тому ваші зміни (тест-кейси, рев'ю та баг-репорти) збережено.",
        "ru": "Этот документ уже открыт в этой сессии, поэтому ваши правки (тест-кейсы, ревью и баг-репорты) сохранены.",
    },
    "storage.save_failed": {
        "en": "Could not save your changes to disk. They are kept only until you close the page.",
        "uk": "Не вдалося зберегти зміни на диск. Вони збережуться лише до закриття сторінки.",
        "ru": "Не удалось сохранить изменения на диск. Они сохранятся только до закрытия страницы.",
    },
    # --- Tabs ----------------------------------------------------------------
    "tab.dashboard": {"en": "Dashboard", "uk": "Дашборд", "ru": "Дашборд"},
    "tab.rtm": {"en": "Traceability (RTM)", "uk": "Трасування (RTM)", "ru": "Трассировка (RTM)"},
    "tab.tests": {"en": "Test cases", "uk": "Тест-кейси", "ru": "Тест-кейсы"},
    "tab.design": {"en": "Test design", "uk": "Тест-дизайн", "ru": "Тест-дизайн"},
    "tab.defects": {"en": "Bug reports", "uk": "Баг-репорти", "ru": "Баг-репорты"},
    "tab.ai": {"en": "AI analysis", "uk": "Аналіз ШІ", "ru": "Анализ ИИ"},
    "tab.export": {"en": "Export", "uk": "Експорт", "ru": "Экспорт"},
    # --- Columns -------------------------------------------------------------
    "column.quality": {"en": "Quality score", "uk": "Оцінка якості", "ru": "Оценка качества"},
    "column.coverage": {"en": "Coverage", "uk": "Покриття", "ru": "Покрытие"},
    "column.open_issues": {"en": "Open issues", "uk": "Відкриті проблеми", "ru": "Открытые проблемы"},
    "column.test_cases": {"en": "Test cases", "uk": "Тест-кейси", "ru": "Тест-кейсы"},
    "column.approved": {"en": "Approved tests", "uk": "Затверджені тести", "ru": "Утверждённые тесты"},
    "column.bugs": {"en": "Bug reports", "uk": "Баг-репорти", "ru": "Баг-репорты"},
    "column.test_id": {"en": "Test ID", "uk": "ID тесту", "ru": "ID теста"},
    "column.bug_id": {"en": "Bug ID", "uk": "ID багу", "ru": "ID бага"},
    "column.ai_id": {"en": "Suggestion", "uk": "Пропозиція", "ru": "Предложение"},
    "column.title": {"en": "Title", "uk": "Назва", "ru": "Название"},
    "column.test_type": {"en": "Test type", "uk": "Тип тесту", "ru": "Тип теста"},
    "column.review": {"en": "Review status", "uk": "Статус рев'ю", "ru": "Статус ревью"},
    "column.description": {"en": "Description", "uk": "Опис", "ru": "Описание"},
    "column.quote": {"en": "Source quote", "uk": "Цитата з джерела", "ru": "Цитата из источника"},
    # --- Filters -------------------------------------------------------------
    "filter.all": {"en": "All", "uk": "Усі", "ru": "Все"},
    "filter.severity": {"en": "Issue severity", "uk": "Важливість проблем", "ru": "Важность проблем"},
    "filter.coverage": {"en": "Coverage", "uk": "Покриття", "ru": "Покрытие"},
    "filter.quality": {"en": "Quality", "uk": "Якість", "ru": "Качество"},
    "filter.search": {"en": "Search ID or text", "uk": "Пошук за ID або текстом", "ru": "Поиск по ID или тексту"},
    # --- Enum labels ---------------------------------------------------------
    "coverage.covered": {"en": "Covered", "uk": "Покрито", "ru": "Покрыто"},
    "coverage.partial": {"en": "Partially covered", "uk": "Частково покрито", "ru": "Частично покрыто"},
    "coverage.not_covered": {"en": "Not covered", "uk": "Не покрито", "ru": "Не покрыто"},
    "review.draft": {"en": "Draft", "uk": "Чернетка", "ru": "Черновик"},
    "review.reviewed": {"en": "Reviewed", "uk": "Переглянуто", "ru": "Проверено"},
    "review.approved": {"en": "Approved", "uk": "Затверджено", "ru": "Утверждено"},
    "grade.good": {"en": "Good", "uk": "Добра", "ru": "Хорошее"},
    "grade.fair": {"en": "Fair", "uk": "Задовільна", "ru": "Удовлетворительное"},
    "grade.poor": {"en": "Poor", "uk": "Низька", "ru": "Низкое"},
    "test_type.positive": {"en": "Positive", "uk": "Позитивний", "ru": "Позитивный"},
    "test_type.negative": {"en": "Negative", "uk": "Негативний", "ru": "Негативный"},
    "test_type.boundary": {"en": "Boundary values", "uk": "Граничні значення", "ru": "Граничные значения"},
    "test_type.equivalence": {"en": "Equivalence classes", "uk": "Класи еквівалентності", "ru": "Классы эквивалентности"},
    "test_type.decision_table": {"en": "Decision table", "uk": "Таблиця рішень", "ru": "Таблица решений"},
    "test_type.error_handling": {"en": "Error handling", "uk": "Обробка помилок", "ru": "Обработка ошибок"},
    "unit.characters": {"en": "characters", "uk": "символів", "ru": "символов"},
    "unit.minutes": {"en": "minutes", "uk": "хвилин", "ru": "минут"},
    "unit.seconds": {"en": "seconds", "uk": "секунд", "ru": "секунд"},
    "unit.hours": {"en": "hours", "uk": "годин", "ru": "часов"},
    "unit.days": {"en": "days", "uk": "днів", "ru": "дней"},
    "unit.attempts": {"en": "attempts", "uk": "спроб", "ru": "попыток"},
    "unit.megabytes": {"en": "MB", "uk": "МБ", "ru": "МБ"},
    "ai_type.ambiguity": {"en": "Ambiguity", "uk": "Неоднозначність", "ru": "Неоднозначность"},
    "ai_type.contradiction": {"en": "Contradiction", "uk": "Суперечність", "ru": "Противоречие"},
    "ai_type.missing_scenario": {"en": "Missing scenario", "uk": "Пропущений сценарій", "ru": "Пропущенный сценарий"},
    # --- Actions -------------------------------------------------------------
    "action.save": {"en": "Save", "uk": "Зберегти", "ru": "Сохранить"},
    "action.saved": {"en": "{id} saved.", "uk": "{id} збережено.", "ru": "{id} сохранён."},
    "action.delete": {"en": "Delete", "uk": "Видалити", "ru": "Удалить"},
    "action.deleted": {"en": "{id} deleted.", "uk": "{id} видалено.", "ru": "{id} удалён."},
    "action.confirm_delete": {
        "en": "Yes, delete {id}",
        "uk": "Так, видалити {id}",
        "ru": "Да, удалить {id}",
    },
    # --- Quality score -------------------------------------------------------
    "quality.heading": {
        "en": "Why does a requirement get this quality score?",
        "uk": "Чому вимога отримала таку оцінку якості?",
        "ru": "Почему требование получило такую оценку качества?",
    },
    "quality.explainer": {
        "en": "The score (0–100) is the sum of the criteria below. Only open rule-based findings reduce it; AI suggestions never change the score.",
        "uk": "Оцінка (0–100) — це сума критеріїв нижче. Її знижують лише відкриті знахідки на основі правил; пропозиції ШІ не впливають на оцінку.",
        "ru": "Оценка (0–100) — это сумма критериев ниже. Её снижают только открытые находки на основе правил; предложения ИИ не влияют на оценку.",
    },
    "quality.select": {"en": "Requirement", "uk": "Вимога", "ru": "Требование"},
    "quality.criterion": {"en": "Criterion", "uk": "Критерій", "ru": "Критерий"},
    "quality.points": {"en": "Points", "uk": "Бали", "ru": "Баллы"},
    "quality.rule": {"en": "How it is checked", "uk": "Як перевіряється", "ru": "Как проверяется"},
    "quality.evidence": {"en": "Evidence", "uk": "Підстава", "ru": "Основание"},
    "criterion.unambiguous": {"en": "Unambiguous", "uk": "Однозначність", "ru": "Однозначность"},
    "criterion.unambiguous.rule": {
        "en": "−10 per ambiguous term (fast, user-friendly, …)",
        "uk": "−10 за кожен неоднозначний термін (швидко, зручно, …)",
        "ru": "−10 за каждый неоднозначный термин (быстро, удобно, …)",
    },
    "criterion.expected_result": {"en": "Expected result", "uk": "Очікуваний результат", "ru": "Ожидаемый результат"},
    "criterion.expected_result.rule": {
        "en": "0 if no observable outcome is stated",
        "uk": "0, якщо не вказано результат, який можна перевірити",
        "ru": "0, если не указан проверяемый результат",
    },
    "criterion.consistent": {"en": "Consistent", "uk": "Узгодженість", "ru": "Согласованность"},
    "criterion.consistent.rule": {
        "en": "0 if it may contradict another requirement",
        "uk": "0, якщо можлива суперечність з іншою вимогою",
        "ru": "0, если возможно противоречие с другим требованием",
    },
    "criterion.boundaries": {"en": "Concrete limits", "uk": "Конкретні межі", "ru": "Конкретные границы"},
    "criterion.boundaries.rule": {
        "en": "0 if limits are mentioned without numbers",
        "uk": "0, якщо межі згадано без чисел",
        "ru": "0, если границы упомянуты без чисел",
    },
    "criterion.error_handling": {"en": "Error handling", "uk": "Обробка помилок", "ru": "Обработка ошибок"},
    "criterion.error_handling.rule": {
        "en": "0 if user input has no failure behavior",
        "uk": "0, якщо для введення даних не описано поведінку при помилці",
        "ru": "0, если для ввода данных не описано поведение при ошибке",
    },
    "criterion.atomic": {"en": "Atomic", "uk": "Атомарність", "ru": "Атомарность"},
    "criterion.atomic.rule": {
        "en": "0 if several sentences each contain an obligation (must, shall, …)",
        "uk": "0, якщо кілька речень містять зобов'язання (повинен, має, …)",
        "ru": "0, если несколько предложений содержат обязательство (должен, …)",
    },
    "criterion.identifiable": {"en": "Has an ID", "uk": "Має ID", "ru": "Есть ID"},
    "criterion.identifiable.rule": {
        "en": "0 if the ID was generated, not written in the document",
        "uk": "0, якщо ID згенеровано, а не вказано в документі",
        "ru": "0, если ID сгенерирован, а не указан в документе",
    },
    # --- Dashboard -----------------------------------------------------------
    "dash.requirements": {"en": "Requirements", "uk": "Вимоги", "ru": "Требования"},
    "dash.open_issues": {"en": "Open issues", "uk": "Відкриті проблеми", "ru": "Открытые проблемы"},
    "dash.test_cases": {"en": "Test cases", "uk": "Тест-кейси", "ru": "Тест-кейсы"},
    "dash.coverage": {"en": "Coverage", "uk": "Покриття", "ru": "Покрытие"},
    "dash.coverage_help": {
        "en": "Share of requirements with at least one Approved test case. With any test case (incl. drafts): {any}%.",
        "uk": "Частка вимог, які мають хоча б один затверджений тест-кейс. З будь-яким тест-кейсом (разом із чернетками): {any}%.",
        "ru": "Доля требований, у которых есть хотя бы один утверждённый тест-кейс. С любым тест-кейсом (включая черновики): {any}%.",
    },
    "dash.avg_quality": {"en": "Avg. quality", "uk": "Сер. якість", "ru": "Ср. качество"},
    "dash.severity_distribution": {"en": "Open issues by severity", "uk": "Відкриті проблеми за важливістю", "ru": "Открытые проблемы по важности"},
    "dash.coverage_distribution": {"en": "Requirements by coverage", "uk": "Вимоги за покриттям", "ru": "Требования по покрытию"},
    "dash.review_distribution": {"en": "Test cases by review status", "uk": "Тест-кейси за статусом рев'ю", "ru": "Тест-кейсы по статусу ревью"},
    "dash.no_match": {
        "en": "No requirements match the filters.",
        "uk": "Жодна вимога не відповідає фільтрам.",
        "ru": "Ни одно требование не соответствует фильтрам.",
    },
    "dash.ai_note": {
        "en": "AI suggestions ({count}) are not counted as issues — see the AI analysis tab.",
        "uk": "Пропозиції ШІ ({count}) не враховуються як проблеми — див. вкладку «Аналіз ШІ».",
        "ru": "Предложения ИИ ({count}) не учитываются как проблемы — см. вкладку «Анализ ИИ».",
    },
    # --- RTM -----------------------------------------------------------------
    "rtm.explainer": {
        "en": "Covered = at least one Approved test case. Partially covered = test cases exist but none is Approved. Not covered = no test cases.",
        "uk": "Покрито — є хоча б один затверджений тест-кейс. Частково покрито — тест-кейси є, але жоден не затверджено. Не покрито — тест-кейсів немає.",
        "ru": "Покрыто — есть хотя бы один утверждённый тест-кейс. Частично покрыто — тест-кейсы есть, но ни один не утверждён. Не покрыто — тест-кейсов нет.",
    },
    "rtm.orphans": {
        "en": "Test cases linked to unknown requirements: {ids}. They are not exported.",
        "uk": "Тест-кейси, пов'язані з невідомими вимогами: {ids}. Їх не буде експортовано.",
        "ru": "Тест-кейсы, связанные с неизвестными требованиями: {ids}. Они не экспортируются.",
    },
    # --- Test case editor ----------------------------------------------------
    "tests.explainer": {
        "en": "Generated test cases are drafts. Edit them, then move them through Draft → Reviewed → Approved. Only Approved tests count as coverage.",
        "uk": "Згенеровані тест-кейси — це чернетки. Відредагуйте їх і проведіть через статуси Чернетка → Переглянуто → Затверджено. Покриття рахують лише затверджені тести.",
        "ru": "Сгенерированные тест-кейсы — это черновики. Отредактируйте их и проведите через статусы Черновик → Проверено → Утверждено. Покрытие считают только утверждённые тесты.",
    },
    "tests.filter_requirement": {"en": "Show test cases for", "uk": "Показати тест-кейси для", "ru": "Показать тест-кейсы для"},
    "tests.add": {"en": "Add test case", "uk": "Додати тест-кейс", "ru": "Добавить тест-кейс"},
    "tests.generate_missing": {
        "en": "Generate drafts for uncovered requirements",
        "uk": "Згенерувати чернетки для непокритих вимог",
        "ru": "Сгенерировать черновики для непокрытых требований",
    },
    "tests.generated": {
        "en": "Created {count} draft test case(s).",
        "uk": "Створено тест-кейсів (чернеток): {count}.",
        "ru": "Создано тест-кейсов (черновиков): {count}.",
    },
    "tests.none": {"en": "No test cases yet.", "uk": "Тест-кейсів ще немає.", "ru": "Тест-кейсов пока нет."},
    "tests.select": {"en": "Edit test case", "uk": "Редагувати тест-кейс", "ru": "Редактировать тест-кейс"},
    "tests.open_questions": {
        "en": "Open questions — the requirement does not answer these yet:",
        "uk": "Відкриті питання — вимога поки не дає на них відповіді:",
        "ru": "Открытые вопросы — требование пока не отвечает на них:",
    },
    "tests.preconditions": {"en": "Preconditions (one per line)", "uk": "Передумови (по одній на рядок)", "ru": "Предусловия (по одному на строку)"},
    "tests.steps": {"en": "Steps (one per line)", "uk": "Кроки (по одному на рядок)", "ru": "Шаги (по одному на строку)"},
    "tests.expected": {"en": "Expected result", "uk": "Очікуваний результат", "ru": "Ожидаемый результат"},
    "tests.assumptions": {
        "en": "Assumptions — not confirmed by the requirement (one per line)",
        "uk": "Припущення — не підтверджені вимогою (по одному на рядок)",
        "ru": "Допущения — не подтверждены требованием (по одному на строку)",
    },
    "tests.comment": {"en": "Reviewer comment", "uk": "Коментар рецензента", "ru": "Комментарий ревьюера"},
    "tests.validation": {
        "en": "Title, at least one step and the expected result are required.",
        "uk": "Потрібні назва, хоча б один крок і очікуваний результат.",
        "ru": "Нужны название, хотя бы один шаг и ожидаемый результат.",
    },
    "tests.new_title": {"en": "New test case", "uk": "Новий тест-кейс", "ru": "Новый тест-кейс"},
    "tests.new_step": {"en": "Describe the first step", "uk": "Опишіть перший крок", "ru": "Опишите первый шаг"},
    "tests.new_expected": {"en": "Describe the expected result", "uk": "Опишіть очікуваний результат", "ru": "Опишите ожидаемый результат"},
    # --- Generated test case text ---------------------------------------------
    "tc.title_positive": {"en": "{req}: {text}", "uk": "{req}: {text}", "ru": "{req}: {text}"},
    "tc.title_decision": {
        "en": "{req}: decision table, rule R{rule}",
        "uk": "{req}: таблиця рішень, правило R{rule}",
        "ru": "{req}: таблица решений, правило R{rule}",
    },
    "tc.title_boundary": {
        "en": "{req}: boundary values for “{phrase}”",
        "uk": "{req}: граничні значення для «{phrase}»",
        "ru": "{req}: граничные значения для «{phrase}»",
    },
    "tc.title_equivalence": {
        "en": "{req}: equivalence classes for “{phrase}”",
        "uk": "{req}: класи еквівалентності для «{phrase}»",
        "ru": "{req}: классы эквивалентности для «{phrase}»",
    },
    "tc.pre_reference": {
        "en": "The behavior described in {req} is available for testing.",
        "uk": "Поведінка, описана в {req}, доступна для тестування.",
        "ru": "Поведение, описанное в {req}, доступно для тестирования.",
    },
    "tc.step_prepare": {
        "en": "Set up the conditions described in {req}.",
        "uk": "Підготуйте умови, описані в {req}.",
        "ru": "Подготовьте условия, описанные в {req}.",
    },
    "tc.step_perform": {
        "en": "Perform the action described in the requirement.",
        "uk": "Виконайте дію, описану у вимозі.",
        "ru": "Выполните действие, описанное в требовании.",
    },
    "tc.step_observe": {
        "en": "Observe the system behavior.",
        "uk": "Перевірте поведінку системи.",
        "ru": "Проверьте поведение системы.",
    },
    "tc.step_condition": {
        "en": "Make sure that “{condition}” is {value}.",
        "uk": "Переконайтеся, що умова «{condition}» — {value}.",
        "ru": "Убедитесь, что условие «{condition}» — {value}.",
    },
    "tc.step_try_value": {
        "en": "Use the value {value} {unit}.",
        "uk": "Використайте значення {value} {unit}.",
        "ru": "Используйте значение {value} {unit}.",
    },
    "tc.step_partition": {
        "en": "Class {interval}: use {value} {unit}.",
        "uk": "Клас {interval}: використайте {value} {unit}.",
        "ru": "Класс {interval}: используйте {value} {unit}.",
    },
    "tc.value_expectation": {
        "en": "{value} {unit} → {expectation}",
        "uk": "{value} {unit} → {expectation}",
        "ru": "{value} {unit} → {expectation}",
    },
    "tc.expected_quote": {
        "en": "The system behaves as stated in the requirement: “{text}”",
        "uk": "Система поводиться так, як зазначено у вимозі: «{text}»",
        "ru": "Система ведёт себя так, как указано в требовании: «{text}»",
    },
    "tc.assumption_open_findings": {
        "en": "The requirement has open findings, so the expected result may change after clarification.",
        "uk": "Вимога має відкриті знахідки, тому очікуваний результат може змінитися після уточнення.",
        "ru": "У требования есть открытые находки, поэтому ожидаемый результат может измениться после уточнения.",
    },
    "tc.question_unspecified_rules": {
        "en": "The requirement does not say what happens in {count} condition combination(s). What is the expected behavior?",
        "uk": "Вимога не описує, що відбувається в комбінаціях умов (кількість: {count}). Яка очікувана поведінка?",
        "ru": "Требование не описывает, что происходит в комбинациях условий (количество: {count}). Какое ожидаемое поведение?",
    },
    "tc.question_exact_value": {
        "en": "What should happen just before and just after “{phrase}”?",
        "uk": "Що має відбуватися безпосередньо до і після «{phrase}»?",
        "ru": "Что должно происходить непосредственно до и после «{phrase}»?",
    },
    # --- Test design -----------------------------------------------------------
    "design.explainer": {
        "en": "Techniques are applied only where the requirement gives what they need: numbers with units (boundaries, classes) or explicit if/when conditions (decision table). Outcomes the requirement does not state are marked “not specified”, never guessed.",
        "uk": "Техніки застосовуються лише там, де вимога містить потрібні дані: числа з одиницями (межі, класи) або явні умови «якщо/коли» (таблиця рішень). Результати, яких немає у вимозі, позначаються як «не визначено» і не вигадуються.",
        "ru": "Техники применяются только там, где требование содержит нужные данные: числа с единицами (границы, классы) или явные условия «если/когда» (таблица решений). Результаты, которых нет в требовании, помечаются как «не определено» и не придумываются.",
    },
    "design.not_applicable": {
        "en": "No numeric limits or explicit conditions in this requirement, so these techniques do not apply.",
        "uk": "У цій вимозі немає числових меж або явних умов, тому ці техніки не застосовуються.",
        "ru": "В этом требовании нет числовых границ или явных условий, поэтому эти техники не применяются.",
    },
    "design.bva": {"en": "Boundary value analysis", "uk": "Аналіз граничних значень", "ru": "Анализ граничных значений"},
    "design.ep": {"en": "Equivalence partitioning", "uk": "Класи еквівалентності", "ru": "Классы эквивалентности"},
    "design.dt": {"en": "Decision table", "uk": "Таблиця рішень", "ru": "Таблица решений"},
    "design.connector_and": {"en": "all conditions must hold", "uk": "мають виконуватися всі умови", "ru": "должны выполняться все условия"},
    "design.connector_or": {"en": "any condition is enough", "uk": "достатньо будь-якої умови", "ru": "достаточно любого условия"},
    "design.value": {"en": "Value", "uk": "Значення", "ru": "Значение"},
    "design.partition": {"en": "Class", "uk": "Клас", "ru": "Класс"},
    "design.representative": {"en": "Test value", "uk": "Тестове значення", "ru": "Тестовое значение"},
    "design.expectation": {"en": "Expected", "uk": "Очікується", "ru": "Ожидается"},
    "design.rule": {"en": "Rule", "uk": "Правило", "ru": "Правило"},
    "design.outcome": {"en": "Outcome", "uk": "Результат", "ru": "Результат"},
    "design.valid": {"en": "accepted (valid)", "uk": "приймається (валідне)", "ru": "принимается (валидное)"},
    "design.invalid": {"en": "rejected (invalid)", "uk": "відхиляється (невалідне)", "ru": "отклоняется (невалидное)"},
    "design.stated": {"en": "as stated in the requirement", "uk": "як зазначено у вимозі", "ru": "как указано в требовании"},
    "design.unspecified": {"en": "not specified — needs clarification", "uk": "не визначено — потребує уточнення", "ru": "не определено — требует уточнения"},
    "design.true": {"en": "true", "uk": "так", "ru": "да"},
    "design.false": {"en": "false", "uk": "ні", "ru": "нет"},
    "design.unspecified_warning": {
        "en": "Some condition combinations have no outcome in the requirement. Ask the author instead of assuming one.",
        "uk": "Для деяких комбінацій умов вимога не вказує результат. Запитайте автора, а не припускайте.",
        "ru": "Для некоторых комбинаций условий требование не указывает результат. Спросите автора, а не предполагайте.",
    },
    # --- Bug reports -----------------------------------------------------------
    "bugs.explainer": {
        "en": "Bug reports describe problems in the requirements (not in the product). Generate them from open findings, then edit freely.",
        "uk": "Баг-репорти описують проблеми у вимогах (а не в продукті). Згенеруйте їх з відкритих знахідок і редагуйте як завгодно.",
        "ru": "Баг-репорты описывают проблемы в требованиях (а не в продукте). Сгенерируйте их из открытых находок и редактируйте как угодно.",
    },
    "bugs.generate": {
        "en": "Generate bug reports from open findings",
        "uk": "Згенерувати баг-репорти з відкритих знахідок",
        "ru": "Сгенерировать баг-репорты из открытых находок",
    },
    "bugs.generated": {
        "en": "Created {count} bug report(s).",
        "uk": "Створено баг-репортів: {count}.",
        "ru": "Создано баг-репортов: {count}.",
    },
    "bugs.none": {"en": "No bug reports yet.", "uk": "Баг-репортів ще немає.", "ru": "Баг-репортов пока нет."},
    "bugs.select": {"en": "Edit bug report", "uk": "Редагувати баг-репорт", "ru": "Редактировать баг-репорт"},
    "bugs.description": {"en": "Description", "uk": "Опис", "ru": "Описание"},
    "bugs.expected": {"en": "Expected behavior", "uk": "Очікувана поведінка", "ru": "Ожидаемое поведение"},
    "bugs.context": {"en": "Reproduction context", "uk": "Контекст відтворення", "ru": "Контекст воспроизведения"},
    "bugs.validation": {"en": "The title is required.", "uk": "Назва обов'язкова.", "ru": "Название обязательно."},
    "bug.title": {"en": "{issue} in {req}", "uk": "{issue} у {req}", "ru": "{issue} в {req}"},
    "bug.description.ambiguous_wording": {
        "en": "{req} uses wording that cannot be verified objectively: {terms}. Testers may interpret it differently.",
        "uk": "{req} містить формулювання, які не можна перевірити об'єктивно: {terms}. Тестувальники можуть тлумачити їх по-різному.",
        "ru": "{req} содержит формулировки, которые нельзя проверить объективно: {terms}. Тестировщики могут трактовать их по-разному.",
    },
    "bug.description.missing_expected_result": {
        "en": "{req} does not state an observable result, so a test cannot decide pass or fail.",
        "uk": "{req} не вказує результат, який можна спостерігати, тому тест не може визначити «пройдено» чи «не пройдено».",
        "ru": "{req} не указывает наблюдаемый результат, поэтому тест не может определить «пройдено» или «не пройдено».",
    },
    "bug.description.missing_boundary": {
        "en": "{req} mentions limits ({terms}) but gives no concrete values.",
        "uk": "{req} згадує межі ({terms}), але не вказує конкретних значень.",
        "ru": "{req} упоминает границы ({terms}), но не указывает конкретных значений.",
    },
    "bug.description.missing_error_handling": {
        "en": "{req} involves user input ({terms}) but does not describe what happens when the input is invalid or the action fails.",
        "uk": "{req} стосується введення даних ({terms}), але не описує, що відбувається, якщо дані некоректні або дія не вдалася.",
        "ru": "{req} касается ввода данных ({terms}), но не описывает, что происходит, если данные некорректны или действие не удалось.",
    },
    "bug.description.contradiction": {
        "en": "{req} may contradict {related}: {terms}.",
        "uk": "{req} може суперечити {related}: {terms}.",
        "ru": "{req} может противоречить {related}: {terms}.",
    },
    "bug.expected.ambiguous_wording": {
        "en": "The requirement uses measurable criteria (numbers, units, explicit conditions).",
        "uk": "Вимога використовує вимірювані критерії (числа, одиниці, явні умови).",
        "ru": "Требование использует измеримые критерии (числа, единицы, явные условия).",
    },
    "bug.expected.missing_expected_result": {
        "en": "The requirement states what the user or system observes when it is met.",
        "uk": "Вимога описує, що бачить користувач або система, коли її виконано.",
        "ru": "Требование описывает, что видит пользователь или система, когда оно выполнено.",
    },
    "bug.expected.missing_boundary": {
        "en": "The requirement gives exact limits (minimum, maximum, units).",
        "uk": "Вимога вказує точні межі (мінімум, максимум, одиниці).",
        "ru": "Требование указывает точные границы (минимум, максимум, единицы).",
    },
    "bug.expected.missing_error_handling": {
        "en": "The requirement describes the behavior for invalid input and failures (message, state, retry).",
        "uk": "Вимога описує поведінку при некоректних даних і збоях (повідомлення, стан, повтор).",
        "ru": "Требование описывает поведение при некорректных данных и сбоях (сообщение, состояние, повтор).",
    },
    "bug.expected.contradiction": {
        "en": "The related requirements agree on one rule.",
        "uk": "Пов'язані вимоги узгоджено на одному правилі.",
        "ru": "Связанные требования согласованы на одном правиле.",
    },
    "bug.expected.ai": {
        "en": "The requirement is clarified by its author.",
        "uk": "Вимогу уточнено її автором.",
        "ru": "Требование уточнено его автором.",
    },
    "bug.context_requirement": {"en": "{req}: “{text}”", "uk": "{req}: «{text}»", "ru": "{req}: «{text}»"},
    "bug.context_line": {
        "en": "Source document line: {line}",
        "uk": "Рядок у документі: {line}",
        "ru": "Строка в документе: {line}",
    },
    "bug.context_terms": {"en": "Matched text: {terms}", "uk": "Знайдений текст: {terms}", "ru": "Найденный текст: {terms}"},
    "bug.context_related": {"en": "Related {req}: “{text}”", "uk": "Пов'язана {req}: «{text}»", "ru": "Связанное {req}: «{text}»"},
    "bug.context_detected_rule": {
        "en": "Detected by: rule-based check (Spec-to-Test). Needs clarification.",
        "uk": "Виявлено: перевірка на основі правил (Spec-to-Test). Потребує уточнення.",
        "ru": "Обнаружено: проверка на основе правил (Spec-to-Test). Требует уточнения.",
    },
    "bug.context_detected_ai": {
        "en": "Detected by: AI suggestion ({model}). Not verified — confirm before filing.",
        "uk": "Виявлено: пропозиція ШІ ({model}). Не перевірено — підтвердьте перед реєстрацією.",
        "ru": "Обнаружено: предложение ИИ ({model}). Не проверено — подтвердите перед регистрацией.",
    },
    "bug.context_quote_verified": {
        "en": "Quote (found in the requirement): “{quote}”",
        "uk": "Цитата (знайдена у вимозі): «{quote}»",
        "ru": "Цитата (найдена в требовании): «{quote}»",
    },
    "bug.context_quote_unverified": {
        "en": "Quote (NOT found in the requirement text): “{quote}”",
        "uk": "Цитата (НЕ знайдена в тексті вимоги): «{quote}»",
        "ru": "Цитата (НЕ найдена в тексте требования): «{quote}»",
    },
    # --- AI analysis -----------------------------------------------------------
    "ai.explainer": {
        "en": "Optional. An AI model can look for ambiguities, contradictions and missing scenarios the rules may miss. AI output is a suggestion, kept separate from rule-based findings, and never changes scores or coverage.",
        "uk": "Необов'язково. Модель ШІ може шукати неоднозначності, суперечності та пропущені сценарії, які правила можуть не помітити. Результат ШІ — лише пропозиція, він зберігається окремо від знахідок на основі правил і не впливає на оцінки чи покриття.",
        "ru": "Необязательно. Модель ИИ может искать неоднозначности, противоречия и пропущенные сценарии, которые правила могут пропустить. Результат ИИ — лишь предложение, он хранится отдельно от находок на основе правил и не влияет на оценки или покрытие.",
    },
    "ai.not_configured": {
        "en": "AI is not configured (or is turned off in AI settings), and the app works fully without it. To enable it, set AI_PROVIDER (anthropic, openai or ollama) and the provider's key (ANTHROPIC_API_KEY or OPENAI_API_KEY; Ollama needs none) in a local .env file, install requirements-ai.txt (see README), and keep “Use AI features” on in AI settings.",
        "uk": "ШІ не налаштовано (або вимкнено в налаштуваннях ШІ), і застосунок повністю працює без нього. Щоб увімкнути, вкажіть AI_PROVIDER (anthropic, openai або ollama) і ключ провайдера (ANTHROPIC_API_KEY або OPENAI_API_KEY; Ollama ключа не потребує) у локальному файлі .env, встановіть requirements-ai.txt (див. README) і залиште «Використовувати функції ШІ» увімкненим у налаштуваннях ШІ.",
        "ru": "ИИ не настроен (или выключен в настройках ИИ), и приложение полностью работает без него. Чтобы включить, укажите AI_PROVIDER (anthropic, openai или ollama) и ключ провайдера (ANTHROPIC_API_KEY или OPENAI_API_KEY; Ollama ключ не нужен) в локальном файле .env, установите requirements-ai.txt (см. README) и оставьте «Использовать функции ИИ» включённым в настройках ИИ.",
    },
    "ai.configured": {
        "en": "Provider: **{provider}** · Model: **{model}**",
        "uk": "Провайдер: **{provider}** · Модель: **{model}**",
        "ru": "Провайдер: **{provider}** · Модель: **{model}**",
    },
    "ai.consent": {
        "en": "I agree to send the text of {count} requirement(s) to {provider} for this analysis.",
        "uk": "Я погоджуюся надіслати текст вимог (кількість: {count}) до {provider} для цього аналізу.",
        "ru": "Я согласен отправить текст требований (количество: {count}) в {provider} для этого анализа.",
    },
    "ai.run": {"en": "Run AI analysis", "uk": "Запустити аналіз ШІ", "ru": "Запустить анализ ИИ"},
    "ai.running": {"en": "Waiting for the AI model…", "uk": "Очікування відповіді моделі ШІ…", "ru": "Ожидание ответа модели ИИ…"},
    "ai.disclaimer": {
        "en": "AI suggestions from {model}. They are not confirmed facts — verify each one against the source requirement.",
        "uk": "Пропозиції ШІ від {model}. Це не підтверджені факти — перевірте кожну за вихідною вимогою.",
        "ru": "Предложения ИИ от {model}. Это не подтверждённые факты — проверьте каждое по исходному требованию.",
    },
    "ai.quote_legend": {
        "en": "✅ quote found verbatim in the requirement · ⚠️ quote not found — the reference may be inaccurate.",
        "uk": "✅ цитату дослівно знайдено у вимозі · ⚠️ цитату не знайдено — посилання може бути неточним.",
        "ru": "✅ цитата дословно найдена в требовании · ⚠️ цитата не найдена — ссылка может быть неточной.",
    },
    "ai.select": {"en": "Suggestion", "uk": "Пропозиція", "ru": "Предложение"},
    "ai.to_bug": {"en": "Create bug report from suggestion", "uk": "Створити баг-репорт з пропозиції", "ru": "Создать баг-репорт из предложения"},
    "ai.bug_exists": {
        "en": "A bug report for this suggestion already exists.",
        "uk": "Баг-репорт для цієї пропозиції вже існує.",
        "ru": "Баг-репорт для этого предложения уже существует.",
    },
    "ai.error.consent_required": {
        "en": "Please confirm that the requirements may be sent to the AI provider.",
        "uk": "Підтвердьте, що вимоги можна надіслати провайдеру ШІ.",
        "ru": "Подтвердите, что требования можно отправить провайдеру ИИ.",
    },
    "ai.error.sdk_missing": {
        "en": "The AI package is not installed. Run: pip install -r requirements-ai.txt",
        "uk": "Пакет ШІ не встановлено. Виконайте: pip install -r requirements-ai.txt",
        "ru": "Пакет ИИ не установлен. Выполните: pip install -r requirements-ai.txt",
    },
    "ai.error.auth": {
        "en": "The AI provider rejected the API key. Check ANTHROPIC_API_KEY or OPENAI_API_KEY in your settings.",
        "uk": "Провайдер ШІ відхилив API-ключ. Перевірте ANTHROPIC_API_KEY або OPENAI_API_KEY у налаштуваннях.",
        "ru": "Провайдер ИИ отклонил API-ключ. Проверьте ANTHROPIC_API_KEY или OPENAI_API_KEY в настройках.",
    },
    "ai.error.rate_limit": {
        "en": "The AI provider's rate limit was reached. Please try again later.",
        "uk": "Досягнуто ліміту запитів провайдера ШІ. Спробуйте пізніше.",
        "ru": "Достигнут лимит запросов провайдера ИИ. Попробуйте позже.",
    },
    "ai.error.connection": {
        "en": "Could not reach the AI provider. Check your internet connection (for Ollama: that the server is running).",
        "uk": "Не вдалося з'єднатися з провайдером ШІ. Перевірте підключення до інтернету (для Ollama — що сервер запущено).",
        "ru": "Не удалось связаться с провайдером ИИ. Проверьте подключение к интернету (для Ollama — что сервер запущен).",
    },
    "ai.error.api": {
        "en": "The AI request failed. Rule-based results are not affected.",
        "uk": "Запит до ШІ не вдався. Результати на основі правил не змінено.",
        "ru": "Запрос к ИИ не удался. Результаты на основе правил не изменены.",
    },
    "ai.error.refused": {
        "en": "The AI model declined this request. Rule-based results are not affected.",
        "uk": "Модель ШІ відхилила цей запит. Результати на основі правил не змінено.",
        "ru": "Модель ИИ отклонила этот запрос. Результаты на основе правил не изменены.",
    },
    "ai.error.truncated": {
        "en": "The AI response was cut off. Try analyzing fewer requirements at once.",
        "uk": "Відповідь ШІ обірвалася. Спробуйте аналізувати менше вимог за раз.",
        "ru": "Ответ ИИ оборвался. Попробуйте анализировать меньше требований за раз.",
    },
    "ai.error.invalid_response": {
        "en": "The AI response could not be read. Please try again.",
        "uk": "Не вдалося прочитати відповідь ШІ. Спробуйте ще раз.",
        "ru": "Не удалось прочитать ответ ИИ. Попробуйте ещё раз.",
    },
    # --- Export ----------------------------------------------------------------
    "export.explainer": {
        "en": "CSV files for Jira and TestRail import wizards, the traceability matrix, and a Markdown QA report. Exports always use your latest edits.",
        "uk": "CSV-файли для майстрів імпорту Jira і TestRail, матриця трасування та QA-звіт у Markdown. Експорт завжди містить ваші останні зміни.",
        "ru": "CSV-файлы для мастеров импорта Jira и TestRail, матрица трассировки и QA-отчёт в Markdown. Экспорт всегда содержит ваши последние изменения.",
    },
    "export.only_approved": {
        "en": "Export only Approved test cases",
        "uk": "Експортувати лише затверджені тест-кейси",
        "ru": "Экспортировать только утверждённые тест-кейсы",
    },
    "export.jira_issue_type": {
        "en": "Jira issue type for test cases (e.g. Task, or Test with Xray/Zephyr)",
        "uk": "Тип задачі Jira для тест-кейсів (напр. Task або Test з Xray/Zephyr)",
        "ru": "Тип задачи Jira для тест-кейсов (напр. Task или Test с Xray/Zephyr)",
    },
    "export.jira_tests": {"en": "Test cases → Jira CSV", "uk": "Тест-кейси → Jira CSV", "ru": "Тест-кейсы → Jira CSV"},
    "export.testrail": {"en": "Test cases → TestRail CSV", "uk": "Тест-кейси → TestRail CSV", "ru": "Тест-кейсы → TestRail CSV"},
    "export.jira_bugs": {"en": "Bug reports → Jira CSV", "uk": "Баг-репорти → Jira CSV", "ru": "Баг-репорты → Jira CSV"},
    "export.rtm": {"en": "Traceability matrix → CSV", "uk": "Матриця трасування → CSV", "ru": "Матрица трассировки → CSV"},
    "export.mapping": {"en": "Field mapping for import", "uk": "Відповідність полів для імпорту", "ru": "Соответствие полей для импорта"},
    "export.mapping_body": {
        "en": "**Jira** (System → External System Import → CSV): Summary → Summary, Issue Type → Issue Type, Priority → Priority, Description → Description, each Labels column → Labels.\n\n**TestRail** (Test Cases → Import → CSV, template *Test Case (Text)*): Title → Title, Section → Section, Type → Type, Priority → Priority, Preconditions → Preconditions, Steps → Steps, Expected Result → Expected Result, References → References.\n\nFull details: docs/EXPORTS.md.",
        "uk": "**Jira** (System → External System Import → CSV): Summary → Summary, Issue Type → Issue Type, Priority → Priority, Description → Description, кожна колонка Labels → Labels.\n\n**TestRail** (Test Cases → Import → CSV, шаблон *Test Case (Text)*): Title → Title, Section → Section, Type → Type, Priority → Priority, Preconditions → Preconditions, Steps → Steps, Expected Result → Expected Result, References → References.\n\nДокладніше: docs/EXPORTS.md.",
        "ru": "**Jira** (System → External System Import → CSV): Summary → Summary, Issue Type → Issue Type, Priority → Priority, Description → Description, каждая колонка Labels → Labels.\n\n**TestRail** (Test Cases → Import → CSV, шаблон *Test Case (Text)*): Title → Title, Section → Section, Type → Type, Priority → Priority, Preconditions → Preconditions, Steps → Steps, Expected Result → Expected Result, References → References.\n\nПодробнее: docs/EXPORTS.md.",
    },
    # --- v1.0.0 -------------------------------------------------------------
    "input.analyzing": {
        "en": "Analyzing requirements…",
        "uk": "Аналіз вимог…",
        "ru": "Анализ требований…",
    },
    "sidebar.storage_session": {
        "en": "Your work is kept only for this browser session and is not saved on the server.",
        "uk": "Ваша робота зберігається лише в цій сесії браузера і не записується на сервер.",
        "ru": "Ваша работа хранится только в этой сессии браузера и не записывается на сервер.",
    },
    "sidebar.secrets_invalid": {
        "en": "The secrets file could not be read. AI settings from it are ignored.",
        "uk": "Не вдалося прочитати файл секретів. Налаштування ШІ з нього ігноруються.",
        "ru": "Не удалось прочитать файл секретов. Настройки ИИ из него игнорируются.",
    },
    "sidebar.version": {"en": "Version {version}", "uk": "Версія {version}", "ru": "Версия {version}"},
    "ai.done": {
        "en": "AI analysis finished: {count} suggestion(s).",
        "uk": "Аналіз ШІ завершено, пропозицій: {count}.",
        "ru": "Анализ ИИ завершён, предложений: {count}.",
    },
    "export.markdown": {"en": "QA report → Markdown", "uk": "QA-звіт → Markdown", "ru": "QA-отчёт → Markdown"},
    "report.title": {"en": "Spec-to-Test QA report", "uk": "QA-звіт Spec-to-Test", "ru": "QA-отчёт Spec-to-Test"},
    "report.note": {
        "en": "Generated by Spec-to-Test. Findings are rule-based hints; test cases need human review.",
        "uk": "Створено Spec-to-Test. Знахідки — підказки на основі правил; тест-кейси потребують перевірки людиною.",
        "ru": "Создано Spec-to-Test. Находки — подсказки на основе правил; тест-кейсы требуют проверки человеком.",
    },
    "report.summary": {"en": "Summary", "uk": "Підсумок", "ru": "Сводка"},
    "report.metric": {"en": "Metric", "uk": "Показник", "ru": "Показатель"},
    "report.value": {"en": "Value", "uk": "Значення", "ru": "Значение"},
    # --- Projects ------------------------------------------------------------
    "projects.heading": {"en": "Projects", "uk": "Проєкти", "ru": "Проекты"},
    "projects.project": {"en": "Project", "uk": "Проєкт", "ru": "Проект"},
    "projects.default_name": {"en": "My project", "uk": "Мій проєкт", "ru": "Мой проект"},
    "projects.document": {
        "en": "Requirements document",
        "uk": "Документ із вимогами",
        "ru": "Документ с требованиями",
    },
    "projects.document_help": {
        "en": "Each document analyzed in this project is kept here with its own test cases, reviews and bug reports. Choose “New requirements” to add another one.",
        "uk": "Кожен документ, проаналізований у цьому проєкті, зберігається тут зі своїми тест-кейсами, рев'ю та баг-репортами. Оберіть «Нові вимоги», щоб додати ще один.",
        "ru": "Каждый документ, проанализированный в этом проекте, хранится здесь со своими тест-кейсами, ревью и баг-репортами. Выберите «Новые требования», чтобы добавить ещё один.",
    },
    "projects.new_document": {
        "en": "➕ New requirements",
        "uk": "➕ Нові вимоги",
        "ru": "➕ Новые требования",
    },
    "projects.document_option": {
        "en": "({count}) {title}",
        "uk": "({count}) {title}",
        "ru": "({count}) {title}",
    },
    "projects.untitled": {"en": "Document {id}", "uk": "Документ {id}", "ru": "Документ {id}"},
    "projects.document_count": {
        "en": "Documents in this project: {count}",
        "uk": "Документів у проєкті: {count}",
        "ru": "Документов в проекте: {count}",
    },
    "projects.new_heading": {"en": "New project", "uk": "Новий проєкт", "ru": "Новый проект"},
    "projects.settings_heading": {
        "en": "Project settings",
        "uk": "Налаштування проєкту",
        "ru": "Настройки проекта",
    },
    "projects.name": {"en": "Name", "uk": "Назва", "ru": "Название"},
    "projects.name_placeholder": {
        "en": "e.g. Mobile banking app",
        "uk": "напр. Мобільний банкінг",
        "ru": "напр. Мобильный банкинг",
    },
    "projects.description": {"en": "Description", "uk": "Опис", "ru": "Описание"},
    "projects.create": {"en": "Create project", "uk": "Створити проєкт", "ru": "Создать проект"},
    "projects.save": {"en": "Save", "uk": "Зберегти", "ru": "Сохранить"},
    "projects.confirm_delete": {
        "en": "I understand that deleting cannot be undone",
        "uk": "Я розумію, що видалення не можна скасувати",
        "ru": "Я понимаю, что удаление нельзя отменить",
    },
    "projects.delete_document": {
        "en": "Delete this document",
        "uk": "Видалити цей документ",
        "ru": "Удалить этот документ",
    },
    "projects.delete_project": {
        "en": "Delete project",
        "uk": "Видалити проєкт",
        "ru": "Удалить проект",
    },
    "projects.created": {
        "en": "Project “{name}” created. Add its requirements below.",
        "uk": "Проєкт «{name}» створено. Додайте його вимоги нижче.",
        "ru": "Проект «{name}» создан. Добавьте его требования ниже.",
    },
    "projects.saved": {
        "en": "Project “{name}” saved.",
        "uk": "Проєкт «{name}» збережено.",
        "ru": "Проект «{name}» сохранён.",
    },
    "projects.deleted": {
        "en": "Project “{name}” deleted.",
        "uk": "Проєкт «{name}» видалено.",
        "ru": "Проект «{name}» удалён.",
    },
    "projects.document_deleted": {
        "en": "Document deleted from the project.",
        "uk": "Документ видалено з проєкту.",
        "ru": "Документ удалён из проекта.",
    },
    "projects.error.name_required": {
        "en": "Enter a project name.",
        "uk": "Введіть назву проєкту.",
        "ru": "Введите название проекта.",
    },
    "projects.error.name_too_long": {
        "en": "The name is too long (at most 80 characters).",
        "uk": "Назва задовга (максимум 80 символів).",
        "ru": "Название слишком длинное (максимум 80 символов).",
    },
    "projects.error.name_taken": {
        "en": "A project with this name already exists.",
        "uk": "Проєкт із такою назвою вже існує.",
        "ru": "Проект с таким названием уже существует.",
    },
    "projects.error.description_too_long": {
        "en": "The description is too long (at most 500 characters).",
        "uk": "Опис задовгий (максимум 500 символів).",
        "ru": "Описание слишком длинное (максимум 500 символов).",
    },
    "projects.error.save_failed": {
        "en": "Could not save the project.",
        "uk": "Не вдалося зберегти проєкт.",
        "ru": "Не удалось сохранить проект.",
    },
    "projects.error.delete_failed": {
        "en": "Could not delete it. Please try again.",
        "uk": "Не вдалося видалити. Спробуйте ще раз.",
        "ru": "Не удалось удалить. Попробуйте ещё раз.",
    },
    "projects.input_heading": {
        "en": "Project: {name}. **Analyze** adds the text below to this project as a document; each document keeps its own requirements, test cases and bug reports.",
        "uk": "Проєкт: {name}. **Аналізувати** додає текст нижче до цього проєкту як документ; кожен документ має власні вимоги, тест-кейси та баг-репорти.",
        "ru": "Проект: {name}. **Анализировать** добавляет текст ниже в этот проект как документ; у каждого документа свои требования, тест-кейсы и баг-репорты.",
    },
}

# Grill Mode text lives in its own module; keys must not collide.
assert not TRANSLATIONS.keys() & GRILL_TRANSLATIONS.keys()
TRANSLATIONS.update(GRILL_TRANSLATIONS)
# Automation tab text, same rule.
assert not TRANSLATIONS.keys() & AUTOMATION_TRANSLATIONS.keys()
TRANSLATIONS.update(AUTOMATION_TRANSLATIONS)
# LLM settings text, same rule.
assert not TRANSLATIONS.keys() & LLM_TRANSLATIONS.keys()
TRANSLATIONS.update(LLM_TRANSLATIONS)
# App shell and page layout text, same rule.
assert not TRANSLATIONS.keys() & UI_TRANSLATIONS.keys()
TRANSLATIONS.update(UI_TRANSLATIONS)
# Saved interviews, finding history, traceability and audit text, same rule.
assert not TRANSLATIONS.keys() & HISTORY_TRANSLATIONS.keys()
TRANSLATIONS.update(HISTORY_TRANSLATIONS)
# QA Agent page text, same rule.
assert not TRANSLATIONS.keys() & QA_AGENT_TRANSLATIONS.keys()
TRANSLATIONS.update(QA_AGENT_TRANSLATIONS)
# Autonomous QA text, same rule.
assert not TRANSLATIONS.keys() & AUTO_TRANSLATIONS.keys()
TRANSLATIONS.update(AUTO_TRANSLATIONS)


def t(key: str, lang: str = DEFAULT_LANGUAGE, **params: object) -> str:
    """Translate `key` into `lang`, filling in any {placeholders}."""
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return key  # makes missing keys easy to spot in the UI
    text = entry.get(lang) or entry[DEFAULT_LANGUAGE]
    return text.format(**params) if params else text


def clarification_question(finding: Finding, lang: str = DEFAULT_LANGUAGE) -> str:
    """Build the translated clarification question for a finding."""
    return t(
        f"question.{finding.type.value}",
        lang,
        terms=", ".join(f"\"{term}\"" for term in finding.matched_terms) or "—",
        related=", ".join(finding.related_requirement_ids) or "—",
    )
