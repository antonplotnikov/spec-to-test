"""QA task mode text in English, Ukrainian and Russian (merged into spec_to_test.i18n).

Lines of the result (qatask.summary.*, qatask.rec.*, ...) are filled from the
tools' output; {names} is a list of already translated names.
"""


def _e(en: str, uk: str, ru: str) -> dict[str, str]:
    return {"en": en, "uk": uk, "ru": ru}


TASK_TRANSLATIONS: dict[str, dict[str, str]] = {
    # --- Page -----------------------------------------------------------------
    "qaagent.mode.task": _e("QA task", "QA-задача", "QA-задача"),
    "qatask.explainer": _e(
        "Describe a QA task in plain words. The agent picks the matching checks (Test Case Critic, Scenario Coverage, Change Impact, Traceability, Suite Planner), runs them on the open document and sums up the result. It only reads: test case statuses change only after you confirm.",
        "Опишіть QA-задачу звичайними словами. Агент вибере відповідні перевірки (критик тест-кейсів, покриття сценаріїв, вплив змін, трасування, планувальник наборів), виконає їх на відкритому документі й підсумує результат. Агент лише читає: статуси тест-кейсів змінюються тільки після вашого підтвердження.",
        "Опишите QA-задачу обычными словами. Агент выберет подходящие проверки (критик тест-кейсов, покрытие сценариев, влияние изменений, трассировка, планировщик наборов), выполнит их на открытом документе и подведёт итог. Агент только читает: статусы тест-кейсов меняются только после вашего подтверждения.",
    ),
    "qatask.input": _e("Task", "Задача", "Задача"),
    "qatask.placeholder": _e(
        "e.g. Check the quality of TC-001 and TC-002 · What scenarios are not covered? · What changed since the previous version? · Plan a smoke suite · Approve TC-003",
        "напр. Перевір якість TC-001 і TC-002 · Які сценарії не покриті? · Що змінилося з попередньої версії? · Сплануй smoke-набір · Затверди TC-003",
        "напр. Проверь качество TC-001 и TC-002 · Какие сценарии не покрыты? · Что изменилось с прошлой версии? · Спланируй smoke-набор · Утверди TC-003",
    ),
    "qatask.run": _e("Run task", "Виконати задачу", "Выполнить задачу"),
    "qatask.limits": _e(
        "At most {steps} checks per task. Supported: test case quality, scenario coverage, change impact, traceability gaps, Smoke/Regression/Full suites, and approving or returning named test cases to Draft (with confirmation).",
        "Не більше {steps} перевірок на задачу. Підтримується: якість тест-кейсів, покриття сценаріїв, вплив змін, прогалини трасування, набори Smoke/Regression/Full, а також затвердження або повернення названих тест-кейсів у чернетку (з підтвердженням).",
        "Не более {steps} проверок на задачу. Поддерживается: качество тест-кейсов, покрытие сценариев, влияние изменений, пробелы трассировки, наборы Smoke/Regression/Full, а также утверждение или возврат названных тест-кейсов в черновик (с подтверждением).",
    ),
    "qatask.tool.critic": _e("Test Case Critic", "Критик тест-кейсів", "Критик тест-кейсов"),
    "qatask.tool.coverage": _e("Scenario Coverage", "Покриття сценаріїв", "Покрытие сценариев"),
    "qatask.tool.impact": _e("Change Impact", "Вплив змін", "Влияние изменений"),
    "qatask.tool.traceability": _e("Traceability", "Трасування", "Трассировка"),
    "qatask.tool.suites": _e("Suite Planner", "Планувальник наборів", "Планировщик наборов"),
    "qatask.plan": _e("Checks run: {tools}", "Виконані перевірки: {tools}", "Выполненные проверки: {tools}"),
    "qatask.scope": _e(
        "Scope: {ids}. Change Impact and Suite Planner always look at the whole document.",
        "Область: {ids}. Вплив змін і планувальник наборів завжди охоплюють увесь документ.",
        "Область: {ids}. Влияние изменений и планировщик наборов всегда охватывают весь документ.",
    ),
    "qatask.scope_all": _e("Scope: the whole document", "Область: увесь документ", "Область: весь документ"),
    "qatask.heading.conclusions": _e("Conclusions", "Висновки", "Выводы"),
    "qatask.heading.problems": _e("Problems ({count})", "Проблеми ({count})", "Проблемы ({count})"),
    "qatask.heading.unknowns": _e("Unknown ({count})", "Невідомо ({count})", "Неизвестно ({count})"),
    "qatask.heading.recommendations": _e("Recommendations", "Рекомендації", "Рекомендации"),
    "qatask.heading.action": _e("Proposed change", "Запропонована зміна", "Предлагаемое изменение"),
    "qatask.no_problems": _e("No problems found by these checks.", "Ці перевірки не знайшли проблем.", "Эти проверки не нашли проблем."),
    "qatask.no_recommendations": _e("Nothing to do.", "Нічого робити не потрібно.", "Ничего делать не нужно."),
    "qatask.status.done": _e("Done", "Виконано", "Выполнено"),
    "qatask.status.partial": _e(
        "Done in part: some checks failed.", "Виконано частково: деякі перевірки не вдалися.",
        "Выполнено частично: некоторые проверки не удались.",
    ),
    "qatask.step_failed": _e(
        "{tool} failed ({error}); its result is missing.", "{tool}: помилка ({error}); результату немає.",
        "{tool}: ошибка ({error}); результата нет.",
    ),
    "qatask.unsupported": _e(
        "This task is not supported. The agent can check test case quality, scenario coverage, change impact, traceability gaps and Smoke/Regression/Full suites, and approve or return named test cases to Draft.",
        "Ця задача не підтримується. Агент може перевірити якість тест-кейсів, покриття сценаріїв, вплив змін, прогалини трасування й набори Smoke/Regression/Full, а також затвердити або повернути названі тест-кейси в чернетку.",
        "Эта задача не поддерживается. Агент может проверить качество тест-кейсов, покрытие сценариев, влияние изменений, пробелы трассировки и наборы Smoke/Regression/Full, а также утвердить или вернуть названные тест-кейсы в черновик.",
    ),
    "qatask.unsupported_terms": _e(
        "Not done by this agent: {terms}. It only analyzes the document and proposes status changes; use the other pages to run, generate, edit or delete.",
        "Цей агент не виконує: {terms}. Він лише аналізує документ і пропонує зміну статусів; щоб запускати, генерувати, редагувати чи видаляти, використовуйте інші сторінки.",
        "Этот агент не выполняет: {terms}. Он только анализирует документ и предлагает изменение статусов; чтобы запускать, генерировать, редактировать или удалять, используйте другие страницы.",
    ),
    "qatask.unknown_ids": _e(
        "Not in this document: {ids}.", "Немає в цьому документі: {ids}.", "Нет в этом документе: {ids}.",
    ),
    "qatask.skipped_tools": _e(
        "Step limit ({max}) reached; not run: {tools}.", "Досягнуто ліміту кроків ({max}); не виконано: {tools}.",
        "Достигнут лимит шагов ({max}); не выполнено: {tools}.",
    ),
    "qatask.action_needs_ids": _e(
        "To change test case statuses, name the test cases (e.g. TC-003).",
        "Щоб змінити статуси тест-кейсів, назвіть їх (напр. TC-003).",
        "Чтобы изменить статусы тест-кейсов, назовите их (напр. TC-003).",
    ),
    "qatask.action_too_large": _e(
        "A status change can name at most {max} test cases.", "Зміна статусу може стосуватися не більше {max} тест-кейсів.",
        "Изменение статуса может касаться не более {max} тест-кейсов.",
    ),
    "qatask.error.empty": _e("Enter a task.", "Введіть задачу.", "Введите задачу."),
    "qatask.error.too_long": _e(
        "The task is too long (at most {max} characters).", "Задача задовга (не більше {max} символів).",
        "Задача слишком длинная (не более {max} символов).",
    ),
    "qatask.error.all_failed": _e(
        "Every check failed; nothing could be concluded.", "Усі перевірки завершилися помилкою; висновків немає.",
        "Все проверки завершились ошибкой; выводов нет.",
    ),
    "qatask.error.unknown_ids": _e(
        "None of the IDs in the task are in this document: {ids}.", "Жодного з ID задачі немає в цьому документі: {ids}.",
        "Ни одного из ID задачи нет в этом документе: {ids}.",
    ),
    # --- Proposed change ------------------------------------------------------
    "qatask.action.describe": _e(
        "Set {ids} to **{status}**.", "Встановити для {ids} статус **{status}**.", "Установить для {ids} статус **{status}**.",
    ),
    "qatask.action.critic_warning": _e(
        "The critic found problems in these test cases (see Problems). The change is not blocked.",
        "Критик знайшов проблеми в цих тест-кейсах (див. «Проблеми»). Зміну не заблоковано.",
        "Критик нашёл проблемы в этих тест-кейсах (см. «Проблемы»). Изменение не заблокировано.",
    ),
    "qatask.action.confirm": _e(
        "I confirm this change", "Підтверджую цю зміну", "Подтверждаю это изменение",
    ),
    "qatask.action.apply": _e("Apply change", "Застосувати зміну", "Применить изменение"),
    "qatask.action.applied": _e(
        "Status changed to {status}: {ids}.", "Статус змінено на {status}: {ids}.", "Статус изменён на {status}: {ids}.",
    ),
    "qatask.action.unchanged": _e(
        "These test cases already have this status.", "Ці тест-кейси вже мають цей статус.",
        "У этих тест-кейсов уже этот статус.",
    ),
    "qatask.action.missing": _e(
        "Not applied: no longer in the document: {ids}.", "Не застосовано: більше немає в документі: {ids}.",
        "Не применено: больше нет в документе: {ids}.",
    ),
    # --- Conclusions ----------------------------------------------------------
    "qatask.summary.critic": _e(
        "Checked {checked} test cases; {problems} have problems.", "Перевірено тест-кейсів: {checked}; з проблемами: {problems}.",
        "Проверено тест-кейсов: {checked}; с проблемами: {problems}.",
    ),
    "qatask.summary.coverage": _e(
        "Checked {checked} requirements: {full} fully covered by Approved test cases, {incomplete} with missing scenarios.",
        "Перевірено вимог: {checked}; повністю покрито затвердженими тест-кейсами: {full}; з пропущеними сценаріями: {incomplete}.",
        "Проверено требований: {checked}; полностью покрыто утверждёнными тест-кейсами: {full}; с пропущенными сценариями: {incomplete}.",
    ),
    "qatask.summary.impact_none": _e(
        "No previous version of this document in the project, so there is nothing to compare.",
        "У проєкті немає попередньої версії цього документа, тож порівнювати нема з чим.",
        "В проекте нет предыдущей версии этого документа, поэтому сравнивать не с чем.",
    ),
    "qatask.summary.impact_unknown": _e(
        "The previous version of “{title}” could not be identified.", "Не вдалося визначити попередню версію «{title}».",
        "Не удалось определить предыдущую версию «{title}».",
    ),
    "qatask.summary.impact": _e(
        "Compared with the previous version “{title}”: {added} added, {modified} modified, {removed} removed, {unknown} unknown.",
        "Порівняно з попередньою версією «{title}»: додано {added}, змінено {modified}, видалено {removed}, невідомо {unknown}.",
        "Сравнено с предыдущей версией «{title}»: добавлено {added}, изменено {modified}, удалено {removed}, неизвестно {unknown}.",
    ),
    "qatask.summary.traceability": _e(
        "{requirements} requirements, {covered} with an Approved test case; {gaps} traceability gaps.",
        "Вимог: {requirements}, із затвердженим тест-кейсом: {covered}; прогалин трасування: {gaps}.",
        "Требований: {requirements}, с утверждённым тест-кейсом: {covered}; пробелов трассировки: {gaps}.",
    ),
    "qatask.summary.suites": _e(
        "Smoke: {smoke}, Regression: {regression}, Full: {full} test cases.",
        "Smoke: {smoke}, Регресія: {regression}, Повний: {full} тест-кейсів.",
        "Smoke: {smoke}, Регрессия: {regression}, Полный: {full} тест-кейсов.",
    ),
    # --- Problems and unknowns ------------------------------------------------
    "qatask.coverage.missing": _e(
        "no Approved test case for: {names}", "немає затвердженого тест-кейсу для: {names}",
        "нет утверждённого тест-кейса для: {names}",
    ),
    "qatask.coverage.unknown": _e(
        "the text is not enough to tell which scenarios apply", "тексту недостатньо, щоб визначити потрібні сценарії",
        "текста недостаточно, чтобы определить нужные сценарии",
    ),
    "qatask.coverage.unknown_categories": _e(
        "unclear whether these apply: {names}", "незрозуміло, чи потрібні: {names}", "неясно, нужны ли: {names}",
    ),
    "qatask.impact.previous_unknown": _e(
        "several documents titled “{title}” are equally recent", "кілька документів «{title}» однаково нові",
        "несколько документов «{title}» одинаково новые",
    ),
    "qatask.impact.test_case": _e(
        "test case of the previous version, linked to {req}: {names}",
        "тест-кейс попередньої версії, пов'язаний з {req}: {names}",
        "тест-кейс предыдущей версии, связанный с {req}: {names}",
    ),
    "qatask.impact.change_unknown": _e(
        "no reliable counterpart in the other version", "немає надійної відповідності в іншій версії",
        "нет надёжного соответствия в другой версии",
    ),
    "qatask.trace.untested": _e("no test case", "немає тест-кейсу", "нет тест-кейса"),
    "qatask.trace.unlinked": _e(
        "linked to a requirement that is not in the document", "пов'язаний з вимогою, якої немає в документі",
        "связан с требованием, которого нет в документе",
    ),
    "qatask.trace.not_approved": _e(
        "has test cases, but none is Approved", "має тест-кейси, але жоден не затверджено",
        "есть тест-кейсы, но ни один не утверждён",
    ),
    "qatask.trace.unknown": _e(
        "no test case; the text is not enough to tell what to test", "немає тест-кейсу; тексту недостатньо, щоб визначити, що тестувати",
        "нет тест-кейса; текста недостаточно, чтобы определить, что тестировать",
    ),
    "qatask.suites.no_approved": _e(
        "no Approved test cases, so Smoke and Regression are empty",
        "немає затверджених тест-кейсів, тому Smoke і Регресія порожні",
        "нет утверждённых тест-кейсов, поэтому Smoke и Регрессия пусты",
    ),
    "qatask.suites.smoke_missing": _e(
        "not represented in Smoke: {ids}", "не представлені в Smoke: {ids}", "не представлены в Smoke: {ids}",
    ),
    # --- Recommendations ------------------------------------------------------
    "qatask.rec.critic_fix": _e(
        "Fix the problems in {ids} before approving them.", "Виправте проблеми в {ids} перед затвердженням.",
        "Исправьте проблемы в {ids} перед утверждением.",
    ),
    "qatask.rec.critic_unknown": _e(
        "Clarify the requirements behind the Unknown items, then review those test cases again.",
        "Уточніть вимоги для пунктів «Невідомо», потім перегляньте ці тест-кейси ще раз.",
        "Уточните требования для пунктов «Неизвестно», затем проверьте эти тест-кейсы ещё раз.",
    ),
    "qatask.rec.coverage": _e(
        "Add and approve test cases for the missing scenarios of {ids}.",
        "Додайте й затвердьте тест-кейси для пропущених сценаріїв {ids}.",
        "Добавьте и утвердите тест-кейсы для пропущенных сценариев {ids}.",
    ),
    "qatask.rec.impact_compare_manually": _e(
        "Open the Analysis page and check which document is the previous version.",
        "Відкрийте сторінку аналізу й перевірте, який документ є попередньою версією.",
        "Откройте страницу анализа и проверьте, какой документ является предыдущей версией.",
    ),
    "qatask.rec.impact_review": _e(
        "Review the test cases of the previous version before reusing them: {ids}.",
        "Перегляньте тест-кейси попередньої версії перед повторним використанням: {ids}.",
        "Проверьте тест-кейсы предыдущей версии перед повторным использованием: {ids}.",
    ),
    "qatask.rec.impact_added": _e(
        "Write test cases for the new requirements: {ids}.", "Напишіть тест-кейси для нових вимог: {ids}.",
        "Напишите тест-кейсы для новых требований: {ids}.",
    ),
    "qatask.rec.trace_untested": _e(
        "Write test cases for {ids}.", "Напишіть тест-кейси для {ids}.", "Напишите тест-кейсы для {ids}.",
    ),
    "qatask.rec.trace_unlinked": _e(
        "Link {ids} to an existing requirement or delete them.", "Пов'яжіть {ids} з наявною вимогою або видаліть їх.",
        "Свяжите {ids} с существующим требованием или удалите их.",
    ),
    "qatask.rec.trace_approve": _e(
        "Review and approve a test case for {ids}.", "Перегляньте й затвердьте тест-кейс для {ids}.",
        "Проверьте и утвердите тест-кейс для {ids}.",
    ),
    "qatask.rec.trace_clarify": _e(
        "Clarify {ids} (Grill Mode) so it is clear what to test.", "Уточніть {ids} (Grill Mode), щоб було зрозуміло, що тестувати.",
        "Уточните {ids} (Grill Mode), чтобы было ясно, что тестировать.",
    ),
    "qatask.rec.suites_approve": _e(
        "Approve test cases to fill the Smoke and Regression suites.", "Затвердьте тест-кейси, щоб заповнити набори Smoke і Регресія.",
        "Утвердите тест-кейсы, чтобы заполнить наборы Smoke и Регрессия.",
    ),
    "qatask.rec.suites_smoke": _e(
        "Approve a Positive test case with High or Medium priority for each requirement missing from Smoke.",
        "Затвердьте позитивний тест-кейс із високим або середнім пріоритетом для кожної вимоги, якої немає в Smoke.",
        "Утвердите позитивный тест-кейс с высоким или средним приоритетом для каждого требования, которого нет в Smoke.",
    ),
    # --- Project memory -------------------------------------------------------
    "qamemory.heading": _e("Project memory ({count})", "Пам'ять проєкту ({count})", "Память проекта ({count})"),
    "qamemory.explainer": _e(
        "Rules you confirmed for this project and your ratings of task results. The agent's own answers are never saved. Entries are shown with a result only when they concern the same checks (and the same IDs, if they name any); they do not change what the checks compute.",
        "Правила, які ви підтвердили для цього проєкту, і ваші оцінки результатів задач. Власні відповіді агента ніколи не зберігаються. Записи показуються з результатом лише тоді, коли стосуються тих самих перевірок (і тих самих ID, якщо вони їх називають); вони не змінюють того, що обчислюють перевірки.",
        "Правила, которые вы подтвердили для этого проекта, и ваши оценки результатов задач. Собственные ответы агента никогда не сохраняются. Записи показываются с результатом, только когда касаются тех же проверок (и тех же ID, если они их называют); они не меняют того, что вычисляют проверки.",
    ),
    "qamemory.empty": _e("Nothing saved for this project yet.", "Для цього проєкту ще нічого не збережено.", "Для этого проекта пока ничего не сохранено."),
    "qamemory.pick": _e("Correct or delete an entry", "Виправити або видалити запис", "Исправить или удалить запись"),
    "qamemory.add_rule": _e("Add a project rule", "Додати правило проєкту", "Добавить правило проекта"),
    "qamemory.rule_text": _e("Rule", "Правило", "Правило"),
    "qamemory.tools": _e("Applies to", "Стосується", "Относится к"),
    "qamemory.rule_confirm": _e(
        "I checked that this rule holds for this project", "Я перевірив, що це правило діє для цього проєкту",
        "Я проверил, что это правило действует для этого проекта",
    ),
    "qamemory.save_rule": _e("Save rule", "Зберегти правило", "Сохранить правило"),
    "qamemory.save": _e("Save", "Зберегти", "Сохранить"),
    "qamemory.delete": _e("Delete", "Видалити", "Удалить"),
    "qamemory.delete_confirm": _e("Confirm deletion", "Підтвердити видалення", "Подтвердить удаление"),
    "qamemory.rule_saved": _e("Rule saved to project memory.", "Правило збережено в пам'яті проєкту.", "Правило сохранено в памяти проекта."),
    "qamemory.entry_saved": _e("Entry updated.", "Запис оновлено.", "Запись обновлена."),
    "qamemory.entry_deleted": _e("Entry deleted.", "Запис видалено.", "Запись удалена."),
    "qamemory.relevant_heading": _e(
        "From project memory", "З пам'яті проєкту", "Из памяти проекта",
    ),
    "qamemory.relevant_note": _e(
        "Saved by you earlier; not verified by the checks above.", "Збережено вами раніше; перевірки вище цього не перевіряли.",
        "Сохранено вами ранее; проверки выше этого не проверяли.",
    ),
    "qamemory.feedback_heading": _e("Was this result useful?", "Чи корисний цей результат?", "Был ли этот результат полезен?"),
    "qamemory.feedback_comment": _e("Comment (optional)", "Коментар (необов'язково)", "Комментарий (необязательно)"),
    "qamemory.feedback_for": _e("Rating of the task “{task}”", "Оцінка задачі «{task}»", "Оценка задачи «{task}»"),
    "qamemory.feedback_saved": _e(
        "Thanks, your rating is saved to project memory.", "Дякуємо, оцінку збережено в пам'яті проєкту.",
        "Спасибо, оценка сохранена в памяти проекта.",
    ),
    "qamemory.rating": _e("Rating", "Оцінка", "Оценка"),
    "qamemory.rating.useful": _e("Useful", "Корисно", "Полезно"),
    "qamemory.rating.not_useful": _e("Not useful", "Не корисно", "Не полезно"),
    "qamemory.error.not_confirmed": _e(
        "Confirm the rule before saving it.", "Підтвердьте правило перед збереженням.", "Подтвердите правило перед сохранением.",
    ),
    "qamemory.error.text_required": _e("Enter the rule.", "Введіть правило.", "Введите правило."),
    "qamemory.error.text_too_long": _e(
        "The text is too long.", "Текст задовгий.", "Текст слишком длинный.",
    ),
    "qamemory.error.no_tools": _e(
        "Choose at least one check it applies to.", "Виберіть хоча б одну перевірку, якої це стосується.",
        "Выберите хотя бы одну проверку, к которой это относится.",
    ),
    "qamemory.error.nothing_to_rate": _e(
        "No check ran, so there is nothing to rate.", "Жодна перевірка не виконалася, тож оцінювати нічого.",
        "Ни одна проверка не выполнилась, поэтому оценивать нечего.",
    ),
    "qamemory.error.full": _e(
        "Project memory is full; delete old entries first.", "Пам'ять проєкту заповнена; спершу видаліть старі записи.",
        "Память проекта заполнена; сначала удалите старые записи.",
    ),
    "qamemory.error.missing": _e(
        "This entry no longer exists.", "Цього запису більше немає.", "Этой записи больше нет.",
    ),
    "qamemory.error.save_failed": _e(
        "Project memory could not be saved.", "Не вдалося зберегти пам'ять проєкту.", "Не удалось сохранить память проекта.",
    ),
}
