#!/usr/bin/env python3
"""Блок «Экономия шагов» в правила Ави и тестировщика (~/.openclaw/workspace*/AGENTS.md) — перед разделом «Меню бота».
Повторный запуск ничего не дублирует. Перед правкой — копия AGENTS.md.bak-steps-<дата>. Больше 19 900 знаков — не пишет.
  python3 steps_rules.py          показать, что будет (ничего не меняет)
  python3 steps_rules.py --apply  вписать
Блок тот же, что в правилах ЖДуши (AGENTS.md комплекта).
"""
import re
import shutil
import sys
from datetime import date
from pathlib import Path

KIT = Path(__file__).resolve().parent
OC = Path.home() / ".openclaw"
LIMIT = 19900
m = re.search(r"## Экономия шагов.*?(?=\n## )", (KIT / "AGENTS.md").read_text(encoding="utf-8"), re.S)
if not m:
    sys.exit("В AGENTS.md комплекта нет блока «Экономия шагов» — сначала обнови комплект.")
BLOCK = m.group(0).rstrip() + "\n\n"
for name in ("workspace", "workspace-tester"):
    p = OC / name / "AGENTS.md"
    if not p.exists():
        print(f"{name}: нет AGENTS.md — пропуск")
        continue
    t = p.read_text(encoding="utf-8")
    if "## Экономия шагов" in t:
        print(f"{name}: блок уже есть ({len(t)} знаков)")
        continue
    pos = t.find("\n## Меню бота")
    pos = pos + 1 if pos >= 0 else t.find("\n## ") + 1
    new = t[:pos] + BLOCK + t[pos:]
    if len(new) > LIMIT:
        print(f"{name}: СТОП — стало бы {len(new)} знаков (лимит {LIMIT}); не меняю")
        continue
    if "--apply" in sys.argv:
        shutil.copy2(p, p.with_name(f"AGENTS.md.bak-steps-{date.today()}"))
        p.write_text(new, encoding="utf-8")
        print(f"{name}: вписано, {len(t)} → {len(new)} знаков (копия — AGENTS.md.bak-steps-{date.today()})")
    else:
        print(f"{name}: будет {len(t)} → {len(new)} знаков (запусти с --apply)")
