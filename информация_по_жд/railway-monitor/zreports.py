#!/usr/bin/env python3
"""Четыре отдельных отчёта по типу вагона (0 токенов): ① прогноз ставки, ② факторы ставки, ③ стоимость вагона и её
факторы, ④ сделка в лизинг и выход из неё (калькулятор, предложения с обоснованием по рынку).

  python3 zreports.py <вагон> [rate|factors|value|deal|all] [--scenario base|opt|pess] [--guest] [--dir saved/<раздел>]
  вагон: inno|gon|kr158|kr138|hop_grain|hop_grain_inno|fit80|fit40|fit60

Файлы: <папка>/ГГГГ-ММ-ДД_<отчёт>_<вагон>.md → PDF: ~/pw/bin/python zreport.py <файл.md>. Цифры — только из моделей
(zrate.py, ztypes.py, zvagon.py, zdeal.py), отчёт их не пересчитывает.
"""
import argparse
import math
import re
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import zdeal  # noqa: E402
import zhelp  # noqa: E402

FILE = {"inno": "полувагон_инновационный", "gon": "полувагон_типовой", "kr158": "крытый_158", "kr138": "крытый_138",
        "hop_grain": "зерновоз", "hop_grain_inno": "зерновоз_инновационный", "fit80": "фитинговая_платформа_80",
        "fit40": "фитинговая_платформа_40", "fit60": "фитинговая_платформа_60"}
SECTION = {"inno": "poluvagony", "gon": "poluvagony", "kr158": "krytye", "kr138": "krytye", "hop_grain": "zerno",
           "hop_grain_inno": "zerno", "fit80": "fiting", "fit40": "fiting", "fit60": "fiting"}
RATE_KEYS = ("Коротко", "Октябрь — декабрь", "2027–2030", "Что нужно", "Точность")
FACTOR_KEYS = ("Из чего складывается", "Цена фактора", "Все факторы", "За чем следить", "События рынка")
LABEL = {"coal": "Уголь", "load": "Погрузка на сети", "turn": "Оборот вагона", "stroy": "Стройка (щебень)",
         "buy": "Выпуск новых вагонов", "off": "Списание вагонов", "pace": "Темп IV квартала", "mortgage": "Ипотека год назад",
         "export": "Экспорт зерна", "park": "Парк зерновозов", "balance": "Баланс контейнеров и платформ"}
FKEYS = {"gon": ["pace", "coal", "load", "stroy", "buy", "off"], "kr": ["stroy", "mortgage", "pace"],
         "hop": ["export", "park", "pace"], "fit": ["balance", "pace"]}


def fkeys(w):
    return FKEYS["gon" if w in ("gon", "inno") else w[:2] if w.startswith("kr") else w[:3]]


def model_md(w, sc, guest):
    """Полный отчёт модели ставки (тот же, что /prognoz)."""
    ns = argparse.Namespace(wagon=w, scenario=sc, set="", guest=guest, json=False, out=None, pick=None, year=None)
    if w in ("gon", "inno"):
        import zrate as Z
        D = Z.load()
        res = {w: {s: Z.forecast(D, w, s) for s in Z.SCN}}
        return Z.report(D, ns, res, {})
    import ztypes as T
    return T.report(w, ns)[1]


def split(md):
    parts = re.split(r"(?m)^(?=## )", md)
    return parts[0], parts[1:]


def pick(md, keys, title):
    head, secs = split(md)
    head = re.sub(r"(?m)^# .*$", f"# {title}", head, count=1)
    keep = [s for s in secs if any(k in s.splitlines()[0] for k in keys)]
    i = 0
    for j, s in enumerate(keep):  # нумерация разделов заново: 1, 2, 3 … («Коротко» — без номера)
        if re.match(r"## \d+\. ", s):
            i += 1
            keep[j] = re.sub(r"^## \d+\. ", f"## {i}. ", s)
    return head + "".join(keep)


def help_md(w):
    L = ["## Откуда значения факторов и где смотреть свежие цифры", ""]
    for k, h in zhelp.for_wagon(w, fkeys(w)).items():
        L += [f"**{LABEL.get(k, k)}** — {h['what']}", "", f"- Почему такие значения в сценариях: {h['why']}",
              f"- Где смотреть: {h['where']}; разумный диапазон {h['range']}."] + ([f"- Сейчас: {h['now']}."] if h["now"] else []) + [""]
    L += ["<small>Свои значения — команда /prognoz или мини-приложение, «Изменить допущения». Источник у каждой цифры — "
          "в скобках; «допущение модели» — значение без внешнего источника.</small>", ""]
    return "\n".join(L)


def n(v, d=1):
    return zdeal.n(v, d)


def value_md(w, sc):
    """③ Стоимость вагона: новый и б/у по сценариям, доход к цене, что двигает цену, чувствительность."""
    nm = zdeal.NAMES[w]
    P = {s: zdeal.model(w, s) for s in zdeal.SCN}
    lvl0, p0, note = P["base"]
    L = [f"# {nm}: стоимость вагона и что на неё влияет", "",
         "<small>млн ₽ без НДС · оценка рынка, не инвестиционная рекомендация</small>", "", "## Коротко", "",
         "| Сценарий ставки | 2026 | 2027 | 2028 | 2029 | 2030 |", "|---|---|---|---|---|---|"]
    for s in ("base", "opt", "pess"):
        L.append(f"| {zdeal.SCN[s]}, новый | " + " | ".join(n(P[s][1][y], 2) for y in range(2026, 2031)) + " |")
    L.append("| Базовый, годовой доход к цене нового, % | " + " | ".join(
        n(lvl0[y] * 365 / (p0[y] * 1e6) * 100) for y in range(2026, 2031)) + " |")
    L += ["", "## 1. Б/у по возрасту (базовый сценарий)", "", "| Возраст | Коэффициент к новому | 2026 | 2030 |", "|---|---|---|---|"]
    for age in (3, 8, 14, 19, 25):
        k = zdeal.age_k(age)
        L.append(f"| {age} {'года' if age % 10 in (2, 3, 4) and age not in (12, 13, 14) else 'лет'} | {n(k, 2)} | {n(p0[2026] * k, 2)} | {n(p0[2030] * k, 2)} |")
    L += ["", "<small>Плавная кривая износа: между точками возраста — по прямой; после 25 лет — к цене лома.</small>", "",
          "## 2. Что двигает цену вагона", ""]
    if w in ("gon", "inno") or w.startswith("kr"):
        import zvagon
        V = zvagon.load()
        typ = w if w in ("gon", "inno") else "kr158"
        c = V["price_model"][typ]
        _, fit26 = zvagon.price_path(V, typ, {y: lvl0[y] for y in range(2027, 2031)})
        gap = (V["market_2026"][typ] / fit26 - 1) * 100
        L += [f"- **Средняя ставка аренды за 3 года** — +10% к ставке дают около {n(c['b'] * 10)}% к цене нового "
              f"(эластичность {n(c['b'], 2)} по 2010–2025 гг.).",
              f"- **Себестоимость и инфляция** — тренд {n((math.exp(c['c']) - 1) * 100)}% в год (металл, комплектующие).",
              f"- **Рынок 2026 г. против модели:** рынок {n(V['market_2026'][typ], 2)} млн ₽, модель {n(fit26, 2)} млн ₽ — "
              f"{'рынок выше модели на ' + n(gap, 0) + '%: вагон дорог относительно ставки' if gap > 5 else 'рынок ниже модели на ' + n(-gap, 0) + '%: вагон дёшев относительно ставки' if gap < -5 else 'рынок около модели'}; "
              "разрыв закрывается за 3 года."]
    else:
        import ztypes
        Pm = ztypes.value(w, sc)["P"]
        cap26 = lvl0[2026] * 365 / (p0[2026] * 1e6) * 100
        if Pm["model"] == "rate":
            L.append(f"- **Средняя ставка за 3 года** — +10% к ставке дают около {n(Pm['b'] * 10)}% к цене нового "
                     f"(эластичность {n(Pm['b'], 2)}); себестоимость — +{n(Pm['trend'])}% в год.")
        else:
            L.append(f"- **Себестоимость завода** — цена не следует за ставкой; базовый рост +{n(Pm['trend']['base'])}% в год, "
                     f"оптимистичный +{n(Pm['trend']['opt'])}%, пессимистичный {n(Pm['trend']['pess'])}%.")
        lo, hi = Pm["cap_range"]
        L.append(f"- **Годовой доход к цене** в 2026 г. — {n(cap26)}% при коридоре 2010–2024 гг. {n(lo)}–{n(hi)}%: "
                 + ("ниже коридора — вагон дорог относительно ставки." if cap26 < lo else
                    "выше коридора — вагон дёшев относительно ставки." if cap26 > hi else "внутри коридора — цена в норме."))
    L += ["- **Возраст** — см. таблицу 1.",
          "- **Предложение новых вагонов** — выпуск падает: за 7 месяцев 2026 г. — 23,6 тыс. вагонов всех типов, −31% к году "
          "(данные ОВС, dp.ru 21.08.2026); хопперы январь–август — 1,2 тыс., −52% (ОПЖТ, Ведомости 14.09.2026). Меньше "
          "выпуск — заводы держат цены, но и ставка растёт медленнее предложения.", "", f"<small>Цена 2026 г.: {note}.</small>", ""]
    L += ["## 3. Чувствительность (базовый сценарий, 2030 г.)", "", "| Если | Цена нового 2030 г. |", "|---|---|",
          f"| базовый сценарий ставки | {n(p0[2030], 2)} |", f"| оптимистичный сценарий ставки | {n(P['opt'][1][2030], 2)} |",
          f"| пессимистичный сценарий ставки | {n(P['pess'][1][2030], 2)} |", "",
          "<small>Подготовлено по открытым источникам и данным участников рынка. Выводы — оценка рынка.</small>"]
    return "\n".join(L) + "\n"


def build(w, what, sc, guest, folder):
    folder = Path(folder or BASE / "saved" / SECTION[w])
    folder.mkdir(parents=True, exist_ok=True)
    nm, d, out = zdeal.NAMES[w], date.today().isoformat(), []
    todo = ["rate", "factors", "value", "deal"] if what == "all" else [what]
    md_full = model_md(w, sc, guest) if {"rate", "factors"} & set(todo) else ""
    for t in todo:
        if t == "rate":
            md, f = pick(md_full, RATE_KEYS, f"{nm}: прогноз ставки аренды до 2030"), "прогноз_ставки"
        elif t == "factors":
            md, f = pick(md_full, FACTOR_KEYS, f"{nm}: факторы ставки — что и насколько её меняет") + "\n" + help_md(w), "факторы_ставки"
        elif t == "value":
            md, f = value_md(w, sc), "стоимость_вагона"
        else:
            a = zdeal.args(["run", "--wagon", w, "--scenario", sc] + (["--guest"] if guest else []))
            md, f = zdeal.report(a)[1], "сделка_и_выход"
        p = folder / f"{d}_{f}_{FILE[w]}.md"
        p.write_text(md, encoding="utf-8")
        out.append(p)
        print(f"Файл: {p}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wagon", choices=list(FILE))
    ap.add_argument("what", nargs="?", default="all", choices=["rate", "factors", "value", "deal", "all"])
    ap.add_argument("--scenario", default="base", choices=list(zdeal.SCN))
    ap.add_argument("--guest", action="store_true")
    ap.add_argument("--dir")
    x = ap.parse_args()
    build(x.wagon, x.what, x.scenario, x.guest, x.dir)
