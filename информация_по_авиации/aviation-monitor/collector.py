#!/usr/bin/env python3
"""Сборщик новостей авиарынка: RSS-ленты + поиск по списку компаний -> архив SQLite.

Только стандартная библиотека Python 3.10+. Команды:
  check                         проверить, открывается ли каждый источник
  collect [--days N]            собрать свежие новости в архив
  export --from D --to D        выгрузить новости за период (для справки агента)
  stats                         сколько новостей в архиве по месяцам
  rescore                       пересчитать баллы архива после правки ключевых слов
"""
import argparse
import builtins
import csv
import email.utils
import functools
import hashlib
import html
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
MSK = timezone(timedelta(hours=3))
UA = "Mozilla/5.0 (X11; Linux x86_64) AviationMonitor/1.0"
GNEWS = "https://news.google.com/rss/search?q={q}&hl=ru&gl=RU&ceid=RU:ru"


def load_config():
    cfg = json.loads((BASE / "sources.json").read_text(encoding="utf-8"))
    watch = []
    wl = BASE / "watchlist.csv"
    if wl.exists():
        with wl.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                name = (row.get("компания") or "").strip()
                if not name:
                    continue
                aliases = [a.strip() for a in (row.get("синонимы") or "").split(",") if a.strip()]
                watch.append({"name": name, "aliases": [name] + aliases})
    return cfg, watch


def db():
    con = sqlite3.connect(BASE / "archive.db")
    con.execute("""CREATE TABLE IF NOT EXISTS news(
        id TEXT PRIMARY KEY, title_key TEXT, published TEXT, collected TEXT,
        source TEXT, title TEXT, summary TEXT, url TEXT,
        entities TEXT, assets TEXT, risks TEXT, score INTEGER)""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pub ON news(published)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_tk ON news(title_key)")
    return con


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=MSK)
    return d.astimezone(MSK)


def parse_feed(raw):
    """RSS 2.0 и Atom -> список (title, summary, url, published)."""
    root = ET.fromstring(raw)
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = {c.tag.split("}")[-1]: c for c in it}
        title = clean(get["title"].text if "title" in get else "")
        link = ""
        if "link" in get:
            link = get["link"].text or get["link"].get("href", "")
        summ = ""
        for k in ("description", "summary", "content"):
            if k in get and get[k].text:
                summ = clean(get[k].text)
                break
        pub = None
        for k in ("pubDate", "published", "updated", "date"):
            if k in get:
                pub = parse_date(get[k].text)
                if pub:
                    break
        if title and link:
            items.append((title, summ[:1500], link.strip(), pub))
    return items


def title_key(title):
    t = re.sub(r"\s[-–—]\s[^-–—]{2,40}$", "", title.lower())  # хвост « - Интерфакс» у Google News
    return re.sub(r"[^a-zа-яё0-9]+", "", t)[:120]


def tag_item(title, summ, cfg, watch):
    low = f"{title} {summ}".lower()
    head = title.lower()
    ents = [w["name"] for w in watch if any(a.lower() in low for a in w["aliases"])]
    assets = [k for k, words in cfg["assets"].items() if any(x in low for x in words)]
    risks = [k for k, words in cfg["risks"].items() if any(x in low for x in words)]
    # про авиацию должен быть сам заголовок: упоминание мимоходом в тексте не считается
    avia = re.compile(r"(?<![а-яёa-z0-9])(?:" + "|".join(map(re.escape, cfg.get("aviation_words", []))) + ")")
    aviation = (any(a.lower() in head for w in watch for a in w["aliases"])
                or any(x in head for words in cfg["assets"].values() for x in words)
                or avia.search(head))
    score = 1 + 3 * len(ents) + 3 * len(risks) + len(assets) if aviation else 0
    return ents, assets, risks, score


def feeds(cfg, watch):
    for s in cfg["feeds"]:
        yield s["name"], s["url"]
    for q in cfg.get("search_topics", []):
        yield f"Поиск: {q}", GNEWS.format(q=urllib.parse.quote(q))
    for w in watch:
        q = " OR ".join(f'"{a}"' for a in w["aliases"][:4])
        yield f"Поиск: {w['name']}", GNEWS.format(q=urllib.parse.quote(q))


def cmd_check(_):
    cfg, watch = load_config()
    ok = 0
    total = 0
    for name, url in feeds(cfg, watch):
        total += 1
        try:
            n = len(parse_feed(fetch(url)))
            print(f"OK    {n:4d} шт.  {name}")
            ok += 1
        except Exception as e:  # noqa: BLE001 — для диагностики важна любая причина
            print(f"FAIL  {name}  {url}  -> {type(e).__name__}: {e}")
    print(f"\nРаботают {ok} из {total} источников")


def cmd_collect(a):
    cfg, watch = load_config()
    con = db()
    since = datetime.now(MSK) - timedelta(days=a.days)
    now = datetime.now(MSK).isoformat(timespec="seconds")
    added = errors = 0
    for name, url in feeds(cfg, watch):
        try:
            items = parse_feed(fetch(url))
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        for title, summ, link, pub in items:
            if pub and pub < since:
                continue
            tk = title_key(title)
            if con.execute("SELECT 1 FROM news WHERE title_key=?", (tk,)).fetchone():
                continue
            ents, assets, risks, score = tag_item(title, summ, cfg, watch)
            src = name if not name.startswith("Поиск:") else re.split(r"\s[-–—]\s", title)[-1]
            cur = con.execute(
                "INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (hashlib.sha1(link.encode()).hexdigest(), tk,
                 (pub or datetime.now(MSK)).isoformat(timespec="seconds"), now,
                 src, title, summ, link, ", ".join(ents), ", ".join(assets),
                 ", ".join(risks), score))
            added += cur.rowcount
    con.commit()
    print(f"Добавлено новых: {added}; источников с ошибкой: {errors}")


def cmd_export(a):
    con = db()
    d_from = a.date_from
    d_to = (date.fromisoformat(a.date_to) + timedelta(days=1)).isoformat()
    sql = "SELECT published, source, title, summary, url, entities, assets, risks, score FROM news " \
          "WHERE published >= ? AND published < ? AND score >= ?"
    args = [d_from, d_to, a.min_score]
    if a.entity:
        sql += " AND (entities LIKE ? OR title LIKE ? OR summary LIKE ?)"
        args += [f"%{a.entity}%"] * 3
    sql += " ORDER BY score DESC, published DESC LIMIT ?"
    args.append(a.limit)
    rows = con.execute(sql, args).fetchall()
    out = open(a.out, "w", encoding="utf-8-sig") if a.out else sys.stdout
    print = functools.partial(builtins.print, file=out)  # noqa: A001 — пишем в файл или на экран
    print(f"# Новости {a.date_from} — {a.date_to}: {len(rows)} шт. (отсортированы по важности)\n")
    for pub, src, title, summ, url, ents, assets, risks, score in rows:
        print(f"## [{score}] {title}")
        print(f"- дата: {pub[:16].replace('T', ' ')} | источник: {src}")
        if ents or assets or risks:
            print(f"- компании: {ents or '—'} | активы: {assets or '—'} | риски: {risks or '—'}")
        if summ:
            print(f"- кратко: {summ[:600]}")
        print(f"- ссылка: {url}\n")
    if a.out:
        out.close()
        builtins.print(f"Сохранено {len(rows)} новостей в файл {a.out}")


def cmd_rescore(_):
    cfg, watch = load_config()
    con = db()
    rows = con.execute("SELECT id, title, summary FROM news").fetchall()
    for nid, title, summ in rows:
        ents, assets, risks, score = tag_item(title, summ, cfg, watch)
        con.execute("UPDATE news SET entities=?, assets=?, risks=?, score=? WHERE id=?",
                    (", ".join(ents), ", ".join(assets), ", ".join(risks), score, nid))
    con.commit()
    print(f"Пересчитано новостей: {len(rows)}")


def cmd_stats(_):
    con = db()
    for m, n, hi in con.execute(
            "SELECT substr(published,1,7), count(*), sum(score>=5) FROM news GROUP BY 1 ORDER BY 1"):
        print(f"{m}: всего {n}, важных (балл ≥5) {hi}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    c = sub.add_parser("collect")
    c.add_argument("--days", type=int, default=3)
    c.set_defaults(fn=cmd_collect)
    e = sub.add_parser("export")
    e.add_argument("--from", dest="date_from", required=True, help="ГГГГ-ММ-ДД")
    e.add_argument("--to", dest="date_to", required=True, help="ГГГГ-ММ-ДД включительно")
    e.add_argument("--min-score", type=int, default=0)
    e.add_argument("--entity", default="")
    e.add_argument("--limit", type=int, default=300)
    e.add_argument("--out", default="", help="записать в файл (UTF-8) вместо вывода на экран")
    e.set_defaults(fn=cmd_export)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    sub.add_parser("rescore", help="пересчитать метки и баллы архива после правки sources.json").set_defaults(fn=cmd_rescore)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
