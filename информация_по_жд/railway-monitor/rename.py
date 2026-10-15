#!/usr/bin/env python3
"""Убирает имя Анастасии из рассылок OpenClaw: подставляет «Владислав» в нужном падеже.

  python3 rename.py          показать, что изменится (ничего не меняет)
  python3 rename.py apply    изменить текст и название рассылок
"""
import json
import re
import subprocess
import sys

NAME = re.compile(r"\b(Анастаси[яюие]й?|Наст[яюеи])\b")
PREP = {"у": "а", "для": "а", "от": "а", "без": "а", "из": "а", "с": "а", "к": "у", "по": "у", "о": "е", "об": "е", "при": "е"}


def fix(text):
    def repl(m):
        w = m.group(1)
        if w in ("Анастасия", "Настя"):
            return "Владислав"
        if w in ("Анастасию", "Настю"):
            return "Владислава"
        if w == "Анастасией":
            return "Владиславом"
        prev = text[:m.start()].split()[-1:] or [""]
        return "Владислав" + PREP.get(prev[0].lower(), "у")  # без предлога чаще «кому?» — Владиславу
    return NAME.sub(repl, text)


def jobs():
    out = subprocess.run(["openclaw", "automations", "list", "--json"], capture_output=True, text=True).stdout
    starts = [i for i in (out.find("{"), out.find("[")) if i >= 0]
    data = json.loads(out[min(starts):]) if starts else []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    return list(walk(data))


def texts(o, path=""):  # все строки задания, где встречается имя
    if isinstance(o, dict):
        for k, v in o.items():
            yield from texts(v, f"{path}.{k}" if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from texts(v, f"{path}.{i}")
    elif isinstance(o, str) and NAME.search(o):
        yield path, o


def main():
    apply = len(sys.argv) > 1 and sys.argv[1] == "apply"
    found = 0
    for j in jobs():
        hits = list(texts(j))
        if not hits:
            continue
        found += 1
        print(f"\n== {j['name']} ({j['id']})")
        msg = None
        for path, s in hits:
            new = fix(s)
            print(f"  {path}:\n    было:  {s[:300]}\n    стало: {new[:300]}")
            if path.split(".")[-1] in ("message", "prompt", "text") and msg is None:
                msg = new
        if apply:
            args = ["openclaw", "automations", "edit", j["id"]]
            if NAME.search(j["name"]):
                args += ["--name", fix(j["name"])]
            if msg:
                args += ["--message", msg]
            r = subprocess.run(args, capture_output=True, text=True)
            print("  ✔ изменено" if r.returncode == 0 else f"  !! не изменено: {(r.stderr or r.stdout)[-300:]}")
    print(f"\nРассылок с именем: {found}." + ("" if apply or not found else " Чтобы изменить: python3 rename.py apply"))


if __name__ == "__main__":
    main()
