"""Финансовый блок карточки: таблица отчётности, расчётные показатели, суммы заимствований из новостей.

Все показатели считаются формулами здесь, а не моделью ИИ, — чтобы в справке не было выдуманных чисел.
"""
import csv
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
FIELDS = ["выручка", "чистая_прибыль", "ebitda", "активы", "обязательства", "капитал", "долг", "денежные_средства"]
LABELS = {"выручка": "Выручка", "чистая_прибыль": "Чистая прибыль", "ebitda": "EBITDA", "активы": "Активы",
          "обязательства": "Обязательства", "капитал": "Капитал", "долг": "Долг (кредиты и займы)",
          "денежные_средства": "Денежные средства"}


def num(s):
    s = (s or "").strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def load(company_names):
    """Строки finance.csv по компании: сначала группа, потом юрлицо; МСФО раньше РСБУ."""
    path = BASE / "finance.csv"
    if not path.exists():
        return []
    names = [n.lower() for n in company_names]
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if any(n in (r.get("компания") or "").lower() for n in names):
                r = {k: (v or "").strip() for k, v in r.items()}
                for k in FIELDS:
                    r[k] = num(r.get(k))
                rows.append(r)
    return rows


def metrics(r):
    """Расчётные показатели строки. Долг/EBITDA — только для годовых данных (для квартала EBITDA неполная)."""
    out = {}
    if r["долг"] is not None and r["денежные_средства"] is not None:
        out["чистый_долг"] = r["долг"] - r["денежные_средства"]
    nd = out.get("чистый_долг", r["долг"])
    if r["тип"].lower() in ("год", "ltm") and nd is not None and r["ebitda"]:
        out["долг_ebitda"] = nd / r["ebitda"]
    if r["обязательства"] is not None and r["активы"]:
        out["обязательства_к_активам"] = r["обязательства"] / r["активы"]
    if r["чистая_прибыль"] is not None and r["выручка"]:
        out["рентабельность"] = r["чистая_прибыль"] / r["выручка"]
    return out


def tables(rows):
    """Группирует строки в таблицы «стандарт · уровень · тип периода», по 2 последних периода для сравнения."""
    by = {}
    for r in rows:
        by.setdefault((r["стандарт"], r["уровень"], r["тип"]), []).append(r)
    order = sorted(by, key=lambda k: (k[0] != "МСФО", k[1] != "группа", k[2] != "год"))
    return [(k, by[k][-2:]) for k in order]


AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(трлн|млрд|млн)\.?\s*(?:руб|₽|рублей)", re.I)
BORROW = re.compile(r"облигац|кредит|займ|заем|заём|размещ|выпуск бумаг|кредитн линии|кредитную линию|синдицир", re.I)
PLAN = re.compile(r"план|намерен|может разместить|собирается|готовит|откроет книгу|зарегистрир|утвердил програм|лимит", re.I)


def to_bln(value, unit):
    v = float(value.replace(",", "."))
    return v * 1000 if unit.lower() == "трлн" else v / 1000 if unit.lower() == "млн" else v


def flat(groups):
    """Сквозной сюжет состоит из нескольких сюжетов — суммы ищем в каждом."""
    for g in groups:
        yield from (g["items"] if g.get("thread") else [g])


def borrowings(groups):
    """Суммы новых заимствований из сюжетов про облигации и кредиты. Берётся первая сумма в заголовке
    (если её нет — в тексте); дубли уже склеены в сюжеты. Результат — к проверке по первоисточнику."""
    out = []
    for g in flat(groups):
        pub, src, title, summ, url = g["main"][:5]
        text = f"{title} {summ}"
        if not BORROW.search(text):
            continue
        m = AMOUNT.search(title) or AMOUNT.search(summ)
        if not m:
            continue
        out.append({"date": pub, "title": title, "url": url, "src": src,
                    "bln": to_bln(m.group(1), m.group(2)), "status": "план" if PLAN.search(text) else "факт"})
    return out


COURT = re.compile(r"иск|взыска|требовани|претензи|банкрот", re.I)


def claims(groups):
    """Сумма исков с известной суммой (первая сумма в заголовке или тексте). К проверке по картотеке дел."""
    total = 0.0
    for g in flat(groups):
        title, summ = g["main"][2], g["main"][3]
        if COURT.search(f"{title} {summ}"):
            m = AMOUNT.search(title) or AMOUNT.search(summ)
            if m:
                total += to_bln(m.group(1), m.group(2))
    return total
