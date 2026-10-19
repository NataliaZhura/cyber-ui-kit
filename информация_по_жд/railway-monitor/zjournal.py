#!/usr/bin/env python3
"""Журнал прогнозов: каждый прогноз записывается, потом сверяется с фактом — так видно, насколько бот точен.
Без нейросети (0 токенов). Файл — saved/journal.csv (только на сервере).

  python3 zjournal.py add --what "Погрузка РЖД, неделя" --type gon --due 2026-10-26 --dir down [--value 23.1 --unit "млн т"]
  python3 zjournal.py due                      прогнозы, срок которых прошёл, а факта нет (сверить в понедельник)
  python3 zjournal.py fact 12 --dir down [--value 22.8] [--src "РЖД, 02.11"]
  python3 zjournal.py score                    точность по показателям: угадано направление, средняя ошибка в %

Направление: up — рост, down — снижение, flat — без изменений (в пределах ±1%).
"""
import argparse
import csv
from datetime import date
from pathlib import Path

FILE = Path(__file__).resolve().parent / "saved" / "journal.csv"
COLS = ["id", "сделан", "показатель", "тип", "срок", "направление", "прогноз", "единица",
        "факт_направление", "факт", "сверен", "источник_факта"]
DIRS = {"up": "рост", "down": "снижение", "flat": "без изменений"}


def load():
    if not FILE.exists():
        return []
    with FILE.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def save(rows):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, delimiter=";")
        w.writeheader()
        w.writerows(rows)


def num(s):
    try:
        return float(str(s).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def stats(rows):
    """По показателю: сверено, угадано направление, средняя ошибка значения в %."""
    by = {}
    for r in rows:
        if not r["сверен"]:
            continue
        s = by.setdefault(r["показатель"], {"n": 0, "hit": 0, "err": []})
        s["n"] += 1
        s["hit"] += r["направление"] == r["факт_направление"]
        p, f = num(r["прогноз"]), num(r["факт"])
        if p is not None and f:
            s["err"].append(abs(p / f - 1) * 100)
    return by


def summary():
    """Блок для сводки рынка."""
    rows = load()
    if not rows:
        return ["Журнал пуст: прогнозы начнут записываться с ближайшего пятничного прогноза.", ""]
    by = stats(rows)
    late = [r for r in rows if not r["сверен"] and r["срок"] < date.today().isoformat()]
    L = ["| Показатель | Сверено | Направление угадано | Средняя ошибка |", "|---|---|---|---|"]
    for k, s in sorted(by.items(), key=lambda x: -x[1]["n"]):
        err = f"{sum(s['err']) / len(s['err']):.1f}%" if s["err"] else "—"
        L.append(f"| {k} | {s['n']} | {s['hit']} из {s['n']} ({s['hit'] / s['n'] * 100:.0f}%) | {err} |")
    if not by:
        L = ["Сверенных прогнозов пока нет."]
    L += ["", f"Ждут сверки с фактом: {len(late)}" + (" — `python3 zjournal.py due`." if late else "."), ""]
    return L


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--what", required=True)
    a.add_argument("--type", default="", help="gon / kr / пусто")
    a.add_argument("--due", required=True, help="ГГГГ-ММ-ДД — к какой дате прогноз")
    a.add_argument("--dir", required=True, choices=list(DIRS))
    a.add_argument("--value", default="")
    a.add_argument("--unit", default="")
    f = sub.add_parser("fact")
    f.add_argument("id")
    f.add_argument("--dir", required=True, choices=list(DIRS))
    f.add_argument("--value", default="")
    f.add_argument("--src", default="")
    sub.add_parser("due")
    sub.add_parser("score")
    x = ap.parse_args()
    rows = load()
    if x.cmd == "add":
        nid = str(max((int(r["id"]) for r in rows), default=0) + 1)
        rows.append({"id": nid, "сделан": date.today().isoformat(), "показатель": x.what, "тип": x.type, "срок": x.due,
                     "направление": x.dir, "прогноз": x.value, "единица": x.unit, "факт_направление": "", "факт": "",
                     "сверен": "", "источник_факта": ""})
        save(rows)
        print(f"Записан прогноз №{nid}: {x.what} к {x.due} — {DIRS[x.dir]} {x.value} {x.unit}".rstrip())
    elif x.cmd == "fact":
        r = next((r for r in rows if r["id"] == x.id), None)
        if not r:
            raise SystemExit(f"Нет прогноза №{x.id}")
        r.update({"факт_направление": x.dir, "факт": x.value, "сверен": date.today().isoformat(), "источник_факта": x.src})
        save(rows)
        print(f"№{x.id} {r['показатель']}: прогноз {DIRS[r['направление']]} {r['прогноз']}, факт {DIRS[x.dir]} {x.value} — "
              + ("угадано" if r["направление"] == x.dir else "не угадано"))
    elif x.cmd == "due":
        late = [r for r in rows if not r["сверен"] and r["срок"] <= date.today().isoformat()]
        for r in late:
            print(f"№{r['id']} · {r['показатель']} · срок {r['срок']} · прогноз: {DIRS[r['направление']]} {r['прогноз']} {r['единица']}")
        print(f"Ждут сверки: {len(late)}")
    else:
        print("\n".join(summary()))


if __name__ == "__main__":
    main()
