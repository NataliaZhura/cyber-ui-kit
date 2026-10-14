#!/usr/bin/env python3
"""Стресс-тест финмодели: будущий поток, свободный денежный поток, покрытие платежей и точки «пробоя».

  ~/pw/bin/python cf.py шаблон model.csv                    пустой шаблон входных данных
  ~/pw/bin/python cf.py run model.csv [--min 1.2] [--var 0] [--xlsx out.xlsx]

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

--var: доля переменных расходов в выручке (0…1). По умолчанию 0 — консервативно: падение выручки целиком уменьшает
EBITDA. Если в модели видно, какие расходы падают вместе с выручкой (топливо, аэропорты), задай долю явно.
"""
import csv
import sys
from pathlib import Path

COLS = ["год", "выручка", "ebitda", "налог", "capex", "изм_оборотки", "проценты", "погашение", "лизинг",
        "прочие_обяз", "деньги_нач", "топливо", "валюта", "плав_долг"]
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


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "шаблон":
        cmd_template(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "run":
        cmd_run(sys.argv[2], *sys.argv[3:])
    else:
        print(__doc__)
