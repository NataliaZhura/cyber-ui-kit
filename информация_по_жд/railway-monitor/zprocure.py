#!/usr/bin/env python3
"""Закупки грузоотправителей «предоставление вагонов» — реальные цены операторов (в том числе ПГК) из открытых
протоколов (ЕИС, zakupki.gov.ru, 223-ФЗ и 44-ФЗ). Без нейросети (0 токенов).

  python3 zprocure.py probe                 доступна ли площадка с сервера и что она отдаёт (первый шаг)
  python3 zprocure.py search [--pages 2] [--days 365]
                                            поиск закупок по 4 типам вагонов → forecast/procure.csv (номер, заказчик,
                                            предмет, начальная цена, дата, ссылка); повтор не дублирует
  python3 zprocure.py show [--wagon gon]    что найдено
  python3 zprocure.py import <файл.html> …  страницы поиска, сохранённые в браузере (сайт закрыт для зарубежного
                                            сервера): «Мои загрузки» → раскладка zinbox.py вызывает это сама
  python3 zprocure.py dump <файл.html>      показать, что программа видит на странице

Это открытые сведения: закупки и протоколы публикуются по закону, для чтения регистрация не нужна. Цена победителя —
в протоколе подведения итогов (следующий шаг, после проверки формата). Файл procure.csv — только на сервере.
"""
import csv
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "forecast" / "procure.csv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SEARCH = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"
# Запросы по типам вагонов: (тип, строка поиска)
QUERIES = [("gon", "предоставление полувагонов"), ("gon", "услуги по предоставлению полувагонов"),
           ("kr", "предоставление крытых вагонов"), ("hop_grain", "предоставление вагонов-зерновозов"),
           ("hop_grain", "предоставление хопперов-зерновозов"), ("fit", "предоставление фитинговых платформ"),
           ("fit", "предоставление платформ для перевозки контейнеров"), ("any", "предоставление подвижного состава")]
COLS = ["number", "wagon", "query", "customer", "subject", "price", "currency", "published", "law", "url"]


def get(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9",
                                               "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def search_url(q, page, days):
    since = (date.today() - timedelta(days=days)).strftime("%d.%m.%Y")
    p = {"searchString": q, "morphology": "on", "fz44": "on", "fz223": "on", "pageNumber": page, "recordsPerPage": "_50",
         "sortBy": "UPDATE_DATE", "sortDirection": "false", "publishDateFrom": since, "af": "on", "ca": "on", "pc": "on", "pa": "on"}
    return SEARCH + "?" + urllib.parse.urlencode(p)


def clean(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def parse(page):
    """Карточки результатов поиска ЕИС. Разметка сайта меняется — разбор терпимый: что не нашлось, остаётся пустым."""
    out = []
    for block in re.split(r'class="search-registry-entry-block', page)[1:]:
        num = re.search(r"№\s*([0-9]{8,})", block)
        href = re.search(r'href="(/epz/order/notice/[^"]+?(?:regNumber|noticeInfoId)=[^"]+)"', block)
        subj = re.search(r'registry-entry__body-value">(.*?)</div>', block, re.S)
        cust = re.search(r'registry-entry__body-href">(.*?)</div>', block, re.S)
        price = re.search(r'price-block__value">(.*?)</div>', block, re.S)
        pub = re.search(r"Размещено</div>\s*<div[^>]*>([\d.]+)", block)
        law = re.search(r"(44-ФЗ|223-ФЗ)", block)
        pr = clean(price.group(1)) if price else ""
        out.append({"number": num.group(1) if num else "", "subject": clean(subj.group(1)) if subj else "",
                    "customer": clean(cust.group(1)) if cust else "",
                    "price": re.sub(r"[^\d,]", "", pr).replace(",", "."), "currency": "₽" if "₽" in pr else "",
                    "published": pub.group(1) if pub else "", "law": law.group(1) if law else "",
                    "url": "https://zakupki.gov.ru" + html.unescape(href.group(1)) if href else ""})
    return [x for x in out if x["number"]]


def cmd_probe():
    url = search_url(QUERIES[0][1], 1, 365)
    print(f"Запрос: {url[:160]}…")
    try:
        st, page = get(url)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Площадка недоступна с сервера: {type(e).__name__}: {str(e)[:200]}. Возможные причины: блокировка "
                 "иностранных или серверных адресов, сайт требует браузер. Дальше — вариант «сохранить страницу» (dump).")
    rows = parse(page)
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    print(f"Ответ: код {st}, {len(page):,} знаков, заголовок «{clean(title.group(1)) if title else '—'}»".replace(",", " "))
    print(f"Карточек закупок разобрано: {len(rows)}")
    for x in rows[:5]:
        print(f"  {x['number']} | {x['published']} | {x['law']} | {x['price']} {x['currency']} | {x['customer'][:50]} | {x['subject'][:80]}")
    if not rows:
        Path(BASE / "saved" / ".procure_probe.html").write_text(page, encoding="utf-8")
        print("Карточки не распознаны — страница сохранена в saved/.procure_probe.html: пришли первые строки команды\n"
              "  grep -o 'class=\"[a-z-]*registry[a-z_-]*' saved/.procure_probe.html | sort | uniq -c | head -20")


def read():
    if not OUT.exists():
        return []
    with OUT.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def cmd_search(pages, days):
    old = {r["number"]: r for r in read()}
    new = 0
    for wagon, q in QUERIES:
        for pg in range(1, pages + 1):
            try:
                _, page = get(search_url(q, pg, days))
            except Exception as e:  # noqa: BLE001
                print(f"!! «{q}», стр. {pg}: {type(e).__name__}")
                break
            rows = parse(page)
            for x in rows:
                if x["number"] not in old:
                    new += 1
                old[x["number"]] = {**x, "wagon": wagon, "query": q}
            print(f"«{q}», стр. {pg}: закупок {len(rows)}")
            if len(rows) < 50:
                break
            time.sleep(2)  # бережно к площадке
    save(list(old.values()))
    print(f"Новых закупок: {new}; всего в файле: {len(old)} → {OUT}")


def save(rows):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, COLS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: "".join(reversed((r.get("published") or "").split("."))), reverse=True))


def parse_text(text):
    """Текст страницы поиска ЕИС (PDF «Печать → Сохранить как PDF» или скопированный текст): карточка начинается с
    «№ <номер>»; внутри — «Объект закупки», «Заказчик», «Начальная цена», «Размещено»."""
    flat = " ".join(text.split())
    parts = re.split(r"(?=№\s?\d{11,19}\b)", flat)
    out = []
    for c in parts:
        num = re.match(r"№\s?(\d{11,19})", c)
        if not num:
            continue
        g = lambda rx: (re.search(rx, c).group(1).strip() if re.search(rx, c) else "")
        price = g(r"Начальная цена\s*([\d\s]+(?:,\d{2})?)\s*₽")
        out.append({"number": num.group(1), "subject": g(r"Объект закупки\s*(.*?)\s*(?:Заказчик|Организация|Начальная|Размещено|$)")[:300],
                    "customer": g(r"(?:Заказчик|Организация, осуществляющая[^А-Я]*)\s*(.*?)\s*(?:Начальная|Размещено|Обновлено|$)")[:200],
                    "price": price.replace(" ", "").replace(",", "."), "currency": "₽" if price else "",
                    "published": g(r"Размещено\s*(\d{2}\.\d{2}\.\d{4})"), "law": g(r"(44-ФЗ|223-ФЗ)"),
                    "url": f"https://zakupki.gov.ru/epz/order/notice/rpec/search-results.html?orderNum={num.group(1)}"})
    return out


def wagon_of(text):
    low = text.lower()
    for k, rx in (("hop_grain", r"зерновоз"), ("fit", r"фитинг|платформ"), ("kr", r"крыт"), ("gon", r"полуваг")):
        if re.search(rx, low):
            return k
    return "any"


def cmd_import(files):
    """Страницы поиска ЕИС, сохранённые в браузере (Ctrl+S) и загруженные через «Мои загрузки»."""
    old = {r["number"]: r for r in read()}
    got = new = 0
    for f in files:
        raw = Path(f).read_bytes()
        if f.lower().endswith(".pdf"):  # сохранено с телефона: «Поделиться → Печать → Сохранить как PDF»
            import pdfplumber
            with pdfplumber.open(f) as pdf:
                rows = parse_text("\n".join(pg.extract_text() or "" for pg in pdf.pages))
        else:
            page = raw.decode("utf-8", "replace") if b"charset=windows-1251" not in raw[:3000] else raw.decode("cp1251", "replace")
            rows = parse(page) or parse_text(clean(page))  # HTML или скопированный текст
        got += len(rows)
        for x in rows:
            new += x["number"] not in old
            old[x["number"]] = {**old.get(x["number"], {}), **x, "wagon": wagon_of(x["subject"]), "query": "страница из браузера"}
        print(f"{Path(f).name}: закупок {len(rows)}")
    save(list(old.values()))
    print(f"разобрано {got}, новых {new}, всего {len(old)}")


def cmd_show(wagon):
    rows = [r for r in read() if not wagon or r["wagon"] == wagon]
    for r in rows[:40]:
        print(f"{r['published']} | {r['wagon']} | {r['price']} {r['currency']} | {r['customer'][:45]} | {r['subject'][:90]} | {r['url']}")
    print(f"Всего: {len(rows)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    opt = lambda k, d: type(d)(a[a.index(k) + 1]) if k in a else d
    if a[:1] == ["probe"]:
        cmd_probe()
    elif a[:1] == ["search"]:
        cmd_search(opt("--pages", 2), opt("--days", 365))
    elif a[:1] == ["show"]:
        cmd_show(opt("--wagon", ""))
    elif a[:1] == ["import"] and len(a) > 1:
        cmd_import(a[1:])
    elif a[:1] == ["dump"] and len(a) > 1:
        for x in parse(Path(a[1]).read_text(encoding="utf-8")):
            print(x)
    else:
        sys.exit(__doc__)
