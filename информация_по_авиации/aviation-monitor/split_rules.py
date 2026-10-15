#!/usr/bin/env python3
"""Укладывает правила Ави в лимит OpenClaw (20 000 знаков): два справочных раздела — в отдельные файлы.

  python3 split_rules.py [путь к AGENTS.md]     по умолчанию ~/.openclaw/workspace/AGENTS.md

«Меню бота» → ~/aviation-monitor/MENU.md, «Новости: что влияет на устойчивость компании» → SIGNALS.md;
в AGENTS.md вместо них — короткие ссылки. Перед заменой — копия AGENTS.md.bak-<дата>. Повторный запуск ничего не ломает.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

AM = Path.home() / "aviation-monitor"
SECTIONS = {
    "## Меню бота": ("MENU.md", """## Меню бота (кнопки команд)

**Перед ответом на любую команду меню** (`/market`, `/company`, `/compare`, `/profile`, `/finance`, `/courts`,
`/assets`, `/find`, `/scale`, `/remember`, `/save`) прочитай `~/aviation-monitor/MENU.md` — что спросить и что прислать.
Коротко: не хватает данных — **по одному вопросу**, варианты нумеруй; сначала компания, потом период.

"""),
    "## Новости: что влияет на устойчивость": ("SIGNALS.md", """## Новости: что влияет на устойчивость компании

В каждой справке — блок **«Что сильнее всего повлияет»** (3–5 новостей по силе влияния): на что именно, кого
касается, масштаб (только цифра из источника), срок. Формат и список факторов — прочитай
`~/aviation-monitor/SIGNALS.md` перед каждой справкой.

"""),
}


def main():
    src = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / ".openclaw" / "workspace" / "AGENTS.md"
    text = src.read_text(encoding="utf-8")
    before = len(text)
    if all(f"`~/aviation-monitor/{f}`" in text for f, _ in SECTIONS.values()):
        print(f"Уже разделено: {src} — {before} знаков")
        return
    bak = src.with_name(f"AGENTS.md.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(src, bak)
    for head, (fname, stub) in SECTIONS.items():
        i = text.find(head)
        if i < 0:
            sys.exit(f"СТОП: не нашёл раздел «{head}» — ничего не изменено (копия {bak.name})")
        j = text.find("\n## ", i + 5)
        j = len(text) if j < 0 else j + 1
        (AM / fname).write_text("# Справка для Ави (читать по ссылке из AGENTS.md)\n\n" + text[i:j], encoding="utf-8")
        text = text[:i] + stub + text[j:]
    src.write_text(text, encoding="utf-8")
    print(f"Копия: {bak}\n{src}: было {before}, стало {len(text)} знаков (лимит 20000)")
    print("Вынесено:", ", ".join(str(AM / f) for f, _ in SECTIONS.values()))


if __name__ == "__main__":
    main()
