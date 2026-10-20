#!/usr/bin/env python3
"""Светофор событий рынка по типам вагонов: что в новостях за последние дни тянет спрос на вагон вверх или вниз. 0 токенов.

  python3 zevents.py [--wagon hop_grain|fit80|kr158|gon|all] [--days 14] [--out файл.md]
  python3 zevents.py set grain.quota_cut=20 grain.port=Тамань:1 grain.freight=30 grain.truck=5
                         fit.to_gondola=10 fit.port=Владивосток:30:1 fit.import=6 fit.discount=0
                                                параметры рынка с цифрами из новостей → рубли в прогнозе (ztypes.py)
  python3 zevents.py show | clear [grain|fit]   что сейчас учтено / сбросить

Цепочка «вагон → порт → судно»: проблема в море или порту (закрытие, атака, нет судов, рост фрахта), квота или пошлина
снижают спрос на вагон, который везёт груз к порту, — вагоны встают в отстой, груз уходит на автотранспорт или в обход.
Контейнеры в полувагонах и крытых — конкуренция фитинговым платформам. Правила — по словам в заголовке и тексте новости
из архива сборщика (archive.db); каждое правило: тип вагона, направление (+ спрос растёт / − падает), почему.
Итог по типу: сумма направлений → какой сценарий прогноза подтверждают события (≤ −2 — пессимистичный, ≥ +2 —
оптимистичный). Цифры прогноза программа не меняет — только подсказывает, какой сценарий брать.
"""
import argparse
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "archive.db"
MSK = timezone(timedelta(hours=3))
NAMES = {"hop_grain": "Хоппер-зерновоз", "fit80": "Фитинговые платформы", "kr158": "Крытые вагоны", "gon": "Полувагоны"}
PORT = (r"(?<![а-яё])(порт|порта|порту|портов|портах|терминал\w*|причал\w*|новороссийск\w*|тамань|тамани|туапсе|"
        r"усть-луг\w*|приморск\w*|высоцк\w*|черн\w* мор\w*|азовск\w* мор\w*|балтийск\w* мор\w*)(?![а-яё])")
STOP = r"(атак|удар|обстрел|повреж|закрыт|закрыл|приостанов|остановл|блокир|затор|очеред\w* судов|скоплени|простаива|не принима)"
GRAIN = r"(зерн|пшениц|элеватор|зерновоз|ячмен|кукуруз)"
BOX = r"(контейнер|фитинг|teu|дфэ)"
# (тип, направление, шаблон, почему[, обязательный контекст]). Шаблоны — по нижнему регистру «заголовок + текст»;
# контекст — без него событие не засчитывается (порт закрыт — это про зерновозы, только если в новости есть зерно).
RULES = [
    ("hop_grain", -1, rf"{STOP}.{{0,80}}{PORT}|{PORT}.{{0,80}}{STOP}", "порт или подходы к нему закрыты — зерно не везут к морю, зерновозы встают", GRAIN),
    ("hop_grain", -1, r"(квот|пошлин).{0,60}(зерн|пшениц)|(зерн|пшениц).{0,60}(квот|пошлин)", "квота или пошлина на экспорт зерна — меньше экспорта"),
    ("hop_grain", -1, r"(фрахт|ставк\w* фрахт).{0,40}(вырос|рост|подорож)|(нехватк|дефицит).{0,30}(судов|балкер|флот)", "суда дороже или их не хватает — экспорт медленнее", GRAIN),
    ("hop_grain", -1, r"зерн.{0,60}(автотранспорт|автомобил|фур)|(автотранспорт|фур).{0,60}зерн", "зерно уходит на автотранспорт"),
    ("hop_grain", -1, r"(низк|снижен|падени|сокращ)\w*.{0,30}(урожа|экспорт\w* зерн)", "урожай или экспорт зерна ниже"),
    ("hop_grain", +1, r"(рекордн|рост|увелич)\w*.{0,30}(урожа|экспорт\w* зерн|погрузк\w* зерн|отгрузк\w* зерн)", "больше зерна к перевозке"),
    ("hop_grain", +1, r"(отмен|снижен|обнул)\w*.{0,30}(пошлин|квот).{0,40}(зерн|пшениц)", "экспорт зерна дешевле или свободнее"),
    ("hop_grain", +1, r"дефицит\w*.{0,30}зерновоз|зерновоз\w*.{0,40}(дефицит|не хватает|рынок продавца)", "зерновозов не хватает — ставка вверх"),
    ("fit80", -1, r"контейнер\w*.{0,40}(полувагон|крыт)|(полувагон|крыт)\w*.{0,40}контейнер", "контейнеры везут в полувагонах и крытых — платформы теряют груз"),
    ("fit80", -1, r"(снижен|падени|сокращ)\w*.{0,40}(импорт|перевоз|оборот)\w*.{0,20}контейнер|контейнер\w*.{0,40}(снизил|упал|сократил)", "меньше контейнеров"),
    ("fit80", -1, rf"{STOP}.{{0,80}}{PORT}|{PORT}.{{0,80}}{STOP}", "порт закрыт или атакован — меньше контейнеров на сеть", BOX),
    ("fit80", -1, r"профицит\w*.{0,30}(фитинг|платформ)|(фитинг|платформ)\w*.{0,40}(профицит|отстой|избыт)", "лишние платформы — ставка вниз"),
    ("fit80", +1, r"(рост|увелич|рекорд)\w*.{0,40}(импорт|перевоз|оборот|транзит)\w*.{0,20}контейнер|контейнер\w*.{0,40}(вырос|рекорд)", "больше контейнеров"),
    ("fit80", +1, r"(скидк|льгот)\w*.{0,60}(фитинг|платформ|контейнер)", "скидки на перевозку на платформах — спрос вверх"),
    ("kr158", +1, r"(рост|увелич|оживлен)\w*.{0,30}(стройк|строительств|ипотек|цемент)", "стройка и ипотека растут — спрос на крытые"),
    ("kr158", -1, r"(снижен|падени|сокращ)\w*.{0,30}(стройк|строительств|ипотек|цемент)", "стройка и ипотека падают"),
    ("kr158", -1, r"профицит\w*.{0,30}крыт|крыт\w*.{0,40}(профицит|отстой)", "лишние крытые вагоны"),
    ("gon", +1, r"(рост|увелич)\w*.{0,30}(экспорт\w* угл|погрузк\w* угл|добыч\w* угл)", "больше угля к перевозке"),
    ("gon", -1, r"(снижен|падени|сокращ)\w*.{0,30}(экспорт\w* угл|погрузк\w* угл|добыч\w* угл)", "меньше угля"),
    ("gon", -1, r"профицит\w*.{0,30}полувагон|полувагон\w*.{0,40}(профицит|отстой)", "лишние полувагоны"),
    ("gon", +1, r"контейнер\w*.{0,40}полувагон|полувагон\w*.{0,40}контейнер", "полувагоны получают контейнеры — дополнительный груз"),
    ("all", 0, r"тариф\w*.{0,60}(фитинг|платформ|полувагон|крыт|зерновоз|хоппер|порожн)", "тариф РЖД по типу вагона или порожнему пробегу — проверить, кому выгоднее"),
]


# ---------- Параметры рынка: события → рубли (forecast/market_params.json, на сервере) ----------
# Квота, закрытые порты, фрахт, автотранспорт (зерно); контейнеры в полувагонах, порты, импорт, скидки РЖД (платформы).
# Бот заполняет их по новостям командой `set` (только с цифрой из новости), ztypes.py переводит в рубли:
#   потеря экспорта за сезон, % = квота + Σ доля порта × месяцы/12 + автотранспорт + 0,1 × рост фрахта;
#   IV кв.: ставка месяца × (1 − 0,9 × потеря отгрузок в этот месяц, %) — 0,9: в авг.–сент. 2026 г. погрузка зерна +55%,
#   ставка +51% (одно наблюдение — уточняется по журналу); 2027 г.: потеря экспорта — в фактор «экспорт зерна».
#   Платформы: баланс контейнеров = импорт − уход в полувагоны − порты + 0,5 × скидка РЖД; IV кв. — коэффициент 0,5.
PARAMS = BASE / "forecast" / "market_params.json"
EMPTY = {"grain": {"quota_cut": 0, "ports": [], "freight": 0, "truck": 0},
         "fit": {"to_gondola": 0, "ports": [], "import": 0, "discount": 0}, "port_shares": {}, "updated": "", "notes": []}
PNAME = {"quota_cut": "квота на экспорт зерна, % недобора к ожидаемому экспорту", "freight": "рост фрахта судов, %",
         "truck": "доля зерна, ушедшая на автотранспорт, %", "to_gondola": "контейнеры, ушедшие в полувагоны и крытые, %",
         "import": "импорт контейнеров к прошлому году, %", "discount": "скидка РЖД на тариф/порожний пробег платформ, %"}


def params():
    import json
    P = json.loads(json.dumps(EMPTY))
    if PARAMS.exists():
        got = json.loads(PARAMS.read_text(encoding="utf-8"))
        for k, v in got.items():
            P[k] = {**P[k], **v} if isinstance(P.get(k), dict) and isinstance(v, dict) else v
    return P


def effects(kind):
    """kind: grain | fit → {'comp': {строка: % к экспорту/балансу 2027}, 'q4': [множители 3 месяцев], 'text': [...]}"""
    P = params()
    g = P[kind]
    ports = g.get("ports", [])
    share = lambda x: float(x.get("share") or P["port_shares"].get(x["port"], 0))
    port_year = sum(share(x) * min(float(x["months"]), 12) / 12 for x in ports)
    port_m = lambda i: sum(share(x) for x in ports if float(x["months"]) >= i)
    if kind == "grain":
        comp = {"Квота на экспорт зерна": -g["quota_cut"], "Порты и море (закрытия, атаки)": -port_year,
                "Фрахт и нехватка судов": -0.1 * g["freight"], "Зерно на автотранспорт": -g["truck"]}
        dis = [port_m(i) + g["truck"] + 0.1 * g["freight"] + g["quota_cut"] for i in (1, 2, 3)]
        q4 = [max(0.5, 1 - 0.9 * d / 100) for d in dis]
    else:
        comp = {"Импорт контейнеров": g["import"], "Контейнеры в полувагонах и крытых": -g["to_gondola"],
                "Порты и море (закрытия, перегрузка)": -port_year, "Скидки РЖД для платформ": 0.5 * g["discount"]}
        dis = [g["import"] - g["to_gondola"] - port_m(i) + 0.5 * g["discount"] for i in (1, 2, 3)]
        q4 = [max(0.5, 1 + 0.5 * d / 100) for d in dis]
    text = [f"{PNAME[k]}: {v:g}" for k, v in g.items() if k != "ports" and v]
    text += [f"порт {x['port']}: доля {share(x):g}%, {x['months']} мес." for x in ports]
    return {"comp": {k: v for k, v in comp.items() if v}, "q4": q4, "text": text, "updated": P.get("updated", "")}


def cmd_set(pairs):
    """set grain.quota_cut=20 grain.port=Тамань:1 grain.port=Новый:7:2 fit.to_gondola=10 fit.port=Владивосток:30:1 …"""
    import json
    P = params()
    for kv in pairs:
        k, _, v = kv.partition("=")
        kind, _, key = k.partition(".")
        if kind not in ("grain", "fit") or not (key == "port" or key in P[kind]):
            sys.exit(f"Не понял «{kv}». Пример: grain.quota_cut=20 grain.port=Тамань:1 fit.to_gondola=10 fit.port=Владивосток:30:1")
        if key == "port":
            parts = v.split(":")
            item = {"port": parts[0], "months": float(parts[-1])}
            if len(parts) == 3:
                item["share"] = float(parts[1].replace(",", "."))
            P[kind]["ports"] = [x for x in P[kind]["ports"] if x["port"] != parts[0]] + ([item] if item["months"] > 0 else [])
        else:
            P[kind][key] = float(v.replace(",", "."))
    P["updated"] = datetime.now(MSK).strftime("%Y-%m-%d %H:%M")
    PARAMS.parent.mkdir(parents=True, exist_ok=True)
    PARAMS.write_text(json.dumps(P, ensure_ascii=False, indent=1), encoding="utf-8")
    cmd_show()


def cmd_show():
    for kind, nm in (("grain", "Зерновоз"), ("fit", "Фитинговые платформы")):
        e = effects(kind)
        print(f"{nm}: " + ("; ".join(e["text"]) or "событий с цифрами нет") +
              f" → 2027: {', '.join(f'{k} {v:+.1f}%' for k, v in e['comp'].items()) or '0'}; IV кв. ×{', ×'.join(f'{x:.2f}' for x in e['q4'])}")


def events(wagon="all", days=14):
    if not DB.exists():
        sys.exit(f"Нет {DB} — сначала: python3 collector.py collect")
    since = (datetime.now(MSK) - timedelta(days=days)).isoformat(timespec="seconds")
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT published, source, title, summary, url FROM news WHERE published >= ? ORDER BY published DESC",
                       (since,)).fetchall()
    found, seen = {}, set()
    for pub, src, title, summ, url in rows:
        low = f"{title} {summ or ''}".lower()
        for typ, sign, pat, why, *ctx in RULES:
            if wagon not in ("all", typ) and typ != "all":
                continue
            key = (typ, title.lower()[:60])
            if key in seen or not re.search(pat, low) or (ctx and not re.search(ctx[0], low)):
                continue
            seen.add(key)
            found.setdefault(typ, []).append({"date": pub[:10], "title": title, "url": url, "sign": sign, "why": why})
    return found


def verdict(items):
    s = sum(e["sign"] for e in items)
    return s, ("пессимистичный" if s <= -2 else "оптимистичный" if s >= 2 else "базовый")


def report(wagon, days):
    found = events(wagon, days)
    L = [f"## События рынка за {days} дней: что тянет спрос на вагоны", ""]
    types = [t for t in NAMES if wagon in ("all", t)]
    if not any(found.get(t) for t in types) and not found.get("all"):
        return "\n".join(L + ["Существенных событий не найдено.", ""]) + "\n"
    L += ["| Тип вагона | За рост спроса | Против | Итог | Подтверждает сценарий |", "|---|---|---|---|---|"]
    for t in types:
        it = found.get(t, [])
        if it:
            s, v = verdict(it)
            L.append(f"| {NAMES[t]} | {sum(e['sign'] > 0 for e in it)} | {sum(e['sign'] < 0 for e in it)} | "
                     f"{'+' if s > 0 else ''}{s} | {v} |")
    L.append("")
    for t in types + ["all"]:
        it = found.get(t, [])[:6]
        if not it:
            continue
        L += [f"**{NAMES.get(t, 'Тарифы РЖД по типам вагонов')}**", ""]
        L += [f"- {'🟢' if e['sign'] > 0 else '🔴' if e['sign'] < 0 else '🟡'} {e['date'][8:10]}.{e['date'][5:7]} — {e['title']} → "
              f"{e['why']} [ССЫЛКА]({e['url']})" for e in it]
        L.append("")
    L += ["<small>Подсказка, а не расчёт: сценарий прогноза выбирается с учётом этих событий; цифры модели не меняются. "
          "Правила — по словам в новостях, возможны ложные срабатывания.</small>", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    if sys.argv[1:2] == ["set"]:
        sys.exit(cmd_set(sys.argv[2:]))
    if sys.argv[1:2] == ["show"]:
        sys.exit(cmd_show())
    if sys.argv[1:2] == ["clear"]:
        import json
        P = params()
        for kind in (sys.argv[2:] or ["grain", "fit"]):
            P[kind] = EMPTY[kind]
        PARAMS.write_text(json.dumps(P, ensure_ascii=False, indent=1), encoding="utf-8")
        sys.exit(cmd_show())
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wagon", default="all", choices=["all"] + list(NAMES))
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--out")
    a = ap.parse_args()
    md = report(a.wagon, a.days)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Файл: {a.out}")
    else:
        print(md)
