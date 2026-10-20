#!/usr/bin/env python3
"""Прогноз рынка авиации до 2030 года: вертолёты и самолёты, с учётом новостей, которые могут изменить картину.

  python3 market.py brief  [--days 30]          коротко для гостя: картина сейчас, прогноз, что может её изменить
  python3 market.py now                         опорные факты рынка с источниками
  python3 market.py forecast [--to 2030] [--xlsx out.xlsx]
                                                сценарии «базовый», «с учётом новостей» и «стресс»: самолёты — расходы,
                                                выручка, операционная маржа; вертолёты — себестоимость часа и цена часа
  python3 market.py news   [--days 30] [--min 5]   новости архива по драйверам прогноза: что и в какую сторону давит
  python3 market.py set <драйвер> <год> <значение> "<ссылка>"   поправка к базовому сценарию по новости
                                                (рост в % за год; ключевая и инфляция — уровнем); без ссылки не пишется
  python3 market.py adj                         список поправок «с учётом новостей»

Данные — market.json (открытые источники со ссылками), поправки — market_adj.csv, новости — archive.db сборщика,
вертолёты — fh_base.csv и fh_contracts.csv (лётный час). Расчёт без модели (ИИ). Прогноз — оценка, не факт.
"""
import csv
import json
import re
import sqlite3
import statistics as st
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE / "market.json").read_text(encoding="utf-8"))
ADJ = BASE / "market_adj.csv"
DB = BASE / "archive.db"
YEARS = ["2026", "2027", "2028", "2029", "2030"]
VARIABLE = {"керосин", "аэропорт", "тоир"}       # растут вместе с объёмом перевозок; остальное — постоянные в моменте


def fmt(v, d=1):
    return "н/д" if v is None else f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def pct(v, d=1):
    return "н/д" if v is None else f"{v * 100:+.{d}f}%".replace(".", ",")


def growth(expr, infl):
    e = str(expr).replace(" ", "").replace(",", ".")
    m = re.fullmatch(r"инф([+-]\d+(?:\.\d+)?)?", e)
    return infl + (float(m.group(1)) if m.group(1) else 0) if m else float(e)


# ---------- поправки по новостям ----------

def adjustments():
    if not ADJ.exists():
        return []
    with ADJ.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def scenarios():
    """базовый, с учётом новостей (= базовый + поправки), стресс."""
    sc = CFG["scenarios"]
    adj = adjustments()
    out = {"базовый": sc["базовый"]}
    if adj:
        news = json.loads(json.dumps(sc["базовый"]))
        for a in adj:
            news.setdefault(a["драйвер"], {})[a["год"]] = a["значение"]
        news["_why"] = "базовый + поправки по новостям (market.py adj)"
        out["с учётом новостей"] = news
    out["стресс"] = sc["стресс"]
    return out


def cmd_set(driver, year, value, source=""):
    names = set(CFG["scenarios"]["базовый"]) - {"_why"}
    if driver not in names:
        sys.exit(f"Драйвер: {', '.join(sorted(names))}")
    if year not in YEARS:
        sys.exit(f"Год: {', '.join(YEARS)}")
    if not source.startswith("http"):
        sys.exit("Нужна ссылка на новость или источник — без неё поправка не записывается.")
    rows = [a for a in adjustments() if not (a["драйвер"] == driver and a["год"] == year)]
    rows.append({"драйвер": driver, "год": year, "значение": value.replace(",", "."), "источник": source,
                 "записано": datetime.now().strftime("%Y-%m-%d")})
    with ADJ.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["драйвер", "год", "значение", "источник", "записано"], delimiter=";")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["драйвер"], r["год"])))
    base = CFG["scenarios"]["базовый"][driver][year]
    print(f"Поправка: {driver} {year}: {base} → {value} ({source}). Сценарий «с учётом новостей» пересчитается.")


def cmd_adj():
    rows = adjustments()
    if not rows:
        print("Поправок по новостям нет — сценарий «с учётом новостей» совпадает с базовым.")
        return
    for a in rows:
        print(f"{a['драйвер']} {a['год']}: {CFG['scenarios']['базовый'][a['драйвер']][a['год']]} → {a['значение']} · "
              f"{a['записано']} · {a['источник']}")


# ---------- самолёты ----------

def airlines(p):
    a = CFG["airlines"]
    shares, m0 = a["cost_shares"], a["operating_margin_base"]
    price = {d: 1.0 for d in shares}
    vol = tariff = 1.0
    rows = [("2025", 1.0, 1.0, m0)]
    for y in YEARS:
        infl = float(str(p["инфляция"][y]).replace(",", "."))
        for d in shares:
            price[d] *= 1 + growth(p[d][y], infl) / 100
        vol *= 1 + growth(p["пассажиропоток"][y], infl) / 100
        tariff *= 1 + growth(p["тариф"][y], infl) / 100
        cost = sum(shares[d] * price[d] * (vol if d in VARIABLE else 1.0) for d in shares)
        rev = vol * tariff
        margin = 1 - (1 - m0) * cost / rev
        rows.append((y, rev, cost, margin))
    return rows


# ---------- вертолёты ----------

def helicopters(p):
    try:
        import fh
        base = fh.base_rows()
    except SystemExit:
        return None
    con = fh.contracts() if fh.FCON.exists() else []
    price = st.median([c["цена_без_ндс"] for c in con if c["дата"][:4] == "2025"]) / 1000 if con else None
    f = {d: 1.0 for d in fh.DRIVERS + ["лизинг"]}
    rows = [("2025", fh.cost_at(base, f, "старый"), fh.cost_at(base, f, "новый"), price)]
    for y in YEARS:
        infl = float(str(p["инфляция"][y]).replace(",", "."))
        for d in ("керосин", "зарплата", "тоир", "аэропорт"):
            f[d] *= 1 + growth(p[d][y], infl) / 100
        f["инфляция"] *= 1 + infl / 100
        f["лизинг"] = 1 + fh.lease_effect(fh.KR_BASE, float(str(p["ключевая"][y]).replace(",", ".")))
        if price is not None:
            price *= 1 + growth(p["цена часа"][y], infl) / 100
        rows.append((y, fh.cost_at(base, f, "старый"), fh.cost_at(base, f, "новый"), price))
    return rows


def light_air(m):
    return "🔴" if m < 0 else "🟡" if m < 0.03 else "🟢"


def light_heli(old, new, price):
    return "" if price is None else "🔴" if price < old else "🟡" if price < new else "🟢"


def cmd_forecast(*opts):
    o = dict(zip(opts[::2], opts[1::2]))
    sc = scenarios()
    print("ПРОГНОЗ РЫНКА АВИАЦИИ до 2030 года — ОЦЕНКА, не факт. Макро — " + CFG["macro_source"].split(" · ")[0])
    res = {}
    for name, p in sc.items():
        air, heli = airlines(p), helicopters(p)
        res[name] = (air, heli)
        print(f"\n━━ Сценарий «{name}»: {p.get('_why', '')}")
        print("✈️ Самолёты (индексы к 2025 году; маржа — операционная, база — Аэрофлот 2025)")
        print(f"{'год':<6}{'выручка':>9}{'расходы':>9}{'маржа':>8}")
        for y, rev, cost, m in air:
            print(f"{y:<6}{fmt(rev * 100, 0):>9}{fmt(cost * 100, 0):>9}{pct(m):>8} {light_air(m)}")
        if heli:
            print("🚁 Вертолёты Ми-8: себестоимость и цена часа, тыс. ₽ без НДС")
            print(f"{'год':<6}{'старый':>8}{'новый':>8}{'цена':>8}{'разрыв к новому':>17}")
            for y, a, b, pr in heli:
                gap = f"{fmt(pr - b)} ({pct((pr - b) / b, 0)})" if pr is not None else "н/д"
                print(f"{y:<6}{fmt(a):>8}{fmt(b):>8}{fmt(pr):>8}{gap:>17} {light_heli(a, b, pr)}")
        else:
            print("🚁 Вертолёты: нет данных лётного часа (python3 fh.py import …)")
        kr = [float(str(p["ключевая"][y]).replace(",", ".")) for y in YEARS]
        print("Ключевая ставка, средняя за год: " + ", ".join(f"{y} — {fmt(k, 2)}%" for y, k in zip(YEARS, kr)))
    print("\nДопущения: доли расходов авиакомпании — по МСФО Аэрофлота 2025 (" + CFG["airlines"]["cost_shares_source"]
          .split(" · ")[0] + "); топливо, аэропорты и ТО растут вместе с перевозками; налоги, курс и лизинг в марже "
          "не учтены. Сценарии и источники — market.json; поправки по новостям — market.py adj.")
    if "--xlsx" in o:
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        for name, (air, heli) in res.items():
            ws = wb.create_sheet(name[:30])
            ws.append(["Самолёты", "Выручка, индекс", "Расходы, индекс", "Операционная маржа"])
            for y, rev, cost, m in air:
                ws.append([int(y), round(rev, 4), round(cost, 4), round(m, 4)])
            if heli:
                ws.append([])
                ws.append(["Вертолёты Ми-8", "Себестоимость, старый парк", "Себестоимость, новый", "Цена часа"])
                for y, a, b, pr in heli:
                    ws.append([int(y), round(a, 2), round(b, 2), round(pr, 2) if pr is not None else None])
            ws.column_dimensions["A"].width = 16
        wb.save(o["--xlsx"])
        print(f"Excel: {o['--xlsx']}")


# ---------- новости ----------

def news(days=30, min_score=5):
    if not DB.exists():
        return {}
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT published, title, summary, url, score FROM news WHERE published >= ? AND score >= ? "
                       "ORDER BY score DESC, published DESC", (since, min_score)).fetchall()
    up = CFG["up_words"]
    down = CFG["down_words"]
    by = {}
    seen = set()
    for pub, title, summ, url, score in rows:
        key = re.sub(r"\W+", " ", (title or "").lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        low = f"{title} {summ or ''}".lower()
        head = (title or "").lower()
        for d, spec in CFG["drivers"].items():
            if any(w in low for w in spec["words"]):
                sign = "↑" if any(w in head for w in up) else "↓" if any(w in head for w in down) else "·"
                by.setdefault(d, []).append((score, pub[:10], title, url, sign))
    return by


def pressure(d, items):
    """Куда новости двигают прогноз: + лучше для отрасли, − хуже."""
    ups = sum(1 for i in items if i[4] == "↑")
    downs = sum(1 for i in items if i[4] == "↓")
    effect = CFG["drivers"][d]["effect"]
    cost_like = effect.startswith("расходы") or d in ("ключевая", "санкции", "беспилотники")
    if ups == downs:
        return "направление неясно"
    worse = (ups > downs) if cost_like else (downs > ups)
    return "хуже для отрасли" if worse else "лучше для отрасли"


def cmd_news(*opts):
    o = dict(zip(opts[::2], opts[1::2]))
    days, mn = int(o.get("--days", 30)), int(o.get("--min", 5))
    by = news(days, mn)
    if not by:
        print(f"Нет новостей с баллом ≥ {mn} за {days} дней (или нет архива archive.db).")
        return
    print(f"НОВОСТИ, КОТОРЫЕ ДВИГАЮТ ПРОГНОЗ (за {days} дней, балл ≥ {mn}; ↑ рост, ↓ снижение, · без направления)")
    for d, items in sorted(by.items(), key=lambda x: (-max(i[0] for i in x[1]), -len(x[1]))):
        spec = CFG["drivers"][d]
        print(f"\n▸ {d} — {spec['effect']} ({spec['segments']}): {len(items)} нов., {pressure(d, items)}")
        for score, pub, title, url, sign in sorted(items, reverse=True)[:3]:
            print(f"   {sign} {pub} [{score}] {title[:110]} — {url}")
    print("\nЕсли в новости есть цифра, меняющая допущение сценария (цена керосина, ставка, пассажиропоток, тарифы), — "
          "python3 market.py set <драйвер> <год> <значение> \"<ссылка>\".")


# ---------- коротко для гостя ----------

def cmd_now():
    for seg in ("airlines", "helicopters"):
        s = CFG[seg]
        print(f"{s['title']}:")
        for name, val, src in s["facts"]:
            print(f"  • {name}: {val} — {src}")
    print("Макро: " + CFG["macro_source"])


def cmd_brief(*opts):
    o = dict(zip(opts[::2], opts[1::2]))
    sc = scenarios()
    main = "с учётом новостей" if "с учётом новостей" in sc else "базовый"
    b, s = sc[main], sc["стресс"]
    ab, as_ = airlines(b), airlines(s)
    hb, hs = helicopters(b), helicopters(s)
    print(f"ПРОГНОЗ РЫНКА АВИАЦИИ ДО 2030 ГОДА (оценка; основной сценарий — «{main}»)")
    print(f"✈️ Самолёты: операционная маржа отрасли (база — Аэрофлот 2025: {pct(ab[0][3])}) — "
          f"2026: {pct(ab[1][3])}, 2028: {pct(ab[3][3])}, 2030: {pct(ab[5][3])} {light_air(ab[5][3])}; "
          f"в стрессе 2030: {pct(as_[5][3])} {light_air(as_[5][3])}.")
    if hb:
        y0, y5 = hb[0], hb[5]
        print(f"🚁 Вертолёты Ми-8: цена часа {fmt(y0[3])} тыс. ₽ против себестоимости нового {fmt(y0[2])} (2025); "
              f"в 2030 — {fmt(y5[3])} против {fmt(y5[2])} {light_heli(y5[1], y5[2], y5[3])}; "
              f"в стрессе 2030 — {fmt(hs[5][3])} против {fmt(hs[5][2])} {light_heli(hs[5][1], hs[5][2], hs[5][3])}.")
    by = news(int(o.get("--days", 30)), 5)
    if by:
        top = sorted(by.items(), key=lambda x: (-max(i[0] for i in x[1]), -len(x[1])))[:4]
        print("Что может изменить картину (новости за месяц):")
        for d, items in top:
            sc0, pub, title, url, sign = max(items)
            print(f"  • {d}: {pressure(d, items)} — {title[:90]} ({pub}) {url}")
    else:
        print("Существенных новостей по драйверам прогноза за месяц нет (или архив новостей недоступен).")
    if adjustments():
        print("Учтены поправки по новостям: python3 market.py adj")


if __name__ == "__main__":
    cmds = {"brief": cmd_brief, "now": cmd_now, "forecast": cmd_forecast, "news": cmd_news, "set": cmd_set,
            "adj": cmd_adj}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]](*sys.argv[2:])
