#!/usr/bin/env python3
"""Меню, описание и кнопка «Меню» для @zhdusha_bot через Telegram Bot API (меню Ави не трогает).

  python3 zmenu.py          поставить меню ЖДуши
  python3 zmenu.py show     показать, какое меню стоит сейчас
  python3 zmenu.py webapp https://<адрес>   кнопка «Меню» открывает мини-приложение (команды остаются — по «/»)
  python3 zmenu.py          (без слов) — вернуть кнопку «Меню» со списком команд
  python3 zmenu.py pin https://<адрес> [ID …]   закреплённое сообщение с кнопкой «Открыть ЖДушу» (для телефона;
                                                без ID — владельцу)
  python3 zmenu.py panel [ID …] [--no-pin]     пульт: кнопки прогноза по 4 типам, ставки, сделка, обзор — открывают
                                                мини-приложение сразу на расчёте (0 токенов); без ID — владельцу

Токен — ~/.secrets/zhdusha_bot; на экран не выводится.
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MENU = [("start", "Старт: начало разговора, что умеет ЖДуша"), ("new", "Новая тема: начать разговор заново"),
        ("poluvagony", "Справка: рынок полувагонов"), ("krytye", "Справка: рынок крытых вагонов"),
        ("market", "Новости рынка за период"), ("rates", "Ставки аренды и предоставления"),
        ("loading", "Погрузка по грузам"), ("balance", "Баланс парка: дефицит или профицит"),
        ("forecast", "Прогноз на неделю"), ("prognoz", "Прогноз ставок до 2030: свой выбор показателей"), ("vagon", "Стоимость вагона: покупать или продавать"), ("company", "Новости по оператору"),
        ("profile", "Справка по компании целиком"), ("finance", "Оценка финансов компании"),
        ("courts", "Суды, приставы, налоги"), ("assets", "Имущество и лизинг"),
        ("compare", "Сравнить две компании"), ("lease", "Оперировать или сдавать в аренду"),
        ("model", "Проверить финмодель (Excel) и стресс-тест"),
        ("zavod", "Завод: аванс и риск задержки поставки"),
        ("find", "Найти ИНН и ОГРН по названию"), ("remember", "Запомнить компанию, правило, факт"),
        ("save", "Сохранить в PDF и Word")]
DESCRIPTION = ("ЖДуша — аналитик рынка полувагонов и крытых вагонов: ставки, погрузка, баланс парка, тарифы, "
               "справки по операторам, прогноз на неделю и стресс-тесты моделей.")
SHORT = "Аналитик рынка полувагонов и крытых вагонов"
TOKEN = (Path.home() / ".secrets" / "zhdusha_bot").read_text(encoding="utf-8").strip()


def api(method, **params):
    req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                 data=urllib.parse.urlencode(params).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# Telegram показывает список из самой «узкой» области: чат > все личные чаты > язык > по умолчанию.
# Если OpenClaw поставил список в узкую область, наш общий его не перебивает — ставим во все.
SCOPES = [("по умолчанию", {}), ("все личные чаты", {"scope": json.dumps({"type": "all_private_chats"})}),
          ("по умолчанию, ru", {"language_code": "ru"}),
          ("все личные чаты, ru", {"scope": json.dumps({"type": "all_private_chats"}), "language_code": "ru"})]


def owner_scope():
    p = Path.home() / ".secrets" / "zhdusha_owner"
    if p.exists():
        cid = p.read_text(encoding="utf-8").strip()
        return [("чат владельца", {"scope": json.dumps({"type": "chat", "chat_id": cid})})]
    return []


def pin(url, ids):
    """Сообщение с кнопкой приложения + закрепить: работает на телефоне, даже если кнопка «Меню» не обновилась."""
    kb = json.dumps({"inline_keyboard": [[{"text": "📂 Открыть ЖДушу", "web_app": {"url": url}}]]}, ensure_ascii=False)
    for cid in ids:
        r = api("sendMessage", chat_id=cid, text="Приложение ЖДуши: отчёты по разделам, поиск и новые запросы.",
                reply_markup=kb)
        if not r.get("ok"):
            print(f"{cid}: Telegram не принял — {r}")
            continue
        p = api("pinChatMessage", chat_id=cid, message_id=r["result"]["message_id"], disable_notification=True)
        print(f"{cid}: кнопка отправлена{', закреплена' if p.get('ok') else ' (закрепить не удалось — закрепи вручную)'}")


URL = "https://zhdusha.duckdns.org"
# Пульт: кнопки открывают мини-приложение сразу на нужном расчёте — считает программа, нейросеть не участвует (0 токенов).
PANEL = [[("📈 Полувагон", "?go=build&w=inno"), ("📦 Крытый", "?go=build&w=kr158")],
         [("🌾 Зерновоз", "?go=build&w=hop_grain"), ("🚢 Платформа", "?go=build&w=fit80")],
         [("💹 Ставки и парк", "?go=rates"), ("🧮 Сделка: лизинг", "?go=deal")],
         [("📰 Обзор рынка", "?go=sec&s=market"), ("📂 Все отчёты", "")]]


# Пульт гостя: без «Ставок и парка» (данные партнёра — только владельцу), с анкетой ставок
GUEST_PANEL = [[("📈 Полувагон", "?go=build&w=inno"), ("📦 Крытый", "?go=build&w=kr158")],
               [("🌾 Зерновоз", "?go=build&w=hop_grain"), ("🚢 Платформа", "?go=build&w=fit80")],
               [("🧮 Сделка: лизинг", "?go=deal"), ("📝 Анкета ставок", "?go=survey")],
               [("📂 Все отчёты", "")]]


def drop_keyboard(cid):
    """Убрать кнопку приложения под полем ввода: из такой кнопки Telegram не передаёт, кто открыл, — «Нет доступа»."""
    r = api("sendMessage", chat_id=cid, text="Приложение ЖДуши — кнопка «Открыть приложение» в закреплённом сообщении.",
            reply_markup=json.dumps({"remove_keyboard": True}), disable_notification=True)
    return r.get("ok")


def set_commands():
    cmds = json.dumps([{"command": c, "description": d} for c, d in MENU], ensure_ascii=False)
    res = api("setMyCommands", commands=cmds)
    for name, extra in SCOPES[1:]:
        api("setMyCommands", commands=cmds, **extra)
    for name, extra in owner_scope():  # личный список владельца, если его кто-то поставил, убираем — пусть берётся общий
        api("deleteMyCommands", **extra)
    return res


def fix(url):
    """Всем — владельцу, гостям, респондентам: кнопка «Приложение» слева от поля ввода (открывает мини-приложение),
    команды — через «/» в поле ввода, в закрепе — только /start и /new (старый пульт с кнопками открепляется)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import zapp
    import zsurvey
    owner = (Path.home() / ".secrets" / "zhdusha_owner").read_text(encoding="utf-8").strip()
    set_commands()
    btn = lambda u, t="Приложение": json.dumps({"type": "web_app", "text": t, "web_app": {"url": u}}, ensure_ascii=False)
    api("setChatMenuButton", menu_button=json.dumps({"type": "commands"}))  # «Меню» — список команд
    people = [(owner, "владелец", PANEL)] + [(g, f"гость {a}", GUEST_PANEL) for g, a in zapp.guests().items()]
    people += [(r, "респондент", None) for r in zsurvey.respondents()]
    for cid, who, pnl in people:
        ok = api("setChatMenuButton", chat_id=cid,  # респонденту — сразу анкета; остальным — «Меню» со списком команд
                 menu_button=btn(url + "?go=survey", "Анкета") if pnl is None else json.dumps({"type": "default"})).get("ok")
        drop_keyboard(cid)
        print(f"{cid} ({who}): {'«Меню» и закреп с кнопкой приложения' if ok else 'не получилось — человек ещё не писал боту'}")
        if pnl is not None and ok:
            note(url, cid)


def note(url, cid):
    """Закреп — коротко: как начать и как сменить тему; старый пульт с кнопками открепляется (всё есть в приложении)."""
    api("unpinAllChatMessages", chat_id=cid)
    kb = json.dumps({"inline_keyboard": [[{"text": "📂 Открыть приложение", "web_app": {"url": url}}]]}, ensure_ascii=False)
    r = api("sendMessage", chat_id=cid, reply_markup=kb,
            text="/start — начало разговора: что умеет ЖДуша\n/new — новая тема (начать разговор заново)")
    if r.get("ok"):
        api("pinChatMessage", chat_id=cid, message_id=r["result"]["message_id"], disable_notification=True)


def panel(url, ids, pin_it=True, rows=None):
    """Сообщение-пульт с кнопками расчётов (+ закрепить). Нажатие кнопки не пишет боту — токены не тратятся."""
    kb = json.dumps({"inline_keyboard": [[{"text": t, "web_app": {"url": url + q}} for t, q in row] for row in rows or PANEL]},
                    ensure_ascii=False)
    text = ("Пульт ЖДуши\n"
            "/start — начало разговора: что умеет ЖДуша\n"
            "/new — перейти на новую тему (новый разговор)\n\n"
            "Кнопки ниже считают программой, мгновенно и без нейросети: прогноз ставки по типу вагона (период, сценарии, "
            "факторы, стоимость вагона), расчёт сделки в лизинг, отчёты. Любой расчёт — кнопкой «PDF в чат».\n"
            "Приложение целиком — кнопка «Приложение» слева от поля ввода. Вопросы словами — как обычно, в чат.")
    for cid in ids:
        r = api("sendMessage", chat_id=cid, text=text, reply_markup=kb)
        if not r.get("ok"):
            print(f"{cid}: Telegram не принял — {r}")
            continue
        if pin_it:
            api("pinChatMessage", chat_id=cid, message_id=r["result"]["message_id"], disable_notification=True)
        print(f"{cid}: пульт отправлен{', закреплён' if pin_it else ''}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["panel"]:  # python3 zmenu.py panel [ID …] [--no-pin]
        owner = (Path.home() / ".secrets" / "zhdusha_owner").read_text(encoding="utf-8").strip()
        ids = [x for x in sys.argv[2:] if not x.startswith("--")]
        panel(URL, ids or [owner], "--no-pin" not in sys.argv)
        sys.exit(0)
    if sys.argv[1:2] == ["fix"]:  # python3 zmenu.py fix — кнопка приложения и пульт всем: владельцу, гостям, респондентам
        fix(URL)
        sys.exit(0)
    if sys.argv[1:2] == ["pin"]:
        if len(sys.argv) < 3 or not sys.argv[2].startswith("https://"):
            sys.exit("Нужен адрес: python3 zmenu.py pin https://zhdusha.duckdns.org [ID …]")
        owner = (Path.home() / ".secrets" / "zhdusha_owner").read_text(encoding="utf-8").strip()
        pin(sys.argv[2], sys.argv[3:] or [owner])
        sys.exit(0)
    if sys.argv[1:] == ["show"]:
        for name, extra in SCOPES + owner_scope():
            cmds = api("getMyCommands", **extra).get("result", [])
            has = ", ".join(("есть /" if any(c["command"] == x for c in cmds) else "НЕТ /") + x for x in ("start", "prognoz"))
            print(f"{name}: {len(cmds)} команд, {has}" if cmds else f"{name}: пусто (берётся общий список)")
        sys.exit(0)
    webapp = sys.argv[2] if sys.argv[1:2] == ["webapp"] and len(sys.argv) > 2 else None  # без «webapp» — «Меню» со списком команд
    if sys.argv[1:2] == ["webapp"] and not (webapp or "").startswith("https://"):
        sys.exit("Нужен адрес с https://, например: python3 zmenu.py webapp https://zhdusha.duckdns.org")
    res = set_commands()
    button = {"type": "web_app", "text": "Приложение", "web_app": {"url": webapp}} if webapp else {"type": "commands"}
    api("setChatMenuButton", menu_button=json.dumps(button, ensure_ascii=False))
    api("setMyDescription", description=DESCRIPTION)
    api("setMyShortDescription", short_description=SHORT)
    if webapp:
        print(f"Кнопка «Меню» открывает мини-приложение: {webapp}")
    print("Меню ЖДуши поставлено: " + ", ".join("/" + c for c, _ in MENU) if res.get("ok") else f"Ошибка Telegram: {res}")
