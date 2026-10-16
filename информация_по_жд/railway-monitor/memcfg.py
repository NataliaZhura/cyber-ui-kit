#!/usr/bin/env python3
"""Показывает, какие настройки поиска по памяти есть в этой версии OpenClaw (только читает).
  openclaw config schema > /tmp/schema.json; python3 memcfg.py /tmp/schema.json
"""
import json
import sys

t = open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/schema.json", encoding="utf-8").read()
d = json.loads(t[t.find("{"):])
seen = set()


def walk(o, p):
    if not isinstance(o, dict):
        return
    for k, v in (o.get("properties") or {}).items():
        q = f"{p}.{k}" if p else k
        low = q.lower()
        if ("memorysearch" in low or "embedding" in low or low.endswith("memory.provider")) and q not in seen:
            seen.add(q)
            print(q, "|", v.get("enum") or v.get("type") or "", "|", (v.get("description") or "")[:80])
        walk(v, q)
    for key in ("anyOf", "oneOf", "allOf"):
        for s in o.get(key) or []:
            walk(s, p)
    if isinstance(o.get("items"), dict):
        walk(o["items"], p + "[]")
    if isinstance(o.get("additionalProperties"), dict):
        walk(o["additionalProperties"], p + ".*")


walk(d, "")
print(f"— найдено настроек: {len(seen)}")
