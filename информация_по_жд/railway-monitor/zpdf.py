#!/usr/bin/env python3
"""Расчёт из мини-приложения → PDF в чат тому, кто считал. Без нейросети (0 токенов).

  python3 zpdf.py <TELEGRAM_ID> '<json>'
  json: {"kind": "forecast", "wagon": "inno", "scenario": "base", "set": {...}, "from": "2026-10", "to": "2026-11"}
        {"kind": "deal", "wagon": "inno", "scenario": "base", "term": 20, "price": "", "spread": "", "util": "", "opex": ""}
        {"kind": "rates", "from": "2026-01", "to": "2026-09"}          — только владельцу (данные партнёра)
        {"kind": "retro", "wagon": "inno", "from": "2025-06", "to": "2026-09"}   — только владельцу
        {"kind": "planfact"}                                                — прогноз и факт (гостю — без ставок факта)

Файл кладётся на полку того, кто считал (владелец — saved/model/, гость — saved_<агент>/model/), PDF приходит в чат
с кнопкой «Читать в приложении». Запускает мини-приложение (zapp.py, /api/pdf); можно и вручную.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
STAMP = "<small>₽/сут без НДС · считает программа ЖДуши без нейросети · оценка рынка, не инвестиционная рекомендация</small>"


def n(v, d=0):
    return "—" if v is None else f"{v:,.{d}f}".replace(",", " ").replace(".", ",").replace("-", "−")


def sg(v):
    return ("+" if v > 0 else "−" if v < 0 else "") + n(abs(v))


MON = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def mname(m):
    return f"{MON[int(m[5:]) - 1]} {m[:4]}"


def span(keys, b):
    """Месяцы из keys в выбранном периоде «с … по …» (ГГГГ-ММ); не задан — все."""
    lo, hi = str(b.get("from") or keys[0]), str(b.get("to") or keys[-1])
    if lo > hi:
        lo, hi = hi, lo
    return [k for k in keys if lo <= k <= hi] or keys[:1]


def forecast_md(b, guest):
    import zapp
    r = zapp.forecast({"wagon": b.get("wagon"), "scenario": b.get("scenario"), "set": b.get("set") or {}})
    if r.get("error"):
        sys.exit(r["error"])
    sc = list(r["years"])
    ms = span(list(r["monthly"][sc[0]]), b)
    y0, y1 = int(ms[0][:4]), int(ms[-1][:4])
    L = [f"# Прогноз ставки: {r['wagon'].lower()} — {mname(ms[0])} – {mname(ms[-1])}", "", STAMP, "",
         f"Сценарий: **{r['scenario'].lower()}**. Данные рынка на {r['as_of']}; последняя ставка — {n(r['now'])} ₽/сут."]
    if b.get("set"):
        L.append("Свои допущения: " + "; ".join(f"{r['factors'].get(k, (k,))[0]} = {v}" for k, v in b["set"].items() if v not in (None, "")) + ".")
    L += ["", "## 1. Ставка по месяцам выбранного периода, ₽/сут", "", "| Месяц | " + " | ".join(sc) + " |", "|---" * (len(sc) + 1) + "|"]
    L += [f"| {mname(m)} | " + " | ".join(n(r["monthly"][k][m]) for k in sc) + " |" for m in ms]
    L += ["", "<small>Октябрь–декабрь 2026 г. — прогноз модели по месяцам (способ, который точнее всего на прошлом). С января "
          "2027 г. — плавный путь через среднюю ставку каждого года, без сезонности: ориентир по уровню, не по месяцу."
          + (" У зерновоза сезонные колебания внутри года — в разы, смотрите среднюю за год." if "зерн" in r["wagon"].lower() else "")
          + "</small>", ""]
    sec = 2
    yrs = [str(y) for y in range(max(y0, 2026), y1 + 1) if str(y) in r["years"][sc[0]]]
    if y1 >= 2027:
        L += [f"## {sec}. Средняя ставка за год", "", "| Сценарий | " + " | ".join(yrs) + " |", "|---" * (len(yrs) + 1) + "|"]
        L += [f"| {k} | " + " | ".join(n(r["years"][k][y]) for y in yrs) + " |" for k in sc]
        sec += 1
        py = [y for y in r["parts"] if y0 <= int(y) <= y1]
        keys = list(dict.fromkeys(k for y in py for k in r["parts"][y]))
        if py and keys:
            L += ["", f"## {sec}. Из чего складывается изменение ставки за год ({r['parts_scenario'].lower()}), ₽/сут", "",
                  "| Фактор | " + " | ".join(py) + " |", "|---" * (len(py) + 1) + "|"]
            L += [f"| {k} | " + " | ".join(sg(r["parts"][y].get(k, 0)) for y in py) + " |" for k in keys]
            L.append("| **Ставка на конец года** | " + " | ".join(f"**{n(r['end'][y])}**" for y in py) + " |")
            sec += 1
    v = r.get("value")
    if v:
        vy = [y for y in v["new"] if int(y) <= max(y1, 2026)]
        L += ["", f"## {sec}. Стоимость вагона, млн ₽ без НДС", "", "| | " + " | ".join(vy) + " |", "|---" * (len(vy) + 1) + "|",
              "| Новый | " + " | ".join(n(v["new"][y], 1) for y in vy) + " |",
              "| Б/у 14 лет | " + " | ".join(n(v["used"][y], 1) for y in vy) + " |",
              "| Доход к цене, % | " + " | ".join(n(v["cap"][y], 1) for y in vy) + " |"]
    acc = r.get("accuracy") or {}
    L += ["", "## Как считается", "",
          "- Ближайшие месяцы — способ, который точнее всего на прошлом для этого типа (проверка допущений модели).",
          "- Годы — годовая модель по факторам (2011–2025 гг.); значения факторов по сценариям — вкладка «Факторы» в приложении.",
          ] + ([f"- Точность годовой модели на прошлых годах: ошибка ±{acc['error']} п.п. в год, направление угадано в "
                f"{round(acc['hit'] * 100)}% лет."] if acc.get("error") is not None and acc.get("hit") is not None else [])
    return f"прогноз_{b.get('wagon', 'inno')}_{ms[0]}_{ms[-1]}", "\n".join(L) + "\n"


def deal_md(b, guest):
    import zdeal
    argv = ["run", "--wagon", str(b.get("wagon") or "inno"), "--scenario", str(b.get("scenario") or "base")]
    for k, lim in (("price", (0.5, 30)), ("spread", (0, 15)), ("util", (30, 100)), ("opex", (0, 60)), ("term", (3, 25))):
        v = str(b.get(k) or "").replace(",", ".").strip()
        if v:
            x = min(lim[1], max(lim[0], float(v)))
            argv += [f"--{k}", str(int(x) if k == "term" else x)]
    if guest:
        argv.append("--guest")
    a = zdeal.args(argv)
    _, md = zdeal.report(a)
    return f"сделка_{a.wagon}_{a.term}лет", md


def rates_md(b, guest):
    if guest:
        sys.exit("Ставки по месяцам — только владельцу")
    import zrates
    t = zrates.table()
    allm = sorted({m for g in t["groups"] for x in g["rows"] for m, _ in x["hist"]})
    ms = span(allm, b)
    L = [f"# Ставки и парк по месяцам: {mname(ms[0])} – {mname(ms[-1])}", "",
         STAMP.replace("оценка рынка", "данные рынка, только для внутреннего использования"), ""]
    for g in t["groups"]:
        L += [f"## {g['title']}", "", "| Показатель | " + " | ".join(m[2:].replace("-", ".") for m in ms) + " | к мес. | к году |",
              "|---" * (len(ms) + 3) + "|"]
        for x in g["rows"]:
            h = dict(x["hist"])
            L.append(f"| {x['name']} | " + " | ".join(n(h.get(m)) for m in ms) +
                     f" | {n(x['mm'], 1) if x['mm'] is not None else '—'}% | {n(x['yy'], 1) if x['yy'] is not None else '—'}% |")
        L.append("")
    if t["alerts"]:
        L += ["## Оповещения", ""] + [f"- {a['text']}" for a in t["alerts"]]
    return f"ставки_по_месяцам_{ms[0]}_{ms[-1]}", "\n".join(L) + "\n"


def retro_md(b, guest):
    if guest:
        sys.exit("Анализ по месяцам — только владельцу")
    import zretro
    w = b.get("wagon") if b.get("wagon") in zretro.RATE else "inno"
    md = zretro.report(w)
    lo, hi = str(b.get("from") or "0000-00"), str(b.get("to") or "9999-99")
    keep = []
    for x in md.splitlines():  # в таблице по месяцам — только строки выбранного периода
        c = x.split("|")
        if x.startswith("| ") and len(c) > 2 and c[1].strip()[:3] in [m[:3] for m in zretro.MON] and c[1].strip()[-4:].isdigit():
            mi = [m[:3] for m in zretro.MON].index(c[1].strip()[:3]) + 1
            if not lo <= f"{c[1].strip()[-4:]}-{mi:02d}" <= hi:
                continue
        keep.append(x)
    per = f" — {lo}…{hi}" if b.get("from") or b.get("to") else ""
    return f"анализ_по_месяцам_{w}", "\n".join(keep).replace("\n", f"{per}\n", 1) + "\n"


def planfact_md(b, guest):
    import zrates
    return f"прогноз_и_факт_{time.strftime('%Y-%m')}", zrates.planfact(guest)


KINDS = {"forecast": forecast_md, "deal": deal_md, "rates": rates_md, "retro": retro_md, "planfact": planfact_md}


def run(uid, body):
    import zapp
    import send
    acc = zapp.who(str(uid))
    if not acc:
        sys.exit("Нет доступа")
    role, _, _, own = acc
    if role == "respondent":
        sys.exit("Респонденту доступна только анкета")
    kind = body.get("kind")
    if kind not in KINDS:
        sys.exit("Нет такого расчёта")
    if role != "owner":  # методика — только владельцу: без своих допущений и разделов «как считаем»
        body["set"] = {}
    name, md = KINDS[kind](body, role != "owner")
    if role != "owner":
        import zclosed
        md = zclosed.strip(md)
        if kind == "forecast":  # гостю — только открытые факторы: что влияет и что сейчас, без вкладов и весов
            md = md.rstrip() + "\n\n" + zclosed.factors_md()
    out = own / "model" / f"{time.strftime('%Y-%m-%d_%H%M')}_{name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    py = Path.home() / "pw" / "bin" / "python"
    subprocess.run([str(py if py.exists() else sys.executable), str(BASE / "zreport.py"), str(out)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pdf = out.with_suffix(".pdf")
    token = send.read_secret("zhdusha_bot")
    ok = send.send(str(uid), pdf if pdf.exists() else out, token)
    print(f"{'Отправлено' if ok else 'Не отправлено'}: {(pdf if pdf.exists() else out).name}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    run(sys.argv[1], json.loads(sys.argv[2]))
