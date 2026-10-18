#!/usr/bin/env python3
"""Стоимость вагона: светофор «покупать / держать / продавать», справедливая цена б/у по возрасту, прогноз цены до 2030.

  python3 zvagon.py run [--type gon|inno|kr158|all] [--age 14] [--scenario base|pess] [--guest] [--out файл.md]
  python3 zvagon.py signals          только светофор (текущие значения показателей)

Данные — ~/railway-monitor/forecast/vagon_data.json (цены, коэффициенты, показатели светофора — обновляет владелец).
Ставки на 2027–2030 — из рабочей модели прогноза ставок (zmodel.py, рекомендуемые показатели).
Цена нового вагона = e^(a + b·ln(средняя ставка за 3 года) + c·(год − 2015)): цена следует за ставкой со сглаживанием
и растёт вместе с себестоимостью. Б/у = новый × коэффициент возраста × коэффициент фазы рынка, не ниже цены лома.
"""
import argparse
import json
import math
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import zmodel  # noqa: E402  — ставки 2027–2030 по рабочей модели

DATA = BASE / "forecast" / "vagon_data.json"
NAMES = {"gon": "Полувагон обычный", "inno": "Полувагон инновационный", "kr158": "Крытый 158 м³"}
RATE_KEY = {"gon": "gon", "inno": "inno", "kr158": "kr158"}


def load():
    if not DATA.exists():
        sys.exit(f"Нет {DATA} — модель стоимости вагонов не загружена на сервер.")
    return json.loads(DATA.read_text(encoding="utf-8"))


def n(v, d=1):
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def rate_paths(scen):
    """Ставки 2024–2030 по типам: история + рабочая модель (рекомендуемые показатели)."""
    D = zmodel.load()
    g = zmodel.forecast_one(D, "gon", D["default"]["gon"], scen, {})
    k = zmodel.forecast_one(D, "kr", D["default"]["kr"], scen, {}, gon_path=g["path"])
    return zmodel.paths(D, {"gon": g, "kr": k}, ["gon", "inno", "kr158"])


def signals(V):
    """Баллы светофора: + за покупку, − против. Пороги проверены на 2007–2025 (полувагоны)."""
    rows, score = [], 0
    for s in V["signals"]:
        v = s["value"]
        pts = 1 if (v <= s["buy"] if s["dir"] == "low" else v >= s["buy"]) else \
            (-1 if (v >= s["sell"] if s["dir"] == "low" else v <= s["sell"]) else 0)
        if s.get("scored", True):
            score += pts
        rows.append((s, pts))
    return rows, score


def verdict(V, score):
    for lvl in V["verdicts"]:
        if score >= lvl["min"]:
            return lvl
    return V["verdicts"][-1]


def price_path(V, typ, rates):
    """Цена нового вагона 2026–2030, млн ₽: 2026 — рынок, далее модель, привязанная к рынку 2026 г."""
    c = V["price_model"][typ]
    hist = {int(y): r for y, r in V["rates_hist"][typ].items()}
    allr = {**hist, **{y: rates[y] for y in rates}}
    fit = {y: math.exp(c["a"] + c["b"] * math.log(sum(allr[y - i] for i in range(3)) / 3) + c["c"] * (y - 2015)) / 1000
           for y in range(2026, 2031)}
    k = V["market_2026"][typ] / fit[2026]  # насколько рынок 2026 г. выше/ниже модели — разрыв закрывается за 3 года
    return {y: fit[y] * (k ** max(0, 1 - (y - 2026) / 3)) for y in fit}, fit[2026]


def age_factor(V, age):
    for a in V["age_factors"]:
        if age <= a["to"]:
            return a["k"]
    return V["age_factors"][-1]["k"]


def run(a):
    V = load()
    types = ["gon", "inno", "kr158"] if a.type == "all" else [a.type]
    rows, score = signals(V)
    vd = verdict(V, score)
    rp = rate_paths(a.scenario)
    L = ["# Стоимость вагона: покупать, держать или продавать", "",
         f"<small>Сценарий ставок: {'базовый' if a.scenario == 'base' else 'пессимистичный'} · возраст б/у: {a.age} лет · "
         f"показатели светофора на {V['as_of']} · ₽ без НДС</small>", "",
         f"{{{{класс:{vd['class']}}}}} **{vd['title']}** — {vd['text']}", "", "## Светофор рынка полувагонов", "",
         "| Показатель | Сейчас | Сигнал | Почему важно |", "|---|---|---|---|"]
    for s, pts in rows:
        mark = "🟢 покупать" if pts > 0 else "🔴 против" if pts < 0 else "🟡 нейтрально"
        L.append(f"| {s['name']}{'' if s.get('scored', True) else ' *'} | {s['shown']} | {mark} | {s['why']} |")
    L += ["", f"Сумма баллов: **{score:+d}** из {sum(1 for s in V['signals'] if s.get('scored', True))}. "
          f"{V['backtest_note']}", "", "<small>* подтверждающий сигнал — в сумму не входит.</small>", ""]
    L += ["## Цена вагона: сейчас и прогноз", "", "```cards"]
    paths, bottoms = {}, {}
    for t in types:
        p, fit26 = price_path(V, t, {y: rp[RATE_KEY[t]][y] for y in range(2027, 2031)})
        paths[t] = p
        gap = (V["market_2026"][t] / fit26 - 1) * 100
        L.append(f"{NAMES[t]}, новый, 2026 | {n(V['market_2026'][t])} млн ₽ | "
                 f"{'⚠ ▲' if gap > 10 else '✓ ▼' if gap < -10 else '▶'} {gap:+.0f}% к справедливой цене")
    L += ["```", "", "| Тип, млн ₽ | " + " | ".join(str(y) for y in range(2026, 2031)) + " | дно цены |", "|---|" + "---|" * 6]
    for t in types:
        p = paths[t]
        low = min(p, key=p.get)
        L.append(f"| {NAMES[t]}, новый | " + " | ".join(n(p[y]) for y in range(2026, 2031)) + f" | {low} |")
        kf, floor = age_factor(V, a.age), V["scrap_floor"]
        ph = V["phase_factor"]["bottom"] if score >= 2 else 1.0  # скидка дна рынка уходит за 3 года
        used = {y: max(floor, p[y] * kf * ph ** max(0, 1 - (y - 2026) / 3)) for y in p}
        bottoms[t] = (low, min(used, key=used.get))
        L.append(f"| {NAMES[t]}, б/у {a.age} лет | " + " | ".join(n(used[y]) for y in range(2026, 2031)) +
                 f" | {min(used, key=used.get)} |")
    pf = f" × {n(V['phase_factor']['bottom'], 2)} на дне рынка (скидка уходит за 3 года)" if score >= 2 else ""
    L += ["", f"<small>Б/у = новый × {n(age_factor(V, a.age), 2)} (возраст {a.age} лет){pf}, не ниже цены лома "
          f"{n(V['scrap_floor'])} млн ₽. Ставки 2027–2030 — рабочая модель /prognoz. Ошибка модели цены — около ±15% "
          "в год.</small>", ""]
    L += ["```chart"] + [f"{NAMES[t]}, новый, млн ₽ | " + " | ".join(f"{y}: {paths[t][y]:.1f}" for y in range(2026, 2031))
                         for t in types] + ["```", ""]
    when = []
    for t in types:
        new_low, used_low = bottoms[t]
        when.append(f"{NAMES[t].lower()}: б/у — {'сейчас' if used_low <= 2026 else f'в {used_low} г.'}, новый — "
                    f"{'сейчас' if new_low <= 2026 else f'ждать {new_low} г. (цены заводов ещё снизятся)'}")
    L += ["## Когда входить в рынок", "", f"> **Что делать:** {vd['action']}", "",
          "**Когда цена ниже всего по прогнозу:** " + "; ".join(when) + ".", "",
          "Продавать старые вагоны — когда светофор уходит в минус: ставка у максимума, парк растёт быстрее грузов.", "",
          "## На что смотреть каждый месяц", ""]
    L += [f"- **{s['name']}** — {s['watch']}" for s in V["signals"]]
    L += ["", V["guest_note"] if a.guest else V["owner_note"]]
    md = "\n".join(L) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Файл: {a.out}")
    else:
        print(md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "signals"])
    ap.add_argument("--type", default="all", choices=["gon", "inno", "kr158", "all"])
    ap.add_argument("--age", type=int, default=14)
    ap.add_argument("--scenario", default="base", choices=["base", "pess"])
    ap.add_argument("--guest", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "signals":
        V = load()
        rows, score = signals(V)
        for s, pts in rows:
            print(f"{pts:+d}  {s['name']}: {s['shown']}")
        print(f"Итого {score:+d} — {verdict(V, score)['title']}")
    else:
        run(a)
