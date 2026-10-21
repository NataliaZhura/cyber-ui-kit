#!/usr/bin/env python3
"""Рабочая модель ставки аренды полувагона (обычный и инновационный): IV квартал 2026 г. по месяцам и 2027–2030 гг.
Без нейросети (0 токенов). Одни и те же цифры — у ЖДуши (/prognoz), в Excel и в мини-приложении.

  python3 zrate.py menu                        меню /prognoz одним сообщением (бот присылает дословно)
  python3 zrate.py run --pick "2 1 4"          ответ на меню: вагон, период, сценарий [, показатели крытых];
                                               крытые (4, 5) — передаются в zmodel.py
  python3 zrate.py run                         все сценарии, оба типа вагона, вклад факторов, что нужно для 1 500 / 1 560
  python3 zrate.py run --wagon inno --scenario opt --set coal=2.5,off=35,pace=-1.5
                                               свои значения: годовые факторы — одно число на 2027–2030 или четыре через «;»
                                               (coal=1;2;2;2); pace — изменение рабочего парка в IV кв. 2026, % в месяц
  python3 zrate.py track coal=2.9 load=1.2 stroy=-3.7 netoff=0.7 workcut=5.1
                                               где рынок сейчас: какой сценарий подтверждают фактические значения
  python3 zrate.py run --guest                 гостю: без помесячных ставок января–сентября
  python3 zrate.py run --json                  для мини-приложения

Модель 2 — от уровня выхода, а не от средней за год:
  IV кв. 2026: ставка меняется вслед за рабочим парком полувагонов: −1% парка → +e% ставки (e — по 2026 г.).
  2027–2030: ставка на конец года = ставка на конец прошлого года × e^(изменение по факторам), средняя за год — середина
  между началом и концом года. Изменение, % = тренд + β × баланс парка (+ γ × стройка для обычного вагона);
  баланс = (уголь + погрузка)/2 + замедление оборота − изменение парка на сети за прошлый год. β, γ, тренд — по истории
  2011–2025 гг., точность — проверкой на прошлых годах. Ограничение: средняя выше рекорда 2024 г. (с инфляцией) →
  заводы наращивают выпуск на 10 тыс. вагонов со следующего года. Пессимистичный 2027–2030 — средняя прошлого года +
  инфляция (Минэкономразвития). Данные — forecast/rate_data.json (только на сервере).
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
Q4 = ["октябрь", "ноябрь", "декабрь"]
WAGONS = {"inno": "Инновационный полувагон", "gon": "Обычный полувагон"}
SCN = {"pess": "Пессимистичный", "base": "Базовый", "opt": "Оптимистичный"}
OWN = "Свой"
AVG = {  # пометки: что за средняя и за какой период
    "month": "ставка месяца — середина диапазона ставок рынка за месяц",
    "2026": "средняя за 2026 г. (январь–декабрь: январь–сентябрь — факт, октябрь–декабрь — прогноз; сумма 12 месяцев / 12)",
    "year": "средняя за год (январь–декабрь) — середина между ставкой на начало года (декабрь прошлого) и на конец "
            "года (декабрь); пессимистичный — средняя прошлого года + инфляция",
    "end": "на конец года — ставка декабря",
}
PICK_W = {"1": "gon", "2": "inno", "3": "all", "4": "kr158", "5": "kr138", "6": "hop_grain", "7": "hop_grain_inno",
          "8": "fit80", "9": "fit40", "10": "fit60"}
PICK_Y = {"1": None, "2": 2026, "3": 2027, "4": 2028, "5": 2029, "6": 2030}
PICK_S = {"1": "base", "2": "opt", "3": "pess", "4": "all", "5": "own"}
FACTORS = {  # ключ → (название, единица)
    "coal": ("Добыча и погрузка угля", "% за год"), "load": ("Погрузка на сети", "% за год"),
    "turn": ("Замедление оборота вагона", "% за год"), "stroy": ("Стройка (щебень)", "% за год"),
    "buy": ("Выпуск новых полувагонов", "тыс. в год"), "off": ("Списание полувагонов", "тыс. в год"),
    "pace": ("Рабочий парк в IV кв. 2026", "% в месяц"),
}


def load():
    if not DATA.exists():
        sys.exit(f"Нет {DATA} — данные модели не загружены на сервер.")
    return json.loads(DATA.read_text(encoding="utf-8"))


def n(v):
    return f"{round(v):,}".replace(",", " ")


def f1(v):
    return f"{v:.1f}".replace(".", ",")


def sg(v, d=0):
    return f"{v:+.{d}f}".replace(".", ",").replace("-", "−")


def fit(D, w):
    """Годовая модель: коэффициенты и проверка на прошлых годах. y — изменение средней ставки, % (логарифм)."""
    r = {int(k): v for k, v in D["rates"][w].items()}
    h = {k: {int(y): v for y, v in s.items()} for k, s in D["hist"].items()}
    names = D["model"][w]
    rows = {}
    for t in sorted(r):
        if t - 1 not in r or t < 2011:
            continue
        c, lo, tu, pk = (h[k].get(t) for k in ("coal", "load", "turn", "park"))
        if None in (c, lo, tu, pk):
            continue
        xs = [(c + lo) / 2 + tu - pk] + [h[f].get(t) for f in names[1:]]
        if None not in xs:
            rows[t] = (100 * math.log(r[t] / r[t - 1]), xs)
    b, r2 = ols(list(rows.values()))
    return {"b": dict(zip(["const"] + names, b)), "r2": r2, "bt": backtest(rows), "n": len(rows)}


def elasticity(D, w):
    """Сколько % ставки даёт сокращение рабочего парка на 1% — по 2026 г. (два отрезка, среднее)."""
    p, r = D["workpark"], D["work_rates"][w]
    e = [math.log(r["aug"] / r[a]) / -math.log(p["aug"] / p[a]) for a in ("dec", "jan")]
    return sum(e) / 2


def months(D, w):
    """Январь–сентябрь 2026; пропуски — из базы наблюдений, если нет — по прямой."""
    m = list(D["month_2026"][w])
    try:  # пропуски — из базы наблюдений (выпуски партнёра, zobs.py), если они там есть
        import zobs
        item = {"gon": "gon69_spot", "inno": "gon75_spot"}[w]
        obs = {int(r["month"][5:]): (float(r["low"]) + float(r["high"])) / 2 for r in zobs.read()
               if r["item"] == item and r["month"].startswith("2026-") and r["source"] in ("partner", "survey")}
        m = [obs.get(i + 1) if v is None else v for i, v in enumerate(m)]
    except Exception:  # noqa: BLE001 — нет базы наблюдений: как раньше, по прямой
        pass
    for i, v in enumerate(m):
        if v is None:
            a = max(j for j in range(i) if m[j] is not None)
            z = min(j for j in range(i, len(m)) if m[j] is not None)
            m[i] = m[a] + (m[z] - m[a]) * (i - a) / (z - a)
    return m


def scenario(D, scen, ov):
    s = {k: list(v) if isinstance(v, list) else v for k, v in D["scenarios"][scen].items()}
    for k, v in ov.items():
        if k == "pace":
            s["pace"] = float(v)
            continue
        vals = [float(x) for x in str(v).split(";")]
        s[k][1:] = vals * 4 if len(vals) == 1 else vals[:4]
    return s


def forecast(D, w, scen, ov=None):
    s = scenario(D, scen, ov or {})
    e, m = elasticity(D, w), months(D, w)
    last = m[-1]
    q4 = [last * math.exp(-e * s["pace"] / 100 * k) for k in (1, 2, 3)]
    dec = q4[-1]  # декабрь без поправки на события: от него — 2027–2030 (события 2027 г. — отдельной строкой)
    try:
        import zevents
        ev = zevents.effects("gon")  # контейнеры в полувагонах, закрытия угольных портов (forecast/market_params.json)
    except Exception:  # noqa: BLE001 — без параметров рынка прогноз считается как раньше
        ev = None
    if ev and ev["comp"]:
        q4 = [x * k for x, k in zip(q4, ev["q4"])]
    q4_rub = [q4[0] - last, q4[1] - q4[0], q4[2] - q4[1]]
    avg26 = (sum(m) + sum(q4)) / 12
    lvl, end, parts, cap_hit = {2026: avg26}, {2026: dec}, {}, []
    f = fit(D, w)
    if scen == "pess":
        for y in YEARS:
            lvl[y] = lvl[y - 1] * (1 + D["inflation"][str(y)] / 100)
            parts[y] = {"Инфляция": lvl[y] - lvl[y - 1]}
        return {"lvl": lvl, "end": {}, "parts": parts, "fit": f, "months": m, "q4": q4, "q4_rub": q4_rub, "e": e,
                "scen": s, "cap": cap_hit, "events": ev}
    b, buy = f["b"], list(s["buy"])
    park = [D["park_start"]]
    rec = D["record"][w]
    for i, y in enumerate(YEARS, start=1):
        park.append(park[-1] + buy[i - 1] - s["off"][i - 1])  # конец года y−1
        pct = {k: 100 * math.log(1 + s[k][i] / 100) for k in ("coal", "load", "turn", "stroy")}
        pk = 100 * math.log(park[i] / park[i - 1])
        comp = {"Уголь": b["balance"] * pct["coal"] / 2, "Погрузка на сети": b["balance"] * pct["load"] / 2,
                "Оборот вагона": b["balance"] * pct["turn"], "Парк: выпуск − списания": -b["balance"] * pk,
                "Стройка (щебень)": b.get("stroy", 0) * pct["stroy"], "Тренд издержек": b["const"]}
        if ev and i == 1:
            comp.update(ev["comp"])  # события рынка 2026 г. — % к изменению ставки 2027 г.
        ch = sum(comp.values())
        end[y] = end[y - 1] * math.exp(ch / 100)
        lvl[y] = math.sqrt(end[y - 1] * end[y])
        parts[y] = {k: (end[y] - end[y - 1]) * c / ch for k, c in comp.items() if abs(c) > 1e-9} if ch else {}
        infl = math.prod(1 + D["inflation"].get(str(k), 4) / 100 for k in range(2025, y + 1))
        if lvl[y] > rec * infl and i < len(buy):  # выше рекорда — заводы наращивают выпуск со следующего года
            buy[i] += 10
            cap_hit.append(y)
    return {"lvl": lvl, "end": end, "parts": parts, "fit": f, "months": m, "q4": q4, "q4_rub": q4_rub, "e": e,
            "scen": s, "cap": cap_hit, "events": ev}


def need(D, w, target):
    """Какое сокращение рабочего парка нужно, чтобы ставка дошла до target: за 1 месяц и за 3 месяца."""
    e, last = elasticity(D, w), months(D, w)[-1]
    pct = math.log(target / last) / e * 100
    return pct, D["workpark"]["aug"] * pct / 100


def unit_price(D, w):
    """₽/сут за изменение фактора на единицу — от текущего уровня (сентябрь)."""
    b, L, e = fit(D, w)["b"], months(D, w)[-1], elasticity(D, w)
    rub = lambda pct: L * (math.exp(pct / 100) - 1)
    return L, {"Рабочий парк −1% (≈5,5 тыс. вагонов), за месяц": rub(e),
               "Уголь +1% за год": rub(b["balance"] * 0.5), "Погрузка на сети +1% за год": rub(b["balance"] * 0.5),
               "Оборот вагона медленнее на 1%": rub(b["balance"]),
               "Списаний больше выпуска на 10 тыс. (парк −1,5%)": rub(-b["balance"] * 100 * math.log(1 - 10 / D["park_start"])),
               "Стройка +1% за год": rub(b.get("stroy", 0)), "Тренд издержек, за год": rub(b["const"])}


def label(sc, ov=None):
    return SCN.get(sc) or OWN


def brief(a, res, W, ov):
    """Коротко по запросу: выбранный вагон, период, сценарий — с пометкой, что за ставка."""
    pick = getattr(a, "pick_scen", None)
    keys = [k for k in (["own", "base"] if "own" in res[W[0]] else [pick] if pick in SCN else ["base", "opt", "pess"])]
    y = getattr(a, "year", None)
    L = ["## Коротко", ""]
    if "own" in res[W[0]]:
        L += ["Свой сценарий — базовый с вашими значениями: " + ", ".join(
            f"{FACTORS[k][0][0].lower() + FACTORS[k][0][1:]} {v.replace(';', ' / ').replace('.', ',').replace('-', '−')} "
            f"{FACTORS[k][1]}" for k, v in ov.items()) + ".", ""]
    if y == 2026:
        head = "| Вагон, сценарий | октябрь* | ноябрь* | декабрь* | средняя за 2026 г.** |"
        row = lambda r: " | ".join(n(q) for q in r["q4"]) + f" | {n(r['lvl'][2026])}"
        notes = [f"* {AVG['month']}.", f"** {AVG['2026']}."]
    elif y:
        head = f"| Вагон, сценарий | средняя за {y} г.* | на конец {y} г.** | средняя {y} г. к средней 2026 г. |"
        row = lambda r: (f"{n(r['lvl'][y])} | {n(r['end'][y]) if r['end'] else '—'} | "
                         f"{sg((r['lvl'][y] / r['lvl'][2026] - 1) * 100)}%")
        notes = [f"* {AVG['year']}.", f"** {AVG['end']}; у пессимистичного не считается."]
    else:
        head = "| Вагон, сценарий | декабрь 2026* | средняя за 2026 г.** | средняя за 2027 г.*** | средняя за 2030 г.*** |"
        row = lambda r: f"{n(r['q4'][-1])} | {n(r['lvl'][2026])} | {n(r['lvl'][2027])} | {n(r['lvl'][2030])}"
        notes = [f"* {AVG['month']}.", f"** {AVG['2026']}.", f"*** {AVG['year']}."]
    L += [head, "|---" * head.count(" | ") + "|---|"]
    for w in W:
        for sc in keys:
            L.append(f"| {WAGONS[w]}, {label(sc).lower()} | {row(res[w][sc])} |")
    return L + [""] + [f"<small>{x}</small>  " for x in notes] + [""]


def report(D, a, res, ov=None):
    W = [a.wagon] if a.wagon != "all" else ["inno", "gon"]
    L = ["# Ставка аренды полувагона: IV квартал 2026 и прогноз до 2030", "",
         f"<small>₽ за вагон в сутки без НДС · данные рынка на {D['as_of']} · оценка рынка, не инвестиционная "
         "рекомендация</small>", ""] + brief(a, res, W, ov or {}) + ["## 1. Октябрь — декабрь 2026", ""]
    for w in W:
        r0 = res[w]["base"]
        L += [f"**{WAGONS[w]}** — сентябрь {n(r0['months'][-1])} ₽. Рабочий парк −1% → ставка +{f1(r0['e'])}%.", "",
              "| Сценарий | Рабочий парк, % в месяц | " + " | ".join(f"{m}*" for m in Q4) + " | средняя за 2026 г.** |",
              "|---|---|---|---|---|---|"]
        for sc in res[w]:
            r = res[w][sc]
            L.append(f"| {label(sc)} | {sg(r['scen']['pace'], 2)} | " + " | ".join(
                f"{n(q)} ({sg(d)})" for q, d in zip(r["q4"], r["q4_rub"])) + f" | {n(r['lvl'][2026])} |")
        L += ["", f"<small>* {AVG['month']}; в скобках — изменение к прошлому месяцу. ** {AVG['2026']}.</small>", ""]
    if not a.guest:
        L += ["| 2026, январь–сентябрь | " + " | ".join(["янв", "фев", "мар", "апр", "май*", "июн*", "июл*", "авг", "сен"]) + " |",
              "|---|" + "---|" * 9] + [f"| {WAGONS[w]} | " + " | ".join(n(x) for x in res[w]["base"]["months"]) + " |" for w in W]
        L += ["", "<small>* по прямой между апрелем и августом.</small>", ""]
    w0 = "inno" if "inno" in W else W[0]
    L += ["## 2. Что нужно, чтобы ставка была выше 1 500 и 1 560", "",
          f"{WAGONS[w0]}, от ставки сентября {n(res[w0]['base']['months'][-1])} ₽ (ставка месяца) — сокращение рабочего парка "
          f"({f1(D['workpark']['aug'])} тыс. в августе; в августе −6,4 тыс. за месяц):", "",
          "| Цель | Сокращение рабочего парка | За 1 месяц | За 3 месяца, в месяц |", "|---|---|---|---|"]
    for t in D["targets"]:
        pct, k = need(D, w0, t)
        one = ("возможно — темп августа" if k <= 6.4 else f"маловероятно — в {f1(k / 6.4)} раза быстрее августа")
        L.append(f"| {n(t)} ₽ | −{f1(pct)}% (−{f1(k)} тыс. вагонов) | {one} | −{f1(k / 3)} тыс. в месяц — "
                 f"{'быстрее' if k / 3 > 6.4 else 'медленнее'} августа |")
    L += ["", "Другие пути к росту (те же рубли, см. «Цена фактора»): экспорт угля в осенний пик, дальнейшее списание "
          "старых вагонов, удорожание ремонта и отстоя (собственники не сдают дешевле).", ""]
    L += ["## 3. 2027–2030: средняя ставка за год (январь–декабрь)", ""]
    for w in W:
        L += [f"**{WAGONS[w]}**", "", "| Сценарий | 2026* | " + " | ".join(f"{y}**" for y in YEARS) + " |", "|---|" + "---|" * 5]
        for sc in res[w]:
            r = res[w][sc]
            L.append(f"| {label(sc)} | " + " | ".join(n(r["lvl"][y]) for y in [2026] + YEARS) + " |" +
                     (f" ⚠ выше рекорда в {', '.join(map(str, r['cap']))} г. — заложен рост выпуска" if r["cap"] else ""))
        L.append("")
    L += [f"<small>* {AVG['2026']}. ** {AVG['year']}.</small>", ""]
    sc = "own" if "own" in res[W[0]] else a.scenario if a.scenario != "pess" else "base"
    for w in W:
        r = res[w][sc]
        L += [f"## 4. Из чего складывается рост: {WAGONS[w].lower()}, {label(sc).lower()}", "",
              "Изменение ставки за год (от конца прошлого года к концу этого), ₽/сут:", "",
              "| Фактор | " + " | ".join(map(str, YEARS)) + " |", "|---|" + "---|" * 4]
        for k in dict.fromkeys(k for y in YEARS for k in r["parts"][y]):
            L.append(f"| {k} | " + " | ".join(sg(r["parts"][y].get(k, 0)) for y in YEARS) + " |")
        L.append("| Ставка на конец года (декабрь) | " + " | ".join(n(r["end"][y]) for y in YEARS) + " |")
        L.append("| **Средняя за год (январь–декабрь)** | " + " | ".join(f"**{n(r['lvl'][y])}**" for y in YEARS) + " |")
        L += ["", "Факторы: " + "; ".join(
            f"{FACTORS[k][0].lower()} {', '.join(sg(v, 1) if k not in ('buy', 'off') else n(v) for v in r['scen'][k][1:])}"
            for k in ("coal", "load", "stroy", "buy", "off")) + " (2027–2030).", ""]
    up = {w: unit_price(D, w) for w in W}
    L += ["## 5. Цена фактора", "", "| Изменение | " + " | ".join(WAGONS[w] for w in W) + " |", "|---|" + "---|" * len(W)]
    for k in up[W[0]][1]:
        L.append(f"| {k} | " + " | ".join(sg(up[w][1][k]) + " ₽" if abs(up[w][1][k]) >= 0.5 else "связи нет" for w in W) + " |")
    L += ["", f"<small>От ставки сентября (ставка месяца): {'; '.join(f'{WAGONS[w].lower()} {n(up[w][0])} ₽' for w in W)}.</small>", ""]
    L += ["## 6. Все факторы: макро и микро", "", "| Фактор | Тип | Сейчас | Влияние на ставку | Последствия | В модели |",
          "|---|---|---|---|---|---|"] + [f"| {' | '.join(row)} |" for row in D["catalog"]]
    L += ["", "## 7. За чем следить кредитору", "", "| Показатель | Пессимистичный | Базовый | Оптимистичный | Где смотреть |",
          "|---|---|---|---|---|"] + [f"| {' | '.join(row)} |" for row in D["watch"]]
    L += ["", "## 8. Точность", ""]
    for w in W:
        f, bt = res[w]["base"]["fit"], res[w]["base"]["fit"]["bt"] or {}
        L.append(f"- {WAGONS[w]}: годовая модель на прошлых годах угадала направление в {round(bt.get('hit', 0) * 100)}% лет "
                 f"({bt.get('years', 0)} проверочных), средняя ошибка по проверочным годам ±{bt.get('error', '—')}% в год; объясняет "
                 f"{round(f['r2'] * 100)}% колебаний за {f['n']} лет.")
    L += ["- IV квартал 2026 зависит от одного допущения — темпа рабочего парка; таблица 1 показывает три темпа.",
          "- 2029–2030 гг. — ориентир: ошибка накапливается.", "",
          "<small>Подготовлено по открытым источникам. Выводы — оценка рынка.</small>"]
    return "\n".join(L) + "\n"


def menu():
    """Меню /prognoz: полувагоны — эта модель, крытые — zmodel.py (показатели ④ — только для крытых)."""
    fs = ""
    try:
        import zmodel
        Z = zmodel.load()
        star = set(Z["default"]["kr"])
        fs = " · ".join(f"{i} {'★ ' if f in star else ''}{Z['factors'][f].get('short', Z['factors'][f]['name'])}"
                        for i, f in enumerate(zmodel.PICK_F, 1))
    except (SystemExit, Exception):  # noqa: BLE001 — нет данных крытых: меню без пункта ④
        pass
    print("Прогноз ставок аренды до 2030 — ответь одной строкой, например: 2 1 4\n\n"
          "① Вагон: 1 полувагон обычный · 2 полувагон инновационный · 3 оба полувагона · 4 крытый 158 м³ · 5 крытый 138 м³ · "
          "6 хоппер-зерновоз · 7 зерновоз инновационный · 8 фитинговая платформа 80' · 9 платформа 40' · 10 платформа 60'\n"
          "② Период: 1 весь 2026–2030 · 2 — 2026 (октябрь–декабрь по месяцам) · 3 — 2027 · 4 — 2028 · 5 — 2029 · 6 — 2030\n"
          "③ Сценарий: 1 базовый · 2 оптимистичный · 3 пессимистичный · 4 все · 5 свой "
          "(после цифр напиши, что изменить: «уголь 2, списания 35, рабочий парк −1,5»)\n"
          + (f"④ Только для крытых, по желанию — свой набор показателей, до 3 через запятую (без ④ — рабочая модель):\n{fs}\n" if fs else "")
          + "\nСтавки — средние за год (январь–декабрь); 2026 — 9 месяцев факта + 3 месяца прогноза.\n"
          "Готовый документ (PDF) — ответь «П».")


def run_kr(a, w, year, sc, rest):
    """Крытые, зерновоз, платформы: рабочая модель ztypes.py (три сценария, как у полувагона);
    крытые со своим набором показателей (пункт ④) — zmodel.py."""
    import subprocess
    if "".join(rest) in ("", "0"):
        cmd = [sys.executable, str(BASE / "ztypes.py"), "run", "--wagon", w, "--scenario", sc if sc in SCN else "base"]
        cmd += (["--set", a.set] if a.set else []) + (["--guest"] if a.guest else []) + (["--out", a.out] if a.out else [])
        sys.exit(subprocess.run(cmd).returncode)
    if sc == "opt":
        sys.exit("Со своим набором показателей оптимистичного сценария нет — выбери 1 базовый, 3 пессимистичный или 5 свой.")
    cmd = [sys.executable, str(BASE / "zmodel.py"), "run", "--wagon", w, "--scenario", "pess" if sc == "pess" else "base"]
    cmd += ["--year", str(year)] if year else []
    f = "".join(rest)
    if f not in ("", "0"):
        import zmodel
        try:
            cmd += ["--factors", ",".join(zmodel.PICK_F[int(x) - 1] for x in f.split(",") if x)]
        except (ValueError, IndexError):
            sys.exit(f"Показатели крытых — номера от 1 до {len(zmodel.PICK_F)} через запятую.")
    cmd += (["--set", a.set] if a.set else []) + (["--guest"] if a.guest else []) + (["--out", a.out] if a.out else [])
    sys.exit(subprocess.run(cmd).returncode)


def apply_pick(a):
    parts = a.pick.replace(";", " ").split()
    if len(parts) < 3 or parts[0] not in PICK_W or parts[1] not in PICK_Y or parts[2] not in PICK_S:
        sys.exit("Ответ — 3 числа: вагон 1–10, период 1–6, сценарий 1–5 (например: 2 1 4).")
    w, a.year, sc = PICK_W[parts[0]], PICK_Y[parts[1]], PICK_S[parts[2]]
    if w not in WAGONS and w != "all":
        run_kr(a, w, a.year, sc, parts[3:] if w.startswith("kr") else [])
    if sc == "own" and not a.set:
        sys.exit("Для своего сценария напиши, что изменить (с 2027 г.): уголь, погрузка, стройка — % за год; выпуск, "
                 "списания — тыс. вагонов в год; рабочий парк в IV кв. 2026 — % в месяц.")
    a.wagon, a.pick_scen = w, sc
    a.scenario = sc if sc in SCN else "base"


def run(a):
    if a.pick:
        apply_pick(a)  # крытые уходят в zmodel.py до загрузки данных полувагонов
    D = load()
    ov = {}
    for kv in filter(None, (a.set or "").split(",")):
        k, _, v = kv.partition("=")
        if k.strip() not in FACTORS:
            sys.exit(f"Нет фактора {k}. Есть: {', '.join(FACTORS)}")
        ov[k.strip()] = v.strip()
    W = [a.wagon] if a.wagon != "all" else ["inno", "gon"]
    res = {w: {sc: forecast(D, w, sc) for sc in SCN} for w in W}
    for w in W:  # свои значения — отдельной строкой «Свой» (от выбранного сценария, по умолчанию базового)
        if ov:
            res[w]["own"] = forecast(D, w, a.scenario if a.scenario != "pess" else "base", ov)
    if a.json:
        out = {w: {sc: {"year": {str(y): round(v) for y, v in r["lvl"].items()}, "q4": [round(x) for x in r["q4"]]}
                   for sc, r in res[w].items()} for w in W}
        print(json.dumps(out, ensure_ascii=False))
        return
    md = report(D, a, res, ov)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Файл: {a.out}")
    else:
        print(md)


def track(a):
    """Фактические значения факторов → какой сценарий они подтверждают."""
    D = load()
    bands, votes = D["track"], []
    L = ["| Показатель | Сейчас | Сценарий |", "|---|---|---|"]
    for kv in a.values:
        k, _, v = kv.partition("=")
        k, v = k.strip(), float(v)
        if k not in bands:
            L.append(f"| {k} | {sg(v, 1)} | нет порогов |")
            continue
        sc = "pess" if v < bands[k]["pess_below"] else "opt" if v >= bands[k]["opt_from"] else "base"
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
    sub.add_parser("menu")
    r = sub.add_parser("run")
    r.add_argument("--pick", help="ответ на меню: вагон период сценарий [показатели крытых]")
    r.add_argument("--year", type=int, choices=[2026] + YEARS)
    r.add_argument("--wagon", default="all", choices=["inno", "gon", "all"])
    r.add_argument("--scenario", default="base", choices=list(SCN))
    r.add_argument("--set", default="")
    r.add_argument("--guest", action="store_true")
    r.add_argument("--json", action="store_true")
    r.add_argument("--out")
    t = sub.add_parser("track")
    t.add_argument("values", nargs="+")
    x = ap.parse_args()
    menu() if x.cmd == "menu" else run(x) if x.cmd == "run" else track(x)
