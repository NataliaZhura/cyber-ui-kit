#!/usr/bin/env python3
"""Ави: ссылки — только рабочим словом ССЫЛКА. Правит AGENTS.md и TEMPLATE.md на месте (копии .bak-<дата>).
  python3 link_rule.py [папка с правилами]     по умолчанию ~/.openclaw/workspace ; повтор ничего не дублирует
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

d = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / ".openclaw" / "workspace"
RULE = ("- **Ссылка — только рабочим словом `[ССЫЛКА](https://…)`** в конце пункта (кликабельно). Не писать голый адрес, "
        "длинную строку ссылок, название источника вместо ссылки или слово «ссылка» без адреса. Нет адреса — не ставить ничего.")
EDITS = {
    "AGENTS.md": [("- Ссылка — одним словом в конце пункта: `[ссылка](https://…)`. Голый длинный адрес не вставляй.", RULE),
                  ("ссылки — только словом: `[ссылка](https://…)`", "ссылки — только рабочим словом `[ССЫЛКА](https://…)`")],
    "TEMPLATE.md": [("— дата, источник, ссылка;", "— дата, [ССЫЛКА](адрес);")],
}
for name, pairs in EDITS.items():
    p = d / name
    if not p.exists():
        print(f"нет {p}")
        continue
    s = p.read_text(encoding="utf-8")
    new = s
    for old, rep in pairs:
        new = new.replace(old, rep)
    if new == s:
        print(f"{name}: уже исправлено или текст другой" + (" (ССЫЛКА уже есть)" if "ССЫЛКА" in s else " — пришли: grep -n ссылк " + str(p)))
        continue
    shutil.copy2(p, p.with_name(f"{name}.bak-{datetime.now():%Y%m%d-%H%M%S}"))
    p.write_text(new, encoding="utf-8")
    print(f"{name}: ссылки → ССЫЛКА ({len(new)} знаков)")
