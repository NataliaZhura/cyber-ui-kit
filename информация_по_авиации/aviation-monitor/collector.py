#!/usr/bin/env python3
"""Сборщик новостей авиарынка: RSS-ленты, поиск, Telegram-каналы -> архив SQLite.

Только стандартная библиотека Python 3.10+. Команды:
  check                         проверить, открывается ли каждый источник
  collect [--days N] [--all]    собрать свежие новости в архив (сайты и каналы компаний — раз в 3 часа или с --all)
  export --from D --to D        выгрузить новости за период, дубли склеены в один сюжет
  company "Ютэйр, UTair"        всё о компании или производителе за год (досбор + выгрузка)
  card "Аэрофлот" --from D --to D  карточка для инвестора: вывод, финансы, долг, имущество, суды
  export ... --new              ежедневная: только новое с прошлой выгрузки
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
from html.parser import HTMLParser
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
                regions = [r.strip() for r in (row.get("регион") or "").split(",") if r.strip()]
                subsidy = (row.get("зависит_от_субсидий") or "").strip().lower() in ("да", "yes", "1", "+")
                watch.append({"name": name, "aliases": [name] + aliases, "regions": regions, "subsidy": subsidy})
    # companies.csv — все компании из материалов владельца: узнаём их в новостях, но отдельный поиск
    # по каждой не запускаем (иначе +75 запросов за сбор на слабом сервере); поиск — только для watchlist
    known = {a.lower() for w in watch for a in w["aliases"]}
    cl = BASE / "companies.csv"
    if cl.exists():
        with cl.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                name = (row.get("компания") or "").strip()
                aliases = [a.strip() for a in (row.get("синонимы") or "").split(",") if len(a.strip()) > 3]
                if not name or any(x.lower() in known for x in [name] + aliases):
                    continue  # уже есть в watchlist (там же и поиск по ней)
                watch.append({"name": name, "aliases": [name] + aliases, "regions": [], "subsidy": False,
                              "search": False})
    # официальные сайты и Telegram-каналы компаний (links.py apply) — свои посты компании
    cs = BASE / "company_sources.json"
    cfg["company_sources"] = json.loads(cs.read_text(encoding="utf-8")) if cs.exists() else []
    cfg["_own"] = {}
    for s in cfg["company_sources"]:
        if s.get("telegram"):
            cfg["_own"][f"TG @{s['telegram']}"] = s["company"]
        if s.get("rss") or s.get("site"):
            cfg["_own"][f"Сайт {s['company']}"] = s["company"]
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


class TgParser(HTMLParser):
    """Публичная веб-лента канала t.me/s/<канал>: текст поста, дата, ссылка."""

    def __init__(self):
        super().__init__()
        self.posts, self.cur, self.depth = [], None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if "data-post" in a:
            self.cur = {"post": a["data-post"], "text": [], "date": None}
            self.posts.append(self.cur)
        elif self.cur is not None and "tgme_widget_message_text" in cls and not self.depth:
            self.depth = 1
        elif self.depth and tag == "div":
            self.depth += 1
            self.cur["text"].append(" ")
        elif self.depth and tag == "br":
            self.cur["text"].append("\n")
        elif self.depth:
            self.cur["text"].append(" ")
        if tag == "time" and self.cur is not None and a.get("datetime") and not self.cur["date"]:
            self.cur["date"] = a["datetime"]

    def handle_endtag(self, tag):
        if self.depth and tag == "div":
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.cur["text"].append(data)


def parse_tg(raw):
    p = TgParser()
    p.feed(raw.decode("utf-8", "replace"))
    items = []
    for post in p.posts:
        text = re.sub(r"[ \t]+", " ", "".join(post["text"])).strip()
        if not text:
            continue
        first = next((s.strip() for s in text.split("\n") if s.strip()), text)
        title = re.split(r"(?<=[.!?])\s", first)[0][:200]
        items.append((title, clean(text)[:1500], f"https://t.me/{post['post']}", parse_date(post["date"])))
    return items


def fetch_items(url):
    raw = fetch(url)
    return parse_tg(raw) if url.startswith("https://t.me/s/") else parse_feed(raw)


def title_key(title):
    t = re.sub(r"\s[-–—]\s[^-–—]{2,40}$", "", title.lower())  # хвост « - Интерфакс» у Google News
    return re.sub(r"[^a-zа-яё0-9]+", "", t)[:120]


def stem(region):
    """«Республика Саха (Якутия)» → «якути»: грубая основа, чтобы ловить «Якутии», «якутского»."""
    words = re.findall(r"[а-яё]+", region.lower())
    skip = {"республика", "край", "область", "автономный", "округ", "федеральный", "город", "саха"}
    main = [w for w in words if w not in skip] or words
    return max(main, key=len)[:-1] if main else region.lower()


def tag_item(title, summ, cfg, watch, source=""):
    low = f"{title} {summ}".lower()
    head = title.lower()
    ents = [w["name"] for w in watch if any(a.lower() in low for a in w["aliases"])]
    assets = [k for k, words in cfg["assets"].items() if any(x in low for x in words)]
    risks = [k for k, words in cfg["risks"].items() if any(x in low for x in words)]
    # про авиацию должен быть сам заголовок: упоминание мимоходом в тексте не считается
    avia = re.compile(r"(?<![а-яёa-z0-9])(?:" + "|".join(map(re.escape, cfg.get("aviation_words", []))) + ")")
    channel = source[4:] if source.startswith("TG @") else ""
    aviation = (channel in cfg.get("aviation_channels", [])  # профильный канал: Росавиация, Вертолёты России
                or any(a.lower() in head for w in watch for a in w["aliases"])
                or any(x in head for words in cfg["assets"].values() for x in words)
                or avia.search(head)
                # санкции важны для любой отрасли, даже если авиация в заголовке не названа
                or any(x in head for x in cfg.get("always_relevant", []))
                # бюджет региона, где летает компания на субсидиях
                or (any(x in low for x in cfg.get("budget_words", []))
                    and any(stem(r) in head for w in watch if w.get("subsidy") for r in w["regions"])))
    # военные сводки про дроны и ПВО — не про рынок; оставляем, только если задета гражданская авиация
    if aviation and any(x in head for x in cfg.get("military_words", [])):
        aviation = (channel in cfg.get("aviation_channels", [])  # профильный канал: Росавиация, Вертолёты России
                    or any(a.lower() in head for w in watch for a in w["aliases"])
                    or any(x in head for x in cfg.get("civil_override", [])))
    score = 1 + 3 * len(ents) + 3 * len(risks) + len(assets) if aviation else 0
    own = cfg.get("_own", {}).get(source)
    if own:
        # пост в канале / на сайте самой компании: компания — его герой, даже если не названа.
        # Балл без «+3 за компанию»: акции и реклама не проходят порог справки, суды/допуск/простой — проходят
        ents = [own] + [x for x in ents if x != own]
        score = 1 + 3 * len(risks) + len(assets)
    return ents, assets, risks, score


def domain(url):
    return urllib.parse.urlparse(url if "//" in url else "https://" + url).netloc.removeprefix("www.")


def feeds(cfg, watch, companies=True):
    if companies:  # сайты и каналы компаний — раз в 3 часа (см. cmd_collect), чтобы не грузить слабый сервер
        for s in cfg.get("company_sources", []):
            if s.get("telegram"):
                yield f"TG @{s['telegram']}", f"https://t.me/s/{s['telegram']}"
            if s.get("rss"):
                yield f"Сайт {s['company']}", s["rss"]
            elif s.get("site"):
                yield f"Сайт {s['company']}", GNEWS.format(q=urllib.parse.quote(f"site:{domain(s['site'])}"))
    for s in cfg["feeds"]:
        yield s["name"], s["url"]
    for q in cfg.get("search_topics", []):
        yield f"Поиск: {q}", GNEWS.format(q=urllib.parse.quote(q))
    for w in watch:
        if not w.get("search", True):
            continue
        q = " OR ".join(f'"{a}"' for a in w["aliases"][:4])
        yield f"Поиск: {w['name']}", GNEWS.format(q=urllib.parse.quote(q))
    regions = {r for w in watch if w.get("subsidy") for r in w["regions"]}
    for r in sorted(regions):
        for q in cfg.get("region_queries", []):
            q = q.format(region=r)
            yield f"Поиск: {q}", GNEWS.format(q=urllib.parse.quote(q))
    for ch in cfg.get("telegram", []):
        ch = ch.strip().lstrip("@").replace("https://t.me/", "").strip("/")
        if ch:
            yield f"TG @{ch}", f"https://t.me/s/{ch}"


def cmd_check(_):
    cfg, watch = load_config()
    ok = 0
    total = 0
    for name, url in feeds(cfg, watch):
        total += 1
        try:
            n = len(fetch_items(url))
            print(f"OK    {n:4d} шт.  {name}")
            ok += 1
        except Exception as e:  # noqa: BLE001 — для диагностики важна любая причина
            print(f"FAIL  {name}  {url}  -> {type(e).__name__}: {e}")
    print(f"\nРаботают {ok} из {total} источников")


def store(con, cfg, watch, name, items, since):
    now = datetime.now(MSK).isoformat(timespec="seconds")
    added = 0
    for title, summ, link, pub in items:
        if pub and pub < since:
            continue
        tk = title_key(title)
        if con.execute("SELECT 1 FROM news WHERE title_key=?", (tk,)).fetchone():
            continue
        ents, assets, risks, score = tag_item(title, summ, cfg, watch, name)
        src = name if not name.startswith("Поиск:") else re.split(r"\s[-–—]\s", title)[-1]
        cur = con.execute(
            "INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (hashlib.sha1(link.encode()).hexdigest(), tk,
             (pub or datetime.now(MSK)).isoformat(timespec="seconds"), now,
             src, title, summ, link, ", ".join(ents), ", ".join(assets),
             ", ".join(risks), score))
        added += cur.rowcount
    return added


def cmd_collect(a):
    cfg, watch = load_config()
    con = db()
    since = datetime.now(MSK) - timedelta(days=a.days)
    added = errors = 0
    companies = datetime.now(MSK).hour % 3 == 0 or getattr(a, "all", False)
    for name, url in feeds(cfg, watch, companies):
        try:
            items = fetch_items(url)
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        added += store(con, cfg, watch, name, items, since)
    con.commit()
    print(f"Добавлено новых: {added}; источников с ошибкой: {errors}")


SYNONYMS = [(r"sukhoi\s*superjet[\s-]*100|superjet[\s-]*100|суперджет[\s-]*100|ssj[\s-]*100|sj[\s-]*100|ссж[\s-]*100", " ssj100 "),
            (r"мс[\s-]*21|mc[\s-]*21", " мс21 "), (r"ил[\s-]*114", " ил114 ")]
STOP = {"году", "года", "годы", "лет", "году", "россии", "россия", "российск", "млн", "млрд", "руб", "рублей",
        "компан", "котор", "будет", "может", "также", "после", "заяви", "сообщ", "для", "что", "это", "как"}


def story_tokens(title, summ):
    t = re.sub(r"\s[-–—]\s[^-–—]{2,40}$", "", title.lower())
    t = f"{t} {' '.join(summ.lower().split()[:25])}"
    for pat, rep in SYNONYMS:
        t = re.sub(pat, rep, t)
    words = re.findall(r"[a-zа-яё0-9]+", t)
    return {w[:5] for w in words if (len(w) >= 3 or w.isdigit()) and w[:5] not in STOP}


def group_stories(rows):
    """Склеивает одну и ту же новость из разных источников: общая часть слов ≥ 50% и ≥ 3 слов, разница ≤ 2 дней."""
    groups = []
    money = re.compile(r"(\d+(?:[.,]\d+)?)\s*(трлн|млрд|млн)", re.I)
    for r in rows:  # rows уже отсортированы по важности — первая в группе самая сильная
        tok = story_tokens(r[2], r[3])
        day = datetime.fromisoformat(r[0])
        amt = {m.group(0).lower().replace(",", ".") for m in money.finditer(r[2])}
        for g in groups:
            common = len(tok & g["tok"])
            if amt and g["amt"] and not (amt & g["amt"]):
                continue  # разные суммы в заголовках — разные события (два выпуска облигаций, два иска)
            if (common >= 3 and common / max(1, min(len(tok), len(g["tok"]))) >= 0.5
                    and abs((day - g["day"]).total_seconds()) <= 2 * 86400):
                g["also"].append(r)
                break
        else:
            groups.append({"main": r, "tok": tok, "day": day, "amt": amt, "also": []})
    return groups


def apply_threads(groups, cfg):
    """Сквозные сюжеты: все сюжеты одной темы (МС-21, ремонт двигателей…) — один пункт с хронологией."""
    out, threads = [], {}
    for g in groups:
        head = g["main"][2].lower()
        th = next((t["name"] for t in cfg.get("threads", []) if any(w in head for w in t["words"])), None)
        if not th:
            out.append(g)
            continue
        if th not in threads:
            threads[th] = {"thread": th, "items": [], "also": []}
            out.append(threads[th])
        threads[th]["items"].append(g)
    for name, t in list(threads.items()):
        if len(t["items"]) == 1:  # одна новость — не сюжет, показываем как обычную
            out[out.index(t)] = t["items"][0]
            del threads[name]
    for t in threads.values():
        t["items"].sort(key=lambda g: g["main"][0], reverse=True)       # хронология: свежее сверху
        best = max(t["items"], key=lambda g: g["main"][8])
        t["main"] = t["items"][0]["main"][:8] + (best["main"][8],)     # последний статус, приоритет — максимальный
        t["tok"], t["day"] = set(), None
    return out


def word_start(words):
    """Совпадение только с начала слова: «флот» не находится в «Аэрофлот», «списан» — в «расписание»."""
    return re.compile(r"(?<![а-яёa-z0-9])(?:" + "|".join(re.escape(w.strip()) for w in words if w.strip()) + ")")


def section_of(title, summ, cfg):
    """Раздел справки: первый подходящий по приоритету (суды → финансы → сделки → имущество → …)."""
    low = f"{title} {summ}".lower()
    head = title.lower()
    military = any(x in head for x in cfg.get("military_words", []))
    # атака дронов — это сбой перевозок, а не имущество в виде БПЛА
    pats = [(sec["name"], word_start(sec.get("words", []))) for sec in cfg["sections"]
            if not (military and sec["name"] == "Вертолёты и БПЛА")]
    for name, pat in pats:
        if pat.search(head):
            return name
    for name, pat in pats:  # в заголовке не нашлось — смотрим текст
        if pat.search(low):
            return name
    return "Прочее"


def clean_title(title):
    """Убирает хвост « - Forbes.ru», который добавляет поиск новостей."""
    return re.sub(r"\s[-–—]\s(?!.*\s[-–—]\s).{2,40}$", "", title).strip()


def useful_summary(title, summ):
    """Анонс показываем, только если он добавляет что-то к заголовку."""
    t, s = clean_title(title).lower(), (summ or "").lower().strip()
    return "" if not s or s.startswith(t[:60]) or t.startswith(s[:60]) else summ


def level(score):
    return ("высокий", "🔴") if score >= 7 else ("средний", "🟡") if score >= 4 else ("фон", "⚪")


def fmt_dt(iso):
    d = datetime.fromisoformat(iso).astimezone(MSK)
    return d.strftime("%d.%m.%Y %H:%M")


def fmt_d(s):
    return date.fromisoformat(s).strftime("%d.%m.%Y")


def render_md(meta, sections, out):
    p = functools.partial(builtins.print, file=out)
    p(f"# {meta['title']}")
    p(f"Период: {meta['period']} · Выгрузка: {meta['made']} МСК")
    p(f"Сюжетов: {meta['n_groups']} (публикаций: {meta['n_rows']}). Повторы из разных источников склеены.\n")
    for si, (name, items) in enumerate(sections, 1):
        p(f"## {si}. {name} — {len(items)}")
        if not items:
            p("Существенных новостей нет.\n")
            continue
        for ii, g in enumerate(items, 1):
            pub, src, title, summ, url, ents, assets, risks, score = g["main"]
            lv = level(score)
            if g.get("thread"):
                p(f"### {si}.{ii}. {lv[1]} Сюжет «{g['thread']}» — {len(g['items'])} новостей, последняя:")
            p(f"{'' if g.get('thread') else f'### {si}.{ii}. {lv[1]} '}{title}" if not g.get("thread") else f"- {title}")
            p(f"- {fmt_dt(pub)} · {src} · приоритет: {lv[0]} ({score})")
            for h in g.get("items", [])[1:6]:
                p(f"  - ранее {fmt_dt(h['main'][0])}: {h['main'][2]} — {h['main'][4]}")
            if useful_summary(title, summ):
                p(f"- {summ[:600]}")
            p(f"- {url}")
            if g["also"]:
                p(f"- также писали ({len(g['also'])}): " + "; ".join(f"{r[1]} {r[4]}" for r in g["also"][:5]))
            p()


HTML_CSS = """
:root{--ink:#1b1f24;--muted:#5f6b7a;--line:#d9dee5;--bg:#ffffff;--soft:#f4f6f9;--accent:#0b4f8a;
--red:#b42318;--amber:#b54708;--grey:#667085}
@media (prefers-color-scheme: dark){:root{--ink:#e6e9ee;--muted:#9aa4b2;--line:#323843;--bg:#16191e;--soft:#1e232a;--accent:#7cb4ec;
--red:#f97066;--amber:#fdb022;--grey:#98a2b3}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Segoe UI",Arial,sans-serif}
main{max-width:920px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:24px;margin:0 0 6px}
.meta{color:var(--muted);font-size:13px;display:flex;flex-wrap:wrap;gap:4px 18px;margin-bottom:18px}
.meta b{color:var(--ink);font-weight:600}
.legend{font-size:12px;color:var(--muted);margin:-8px 0 18px}
nav{background:var(--soft);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin-bottom:26px}
nav ol{margin:0;padding-left:22px;columns:2;column-gap:28px}
nav li{margin:2px 0}
nav a{color:var(--accent);text-decoration:none}
nav .n{color:var(--muted)}
h2{font-size:18px;margin:30px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--accent)}
h2 .n{color:var(--muted);font-weight:400}
.empty{color:var(--muted);font-style:italic;margin:6px 0 0}
article{border-left:4px solid var(--grey);padding:8px 0 8px 14px;margin:0 0 14px}
article.hi{border-color:var(--red)} article.mid{border-color:var(--amber)}
.num{font-weight:700;color:var(--muted);margin-right:6px;font-variant-numeric:tabular-nums}
h3{font-size:15.5px;margin:0 0 4px;font-weight:600}
h3 a{color:var(--ink);text-decoration:none} h3 a:hover{text-decoration:underline}
.line{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.tag{display:inline-block;font-size:11.5px;padding:0 7px;border-radius:9px;margin-left:6px;border:1px solid currentColor}
.tag.hi{color:var(--red)} .tag.mid{color:var(--amber)} .tag.lo{color:var(--grey)}
.sum{margin:5px 0 0;font-size:14px}
.also{margin:5px 0 0;font-size:12.5px;color:var(--muted)}
.also a{color:var(--accent)}
.thread{font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--accent);font-weight:600;margin-bottom:2px}
details.also summary{cursor:pointer} details.also ul{margin:4px 0 0;padding-left:18px}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0 14px;font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:right}
th:first-child,td:first-child{text-align:left}
thead th{background:var(--soft);font-weight:600}
td.calc{color:var(--accent)}
.cap{font-size:12.5px;color:var(--muted);margin:0 0 4px}
.lights{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 4px}
.light{border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:13px;background:var(--soft)}
.box{border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:8px 0 6px;background:var(--soft)}
.big{font-size:17px;font-weight:600}
ol.plain{list-style:none;padding:0;margin:4px 0 8px} ol.plain li{margin:0 0 7px;padding-left:0}
ol.plain a{color:var(--ink)} .line{color:var(--muted)}
footer{margin-top:36px;font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:10px}
@media print{nav{break-after:page} article{break-inside:avoid} a{color:inherit}}
@media (max-width:600px){nav ol{columns:1}}
"""


def render_html(meta, sections, out):
    e = html.escape
    w = out.write
    w(f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
      f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(meta['title'])}</title>"
      f"<style>{HTML_CSS}</style></head><body><main>")
    w(f"<h1>{e(meta['title'])}</h1><div class='meta'>"
      f"<span>Период: <b>{e(meta['period'])}</b></span>"
      f"<span>Выгрузка: <b>{e(meta['made'])} МСК</b></span>"
      f"<span>Сюжетов: <b>{meta['n_groups']}</b> (публикаций: {meta['n_rows']})</span></div>")
    w("<div class='legend'>Приоритет рассчитан по ключевым словам и служит для сортировки, "
      "это не оценка кредитного риска. 🔴 высокий · 🟡 средний · ⚪ фон. "
      "Одна новость из разных источников показана один раз.</div>")
    w("<nav><ol>")
    for si, (name, items) in enumerate(sections, 1):
        w(f"<li><a href='#s{si}'>{e(name)}</a> <span class='n'>— {len(items)}</span></li>")
    w("</ol></nav>")
    for si, (name, items) in enumerate(sections, 1):
        if name == "Прочее" and items:
            w(f"<h2 id='s{si}'>{si}. {e(name)} <span class='n'>· {len(items)}</span></h2>"
              "<details><summary>Новости без явного отношения к рискам — открыть</summary>")
        else:
            w(f"<h2 id='s{si}'>{si}. {e(name)} <span class='n'>· {len(items)}</span></h2>")
        if not items:
            w("<p class='empty'>Существенных новостей нет.</p>")
            continue
        for ii, g in enumerate(items, 1):
            pub, src, title, summ, url, ents, assets, risks, score = g["main"]
            lv = level(score)
            cls = {"высокий": "hi", "средний": "mid"}.get(lv[0], "lo")
            w(f"<article class='{cls}'>")
            if g.get("thread"):
                w(f"<div class='thread'>Сюжет «{e(g['thread'])}» · {len(g['items'])} новостей за период</div>")
            w(f"<h3><span class='num'>{si}.{ii}</span>"
              f"<a href='{e(url)}' target='_blank' rel='noopener'>{e(clean_title(title))}</a></h3>")
            w(f"<div class='line'>{e(fmt_dt(pub))} · {e(src)}"
              f"<span class='tag {cls}'>{lv[1]} {e(lv[0])}</span></div>")
            if useful_summary(title, summ):
                w(f"<p class='sum'>{e(summ[:600])}</p>")
            if g.get("items", [])[1:]:
                w("<details class='also'><summary>Хронология сюжета</summary><ul>" + "".join(
                    f"<li>{e(fmt_dt(h['main'][0]))} — <a href='{e(h['main'][4])}' target='_blank' rel='noopener'>"
                    f"{e(h['main'][2])}</a></li>" for h in g["items"][1:12]) + "</ul></details>")
            if g["also"]:
                links = ", ".join(f"<a href='{e(r[4])}' target='_blank' rel='noopener'>{e(r[1])}</a>"
                                  for r in g["also"][:8])
                w(f"<p class='also'>Также писали ({len(g['also'])}): {links}</p>")
            w("</article>")
        if name == "Прочее" and items:
            w("</details>")
    w(f"<footer>Источники: открытые СМИ, сайты ведомств, поиск новостей, публичные Telegram-каналы. "
      f"Каждый факт проверяйте по ссылке на первоисточник. Сформировано {e(meta['made'])} МСК.</footer>")
    w("</main></body></html>")


def build(a, cfg):
    """Отбор, склейка дублей, сквозные сюжеты и раскладка по разделам — общее для справки и карточки."""
    con = db()
    d_to = (date.fromisoformat(a.date_to) + timedelta(days=1)).isoformat()
    names = [n.strip() for n in (a.entity or "").split(",") if n.strip()]
    rows = con.execute(
        "SELECT published, source, title, summary, url, entities, assets, risks, score, collected FROM news "
        "WHERE published >= ? AND published < ? AND (score >= ? OR ?) ORDER BY score DESC, published DESC",
        (a.date_from, d_to, a.min_score, bool(names))).fetchall()
    if names:  # по выбранной компании её новости важны, даже если в заголовке нет слов про авиацию
        _, watch = load_config()
        watch = watch + [{"name": names[0], "aliases": names, "regions": [], "subsidy": False}]
        low = [n.lower() for n in names]
        rows = [r[:5] + tuple(", ".join(x) if i < 3 else x for i, x in enumerate(tag_item(r[2], r[3], cfg, watch, r[1])))
                + (r[9],) for r in rows if any(n in f"{r[2]} {r[3]}".lower() for n in low)]
        rows = sorted((r for r in rows if r[8] >= a.min_score), key=lambda r: (r[8], r[0]), reverse=True)
    if getattr(a, "new", False):  # ежедневная: только то, что собрано после прошлой такой выгрузки
        state_path = BASE / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        mark = state.get(a.out or "screen", "")
        rows = [r for r in rows if r[9] > mark]
        state[a.out or "screen"] = datetime.now(MSK).isoformat(timespec="seconds")
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = [r[:9] for r in rows]
    groups = apply_threads(group_stories(rows), cfg)[:a.limit]
    order = [s["name"] for s in cfg["sections_display"]]
    buckets = {n: [] for n in order}
    for g in groups:
        sec = next((th.get("section") for th in cfg.get("threads", []) if th["name"] == g.get("thread")), None) \
            or section_of(g["main"][2], g["main"][3], cfg)
        buckets.setdefault(sec, []).append(g)
    for items in buckets.values():  # внутри раздела: сначала важнее, при равенстве — свежее
        items.sort(key=lambda g: (g["main"][8], g["main"][0]), reverse=True)
    sections = [(n, buckets[n]) for n in order] + [(n, v) for n, v in buckets.items() if n not in order]
    subject = a.entity.split(",")[0].strip() if a.entity else "Авиарынок"
    meta = {"title": f"{subject}: мониторинг новостей",
            "period": f"{fmt_d(a.date_from)} — {fmt_d(a.date_to)}",
            "made": datetime.now(MSK).strftime("%d.%m.%Y %H:%M"),
            "n_groups": len(groups), "n_rows": len(rows), "subject": subject}
    return meta, rows, groups, sections


def cmd_export(a):
    cfg, _ = load_config()
    meta, rows, groups, sections = build(a, cfg)
    if getattr(a, "new", False):
        meta["title"] = meta["title"].replace("мониторинг новостей", "новое с прошлой справки")
    if a.out:
        is_html = a.out.lower().endswith((".html", ".htm"))
        with open(a.out, "w", encoding="utf-8" if is_html else "utf-8-sig") as f:
            (render_html if is_html else render_md)(meta, sections, f)
        builtins.print(f"Сохранено: {len(groups)} сюжетов ({len(rows)} публикаций) → {a.out}")
    else:
        render_md(meta, sections, sys.stdout)


def cmd_company(a):
    """Досбор по любой компании или производителю и выгрузка всего, что о ней есть в архиве."""
    cfg, watch = load_config()
    con = db()
    since = datetime.now(MSK) - timedelta(days=a.days)
    added = 0
    for name in [n.strip() for n in a.name.split(",") if n.strip()]:
        url = GNEWS.format(q=urllib.parse.quote(f'"{name}"'))
        try:
            added += store(con, cfg, watch, f"Поиск: {name}", fetch_items(url), since)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL поиск «{name}»: {type(e).__name__}: {e}", file=sys.stderr)
    con.commit()
    builtins.print(f"Дособрано новых публикаций: {added}")
    a.date_from = since.date().isoformat()
    a.date_to = datetime.now(MSK).date().isoformat()
    a.entity = a.name
    a.min_score = 0
    cmd_export(a)


def cmd_rescore(_):
    cfg, watch = load_config()
    con = db()
    rows = con.execute("SELECT id, title, summary, source FROM news").fetchall()
    for nid, title, summ, src in rows:
        ents, assets, risks, score = tag_item(title, summ, cfg, watch, src)
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
    c.add_argument("--all", action="store_true", help="опросить и сайты/каналы компаний вне 3-часового окна")
    c.set_defaults(fn=cmd_collect)
    e = sub.add_parser("export")
    e.add_argument("--from", dest="date_from", required=True, help="ГГГГ-ММ-ДД")
    e.add_argument("--to", dest="date_to", required=True, help="ГГГГ-ММ-ДД включительно")
    e.add_argument("--min-score", type=int, default=0)
    e.add_argument("--entity", default="")
    e.add_argument("--limit", type=int, default=300)
    e.add_argument("--out", default="", help="файл .html (для чтения) или .md (для агента)")
    e.add_argument("--new", action="store_true", help="только новое с прошлой выгрузки в этот же файл (ежедневная)")
    e.set_defaults(fn=cmd_export)
    co = sub.add_parser("company", help="всё о компании: досбор из поиска + выгрузка из архива")
    co.add_argument("name", help="название, можно несколько через запятую: \"Ютэйр, UTair\"")
    co.add_argument("--days", type=int, default=365)
    co.add_argument("--limit", type=int, default=300)
    co.add_argument("--out", default="")
    co.set_defaults(fn=cmd_company)
    k = sub.add_parser("card", help="карточка компании для инвестора (HTML): вывод, финансы, долг, имущество, суды")
    k.add_argument("entity", help="название и синонимы через запятую: \"Аэрофлот, Aeroflot\"")
    k.add_argument("--from", dest="date_from", required=True)
    k.add_argument("--to", dest="date_to", required=True)
    k.add_argument("--min-score", type=int, default=1)
    k.add_argument("--limit", type=int, default=500)
    k.add_argument("--summary", default="", help="файл с текстом вывода (пишет агент)")
    k.add_argument("--moex", default="", help="как искать облигации на Мосбирже (по умолчанию — первое название)")
    k.add_argument("--no-moex", action="store_true", help="не запрашивать Мосбиржу")
    k.add_argument("--out", default="")
    k.set_defaults(fn=lambda a: __import__("card").cmd_card(a))
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    sub.add_parser("rescore", help="пересчитать метки и баллы архива после правки sources.json").set_defaults(fn=cmd_rescore)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
