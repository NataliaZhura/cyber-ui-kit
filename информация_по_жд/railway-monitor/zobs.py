#!/usr/bin/env python3
"""База наблюдений рынка вагонов — основа «Обзора рынка вагонов ЖДуши» (zissue.py). Без нейросети (0 токенов).

  python3 zobs.py pdf <выпуск.pdf> [ещё …]     таблицы выпуска данных партнёра → наблюдения (ставки аренды, оперирования,
                                              техрейса; парк; поступление и выбытие; погрузка); повтор не дублирует
  python3 zobs.py add <месяц> <показатель> <мин> [макс] [--source опрос] [--note "…"]
                                              ручной ввод: ответ участника рынка, ремонт, отстой, цена вагона
  python3 zobs.py show [месяц]                что есть за месяц (по умолчанию — последний)
  python3 zobs.py months                      какие месяцы есть по каждой группе показателей
  python3 zobs.py seed                        известные точки из СМИ (ремонты, неисправные, отстой, профицит, оценки ПГК)
  python3 zobs.py add 2026-03 fleet_bad 150 --source media --note "РЖД, ссылка"   новая цифра из новости — вручную
  python3 zobs.py diag <выпуск.pdf> [ещё …]    почему раздел не прочитался: заголовок таблицы, похожие строки

Наблюдение = месяц;показатель;мин;макс;источник;пометка. Источник: partner (данные партнёра — пока вместо опроса),
survey (опрос участников), rzd (РЖД), media (СМИ), own (свой расчёт). Файл — forecast/observations.csv (только на сервере,
в репозиторий не кладётся). Опрос заменит данные партнёра без переделки выпуска: меняется только источник.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "forecast" / "observations.csv"
FIELDS = ["month", "item", "low", "high", "source", "note"]

# Показатели: ключ → (группа, название, единица). Порядок = порядок строк в выпуске.
ITEMS = {
    "gon69_spot": ("lease", "Полувагон 69 т (типовой), спот", "руб./сут"),
    "gon69_long": ("lease", "Полувагон 69 т (типовой), долгосрочный контракт", "руб./сут"),
    "gon75_spot": ("lease", "Полувагон 75 т (инновационный), спот", "руб./сут"),
    "gon75_long": ("lease", "Полувагон 75 т (инновационный), долгосрочный контракт", "руб./сут"),
    "gon_fert": ("lease", "Полувагон под удобрения и серу", "руб./сут"),
    "hop_min": ("lease", "Хоппер-минераловоз", "руб./сут"),
    "hop_grain": ("lease", "Хоппер-зерновоз", "руб./сут"),
    "kr138": ("lease", "Крытый вагон 138 м³", "руб./сут"),
    "kr158": ("lease", "Крытый вагон 158 м³", "руб./сут"),
    "fit40": ("lease", "Фитинговая платформа 40'", "руб./сут"),
    "fit60": ("lease", "Фитинговая платформа 60'", "руб./сут"),
    "fit80": ("lease", "Фитинговая платформа 80'", "руб./сут"),
    "op_coal": ("oper", "Полувагон 69 т, уголь", "руб./сут"),
    "op_met": ("oper", "Полувагон 69 т, черные металлы, спот", "руб./сут"),
    "op_met_serv": ("oper", "Полувагон 69 т, черные металлы, сервисный контракт", "руб./сут"),
    "tr_kuz_vost": ("trip", "Кузбасс — Восточный", "руб./вагон"),
    "tr_kuz_vost75": ("trip", "Кузбасс — Восточный, 75 т", "руб./вагон"),
    "tr_kuz_ul": ("trip", "Кузбасс — Усть-Луга", "руб./вагон"),
    "tr_kuz_tam": ("trip", "Кузбасс — Тамань", "руб./вагон"),
    "tr_kz_ul": ("trip", "Центральный Казахстан — Усть-Луга", "руб./вагон"),
    "tr_kz_tam": ("trip", "Центральный Казахстан — Тамань", "руб./вагон"),
    "rep_dr": ("repair", "Деповской ремонт", "руб."),
    "rep_kr_gon": ("repair", "Капитальный ремонт полувагона", "руб."),
    "rep_kr_other": ("repair", "Капитальный ремонт крытого, хоппера, платформы", "руб."),
    "rep_tr1": ("repair", "Текущий ремонт ТР-1", "руб."),
    "rep_tr2": ("repair", "Текущий ремонт ТР-2", "руб."),
    "stoy_npp": ("repair", "Отстой на путях необщего пользования", "руб./сут"),
    "stoy_off": ("repair", "Отстой со снятием с инфраструктуры", "руб./сут"),
    "price_new_gon": ("price", "Новый полувагон типовой", "руб."),
    "price_new_inno": ("price", "Новый полувагон инновационный", "руб."),
    "price_new_fit80": ("price", "Новая фитинговая платформа 80'", "руб."),
    # Состояние парка — вручную из СМИ и оценок отрасли (источник media): ремонты, неисправные, отстой, профицит
    "fleet_repair": ("fleet", "Ремонтов вагонов в месяц", "тыс. ваг."),
    "fleet_bad": ("fleet", "Неисправные вагоны на сети", "тыс. ваг."),
    "fleet_stoy": ("fleet", "Вагоны в длительном отстое", "тыс. ваг."),
    "fleet_surplus": ("fleet", "Лишние вагоны (оценка профицита)", "тыс. ваг."),
    "fleet_off": ("fleet", "Списано вагонов за период", "тыс. ваг."),
    "load_total": ("load", "Погрузка на сети РЖД, всего", "млн т"),
    "load_coal": ("load", "Каменный уголь", "млн т"),
    "load_build": ("load", "Строительные грузы", "млн т"),
    "load_ore": ("load", "Руда железная и марганцевая", "млн т"),
    "load_fert": ("load", "Удобрения", "млн т"),
    "load_metal": ("load", "Черные металлы", "млн т"),
    "load_grain": ("load", "Зерно", "млн т"),
    "load_wood": ("load", "Лесные грузы", "млн т"),
    "load_scrap": ("load", "Лом черных металлов", "млн т"),
}
PARK = {"gon": "Полувагоны", "plat": "Платформы", "fit": "Фитинговые платформы", "hop": "Хопперы",
        "hop_grain": "Хопперы-зерновозы", "hop_min": "Хопперы-минераловозы", "kr": "Крытые вагоны", "total": "Итого"}
for k, nm in PARK.items():
    ITEMS[f"park_{k}_reg"] = ("park", f"{nm}: зарегистрировано", "ед.")
    ITEMS[f"park_{k}_work"] = ("park", f"{nm}: рабочие", "ед.")
    ITEMS[f"park_{k}_exp"] = ("park", f"{nm}: с истекшим сроком службы", "ед.")
    ITEMS[f"flow_{k}_in"] = ("flow", f"{nm}: поступило на сеть", "ед.")
    ITEMS[f"flow_{k}_new"] = ("flow", f"{nm}: поступило новых", "ед.")
    ITEMS[f"flow_{k}_out"] = ("flow", f"{nm}: покинуло сеть", "ед.")

MON = {"янв": 1, "февр": 2, "фев": 2, "март": 3, "мар": 3, "апр": 4, "май": 5, "мая": 5, "июнь": 6, "июн": 6, "июль": 7,
       "июл": 7, "авг": 8, "сент": 9, "сен": 9, "окт": 10, "нояб": 11, "ноя": 11, "дек": 12}
GEN = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
       "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
NUM = r"\d{1,3}(?: \d{3})+|\d+"
RANGE2 = re.compile(rf"^(?P<name>\S.*?)\s+(?P<a>{NUM})\s*[—–-]\s*(?P<b>{NUM})\s+(?P<c>{NUM})\s*[—–-]\s*(?P<d>{NUM})\s*$")
LEASE = [(r"69 т \(уголь, спот", "gon69_spot"), (r"69 т \(уголь, долгоср", "gon69_long"), (r"75 т.*спот", "gon75_spot"),
         (r"75 т.*долгоср", "gon75_long"), (r"удобрени", "gon_fert"), (r"минераловоз", "hop_min"), (r"зерновоз", "hop_grain"),
         (r"138", "kr138"), (r"158", "kr158"), (r"^40", "fit40"), (r"^60", "fit60"), (r"^80", "fit80")]
OPER = [(r"сервисн", "op_met_serv"), (r"черные металлы", "op_met"), (r"уголь", "op_coal")]
TRIP = [(r"Восточный, 75", "tr_kuz_vost75"), (r"Кузбасс — Восточный", "tr_kuz_vost"), (r"Кузбасс — Усть", "tr_kuz_ul"),
        (r"Кузбасс — Тамань", "tr_kuz_tam"), (r"Казахстан — Усть", "tr_kz_ul"), (r"Казахстан — Тамань", "tr_kz_tam")]
PARKROW = [(r"^Полувагоны, всего", "gon"), (r"^Платформы, всего", "plat"), (r"^Фитинговые платформы", "fit"),
           (r"^Хопперы, всего", "hop"), (r"^Хопперы-зерновозы", "hop_grain"), (r"^Хопперы-минераловозы", "hop_min"),
           (r"^Крытые вагоны, всего", "kr"), (r"^Итого", "total")]
LOADROW = [(r"^Каменный уголь", "load_coal"), (r"^Строительные", "load_build"), (r"^Руда", "load_ore"),
           (r"удобрения", "load_fert"), (r"^Черные металлы", "load_metal"), (r"^Зерно", "load_grain"),
           (r"^Лесные", "load_wood"), (r"^Лом", "load_scrap")]


def ym(y, m):
    return f"{y}-{m:02d}"


def shift(month, k):
    y, m = map(int, month.split("-"))
    m += k
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return ym(y, m)


def pick(rules, name):
    return next((k for rx, k in rules if re.search(rx, name)), None)


def num(s):
    return float(s.replace(" ", "").replace(",", "."))


def parse_text(text):
    """Текст выпуска (pdfplumber или pdftotext) → наблюдения. Месяц выпуска — из даты в колонтитуле."""
    flat = " ".join(text[:20000].split())
    m = re.search(r"(20\d\d),\s*выпуск\s+[IVXLC]+,\s*№\s*(\d{1,2})\b", flat)  # обложка: № выпуска = месяц
    if m and 1 <= int(m.group(2)) <= 12:
        cur = ym(int(m.group(1)), int(m.group(2)))
    else:
        m = re.search(r"Логистика сухих грузов\s+(\d{1,2})\s+([а-я]+)\s+(\d{4})", text)
        if not m or m.group(2) not in GEN:
            raise ValueError("не найдена дата выпуска (обложка «ГГГГ, выпуск …, № N» или колонтитул)")
        cur = ym(int(m.group(3)), GEN[m.group(2)])
    prev, obs, group = shift(cur, -1), [], None
    lines = [" ".join(x.split()) for x in text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith("Ставки аренды подвижного состава в России"):
            group = "lease"
        elif line.startswith("Ставка оперирования подвижным составом в России"):
            group = "oper"
        elif line.startswith("Ставки предоставления типового полувагона на технический рейс"):
            group = "trip"
        elif line.startswith(("Ставки аренды подвижного состава в Казахстане", "Все права защищены")):
            group = None
        elif line.startswith("Парк частных вагонов"):
            obs += table_park(lines[i + 1:i + 30], cur, prev)
        elif line.startswith("Поступление и выбытие частных вагонов"):
            obs += table_flow(lines[i + 1:i + 30], prev, shift(cur, -2))
        elif line.startswith("Погрузка основных сухих грузов на сети РЖД"):
            obs += table_load(lines[i + 1:i + 22], prev)
        elif re.match(r"^Погрузка на сети РЖД млн т", line):
            obs += table_load_total(lines[i + 1:i + 60])
        if group and (r := RANGE2.match(line)):
            key = pick({"lease": LEASE, "oper": OPER, "trip": TRIP}[group], r["name"])
            if key:
                obs.append((cur, key, num(r["a"]), num(r["b"]), "partner", ""))
                obs.append((prev, key, num(r["c"]), num(r["d"]), "partner", "из колонки прошлого месяца"))
    return cur, obs


def cells(line):
    return re.findall(r"-?\d+(?:,\d+)?|—", line)


def table_park(lines, cur, prev):
    out = []
    for line in lines:
        k = pick(PARKROW, line)
        c = cells(line)
        if k and len(c) >= 9:
            for j, part in ((0, "reg"), (3, "work"), (6, "exp")):
                out += [(cur, f"park_{k}_{part}", num(c[j]), num(c[j]), "partner", "на 1-е число"),
                        (prev, f"park_{k}_{part}", num(c[j + 1]), num(c[j + 1]), "partner", "на 1-е число")]
        if line.startswith("* —"):
            break
    return out


def table_flow(lines, m1, m2):
    out = []
    for line in lines:
        k = pick(PARKROW, line)
        c = cells(line)
        if k and len(c) >= 9:
            for j, part in ((0, "in"), (3, "new"), (6, "out")):
                out += [(m1, f"flow_{k}_{part}", num(c[j]), num(c[j]), "partner", "за месяц"),
                        (m2, f"flow_{k}_{part}", num(c[j + 1]), num(c[j + 1]), "partner", "за месяц")]
        if line.startswith("* —"):
            break
    return out


def table_load(lines, month):
    out = []
    for line in lines:
        k = pick(LOADROW, line)
        c = cells(line)
        if k and c:
            v = num(c[0])
            out.append((month, k, v, v, "rzd", "по данным РЖД"))
            if len(c) >= 4:  # колонки «± прошлый месяц» и «± год назад» — в абсолютных млн т
                out += [(shift(month, -1), k, round(v - num(c[1]), 1), round(v - num(c[1]), 1), "rzd", "из колонки ± месяц"),
                        (shift(month, -12), k, round(v - num(c[3]), 1), round(v - num(c[3]), 1), "rzd", "из колонки ± год")]
        if line.startswith("— по данным"):
            break
    return out


def table_load_total(lines):
    out = []
    for line in lines:
        r = re.match(r"^([А-Яа-я]+)\.?\s+(\d{2})\s+(\d+,\d)", line)
        if r and r.group(1).lower().rstrip(".") in MON:
            out.append((ym(2000 + int(r.group(2)), MON[r.group(1).lower().rstrip(".")]), "load_total",
                        num(r.group(3)), num(r.group(3)), "rzd", "по данным РЖД"))
        if line.startswith("— по данным"):
            break
    return out


def read():
    if not DATA.exists():
        return []
    with DATA.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def write(rows):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["month"], list(ITEMS).index(r["item"]) if r["item"] in ITEMS else 999, r["source"]))
    with DATA.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, FIELDS, delimiter=";")
        w.writeheader()
        w.writerows(rows)


def merge(new):
    """Новые наблюдения поверх старых: ключ — месяц + показатель + источник. Колонка «текущий месяц» важнее «прошлого»."""
    rows = {(r["month"], r["item"], r["source"]): r for r in read()}
    added = 0
    for month, item, lo, hi, src, note in new:
        key = (month, item, src)
        old = rows.get(key)
        if old and note.startswith("из колонки") and not old["note"].startswith("из колонки"):
            continue  # уже есть значение из выпуска этого месяца — оно точнее
        added += key not in rows
        rows[key] = {"month": month, "item": item, "low": f"{lo:.10g}", "high": f"{hi:.10g}", "source": src, "note": note}
    write(list(rows.values()))
    return added, len(rows)


def pdf_text(path):
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8")
    import logging
    import pdfplumber
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def cmd_pdf(files):
    for f in files:
        try:
            cur, obs = parse_text(pdf_text(Path(f).expanduser()))
        except ValueError as e:
            print(f"{f}: пропуск — {e}")
            continue
        groups = sorted({ITEMS[o[1]][0] for o in obs})
        added, total = merge(obs)
        print(f"{Path(f).name}: выпуск {cur}, наблюдений {len(obs)} (новых {added}), разделы: {', '.join(groups)}; всего в базе {total}")


TITLES = {"lease": "Ставки аренды подвижного состава в России", "oper": "Ставка оперирования подвижным составом в России",
          "trip": "Ставки предоставления типового полувагона на технический рейс", "park": "Парк частных вагонов",
          "flow": "Поступление и выбытие частных вагонов", "load": "Погрузка основных сухих грузов на сети РЖД"}


def cmd_diag(files):
    """Почему из выпуска не прочитался раздел: есть ли заголовок таблицы; если нет — похожие строки; если есть, но строк
    нет, — первые строки таблицы (видно, сколько в них чисел)."""
    for f in files:
        text = pdf_text(Path(f).expanduser())
        try:
            cur, obs = parse_text(text)
        except ValueError as e:
            print(f"== {Path(f).name}: {e}")
            continue
        got = {ITEMS[o[1]][0] for o in obs}
        lines = [" ".join(x.split()) for x in text.splitlines()]
        print(f"== {Path(f).name}: выпуск {cur}, прочитано: {', '.join(sorted(got)) or '—'}")
        for g, title in TITLES.items():
            if g in got:
                continue
            hit = [i for i, x in enumerate(lines) if x.startswith(title)]
            if not hit:
                word = title.split()[0][:6]
                like = [x[:90] for x in lines if x.startswith(word)][:4]
                print(f"  {g}: заголовка «{title[:40]}…» нет; похожие: {' | '.join(like) or 'нет'}")
                continue
            print(f"  {g}: заголовок есть (стр. текста {hit[0]}), строки таблицы не распознаны:")
            for x in lines[hit[0] + 1:hit[0] + 9]:
                print(f"     [{len(cells(x))} чисел] {x[:100]}")


def cmd_months():
    by = {}
    for r in read():
        by.setdefault(ITEMS.get(r["item"], ("?",))[0], set()).add(r["month"])
    names = {"lease": "аренда", "oper": "оперирование", "trip": "техрейс", "repair": "ремонт/отстой", "price": "цены вагонов",
             "load": "погрузка", "park": "парк", "flow": "поступление/выбытие", "fleet": "ремонты/отстой (СМИ)"}
    for g, ms in by.items():
        print(f"{names.get(g, g):20s} {', '.join(sorted(ms))}")


def cmd_show(month):
    rows = read()
    month = month or max((r["month"] for r in rows if ITEMS.get(r["item"], ("",))[0] == "lease"), default=None)
    for r in rows:
        if r["month"] == month:
            nm, unit = ITEMS.get(r["item"], ("", r["item"], ""))[1:]
            val = r["low"] if r["low"] == r["high"] else f"{r['low']}—{r['high']}"
            print(f"{nm:55s} {val:>15s} {unit:10s} {r['source']}")


# Известные точки из СМИ (поисковая выдача 22.10.2026, страницы не открывались — сверить по ссылке). Повтор не дублирует.
SEED = [
    ("2024-12", "fleet_repair", 38, 39, "ИПЕМ: ремонт 38–39 тыс. вагонов в месяц в конце 2024 г. (Коммерсантъ, kommersant.ru/doc/8782122)"),
    ("2026-02", "fleet_repair", 20, 23, "ИПЕМ: 20–23 тыс. в месяц в начале 2026 г. (Коммерсантъ, kommersant.ru/doc/8782122)"),
    ("2026-02", "fleet_bad", 158, 158, "неисправных 158 тыс. к концу февраля 2026 г. (Коммерсантъ, kommersant.ru/doc/8572406)"),
    ("2024-12", "fleet_stoy", 75, 75, "из движения выведено около 75 тыс. к концу 2024 г. (vgudok.com, infranews.ru)"),
    ("2025-02", "fleet_stoy", 116, 116, "более 116 тыс. в длительном отстое на путях необщего пользования, начало 2025 г. (vgudok.com)"),
    ("2024-12", "fleet_surplus", 250, 250, "оценка РЖД, 2024 г. (rzd-partner.ru)"),
    ("2025-02", "fleet_surplus", 400, 400, "оценка РЖД, февраль 2025 г. (rzd-partner.ru)"),
    ("2025-06", "fleet_off", 16, 16, "списано за I пол. 2025 г., +66% к году (expert.ru)"),
    ("2025-12", "fleet_off", 38.3, 38.3, "списано за 2025 г. (vgudok.com)"),
    ("2026-07", "fleet_off", 16, 16, "списано за 7 мес. 2026 г. (vgudok.com)"),
    ("2026-06", "gon69_spot", 750, 750, "оценка аналитиков ПГК: типовой +15% с начала года (Коммерсантъ 03.07.2026, kommersant.ru/doc/8782122)"),
    ("2026-06", "gon75_spot", 1200, 1200, "оценка аналитиков ПГК: инновационный +20% (Коммерсантъ 03.07.2026)"),
    ("2025-09", "gon69_spot", 880, 880, "СОЖТ: 880 ₽/сут в сентябре 2025 г. (vgudok.com)"),
]


def cmd_seed():
    """Известные точки из СМИ — в базу (источник media). Одинаковый месяц и показатель: последняя запись из списка."""
    added, total = merge([(m, it, lo, hi, "media", note) for m, it, lo, hi, note in SEED])
    print(f"Из СМИ: записано {len(SEED)} точек (новых {added}); всего в базе {total}")


def cmd_add(a):
    if a.item not in ITEMS:
        sys.exit(f"Нет показателя {a.item}. Есть: {', '.join(ITEMS)}")
    if not re.fullmatch(r"\d{4}-\d{2}", a.month):
        sys.exit("Месяц — ГГГГ-ММ, например 2026-10")
    added, total = merge([(a.month, a.item, num(a.low), num(a.high or a.low), a.source, a.note)])
    print(f"Записано: {a.month} {ITEMS[a.item][1]} {a.low}{'—' + a.high if a.high else ''} ({a.source}); всего в базе {total}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pdf").add_argument("files", nargs="+")
    s = sub.add_parser("show")
    s.add_argument("month", nargs="?")
    sub.add_parser("months")
    sub.add_parser("seed")
    sub.add_parser("diag").add_argument("files", nargs="+")
    d = sub.add_parser("add")
    d.add_argument("month")
    d.add_argument("item")
    d.add_argument("low")
    d.add_argument("high", nargs="?")
    d.add_argument("--source", default="survey", choices=["partner", "survey", "rzd", "media", "own"])
    d.add_argument("--note", default="")
    x = ap.parse_args()
    {"pdf": lambda: cmd_pdf(x.files), "show": lambda: cmd_show(x.month), "months": cmd_months,
     "diag": lambda: cmd_diag(x.files), "seed": cmd_seed,
     "add": lambda: cmd_add(x)}[x.cmd]()
