#!/usr/bin/env python3
"""Рабочая модель ставки аренды полувагона (обычный и инновационный) на 2027–2030 гг.: факторы → ставка.
Без нейросети (0 токенов). Одни и те же цифры — у ЖДуши (/prognoz), в Excel и в мини-приложении.

  python3 zrate.py run                         все сценарии, оба типа вагона, вклад факторов (базовый)
  python3 zrate.py run --wagon inno --scenario opt --set coal=2.5,off=35
                                               свои значения факторов: одно число — на все годы 2027–2030,
                                               четыре через «;» — по годам: coal=1;2;2;2
  python3 zrate.py track coal=2.9 load=1.2 stroy=-3.7 netoff=0.7 workcut=5.1
                                               где рынок сейчас: какой сценарий подтверждают фактические значения
  python3 zrate.py run --guest                 гостю: без помесячных ставок
  python3 zrate.py run --json                  для мини-приложения

Модель: изменение средней ставки за год, % = тренд + β × баланс парка (+ γ × стройка для обычного вагона).
Баланс парка = (уголь + погрузка) / 2 + замедление оборота вагона − изменение парка на сети за прошлый год, %.
Коэффициенты считаются заново при каждом запуске по истории 2011–2025 гг. (метод наименьших квадратов),
точность — проверкой на прошлых годах (модель учится только на годах до проверяемого).
Пессимистичный сценарий — средняя ставка прошлого года + инфляция (прогноз Минэкономразвития).
Данные — forecast/rate_data.json (только на сервере).
"""
import argparse
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from zmodel import backtest, ols  # noqa: E402  — тот же расчёт регрессии и проверки, что в /prognoz

DATA = BASE / "forecast" / "rate_data.json"
YEARS = [2027, 2028, 2029, 2030]
WAGONS = {"inno": "Инновационный полувагон", "gon": "Обычный полувагон"}
SCN = {"pess": "Пессимистичный", "base": "Базовый", "opt": "Оптимистичный"}
FACTORS = {  # ключ → (название, единица)
    "coal": ("Добыча угля", "% за год"), "load": ("Погрузка на сети", "% за год"),
    "turn": ("Замедление оборота вагона", "% за год"), "stroy": ("Стройка (щебень)", "% за год"),
    "buy": ("Выпуск новых полувагонов", "тыс. в год"), "off": ("Списание полувагонов", "тыс. в год"),
}


def load():
    if not DATA.exists():
        sys.exit(f"Нет {DATA} — данные модели не загружены на сервер.")
    return json.loads(DATA.read_text(encoding="utf-8"))


def n(v):
    return f"{round(v):,}".replace(",", " ")


def sg(v, d=0):
    s = f"{v:+.{d}f}".replace(".", ",")
    return s.replace("-", "−")


def fit(D, w):
    """Коэффициенты и проверка на прошлых годах. y — изменение средней ставки, % (логарифм)."""
    r = {int(k): v for k, v in D["rates"][w].items()}
    h = {k: {int(y): v for y, v in s.items()} for k, s in D["hist"].items()}
    names = D["model"][w]
    rows = {}
    for t in sorted(r):
        if t - 1 not in r or t < 2011:
            continue
        bal = h["coal"].get(t), h["load"].get(t), h["turn"].get(t), h["park"].get(t)
        if None in bal:
            continue
        xs = [(bal[0] + bal[1]) / 2 + bal[2] - bal[3]] + [h[f].get(t) for f in names[1:]]
        if None in xs:
            continue
        rows[t] = (100 * math.log(r[t] / r[t - 1]), xs)
    b, r2 = ols(list(rows.values()))
    return {"b": dict(zip(["const"] + names, b)), "r2": r2, "bt": backtest(rows), "n": len(rows)}


def scenario(D, scen, ov):
    """Значения факторов 2026–2030 (2026 — только для парка: влияет на ставку 2027 г.)."""
    s = {k: list(v) for k, v in D["scenarios"]["opt" if scen == "opt" else "base"].items()}
    for k, v in ov.items():
        vals = [float(x) for x in str(v).split(";")]
        s[k][1:] = vals * 4 if len(vals) == 1 else vals[:4]
    return s


def start(D, w, scen):
    """Средняя ставка 2026 г.: 9 месяцев факт (пропуски — по прямой), IV квартал — по сценарию."""
    m = list(D["month_2026"][w])
    for i, v in enumerate(m):
        if v is None:
            a = max(j for j in range(i) if m[j] is not None)
            z = min(j for j in range(i, len(m)) if m[j] is not None)
            m[i] = m[a] + (m[z] - m[a]) * (i - a) / (z - a)
    last, step = m[-1], D["q4_step"][w] if scen == "opt" else 0
    q4 = [last + step * k for k in (1, 2, 3)]
    return sum(m + q4) / 12, m, q4


def forecast(D, w, scen, ov):
    f = fit(D, w)
    avg26, months, q4 = start(D, w, "base" if scen == "pess" else scen)
    lvl, parts = {2026: avg26}, {}
    if scen == "pess":
        for y in YEARS:
            lvl[y] = lvl[y - 1] * (1 + D["inflation"][str(y)] / 100)
            parts[y] = {"Инфляция": lvl[y] - lvl[y - 1]}
        return {"lvl": lvl, "parts": parts, "fit": f, "months": months, "q4": q4}
    s = scenario(D, scen, ov)
    park = [D["park_start"]]
    for b_, o in zip(s["buy"], s["off"]):
        park.append(park[-1] + b_ - o)
    b = f["b"]
    for i, y in enumerate(YEARS, start=1):
        pct = {k: 100 * math.log(1 + s[k][i] / 100) for k in ("coal", "load", "turn", "stroy")}
        pk = 100 * math.log(park[i] / park[i - 1])  # изменение парка за прошлый год
        comp = {"Уголь": b["balance"] * pct["coal"] / 2, "Погрузка на сети": b["balance"] * pct["load"] / 2,
                "Оборот вагона": b["balance"] * pct["turn"], "Парк: выпуск − списания": -b["balance"] * pk,
                "Стройка (щебень)": b.get("stroy", 0) * pct["stroy"], "Тренд": b["const"]}
        ch = sum(comp.values())
        lvl[y] = lvl[y - 1] * math.exp(ch / 100)
        parts[y] = {k: (lvl[y] - lvl[y - 1]) * c / ch for k, c in comp.items() if abs(c) > 1e-9} if ch else {}
    return {"lvl": lvl, "parts": parts, "fit": f, "months": months, "q4": q4, "scen": s}


def unit_price(D, w):
    """Сколько ₽/сут даёт изменение фактора на единицу — от последнего фактического уровня."""
    b, L = fit(D, w)["b"], D["month_2026"][w][-1]
    rub = lambda pct: L * (math.exp(pct / 100) - 1)
    return L, {"Уголь +1%": rub(b["balance"] * 0.5), "Погрузка +1%": rub(b["balance"] * 0.5),
               "Списаний больше выпуска на 10 тыс.": rub(-b["balance"] * 100 * math.log(1 - 10 / D["park_start"])),
               "Стройка +1%": rub(b.get("stroy", 0)), "Оборот вагона медленнее на 1%": rub(b["balance"])}


def report(D, a, res):
    W = [a.wagon] if a.wagon != "all" else ["inno", "gon"]
    L = ["# Прогноз ставки аренды полувагона 2027–2030", "",
         f"<small>Средняя ставка за год, ₽ за вагон в сутки без НДС · данные рынка на {D['as_of']} · "
         f"оценка рынка, не инвестиционная рекомендация</small>", ""]
    for w in W:
        L += [f"## {WAGONS[w]}", "", "| Сценарий | 2026 | " + " | ".join(map(str, YEARS)) + " |", "|---|" + "---|" * 5]
        for sc in ("pess", "base", "opt"):
            r = res[w][sc]["lvl"]
            L.append(f"| {SCN[sc]} | " + " | ".join(n(r[y]) for y in [2026] + YEARS) + " |")
        L.append("")
    w0 = W[0]
    avg, m, q4 = start(D, w0, "base")
    L += ["## От чего отталкиваемся", ""]
    if a.guest:
        L += [f"Средняя ставка 2026 г. — **{n(avg)} ₽** ({WAGONS[w0].lower()}): факт девяти месяцев рынка, IV квартал — "
              f"на уровне сентября ({n(m[-1])} ₽). Первое полугодие было слабым, поэтому средняя ниже текущей ставки.", ""]
    else:
        L += ["| 2026 | " + " | ".join(["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен"]) + " | IV кв. |",
              "|---|" + "---|" * 10]
        for w in W:
            av, mm, qq = start(D, w, "base")
            L.append(f"| {WAGONS[w]} | " + " | ".join(n(x) for x in mm) + f" | {n(qq[0])} |")
        L += ["", "Май–июль — по прямой между апрелем и августом. IV квартал: базовый и пессимистичный — на уровне "
              f"сентября; оптимистичный — сентябрьский рост продолжается ({'; '.join(f'{WAGONS[w].lower()} +{D['q4_step'][w]} ₽ в месяц' for w in W)}).", ""]
    sc = a.scenario if a.scenario != "pess" else "base"
    for w in W:
        r = res[w][sc]
        L += [f"## Из чего складывается ставка: {WAGONS[w].lower()}, {SCN[sc].lower()} сценарий", "",
              "| Фактор, ₽/сут | " + " | ".join(map(str, YEARS)) + " |", "|---|" + "---|" * 4]
        keys = list(dict.fromkeys(k for y in YEARS for k in r["parts"][y]))
        for k in keys:
            L.append(f"| {k} | " + " | ".join(sg(r["parts"][y].get(k, 0)) for y in YEARS) + " |")
        L.append("| **Ставка** | " + " | ".join(f"**{n(r['lvl'][y])}**" for y in YEARS) + " |")
        L += ["", "Значения факторов: " + "; ".join(
            f"{FACTORS[k][0].lower()} {', '.join(sg(v, 1) if k not in ('buy', 'off') else n(v) for v in r['scen'][k][1:])}"
            for k in ("coal", "load", "stroy", "buy", "off")) + " (2027–2030).", ""]
    L += ["## Цена фактора", "", "| Изменение | " + " | ".join(WAGONS[w] for w in W) + " |", "|---|" + "---|" * len(W)]
    up = {w: unit_price(D, w) for w in W}
    for k in up[W[0]][1]:
        L.append(f"| {k} | " + " | ".join(sg(up[w][1][k]) + " ₽" if abs(up[w][1][k]) >= 0.5 else "связи нет" for w in W) + " |")
    L += ["", f"<small>От текущего уровня: {'; '.join(f'{WAGONS[w].lower()} {n(up[w][0])} ₽' for w in W)}. "
          "Уголь, погрузка, оборот и парк входят в модель одним показателем — балансом парка, поэтому одно и то же "
          "движение не считается дважды.</small>", ""]
    L += ["## За чем следить кредитору", "", "| Показатель | Пессимистичный | Базовый | Оптимистичный | Где смотреть |",
          "|---|---|---|---|---|"] + [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |" for r in D["watch"]]
    L += ["", "**Без оценки в рублях** (нет рядов за прошлые годы или связь со ставкой не подтвердилась): "
          + "; ".join(D["watch_extra"]) + ".", ""]
    L += ["## Точность", ""]
    for w in W:
        f = res[w]["base"]["fit"]
        bt = f["bt"] or {}
        L.append(f"- {WAGONS[w]}: на прошлых годах направление угадано в {round(bt.get('hit', 0) * 100)}% лет "
                 f"({bt.get('years', 0)} проверочных), средняя ошибка ±{bt.get('error', '—')}% в год. "
                 f"Модель объясняет {round(f['r2'] * 100)}% колебаний ставки за {f['n']} лет.")
    L += ["- 2029–2030 гг. — ориентир: ошибка за год накапливается.", "",
          "<small>Подготовлено по открытым источникам. Выводы — оценка рынка.</small>"]
    return "\n".join(L) + "\n"


def run(a):
    D = load()
    ov = {}
    for kv in filter(None, (a.set or "").split(",")):
        k, _, v = kv.partition("=")
        if k.strip() not in FACTORS:
            sys.exit(f"Нет фактора {k}. Есть: {', '.join(FACTORS)}")
        ov[k.strip()] = v.strip()
    W = [a.wagon] if a.wagon != "all" else ["inno", "gon"]
    res = {w: {sc: forecast(D, w, sc, ov if sc == a.scenario else {}) for sc in SCN} for w in W}
    if a.json:
        out = {w: {sc: {str(y): round(v) for y, v in r["lvl"].items()} for sc, r in res[w].items()} for w in W}
        out["parts"] = {w: {str(y): {k: round(v) for k, v in res[w][a.scenario]["parts"][y].items()} for y in YEARS} for w in W}
        print(json.dumps(out, ensure_ascii=False))
        return
    md = report(D, a, res)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Файл: {a.out}")
    else:
        print(md)


def track(a):
    """Фактические значения факторов → какой сценарий они подтверждают и какую ставку 2027 г. дают."""
    D = load()
    got = {}
    for kv in a.values:
        k, _, v = kv.partition("=")
        got[k.strip()] = float(v)
    bands = D["track"]
    L = ["| Показатель | Сейчас | Сценарий |", "|---|---|---|"]
    votes = []
    for k, v in got.items():
        if k not in bands:
            L.append(f"| {k} | {sg(v, 1)} | нет порогов |")
            continue
        lo, hi = bands[k]["pess_below"], bands[k]["opt_from"]
        sc = "pess" if v < lo else "opt" if v >= hi else "base"
        votes.append(sc)
        L.append(f"| {bands[k]['name']} | {sg(v, 1)} {bands[k]['unit']} | {SCN[sc]} |")
    if votes:
        best = max(votes.count(k) for k in SCN)
        top = [SCN[k] for k in SCN if votes.count(k) == best]
        L += ["", f"Рынок ближе всего к сценарию: **{' / '.join(top)}** ({best} из {len(votes)} показателей"
              + (" у каждого — рынок между сценариями" if len(top) > 1 else "") + ")."]
    print("\n".join(L))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--wagon", default="all", choices=["inno", "gon", "all"])
    r.add_argument("--scenario", default="base", choices=list(SCN))
    r.add_argument("--set", default="")
    r.add_argument("--guest", action="store_true")
    r.add_argument("--json", action="store_true")
    r.add_argument("--out")
    t = sub.add_parser("track")
    t.add_argument("values", nargs="+")
    x = ap.parse_args()
    run(x) if x.cmd == "run" else track(x)
