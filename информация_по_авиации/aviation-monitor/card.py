"""Карточка компании для инвестора: 15 минут чтения. Вывод → светофор → финансы → долг → имущество → суды →
регулятор, санкции, бюджеты → сквозные сюжеты → приложение со всеми источниками."""
import html
from datetime import datetime

import collector as C
import finance as F

e = html.escape
PROPERTY = ("Самолёты: парк, ресурс, ремонт", "Вертолёты и БПЛА")
LIGHTS = [("Суды", ("Суды и споры",)), ("Сделки", ("Слияния и поглощения",)),
          ("Имущество", PROPERTY), ("Долг и финансы", ("Финансы: займы, кредиты, размещения",)),
          ("Санкции", ("Санкции и геополитика",)),
          ("Регулятор и бюджеты", ("Правительство и регулирование", "Бюджеты регионов и субсидии"))]


def fmt(v, pct=False, x=False):
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.1f}%".replace(".", ",")
    if x:
        return f"{v:.1f}×".replace(".", ",")
    return f"{v:,.1f}".replace(",", " ").replace(".", ",")


def delta(a, b):
    if a is None or b is None or a == 0:
        return "—"
    d = (b - a) / abs(a) * 100
    return f"{'+' if d >= 0 else ''}{d:.0f}%"


def light(items):
    scores = [g["main"][8] for g in items]
    if any(s >= 7 for s in scores):
        return "🔴"
    if any(s >= 4 for s in scores):
        return "🟡"
    return "🟢"


def item_html(g, num):
    pub, src, title, summ, url = g["main"][:5]
    head = f"<b>Сюжет «{e(g['thread'])}»</b> ({len(g['items'])} новостей), последняя: " if g.get("thread") else ""
    also = f" · ещё {len(g['also'])} ист." if g.get("also") else ""
    return (f"<li><span class='num'>{num}</span>{head}<a href='{e(url)}' target='_blank' rel='noopener'>{e(C.clean_title(title))}</a>"
            f" <span class='line'>— {e(C.fmt_dt(pub))}, {e(src)}{also}</span></li>")


def top(sections, names, n):
    items = [g for name, its in sections if name in names for g in its]
    items.sort(key=lambda g: (g["main"][8], g["main"][0]), reverse=True)
    return items[:n], len(items)


def render(a, meta, sections, groups, fin_rows, summary, out):
    w = out.write
    w(f"<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
      f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(meta['subject'])}: карточка</title>"
      f"<style>{C.HTML_CSS}</style></head><body><main>")
    w(f"<h1>{e(meta['subject'])}: карточка для решения о финансировании</h1><div class='meta'>"
      f"<span>Период: <b>{e(meta['period'])}</b></span><span>Выгрузка: <b>{e(meta['made'])} МСК</b></span>"
      f"<span>Сюжетов: <b>{meta['n_groups']}</b> (публикаций: {meta['n_rows']})</span></div>")

    # 1. Вывод
    w("<h2>1. Вывод</h2>")
    if summary:
        w("<div class='box'>" + "".join(f"<p style='margin:4px 0'>{e(s)}</p>" for s in summary.splitlines() if s.strip())
          + "</div>")
    else:
        w("<p class='empty'>Вывод пишет агент по фактам ниже (файл с текстом передаётся параметром --summary).</p>")
    w("<div class='lights'>" + "".join(
        f"<span class='light'>{light([g for n, its in sections if n in names for g in its])} {e(label)}</span>"
        for label, names in LIGHTS) + "</div>")
    w("<p class='cap'>Светофор — по новостям за период: 🔴 есть событие высокого приоритета, 🟡 среднего, "
      "🟢 существенных событий нет. Это сигнал, где читать внимательнее, а не оценка кредитного риска.</p>")

    # 2. Финансы
    w("<h2>2. Финансовое состояние</h2>")
    tabs = F.tables(fin_rows)
    annual = [rows for (std, lvl, typ), rows in tabs if typ.lower() == "год"]
    last_rev = annual[0][-1]["выручка"] if annual else None   # годовая выручка — база для доли исков
    last_debt = tabs[0][1][-1]["долг"] if tabs else None      # долг на конец последнего периода — база для прироста
    if not tabs:
        w("<p class='empty'>Нет данных отчётности: заполните finance.csv (РСБУ и МСФО, по группе, если есть).</p>")
    for (std, lvl, typ), rows in tabs:
        cols = [r["период"] for r in rows]
        w(f"<p class='cap'><b>{e(std)}</b>, {e(lvl)}, {e(typ)} · млрд ₽ · источник: "
          f"{e('; '.join(sorted({r['источник'] for r in rows if r['источник']})) or 'не указан')}</p>")
        w("<table><thead><tr><th>Показатель</th>" + "".join(f"<th>{e(c)}</th>" for c in cols)
          + ("<th>Изменение</th>" if len(rows) == 2 else "") + "</tr></thead><tbody>")
        for k in F.FIELDS:
            vals = [r[k] for r in rows]
            w(f"<tr><td>{e(F.LABELS[k])}</td>" + "".join(f"<td>{fmt(v)}</td>" for v in vals)
              + (f"<td>{delta(*vals)}</td>" if len(vals) == 2 else "") + "</tr>")
        ms = [F.metrics(r) for r in rows]
        for key, label, kw in (("чистый_долг", "Чистый долг = долг − денежные средства", {}),
                               ("долг_ebitda", "Чистый долг / EBITDA (только за год)", {"x": True}),
                               ("обязательства_к_активам", "Обязательства / активы", {"pct": True}),
                               ("рентабельность", "Чистая прибыль / выручка", {"pct": True})):
            vals = [m.get(key) for m in ms]
            w(f"<tr><td class='calc'>{e(label)}</td>" + "".join(f"<td class='calc'>{fmt(v, **kw)}</td>" for v in vals)
              + ("<td></td>" if len(vals) == 2 else "") + "</tr>")
        w("</tbody></table>")

    # 3. Заимствования
    w("<h2>3. Новые заимствования</h2>")
    bor = F.borrowings(groups)
    if not bor:
        w("<p class='empty'>За период в новостях нет сумм по облигациям и кредитам.</p>")
    else:
        plan = sum(b["bln"] for b in bor if b["status"] == "план")
        fact = sum(b["bln"] for b in bor if b["status"] == "факт")
        total = plan + fact
        w(f"<div class='box'><span class='big'>{fmt(total)} млрд ₽</span> — сумма из новостей за период "
          f"(размещено/получено {fmt(fact)}, объявлено {fmt(plan)}).")
        if last_debt:
            w(f"<br>К долгу на конец последнего отчётного периода ({fmt(last_debt)} млрд ₽) это "
              f"<b>+{total / last_debt * 100:.0f}%</b>. Расчёт: {fmt(total)} / {fmt(last_debt)}.")
        w("</div><p class='cap'>Суммы найдены в текстах новостей автоматически. Одно и то же размещение может "
          "упоминаться как план и как факт — сверяйте с проспектом и раскрытием эмитента.</p><ol class='plain'>")
        for b in bor:
            w(f"<li>{e(C.fmt_dt(b['date']))} · <b>{fmt(b['bln'])} млрд ₽</b> · {e(b['status'])} · "
              f"<a href='{e(b['url'])}' target='_blank' rel='noopener'>{e(b['title'])}</a></li>")
        w("</ol>")

    # 4–7: короткие блоки по 5 главных сюжетов
    blocks = [("4. Имущество: самолёты, вертолёты, БПЛА", PROPERTY, 7),
              ("5. Суды и споры", ("Суды и споры",), 5),
              ("6. Сделки: слияния и поглощения", ("Слияния и поглощения",), 5),
              ("7. Регулятор, бюджеты регионов, санкции",
               ("Правительство и регулирование", "Бюджеты регионов и субсидии", "Санкции и геополитика"), 6)]
    for title, names, n in blocks:
        its, total = top(sections, names, n)
        w(f"<h2>{e(title)} <span class='n'>· {total}</span></h2>")
        if title.startswith("5.") and its:
            claims = F.claims(its)
            if claims and last_rev:
                w(f"<div class='box'>Иски с известной суммой: <b>{fmt(claims)} млрд ₽</b> = "
                  f"<b>{claims / last_rev * 100:.0f}% годовой выручки</b> ({fmt(last_rev)} млрд ₽).</div>")
        if not its:
            w("<p class='empty'>Существенных новостей нет.</p>")
            continue
        w("<ol class='plain'>" + "".join(item_html(g, f"{title.split('.')[0]}.{i}") for i, g in enumerate(its, 1))
          + "</ol>")
        if total > n:
            w(f"<p class='cap'>Ещё {total - n} — в приложении.</p>")

    # Приложение
    w("<h2>Приложение: все сюжеты по разделам</h2><details><summary>Открыть полный список</summary>")
    for si, (name, its) in enumerate(sections, 1):
        if its:
            w(f"<h3 style='margin-top:14px'>{si}. {e(name)} · {len(its)}</h3><ol class='plain'>"
              + "".join(item_html(g, f"{si}.{i}") for i, g in enumerate(its, 1)) + "</ol>")
    w("</details>")
    w(f"<footer>Финансовые показатели — из отчётности (finance.csv), расчёты — формулами. Новости — открытые источники, "
      f"каждый факт проверяйте по ссылке. Сформировано {e(meta['made'])} МСК.</footer></main></body></html>")


def cmd_card(a):
    cfg, _ = C.load_config()
    a.min_score = getattr(a, "min_score", 1)
    meta, rows, groups, sections = C.build(a, cfg)
    names = [n.strip() for n in a.entity.split(",") if n.strip()]
    fin = F.load(names)
    summary = open(a.summary, encoding="utf-8-sig").read() if a.summary else ""
    out = a.out or f"{names[0]}_карточка.html"
    with open(out, "w", encoding="utf-8") as f:
        render(a, meta, sections, groups, fin, summary, f)
    print(f"Карточка: {meta['n_groups']} сюжетов, строк отчётности {len(fin)} → {out}")
