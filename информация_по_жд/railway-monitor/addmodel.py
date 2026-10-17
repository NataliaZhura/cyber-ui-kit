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
        row = ("| `/model` | «пришлите Excel-модель» (или «демо» — `excel_tester/in/demo_model.xlsx`) | проверка по навыкам "
               "`excel` и `model-stress`: ошибки в файле, поток на обслуживание долга, покрытие платежей по годам, "
               "стресс-сценарии, где модель пробивает → Excel с расчётом + PDF |\n")
        i = t.find("| `/find`")
        shutil.copy2(md, md.with_name(f"MENU.md.bak-model-{stamp}"))
        md.write_text(t[:i] + row + t[i:] if i >= 0 else t + row, encoding="utf-8")
        print("MENU.md: строка /model добавлена")
subprocess.run(["python3", str(menu)], check=False)
