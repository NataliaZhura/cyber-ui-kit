#!/usr/bin/env python3
"""Рассылка готовой справки подписчикам без модели: модель пишет справку один раз, программа рассылает всем.

  python3 relay.py daily      утренняя справка: out/daily_ГГГГ-ММ-ДД.md → подписчикам «daily»
  python3 relay.py signal     дневные сигналы:  out/signal_ГГГГ-ММ-ДД_ЧЧММ.md → подписчикам «signal»
  python3 relay.py list       кто подписан

Файлы в out/ пишет Ави (правило в AGENTS.md: готовый текст сообщения — дословно в файл).
Подписчики — relay.csv (только на сервере, в репозиторий не кладётся; меняет только владелец):
  имя;telegram_id;что          что — daily, signal или daily+signal
Каждый файл уходит каждому один раз (отметки — out/relay_sent.json). Отправки пишутся в saved/sent.log.
Подписчик должен хотя бы раз сам написать боту /start, иначе Telegram не примет сообщение.
"""
import csv
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "out"
SUBS = BASE / "relay.csv"
SENT = OUT / "relay_sent.json"
MSK = timezone(timedelta(hours=3))
PART = 3500  # Telegram принимает до 4096 знаков; оставляем запас на разметку


def subscribers(kind):
    if not SUBS.exists():
        sys.exit(f"Нет {SUBS.name} — подписчиков нет (формат: имя;telegram_id;daily+signal)")
    with SUBS.open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.reader(f, delimiter=";") if r and not r[0].startswith("#") and len(r) >= 3]
    return [(r[0].strip(), r[1].strip()) for r in rows
            if r[1].strip().isdigit() and kind in r[2].replace(" ", "").split("+")]


def to_html(md):
    """Разметка Ави (жирный, ссылки словом, код, заголовки) → HTML, который понимает Telegram."""
    t = html.escape(md, quote=False)
    # адрес уже экранирован строкой выше (& → &amp;) — повторно не экранируем, только кавычку
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{m[2].replace(chr(34), "&quot;")}">{m[1]}</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    return re.sub(r"(?m)^#{1,6}\s*(.+)$", r"<b>\1</b>", t)


def parts(text):
    """Режем по абзацам, чтобы не разорвать разметку посреди строки."""
    out, cur = [], ""
    for para in text.split("\n\n"):
        if cur and len(cur) + len(para) + 2 > PART:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
        while len(cur) > PART:  # один огромный абзац — режем по строкам
            cut = cur.rfind("\n", 0, PART)
            cut = cut if cut > 0 else PART
            out.append(cur[:cut])
            cur = cur[cut:].lstrip("\n")
    return out + ([cur] if cur.strip() else [])


def send(tok, chat_id, text):
    for chunk in parts(text):
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": to_html(chunk), "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=60) as r:
                if not json.loads(r.read().decode()).get("ok"):
                    return False
        except urllib.error.HTTPError as e:
            print(f"  Telegram не принял: {e.read(200).decode('utf-8', 'replace')}", file=sys.stderr)
            return False
    return True


def cmd_relay(kind):
    subs = subscribers(kind)
    today = datetime.now(MSK).strftime("%Y-%m-%d")
    files = sorted(OUT.glob(f"{kind}_{today}*.md"))
    sent = json.loads(SENT.read_text(encoding="utf-8")) if SENT.exists() else {}
    todo = [(f, name, cid) for f in files for name, cid in subs if cid not in sent.get(f.name, [])]
    if not todo:
        print(f"Нечего рассылать ({kind}: файлов за сегодня {len(files)}, подписчиков {len(subs)})")
        return
    sys.path.insert(0, str(BASE))
    import share  # токен бота — тем же способом, что и для меню; на экран не выводится
    tok = share.tg_token()
    for f, name, cid in todo:
        text = f.read_text(encoding="utf-8").strip()
        if text and send(tok, cid, text):
            sent.setdefault(f.name, []).append(cid)
            SENT.write_text(json.dumps(sent, ensure_ascii=False, indent=1), encoding="utf-8")
            share.log("telegram-relay", cid, [str(f)])
            print(f"Отправлено {name}: {f.name}")
        else:
            print(f"Не отправлено {name}: {f.name}", file=sys.stderr)


def cmd_list():
    for kind in ("daily", "signal"):
        print(f"{kind}: " + (", ".join(f"{n} ({c})" for n, c in subscribers(kind)) or "—"))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("daily", "signal"):
        cmd_relay(arg)
    elif arg == "list":
        cmd_list()
    else:
        print(__doc__)
        sys.exit(1)
