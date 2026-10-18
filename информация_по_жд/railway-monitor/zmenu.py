#!/usr/bin/env python3
"""Меню, описание и кнопка «Меню» для @zhdusha_bot через Telegram Bot API (меню Ави не трогает).

  python3 zmenu.py          поставить меню ЖДуши
  python3 zmenu.py show     показать, какое меню стоит сейчас
  python3 zmenu.py webapp https://<адрес>   кнопка «Меню» открывает мини-приложение (команды остаются — по «/»)
  python3 zmenu.py          (без слов) — вернуть кнопку «Меню» со списком команд

Токен — ~/.secrets/zhdusha_bot; на экран не выводится.
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MENU = [("start", "Знакомство: что умеет ЖДуша"), ("new", "Новый разговор"),
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


if __name__ == "__main__":
    if sys.argv[1:] == ["show"]:
        for name, extra in SCOPES + owner_scope():
            cmds = api("getMyCommands", **extra).get("result", [])
            has = "есть /prognoz" if any(c["command"] == "prognoz" for c in cmds) else "НЕТ /prognoz"
            print(f"{name}: {len(cmds)} команд, {has}" if cmds else f"{name}: пусто (берётся общий список)")
        sys.exit(0)
    webapp = sys.argv[2] if sys.argv[1:2] == ["webapp"] and len(sys.argv) > 2 else None
    if sys.argv[1:2] == ["webapp"] and not (webapp or "").startswith("https://"):
        sys.exit("Нужен адрес с https://, например: python3 zmenu.py webapp https://zhdusha.duckdns.org")
    cmds = json.dumps([{"command": c, "description": d} for c, d in MENU], ensure_ascii=False)
    res = api("setMyCommands", commands=cmds)
    for name, extra in SCOPES[1:]:
        api("setMyCommands", commands=cmds, **extra)
    for name, extra in owner_scope():  # личный список владельца, если его кто-то поставил, убираем — пусть берётся общий
        api("deleteMyCommands", **extra)
    button = {"type": "web_app", "text": "Меню", "web_app": {"url": webapp}} if webapp else {"type": "commands"}
    api("setChatMenuButton", menu_button=json.dumps(button, ensure_ascii=False))
    api("setMyDescription", description=DESCRIPTION)
    api("setMyShortDescription", short_description=SHORT)
    if webapp:
        print(f"Кнопка «Меню» открывает мини-приложение: {webapp}")
    print("Меню ЖДуши поставлено: " + ", ".join("/" + c for c, _ in MENU) if res.get("ok") else f"Ошибка Telegram: {res}")
