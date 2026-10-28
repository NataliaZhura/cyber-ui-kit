#!/usr/bin/env python3
"""Поправки сценариев по сверке с рынком — поверх данных модели. Файл forecast/scen_fix.json (только на сервере).

  {"rate": {"base": {"stroy": {"2027": -5}}, "opt": {"off": {"2027": "+15"}}},
   "kr":   {"base": {"stroy": {"2027": -5}, "mortgage": {"2027": 20}}}}
  "rate" — полувагоны (zrate.py), "kr" — крытые (zmodel.py / ztypes.py); число — новое значение, «+15» / «−5» — прибавка.

  python3 zfix.py show          что действует
  ZFIX_OFF=1 python3 …          расчёт без поправок (для сравнения «было — стало»)
"""
import json
import os
import sys
from pathlib import Path

FILE = Path(__file__).resolve().parent / "forecast" / "scen_fix.json"


def rules():
    if os.environ.get("ZFIX_OFF") or not FILE.exists():
        return {}
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def val(old, new):
    s = str(new).replace("−", "-")
    return float(old) + float(s) if s[:1] in "+-" and isinstance(new, str) else float(new)


def apply(D, model, y0):
    """D["scenarios"][сценарий][фактор][год − y0] ← поправка. y0: 2026 у zrate (индекс 0 = 2026), 2025 у zmodel."""
    for sc, fs in rules().get(model, {}).items():
        for k, ys in fs.items():
            row = D.get("scenarios", {}).get(sc, {}).get(k)
            if not isinstance(row, list):
                continue
            for y, v in ys.items():
                i = int(y) - y0
                if 0 <= i < len(row):
                    row[i] = val(row[i], v)
    return D


def apply_list(s, model, sc, y0=2027):
    """Для готового списка 2027–2030 (ztypes, оптимистичный крытых задан в коде)."""
    for k, ys in rules().get(model, {}).get(sc, {}).items():
        if k in s:
            for y, v in ys.items():
                i = int(y) - y0
                if 0 <= i < len(s[k]):
                    s[k][i] = val(s[k][i], v)
    return s


if __name__ == "__main__":
    print(json.dumps(rules(), ensure_ascii=False, indent=1) if sys.argv[1:2] == ["show"] else __doc__)
