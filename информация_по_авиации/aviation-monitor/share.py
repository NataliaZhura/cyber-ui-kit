#!/usr/bin/env python3
"""Справка → PDF и Word → в чат, на почту или в Telegram другому человеку.

  ~/pw/bin/python share.py save saved/2026-10-14_ГазпромАвиа.md        Word + PDF и оба файла владельцу в чат
  ~/pw/bin/python share.py convert saved/2026-10-14_ГазпромАвиа.md     → .docx и .pdf рядом с файлом
  ~/pw/bin/python share.py report saved/2026-10-14_ГазпромАвиа.md owner  справка по компании: только PDF → в чат
                                                                          (owner или Telegram ID)
  Разметка для красивого PDF (в .md): {{класс:B}} — цветная плашка класса; блок ```cards``` — карточки цифр
  (строки «Выручка | 905 млрд ₽ | +11%»); блок ```chart``` — графики (строки «Выручка, млрд ₽ | 2024: 812 | 2025: 905»).
  python3 share.py tg <telegram_id> <файл> [<файл> …]                    файлы в Telegram (себе или получателю)
  python3 share.py email <адрес> "<тема>" <файл> [<файл> …] [--new]      письмо с вложениями
  python3 share.py book                                                   адресная книга
  python3 share.py copy <файл.md>                                         текст файла владельцу сообщением (копия)

Адресная книга — recipients.csv (имя;email;telegram_id). Адрес не из книги — только с флагом --new, который агент
ставит после явного «да» владельца. Каждая отправка пишется в saved/sent.log.
Почта бота — ~/.secrets/smtp (4 строки: сервер, порт, логин, пароль приложения). Пароль не печатается.
"""
import csv
import html as html_lib
import json
import mimetypes
import os
import re
import smtplib
import subprocess
import sys
import urllib.parse
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
CSS = """body{font-family:'DejaVu Sans',Arial,sans-serif;font-size:10.5pt;line-height:1.45;margin:0!important;
max-width:none!important;padding:0!important;color:#1d2433}
h1{font-size:19pt;margin:0 0 4pt;color:#0b2a4a}h2{font-size:12.5pt;margin:16pt 0 6pt;color:#0b2a4a;
border-bottom:2px solid #d6e2f0;padding-bottom:3pt}h3{font-size:11pt;margin:10pt 0 4pt}
table{border-collapse:collapse;margin:6pt 0;width:100%}td,th{border-bottom:1px solid #dde3ea;padding:4pt 6pt;
font-size:9.5pt;text-align:left}th{background:#eef3f8;color:#0b2a4a}tr:nth-child(even) td{background:#fafbfc}
pre,code{font-family:'DejaVu Sans Mono',monospace;font-size:9pt}pre{background:#f4f6f8;padding:6pt;border-radius:4pt}
a{color:#0b62c4;text-decoration:none;font-weight:bold}blockquote{margin:6pt 0;padding:4pt 10pt;border-left:3px solid #0b62c4;
background:#f2f7fd}.foot{margin-top:18pt;font-size:8.5pt;color:#667}
.badge{display:inline-block;padding:3pt 12pt;border-radius:12pt;color:#fff;font-weight:bold;font-size:12pt}
.cA{background:#1e8e3e}.cB{background:#7cb342}.cC{background:#f9a825}.cD{background:#ef6c00}.cE{background:#c62828}
.cards{display:flex;flex-wrap:wrap;gap:8pt;margin:8pt 0}.card{flex:1 1 28%;break-inside:avoid;border:1px solid #dde3ea;border-radius:6pt;
padding:6pt 9pt;background:#f8fafc}.card .k{font-size:8.5pt;color:#556}.card .v{font-size:14pt;font-weight:bold;color:#0b2a4a}
.card .d{font-size:9pt;color:#556}.warn{color:#c62828}
.charts{display:flex;flex-wrap:wrap;gap:10pt;margin:8pt 0}.chart{flex:1 1 40%;break-inside:avoid;border:1px solid #dde3ea;border-radius:6pt;
padding:6pt}.chart .t{font-size:9pt;font-weight:bold;color:#0b2a4a;margin-bottom:2pt}"""


def log(kind, to, files):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M}\t{kind}\t{to}\t{', '.join(Path(x).name for x in files)}\n")


def book():
    if not BOOK.exists():
        return []
    with BOOK.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f, delimiter=";")]



def _num(s):
    s = s.replace("\u2212", "-").replace(" ", "").replace("\xa0", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _svg(title, pairs):
    """Столбики по годам; отрицательные — красным вниз от нуля."""
    vals = [v for _, v in pairs if v is not None]
    if not vals:
        return ""
    w, h, top, bottom = 300, 160, 18, 34
    hi, lo = max(max(vals), 0), min(min(vals), 0)
    span = (hi - lo) or 1
    zero = top + (h - top - bottom) * hi / span
    bw = min(60, (w - 20) / len(pairs) - 14)
    out = [f'<svg width="100%" viewBox="0 0 {w} {h}">',
           f'<line x1="6" x2="{w - 6}" y1="{zero:.1f}" y2="{zero:.1f}" stroke="#99a" stroke-width="1"/>']
    for i, (label, v) in enumerate(pairs):
        x = 16 + i * (bw + 14)
        if v is None:
            continue
        bh = (h - top - bottom) * abs(v) / span
        y = zero - bh if v >= 0 else zero
        col = "#0b62c4" if v >= 0 else "#c62828"
        txt = f"{v:,.1f}".replace(",", " ").replace(".", ",").replace(",0", "")
        ty = y - 4 if v >= 0 else y + bh + 11
        out += [f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(bh, 1):.1f}" rx="3" fill="{col}"/>',
                f'<text x="{x + bw / 2:.1f}" y="{ty:.1f}" font-size="10" text-anchor="middle" fill="#1d2433">{html_lib.escape(txt)}</text>',
                f'<text x="{x + bw / 2:.1f}" y="{h - 6}" font-size="10" text-anchor="middle" fill="#556">{html_lib.escape(label)}</text>']
    out.append("</svg>")
    return f'<div class="chart"><div class="t">{html_lib.escape(title)}</div>{"".join(out)}</div>'


def _rich(md):
    """Разметка Ави → HTML-вставки: плашка класса, карточки цифр, графики."""
    def badge(m):
        c = m.group(1).upper().translate(str.maketrans("АВСЕ", "ABCE"))
        return f'<span class="badge c{c}">Класс {c}</span>'
    md = re.sub(r"\{\{\s*класс\s*:\s*([A-EА-Еa-e])\s*\}\}", badge, md, flags=re.I)

    def cards(m):
        items = []
        for line in m.group(1).strip().splitlines():
            parts = [x.strip() for x in line.split("|")]
            if len(parts) < 2:
                continue
            d = parts[2] if len(parts) > 2 else ""
            cls = "warn" if d.strip().startswith("⚠") else ""  # красным — только то, что Ави пометил как риск
            items.append(f'<div class="card"><div class="k">{html_lib.escape(parts[0])}</div>'
                         f'<div class="v">{html_lib.escape(parts[1])}</div><div class="d {cls}">{html_lib.escape(d)}</div></div>')
        return '\n<div class="cards">' + "".join(items) + "</div>\n"
    md = re.sub(r"```cards\s*\n(.*?)```", cards, md, flags=re.S)

    def charts(m):
        out = []
        for line in m.group(1).strip().splitlines():
            parts = [x.strip() for x in line.split("|")]
            pairs = []
            for p in parts[1:]:
                if ":" in p:
                    k, v = p.split(":", 1)
                    pairs.append((k.strip(), _num(v)))
            if pairs:
                out.append(_svg(parts[0], pairs))
        return '\n<div class="charts">' + "".join(out) + "</div>\n"
    return re.sub(r"```chart\s*\n(.*?)```", charts, md, flags=re.S)


def _pdf(html, pdf, title):
    from playwright.sync_api import sync_playwright
    foot = (f'<div style="font-size:7pt;color:#778;width:100%;padding:0 14mm;display:flex;justify-content:space-between">'
            f'<span>{html_lib.escape(FOOTER)}</span><span><span class="pageNumber"></span>/<span class="totalPages"></span></span></div>')
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
                              executable_path=os.environ.get("PW_CHROMIUM") or None)
        pg = b.new_page()
        pg.goto(html.as_uri())
        pg.pdf(path=str(pdf), format="A4", print_background=True, display_header_footer=True,
               header_template="<span></span>", footer_template=foot,
               margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        b.close()


def cmd_report(src, to="owner"):
    """Справка по компании → только PDF (с плашкой класса, карточками и графиками) → в Telegram."""
    src = Path(src).expanduser().resolve()
    pdf, html = src.with_suffix(".pdf"), src.with_suffix(".html")
    tmp = src.with_name(src.stem + "_tmp.md")
    tmp.write_text(_rich(src.read_text(encoding="utf-8")), encoding="utf-8")
    try:
        subprocess.run(["pandoc", str(tmp), "-f", "markdown+raw_html", "-s", "--metadata", f"pagetitle={src.stem}",
                        "-o", str(html)], check=True)
    except FileNotFoundError:
        sys.exit("Нет pandoc: установи командой  apt install -y pandoc fonts-dejavu")
    finally:
        tmp.unlink(missing_ok=True)
    html.write_text(html.read_text(encoding="utf-8").replace("</head>", f"<style>{CSS}</style></head>"), encoding="utf-8")
    _pdf(html, pdf, src.stem)
    html.unlink(missing_ok=True)
    print(f"PDF: {pdf}")
    cmd_tg(to, str(pdf))


def cmd_convert(src):
    """Markdown → Word (pandoc) и PDF (pandoc → HTML → Chromium). Без pandoc — понятная ошибка, а не пустой файл."""
    src = Path(src).expanduser().resolve()
    docx, pdf, html = src.with_suffix(".docx"), src.with_suffix(".pdf"), src.with_suffix(".html")
    md = _rich(src.read_text(encoding="utf-8"))
    tmp = src.with_name(src.stem + "_tmp.md")
    tmp.write_text(md, encoding="utf-8")
    try:
        subprocess.run(["pandoc", str(tmp), "-o", str(docx)], check=True)
        subprocess.run(["pandoc", str(tmp), "-f", "markdown+raw_html", "-s", "--metadata", f"pagetitle={src.stem}",
                        "-o", str(html)], check=True)
    except FileNotFoundError:
        sys.exit("Нет pandoc: установи командой  apt install -y pandoc fonts-dejavu")
    finally:
        tmp.unlink(missing_ok=True)
    page = html.read_text(encoding="utf-8").replace("</head>", f"<style>{CSS}</style></head>")
    html.write_text(page, encoding="utf-8")
    _pdf(html, pdf, src.stem)
    html.unlink(missing_ok=True)
    print(f"Готово:\n  {docx}\n  {pdf}")


def tg_token():
    sys.path.insert(0, str(BASE))
    import menu  # тот же способ, что и для меню: токен из файла OpenClaw, на экран не выводится
    return menu.token()


def owner_id():
    """Telegram ID владельца — первый из разрешённых в настройке OpenClaw channels.telegram.allowFrom."""
    out = subprocess.run(["openclaw", "config", "get", "channels.telegram.allowFrom"],
                         capture_output=True, text=True, timeout=60).stdout
    start = out.find("[")
    ids = json.loads(out[start:out.rfind("]") + 1]) if start >= 0 else []
    if not ids:
        sys.exit("Не нашёл Telegram ID владельца в channels.telegram.allowFrom")
    return str(ids[0]).replace("tg:", "").replace("telegram:", "")


def cmd_tg(chat_id, *files):
    if chat_id == "owner":
        chat_id = owner_id()
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


def cmd_copy(src):
    """Копия текста владельцу обычным сообщением (части по 3500 знаков). Получатель зашит — только владелец."""
    path = Path(src).expanduser()
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        sys.exit(f"Пустой файл: {path}")
    tok, chat_id = tg_token(), owner_id()
    parts = [text[i:i + 3500] for i in range(0, len(text), 3500)]
    for n, part in enumerate(parts, 1):
        head = f"[копия {n}/{len(parts)}]\n" if len(parts) > 1 else ""
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": head + part,
                                       "disable_web_page_preview": "true"}).encode()
        with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=60) as r:
            ok = json.loads(r.read().decode()).get("ok")
        if not ok:
            sys.exit("Telegram не принял копию")
    print(f"Копия отправлена владельцу: {path.name} ({len(parts)} сообщ.)")
    log("telegram-copy", chat_id, [str(path)])


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


def cmd_save(src):
    """Одной командой: .md → Word и PDF → оба файла владельцу в чат вложениями."""
    src = Path(src).expanduser().resolve()
    cmd_convert(src)
    cmd_tg("owner", str(src.with_suffix(".pdf")), str(src.with_suffix(".docx")))
    print(f"Сохранено: {src.with_suffix('')} (.md, .docx, .pdf)")


def cmd_book():
    rows = book()
    if not rows:
        print("Адресная книга пуста (recipients.csv: имя;email;telegram_id).")
    for i, r in enumerate(rows, 1):
        print(f"{i} — {r.get('имя')} · {r.get('email') or '—'} · Telegram {r.get('telegram_id') or '—'}")


if __name__ == "__main__":
    cmds = {"save": cmd_save, "convert": cmd_convert, "tg": cmd_tg, "report": cmd_report, "copy": cmd_copy, "email": cmd_email, "book": cmd_book}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]](*sys.argv[2:])
