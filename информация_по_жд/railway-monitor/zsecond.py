#!/usr/bin/env python3
"""«Второе мнение GPT» по рынку вагонов: пакет данных (программа, 0 токенов) → задача ЖДуше на GPT → ответ PDF владельцу →
прогноз GPT в журнал рядом с нашим (через 2–3 месяца видно, чей точнее).

  python3 zsecond.py pack                  только собрать пакет: saved/second/ГГГГ-ММ-ДД_пакет.md
  python3 zsecond.py run                   пакет + задача ЖДуше (GPT); ответ придёт в чат через несколько минут
  python3 zsecond.py record [файл.md]      прогнозы GPT из ответа (строки «ПРОГНОЗ|…») → forecast/gpt_journal.csv
  python3 zsecond.py score                 прогнозы GPT против факта: угадано ли направление

Задача ставится тем же способом, что «Поставить задачу» в мини-приложении (miniapp.json → task_cmd). Нет настройки —
программа печатает текст задачи, его можно вставить в чат с ЖДушей.
"""
import csv
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
OUT = BASE / "saved" / "second"
JOURNAL = BASE / "forecast" / "gpt_journal.csv"
TYPES = ["inno", "gon", "kr158", "hop_grain", "fit80"]
LIMIT = 45000  # знаков в пакете — чтобы не тратить лимит GPT


def owner():
    p = Path.home() / ".secrets" / "zhdusha_owner"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def pack():
    import zreports
    import zretro
    import zdeal
    d = date.today().isoformat()
    L = [f"# Пакет для второго мнения — {d}", "",
         "Данные рынка — только для внутреннего использования. Ставки — ₽/сут без НДС, середина диапазона рынка за месяц.", ""]
    issues = sorted(p for p in (BASE / "saved" / "market").glob("*_обзор_рынка_вагонов.md"))
    if issues:
        txt = issues[-1].read_text(encoding="utf-8")
        txt = txt[:txt.find("## Методика")] if "## Методика" in txt else txt
        L += ["## А. Обзор рынка (последний выпуск)", "", txt[:14000], ""]
    S = zretro.data()
    for w in TYPES:
        nm = zretro.NAMES[w]
        L += [f"## Б. {nm}", ""]
        try:
            md = zreports.model_md(w, "base", False)
            L += [zreports.pick(md, ("Коротко",), f"{nm}: прогноз").split("## Коротко", 1)[-1].strip()[:2500], ""]
        except (SystemExit, Exception) as e:  # noqa: BLE001
            L += [f"(прогноз недоступен: {type(e).__name__})", ""]
        r = S.get(zretro.RATE[w], {})
        if r:
            L += ["Ставка по месяцам: " + "; ".join(f"{m} {round(v)}" for m, v in sorted(r.items())[-21:]), ""]
        L += ["Обвал 2025 г. и восстановление:"] + [x for x in zretro.collapse_md(w, S) if x.startswith(("Пик", "|", "**"))][:22] + [""]
        top25 = [f"{x[0]} ({x[1]:+.2f})" for x in zretro.drivers(w, 2025, S)[:4]]
        top26 = [f"{x[0]} ({x[1]:+.2f})" for x in zretro.drivers(w, 2026, S)[:4]]
        L += [f"Связь изменения ставки с показателями (корреляция): 2025 — {', '.join(top25)}; 2026 — {', '.join(top26)}.", ""]
        try:
            dd = zdeal.deal(w, "base")
            L += [f"Сделка (лизинг 20 лет, ключевая + 3,5 п.п.): цена {dd['price']:.2f} млн ₽, предельная {dd['maxp']:.2f}, "
                  f"доходность {dd['irr'] or 0:.1f}%, окупаемость {dd['payback']}, аренда не покрывает платёж: "
                  f"{', '.join(map(str, dd['neg'][:4])) or 'нет'}.", ""]
        except (SystemExit, Exception):  # noqa: BLE001
            pass
    try:
        import zfactors
        L += ["## В. Факторы и открытые данные (сокращённо)", ""] + [x for x in zfactors.md("inno") if x.startswith("|")][:20]
    except Exception:  # noqa: BLE001
        pass
    text = "\n".join(L)[:LIMIT]
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{d}_пакет.md"
    p.write_text(text, encoding="utf-8")
    print(f"Пакет: {p} ({len(text):,} знаков)".replace(",", " "))
    return p


TASK = """Режим «второе мнение» (не обычный ответ на команду). Прочитай файл {pack} — там наш обзор рынка вагонов, прогнозы
моделей, ставки по месяцам, разбор обвала 2025 г. и расчёт сделки по 5 типам вагонов. Ты — независимый аналитик: можешь не
соглашаться с нашими моделями. Цифры — только из пакета или из открытого источника со ссылкой; не выдумывай.
Напиши ответ в файл {answer} строго по разделам:
1. С чем не согласен в наших прогнозах и выводах — по каждому типу, со ссылкой на цифры пакета.
2. Какие факторы и риски не учтены.
3. Свой прогноз — по одной строке на тип, ровно в таком виде (без пробелов вокруг «|»):
ПРОГНОЗ|<тип: inno, gon, kr158, hop_grain, fit80>|3м|<рост, снижение или без изменений>|<мин ₽/сут>|<макс ₽/сут>|<почему, коротко>
ПРОГНОЗ|<тип>|2027|<рост, снижение или без изменений>|<мин>|<макс>|<почему>
(3м — средняя ставка через 3 месяца от последнего месяца данных; 2027 — средняя за 2027 г.)
4. Что проверить в данных.
Потом: ~/pw/bin/python ~/railway-monitor/zreport.py {answer} и python3 ~/railway-monitor/send.py {pdf}; затем
python3 ~/railway-monitor/zsecond.py record {answer}. В чат — 3–5 строк главного и «Полный разбор — в PDF»."""


def run():
    p = pack()
    ans = OUT / f"{date.today().isoformat()}_второе_мнение.md"
    task = TASK.format(pack=p, answer=ans, pdf=ans.with_suffix(".pdf")).replace("\n", " ")
    cfg = BASE / "miniapp.json"
    cmd = json.loads(cfg.read_text(encoding="utf-8")).get("task_cmd") if cfg.exists() else None
    if not cmd or not owner():
        print("Нет настройки отправки задач (miniapp.json) — вставь в чат с ЖДушей этот текст:\n\n" + task)
        return
    sid = f"second-{date.today().strftime('%Y%m%d')}"
    args = [a.replace("{agent}", "zhdusha").replace("{to}", owner()).replace("{text}", task).replace("{session}", sid) for a in cmd]
    log = (BASE / "saved" / "task.log").open("a", encoding="utf-8")
    log.write(f"\n{date.today()} второе мнение: {p}\n")
    log.flush()
    subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    print("Задача поставлена ЖДуше (GPT). Ответ и PDF придут в чат через 5–15 минут; журнал — saved/task.log")


def record(path=None):
    if not path:
        files = sorted(OUT.glob("*_второе_мнение.md"))
        if not files:
            sys.exit("Нет ответа второго мнения в saved/second/")
        path = files[-1]
    text = Path(path).read_text(encoding="utf-8")
    import zretro
    S = zretro.data()
    made = max(S.get("gon75_spot", {"": 0}))
    rows = []
    for m in re.finditer(r"ПРОГНОЗ\|(\w+)\|(3м|2027)\|([^|]+)\|([\d\s]+)\|([\d\s]+)\|([^\n]*)", text):
        w, hz, dr, lo, hi, why = m.groups()
        rows.append({"made": made, "wagon": w, "horizon": hz, "dir": dr.strip(), "low": lo.replace(" ", ""),
                     "high": hi.replace(" ", ""), "why": why.strip()[:200], "file": Path(path).name})
    if not rows:
        sys.exit("В ответе нет строк «ПРОГНОЗ|…» — попроси ЖДушу дописать раздел 3 по шаблону.")
    old = []
    if JOURNAL.exists():
        with JOURNAL.open(encoding="utf-8") as f:
            old = [r for r in csv.DictReader(f, delimiter=";") if r["made"] != made]
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, list(rows[0]), delimiter=";")
        wr.writeheader()
        wr.writerows(old + rows)
    print(f"Прогнозы GPT записаны: {len(rows)} (данные на {made}) → {JOURNAL}")


def score():
    import zretro
    import zobs
    if not JOURNAL.exists():
        sys.exit("Журнал второго мнения пуст: сначала run, затем record.")
    S = zretro.data()
    with JOURNAL.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f, delimiter=";") if r["horizon"] == "3м"]
    for r in rows:
        d = S.get(zretro.RATE.get(r["wagon"], ""), {})
        tgt = zobs.shift(r["made"], 3)
        if tgt not in d or r["made"] not in d:
            print(f"{r['made']} {r['wagon']}: факт за {tgt} ещё не известен")
            continue
        f, base = d[tgt], d[r["made"]]
        fact = "рост" if f > base * 1.02 else "снижение" if f < base * 0.98 else "без изменений"
        inside = float(r["low"]) <= f <= float(r["high"])
        print(f"{r['made']} {r['wagon']}: GPT — {r['dir']} ({r['low']}–{r['high']}), факт — {fact} ({round(f)}); "
              f"направление {'угадано' if fact in r['dir'] else 'нет'}, в диапазоне — {'да' if inside else 'нет'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pack":
        pack()
    elif cmd == "run":
        run()
    elif cmd == "record":
        record(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "score":
        score()
    else:
        sys.exit(__doc__)
