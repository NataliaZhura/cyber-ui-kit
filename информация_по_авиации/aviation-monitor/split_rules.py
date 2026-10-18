#!/usr/bin/env python3
"""Укладывает правила Ави в лимит OpenClaw (20 000 знаков): три справочных раздела — в отдельные файлы.

  python3 split_rules.py [путь к AGENTS.md]     по умолчанию ~/.openclaw/workspace/AGENTS.md

«Меню бота» → ~/aviation-monitor/MENU.md, «Новости: что влияет на устойчивость компании» → SIGNALS.md,
«Рынок БПЛА и низковысотной авиации» → BPLA.md; в AGENTS.md вместо них — короткие ссылки.
Перед заменой — копия AGENTS.md.bak-<дата>. Уже вынесенный раздел пропускается, его файл не перезаписывается.
Правила тестировщика после этого пересобрать: bash tester/setup.sh <ID> (в них — копия правил Ави).
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
    "## Рынок БПЛА": ("BPLA.md", """## Рынок БПЛА и низковысотной авиации

Вопрос, новость или справка про БПЛА, беспилотные системы, низковысотную авиацию — сначала прочитай
`~/aviation-monitor/BPLA.md`: что отслеживать, источники, как оценивать.

"""),
}


def main():
    src = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / ".openclaw" / "workspace" / "AGENTS.md"
    text = src.read_text(encoding="utf-8")
    before = len(text)
    todo = {h: v for h, v in SECTIONS.items() if f"`~/aviation-monitor/{v[0]}`" not in text}
    if not todo:
        print(f"Уже разделено: {src} — {before} знаков")
        return
    missing = [h for h in todo if h not in text]
    if missing:
        sys.exit("СТОП: не нашёл раздел " + ", ".join(f"«{h}»" for h in missing) + " — ничего не изменено")
    bak = src.with_name(f"AGENTS.md.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(src, bak)
    for head, (fname, stub) in todo.items():
        i = text.find(head)
        j = text.find("\n## ", i + 5)
        j = len(text) if j < 0 else j + 1
        (AM / fname).write_text("# Справка для Ави (читать по ссылке из AGENTS.md)\n\n" + text[i:j], encoding="utf-8")
        text = text[:i] + stub + text[j:]
    src.write_text(text, encoding="utf-8")
    print(f"Копия: {bak}\n{src}: было {before}, стало {len(text)} знаков (лимит 20000)")
    print("Вынесено:", ", ".join(str(AM / todo[h][0]) for h in todo))


if __name__ == "__main__":
    main()
