#!/usr/bin/env python3
"""Загрузка финансовых данных из открытых источников.

  python3 fin_fetch.py moex "Аэрофлот"     облигации эмитента на Мосбирже: объём, погашение, купон, итог в обращении
  python3 fin_fetch.py girbo 7712040126    проверка ГИР БО (бухотчётность РСБУ по ИНН): что и в каком виде отдаёт

ГИР БО — отчётность юрлица по РСБУ (не группы). МСФО группы в машиночитаемом виде открыто не публикуется —
её строки в finance.csv заполняются вручную из отчёта.
"""
import json
import sys
import urllib.parse
import urllib.error
import urllib.request
from datetime import date

UA = "Mozilla/5.0 (X11; Linux x86_64) AviationMonitor/1.0"


def peek(url, timeout=30):
    """Что сервер отвечает на самом деле: код, тип содержимого, начало ответа."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json",
                                               "Referer": "https://bo.nalog.ru/"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(400).decode("utf-8", "replace")
            return r.status, r.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read(400).decode("utf-8", "replace")


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def iss_rows(block):
    """Блок ISS Мосбиржи {columns, data} → список словарей."""
    return [dict(zip(block["columns"], row)) for row in block.get("data", [])]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def moex_bonds(query):
    """Облигации эмитента на Мосбирже: список выпусков и сумма рублёвых в обращении по номиналу, млрд ₽."""
    url = ("https://iss.moex.com/iss/securities.json?iss.meta=off&limit=100&q="
           + urllib.parse.quote(query))
    _, data = get_json(url)
    found = [r for r in iss_rows(data["securities"]) if "bond" in str(r.get("group", ""))]
    today = date.today().isoformat()
    out, total = [], 0.0
    for r in found:
        _, d = get_json(f"https://iss.moex.com/iss/securities/{r['secid']}.json?iss.meta=off")
        desc = {x["name"]: x.get("value") for x in iss_rows(d["description"])}
        size, face = num(desc.get("ISSUESIZE")), num(desc.get("FACEVALUE"))
        cur = desc.get("FACEUNIT") or "RUB"
        mat = desc.get("MATDATE") or ""
        bln = size * face / 1e9 if size and face else None
        live = bool(mat) and mat >= today
        rub = cur in ("RUB", "SUR")
        if bln and live and rub:
            total += bln
        out.append({"secid": r["secid"], "name": str(desc.get("SHORTNAME") or r.get("shortname")),
                    "bln": bln, "mat": mat, "coupon": desc.get("COUPONPERCENT"), "live": live, "cur": cur})
    return out, total


def cmd_moex(query):
    rows, total = moex_bonds(query)
    if not rows:
        print(f"Облигаций по запросу «{query}» не найдено.")
        return
    print(f"{'SECID':14} {'Выпуск':32} {'Объём, млрд':>11} {'Погашение':>10} {'Купон,%':>7}")
    for b in rows:
        size = f"{b['bln']:.1f}" if b["bln"] else "—"
        note = ("" if b["live"] else "  (погашен)") + ("" if b["cur"] in ("RUB", "SUR") else f"  ({b['cur']})")
        print(f"{b['secid']:14} {b['name'][:32]:32} {size:>11} {b['mat']:>10} {str(b['coupon'] or '—'):>7}{note}")
    print(f"\nВ обращении рублёвых выпусков по номиналу: {total:.1f} млрд ₽ "
          f"(объём выпуска × номинал; без учёта досрочных выкупов и амортизации)")


def cmd_girbo(inn):
    """Разведка: какие адреса отвечают и что в ответе. Формат ГИР БО публично не документирован —
    по результату будет написан разбор."""
    tries = [f"https://bo.nalog.ru/advanced-search/organizations/search?query={inn}&page=0",
             f"https://bo.nalog.ru/nbo/organizations/search?query={inn}&page=0"]
    org_id = None
    for url in tries:
        try:
            st, data = get_json(url)
            content = data.get("content", data) if isinstance(data, dict) else data
            first = content[0] if isinstance(content, list) and content else {}
            print(f"OK {st} {url}\n   ключи: {list(data)[:12] if isinstance(data, dict) else type(data).__name__}")
            print(f"   первая запись: { {k: first.get(k) for k in list(first)[:8]} }")
            org_id = org_id or first.get("id")
        except Exception as e:  # noqa: BLE001 — для разведки важна любая причина
            print(f"FAIL {url} -> {type(e).__name__}: {e}")
            try:
                st, ctype, body = peek(url)
                print(f"   ответ: код {st}, тип {ctype}\n   начало: {' '.join(body.split())[:300]}")
            except Exception as e2:  # noqa: BLE001
                print(f"   не удалось прочитать ответ: {type(e2).__name__}: {e2}")
    if not org_id:
        print("\nОрганизация не найдена или формат другой — пришли этот вывод.")
        return
    url = f"https://bo.nalog.ru/nbo/organizations/{org_id}/bfo/"
    try:
        st, data = get_json(url)
        reps = data if isinstance(data, list) else data.get("content", [])
        print(f"\nOK {st} {url}: отчётов {len(reps)}")
        for r in reps[:3]:
            print(f"   период {r.get('period')} · id {r.get('id')} · ключи {list(r)[:10]}")
        if reps:
            rep = reps[0]
            corr = (rep.get("typeCorrections") or [{}])[0].get("correction", {}) if isinstance(rep, dict) else {}
            bal = corr.get("balance") or {}
            fin = corr.get("financialResult") or {}
            print(f"   баланс, строк {len(bal)}: пример {dict(list(bal.items())[:6])}")
            print(f"   отчёт о фин. результатах, строк {len(fin)}: пример {dict(list(fin.items())[:6])}")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {url} -> {type(e).__name__}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("moex", "girbo"):
        print(__doc__)
        sys.exit(1)
    {"moex": cmd_moex, "girbo": cmd_girbo}[sys.argv[1]](sys.argv[2])
