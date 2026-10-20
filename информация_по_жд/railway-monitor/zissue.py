#!/usr/bin/env python3
"""«Обзор рынка вагонов ЖДуши» — ежемесячный выпуск по базе наблюдений (zobs.py) и моделям ЖДуши. 0 токенов.

  python3 zissue.py [--month 2026-09] [--demo] [--guest] [--out saved/market/ГГГГ-ММ_обзор_рынка_вагонов.md]
  затем PDF: ~/pw/bin/python zreport.py <файл.md>

Разделы — как в отраслевом ежемесячном обзоре (ставки аренды, оперирования, техрейса; погрузка; парк и обновление),
плюс то, чего в таком обзоре нет: прогноз ставки моделью (zrate.py), стоимость вагона (zvagon.py), сигналы для
лизингодателя. Цифры — только из базы и моделей; текст собирается по правилам, без нейросети.
--demo: данные партнёра (ставки, парк) заменены демонстрационными (сдвиг ±6%, парк ±3% на показатель) — для показа
внешним людям, пока нет своего опроса. --guest = --demo (гостю данные партнёра не показываются).
"""
import argparse
import hashlib
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import zobs  # noqa: E402

MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября",
              "декабря"]
DEMO_GROUPS = ("lease", "oper", "trip", "repair", "park", "flow")  # всё, что от партнёра


def mname(month, gen=False):
    y, m = map(int, month.split("-"))
    return f"{(MONTHS_GEN if gen else MONTHS)[m - 1]} {y}"


def n(v, d=0):
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",")


def sg(v, d=0):
    s = n(abs(v), d)
    return "0" if s.strip("0, ") == "" else ("+" if v > 0 else "−") + s


class Base:
    """Наблюдения: значение показателя за месяц (приоритет источника: опрос → партнёр → РЖД → СМИ → свой расчёт)."""
    ORDER = ["survey", "partner", "rzd", "media", "own"]

    def __init__(self, demo):
        self.v = {}
        for r in zobs.read():
            key = (r["month"], r["item"])
            old = self.v.get(key)
            if old and self.ORDER.index(old[2]) <= self.ORDER.index(r["source"]):
                continue
            lo, hi = float(r["low"]), float(r["high"])
            if demo and r["source"] == "partner" and zobs.ITEMS.get(r["item"], ("",))[0] in DEMO_GROUPS:
                k = 1 + (int(hashlib.md5(r["item"].encode()).hexdigest(), 16) % 13 - 6) / 100
                g = zobs.ITEMS[r["item"]][0]
                k = 1 + (k - 1) / 2 if g in ("park", "flow") else k  # парк — сдвиг ±3%
                step = 500 if g == "trip" else 1 if g in ("park", "flow") else 10
                lo, hi = round(lo * k / step) * step, round(hi * k / step) * step
            self.v[key] = (lo, hi, r["source"])

    def get(self, month, item):
        return self.v.get((month, item))

    def mid(self, month, item):
        x = self.get(month, item)
        return (x[0] + x[1]) / 2 if x else None

    def before(self, month, item):
        """Ближайший более ранний месяц с этим показателем."""
        ms = sorted(m for m, i in self.v if i == item and m < month)
        return ms[-1] if ms else None

    def latest(self, group, upto):
        ms = [m for m, i in self.v if zobs.ITEMS.get(i, ("",))[0] == group and m <= upto]
        return max(ms) if ms else None


def rng(x):
    return n(x[0]) if x[0] == x[1] else f"{n(x[0])}—{n(x[1])}"


def rate_table(B, month, group, title):
    prev = {i: B.before(month, i) for i, g in zobs.ITEMS.items() if g[0] == group}
    rows, movers = [], []
    pm = max((p for p in prev.values() if p), default=None)
    head = (f"| {title} | {mname(month)} | {mname(pm) if pm else 'прошлый'} | Изменение средней | % |", "|---|---|---|---|---|")
    for item, (g, name, unit) in zobs.ITEMS.items():
        cur = B.get(month, item) if g == group else None
        if not cur:
            continue
        p = prev[item]
        old = B.get(p, item) if p else None
        if old:
            d = (cur[0] + cur[1] - old[0] - old[1]) / 2
            pct = d / ((old[0] + old[1]) / 2) * 100
            movers.append((pct, name, d, unit))
            rows.append(f"| {name} | {rng(cur)} | {rng(old)}{'' if p == pm else f' ({mname(p)})'} | {sg(d)} | {sg(pct, 1)} |")
        else:
            rows.append(f"| {name} | {rng(cur)} | — | — | — |")
    return list(head) + rows, movers


def signals(B, month):
    """Сигналы рынка для лизингодателя: + рынок у арендодателя (ставки вверх), − у арендатора. Пороги — рабочие."""
    out = []

    def add(name, now, pts, why):
        out.append((name, now, pts, why))

    m0 = B.before(month, "gon69_spot")
    if B.get(month, "gon69_spot") and m0:
        d = (B.mid(month, "gon69_spot") / B.mid(m0, "gon69_spot") - 1) * 100
        add("Ставка аренды типового полувагона (спот), к прошлому месяцу", f"{sg(d, 1)}%", 1 if d > 2 else -1 if d < -2 else 0,
            "направление цены услуги")
    pk = B.latest("park", month)
    if pk and B.get(pk, "park_gon_work") and B.before(pk, "park_gon_work"):
        p0 = B.before(pk, "park_gon_work")
        d = (B.get(pk, "park_gon_work")[0] / B.get(p0, "park_gon_work")[0] - 1) * 100
        add("Рабочий парк полувагонов, за месяц", f"{sg(d, 1)}%", 1 if d < -0.5 else -1 if d > 0.5 else 0,
            "меньше вагонов в работе — ставка растёт (−1% парка ≈ +5% ставки)")
    fl = B.latest("flow", month)
    if fl and B.get(fl, "flow_gon_new") and B.get(fl, "flow_gon_out"):
        net = B.get(fl, "flow_gon_new")[0] - B.get(fl, "flow_gon_out")[0]
        add(f"Новые полувагоны минус выбывшие, {mname(fl)}", f"{sg(net)} ваг.", 1 if net < -500 else -1 if net > 500 else 0,
            "выбывает больше, чем приходит, — парк сжимается")
    ld = B.latest("load", month)
    if ld and B.get(ld, "load_total"):
        y0 = f"{int(ld[:4]) - 1}{ld[4:]}"
        if B.get(y0, "load_total"):
            d = (B.get(ld, "load_total")[0] / B.get(y0, "load_total")[0] - 1) * 100
            add(f"Погрузка на сети РЖД, {mname(ld)} к году назад", f"{sg(d, 1)}%", 1 if d > 0.5 else -1 if d < -0.5 else 0,
                "больше грузов — больше спрос на вагоны")
    return out


def build(a):
    demo = a.demo or a.guest
    B = Base(demo)
    month = a.month or B.latest("lease", "9999-12")
    if not month:
        sys.exit("В базе нет ставок аренды — сначала: python3 zobs.py pdf <выпуск.pdf>")
    lease, movers = rate_table(B, month, "lease", "Тип вагона")
    oper, mo = rate_table(B, month, "oper", "Оперирование")
    trip, mt = rate_table(B, month, "trip", "Маршрут")
    src = "демонстрационные данные (ставки изменены, не для решений)" if demo else \
        "опрос участников рынка (прототип: данные партнёра)"
    L = [f"# Обзор рынка вагонов ЖДуши: {mname(month)}", "",
         f"<small>Ставки — руб. без НДС · источник ставок: {src} · погрузка — РЖД · прогноз и стоимость вагона — "
         "модели ЖДуши · оценка рынка, не инвестиционная рекомендация</small>", ""]
    if demo:
        L += ["> **Демонстрационная версия:** цифры ставок условные, структура и расчёты — как в рабочем выпуске.", ""]
    # Главное — карточки
    cards = []
    for item, label in (("gon69_spot", "Полувагон типовой, спот"), ("gon75_spot", "Полувагон инновационный, спот")):
        if B.get(month, item) and B.before(month, item):
            c, p = B.mid(month, item), B.mid(B.before(month, item), item)
            cards.append(f"{label}, ₽/сут | {n(c)} | {'✓ ▲' if c >= p else '⚠ ▼'} {sg((c / p - 1) * 100, 1)}% за месяц")
    pk = B.latest("park", month)
    if pk and B.get(pk, "park_gon_work") and B.before(pk, "park_gon_work"):
        c, p = B.get(pk, "park_gon_work")[0], B.get(B.before(pk, "park_gon_work"), "park_gon_work")[0]
        cards.append(f"Рабочий парк полувагонов, тыс. | {n(c / 1000, 1)} | {'✓ ▼' if c < p else '⚠ ▲'} "
                     f"{sg((c / p - 1) * 100, 1)}% за месяц")
    rz = None
    try:
        import zrate
        R = zrate.load()
        rz = {w: {sc: zrate.forecast(R, w, sc) for sc in zrate.SCN} for w in ("inno", "gon")}
        cards.append(f"Инновационный, декабрь 2026 (прогноз), ₽/сут | {n(rz['inno']['base']['q4'][-1])} | ▶ базовый сценарий")
    except SystemExit:
        pass
    L += ["## Главное", "", "```cards"] + cards + ["```", ""]
    bullets = []
    for pct, name, d, unit in sorted(movers, key=lambda x: -abs(x[0]))[:3]:
        bullets.append(f"{name}: {'рост' if d > 0 else 'снижение'} средней ставки на {n(abs(d))} {unit} ({sg(pct, 1)}%).")
    if mo:
        pct, name, d, unit = next((x for x in mo if "уголь" in x[1]), mo[0])
        bullets.append(f"Оперирование ({name.lower()}): {sg(d)} {unit} ({sg(pct, 1)}%).")
    sig = signals(B, month)
    score = sum(s[2] for s in sig)
    phase = "у арендодателя: ставки вверх" if score >= 2 else "у арендатора: ставки вниз" if score <= -2 else "в равновесии"
    bullets.append(f"Рынок полувагонов {phase} — сумма сигналов {sg(score)} из {len(sig)} (раздел 7).")
    L += [f"- {b}" for b in bullets] + [""]
    # 1–2. Ставки
    L += ["## 1. Ставки аренды подвижного состава", "", "руб./сут без НДС", ""] + lease + [""]
    L += ["## 2. Оперирование и технический рейс", "", "Ставка оперирования — руб./сут без НДС, включая порожний пробег:",
          ""] + oper + ["", "Ставка предоставления типового полувагона на технический рейс — руб./вагон без НДС:", ""] + trip
    L += ["", "<small>Диапазон — от минимальной до максимальной ставки участников рынка; изменение — по середине "
          "диапазона. Единичные сделки вне диапазона в таблицу не входят.</small>", ""]
    rp = B.latest("repair", month)
    if rp:
        L += [f"**Ремонт и отстой** (последние данные — {mname(rp)}, руб. без НДС): " + "; ".join(
            f"{nm.lower()} {rng(B.get(rp, i))} {u}" for i, (g, nm, u) in zobs.ITEMS.items() if g == "repair" and B.get(rp, i)) + ".", ""]
    # 3. Погрузка
    ld = B.latest("load", month)
    if ld:
        L += [f"## 3. Погрузка на сети РЖД: {mname(ld)}", "", "| Груз | млн т | к прошлому месяцу, % | к году назад, % |",
              "|---|---|---|---|"]
        for i, (g, nm, u) in zobs.ITEMS.items():
            if g == "load" and B.get(ld, i):
                c = B.get(ld, i)[0]
                p, y = B.get(zobs.shift(ld, -1), i), B.get(zobs.shift(ld, -12), i)
                L.append(f"| {nm} | {n(c, 1)} | {sg((c / p[0] - 1) * 100, 1) if p else '—'} | "
                         f"{sg((c / y[0] - 1) * 100, 1) if y else '—'} |")
        ser = [(m, B.get(m, "load_total")[0]) for m in sorted(m for m, i in B.v if i == "load_total" and m <= ld)][-12:]
        if len(ser) > 3:
            L += ["", "```chart", "Погрузка на сети РЖД, млн т | " + " | ".join(
                f"{m[5:]}.{m[2:4]}: {v:.1f}" for m, v in ser), "```"]
        L += ["", "<small>По данным РЖД.</small>", ""]
    # 4. Парк
    if pk:
        p0 = B.before(pk, "park_gon_work")
        L += [f"## 4. Парк вагонов на 1 {mname(pk, gen=True)}", "",
              "| Вагоны | Зарегистрировано | Рабочие | Доля в работе | Рабочие за месяц | С истекшим сроком |",
              "|---|---|---|---|---|---|"]
        for k, nm in zobs.PARK.items():
            reg, work, exp = (B.get(pk, f"park_{k}_{x}") for x in ("reg", "work", "exp"))
            if not (reg and work):
                continue
            w0 = B.get(p0, f"park_{k}_work") if p0 else None
            L.append(f"| {nm} | {n(reg[0])} | {n(work[0])} | {n(work[0] / reg[0] * 100, 1)}% | "
                     f"{sg((work[0] / w0[0] - 1) * 100, 1) + '%' if w0 else '—'} | {n(exp[0]) if exp else '—'} |")
        fl = B.latest("flow", month)
        if fl:
            L += ["", f"**Обновление парка, {mname(fl)}:**", "", "| Вагоны | Поступило всего | Новых | Покинуло сеть | Новые − выбывшие |",
                  "|---|---|---|---|---|"]
            for k, nm in zobs.PARK.items():
                i_, nw, o = (B.get(fl, f"flow_{k}_{x}") for x in ("in", "new", "out"))
                if i_ and nw and o:
                    L.append(f"| {nm} | {n(i_[0])} | {n(nw[0])} | {n(o[0])} | {sg(nw[0] - o[0])} |")
        if rz and p0 and B.get(pk, "park_gon_work"):
            d = round((B.get(pk, "park_gon_work")[0] / B.get(p0, "park_gon_work")[0] - 1) * 100, 1)
            e = rz["inno"]["base"]["e"]
            fact = ""
            if B.get(month, "gon75_spot") and B.before(month, "gon75_spot"):
                fact = (f"; фактически спотовая ставка инновационного полувагона за месяц "
                        f"{sg((B.mid(month, 'gon75_spot') / B.mid(B.before(month, 'gon75_spot'), 'gon75_spot') - 1) * 100, 1)}%")
            L += ["", f"Что это значит для ставки: рабочий парк полувагонов {sg(d, 1)}% за месяц; по модели ЖДуши −1% рабочего "
                  f"парка даёт около +{n(e, 1)}% к ставке инновационного полувагона, то есть {sg(-d * e, 1)}%{fact}."]
        L += ["", "<small>Парк частных вагонов для сухих грузов и контейнеров, по данным участников рынка; «Итого» — "
              "с вагонами на балансе РЖД.</small>", ""]
    # 5. Прогноз
    if rz:
        L += [f"## 5. Прогноз ставки аренды (модель ЖДуши, данные на {R['as_of']})", "",
              "| Вагон, сценарий | октябрь* | ноябрь* | декабрь* | средняя за 2026 г.** | средняя за 2027 г.*** | средняя за 2030 г.*** |",
              "|---|---|---|---|---|---|---|"]
        for w in ("inno", "gon"):
            for sc in ("base", "opt", "pess"):
                r = rz[w][sc]
                L.append(f"| {zrate.WAGONS[w]}, {zrate.SCN[sc].lower()} | " + " | ".join(n(q) for q in r["q4"]) +
                         f" | {n(r['lvl'][2026])} | {n(r['lvl'][2027])} | {n(r['lvl'][2030])} |")
        try:  # крытые — та же схема (ztypes.py)
            import ztypes
            for w in ("kr158", "kr138", "hop_grain", "fit80"):
                for sc in ("base", "opt", "pess"):
                    r = ztypes.forecast(w, sc)
                    L.append(f"| {ztypes.TYPES[w]['name']}, {ztypes.SCN[sc].lower()} | " + " | ".join(n(q) for q in r["q4"]) +
                             f" | {n(r['lvl'][2026])} | {n(r['lvl'][2027])} | {n(r['lvl'][2030])} |")
        except SystemExit:
            pass
        L += ["", f"<small>* {zrate.AVG['month']}. ** {zrate.AVG['2026']}. *** {zrate.AVG['year']}. Крытые: пессимистичный — по "
              "факторам спада (стройка, ипотека), не выше «средняя прошлого года + инфляция».</small>", ""]
        need = [f"{n(t)} ₽ — рабочий парк −{n(zrate.need(R, 'inno', t)[0], 1)}% (≈{n(zrate.need(R, 'inno', t)[1], 1)} тыс. вагонов)"
                for t in R["targets"]]
        L += ["Что нужно для роста ставки инновационного полувагона: " + "; ".join(need) + ". Полный расчёт с вкладом "
              "каждого фактора в рублях — /prognoz и «Построить прогноз» в мини-приложении.", ""]
    # 6. Стоимость вагона
    try:
        import zvagon
        V = zvagon.load()
        rows, sc = zvagon.signals(V)
        vd = zvagon.verdict(V, sc)
        rp_ = zvagon.rate_paths("base")
        L += ["## 6. Стоимость вагона", "", f"{{{{класс:{vd['class']}}}}} **{vd['title']}** — {vd['text']}", "",
              "| Вагон, млн ₽ без НДС | 2026 | 2027 | 2028 | 2029 | 2030 |", "|---|---|---|---|---|---|"]
        kf, floor = zvagon.age_factor(V, 14), V["scrap_floor"]
        ph = V["phase_factor"]["bottom"] if sc >= 2 else 1.0
        for t in ("gon", "inno", "kr158"):
            p, _ = zvagon.price_path(V, t, {y: rp_[zvagon.RATE_KEY[t]][y] for y in range(2027, 2031)})
            used = {y: max(floor, p[y] * kf * ph ** max(0, 1 - (y - 2026) / 3)) for y in p}
            L.append(f"| {zvagon.NAMES[t]}, новый | " + " | ".join(n(p[y], 1) for y in range(2026, 2031)) + " |")
            L.append(f"| {zvagon.NAMES[t]}, б/у 14 лет | " + " | ".join(n(used[y], 1) for y in range(2026, 2031)) + " |")
        try:  # зерновоз и платформа — модель стоимости ztypes.py
            import ztypes
            for t_ in ("hop_grain", "fit80"):
                v = ztypes.value(t_, "base")
                if v:
                    nm = ztypes.TYPES[t_]["name"]
                    L.append(f"| {nm}, новый | " + " | ".join(n(v['new'][y], 1) for y in range(2026, 2031)) + " |")
                    L.append(f"| {nm}, б/у 14 лет | " + " | ".join(n(v['used'][y], 1) for y in range(2026, 2031)) + " |")
        except SystemExit:
            pass
        L += ["", "<small>Цена нового вагона следует за средней ставкой за 3 года и себестоимостью; б/у — по возрасту и фазе "
              "рынка, не ниже цены лома. Ставки — модель раздела 5 (базовый сценарий). Ошибка — около ±15% в год. Зерновоз: цена 2026 г. — "
              "оценка через годовой доход к цене; платформа — по себестоимости (прайс заводов), за ставкой не следует. Подробно — "
              "/vagon и /prognoz.</small>", ""]
    except SystemExit:
        pass
    # 7. Сигналы
    if sig:
        L += ["## 7. Сигналы для лизингодателя", "", "| Показатель | Сейчас | Сигнал | Почему важно |", "|---|---|---|---|"]
        for name, now, pts, why in sig:
            L.append(f"| {name} | {now} | {'🟢 за рост ставок' if pts > 0 else '🔴 против' if pts < 0 else '🟡 нейтрально'} | {why} |")
        act = ("новые сделки — да: арендный поток растёт, залог дорожает; фиксировать ставку лизинга сейчас" if score >= 2 else
               "новые сделки — осторожно: ставка и загрузка вагонов падают; запас покрытия платежа и аванс выше" if score <= -2
               else "новые сделки — на обычных условиях; проверять покрытие платежа по пессимистичному сценарию")
        L += ["", f"> **Что делать:** {act}.", "",
              "<small>Пороги: ставка ±2% за месяц; рабочий парк ±0,5%; новые − выбывшие ±500 вагонов; погрузка ±0,5% к году "
              "назад. Пороги рабочие — уточняются по журналу «прогноз — факт».</small>", ""]
    try:  # события рынка по типам вагонов (цепочка «вагон → порт → судно»)
        import zevents
        L += [zevents.report("all", 30).replace("## События рынка", "## 8. События рынка")]
    except SystemExit:
        pass
    # Методика
    L += ["## Методика и источники", "",
          "- **Ставки аренды, оперирования, техрейса, ремонта** — ежемесячный опрос операторов, грузоотправителей и "
          "экспедиторов; диапазон от минимальной до максимальной ставки, без НДС; спот и долгосрочные контракты, типовой и "
          "инновационный вагон — раздельно; изменение — по середине диапазона."
          + (" В прототипе вместо опроса — данные партнёра." if not demo else " В демонстрационной версии ставки условные."),
          "- **Погрузка** — РЖД. **Парк, поступление и выбытие** — данные участников рынка.",
          "- **Прогноз ставки** — модель ЖДуши: IV квартал — по рабочему парку, 2027–2030 — по балансу парка (уголь, "
          "погрузка, оборот, выпуск и списание), проверка на 2011–2025 гг. **Стоимость вагона** — модель ЖДуши по ставке и "
          "себестоимости.", "- Каждый прогноз записывается в журнал и сверяется с фактом.", "",
          "<small>Подготовлено ЖДушей. Выводы — оценка рынка, не инвестиционная рекомендация.</small>"]
    return month, "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--guest", action="store_true")
    ap.add_argument("--out")
    x = ap.parse_args()
    month, md = build(x)
    if x.out:
        Path(x.out).parent.mkdir(parents=True, exist_ok=True)
        Path(x.out).write_text(md, encoding="utf-8")
        print(f"Файл: {x.out}")
    else:
        print(md)
