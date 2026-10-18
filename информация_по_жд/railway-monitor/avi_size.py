#!/usr/bin/env python3
"""Только смотрит: длина правил Ави (лимит OpenClaw — 20 000 знаков, хвост сверх лимита бот не видит) и размер разделов.
  python3 ~/railway-monitor/avi_size.py
"""
from pathlib import Path

OC = Path.home() / ".openclaw"
for name in ("workspace", "workspace-tester"):
    p = OC / name / "AGENTS.md"
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    warn = ("  ⚠ БОЛЬШЕ ЛИМИТА — конец правил бот не видит" if len(t) > 20000
            else f"  ⚠ запас до лимита {20000 - len(t)} знаков — пора выносить разделы" if len(t) > 18000 else "")
    print(f"== {p}: {len(t)} знаков" + warn)
    pos = [i for i in range(len(t)) if t.startswith("\n## ", i)] + [len(t)]
    head = t[:pos[0]]
    print(f"   {len(head):6d}  (начало до первого раздела)")
    for a, b in zip(pos, pos[1:]):
        title = t[a + 1:t.find("\n", a + 1)]
        print(f"   {b - a:6d}  {title[:80]}")
