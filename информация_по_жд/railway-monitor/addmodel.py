#!/usr/bin/env python3
"""Кнопка «/model — проверить финмодель (Excel)» в меню Ави. Правит серверные menu.py и MENU.md на месте
(копии .bak-model), остальное меню Ави не трогает; повторный запуск ничего не дублирует.
  python3 ~/railway-monitor/addmodel.py
"""
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

AM = Path.home() / "aviation-monitor"
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
menu = AM / "menu.py"
s = menu.read_text(encoding="utf-8")
if '("model",' in s:
    print("menu.py: /model уже есть")
else:
    m = re.search(r'\("find", "[^"]*"\), ', s) or re.search(r'\("remember", "[^"]*"\)', s)
    if not m:
        raise SystemExit("СТОП: не нашла в menu.py место для /model — ничего не изменено")
    shutil.copy2(menu, menu.with_name(f"menu.py.bak-model-{stamp}"))
    item = '("model", "Проверить финмодель (Excel) и стресс-тест"), '
    s = s[:m.start()] + item + s[m.start():]
    menu.write_text(s, encoding="utf-8")
    print("menu.py: /model добавлена")
md = AM / "MENU.md"
if md.exists():
    t = md.read_text(encoding="utf-8")
    if "`/model`" in t:
        print("MENU.md: /model уже есть")
    else:
        row = ("| `/model` | только файл, если его нет («демо» — `excel_tester/in/demo_model.xlsx`) | сразу полная проверка "
               "без вопросов «что сделать» — см. «Excel» в AGENTS.md |\n")
        i = t.find("| `/find`")
        shutil.copy2(md, md.with_name(f"MENU.md.bak-model-{stamp}"))
        md.write_text(t[:i] + row + t[i:] if i >= 0 else t + row, encoding="utf-8")
        print("MENU.md: строка /model добавлена")
RULE = ("**Пришла финмодель (Excel) или `/model` — не спрашивай «что сделать»: сразу полная проверка** по навыкам "
        "`excel` и `model-stress` — ошибки и формулы (внешние ссылки — отдельной строкой: значения могли устареть), "
        "поток на обслуживание долга, DSCR и DCR по годам, стресс-сценарии (налёт, доходная ставка, топливо, ТО, курс, "
        "ключевая ставка), год, где модель пробивает → Excel с расчётом + PDF. В конце — одна строка «могу ещё: …». Это главнее меню навыка `excel` (варианты 1–4 не присылай).\n\n")
for p in (Path.home() / ".openclaw/workspace/AGENTS.md", Path.home() / ".openclaw/workspace-tester/AGENTS.md",
          AM / "AGENTS.md"):
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    if "не спрашивай «что сделать»" in t:
        print(f"{p}: правило уже есть")
        continue
    i = t.find("## Excel\n")
    if i < 0:
        print(f"{p}: нет раздела «## Excel» — пропускаю")
        continue
    j = t.find("\n", i) + 1
    j = j + 1 if t[j:j + 1] == "\n" else j
    new = t[:j] + RULE + t[j:]
    if len(new) > 19900:
        print(f"{p}: СТОП — станет {len(new)} знаков (лимит 20000), не меняю")
        continue
    shutil.copy2(p, p.with_name(f"AGENTS.md.bak-model-{stamp}"))
    p.write_text(new, encoding="utf-8")
    print(f"{p}: правило добавлено, {len(new)} знаков")
subprocess.run(["python3", str(menu)], check=False)
