#!/usr/bin/env python3
"""Лётный час (/flighthour) — правка ТЕКУЩЕГО AGENTS.md по меткам.

  python3 patch_fh.py                 показать, что изменится (Ави)
  python3 patch_fh.py --apply         применить (копия прежнего файла — в bak/)
  python3 patch_fh.py --agents ~/.openclaw/workspace-tester/AGENTS.md [--apply]   то же для тестера
Повторный запуск ничего не ломает.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
AGENTS = Path(sys.argv[sys.argv.index("--agents") + 1]).expanduser() if "--agents" in sys.argv \
    else Path.home() / ".openclaw" / "workspace" / "AGENTS.md"
MARK = "## Лётный час"
SECTION = """
## Лётный час

Себестоимость лётного часа, цены часа в госконтрактах, «ножницы», светофор, прогноз до 2030 года и калькулятор
сделки (окупает ли тариф, минимальная ставка для DSCR, справедливая ставка) — команда `/flighthour` и любые вопросы
о стоимости часа. **Сначала прочитай целиком** `~/aviation-monitor/guides/flight-hour.md` и действуй по нему; расчёт —
только программой `fh.py`. В «Итоги недели» — строка светофора лётного часа (`python3 fh.py index --short`).
"""
BEFORE = "## Отраслевые материалы и оценка"
ROW_PREFIXES = ("| `/model` |", "| `/bpla` |", "| `/compare` |")
ROW = "| `/flighthour` | пункт подменю (guides/flight-hour.md) | себестоимость лётного часа, цены, прогноз, калькулятор ставки |\n"
GREET_AFTER = "• /bpla — 🆕 беспилотники: новости, рынок до 2030, компании БАС, риск замещения вертолётов\n"
GREET = "• /flighthour — 🆕 лётный час: из чего складывается, цены в контрактах, прогноз, расчёт ставки\n"


def main():
    if not AGENTS.exists():
        sys.exit(f"Нет {AGENTS}")
    t = AGENTS.read_text(encoding="utf-8")
    new = t
    if MARK in new:
        print("AGENTS.md: раздел «Лётный час» уже есть — пропускаю")
    else:
        new = new.replace(BEFORE, SECTION.lstrip("\n") + "\n" + BEFORE, 1) if BEFORE in new \
            else new.rstrip("\n") + "\n" + SECTION
        row = next((l for p in ROW_PREFIXES for l in new.splitlines(keepends=True) if l.startswith(p)), None)
        if row:
            new = new.replace(row, row + ROW, 1)
        else:
            print("AGENTS.md: таблица меню не найдена — строку /flighthour в таблицу не добавила")
        if GREET_AFTER in new:
            new = new.replace(GREET_AFTER, GREET_AFTER + GREET, 1)
        else:
            print("AGENTS.md: строка /bpla в приветствии не найдена — приветствие не меняю")
    if new == t:
        print("Менять нечего.")
        return
    print(f"• {AGENTS}: раздел «Лётный час», строка меню /flighthour, строка в приветствии")
    if "--apply" not in sys.argv:
        print("Это предпросмотр. Применить: добавь --apply")
        return
    (BASE / "bak").mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    shutil.copy2(AGENTS, BASE / "bak" / f"{AGENTS.parent.name}-AGENTS-before-fh-{stamp}.md")
    AGENTS.write_text(new, encoding="utf-8")
    print(f"Готово. Копия: bak/{AGENTS.parent.name}-AGENTS-before-fh-{stamp}.md")


if __name__ == "__main__":
    main()
