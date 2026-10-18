"""Rule-based Bug Report Generator: a free-text bug description becomes a structured report.

Runs locally; nothing is sent anywhere. Every value is text found in the
description, never a guess:

1. Labeled parts ("Steps:", "Expected result:", "Шаги:", "Очікуваний результат:",
   Markdown headings, ...) fill their field as written.
2. Unlabeled text is split into sentences and clauses (then / but / commas /
   "and" before a new action) and each clause is classified by cue words in
   English, Ukrainian and Russian: expected ("should", "должен", "має бути"),
   precondition ("logged in as", "авторизован"), actual result (errors,
   negations, "shows"), step (an action verb at the start), trigger ("when I",
   "после", "після").
3. Environment details (browser, OS, device, app version, test environment,
   resolution), where (pages, screens, URLs) and when (trigger, frequency,
   "since the last release") are copied verbatim from the observed parts of the
   text (not from the expected result).
4. Severity and priority are preliminary: stated by the reporter ("Severity:
   High") or suggested from cue words in the actual result (crash, data loss,
   500 → High; typo, alignment → Low; any other failure → Medium). Priority
   follows severity, one level lower when the problem does not happen every time.

Clauses no rule recognises are kept in `unassigned`, so nothing of the
description is lost. Fields with no matching text stay empty and are shown as
"Needs clarification".
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from spec_to_test.bug_generator.models import (
    FREQUENCY,
    MAX_DESCRIPTION_CHARS,
    MAX_FIELD_CHARS,
    MAX_ITEMS,
    ProductBugReport,
)
from spec_to_test.grill.models import Priority
from spec_to_test.input_parser import InputError, validate_text
from spec_to_test.models import Severity, Source


class BugInputError(ValueError):
    """The description cannot be used; `code` maps to bugreport.error.<code>."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

_LABELS: dict[str, tuple[str, ...]] = {
    "title": ("title", "summary", "subject", "bug", "bug title", "заголовок", "название", "назва", "тема", "суть",
              "баг"),
    "what": ("what", "what happened", "what happens", "problem", "issue", "что", "что произошло", "что случилось",
             "проблема", "що", "що сталося", "що відбувається"),
    "where": ("where", "location", "page", "screen", "url", "link", "module", "component", "feature", "area", "где",
              "страница", "экран", "ссылка", "модуль", "раздел", "компонент", "де", "сторінка", "екран",
              "посилання", "розділ"),
    "when": ("when", "frequency", "reproducibility", "reproducible", "occurs", "how often", "когда", "частота",
             "воспроизводимость", "как часто", "коли", "відтворюваність", "як часто"),
    "preconditions": ("preconditions", "precondition", "pre-conditions", "prerequisites", "setup", "given",
                      "предусловия", "предусловие", "предварительные условия", "передумови", "передумова",
                      "попередні умови"),
    "steps": ("steps", "steps to reproduce", "str", "how to reproduce", "reproduction steps", "repro steps", "шаги",
              "шаги воспроизведения", "шаги для воспроизведения", "как воспроизвести", "кроки", "кроки відтворення",
              "кроки для відтворення", "як відтворити"),
    "actual_result": ("actual", "actual result", "actual results", "actual behavior", "actual behaviour", "observed",
                      "observed result", "result", "фактический результат", "фактически", "фактическое поведение",
                      "результат", "фактичний результат", "фактично", "фактична поведінка"),
    "expected_result": ("expected", "expected result", "expected results", "expected behavior", "expected behaviour",
                        "ожидаемый результат", "ожидается", "ожидаемое поведение", "очікуваний результат",
                        "очікується", "очікувана поведінка"),
    "environment": ("environment", "env", "environments", "окружение", "среда", "тестовая среда", "оточення",
                    "середовище"),
    "severity": ("severity", "серьёзность", "серьезность", "критичность", "серйозність", "критичність"),
    "priority": ("priority", "приоритет", "пріоритет"),
}
# Environment details: kept with their label ("Browser: Chrome 120").
_ENV_LABELS = (
    "browser", "os", "operating system", "device", "platform", "version", "app version", "build", "release",
    "resolution", "браузер", "ос", "операционная система", "устройство", "платформа", "версия", "версия приложения",
    "сборка", "релиз", "разрешение", "операційна система", "пристрій", "версія", "версія застосунку", "збірка",
    "реліз", "роздільна здатність",
)
_LEVELS: dict[str, tuple[str, ...]] = {
    "high": ("high", "critical", "blocker", "major", "urgent", "highest", "высокая", "высокий", "критическая",
             "критический", "критичная", "блокер", "блокирующий", "срочный", "висока", "високий", "критична",
             "критичний", "блокуючий", "терміновий"),
    "medium": ("medium", "normal", "moderate", "средняя", "средний", "нормальная", "нормальный", "середня",
               "середній", "нормальна", "нормальний"),
    "low": ("low", "minor", "trivial", "lowest", "низкая", "низкий", "незначительная", "незначительный",
            "тривиальная", "минорная", "низька", "низький", "незначна", "незначний", "тривіальна"),
}
# The reporter says the value is not known: the field stays empty.
_UNKNOWN = {"unknown", "n/a", "na", "-", "—", "?", "tbd", "not known", "none", "неизвестно", "невідомо", "нет",
            "немає", "нема"}

_LABEL_LINE = re.compile(r"^\s*(?:#{1,6}\s*)?[*_]{0,2}(?P<label>[^:：*_#\n]{1,40}?)[*_]{0,2}\s*[:：]\s*[*_]{0,2}\s*(?P<rest>.*)$")
_HEADING_LINE = re.compile(r"^\s*(?:#{1,6}\s*(?P<h>[^#\n]{1,40}?)\s*#*|\*\*(?P<b>[^*\n]{1,40})\*\*)\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+•–—·]|\d{1,3}[.)]|(?:step|шаг|крок)\s*\d+[.:)]?)\s+", re.I)
_INLINE_STEPS = re.compile(r"\s*(?:→|->|=>|;)\s*|\s+(?=\d{1,2}[.)]\s)")


def _key(text: str) -> str:
    return " ".join(text.replace("’", "'").strip(" *_").split()).casefold()


_LABEL_MAP = {_key(label): name for name, labels in _LABELS.items() for label in labels}
_ENV_LABEL_SET = {_key(label) for label in _ENV_LABELS}
_LEVEL_MAP = {_key(word): level for level, words in _LEVELS.items() for word in words}


# ---------------------------------------------------------------------------
# Cue words
# ---------------------------------------------------------------------------

def _words(*forms: str) -> str:
    return "|".join(forms)


_EN_VERBS = _words(
    "open", "go", "navigate", "visit", "click", "double-click", "right-click", "tap", "press", "hit", "select",
    "choose", "pick", "enter", "type", "fill", "input", "submit", "upload", "download", "add", "remove", "delete",
    "drag", "drop", "scroll", "hover", "log", "login", "sign", "register", "search", "apply", "change", "edit",
    "update", "save", "close", "refresh", "reload", "switch", "toggle", "check", "uncheck", "tick", "untick",
    "launch", "start", "run", "create", "send", "pay", "place", "confirm", "attach", "copy", "paste", "move", "set",
    "try", "attempt", "wait", "return", "use", "put", "insert", "clear", "reset", "install", "rotate", "zoom",
    "expand", "collapse", "book", "buy", "purchase", "share", "invite", "import", "export", "follow",
)
_EN_ACTION = (
    rf"(?:{_EN_VERBS})(?:s|es|ed|d|ing|ped|ping|ged|ging|ted|ting|red|ring|ied|ies)?\b"
    r"|(?:went|chose|chosen|ran|sent|paid|made|tried|put|set)\b"
)
_RU_ACTION = (
    r"(?:открыва|откры|откро|перехож|перехожу|перейд|перешё|перешел|перешла|нажима|нажа|нажм|клика|кликну|ввод|"
    r"ввож|ввёл|ввел|введ|выбира|выбра|выбер|загружа|загрузи|добавля|добави|заполня|заполни|отправля|отправи|"
    r"захож|зашёл|зашел|зашла|зайти|зайд|авторизу|залогин|логинюсь|скролл|прокручива|прокрути|удаля|удали|сохраня|"
    r"сохрани|обновля|обнови|перезагружа|перезагрузи|переключа|переключи|запуска|запусти|созда|оформля|оформи|"
    r"оплачива|оплати|подтвержда|подтверди|копиру|скопирова|вставля|встав|ставлю|постав|отмеча|отмети|жду|подожд|"
    r"пробу|попробова|пыта|захожу|вхожу|войти|войд|вошёл|вошел|регистриру|зарегистрир|ищу|иска|найти|меняю|изменя|"
    r"измени|редактиру|отредактир|закрыва|закро|закры|возвраща|верну|использу|прикрепля|прикрепи|импортиру|"
    r"экспортиру|покупа|купи|бронирую|забронир|заказыва|заказал|закажу|заказать|перетаскива|перетащи)\w*"
)
_UK_ACTION = (
    r"(?:відкрива|відкри|переход|перейш|перейд|натиска|натисн|клаца|клацн|кліка|клікну|вводж|ввод|ввів|ввел|введ|"
    r"обира|обра|вибира|вибра|вибер|завантаж|додаю|додава|додав|додати|додайте|заповню|заповни|надсила|надісла|відправля|відправи|"
    r"заходж|заход|зайш|зайти|увійш|увійти|авториз|залогін|прокручу|прокрути|гортаю|видаля|видали|зберіга|зберег|"
    r"оновлю|онови|перезаванта|перемика|перемкну|запуска|запусти|створю|створи|оформлю|оформи|оплачу|оплати|"
    r"підтверджу|підтверди|копію|скопію|вставля|встави|позначаю|познач|чекаю|зачека|пробую|спробува|намагаю|шукаю|"
    r"шука|знайти|змінюю|зміню|зміни|редагую|відредаг|закрива|закри|поверта|поверну|використову|прикріпл|"
    r"прикріпи|імпорту|експорту|купую|купи|бронюю|заброню|замовля|замови|перетягу|перетягни)\w*"
)
_SUBJECT = (
    r"(?:(?:i|we|you|the user|user|a user|я|мы|вы|пользователь|юзер|ми|ви|користувач)\s+)?"
    r"(?:(?:then|first|next|now|again|also|just|сначала|потом|затем|снова|опять|далее|спочатку|потім|далі|знову)\s+)?"
)
_ACTION_START = re.compile(rf"^{_SUBJECT}(?:{_EN_ACTION}|{_RU_ACTION}|{_UK_ACTION})", re.I)
# Third-person reflexive verbs describe what the product does ("открывается", "з'являється"), not a step.
_OBSERVATION_VERB = re.compile(
    rf"^{_SUBJECT}\w+(?:ется|ится|ются|ятся|ється|иться|ються|яться)\b"
    r"|^[\w-]+(?:\s+[\w-]+)?\s+(?:is|are|was|were|has|have|had|shows?|returns?|displays?|becomes|stays|remains|"
    r"results?|gives|looks|seems|works|loads)\b",
    re.I,
)

_EXPECTED = re.compile(
    r"\b(?:should(?:n't| not)?|expected|expect(?:s|ing)?|supposed to|ought to|must|needs? to be|is meant to|"
    r"would expect|должн\w*|ожида\w*|предполага\w*|по идее|по логике|нужно,? чтобы|надо,? чтобы|повин\w*|"
    r"очіку\w*|передбача\w*|має бути|мають бути|ма(?:є|ють)\s+\w+(?:ся|ти|тись)|мало б\w*|мав би|мала б|по ідеї|"
    r"потрібно,? щоб|треба,? щоб)\b",
    re.I,
)
_INSTEAD = re.compile(
    r"^(?:instead of|rather than|вместо(?: того,? чтобы)?|замість(?: того,? щоб)?)\s+", re.I
)
_INSTEAD_SPLIT = re.compile(r"\s+(?=(?:instead of|rather than|вместо|замість)\s)", re.I)
_PRECONDITION = re.compile(
    r"(?:\b(?:logged|signed) in as\b|^(?:i am |i'm |the user is |user is |being |while )?(?:logged|signed) in\b|"
    r"^as an? (?!result\b)\w+|^given\b|^having\b|\bwith an? (?:empty|full|existing|valid|expired|new|blocked)\b|"
    r"^(?:the )?user (?:has|with)\b|^(?:i|we) have\b|авторизован\w*|залогинен\w*|"
    r"\bпод (?:пользователем|учётн\w+|учетн\w+|аккаунтом|ролью|админом)\b|^имея\b|^при наличии\b|"
    r"^у (?:меня|пользователя) есть\b|\bс пустой корзиной\b|\bв роли\b|залогінен\w*|авторизован\w*|"
    r"\bпід (?:користувачем|обліков\w+|акаунтом|роллю)\b|^маючи\b|^за наявності\b|^у (?:мене|користувача) є\b|"
    r"\bз порожнім кошиком\b|\bу ролі\b)",
    re.I,
)
_ACTUAL_STRONG = re.compile(
    r"\b(?:errors?|exceptions?|fail(?:s|ed|ing|ure)?|crash(?:es|ed|ing)?|freez(?:e|es|ing)|froze|frozen|"
    r"hang(?:s|ing)?|hung|stuck|broken|breaks|blank|disappear(?:s|ed)?|vanish(?:es|ed)?|nothing happens|does not|"
    r"doesn't|did not|didn't|do not|don't|is not|isn't|are not|aren't|was not|wasn't|were not|weren't|cannot|"
    r"can't|could not|couldn't|unable|won't|will not|no longer|not|wrong|incorrect(?:ly)?|invalid|timeout|"
    r"timed out|times out|glitch\w*|slow(?:ly)?|overlap(?:s|ping)?|cut off|truncated|misaligned|typo|misspelled|"
    r"duplicated?|twice|missing|"
    r"ошибк\w*|исключени\w*|ничего не происходит|не\s+\w+|нет|ничего|пада\w*|упал\w*|вылет\w*|завис\w*|тормоз\w*|сломал\w*|сломан\w*|"
    r"глюч\w*|пропада\w*|пропал\w*|исчеза\w*|исчез\w*|неверн\w*|неправильн\w*|некорректн\w*|бесконечн\w*|"
    r"таймаут\w*|дважды|дублир\w*|задвоен\w*|обрезан\w*|наезжа\w*|съезжа\w*|опечатк\w*|медленн\w*|долго|"
    r"помилк\w*|винят\w*|нічого не відбувається|немає|нема|нічого|впав\w*|впала|виліта\w*|зависа\w*|гальму\w*|злама\w*|зника\w*|"
    r"зник\w*|невірн\w*|нескінченн\w*|двічі|дублю\w*|задвоє\w*|обрізан\w*|наїжджа\w*|повільн\w*|довго)\b"
    r"|\b(?:http|error|status|code|ошибка|ошибку|помилка|помилку)\s*[45]\d{2}\b"
    r"|\b[45]\d{2}\s*(?:error|status|internal|not found|bad request|ошибк\w*|помилк\w*)",
    re.I,
)
_ACTUAL_WEAK = re.compile(
    r"\b(?:shows?|showed|shown|showing|displays?|displayed|appears?|appeared|gets?|got|getting|sees?|saw|seeing|"
    r"receive[sd]?|returns?|returned|redirects?|redirected|reloads?|reloaded|loads?|loading|spins?|spinner|empty|"
    r"becomes|became|stays|remains|opens|opened|"
    r"показыва\w*|показал\w*|отобража\w*|отобразил\w*|появля\w*|появил\w*|получа\w*|получил\w*|вижу|видно|выда\w*|"
    r"возвраща\w*|вернул\w*|перенаправля\w*|перенаправил\w*|перекидыва\w*|перекинул\w*|остаётся|остается|"
    r"становится|открывается|грузится|загружается|крутится|пуст\w*|"
    r"показу\w*|показав\w*|відобража\w*|відобразив\w*|з[’']являється|з[’']явил\w*|отриму\w*|отримав\w*|бачу|"
    r"видає|видав\w*|поверта\w*|повернув\w*|перенаправля\w*|перекида\w*|залишається|стає|відкривається|"
    r"вантажиться|завантажується|крутиться|порожн\w*|"
    # What the product does: "формируется", "з'являється", "зберігається".
    r"[\w'’]{3,}(?:ется|ится|ются|ятся|ється|иться|ються|яться|еться))\b",
    re.I,
)
_TRIGGER = re.compile(
    r"^(?:when|whenever|after|upon|while|once|as soon as|if|on (?:clicking|tapping|pressing|submitting|saving|"
    r"opening)|когда|при|после того,? как|после|как только|во время|если|коли|при|після того,? як|після|щойно|"
    r"як тільки|під час|якщо)\b",
    re.I,
)
# "When I click Save" also names a step: "I click Save".
_TRIGGER_STEP = re.compile(r"^(?:when|whenever|if|когда|если|коли|якщо)\s+(?P<step>(?:i|we|я|мы|ми)\s+\S.*)$", re.I)

_TIMING = re.compile(
    r"\bsince\s+(?:the\s+)?(?:(?!(?:in|on|at|for|with|when|and|but|if|after|before)\b)[\w.'’-]+\s*){1,4}"
    r"|\bafter\s+(?:the\s+)?(?:latest\s+|last\s+|recent\s+|new\s+)?(?:update|upgrade|release|deploy(?:ment)?|"
    r"migration)(?:\s+(?:to\s+)?v?\d[\d.]*)?"
    r"|\b(?:yesterday|today|this morning|last (?:week|night))\b|\bstarting (?:from\s+)?[\w.-]+(?:\s+[\w.-]+){0,2}"
    r"|\bс\s+(?:последн\w+|прошл\w+|вчерашн\w+|новой|нового)\s+\w+(?:\s+v?\d[\d.]*)?"
    r"|\bпосле\s+(?:последн\w+\s+|недавн\w+\s+)?(?:обновлени\w+|релиз\w*|деплоя|выкатки|миграции)(?:\s+(?:до\s+)?v?\d[\d.]*)?"
    r"|\b(?:вчера|сегодня|с утра)\b|на прошлой неделе|\bначиная с\s+\w+(?:\s+[\w.]+)?"
    r"|\bз\s+(?:останн\w+|минул\w+|вчорашн\w+|нов\w+)\s+\w+(?:\s+v?\d[\d.]*)?"
    r"|\bпісля\s+(?:останн\w+\s+|нещодавн\w+\s+)?(?:оновленн\w+|релізу|деплою|міграції)(?:\s+(?:до\s+)?v?\d[\d.]*)?"
    r"|\b(?:вчора|сьогодні|зранку)\b|минулого тижня|\bпочинаючи з\s+\w+(?:\s+[\w.]+)?",
    re.I,
)

# --- Where ----------------------------------------------------------------------------

_URL = re.compile(r"https?://[^\s<>\"'«»)\]]+", re.I)
_PATH = re.compile(r"(?<![\w/.:])/[a-z][a-z0-9_-]+(?:/[a-z0-9_.-]+)*/?", re.I)
_EN_PLACE_NOUNS = (
    "page|screen|form|tab|dialog|modal|window|menu|section|panel|view|widget|pop-?up|sidebar|header|footer|"
    "dashboard|list|table|cart|basket|checkout|settings|profile|catalog|catalogue|gallery|feed|inbox|chat|editor|"
    "calendar|account|wizard|onboarding|homepage|home page|main page|landing page"
)
_VAGUE_NOUNS = {"page", "screen", "form", "tab", "dialog", "modal", "window", "menu", "section", "panel", "view",
                "widget", "popup", "pop-up", "list", "table"}
_EN_PLACE = re.compile(
    r"\b(?:(?P<prep>on|in|at|from|inside|within)|(?:open(?:s|ed|ing)?|go(?:es|ing)? to|went to|navigat\w* to|"
    r"visit(?:s|ed|ing)?|access(?:es|ed|ing)?|redirect\w* to))\s+(?P<det>(?:the|a|an|my|our|this)\s+)?"
    rf"(?P<mods>(?:(?:[\"'«“][^\"'»”]{{1,40}}[\"'»”]|[\w-]+)\s+){{0,3}}?)(?P<noun>{_EN_PLACE_NOUNS})\b"
    r"(?:\s+[\"'«“][^\"'»”]{1,40}[\"'»”])?",
    re.I,
)
_SLAVIC_PLACE = re.compile(
    r"(?:\b(?P<prep>на|в|во|из|у|з|із)\s+|\b(?:открыва\w*|открыл\w*|откро\w*|открыть|відкрива\w*|відкри\w*)\s+)"
    r"(?:(?:главной|основной|стартовой|новой|главную|головній|основній|стартовій|новій|головну)\s+)?"
    r"(?P<noun>странице|страницы|экране|экрана|форме|формы|вкладке|вкладки|разделе|раздела|модальном окне|окне|"
    r"окна|модалке|меню|панели|блоке|попапе|диалоге|корзине|корзины|профиле|профиля|настройках|личном кабинете|"
    r"кабинете|каталоге|карточке товара|карточке|списке|таблице|сторінці|сторінки|екрані|формі|вкладці|розділі|"
    r"розділу|модальному вікні|вікні|вікна|блоці|попапі|діалозі|кошику|кошика|профілі|профілю|налаштуваннях|"
    r"особистому кабінеті|кабінеті|каталозі|картці товару|картці|списку|таблиці|"
    r"страницу|вкладку|раздел|форму|экран|окно|корзину|профиль|настройки|каталог|карточку товара|карточку|"
    r"сторінку|розділ|вікно|кошик|профіль|налаштування|картку товару|картку)\b"
    r"(?P<tail>(?:[ \t]+(?:[«\"“][^»\"”]{1,40}[»\"”]|[\w'’-]+)){0,3})",
    re.I,
)
_TAIL_STOP = re.compile(
    r"^(?:и|а|но|или|когда|после|при|если|затем|потом|то|я|мы|он|она|оно|они|это|что|чтобы|где|не|ни|і|й|та|"
    r"але|або|коли|після|якщо|потім|ми|воно|вони|це|що|щоб|де|кнопк\w*|ссылк\w*|посиланн\w*|поле|поля|страниц\w*|"
    r"сторінк\w*)$",
    re.I,
)

# --- Environment ----------------------------------------------------------------------

_NUM = r"v?\d+(?:\.\d+)*"
_ENVIRONMENT = (
    re.compile(
        r"\b(?:Google\s+)?(?:Chrome|Chromium|Mozilla\s+Firefox|Firefox|Safari|Microsoft\s+Edge|(?-i:Edge)|Opera|Brave|"
        rf"Vivaldi|Samsung\s+Internet|Yandex(?:\s?Browser)?|Яндекс[\s.]?Браузер\w*)(?:\s+(?:version\s+)?{_NUM})?\b",
        re.I,
    ),
    re.compile(
        r"\b(?:(?-i:Windows)(?:\s+(?:10|11|7|8(?:\.1)?|XP|Server\s+\d{4}))?|macOS(?:\s+(?-i:[A-Z][a-z]+))?"
        rf"(?:\s+{_NUM})?|Mac\s?OS(?:\s?X)?(?:\s+{_NUM})?|OS\s?X|iOS\s*\d+(?:\.\d+)*|iPadOS(?:\s*\d+(?:\.\d+)*)?|"
        rf"Android(?:\s+{_NUM})?|Ubuntu(?:\s+{_NUM})?|Linux|Debian|Fedora|ChromeOS)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:iPhone(?:\s+(?:\d+|SE|X[RS]?))?(?:\s+(?:Pro\s+Max|Pro|Plus|Mini))?|iPad(?:\s+(?:Pro|Air|Mini))?|"
        r"Pixel\s+\d+\w*|Samsung\s+Galaxy\s+\w+|(?-i:Galaxy)\s+[A-Z]\d+\w*|Xiaomi\s+\w+|Redmi\s+\w+|"
        r"Huawei\s+\w+|OnePlus\s+\w+|MacBook(?:\s+(?:Pro|Air))?)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:app\s+)?(?:version|ver\.?|build|release|версия|версии|версию|версія|версії|сборка|сборке|сборки|"
        r"збірка|збірці|збірки|релиз|релизе|релиза|реліз|релізі|релізу)\s*[:#]?\s*v?\d+(?:\.\d+)*(?:[-+][\w.]+)?"
        r"|\bv\d+(?:\.\d+)+(?:[-+][\w.]+)?\b",
        re.I,
    ),
    re.compile(
        r"\b(?:staging|production|prod|preprod|pre-prod|UAT|sandbox|dev(?:\s+(?:environment|server|env))?|"
        r"QA\s+(?:environment|env|server|stand)|test\s+(?:environment|env|server)|стейдж\w*|стейджинг\w*|"
        r"продакшн\w*|продакшен\w*|прод(?:е|а|у|і)?|тестов\w+\s+(?:среде|среда|стенде|стенд|сервере|середовищі|"
        r"сервері|стенді)|стенде|стенді)\b",
        re.I,
    ),
    re.compile(r"\b\d{3,4}\s?[x×]\s?\d{3,4}\b"),
)

# --- Severity cues (checked in the actual result) ---------------------------------------

_HIGH = re.compile(
    r"\b(?:crash\w*|data loss|lost (?:all |my |the )*(?:data|changes|edits|work|orders?|files?)|corrupt\w*|security|"
    r"vulnerab\w*|exposed|leak\w*|password (?:is )?(?:visible|shown)|charged twice|double charge\w*|"
    r"payments? fail\w*|(?:cannot|can't|unable to) (?:log ?in|sign in|pay|check ?out|save|place)|"
    r"internal server error|server error|500|blocks?|blocker|blocked|all users|everyone|white screen|"
    r"blank screen|freez\w*|hangs|hung|not responding|unresponsive|"
    r"пада\w*|упал\w*|вылет\w*|потер\w* данн\w*|данные (?:пропа|удал|теря)\w*|безопасност\w*|уязвим\w*|"
    r"утечк\w*|пароль (?:виден|отображается)|списал\w* дважды|двойн\w* списани\w*|"
    r"(?:не могу|невозможно) (?:войти|залогиниться|авторизоваться|оплатить|оформить|сохранить)|"
    r"оплата не\s+\w+|ошибка сервера|серверная ошибка|блокир\w*|блокер|у всех|все пользователи|белый экран|"
    r"пустой экран|завис\w*|не отвечает|"
    r"впав\w*|впала|виліта\w*|втрат\w* даних|дані (?:зника|видал|втрача)\w*|безпек\w*|вразлив\w*|витік\w*|"
    r"пароль (?:видно|відображається)|списал\w* двічі|подвійн\w* списанн\w*|"
    r"(?:не можу|неможливо) (?:увійти|залогінитися|авторизуватися|оплатити|оформити|зберегти)|"
    r"помилка сервера|блоку\w*|у всіх|(?:всі|усі) користувачі|білий екран|порожній екран|зависа\w*|"
    r"не відповідає)\b",
    re.I,
)
_LOW = re.compile(
    r"\b(?:typo\w*|misspell\w*|spelling|grammar|alignment|misaligned|not aligned|colou?rs?|fonts?|spacing|padding|"
    r"margins?|cosmetic|tooltips?|icons?|placeholders?|translation|untranslated|truncated|cut off|overlap\w*|"
    r"опечатк\w*|орфограф\w*|выравнивани\w*|не выровн\w*|съезжа\w*|цвет\w*|шрифт\w*|отступ\w*|косметич\w*|"
    r"подсказк\w*|иконк\w*|плейсхолдер\w*|перевод\w*|не переведен\w*|обрезан\w*|наезжа\w*|"
    r"друкарськ\w* помилк\w*|орфограф\w*|вирівнюванн\w*|не вирівн\w*|з'їжджа\w*|колір|кольор\w*|відступ\w*|"
    r"підказк\w*|іконк\w*|переклад\w*|не перекладен\w*|обрізан\w*|наїжджа\w*)\b",
    re.I,
)
_CORE_FLOW = re.compile(
    r"\b(?:check ?out|payments?|pay|purchase|log ?in|sign ?in|sign ?up|registration|оплат\w*|платеж\w*|платёж\w*|"
    r"оформлени\w* заказа|вход\w*|войти|логин\w*|авторизац\w*|регистрац\w*|платіж\w*|оформленн\w* замовленн\w*|"
    r"вхід|увійти|реєстрац\w*)\b",
    re.I,
)
_INTERMITTENT = re.compile(
    r"\b(?:sometimes|occasionally|intermittent(?:ly)?|randomly|from time to time|once|only once|rarely|not always|"
    r"иногда|периодически|время от времени|случайно|редко|один раз|однажды|не всегда|іноді|інколи|періодично|"
    r"час від часу|випадково|рідко|одного разу|не завжди)\b",
    re.I,
)

# --- Clause splitting -------------------------------------------------------------------

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_HARD_SPLIT = re.compile(
    r"\s*;\s*|\s*(?:→|->|=>)\s*"
    r"|,?\s+(?:and then|then|after that|afterwards|but|however|затем|потом|после этого|после чего|но|однако|"
    r"потім|після цього|після чого|але|проте|однак)\s+|,\s+а\s+"
    # "the app crashed when I uploaded a photo": the trigger starts a clause of its own.
    r"|(?<=\w)(?=\s+(?:when|whenever|когда|коли)\s)",
    re.I,
)
_LEADING = re.compile(
    r"^(?:(?:and then|and|then|so|also|next|first|finally|after that|и|а|но|затем|потом|сначала|далее|потім|і|й|"
    r"та|але|спочатку|далі)\s+)+",
    re.I,
)
# Dropped from the start of What and the title only ("I get a 500 error" → "500 error").
_OBSERVER = re.compile(
    r"^(?:(?:i|we)\s+(?:(?:always|still|now|then)\s+)?(?:get|got|see|saw|receive|received)\s+(?:an?\s+|the\s+)?|"
    r"there(?:'s| is| are)\s+(?:an?\s+)?|it\s+(?:shows|displays)\s+(?:an?\s+)?|"
    r"(?:я\s+|мы\s+)?(?:получаю|получил\w*|вижу|видим|получаем)\s+|у меня\s+|"
    r"(?:я\s+|ми\s+)?(?:отримую|отримав\w*|бачу|бачимо|отримуємо)\s+|у мене\s+)",
    re.I,
)


_GREETING = re.compile(
    r"^(?:(?:hey|hi|hello)(?:\s+(?:team|all|guys|everyone))?|привет(?:ствую)?|здравствуйте|добрый день|коллеги|"
    r"привіт|вітаю|добрий день|колеги)(?:[,!.]+\s*|\s+)",
    re.I,
)


def _clean(text: str) -> str:
    text = _LEADING.sub("", _GREETING.sub("", " ".join(text.split())))
    return text.strip(" \t,;:").rstrip(".!") if not text.endswith("...") else text.strip(" \t,;:")


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _limit(text: str) -> str:
    return text if len(text) <= MAX_FIELD_CHARS else text[: MAX_FIELD_CHARS - 1].rstrip() + "…"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for item in items:
        if (key := _key(item)) and key not in seen:
            seen.add(key)
            result.append(item)
    return result[:MAX_ITEMS]


# ---------------------------------------------------------------------------
# 1. Labeled parts
# ---------------------------------------------------------------------------

@dataclass
class _Parsed:
    sections: dict[str, list[str]] = field(default_factory=dict)
    # Lines outside any labeled part, in order.
    prose: list[str] = field(default_factory=list)
    unassigned: list[str] = field(default_factory=list)


def _label_of(line: str) -> tuple[str | None, str, str]:
    """(field or "env:<label>" or None, label as written, text after the label)."""
    if heading := _HEADING_LINE.match(line):
        label = (heading.group("h") or heading.group("b") or "").strip(" :")
        if _key(label) in _LABEL_MAP:
            return _LABEL_MAP[_key(label)], label, ""
    if match := _LABEL_LINE.match(line):
        label, rest = match.group("label").strip(), match.group("rest").strip()
        if _key(label) in _LABEL_MAP:
            return _LABEL_MAP[_key(label)], label, rest
        if _key(label) in _ENV_LABEL_SET:
            return "env", label, rest
        return "", label, rest
    return None, "", ""


def _parse_labels(text: str) -> _Parsed:
    parsed = _Parsed()
    current: str | None = None
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if current and parsed.sections.get(current):
                current = None  # a blank line ends a labeled part that has content
            continue
        name, label, rest = _label_of(line)
        if name == "env":
            current = "environment"
            parsed.sections.setdefault(current, [])
            if rest:
                parsed.sections[current].append(f"{label}: {rest}")
            continue
        if name:
            current = name
            parsed.sections.setdefault(current, [])
            if rest:
                parsed.sections[current].append(rest)
            continue
        if name == "" and not _BULLET.match(line):
            current = None  # an unknown label ("Note: …") starts text of no field
        if current:
            parsed.sections[current].append(line)
        else:
            parsed.prose.append(line)
    return parsed


def _is_unknown(value: str) -> bool:
    return _key(value).rstrip(".") in _UNKNOWN


def _items(lines: list[str]) -> list[str]:
    items = [_BULLET.sub("", line).strip() for line in lines]
    return [item for item in items if item and not _is_unknown(item)]


def _level(value: str) -> str | None:
    words = re.split(r"[\s,.;/()-]+", _key(value))
    return next((_LEVEL_MAP[w] for w in words if w in _LEVEL_MAP), None)


# ---------------------------------------------------------------------------
# 2. Unlabeled text
# ---------------------------------------------------------------------------

@dataclass
class _Clause:
    text: str
    kind: str | None  # expected, precondition, actual, step, trigger, context or None


def _where_phrases(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for m in _URL.finditer(text):
        found.append((m.start(), m.group(0).rstrip(".,;:!?")))
    without_urls = _URL.sub(lambda m: " " * len(m.group(0)), text)
    for m in _PATH.finditer(without_urls):
        found.append((m.start(), m.group(0)))
    for m in _EN_PLACE.finditer(text):
        noun = m.group("noun").lower()
        if not m.group("mods").strip() and noun in _VAGUE_NOUNS and not m.group(0).rstrip().endswith(("\"", "”", "»", "'")):
            continue  # "on the page": which one?
        # After a verb the phrase starts at the place itself: "opened the Orders page" → "Orders page".
        start = m.start() if m.group("prep") else m.start("mods")
        found.append((start, text[start: m.end()].strip()))
    for m in _SLAVIC_PLACE.finditer(text):
        words = []
        for word in m.group("tail").split():
            if _TAIL_STOP.match(word) or _ACTION_START.match(word) or _ACTUAL_STRONG.match(word) \
                    or _ACTUAL_WEAK.match(word) or _EXPECTED.match(word):
                break
            words.append(word)
        start = m.start() if m.group("prep") else m.start("noun")  # "открываю раздел «Отчёты»" → "раздел «Отчёты»"
        phrase = text[start: m.start("tail")] + (" " + " ".join(words) if words else "")
        found.append((m.start(), phrase.strip()))
    found.sort()
    phrases = _unique([_clean(p) for _, p in found])
    # "on the checkout page" also contains "checkout": keep the longer one.
    return [p for p in phrases if not any(p != q and _key(p) in _key(q) for q in phrases)]


def _environment_items(text: str) -> list[str]:
    spans: list[tuple[int, int, str]] = []
    for pattern in _ENVIRONMENT:
        spans += [(m.start(), m.end(), m.group(0).strip()) for m in pattern.finditer(text)]
    # Overlapping matches ("Chrome version 120" and "version 120"): keep the longest.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int, str]] = []
    for span in spans:
        if kept and span[0] < kept[-1][1]:
            continue
        kept.append(span)
    return _unique([s[2] for s in kept])


def _when_phrases(text: str) -> list[str]:
    found = [(m.start(), m.group(0)) for m in _TIMING.finditer(text)]
    found += [(m.start(), m.group(0)) for m in FREQUENCY.finditer(text)]
    found.sort()
    phrases = _unique([_clean(p) for _, p in found])
    return [p for p in phrases if not any(p != q and _key(p) in _key(q) for q in phrases)]


def _context_phrases(text: str) -> list[str]:
    return _where_phrases(text) + _environment_items(text) + _when_phrases(text)


def _context_only(text: str) -> bool:
    """True when `text` is (almost) only where / environment / when: "In Chrome 120 on Windows 11", "every time"."""
    phrases = _context_phrases(text)
    if not phrases:
        return False
    rest = text
    for phrase in sorted(phrases, key=len, reverse=True):
        rest = re.sub(re.escape(phrase), " ", rest, flags=re.I)
    return sum(len(word) > 3 for word in re.findall(r"[\w'’-]+", rest)) <= 1


def _without_leading_place(text: str) -> str:
    """ "On the checkout page I click Pay" → "I click Pay", to find the action after the place."""
    for phrase in _where_phrases(text):
        if _key(text).startswith(_key(phrase)):
            return text[len(phrase):].lstrip(" ,")
    return text


def _is_step(text: str) -> bool:
    return any(
        _ACTION_START.match(candidate) is not None and not _OBSERVATION_VERB.match(candidate)
        for candidate in (text, _without_leading_place(text))
    )


def _kind(text: str) -> str | None:
    if not text:
        return None
    if _INSTEAD.match(text) or _EXPECTED.search(text):
        return "expected"
    if _PRECONDITION.search(text):
        return "precondition"
    if _ACTUAL_STRONG.search(text):
        return "actual"
    if _TRIGGER.match(text):
        return "trigger"
    if _is_step(text):
        return "step"
    if _context_only(text):
        return "context"
    if _ACTUAL_WEAK.search(text):
        return "actual"
    return None


def _split_merging_unknown(pattern: re.Pattern[str], text: str) -> list[str]:
    """Split at `pattern`, but join parts no rule recognises back to their neighbour with the
    separator as written ("name, email and phone" and "Terms and Conditions" stay one clause)."""
    pieces = pattern.split(text)  # the pattern has one group: [part, separator, part, ...]
    parts, separators = pieces[::2], ["", *pieces[1::2]]
    merged: list[str] = []
    pending = ""
    for part, separator in zip(parts, separators, strict=True):
        if not part.strip():
            continue
        if _kind(_clean(part)) is None:
            if merged:
                merged[-1] = f"{merged[-1]}{separator}{part}"
            else:
                pending = f"{pending}{separator}{part}" if pending else part
            continue
        merged.append(f"{pending}{separator}{part}" if pending else part)
        pending = ""
    if pending:
        merged.append(pending)
    return merged


_COMMA = re.compile(r"(,\s+)")
_AND = re.compile(r"(\s+(?:and|и|і|та|й)\s+)", re.I)


def _clauses(prose: list[str]) -> list[_Clause]:
    clauses: list[_Clause] = []
    for line in prose:
        line = _BULLET.sub("", line)
        for sentence in _SENTENCE_END.split(line):
            for hard in _HARD_SPLIT.split(sentence):
                for instead in _INSTEAD_SPLIT.split(hard or ""):
                    for part in _split_merging_unknown(_COMMA, instead):
                        for piece in _split_merging_unknown(_AND, part):
                            if text := _clean(piece):
                                clauses.append(_Clause(text, _kind(text)))
    return clauses


# ---------------------------------------------------------------------------
# 3. Severity and priority
# ---------------------------------------------------------------------------

_ORDER = [Severity.LOW, Severity.MEDIUM, Severity.HIGH]


def _suggest_severity(actual: str, context: str) -> tuple[Severity | None, list[str]]:
    """High for crash / data loss / security / server errors, or any failure in a core flow
    (payment, checkout, login); Low for cosmetic problems; Medium for any other failure."""
    if not actual.strip():
        return None, []
    if high := _unique([m.group(0) for m in _HIGH.finditer(actual)]):
        return Severity.HIGH, high[:3]
    if low := _unique([m.group(0) for m in _LOW.finditer(actual)]):
        return Severity.LOW, low[:3]
    failure = _ACTUAL_STRONG.search(actual)
    if failure and (flow := _CORE_FLOW.search(f"{actual}\n{context}")):
        return Severity.HIGH, _unique([failure.group(0), flow.group(0)])
    return Severity.MEDIUM, []


def _suggest_priority(severity: Severity | None, when: str) -> tuple[Priority | None, list[str]]:
    if severity is None:
        return None, []
    index = _ORDER.index(severity)
    basis = ["follows_severity"]
    if index > 0 and _INTERMITTENT.search(when):
        index -= 1
        basis.append("lowered_intermittent")
    return Priority(_ORDER[index].value), basis


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def _text_value(lines: list[str]) -> str:
    items = _items(lines)
    return _limit("\n".join(items)) if items else ""


def _steps_value(lines: list[str]) -> list[str]:
    items = _items(lines)
    if len(items) == 1:
        items = [i.strip() for i in _INLINE_STEPS.split(items[0]) if i and i.strip()]
        items = [_BULLET.sub("", i).strip() for i in items]
    return _unique([_limit(_capitalize(_clean(i))) for i in items if _clean(i)])


def generate_bug_report(text: str, report_id: str, created_at: str = "") -> ProductBugReport:
    """Build a report from the description. Raises BugInputError for empty or too long text."""
    try:
        description = validate_text(text)
    except InputError as error:
        raise BugInputError("empty" if error.code == "empty_input" else "too_long") from error
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise BugInputError("too_long")

    parsed = _parse_labels(description)
    sections = parsed.sections
    clauses = _clauses(parsed.prose)
    unassigned = list(parsed.unassigned)

    def of(kind: str) -> list[str]:
        return [c.text for c in clauses if c.kind == kind]

    values: dict[str, object] = {}
    for name in ("title", "what", "where", "when", "actual_result", "expected_result"):
        if name in sections:
            values[name] = _text_value(sections[name])
    for name in ("preconditions", "environment"):
        if name in sections:
            values[name] = _unique([_limit(i) for i in _items(sections[name])])
    if "steps" in sections:
        values["steps"] = _steps_value(sections["steps"])

    # Unlabeled clauses fill only the fields that were not labeled; the rest stays visible as unassigned.
    def fill(name: str, kind: str, joined: bool) -> None:
        found = [_capitalize(c) for c in of(kind)]
        if not found:
            return
        if name in sections:
            unassigned.extend(found)
        elif joined:
            values[name] = _limit(". ".join(_unique(found)))
        else:
            values[name] = _unique([_limit(f) for f in found])

    expected = [_capitalize(_clean(_INSTEAD.sub("", c))) for c in of("expected")]
    if expected:
        if "expected_result" in sections:
            unassigned.extend(expected)
        else:
            values["expected_result"] = _limit(". ".join(_unique(expected)))
    fill("actual_result", "actual", joined=True)
    fill("preconditions", "precondition", joined=False)
    trigger_steps = [m.group("step") for c in of("trigger") if (m := _TRIGGER_STEP.match(c))]
    steps = [_capitalize(s) for s in of("step") + trigger_steps]
    if steps:
        if "steps" in sections:
            unassigned.extend(c for c in of("step") if c not in trigger_steps)
        else:
            values["steps"] = _unique([_limit(s) for s in _order_steps(steps, clauses)])
    unassigned += [_capitalize(c.text) for c in clauses if c.kind is None]

    # Context comes only from what was observed: never from the expected result.
    observed_parts = [c.text for c in clauses if c.kind != "expected"]
    for name in ("title", "what", "where", "when", "actual_result", "steps", "preconditions"):
        if name in sections:
            observed_parts += _items(sections[name])
    # Each part on its own, so a phrase never runs from one clause into the next.
    def collect(find: Callable[[str], list[str]]) -> list[str]:
        found = _unique([item for part in observed_parts for item in find(part)])
        return [f for f in found if not any(f != o and _key(f) in _key(o) for o in found)]

    if "environment" not in values:
        values["environment"] = collect(_environment_items)
    if "where" not in values and (where := collect(_where_phrases)):
        values["where"] = _limit("; ".join(where))
    if "when" not in values:
        when = _unique([_capitalize(c) for c in of("trigger")] + collect(_when_phrases))
        when = [w for w in when if not any(w != o and _key(w) in _key(o) for o in when)]
        if when:
            values["when"] = _limit("; ".join(when))

    actual = str(values.get("actual_result") or "")
    if "what" not in values and actual:
        first = re.split(r"(?<=\S)\.\s+", actual)[0]
        values["what"] = _limit(_capitalize(_OBSERVER.sub("", first)) or first)
    if "title" not in values and (what := str(values.get("what") or "")):
        values["title"] = _title(what.splitlines()[0], str(values.get("where") or "").split("; ")[0],
                                 _step_before_actual(clauses))

    # Severity and priority: the reporter's word first, else a suggestion from the actual result.
    severity, severity_source, severity_basis = None, Source.RULE, []
    if "severity" in sections and (stated := " ".join(_items(sections["severity"]))):
        if (level := _level(stated)) is not None:
            severity, severity_source, severity_basis = Severity(level), Source.USER, [stated]
        else:
            unassigned.append(f"{_label_text('severity', description)}: {stated}")
    if severity is None and severity_source == Source.RULE:
        context = "\n".join([str(values.get("where") or ""), *map(str, values.get("steps") or [])])  # type: ignore[call-overload]
        severity, severity_basis = _suggest_severity("\n".join([actual, str(values.get("what") or "")]), context)
    priority, priority_source, priority_basis = None, Source.RULE, []
    if "priority" in sections and (stated := " ".join(_items(sections["priority"]))):
        if (level := _level(stated)) is not None:
            priority, priority_source, priority_basis = Priority(level), Source.USER, [stated]
        else:
            unassigned.append(f"{_label_text('priority', description)}: {stated}")
    if priority is None:
        priority, priority_basis = _suggest_priority(severity, str(values.get("when") or ""))

    return ProductBugReport(
        id=report_id,
        **values,  # type: ignore[arg-type]
        severity=severity,
        severity_source=severity_source,
        severity_basis=severity_basis,
        priority=priority,
        priority_source=priority_source,
        priority_basis=priority_basis,
        description=description,
        unassigned=_unique([_limit(u) for u in unassigned]),
        source=Source.RULE,
        created_at=created_at,
        updated_at=created_at,
    )


def _step_before_actual(clauses: list[_Clause]) -> str:
    """The step written right before the first actual result ("I click Pay", then "nothing happens")."""
    for index, clause in enumerate(clauses):
        if clause.kind == "actual":
            previous = clauses[index - 1] if index else None
            if previous is not None and previous.kind in ("step", "trigger"):
                return previous.text
            return ""
    return ""


def _title(what: str, where: str, step: str) -> str:
    """What — where, both as written. A short What ("nothing happens") is put after the step that caused it."""
    title = what
    if step and len(what.split()) <= 3:
        title = f"{_capitalize(step)} — {what[:1].lower()}{what[1:]}"
    if where and _key(where) not in _key(title):
        title = f"{title} — {where[:1].lower()}{where[1:]}" if title == what else f"{title} ({where})"
    return title if len(title) <= 120 else title[:119].rstrip() + "…"


def _order_steps(steps: list[str], clauses: list[_Clause]) -> list[str]:
    """Steps in the order they were written (trigger steps sit where their trigger was)."""
    position: dict[str, int] = {}
    for index, clause in enumerate(clauses):
        if clause.kind == "trigger" and (m := _TRIGGER_STEP.match(clause.text)):
            position.setdefault(_key(m.group("step")), index)
        else:
            position.setdefault(_key(clause.text), index)
    return sorted(steps, key=lambda s: position.get(_key(s), len(clauses)))


def _label_text(name: str, description: str) -> str:
    for line in description.split("\n"):
        found, label, _ = _label_of(line.strip())
        if found == name:
            return label
    return name
