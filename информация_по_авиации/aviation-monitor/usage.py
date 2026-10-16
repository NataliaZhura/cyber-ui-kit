#!/usr/bin/env python3
"""Замер расхода лимита модели — без модели: раз в час записывает остаток лимита в usage.log.

  python3 usage.py log       записать текущий остаток (запускается расписанием-командой раз в час)
  python3 usage.py show      таблица за последние сутки: сколько процентов ушло за каждый час

Источник — `openclaw models status --agent main` (строка «usage: 5h 99% left · Week 100% left»).
Лимит общий на всех агентов, поэтому по часам видно, какие запуски по расписанию его съедают.
"""
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent / "usage.log"


def cmd_log():
    out = subprocess.run(["openclaw", "models", "status", "--agent", "main"],
                         capture_output=True, text=True, timeout=120).stdout
    m = re.search(r"usage:\s*5h\s+(\d+)%\s*left.*?Week\s+(\d+)%\s*left", out, re.S)
    if not m:
        sys.exit("Не нашёл строку usage в выводе openclaw models status")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M};{m[1]};{m[2]}\n")
    print(f"5 ч: осталось {m[1]}%, неделя: осталось {m[2]}%")


def cmd_show():
    rows = [ln.strip().split(";") for ln in LOG.read_text(encoding="utf-8").splitlines()[-25:]] if LOG.exists() else []
    if len(rows) < 2:
        sys.exit("Мало замеров — нужно хотя бы два часа записей")
    print("время              5 ч, осталось   неделя, осталось   недели ушло за час")
    for prev, cur in zip(rows, rows[1:]):
        spent = int(prev[2]) - int(cur[2])
        print(f"{cur[0]}   {cur[1]:>6}%         {cur[2]:>6}%            {f'{spent}%' if spent >= 0 else 'обновился'}")


if __name__ == "__main__":
    {"log": cmd_log, "show": cmd_show}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
