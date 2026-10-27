#!/usr/bin/env python3
"""Рабочая модель прогноза ставок аренды до 2030 г.: тип вагона × год × выбранные показатели × сценарий.

  python3 zmodel.py list                                          показатели и их надёжность
  python3 zmodel.py run --wagon gon --factors coal,park,stroy --scenario base [--year 2028] [--set gdp=2,off=40]
        [--guest] [--out saved/2026-10-17_прогноз.md]
  wagon: gon (полувагон обычный), inno (инновационный), kr158, kr138, all (все четыре)

Данные — ~/railway-monitor/forecast/model_data.json (только на сервере: история ставок — внутренние данные).
Модель: изменение ставки за год (в %) = константа + Σ сила_показателя × изменение_показателя; силы считаются
заново по истории для выбранного набора. Надёжность набора — проверка «на прошлом»: модель учится до года t
и прогнозирует год t; ошибка сравнивается с прогнозом «ставка не изменится».
Без внешних библиотек — работает на любом python3.
"""
import argparse
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "forecast" / "model_data.json"
YEARS = [2027, 2028, 2029, 2030]
NAMES = {"gon": "Полувагон обычный", "inno": "Полувагон инновационный", "kr158": "Крытый 158 м³", "kr138": "Крытый 138 м³"}
MAX_FACTORS = 3


def load():
    if not DATA.exists():
        sys.exit(f"Нет {DATA} — модель не загружена на сервер (prognoz.sh).")
    return json.loads(DATA.read_text(encoding="utf-8"))


def solve(a, b):
    """Решение a·x = b методом Гаусса (матрицы до 4×4)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("показатели повторяют друг друга — выбери другой набор")
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                k = m[r][c] / m[c][c]
                m[r] = [x - k * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def ols(rows):
    """rows: [(y, [x1..xk])] → [b0, b1..bk], R²."""
    k = len(rows[0][1]) + 1
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for y, xs in rows:
        v = [1.0] + xs
        for i in range(k):
            xty[i] += v[i] * y
            for j in range(k):
                xtx[i][j] += v[i] * v[j]
    b = solve(xtx, xty)
    ys = [y for y, _ in rows]
    mean = sum(ys) / len(ys)
    ss = sum((y - mean) ** 2 for y in ys) or 1e-9
    res = sum((y - b[0] - sum(bi * x for bi, x in zip(b[1:], xs))) ** 2 for y, xs in rows)
    return b, 1 - res / ss


def series(D, model, fid):
    """История показателя в том виде, в каком он входит в модель: {год: значение}."""
    return {int(y): v for y, v in D["history"][model]["x"][fid].items()}


def history_rows(D, model, fids):
    """{год: (изменение ставки, [показатели])} — только годы, где есть всё."""
    y = {int(k): v for k, v in D["history"][model]["y"].items()}
    xs = [series(D, model, f) for f in fids]
    return {t: (y[t], [x[t] for x in xs]) for t in sorted(y)
            if y[t] is not None and all(x.get(t) is not None for x in xs)}


def backtest(rows_by_year, start=2014):
    err, naive, hit = [], [], 0
    years = sorted(rows_by_year)
    for t in years:
        if t < start:
            continue
        train = [rows_by_year[s] for s in years if s < t]
        if len(train) < len(rows_by_year[t][1]) + 5:
            continue
        b, _ = ols(train)
        y, xs = rows_by_year[t]
        p = b[0] + sum(bi * x for bi, x in zip(b[1:], xs))
        err.append((y - p) ** 2)
        naive.append((y - sum(r[0] for r in train) / len(train)) ** 2)
        hit += (p > 0) == (y > 0)
    if len(err) < 4:
        return None
    ratio = math.sqrt(sum(err) / len(err)) / math.sqrt(sum(naive) / len(naive))
    return {"ratio": round(ratio, 2), "hit": round(hit / len(err), 2), "years": len(err), "k": len(rows_by_year[t][1]),
            "error": round(math.sqrt(sum(err) / len(err)))}


def wrong_signs(D, fids, b):
    """Показатели, которые в этом наборе тянут ставку не в ту сторону (пересекаются с соседями по набору)."""
    return [D["factors"][f]["name"] for f, bi in zip(fids, b[1:]) if D["factors"][f].get("sign", 0) * bi < 0]


def grade(bt, wrong=()):
    if wrong:
        return "низкая — " + ("связь обратная ожидаемой" if len(wrong) == 1 and bt and bt.get("k") == 1 else
                              "в этом наборе работает в обратную сторону: " + ", ".join(wrong))
    if not bt or bt["years"] < 6:
        return "низкая — мало лет для проверки"
    if bt["ratio"] < 0.7:
        return "высокая"
    if bt["ratio"] < 0.9:
        return "средняя"
    return "низкая — не лучше прогноза «ставка не изменится»"


def scenario_x(D, model, fid, scen, overrides, gon_path=None):
    """Будущие значения показателя по годам в том же виде, что история."""
    f = D["factors"][fid]
    if f["kind"] == "park":  # парк на сети: из закупок и списаний, изменение парка прошлого года, %
        sc = dict(D["scenarios"][scen]["park"])
        for k in ("buy", "off"):
            if k in overrides:
                sc[k] = sc[k][:1] + [overrides[k]] * (len(sc[k]) - 1)  # свои значения — с 2027 г. (2026 — факт)
        park, out = [D["start"]["park"]], {}
        for b, o in zip(sc["buy"], sc["off"]):
            park.append(park[-1] + b - o)
        for i, y in enumerate(YEARS):  # park[i+1] — конец года y-1 (2026 → индекс 1)
            out[y] = 100 * math.log(park[i + 1] / park[i])
        return out
    if f["kind"] == "balance":  # баланс парка: (уголь + погрузка) / 2 + оборот вагона − парк год назад
        c, l, t, p = (scenario_x(D, model, k, scen, overrides) for k in ("coal", "load", "turn", "park"))
        return {y: (c[y] + l[y]) / 2 + t[y] - p[y] for y in YEARS}
    if f["kind"] == "gon_lag":  # ставка полувагона год назад
        prev = {2026: D["start"]["gon"], **gon_path}
        out = {2027: 100 * math.log(D["start"]["gon"] / D["start"]["gon_2025"])}
        for y in YEARS[1:]:
            out[y] = 100 * math.log(prev[y - 1] / prev[y - 2])
        return out
    lag = f.get("lag", {}).get(model, 0)
    vals = list(D["scenarios"][scen][fid])  # значения 2025–2030 (2025 — факт)
    if fid in overrides:
        vals = vals[:2] + [overrides[fid]] * (len(vals) - 2)  # свои значения — с 2027 г.
    lvl = dict(zip(range(2025, 2031), vals))
    out = {}
    for y in YEARS:
        t = y - lag
        if f["kind"] == "level":
            out[y] = lvl[t]
        elif f["kind"] == "diff":
            out[y] = lvl[t] - lvl[t - 1]
        else:  # pct: в сценарии — изменение за год, %
            out[y] = 100 * math.log(1 + lvl[t] / 100)
    return out


def forecast_one(D, model, fids, scen, overrides, gon_path=None):
    rows = history_rows(D, model, fids)
    b, r2 = ols(list(rows.values()))
    bt = backtest(rows)
    xs = {f: scenario_x(D, model, f, scen, overrides, gon_path) for f in fids}
    start = D["start"]["gon" if model == "gon" else "kr158"]
    floor = D["floor"].get(model, 0)
    path, contrib, lvl = {2026: start}, {}, start
    for y in YEARS:
        parts = {f: b[i + 1] * xs[f][y] for i, f in enumerate(fids)}
        ch = b[0] + sum(parts.values())
        lvl = max(floor, lvl * math.exp(ch / 100))
        path[y], contrib[y] = round(lvl), {"Константа (общий тренд)": b[0], **{D["factors"][f].get("short", D["factors"][f]["name"]): v for f, v in parts.items()}}
    return {"path": path, "contrib": contrib, "b": dict(zip(["const"] + fids, b)), "r2": round(r2, 2), "n": len(rows), "bt": bt,
            "grade": grade(bt, wrong_signs(D, fids, b))}


def run(a):
    D = load()
    fids = [f.strip() for f in a.factors.split(",") if f.strip()]
    bad = [f for f in fids if f not in D["factors"]]
    if bad:
        sys.exit(f"Нет таких показателей: {', '.join(bad)}. Есть: {', '.join(D['factors'])}")
    ov = {}
    for kv in filter(None, (a.set or "").split(",")):
        k, _, v = kv.partition("=")
        ov[k.strip()] = float(v)
    wagons = ["gon", "inno", "kr158", "kr138"] if a.wagon == "all" else [a.wagon]
    res = {}
    order = list(D["factors"])
    pick = lambda m: sorted([f for f in fids if m in D["factors"][f]["models"]], key=order.index) or D["default"][m]
    for m, nm in (("gon", "полувагона"), ("kr", "крытого")):
        if len(pick(m)) > MAX_FACTORS:
            sys.exit(f"Для ставки {nm} выбери не больше {MAX_FACTORS} показателей: при большем числе модель "
                     "подгоняется под прошлое и хуже прогнозирует.")
    gon_f = pick("gon")
    g = forecast_one(D, "gon", gon_f, a.scenario, ov)
    if {"gon", "inno"} & set(wagons):
        res["gon"] = g
    if {"kr158", "kr138"} & set(wagons):
        kr_f = pick("kr")
        res["kr"] = forecast_one(D, "kr", kr_f, a.scenario, ov, gon_path=g["path"])
    md = report(D, a, wagons, res, ov)
    if a.guest:  # методика — только владельцу
        import zclosed
        md = zclosed.strip(md)
    out = Path(a.out) if a.out else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"Файл: {out}")
    else:
        print(md)


def paths(D, res, wagons):
    rows = {}
    if "gon" in res:
        p = res["gon"]["path"]
        if "gon" in wagons:
            rows["gon"] = p
        if "inno" in wagons:
            d = D["inno_delta"]
            def delta(y):  # рост рынка > +3% — «рост», падение < −3% — «падение», между ними — середина
                ch = p[y] / p[y - 1] - 1
                return d["up"] if ch > 0.03 else d["down"] if ch < -0.03 else (d["up"] + d["down"]) / 2
            rows["inno"] = {y: (D["start"]["inno"] if y == 2026 else round(p[y] + delta(y))) for y in p}
    if "kr" in res:
        p = res["kr"]["path"]
        if "kr158" in wagons:
            rows["kr158"] = p
        if "kr138" in wagons:
            rows["kr138"] = {y: round(v * D["kr138_ratio"]) for y, v in p.items()}
    return rows


def fmt(x):
    return f"{x:g}".replace(".", ",").replace("-", "−")


def n(v):
    return f"{round(v):,}".replace(",", " ")


def report(D, a, wagons, res, ov):
    yrs = [a.year] if a.year else [2026] + YEARS
    scen = D["scenarios"][a.scenario]["name"]
    rows = paths(D, res, wagons)
    used = sorted({f for r in res.values() for f in r["b"] if f != "const"})
    title = "Прогноз ставок аренды" + (f" на {a.year} год" if a.year else " на 2026–2030 годы")
    L = [f"# {title}", "", f"<small>Сценарий: {scen}{' (свои значения: ' + ', '.join(f'{k}={v:g}' for k, v in ov.items()) + ')' if ov else ''} · "
         f"показатели: {', '.join(D['factors'][f]['name'] for f in used)} · ₽ за вагон в сутки без НДС</small>", "",
         "## Главное", "", "```cards"]
    for w in wagons:
        p = rows[w]
        last = a.year or 2030
        ch = (p[last] / p[2026] - 1) * 100
        L.append(f"{NAMES[w]}, средняя за {last} г. | {n(p[last])} ₽ | {'✓ ▲' if ch >= 0 else '⚠ ▼'} {ch:+.0f}% к 2026")
    L += ["```", ""]
    weak = [("полувагона" if k == "gon" else "крытого вагона") for k, r in res.items() if r["grade"].startswith("низкая")]
    if weak:
        rec = ", ".join(D["factors"][f]["name"] for f in dict.fromkeys(D["default"]["gon"] + D["default"]["kr"]))
        L += [f"> ⚠ **Набор для ставки {' и '.join(weak)} ненадёжен** — на прошлых годах он прогнозировал не лучше, чем "
              f"«ставка не изменится», или показатель в нём работает не в ту сторону. Цифрам ниже не доверяй; "
              f"рекомендуемый набор: {rec}.", ""]
    L += ["## Прогноз по годам: средняя ставка за год (январь–декабрь)", "", "| Тип вагона | " + " | ".join(str(y) for y in [2026] + YEARS) + " |",
          "|---|" + "---|" * (len(YEARS) + 1)]
    for w in wagons:
        L.append(f"| {NAMES[w]} | " + " | ".join(n(rows[w][y]) for y in [2026] + YEARS) + " |")
    L += ["", "<small>Все цифры — средняя ставка за год (январь–декабрь). 2026 — оценка средней за год по фактическим "
          "данным за 9 месяцев (январь–сентябрь). Инновационный = обычный + "
          f"{D['inno_delta']['up']} ₽ при росте рынка и + {D['inno_delta']['down']} ₽ при падении; крытый 138 м³ = "
          f"{round(D['kr138_ratio'] * 100)}% от 158 м³. Нижняя граница ставки полувагона — {D['floor']['gon']} ₽.</small>", ""]
    if not a.year:
        L += ["```chart"] + [f"{NAMES[w]}, ₽/сут | " + " | ".join(f"{y}: {rows[w][y]}" for y in [2026] + YEARS) for w in wagons] + ["```", ""]
    L += ["## Что двигает прогноз", ""]
    for key, r in res.items():
        nm = "полувагона" if key == "gon" else "крытого вагона"
        L += [f"**Ставка {nm}** — вклад каждого показателя в изменение ставки за год, %:", "",
              "| Показатель | " + " | ".join(str(y) for y in YEARS) + " |", "|---|" + "---|" * len(YEARS)]
        for c in r["contrib"][YEARS[0]]:
            L.append(f"| {c} | " + " | ".join(f"{r['contrib'][y][c]:+.0f}" for y in YEARS) + " |")
        bt = r["bt"]
        L += ["", f"Надёжность набора: **{r['grade']}**" + (
            f" — проверка на {bt['years']} прошлых годах: ошибка {bt['error']}% против {round(bt['error'] / bt['ratio'])}% у прогноза "
            f"«ставка не изменится», направление угадано в {round(bt['hit'] * 100)}% лет." if bt else "") +
            f" Набор объясняет {round(r['r2'] * 100)}% колебаний ставки за {r['n']} лет.", ""]
    L += ["## Допущения сценария", "", "| Показатель | " + " | ".join(str(y) for y in [2026] + YEARS) + " |",
          "|---|" + "---|" * (len(YEARS) + 1)]
    sc = D["scenarios"][a.scenario]
    shown = []
    for f in used:
        shown += ["coal", "load", "turn", "park"] if D["factors"][f]["kind"] == "balance" else [f]
    for f in dict.fromkeys(shown):
        fd = D["factors"][f]
        if fd["kind"] == "park":
            for k, nm in (("buy", "Закупки полувагонов, тыс."), ("off", "Списания полувагонов, тыс.")):
                v = sc["park"][k]
                L.append(f"| {nm} | " + " | ".join(fmt(x) for x in v[:1] + [ov.get(k, x) for x in v[1:]]) + " |")
        elif fd["kind"] not in ("gon_lag", "balance"):
            v = sc[f][1:]
            L.append(f"| {fd['name']}, {fd['unit']} | " + " | ".join(fmt(x) for x in v[:1] + [ov.get(f, x) for x in v[1:]]) + " |")
    L += ["", "> **Как читать:** это расчёт по выбранным показателям, а не гарантия. Средняя ошибка модели за год — "
          "±25–35%; прогноз задаёт направление и порядок ставки. Ставку сильнее всего двигает баланс парка: "
          "сколько вагонов нужно под грузы против сколько их на сети."]
    if not a.guest:
        L += ["", "<small>Подготовлено по открытым источникам.</small>"]
    else:
        L += ["", "<small>Подготовлено по открытым источникам.</small>"]
    return "\n".join(L) + "\n"


def cmd_list():
    D = load()
    print("Показатели (код — название — для каких вагонов — надёжность в одиночку):")
    for k, f in D["factors"].items():
        note = "; ".join(f"{'полувагон' if m == 'gon' else 'крытый'}: {g}" for m, g in f.get("note", {}).items())
        print(f"  {k:9s} {f['name']} — {note}")
    print("\nРекомендуемые наборы:", json.dumps(D["default"], ensure_ascii=False))


PICK_W = {"1": "gon", "2": "inno", "3": "kr158", "4": "kr138", "5": "all"}
PICK_Y = {"1": None, "2": 2026, "3": 2027, "4": 2028, "5": 2029, "6": 2030}
PICK_S = {"1": "base", "2": "pess", "3": "base"}
PICK_F = ["balance", "stroy", "mortgage", "park", "coal", "load", "turnover", "gdp", "housing", "key", "price",
          "tariff", "turn", "gon_lag"]


def cmd_menu():
    """Меню выбора одним сообщением — бот присылает его дословно."""
    D = load()
    star = set(D["default"]["gon"] + D["default"]["kr"])
    fs = " · ".join(f"{i} {'★ ' if f in star else ''}{D['factors'][f].get('short', D['factors'][f]['name'])}"
                    for i, f in enumerate(PICK_F, 1))
    print("Прогноз ставок аренды до 2030 — выберите и ответьте одной строкой, например: 5 1 1 0\n\n"
          "① Тип вагона: 1 полувагон обычный · 2 инновационный · 3 крытый 158 м³ · 4 крытый 138 м³ · 5 все\n"
          "② Период: 1 весь 2026–2030 · 2 — 2026 · 3 — 2027 · 4 — 2028 · 5 — 2029 · 6 — 2030\n"
          "③ Сценарий: 1 базовый · 2 пессимистичный · 3 свой (после цифр напишите, что изменить, например «ВВП 2%, списания 40»)\n"
          f"④ Показатели — до 3 через запятую, 0 — рекомендуемые ★:\n{fs}\n\n"
          "Готовая презентация (PDF) — ответьте «П».")


def apply_pick(a):
    """--pick "5 1 2 1,2,3" → вагон, период, сценарий, показатели."""
    parts = a.pick.replace(";", " ").split()
    if len(parts) < 3:
        sys.exit("Ответ — 3–4 числа: тип, период, сценарий, показатели (например: 5 1 1 0).")
    w, y, sc = parts[0], parts[1], parts[2]
    if w not in PICK_W or y not in PICK_Y or sc not in PICK_S:
        sys.exit("Не поняла выбор: тип 1–5, период 1–6, сценарий 1–3.")
    a.wagon, a.year, a.scenario = PICK_W[w], PICK_Y[y], PICK_S[sc]
    f = "".join(parts[3:]) if len(parts) > 3 else "0"
    if f not in ("", "0"):
        try:
            a.factors = ",".join(PICK_F[int(x) - 1] for x in f.split(",") if x)
        except (ValueError, IndexError):
            sys.exit(f"Показатели — номера от 1 до {len(PICK_F)} через запятую.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["list", "run", "menu"])
    ap.add_argument("--pick", help="ответ на меню одной строкой: тип период сценарий показатели")
    ap.add_argument("--wagon", default="all", choices=["gon", "inno", "kr158", "kr138", "all"])
    ap.add_argument("--factors", default="")
    ap.add_argument("--scenario", default="base", choices=["base", "pess"])
    ap.add_argument("--year", type=int, choices=[2026] + YEARS)
    ap.add_argument("--set", default="")
    ap.add_argument("--guest", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "list":
        cmd_list()
    elif a.cmd == "menu":
        cmd_menu()
    else:
        if a.pick:
            apply_pick(a)
        run(a)
