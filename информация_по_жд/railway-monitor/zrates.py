#!/usr/bin/env python3
"""Ставки и парк по месяцам, оповещения, журнал «прогноз — факт». Без нейросети (0 токенов).

  python3 zrates.py table [--json]        ставки аренды, оперирования, техрейса и рабочий парк: последний месяц,
                                          к прошлому месяцу и к году назад, история 13 месяцев (вкладка «Ставки» мини-приложения)
  python3 zrates.py alerts [--send]       оповещения: ставка за месяц ±5% и больше, рабочий парк −1% и больше, факт вне
                                          коридора прогноза, главные показатели по типам (WATCH — по разбору обвала
                                          2025 г.: уголь, зерно, стройгрузы, сальдо вагонов, доля в работе); --send — в Telegram,
                                          каждое оповещение один раз (forecast/alerts_sent.json)
  python3 zrates.py snap                  записать прогноз IV кв. по всем типам в журнал (forecast/fcst_journal.csv) —
                                          после каждого нового выпуска; повтор за тот же месяц данных заменяет запись
  python3 zrates.py planfact [--guest]    «Прогноз и факт» для отчёта: гостю — без ставок факта (данные партнёра) и
                                          без методики; PDF в чат — zpdf.py <ID> '{"kind":"planfact"}'
  python3 zrates.py score                 точность: прогноз месяцев против факта (журнал) + проверка метода IV кв. на
                                          истории ставок с 12.2024; поправочные коэффициенты событий — по факту

Факт — середина диапазона ставки партнёра (forecast/observations.csv). Все файлы — только на сервере.
"""
import csv
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import zobs  # noqa: E402

JOURNAL = BASE / "forecast" / "fcst_journal.csv"
SENT = BASE / "forecast" / "alerts_sent.json"
JCOLS = ["made", "wagon", "target", "pess", "base", "opt", "base_noev", "k"]
GROUPS = [("Аренда, ₽/сут без НДС", ["gon69_spot", "gon75_spot", "gon69_long", "gon75_long", "kr158", "kr138", "hop_grain",
                                    "fit80", "fit40", "fit60", "hop_min", "gon_fert"]),
          ("Оперирование, ₽/сут", ["op_coal", "op_met", "op_met_serv"]),
          ("Технический рейс, ₽/вагон", ["tr_kuz_vost", "tr_kuz_vost75", "tr_kuz_ul", "tr_kuz_tam", "tr_kz_ul", "tr_kz_tam"]),
          ("Рабочий парк, вагонов", ["park_gon_work", "park_kr_work", "park_hop_grain_work", "park_fit_work", "park_total_work"])]
# Тип прогноза → показатель факта (полувагоны — спот, как в модели zrate.py: сентябрь 2026 = середина спота).
FACT = {"gon": "gon69_spot", "inno": "gon75_spot", "kr158": "kr158", "kr138": "kr138", "hop_grain": "hop_grain",
        "fit80": "fit80", "fit40": "fit40", "fit60": "fit60"}
NAMES = {"gon": "Полувагон типовой", "inno": "Полувагон инновационный", "kr158": "Крытый 158 м³", "kr138": "Крытый 138 м³",
         "hop_grain": "Хоппер-зерновоз", "fit80": "Платформа 80'", "fit40": "Платформа 40'", "fit60": "Платформа 60'"}
KEV = {"hop_grain": 0.9, "fit80": 0.5, "fit40": 0.5, "fit60": 0.5, "kr158": 0.5, "kr138": 0.5, "gon": 0.5, "inno": 0.5}
PACE = {"pess": -1.0, "base": 0.4, "opt": 1.5}  # проверка метода IV кв. на истории — темпы крытых (как в ztypes.py)


def series():
    """{показатель: {месяц: середина}}; опрос важнее данных партнёра."""
    out = {}
    for r in zobs.read():
        if r["source"] not in ("partner", "survey", "rzd"):
            continue
        d = out.setdefault(r["item"], {})
        if r["source"] == "survey" or r["month"] not in d:
            d[r["month"]] = (float(r["low"]) + float(r["high"])) / 2
    return out


def pct(a, b):
    return round((a / b - 1) * 100, 1) if a and b else None


def table():
    S = series()
    groups = []
    for title, items in GROUPS:
        rows = []
        for it in items:
            d = S.get(it)
            if not d:
                continue
            ms = sorted(d)
            last = ms[-1]
            prev, year = zobs.shift(last, -1), zobs.shift(last, -12)
            rows.append({"item": it, "name": zobs.ITEMS[it][1], "month": last, "value": round(d[last]),
                         "mm": pct(d[last], d.get(prev)), "yy": pct(d[last], d.get(year)),
                         "hist": [[m, round(d[m])] for m in ms[-13:]]})
        if rows:
            groups.append({"title": title, "rows": rows})
    as_of = max((r["month"] for g in groups for r in g["rows"]), default="")
    return {"as_of": as_of, "groups": groups, "alerts": alerts()}


def journal():
    if not JOURNAL.exists():
        return []
    with JOURNAL.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


# Главные показатели по типам (разбор обвала 2025 г., zretro.py): (тип, ряд, как считать, знак, порог, текст {v}).
# mm/yy — % к месяцу/году, pp — изменение доли за месяц в п.п., lvl — значение месяца.
WATCH = [
    ("Полувагоны", "load_coal", "yy", "<=", -3, "погрузка угля {v}% к году — спрос слабеет (перед обвалом 2025 г. было до −7%)"),
    ("Полувагоны", "load_coal", "yy", ">=", 5, "погрузка угля {v}% к году — поддержка ставки (весной 2026 г. +5…+11%)"),
    ("Полувагоны", "op_coal", "mm", "<=", -5, "ставка оперирования на угле {v}% за месяц — в 2025 г. падала вместе с арендой"),
    ("Полувагоны", "net_gon", "lvl", ">=", 0, "новых полувагонов больше, чем выбывших ({v}) — парк снова растёт"),
    ("Полувагоны", "share_gon", "pp", "<=", -1, "доля полувагонов в работе {v} п.п. за месяц — больше в отстое или ремонте"),
    ("Зерновозы", "load_grain", "yy", "<=", -15, "погрузка зерна {v}% к году — как перед обвалом 2025 г. (−18…−27%)"),
    ("Зерновозы", "flow_hop_grain_new", "lvl", ">=", 500,
     "новых зерновозов {v} за месяц — приток, как перед обвалом (около 1 000 в месяц в конце 2024 г.)"),
    ("Платформы", "gon69_spot", "mm", "<=", -5,
     "ставка полувагона {v}% за месяц — контейнеры уходят в полувагоны (в падение 2025 г. до −14% в месяц)"),
    ("Платформы", "flow_fit_new", "lvl", ">=", 300, "новых платформ {v} за месяц — предложение растёт"),
    ("Крытые", "load_build", "yy", "<=", -10, "погрузка стройгрузов {v}% к году — в 2025 г. −15%, не восстановилась"),
    ("Крытые", "hop_grain", "mm", "<=", -10, "ставка зерновоза {v}% за месяц — крытые теряют спрос на зерно в мешках"),
]


def watch():
    """Сработавшие главные показатели по последнему месяцу каждого ряда."""
    try:
        import zretro
        S = zretro.data()  # с производными рядами: доля в работе, сальдо вагонов
    except Exception:  # noqa: BLE001
        S = series()
    out = []
    for typ, key, how, op, thr, text in WATCH:
        d = S.get(key, {})
        if len(d) < 2:
            continue
        m = max(d)
        if how == "lvl":
            v = d[m]
        elif how == "pp":
            p = d.get(zobs.shift(m, -1))
            v = d[m] - p if p is not None else None
        else:
            p = d.get(zobs.shift(m, -1 if how == "mm" else -12))
            v = (d[m] / p - 1) * 100 if p else None
        if v is None or not (v <= thr if op == "<=" else v >= thr):
            continue
        vs = (f"{v:+.1f}" if how != "lvl" else f"{v:,.0f}").replace(",", " ").replace(".", ",").replace("-", "−")
        out.append({"key": f"{m}:{key}:{op}", "text": f"{typ}: {text.format(v=vs)} ({m})"})
    return out


def alerts():
    S, out = series(), watch()
    for _, items in GROUPS[:1]:
        for it in items:
            d = S.get(it, {})
            if len(d) >= 2:
                last = max(d)
                ch = pct(d[last], d.get(zobs.shift(last, -1)))
                if ch is not None and abs(ch) >= 5:
                    out.append({"key": f"{last}:{it}:mm", "text": f"{zobs.ITEMS[it][1]}: {ch:+.1f}".replace(".", ",").replace("-", "−") + f"% за месяц ({last}, {round(d[last])} ₽)"})
    for it in GROUPS[3][1]:
        d = S.get(it, {})
        if len(d) >= 2:
            last = max(d)
            ch = pct(d[last], d.get(zobs.shift(last, -1)))
            if ch is not None and ch <= -1:
                out.append({"key": f"{last}:{it}:park", "text": f"{zobs.ITEMS[it][1].replace(': рабочие', '')}: рабочий парк "
                                                             f"{ch:+.1f}".replace(".", ",").replace("-", "−") + f"% за месяц ({last}) — вагоны уходят в отстой"})
    for r in journal():  # факт вне коридора прогноза
        f = S.get(FACT.get(r["wagon"], ""), {}).get(r["target"])
        if f is None:
            continue
        lo, hi = sorted([float(r["pess"]), float(r["opt"])])
        if not lo * 0.98 <= f <= hi * 1.02:
            side = "выше оптимистичного" if f > hi else "ниже пессимистичного"
            out.append({"key": f"{r['target']}:{r['wagon']}:corr", "text": f"{NAMES[r['wagon']]}: факт {r['target']} — "
                        f"{round(f)} ₽, {side} прогноза ({round(lo)}–{round(hi)} ₽, сделан по данным {r['made']})"})
    return out


def cmd_alerts(send):
    al = alerts()
    sent = set(json.loads(SENT.read_text(encoding="utf-8"))) if SENT.exists() else set()
    new = [a for a in al if a["key"] not in sent]
    for a in al:
        print(("🆕 " if a in new else "   ") + a["text"])
    if not al:
        print("Оповещений нет: ставки в пределах ±5% за месяц, рабочий парк без сокращения, факт в коридоре прогноза.")
    if send and new:
        import subprocess
        tmp = BASE / "saved" / ".alerts.txt"
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_text("<b>ЖДуша: оповещения рынка</b>\n" + "\n".join("• " + a["text"] for a in new)[:3800], encoding="utf-8")
        r = subprocess.run([sys.executable, str(BASE / "send.py"), "--text", str(tmp)], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        if r.returncode == 0:
            SENT.write_text(json.dumps(sorted(sent | {a["key"] for a in new}), ensure_ascii=False), encoding="utf-8")


def forecasts():
    """{тип: (месяц данных, {целевой месяц: {сценарий: ставка}}, {целевой месяц: база без событий})}."""
    out = {}
    try:
        import zrate as Z
        D = Z.load()
        for w in ("gon", "inno"):
            res = {s: Z.forecast(D, w, s) for s in Z.SCN}
            made = f"2026-{len(Z.months(D, w)):02d}"
            ev = res["base"].get("events")
            tg = [zobs.shift(made, k) for k in (1, 2, 3)]
            q = {m: {s: res[s]["q4"][i] for s in res} for i, m in enumerate(tg)}
            noev = {m: res["base"]["q4"][i] / (ev["q4"][i] if ev and ev["comp"] else 1) for i, m in enumerate(tg)}
            out[w] = (made, q, noev)
    except SystemExit:
        pass
    import ztypes as T
    for w in ("kr158", "kr138", "hop_grain", "fit80", "fit40", "fit60"):
        try:
            res = {s: T.forecast(w, s) for s in T.SCN}
        except SystemExit:
            continue
        r0 = res["base"]
        made = f"2026-{r0['last_m']:02d}"
        n = len(r0["q4"])
        tg = [zobs.shift(made, k) for k in range(1, n + 1)]
        ev = r0.get("events")
        q = {m: {s: res[s]["q4"][i] for s in res} for i, m in enumerate(tg)}
        noev = {m: r0["q4"][i] / (ev["q4"][i] if ev and ev["comp"] and i < 3 else 1) for i, m in enumerate(tg)}
        out[w] = (made, q, noev)
    return out


def cmd_snap():
    rows = journal()
    F = forecasts()
    keep = [r for r in rows if (r["wagon"], r["made"]) not in {(w, v[0]) for w, v in F.items()}]
    for w, (made, q, noev) in F.items():
        for m, sc in q.items():
            keep.append({"made": made, "wagon": w, "target": m, "pess": round(sc["pess"]), "base": round(sc["base"]),
                         "opt": round(sc["opt"]), "base_noev": round(noev[m]), "k": KEV[w]})
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, JCOLS, delimiter=";")
        wr.writeheader()
        wr.writerows(sorted(keep, key=lambda r: (r["made"], r["wagon"], r["target"])))
    print(f"Журнал: записан прогноз по {len(F)} типам ({', '.join(NAMES[w] for w in F)}); всего строк {len(keep)}.")


MON = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def planfact(guest=False):
    """«Прогноз и факт» по журналу: каждый прогноз, записанный после выпуска, против факта. Без нейросети.
    Владельцу — ставка факта и ошибка; гостю — только наш прогноз, отклонение факта в % и попадание в коридор
    сценариев: абсолютные ставки факта — данные партнёра, гостю их нельзя."""
    S = series()
    rows = []
    for r in journal():
        f = S.get(FACT.get(r["wagon"], ""), {}).get(r["target"])
        if f is None:
            continue
        b, lo, hi = float(r["base"]), *sorted([float(r["pess"]), float(r["opt"])])
        rows.append((r["wagon"], r["made"], r["target"], b, lo, hi, f))
    nm = lambda m: f"{MON[int(m[5:]) - 1]} {m[:4]}"  # noqa: E731
    rub = lambda v: f"{v:,.0f}".replace(",", " ")  # noqa: E731
    L = ["# Прогноз и факт: ставки аренды вагонов", "",
         "<small>₽ за вагон в сутки без НДС · прогноз ЖДуши, записанный сразу после выхода данных месяца, против факта"
         " · оценка рынка, не инвестиционная рекомендация</small>", ""]
    if not rows:
        return "\n".join(L + ["Пока нет месяцев, где известны и прогноз, и факт: первая сверка — после следующего выпуска данных.", ""])
    by = {}
    for x in rows:
        by.setdefault(x[0], []).append(x)
    L += ["## Коротко", "", "| Тип вагона | Сверено месяцев | Среднее отклонение факта от прогноза | Факт в коридоре сценариев |",
          "|---|---|---|---|"]
    for w, xs in by.items():
        err = sum(abs(f / b - 1) * 100 for *_, b, lo, hi, f in xs) / len(xs)
        inside = sum(lo * 0.98 <= f <= hi * 1.02 for *_, b, lo, hi, f in xs)
        L.append(f"| {NAMES[w]} | {len(xs)} | ±{err:.1f}% | {inside} из {len(xs)} |".replace(".", ","))
    for w, xs in by.items():
        L += ["", f"## {NAMES[w]}", ""]
        if guest:
            L += ["| Прогноз сделан | Месяц | Прогноз (базовый) | Коридор сценариев | Факт к прогнозу | В коридоре |", "|---|---|---|---|---|---|"]
            L += [f"| {nm(m)} | {nm(t)} | {rub(b)} | {rub(lo)}–{rub(hi)} | {(f / b - 1) * 100:+.1f}% | {'да' if lo * 0.98 <= f <= hi * 1.02 else 'нет'} |".replace(".", ",", 1)
                  for _, m, t, b, lo, hi, f in xs]
        else:
            L += ["| Прогноз сделан | Месяц | Прогноз (базовый) | Коридор | Факт | Отклонение | В коридоре |", "|---|---|---|---|---|---|---|"]
            L += [f"| {nm(m)} | {nm(t)} | {rub(b)} | {rub(lo)}–{rub(hi)} | {rub(f)} | {(f / b - 1) * 100:+.1f}% | {'да' if lo * 0.98 <= f <= hi * 1.02 else 'нет'} |".replace(".", ",", 1)
                  for _, m, t, b, lo, hi, f in xs]
    L += ["", "<small>Отклонение: плюс — факт выше прогноза, минус — ниже. Коридор — от пессимистичного до оптимистичного"
          " сценария (допуск ±2%).</small>", ""]
    return "\n".join(L)


def cmd_score():
    S = series()
    L = ["1. Журнал «прогноз — факт» (прогнозы, записанные после выпусков)", ""]
    by = {}
    for r in journal():
        f = S.get(FACT.get(r["wagon"], ""), {}).get(r["target"])
        if f is None:
            continue
        b, lo, hi = float(r["base"]), *sorted([float(r["pess"]), float(r["opt"])])
        e = by.setdefault(r["wagon"], {"n": 0, "err": 0, "in": 0, "ev": []})
        e["n"] += 1
        e["err"] += abs(b / f - 1) * 100
        e["in"] += lo * 0.98 <= f <= hi * 1.02
        nb = float(r["base_noev"])
        if abs(b - nb) > 1:  # месяц с поправкой на события: какая доля поправки подтвердилась фактом
            e["ev"].append(((f - nb) / (b - nb), float(r["k"])))
    if not by:
        L.append("Пока нет месяцев, где известен и прогноз, и факт: первая сверка — после следующего выпуска.")
    for w, e in by.items():
        line = (f"- {NAMES[w]}: месяцев {e['n']}, средняя ошибка базового ±{e['err'] / e['n']:.1f}%, факт в коридоре "
                f"сценариев — {e['in']} из {e['n']}")
        if e["ev"]:
            share = sum(x for x, _ in e["ev"]) / len(e["ev"])
            k = e["ev"][0][1]
            line += (f"; события: подтвердилось {share * 100:.0f}% поправки → коэффициент {k:g} × {share:.2f} = "
                     f"{k * share:.2f}" + (" (мало месяцев — пока не менять)" if len(e["ev"]) < 3 else " — можно уточнить"))
        L.append(line)
    L += ["", "2. Метод IV кв. на истории: ставка через 1–3 месяца = ставка месяца × (1 + темп)^k; темпы −1 / +0,4 / +1,5% в мес.", "",
          "| Тип | прогнозов | ошибка базового, ±% | в коридоре, % | лучший постоянный темп, % в мес. |", "|---|---|---|---|---|"]
    for w, it in FACT.items():
        d = S.get(it, {})
        ms = sorted(d)
        n = err = inside = 0
        trend = []
        for i, m in enumerate(ms):
            for k in (1, 2, 3):
                t = zobs.shift(m, k)
                if t not in d:
                    continue
                f = d[t]
                base = d[m] * (1 + PACE["base"] / 100) ** k
                lo, hi = d[m] * (1 + PACE["pess"] / 100) ** k, d[m] * (1 + PACE["opt"] / 100) ** k
                n += 1
                err += abs(base / f - 1) * 100
                inside += lo <= f <= hi
                trend.append(((f / d[m]) ** (1 / k) - 1) * 100)
        if n:
            trend.sort()
            L.append(f"| {NAMES[w]} | {n} | {err / n:.1f} | {inside * 100 / n:.0f} | {trend[len(trend) // 2]:+.1f} (медиана) |")
    L += ["", "Как читать: ошибка ±10–15% за 1–3 месяца — обычный разброс ставки; «в коридоре» ниже 50% — темпы сценариев "
          "узкие, коридор надо расширять. Коэффициенты событий (0,9 зерно, 0,5 остальные) меняются, когда месяцев с "
          "событиями будет 3 и больше."]
    print("\n".join(L))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "table":
        T_ = table()
        if "--json" in sys.argv:
            print(json.dumps(T_, ensure_ascii=False))
        else:
            print(f"Данные на {T_['as_of']}")
            for g in T_["groups"]:
                print(f"\n{g['title']}")
                for r in g["rows"]:
                    mm = f"{r['mm']:+.1f}%" if r["mm"] is not None else "—"
                    yy = f"{r['yy']:+.1f}%" if r["yy"] is not None else "—"
                    v = f"{r['value']:,}".replace(",", " ")
                    print(f"  {r['name'][:48]:48s} {r['month']} {v:>9} м/м {mm:>7} г/г {yy:>7}")
    elif cmd == "alerts":
        cmd_alerts("--send" in sys.argv)
    elif cmd == "planfact":
        print(planfact("--guest" in sys.argv))
    elif cmd == "snap":
        cmd_snap()
    elif cmd == "score":
        cmd_score()
    else:
        sys.exit(__doc__)
