#!/usr/bin/env python3
"""Меню, описание и кнопка «Меню» для @zhdusha_bot через Telegram Bot API (меню Ави не трогает).

  python3 zmenu.py          поставить меню ЖДуши
  python3 zmenu.py show     показать, какое меню стоит сейчас

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
        ("forecast", "Прогноз на неделю"), ("prognoz", "Прогноз ставок до 2030 (PDF)"), ("company", "Новости по оператору"),
        ("profile", "Справка по компании целиком"), ("finance", "Оценка финансов компании"),
        ("courts", "Суды, приставы, налоги"), ("assets", "Имущество и лизинг"),
        ("compare", "Сравнить две компании"), ("lease", "Оперировать или сдавать в аренду"),
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


if __name__ == "__main__":
    if sys.argv[1:] == ["show"]:
        for c in api("getMyCommands").get("result", []):
            print(f"/{c['command']} — {c['description']}")
        sys.exit(0)
    res = api("setMyCommands", commands=json.dumps([{"command": c, "description": d} for c, d in MENU], ensure_ascii=False))
    api("setChatMenuButton", menu_button=json.dumps({"type": "commands"}))
    api("setMyDescription", description=DESCRIPTION)
    api("setMyShortDescription", short_description=SHORT)
    print("Меню ЖДуши поставлено: " + ", ".join("/" + c for c, _ in MENU) if res.get("ok") else f"Ошибка Telegram: {res}")
