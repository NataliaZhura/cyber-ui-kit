#!/usr/bin/env python3
"""Данные о компании из API Checko (api.checko.ru): реквизиты, отчётность РСБУ, суды, исполнительные производства.

  python3 checko.py profile 1025007509768 [2025]   понятная справка (финансы столбиком: 2 последних года до указанного)
  python3 checko.py compare <ОГРН1> <ОГРН2> [2025]  две компании за один год, столбиком
  python3 checko.py find "ЮТэйр"                   поиск по названию → ИНН, ОГРН, регион, статус (до 10 вариантов)
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
    print(f"{endpoint}: сохранено {path.relative_to(BASE)}" + (f" · лимит/баланс: {left}" if left else ""),
          file=sys.stderr)
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
            # рубли → млрд ₽; нет строки — пусто («н/д»), не ноль
            row[field] = f"{sum(vals) / 1e9:.2f}".replace(".", ",") if vals else ""
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
    print("Единицы: Checko отдаёт отчётность в рублях, здесь — млрд ₽. Сверь один год с карточкой на checko.ru.")


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
        print(f"  {endpoint}: нет данных ({e})", file=sys.stderr)
        return None


def g(d, *path):
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return d


def name_of(x):
    return x if isinstance(x, str) else g(x, "Наим") or g(x, "НаимПолн") or g(x, "НаимСокр") or g(x, "ФИО") or ""


def money(v, unit=1):
    """Рубли в «млн ₽» / «млрд ₽» по-русски. Checko отдаёт суммы, включая отчётность, в рублях."""
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
                out.append(f"{name_of(f)}" + (f" — {float(share):g}%" if share is not None else ""))
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


# Строки таблицы: подпись → коды РСБУ (суммируются). Обязательства = долгосрочные + краткосрочные.
ROWS = [("Выручка", ["2110"]), ("Прибыль от продаж", ["2200"]), ("Чистая прибыль", ["2400"]),
        ("Активы", ["1600"]), ("Собственный капитал", ["1300"]), ("Обязательства долгоср.", ["1400"]),
        ("Обязательства краткоср.", ["1500"]), ("Кредиты и займы", ["1410", "1510"]),
        ("Дебиторская задолж.", ["1230"]), ("Денежные средства", ["1250"])]


def val(year_lines, codes):
    vs = [year_lines.get(c) for c in codes]
    vs = [float(v) for v in vs if isinstance(v, (int, float))]
    return sum(vs) if vs else None


def bln(v):
    if v is None:
        return "н/д"
    digits = 3 if 0 < abs(v) < 1e8 else 1  # мелкие суммы (например, 13,7 млн ₽) не превращаем в «0,0»
    return f"{v / 1e9:,.{digits}f}".replace(",", " ").replace(".", ",")


def chg(a, b):
    """Изменение в %. Если хоть одно значение отрицательное (убыток) — % вводит в заблуждение,
    поэтому пишем разницу в млрд ₽: «убыток сократился на 5,3» будет видно как «+5,3»."""
    if a is None or b is None:
        return ""
    if a < 0 or b < 0:
        return f"{(b - a) / 1e9:+.1f}".replace(".", ",")
    return f"{(b - a) / a * 100:+.0f}%" if a else ""


def pick(fin, upto=None):
    """Два последних года (до upto включительно) — по умолчанию только они."""
    ys = [y for y in sorted(fin) if not upto or y <= str(upto)]
    return ys[-2:]


def fin_table(fin, upto=None):
    """Таблица столбиком (млрд ₽): показатель | прошлый год | последний год | изменение.
    Третий год не показываем, но если выручка или активы вернулись к уровню позапрошлого года — пишем об этом."""
    ys = pick(fin, upto)
    if not ys:
        return []
    w = 24
    rows = [f"{'млрд ₽':<{w}}" + "".join(f"{y:>9}" for y in ys) + ("   изм." if len(ys) == 2 else "")]
    for label, codes in ROWS:
        vals = [val(fin[y], codes) for y in ys]
        rows.append(f"{label:<{w}}" + "".join(f"{bln(v):>9}" for v in vals)
                    + (f"{chg(*vals):>7}" if len(vals) == 2 else ""))
    notes = []
    allys = [y for y in sorted(fin) if not upto or y <= str(upto)]
    if len(allys) >= 3:
        y0, last = allys[-3], allys[-1]
        for label, code in (("Выручка", "2110"), ("Активы", "1600"), ("Собственный капитал", "1300")):
            a, b = val(fin[y0], [code]), val(fin[last], [code])
            if a and b is not None and b <= a:
                notes.append(f"{label} {last} ({bln(b)}) — на уровне {y0} или ниже ({bln(a)}).")
    legend = "изм.: % к прошлому году; для убытков — разница в млрд ₽ (плюс = улучшение)"
    return ["```"] + rows + ["```", legend] + notes


def cmd_profile(ident, upto=None):
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
        lines += ["\n▎Финансы (РСБУ, юрлицо, млрд ₽)"] + fin_table(fin, upto)
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
    lines.append("\nИсточник: Checko (данные ФНС, ГИР БО, картотеки судов и ФССП).")
    text = "\n".join(lines)
    OUT.mkdir(exist_ok=True)
    (OUT / f"{ident}_профиль.txt").write_text(text, encoding="utf-8")
    print(text)


def cmd_compare(id1, id2, upto=None):
    """Две компании за один и тот же последний год (или год upto), столбиком."""
    data = []
    for ident in (id1, id2):
        c = cached("company", ident) or {}
        fin = years(cached("finances", ident)) or {}
        data.append((c.get("НаимСокр") or ident, fin))
    common = sorted(set(data[0][1]) & set(data[1][1]))
    if upto:
        common = [y for y in common if y <= str(upto)]
    if not common:
        sys.exit("Нет общего года отчётности у двух компаний.")
    y = common[-1]
    w = 24
    out = [f"Сравнение за {y} год, РСБУ юрлиц, млрд ₽ (Checko)",
           *[f"{i}) {n}" for i, (n, _) in enumerate(data, 1)], "```",
           f"{'':<{w}}{'1)':>9}{'2)':>9}"]
    for label, codes in ROWS:
        out.append(f"{label:<{w}}" + "".join(f"{bln(val(f[y], codes)):>9}" for _, f in data))
    for label, a, b in (("Капитал / активы", "1300", "1600"), ("Чистая рентаб.", "2400", "2110")):
        cells = []
        for _, f in data:
            x, z = val(f[y], [a]), val(f[y], [b])
            cells.append(f"{x / z * 100:.1f}%".replace(".", ",") if x is not None and z else "н/д")
        out.append(f"{label:<{w}}" + "".join(f"{c:>9}" for c in cells))
    out.append("```")
    print("\n".join(out))


def records(x):
    """Список карточек организаций из ответа поиска — где бы он ни лежал в JSON."""
    if isinstance(x, list) and x and isinstance(x[0], dict) and ("ИНН" in x[0] or "ОГРН" in x[0]):
        return x
    if isinstance(x, dict):
        for v in x.values():
            r = records(v)
            if r:
                return r
    return []


def cmd_find(*words):
    """Поиск компании по названию → ИНН, ОГРН, регион, статус. Формат метода поиска Checko сверяется
    по ответу; если метод недоступен на тарифе — сообщает, и агент ищет через onec.py find."""
    query = " ".join(words)
    q = urllib.parse.urlencode({"key": key(), "by": "name", "obj": "org", "query": query, "limit": 10})
    req = urllib.request.Request(API + "search?" + q, headers={"User-Agent": "AviationMonitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"Поиск Checko недоступен: HTTP {e.code} {e.read(200).decode('utf-8', 'replace')}")
    meta = data.get("meta") or {}
    if meta.get("status") not in (None, "ok"):
        sys.exit(f"Поиск Checko недоступен: {meta}")
    rows = records(data.get("data"))
    if not rows:
        print(f"По «{query}» ничего не найдено в Checko.")
        return
    for i, r in enumerate(rows[:10], 1):
        print(f"{i} — {r.get('НаимСокр') or r.get('НаимПолн')} · ИНН {r.get('ИНН')} · ОГРН {r.get('ОГРН')} · "
              f"{name_of(r.get('Регион'))} · {name_of(r.get('Статус'))}")


if __name__ == "__main__":
    cmds = {"raw": (cmd_raw, 2), "fin": (cmd_fin, 2), "risk": (cmd_risk, 1), "profile": (cmd_profile, 1), "compare": (cmd_compare, 2), "find": (cmd_find, 1)}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds or len(sys.argv) - 2 < cmds[sys.argv[1]][1]:
        print(__doc__)
        sys.exit(1)
    fn, n = cmds[sys.argv[1]]
    fn(*(sys.argv[2:] if fn is cmd_find else sys.argv[2:3 + n]))  # последний необязательный аргумент — год отчётности
