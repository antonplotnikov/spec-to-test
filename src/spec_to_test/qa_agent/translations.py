"""QA Agent page text in English, Ukrainian and Russian (merged into spec_to_test.i18n)."""

QA_AGENT_TRANSLATIONS: dict[str, dict[str, str]] = {
    # --- Navigation ---------------------------------------------------------
    "ui.page.qa_agent": {"en": "QA Agent", "uk": "QA-агент", "ru": "QA-агент"},
    "ui.page.qa_agent.subtitle": {
        "en": "Plan, run and report browser tests against your authorized web app.",
        "uk": "Плануйте, запускайте й звітуйте про браузерні тести вашого авторизованого вебзастосунку.",
        "ru": "Планируйте, запускайте и формируйте отчёты по браузерным тестам вашего авторизованного веб-приложения.",
    },
    "qaagent.explainer": {
        "en": "Turn the document's test cases into an executable plan linked to requirement IDs, approve the cases, and run them in a real browser (Playwright). Every result comes from the run itself: status, screenshot, error and what the page showed.",
        "uk": "Перетворіть тест-кейси документа на виконуваний план, прив'язаний до ID вимог, затвердьте кейси й запустіть їх у справжньому браузері (Playwright). Кожен результат береться з самого запуску: статус, знімок екрана, помилка й те, що показала сторінка.",
        "ru": "Превратите тест-кейсы документа в исполняемый план, связанный с ID требований, утвердите кейсы и запустите их в настоящем браузере (Playwright). Каждый результат берётся из самого запуска: статус, снимок экрана, ошибка и то, что показала страница.",
    },
    "qaagent.tab.plan": {"en": "Test plan", "uk": "Тест-план", "ru": "Тест-план"},
    "qaagent.tab.run": {"en": "Run", "uk": "Запуск", "ru": "Запуск"},
    "qaagent.tab.history": {"en": "History", "uk": "Історія", "ru": "История"},
    "qaagent.tab.report": {"en": "QA report", "uk": "QA-звіт", "ru": "QA-отчёт"},
    # --- Setup --------------------------------------------------------------
    "qaagent.setup.heading": {"en": "Safety settings", "uk": "Налаштування безпеки", "ru": "Настройки безопасности"},
    "qaagent.setup.allowlist": {
        "en": "**Hosts you may test:** {hosts}",
        "uk": "**Хости, які можна тестувати:** {hosts}",
        "ru": "**Хосты, которые можно тестировать:** {hosts}",
    },
    "qaagent.setup.private_on": {
        "en": "Private and local addresses are allowed (AUTOMATION_ALLOW_PRIVATE_NETWORK). Cloud metadata addresses are always blocked.",
        "uk": "Приватні й локальні адреси дозволені (AUTOMATION_ALLOW_PRIVATE_NETWORK). Адреси хмарних метаданих заблоковані завжди.",
        "ru": "Частные и локальные адреса разрешены (AUTOMATION_ALLOW_PRIVATE_NETWORK). Адреса облачных метаданных заблокированы всегда.",
    },
    "qaagent.setup.private_off": {
        "en": "Only public addresses can be tested; private, local and cloud metadata addresses are blocked.",
        "uk": "Тестувати можна лише публічні адреси; приватні, локальні адреси й адреси хмарних метаданих заблоковані.",
        "ru": "Тестировать можно только публичные адреса; частные, локальные адреса и адреса облачных метаданных заблокированы.",
    },
    "qaagent.setup.secrets": {
        "en": "Secrets the steps can type (values come from the environment, never from the plan): {names}",
        "uk": "Секрети, які можуть вводити кроки (значення беруться з оточення, ніколи з плану): {names}",
        "ru": "Секреты, которые могут вводить шаги (значения берутся из окружения, никогда из плана): {names}",
    },
    "qaagent.setup.limits": {
        "en": "Limits: {cases} cases per run, {steps} steps per case, {step} s per step, {run} s per run. One run at a time.",
        "uk": "Обмеження: {cases} кейсів за запуск, {steps} кроків на кейс, {step} с на крок, {run} с на запуск. Один запуск за раз.",
        "ru": "Ограничения: {cases} кейсов за запуск, {steps} шагов на кейс, {step} с на шаг, {run} с на запуск. Один запуск за раз.",
    },
    "qaagent.setup.disabled": {
        "en": "Running tests is off: the operator has not allowed any host. Set AUTOMATION_ALLOWED_HOSTS (for example \"staging.example.com\" or \"127.0.0.1:8765\") in the server environment. You can still build and approve the plan.",
        "uk": "Запуск тестів вимкнено: оператор не дозволив жодного хоста. Задайте AUTOMATION_ALLOWED_HOSTS (наприклад \"staging.example.com\" або \"127.0.0.1:8765\") в оточенні сервера. План усе одно можна складати й затверджувати.",
        "ru": "Запуск тестов выключен: оператор не разрешил ни одного хоста. Задайте AUTOMATION_ALLOWED_HOSTS (например \"staging.example.com\" или \"127.0.0.1:8765\") в окружении сервера. План всё равно можно составлять и утверждать.",
    },
    "qaagent.setup.playwright_missing": {
        "en": "Python Playwright is not installed: pip install -r requirements-qa.txt && python -m playwright install chromium",
        "uk": "Python Playwright не встановлено: pip install -r requirements-qa.txt && python -m playwright install chromium",
        "ru": "Python Playwright не установлен: pip install -r requirements-qa.txt && python -m playwright install chromium",
    },
    # --- Plan ---------------------------------------------------------------
    "qaagent.url_label": {"en": "Web app URL", "uk": "URL вебзастосунку", "ru": "URL веб-приложения"},
    "qaagent.url_help": {
        "en": "Only hosts on the operator's allowlist can be tested. Steps with paths (\"/login\") are opened on this site.",
        "uk": "Тестувати можна лише хости з білого списку оператора. Кроки зі шляхами (\"/login\") відкриваються на цьому сайті.",
        "ru": "Тестировать можно только хосты из белого списка оператора. Шаги с путями (\"/login\") открываются на этом сайте.",
    },
    "qaagent.url_ok": {
        "en": "✅ This URL passes the allowlist and network safety checks.",
        "uk": "✅ Цей URL проходить перевірки білого списку й мережевої безпеки.",
        "ru": "✅ Этот URL проходит проверки белого списка и сетевой безопасности.",
    },
    "qaagent.plan.cases": {"en": "Plan cases", "uk": "Кейси плану", "ru": "Кейсы плана"},
    "qaagent.plan.approved": {"en": "Approved to run", "uk": "Затверджено до запуску", "ru": "Утверждено к запуску"},
    "qaagent.plan.needs_steps": {"en": "Need steps", "uk": "Потребують кроків", "ru": "Нуждаются в шагах"},
    "qaagent.generate.only_approved": {
        "en": "Only test cases with the Approved review status",
        "uk": "Лише тест-кейси зі статусом рев'ю «Затверджено»",
        "ru": "Только тест-кейсы со статусом ревью «Утверждено»",
    },
    "qaagent.generate.button": {
        "en": "Add cases from test cases", "uk": "Додати кейси з тест-кейсів", "ru": "Добавить кейсы из тест-кейсов",
    },
    "qaagent.generate.added": {
        "en": "Added {count} case(s) to the plan. Review their steps, then approve them.",
        "uk": "До плану додано кейсів: {count}. Перегляньте їхні кроки, потім затвердьте.",
        "ru": "В план добавлено кейсов: {count}. Проверьте их шаги, затем утвердите.",
    },
    "qaagent.generate.none_added": {
        "en": "No new test cases to add (every matching test case is already in the plan).",
        "uk": "Немає нових тест-кейсів для додавання (кожен відповідний тест-кейс уже в плані).",
        "ru": "Нет новых тест-кейсов для добавления (каждый подходящий тест-кейс уже в плане).",
    },
    "qaagent.add_case": {"en": "Add an empty case", "uk": "Додати порожній кейс", "ru": "Добавить пустой кейс"},
    "qaagent.new_case_title": {"en": "New browser test", "uk": "Новий браузерний тест", "ru": "Новый браузерный тест"},
    "qaagent.plan.import_export": {"en": "Import / export the plan", "uk": "Імпорт / експорт плану", "ru": "Импорт / экспорт плана"},
    "qaagent.plan.download": {"en": "Download the plan (JSON)", "uk": "Завантажити план (JSON)", "ru": "Скачать план (JSON)"},
    "qaagent.plan.import": {
        "en": "Plan file (JSON, replaces the current plan; approvals are not imported)",
        "uk": "Файл плану (JSON, замінює поточний план; затвердження не імпортуються)",
        "ru": "Файл плана (JSON, заменяет текущий план; утверждения не импортируются)",
    },
    "qaagent.plan.import_button": {"en": "Import", "uk": "Імпортувати", "ru": "Импортировать"},
    "qaagent.plan.imported": {
        "en": "Imported {count} case(s). Approve each one before running it.",
        "uk": "Імпортовано кейсів: {count}. Затвердьте кожен перед запуском.",
        "ru": "Импортировано кейсов: {count}. Утвердите каждый перед запуском.",
    },
    "qaagent.plan.save_failed": {
        "en": "The plan could not be saved; your changes are kept in this session only.",
        "uk": "Не вдалося зберегти план; зміни збережено лише в цьому сеансі.",
        "ru": "Не удалось сохранить план; изменения сохранены только в этом сеансе.",
    },
    "qaagent.plan.unknown_requirements": {
        "en": "These requirement IDs are not in the open document: {ids}. Coverage lists them separately.",
        "uk": "Цих ID вимог немає у відкритому документі: {ids}. Покриття показує їх окремо.",
        "ru": "Этих ID требований нет в открытом документе: {ids}. Покрытие показывает их отдельно.",
    },
    "qaagent.plan.empty": {"en": "The plan is empty", "uk": "План порожній", "ru": "План пуст"},
    "qaagent.plan.empty_body": {
        "en": "Add cases from the document's test cases, import a plan file, or add an empty case and write its steps.",
        "uk": "Додайте кейси з тест-кейсів документа, імпортуйте файл плану або додайте порожній кейс і напишіть кроки.",
        "ru": "Добавьте кейсы из тест-кейсов документа, импортируйте файл плана или добавьте пустой кейс и напишите шаги.",
    },
    "qaagent.syntax.heading": {"en": "How to write steps", "uk": "Як писати кроки", "ru": "Как писать шаги"},
    "qaagent.syntax.body": {
        "en": "One step per line: `action target | value`.\n\n"
              "- Actions: `goto /path`, `fill <target> | text`, `click <target>`, `select <target> | option`, `check <target>`, `uncheck <target>`, `press Enter`, `wait_for <target>`\n"
              "- Checks: `expect_text [target |] text`, `expect_no_text [target |] text`, `expect_visible <target>`, `expect_hidden <target>`, `expect_url /path`, `expect_title text`, `expect_value <target> | text`\n"
              "- Targets: `label=Email`, `role=button[name=Sign in]`, `text=Welcome`, `placeholder=Search`, `testid=submit`, or a CSS selector such as `#email`\n"
              "- `{{secret:NAME}}` types the secret AUTOMATION_SECRET_NAME; `{{empty}}` clears a field.\n\n"
              "Every case starts on the web app URL and needs at least one check. Steps are data: they are never run as code.",
        "uk": "Один крок на рядок: `дія ціль | значення`.\n\n"
              "- Дії: `goto /path`, `fill <ціль> | текст`, `click <ціль>`, `select <ціль> | опція`, `check <ціль>`, `uncheck <ціль>`, `press Enter`, `wait_for <ціль>`\n"
              "- Перевірки: `expect_text [ціль |] текст`, `expect_no_text [ціль |] текст`, `expect_visible <ціль>`, `expect_hidden <ціль>`, `expect_url /path`, `expect_title текст`, `expect_value <ціль> | текст`\n"
              "- Цілі: `label=Email`, `role=button[name=Sign in]`, `text=Welcome`, `placeholder=Search`, `testid=submit` або CSS-селектор, наприклад `#email`\n"
              "- `{{secret:NAME}}` вводить секрет AUTOMATION_SECRET_NAME; `{{empty}}` очищає поле.\n\n"
              "Кожен кейс починається з URL вебзастосунку й потребує щонайменше однієї перевірки. Кроки — це дані: вони ніколи не виконуються як код.",
        "ru": "Один шаг на строку: `действие цель | значение`.\n\n"
              "- Действия: `goto /path`, `fill <цель> | текст`, `click <цель>`, `select <цель> | опция`, `check <цель>`, `uncheck <цель>`, `press Enter`, `wait_for <цель>`\n"
              "- Проверки: `expect_text [цель |] текст`, `expect_no_text [цель |] текст`, `expect_visible <цель>`, `expect_hidden <цель>`, `expect_url /path`, `expect_title текст`, `expect_value <цель> | текст`\n"
              "- Цели: `label=Email`, `role=button[name=Sign in]`, `text=Welcome`, `placeholder=Search`, `testid=submit` или CSS-селектор, например `#email`\n"
              "- `{{secret:NAME}}` вводит секрет AUTOMATION_SECRET_NAME; `{{empty}}` очищает поле.\n\n"
              "Каждый кейс начинается с URL веб-приложения и требует хотя бы одной проверки. Шаги — это данные: они никогда не выполняются как код.",
    },
    # --- Case editor ----------------------------------------------------------
    "qaagent.case.badge_approved": {"en": "Approved", "uk": "Затверджено", "ru": "Утверждено"},
    "qaagent.case.badge_changed": {
        "en": "Changed after approval", "uk": "Змінено після затвердження", "ru": "Изменено после утверждения",
    },
    "qaagent.case.badge_needs_steps": {"en": "Needs steps", "uk": "Потрібні кроки", "ru": "Нужны шаги"},
    "qaagent.case.badge_draft": {"en": "Not approved", "uk": "Не затверджено", "ru": "Не утверждено"},
    "qaagent.origin.test_case": {"en": "From a test case", "uk": "З тест-кейсу", "ru": "Из тест-кейса"},
    "qaagent.origin.manual": {"en": "Written here", "uk": "Написано тут", "ru": "Написано здесь"},
    "qaagent.origin.ai": {"en": "Steps proposed by AI", "uk": "Кроки запропонував ШІ", "ru": "Шаги предложил ИИ"},
    "qaagent.origin.imported": {"en": "Imported", "uk": "Імпортовано", "ru": "Импортировано"},
    "qaagent.case.from_test_case": {"en": "Test case: {id}", "uk": "Тест-кейс: {id}", "ru": "Тест-кейс: {id}"},
    "qaagent.case.unparsed": {
        "en": "These written steps could not be turned into browser steps, so the case has none yet. Write the steps below (or ask AI to propose them).",
        "uk": "Ці написані кроки не вдалося перетворити на браузерні, тож кейс поки що без кроків. Напишіть кроки нижче (або попросіть ШІ їх запропонувати).",
        "ru": "Эти написанные шаги не удалось превратить в браузерные, поэтому у кейса пока нет шагов. Напишите шаги ниже (или попросите ИИ их предложить).",
    },
    "qaagent.case.title": {"en": "Title", "uk": "Назва", "ru": "Название"},
    "qaagent.case.requirement": {"en": "Requirement", "uk": "Вимога", "ru": "Требование"},
    "qaagent.case.steps": {"en": "Steps", "uk": "Кроки", "ru": "Шаги"},
    "qaagent.case.steps_help": {
        "en": "One step per line, see “How to write steps”. Editing an approved case revokes its approval.",
        "uk": "Один крок на рядок, див. «Як писати кроки». Редагування затвердженого кейсу скасовує затвердження.",
        "ru": "Один шаг на строку, см. «Как писать шаги». Редактирование утверждённого кейса отменяет утверждение.",
    },
    "qaagent.case.expected": {"en": "Expected result", "uk": "Очікуваний результат", "ru": "Ожидаемый результат"},
    "qaagent.case.save": {"en": "Save case", "uk": "Зберегти кейс", "ru": "Сохранить кейс"},
    "qaagent.case.saved": {"en": "{id} saved.", "uk": "{id} збережено.", "ru": "{id} сохранён."},
    "qaagent.case.saved_revoked": {
        "en": "{id} saved. It changed, so it must be approved again before it can run.",
        "uk": "{id} збережено. Кейс змінився, тож його треба затвердити знову перед запуском.",
        "ru": "{id} сохранён. Кейс изменился, поэтому его нужно утвердить снова перед запуском.",
    },
    "qaagent.case.added": {"en": "{id} added.", "uk": "{id} додано.", "ru": "{id} добавлен."},
    "qaagent.case.approve": {"en": "Approve to run", "uk": "Затвердити до запуску", "ru": "Утвердить к запуску"},
    "qaagent.case.approved": {"en": "{id} approved to run.", "uk": "{id} затверджено до запуску.", "ru": "{id} утверждён к запуску."},
    "qaagent.case.revoke": {"en": "Revoke approval", "uk": "Скасувати затвердження", "ru": "Отменить утверждение"},
    "qaagent.case.revoked": {
        "en": "Approval of {id} revoked.", "uk": "Затвердження {id} скасовано.", "ru": "Утверждение {id} отменено.",
    },
    "qaagent.case.delete": {"en": "Remove from plan", "uk": "Вилучити з плану", "ru": "Убрать из плана"},
    "qaagent.case.deleted": {"en": "{id} removed from the plan.", "uk": "{id} вилучено з плану.", "ru": "{id} убран из плана."},
    "qaagent.ai.button": {"en": "Propose steps", "uk": "Запропонувати кроки", "ru": "Предложить шаги"},
    "qaagent.ai.explainer": {
        "en": "{provider} receives the requirement, the test case text, the web app URL and the names of the secrets (never their values or page content). It proposes steps as data; you review and approve them.",
        "uk": "{provider} отримує вимогу, текст тест-кейсу, URL вебзастосунку й назви секретів (ніколи їхні значення чи вміст сторінок). Він пропонує кроки як дані; ви їх перевіряєте й затверджуєте.",
        "ru": "{provider} получает требование, текст тест-кейса, URL веб-приложения и названия секретов (никогда их значения или содержимое страниц). Он предлагает шаги как данные; вы их проверяете и утверждаете.",
    },
    "qaagent.ai.consent": {
        "en": "Send this case to the AI provider", "uk": "Надіслати цей кейс постачальнику ШІ",
        "ru": "Отправить этот кейс поставщику ИИ",
    },
    "qaagent.ai.run": {"en": "Propose", "uk": "Запропонувати", "ru": "Предложить"},
    "qaagent.ai.consent_needed": {
        "en": "Tick the consent box first: nothing is sent without it.",
        "uk": "Спершу поставте позначку згоди: без неї нічого не надсилається.",
        "ru": "Сначала поставьте отметку согласия: без неё ничего не отправляется.",
    },
    "qaagent.ai.done": {
        "en": "AI proposed steps for {id}. Review them, then approve the case.",
        "uk": "ШІ запропонував кроки для {id}. Перевірте їх, потім затвердьте кейс.",
        "ru": "ИИ предложил шаги для {id}. Проверьте их, затем утвердите кейс.",
    },
    # --- Step and plan errors ---------------------------------------------------
    "qaagent.step_error_line": {
        "en": "Line {line} (“{text}”): {problem}", "uk": "Рядок {line} («{text}»): {problem}",
        "ru": "Строка {line} («{text}»): {problem}",
    },
    "qaagent.step_error.action": {
        "en": "unknown action; see “How to write steps”.", "uk": "невідома дія; див. «Як писати кроки».",
        "ru": "неизвестное действие; см. «Как писать шаги».",
    },
    "qaagent.step_error.value": {
        "en": "this action needs a value and no target.", "uk": "цій дії потрібне значення без цілі.",
        "ru": "этому действию нужно значение без цели.",
    },
    "qaagent.step_error.target": {
        "en": "this action needs a target and no value.", "uk": "цій дії потрібна ціль без значення.",
        "ru": "этому действию нужна цель без значения.",
    },
    "qaagent.step_error.target_value": {
        "en": "write it as “target | value”.", "uk": "пишіть у форматі «ціль | значення».",
        "ru": "пишите в формате «цель | значение».",
    },
    "qaagent.step_error.role": {
        "en": "unknown role; use e.g. role=button[name=Save].", "uk": "невідома роль; напр. role=button[name=Save].",
        "ru": "неизвестная роль; напр. role=button[name=Save].",
    },
    "qaagent.step_error.key": {
        "en": "not a key name (e.g. Enter, Tab, Control+A).", "uk": "це не назва клавіші (напр. Enter, Tab, Control+A).",
        "ru": "это не название клавиши (напр. Enter, Tab, Control+A).",
    },
    "qaagent.step_error.secret": {
        "en": "{{secret:NAME}} can only be the whole value of a fill step.",
        "uk": "{{secret:NAME}} може бути лише всім значенням кроку fill.",
        "ru": "{{secret:NAME}} может быть только всем значением шага fill.",
    },
    "qaagent.step_error.too_long": {"en": "too long.", "uk": "задовго.", "ru": "слишком длинно."},
    "qaagent.plan_error.no_steps": {
        "en": "The case has no steps yet.", "uk": "У кейсі ще немає кроків.", "ru": "В кейсе ещё нет шагов.",
    },
    "qaagent.plan_error.no_assertion": {
        "en": "Add at least one check (expect_…), so a pass means something was verified.",
        "uk": "Додайте щонайменше одну перевірку (expect_…), щоб «пройдено» означало, що щось перевірено.",
        "ru": "Добавьте хотя бы одну проверку (expect_…), чтобы «пройдено» означало, что что-то проверено.",
    },
    "qaagent.plan_error.invalid_step": {
        "en": "A step is not valid.", "uk": "Один із кроків некоректний.", "ru": "Один из шагов некорректен.",
    },
    "qaagent.plan_error.title": {"en": "The title is empty.", "uk": "Назва порожня.", "ru": "Название пустое."},
    "qaagent.plan_error.too_large": {
        "en": "The file is too large (at most 1 MB).", "uk": "Файл завеликий (максимум 1 МБ).",
        "ru": "Файл слишком большой (максимум 1 МБ).",
    },
    "qaagent.plan_error.invalid_file": {
        "en": "This is not a QA Agent plan file.", "uk": "Це не файл плану QA-агента.",
        "ru": "Это не файл плана QA-агента.",
    },
    "qaagent.plan_error.too_many_cases": {
        "en": "The plan has too many cases (at most 500).", "uk": "У плані забагато кейсів (максимум 500).",
        "ru": "В плане слишком много кейсов (максимум 500).",
    },
    "qaagent.plan_error.duplicate_ids": {
        "en": "Two cases in the file have the same ID.", "uk": "Два кейси у файлі мають однаковий ID.",
        "ru": "Два кейса в файле имеют одинаковый ID.",
    },
    # --- Run --------------------------------------------------------------------
    "qaagent.run.summary": {
        "en": "**{count} of {total}** cases are approved to run against **{url}**.",
        "uk": "**{count} з {total}** кейсів затверджено до запуску на **{url}**.",
        "ru": "**{count} из {total}** кейсов утверждено к запуску на **{url}**.",
    },
    "qaagent.run.not_approved_note": {
        "en": "Cases that are not approved are recorded as Not run; nothing is executed without approval.",
        "uk": "Незатверджені кейси записуються як «Не запущено»; без затвердження нічого не виконується.",
        "ru": "Неутверждённые кейсы записываются как «Не запущено»; без утверждения ничего не выполняется.",
    },
    "qaagent.run.no_url": {
        "en": "Enter the web app URL on the Test plan tab.", "uk": "Введіть URL вебзастосунку на вкладці «Тест-план».",
        "ru": "Введите URL веб-приложения на вкладке «Тест-план».",
    },
    "qaagent.run.authorize": {
        "en": "I am authorized to test {host} and I approve running {count} case(s) against it now.",
        "uk": "Я маю дозвіл тестувати {host} і погоджую запуск {count} кейс(ів) на ньому зараз.",
        "ru": "У меня есть разрешение тестировать {host}, и я одобряю запуск {count} кейс(ов) на нём сейчас.",
    },
    "qaagent.run.destructive": {
        "en": "Allow destructive actions (delete, pay, cancel an order…)",
        "uk": "Дозволити руйнівні дії (видалення, оплата, скасування замовлення…)",
        "ru": "Разрешить разрушительные действия (удаление, оплата, отмена заказа…)",
    },
    "qaagent.run.destructive_help": {
        "en": "Off by default: a case that would click or open something that looks destructive is Blocked instead.",
        "uk": "Вимкнено за замовчуванням: кейс, який натиснув би або відкрив щось схоже на руйнівне, стає «Заблоковано».",
        "ru": "Выключено по умолчанию: кейс, который нажал бы или открыл что-то похожее на разрушительное, становится «Заблокировано».",
    },
    "qaagent.run.start": {
        "en": "Run {count} approved case(s)", "uk": "Запустити затверджені кейси ({count})",
        "ru": "Запустить утверждённые кейсы ({count})",
    },
    "qaagent.run.starting": {"en": "Starting the browser…", "uk": "Запуск браузера…", "ru": "Запуск браузера…"},
    "qaagent.run.progress": {
        "en": "{done} of {total}: {case} — {status}", "uk": "{done} з {total}: {case} — {status}",
        "ru": "{done} из {total}: {case} — {status}",
    },
    "qaagent.run.done": {
        "en": "Run finished: {passed} passed, {failed} failed, {blocked} blocked, {not_run} not run; {bugs} bug report(s). See History.",
        "uk": "Запуск завершено: пройдено {passed}, провалено {failed}, заблоковано {blocked}, не запущено {not_run}; баг-репортів: {bugs}. Див. «Історія».",
        "ru": "Запуск завершён: пройдено {passed}, провалено {failed}, заблокировано {blocked}, не запущено {not_run}; баг-репортов: {bugs}. См. «История».",
    },
    "qaagent.error.disabled": {
        "en": "Running tests is off until the operator sets AUTOMATION_ALLOWED_HOSTS.",
        "uk": "Запуск тестів вимкнено, доки оператор не задасть AUTOMATION_ALLOWED_HOSTS.",
        "ru": "Запуск тестов выключен, пока оператор не задаст AUTOMATION_ALLOWED_HOSTS.",
    },
    "qaagent.error.not_authorized": {
        "en": "Confirm that you are authorized to test this web app first.",
        "uk": "Спершу підтвердьте, що маєте дозвіл тестувати цей вебзастосунок.",
        "ru": "Сначала подтвердите, что у вас есть разрешение тестировать это веб-приложение.",
    },
    "qaagent.error.playwright_missing": {
        "en": "Python Playwright is not installed on this server (requirements-qa.txt).",
        "uk": "На цьому сервері не встановлено Python Playwright (requirements-qa.txt).",
        "ru": "На этом сервере не установлен Python Playwright (requirements-qa.txt).",
    },
    "qaagent.error.nothing_approved": {
        "en": "No case is approved yet. Approve cases on the Test plan tab.",
        "uk": "Жоден кейс ще не затверджено. Затвердьте кейси на вкладці «Тест-план».",
        "ru": "Ни один кейс ещё не утверждён. Утвердите кейсы на вкладке «Тест-план».",
    },
    "qaagent.error.busy": {
        "en": "Another run is using the browser. Try again when it has finished.",
        "uk": "Браузер зайнятий іншим запуском. Спробуйте, коли він завершиться.",
        "ru": "Браузер занят другим запуском. Попробуйте, когда он завершится.",
    },
    # --- Statuses and reasons ----------------------------------------------------
    "qaagent.status.passed": {"en": "Passed", "uk": "Пройдено", "ru": "Пройдено"},
    "qaagent.status.failed": {"en": "Failed", "uk": "Провалено", "ru": "Провалено"},
    "qaagent.status.blocked": {"en": "Blocked", "uk": "Заблоковано", "ru": "Заблокировано"},
    "qaagent.status.not_run": {"en": "Not run", "uk": "Не запущено", "ru": "Не запущено"},
    "qaagent.state.running": {"en": "running", "uk": "виконується", "ru": "выполняется"},
    "qaagent.state.completed": {"en": "completed", "uk": "завершено", "ru": "завершён"},
    "qaagent.state.aborted": {"en": "aborted", "uk": "перервано", "ru": "прерван"},
    "qaagent.reason.no_steps": {
        "en": "The case has no executable steps.", "uk": "У кейсі немає виконуваних кроків.",
        "ru": "В кейсе нет исполняемых шагов.",
    },
    "qaagent.reason.not_approved": {
        "en": "Not approved to run.", "uk": "Не затверджено до запуску.", "ru": "Не утверждён к запуску.",
    },
    "qaagent.reason.changed_after_approval": {
        "en": "Changed after it was approved; approve it again.", "uk": "Змінено після затвердження; затвердьте знову.",
        "ru": "Изменён после утверждения; утвердите снова.",
    },
    "qaagent.reason.no_assertion": {
        "en": "The case has no check (expect_…).", "uk": "У кейсі немає перевірки (expect_…).",
        "ru": "В кейсе нет проверки (expect_…).",
    },
    "qaagent.reason.too_many_steps": {
        "en": "More than {max} steps.", "uk": "Понад {max} кроків.", "ru": "Больше {max} шагов.",
    },
    "qaagent.reason.invalid_step": {
        "en": "Step {step} is not valid ({code}).", "uk": "Крок {step} некоректний ({code}).",
        "ru": "Шаг {step} некорректен ({code}).",
    },
    "qaagent.reason.secret_missing": {
        "en": "The secret {name} is not configured (AUTOMATION_SECRET_{name}).",
        "uk": "Секрет {name} не налаштовано (AUTOMATION_SECRET_{name}).",
        "ru": "Секрет {name} не настроен (AUTOMATION_SECRET_{name}).",
    },
    "qaagent.reason.destructive": {
        "en": "Stopped before a destructive action (“{term}”). Allow destructive actions to run it.",
        "uk": "Зупинено перед руйнівною дією («{term}»). Дозвольте руйнівні дії, щоб запустити.",
        "ru": "Остановлено перед разрушительным действием («{term}»). Разрешите разрушительные действия, чтобы запустить.",
    },
    "qaagent.reason.run_limit": {
        "en": "The run limit of {max} cases was reached.", "uk": "Досягнуто ліміту запуску: {max} кейсів.",
        "ru": "Достигнут лимит запуска: {max} кейсов.",
    },
    "qaagent.reason.run_timeout": {
        "en": "The run ran out of time.", "uk": "Час запуску вичерпано.", "ru": "Время запуска исчерпано.",
    },
    "qaagent.reason.browser": {
        "en": "The browser could not start.", "uk": "Не вдалося запустити браузер.", "ru": "Не удалось запустить браузер.",
    },
    "qaagent.reason.aborted": {
        "en": "The run stopped before this case.", "uk": "Запуск зупинився до цього кейсу.",
        "ru": "Запуск остановился до этого кейса.",
    },
    "qaagent.reason.assertion": {
        "en": "A check did not hold.", "uk": "Перевірка не виконалася.", "ru": "Проверка не выполнилась.",
    },
    "qaagent.reason.action_error": {
        "en": "A step could not be performed.", "uk": "Не вдалося виконати крок.", "ru": "Не удалось выполнить шаг.",
    },
    "qaagent.reason.http_status": {
        "en": "The server answered with HTTP {status}.", "uk": "Сервер відповів HTTP {status}.",
        "ru": "Сервер ответил HTTP {status}.",
    },
    "qaagent.reason.redirect": {
        "en": "The page tried to go outside the allowed hosts ({url}); the browser was stopped there.",
        "uk": "Сторінка намагалася вийти за межі дозволених хостів ({url}); браузер зупинено.",
        "ru": "Страница пыталась уйти за пределы разрешённых хостов ({url}); браузер остановлен.",
    },
    # --- History ----------------------------------------------------------------
    "qaagent.history.empty": {"en": "No runs yet", "uk": "Запусків ще немає", "ru": "Запусков ещё нет"},
    "qaagent.history.empty_body": {
        "en": "Approve cases on the Test plan tab and start a run on the Run tab.",
        "uk": "Затвердьте кейси на вкладці «Тест-план» і почніть запуск на вкладці «Запуск».",
        "ru": "Утвердите кейсы на вкладке «Тест-план» и начните запуск на вкладке «Запуск».",
    },
    "qaagent.history.select": {"en": "Run", "uk": "Запуск", "ru": "Запуск"},
    "qaagent.history.retest_badge": {"en": "retest", "uk": "повторний тест", "ru": "повторный тест"},
    "qaagent.history.meta": {
        "en": "Target {url} · started {started} · finished {finished} · {browser} · {state}",
        "uk": "Ціль {url} · початок {started} · кінець {finished} · {browser} · {state}",
        "ru": "Цель {url} · начало {started} · конец {finished} · {browser} · {state}",
    },
    "qaagent.history.parent": {
        "en": "Retest of run {id}.", "uk": "Повторний тест запуску {id}.", "ru": "Повторный тест запуска {id}.",
    },
    "qaagent.history.run_error": {
        "en": "The run reported an error:", "uk": "Запуск повідомив про помилку:", "ru": "Запуск сообщил об ошибке:",
    },
    "qaagent.history.expected": {"en": "Expected", "uk": "Очікувано", "ru": "Ожидалось"},
    "qaagent.history.actual": {"en": "Actual", "uk": "Фактично", "ru": "Фактически"},
    "qaagent.history.error": {"en": "Error", "uk": "Помилка", "ru": "Ошибка"},
    "qaagent.history.step": {"en": "Step", "uk": "Крок", "ru": "Шаг"},
    "qaagent.history.screenshot": {
        "en": "Screenshot at the end of the case ({name})", "uk": "Знімок екрана в кінці кейсу ({name})",
        "ru": "Снимок экрана в конце кейса ({name})",
    },
    "qaagent.history.console": {"en": "Browser console errors", "uk": "Помилки консолі браузера", "ru": "Ошибки консоли браузера"},
    "qaagent.history.blocked_requests": {
        "en": "Requests stopped by the network policy", "uk": "Запити, зупинені мережевою політикою",
        "ru": "Запросы, остановленные сетевой политикой",
    },
    "qaagent.history.retest_heading": {"en": "Retest", "uk": "Повторний тест", "ru": "Повторный тест"},
    "qaagent.history.nothing_to_retest": {
        "en": "Nothing failed or was blocked in this run.", "uk": "У цьому запуску нічого не провалилося й не заблоковано.",
        "ru": "В этом запуске ничего не провалилось и не заблокировано.",
    },
    "qaagent.history.retest": {
        "en": "Retest failed and blocked cases ({count})", "uk": "Перетестувати провалені й заблоковані кейси ({count})",
        "ru": "Перетестировать проваленные и заблокированные кейсы ({count})",
    },
    "qaagent.history.delete": {"en": "Delete this run", "uk": "Видалити цей запуск", "ru": "Удалить этот запуск"},
    "qaagent.history.deleted": {"en": "Run deleted.", "uk": "Запуск видалено.", "ru": "Запуск удалён."},
    # --- Bug reports ------------------------------------------------------------
    "qaagent.bug.title": {"en": "Summary", "uk": "Короткий опис", "ru": "Краткое описание"},
    "qaagent.bug.severity": {"en": "Severity", "uk": "Серйозність", "ru": "Серьёзность"},
    "qaagent.bug.save": {"en": "Save bug report", "uk": "Зберегти баг-репорт", "ru": "Сохранить баг-репорт"},
    "qaagent.bug.saved": {"en": "{id} saved.", "uk": "{id} збережено.", "ru": "{id} сохранён."},
    "qaagent.bug.steps": {"en": "Steps to reproduce", "uk": "Кроки відтворення", "ru": "Шаги воспроизведения"},
    "qaagent.bug.evidence": {"en": "Evidence", "uk": "Докази", "ru": "Доказательства"},
    "qaagent.bug.environment": {"en": "Environment", "uk": "Середовище", "ru": "Окружение"},
    # --- Report -------------------------------------------------------------------
    "qaagent.report.title": {"en": "QA report", "uk": "QA-звіт", "ru": "QA-отчёт"},
    "qaagent.report.target": {"en": "Target", "uk": "Ціль", "ru": "Цель"},
    "qaagent.report.run": {"en": "Run", "uk": "Запуск", "ru": "Запуск"},
    "qaagent.report.retest_of": {"en": "retest of", "uk": "повторний тест запуску", "ru": "повторный тест запуска"},
    "qaagent.report.document": {"en": "Document", "uk": "Документ", "ru": "Документ"},
    "qaagent.report.started": {"en": "Started", "uk": "Початок", "ru": "Начало"},
    "qaagent.report.finished": {"en": "Finished", "uk": "Кінець", "ru": "Конец"},
    "qaagent.report.state": {"en": "State", "uk": "Стан", "ru": "Состояние"},
    "qaagent.report.browser": {"en": "Browser", "uk": "Браузер", "ru": "Браузер"},
    "qaagent.report.summary": {"en": "Summary", "uk": "Підсумок", "ru": "Итог"},
    "qaagent.report.pass_rate": {"en": "Pass rate", "uk": "Частка пройдених", "ru": "Доля пройденных"},
    "qaagent.report.pass_rate_note": {
        "en": "Pass rate = passed / (passed + failed). Blocked and not-run cases are not counted as executed.",
        "uk": "Частка пройдених = пройдено / (пройдено + провалено). Заблоковані й незапущені кейси не вважаються виконаними.",
        "ru": "Доля пройденных = пройдено / (пройдено + провалено). Заблокированные и незапущенные кейсы не считаются выполненными.",
    },
    "qaagent.report.bugs": {"en": "Bugs", "uk": "Баги", "ru": "Баги"},
    "qaagent.report.coverage": {
        "en": "Requirement coverage", "uk": "Покриття вимог", "ru": "Покрытие требований",
    },
    "qaagent.report.cases": {"en": "Cases", "uk": "Кейси", "ru": "Кейсы"},
    "qaagent.report.result": {"en": "Result", "uk": "Результат", "ru": "Результат"},
    "qaagent.report.results": {"en": "Results", "uk": "Результати", "ru": "Результаты"},
    "qaagent.report.case": {"en": "Case", "uk": "Кейс", "ru": "Кейс"},
    "qaagent.report.case_title": {"en": "Title", "uk": "Назва", "ru": "Название"},
    "qaagent.report.reason": {"en": "Reason", "uk": "Причина", "ru": "Причина"},
    "qaagent.report.evidence": {"en": "Evidence", "uk": "Докази", "ru": "Доказательства"},
    "qaagent.report.screenshot_withheld": {
        "en": "Screenshot withheld: the page showed a secret value.",
        "uk": "Знімок екрана не збережено: сторінка показувала значення секрету.",
        "ru": "Снимок экрана не сохранён: страница показывала значение секрета.",
    },
    "qaagent.report.bug_reports": {"en": "Bug reports", "uk": "Баг-репорти", "ru": "Баг-репорты"},
    "qaagent.report.no_bugs": {
        "en": "No case failed in this run, so there are no bug reports.",
        "uk": "У цьому запуску жоден кейс не провалився, тож баг-репортів немає.",
        "ru": "В этом запуске ни один кейс не провалился, поэтому баг-репортов нет.",
    },
    "qaagent.report.requirements_passed": {
        "en": "Requirements passed", "uk": "Вимоги пройдено", "ru": "Требования пройдены",
    },
    "qaagent.report.requirements_failed": {
        "en": "Requirements failed", "uk": "Вимоги провалено", "ru": "Требования провалены",
    },
    "qaagent.report.downloads": {"en": "Downloads", "uk": "Завантаження", "ru": "Загрузки"},
    "qaagent.report.download_md": {"en": "Report (Markdown)", "uk": "Звіт (Markdown)", "ru": "Отчёт (Markdown)"},
    "qaagent.report.download_zip": {
        "en": "Report + screenshots (ZIP)", "uk": "Звіт + знімки екрана (ZIP)", "ru": "Отчёт + снимки экрана (ZIP)",
    },
    "qaagent.report.download_json": {"en": "Run data (JSON)", "uk": "Дані запуску (JSON)", "ru": "Данные запуска (JSON)"},
    "qaagent.report.download_results": {"en": "Results (CSV)", "uk": "Результати (CSV)", "ru": "Результаты (CSV)"},
    "qaagent.report.download_bugs": {"en": "Bug reports (CSV)", "uk": "Баг-репорти (CSV)", "ru": "Баг-репорты (CSV)"},
    "qaagent.report.not_run_note": {
        "en": "Some cases were not run; their requirements are not verified by this run.",
        "uk": "Деякі кейси не запускалися; їхні вимоги цей запуск не перевіряє.",
        "ru": "Некоторые кейсы не запускались; их требования этот запуск не проверяет.",
    },
    "qaagent.coverage.passed": {"en": "Passed", "uk": "Пройдено", "ru": "Пройдено"},
    "qaagent.coverage.partial": {
        "en": "Partly verified", "uk": "Частково перевірено", "ru": "Частично проверено",
    },
    "qaagent.coverage.failed": {"en": "Failed", "uk": "Провалено", "ru": "Провалено"},
    "qaagent.coverage.blocked": {"en": "Blocked", "uk": "Заблоковано", "ru": "Заблокировано"},
    "qaagent.coverage.not_run": {"en": "Not run", "uk": "Не запущено", "ru": "Не запущено"},
    "qaagent.coverage.not_covered": {"en": "No case", "uk": "Немає кейсу", "ru": "Нет кейса"},
}
