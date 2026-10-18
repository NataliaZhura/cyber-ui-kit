#!/usr/bin/env python3
"""Завод или оператор вагонов: финансовый анализ по методике, свободный денежный поток, сравнение с отраслью,
стресс-тест, риск аванса и задержки поставки.

  python3 zfactory.py run <ИНН|ОГРН> --name "Алтайвагон" [--deal 500000] [--zavod] [--guest] [--out файл.md]
      --deal   сумма сделки, тыс. ₽ (для расчёта аванса в % от сделки)
      --zavod  блоки «аванс» и «задержка поставки» (производитель вагонов); без ключа — оператор
  python3 zfactory.py peers zavod|oper [--force]
      отраслевое сравнение: показатели заводов (ИНН из ZAVODY.md) или операторов (watchlist.csv, тип «оператор»)
      → peers_<группа>.json; уже посчитанные за последний год не запрашиваются (без --force). Раз в месяц.

Отчётность — РСБУ юрлица из ГИР БО через Checko (те же запросы и кеш, что у Ави: ~/aviation-monitor/checko.py).
Нет строки — «нет данных», не ноль. Средние — (начало года + конец года) / 2, год — 360 дней, как в методике.
Стоп-правило: чистый оборотный капитал < 0 или долг > 7 годовых прибылей от продаж — решения нет без пояснения
компании. Пороги — в словаре TH; итог — оценка эксперта по открытой отчётности, а не заключение о кредитоспособности.
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.environ.get("AVI_DIR", str(Path.home() / "aviation-monitor")))
import checko  # noqa: E402

HERE = Path(__file__).resolve().parent

TH = {
    "adv_rev_q": 0.25,      # аванс не больше 25% квартальной выручки завода
    "adv_free_cash": 1.0,   # и не больше свободных денег (деньги − 25% краткосрочного долга)
    "adv_equity": 0.10,     # и не больше 10% собственного капитала
    "deal_cap": {"A": 0.25, "B": 0.20, "C": 0.10, "D": 0.0, "E": 0.0},  # доля сделки без банковской гарантии
    "stress": [("База", 1.0, 0.0, 0.0), ("Платежи по долгу +20%", 1.0, 0.2, 0.0),
               ("Платежи по долгу +50%", 1.0, 0.5, 0.0), ("Выручка −20%", 0.8, 0.0, 0.0),
               ("Ключевая ставка +2 п.п.", 1.0, 0.0, 2.0), ("Всё сразу: выручка −20%, долг +50%, ставка +2", 0.8, 0.5, 2.0)],
    "stop_debt_ebit": 7.0,  # долг больше 7 прибылей от продаж — прибыли хватает только на проценты (стоп)
    "debt_ebit_ok": 3.0,    # до 3 — надёжный заёмщик (методика: 2–3)
    "cur_liq": (1.0, 2.0),  # текущая ликвидность: приемлемо 1–2
    "drop": 0.15,           # падение показателя больше чем на 15% за год — «ухудшение»
    "stale_years": 2,       # отчётность старше (текущий год − 2) — устарела: выводы не делать, в отрасль не брать
}


def stale(year):
    return int(year) < datetime.now().year - TH["stale_years"]

# строки РСБУ; оттоки денег (4xxx) в отчёте со знаком минус — берём по модулю
K = {"rev": "2110", "cogs": "2120", "sell": "2210", "adm": "2220", "ebit": "2200", "int": "2330", "net": "2400",
     "nca": "1100", "ca": "1200", "inv": "1210", "ar": "1230", "stfi": "1240", "cash": "1250", "eq": "1300",
     "reval": "1340", "re": "1370", "ltl": "1400", "debt_l": "1410", "stl": "1500", "debt_s": "1510", "ap": "1520",
     "defrev": "1530", "ta": "1600", "cfo": "4100", "rcpt": "4111", "int_paid": "4123", "capex": "4221",
     "borrow": "4311", "repay": "4321", "div": "4322"}
ABS = {"cogs", "sell", "adm", "int", "int_paid", "capex", "repay", "div"}

# формулы для справки: строки баланса и отчёта о финансовых результатах (Δ — прирост за год, ср. — средняя за год)
F = {
    "cur_liq": "1200 / 1500", "quick": "(1230 + 1240 + 1250) / 1500", "abs_liq": "(1240 + 1250) / 1500",
    "cash_days": "1250 / ((2120 + 2210 + 2220) / 360)", "nwc": "1300 + 1400 − 1100", "nwc_ta": "(1300 + 1400 − 1100) / 1600",
    "eq_ta": "1300 / 1600", "eq_td": "1300 / (1400 + 1500)", "debt_ebit": "(1410 + 1510) / 2200",
    "int_cov": "2200 / 2330", "selffin": "Δ1370 / 2400", "at_turn": "2110 / ср. 1600",
    "cost_cycle": "ср. (1200 − 1250) / (2110 / 360)", "credit_cycle": "ср. (1500 − 1510) / (2110 / 360)",
    "ros": "2200 / 2110", "npm": "2400 / 2110", "roe": "2400 / ср. 1300", "roa": "2400 / ср. 1600",
    "fcf": "2400 − (Δ1100 − Δ1340) − Δ[(1200 − 1250) − (1500 − 1510 − 1530)]", "fcf_cf": "4100 − 4221",
}
FCF_WORDS = ("чистая прибыль − вложения во внеоборотные активы (прирост внеоборотных активов без переоценки) − "
             "прирост оборотного капитала (оборотные активы без денег минус краткосрочные обязательства без кредитов "
             "и доходов будущих периодов)")


def num(lines, code):
    v = (lines or {}).get(code)
    return float(v) / 1000 if isinstance(v, (int, float)) else None  # рубли → тыс. ₽


def years_data(ys):
    """{год: {поле: тыс. ₽}} по всем годам отчётности."""
    out = {}
    for y, lines in ys.items():
        d = {}
        for k, code in K.items():
            v = num(lines, code)
            d[k] = abs(v) if (v is not None and k in ABS) else v
        out[y] = d
    return out


def div(a, b):
    return None if a is None or b in (None, 0) else a / b


def add(*xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) if xs else None


def avg(cur, prev):
    return cur if prev is None else None if cur is None else (cur + prev) / 2


def ratios(Y, y):
    """Показатели года y (prev — прошлый год, для средних и приростов)."""
    c, p = Y[y], Y.get(str(int(y) - 1), {})
    r = {"year": y}
    r["debt"] = add(c["debt_l"], c["debt_s"])
    r["cur_liq"] = div(c["ca"], c["stl"])
    r["quick"] = div(add(c["ar"], c["stfi"], c["cash"]), c["stl"])
    r["abs_liq"] = div(add(c["stfi"], c["cash"]), c["stl"])
    r["cash_days"] = div(c["cash"], div(add(c["cogs"], c["sell"], c["adm"]), 360))
    r["nwc"] = None if c["eq"] is None or c["nca"] is None else c["eq"] + (c["ltl"] or 0) - c["nca"]
    r["nwc_ta"] = div(r["nwc"], c["ta"])
    r["eq_ta"] = div(c["eq"], c["ta"])
    r["eq_td"] = div(c["eq"], add(c["ltl"], c["stl"]))
    r["debt_ebit"] = div(r["debt"], c["ebit"]) if (c["ebit"] or 0) > 0 else None
    r["no_ebit"] = bool(r["debt"]) and (c["ebit"] is not None and c["ebit"] <= 0)
    r["int_cov"] = div(c["ebit"], c["int"])
    d_re = None if c["re"] is None or p.get("re") is None else c["re"] - p["re"]
    r["selffin"] = div(d_re, c["net"]) if (c["net"] or 0) > 0 and (d_re or 0) > 0 else None
    r["at_turn"] = div(c["rev"], avg(c["ta"], p.get("ta")))
    wc_a = None if c["ca"] is None else c["ca"] - (c["cash"] or 0)
    wc_a_p = None if p.get("ca") is None else p["ca"] - (p.get("cash") or 0)
    r["cost_cycle"] = div(avg(wc_a, wc_a_p), div(c["rev"], 360))
    cl = None if c["stl"] is None else c["stl"] - (c["debt_s"] or 0)
    cl_p = None if p.get("stl") is None else p["stl"] - (p.get("debt_s") or 0)
    r["credit_cycle"] = div(avg(cl, cl_p), div(c["rev"], 360))
    r["ros"], r["npm"] = div(c["ebit"], c["rev"]), div(c["net"], c["rev"])
    eq_avg = avg(c["eq"], p.get("eq"))
    r["roe"] = div(c["net"], eq_avg) if (eq_avg or 0) > 0 else None
    r["roa"] = div(c["net"], avg(c["ta"], p.get("ta")))
    # свободный денежный поток по балансу: амортизация сокращается (прибыль + износ − (прирост ВНА + износ))
    if p and None not in (c["net"], c["nca"], p.get("nca"), wc_a, wc_a_p, cl, cl_p):
        r["capex_b"] = (c["nca"] - p["nca"]) - ((c["reval"] or 0) - (p.get("reval") or 0))
        r["dwc"] = (wc_a - cl + (c["defrev"] or 0)) - (wc_a_p - cl_p + (p.get("defrev") or 0))
        r["fcf"] = c["net"] - r["capex_b"] - r["dwc"]
    else:
        r["capex_b"] = r["dwc"] = r["fcf"] = None
    r["fcf_cf"] = None if c["cfo"] is None else c["cfo"] - (c["capex"] or 0)
    r["fcf_rev"] = div(r["fcf"], c["rev"])
    return r


# ---------- оформление ----------
def t(v):
    if v is None:
        return "нет данных"
    n, u = (v / 1e6, "млрд ₽") if abs(v) >= 1e6 else (v / 1e3, "млн ₽") if abs(v) >= 1e3 else (v, "тыс. ₽")
    s = f"{n:,.1f}" if u == "млрд ₽" else f"{n:,.0f}"
    return s.replace(",", " ").replace(".", ",").replace("-", "−") + " " + u


def pct(v, sign=True):
    return "нет данных" if v is None else (f"{v * 100:+.0f}%" if sign else f"{v * 100:.0f}%").replace("-", "−")


def x(v, nd=2):
    return "нет данных" if v is None else f"{v:.{nd}f}".replace(".", ",").replace("-", "−")


def days(v):
    return "нет данных" if v is None else f"{v:.0f} дн."


def ch(a, b):
    return None if a is None or b in (None, 0) else a / b - 1


FMT = {"cur_liq": x, "quick": x, "abs_liq": x, "cash_days": days, "nwc": t, "nwc_ta": lambda v: pct(v, False),
       "eq_ta": lambda v: pct(v, False), "eq_td": x, "debt_ebit": lambda v: "нет данных" if v is None else x(v, 1) + " года",
       "int_cov": lambda v: "нет данных" if v is None else x(v, 1) + " раза", "selffin": lambda v: pct(v, False),
       "at_turn": x, "cost_cycle": days, "credit_cycle": days, "ros": lambda v: pct(v, False),
       "npm": lambda v: pct(v, False), "roe": lambda v: pct(v, False), "roa": lambda v: pct(v, False), "fcf": t,
       "fcf_rev": lambda v: pct(v, False)}

ROWS = [("Ликвидность", None), ("Текущая ликвидность", "cur_liq"), ("Срочная ликвидность", "quick"),
        ("Абсолютная ликвидность", "abs_liq"), ("Деньги, дней платежей", "cash_days"),
        ("Чистый оборотный капитал", "nwc"),
        ("Устойчивость и долг", None), ("Капитал / активы", "eq_ta"), ("Капитал / заёмные", "eq_td"),
        ("Долг / прибыль от продаж", "debt_ebit"), ("Покрытие процентов", "int_cov"),
        ("Прибыль, оставленная в компании", "selffin"),
        ("Оборачиваемость", None), ("Оборачиваемость активов", "at_turn"),
        ("Запасы и долги покупателей", "cost_cycle"), ("Поставщики и авансы покупателей", "credit_cycle"),
        ("Прибыльность", None), ("Прибыльность продаж", "ros"), ("Прибыльность всей деятельности", "npm"),
        ("Рентабельность капитала", "roe"), ("Рентабельность активов", "roa"),
        ("Свободный денежный поток", "fcf")]

GRADE = {"A": "Низкий", "B": "Умеренный", "C": "Повышенный", "D": "Высокий", "E": "Критический"}


# ---------- диагноз по методике ----------
def worse(cur, prev, higher_better=True):
    if cur is None or prev in (None, 0):
        return False
    c = (cur - prev) / abs(prev)
    return c < -TH["drop"] if higher_better else c > TH["drop"]


def diagnose(Y, R, yrs):
    """Три проблемы (ликвидность, устойчивость, рентабельность), стоп-условия и причины."""
    y = yrs[-1]
    r, rp = R[y], R.get(yrs[-2]) if len(yrs) > 1 else None
    c, p = Y[y], Y[yrs[-2]] if len(yrs) > 1 else {}
    rp = rp or {}
    stops, prob = [], {}

    liq = []
    if r["nwc"] is not None and r["nwc"] < 0:
        stops.append(f"чистый оборотный капитал отрицательный ({t(r['nwc'])}): часть внеоборотных активов куплена "
                     "на короткие долги, запаса на случай задержки оплат нет")
    if r["cur_liq"] is not None and r["cur_liq"] < TH["cur_liq"][0]:
        liq.append(f"текущая ликвидность {x(r['cur_liq'])} — ниже 1: оборотных активов не хватает на долги года")
    if worse(r["cur_liq"], rp.get("cur_liq")):
        liq.append(f"текущая ликвидность снизилась: {x(rp.get('cur_liq'))} → {x(r['cur_liq'])}")
    if worse(r["nwc"], rp.get("nwc")):
        liq.append(f"чистый оборотный капитал сократился: {t(rp['nwc'])} → {t(r['nwc'])}")
    prob["Ликвидность"] = ("критично" if r["nwc"] is not None and r["nwc"] < 0 else "ухудшение" if liq else "норма", liq)

    st = []
    if r["debt_ebit"] is not None and r["debt_ebit"] > TH["stop_debt_ebit"]:
        stops.append(f"долг в {x(r['debt_ebit'], 1)} раза больше годовой прибыли от продаж (порог — "
                     f"{TH['stop_debt_ebit']:.0f}): прибыли хватает в лучшем случае на проценты, не на погашение")
    elif r["no_ebit"]:
        stops.append(f"долг {t(r['debt'])} при убытке от продаж: гасить долг из прибыли нечем")
    elif r["debt_ebit"] is not None and r["debt_ebit"] > TH["debt_ebit_ok"]:
        st.append(f"долг — {x(r['debt_ebit'], 1)} годовой прибыли от продаж (надёжно — до 2–3)")
    if c["eq"] is not None and c["eq"] < 0:
        st.append(f"собственный капитал отрицательный ({t(c['eq'])}): долги больше имущества")
    if r["eq_td"] is not None and r["eq_td"] < 1 and worse(r["eq_td"], rp.get("eq_td")):
        st.append(f"собственного капитала меньше заёмного, и доля падает: {x(rp.get('eq_td'))} → {x(r['eq_td'])}")
    if r["int_cov"] is not None and r["int_cov"] < 1:
        st.append(f"прибыль от продаж не покрывает проценты (покрытие {x(r['int_cov'], 1)} раза)")
    crit_st = any("прибыли от продаж (порог" in s or "при убытке от продаж" in s for s in stops)
    prob["Устойчивость"] = ("критично" if crit_st else "ухудшение" if st else "норма", st)

    pr = []
    if (c["net"] or 0) < 0:
        pr.append(f"чистый убыток {t(c['net'])}" + (" второй год подряд" if (p.get("net") or 0) < 0 else ""))
    if worse(r["roe"], rp.get("roe")):
        pr.append(f"рентабельность собственного капитала упала: {pct(rp.get('roe'), False)} → {pct(r['roe'], False)}")
    if worse(r["ros"], rp.get("ros")):
        pr.append(f"прибыльность продаж упала: {pct(rp.get('ros'), False)} → {pct(r['ros'], False)}")
    prob["Рентабельность"] = ("ухудшение" if pr else "норма", pr)

    # причины (методика: убытки, вложения сверх прибыли, короткие кредиты на вложения, оборотный капитал, вывод прибыли)
    causes = []
    d_nca = None if c["nca"] is None or p.get("nca") is None else c["nca"] - p["nca"]
    d_eq = None if c["eq"] is None or p.get("eq") is None else c["eq"] - p["eq"]
    d_ltl = (c["ltl"] or 0) - (p.get("ltl") or 0) if p else None
    d_ds = (c["debt_s"] or 0) - (p.get("debt_s") or 0) if p else None
    if (c["net"] or 0) < 0:
        causes.append("убытки сокращают собственный капитал — главная причина падения ликвидности и устойчивости")
    if d_nca is not None and d_eq is not None and d_nca > max(d_eq, 0):
        causes.append(f"вложения во внеоборотные активы ({t(d_nca)}) больше прироста собственного капитала ({t(d_eq)}) — "
                      "недостающее взято в долг")
        if d_ds is not None and d_ds > 0 and d_nca > max(d_eq, 0) + max(d_ltl or 0, 0):
            causes.append(f"вложения частично на короткие кредиты (прирост {t(d_ds)}) — нарушено правило «длинные "
                          "вложения — на длинные деньги»")
    if worse(r["cost_cycle"], rp.get("cost_cycle"), higher_better=False):
        causes.append(f"деньги дольше лежат в запасах и долгах покупателей: {days(rp.get('cost_cycle'))} → "
                      f"{days(r['cost_cycle'])}")
    if worse(r["credit_cycle"], rp.get("credit_cycle"), higher_better=False) and worse(r["cost_cycle"], rp.get("cost_cycle"), False):
        causes.append(f"отсрочка поставщикам выросла ({days(rp.get('credit_cycle'))} → {days(r['credit_cycle'])}) — "
                      "похоже, вынужденно: нехватку денег закрывают за счёт поставщиков")
    if (c["div"] or 0) > 0 and (r["selffin"] is None or r["selffin"] < 0.5):
        causes.append(f"дивиденды {t(c['div'])} при низкой доле прибыли, оставленной в компании")
    loss_yrs = None
    if (c["re"] or 0) < 0:
        best = max([Y[k]["net"] for k in yrs if (Y[k]["net"] or 0) > 0] or [0])
        loss_yrs = -c["re"] / best if best else None
        causes.append(f"накопленный убыток {t(c['re'])}" + (
            f" — при лучшей годовой прибыли его покрытие займёт {x(loss_yrs, 1)} года" if loss_yrs else
            " — прибыльных лет в отчётности нет"))
    return stops, prob, causes


def grade(prob, stops, cover):
    pts = sum({"норма": 0, "ухудшение": 1, "критично": 2}[v[0]] for v in prob.values())
    pts += cover is not None and cover < 1.0
    cls = "ABCDE"[min(4, pts)]
    if stops and cls < "D":
        cls = "D"  # стоп-условие: решение только после пояснения компании
    return cls


# ---------- денежный поток и стресс (прежний расчёт) ----------
def runway(m, rev_k=1.0, debt_k=0.0, rate_pp=0.0):
    """Сколько месяцев хватит денег: деньги / (месячные платежи по долгу − месячный поток), с учётом стресса."""
    cfo, cash = m["cfo"], m["cash"]
    if cfo is None or cash is None:
        return None, None
    debt = add(m["debt_l"], m["debt_s"]) or 0
    ebit_drop = (1 - rev_k) * (m["rev"] or 0) * 0.5  # при падении выручки половина выпадает из потока (постоянные затраты)
    extra_int = debt * rate_pp / 100
    service = ((m["repay"] or (m["debt_s"] or 0)) + (m["int_paid"] or m["int"] or 0)) * (1 + debt_k) + extra_int
    flow = cfo + (m["int_paid"] or m["int"] or 0) - ebit_drop  # поток до процентов
    cover = flow / service if service else None
    gap = service - flow
    months = None if gap <= 0 else 12 * cash / gap
    return cover, months


def advance_block(m, mp, cls, deal):
    rows, flags, caps = [], [], []
    if m["rev"]:
        caps.append(("25% квартальной выручки", TH["adv_rev_q"] * m["rev"] / 4))
    if m["cash"] is not None:
        caps.append(("свободные деньги (деньги − 25% краткосрочного долга)", max(0, m["cash"] - 0.25 * (m["debt_s"] or 0))))
    if m["eq"] is not None:
        caps.append(("10% собственного капитала", max(0, TH["adv_equity"] * m["eq"])))
    lim = min(v for _, v in caps) if caps else None
    share = TH["deal_cap"][cls]
    rows += ["| Ограничение | Сумма |", "|---|---|"] + [f"| {n} | {t(v)} |" for n, v in caps]
    by_deal = deal * share if deal else None
    final = min(z for z in (lim, by_deal) if z is not None) if (lim is not None or by_deal is not None) else None
    d_ap, d_inv = ch(m["ap"], mp.get("ap")), ch(m["inv"], mp.get("inv"))
    if d_ap is not None and d_inv is not None and d_ap > 0.2 and d_inv < d_ap / 2:
        flags.append(f"кредиторка (в ней авансы покупателей) выросла на {pct(d_ap)}, а запасы — только на {pct(d_inv)}: "
                     "полученные деньги могли пойти не в производство")
    if m["repay"] and m["cfo"] is not None and m["repay"] > max(m["cfo"], 0) + (m["borrow"] or 0) * 0.5:
        flags.append(f"возврат кредитов {t(m['repay'])} больше потока от операций {t(m['cfo'])}: долги гасятся "
                     "за счёт других денег, в том числе авансов")
    if m["cfo"] is not None and m["cfo"] < 0 and (m["debt_s"] or 0) > (m["cash"] or 0):
        flags.append("поток от операций отрицательный, а долг к погашению за 12 месяцев больше денег на счетах")
    return rows, share, final, flags


def delay_block(m, mp):
    flags = []
    r = ch(m["rev"], mp.get("rev"))
    if r is not None and r < -0.2:
        flags.append(f"выручка упала на {abs(r) * 100:.0f}% — завод снижает выпуск, загрузка мощностей низкая")
    i = ch(m["inv"], mp.get("inv"))
    if i is not None and r is not None and i > 0.15 and r < 0:
        flags.append(f"запасы выросли на {pct(i)} при падении выручки — затоваривание или задержки отгрузок")
    if m["ebit"] is not None and m["ebit"] < 0:
        flags.append("убыток от продаж — риск экономии на закупках комплектующих (колёса, литьё)")
    return flags


# ---------- отрасль ----------
PEER_KEYS = [("cur_liq", True), ("nwc_ta", True), ("eq_td", True), ("debt_ebit", False), ("int_cov", True),
             ("cost_cycle", False), ("ros", True), ("roe", True), ("fcf_rev", True)]
PEER_NAMES = {"cur_liq": "Текущая ликвидность", "nwc_ta": "Чистый оборотный капитал к активам",
              "eq_td": "Собственный капитал к заёмному", "debt_ebit": "Долг / прибыль от продаж",
              "int_cov": "Покрытие процентов", "cost_cycle": "Деньги в запасах и долгах покупателей",
              "ros": "Прибыльность продаж", "roe": "Рентабельность собственного капитала",
              "fcf_rev": "Свободный денежный поток к выручке"}


def peer_list(group):
    """Заводы — список из раздела «Отрасль для сравнения» в ZAVODY.md; операторы — watchlist.csv (тип «оператор»)."""
    if group == "zavod":
        out, on = [], False
        for line in (HERE / "ZAVODY.md").read_text(encoding="utf-8").splitlines():
            if line.startswith("**Отрасль для сравнения"):
                on = True
            elif on and line.startswith("- "):
                inn = re.search(r"\b\d{10}\b", line)
                name = line[2:].split(" — ")[0].strip()
                q = re.search(r"«([^»]+)»", line)  # что искать, если ИНН ещё нет
                out.append((inn.group(0) if inn else None, name, q.group(1) if q else name.split(" (")[0]))
            elif on and line.strip() and not line.startswith("- "):
                break
        return out
    path = HERE / "watchlist.csv"
    if not path.exists():
        sys.exit(f"Нет {path} — список операторов только на сервере")
    with path.open(encoding="utf-8-sig") as f:
        return [(r["инн"].strip(), r["компания"].strip(), "") for r in csv.DictReader(f, delimiter=";")
                if re.fullmatch(r"\d{10}", (r.get("инн") or "").strip()) and "оператор" in (r.get("тип") or "")]


def peers_cmd(a):
    path = HERE / f"peers_{a.group}.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    db = {}  # только компании из текущего списка
    for inn, name, q in peer_list(a.group):
        if not inn:
            print(f"  {name}: нет ИНН — найди: python3 ~/aviation-monitor/checko.py find \"{q}\" "
                  "и впиши ИНН в ZAVODY.md («Отрасль для сравнения»)")
            continue
        if inn in old and not a.force:
            db[inn] = {**old[inn], "name": name}
            print(f"  {name}: уже есть ({old[inn]['year']})")
            continue
        ys = checko.years(checko.cached("finances", inn))
        if not ys:
            print(f"  {name}: отчётность не получена (лимит Checko?) — запусти позже")
            continue
        Y = years_data(ys)
        y = sorted(Y)[-1]
        r = ratios(Y, y)
        db[inn] = {"name": name, "year": y, **{k: r[k] for k, _ in PEER_KEYS}}
        print(f"  {name}: {y} " + ("⚠ свежей отчётности нет — в таблице для справки, в середину отрасли не входит"
                                   if stale(y) else "✓"))
    path.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Файл: {path} — компаний: {len(db)}")


def peers_block(inn, r, group, year):
    """Таблица «компания и каждый завод отрасли»; середина — только по свежей отчётности (если таких 2 и больше)."""
    path = HERE / f"peers_{group}.json"
    if not path.exists():
        return ["Сравнение с отраслью не построено — нет файла отрасли (`python3 zfactory.py peers "
                f"{group}`)."]
    allp = {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if k != inn}
    if not allp:
        return ["Сравнение с отраслью не построено — в файле отрасли нет других компаний."]
    peers = sorted(allp.values(), key=lambda v: (stale(v["year"]), v["name"]))
    fresh = [v for v in peers if not stale(v["year"])]
    use_med = len(fresh) >= 2
    head = ["Показатель", f"Компания ({year})"] + [f"{v['name']} ({v['year']}{' ⚠' if stale(v['year']) else ''})" for v in peers]
    head += ["Середина (свежие)", "Оценка"] if use_med else []
    L = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for k, hb in PEER_KEYS:
        f, mine = FMT[k], r.get(k)
        row = [PEER_NAMES[k], f(mine)] + [f(v.get(k)) for v in peers]
        if use_med:
            vals = [v[k] for v in fresh if v.get(k) is not None]
            med = statistics.median(vals) if len(vals) >= 2 else None
            mark = ("нет данных" if mine is None or med is None else "✓ лучше" if (mine > med) == hb and mine != med
                    else "⚠ хуже" if mine != med else "на уровне")
            row += [f(med), mark]
        L.append("| " + " | ".join(row) + " |")
    old = [v["name"] for v in peers if stale(v["year"])]
    who = "заводы-производители вагонов" if group == "zavod" else "операторы вагонов"
    L += ["", f"<small>Отрасль: {who}. Середина — медиана по заводам со свежей отчётностью"
          + ("" if use_med else " — не считается: свежая отчётность меньше чем у двух") + "."
          + (f" ⚠ {', '.join(old)} — в открытом реестре нет свежей отчётности, цифры старые, только для справки." if old else "")
          + " Источник — РСБУ через Checko.</small>"]
    return L


# ---------- справка ----------
def run(a):
    data = checko.years(checko.cached("finances", a.id))
    if not data:
        sys.exit("Отчётность не получена (лимит Checko или формат) — попробуй 1С (onec.py) или позже.")
    Y = years_data(data)
    yrs = sorted(Y)[-4:]
    R = {y: ratios(Y, y) for y in yrs}
    y, yp = yrs[-1], (yrs[-2] if len(yrs) > 1 else None)
    m, mp, r = Y[y], (Y[yp] if yp else {}), R[y]
    m = {**m, "debt": r["debt"]}
    cover, months = runway(m)
    stops, prob, causes = diagnose(Y, R, yrs)
    is_old = stale(y)
    if is_old:
        stops.insert(0, f"последняя отчётность в открытом реестре — за {y} г., свежее нет (компания не раскрыла "
                        "отчётность; у компаний под санкциями это бывает). Все цифры ниже — по состоянию на конец "
                        f"{y} г. и для решения не годятся: запросить у {'завода' if a.zavod else 'компании'} "
                        "бухгалтерскую отчётность за последний год и последний квартал")
    cls = grade(prob, stops, cover)
    who = "завода" if a.zavod else "компании"
    cases = checko.cases_summary(checko.cached("legal-cases", a.id))

    head = (f"свежей отчётности нет — последняя за {y} год" if is_old else
            f"чистый оборотный капитал {t(r['nwc'])}, долг — {FMT['debt_ebit'](r['debt_ebit'])} прибыли от продаж"
            if stops else
            f"поток покрывает платежи по долгу в {x(cover, 1)} раза" if cover is not None else
            "поток не рассчитан — нет отчёта о движении денег")
    L = [f"# {a.name} — финансовое состояние" + (" и риск аванса" if a.zavod else ""), "",
         f"{{{{класс:{cls}}}}} **{GRADE[cls]} риск:** {head}"
         + (f", денег хватит на {months:.0f} мес. без новых поступлений." if months and months <= 24 and not stops else "."), "",
         f"<small>ИНН/ОГРН {a.id} · последняя доступная отчётность: РСБУ юрлица на 31.12.{y}"
         + (f" (к {yp} г.)" if yp else "") + (" ⚠ устарела" if is_old else "") + " · Подготовлено по открытым источникам</small>", ""]
    if stops:
        L += [f"> **⛔ Решение — только после пояснения {who}.** " + "; ".join(s[0].upper() + s[1:] for s in stops) + ". Запросить у " + who + ": "
              + ("как будет выполнен заказ — портфель заказов, график выпуска, источники денег на производство, "
                 "план погашения долгов" if a.zavod else "как будет обслуживаться долг — график погашения, "
                 "источники денег, планы по капиталу") + " (оценка эксперта).", ""]
    L += ["## Главное за минуту", "", "```cards",
          f"Выручка, {y} | {t(m['rev'])} | {'⚠ ▼' if (ch(m['rev'], mp.get('rev')) or 0) < 0 else '✓ ▲'} {pct(ch(m['rev'], mp.get('rev')))}"
          + (f" к {yp}" if yp else ""),
          f"Свободный денежный поток | {t(r['fcf'])} | {'⚠ отрицательный' if (r['fcf'] or 0) < 0 else '✓ положительный' if r['fcf'] is not None else 'нужен прошлый год'}",
          f"Чистый оборотный капитал | {t(r['nwc'])} | {'⚠ меньше нуля — стоп' if (r['nwc'] or 0) < 0 else '✓ больше нуля'}",
          f"Долг / прибыль от продаж | {FMT['debt_ebit'](r['debt_ebit'])} | "
          + ("⚠ прибыли от продаж нет" if r["no_ebit"] else "⚠ больше 7 — стоп" if (r["debt_ebit"] or 0) > TH["stop_debt_ebit"]
             else "⚠ больше 3" if (r["debt_ebit"] or 0) > TH["debt_ebit_ok"] else "✓ до 3" if r["debt_ebit"] is not None else "долга нет"),
          f"Покрытие процентов | {FMT['int_cov'](r['int_cov'])} | {'⚠ меньше 1' if r['int_cov'] is not None and r['int_cov'] < 1 else '✓'}",
          f"Капитал | {t(m['eq'])} | {'⚠ отрицательный' if (m['eq'] or 0) < 0 else '✓'}", "```", ""]

    ty = yrs[-3:]  # в таблице — 3 последних года, чтобы помещалась на страницу
    L += ["## Показатели по методике", "", "| Показатель | " + " | ".join(ty) + " | Формула (строки РСБУ) |",
          "|---|" + "---|" * len(ty) + "---|"]
    for name, k in ROWS:
        if k is None:
            L.append(f"| **{name}** |" + " |" * (len(ty) + 1))
        else:
            L.append(f"| {name} | " + " | ".join(FMT[k](R[q][k]) for q in ty) + " | "
                     + ("см. «Свободный денежный поток»" if k == "fcf" else F[k]) + " |")
    L += ["", "<small>Ликвидность — оборотные активы (текущая), без запасов (срочная), только деньги (абсолютная) к долгам "
          "на год. Дни — сколько дней выручки лежит в запасах и долгах покупателей и сколько дней завод живёт за счёт "
          "поставщиков и авансов. Средние — (начало года + конец года) / 2, год — 360 дней. «Долг / прибыль от продаж» — вместо "
          "«долг / EBITDA»: износа нет в открытых формах, поэтому оценка строже. Ориентиры: текущая ликвидность 1–2; "
          "собственный капитал к заёмному — от 1; долг / прибыль — надёжно до 2–3, больше 7 — прибыли хватает только "
          "на проценты; покрытие процентов — больше 1. Остальное оценивается по изменению и по отрасли.</small>", ""]

    L += ["## Свободный денежный поток", "", "| Год | Чистая прибыль | Вложения во внеоборотные активы | Прирост оборотного "
          "капитала | Свободный поток (по балансу) | Сверка: по отчёту о движении денег |", "|---|---|---|---|---|---|"]
    for q in yrs:
        L.append(f"| {q} | {t(Y[q]['net'])} | {t(R[q]['capex_b'])} | {t(R[q]['dwc'])} | **{t(R[q]['fcf'])}** | {t(R[q]['fcf_cf'])} |")
    L += ["", f"**Формула (строки баланса):** свободный поток = {F['fcf']}.", "",
          f"То же словами: {FCF_WORDS}. Износ в расчёт не входит — он есть и в прибыли, и во вложениях, и сокращается. "
          f"Сверка — {F['fcf_cf']} (поток от операций минус покупка внеоборотных активов); заметное расхождение — "
          "переоценки, продажа активов или неденежные статьи.", ""]
    L += ["## Сравнение с отраслью", ""] + peers_block(a.id, r, "zavod" if a.zavod else "oper", y) + [""]

    L += ["## Выводы", "",
          "**1. Состояние.** " + "; ".join(f"{n} — {v[0]}" for n, v in prob.items()) + ".", ""]
    good = []
    if (m["net"] or 0) > 0:
        good.append(f"прибыль {t(m['net'])}")
    if (r["fcf"] or 0) > 0:
        good.append(f"свободный денежный поток положительный ({t(r['fcf'])})")
    if r["nwc"] is not None and r["nwc"] > 0:
        good.append("оборотные активы покрывают долги года с запасом")
    if r["debt_ebit"] is not None and r["debt_ebit"] <= TH["debt_ebit_ok"]:
        good.append(f"долг по силам — {FMT['debt_ebit'](r['debt_ebit'])} прибыли")
    weak = [s for _, v in prob.items() for s in v[1]]
    L += ["**2. Сильные и слабые стороны.** Сильные: " + ("; ".join(good) if good else "по отчётности не видно") + ". "
          "Слабые: " + ("; ".join(weak) if weak else "по отчётности не видно") + ".", ""]
    L += ["**3. Причины изменений:**", ""] + ([f"- ⚠ Риск: {s}" for s in causes] or ["- явных причин ухудшения в отчётности нет"])
    L += ["", "**4. Что улучшит положение и что запросить** (оценка эксперта): рост прибыли и доли собственного капитала; "
          "вложения — в пределах прибыли и длинных кредитов; меньше денег в запасах и долгах покупателей. Запросить у "
          f"{who}: расшифровку долгов покупателей (безнадёжные), неликвидных запасов и незавершённой стройки, "
          "начисленные пени и штрафы, деление затрат на постоянные и переменные, график погашения кредитов.", ""]

    L += ["## Сколько выдержит при росте нагрузки", "", "| Сценарий | Покрытие платежей потоком | Денег хватит |", "|---|---|---|"]
    for name, rk, dk, rp_ in TH["stress"]:
        c_, mo = runway(m, rk, dk, rp_)
        cs = "нет данных" if c_ is None else "поток отрицательный" if c_ < 0 else x(c_, 1)
        ms = ("поток покрывает платежи" if c_ is not None and mo is None else "больше 2 лет" if mo and mo > 24
              else f"{mo:.0f} мес." if mo else "нет данных")
        L.append(f"| {name} | {cs} | {ms} |")
    L += ["", "<small>Покрытие = (4100 + 4123) / (4321 + 4123) — поток от операций до процентов к возврату кредитов "
          "и процентам. Меньше 1 — платежи идут из денег на счетах или новых займов. «Денег хватит» = 1250 / месячный "
          "недостаток потока.</small>", ""]

    if a.zavod:
        rows, share, final, flags = advance_block(m, mp, cls, a.deal)
        L += ["## Сколько аванса можно перечислить заводу", ""] + rows + [""]
        if stops:
            L += ["> **Аванс не перечислять, пока завод не пояснит, как выполнит заказ** (см. стоп-условия выше). После "
                  "пояснения — только под банковскую гарантию возврата аванса, аккредитив или по готовности вагонов "
                  "(оценка эксперта).", ""]
        elif not final:
            L += ["> **Аванс без банковской гарантии не перечислять:** свободных денег у завода нет или класс риска высокий. "
                  "Оплата — только под банковскую гарантию возврата аванса, аккредитив или по готовности вагонов "
                  "(оценка эксперта).", ""]
        else:
            L += [f"> **Допустимый аванс без банковской гарантии: {t(final)}**"
                  + (f" — {final / a.deal * 100:.0f}% от сделки {t(a.deal)}" if a.deal else "")
                  + f". По классу {cls} — не больше {share * 100:.0f}% сделки. Сверх этого — только под банковскую "
                  "гарантию возврата аванса, аккредитив или поэтапную оплату по готовности вагонов (оценка эксперта).", ""]
        L += ["**Не уйдёт ли аванс на долги, а не в производство:**", ""]
        L += [f"- ⚠ Риск (высокий): {f}" for f in flags] or ["- ✓ явных признаков в отчётности нет"]
        dl = delay_block(m, mp)
        if cases and cases.get("n"):
            dl.append(f"судебных дел: {cases['n']}, сумма требований {checko.money(cases['sum'])} — проверить споры "
                      "с покупателями о сроках поставки")
        L += ["", "**Риск задержки поставки:**", ""] + ([f"- ⚠ Риск: {f}" for f in dl] or ["- ✓ явных признаков в отчётности нет"])
        L += ["", "<small>Проверить отдельно (в отчётности не видно): портфель заказов против выпуска, простои и неполная "
              "неделя, поставщики колёсных пар и литья, санкции — раздел новостей.</small>", ""]

    L += ["## Отчётность", "", "| Показатель | Строка | " + " | ".join(yrs) + " |", "|---|---|" + "---|" * len(yrs)]
    for n_, k in (("Выручка", "rev"), ("Прибыль от продаж", "ebit"), ("Проценты к уплате", "int"), ("Чистая прибыль", "net"),
                  ("Внеоборотные активы", "nca"), ("Оборотные активы", "ca"), ("Запасы", "inv"), ("Дебиторка", "ar"),
                  ("Деньги", "cash"), ("Капитал", "eq"), ("Нераспределённая прибыль (убыток)", "re"),
                  ("Долгосрочные обязательства", "ltl"), ("в т. ч. кредиты", "debt_l"), ("Краткосрочные обязательства", "stl"),
                  ("в т. ч. кредиты", "debt_s"), ("Кредиторка (в т. ч. авансы полученные)", "ap"), ("Активы всего", "ta"),
                  ("Поток от операций", "cfo"), ("Покупка внеоборотных активов", "capex"), ("Возврат кредитов", "repay"),
                  ("Дивиденды", "div")):
        L.append(f"| {n_} | {K[k]} | " + " | ".join(t(Y[q][k]) for q in yrs) + " |")
    L += ["", "> **Как читать:** оценка по открытой годовой отчётности юрлица (тыс. ₽ → млн/млрд ₽); квартальных данных "
          "и договоров нет. Нормативов в методике нет — показатели сравниваются по годам и с отраслью."]
    md = "\n".join(L) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Файл: {a.out}")
    else:
        print(md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("id")
    pr.add_argument("--name", default="Компания")
    pr.add_argument("--deal", type=float, help="сумма сделки, тыс. ₽")
    pr.add_argument("--zavod", action="store_true")
    pr.add_argument("--guest", action="store_true")
    pr.add_argument("--out")
    pp = sub.add_parser("peers")
    pp.add_argument("group", choices=["zavod", "oper"])
    pp.add_argument("--force", action="store_true")
    a = ap.parse_args()
    run(a) if a.cmd == "run" else peers_cmd(a)
