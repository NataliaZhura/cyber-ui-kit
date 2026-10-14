#!/usr/bin/env python3
"""Данные о компании из API Checko (api.checko.ru): реквизиты, отчётность РСБУ, суды, исполнительные производства.

  python3 checko.py raw company 1025007509768      ответ API как есть → checko/<id>_company.json (+ структура на экран)
  python3 checko.py fin 1025007509768 "Название АК" отчётность РСБУ по годам → строки finance.csv (млрд ₽)
  python3 checko.py risk 1025007509768             суды, исполнительные производства, банкротство → checko/*.json

Идентификатор: ОГРН (13 цифр), ИНН (10 или 12 цифр). Ключ — в ~/.secrets/checko (или в переменной CHECKO_KEY).
Ключ никогда не печатается и не пишется в файлы рядом с данными.
"""
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "checko"
API = "https://api.checko.ru/v2/"
RISK = ["legal-cases", "enforcements", "bankruptcy-messages"]

# Строки РСБУ (коды форм баланса и отчёта о финансовых результатах) → поля finance.csv
CODES = {"выручка": ["2110"], "чистая_прибыль": ["2400"], "активы": ["1600"], "капитал": ["1300"],
         "денежные_средства": ["1250"], "долг": ["1410", "1510"], "обязательства": ["1400", "1500"]}


def key():
    path = Path.home() / ".secrets" / "checko"
    k = os.environ.get("CHECKO_KEY") or (path.read_text(encoding="utf-8") if path.exists() else "")
    return k.strip() or sys.exit(f"Нет ключа Checko: сохрани его в {path} (только на сервере).")


def id_param(ident):
    ident = ident.strip()
    if not ident.isdigit():
        sys.exit("Идентификатор — только цифры: ОГРН (13) или ИНН (10/12).")
    return {13: "ogrn", 15: "ogrn", 10: "inn", 12: "inn"}.get(len(ident)) or sys.exit("Длина не похожа на ОГРН/ИНН.")


def call(endpoint, ident):
    param = id_param(ident)
    q = urllib.parse.urlencode({"key": key(), param: ident})
    req = urllib.request.Request(API + endpoint + "?" + q, headers={"User-Agent": "AviationMonitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:  # текст ошибки API, без адреса запроса (в нём ключ)
        sys.exit(f"Checko {endpoint}: HTTP {e.code} {e.read(300).decode('utf-8', 'replace')}")
    meta = data.get("meta") or {}
    if meta.get("status") not in (None, "ok"):
        sys.exit(f"Checko {endpoint}: {meta}")
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{ident}_{endpoint}.json"
    data["_выгружено"] = datetime.now().strftime("%Y-%m-%d %H:%M МСК")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    left = {k: v for k, v in meta.items() if k != "status"}
    print(f"{endpoint}: сохранено {path.relative_to(BASE)}" + (f" · лимит/баланс: {left}" if left else ""))
    return data.get("data")


def shape(x, depth=0, limit=40):
    """Структура ответа без значений-простыней: ключи, типы, длины списков."""
    pad = "  " * depth
    if isinstance(x, dict):
        for i, (k, v) in enumerate(x.items()):
            if i >= limit:
                print(f"{pad}… ещё {len(x) - limit} ключей")
                break
            if isinstance(v, (dict, list)) and depth < 2:
                print(f"{pad}{k}: {type(v).__name__}" + (f"[{len(v)}]" if isinstance(v, list) else ""))
                shape(v if isinstance(v, dict) else (v[0] if v else {}), depth + 1, limit)
            else:
                print(f"{pad}{k}: {str(v)[:80]}")


def cmd_raw(endpoint, ident):
    shape(call(endpoint, ident))


def years(data):
    """Отчётность по годам: {"2024": {"2110": 123, ...}}. Если формат другой — сообщает, а не угадывает."""
    if isinstance(data, dict):
        ys = {k: v for k, v in data.items() if k.isdigit() and len(k) == 4 and isinstance(v, dict)}
        if ys:
            return ys
    sys.exit("Формат отчётности не распознан — запусти: python3 checko.py raw finances <ОГРН> и пришли вывод.")


def cmd_fin(ident, company):
    ys = years(call("finances", ident))
    new = []
    for y in sorted(ys)[-3:]:
        lines = ys[y]
        row = {"компания": company, "стандарт": "РСБУ", "уровень": "юрлицо", "период": y, "тип": "год",
               "ebitda": "", "источник": f"ГИР БО через Checko, ОГРН/ИНН {ident}, выгружено {datetime.now():%d.%m.%Y}"}
        for field, codes in CODES.items():
            vals = [lines.get(c) for c in codes]
            vals = [float(v) for v in vals if isinstance(v, (int, float, str)) and str(v).lstrip("-").replace(".", "").isdigit()]
            # тыс. ₽ в отчётности → млрд ₽; нет строки — пусто («н/д»), не ноль
            row[field] = f"{sum(vals) / 1e6:.2f}".replace(".", ",") if vals else ""
        new.append(row)
    path = BASE / "finance.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f, delimiter=";")
        cols, old = rd.fieldnames, list(rd)
    same = {(r["компания"], r["стандарт"], r["уровень"], r["период"]) for r in new}
    kept = [r for r in old if (r["компания"], r["стандарт"], r["уровень"], r["период"]) not in same]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
        w.writeheader()
        w.writerows(kept + new)
    print(f"finance.csv: {company}, РСБУ юрлицо, годы {', '.join(r['период'] for r in new)} "
          f"(заменено строк: {len(old) - len(kept)}). EBITDA не заполняется: амортизации нет в формах — н/д.")
    for r in new:
        print("  " + " · ".join(f"{k}={r[k] or 'н/д'}" for k in ("период", "выручка", "чистая_прибыль", "активы", "долг")))
    print("Единицы: предполагается, что Checko отдаёт тыс. ₽ (как в бухотчётности). Сверь один год с карточкой на checko.ru.")


def cmd_risk(ident):
    for ep in RISK:
        try:
            d = call(ep, ident)
        except SystemExit as e:
            print(e)
            continue
        if isinstance(d, dict):
            print("  " + ", ".join(f"{k}={v}" for k, v in d.items() if not isinstance(v, (dict, list)))[:300])


if __name__ == "__main__":
    cmds = {"raw": (cmd_raw, 2), "fin": (cmd_fin, 2), "risk": (cmd_risk, 1)}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds or len(sys.argv) - 2 < cmds[sys.argv[1]][1]:
        print(__doc__)
        sys.exit(1)
    fn, n = cmds[sys.argv[1]]
    fn(*sys.argv[2:2 + n])
