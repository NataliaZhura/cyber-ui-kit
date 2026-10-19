#!/usr/bin/env python3
"""Сводка рынка для ЖДуши: все цифры рынка в одном файле, собирается программой (0 токенов) после каждого сбора новостей.
Бот отвечает на /poluvagony, /krytye, /rates, /loading, /balance, /market, /forecast по сводке, а не ищет заново:
меньше шагов и одни и те же проверенные цифры с датой и источником.

  python3 zmarket.py build                 обе сводки: saved/market/сводка_полувагоны.md и сводка_крытые.md
  python3 zmarket.py build --guest         то же для гостя → forecast/guest/ (без Argus и внутренних данных)
  python3 zmarket.py build --type gon      одна сводка (gon — полувагоны, kr — крытые)

В сводке: свежесть каждого блока (⚠ если данные устарели), ставки Argus (только владельцу), прогноз модели 2026–2030
(zmodel.py), светофор стоимости вагона (zvagon.py), показатели из новостей за 45 дней (погрузка, ставки, парк, цены,
уголь / стройка) — каждый со ссылкой, главные новости за 7 дней, точность прошлых прогнозов (zjournal.py).
"""
import argparse
import csv
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import collector  # noqa: E402

ARGUS = BASE / "private" / "argus" / "rates.csv"
TYPES = {"gon": ("полувагоны", r"полуваг"), "kr": ("крытые", r"крыт")}
NUM = re.compile(r"\d[\d\s,.]*\s*(%|проц|млн|млрд|тыс|руб|₽|т\b|тонн|ваг|ед\.)", re.I)
# Показатели из новостей: название → (слова в заголовке или анонсе, для каких типов)
INDICATORS = [
    ("Погрузка РЖД", r"погрузк", "gon kr"),
    ("Ставки аренды", r"ставк\w* (аренд|предоставлен|оперирован|на (полу)?ваг|на крыт)|руб\.?\s*/\s*сут|в сутки", "gon kr"),
    ("Парк: профицит, отстой, неисправные", r"профицит|дефицит ваг|отставлен|простаива|неисправн|избыт\w* парк", "gon kr"),
    ("Выпуск и списание вагонов", r"списан|выпуск\w* ваг|производств\w* (грузов\w* )?ваг|закупк\w* ваг|вагоностро", "gon kr"),
    ("Цены вагонов", r"(стоимост|цен)\w* (нов\w* |б/у )?(полу)?ваг|(полу)?вагон\w* (подешев|подорож)", "gon kr"),
    ("Уголь: добыча и экспорт", r"угол|угл[яеиь]", "gon"),
    ("Металлы и лом", r"металл|лом\b|стал[ьи]", "gon"),
    ("Стройка, щебень, цемент", r"щеб|строительн\w* груз|цемент|ввод\w* жиль|ипотек", "kr"),
    ("Зерно, ЦБП, ТНП", r"зерн|целлюлоз|бумаг|тнп|потребительск", "kr"),
]
STALE = {"news": 1, "argus": 45}  # дней: новости — сбор раз в 3 часа; Argus — ежемесячно


def ddmm(iso):
    return collector.fmt_dt(iso)[:10]


def news_rows(con, since):
    return con.execute("SELECT published, source, title, summary, url, score, title_key FROM news WHERE published >= ? "
                       "ORDER BY published DESC", (since,)).fetchall()


def indicators(rows, typ):
    """По каждому показателю — 3 последние новости с цифрой; дубли одного события (один заголовок) — один раз."""
    word, other = TYPES[typ][1], TYPES["kr" if typ == "gon" else "gon"][1]
    out = []
    for name, rx, types in INDICATORS:
        if typ not in types.split():
            continue
        seen, found = set(), []
        for pub, src, title, summ, url, score, tk in rows:
            text = f"{title} {summ or ''}"
            if tk in seen or not re.search(rx, text, re.I) or not NUM.search(text):
                continue
            if name in ("Ставки аренды", "Цены вагонов") and not re.search(word, text, re.I):
                continue  # ставка и цена — только своего типа вагона
            if re.search(other, text, re.I) and not re.search(word, text, re.I):
                continue  # новость только о другом типе вагона
            seen.add(tk)
            found.append(f"- {ddmm(pub)} · {src} · {collector.clean_title(title)} — [ссылка]({url})")
            if len(found) == 3:
                break
        out += [f"**{name}**"] + (found or ["- за 45 дней новостей с цифрами нет"]) + [""]
    return out


def argus_block(typ):
    """Последний выпуск Argus: строки своего типа вагона. Только владельцу."""
    if not ARGUS.exists():
        return ["Нет `private/argus/rates.csv` — выпуски Argus не разобраны (`~/pw/bin/python argus.py`).", ""]
    with ARGUS.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    if not rows:
        return ["В `rates.csv` нет строк.", ""]

    def as_date(s):
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(s.strip(), fmt).date()
            except ValueError:
                pass
        return date.min
    last = max(rows, key=lambda r: as_date(r["выпуск"]))["выпуск"]
    age = (date.today() - as_date(last)).days
    mine = [r for r in rows if r["выпуск"] == last and re.search(TYPES[typ][1], f"{r['таблица']} {r['показатель']}", re.I)]
    L = [f"Выпуск Argus от {last}" + (f" — ⚠ {age} дн. назад, новее нет" if age > STALE["argus"] else "") +
         ". Руб., без НДС. Только для внутреннего использования.", ""]
    if not mine:
        return L + [f"В выпуске нет ставок по типу «{TYPES[typ][0]}» (с 01.03.2026 Argus приостанавливал аналитику по РФ).", ""]
    L += ["| Показатель | Сейчас | Прошлый период | Стр. |", "|---|---|---|---|"]
    L += [f"| {r['показатель']} | {r['мин']}–{r['макс']} | {r['прошлый_мин']}–{r['прошлый_макс']} | {r['страница']} |"
          for r in mine[:15]]
    return L + [""]


def model_block(typ):
    """Прогноз ставок 2026–2030 (рабочая модель) и светофор стоимости вагона — те же цифры, что в /prognoz и /vagon."""
    try:
        import zmodel
        import zvagon
        D = zmodel.load()
    except SystemExit as e:
        return [f"Модель не загружена: {e}", ""]
    L = ["| Сценарий | " + " | ".join(str(y) for y in range(2026, 2031)) + " |", "|---|" + "---|" * 5]
    wag = ["gon", "inno"] if typ == "gon" else ["kr158"]
    names = {"gon": "обычный", "inno": "инновационный", "kr158": "крытый 158 м³"}
    for scen in ("base", "pess"):
        g = zmodel.forecast_one(D, "gon", D["default"]["gon"], scen, {})
        k = zmodel.forecast_one(D, "kr", D["default"]["kr"], scen, {}, gon_path=g["path"])
        rows = zmodel.paths(D, {"gon": g, "kr": k}, wag)
        for w in wag:
            L.append(f"| {names[w]}, {'базовый' if scen == 'base' else 'пессимистичный'} | " +
                     " | ".join(f"{round(rows[w][y]):,}".replace(",", " ") for y in range(2026, 2031)) + " |")
    L += ["", "₽ за вагон в сутки без НДС, рабочая модель /prognoz (ошибка модели — около ±25–35% в год).", ""]
    if typ == "gon":
        try:
            V = zvagon.load()
            sig, score = zvagon.signals(V)
            vd = zvagon.verdict(V, score)
            L += [f"Светофор стоимости вагона (/vagon): **{vd['title']}**, баллы {score:+d}, показатели на {V['as_of']}.", ""]
        except SystemExit as e:
            L += [f"Светофор: {e}", ""]
    return L


def journal_block():
    try:
        import zjournal
        return zjournal.summary()
    except Exception as e:  # noqa: BLE001 — сводка собирается и без журнала
        return [f"Журнал прогнозов недоступен: {type(e).__name__}", ""]


def top_news(typ, days):
    cfg, _ = collector.load_config()
    a = argparse.Namespace(date_from=(date.today() - timedelta(days=days)).isoformat(), date_to=date.today().isoformat(),
                           entity="", min_score=4, limit=40, new=False, out="")
    _, _, groups, sections = collector.build(a, cfg)
    word = TYPES[typ][1]
    other = TYPES["kr" if typ == "gon" else "gon"][1]
    L, n = [], 0
    for name, items in sections:
        if name == "Прочее":
            continue
        # чужой тип вагона без своего в заголовке — не в эту сводку
        items = [g for g in items if not (re.search(other, g["main"][2], re.I) and not re.search(word, g["main"][2], re.I))]
        if not items:
            continue
        L.append(f"**{name}**")
        for g in items[:4]:
            pub, src, title, summ, url, *_, score = g["main"]
            L.append(f"- {collector.level(score)[1]} {ddmm(pub)} · {src} · {collector.clean_title(title)} — [ссылка]({url})"
                     + (f" (также писали: {len(g['also'])})" if g["also"] else ""))
            n += 1
        L.append("")
    return (L or ["Существенных новостей нет.", ""]), n


def build(typ, guest, days):
    con = collector.db()
    last = con.execute("SELECT max(collected) FROM news").fetchone()[0]
    now = datetime.now(collector.MSK)
    age_h = (now - datetime.fromisoformat(last)).total_seconds() / 3600 if last else 1e9
    rows = news_rows(con, (date.today() - timedelta(days=45)).isoformat())
    news, n = top_news(typ, days)
    title = TYPES[typ][0]
    L = [f"# Сводка рынка: {title}", "",
         f"Собрано {now:%d.%m.%Y %H:%M} МСК программой. Последний сбор новостей: "
         + (f"{datetime.fromisoformat(last).astimezone(collector.MSK):%d.%m %H:%M}" if last else "нет")
         + (" — ⚠ сбор новостей не работал больше суток, данные могут быть неполными" if age_h > 24 * STALE["news"] else ""), "",
         "Правило для бота: цифры — только отсюда, с датой и источником; новее этой сводки — один поиск «что нового за сутки».", ""]
    if not guest:
        L += ["## 1. Ставки — Argus", ""] + argus_block(typ)
    L += [f"## {1 if guest else 2}. Прогноз ставок 2026–2030 и стоимость вагона", ""] + model_block(typ)
    L += [f"## {2 if guest else 3}. Показатели из новостей за 45 дней", "",
          "Последние 3 новости с цифрой по каждому показателю; проверять по ссылке.", ""] + indicators(rows, typ)
    L += [f"## {3 if guest else 4}. Главные новости за {days} дн. — {n}", ""] + news
    if not guest:
        L += ["## 5. Точность прошлых прогнозов", ""] + journal_block()
    L += ["<small>Подготовлено по открытым источникам" + ("" if guest else " и данным подписки владельца") + ".</small>"]
    out = (BASE / "forecast" / "guest" if guest else BASE / "saved" / "market") / f"сводка_{title}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"Сводка: {out.relative_to(BASE)} ({len(L)} строк)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--type", default="all", choices=["gon", "kr", "all"])
    ap.add_argument("--guest", action="store_true")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    for t in (["gon", "kr"] if a.type == "all" else [a.type]):
        build(t, a.guest, a.days)
