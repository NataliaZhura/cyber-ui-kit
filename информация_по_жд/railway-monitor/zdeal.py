#!/usr/bin/env python3
"""Расчёт сделки: покупка вагона в лизинг для сдачи в аренду — окупаемость, предельная цена, когда выходить, когда
докупать. 4 типа вагонов, три сценария ставки. Без нейросети (0 токенов).

  python3 zdeal.py run --wagon inno|gon|kr158|kr138|hop_grain|hop_grain_inno|fit80|fit40|fit60
                       [--price 5.2] [--scenario base|opt|pess] [--spread 3.5] [--term 20] [--util 95] [--opex 12]
                       [--key "2027=12;2028=9"] [--guest] [--out файл.md | --json]

Условия лизинга (владелец, 21.10.2026): 20 лет, без аванса, ставка = ключевая + 3,5 п.п., плавающая — платёж
пересчитывается каждый год на остаток долга (аннуитет на оставшийся срок). Вагон покупается в конце 2026 г.
Ставка аренды 2027–2030 — рабочие модели (zrate.py, ztypes.py), после 2030 г. — + инфляция в год (пессимистичный —
половина инфляции). Цена нового вагона — модели стоимости (zvagon.py, ztypes.py), после 2030 г. — + инфляция;
б/у — новый × коэффициент возраста (плавная кривая). Расчёт до налога на прибыль.
"""
import argparse
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

# Ключевая ставка, средняя за год, %: 2026 — 14,5 (Банк России, ср.-срочный прогноз 24.07.2026: 14,5–14,6);
# 2027 — 11,5 (середина 10,5–12,5); 2028 — 8,5 (середина 8,0–9,0); 2029 и далее — как 2028 г. (допущение).
# https://www.cbr.ru/Content/Document/File/194258/forecast_260724.pdf ; ставка на 21.10.2026 — 14% (решение 11.09.2026).
KEY = {2026: 14.5, 2027: 11.5, 2028: 8.5}
KEY_NOTE = ("ключевая ставка — середина прогноза Банка России от 24.07.2026 (2027 г. — 10,5–12,5%, 2028 г. — 8,0–9,0%), "
            "с 2029 г. — как в 2028 г. (допущение); 23.10.2026 — заседание Банка России с новым прогнозом: ставку обновим")
INFL = 4.0  # % в год после 2030 г. (Минэкономразвития, прогноз СЭР сентябрь 2026: 4,0% в 2027–2029 гг.)
NAMES = {"gon": "Полувагон типовой", "inno": "Полувагон инновационный", "kr158": "Крытый вагон 158 м³",
         "kr138": "Крытый вагон 138 м³", "hop_grain": "Хоппер-зерновоз", "hop_grain_inno": "Хоппер-зерновоз инновационный",
         "fit80": "Фитинговая платформа 80'", "fit40": "Фитинговая платформа 40'", "fit60": "Фитинговая платформа 60'"}
SCN = {"base": "Базовый", "opt": "Оптимистичный", "pess": "Пессимистичный"}
Y0, HORIZON = 2026, 20


def n(v, d=1):
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def key_path(over):
    k = dict(KEY)
    for kv in filter(None, (over or "").split(";")):
        y, v = kv.split("=")
        k[int(y)] = float(v.replace(",", "."))
    last = max(k)
    return lambda y: k.get(y, k[last] if y > last else k[min(k)])


def model(w, sc):
    """(ставки {год: средняя за год 2026–2030}, цена нового {год 2026–2030}, пометка о цене)."""
    if w in ("gon", "inno"):
        import zrate as Z
        import zvagon
        lvl = Z.forecast(Z.load(), w, sc)["lvl"]
        V = zvagon.load()
        p, _ = zvagon.price_path(V, w, {y: lvl[y] for y in range(2027, 2031)})
        return lvl, p, "модель цены нового вагона (zvagon), рынок 2026 г."
    import ztypes as T
    lvl = T.forecast(w, sc)["lvl"]
    if w.startswith("kr"):
        import zvagon
        V = zvagon.load()
        lv158 = lvl if w == "kr158" else T.forecast("kr158", sc)["lvl"]
        p, _ = zvagon.price_path(V, "kr158", {y: lv158[y] for y in range(2027, 2031)})
        if w == "kr138":  # цены 138 м³ в модели нет — пропорционально ставке (оценка)
            p = {y: v * lvl[2026] / lv158[2026] for y, v in p.items()}
            return lvl, p, "цена 138 м³ — как у 158 м³ пропорционально ставке (оценка; задайте свою цену)"
        return lvl, p, "модель цены нового вагона (zvagon), рынок 2026 г."
    v = T.value(w, sc)
    if not v:
        sys.exit(f"Нет модели цены для {NAMES[w]} — задайте цену: --price <млн ₽>")
    note = v["P"]["note"]
    if w.startswith("hop_grain"):
        note += ("; цена нового зерновоза 2026 г. в открытых источниках не подтверждена: 2023–2024 гг. — 5,2–7,1 млн ₽ "
                 "(Коммерсантъ, СберЛизинг), прайс лизинговой компании — от 6,0 млн ₽ без НДС; задайте свою цену")
    if w in ("fit40", "fit60"):
        note += f"; цена {NAMES[w]} — как у 80' (своей модели нет, задайте свою цену)"
    return lvl, v["new"], note


@__import__("functools").lru_cache(maxsize=None)
def paths(w, sc):
    lvl, p, note = model(w, sc)
    g = INFL / 2 if sc == "pess" else INFL
    rate, price = dict(lvl), dict(p)
    for y in range(2031, 2031 + HORIZON + 2):
        rate[y] = rate[y - 1] * (1 + g / 100)
        price[y] = price[y - 1] * (1 + INFL / 100)
    return rate, price, note


def age_k(a):
    import ztypes
    return ztypes.age_k(a)


def deal(w, sc, price=None, spread=3.5, term=20, util=95, opex=12, key=None, buy=Y0):
    """Покупка в конце года buy, лизинг на term лет. Все суммы — млн ₽ без НДС."""
    rate, newp, note = paths(w, sc)
    rate, newp = dict(rate), dict(newp)
    kp = key_path(key)
    P = price if price else newp[buy]
    bal, cum, cum_noi, rows = P, 0.0, 0.0, []
    opex0 = rate[buy + 1] * 365 * util / 100 / 1e6 * opex / 100
    for k in range(1, HORIZON + 1):
        y = buy + k
        rev = rate[y] * 365 * util / 100 / 1e6
        cost = opex0 * (1 + INFL / 100) ** (k - 1)
        noi = rev - cost
        r = (kp(y) + spread) / 100
        left = term - k + 1
        if left > 0 and bal > 1e-9:
            pay = bal * r / (1 - (1 + r) ** -left)  # аннуитет на остаток срока по ставке этого года
            bal -= pay - bal * r
        else:
            pay = 0.0
        cum += noi - pay
        cum_noi += noi
        val = newp[y] * age_k(k)
        rows.append({"y": y, "k": k, "rate": rate[y], "rev": rev, "noi": noi, "r": r * 100, "pay": pay, "cf": noi - pay,
                     "cum": cum, "dscr": noi / pay if pay else None, "bal": max(bal, 0), "val": val,
                     "exit": cum + val - max(bal, 0), "cum_noi": cum_noi})
    # доходность удержания на год вперёд: (чистый доход + рост цены б/у) / цена б/у против ставки лизинга
    # выход — с года, после которого удержание ни разу больше не окупает ставку лизинга (временный провал — не повод)
    hold = None
    for a, b in zip(rows, rows[1:]):
        a["hold"] = (b["noi"] + b["val"] - a["val"]) / a["val"] * 100
        if a["hold"] >= b["r"]:
            hold = None
        elif hold is None:
            hold = a["y"]
    for i, x in enumerate(rows):  # доходность, если продать вагон в конце этого года
        f = [-P] + [z["noi"] for z in rows[:i + 1]]
        f[-1] += x["val"]
        x["irr_to"] = irr(f)
    flows = [-P] + [x["noi"] for x in rows]
    flows[-1] += rows[-1]["val"]
    return {"w": w, "sc": sc, "price": P, "rows": rows, "note": note, "irr": irr(flows),
            "payback": next((x["y"] for x in rows if x["cum_noi"] >= P), None),
            "neg": [x["y"] for x in rows if x["dscr"] is not None and x["dscr"] < 1],
            "maxp": max_price(rows, kp, spread, buy), "exit": hold, "market": newp[buy]}


def max_price(rows, kp, spread, buy):
    """Предельная цена: сегодняшняя стоимость чистого дохода за 20 лет + цена б/у в конце, по ставке лизинга."""
    disc, pv = 1.0, 0.0
    for x in rows:
        disc /= 1 + (kp(x["y"]) + spread) / 100
        pv += x["noi"] * disc
    return pv + rows[-1]["val"] * disc


def irr(flows):
    lo, hi = -0.9, 1.0
    f = lambda r: sum(c / (1 + r) ** i for i, c in enumerate(flows))
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
    return mid * 100


def buy_more(w, sc, a):
    """Когда докупать: предельная цена вагона, купленного в конце года, против прогноза рыночной цены нового."""
    out = []
    for b in range(Y0, 2031):
        d = deal(w, sc, None, a.spread, a.term, a.util, a.opex, a.key, buy=b)
        k = d["market"] / d["maxp"]
        out.append((b, d["market"], d["maxp"], "докупать" if k <= 0.9 else "можно" if k <= 1 else "дорого"))
    return out


def report(a):
    D = {sc: deal(a.wagon, sc, a.price, a.spread, a.term, a.util, a.opex, a.key) for sc in SCN}
    d = D[a.scenario]
    nm = NAMES[a.wagon]
    L = [f"# Сделка: {nm.lower()} в лизинг — окупаемость и предельная цена", "",
         f"<small>млн ₽ без НДС · покупка в конце 2026 г. · лизинг {a.term} лет без аванса, ставка = ключевая + "
         f"{n(a.spread)} п.п. (плавающая) · загрузка {a.util}% · расходы {a.opex}% выручки 2027 г. + инфляция · оценка, "
         "не инвестиционная рекомендация</small>", "", "## Коротко", "",
         "| Сценарий ставки | Цена покупки | Предельная цена | Доходность вагона, % годовых | Окупаемость (год) | Годы, когда аренда не покрывает платёж | Выйти (продать) в конце года |",
         "|---|---|---|---|---|---|---|"]
    for sc in ("base", "opt", "pess"):
        x = D[sc]
        L.append(f"| {SCN[sc]} | {n(x['price'], 2)} | {n(x['maxp'], 2)} | {n(x['irr']) if x['irr'] is not None else '—'} | "
                 f"{x['payback'] or 'не окупается за 20 лет'} | {', '.join(map(str, x['neg'][:6])) + ('…' if len(x['neg']) > 6 else '') or 'нет'} | "
                 f"{x['exit'] or 'держать весь срок'} |")
    v = "покупка оправдана" if d["price"] <= d["maxp"] * 0.9 else "на грани" if d["price"] <= d["maxp"] else "дорого"
    if v == "покупка оправдана" and len(d["neg"]) >= 3:
        v = "оправдана по цене, но аренда не покрывает платёж несколько лет"
    L += ["", f"**Вывод ({SCN[a.scenario].lower()} сценарий): {v}** — цена {n(d['price'], 2)} млн ₽ против предельной "
          f"{n(d['maxp'], 2)} млн ₽ (запас {n((1 - d['price'] / d['maxp']) * 100)}%).", "",
          "<small>Предельная цена — столько стоит сегодня весь чистый доход вагона за 20 лет плюс цена б/у в конце, если "
          "дисконтировать по ставке лизинга; дороже — сделка не окупает стоимость денег. Доходность вагона — внутренняя "
          "норма доходности (цена → чистый доход → продажа б/у через 20 лет); сравнивать со ставкой лизинга. "
          "Окупаемость — год, когда сумма чистого дохода превысит цену покупки.</small>", "",
          f"## 1. Денежный поток по годам ({SCN[a.scenario].lower()})", "",
          "| Год | Ставка, ₽/сут | Чистый доход | Ставка лизинга, % | Платёж | Покрытие платежа | Остаток долга | Цена б/у | Итог, если продать |",
          "|---|---|---|---|---|---|---|---|---|"]
    for x in d["rows"]:
        L.append(f"| {x['y']} | {n(x['rate'], 0)} | {n(x['noi'], 2)} | {n(x['r'])} | {n(x['pay'], 2)} | "
                 f"{n(x['dscr'], 2) + (' ⚠' if x['dscr'] < 1 else '') if x['dscr'] else '—'} | {n(x['bal'], 2)} | "
                 f"{n(x['val'], 2)} | {n(x['exit'], 2)} |")
    L += ["", "<small>Покрытие платежа = чистый доход / платёж: ниже 1 — аренда не покрывает лизинг, нужна доплата "
          "(для банка обычно нужно 1,2 и выше). «Итог, если продать» — накопленный поток после платежей + цена б/у − "
          "остаток долга.</small>", "", "## 2. Когда выходить", ""]
    if d["exit"]:
        L.append(f"Держать до конца {d['exit']} г.: после этого доход года (аренда + рост цены б/у) к цене вагона ниже "
                 "ставки лизинга — деньги выгоднее вынуть (продать вагон, погасить долг).")
    else:
        L.append("Доход удержания каждый год выше ставки лизинга — держать весь срок.")
    if d["neg"]:
        L.append(f"Риск: в {', '.join(map(str, d['neg'][:6]))} г. аренда не покрывает платёж — заложить доплату или "
                 "договориться о графике (каникулы, сезонный платёж).")
    L += ["", "**Калькулятор выхода: если продать вагон в конце года**", "",
          "| Год продажи | Цена б/у | Долг к погашению | Накоплено после платежей | Итог | Доходность до продажи, % |", "|---|---|---|---|---|---|"]
    for x in d["rows"]:
        if x["k"] in (1, 2, 3, 4, 5, 7, 10, 15, 20):
            L.append(f"| {x['y']} | {n(x['val'], 2)} | {n(x['bal'], 2)} | {n(x['cum'], 2)} | {n(x['exit'], 2)} | "
                     f"{n(x['irr_to']) if x['irr_to'] is not None else '—'} |")
    L += ["", f"<small>Доходность до продажи — как если бы вагон купили за {n(d['price'], 2)} млн ₽, получали чистый доход и "
          f"продали в этом году; сравнивать со ставкой лизинга и с доходностью удержания весь срок "
          f"({n(d['irr']) if d['irr'] is not None else '—'}%).</small>", ""]
    A = advice(a.wagon, D)
    L += ["## Предложения и обоснование по рынку", "", f"> **Что делать:** {A['action']}; выход — {A['exit']}.", "",
          "Почему:"] + [f"- {x}" for x in A["why"]]
    L += ["", "## 3. Когда докупать", "", "| Покупка в конце года | Цена нового (прогноз) | Предельная цена | Решение |",
          "|---|---|---|---|"]
    for b, m, mp, s in buy_more(a.wagon, a.scenario, a):
        L.append(f"| {b} | {n(m, 2)} | {n(mp, 2)} | {s} |")
    L += ["", "<small>«Докупать» — рыночная цена на 10% и больше ниже предельной; «дорого» — выше предельной.</small>", "",
          "## Допущения", "", f"- {KEY_NOTE}.",
          f"- Ставка аренды 2027–2030 гг. — рабочие модели; после 2030 г. — +{n(INFL)}% в год (пессимистичный — +{n(INFL / 2)}%).",
          f"- Цена вагона: {d['note'].rstrip('.')}.", "- Загрузка и расходы (ремонт, страховка, налог на имущество) — допущения, "
          "меняются в мини-приложении («Расчёт сделки»). Налог на прибыль и НДС не учтены.", "",
          "<small>Подготовлено по открытым источникам и данным участников рынка. Выводы — оценка рынка.</small>"]
    return D, "\n".join(L) + "\n"


def as_json(D, a):
    d = D[a.scenario]
    return {"wagon": NAMES[a.wagon], "scenario": SCN[a.scenario],
            "summary": {SCN[sc]: {"price": round(x["price"], 2), "maxp": round(x["maxp"], 2),
                                  "irr": round(x["irr"], 1) if x["irr"] is not None else None, "payback": x["payback"],
                                  "neg": x["neg"], "exit": x["exit"]} for sc, x in D.items()},
            "rows": [{k: (round(v, 1 if k == "irr_to" else 2) if isinstance(v, float) else v) for k, v in x.items() if k in
                      ("y", "rate", "noi", "r", "pay", "dscr", "bal", "val", "exit", "cum", "irr_to")} for x in d["rows"]],
            "irr_full": round(d["irr"], 1) if d["irr"] is not None else None, "advice": advice(a.wagon, D),
            "buy": [{"y": b, "market": round(m, 2), "maxp": round(mp, 2), "s": s} for b, m, mp, s in buy_more(a.wagon, a.scenario, a)],
            "note": KEY_NOTE, "price_note": d["note"]}


EV_TYPE = {"gon": "gon", "inno": "gon", "kr158": "kr158", "kr138": "kr158", "hop_grain": "hop_grain",
           "hop_grain_inno": "hop_grain", "fit80": "fit80", "fit40": "fit80", "fit60": "fit80"}
TARIFF_ROW = {"gon": "Полувагон", "inno": "Инновационный", "kr158": "Крытый", "kr138": "Крытый", "hop_grain": "Хоппер",
              "hop_grain_inno": "Хоппер", "fit80": "Фитинговая", "fit40": "Фитинговая", "fit60": "Фитинговая"}


def advice(w, D):
    """Предложения с обоснованием по рынку: покупать / держать / продавать. Каждое «почему» — цифра из базы или модели."""
    b, ps = D["base"], D["pess"]
    why, score = [], 0
    k = b["price"] / b["maxp"]
    if k <= 0.9:
        score += 1
        why.append(f"цена {n(b['price'], 2)} млн ₽ на {n((1 - k) * 100, 0)}% ниже предельной по базовому сценарию")
    elif k > 1:
        score -= 1
        why.append(f"цена выше предельной по базовому сценарию ({n(b['price'], 2)} против {n(b['maxp'], 2)} млн ₽)")
    if ps["price"] > ps["maxp"]:
        score -= 1
        why.append(f"в пессимистичном сценарии предельная цена {n(ps['maxp'], 2)} млн ₽ — ниже цены: риск для кредитора")
    if len(b["neg"]) >= 3:
        score -= 1
    if b["neg"]:
        why.append(f"в {', '.join(map(str, b['neg'][:3]))} г. аренда не покрывает платёж — нужен запас или сезонный график")
    try:
        import zhelp
        import zrates
        S = zrates.series()
        r = S.get(zhelp.RATE_ITEM[w], {})
        if len(r) >= 2:
            last = max(r)
            prev, year = r.get(zrates.zobs.shift(last, -1)), r.get(zrates.zobs.shift(last, -12))
            if prev:
                ch = (r[last] / prev - 1) * 100
                score += 1 if ch >= 2 else -1 if ch <= -2 else 0
                why.append(f"ставка аренды за месяц {ch:+.1f}% ({last}, {round(r[last])} ₽/сут)".replace(".", ","))
            if year:
                why.append(f"к году назад {(r[last] / year - 1) * 100:+.1f}%".replace(".", ","))
        pk = S.get(zhelp.PARK_ITEM[w], {})
        if len(pk) >= 2:
            last = max(pk)
            prev = pk.get(zrates.zobs.shift(last, -1))
            if prev:
                ch = (pk[last] / prev - 1) * 100
                if "work" in zhelp.PARK_ITEM[w]:
                    score += 1 if ch <= -0.5 else -1 if ch >= 0.5 else 0
                    why.append(f"рабочий парк за месяц {ch:+.1f}% — {'вагоны уходят в отстой, предложение сжимается' if ch < 0 else 'предложение растёт'}".replace(".", ","))
    except Exception:  # noqa: BLE001 — нет базы наблюдений: без рыночных строк
        pass
    try:
        import zevents
        it = zevents.events(EV_TYPE[w], 30).get(EV_TYPE[w], [])
        if it:
            s, v = zevents.verdict(it)
            score += 1 if s >= 2 else -1 if s <= -2 else 0
            why.append(f"события рынка за 30 дней: {'+' if s > 0 else ''}{s} — подтверждают {v} сценарий")
    except SystemExit:
        pass
    try:
        import ztariff
        row = next((x for x in ztariff.BY_TYPE if x[0].startswith(TARIFF_ROW[w])), None)
        if row:
            why.append("тарифы РЖД: " + "; ".join(x for x in ((f"выгодно — {row[1]}" if row[1].strip("— ") else ""),
                                                              f"невыгодно — {row[2]}") if x))
    except Exception:  # noqa: BLE001
        pass
    act = ("покупать / докупать: цена ниже предельной, рынок поддерживает" if score >= 2 and k <= 0.9 else
           "не покупать по этой цене, действующий парк — держать и искать выход, если ставка продолжит падать" if score <= -2
           else "держать; покупать — только с запасом к предельной цене и проверкой пессимистичного сценария")
    ex = b["exit"]
    return {"action": act, "score": score, "why": why,
            "exit": (f"по базовому сценарию — продать в конце {ex} г." if ex else "по базовому сценарию — держать весь срок")}


def args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--wagon", default="inno", choices=list(NAMES))
    r.add_argument("--scenario", default="base", choices=list(SCN))
    r.add_argument("--price", type=float)
    r.add_argument("--spread", type=float, default=3.5)
    r.add_argument("--term", type=int, default=20)
    r.add_argument("--util", type=float, default=95)
    r.add_argument("--opex", type=float, default=12)
    r.add_argument("--key", default="")
    r.add_argument("--guest", action="store_true")
    r.add_argument("--json", action="store_true")
    r.add_argument("--out")
    return ap.parse_args(argv)


if __name__ == "__main__":
    a = args()
    D, md = report(a)
    if a.json:
        print(json.dumps(as_json(D, a), ensure_ascii=False))
    elif a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Файл: {a.out}")
    else:
        print(md)
