#!/usr/bin/env python3
"""ИНН, официальные сайты и Telegram-каналы компаний из companies.csv → источники новостей для сборщика.

  python3 links.py inn  [--limit 40]   дописать недостающие ИНН/ОГРН (поиск Checko); спорные → links_check.csv
  ~/pw/bin/python links.py inn1c [--limit 40]  то же через 1С:Контрагент (без дневного лимита Checko; ОГРН из ссылки)
  python3 links.py check               спорные компании с вариантами (нумерованный список)
  python3 links.py pick 3 2801118992   записать ИНН для компании №3 из списка check
  python3 links.py find [--limit 40]   сайт (Checko) → на сайте ищем ссылку на Telegram и RSS → links.csv
  python3 links.py show                таблица links.csv коротко (для владельца)
  python3 links.py apply               одобренные строки links.csv → company_sources.json (его читает collector.py)

--limit — сколько запросов к Checko за запуск (дневной лимит тарифа). Повторный запуск продолжает с места остановки.
links.csv: компания;инн;сайт;rss;telegram;откуда;статус;одобрено. «одобрено» = да/нет — правит владелец;
по умолчанию «да» только если канал найден по ссылке на официальном сайте компании.
Перед изменением companies.csv делается копия в bak/.
"""
import csv
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import checko

BASE = Path(__file__).resolve().parent
COMPANIES = BASE / "companies.csv"
LINKS = BASE / "links.csv"
CHECK = BASE / "links_check.csv"
SOURCES = BASE / "company_sources.json"
FIELDS = ["компания", "инн", "сайт", "rss", "telegram", "откуда", "статус", "одобрено"]
UA = {"User-Agent": "Mozilla/5.0 (AviationMonitor/1.0)"}
# служебные адреса Telegram, которые не являются каналом компании
TG_SKIP = {"share", "joinchat", "addstickers", "proxy", "iv", "s", "c", "login", "telegram", "durov", "boost"}


def read_csv(path):
    if not path.exists():
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f, delimiter=";")
        return list(r), list(r.fieldnames or [])


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def norm(name):
    """«АО "Авиакомпания "Ангара"» → «ангара»: для сравнения названий."""
    s = re.sub(r"[«»\"'()]", " ", name.lower())
    s = re.sub(r"\b(ооо|оао|зао|пао|ао|нао|ак|авиакомпания|авиапредприятие|авиалинии|компания|акционерное общество|"
               r"общество с ограниченной ответственностью|публичное)\b", " ", s)
    return " ".join(s.split())


def limit_arg(default=40):
    if "--limit" in sys.argv:
        return int(sys.argv[sys.argv.index("--limit") + 1])
    return default


AVIA = re.compile(r"авиа|аэро|вертол|аэропорт|авиабаз|airlines|avia", re.I)


def match(name, found):
    """Кандидаты из поиска, которые похожи на нашу компанию: то же «ядро» названия, а при совпадении части —
    только авиационные (иначе «Ямал» находит «Ямал СПГ»)."""
    core = norm(name)
    active = [x for x in found if "не действ" not in x["status"].lower() and "ликвид" not in x["status"].lower()]
    same = [x for x in active if norm(x["name"] or "") == core]
    # тёзки с тем же «ядром» («ООО Ангара» и «АО Авиакомпания Ангара») — оставляем авиационных, если они есть
    avia_same = [x for x in same if AVIA.search(x["name"] or "")]
    if avia_same:
        return avia_same
    if same:
        return same
    return [x for x in active if core and core in norm(x["name"] or "") and AVIA.search(x["name"] or "")]


def save_companies(rows, fields):
    bak = BASE / "bak"
    bak.mkdir(exist_ok=True)
    shutil.copy2(COMPANIES, bak / f"companies-{datetime.now():%Y-%m-%d-%H%M}.csv")
    if "огрн" not in fields:
        fields.append("огрн")
    write_csv(COMPANIES, rows, fields)


def cmd_inn():
    rows, fields = read_csv(COMPANIES)
    if not rows:
        sys.exit(f"Нет {COMPANIES.name}")
    todo = [r for r in rows if not (r.get("инн") or "").strip()]
    budget, filled, check = limit_arg(), 0, []
    for r in todo:
        if budget <= 0:
            break
        name = (r.get("компания") or "").strip()
        cands, seen = [], []
        # сначала «ядро» названия без формы собственности («Ангара»), затем полное название
        for q in dict.fromkeys([norm(name), name]):
            if budget <= 0 or not q:
                break
            try:
                found = checko.search(q, limit=20)
            except RuntimeError as e:
                print(f"Стоп: {e}")
                budget = 0
                break
            budget -= 1
            seen += found
            cands = match(name, found)
            if cands:
                break
        uniq = {c["inn"]: c for c in cands}
        if len(uniq) == 1:
            pick = next(iter(uniq.values()))
            r["инн"], r["огрн"] = pick["inn"] or "", pick["ogrn"] or ""
            filled += 1
            print(f"  + {name} → {pick['name']} ИНН {pick['inn']}")
        else:
            show = list(uniq.values()) or [x for x in seen if AVIA.search(x["name"] or "")] or seen
            check.append({"компания": name, "варианты": " | ".join(
                f"{x['name']} ИНН {x['inn']} {x['region']}" for x in show[:4]) or "не найдено"})
    if filled:
        save_companies(rows, fields)
    if check:
        old, _ = read_csv(CHECK)
        names = {c["компания"] for c in check}
        write_csv(CHECK, [o for o in old if o["компания"] not in names] + check, ["компания", "варианты"])
    left = sum(1 for r in rows if not (r.get("инн") or "").strip())
    print(f"ИНН дописано: {filled}; выбрать вручную: {len(check)}; без ИНН осталось: {left}")
    cmd_check()


def cmd_inn1c():
    """Недостающие ИНН через поиск 1С:Контрагент — одно окно браузера на весь список (сервер слабый)."""
    import onec
    rows, fields = read_csv(COMPANIES)
    todo = [r for r in rows if not (r.get("инн") or "").strip()]
    budget, filled, check = limit_arg(), 0, []
    with onec.sync_playwright() as p:
        b, page = onec.open_search(p)
        for r in todo:
            if budget <= 0:
                break
            name = (r.get("компания") or "").strip()
            cands, seen = [], []
            for q in dict.fromkeys([norm(name), name]):
                if budget <= 0 or not q:
                    break
                try:
                    found = onec.search(page, q, limit=15)
                except Exception as e:  # noqa: BLE001 — сайт не ответил: сохраняем сделанное
                    print(f"Стоп на «{name}»: {type(e).__name__}: {e}")
                    budget = 0
                    break
                budget -= 1
                seen += found
                cands = match(name, found)
                if cands:
                    break
            uniq = {c["ogrn"]: c for c in cands}
            if len(uniq) == 1 and next(iter(uniq.values()))["inn"]:
                pick = next(iter(uniq.values()))
                r["инн"], r["огрн"] = pick["inn"], pick["ogrn"]
                filled += 1
                print(f"  + {name} → {pick['name'][:80]} ИНН {pick['inn']}")
            else:
                show = list(uniq.values()) or [x for x in seen if AVIA.search(x["name"])] or seen
                check.append({"компания": name, "варианты": " | ".join(
                    f"{x['name'][:70]} ИНН {x['inn'] or '?'} ОГРН {x['ogrn']}" for x in show[:4]) or "не найдено"})
        b.close()
    if filled:
        save_companies(rows, fields)
    if check:
        old, _ = read_csv(CHECK)
        names = {c["компания"] for c in check}
        write_csv(CHECK, [o for o in old if o["компания"] not in names] + check, ["компания", "варианты"])
    left = sum(1 for r in rows if not (r.get("инн") or "").strip())
    print(f"1С:Контрагент — ИНН дописано: {filled}; выбрать вручную: {len(check)}; без ИНН осталось: {left}")
    cmd_check()


def cmd_check():
    rows, _ = read_csv(CHECK)
    have = {(r.get("компания") or "").strip() for r, in [(x,) for x in read_csv(COMPANIES)[0]]
            if (r.get("инн") or "").strip()}
    rows = [r for r in rows if r["компания"] not in have]
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['компания']}\n   {r['варианты'][:300]}")
    if rows:
        print("\nВыбор: python3 links.py pick <номер> <ИНН> (ИНН из вариантов или свой); пропустить — не отвечать.")


def cmd_pick(num, inn):
    rows, _ = read_csv(CHECK)
    comp, fields = read_csv(COMPANIES)
    have = {(r.get("компания") or "").strip() for r in comp if (r.get("инн") or "").strip()}
    rows = [r for r in rows if r["компания"] not in have]
    n = int(num)
    if not 1 <= n <= len(rows) or not inn.isdigit() or len(inn) not in (10, 12):
        sys.exit("Нужно: номер из списка и ИНН (10 или 12 цифр).")
    name = rows[n - 1]["компания"]
    for r in comp:
        if (r.get("компания") or "").strip() == name:
            r["инн"] = inn
    save_companies(comp, fields)
    print(f"Записано: {name} → ИНН {inn}")


def find_site(inn, budget):
    """Сайт из карточки Checko (сначала сохранённая карточка, без запроса). → (сайт, потрачено запросов)."""
    path = checko.OUT / f"{inn}_company.json"
    spent = 0
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8")).get("data") or {}
    elif budget > 0:
        data = checko.call("company", inn) or {}
        spent = 1
    else:
        return None, 0

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if re.search(r"сайт|web", k, re.I) and v:
                    return v[0] if isinstance(v, list) else v
                got = walk(v)
                if got:
                    return got
        elif isinstance(x, list):
            for v in x:
                got = walk(v)
                if got:
                    return got
        return None

    site = walk(data)
    if site and isinstance(site, str):
        site = site.strip()
        if not site.startswith("http"):
            site = "https://" + site
        return site, spent
    return "", spent


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(1_500_000).decode("utf-8", "replace"), r.geturl()


def scan_site(site):
    """Главная страница сайта → (telegram-каналы, rss)."""
    html, final = get(site)
    tg = []
    for m in re.finditer(r"(?:https?:)?//(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,})", html):
        ch = m.group(1)
        if ch.lower() not in TG_SKIP and ch not in tg:
            tg.append(ch)
    rss = ""
    m = re.search(r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", html, re.I)
    if m:
        h = re.search(r"href=[\"']([^\"']+)", m.group(0))
        if h:
            rss = urllib.parse.urljoin(final, h.group(1))
    return tg, rss


def tg_alive(ch):
    try:
        html, _ = get(f"https://t.me/s/{ch}", timeout=20)
    except Exception:  # noqa: BLE001
        return False
    return "tgme_widget_message" in html


def cmd_find():
    rows, _ = read_csv(COMPANIES)
    done, _ = read_csv(LINKS)
    have = {d["инн"]: d for d in done if d.get("статус") != "ошибка"}
    budget, out = limit_arg(), [d for d in done if d.get("статус") != "ошибка"]
    for r in rows:
        inn = (r.get("инн") or "").strip()
        name = (r.get("компания") or "").strip()
        if not inn or inn in have:
            continue
        try:
            site, spent = find_site(inn, budget)
        except SystemExit as e:  # ошибка или лимит Checko: сохраняем сделанное и выходим
            print(f"Стоп на «{name}»: {e}")
            break
        budget -= spent
        if site is None:
            print("Лимит запросов Checko на этот запуск исчерпан — продолжу при следующем запуске.")
            break
        row = {"компания": name, "инн": inn, "сайт": site, "rss": "", "telegram": "", "откуда": "", "статус": "",
               "одобрено": "нет"}
        if not site:
            row["статус"] = "сайта нет в Checko — указать вручную"
        else:
            try:
                tgs, rss = scan_site(site)
                row["rss"] = rss
                alive = [c for c in tgs if tg_alive(c)]
                row["telegram"] = alive[0] if alive else ""
                row["откуда"] = "ссылка на сайте компании" if alive else ""
                row["статус"] = ("найдено" if alive or rss else "на сайте нет Telegram и RSS — новости сайта через поиск")
                if len(alive) > 1:
                    row["статус"] += f"; ещё каналы на сайте: {', '.join(alive[1:3])} — проверить"
                row["одобрено"] = "да"  # сайт из реестра, канал — со страницы этого сайта
            except Exception as e:  # noqa: BLE001
                row["статус"] = "ошибка"
                row["откуда"] = f"сайт не открылся: {type(e).__name__}"
        out.append(row)
        print(f"{name}: сайт {row['сайт'] or '—'} · TG {row['telegram'] or '—'} · RSS {'есть' if row['rss'] else '—'}")
    write_csv(LINKS, out, FIELDS)
    without = sum(1 for r in rows if not (r.get("инн") or "").strip())
    print(f"\nВ {LINKS.name}: {len(out)} компаний; с Telegram: {sum(1 for o in out if o['telegram'])}; "
          f"с RSS: {sum(1 for o in out if o['rss'])}; без ИНН (пропущены): {without}")


def cmd_show():
    rows, _ = read_csv(LINKS)
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['компания']} — {r['одобрено']}\n   сайт: {r['сайт'] or '—'}\n   TG: "
              f"{('@' + r['telegram']) if r['telegram'] else '—'} · RSS: {'есть' if r['rss'] else '—'}"
              + (f"\n   {r['статус']}" if r['статус'] not in ('найдено', '') else ""))


def cmd_apply():
    rows, _ = read_csv(LINKS)
    ok = [r for r in rows if (r.get("одобрено") or "").strip().lower() in ("да", "yes", "1", "+")]
    src = [{"company": r["компания"], "inn": r["инн"], "site": r["сайт"], "rss": r["rss"], "telegram": r["telegram"]}
           for r in ok if r["сайт"] or r["telegram"]]
    if SOURCES.exists():
        bak = BASE / "bak"
        bak.mkdir(exist_ok=True)
        shutil.copy2(SOURCES, bak / f"company_sources-{datetime.now():%Y-%m-%d-%H%M}.json")
    SOURCES.write_text(json.dumps(src, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Подключено компаний: {len(src)} (Telegram: {sum(1 for s in src if s['telegram'])}, "
          f"RSS: {sum(1 for s in src if s['rss'])}, сайт через поиск: {sum(1 for s in src if s['site'] and not s['rss'])}). "
          "Сборщик опрашивает их раз в 3 часа.")


if __name__ == "__main__":
    cmds = {"inn": cmd_inn, "inn1c": cmd_inn1c, "check": cmd_check, "pick": cmd_pick, "find": cmd_find, "show": cmd_show, "apply": cmd_apply}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    args = [a for a in sys.argv[2:] if not a.startswith("--") and not (sys.argv.index(a) > 1 and sys.argv[sys.argv.index(a) - 1] == "--limit")]
    cmds[sys.argv[1]](*args)
