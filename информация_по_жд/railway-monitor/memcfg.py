#!/usr/bin/env python3
"""Ищет в справочнике настроек OpenClaw всё про поиск по памяти (только читает).
  openclaw config schema > /tmp/schema.json; python3 memcfg.py /tmp/schema.json
"""
import json
import re
import sys

t = open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/schema.json", encoding="utf-8").read()
print(f"размер справочника: {len(t)} знаков")
KEY = re.compile(r"memorysearch|embedd|fts|vector", re.I)
hits = []


def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items():
            p = f"{path}.{k}" if path else k
            if KEY.search(k) and k not in ("description", "title"):
                desc = v.get("description", "") if isinstance(v, dict) else ""
                kind = (v.get("enum") or v.get("type") or v.get("default")) if isinstance(v, dict) else v
                hits.append(f"{p} | {str(kind)[:60]} | {str(desc)[:70]}")
            walk(v, p)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, f"{path}[{i}]")


try:
    walk(json.loads(t[t.find("{"):]), "")
except ValueError as e:
    print("справочник не JSON:", e)
for h in hits[:40]:
    print(h)
print(f"— найдено: {len(hits)}")
if not hits:  # запасной путь: показать строки текста со словами про память
    for m in list(re.finditer(r"[^\n]{0,80}(memorySearch|embedding|fts-only)[^\n]{0,80}", t))[:15]:
        print("  …", m.group(0).strip())
