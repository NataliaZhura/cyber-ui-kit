#!/usr/bin/env python3
"""Печатает ID автоматизации OpenClaw по её названию.

  openclaw automations list --json | python3 automation_id.py "Авиа: утренняя справка"
"""
import json
import sys


def walk(o):
    if isinstance(o, dict):
        if "id" in o and "name" in o:
            yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


text = sys.stdin.read()
starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]  # перед JSON может быть заставка CLI
data = json.loads(text[min(starts):]) if starts else []
ids = [o["id"] for o in walk(data) if o.get("name") == sys.argv[1]]
if not ids:
    sys.exit(f"Не найдено: {sys.argv[1]}")
print(ids[0])
