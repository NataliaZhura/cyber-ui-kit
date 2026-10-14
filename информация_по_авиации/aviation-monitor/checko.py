#!/usr/bin/env python3
"""Данные о компании из API Checko (api.checko.ru): реквизиты, отчётность РСБУ, суды, исполнительные производства.

  python3 checko.py profile 1025007509768          понятная справка по компании (для Telegram) → checko/<id>_профиль.txt
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
    return None


def cmd_fin(ident, company):
    ys = years(call("finances", ident))
    if not ys:
        sys.exit("Формат отчётности не распознан — запусти: python3 checko.py raw finances <ОГРН> и пришли вывод.")
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


def cached(endpoint, ident):
    """Ответ за сегодня берётся из файла — не тратим дневной лимит запросов."""
    path = OUT / f"{ident}_{endpoint}.json"
    if path.exists() and datetime.fromtimestamp(path.stat().st_mtime).date() == datetime.now().date():
        return json.loads(path.read_text(encoding="utf-8")).get("data")
    try:
        return call(endpoint, ident)
    except SystemExit as e:
        print(f"  {endpoint}: нет данных ({e})")
        return None


def g(d, *path):
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return d


def name_of(x):
    return x if isinstance(x, str) else g(x, "Наим") or g(x, "НаимПолн") or g(x, "НаимСокр") or g(x, "ФИО") or ""


def money(v, unit=1e3):
    """Рубли в «млн ₽» / «млрд ₽» по-русски. unit — во что выражено v (по умолчанию тыс. ₽ из отчётности)."""
    try:
        r = float(v) * unit
    except (TypeError, ValueError):
        return "н/д"
    if abs(r) >= 1e9:
        return f"{r / 1e9:,.1f} млрд ₽".replace(",", " ").replace(".", ",")
    return f"{r / 1e6:,.1f} млн ₽".replace(",", " ").replace(".", ",")


def dt(v):
    """2026-01-31 → 31.01.2026."""
    v = str(v or "")
    return ".".join(reversed(v[:10].split("-"))) if len(v) >= 10 and v[4] == "-" else v


def lst(x):
    return x if isinstance(x, list) else []


def founders(c):
    u = c.get("Учред")
    out = []
    if isinstance(u, dict):
        for group in u.values():
            for f in lst(group):
                share = g(f, "Доля", "Процент")
                out.append(f"{name_of(f)}" + (f" — {share}%" if share is not None else ""))
    elif isinstance(u, list):
        out = [name_of(f) for f in u]
    return [x for x in out if x]


def cases_summary(d):
    """Суды: число дел и сумма требований; поля API разбираются бережно — чего нет, то «н/д»."""
    if not isinstance(d, dict):
        return None
    recs = lst(d.get("Записи"))
    total = d.get("ОбщСуммИск")
    if total is None and recs:
        total = sum(float(r.get("СуммИск") or 0) for r in recs)
    big = sorted(recs, key=lambda r: float(r.get("СуммИск") or 0), reverse=True)[:5]
    return {"n": d.get("ЗапВсего", len(recs)), "sum": total, "big": big}


def section(title, rows):
    rows = [r for r in rows if r]
    return [f"\n▎{title}"] + [f"• {r}" for r in rows] if rows else []


def cmd_profile(ident):
    c = cached("company", ident) or {}
    if not c:
        sys.exit("Компания не найдена.")
    fin = years(cached("finances", ident))
    courts = cases_summary(cached("legal-cases", ident))
    enf = cached("enforcements", ident)
    made = datetime.now().strftime("%d.%m.%Y %H:%M")

    head = [f"🏢 {c.get('НаимСокр') or c.get('НаимПолн')}",
            f"{name_of(c.get('Статус'))} · ИНН {c.get('ИНН')} · ОГРН {c.get('ОГРН')}",
            f"Данные Checko (ЕГРЮЛ, ГИР БО, картотека судов) на {made} МСК"]
    reg = [f"Регион: {name_of(c.get('Регион'))}",
           f"Адрес: {g(c, 'ЮрАдрес', 'АдресРФ')}" + (" ⚠️ недостоверен" if g(c, "ЮрАдрес", "Недост") else ""),
           f"Зарегистрирована: {dt(c.get('ДатаРег'))}",
           f"Деятельность: {g(c, 'ОКВЭД', 'Код')} {name_of(c.get('ОКВЭД'))}",
           f"Уставный капитал: {money(g(c, 'УстКап', 'Сумма'), 1)}" if g(c, "УстКап", "Сумма") else "",
           f"Сотрудников: {c.get('СЧР')}" if c.get("СЧР") else ""]
    own = founders(c)
    lines = head + section("Реквизиты", reg) + section("Владельцы", own[:6] + ([f"… ещё {len(own) - 6}"] if len(own) > 6 else []))

    if fin:
        fr = []
        for y in sorted(fin)[-3:]:
            v = fin[y]
            debt = [v.get(k) for k in ("1410", "1510") if v.get(k) is not None]
            fr.append(f"{y}: выручка {money(v.get('2110'))}, чистая прибыль {money(v.get('2400'))}, "
                      f"активы {money(v.get('1600'))}, капитал {money(v.get('1300'))}, "
                      f"кредиты и займы {money(sum(map(float, debt))) if debt else 'н/д'}")
        lines += section("Финансы (РСБУ, юрлицо)", fr)
    else:
        lines += section("Финансы (РСБУ, юрлицо)", ["н/д — отчётность недоступна по текущему тарифу или не сдана"])

    if courts:
        cr = [f"Дел: {courts['n']}, сумма требований: {money(courts['sum'], 1)}"]
        cr += [f"{dt(r.get('Дата'))} · {r.get('Номер', '')} · {money(r.get('СуммИск'), 1)}" for r in courts["big"]]
        lines += section("Суды (крупнейшие)", cr)
    if isinstance(enf, dict):
        lines += section("Исполнительные производства",
                         [f"Всего: {enf.get('ЗапВсего', len(lst(enf.get('Записи'))))}, "
                          f"сумма: {money(enf.get('ОбщСумДолг') or enf.get('СуммДолг'), 1)}"])
    lines.append("\nИсточник: Checko. Цифры отчётности — в тыс. ₽ из ГИР БО, пересчитаны в млн/млрд ₽.")
    text = "\n".join(lines)
    OUT.mkdir(exist_ok=True)
    (OUT / f"{ident}_профиль.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    cmds = {"raw": (cmd_raw, 2), "fin": (cmd_fin, 2), "risk": (cmd_risk, 1), "profile": (cmd_profile, 1)}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds or len(sys.argv) - 2 < cmds[sys.argv[1]][1]:
        print(__doc__)
        sys.exit(1)
    fn, n = cmds[sys.argv[1]]
    fn(*sys.argv[2:2 + n])
