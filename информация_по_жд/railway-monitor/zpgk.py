#!/usr/bin/env python3
"""ПГК (крупнейший оператор) — наблюдение по открытым источникам и сверка с нашими ставками. 0 токенов.

  python3 zpgk.py scan [--days 180]     новости с упоминанием ПГК: ставки, парк, покупки вагонов, отчётность, рейтинг —
                                        и готовые строки `zobs.py add` для ставок с цифрой (записывает владелец)
  python3 zpgk.py compare               оценки ставок ПГК из СМИ против наших данных за тот же месяц: насколько расходятся
  python3 zpgk.py plan                  что и когда смотреть по ПГК (раз в месяц / полгода)

Только законные открытые каналы: СМИ, раскрытие эмитента, рейтинговые агентства, сайт компании. Регистрация клиентом
без намерения перевозить груз — не используется.
"""
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import zobs  # noqa: E402

DB = BASE / "archive.db"
MSK = timezone(timedelta(hours=3))
PGK = r"(пгк|первая грузовая|первой грузовой|первую грузовую)"
TOPIC = [("ставка", r"ставк\w*|руб\.?/сут|₽/сут|тыс\.? руб"), ("парк", r"парк\w*|вагон\w* в управлени"),
         ("покупка вагонов", r"закуп\w*|приобр\w*|купил\w*|поставк\w* вагон"), ("отчётность", r"мсфо|рсбу|выручк|ebitda|прибыл|убыт"),
         ("рейтинг и облигации", r"рейтинг|облигац|эксперт ра|нкр|акра")]
WAGON = [("gon75_spot", r"инновацион\w*"), ("gon69_spot", r"полуваг\w*"), ("kr158", r"крыт\w*"), ("hop_grain", r"зерновоз\w*"),
         ("fit80", r"платформ\w*|фитинг\w*")]
NUM = r"(\d[\d\s]{0,6}(?:[,.]\d+)?)\s*(тыс\.?\s*)?(?:руб|₽)\w*\.?\s*(?:/|в)\s*сут"


def scan(days):
    if not DB.exists():
        sys.exit(f"Нет {DB} — сначала: python3 collector.py collect")
    since = (datetime.now(MSK) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = sqlite3.connect(DB).execute("SELECT published, title, summary, url FROM news WHERE published >= ? ORDER BY published DESC",
                                       (since,)).fetchall()
    found, adds = [], []
    for pub, title, summ, url in rows:
        low = f"{title}. {summ or ''}".lower()
        if not re.search(PGK, low):
            continue
        tags = [nm for nm, rx in TOPIC if re.search(rx, low)]
        found.append((pub[:10], ", ".join(tags) or "прочее", title, url))
        for m in re.finditer(NUM, low):  # тип вагона — ближайшее слово перед числом (до 80 знаков)
            win = low[max(0, m.start() - 80):m.start()]
            hits = [(mm.end(), k) for k, rx in WAGON for mm in re.finditer(rx, win)]
            if not hits:
                continue
            w = max(hits)[1]
            if w == "gon69_spot" and re.search(r"инновацион\w*\s+\w*\s*полуваг", win[-60:]):
                w = "gon75_spot"  # «инновационный полувагон» — не типовой
            v = float(m.group(1).replace(" ", "").replace(",", ".")) * (1000 if m.group(2) else 1)
            if 200 <= v <= 10000:
                adds.append(f"python3 zobs.py add {pub[:7]} {w} {v:g} --source media --note \"оценка ПГК: {title[:60]} {url}\"")
    if not found:
        return print(f"За {days} дн. новостей о ПГК нет.")
    print(f"Новости о ПГК за {days} дн.: {len(found)}")
    for d, tg, ti, u in found[:30]:
        print(f"  {d[8:10]}.{d[5:7]} [{tg}] {ti[:100]} {u}")
    if adds:
        print("\nСтавки с цифрой — проверь и, если верно, запиши:")
        print("\n".join("  " + a for a in dict.fromkeys(adds)))


def compare():
    rows = zobs.read()
    ours = {(r["month"], r["item"]): (float(r["low"]) + float(r["high"])) / 2 for r in rows if r["source"] in ("partner", "survey")}
    lines = []
    for r in rows:
        if r["source"] == "media" and "ПГК" in r["note"] and r["item"] in zobs.ITEMS:
            v = (float(r["low"]) + float(r["high"])) / 2
            o = ours.get((r["month"], r["item"]))
            diff = f"{(o / v - 1) * 100:+.0f}%".replace("-", "−") if o else "нет наших данных"
            f0 = lambda x: f"{x:,.0f}".replace(",", " ")
            lines.append(f"| {r['month']} | {zobs.ITEMS[r['item']][1]} | {f0(v)} | {f0(o) if o else '—'} | {diff} |")
    if not lines:
        return print("Оценок ПГК в базе нет: python3 zobs.py seed или zpgk.py scan.")
    print("| Месяц | Ставка | Оценка ПГК, ₽/сут | Наши данные, ₽/сут | Наши к ПГК |\n|---|---|---|---|---|\n" + "\n".join(lines))
    print("\nРасхождение до ±15% — нормально (разные выборки: ПГК — свой портфель, у нас — середина диапазона рынка).")


PLAN = """Наблюдение за ПГК — что и когда:
  Ежедневно (автоматически, 0 токенов): сборщик новостей → «ПГК» в утренней сводке; zpgk.py scan — оценки ставок с цифрой.
  Ежемесячно: zpgk.py compare — оценки ПГК против наших ставок (сверка точности, «второй источник» вместо опроса).
  Раз в полгода: справка по компании (/profile ПГК: МСФО, РСБУ, долг, суды) — по COMPANY.md; рейтинги Эксперт РА и НКР —
    парк, долг, причины смены прогноза (готовые сигналы рынка).
  По событию: покупки вагонов ПГК (тип и количество — сигнал «докупать/не докупать»), новые выпуски облигаций.
Что переносим в модель: доход на вагон-сутки и долг/EBITDA как индикатор здоровья рынка; причины рейтинговых решений
  (избыток парка, погрузка, ставки оперирования) — уже в оповещениях; ремонт по износу — в расчёт сделки (когда будут цены
  ремонта). Законно и без «инкогнито»: ставки по направлениям — только через реальных клиентов с их согласия (анкета)."""


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if cmd == "scan":
        scan(int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 180)
    elif cmd == "compare":
        compare()
    else:
        print(PLAN)
