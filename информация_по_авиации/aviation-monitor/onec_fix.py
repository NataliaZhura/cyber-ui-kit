#!/usr/bin/env python3
"""Правка входа в 1С:Контрагент: поле логина — первое видимое и доступное (а не первое попавшееся).
  python3 onec_fix.py      копия onec.py.bak-<дата>; повторный запуск ничего не дублирует
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

P = Path(__file__).resolve().parent / "onec.py"
s = P.read_text(encoding="utf-8")
if "_visible_enabled" in s:
    sys.exit("Уже исправлено")
OLD = '''        user = page.query_selector("input[name=login], input[type=email], input[name*=user i], "
                                   "input[name*=mail i], input[type=text], input:not([type])")
'''
NEW = '''        cands = page.query_selector_all("input[name=login], input[type=email], input[name*=user i], "
                                        "input[name*=mail i], input[type=tel], input[type=text], input:not([type])")
        user = next((e for e in cands if e.is_visible() and e.is_enabled()), None)  # _visible_enabled
'''
if OLD not in s:
    sys.exit("СТОП: onec.py на сервере отличается от ожидаемого — ничего не изменено")
shutil.copy2(P, P.with_name(f"onec.py.bak-{datetime.now():%Y%m%d-%H%M%S}"))
P.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("Готово: вход 1С берёт видимое доступное поле логина")
