#!/usr/bin/env python3
"""Лётный час: себестоимость по статьям, цены часа в госконтрактах, «ножницы», светофор, прогноз и калькулятор ставки.

  python3 fh.py import <модель.xlsx>           структура себестоимости (лист «СС ЛЧ») → fh_base.csv
  python3 fh.py contracts <модель.xlsx> [лист] госконтракты (лист «…ЕИС…») → fh_contracts.csv
  python3 fh.py base                            разбивка часа по статьям: старый парк и новый вертолёт, доли, драйверы
  python3 fh.py prices                          цены часа в контрактах без НДС по видам работ и «ножницы»
  python3 fh.py driver <драйвер> <ГГГГ-ММ> <изменение %|уровень> "<источник>"   записать изменение драйвера
  python3 fh.py index [--short]                 индекс расходов (старый/новый) и доходов, светофор по видам работ
  python3 fh.py forecast [--to 2030] [--xlsx out.xlsx]   прогноз себестоимости и цены часа: «базовый» и «ножницы»
  python3 fh.py calc --opex <руб/ч> [--mro <руб/ч>] --hours <ч/мес> --rate <руб/ч> --price <млн ₽> --lease <%>
        --term <лет> [--advance <%>] [--wacc 15] [--dscr 1.2] [--rate-idx 5] [--opex-idx 5] [--mro-idx 12]
        [--tax 20] [--xlsx out.xlsx]
        калькулятор сделки: себестоимость часа, ставка безубыточности, минимальная ставка для DSCR, справедливая
        ставка (NPV = 0 при WACC), DSCR и NPV по годам, ставка при налёте 30–80 ч/мес, факторы влияния ±20%

Файлы с данными владельца (fh_base.csv, fh_contracts.csv, fh_drivers.csv) — только на сервере, в репозиторий не кладутся.
Суммы — без НДС. Драйверы: керосин, зарплата, тоир, аэропорт, инфляция, ключевая (уровень, % годовых → лизинг).
Прогноз — оценка: допущения печатаются вместе с результатом и меняются в fh_scen.csv. Модель (ИИ) не используется.
"""
import csv
import re
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
FBASE, FCON, FDRV, FSCEN = (BASE / n for n in ("fh_base.csv", "fh_contracts.csv", "fh_drivers.csv", "fh_scen.csv"))

# статья себестоимости → драйвер, который её двигает
DRIVER_OF = [("гсм", "керосин"), ("топлив", "керосин"), ("аэропорт", "аэропорт"), ("аэронавиг", "аэропорт"),
             ("заработн", "зарплата"), ("налоги на заработ", "зарплата"), ("экипаж", "зарплата"),
             ("лизинг", "лизинг"), ("тоир", "тоир"), ("ремонт", "тоир"), ("% по кредит", "ключевая")]
DRIVERS = ["керосин", "зарплата", "тоир", "аэропорт", "инфляция", "ключевая"]
LEASE_SPREAD, LEASE_TERM = 2.25, 10      # ставка лизинга = ключевая + 2,25 п. п. (коммерческая 16,5% при КС 14,25%)
KR_BASE = 14.25   # ключевая ставка, под которую посчитан лизинг нового вертолёта в базе (модель: лист «Допущения», 2026)

# сценарии прогноза: рост в % за год (ключевая — уровень в % годовых); «инф» = инфляция этого года
SCEN_DEFAULT = """сценарий;показатель;2026;2027;2028;2029;2030;пояснение
базовый;инфляция;5.35;4;4;4;4;Банк России, прогноз 07.05.2026 (2026 — середина 5,1–5,6); 2029–2030 — цель 4%
базовый;ключевая;14.25;9;8;8;8;Банк России, прогноз 07.05.2026; 2029–2030 — как 2028
базовый;керосин;инф;инф;инф;инф;инф;растёт вместе с инфляцией
базовый;зарплата;инф+3;инф+3;инф+3;инф+3;инф+3;дефицит пилотов и техников
базовый;тоир;12;12;12;12;12;индексация ТОиР в модели лизинга Ми-8МТВ-1
базовый;аэропорт;инф;инф;инф;инф;инф;
базовый;цена часа;инф;инф;инф;инф;инф;цены контрактов растут с инфляцией
ножницы;инфляция;5.35;5;5;5;5;инфляция выше цели
ножницы;ключевая;17.25;12;11;11;11;на 3 п. п. выше базового
ножницы;керосин;инф+5;инф+5;инф+5;инф+5;инф+5;
ножницы;зарплата;инф+6;инф+6;инф+6;инф+6;инф+6;
ножницы;тоир;15;15;15;15;15;
ножницы;аэропорт;инф+2;инф+2;инф+2;инф+2;инф+2;
ножницы;цена часа;инф-2;инф-2;инф-2;инф-2;инф-2;заказчики (бюджеты) не успевают за затратами
"""


# ---------- общее ----------

def num(v):
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    m = re.match(r"-?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


def read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def fmt(v, d=1):
    if v is None:
        return "н/д"
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def pct(v, d=0):
    return "н/д" if v is None else f"{v * 100:.{d}f}%".replace(".", ",")


def driver_of(name):
    low = name.lower()
    return next((d for k, d in DRIVER_OF if k in low), "инфляция")


def need(path, hint):
    if not path.exists():
        sys.exit(f"Нет {path.name}. {hint}")


# ---------- импорт из модели ----------

def cmd_import(xlsx):
    import warnings
    warnings.filterwarnings("ignore")
    from openpyxl import load_workbook
    wb = load_workbook(xlsx, data_only=True)
    ws = next((w for w in wb.worksheets if w.title.strip().lower() in ("сс лч", "себестоимость лч")), None)
    if ws is None:
        sys.exit("Нет листа «СС ЛЧ» (себестоимость лётного часа).")
    # строка заголовков: «Статья расходов»; столбцы: факт «Авиационная работа» (старый парк), «Сумма» (новый вертолёт)
    hdr = next(r for r in range(1, 15) if any(str(ws.cell(r, c).value or "").strip().lower() == "статья расходов"
                                            for c in range(1, 15)))
    cols = {str(ws.cell(hdr, c).value or "").strip().lower(): c for c in range(1, 20)}
    c_name = cols["статья расходов"]
    c_tr = next(c for c in range(1, 20) if "транспорт" in str(ws.cell(hdr, c).value or "").lower())
    c_old = next(c for c in range(1, 20) if "авиацион" in str(ws.cell(hdr, c).value or "").lower())
    c_new = next(c for c in range(1, 20) for r in (hdr, hdr + 1) if str(ws.cell(r, c).value or "").strip().lower() == "сумма")
    rows = []
    for r in range(hdr + 1, hdr + 30):
        name = str(ws.cell(r, c_name).value or "").strip()
        if not name or name.lower().startswith("итого"):
            if name.lower().startswith("итого"):
                break
            continue
        old, new, tr = num(ws.cell(r, c_old).value), num(ws.cell(r, c_new).value), num(ws.cell(r, c_tr).value)
        if old is None and new is None:
            continue
        rows.append({"статья": name, "драйвер": driver_of(name), "старый": old or 0, "новый": new or 0,
                     "транспортная": tr or 0})
    write(FBASE, ["статья", "драйвер", "старый", "новый", "транспортная"], rows)
    so, sn = sum(float(r["старый"]) for r in rows), sum(float(r["новый"]) for r in rows)
    print(f"Себестоимость часа: старый парк {fmt(so)} тыс. ₽, новый вертолёт {fmt(sn)} тыс. ₽ (статей {len(rows)}) → "
          f"{FBASE.name}. Проверь: python3 fh.py base")


def cmd_contracts(xlsx, sheet=None):
    import warnings
    warnings.filterwarnings("ignore")
    from openpyxl import load_workbook
    wb = load_workbook(xlsx, data_only=True)
    ws = wb[sheet] if sheet else next((w for w in wb.worksheets if "еис" in w.title.lower()), None)
    if ws is None:
        sys.exit("Нет листа с контрактами ЕИС — укажи лист вторым параметром.")
    hdr = next(r for r in range(1, 10) if any("цена за единицу" in str(ws.cell(r, c).value or "").lower()
                                            for c in range(1, 25)))
    col = lambda word: next((c for c in range(1, 25) if word in str(ws.cell(hdr, c).value or "").lower()), None)
    c_no, c_date, c_price, c_vat = col("контракт"), col("заключение"), col("цена за единицу"), col("ндс")
    c_qty, c_type, c_kind, c_reg = col("количество"), col("тип вс"), col("укрупненный"), col("субъект")
    c_exec = col("исполнитель")
    out = []
    for r in range(hdr + 1, ws.max_row + 1):
        p = num(ws.cell(r, c_price).value)
        if p is None:
            continue
        vat = num(ws.cell(r, c_vat).value) if c_vat else 0
        vat = (vat or 0) / 100 if (vat or 0) > 1 else (vat or 0)
        d = ws.cell(r, c_date).value
        d = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else "-".join(reversed(str(d).strip().split(".")))
        out.append({"контракт": str(ws.cell(r, c_no).value or "").strip(), "дата": d,
                    "цена_без_ндс": round(p / (1 + vat), 2), "ндс": vat,
                    "часы": num(ws.cell(r, c_qty).value) if c_qty else "",
                    "тип_вс": ws.cell(r, c_type).value if c_type else "",
                    "вид_работ": str(ws.cell(r, c_kind).value or "").split("/")[0].strip(),
                    "регион": ws.cell(r, c_reg).value if c_reg else "",
                    "исполнитель": str(ws.cell(r, c_exec).value or "").strip() if c_exec else ""})
    write(FCON, ["контракт", "дата", "цена_без_ндс", "ндс", "часы", "тип_вс", "вид_работ", "регион", "исполнитель"], out)
    print(f"Контрактов: {len(out)} → {FCON.name}. Посмотреть: python3 fh.py prices")


# ---------- база и цены ----------

def base_rows():
    need(FBASE, "Сначала: python3 fh.py import <модель.xlsx>")
    return [{**r, "старый": float(r["старый"]), "новый": float(r["новый"])} for r in read(FBASE)]


def cmd_base():
    rows = base_rows()
    so, sn = sum(r["старый"] for r in rows), sum(r["новый"] for r in rows)
    print("СЕБЕСТОИМОСТЬ ЛЁТНОГО ЧАСА, тыс. ₽ без НДС (старый парк — факт, новый вертолёт — расчёт)")
    print(f"{'статья':<34}{'старый':>8}{'доля':>6}{'новый':>8}{'доля':>6}  драйвер")
    for r in sorted(rows, key=lambda r: -r["новый"]):
        print(f"{r['статья'][:33]:<34}{fmt(r['старый']):>8}{pct(r['старый'] / so):>6}{fmt(r['новый']):>8}"
              f"{pct(r['новый'] / sn):>6}  {r['драйвер']}")
    print(f"{'Итого':<34}{fmt(so):>8}{'100%':>6}{fmt(sn):>8}{'100%':>6}")
    by = {}
    for r in rows:
        by.setdefault(r["драйвер"], [0, 0])
        by[r["драйвер"]][0] += r["старый"] / so
        by[r["драйвер"]][1] += r["новый"] / sn
    by.pop("ключевая", None)
    print("\nВЕС ДРАЙВЕРОВ (на сколько % вырастет час, если драйвер вырастет на 10%):")
    for d, (a, b) in sorted(by.items(), key=lambda x: -x[1][1]):
        print(f"  {d:<10} старый парк +{fmt(a * 10)}%, новый вертолёт +{fmt(b * 10)}%")
    print("Ключевая ставка действует на новый вертолёт через лизинг: +1 п. п. ставки ≈ "
          f"+{fmt(lease_effect(KR_BASE, KR_BASE + 1) * by.get('лизинг', [0, 0])[1] * 100)}% к часу "
          f"(при ставке {fmt(KR_BASE, 2)}%).")


def lease_effect(kr0, kr1, term=LEASE_TERM):
    """Относительное изменение аннуитетного платежа при смене ключевой ставки kr0 → kr1 (% годовых)."""
    def pmt(k):
        r = (k + LEASE_SPREAD) / 100
        return r / (1 - (1 + r) ** -term)
    return pmt(kr1) / pmt(kr0) - 1


def contracts():
    need(FCON, "Сначала: python3 fh.py contracts <модель.xlsx>")
    return [{**r, "цена_без_ндс": float(r["цена_без_ндс"])} for r in read(FCON)]


def cmd_prices():
    rows, base = contracts(), base_rows()
    so, sn = sum(r["старый"] for r in base) * 1000, sum(r["новый"] for r in base) * 1000
    kinds = {}
    for c in rows:
        kinds.setdefault(c["вид_работ"] or "прочее", []).append(c["цена_без_ндс"])
    allp = [c["цена_без_ндс"] for c in rows]
    print(f"ЦЕНА ЛЁТНОГО ЧАСА В ГОСКОНТРАКТАХ, тыс. ₽ без НДС ({len(rows)} контрактов, "
          f"{min(c['дата'] for c in rows)}…{max(c['дата'] for c in rows)})")
    print(f"Себестоимость: старый парк {fmt(so / 1000)}, новый вертолёт {fmt(sn / 1000)}")
    print(f"{'вид работ':<30}{'шт':>4}{'мин':>7}{'медиана':>9}{'макс':>7}{'< нового':>10}{'< старого':>11}")
    for k, v in sorted(kinds.items(), key=lambda x: -len(x[1])) + [("ВСЕ", allp)]:
        bn, bo = sum(1 for x in v if x < sn), sum(1 for x in v if x < so)
        print(f"{k[:29]:<30}{len(v):>4}{fmt(min(v) / 1000, 0):>7}{fmt(st.median(v) / 1000, 0):>9}"
              f"{fmt(max(v) / 1000, 0):>7}{f'{bn} ({pct(bn / len(v))})':>10}{f'{bo} ({pct(bo / len(v))})':>11}")
    print("«< нового» — цена ниже себестоимости нового вертолёта: обновление парка за счёт этих работ не окупится; "
          "«< старого» — ниже даже себестоимости старого парка.")


# ---------- драйверы и индекс ----------

def drivers():
    rows = read(FDRV)
    for r in rows:
        r["значение"] = float(str(r["значение"]).replace(",", "."))
    return sorted(rows, key=lambda r: r["месяц"])


def cmd_driver(name, month, value, source=""):
    name = name.lower()
    if name not in DRIVERS:
        sys.exit(f"Драйвер: {', '.join(DRIVERS)}")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        sys.exit("Месяц — ГГГГ-ММ")
    if not source:
        sys.exit("Нужен источник (ссылка) — без него драйвер не записывается.")
    v = float(value.replace(",", ".").replace("%", "").replace("+", ""))
    rows = [r for r in read(FDRV) if not (r["драйвер"] == name and r["месяц"] == month)]
    rows.append({"драйвер": name, "месяц": month, "значение": v,
                 "тип": "уровень" if name == "ключевая" else "%", "источник": source,
                 "записано": datetime.now().strftime("%Y-%m-%d")})
    write(FDRV, ["драйвер", "месяц", "значение", "тип", "источник", "записано"],
          sorted(rows, key=lambda r: (r["драйвер"], r["месяц"])))
    print(f"Записано: {name} {month} = {v}{'' if name == 'ключевая' else '%'} ({source})")


def factors(upto, drv):
    """Накопленный рост каждого драйвера от базы до месяца upto включительно: {драйвер: множитель}."""
    f = {d: 1.0 for d in DRIVERS + ["лизинг"]}
    kr0 = kr = KR_BASE
    for r in drv:
        if r["месяц"] > upto:
            continue
        if r["драйвер"] == "ключевая":
            kr = r["значение"]
        else:
            f[r["драйвер"]] *= 1 + r["значение"] / 100
    f["лизинг"] = 1 + lease_effect(kr0, kr)
    return f


def cost_at(base, f, line):
    return sum(r[line] * f.get(r["драйвер"], 1.0) for r in base)


def cmd_index(*opts):
    base, drv = base_rows(), drivers()
    short = "--short" in opts
    so0, sn0 = cost_at(base, {}, "старый"), cost_at(base, {}, "новый")
    months = sorted({r["месяц"] for r in drv})
    if not months:
        print("Драйверов ещё нет: python3 fh.py driver керосин 2026-09 +2,1 \"ссылка\" (рост за месяц, %); "
              "ключевая — уровнем: python3 fh.py driver ключевая 2026-10 16,5 \"ссылка\"")
    con = contracts() if FCON.exists() else []
    # доходы: медиана цены контрактов по кварталам, база — первое полугодие 2025
    q = lambda d: f"{d[:4]}-К{(int(d[5:7]) - 1) // 3 + 1}"
    byq = {}
    for c in con:
        byq.setdefault(q(c["дата"]), []).append(c["цена_без_ндс"])
    base_rev = [c["цена_без_ндс"] for c in con if "2025-01" <= c["дата"][:7] <= "2025-06"]
    rev0 = st.median(base_rev) if base_rev else None
    last = months[-1] if months else None
    f = factors(last, drv) if last else {}
    so, sn = cost_at(base, f, "старый"), cost_at(base, f, "новый")
    # светофор по видам работ: медиана цены последних 12 месяцев против себестоимости сейчас
    since = max((c["дата"] for c in con), default="")[:4]
    lights = []
    kinds = {}
    for c in con:
        kinds.setdefault(c["вид_работ"] or "прочее", []).append(c)
    for k, cs in kinds.items():
        lastd = max(c["дата"] for c in cs)
        recent = [c["цена_без_ндс"] for c in cs if c["дата"] >= f"{int(lastd[:4]) - 1}{lastd[4:]}"]
        m = st.median(recent) / 1000
        light = "🔴" if m < so else "🟡" if m < sn else "🟢"
        lights.append((k, light, m, len(recent)))
    # «ножницы» 3 месяца подряд: расходы растут быстрее цен — по месяцам драйверов, где есть цены
    scissors = []
    for m in months[-3:]:
        prev = months[months.index(m) - 1] if months.index(m) else None
        if prev:
            c1, c0 = cost_at(base, factors(m, drv), "новый"), cost_at(base, factors(prev, drv), "новый")
            scissors.append(c1 > c0)
    scis_red = len(scissors) == 3 and all(scissors)
    if short:
        worst = min(lights, key=lambda x: "🔴🟡🟢".index(x[1])) if lights else None
        print(f"Лётный час Ми-8: себестоимость старый {fmt(so)} / новый {fmt(sn)} тыс. ₽ "
              f"({pct(sn / sn0 - 1, 1)} к базе)"
              + (f"; хуже всего — {worst[0].lower()} {worst[1]} (медиана {fmt(worst[2], 0)} тыс. ₽)" if worst else "")
              + ("; 🔴 расходы растут 3 месяца подряд" if scis_red else ""))
        return
    print(f"ИНДЕКС РАСХОДОВ ЛЁТНОГО ЧАСА (база — факт 1-го полугодия 2025 года, без НДС)")
    print(f"{'месяц':<9}{'старый, тыс. ₽':>15}{'индекс':>8}{'новый, тыс. ₽':>15}{'индекс':>8}")
    print(f"{'база':<9}{fmt(so0):>15}{'100':>8}{fmt(sn0):>15}{'100':>8}")
    for m in months:
        ff = factors(m, drv)
        a, b = cost_at(base, ff, "старый"), cost_at(base, ff, "новый")
        print(f"{m:<9}{fmt(a):>15}{fmt(a / so0 * 100):>8}{fmt(b):>15}{fmt(b / sn0 * 100):>8}")
    if byq:
        print("\nИНДЕКС ДОХОДОВ: медиана цены часа в контрактах, тыс. ₽ без НДС")
        for k in sorted(byq):
            v = byq[k]
            print(f"  {k}: {fmt(st.median(v) / 1000)} ({len(v)} шт.)" + (f", индекс {fmt(st.median(v) / rev0 * 100)}"
                                                                      if rev0 else ""))
    print("\nСВЕТОФОР по видам работ (медиана цены за последние 12 месяцев против себестоимости сейчас):")
    for k, light, m, n in sorted(lights, key=lambda x: "🔴🟡🟢".index(x[1])):
        print(f"  {light} {k}: {fmt(m, 0)} тыс. ₽ ({n} шт.) — "
              + ("ниже себестоимости даже старого парка" if light == "🔴" else
                 "покрывает старый парк, но не новый вертолёт" if light == "🟡" else "покрывает новый вертолёт"))
    if scis_red:
        print("  🔴 расходы нового вертолёта росли 3 месяца подряд — проверь, растут ли цены новых контрактов")
    stale = [d for d in DRIVERS if not any(r["драйвер"] == d for r in drv)]
    if stale:
        print(f"Нет данных по драйверам: {', '.join(stale)} — их вклад принят без изменений.")


# ---------- прогноз ----------

def scen():
    if not FSCEN.exists():
        FSCEN.write_text(SCEN_DEFAULT, encoding="utf-8")
    rows = read(FSCEN)
    years = [k for k in rows[0] if re.fullmatch(r"\d{4}", k or "")]
    out = {}
    for r in rows:
        out.setdefault(r["сценарий"], {})[r["показатель"]] = {y: r[y] for y in years}
        out[r["сценарий"]].setdefault("_пояснения", {})[r["показатель"]] = r.get("пояснение", "")
    return out, years


def growth(expr, infl):
    e = str(expr).replace(" ", "").replace(",", ".")
    m = re.fullmatch(r"инф([+-]\d+(?:\.\d+)?)?", e)
    return infl + (float(m.group(1)) if m and m.group(1) else 0) if m else float(e)


def forecast_rows(to=2030):
    """{сценарий: [(год, себестоимость старого, нового, цена часа)]}, сценарии, годы, цена 2025, контракты."""
    base = base_rows()
    con = contracts() if FCON.exists() else []
    sc, years = scen()
    years = [y for y in years if int(y) <= to]
    price0 = st.median([c["цена_без_ндс"] for c in con if c["дата"][:4] == "2025"]) / 1000 if con else None
    kr_base = KR_BASE
    res = {}
    for name, p in sc.items():
        f = {d: 1.0 for d in DRIVERS + ["лизинг"]}
        price = price0
        rows = [("2025", cost_at(base, f, "старый"), cost_at(base, f, "новый"), price)]
        for y in years:
            infl = float(str(p["инфляция"][y]).replace(",", "."))
            for d in ("керосин", "зарплата", "тоир", "аэропорт"):
                f[d] *= 1 + growth(p[d][y], infl) / 100
            f["инфляция"] *= 1 + infl / 100
            f["лизинг"] = 1 + lease_effect(kr_base, float(str(p["ключевая"][y]).replace(",", ".")))
            if price is not None:
                price *= 1 + growth(p["цена часа"][y], infl) / 100
            rows.append((y, cost_at(base, f, "старый"), cost_at(base, f, "новый"), price))
        res[name] = rows
    return res, sc, years, price0, con


def cmd_forecast(*opts):
    o = dict(zip(opts[::2], opts[1::2]))
    to = int(o.get("--to", 2030))
    res, sc, years, price0, con = forecast_rows(to)
    print(f"ПРОГНОЗ ЛЁТНОГО ЧАСА Ми-8 до {to} года, тыс. ₽ без НДС — ОЦЕНКА, не факт")
    print(f"Лизинг нового вертолёта пересчитан по ключевой ставке сценария (база — {fmt(KR_BASE, 2)}%; "
          "договоры, заключённые в этом году).")
    for name, rows in res.items():
        print(f"\nСценарий «{name}»")
        print(f"{'год':<6}{'старый':>9}{'новый':>9}{'цена часа':>11}{'разрыв к новому':>17}  сигнал")
        for y, a, b, pr in rows:
            gap = (pr - b) if pr is not None else None
            sig = "" if pr is None else "🔴" if pr < a else "🟡" if pr < b else "🟢"
            print(f"{y:<6}{fmt(a):>9}{fmt(b):>9}{fmt(pr):>11}{(fmt(gap) + ' (' + pct(gap / b) + ')') if gap is not None else 'н/д':>17}  {sig}")
        notes = sc[name]["_пояснения"]
        print("  допущения: " + "; ".join(f"{k} — {', '.join(str(sc[name][k][y]) for y in years)}"
                                          + (f" ({notes[k]})" if notes.get(k) else "")
                                          for k in sc[name] if k != "_пояснения"))
    if price0 is not None:
        print(f"\nЦена часа 2025 года — медиана {len(con)} госконтрактов за 2025 год ({fmt(price0)} тыс. ₽ без НДС), "
              "все виды работ; по видам — python3 fh.py prices.")
    if "--xlsx" in o:
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        for name, rows in res.items():
            ws = wb.create_sheet(name[:30])
            ws.append(["Год", "Себестоимость, старый парк", "Себестоимость, новый вертолёт", "Цена часа (медиана)",
                       "Разрыв к новому"])
            for i, (y, a, b, pr) in enumerate(rows, 2):
                ws.append([int(y), round(a, 2), round(b, 2), round(pr, 2) if pr is not None else None,
                           f"=D{i}-C{i}" if pr is not None else None])
            ws.column_dimensions["B"].width = ws.column_dimensions["C"].width = 28
        wb.save(o["--xlsx"])
        print(f"Excel: {o['--xlsx']}")


# ---------- калькулятор сделки ----------

def deal(p):
    """Годы сделки: выручка, расходы, платёж, EBITDA, DSCR, поток после налога (как в модели лизинга Ми-8МТВ-1)."""
    H = p["hours"] * 12
    price, adv = p["price"] * 1e6, p["advance"] / 100
    fin = price * (1 - adv)
    r = p["lease"] / 100
    pay = fin * r / (1 - (1 + r) ** -p["term"]) if r else fin / p["term"]
    out = []
    for t in range(int(p["term"])):
        rev = p["rate"] * (1 + p["rate_idx"] / 100) ** t * H
        cost = (p["opex"] * (1 + p["opex_idx"] / 100) ** t + p["mro"] * (1 + p["mro_idx"] / 100) ** t) * H
        ebitda = rev - cost
        ebt = ebitda - pay
        tax = max(0.0, ebt) * p["tax"] / 100
        out.append({"год": t + 1, "выручка": rev, "расходы": cost, "платёж": pay, "ebitda": ebitda,
                    "dscr": ebitda / pay if pay else None, "поток": ebt - tax})
    return out, pay, price * adv


def npv(p):
    rows, _, adv = deal(p)
    w = p["wacc"] / 100
    return -adv + sum(x["поток"] / (1 + w) ** x["год"] for x in rows)


def solve(fn, lo, hi):
    """Корень монотонной функции на [lo, hi] (бисекция); None — нет смены знака."""
    flo, fhi = fn(lo), fn(hi)
    if flo * fhi > 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if fn(lo) * fn(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def cmd_calc(*opts):
    o = dict(zip(opts[::2], opts[1::2]))
    g = lambda k, d=None: float(str(o[k]).replace(",", ".").replace(" ", "")) if k in o else d
    p = {"opex": g("--opex"), "mro": g("--mro", 0.0), "hours": g("--hours"), "rate": g("--rate"),
         "price": g("--price"), "lease": g("--lease"), "term": g("--term"), "advance": g("--advance", 0.0),
         "wacc": g("--wacc", 15.0), "dscr": g("--dscr", 1.2), "rate_idx": g("--rate-idx", 5.0),
         "opex_idx": g("--opex-idx", 5.0), "mro_idx": g("--mro-idx", 12.0), "tax": g("--tax", 20.0)}
    miss = [k for k in ("opex", "hours", "rate", "price", "lease", "term") if p[k] is None]
    if miss:
        sys.exit("Не хватает: " + ", ".join("--" + k for k in miss))
    rows, pay, adv = deal(p)
    H = p["hours"] * 12
    unit = p["opex"] + p["mro"]
    lease_h = pay / H
    breakeven = unit + lease_h
    min_dscr_rate = unit + p["dscr"] * lease_h
    fair = solve(lambda x: npv({**p, "rate": x}), 1.0, 1e8)
    v = npv(p)
    dmin = min((x["dscr"], x["год"]) for x in rows)
    print(f"СДЕЛКА: налёт {fmt(p['hours'], 1)} ч/мес ({fmt(H, 0)} ч/год), ставка часа {fmt(p['rate'], 0)} ₽, "
          f"вертолёт {fmt(p['price'], 0)} млн ₽, лизинг {fmt(p['lease'], 1)}% на {fmt(p['term'], 0)} лет, аванс "
          f"{fmt(p['advance'], 0)}%")
    print(f"\nСЕБЕСТОИМОСТЬ ЧАСА, 1-й год, ₽: расходы {fmt(p['opex'], 0)} + ТОиР {fmt(p['mro'], 0)} + лизинг "
          f"{fmt(lease_h, 0)} = {fmt(breakeven, 0)}")
    print(f"  а) окупает ли тариф: ставка {fmt(p['rate'], 0)} ₽ — "
          + (f"запас {fmt(p['rate'] - breakeven, 0)} ₽ ({pct((p['rate'] - breakeven) / breakeven, 1)}) к безубыточности"
             if p["rate"] >= breakeven else f"НИЖЕ безубыточности на {fmt(breakeven - p['rate'], 0)} ₽ "
                                            f"({pct((breakeven - p['rate']) / breakeven, 1)})"))
    print(f"     минимальная ставка для DSCR {fmt(p['dscr'], 2)} в 1-й год: {fmt(min_dscr_rate, 0)} ₽")
    print(f"     DSCR: 1-й год {fmt(rows[0]['dscr'], 2)}, минимум {fmt(dmin[0], 2)} в {dmin[1]}-й год"
          + (" ⚠️ расходы растут быстрее ставки" if p["mro_idx"] > p["rate_idx"] or p["opex_idx"] > p["rate_idx"] else ""))
    print(f"  б) справедливая ставка для заказчика (NPV = 0 при WACC {fmt(p['wacc'], 1)}% за {fmt(p['term'], 0)} лет, "
          f"ставка растёт на {fmt(p['rate_idx'], 1)}% в год): {fmt(fair, 0) if fair else 'н/д'} ₽ в 1-й год")
    print(f"     NPV при текущей ставке: {fmt(v / 1e6, 1)} млн ₽")
    # налёт 30–80 ч/мес
    print("\nСТАВКА ПРИ РАЗНОМ НАЛЁТЕ (1-й год, ₽ за час; ТОиР и расходы на час — как в базе)")
    print(f"{'ч/мес':>6}{'безубыточность':>16}{'для DSCR':>11}{'DSCR':>7}")
    for hh in (30, 40, 50, 57.7, 60, 70, 80):
        lh = pay / (hh * 12)
        d1 = (p["rate"] - unit) * hh * 12 / pay
        print(f"{fmt(hh, 1):>6}{fmt(unit + lh, 0):>16}{fmt(unit + p['dscr'] * lh, 0):>11}{fmt(d1, 2):>7}")
    # факторы влияния ±20%
    keys = [("ставка часа", "rate"), ("налёт", "hours"), ("цена вертолёта", "price"), ("ставка лизинга", "lease"),
            ("расходы без ТОиР", "opex"), ("ТОиР", "mro"), ("рост ТОиР в год", "mro_idx"), ("WACC", "wacc")]
    eff = []
    for label, k in keys:
        if not p[k]:
            continue
        lo, hi = npv({**p, k: p[k] * 0.8}), npv({**p, k: p[k] * 1.2})
        dl = min(x["dscr"] for x in deal({**p, k: p[k] * 0.8})[0])
        dh = min(x["dscr"] for x in deal({**p, k: p[k] * 1.2})[0])
        eff.append((abs(hi - lo), label, lo, hi, dl, dh))
    print("\nЧТО СИЛЬНЕЕ ВСЕГО ДВИГАЕТ РЕЗУЛЬТАТ (каждый фактор −20% / +20%, остальное без изменений)")
    print(f"{'фактор':<20}{'NPV −20%':>10}{'NPV +20%':>10}{'мин.DSCR −20%':>15}{'+20%':>7}")
    for _, label, lo, hi, dl, dh in sorted(eff, reverse=True):
        print(f"{label:<20}{fmt(lo / 1e6, 0):>10}{fmt(hi / 1e6, 0):>10}{fmt(dl, 2):>15}{fmt(dh, 2):>7}")
    print("NPV — млн ₽. Допущения: ставка и расходы индексируются (ставка "
          f"{fmt(p['rate_idx'], 1)}%, расходы {fmt(p['opex_idx'], 1)}%, ТОиР {fmt(p['mro_idx'], 1)}% в год); "
          f"налог {fmt(p['tax'], 0)}% с прибыли после платежа, убыток не переносится; поток — на конец года.")
    if "--xlsx" in o:
        write_calc_xlsx(p, rows, o["--xlsx"])


def write_calc_xlsx(p, rows, out):
    """Лист «Сделка»: допущения в ячейках и расчёт по годам формулами — меняешь допущение, Excel пересчитывает."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter as L
    wb = Workbook()
    ws = wb.active
    ws.title = "Сделка"
    ws["A1"], ws["A1"].font = "Лётный час: расчёт сделки (меняйте жёлтые ячейки — формулы пересчитаются)", Font(bold=True)
    inp = [("Ставка часа, ₽", p["rate"]), ("Налёт, ч/мес", p["hours"]), ("Расходы без ТОиР, ₽/ч", p["opex"]),
           ("ТОиР, ₽/ч", p["mro"]), ("Цена вертолёта, млн ₽", p["price"]), ("Аванс, %", p["advance"]),
           ("Ставка лизинга, %", p["lease"]), ("Срок, лет", p["term"]), ("WACC, %", p["wacc"]),
           ("Рост ставки, %/год", p["rate_idx"]), ("Рост расходов, %/год", p["opex_idx"]),
           ("Рост ТОиР, %/год", p["mro_idx"]), ("Налог, %", p["tax"]), ("Целевой DSCR", p["dscr"])]
    for i, (lab, val) in enumerate(inp, 3):
        ws.cell(row=i, column=1, value=lab)
        ws.cell(row=i, column=2, value=val)
    ws["A18"], ws["B18"] = "Платёж лизинга, ₽/год", "=B7*1000000*(1-B8/100)*(B9/100)/(1-(1+B9/100)^(-B10))"
    ws["A19"], ws["B19"] = "Себестоимость часа, 1-й год", "=B5+B6+B18/(B4*12)"
    ws["A20"], ws["B20"] = "Ставка для целевого DSCR", "=B5+B6+B16*B18/(B4*12)"
    labels = ["Год", "Выручка", "Расходы", "EBITDA", "Платёж", "DSCR", "Налог", "Поток после налога"]
    for j, lab in enumerate(labels):
        ws.cell(row=22 + j, column=1, value=lab)
    for t in range(len(rows)):
        c = L(t + 2)
        ws[f"{c}22"] = t + 1
        ws[f"{c}23"] = f"=$B$3*(1+$B$12/100)^({c}22-1)*$B$4*12"
        ws[f"{c}24"] = f"=($B$5*(1+$B$13/100)^({c}22-1)+$B$6*(1+$B$14/100)^({c}22-1))*$B$4*12"
        ws[f"{c}25"] = f"={c}23-{c}24"
        ws[f"{c}26"] = "=$B$18"
        ws[f"{c}27"] = f"={c}25/{c}26"
        ws[f"{c}28"] = f"=MAX(0,{c}25-{c}26)*$B$15/100"
        ws[f"{c}29"] = f"={c}25-{c}26-{c}28"
    last = L(len(rows) + 1)
    ws["A31"], ws["B31"] = "NPV, ₽", f"=-B7*1000000*B8/100+NPV(B11/100,B29:{last}29)"
    ws["A32"], ws["B32"] = "Минимальный DSCR", f"=MIN(B27:{last}27)"
    for r in range(3, 17):
        ws.cell(row=r, column=2).font = Font(color="000000")
        ws.cell(row=r, column=2).fill = __import__("openpyxl").styles.PatternFill("solid", fgColor="FFF2CC")
    ws.column_dimensions["A"].width = 30
    wb.save(out)
    print(f"\nExcel: {out} (допущения в жёлтых ячейках, расчёт — формулами)")


if __name__ == "__main__":
    cmds = {"import": cmd_import, "contracts": cmd_contracts, "base": cmd_base, "prices": cmd_prices,
            "driver": cmd_driver, "index": cmd_index, "forecast": cmd_forecast, "calc": cmd_calc}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]](*sys.argv[2:])
