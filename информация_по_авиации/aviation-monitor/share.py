#!/usr/bin/env python3
"""Справка → PDF и Word → в чат, на почту или в Telegram другому человеку.

  ~/pw/bin/python share.py convert saved/2026-10-14_ГазпромАвиа.md     → .docx и .pdf рядом с файлом
  python3 share.py tg <telegram_id> <файл> [<файл> …]                    файлы в Telegram (себе или получателю)
  python3 share.py email <адрес> "<тема>" <файл> [<файл> …] [--new]      письмо с вложениями
  python3 share.py book                                                   адресная книга

Адресная книга — recipients.csv (имя;email;telegram_id). Адрес не из книги — только с флагом --new, который агент
ставит после явного «да» владельца. Каждая отправка пишется в saved/sent.log.
Почта бота — ~/.secrets/smtp (4 строки: сервер, порт, логин, пароль приложения). Пароль не печатается.
"""
import csv
import json
import mimetypes
import os
import smtplib
import subprocess
import sys
import urllib.request
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

BASE = Path(__file__).resolve().parent
BOOK = BASE / "recipients.csv"
LOG = BASE / "saved" / "sent.log"
SMTP = Path.home() / ".secrets" / "smtp"
FOOTER = "Подготовлено по открытым источникам. Не является инвестиционной или кредитной рекомендацией."
CSS = """body{font-family:'DejaVu Sans',Arial,sans-serif;font-size:11pt;line-height:1.4;margin:18mm 16mm;color:#111}
h1{font-size:16pt}h2{font-size:13pt;margin-top:14pt}table{border-collapse:collapse;margin:6pt 0}
td,th{border:1px solid #999;padding:3pt 6pt;font-size:10pt}pre,code{font-family:'DejaVu Sans Mono',monospace;font-size:9.5pt}
pre{background:#f4f4f4;padding:6pt}.foot{margin-top:18pt;font-size:9pt;color:#555}"""


def log(kind, to, files):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M}\t{kind}\t{to}\t{', '.join(Path(x).name for x in files)}\n")


def book():
    if not BOOK.exists():
        return []
    with BOOK.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f, delimiter=";")]


def cmd_convert(src):
    """Markdown → Word (pandoc) и PDF (pandoc → HTML → Chromium). Без pandoc — понятная ошибка, а не пустой файл."""
    src = Path(src).expanduser().resolve()
    docx, pdf, html = src.with_suffix(".docx"), src.with_suffix(".pdf"), src.with_suffix(".html")
    md = src.read_text(encoding="utf-8") + f"\n\n---\n\n*{FOOTER}*\n"
    tmp = src.with_name(src.stem + "_tmp.md")
    tmp.write_text(md, encoding="utf-8")
    try:
        subprocess.run(["pandoc", str(tmp), "-o", str(docx)], check=True)
        subprocess.run(["pandoc", str(tmp), "-s", "--metadata", f"pagetitle={src.stem}",
                        "-o", str(html)], check=True)
    except FileNotFoundError:
        sys.exit("Нет pandoc: установи командой  apt install -y pandoc fonts-dejavu")
    finally:
        tmp.unlink(missing_ok=True)
    page = html.read_text(encoding="utf-8").replace("</head>", f"<style>{CSS}</style></head>")
    html.write_text(page, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
                              executable_path=os.environ.get("PW_CHROMIUM") or None)
        pg = b.new_page()
        pg.goto(html.as_uri())
        pg.pdf(path=str(pdf), format="A4", print_background=True)
        b.close()
    html.unlink(missing_ok=True)
    print(f"Готово:\n  {docx}\n  {pdf}")


def tg_token():
    sys.path.insert(0, str(BASE))
    import menu  # тот же способ, что и для меню: токен из файла OpenClaw, на экран не выводится
    return menu.token()


def cmd_tg(chat_id, *files):
    tok = tg_token()
    for f in files:
        path = Path(f).expanduser()
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + \
            f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendDocument", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                ok = json.loads(r.read().decode()).get("ok")
        except urllib.error.HTTPError as e:
            sys.exit(f"Telegram не принял {path.name}: {e.read(300).decode('utf-8', 'replace')} "
                     "(получатель должен сначала сам написать боту /start)")
        print(f"{'Отправлено' if ok else 'Ошибка'} в Telegram {chat_id}: {path.name}")
    log("telegram", chat_id, files)


def cmd_email(to, subject, *files):
    files = [f for f in files if f != "--new"]
    known = {r.get("email", "").lower() for r in book()}
    if to.lower() not in known and "--new" not in sys.argv:
        sys.exit(f"Адреса {to} нет в адресной книге. Нужно явное «да» владельца (флаг --new).")
    if not SMTP.exists():
        sys.exit(f"Нет настроек почты {SMTP} — сначала настрой ящик бота.")
    host, port, login, password = SMTP.read_text(encoding="utf-8").splitlines()[:4]
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = login, to, subject
    msg.set_content(f"Здравствуйте!\n\nВо вложении: {', '.join(Path(f).name for f in files)}.\n\n{FOOTER}\n")
    for f in files:
        path = Path(f).expanduser()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        main, sub = ctype.split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=main, subtype=sub, filename=path.name)
    with smtplib.SMTP_SSL(host, int(port), timeout=60) as s:
        s.login(login, password)
        s.send_message(msg)
    log("email", to, files)
    print(f"Письмо отправлено: {to} · вложений {len(files)}")


def cmd_book():
    rows = book()
    if not rows:
        print("Адресная книга пуста (recipients.csv: имя;email;telegram_id).")
    for i, r in enumerate(rows, 1):
        print(f"{i} — {r.get('имя')} · {r.get('email') or '—'} · Telegram {r.get('telegram_id') or '—'}")


if __name__ == "__main__":
    cmds = {"convert": cmd_convert, "tg": cmd_tg, "email": cmd_email, "book": cmd_book}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]](*sys.argv[2:])
