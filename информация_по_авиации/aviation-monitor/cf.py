#!/usr/bin/env python3
"""Стресс-тест финмодели: будущий поток, свободный денежный поток, покрытие платежей и точки «пробоя».

  ~/pw/bin/python cf.py шаблон model.csv                    пустой шаблон входных данных
  ~/pw/bin/python cf.py run model.csv [--min 1.2] [--var 0] [--xlsx out.xlsx]
  ~/pw/bin/python cf.py eval model.csv --rate 18 [--years 5] [--from 2027] [--invest 10] [--t0] [--tv 2]
        [--rate-eq 22] [--min 1.2] [--var 0] [--shock "Название:rev=-10,cost=5,rate=3,int=10"]…
        [--scen "Название=файл.csv"]… [--xlsx out.xlsx]
     оценка на выбранном горизонте: свободный поток проекта и акционера, NPV, IRR, индекс доходности,
     рентабельность, простая и дисконтированная окупаемость + сценарии (см. «Оценка» ниже)

Входные данные (model.csv, «;», суммы в млрд ₽, по строке на год) Ави выписывает из модели компании:
  год;выручка;ebitda;налог;capex;изм_оборотки;проценты;погашение;лизинг;прочие_обяз;деньги_нач
  необязательно: топливо (расходы на топливо), валюта (платежи в валюте в рублях: лизинг, ремонт),
                 плав_долг (остаток долга с плавающей ставкой)
  деньги_нач — только в первой строке (остаток денег на начало первого года).

Формулы (как в навыке fin-assessment):
  CFADS (поток для обслуживания долга) = EBITDA − налог − CAPEX − прирост оборотного капитала
  Свободный поток акционерам             = CFADS − проценты − погашение − лизинг − прочие обязательные платежи
  DSCR      = CFADS / (проценты + погашение)
  DCR all-in = CFADS / (проценты + погашение + лизинг + прочие обязательные платежи)
  Деньги на конец = деньги на начало + свободный поток

Оценка (eval), всё — только по годам горизонта (--years лет начиная с --from; по умолчанию весь срок модели):
  Поток проекта (FCFF)     = EBITDA − налог − CAPEX − прирост оборотного капитала − инвестиции
  Поток акционеру (FCFE)   = поток проекта − проценты − погашение − лизинг − прочие обязательные + привлечение долга
  NPV = −вложения + Σ поток_t / (1 + ставка)^t, t = 1…N (конец года); --t0 — первый год горизонта не дисконтируется.
  IRR — ставка, при которой NPV = 0 (поток должен хотя бы раз сменить знак, иначе «не считается»).
  Индекс доходности = PV положительных потоков / (вложения + PV отрицательных потоков).
  Окупаемость — год, когда накопленный (дисконтированный) поток с учётом вложений становится ≥ 0, с долями года.
  --invest — разовые вложения до начала горизонта (покупка, проект), млрд ₽; инвестиции по годам — столбец «инвестиции».
  Для акционера вложения считаются его деньгами; часть в долг — столбец «привлечение» (приток в поток акционеру).
  --tv g — добавить стоимость за горизонтом по Гордону: поток последнего года × (1 + g%) / (ставка − g%); по умолчанию нет.
  --rate — ставка дисконтирования, % (спросить у пользователя; не угадывать); --rate-eq — для потока акционеру
  (нет — та же ставка, с пометкой).
  Сценарии: --shock — доходы (rev), расходы (cost = выручка − EBITDA), ставка по кредитам (rate, п. п. к остатку
  «долг», нет его — к «плав_долг»), процентные платежи (int), всё в %; --scen — потоки пересчитанной модели
  (assume.py scen). Налог в сценариях не пересчитывается (консервативно при ухудшении).

--var: доля переменных расходов в выручке (0…1). По умолчанию 0 — консервативно: падение выручки целиком уменьшает
EBITDA. Если в модели видно, какие расходы падают вместе с выручкой (топливо, аэропорты), задай долю явно.
"""
import csv
import sys
from pathlib import Path

COLS = ["год", "выручка", "ebitda", "налог", "capex", "изм_оборотки", "проценты", "погашение", "лизинг",
        "прочие_обяз", "деньги_нач", "топливо", "валюта", "плав_долг",
        "инвестиции", "привлечение", "долг", "чистая_прибыль"]
NEED = COLS[:10]


def num(s):
    s = (s or "").strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [{k: (num(v) if k != "год" else (v or "").strip()) for k, v in r.items()}
                for r in csv.DictReader(f, delimiter=";")]
    miss = sorted({c for r in rows for c in NEED if r.get(c) is None})
    if miss:
        sys.exit("Нет данных в обязательных столбцах: " + ", ".join(miss) + " — заполни (0, если статьи нет).")
    return rows


def calc(rows, rev=0.0, var=0.0, fuel=0.0, fx=0.0, rate=0.0):
    """Один сценарий. rev — падение выручки (0,1 = −10%), fuel — рост цены топлива, fx — рост рублёвой стоимости
    валютных платежей (ослабление рубля), rate — рост ставки в п. п. на плавающий долг."""
    out, cash = [], rows[0].get("деньги_нач") or 0.0
    for r in rows:
        ebitda = r["ebitda"] - r["выручка"] * rev * (1 - var) - (r.get("топливо") or 0) * fuel
        interest = r["проценты"] + (r.get("плав_долг") or 0) * rate / 100
        extra_fx = (r.get("валюта") or 0) * fx
        cfads = ebitda - r["налог"] - r["capex"] - r["изм_оборотки"]
        debt = interest + r["погашение"]
        allin = debt + r["лизинг"] + r["прочие_обяз"] + extra_fx
        fcfe = cfads - allin
        cash += fcfe
        out.append({"год": r["год"], "cfads": cfads, "fcfe": fcfe, "dscr": cfads / debt if debt > 0 else None,
                    "dcr": cfads / allin if allin > 0 else None, "cash": cash})
    return out


def worst(res):
    dcrs = [(x["dcr"], x["год"]) for x in res if x["dcr"] is not None]
    return min(dcrs) if dcrs else (None, None)


def breakpoint(rows, key, level, var, hi):
    """Минимальный шок, при котором минимальный DCR опускается до уровня level (бинарный поиск 0…hi)."""
    if (worst(calc(rows, var=var))[0] or 0) < level:
        return 0.0
    if (worst(calc(rows, var=var, **{key: hi}))[0] or 0) >= level:
        return None  # не пробивает даже при максимальном шоке
    lo, top = 0.0, hi
    for _ in range(40):
        mid = (lo + top) / 2
        if (worst(calc(rows, var=var, **{key: mid}))[0] or 0) < level:
            top = mid
        else:
            lo = mid
    return top


def f(v, pct=False, x=False):
    if v is None:
        return "н/д"
    if pct:
        return f"{v * 100:.0f}%"
    if x:
        return f"{v:.2f}".replace(".", ",")
    return f"{v:,.1f}".replace(",", " ").replace(".", ",")


def cmd_template(path):
    Path(path).write_text(";".join(COLS) + "\n" + ";".join(["2026"] + [""] * (len(COLS) - 1)) + "\n", encoding="utf-8")
    print(f"Шаблон: {path}")


def cmd_run(path, *opts):
    o = dict(zip(opts[::2], opts[1::2]))
    level, var, xlsx = float(o.get("--min", 1.2)), float(o.get("--var", 0)), o.get("--xlsx")
    rows = load(path)
    has_fuel = any(r.get("топливо") for r in rows)
    has_fx = any(r.get("валюта") for r in rows)
    has_rate = any(r.get("плав_долг") for r in rows)

    base = calc(rows, var=var)
    print("БАЗОВЫЙ СЦЕНАРИЙ (млрд ₽)")
    print(f"{'год':<6}{'CFADS':>9}{'своб.поток':>11}{'DSCR':>7}{'DCR':>7}{'деньги':>9}")
    for x in base:
        flag = " ⚠️" if x["dcr"] is not None and x["dcr"] < level else ""
        print(f"{x['год']:<6}{f(x['cfads']):>9}{f(x['fcfe']):>11}{f(x['dscr'], x=True):>7}{f(x['dcr'], x=True):>7}"
              f"{f(x['cash']):>9}{flag}")
    m, y = worst(base)
    neg = [x["год"] for x in base if x["cash"] < 0]
    print(f"Минимальный DCR {f(m, x=True)} в {y}; порог банка {f(level, x=True)}."
          + (f" Деньги уходят в минус: {', '.join(neg)}." if neg else ""))

    scen = [("Выручка −10%", {"rev": .10}), ("Выручка −20%", {"rev": .20})]
    if has_fuel:
        scen.append(("Топливо +15%", {"fuel": .15}))
    if has_fx:
        scen.append(("Рубль слабее на 20%", {"fx": .20}))
    if has_rate:
        scen.append(("Ставка +3 п. п.", {"rate": 3}))
    combo = {"rev": .10, **({"fuel": .15} if has_fuel else {}), **({"fx": .20} if has_fx else {}),
             **({"rate": 3} if has_rate else {})}
    scen.append(("Плохой год (всё вместе)", combo))
    print("\nСТРЕСС-СЦЕНАРИИ")
    print(f"{'сценарий':<26}{'мин.DCR':>8}{'год':>6}{'дефицит денег':>15}")
    table = []
    for name, kw in scen:
        res = calc(rows, var=var, **kw)
        mm, yy = worst(res)
        low = min(x["cash"] for x in res)
        table.append((name, mm, yy, low))
        print(f"{name:<26}{f(mm, x=True):>8}{str(yy):>6}{(f(-low) + ' в мин.') if low < 0 else '—':>15}")

    print("\nГДЕ МОДЕЛЬ ПРОБИВАЕТ (минимальный шок, при котором DCR падает ниже уровня)")
    checks = [("падение выручки", "rev", 1.0)]
    if has_fuel:
        checks.append(("рост цены топлива", "fuel", 3.0))
    if has_fx:
        checks.append(("ослабление рубля", "fx", 3.0))
    def say(b, unit):
        if b is None:
            return "не пробивает"
        if b == 0:
            return "уже в базовом сценарии"
        return f"при {f(b, pct=True)}" if unit == "%" else f"при +{f(b, x=True)} п. п."

    for label, key, hi in checks:
        b1, bl = breakpoint(rows, key, 1.0, var, hi), breakpoint(rows, key, level, var, hi)
        print(f"  {label}: ниже {f(level, x=True)} — {say(bl, '%')}; ниже 1,00 — {say(b1, '%')}")
    if has_rate:
        print(f"  рост ставки: ниже 1,00 — {say(breakpoint(rows, 'rate', 1.0, var, 50.0), 'пп')}")
    missing = [n for n, h in (("топливо", has_fuel), ("валюта", has_fx), ("плав_долг", has_rate)) if not h]
    if missing:
        print(f"Не посчитано (нет данных в модели): {', '.join(missing)} — стресс по ним н/д.")
    print(f"Допущение: доля переменных расходов {f(var, pct=True)} "
          f"({'консервативно — всё падение выручки уменьшает EBITDA' if var == 0 else 'задана по модели'}).")
    if xlsx:
        write_xlsx(rows, base, table, level, xlsx)


def write_xlsx(rows, base, table, level, out):
    """Лист «Расчёт» — с формулами Excel (видно, как посчитано); лист «Стресс» — итоги сценариев."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter as L
    wb = Workbook()
    ws = wb.active
    ws.title = "Расчёт"
    ws["A1"], ws["A1"].font = "Базовый сценарий, млрд ₽ (формулы — как в навыке fin-assessment)", Font(bold=True)
    labels = ["Год", "Выручка", "EBITDA", "Налог", "CAPEX", "Прирост оборотного капитала", "Проценты", "Погашение",
              "Лизинг", "Прочие обязательные", "CFADS", "Свободный поток", "DSCR", "DCR all-in", "Деньги на конец"]
    keys = ["год", "выручка", "ebitda", "налог", "capex", "изм_оборотки", "проценты", "погашение", "лизинг", "прочие_обяз"]
    for i, lab in enumerate(labels, 3):
        ws.cell(row=i, column=1, value=lab)
    start = rows[0].get("деньги_нач") or 0
    ws.cell(row=18, column=1, value="Деньги на начало первого года")
    ws.cell(row=18, column=2, value=start)
    for j, r in enumerate(rows, 2):
        c = L(j)
        for i, k in enumerate(keys, 3):
            ws.cell(row=i, column=j, value=r[k])
        ws[f"{c}13"] = f"={c}5-{c}6-{c}7-{c}8"
        ws[f"{c}14"] = f"={c}13-{c}9-{c}10-{c}11-{c}12"
        ws[f"{c}15"] = f'=IF(({c}9+{c}10)>0,{c}13/({c}9+{c}10),"н/д")'
        ws[f"{c}16"] = f'=IF(({c}9+{c}10+{c}11+{c}12)>0,{c}13/({c}9+{c}10+{c}11+{c}12),"н/д")'
        ws[f"{c}17"] = f"=B18+{c}14" if j == 2 else f"={L(j - 1)}17+{c}14"
    ws.column_dimensions["A"].width = 34
    st = wb.create_sheet("Стресс")
    st.append([f"Сценарий (порог банка {level})", "Мин. DCR", "Год", "Мин. остаток денег, млрд ₽"])
    for name, mm, yy, low in table:
        st.append([name, round(mm, 2) if mm is not None else "н/д", yy, round(low, 2)])
    st.column_dimensions["A"].width = 30
    wb.save(out)
    print(f"\nExcel: {out} (формулы пересчитаются при открытии в Excel)")


# ---------- оценка на горизонте: NPV, IRR, окупаемость, сценарии ----------

def g(r, k):
    return r.get(k) or 0.0


def flows(rows, rev=0.0, cost=0.0, rate=0.0, int_=0.0, var=0.0):
    """Потоки по годам в сценарии. rev, cost, int_ — доли (0,1 = +10%), rate — п. п. к ставке по кредитам."""
    out, cash = [], rows[0].get("деньги_нач") or 0.0
    for r in rows:
        opex = r["выручка"] - r["ebitda"]
        ebitda = r["выручка"] * (1 + rev) - opex * (1 + var * rev) * (1 + cost)
        debt_base = g(r, "долг") or g(r, "плав_долг")
        interest = r["проценты"] * (1 + int_) + debt_base * rate / 100
        cfads = ebitda - r["налог"] - r["capex"] - r["изм_оборотки"]
        fcff = cfads - g(r, "инвестиции")
        allin = interest + r["погашение"] + r["лизинг"] + r["прочие_обяз"]
        fcfe = fcff - allin + g(r, "привлечение")
        cash += fcfe
        debt = interest + r["погашение"]
        out.append({"год": r["год"], "выручка": r["выручка"] * (1 + rev), "ebitda": ebitda, "fcff": fcff,
                    "fcfe": fcfe, "dscr": cfads / debt if debt > 0 else None,
                    "dcr": cfads / allin if allin > 0 else None, "cash": cash,
                    "net": r.get("чистая_прибыль"), "инвестиции": g(r, "инвестиции")})
    return out


def npv(rate, cfs, invest=0.0, t0=False, tv=0.0):
    """−вложения + Σ cf / (1+r)^t; tv — стоимость за горизонтом, приходит вместе с последним годом."""
    sh = 0 if t0 else 1
    s = -invest + sum(cf / (1 + rate) ** (i + sh) for i, cf in enumerate(cfs))
    return s + (tv / (1 + rate) ** (len(cfs) - 1 + sh) if tv else 0.0)


def irr(cfs, invest=0.0, t0=False):
    seq = ([-invest] if invest else []) + list(cfs)
    if not (any(x < 0 for x in seq) and any(x > 0 for x in seq)):
        return None, "поток не меняет знак"
    f = lambda r: npv(r, cfs, invest, t0)
    grid = [-0.95 + i * 0.01 for i in range(0, 1096)]   # −95% … +1000%
    roots = []
    for a, b in zip(grid, grid[1:]):
        fa, fb = f(a), f(b)
        if fa == 0:
            roots.append(a)
        elif fa * fb < 0:
            lo, hi = a, b
            for _ in range(60):
                mid = (lo + hi) / 2
                if f(lo) * f(mid) <= 0:
                    hi = mid
                else:
                    lo = mid
            roots.append((lo + hi) / 2)
    if not roots:
        return None, "NPV не обнуляется в диапазоне −95…+1000%"
    signs = sum(1 for a, b in zip(seq, seq[1:]) if a * b < 0)
    return roots[0], ("несколько смен знака потока — IRR может быть не один" if signs > 1 or len(roots) > 1 else "")


def payback(cfs, invest=0.0, rate=None, t0=False):
    """Лет до окупаемости (с долями) от начала горизонта; None — не окупается в горизонте."""
    sh = 0 if t0 else 1
    cum = -invest
    if cum >= 0 and all(c >= 0 for c in cfs):
        return "нет вложений"
    for i, cf in enumerate(cfs):
        d = cf / (1 + rate) ** (i + sh) if rate is not None else cf
        if cum < 0 <= cum + d and d > 0:
            return i + sh - 1 + (-cum / d) if not t0 or i else -cum / d
        cum += d
    return None


def pi(rate, cfs, invest=0.0, t0=False):
    sh = 0 if t0 else 1
    pv = [cf / (1 + rate) ** (i + sh) for i, cf in enumerate(cfs)]
    neg = invest + sum(-x for x in pv if x < 0)
    return sum(x for x in pv if x > 0) / neg if neg > 0 else None


def shock(spec):
    """«Название:rev=-10,cost=5,rate=3,int=10» → (название, {…}) — проценты в доли, ставка — в п. п."""
    name, _, body = spec.partition(":")
    kw = {}
    for part in filter(None, (x.strip() for x in body.split(","))):
        k, _, v = part.partition("=")
        k, v = k.strip(), float(v.replace("%", "").replace(",", ".").strip())
        if k not in ("rev", "cost", "rate", "int"):
            sys.exit(f"Неизвестный параметр сценария «{k}»: rev, cost, rate, int")
        kw["int_" if k == "int" else k] = v if k == "rate" else v / 100
    return name.strip(), kw


def horizon(rows, years=None, start=None):
    """Индексы горизонта [i, j) и пометка. Потоки считаются по всей модели (деньги переходят из года в год),
    оценка — только по годам горизонта."""
    i = 0
    if start:
        idx = [n for n, r in enumerate(rows) if str(r["год"]).startswith(str(start))]
        if not idx:
            sys.exit(f"Нет года {start} в модели: {', '.join(str(r['год']) for r in rows)}")
        i = idx[0]
    j = min(len(rows), i + years) if years else len(rows)
    note = f"в модели только {j - i} лет — горизонт сокращён" if years and j - i < years else ""
    return i, j, note


def evaluate(res, rate, rate_eq, invest, t0, tvg):
    ff, fe = [x["fcff"] for x in res], [x["fcfe"] for x in res]
    tv = tv_e = 0.0
    if tvg is not None:
        if rate <= tvg:
            sys.exit("Для стоимости за горизонтом ставка должна быть больше темпа роста (--tv).")
        tv = ff[-1] * (1 + tvg) / (rate - tvg)
        tv_e = fe[-1] * (1 + tvg) / (rate_eq - tvg) if rate_eq > tvg else 0.0
    inv_all = invest + sum(x["инвестиции"] for x in res)
    rv, eb = sum(x["выручка"] for x in res), sum(x["ebitda"] for x in res)
    nets = [x["net"] for x in res]
    m, y = worst(res)
    return {"npv": npv(rate, ff, invest, t0, tv), "irr": irr(ff, invest, t0),
            "npv_e": npv(rate_eq, fe, invest, t0, tv_e), "irr_e": irr(fe, invest, t0),
            "pi": pi(rate, ff, invest, t0), "pb": payback(ff, invest, None, t0),
            "dpb": payback(ff, invest, rate, t0), "ebitda_m": eb / rv if rv else None,
            "net_m": sum(nets) / rv if rv and all(n is not None for n in nets) else None,
            "roi": (sum(ff) - invest) / inv_all if inv_all > 0 else None,
            "tv": tv, "min_dcr": m, "min_dcr_y": y, "low_cash": min(x["cash"] for x in res),
            "sum_ff": sum(ff), "sum_fe": sum(fe)}


def yrs(v):
    if v is None:
        return "не окупается в горизонте"
    if isinstance(v, str):
        return v
    return f"{v:.1f}".replace(".", ",") + " г."


def cmd_eval(path, *opts):
    o = {}
    multi = {"--shock": [], "--scen": []}
    i = 0
    while i < len(opts):
        k = opts[i]
        if k == "--t0":
            o[k] = True
            i += 1
            continue
        if i + 1 >= len(opts):
            sys.exit(f"Нет значения у {k}")
        if k in multi:
            multi[k].append(opts[i + 1])
        else:
            o[k] = opts[i + 1]
        i += 2
    if "--rate" not in o:
        sys.exit("Нужна ставка дисконтирования: --rate 18 (спроси пользователя; не угадывать).")
    rate = float(o["--rate"].replace(",", ".")) / 100
    rate_eq = float(o["--rate-eq"].replace(",", ".")) / 100 if "--rate-eq" in o else rate
    invest = float(o.get("--invest", "0").replace(",", "."))
    t0, tvg = bool(o.get("--t0")), (float(o["--tv"].replace(",", ".")) / 100 if "--tv" in o else None)
    level, var = float(o.get("--min", 1.2)), float(o.get("--var", 0))
    years = int(o["--years"]) if "--years" in o else None
    rows = load(path)
    hi, hj, note = horizon(rows, years, o.get("--from"))

    scen = [("Базовый", rows, {})]
    for s in multi["--shock"]:
        name, kw = shock(s)
        if kw.get("rate") and not any(g(r, "долг") or g(r, "плав_долг") for r in rows):
            kw.pop("rate")
            print(f"⚠ «{name}»: рост ставки не посчитан — в данных нет остатка долга (столбец «долг»)"
                  + (". Сценарий пропущен." if not kw else ", остальное посчитано."))
            if not kw:
                continue
            name += " (без ставки)"
        scen.append((name, rows, kw))
    for s in multi["--scen"]:
        name, _, f2 = s.partition("=")
        scen.append((name.strip(), load(f2), {}))

    hz = f"{rows[hi]['год']}–{rows[hj - 1]['год']} (лет: {hj - hi})"
    print(f"ОЦЕНКА НА ГОРИЗОНТЕ {hz}, млрд ₽. Ставка {f(rate, pct=True)}"
          + (f", для акционера {f(rate_eq, pct=True)}" if "--rate-eq" in o else " (для акционера — та же)")
          + (f", вложения {f(invest)}" if invest else "") + (". " + note if note else ""))
    results = []
    for name, rr, kw in scen:
        if len(rr) != len(rows):
            sys.exit(f"В сценарии «{name}» другое число лет, чем в базовой модели.")
        res = flows(rr, var=var, **kw)[hi:hj]
        results.append((name, res, evaluate(res, rate, rate_eq, invest, t0, tvg)))
    base_res, b = results[0][1], results[0][2]
    print(f"{'год':<6}{'выручка':>9}{'EBITDA':>8}{'поток проекта':>14}{'поток акц.':>11}{'DCR':>6}{'деньги':>8}")
    for x in base_res:
        print(f"{x['год']:<6}{f(x['выручка']):>9}{f(x['ebitda']):>8}{f(x['fcff']):>14}{f(x['fcfe']):>11}"
              f"{f(x['dcr'], x=True):>6}{f(x['cash']):>8}")
    pct = lambda v: f"{v * 100:.1f}%".replace(".", ",") if v is not None else "н/д"
    print(f"\nNPV проекта {f(b['npv'])}; IRR {pct(b['irr'][0]) if b['irr'][0] is not None else 'не считается'}"
          + (f" ({b['irr'][1]})" if b['irr'][1] else ""))
    print(f"NPV акционера {f(b['npv_e'])}; IRR {pct(b['irr_e'][0]) if b['irr_e'][0] is not None else 'не считается'}"
          + (f" ({b['irr_e'][1]})" if b['irr_e'][1] else ""))
    print(f"Индекс доходности {f(b['pi'], x=True)}; окупаемость простая {yrs(b['pb'])}, дисконтированная {yrs(b['dpb'])}")
    print(f"Рентабельность за горизонт: EBITDA {pct(b['ebitda_m'])}, чистая {pct(b['net_m'])}, "
          f"отдача на вложения {pct(b['roi'])}")
    if b["tv"]:
        print(f"Стоимость за горизонтом (рост {f(tvg, pct=True)}): {f(b['tv'])} — включена в NPV")
    if len(results) > 1:
        print("\nСЦЕНАРИИ")
        print(f"{'сценарий':<28}{'NPV':>7}{'Δ к баз.':>9}{'IRR':>8}{'окупаем.':>10}{'мин.DCR':>8}{'мин.деньги':>11}")
        for name, _, e in results:
            print(f"{name[:27]:<28}{f(e['npv']):>7}{f(e['npv'] - b['npv']):>9}"
                  f"{(pct(e['irr'][0]) if e['irr'][0] is not None else 'н/с'):>8}"
                  f"{yrs(e['pb']).replace('не окупается в горизонте', 'нет'):>10}{f(e['min_dcr'], x=True):>8}"
                  f"{f(e['low_cash']):>11}")
    print(f"\nДопущения: поток на конец года{' (первый год — без дисконтирования)' if t0 else ''}; "
          f"доля переменных расходов {f(var, pct=True)}; налог в сценариях не пересчитан; "
          + ("стоимость за горизонтом не включена." if tvg is None else "стоимость за горизонтом включена."))
    if o.get("--xlsx"):
        write_eval_xlsx(results, rate, rate_eq, invest, t0, tvg, level, o["--xlsx"])


def write_eval_xlsx(results, rate, rate_eq, invest, t0, tvg, level, out):
    """Лист «Оценка» — потоки и NPV/IRR формулами Excel; лист «Сценарии» — итоги."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter as L
    wb = Workbook()
    ws = wb.active
    ws.title = "Оценка"
    res = results[0][1]
    n = len(res)
    ws["A1"], ws["A1"].font = "Базовый сценарий, млрд ₽: поток проекта и акционера, NPV и IRR — формулами", Font(bold=True)
    ws["A2"], ws["B2"] = "Ставка дисконтирования", rate
    ws["A3"], ws["B3"] = "Ставка для акционера", rate_eq
    ws["B2"].number_format = ws["B3"].number_format = "0.0%"
    ws["A5"], ws["B5"] = "Год", "вложения"
    labels = [("Выручка", "выручка"), ("EBITDA", "ebitda"), ("Поток проекта (FCFF)", "fcff"),
              ("Поток акционеру (FCFE)", "fcfe"), ("DCR all-in", "dcr"), ("Деньги на конец", "cash")]
    for i, (lab, _) in enumerate(labels, 6):
        ws.cell(row=i, column=1, value=lab)
    ws["B8"], ws["B9"] = -invest, -invest
    for j, x in enumerate(res, 3):
        ws.cell(row=5, column=j, value=str(x["год"]))
        for i, (_, k) in enumerate(labels, 6):
            v = x[k]
            ws.cell(row=i, column=j, value=round(v, 6) if v is not None else "н/д")
    last = L(2 + n)
    first, rest = ("C", "D") if t0 else (None, "C")
    def npv_f(row, rc):
        body = f"NPV({rc},{rest}{row}:{last}{row})" if n > (1 if t0 else 0) else "0"
        return f"=B{row}+" + (f"{first}{row}+" if t0 else "") + body
    ws["A13"], ws["B13"] = "NPV проекта", npv_f(8, "$B$2")
    ws["A14"], ws["B14"] = "IRR проекта", f'=IFERROR(IRR(B8:{last}8),"не считается")'
    ws["A15"], ws["B15"] = "NPV акционера", npv_f(9, "$B$3")
    ws["A16"], ws["B16"] = "IRR акционера", f'=IFERROR(IRR(B9:{last}9),"не считается")'
    ws["B14"].number_format = ws["B16"].number_format = "0.0%"
    note = "Поток — на конец года" + ("; первый год горизонта не дисконтируется" if t0 else "")
    if tvg is not None:
        note += f"; стоимость за горизонтом (рост {tvg:.1%}) в формулы не входит — см. лист «Сценарии»"
    ws["A18"] = note
    ws.column_dimensions["A"].width = 30
    st = wb.create_sheet("Сценарии")
    st.append([f"Сценарий (порог DCR {level})", "NPV проекта", "IRR проекта", "NPV акционера", "IRR акционера",
               "Окупаемость, лет", "Дисконт. окупаемость, лет", "Индекс доходности", "Мин. DCR", "Год",
               "Мин. остаток денег"])
    r2 = lambda v: round(v, 4) if isinstance(v, float) else (v if v is not None else "н/д")
    for name, _, e in results:
        st.append([name, r2(e["npv"]), r2(e["irr"][0]) if e["irr"][0] is not None else "не считается",
                   r2(e["npv_e"]), r2(e["irr_e"][0]) if e["irr_e"][0] is not None else "не считается",
                   r2(e["pb"]) if e["pb"] is not None else "не окупается", r2(e["dpb"]) if e["dpb"] is not None
                   else "не окупается", r2(e["pi"]), r2(e["min_dcr"]), e["min_dcr_y"], r2(e["low_cash"])])
    st.column_dimensions["A"].width = 32
    wb.save(out)
    print(f"\nExcel: {out} (NPV и IRR — формулами, пересчитаются при открытии)")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "шаблон":
        cmd_template(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "run":
        cmd_run(sys.argv[2], *sys.argv[3:])
    elif len(sys.argv) >= 3 and sys.argv[1] == "eval":
        cmd_eval(sys.argv[2], *sys.argv[3:])
    else:
        print(__doc__)
