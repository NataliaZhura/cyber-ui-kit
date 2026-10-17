#!/usr/bin/env python3
"""Компании БАС и «риск замещения беспилотниками» — правка ТЕКУЩИХ файлов на сервере, без замены целиком.

  python3 patch_bas.py            показать, что изменится
  python3 patch_bas.py --apply    применить (копии прежних файлов — в bak/)

1. AGENTS.md: рабочий список компаний БАС (focus_bas.csv) наравне с focus.csv; вопросы о рынке БПЛА — сначала
   опорная справка guides/bpla-market.md.
2. guides/company-report.md: в справке по вертолётной компании — строка «Риск замещения беспилотниками».
Повторный запуск ничего не ломает.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
AGENTS = Path.home() / ".openclaw" / "workspace" / "AGENTS.md"
GUIDE = BASE / "guides" / "company-report.md"

FOCUS_OLD = "- Рабочий список — `~/aviation-monitor/focus.csv` (11 компаний в тесте). Для них — все источники ниже.\n"
FOCUS_NEW = ("- Рабочий список — `~/aviation-monitor/focus.csv` (11 компаний в тесте) и `~/aviation-monitor/focus_bas.csv`\n"
             "  (компании беспилотной отрасли, БАС). Для них — все источники ниже.\n")
MARKET = """
## Рынок БПЛА и низковысотной авиации

Вопрос о рынке беспилотников, низковысотной или малой авиации — **сначала прочитай** `~/aviation-monitor/guides/bpla-market.md`
(опорная справка на 16.10.2026: размер рынка, нацпроект, госзаказ, спрос по отраслям, дрон против вертолёта, правила,
риски, сценарии до 2030). Цифры бери оттуда с датой; если данным больше 3 месяцев — проверь свежие новости раздела
«БПЛА и низковысотная авиация» и скажи, что изменилось. Источники в ответе — словом «ссылка».
"""
MARKET_BEFORE = "## Отраслевые материалы и оценка"
GUIDE_AFTER = "    рост выручки, диверсификация заказчиков, платёжная дисциплина — только подтверждённое данными).\n"
GUIDE_ADD = ("    **Вертолётная компания — строка «Риск замещения беспилотниками»** (по `guides/bpla-market.md`, раздел 5):\n"
             "    облёт трубопроводов и ЛЭП, аэрофотосъёмка — высокий; авиахимработы, лесоохрана — средний; перевозки людей,\n"
             "    санавиация, внешняя подвеска, тяжёлые грузы — нет. Есть разбивка выручки по видам работ — оцени долю\n"
             "    выручки под риском; нет — так и напиши и добавь в «Чего не хватает»: «выручка по видам работ».\n")


def main():
    apply = "--apply" in sys.argv
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    changes = []
    if AGENTS.exists():
        t = AGENTS.read_text(encoding="utf-8")
        new = t
        if "focus_bas.csv" in new:
            print("AGENTS.md: список БАС уже есть — пропускаю")
        elif FOCUS_OLD in new:
            new = new.replace(FOCUS_OLD, FOCUS_NEW)
        else:
            print("AGENTS.md: строка про рабочий список не найдена — пропускаю (пришли вывод, поправлю вручную)")
        if "guides/bpla-market.md" in new:
            print("AGENTS.md: раздел о рынке БПЛА уже есть — пропускаю")
        elif MARKET_BEFORE in new:
            new = new.replace(MARKET_BEFORE, MARKET.lstrip("\n") + "\n" + MARKET_BEFORE, 1)
        else:
            new = new.rstrip("\n") + "\n" + MARKET
        if new != t:
            changes.append((AGENTS, new, "AGENTS.md: список компаний БАС + опорная справка о рынке БПЛА"))
    else:
        print(f"Нет {AGENTS}")
    if GUIDE.exists():
        g = GUIDE.read_text(encoding="utf-8")
        if "Риск замещения беспилотниками" in g:
            print("guides/company-report.md: строка уже есть — пропускаю")
        elif GUIDE_AFTER in g:
            changes.append((GUIDE, g.replace(GUIDE_AFTER, GUIDE_AFTER + GUIDE_ADD), "guides/company-report.md: риск замещения"))
        else:
            print("guides/company-report.md: место для вставки не найдено — пропускаю")
    else:
        print("Нет guides/company-report.md — сначала python3 slim.py ~/.openclaw/workspace/AGENTS.md --relay --apply")
    if not (BASE / "guides" / "bpla-market.md").exists():
        print("⚠ Нет guides/bpla-market.md — загрузи справку о рынке (команда scp в сообщении)")
    if not changes:
        print("Менять нечего.")
        return
    for _, _, msg in changes:
        print("•", msg)
    if not apply:
        print("Это предпросмотр. Применить: python3 patch_bas.py --apply")
        return
    (BASE / "bak").mkdir(exist_ok=True)
    for path, text, _ in changes:
        shutil.copy2(path, BASE / "bak" / f"{path.stem}-before-bas-{stamp}{path.suffix}")
        path.write_text(text, encoding="utf-8")
    print(f"Готово. Копии прежних файлов: bak/*-before-bas-{stamp}.*")


if __name__ == "__main__":
    main()
