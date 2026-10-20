#!/usr/bin/env python3
"""Прогноз рынка (/forecast) — правка ТЕКУЩЕГО AGENTS.md по меткам, с копией в bak/.

  python3 patch_market.py [--agents <AGENTS.md>] [--apply]
Повторный запуск ничего не ломает.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
AGENTS = Path(sys.argv[sys.argv.index("--agents") + 1]).expanduser() if "--agents" in sys.argv \
    else Path.home() / ".openclaw" / "workspace" / "AGENTS.md"
MARK = "## Прогноз рынка авиации"
SECTION = """
## Прогноз рынка авиации

Прогноз рынка самолётов и вертолётов до 2030 года с учётом новостей — команда `/forecast` и вопросы «что будет с
рынком», «прогноз», «перспективы отрасли». **Сначала прочитай целиком** `~/aviation-monitor/guides/market-forecast.md`
и действуй по нему; расчёт — только программой `market.py`. Новость с цифрой, меняющей допущение прогноза, —
предложи владельцу поправку (порядок — в том же файле).
"""
BEFORE = "## Отраслевые материалы и оценка"
GREET_AFTERS = ("• /flighthour — 🆕 лётный час: из чего складывается, цены в контрактах, прогноз, расчёт ставки\n",
                "• /bpla — 🆕 беспилотники: новости, рынок до 2030, компании БАС, риск замещения вертолётов\n")
GREET = "• /forecast — 🆕 прогноз рынка самолётов и вертолётов до 2030 года и что может его изменить\n"


def main():
    if not AGENTS.exists():
        sys.exit(f"Нет {AGENTS}")
    t = AGENTS.read_text(encoding="utf-8")
    if MARK in t:
        print("AGENTS.md: раздел прогноза уже есть — менять нечего")
        return
    new = t.replace(BEFORE, SECTION.lstrip("\n") + "\n" + BEFORE, 1) if BEFORE in t else t.rstrip("\n") + "\n" + SECTION
    ga = next((g for g in GREET_AFTERS if g in new), None)
    if ga:
        new = new.replace(ga, ga + GREET, 1)
    else:
        print("Приветствие с /flighthour или /bpla не найдено — строку /forecast в приветствие не добавила")
    print(f"• {AGENTS}: раздел «Прогноз рынка авиации»" + (", строка в приветствии" if ga else ""))
    if "--apply" not in sys.argv:
        print("Это предпросмотр. Применить: добавь --apply")
        return
    (BASE / "bak").mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    shutil.copy2(AGENTS, BASE / "bak" / f"{AGENTS.parent.name}-AGENTS-before-market-{stamp}.md")
    AGENTS.write_text(new, encoding="utf-8")
    print(f"Готово. Копия: bak/{AGENTS.parent.name}-AGENTS-before-market-{stamp}.md")


if __name__ == "__main__":
    main()
