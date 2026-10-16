#!/usr/bin/env python3
"""Изучить официальный сайт компании: о компании, флот, маршруты, пресс-центр, раскрытие отчётности → sites/<ИНН>/.

  python3 sitecrawl.py run  [ИНН]      обойти сайты (все из company_sources.json или один) → sites/<ИНН>/summary.md
  python3 sitecrawl.py show <ИНН>      сводка по сайту компании (её читает Ави для справки)

Бережно к сайтам и серверу: не больше 25 страниц на сайт, 1 запрос в секунду, соблюдаются запреты robots.txt,
страницы больше 2 МБ не читаются. Запуск — раз в неделю ночью (расписание), справка берёт уже сохранённое.
Отчётность в PDF не скачивается автоматически: ссылки на неё перечислены в сводке, разбор — навыком pdf-read.
"""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "sites"
SOURCES = BASE / "company_sources.json"
UA = "Mozilla/5.0 (AviationMonitor/1.0; +research)"
MAX_PAGES, PAUSE, MAX_BYTES = 25, 1.0, 2_000_000

# разделы, которые ищем на сайте: (название, слова в адресе или тексте ссылки)
SECTIONS = [
    ("О компании", ["о компании", "о нас", "about", "company", "history", "история"]),
    ("Флот", ["флот", "парк", "fleet", "воздушные суда", "самолёт", "самолет", "вертол"]),
    ("Маршруты и география", ["маршрут", "направлен", "география", "route", "destinations", "расписание", "schedule"]),
    ("Пресс-центр и новости", ["новост", "пресс", "news", "press", "media"]),
    ("Раскрытие информации и отчётность", ["раскрыти", "отчет", "отчёт", "disclosure", "investor", "инвестор",
                                           "акционер", "shareholder", "бухгалтер", "финанс"]),
    ("Руководство и структура", ["руководств", "management", "дирекц", "структур", "совет директоров"]),
    ("Закупки и тендеры", ["закупк", "тендер", "procurement", "purchase"]),
    ("Услуги и деятельность", ["услуг", "services", "деятельност", "санитар", "авиаработ", "пассажир", "грузов"]),
]
DATE = re.compile(r"\b(\d{1,2}[./]\d{1,2}[./]20\d{2}|\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
                  r"сентября|октября|ноября|декабря)\s+20\d{2})")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        ctype = r.headers.get("Content-Type", "")
        raw = r.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("страница больше 2 МБ")
        enc = re.search(r"charset=([\w-]+)", ctype)
        return raw.decode(enc.group(1) if enc else "utf-8", "replace"), r.geturl(), ctype


def text_of(page):
    page = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</tr>|</div>", "\n", page)
    t = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [" ".join(x.split()) for x in t.splitlines()]
    return "\n".join(x for x in lines if len(x) > 2)


def links_of(page, base):
    out = []
    for m in re.finditer(r"(?is)<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", page):
        href = urllib.parse.urljoin(base, html.unescape(m.group(1)).strip())
        label = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())[:80]
        out.append((href, label))
    return out


def section_of(url, label):
    s = f"{urllib.parse.unquote(url)} {label}".lower()
    for name, words in SECTIONS:
        if any(w in s for w in words):
            return name
    return None


def crawl(company, site):
    site = site if site.startswith("http") else "https://" + site
    host = urllib.parse.urlparse(site).netloc.removeprefix("www.")
    robots = urllib.robotparser.RobotFileParser()
    try:
        robots.set_url(urllib.parse.urljoin(site, "/robots.txt"))
        robots.read()
    except Exception:  # noqa: BLE001 — нет robots.txt: обходим как обычно
        robots = None
    queue, seen, pages, pdfs = [(site, "Главная", "главная")], set(), [], {}
    while queue and len(pages) < MAX_PAGES:
        url, section, label = queue.pop(0)
        url = url.split("#")[0]
        if url in seen or (robots and not robots.can_fetch(UA, url)):
            continue
        seen.add(url)
        try:
            page, final, ctype = fetch(url)
        except Exception as e:  # noqa: BLE001
            pages.append({"url": url, "section": section, "error": f"{type(e).__name__}"})
            continue
        finally:
            time.sleep(PAUSE)
        if "html" not in ctype:
            continue
        txt = text_of(page)
        pages.append({"url": final, "section": section, "label": label, "text": txt[:20000],
                      "dates": DATE.findall(txt)[:15]})
        for href, lab in links_of(page, final):
            p = urllib.parse.urlparse(href)
            if p.scheme not in ("http", "https") or p.netloc.removeprefix("www.") != host:
                continue
            if href.lower().split("?")[0].endswith(".pdf"):
                pdfs.setdefault(href, lab or Path(p.path).name)
                continue
            sec = section_of(href, lab)
            # главная → разделы; внутри разделов берём их подстраницы (новости, документы), но не уходим в стороны
            if sec and href not in seen:
                queue.append((href, sec, lab))
        queue.sort(key=lambda q: [n for n, _ in SECTIONS].index(q[1]) if q[1] in [n for n, _ in SECTIONS] else 99)
    return pages, pdfs


def summary(company, inn, site, pages, pdfs):
    lines = [f"# Сайт компании: {company}", "",
             f"Сайт: {site} · ИНН {inn} · обойдено страниц: {len(pages)} · дата: {datetime.now():%d.%m.%Y}", ""]
    by = {}
    for p in pages:
        by.setdefault(p["section"], []).append(p)
    for name in ["Главная"] + [n for n, _ in SECTIONS]:
        items = [p for p in by.get(name, []) if p.get("text")]
        if not items:
            continue
        lines += [f"## {name}", ""]
        for p in items[:4]:
            lines.append(f"**{p.get('label') or name}** — [ссылка]({p['url']})")
            body = p["text"]
            # для новостей — строки с датами; для остальных разделов — начало содержательного текста
            if name == "Пресс-центр и новости":
                hits = [ln for ln in body.splitlines() if DATE.search(ln)][:12]
                body = "\n".join(f"- {ln[:300]}" for ln in hits) or body[:1200]
            else:
                body = "\n".join(ln for ln in body.splitlines() if len(ln) > 40)[:1500]
            lines += [body, ""]
    if pdfs:
        lines += ["## Документы PDF на сайте (отчётность, раскрытие)", ""]
        lines += [f"- {lab} — [ссылка]({url})" for url, lab in list(pdfs.items())[:30]]
        lines.append("")
    errors = [p for p in pages if p.get("error")]
    if errors:
        lines += ["## Не открылись", ""] + [f"- {p['url']} ({p['error']})" for p in errors[:10]]
    return "\n".join(lines)


def cmd_run(inn=None):
    if not SOURCES.exists():
        sys.exit("Нет company_sources.json — сначала links.py find → show → apply.")
    src = [s for s in json.loads(SOURCES.read_text(encoding="utf-8")) if s.get("site")]
    if inn:
        src = [s for s in src if s.get("inn") == inn]
    if not src:
        sys.exit("Нет компаний с сайтом для обхода.")
    for s in src:
        d = OUT / s["inn"]
        d.mkdir(parents=True, exist_ok=True)
        print(f"{s['company']}: {s['site']} …", flush=True)
        pages, pdfs = crawl(s["company"], s["site"])
        (d / "pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
        (d / "summary.md").write_text(summary(s["company"], s["inn"], s["site"], pages, pdfs), encoding="utf-8")
        found = sorted({p["section"] for p in pages if p.get("text")})
        print(f"  страниц {len(pages)}, разделы: {', '.join(found) or '—'}, PDF: {len(pdfs)} → {d / 'summary.md'}")


def cmd_show(inn):
    f = OUT / inn / "summary.md"
    if not f.exists():
        sys.exit(f"Сайт компании с ИНН {inn} ещё не изучен: python3 sitecrawl.py run {inn}")
    print(f.read_text(encoding="utf-8"))


if __name__ == "__main__":
    cmds = {"run": cmd_run, "show": cmd_show}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]](*sys.argv[2:3])
