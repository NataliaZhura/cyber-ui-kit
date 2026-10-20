#!/usr/bin/env python3
"""Подменю /model, /flighthour, /bpla — правило ВЫСОКО в AGENTS.md: на команду без уточнений бот отправляет подменю
дословно из guides/menus.md и ждёт цифру (а не отвечает сразу). Правка по меткам, с копией в bak/.

  python3 patch_menus.py                [--agents <AGENTS.md>]   показать, что изменится
  python3 patch_menus.py --apply        [--agents <AGENTS.md>]   применить
Повторный запуск ничего не ломает.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
AGENTS = Path(sys.argv[sys.argv.index("--agents") + 1]).expanduser() if "--agents" in sys.argv \
    else Path.home() / ".openclaw" / "workspace" / "AGENTS.md"
MARK = "**Подменю (/model, /flighthour, /bpla).**"
RULE = (MARK + " Команда `/model`, `/flighthour` или `/bpla` без уточнений (и Excel-файл без вопроса — как `/model`) —\n"
        "ответь **только** текстом подменю этой команды из `~/aviation-monitor/guides/menus.md` (между линиями «---»)\n"
        "**дословно**, ничего не запуская, не считая и не добавляя от себя. Затем жди цифру; после выбора — по строке\n"
        "«Дальше» того же раздела. Не отвечай на подменю готовым анализом: выбирает пользователь.\n\n")
ANCHORS = ("**Перед ответом на любую команду меню**", "## Меню бота", "## Что ты делаешь и когда")


def main():
    if not AGENTS.exists():
        sys.exit(f"Нет {AGENTS}")
    if not (BASE / "guides" / "menus.md").exists():
        sys.exit("Нет guides/menus.md — скачай его вместе с программой.")
    t = AGENTS.read_text(encoding="utf-8")
    if MARK in t:
        print("AGENTS.md: правило подменю уже есть — менять нечего")
        return
    a = next((x for x in ANCHORS if x in t), None)
    if a is None:
        print("Метка не найдена — правило будет в начале файла, после первого заголовка")
        k = t.find("\n## ")
        new = t[:k + 1] + RULE + t[k + 1:] if k >= 0 else RULE + t
    else:
        i = t.index(a)
        if a.startswith("## "):      # после строки заголовка
            j = t.index("\n", i) + 1
            new = t[:j] + "\n" + RULE + t[j:]
        else:                        # перед абзацем «Перед ответом на любую команду меню»
            new = t[:i] + RULE + t[i:]
        print(f"Вставлю правило подменю у метки «{a}»")
    if "--apply" not in sys.argv:
        print("Это предпросмотр. Применить: добавь --apply")
        return
    (BASE / "bak").mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    shutil.copy2(AGENTS, BASE / "bak" / f"{AGENTS.parent.name}-AGENTS-before-menus-{stamp}.md")
    AGENTS.write_text(new, encoding="utf-8")
    print(f"Готово. Копия: bak/{AGENTS.parent.name}-AGENTS-before-menus-{stamp}.md")


if __name__ == "__main__":
    main()
