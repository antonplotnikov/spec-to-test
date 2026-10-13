"""Text for saved interviews, finding history, decision traceability and the audit log
in English, Ukrainian and Russian. Merged into spec_to_test.i18n.TRANSLATIONS."""

HISTORY_TRANSLATIONS: dict[str, dict[str, str]] = {
    # --- Saved interviews ----------------------------------------------------------
    "grill.ui.saved_heading": {
        "en": "Unfinished interviews ({count})", "uk": "Незавершені інтерв'ю ({count})",
        "ru": "Незавершённые интервью ({count})",
    },
    "grill.ui.saved_disk": {
        "en": "Saved on this computer after every answer; the last one reopens after a page reload.",
        "uk": "Зберігаються на цьому комп'ютері після кожної відповіді; останнє відкривається знову після перезавантаження сторінки.",
        "ru": "Сохраняются на этом компьютере после каждого ответа; последнее открывается снова после перезагрузки страницы.",
    },
    "grill.ui.saved_session": {
        "en": "Kept in this browser session only. To continue after a reload or on another device, use “Save progress to a file”.",
        "uk": "Зберігаються лише в цьому сеансі браузера. Щоб продовжити після перезавантаження чи на іншому пристрої, скористайтеся «Зберегти прогрес у файл».",
        "ru": "Хранятся только в этом сеансе браузера. Чтобы продолжить после перезагрузки или на другом устройстве, используйте «Сохранить прогресс в файл».",
    },
    "grill.ui.saved_none": {
        "en": "No unfinished interviews in this project.", "uk": "У цьому проєкті немає незавершених інтерв'ю.",
        "ru": "В этом проекте нет незавершённых интервью.",
    },
    "grill.ui.saved_progress": {"en": "{done}/{total} handled", "uk": "Опрацьовано {done}/{total}", "ru": "Обработано {done}/{total}"},
    "grill.ui.saved_open": {"en": "{count} open", "uk": "Відкритих: {count}", "ru": "Открытых: {count}"},
    "grill.ui.saved_when": {"en": "Last change: {time} (UTC)", "uk": "Остання зміна: {time} (UTC)", "ru": "Последнее изменение: {time} (UTC)"},
    "grill.ui.untitled": {"en": "Untitled draft", "uk": "Чернетка без назви", "ru": "Черновик без названия"},
    "grill.ui.resume_interview": {"en": "Resume", "uk": "Продовжити", "ru": "Продолжить"},
    "grill.ui.resume_help": {
        "en": "Continue exactly where you stopped: answers, question history and open questions are restored.",
        "uk": "Продовжити з того самого місця: відповіді, історія питань і відкриті питання відновлюються.",
        "ru": "Продолжить с того же места: ответы, история вопросов и открытые вопросы восстанавливаются.",
    },
    "grill.ui.open_interview": {"en": "Open", "uk": "Відкрити", "ru": "Открыть"},
    "grill.ui.delete_interview": {"en": "Delete", "uk": "Видалити", "ru": "Удалить"},
    "grill.ui.delete_confirm": {
        "en": "Delete this saved interview? Its answers and history are removed for good.",
        "uk": "Видалити це збережене інтерв'ю? Його відповіді та історію буде видалено назавжди.",
        "ru": "Удалить это сохранённое интервью? Его ответы и история будут удалены навсегда.",
    },
    "grill.ui.delete_yes": {"en": "Yes, delete", "uk": "Так, видалити", "ru": "Да, удалить"},
    "grill.ui.finished_heading": {
        "en": "Finished and cancelled ({count})", "uk": "Завершені та скасовані ({count})",
        "ru": "Завершённые и отменённые ({count})",
    },
    "grill.ui.import_label": {
        "en": "Resume from a file (.json saved with “Save progress to a file”)",
        "uk": "Продовжити з файлу (.json, збережений через «Зберегти прогрес у файл»)",
        "ru": "Продолжить из файла (.json, сохранённый через «Сохранить прогресс в файл»)",
    },
    "grill.ui.import_help": {
        "en": "The file is checked before use; older versions are upgraded, anything invalid is refused.",
        "uk": "Файл перевіряється перед використанням; старі версії оновлюються, некоректні файли відхиляються.",
        "ru": "Файл проверяется перед использованием; старые версии обновляются, некорректные файлы отклоняются.",
    },
    "grill.ui.import_button": {"en": "Load interview", "uk": "Завантажити інтерв'ю", "ru": "Загрузить интервью"},
    "grill.ui.saved_on_disk": {"en": "Saved {time}", "uk": "Збережено {time}", "ru": "Сохранено {time}"},
    "grill.ui.saved_in_session": {
        "en": "Kept in this session · {time}", "uk": "У цьому сеансі · {time}", "ru": "В этом сеансе · {time}",
    },
    "grill.ui.close_interview": {"en": "Close, keep saved", "uk": "Закрити, зберігши", "ru": "Закрыть с сохранением"},
    "grill.ui.close_help": {
        "en": "Leave this interview for now. It stays in the list of unfinished interviews and can be resumed any time.",
        "uk": "Відкласти це інтерв'ю. Воно залишиться в списку незавершених, і його можна продовжити будь-коли.",
        "ru": "Отложить это интервью. Оно останется в списке незавершённых, и его можно продолжить в любой момент.",
    },
    "grill.ui.export_progress": {"en": "Save progress to a file", "uk": "Зберегти прогрес у файл", "ru": "Сохранить прогресс в файл"},
    "grill.ui.export_help": {
        "en": "Downloads the whole interview (answers, history, draft) to resume later with “Resume from a file”.",
        "uk": "Завантажує все інтерв'ю (відповіді, історію, чернетку), щоб продовжити пізніше через «Продовжити з файлу».",
        "ru": "Скачивает всё интервью (ответы, историю, черновик), чтобы продолжить позже через «Продолжить из файла».",
    },
    "grill.ui.restored": {
        "en": "Your unfinished interview was restored (last change {time} UTC).",
        "uk": "Ваше незавершене інтерв'ю відновлено (остання зміна {time} UTC).",
        "ru": "Ваше незавершённое интервью восстановлено (последнее изменение {time} UTC).",
    },
    "grill.ui.resumed": {"en": "Interview reopened.", "uk": "Інтерв'ю знову відкрито.", "ru": "Интервью снова открыто."},
    "grill.ui.imported": {"en": "Interview loaded from the file.", "uk": "Інтерв'ю завантажено з файлу.", "ru": "Интервью загружено из файла."},
    "grill.ui.interview_deleted": {"en": "Saved interview deleted.", "uk": "Збережене інтерв'ю видалено.", "ru": "Сохранённое интервью удалено."},
    "grill.ui.save_failed": {
        "en": "The interview could not be saved on disk; it is still open in this session.",
        "uk": "Не вдалося зберегти інтерв'ю на диску; воно й далі відкрите в цьому сеансі.",
        "ru": "Не удалось сохранить интервью на диске; оно по-прежнему открыто в этом сеансе.",
    },
    "grill.ui.settled_note": {
        "en": "{count} finding(s) already resolved in this document will not be asked about again.",
        "uk": "Зауваження, вже розв'язані в цьому документі ({count}), не обговорюватимуться повторно.",
        "ru": "Замечания, уже решённые в этом документе ({count}), повторно обсуждаться не будут.",
    },
    "grill.ui.resolve_undo_hint": {
        "en": "Every change is recorded and can be reopened or undone on the Requirements Analysis page (Findings tab).",
        "uk": "Кожну зміну записано; її можна перевідкрити або скасувати на сторінці «Аналіз вимог» (вкладка «Зауваження»).",
        "ru": "Каждое изменение записано; его можно переоткрыть или отменить на странице «Анализ требований» (вкладка «Замечания»).",
    },
    "grill.error.interview_invalid": {
        "en": "This file is not a saved Spec-to-Test interview, or it is damaged.",
        "uk": "Цей файл не є збереженим інтерв'ю Spec-to-Test або пошкоджений.",
        "ru": "Этот файл не является сохранённым интервью Spec-to-Test или повреждён.",
    },
    "grill.error.interview_version": {
        "en": "This interview was saved by a newer version of the app and cannot be opened here.",
        "uk": "Це інтерв'ю збережено новішою версією застосунку, тут його не відкрити.",
        "ru": "Это интервью сохранено более новой версией приложения, здесь его не открыть.",
    },
    "grill.error.interview_too_large": {
        "en": "The file is too large to be a saved interview.", "uk": "Файл завеликий для збереженого інтерв'ю.",
        "ru": "Файл слишком велик для сохранённого интервью.",
    },
    "grill.error.reason_too_long": {
        "en": "The reason is too long (500 characters at most).", "uk": "Причина задовга (не більше 500 символів).",
        "ru": "Причина слишком длинная (не более 500 символов).",
    },
    "grill.error.nothing_to_resolve": {
        "en": "These findings are already resolved.", "uk": "Ці зауваження вже розв'язані.", "ru": "Эти замечания уже решены.",
    },
    # --- Finding history (Requirements Analysis) ----------------------------------------
    "findings.heading": {
        "en": "Resolved findings ({count})", "uk": "Розв'язані зауваження ({count})", "ru": "Решённые замечания ({count})",
    },
    "findings.explainer": {
        "en": "Findings are resolved by clarifications you confirm in Grill Mode. Reopen one if the clarification no longer holds, or undo the last change; every change is kept with its reason.",
        "uk": "Зауваження розв'язуються уточненнями, які ви підтверджуєте в режимі Grill. Перевідкрийте зауваження, якщо уточнення більше не діє, або скасуйте останню зміну; кожна зміна зберігається з причиною.",
        "ru": "Замечания решаются уточнениями, которые вы подтверждаете в режиме Grill. Переоткройте замечание, если уточнение больше не действует, или отмените последнее изменение; каждое изменение хранится с причиной.",
    },
    "findings.select": {"en": "Resolved finding", "uk": "Розв'язане зауваження", "ru": "Решённое замечание"},
    "findings.none_resolved": {
        "en": "No resolved findings in this document.", "uk": "У цьому документі немає розв'язаних зауважень.",
        "ru": "В этом документе нет решённых замечаний.",
    },
    "findings.no_history": {
        "en": "Resolved before change history was recorded: when and why is not known.",
        "uk": "Розв'язано до появи історії змін: коли й чому — невідомо.",
        "ru": "Решено до появления истории изменений: когда и почему — неизвестно.",
    },
    "findings.reason_label": {"en": "Reason (optional)", "uk": "Причина (необов'язково)", "ru": "Причина (необязательно)"},
    "findings.reason_placeholder": {
        "en": "e.g. the product owner changed the rule", "uk": "напр. власник продукту змінив правило",
        "ru": "напр. владелец продукта изменил правило",
    },
    "findings.reopen": {"en": "Reopen finding", "uk": "Перевідкрити зауваження", "ru": "Переоткрыть замечание"},
    "findings.reopen_help": {
        "en": "Sets the finding back to “needs clarification”; it counts against quality and coverage again.",
        "uk": "Повертає зауваженню статус «потребує уточнення»; воно знову впливає на якість і покриття.",
        "ru": "Возвращает замечанию статус «требует уточнения»; оно снова влияет на качество и покрытие.",
    },
    "findings.undo": {"en": "Undo last change", "uk": "Скасувати останню зміну", "ru": "Отменить последнее изменение"},
    "findings.undo_help": {
        "en": "Undo the last change: {change} ({count} finding(s)). The undo itself is recorded.",
        "uk": "Скасувати останню зміну: {change} (зауважень: {count}). Саме скасування теж записується.",
        "ru": "Отменить последнее изменение: {change} (замечаний: {count}). Сама отмена тоже записывается.",
    },
    "findings.undo_none": {
        "en": "Nothing to undo: no change yet, or the findings changed again since.",
        "uk": "Нічого скасовувати: змін ще не було або зауваження відтоді знову змінювалися.",
        "ru": "Нечего отменять: изменений ещё не было или замечания с тех пор снова менялись.",
    },
    "findings.history_heading": {
        "en": "Change history ({count})", "uk": "Історія змін ({count})", "ru": "История изменений ({count})",
    },
    "findings.col_time": {"en": "Time (UTC)", "uk": "Час (UTC)", "ru": "Время (UTC)"},
    "findings.col_change": {"en": "Change", "uk": "Зміна", "ru": "Изменение"},
    "findings.col_finding": {"en": "Finding", "uk": "Зауваження", "ru": "Замечание"},
    "findings.col_via": {"en": "By", "uk": "Через", "ru": "Через"},
    "findings.col_reason": {"en": "Reason or clarification", "uk": "Причина або уточнення", "ru": "Причина или уточнение"},
    "findings.change.resolved": {"en": "Resolved", "uk": "Розв'язано", "ru": "Решено"},
    "findings.change.reopened": {"en": "Reopened", "uk": "Перевідкрито", "ru": "Переоткрыто"},
    "findings.via.grill": {"en": "Grill clarification", "uk": "Уточнення Grill", "ru": "Уточнение Grill"},
    "findings.via.manual": {"en": "By hand", "uk": "Вручну", "ru": "Вручную"},
    "findings.via.undo": {"en": "Undo", "uk": "Скасування", "ru": "Отмена"},
    "findings.reopened": {"en": "Finding reopened.", "uk": "Зауваження перевідкрито.", "ru": "Замечание переоткрыто."},
    "findings.undone": {"en": "Last change undone.", "uk": "Останню зміну скасовано.", "ru": "Последнее изменение отменено."},
    "findings.error.reason_too_long": {
        "en": "The reason is too long (500 characters at most).", "uk": "Причина задовга (не більше 500 символів).",
        "ru": "Причина слишком длинная (не более 500 символов).",
    },
    "findings.error.nothing_to_resolve": {
        "en": "These findings are already resolved.", "uk": "Ці зауваження вже розв'язані.", "ru": "Эти замечания уже решены.",
    },
    "findings.error.not_resolved": {
        "en": "This finding is not resolved.", "uk": "Це зауваження не розв'язане.", "ru": "Это замечание не решено.",
    },
    "findings.error.nothing_to_undo": {
        "en": "There is no change that can be undone.", "uk": "Немає зміни, яку можна скасувати.",
        "ru": "Нет изменения, которое можно отменить.",
    },
    # --- Traceability -----------------------------------------------------------------
    "grill.trace.tab": {"en": "History", "uk": "Історія", "ru": "История"},
    "grill.trace.heading": {"en": "Decision trace", "uk": "Трасування рішень", "ru": "Трассировка решений"},
    "grill.trace.note": {
        "en": "Where each question came from, what was answered and its state. Confirmed answers are decisions; assumptions, unknowns and conflicts are not.",
        "uk": "Звідки кожне питання, що відповіли та його стан. Підтверджені відповіді — це рішення; припущення, невідоме й конфлікти — ні.",
        "ru": "Откуда каждый вопрос, что ответили и его состояние. Подтверждённые ответы — это решения; допущения, неизвестное и конфликты — нет.",
    },
    "grill.trace.none": {"en": "Nothing recorded yet.", "uk": "Ще нічого не записано.", "ru": "Пока ничего не записано."},
    "grill.trace.col_source": {"en": "Source", "uk": "Джерело", "ru": "Источник"},
    "grill.trace.col_changes": {"en": "Changes", "uk": "Змін", "ru": "Изменений"},
    "grill.trace.col_history": {"en": "Answer history", "uk": "Історія відповідей", "ru": "История ответов"},
    "grill.trace.superseded": {"en": "overruled", "uk": "скасовано рішенням", "ru": "отменено решением"},
    "grill.trace.changed_n": {"en": "changed {count}×", "uk": "змінено {count}×", "ru": "изменено {count}×"},
    "grill.trace.pick_history": {
        "en": "Answer history of a changed question", "uk": "Історія відповідей зміненого питання",
        "ru": "История ответов изменённого вопроса",
    },
    "grill.trace.origin.rule": {"en": "Rule finding", "uk": "Правило аналізу", "ru": "Правило анализа"},
    "grill.trace.origin.contradiction": {
        "en": "Contradiction in the source", "uk": "Суперечність у джерелі", "ru": "Противоречие в источнике",
    },
    "grill.trace.origin.conflict": {
        "en": "Answer contradicts a requirement or answer", "uk": "Відповідь суперечить вимозі чи відповіді",
        "ru": "Ответ противоречит требованию или ответу",
    },
    "grill.trace.origin.followup": {"en": "Follow-up to an answer", "uk": "Уточнення до відповіді", "ru": "Уточнение к ответу"},
    "grill.trace.origin.ai": {"en": "AI interviewer", "uk": "ШІ-інтерв'юер", "ru": "ИИ-интервьюер"},
    "grill.trace.origin.field": {"en": "Empty draft field", "uk": "Порожнє поле чернетки", "ru": "Пустое поле черновика"},
    # --- Audit log ----------------------------------------------------------------------
    "grill.audit.heading": {"en": "Audit log ({count})", "uk": "Журнал змін ({count})", "ru": "Журнал изменений ({count})"},
    "grill.audit.note": {
        "en": "Every answer, change and confirmation, newest first. Entries are never edited.",
        "uk": "Кожна відповідь, зміна й підтвердження, найновіші вгорі. Записи ніколи не редагуються.",
        "ru": "Каждый ответ, изменение и подтверждение, новые сверху. Записи никогда не редактируются.",
    },
    "grill.audit.all": {"en": "Whole log ({count})", "uk": "Увесь журнал ({count})", "ru": "Весь журнал ({count})"},
    "grill.audit.col_time": {"en": "Time (UTC)", "uk": "Час (UTC)", "ru": "Время (UTC)"},
    "grill.audit.col_action": {"en": "Action", "uk": "Дія", "ru": "Действие"},
    "grill.audit.col_detail": {"en": "Details", "uk": "Деталі", "ru": "Подробности"},
    "grill.audit.download": {"en": "Download audit log (JSON)", "uk": "Завантажити журнал (JSON)", "ru": "Скачать журнал (JSON)"},
    "grill.audit.download_help": {
        "en": "Requirements, every decision with its source and state, and the full change log.",
        "uk": "Вимоги, кожне рішення з джерелом і станом та повний журнал змін.",
        "ru": "Требования, каждое решение с источником и состоянием и полный журнал изменений.",
    },
    "grill.audit.action.started": {"en": "Started", "uk": "Розпочато", "ru": "Начато"},
    "grill.audit.action.answered": {"en": "Answered", "uk": "Відповідь", "ru": "Ответ"},
    "grill.audit.action.answer_changed": {"en": "Answer changed", "uk": "Відповідь змінено", "ru": "Ответ изменён"},
    "grill.audit.action.question_added": {"en": "AI question added", "uk": "Додано питання ШІ", "ru": "Добавлен вопрос ИИ"},
    "grill.audit.action.draft_edited": {"en": "Draft edited", "uk": "Чернетку змінено", "ru": "Черновик изменён"},
    "grill.audit.action.reviewed": {"en": "Reviewed", "uk": "Перевірено", "ru": "Проверено"},
    "grill.audit.action.ai_reviewed": {"en": "AI review added", "uk": "Додано перевірку ШІ", "ru": "Добавлена проверка ИИ"},
    "grill.audit.action.confirmation_requested": {
        "en": "Confirmation requested", "uk": "Запит на підтвердження", "ru": "Запрос подтверждения",
    },
    "grill.audit.action.confirmed": {"en": "Confirmed", "uk": "Підтверджено", "ru": "Подтверждено"},
    "grill.audit.action.cancelled": {"en": "Cancelled", "uk": "Скасовано", "ru": "Отменено"},
    "grill.audit.action.migrated": {
        "en": "Upgraded from an older version (earlier history not recorded)",
        "uk": "Оновлено зі старої версії (попередню історію не записано)",
        "ru": "Обновлено со старой версии (предыдущая история не записана)",
    },
    "grill.audit.text.answered": {
        "en": "“{question}” → {status}: {value}", "uk": "«{question}» → {status}: {value}",
        "ru": "«{question}» → {status}: {value}",
    },
    "grill.audit.text.answer_changed": {
        "en": "“{question}”: {before} ({before_value}) → {status} ({value})",
        "uk": "«{question}»: було {before} ({before_value}), стало {status} ({value})",
        "ru": "«{question}»: было {before} ({before_value}), стало {status} ({value})",
    },
    "grill.audit.text.question_added": {
        "en": "“{question}” (proposed by {model})", "uk": "«{question}» (запропонувала модель {model})",
        "ru": "«{question}» (предложила модель {model})",
    },
    "grill.audit.text.draft_edited": {"en": "Fields: {fields}", "uk": "Поля: {fields}", "ru": "Поля: {fields}"},
    "grill.audit.action.question_retired": {
        "en": "Question closed without asking", "uk": "Питання закрито без запиту", "ru": "Вопрос закрыт без запроса",
    },
    "grill.audit.action.question_restored": {
        "en": "Question back in the queue", "uk": "Питання повернулося в чергу", "ru": "Вопрос вернулся в очередь",
    },
    "grill.audit.action.findings_synced": {
        "en": "Findings changed in the document", "uk": "Зауваження змінено в документі",
        "ru": "Замечания изменены в документе",
    },
    "grill.audit.text.question_retired": {
        "en": "“{question}”: {reason}", "uk": "«{question}»: {reason}", "ru": "«{question}»: {reason}",
    },
    "grill.audit.text.question_restored": {
        "en": "“{question}” applies again", "uk": "«{question}» знову актуальне", "ru": "«{question}» снова актуален",
    },
    "grill.audit.text.findings_synced": {
        "en": "Resolved: {resolved}. Reopened: {reopened}.", "uk": "Розв'язано: {resolved}. Знову відкрито: {reopened}.",
        "ru": "Решено: {resolved}. Снова открыто: {reopened}.",
    },
    "grill.retire_reason.settled": {
        "en": "its finding was resolved in the document", "uk": "зауваження розв'язано в документі",
        "ru": "замечание решено в документе",
    },
    "grill.retire_reason.answered_elsewhere": {
        "en": "already answered by “{other}”", "uk": "вже відповідь на «{other}»", "ru": "уже ответ на «{other}»",
    },
    "grill.retire_reason.duplicate": {
        "en": "asks the same as “{other}”", "uk": "питає те саме, що «{other}»", "ru": "спрашивает то же, что «{other}»",
    },
    "grill.retire_reason.obsolete": {
        "en": "no longer applies", "uk": "більше не актуальне", "ru": "больше не актуален",
    },
    "grill.ui.findings_synced": {
        "en": "Findings changed in the document: {resolved} resolved, {reopened} reopened. The interview queue was updated; your answers are kept.",
        "uk": "Зауваження змінено в документі: розв'язано {resolved}, знову відкрито {reopened}. Чергу питань оновлено, ваші відповіді збережено.",
        "ru": "Замечания изменены в документе: решено {resolved}, снова открыто {reopened}. Очередь вопросов обновлена, ваши ответы сохранены.",
    },
    "grill.ui.retired_heading": {
        "en": "Closed without asking ({count})", "uk": "Закрито без запиту ({count})", "ru": "Закрыто без запроса ({count})",
    },
}
