#!/usr/bin/env python3
"""Выбор компании для бота: готовый текст вопроса со списком — агенту остаётся переслать его как есть.

  python3 pick.py letter М        компании из своего списка на «М» (или на «Мо» — сколько букв ввели)
  python3 pick.py name ЮТэйр      похожие по названию: сначала свой список, потом Checko (лимит — 1С:Контрагент); у каждой ИНН
  python3 pick.py choose 3        что выбрал пользователь в последнем списке → название, ИНН, ОГРН

Свой список — watchlist.csv и, если есть, companies.csv (компания;инн;огрн — из твоих материалов).
Последний показанный список хранится в pick_last.json, чтобы ответ цифрой разбирался без ошибок.
"""
import csv
import difflib
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
LAST = BASE / "pick_last.json"
FORMS = r"\b(?:пао|оао|зао|нао|ао|ооо|ип|фгуп|гуп|муп|ак|авиакомпания|авиапредприятие|компания|группа)\b"
OTHER = "0 — иная компания: напишите название или ИНН/ОГРН"
LIMIT = 15


def norm(name):
    """«ПАО „Авиакомпания «ЮТэйр»“» → «ютэйр»: без формы собственности, кавычек и слова «авиакомпания»."""
    s = re.sub(r"[«»\"'„“”]", " ", (name or "").lower().replace("ё", "е"))
    s = re.sub(FORMS, " ", s)
    return " ".join(s.split())


def own():
    """Свои компании: watchlist.csv + companies.csv. Дубли по ИНН (или по названию, если ИНН нет) — один раз."""
    out, seen = [], set()
    for fname in ("watchlist.csv", "companies.csv"):
        path = BASE / fname
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                name = (r.get("компания") or "").strip()
                if not name or name.upper().startswith("ПРИМЕР"):
                    continue
                inn = (r.get("инн") or "").strip()
                key = inn or norm(name)
                if key in seen:
                    continue
                seen.add(key)
                aliases = [a.strip() for a in (r.get("синонимы") or "").split(",") if a.strip()]
                out.append({"name": name, "inn": inn, "ogrn": (r.get("огрн") or "").strip(),
                            "aliases": aliases, "region": (r.get("регион") or "").strip(), "src": "свой список"})
    return out


def line(i, c):
    parts = [c["name"], f"ИНН {c['inn']}" if c.get("inn") else "ИНН не указан", c.get("region"), c.get("status")]
    return f"{i} — " + " · ".join(p for p in parts if p)


def show(title, items):
    items = items[:LIMIT]
    LAST.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    print("\n".join([title] + [line(i, c) for i, c in enumerate(items, 1)] + [OTHER]))


def cmd_letter(prefix):
    p = norm(prefix)
    items = sorted((c for c in own() if norm(c["name"]).startswith(p)
                    or any(norm(a).startswith(p) for a in c["aliases"])), key=lambda c: norm(c["name"]))
    if not items:
        show(f"В вашем списке нет компаний на «{prefix}».", [])
        return
    more = f" (показаны первые {LIMIT} — введите больше букв)" if len(items) > LIMIT else ""
    show(f"Компании на «{prefix}» из вашего списка{more}. Выберите цифрой:", items)


def onec_search(query):
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
        m = re.match(r"\d+ — ОГРН (\d{13,15})(?: · ИНН (\d{10}|\d{12}))? · (.*)", ln.strip())
        if m:
            name = re.split(r"\bИНН\b|\bОГРН\b", m.group(3))[0].strip(" ,·") or m.group(3)[:80]
            items.append({"name": name[:120], "inn": m.group(2) or "", "ogrn": m.group(1), "src": "1С:Контрагент"})
    return items


def cmd_name(*words):
    query = " ".join(words)
    q = norm(query)

    def score(c):
        names = [norm(c["name"])] + [norm(a) for a in c["aliases"]]
        if any(q and q in n for n in names):
            return 1.0
        return max(difflib.SequenceMatcher(None, q, n).ratio() for n in names)

    mine = sorted((c for c in own() if score(c) >= 0.6), key=score, reverse=True)
    found, note = [], ""
    try:
        import checko
        have = {c["inn"] for c in mine if c["inn"]}
        found = [dict(c, src="Checko") for c in checko.search(query) if c["inn"] not in have]
    except (Exception, SystemExit) as e:  # noqa: BLE001 — Checko недоступен (чаще всего суточный лимит) → ищем в 1С
        have = {c["inn"] for c in mine if c["inn"]}
        found = [c for c in onec_search(query) if not c["inn"] or c["inn"] not in have]
        if not found:
            note = " (поиск по реестру сейчас недоступен — показан только ваш список)"
    items = mine + found
    if not items:
        show(f"По «{query}» ничего не найдено{note}.", [])
        return
    show(f"Похожие на «{query}»{note}. Сначала — из вашего списка. Выберите цифрой:", items)


def cmd_choose(num):
    if not LAST.exists():
        sys.exit("Список ещё не показывали — сначала pick.py letter или pick.py name.")
    items = json.loads(LAST.read_text(encoding="utf-8"))
    n = int(num)
    if n == 0:
        print("Иная компания: попросите название или ИНН/ОГРН и запустите pick.py name <название>.")
        return
    if not 1 <= n <= len(items):
        sys.exit(f"Нет варианта {n}: в списке 1–{len(items)} и 0.")
    c = items[n - 1]
    print(json.dumps({k: c.get(k, "") for k in ("name", "inn", "ogrn", "region", "src")}, ensure_ascii=False))


if __name__ == "__main__":
    cmds = {"letter": cmd_letter, "name": cmd_name, "choose": cmd_choose}
    if len(sys.argv) < 3 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]](*sys.argv[2:]) if sys.argv[1] == "name" else cmds[sys.argv[1]](sys.argv[2])
