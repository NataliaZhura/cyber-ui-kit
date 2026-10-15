#!/usr/bin/env python3
"""Выпуски Argus «Логистика сухих грузов» → сжатые данные для ЖДуши (без самих PDF в ответах).

  ~/pw/bin/python argus.py            разобрать все PDF из private/argus/
  ~/pw/bin/python argus.py show       последние ставки по полувагонам и крытым (кратко)

Результат (всё в private/argus/, в репозиторий не попадает):
  rates.csv          выпуск;страница;таблица;показатель;мин;макс;прошлый_мин;прошлый_макс (руб., без НДС, как в выпуске)
  digest/<дата>.txt  только страницы о подвижном составе (ставки, комментарии рынка), без моря, Казахстана и прочего
Повторный запуск пересобирает всё заново; PDF не меняются.
"""
import csv
import logging
import re
import sys
from pathlib import Path

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)
DIR = Path(__file__).resolve().parent / "private" / "argus"
MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
          "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
NUM = r"\d{1,3}(?: \d{3})+|\d+"
ROW = re.compile(rf"^(?P<name>\D.*?)\s+(?P<a>{NUM})\s*[—–-]\s*(?P<b>{NUM})\s+(?P<c>{NUM})\s*[—–-]\s*(?P<d>{NUM})\s*$")
RAIL = ("ПОДВИЖНОЙ СОСТАВ", "ПОЛУВАГОН", "КРЫТ")
SKIP_TABLES = ("Казахстан", "$")


def issue_date(text):
    m = re.search(r"Логистика сухих грузов\s+(\d{1,2})\s+([а-я]+)\s+(\d{4})", text)
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}" if m and m.group(2) in MONTHS else None


def n(s):
    return int(s.replace(" ", ""))


def parse(pdf_path):
    rows, digest, date = [], [], None
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            page.flush_cache()
            date = date or issue_date(text)
            head = "\n".join(text.splitlines()[:3]).upper()
            if not any(k in head for k in RAIL) or "КАЗАХСТАН" in head:  # Россия only
                continue
            body = [l for l in text.splitlines() if not l.startswith(("Все права защищены", "Лицензия зарегистрирована"))]
            digest.append(f"--- стр. {i}\n" + "\n".join(body))
            table = None
            for line in body:
                if re.match(r"^(Ставк|Стоимост)", line) and ("руб." in line or "$" in line):
                    table = line.strip()
                    continue
                m = ROW.match(line.strip())
                if m and table and not any(s in table for s in SKIP_TABLES):
                    rows.append([date, i, table, m["name"].strip(), n(m["a"]), n(m["b"]), n(m["c"]), n(m["d"])])
    return date, rows, digest


def cmd_build():
    pdfs = sorted(DIR.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"В {DIR} нет PDF — сначала загрузи выпуски Argus.")
    (DIR / "digest").mkdir(exist_ok=True)
    allrows = []
    for p in pdfs:
        date, rows, digest = parse(p)
        if not date:
            print(f"· {p.name}: не похоже на выпуск Argus — пропущен")
            continue
        (DIR / "digest" / f"{date}.txt").write_text(f"Argus «Логистика сухих грузов», выпуск от {date}\n\n" + "\n\n".join(digest),
                                                    encoding="utf-8")
        allrows += rows
        print(f"✓ {date}: строк ставок {len(rows)}, страниц о подвижном составе {len(digest)}  ({p.name})")
    allrows.sort(key=lambda r: (r[0], r[1]))
    with open(DIR / "rates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["выпуск", "страница", "таблица", "показатель", "мин", "макс", "прошлый_мин", "прошлый_макс"])
        w.writerows(allrows)
    print(f"Готово: {DIR / 'rates.csv'} ({len(allrows)} строк), выжимки — {DIR / 'digest'}")


def cmd_show():
    with open(DIR / "rates.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    last = max(r["выпуск"] for r in rows)
    print(f"Argus, выпуск от {last} (руб., без НДС):")
    for r in rows:
        if r["выпуск"] == last and any(k in r["показатель"] for k in ("Полувагон", "Крыт", "Кузбасс")):
            t = r["таблица"].lower()
            kind = "оперирование" if "оперирован" in t else "тех. рейс, руб./ваг" if "рейс" in t else "аренда, руб./сут"
            print(f"  [{kind}] {r['показатель']}: {r['мин']}–{r['макс']} (было {r['прошлый_мин']}–{r['прошлый_макс']})")


if __name__ == "__main__":
    {"show": cmd_show}.get(sys.argv[1] if len(sys.argv) > 1 else "", cmd_build)()
