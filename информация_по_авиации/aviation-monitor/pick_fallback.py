#!/usr/bin/env python3
"""Вставляет в pick.py запасной поиск по 1С:Контрагент (когда Checko недоступен). Копия pick.py.bak-<дата>.
  python3 pick_fallback.py          повторный запуск ничего не дублирует
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

P = Path(__file__).resolve().parent / "pick.py"
s = P.read_text(encoding="utf-8")
if "def onec_search" in s:
    sys.exit("Уже есть: pick.py ищет в 1С при недоступном Checko")
OLD = '''    except (Exception, SystemExit) as e:  # noqa: BLE001 — без Checko всё равно показываем свой список
        note = " (поиск по реестру сейчас недоступен — показан только ваш список)"
'''
NEW = '''    except (Exception, SystemExit) as e:  # noqa: BLE001 — Checko недоступен (чаще всего суточный лимит) → ищем в 1С
        have = {c["inn"] for c in mine if c["inn"]}
        found = [c for c in onec_search(query) if not c["inn"] or c["inn"] not in have]
        if not found:
            note = " (поиск по реестру сейчас недоступен — показан только ваш список)"
'''
FUNC = '''def onec_search(query):
    """Запасной поиск — 1С:Контрагент (onec.py find, браузер без экрана, до 2 минут). Ошибка → пустой список."""
    import subprocess
    py = Path.home() / "pw" / "bin" / "python"
    try:
        out = subprocess.run([str(py), str(BASE / "onec.py"), "find", query], capture_output=True, text=True,
                             timeout=150).stdout
    except Exception:  # noqa: BLE001
        return []
    items = []
    for ln in out.splitlines():
        m = re.match(r"\\d+ — ОГРН (\\d{13,15})(?: · ИНН (\\d{10}|\\d{12}))? · (.*)", ln.strip())
        if m:
            name = re.split(r"\\bИНН\\b|\\bОГРН\\b", m.group(3))[0].strip(" ,·") or m.group(3)[:80]
            items.append({"name": name[:120], "inn": m.group(2) or "", "ogrn": m.group(1), "src": "1С:Контрагент"})
    return items


def cmd_name(*words):'''
if OLD not in s or "def cmd_name(*words):" not in s:
    sys.exit("СТОП: pick.py на сервере отличается от ожидаемого — ничего не изменено, пришли: grep -n except pick.py")
shutil.copy2(P, P.with_name(f"pick.py.bak-{datetime.now():%Y%m%d-%H%M%S}"))
s = s.replace(OLD, NEW, 1).replace("def cmd_name(*words):", FUNC, 1)
P.write_text(s, encoding="utf-8")
print("Готово: pick.py при недоступном Checko ищет в 1С:Контрагент")
