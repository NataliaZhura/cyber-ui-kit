#!/usr/bin/env python3
"""Добавляет в правила Ави запасной путь: кончился лимит Checko → справка и сравнение по 1С:Контрагент.

  python3 limit_rule.py [путь к AGENTS.md]     по умолчанию ~/.openclaw/workspace/AGENTS.md (копия .bak-<дата>)
Повторный запуск ничего не дублирует.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

MARK = "**Лимит Checko кончился**"
RULE = ("5. **Лимит Checko кончился** (ответ «Превышен суточный лимит», HTTP 403) — не останавливайся: справку делай\n"
        "   по отчёту 1С (п. 2), сравнение (`/compare`) — по двум отчётам 1С рядом в одной таблице; поиск компании\n"
        "   `pick.py` сам переводит на 1С. В справке одной строкой: «данные: 1С:Контрагент». Про лимит пользователю не пиши.\n")
ANCHOR = "\n### Как отдавать справку"

src = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / ".openclaw" / "workspace" / "AGENTS.md"
text = src.read_text(encoding="utf-8")
if MARK in text:
    sys.exit(f"Уже есть: {src} — {len(text)} знаков")
if ANCHOR not in text:
    sys.exit(f"СТОП: не нашёл «{ANCHOR.strip()}» в {src} — ничего не изменено")
shutil.copy2(src, src.with_name(f"AGENTS.md.bak-{datetime.now():%Y%m%d-%H%M%S}"))
text = text.replace(ANCHOR, RULE + ANCHOR, 1)
src.write_text(text, encoding="utf-8")
print(f"Добавлено: {src} — {len(text)} знаков (лимит 20000)")
