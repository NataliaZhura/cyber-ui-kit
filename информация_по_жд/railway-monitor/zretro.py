#!/usr/bin/env python3
"""Разбор ставки по месяцам и проверка прогноза на прошлом — по каждому типу вагона. Без нейросети (0 токенов).

  python3 zretro.py panel <тип> [--json]     ставка по месяцам 2025–2026 и рыночные данные того же месяца
  python3 zretro.py test [<тип>|all]          проверка на прошлом: октябрь–декабрь 2025 г. по данным января–сентября
                                              2025 г.; кварталы 2026 г. по данным 2025 г. — три способа прогноза
  python3 zretro.py drivers [<тип>|all]       какие показатели сильнее всего двигали ставку: 2025 и 2026 г. отдельно
  python3 zretro.py report <тип> --out <файл.md>   всё вместе + сезонность + что отслеживать + точка входа
  тип: inno|gon|kr158|kr138|hop_grain|fit80|fit40|fit60

Данные — база наблюдений (forecast/observations.csv: ставки и парк партнёра, погрузка РЖД) и открытые ряды
(zmacro.py: ключевая ставка, цены металла, контейнеры). Ставка месяца — середина диапазона. Изменение ставки за месяц
сравнивается с изменением показателя в тот же и в прошлый месяц (показатель часто опережает ставку). Мало точек
(9–12 в год) — связи ориентировочные, это помечается в отчёте.
"""
import argparse
import json
import math
import statistics
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import zobs  # noqa: E402
import zrates  # noqa: E402

NAMES = zrates.NAMES
RATE = zrates.FACT
MON = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
# Показатели-кандидаты по типу: (ключ, название, как считать: mm — % к прошлому месяцу, yy — % к году назад, lvl — уровень)
D_GON = [("load_coal", "Погрузка угля", "yy"), ("load_build", "Погрузка стройгрузов", "yy"),
         ("load_metal", "Погрузка чёрных металлов", "yy"), ("load_ore", "Погрузка руды", "yy"),
         ("load_total", "Погрузка на сети", "yy"), ("park_gon_work", "Рабочий парк полувагонов", "mm"),
         ("park_gon_reg", "Парк полувагонов (зарег.)", "mm"), ("flow_gon_new", "Новые полувагоны за месяц", "lvl"),
         ("flow_gon_out", "Выбыло полувагонов за месяц", "lvl"), ("op_coal", "Ставка оперирования (уголь)", "mm"),
         ("key", "Ключевая ставка", "lvl")]
D_KR = [("load_build", "Погрузка стройгрузов (цемент)", "yy"), ("load_fert", "Погрузка удобрений", "yy"),
        ("load_grain", "Погрузка зерна", "yy"), ("load_total", "Погрузка на сети", "yy"),
        ("park_kr_work", "Рабочий парк крытых", "mm"), ("park_kr_reg", "Парк крытых (зарег.)", "mm"),
        ("flow_kr_new", "Новые крытые за месяц", "lvl"), ("flow_kr_out", "Выбыло крытых за месяц", "lvl"),
        ("key", "Ключевая ставка", "lvl")]
D_GRAIN = [("load_grain", "Погрузка зерна", "mm"), ("load_grain#yy", "Погрузка зерна к году назад", "yy"),
           ("park_hop_grain_work", "Рабочий парк зерновозов", "mm"), ("park_hop_grain_reg", "Парк зерновозов (зарег.)", "mm"),
           ("flow_hop_grain_new", "Новые зерновозы за месяц", "lvl"), ("flow_hop_grain_out", "Выбыло зерновозов", "lvl"),
           ("kr158", "Ставка крытого 158 м³ (замена зерновозу)", "mm"), ("key", "Ключевая ставка", "lvl")]
D_FIT = [("park_fit_work", "Рабочий парк платформ", "mm"), ("park_fit_reg", "Парк платформ (зарег.)", "mm"),
         ("flow_fit_new", "Новые платформы за месяц", "lvl"), ("flow_fit_out", "Выбыло платформ", "lvl"),
         ("gon69_spot", "Ставка полувагона (контейнеры уходят в полувагоны)", "mm"), ("teu", "Перевозки контейнеров, TEU", "yy"),
         ("load_total", "Погрузка на сети", "yy"), ("key", "Ключевая ставка", "lvl")]
DRIVERS = {"gon": D_GON, "inno": D_GON, "kr158": D_KR, "kr138": D_KR, "hop_grain": D_GRAIN,
           "fit80": D_FIT, "fit40": D_FIT, "fit60": D_FIT}
CARGO = {"gon": "load_coal", "inno": "load_coal", "kr158": "load_build", "kr138": "load_build", "hop_grain": "load_grain",
         "fit80": "load_total", "fit40": "load_total", "fit60": "load_total"}  # груз для сезонности
PACE = {"kr158": 0.4, "kr138": 0.4, "hop_grain": 0.5, "fit80": 0.4, "fit40": 0.4, "fit60": 0.4}  # базовый темп (ztypes)


def months(a, b):
    out, m = [], a
    while m <= b:
        out.append(m)
        m = zobs.shift(m, 1)
    return out


def data():
    S = zrates.series()
    try:
        import zmacro
        S.update(zmacro.series())
    except ImportError:
        pass
    return S


def val(S, key, m, how):
    """Значение показателя в месяце m: mm/yy — % изменения, lvl — уровень."""
    k = key.split("#")[0]
    d = S.get(k, {})
    if m not in d:
        return None
    if how == "lvl":
        return d[m]
    p = d.get(zobs.shift(m, -1 if how == "mm" else -12))
    return (d[m] / p - 1) * 100 if p else None


def chg(d, m):
    p = d.get(zobs.shift(m, -1))
    return (math.log(d[m] / p) * 100) if (p and m in d) else None


def panel(w, S=None):
    S = S or data()
    r = S.get(RATE[w], {})
    rows = []
    for m in months("2025-01", max(r) if r else "2026-09"):
        row = {"m": m, "rate": r.get(m), "mm": chg(r, m) if m in r else None,
               "yy": ((r[m] / r[zobs.shift(m, -12)] - 1) * 100) if m in r and zobs.shift(m, -12) in r else None}
        for key, _, how in DRIVERS[w]:
            row[key] = val(S, key, m, how)
        rows.append(row)
    return rows


def corr(x, y):
    if len(x) < 4:
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if not sx or not sy:
        return None
    rr = sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)
    return rr, rr * sy / sx  # корреляция, наклон (% ставки на единицу показателя)


def drivers(w, year, S=None):
    """[(название, корреляция, наклон, лаг, n, единица)] по убыванию силы связи — за год year."""
    S = S or data()
    r = S.get(RATE[w], {})
    out = []
    for key, nm, how in DRIVERS[w]:
        best = None
        for lag in (0, 1):
            xs, ys = [], []
            for m in months(f"{year}-01", f"{year}-12"):
                y = chg(r, m)
                x = val(S, key, zobs.shift(m, -lag), how)
                if how == "lvl" and x is not None:  # уровень → изменение за месяц
                    p = val(S, key, zobs.shift(m, -lag - 1), how)
                    x = x - p if p is not None else None
                if y is not None and x is not None:
                    xs.append(x)
                    ys.append(y)
            c = corr(xs, ys)
            if c and (best is None or abs(c[0]) > abs(best[1])):
                u = "п.п. ключевой ставки" if key == "key" else "вагон за месяц" if key.startswith("flow") else \
                    {"mm": "% за месяц", "yy": "% к году", "lvl": "изм. за месяц"}[how]
                best = (nm, c[0], c[1], lag, len(xs), u)
        if best:
            out.append(best)
    return sorted(out, key=lambda x: -abs(x[1]))


def season(S, key, upto):
    """Сезонный индекс груза по месяцам (1 = средний месяц года) — по годам до upto (без подглядывания вперёд)."""
    d = S.get(key, {})
    by = {}
    for m, v in d.items():
        if m <= upto:
            by.setdefault(m[:4], {})[int(m[5:])] = v
    idx = {k: [] for k in range(1, 13)}
    for y, ms in by.items():
        if len(ms) == 12:
            avg = sum(ms.values()) / 12
            for k, v in ms.items():
                idx[k].append(v / avg)
    return {k: statistics.mean(v) for k, v in idx.items() if v}


def elastic(r, L, ms):
    """Сколько % ставки на 1% изменения погрузки груза за месяц — по месяцам ms, ограничено 0…3."""
    xs, ys = [], []
    for m in ms:
        a, b = chg(r, m), chg(L, m)
        if a is not None and b is not None:
            xs.append(b)
            ys.append(a)
    c = corr(xs, ys)
    return min(3.0, max(0.0, c[1])) if c else 0.0


def gon_pace(S, w, ms):
    """Текущий метод полувагона: темп ставки = −эластичность × темп рабочего парка, обе — по месяцам ms."""
    r, p = S.get(RATE[w], {}), S.get("park_gon_work", {})
    pairs = [(chg(r, m), chg(p, m)) for m in ms if chg(r, m) is not None and chg(p, m) is not None]
    if len(pairs) < 3:
        return 0.4
    c = corr([b for _, b in pairs], [a for a, _ in pairs])
    e = -c[1] if c and c[1] < 0 else 0
    return -e * statistics.mean(b for _, b in pairs)


def test_q4(w, S):
    """Октябрь–декабрь 2025 г. по данным январь–сентябрь 2025 г."""
    r = S.get(RATE[w], {})
    hist = [m for m in months("2025-01", "2025-09") if m in r]
    if "2025-09" not in r or not all(m in r for m in ("2025-10", "2025-11", "2025-12")):
        return None
    last = r["2025-09"]
    pace = gon_pace(S, w, hist) if w in ("gon", "inno") else PACE[w]
    m1 = [last * (1 + pace / 100) ** k for k in (1, 2, 3)]
    L = S.get(CARGO[w], {})
    si = season(S, CARGO[w], "2024-12")
    e = elastic(r, L, hist)
    m2 = [last * (si.get(k, 1) / si.get(9, 1)) ** e for k in (10, 11, 12)] if si else m1
    # «если бы знали показатель»: лучший показатель 2025 г. (январь–сентябрь) с фактическими значениями октября–декабря
    best = [x for x in drivers_window(w, S, hist) if x[4] >= 5][:1]
    m3 = None
    if best:
        key, how, slope, lag = best[0][6], best[0][7], best[0][2], best[0][3]
        v, m3 = last, []
        for m in ("2025-10", "2025-11", "2025-12"):
            x = val(S, key, zobs.shift(m, -lag), how)
            if how == "lvl" and x is not None:
                p = val(S, key, zobs.shift(m, -lag - 1), how)
                x = x - p if p is not None else None
            v = v * math.exp(slope * (x or 0) / 100)
            m3.append(v)
    fact = [r[m] for m in ("2025-10", "2025-11", "2025-12")]
    return {"fact": fact, "m1": m1, "m2": m2, "m3": m3, "pace": pace, "e": e, "best": best[0][0] if best else None}


def drivers_window(w, S, ms):
    r = S.get(RATE[w], {})
    out = []
    for key, nm, how in DRIVERS[w]:
        for lag in (0, 1):
            xs, ys = [], []
            for m in ms:
                y, x = chg(r, m), val(S, key, zobs.shift(m, -lag), how)
                if how == "lvl" and x is not None:
                    p = val(S, key, zobs.shift(m, -lag - 1), how)
                    x = x - p if p is not None else None
                if y is not None and x is not None:
                    xs.append(x)
                    ys.append(y)
            c = corr(xs, ys)
            if c:
                out.append((nm, c[0], c[1], lag, len(xs), "", key, how))
    return sorted(out, key=lambda x: -abs(x[1]))


def test_2026(w, S):
    """Средние ставки I–III кв. 2026 г. по данным 2025 г. (до декабря включительно)."""
    r = S.get(RATE[w], {})
    if "2025-12" not in r:
        return None
    dec = r["2025-12"]
    hist = [m for m in months("2025-01", "2025-12") if m in r]
    pace = gon_pace(S, w, hist) if w in ("gon", "inno") else PACE[w]
    out = []
    for q in (1, 2, 3):
        ms = [f"2026-{k:02d}" for k in range(3 * q - 2, 3 * q + 1)]
        fact = [r[m] for m in ms if m in r]
        if len(fact) < 2:
            continue
        k0 = 3 * q - 2
        m1 = statistics.mean(dec * (1 + pace / 100) ** k for k in range(k0, k0 + 3))
        last_year = [r.get(f"2025-{k:02d}") for k in range(k0, k0 + 3)]
        trend = dec / r["2024-12"] if "2024-12" in r else 1
        m2 = statistics.mean(x for x in last_year if x) * trend if any(last_year) else None
        si = season(S, CARGO[w], "2025-12")
        e = elastic(r, S.get(CARGO[w], {}), hist)
        m3 = statistics.mean(dec * (si.get(k, 1) / si.get(12, 1)) ** e for k in range(k0, k0 + 3)) if si else None
        out.append({"q": q, "fact": statistics.mean(fact), "m1": m1, "m2": m2, "m3": m3})
    return {"rows": out, "pace": pace}


def err(f, p):
    return abs(p / f - 1) * 100 if (p and f) else None


def n0(v):
    return "—" if v is None else f"{round(v):,}".replace(",", " ")


def p1(v):
    return "—" if v is None else f"{v:+.1f}".replace(".", ",").replace("-", "−")


def test_md(w, S):
    L = []
    t = test_q4(w, S)
    if t:
        L += ["### Тест 1. Октябрь–декабрь 2025 г. по данным января–сентября 2025 г.", "",
              "| Месяц | Факт | ① ровный темп | ② сезонность груза | ③ по главному показателю* |", "|---|---|---|---|---|"]
        for i, mn in enumerate(("октябрь", "ноябрь", "декабрь")):
            L.append(f"| {mn} | {n0(t['fact'][i])} | {n0(t['m1'][i])} | {n0(t['m2'][i])} | {n0(t['m3'][i] if t['m3'] else None)} |")
        e = {k: statistics.mean(err(f, p) for f, p in zip(t["fact"], t[k])) for k in ("m1", "m2") }
        if t["m3"]:
            e["m3"] = statistics.mean(err(f, p) for f, p in zip(t["fact"], t["m3"]))
        L += ["", "Средняя ошибка: " + "; ".join(f"{lbl} ±{x:.0f}%".replace(".", ",") for lbl, x in
                                                 zip(("① ровный темп", "② сезонность", "③ по показателю"), e.values())) + ".",
              f"<small>① темп {p1(t['pace'])}% в месяц ({'по рабочему парку января–сентября 2025 г.' if w in ('gon', 'inno') else 'базовый темп модели'}); "
              f"② сезонность погрузки груза по 2023–2024 гг., чувствительность ставки к погрузке {str(round(t['e'], 2)).replace('.', ',')} (январь–сентябрь 2025 г.); "
              f"* ③ — «если бы знали показатель заранее»: {t['best'] or 'нет'} с фактическими значениями — показывает силу связи, "
              "а не прогноз.</small>".replace(".", ",", 0), ""]
        t["err"] = e
    else:
        L += ["### Тест 1. Октябрь–декабрь 2025 г.", "", "Нет ставок за весь 2025 г. в базе — тест не проводится.", ""]
    t2 = test_2026(w, S)
    if t2 and t2["rows"]:
        L += ["### Тест 2. Средние ставки кварталов 2026 г. по данным 2025 г.", "",
              "| Квартал 2026 | Факт | ① ровный темп от декабря | ② тот же квартал 2025 × годовой тренд | ③ сезонность груза |",
              "|---|---|---|---|---|"]
        for x in t2["rows"]:
            e_ = lambda v: "—" if v is None else f"±{v:.0f}%"
            L.append(f"| {x['q']} кв. | {n0(x['fact'])} | {n0(x['m1'])} ({e_(err(x['fact'], x['m1']))}) | "
                     f"{n0(x['m2'])} ({e_(err(x['fact'], x['m2']))}) | {n0(x['m3'])} ({e_(err(x['fact'], x['m3']))}) |")
        L += ["", "<small>В скобках — ошибка. ② «тот же квартал прошлого года × (декабрь 2025 / декабрь 2024)» "
              "переносит сезонность прошлого года.</small>", ""]
    return L, t, t2


def drivers_md(w, S):
    L = ["| Показатель | 2025 г.: связь | на 1 ед. показателя, % ставки | 2026 г.: связь | на 1 ед., % ставки |", "|---|---|---|---|---|"]
    d25 = {x[0]: x for x in drivers(w, 2025, S)}
    d26 = {x[0]: x for x in drivers(w, 2026, S)}
    keys = sorted(set(d25) | set(d26), key=lambda k: -max(abs(d25.get(k, (0, 0))[1]), abs(d26.get(k, (0, 0))[1])))
    num = lambda v: f"{v:+.2f}".replace(".", ",").replace("-", "−")
    cell = lambda x: (f"{num(x[1])}{' (показатель на месяц раньше)' if x[3] else ''}, точек {x[4]}",
                      f"{num(x[2])} на 1 {x[5]}") if x else ("—", "—")
    for k in keys:
        a, b = cell(d25.get(k)), cell(d26.get(k))
        L.append(f"| {k} | {a[0]} | {a[1]} | {b[0]} | {b[1]} |")
    L += ["", "<small>Связь — корреляция изменения ставки за месяц с изменением показателя (от −1 до +1): ближе к ±1 — сильнее; "
          "знак «−» — показатель растёт, ставка падает. При 9–12 точках в год связь слабее ±0,6 — случайная. "
          "«На 1 ед.» — на сколько % в среднем менялась ставка при изменении показателя на единицу.</small>", ""]
    top25 = [x[0] for x in drivers(w, 2025, S) if abs(x[1]) >= 0.6][:3]
    top26 = [x[0] for x in drivers(w, 2026, S) if abs(x[1]) >= 0.6][:3]
    L += [f"**Главные в 2025 г.:** {', '.join(top25) or 'устойчивых связей нет'}. "
          f"**Главные в 2026 г.:** {', '.join(top26) or 'устойчивых связей нет'}.", ""]
    return L, top25, top26


def report(w):
    S = data()
    nm = NAMES[w]
    P = panel(w, S)
    L = [f"# {nm}: ставка по месяцам 2025–2026, что её двигало и насколько точен прогноз", "",
         "<small>₽/сут без НДС · данные рынка (только для внутреннего использования) и открытые данные · оценка, не "
         "инвестиционная рекомендация</small>", "", "## 1. Ставка и рынок по месяцам", ""]
    cols = DRIVERS[w][:6]
    unit = {"mm": "% к мес.", "yy": "% к году", "lvl": "ваг."}
    L += ["| Месяц | Ставка | к мес., % | к году, % | " + " | ".join(f"{c[1]}, {unit[c[2]]}" for c in cols) + " |",
          "|---" * (4 + len(cols)) + "|"]
    for x in P:
        if x["rate"] is None and not any(x[c[0]] is not None for c in cols):
            continue
        cells = [p1(x[c[0]]) if c[2] != "lvl" else n0(x[c[0]]) for c in cols]
        L.append(f"| {MON[int(x['m'][5:]) - 1]} {x['m'][:4]} | {n0(x['rate'])} | {p1(x['mm'])} | {p1(x['yy'])} | " + " | ".join(cells) + " |")
    L += ["", "<small>«% к мес.» — к прошлому месяцу, «% к году» — к тому же месяцу прошлого года, «ваг.» — вагонов за месяц. "
          "«—» — данных нет (выпуск не прочитан или показатель не публикуется).</small>", "",
          "## 2. Сезонность", ""]
    r = S.get(RATE[w], {})
    si = season(S, CARGO[w], "2026-12")
    by = {y: {int(m[5:]): v for m, v in r.items() if m.startswith(y)} for y in ("2025", "2026")}
    L += ["| | " + " | ".join(MON) + " |", "|---" * 13 + "|"]
    for y, ms in by.items():
        if ms:
            avg = statistics.mean(ms.values())
            L.append(f"| Ставка {y}, к средней | " + " | ".join(f"{ms[k] / avg:.2f}".replace(".", ",") if k in ms else "—" for k in range(1, 13)) + " |")
    if si:
        L.append(f"| Погрузка груза, сезонный индекс | " + " | ".join(f"{si[k]:.2f}".replace(".", ",") if k in si else "—" for k in range(1, 13)) + " |")
    L += ["", f"<small>1,00 — средний месяц года. Груз для сезонности: {dict((k, n) for k, n, _ in DRIVERS[w]).get(CARGO[w], CARGO[w])}; "
          "индекс — по полным годам с 2023 г.</small>", "", "## 3. Что двигало ставку: 2025 и 2026 гг.", ""]
    dl, top25, top26 = drivers_md(w, S)
    L += dl + ["## 4. Проверка прогноза на прошлом", ""]
    tl, t1, t2 = test_md(w, S)
    L += tl
    L += ["## 5. Что отслеживать и точка входа", ""]
    watch = list(dict.fromkeys(top26 + top25))[:5]
    L += [f"- Главные показатели для этого вагона: {', '.join(watch) if watch else 'устойчивых связей пока нет — нужен ещё год данных'}."]
    if r:
        low = min((m for m in r if m >= "2025-01"), key=lambda m: r[m])
        L.append(f"- Дно ставки за 2025–2026 гг.: {MON[int(low[5:]) - 1]} {low[:4]} — {n0(r[low])} ₽. Показатели в тот месяц: "
                 + "; ".join(f"{c[1]} {p1(x[c[0]]) if c[2] != 'lvl' else n0(x[c[0]])}" for x in P if x["m"] == low for c in cols
                             if x[c[0]] is not None) + ". Повторение такого набора — сигнал «точка входа» (покупка дешевле, ставка у дна).")
    if t1 and t1.get("err"):
        best = min(t1["err"], key=t1["err"].get)
        L.append(f"- Для IV квартала точнее был способ {({'m1': '① ровный темп', 'm2': '② сезонность груза', 'm3': '③ по показателю'})[best]}.")
    import zmacro  # рыночный фон по типу: контейнеры в полувагонах, зерно, металл (открытые данные с источниками)
    L += ["", "## 6. Рыночный фон (открытые данные)", ""]
    if w in ("hop_grain",) or w.startswith("kr"):
        L += [zmacro.grain_md().replace("## ", "### ")]
    if w.startswith("fit") or w in ("gon", "inno"):
        L += [zmacro.report().replace("## ", "### ")]
    L += [f"**Металл и цена вагона:** {zmacro.METAL_NOTE}.", ""]
    L += ["", "<small>Выводы ориентировочные: 21 месяц данных. Каждый новый выпуск добавляет месяц — отчёт пересобирается.</small>"]
    return "\n".join(L) + "\n"


def api(w):
    """Для мини-приложения: помесячная таблица, главные показатели 2025 и 2026 гг., проверка на прошлом."""
    S = data()
    cols = DRIVERS[w][:5]
    unit = {"mm": "% к мес.", "yy": "% к году", "lvl": "ваг."}
    rows = [{"m": x["m"], "rate": x["rate"], "mm": x["mm"], "yy": x["yy"], "x": [x[c[0]] for c in cols]}
            for x in panel(w, S) if x["rate"] is not None]
    dd = {y: [{"name": d[0], "r": round(d[1], 2), "b": round(d[2], 2), "lag": d[3], "n": d[4], "unit": d[5]}
              for d in drivers(w, y, S)[:5]] for y in (2025, 2026)}
    t1, t2 = test_q4(w, S), test_2026(w, S)
    tests = {}
    if t1:
        tests["q4_2025"] = {k: round(statistics.mean(err(f, p) for f, p in zip(t1["fact"], t1[k])), 1)
                            for k in ("m1", "m2", "m3") if t1.get(k)}
    if t2 and t2["rows"]:
        tests["q_2026"] = {k: round(statistics.mean(err(x["fact"], x[k]) for x in t2["rows"] if x[k]), 1) for k in ("m1", "m2", "m3")}
    return {"wagon": NAMES[w], "cols": [f"{c[1]}, {unit[c[2]]}" for c in cols], "rows": rows, "drivers": dd, "tests": tests}


def summary():
    S = data()
    L = ["| Тип | Тест 1: ① ровный темп | ② сезонность | ③ по показателю | Тест 2 (кв. 2026): ① | ② | ③ |", "|---|---|---|---|---|---|---|"]
    for w in RATE:
        t1, t2 = test_q4(w, S), test_2026(w, S)
        e1 = [statistics.mean(err(f, p) for f, p in zip(t1["fact"], t1[k])) if t1 and t1.get(k) else None for k in ("m1", "m2", "m3")]
        e2 = [statistics.mean(err(x["fact"], x[k]) for x in t2["rows"] if x[k]) if t2 and t2["rows"] else None for k in ("m1", "m2", "m3")]
        L.append(f"| {NAMES[w]} | " + " | ".join("—" if v is None else f"±{v:.0f}%" for v in e1 + e2) + " |")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["panel", "test", "drivers", "report"])
    ap.add_argument("wagon", nargs="?", default="all")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    ws = list(RATE) if a.wagon == "all" else [a.wagon]
    if a.cmd == "panel":
        rows = panel(ws[0])
        print(json.dumps(rows, ensure_ascii=False) if a.json else "\n".join(
            f"{x['m']} {n0(x['rate']):>7} {p1(x['mm']):>7}" for x in rows))
    elif a.cmd == "test":
        print(summary() if a.wagon == "all" else "\n".join(test_md(ws[0], data())[0]))
    elif a.cmd == "drivers":
        for w in ws:
            print(f"== {NAMES[w]}\n" + "\n".join(drivers_md(w, data())[0]))
    else:
        md = report(ws[0])
        if a.out:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(md, encoding="utf-8")
            print(f"Файл: {a.out}")
        else:
            print(md)
