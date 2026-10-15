#!/usr/bin/env python3
"""Файлы владельцу в Telegram через бота ЖДуши (@zhdusha_bot).

  python3 send.py saved/2026-10-16_рынок.pdf [ещё файлы …]       владельцу
  python3 send.py --to <telegram_id> файл.pdf                      другому человеку (только после «да» владельца)

Токен — ~/.secrets/zhdusha_bot (на экран не выводится). Telegram ID владельца — ~/.secrets/zhdusha_owner
(одна строка с числом). Получатель должен сначала сам написать боту /start. Отправки пишутся в saved/sent.log.
"""
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
SECRETS = Path.home() / ".secrets"


def read_secret(name):
    p = SECRETS / name
    if not p.exists():
        sys.exit(f"Нет файла {p}. Как создать — SETUP.md, шаг 2.")
    return p.read_text(encoding="utf-8").strip()


def send(chat_id, path, token):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + \
        f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendDocument", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode()).get("ok")
    except urllib.error.HTTPError as e:
        sys.exit(f"Telegram не принял {path.name}: {e.read(300).decode('utf-8', 'replace')} "
                 "(получатель должен сначала сам написать боту /start)")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    chat_id = None
    if args[0] == "--to":
        chat_id, args = args[1], args[2:]
    chat_id = chat_id or read_secret("zhdusha_owner")
    token = read_secret("zhdusha_bot")
    log = BASE / "saved" / "sent.log"
    log.parent.mkdir(exist_ok=True)
    for f in args:
        path = Path(f).expanduser()
        ok = send(chat_id, path, token)
        print(f"{'Отправлено' if ok else 'Ошибка'} в Telegram {chat_id}: {path.name}")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M}\ttelegram\t{chat_id}\t{path.name}\t{'ok' if ok else 'error'}\n")


if __name__ == "__main__":
    main()
