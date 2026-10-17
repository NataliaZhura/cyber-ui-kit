#!/usr/bin/env python3
"""Меню бота в Telegram в нашем порядке, с «Новый разговор» первым.

OpenClaw при запуске ставит меню сам и не даёт добавить /new в свой список (конфликт со встроенной командой).
Этот скрипт запускается после старта OpenClaw и ставит меню целиком через Telegram Bot API (setMyCommands).

  python3 menu.py          поставить меню
  python3 menu.py show     показать, какое меню стоит сейчас

Токен бота берётся из файла, указанного в настройке OpenClaw channels.telegram.tokenFile; на экран не выводится.
"""
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MENU = [("start", "Знакомство: что умеет Ави"), ("new", "Новый разговор"), ("market", "Новости рынка за период"),
        ("bpla", "🆕 Беспилотники: новости, рынок, компании"),
        ("company", "Новости авиакомпании за период"), ("compare", "Сравнить две компании"),
        ("profile", "Справка по компании целиком"), ("finance", "Оценка финансов компании"),
        ("courts", "Суды, приставы, налоги"), ("assets", "Имущество и лизинг"),
        ("find", "Найти ИНН и ОГРН по названию"), ("scale", "Что значат классы риска A-E"),
        ("remember", "Запомнить компанию, правило, факт"), ("save", "Сохранить ответ или справку")]


DESCRIPTION = ("Ави — аналитик авиарынка. Новости отрасли с оценкой влияния, справки по авиакомпаниям и производителям, "
               "рынок беспилотников и компании БАС, финансовый анализ и стресс-тесты моделей. Только открытые источники.")
SHORT = "Аналитик авиарынка: новости, справки по компаниям, финансовый анализ"


_TOKEN = None


def token():
    """Токен читаем один раз: каждый вызов openclaw — несколько секунд, а при запуске службы время ограничено."""
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = _read_token()
    return _TOKEN


def _read_token():
    out = subprocess.run(["openclaw", "config", "get", "channels.telegram.tokenFile"],
                         capture_output=True, text=True, timeout=60).stdout
    # в выводе могут быть служебные строки; путь — последняя строка в кавычках или без
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    if not lines:
        sys.exit("Не нашёл настройку channels.telegram.tokenFile")
    raw = lines[-1]
    path = json.loads(raw) if raw.startswith('"') else raw
    return Path(path).expanduser().read_text(encoding="utf-8").strip()


def api(method, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token()}/{method}", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


if __name__ == "__main__":
    if sys.argv[1:] == ["show"]:
        res = api("getMyCommands")
        for c in res.get("result", []):
            print(f"/{c['command']} — {c['description']}")
        sys.exit(0)
    cmds = json.dumps([{"command": c, "description": d} for c, d in MENU], ensure_ascii=False)
    res = api("setMyCommands", commands=cmds)
    api("setChatMenuButton", menu_button=json.dumps({"type": "commands"}))
    api("setMyDescription", description=DESCRIPTION)        # текст «Что умеет этот бот?» до нажатия «Старт»
    api("setMyShortDescription", short_description=SHORT)   # строка в профиле бота
    print("Меню поставлено: " + ", ".join("/" + c for c, _ in MENU) if res.get("ok") else f"Ошибка Telegram: {res}")
