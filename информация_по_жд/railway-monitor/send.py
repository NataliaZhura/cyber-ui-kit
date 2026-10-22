#!/usr/bin/env python3
"""Файлы владельцу в Telegram через бота ЖДуши (@zhdusha_bot).

  python3 send.py saved/2026-10-16_рынок.pdf [ещё файлы …]       владельцу
  python3 send.py --to <telegram_id> файл.pdf                      другому человеку (только после «да» владельца)
  python3 send.py --copy файл.md                                   текст файла владельцу сообщением (копия переписки гостя)
  python3 send.py --note "гость-прогноз"                           одна строка владельцу (гость что-то запросил)
  python3 send.py --to <telegram_id> --text письмо.html             текст файла сообщением (HTML-разметка Telegram: <b>…</b>)

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


# тип файла для Telegram: с application/octet-stream PDF на компьютере и в веб-версии не открывается встроенным просмотром
MIME = {".pdf": "application/pdf", ".md": "text/markdown", ".csv": "text/csv", ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".html": "text/html"}


APP = "https://zhdusha.duckdns.org"


def read_button(chat_id, path):
    """Кнопка «Читать в приложении» под отчётом: на компьютере Telegram не показывает PDF внутри чата."""
    try:
        import urllib.parse as up
        import zapp
        fid = zapp.read_id(chat_id, path)
    except Exception:  # noqa: BLE001 — нет мини-приложения на этой машине: просто файл
        return ""
    if not fid:
        return ""
    return json.dumps({"inline_keyboard": [[{"text": "📖 Читать в приложении",
                                             "web_app": {"url": f"{APP}?go=read&f={up.quote(fid)}"}}]]}, ensure_ascii=False)


def send(chat_id, path, token):
    boundary = uuid.uuid4().hex
    kb = read_button(chat_id, path)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            + (f"--{boundary}\r\nContent-Disposition: form-data; name=\"reply_markup\"\r\n\r\n{kb}\r\n" if kb else "")
            + f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {MIME.get(path.suffix.lower(), 'application/octet-stream')}\r\n\r\n").encode() + path.read_bytes() + \
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
    if args[0] == "--note":  # одна короткая строка владельцу — без копии ответа
        token, owner = read_secret("zhdusha_bot"), read_secret("zhdusha_owner")
        data = json.dumps({"chat_id": owner, "text": " ".join(args[1:])[:200], "disable_notification": False}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
        print("Уведомление отправлено владельцу")
        return
    if args[0] == "--copy":  # текст сообщением владельцу, частями по 3 500 знаков
        token, owner = read_secret("zhdusha_bot"), read_secret("zhdusha_owner")
        text = Path(args[1]).expanduser().read_text(encoding="utf-8")
        for i in range(0, len(text), 3500):
            data = json.dumps({"chat_id": owner, "text": text[i:i + 3500]}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=60).read()
        print("Копия отправлена владельцу")
        return
    if args[0] == "--to":
        chat_id, args = args[1], args[2:]
    if args[:1] == ["--text"]:  # письмо от бота: текст файла одним сообщением, не длиннее 4 000 знаков
        token = read_secret("zhdusha_bot")
        text = Path(args[1]).expanduser().read_text(encoding="utf-8").strip()
        if len(text) > 4000:
            sys.exit(f"Текст {len(text)} знаков — Telegram принимает до 4 096; сократи.")
        data = json.dumps({"chat_id": chat_id or read_secret("zhdusha_owner"), "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=60).read()
        except urllib.error.HTTPError as e:
            sys.exit(f"Telegram не принял: {e.read(300).decode('utf-8', 'replace')}")
        print(f"Сообщение отправлено в Telegram {chat_id or 'владельцу'}")
        return
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
