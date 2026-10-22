#!/usr/bin/env python3
"""Проверка допущений модели на прошлом — по всем типам вагонов: ставка, стоимость, вход и выход из сделки.
Каждое допущение: прогноз только по данным «до» → сравнение с фактом → вердикт. Без нейросети (0 токенов).

  python3 zverify.py            все проверки → saved/model/ГГГГ-ММ-ДД_проверка_модели.md (и вывод на экран)

Данные: база наблюдений (месяцы с 12.2024), годовые ряды forecast/*.json (2007–2025), цены новых вагонов —
forecast/price_hist.json (полувагоны и крытый — из презентаций рынков, только на сервере), зерновоз и платформа —
forecast/types_data.json.
"""
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
FC = BASE / "forecast"
TYPES = ["gon", "inno", "kr158", "hop_grain", "fit80"]
NM = {"gon": "Полувагон типовой", "inno": "Полувагон инновационный", "kr158": "Крытый 158 м³",
      "hop_grain": "Хоппер-зерновоз", "fit80": "Платформа 80'"}
UTIL, OPEX = 0.95, 0.12  # загрузка и расходы — как в калькуляторе сделки (zdeal.py)
V = []  # итог: (раздел, допущение, результат, вердикт)


def js(name):
    p = FC / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def yr(d):
    return {int(k): float(v) for k, v in (d or {}).items() if v is not None}


def pct(v, d=1):
    return "—" if v is None else f"{v:+.{d}f}%".replace(".", ",").replace("-", "−")


def f1(v, d=1):
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",").replace("-", "−")


def n0(v):
    return "—" if v is None else f"{round(v):,}".replace(",", " ")


def mean(x):
    x = [v for v in x if v is not None]
    return statistics.mean(x) if x else None


def corr(a, b):
    if len(a) < 4 or statistics.pstdev(a) == 0 or statistics.pstdev(b) == 0:
        return None
    ma, mb = statistics.mean(a), statistics.mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a) / statistics.pstdev(a) / statistics.pstdev(b)


def verdict(sec, what, res, ok):
    V.append((sec, what, res, {True: "✅ подтверждено", False: "❌ не подтверждено", None: "⚪ проверить нельзя"}[ok]))


# ---------- годовые ряды: ставка и цена нового вагона ----------
def annual(w):
    R, T, P = js("rate_data.json"), js("types_data.json"), js("price_hist.json")
    if w in ("gon", "inno"):
        rate = yr(R.get("rates", {}).get(w))
    elif w == "kr158":
        rate = yr(P.get("kr158", {}).get("rate"))
    else:
        rate = yr(T.get(w, {}).get("rate"))
    price = yr(T.get(w, {}).get("value")) if w in ("hop_grain", "fit80") else yr(P.get(w, {}).get("price"))
    return rate, price


# ---------- 1. Ставка: ближайшие месяцы ----------
def t_quarters(L):
    import zretro
    S = zretro.data()
    L += ["## 1. Ставка на ближайшие месяцы: какой способ точнее на прошлом", "",
          "Тест 1 — октябрь–декабрь 2025 г. по данным января–сентября 2025 г.; тест 2 — средние ставки I–III кв. 2026 г. по данным "
          "до декабря 2025 г. Ошибка — средняя по модулю, %.", "",
          "| Тип | Способ в модели | ① ровный темп: т1 / т2 | ② сезон: т1 / т2 | ③ показатель: т1 / т2 | Лучший | Вердикт |",
          "|---|---|---|---|---|---|---|"]
    used = {"gon": 1, "inno": 1, "kr158": 1, "hop_grain": 2, "fit80": 1}
    for w in TYPES:
        a, b = zretro.test_q4(w, S), zretro.test_2026(w, S)
        e = {}
        for m in ("m1", "m2", "m3"):
            e1 = mean([abs(p / f - 1) * 100 for f, p in zip(a["fact"], a[m] or [])]) if a and a.get(m) else None
            e2 = mean([abs(x[m] / x["fact"] - 1) * 100 for x in b["rows"] if x.get(m)]) if b else None
            e[m] = (e1, e2)
        score = {m: mean(v) for m, v in e.items() if mean(v) is not None}
        best = min(score, key=score.get) if score else None
        u = f"m{used[w]}"
        ok = None if not best else (score.get(u) is not None and score[u] <= score[best] * 1.15)
        L.append(f"| {NM[w]} | {'①②③'[used[w] - 1]} | " + " | ".join(f"{f1(x)} / {f1(y)}" for x, y in e.values()) +
                 f" | {'①②③'[int(best[1]) - 1] if best else '—'} | {'да' if ok else 'нет' if ok is False else '—'} |")
        verdict("Ставка", f"{NM[w]}: способ на ближайшие месяцы {'①②③'[used[w] - 1]}",
                f"ошибка {f1(score.get(u))}% против лучшего {f1(score.get(best))}%" if best else "мало данных", ok)
    L += ["", "<small>③ «по главному показателю» в тесте берёт фактические значения показателя — в жизни их заранее не знаем, "
          "поэтому ③ — верхняя граница возможного, а не готовый способ. Вердикт «да» — способ модели не хуже лучшего более "
          "чем на 15%.</small>", ""]


# ---------- 2. Полувагон: связь «рабочий парк → ставка» ----------
def t_elastic(L):
    import zretro
    import zobs
    S = zretro.data()
    p = S.get("park_gon_work", {})
    L += ["## 2. Полувагон: «рабочий парк −1% → ставка +X%»", ""]
    try:
        import zrate
        e_model = zrate.elasticity(zrate.load(), "inno")
    except (SystemExit, Exception):  # noqa: BLE001
        e_model = None
    L.append(f"В модели: X = {f1(e_model)} (по двум отрезкам 2026 г.: декабрь→август и январь→август). Проверка: та же "
             "связь на скользящих отрезках по 6 месяцев и прогноз 2026 г. по связи, оценённой только на 2025 г.")
    L += ["", "| Тип | Отрезок (6 мес.) | Парк | Ставка | X |", "|---|---|---|---|---|"]
    for w in ("inno", "gon"):
        r = S.get(zretro.RATE[w], {})
        ms = sorted(set(r) & set(p))
        xs = []
        for i in range(6, len(ms)):
            a, b = ms[i - 6], ms[i]
            dp, dr = math.log(p[b] / p[a]), math.log(r[b] / r[a])
            if abs(dp) >= 0.005:
                xs.append(-dr / dp)
                L.append(f"| {NM[w]} | {a} → {b} | {pct(dp * 100)} | {pct(dr * 100)} | {f1(-dr / dp)} |")
        pos = sum(1 for x in xs if x > 0)
        if xs:
            L.append(f"| {NM[w]} | **итого {len(xs)} отрезков** | | | X > 0 в {pos} из {len(xs)}; разброс {f1(min(xs))}…{f1(max(xs))} |")
        # прогноз 2026 г. по связи 2025 г.
        a0, b0 = "2024-12", "2025-12"
        if all(k in r and k in p for k in (a0, b0)) and abs(math.log(p[b0] / p[a0])) >= 0.005:
            e25 = -math.log(r[b0] / r[a0]) / math.log(p[b0] / p[a0])
            ms26 = [m for m in ms if m.startswith("2026-")]
            em = [abs(r[b0] * (p[m] / p[b0]) ** (-e25) / r[m] - 1) * 100 for m in ms26]
            ef = [abs(r[b0] / r[m] - 1) * 100 for m in ms26]
            ok = mean(em) < mean(ef) if em else None
            verdict("Ставка", f"{NM[w]}: связь с рабочим парком",
                    f"X 2025 г. = {f1(e25)}; прогноз 2026 г. по ней — ошибка {f1(mean(em))}% против {f1(mean(ef))}% "
                    f"у «ставка не изменится»; знак X > 0 в {pos} из {len(xs)} отрезков", ok if pos >= len(xs) * 0.7 else False)
        else:
            verdict("Ставка", f"{NM[w]}: связь с рабочим парком",
                    f"знак X > 0 в {pos} из {len(xs)} отрезков; за 2025 г. парк почти не менялся — прогноз по 2025 г. не построить",
                    (pos >= len(xs) * 0.7) if xs else None)
    L += ["", "<small>X > 0 — ставка растёт, когда парк сокращается (как в модели). Если знак часто меняется или разброс "
          "большой, связь нельзя переносить на будущее одним числом.</small>", ""]
    _ = zobs


# ---------- 3. Устойчивость связей: 2025 против 2026 г. ----------
def t_signs(L):
    import zretro
    S = zretro.data()
    L += ["## 3. Показатели, на которые опирается ставка: одинаковая ли связь в 2025 и 2026 гг.", "",
          "| Тип | Связь устойчива (знак тот же, сила ≥ 0,3 оба года) | Связь меняет знак |", "|---|---|---|"]
    for w in TYPES:
        a = {x[0]: x[1] for x in zretro.drivers(w, 2025, S)}
        b = {x[0]: x[1] for x in zretro.drivers(w, 2026, S)}
        st = [f"{k} ({f1(a[k], 2)} / {f1(b[k], 2)})" for k in a if k in b and abs(a[k]) >= 0.3 and abs(b[k]) >= 0.3 and a[k] * b[k] > 0]
        fl = [f"{k} ({f1(a[k], 2)} / {f1(b[k], 2)})" for k in a if k in b and abs(a[k]) >= 0.3 and abs(b[k]) >= 0.3 and a[k] * b[k] < 0]
        L.append(f"| {NM[w]} | {'; '.join(st) or '—'} | {'; '.join(fl) or '—'} |")
        verdict("Ставка", f"{NM[w]}: связи с показателями повторяются год к году",
                f"устойчивых {len(st)}, меняют знак {len(fl)}", (len(st) > len(fl)) if (st or fl) else None)
    L += ["", "<small>В скобках — сила связи в 2025 / 2026 г. (от −1 до +1). Показатель, меняющий знак, нельзя использовать "
          "в прогнозе как постоянный фактор — только как признак момента.</small>", ""]


# ---------- 4. Годовые модели 2027–2030 ----------
def t_annual(L):
    L += ["## 4. Прогноз на 2027–2030 гг.: годовая модель по факторам на прошлых годах", "",
          "Модель учится на годах до t и прогнозирует год t (2014/2016–2025). Сравнение — с прогнозом «изменение как в среднем».", "",
          "| Тип | Факторы | Лет проверки | Ошибка, п.п. | Ошибка к простому прогнозу | Угадано направление |", "|---|---|---|---|---|---|"]
    rows = []
    try:
        import zrate
        D = zrate.load()
        for w in ("gon", "inno"):
            f = zrate.fit(D, w)
            rows.append((w, ", ".join(D["model"][w]), f["bt"]))
    except (SystemExit, Exception):  # noqa: BLE001
        pass
    try:
        import ztypes
        for w in ("kr158", "hop_grain", "fit80"):
            T = ztypes.TYPES[w]
            rows.append((w, ", ".join(T.get("factors") or ztypes.fkeys(T)), ztypes.fit(T)[1]["bt"]))
    except (SystemExit, Exception):  # noqa: BLE001
        pass
    for w, fs, bt in rows:
        if not bt:
            L.append(f"| {NM[w]} | {fs} | — | — | — | — |")
            verdict("Ставка 2027–2030", f"{NM[w]}: годовая модель", "мало лет для проверки", None)
            continue
        L.append(f"| {NM[w]} | {fs} | {bt['years']} | ±{bt['error']} | {f1(bt['ratio'], 2)} | {round(bt['hit'] * 100)}% |")
        verdict("Ставка 2027–2030", f"{NM[w]}: годовая модель по факторам",
                f"ошибка ±{bt['error']} п.п. в год, {f1(bt['ratio'], 2)} от простого прогноза, направление {round(bt['hit'] * 100)}%",
                bt["ratio"] < 1 and bt["hit"] >= 0.6)
    L += ["", "<small>«Ошибка к простому прогнозу» меньше 1 — модель лучше, чем «каждый год как в среднем». Ошибка в п.п. — "
          "насколько в среднем промахивается годовое изменение ставки.</small>", ""]


# ---------- 5. Пессимистичный сценарий против истории ----------
def t_pess(L):
    L += ["## 5. Пессимистичный сценарий: насколько он плохой по меркам истории", "",
          "| Тип | Пессимистичный, 2027 г. к 2026 г. | Лет в истории хуже | Худший год в истории |", "|---|---|---|---|"]
    for w in TYPES:
        rate, _ = annual(w)
        ch = {y: (rate[y] / rate[y - 1] - 1) * 100 for y in rate if y - 1 in rate}
        try:
            if w in ("gon", "inno"):
                import zrate
                lv = zrate.forecast(zrate.load(), w, "pess")["lvl"]
            else:
                import ztypes
                lv = ztypes.forecast(w, "pess")["lvl"]
            pc = (lv[2027] / lv[2026] - 1) * 100
        except (SystemExit, Exception):  # noqa: BLE001
            pc = None
        if not ch or pc is None:
            L.append(f"| {NM[w]} | {pct(pc)} | — | — |")
            continue
        worse = [y for y, v in ch.items() if v < pc]
        wy = min(ch, key=ch.get)
        L.append(f"| {NM[w]} | {pct(pc)} | {len(worse)} из {len(ch)} ({', '.join(map(str, worse[:6]))}) | {wy} г.: {pct(ch[wy])} |")
        verdict("Сценарии", f"{NM[w]}: пессимистичный сценарий покрывает плохие годы",
                f"хуже него — {len(worse)} из {len(ch)} лет истории, худший год {pct(ch[wy], 0)}", len(worse) <= len(ch) * 0.2)
    L += ["", "<small>Если хуже пессимистичного было больше 20% лет, это не стресс-сценарий, а «умеренно плохой». Для кредитора "
          "нужен отдельный стресс по худшему году истории.</small>", ""]


# ---------- 6. Стоимость вагона ----------
def t_value(L):
    import zmodel
    L += ["## 6. Стоимость нового вагона: следует ли она за ставкой", "",
          "Модель: ln(цена) = a + b · ln(средняя ставка за 3 года) + c · (год − 2015). Проверка: модель учится на годах до t и "
          "прогнозирует цену года t по фактической ставке; сравнение — с «цена как в прошлом году».", "",
          "| Тип | Лет | b (сила связи) | Связь изменений цены и ставки | Ошибка модели | Ошибка «как в прошлом году» | Годы падения цены > 5% | Худшее падение |",
          "|---|---|---|---|---|---|---|---|"]
    for w in TYPES:
        rate, price = annual(w)
        if len(price) < 6 or len(rate) < 6:
            L.append(f"| {NM[w]} | нет ряда цен | | | | | | |")
            verdict("Стоимость", f"{NM[w]}: цена следует за ставкой", "нет ряда цен на сервере (forecast/price_hist.json)", None)
            continue
        avg3 = {y: sum(rate[y - i] for i in range(3)) / 3 for y in rate if all(y - i in rate for i in range(3))}
        ys = sorted(y for y in price if y in avg3)
        data = {y: (math.log(price[y]), [math.log(avg3[y]), y - 2015]) for y in ys}
        em, en = [], []
        for t in ys:
            tr = [data[y] for y in ys if y < t]
            if len(tr) < 6 or t - 1 not in price:
                continue
            b, _ = zmodel.ols(tr)
            pr = math.exp(b[0] + b[1] * data[t][1][0] + b[2] * data[t][1][1])
            em.append(abs(pr / price[t] - 1) * 100)
            en.append(abs(price[t - 1] / price[t] - 1) * 100)
        b_all, r2 = zmodel.ols(list(data.values()))
        dc = [y for y in ys if y - 1 in price and y - 1 in avg3]
        c = corr([math.log(price[y] / price[y - 1]) for y in dc], [math.log(avg3[y] / avg3[y - 1]) for y in dc])
        drops = {y: (price[y] / price[y - 1] - 1) * 100 for y in sorted(price) if y - 1 in price}
        big = [f"{y} ({pct(v, 0)})" for y, v in drops.items() if v < -5]
        wy = min(drops, key=drops.get)
        L.append(f"| {NM[w]} | {min(ys)}–{max(ys)} | {f1(b_all[1], 2)} | {f1(c, 2)} | ±{f1(mean(em))}% | ±{f1(mean(en))}% | "
                 f"{', '.join(big) or 'нет'} | {wy} г.: {pct(drops[wy], 0)} |")
        verdict("Стоимость", f"{NM[w]}: цена нового вагона следует за средней ставкой за 3 года",
                f"связь изменений {f1(c, 2)}; ошибка ±{f1(mean(em))}% против ±{f1(mean(en))}%",
                (mean(em) < mean(en) and (c or 0) > 0.3) if em else None)
        verdict("Стоимость", f"{NM[w]}: цена нового падает не больше 5% в год",
                f"падений больше 5%: {len(big)}, худшее {pct(drops[wy], 0)} ({wy} г.)", not big)
    L += ["", "<small>Если цена падала больше чем на 5% в год, ограничение «не больше −5%» в модели делает пессимистичный "
          "сценарий стоимости слишком мягким: его надо заменить на худшее падение истории.</small>", ""]
    verdict("Стоимость", "Скидка за возраст вагона б/у", "нет открытого ряда сделок с б/у вагонами", None)


# ---------- 7. Вход и выход: сигнал «ставка к максимуму за 4 года» ----------
def t_entry(L):
    L += ["## 7. Когда входить и выходить: проверка на прошлых покупках", "",
          "Каждый год t «покупаем» новый вагон по цене года t, 3 года сдаём (ставка × 365 × 95% загрузки − 12% расходов), "
          "в конце продаём по цене нового × 0,88 (возраст 3 года). Сигнал входа — ставка года t к максимуму за 4 года: "
          "≤ 0,6 — зона покупки, ≥ 0,95 — зона продажи.", "",
          "| Тип | Лет | Доход за 3 года: зона покупки | середина | зона продажи | Нижняя / верхняя треть сигнала | Связь «сигнал → доход» |",
          "|---|---|---|---|---|---|---|"]
    for w in TYPES:
        rate, price = annual(w)
        rows = []
        for t in sorted(price):
            if not all(t + i in rate for i in (1, 2, 3)) or t + 3 not in price or not all(t - i in rate for i in range(4)):
                continue
            noi = sum(rate[t + i] * 365 * UTIL * (1 - OPEX) / 1e6 for i in (1, 2, 3))
            ret = (noi + price[t + 3] * 0.88) / price[t] * 100 - 100
            s = rate[t] / max(rate[t - i] for i in range(4))
            rows.append((t, s, ret))
        if len(rows) < 5:
            L.append(f"| {NM[w]} | {len(rows)} | мало лет | | | |")
            verdict("Вход и выход", f"{NM[w]}: сигнал входа «ставка у дна»", "мало лет с ценой и ставкой", None)
            continue
        z = {k: mean([r for _, s, r in rows if f(s)]) for k, f in
             (("buy", lambda s: s <= 0.6), ("mid", lambda s: 0.6 < s < 0.95), ("sell", lambda s: s >= 0.95))}
        srt = sorted(rows, key=lambda x: x[1])
        k3 = max(1, len(srt) // 3)
        lo, hi = mean([r for *_, r in srt[:k3]]), mean([r for *_, r in srt[-k3:]])
        c = corr([s for _, s, _ in rows], [r for *_, r in rows])
        L.append(f"| {NM[w]} | {rows[0][0]}–{rows[-1][0]} ({len(rows)}) | {pct(z['buy'], 0)} | {pct(z['mid'], 0)} | "
                 f"{pct(z['sell'], 0)} | {pct(lo, 0)} / {pct(hi, 0)} | {f1(c, 2)} |")
        verdict("Вход и выход", f"{NM[w]}: покупка у дна ставки выгоднее, чем у пика",
                f"треть лет с самой низкой ставкой {pct(lo, 0)}, с самой высокой {pct(hi, 0)} за 3 года; связь {f1(c, 2)}"
                + ("" if z["buy"] is not None else "; ставка ни разу не была ниже 60% максимума — порог зоны покупки для этого типа не проверен"),
                lo > hi)
    L += ["", "<small>Связь отрицательная — чем ниже ставка при покупке (к своему максимуму), тем выше доход: это и есть "
          "подтверждение правила «покупать у дна, продавать у пика». Доход до налога и без долга.</small>", ""]


# ---------- 8. Ключевая ставка: чувствительность сделки ----------
def t_key(L):
    L += ["## 8. Ключевая ставка ±2 п.п.: насколько меняется сделка", "",
          "| Тип | Доходность вагона без долга (от ключевой не зависит): −2 / прогноз / +2 п.п. | Предельная цена, млн ₽: −2 / прогноз / +2 | Лет «аренда не покрывает платёж»: −2 / прогноз / +2 |",
          "|---|---|---|---|"]
    try:
        import zdeal
    except Exception:  # noqa: BLE001
        return
    for w in TYPES:
        out = []
        for dk in (-2, 0, 2):
            key = ";".join(f"{y}={v + dk}" for y, v in zdeal.KEY.items())
            try:
                d = zdeal.deal(w, "base", key=key)
                out.append((d["irr"], d["maxp"], len(d["neg"])))
            except (SystemExit, Exception):  # noqa: BLE001
                out.append((None, None, None))
        L.append(f"| {NM[w]} | " + " / ".join(f1(x[0]) for x in out) + " | " + " / ".join(f1(x[1], 2) for x in out) +
                 " | " + " / ".join(str(x[2]) if x[2] is not None else "—" for x in out) + " |")
        if out[2][2] is not None and out[1][2] is not None:
            verdict("Вход и выход", f"{NM[w]}: сделка выдерживает ключевую +2 п.п.",
                    f"лет без покрытия {out[1][2]} → {out[2][2]}; предельная цена {f1(out[1][1], 2)} → {f1(out[2][1], 2)} млн ₽",
                    out[2][2] <= out[1][2] + 1)
    L += ["", "<small>Ключевая ставка в расчёте — середина прогноза Банка России от 24.07.2026; после заседания 23.10.2026 "
          "обновим.</small>", ""]


def main():
    L = [f"# Проверка допущений модели на прошлом — {date.today().strftime('%d.%m.%Y')}", "",
         "<small>Только для внутреннего использования. Месячные ставки — с декабря 2024 г.; годовые ряды — 2007–2025 гг. "
         "Расчёт без нейросети: zverify.py.</small>", ""]
    for t in (t_quarters, t_elastic, t_signs, t_annual, t_pess, t_value, t_entry, t_key):
        try:
            t(L)
        except Exception as e:  # noqa: BLE001 — одна проверка не должна ронять остальные
            L += [f"_Проверка {t.__name__}: не выполнена ({type(e).__name__}: {e})_", ""]
    S = ["## Итог: допущение → результат → вердикт", "", "| Раздел | Допущение | Результат | Вердикт |", "|---|---|---|---|"]
    S += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in V]
    cnt = {k: sum(1 for x in V if x[3].startswith(k)) for k in ("✅", "❌", "⚪")}
    S += ["", f"Подтверждено {cnt['✅']}, не подтверждено {cnt['❌']}, проверить нельзя {cnt['⚪']}.", ""]
    text = "\n".join(L[:3] + S + L[3:])
    out = BASE / "saved" / "model" / f"{date.today().isoformat()}_проверка_модели.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nФайл: {out}")


if __name__ == "__main__":
    main()
