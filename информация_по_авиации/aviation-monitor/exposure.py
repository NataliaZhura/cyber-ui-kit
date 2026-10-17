#!/usr/bin/env python3
"""Карта влияния беспилотников: какие виды работ и заказчики у каждой компании рабочего списка.

  python3 exposure.py draft              черновик по focus.csv: сайты (sites/<ИНН>) + архив новостей за год → exposure_draft.csv
  python3 exposure.py show               черновик и подтверждённое — коротко, с доказательствами (для владельца)
  python3 exposure.py set <ИНН> "<виды работ через запятую>" ["<заказчики через запятую>"]
                                         подтвердить строку → exposure.csv (его читает сборщик новостей)

Виды работ: облёт ЛЭП, облёт трубопроводов, аэрофотосъёмка, авиахимработы, лесоохрана, перевозки, санавиация,
грузы и подвеска. Черновик — только подсказка по словам в текстах; в exposure.csv попадает лишь то, что подтвердил
владелец (виды работ нельзя угадывать: ошибка исказит оценку риска). Модель не используется.
"""
import csv
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
FOCUS, DRAFT, FINAL = BASE / "focus.csv", BASE / "exposure_draft.csv", BASE / "exposure.csv"

# вид работ → (слова в тексте, риск замещения беспилотниками — по опорной справке guides/bpla-market.md, раздел 5)
WORK = {
    "облёт ЛЭП": (["лэп", "линий электропередач", "линии электропередач", "электросет", "россети", "энергообъект"], "высокий"),
    "облёт трубопроводов": (["трубопровод", "нефтепровод", "газопровод", "транснефть"], "высокий"),
    "аэрофотосъёмка": (["аэрофотосъем", "аэрофотосъём", "картограф", "кадастр", "геодези"], "высокий"),
    "авиахимработы": (["авиахим", "авиационно-химическ", "опрыскив", "агродрон", "сельхозработ"], "средний"),
    "лесоохрана": (["лесоохран", "лесных пожар", "лесного пожар", "лесные пожар", "авиалесоохран"], "средний"),
    "перевозки": (["пассажир", "вахт", "регулярные рейс", "чартер"], "нет"),
    "санавиация": (["санавиац", "санитарн авиац", "медицинск эвакуац", "санитарного задан"], "нет"),
    "грузы и подвеска": (["внешн подвеск", "внешней подвеск", "монтаж", "грузоперевоз", "перевозк груз"], "нет"),
}
CUSTOMERS = ["Газпром", "Роснефть", "Транснефть", "Лукойл", "Новатэк", "Сургутнефтегаз", "Россети", "РусГидро",
             "Росатом", "Норникель", "МЧС", "Авиалесоохрана", "Минздрав", "Росгвардия", "Полюс", "Алроса"]
FIELDS = ["компания", "инн", "виды_работ", "заказчики", "статус", "доказательства"]


def read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def texts(name, inn):
    """(источник, текст): страницы сайта компании и новости о ней за год из архива."""
    pages = BASE / "sites" / inn / "pages.json"
    if pages.exists():
        for p in json.loads(pages.read_text(encoding="utf-8")):
            if p.get("text"):
                yield f"сайт: {p.get('section', '')}", p["text"]
    db = BASE / "archive.db"
    if db.exists():
        since = (datetime.now() - timedelta(days=365)).date().isoformat()
        con = sqlite3.connect(db)
        for title, summ, url in con.execute(
                "SELECT title, summary, url FROM news WHERE published >= ? AND (entities LIKE ? OR title LIKE ?)",
                (since, f"%{name}%", f"%{name}%")):
            yield f"новость: {url}", f"{title}. {summ or ''}"


def cmd_draft():
    comps = read(FOCUS)
    if not comps:
        sys.exit("Нет focus.csv — сначала рабочий список из 11 компаний.")
    out = []
    for c in comps:
        name, inn = (c.get("компания") or "").strip(), (c.get("инн") or "").strip()
        hits, cust, proof = {}, {}, {}
        for src, t in texts(name, inn):
            low = t.lower()
            for work, (words, _) in WORK.items():
                n = sum(low.count(w) for w in words)
                if n:
                    hits[work] = hits.get(work, 0) + n
                    if work not in proof:
                        w = next(x for x in words if x in low)
                        i = low.index(w)
                        proof[work] = f"{src}: «…{t[max(0, i - 60):i + 80].strip()}…»"
            for cu in CUSTOMERS:
                if cu.lower() in low and cu.lower() not in name.lower():
                    cust[cu] = cust.get(cu, 0) + 1
        works = sorted(hits, key=hits.get, reverse=True)
        out.append({"компания": name, "инн": inn,
                    "виды_работ": ", ".join(f"{w} ({hits[w]})" for w in works),
                    "заказчики": ", ".join(f"{k} ({v})" for k, v in sorted(cust.items(), key=lambda x: -x[1])[:6]),
                    "статус": "черновик" if works else "нет данных — спросить владельца",
                    "доказательства": " | ".join(proof[w] for w in works[:4])})
    write(DRAFT, out)
    print(f"Черновик: {DRAFT.name}, компаний {len(out)}, с найденными видами работ: "
          f"{sum(1 for o in out if o['виды_работ'])}. Посмотреть: python3 exposure.py show")


def cmd_show():
    final = {r["инн"]: r for r in read(FINAL)}
    for i, r in enumerate(read(DRAFT), 1):
        f = final.get(r["инн"])
        print(f"{i}. {r['компания']} (ИНН {r['инн']})" + (" — ✅ подтверждено" if f else ""))
        if f:
            print(f"   работы: {f['виды_работ']}\n   заказчики: {f['заказчики'] or '—'}")
            continue
        print(f"   по текстам: {r['виды_работ'] or '—'}\n   заказчики в текстах: {r['заказчики'] or '—'}")
        for p in (r["доказательства"] or "").split(" | ")[:3]:
            if p:
                print(f"   · {p[:220]}")


def cmd_set(inn, works, customers=""):
    bad = [w.strip() for w in works.split(",") if w.strip() and w.strip() not in WORK]
    if bad:
        sys.exit(f"Неизвестные виды работ: {', '.join(bad)}. Допустимые: {', '.join(WORK)}")
    name = next((r["компания"] for r in read(DRAFT) + read(FOCUS) if r.get("инн") == inn), "")
    if not name:
        sys.exit(f"ИНН {inn} нет в focus.csv")
    rows = [r for r in read(FINAL) if r["инн"] != inn]
    rows.append({"компания": name, "инн": inn, "виды_работ": ", ".join(w.strip() for w in works.split(",") if w.strip()),
                 "заказчики": customers, "статус": f"подтверждено {datetime.now():%d.%m.%Y}", "доказательства": ""})
    write(FINAL, rows)
    print(f"Подтверждено: {name} — {works}" + (f"; заказчики: {customers}" if customers else ""))


def load():
    """Подтверждённая карта для сборщика: [(компания, {виды}, [заказчики])]."""
    return [(r["компания"], {w.strip() for w in r["виды_работ"].split(",") if w.strip()},
             [c.strip() for c in (r.get("заказчики") or "").split(",") if c.strip()]) for r in read(FINAL)]


def impact(text, cmap):
    """Новость о беспилотниках → кого из компаний она задевает: «ПАНХ — авиахимработы (риск средний)»."""
    low = text.lower()
    found = [w for w, (words, risk) in WORK.items() if risk != "нет" and any(x in low for x in words)]
    out = []
    for name, works, customers in cmap:
        why = [f"{w} (риск {WORK[w][1]})" for w in found if w in works]
        why += [f"заказчик {c}" for c in customers if c.lower() in low]
        if why:
            out.append(f"{name} — {', '.join(why)}")
    return out


if __name__ == "__main__":
    cmds = {"draft": cmd_draft, "show": cmd_show, "set": cmd_set}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]](*sys.argv[2:])
