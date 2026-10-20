#!/usr/bin/env python3
"""Прогноз ставки аренды по типам вагонов (кроме полувагона — он в zrate.py) по той же схеме, что у полувагона. 0 токенов.

  python3 ztypes.py run --wagon kr158|kr138|hop_grain|hop_grain_inno|fit80|fit40|fit60 [--scenario base|opt|pess] [--set stroy=2;3;3;3,mortgage=10] [--guest] [--out файл.md]
  python3 ztypes.py run --wagon kr158 --json        для мини-приложения и «Обзора рынка»

Схема (как у полувагона, zrate.py):
  IV кв. текущего года — от ставки последнего месяца (база наблюдений zobs.py) с месячным темпом сценария;
  средняя за год — январь–сентябрь факт (пропуски — по прямой) + октябрь–декабрь прогноз;
  2027–2030 — ставка на конец года = конец прошлого года × e^(изменение по факторам), средняя за год — середина года;
  изменение, % = тренд + Σ β × фактор; β и тренд — по истории 2011–2025 гг. (forecast/model_data.json), проверка на
  прошлых годах (модель учится только на годах до проверяемого). Пессимистичный 2027–2030 — средняя прошлого года +
  инфляция как верхняя граница: по факторам пессимистичного сценария, но не выше этого уровня. Вклад каждого
  фактора — в ₽ к изменению ставки за год.
Типы: крытый 158/138 м³; хоппер-зерновоз (инновационный = типовой × 1,18); фитинговые платформы 80' (основной
ряд), 40' и 60' — по своим месячным ставкам, годовая динамика — как у 80'.
"""
import argparse
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import zmodel  # noqa: E402  — история факторов и регрессия (те же, что в /prognoz)
import zobs  # noqa: E402  — ставки месяцев

YEARS = [2027, 2028, 2029, 2030]
SCN = {"pess": "Пессимистичный", "base": "Базовый", "opt": "Оптимистичный"}
MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
INFL = {2027: 3.975, 2028: 3.963, 2029: 3.955, 2030: 3.951}  # прогноз Минэкономразвития, % (как в zrate)

# Тип → годовая модель, месячные ставки (показатель zobs), сценарии.
# Крытые: модель и base/pess значения факторов — model_data.json (как в /prognoz); opt — допущение «стройка и ипотека
# восстанавливаются». Зерновоз и платформа: модель — по рядам forecast/types_data.json (презентации, оценка INFOLine);
# фактор = Σ знак × изменение ряда (% лог.) со сдвигом lag лет; сценарии — % за год на 2027–2030 (допущения, меняются --set).
# Уровень ставки — по месячным данным участников рынка (zobs), годовые изменения — по модели (источники различаются по
# уровню, совпадают по направлению). pace — темп ставки в месяц в IV кв. текущего года.
TDATA = BASE / "forecast" / "types_data.json"
GRAIN_F = {"export": ("Экспорт зерна (сезон, начатый год назад)", [("export", 1, 1)]),
           "park": ("Парк зерновозов год назад", [("park", 1, -1)])}
GRAIN_S = {"base": {"export": [0, 0, 0, 0], "park": [2, 2, 2, 2]},
           "opt": {"export": [8, 8, 8, 8], "park": [1, 1, 1, 1]},
           "pess": {"export": [-10, -5, 0, 0], "park": [3, 3, 2, 2]}}
FIT_F = {"balance": ("Контейнеры минус рост парка платформ", [("teu", 0, 1), ("park", 0, -1)])}
FIT_S = {"base": {"balance": [0, 0, 0, 0]}, "opt": {"balance": [4, 4, 4, 4]}, "pess": {"balance": [-6, -4, -2, 0]}}
TYPES = {
    "kr158": {"name": "Крытый вагон 158 м³", "model": "kr", "factors": ["stroy", "mortgage"], "month_item": "kr158",
              "pace": {"pess": -1.0, "base": 0.4, "opt": 1.5},
              "opt": {"stroy": [2, 3, 3, 3], "mortgage": [15, 15, 12, 10]}},
    "kr138": {"name": "Крытый вагон 138 м³", "model": "kr", "factors": ["stroy", "mortgage"], "month_item": "kr138",
              "pace": {"pess": -1.0, "base": 0.4, "opt": 1.5},
              "opt": {"stroy": [2, 3, 3, 3], "mortgage": [15, 15, 12, 10]}},
    "hop_grain": {"name": "Хоппер-зерновоз", "data": "hop_grain", "factors": GRAIN_F, "month_item": "hop_grain",
                  "pace": {"pess": -3.0, "base": 0.5, "opt": 2.0}, "scen": GRAIN_S},
    "hop_grain_inno": {"name": "Хоппер-зерновоз инновационный", "data": "hop_grain", "factors": GRAIN_F,
                       "month_item": "hop_grain", "ratio": 1.18, "pace": {"pess": -3.0, "base": 0.5, "opt": 2.0},
                       "scen": GRAIN_S},
    "fit80": {"name": "Фитинговая платформа 80'", "data": "fit80", "factors": FIT_F, "month_item": "fit80",
              "pace": {"pess": -2.0, "base": 0.4, "opt": 1.5}, "scen": FIT_S},
    "fit40": {"name": "Фитинговая платформа 40'", "data": "fit80", "factors": FIT_F, "month_item": "fit40",
              "pace": {"pess": -2.0, "base": 0.4, "opt": 1.5}, "scen": FIT_S},
    "fit60": {"name": "Фитинговая платформа 60'", "data": "fit80", "factors": FIT_F, "month_item": "fit60",
              "pace": {"pess": -2.0, "base": 0.4, "opt": 1.5}, "scen": FIT_S},
}
FNAME = {"stroy": "Стройка (щебень)", "mortgage": "Ипотека год назад", "const": "Общий тренд ставки"}
NOTE = {"hop_grain": "Инновационный зерновоз = типовой × 1,18 (средняя разница 2014–2025 гг.; данных партнёра по нему нет).",
        "fit80": "Годовые ряды не объясняют ставку платформ лучше среднего роста: её определяют санкции, импорт из Китая и "
                 "вывоз контейнеров в полувагонах. Прогноз — сценарный, коридор широкий."}


def fname(T, k):
    return T["factors"][k][0] if isinstance(T["factors"], dict) else FNAME[k]


def fkeys(T):
    return list(T["factors"])


def xval(T, k, v):
    """Значение сценария (изменение показателя, %) → значение фактора модели: у одиночного ряда — со знаком влияния."""
    if isinstance(T["factors"], dict) and len(T["factors"][k][1]) == 1:
        return T["factors"][k][1][0][2] * v
    return v


def n(v):
    return f"{round(v):,}".replace(",", " ")


def f1(v):
    return f"{v:.1f}".replace(".", ",")


def sg(v, d=0):
    return f"{v:+.{d}f}".replace(".", ",").replace("-", "−")


def months(item, year=2026):
    """Ставки месяцев года (середина диапазона): факт из базы наблюдений, пропуски — по прямой. Последний — факт."""
    obs = {}
    for r in zobs.read():
        if r["item"] == item and r["month"].startswith(f"{year}-") and r["source"] in ("survey", "partner"):
            m = int(r["month"][5:])
            if r["source"] == "survey" or m not in obs:
                obs[m] = (float(r["low"]) + float(r["high"])) / 2
    if not obs:
        sys.exit(f"Нет ставок {item} за {year} г. в базе наблюдений — сначала: python3 zobs.py pdf <выпуск.pdf>")
    last = max(obs)
    out = {}
    for m in range(1, last + 1):
        if m in obs:
            out[m] = obs[m]
            continue
        a = max((k for k in obs if k < m), default=None)
        b = min((k for k in obs if k > m), default=None)
        out[m] = obs[a] + (obs[b] - obs[a]) * (m - a) / (b - a) if a and b else obs[a or b]
    return out, set(obs)


def rows_of(T):
    """{год: (изменение ставки, % лог., [факторы])} по рядам types_data.json."""
    if not TDATA.exists():
        sys.exit(f"Нет {TDATA} — ряды по зерновозу и платформе не загружены на сервер.")
    S = json.loads(TDATA.read_text(encoding="utf-8"))[T["data"]]
    rate = {int(y): v for y, v in S["rate"].items()}
    x = {k: {int(y): v for y, v in s.items()} for k, s in S["x"].items()}
    dl = lambda d, y: 100 * math.log(d[y] / d[y - 1]) if d.get(y) and d.get(y - 1) else None
    rows = {}
    for y in sorted(rate):
        vals = []
        for k, (_, terms) in T["factors"].items():
            parts = [dl(x[s], y - lag) for s, lag, _ in terms]
            vals.append(None if None in parts else sum(sg_ * v for (_, _, sg_), v in zip(terms, parts)))
        if dl(rate, y) is not None and None not in vals:
            rows[y] = (dl(rate, y), vals)
    return rows


def fit(T):
    if "model" in T:
        D = zmodel.load()
        rows = zmodel.history_rows(D, T["model"], T["factors"])
    else:
        D, rows = None, rows_of(T)
    b, r2 = zmodel.ols(list(rows.values()))
    return D, {"b": dict(zip(["const"] + fkeys(T), b)), "r2": r2, "bt": zmodel.backtest(rows, start=2016), "n": len(rows)}


def scenario(D, T, scen, ov):
    """Значения факторов 2027–2030 по сценарию; ov — свои значения: одно число или четыре через «;»."""
    if "scen" in T:
        s = {f: [float(v) for v in T["scen"][scen][f]] for f in fkeys(T)}
    else:
        src = D["scenarios"]["pess" if scen == "pess" else "base"]
        s = {f: [float(x) for x in src[f][2:6]] for f in T["factors"]}  # индексы 2..5 = 2027..2030
    if scen == "opt" and "opt" in T:
        s.update({f: list(v) for f, v in T["opt"].items()})
    for k, v in (ov or {}).items():
        if k in s:
            vals = [float(x) for x in str(v).split(";")]
            s[k] = vals * 4 if len(vals) == 1 else vals[:4]
    return s


def forecast(w, scen="base", ov=None):
    T = TYPES[w]
    D, f = fit(T)
    m, real = months(T["month_item"])
    m = {k: v * T.get("ratio", 1) for k, v in m.items()}
    last_m = max(m)
    pace = float((ov or {}).get("pace", T["pace"][scen]))
    q = [m[last_m] * (1 + pace / 100) ** k for k in range(1, 13 - last_m)]
    year = list(m.values()) + q
    avg26, dec = sum(year) / 12, year[-1]
    lvl, end, parts = {2026: avg26}, {2026: dec}, {}
    s = scenario(D, T, scen, ov)
    for i, y in enumerate(YEARS):
        comp = {FNAME["const"]: f["b"]["const"]}
        comp.update({fname(T, k): f["b"][k] * xval(T, k, s[k][i]) for k in fkeys(T)})
        ch = sum(comp.values())
        end[y] = end[y - 1] * math.exp(ch / 100)
        lvl[y] = math.sqrt(end[y - 1] * end[y])
        parts[y] = {k: (end[y] - end[y - 1]) * c / ch for k, c in comp.items()} if ch else {}
        if scen == "pess" and lvl[y] > lvl[y - 1] * (1 + INFL[y] / 100):  # пессимистичный — не выше «средняя + инфляция»
            lvl[y] = lvl[y - 1] * (1 + INFL[y] / 100)
            end[y] = lvl[y] ** 2 / end[y - 1]
            parts[y] = {"Инфляция (верхняя граница)": end[y] - end[y - 1]}
    return {"lvl": lvl, "end": end, "parts": parts, "fit": f, "months": m,
            "real": real, "q4": q[-3:], "last_m": last_m, "pace": pace, "scen": s}


def report(w, a):
    T = TYPES[w]
    ov = dict(kv.split("=", 1) for kv in filter(None, (a.set or "").split(",")))
    res = {sc: forecast(w, sc, ov if sc == a.scenario else None) for sc in SCN}
    r0 = res["base"]
    lm = r0["last_m"]
    L = [f"# Ставка аренды: {T['name'].lower()} — IV квартал 2026 и прогноз до 2030", "",
         "<small>₽ за вагон в сутки без НДС · оценка рынка, не инвестиционная рекомендация</small>", "", "## Коротко", "",
         "| Сценарий | декабрь 2026* | средняя за 2026 г.** | средняя за 2027 г.*** | средняя за 2030 г.*** |", "|---|---|---|---|---|"]
    for sc in ("base", "opt", "pess"):
        r = res[sc]
        L.append(f"| {SCN[sc]} | {n(r['q4'][-1])} | {n(r['lvl'][2026])} | {n(r['lvl'][2027])} | {n(r['lvl'][2030])} |")
    L += ["", "<small>* ставка месяца — середина диапазона ставок рынка за месяц. ** средняя за 2026 г. — январь–декабрь: "
          f"январь–{MONTHS[lm - 1]} факт, далее прогноз; сумма 12 месяцев / 12. *** средняя за год (январь–декабрь) — середина "
          "между ставкой на начало и на конец года; пессимистичный — по факторам спада, не выше «средняя прошлого года + инфляция».</small>", "",
          f"## 1. Октябрь — декабрь 2026", "", f"**{T['name']}** — {MONTHS[lm - 1]} {n(r0['months'][lm])} ₽.", "",
          "| Сценарий | Темп, % в месяц | октябрь* | ноябрь* | декабрь* | средняя за 2026 г.** |", "|---|---|---|---|---|---|"]
    for sc in SCN:
        r = res[sc]
        L.append(f"| {SCN[sc]} | {sg(r['pace'], 1)} | " + " | ".join(n(x) for x in r["q4"]) + f" | {n(r['lvl'][2026])} |")
    if not a.guest:
        L += ["", "| 2026 | " + " | ".join(f"{MONTHS[k - 1]}{'' if k in r0['real'] else '*'}" for k in r0["months"]) + " |",
              "|---|" + "---|" * len(r0["months"]),
              f"| {T['name']} | " + " | ".join(n(v) for v in r0["months"].values()) + " |", "",
              "<small>* по прямой между соседними месяцами с данными.</small>"]
    L += ["", "<small>Темп IV кв.: пессимистичный — сезонное снижение, как в начале года; базовый — по инфляции; "
          "оптимистичный — темп сентября.</small>", "", "## 2. 2027–2030: средняя ставка за год (январь–декабрь)", "",
          "| Сценарий | 2026 | " + " | ".join(map(str, YEARS)) + " |", "|---|" + "---|" * 5]
    for sc in SCN:
        L.append(f"| {SCN[sc]} | " + " | ".join(n(res[sc]["lvl"][y]) for y in [2026] + YEARS) + " |")
    sc = a.scenario
    r = res[sc]
    L += ["", f"## 3. Из чего складывается рост: {SCN[sc].lower()} сценарий", "",
          "Изменение ставки за год (от декабря к декабрю), ₽/сут:", "", "| Фактор | " + " | ".join(map(str, YEARS)) + " |",
          "|---|" + "---|" * 4]
    for k in dict.fromkeys(k for y in YEARS for k in r["parts"][y]):
        L.append(f"| {k} | " + " | ".join(sg(r["parts"][y].get(k, 0)) for y in YEARS) + " |")
    L.append("| Ставка на конец года (декабрь) | " + " | ".join(n(r["end"][y]) for y in YEARS) + " |")
    L.append("| **Средняя за год (январь–декабрь)** | " + " | ".join(f"**{n(r['lvl'][y])}**" for y in YEARS) + " |")
    L += ["", "Значения факторов, % за год (2027–2030): " + "; ".join(
        f"{fname(T, k).lower()} {', '.join(sg(v, 1) for v in r['scen'][k])}" for k in fkeys(T)) + ".", ""]
    f = r0["fit"]
    bt = f["bt"] or {}
    L += ["## 4. Цена фактора", "", "| Изменение за год | ₽/сут |", "|---|---|"]
    lvl = r0["months"][lm]
    for k in fkeys(T):
        L.append(f"| {fname(T, k)} +1% | {sg(lvl * (math.exp(f['b'][k] * xval(T, k, 1) / 100) - 1))} |")
    L.append(f"| {FNAME['const']}, за год | {sg(lvl * (math.exp(f['b']['const'] / 100) - 1))} |")
    L += ["", f"<small>От ставки {MONTHS[lm - 1]} {n(lvl)} ₽.</small>", "", "## 5. Точность", "",
          f"- Годовая модель объясняет {round(f['r2'] * 100)}% колебаний ставки за {f['n']} лет; на прошлых годах "
          f"угадала направление в {round(bt.get('hit', 0) * 100)}% лет ({bt.get('years', 0)} проверочных), средняя ошибка "
          f"по проверочным годам ±{bt.get('error', '—')}% в год.",
          f"- Лучше, чем прогноз «средний рост прошлых лет», на {round((1 - bt['ratio']) * 100)}%." if bt.get("ratio", 1) <= 0.9 else
          "- ⚠ На прошлых годах модель не точнее прогноза «средний рост прошлых лет» — пользуйтесь сценариями.",
          "- IV квартал зависит от допущения о месячном темпе — таблица 1 показывает три темпа.",
          *([f"- {NOTE[T.get('data', '')]}"] if T.get("data") in NOTE else []),
          "- 2029–2030 гг. — ориентир: ошибка накапливается.", "",
          "<small>Подготовлено по открытым источникам и данным участников рынка. Выводы — оценка рынка.</small>"]
    return res, "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--wagon", default="kr158", choices=list(TYPES))
    r.add_argument("--scenario", default="base", choices=list(SCN))
    r.add_argument("--set", default="")
    r.add_argument("--guest", action="store_true")
    r.add_argument("--json", action="store_true")
    r.add_argument("--out")
    x = ap.parse_args()
    res, md = report(x.wagon, x)
    if x.json:
        print(json.dumps({sc: {"year": {str(y): round(v) for y, v in r_["lvl"].items()}, "q4": [round(q) for q in r_["q4"]]}
                          for sc, r_ in res.items()}, ensure_ascii=False))
    elif x.out:
        Path(x.out).parent.mkdir(parents=True, exist_ok=True)
        Path(x.out).write_text(md, encoding="utf-8")
        print(f"Файл: {x.out}")
    else:
        print(md)
