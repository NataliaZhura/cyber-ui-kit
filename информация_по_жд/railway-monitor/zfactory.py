#!/usr/bin/env python3
"""Завод или оператор: денежный поток, запас прочности, стресс-тест, риск аванса и задержки поставки.

  python3 zfactory.py run <ИНН|ОГРН> --name "Алтайвагон" [--deal 500000] [--zavod] [--guest] [--out файл.md]
      --deal   сумма сделки, тыс. ₽ (для расчёта аванса в % от сделки)
      --zavod  блоки «аванс» и «задержка поставки» (для производителя вагонов)

Отчётность — РСБУ юрлица из ГИР БО через Checko (те же запросы и кеш, что у Ави: ~/aviation-monitor/checko.py).
Строки: 2110 выручка, 2200 прибыль от продаж, 2330 проценты к уплате, 1210 запасы, 1230 дебиторка, 1250 деньги,
1410/1510 кредиты, 1520 кредиторка (в т. ч. полученные авансы), 1300 капитал, 4100 поток от текущих операций,
4111 поступления от продаж, 4123 проценты уплаченные, 4321 возврат кредитов. Нет строки — «нет данных», не ноль.
Все пороги — в словаре TH ниже; итог — оценка эксперта по открытой отчётности, а не заключение о кредитоспособности.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("AVI_DIR", str(Path.home() / "aviation-monitor")))
import checko  # noqa: E402

TH = {
    "adv_rev_q": 0.25,      # аванс не больше 25% квартальной выручки завода
    "adv_free_cash": 1.0,   # и не больше свободных денег (деньги − 25% краткосрочного долга)
    "adv_equity": 0.10,     # и не больше 10% собственного капитала
    "deal_cap": {"A": 0.25, "B": 0.20, "C": 0.10, "D": 0.0, "E": 0.0},  # доля сделки без банковской гарантии
    "stress": [("База", 1.0, 0.0, 0.0), ("Платежи по долгу +20%", 1.0, 0.2, 0.0),
               ("Платежи по долгу +50%", 1.0, 0.5, 0.0), ("Выручка −20%", 0.8, 0.0, 0.0),
               ("Ключевая ставка +2 п.п.", 1.0, 0.0, 2.0), ("Всё сразу: выручка −20%, долг +50%, ставка +2", 0.8, 0.5, 2.0)],
}


def num(lines, *codes):
    vals = [lines.get(c) for c in codes]
    vals = [float(v) for v in vals if isinstance(v, (int, float))]
    return sum(vals) / 1000 if vals else None  # рубли → тыс. ₽


def t(v):
    if v is None:
        return "нет данных"
    s = (f"{v / 1e6:,.1f} млрд ₽" if abs(v) >= 1e6 else f"{v / 1e3:,.0f} млн ₽" if abs(v) >= 1e3 else f"{v:,.0f} тыс. ₽")
    return s.replace(",", " ").replace(".", ",").replace("-", "−")


def pct(v):
    return "нет данных" if v is None else f"{v * 100:+.0f}%".replace("-", "−")


def metrics(ys):
    y = sorted(ys)[-1]
    p = sorted(ys)[-2] if len(ys) > 1 else None
    L, P = ys[y], ys.get(p, {}) if p else {}
    m = {"year": y, "prev": p}
    for k, codes in {"rev": ["2110"], "ebit": ["2200"], "int": ["2330"], "net": ["2400"], "inv": ["1210"],
                     "ar": ["1230"], "cash": ["1250"], "debt_l": ["1410"], "debt_s": ["1510"], "ap": ["1520"],
                     "eq": ["1300"], "cfo": ["4100"], "rcpt": ["4111"], "int_paid": ["4123"], "repay": ["4321"],
                     "borrow": ["4311"]}.items():
        m[k], m[k + "_p"] = num(L, *codes), num(P, *codes)
    m["debt"] = sum(v for v in (m["debt_l"], m["debt_s"]) if v is not None) if (m["debt_l"] or m["debt_s"]) else None
    return m


def ch(a, b):
    return None if a is None or b in (None, 0) else a / b - 1


def runway(m, rev_k=1.0, debt_k=0.0, rate_pp=0.0):
    """Сколько месяцев хватит денег: деньги / (месячные платежи по долгу − месячный поток), с учётом стресса."""
    cfo, cash = m["cfo"], m["cash"]
    if cfo is None or cash is None:
        return None, None
    ebit_drop = (1 - rev_k) * (m["rev"] or 0) * 0.5  # при падении выручки половина выпадает из потока (постоянные затраты)
    extra_int = (m["debt"] or 0) * rate_pp / 100
    service = ((m["repay"] or (m["debt_s"] or 0)) + (m["int_paid"] or m["int"] or 0)) * (1 + debt_k) + extra_int
    flow = cfo + (m["int_paid"] or m["int"] or 0) - ebit_drop  # поток до процентов
    cover = flow / service if service else None
    gap = service - flow
    months = None if gap <= 0 else 12 * cash / gap
    return cover, months


def grade(m):
    cover, months = runway(m)
    bad = 0
    bad += cover is not None and cover < 1.0
    bad += m["eq"] is not None and m["eq"] < 0
    bad += m["cfo"] is not None and m["cfo"] < 0
    bad += (ch(m["rev"], m["rev_p"]) or 0) < -0.25
    bad += m["debt"] is not None and m["rev"] and m["debt"] > m["rev"]
    return "ABCDE"[min(4, bad)], cover, months


def advance_block(m, cls, deal):
    rows, flags = [], []
    caps = []
    if m["rev"]:
        caps.append(("25% квартальной выручки", TH["adv_rev_q"] * m["rev"] / 4))
    if m["cash"] is not None:
        caps.append(("свободные деньги (деньги − 25% краткосрочного долга)", max(0, m["cash"] - 0.25 * (m["debt_s"] or 0))))
    if m["eq"] is not None:
        caps.append(("10% собственного капитала", max(0, TH["adv_equity"] * m["eq"])))
    lim = min(v for _, v in caps) if caps else None
    share = TH["deal_cap"][cls]
    rows.append("| Ограничение | Сумма |")
    rows.append("|---|---|")
    rows += [f"| {n} | {t(v)} |" for n, v in caps]
    by_deal = deal * share if deal else None
    final = min(x for x in (lim, by_deal) if x is not None) if (lim is not None or by_deal is not None) else None
    # признаки «аванс уйдёт на долги, а не в производство»
    d_ap, d_inv = ch(m["ap"], m["ap_p"]), ch(m["inv"], m["inv_p"])
    if d_ap is not None and d_inv is not None and d_ap > 0.2 and d_inv < d_ap / 2:
        flags.append(f"кредиторка (в ней авансы покупателей) выросла на {pct(d_ap)}, а запасы — только на {pct(d_inv)}: "
                     "полученные деньги могли пойти не в производство")
    if m["repay"] and m["cfo"] is not None and m["repay"] > max(m["cfo"], 0) + (m["borrow"] or 0) * 0.5:
        flags.append(f"возврат кредитов {t(m['repay'])} больше потока от операций {t(m['cfo'])}: долги гасятся "
                     "за счёт других денег, в том числе авансов")
    if m["cfo"] is not None and m["cfo"] < 0 and (m["debt_s"] or 0) > (m["cash"] or 0):
        flags.append("поток от операций отрицательный, а долг к погашению за 12 месяцев больше денег на счетах")
    return rows, lim, share, by_deal, final, flags


def delay_block(m):
    flags = []
    r = ch(m["rev"], m["rev_p"])
    if r is not None and r < -0.2:
        flags.append(f"выручка упала на {abs(r) * 100:.0f}% — завод снижает выпуск, загрузка мощностей низкая")
    i = ch(m["inv"], m["inv_p"])
    if i is not None and r is not None and i > 0.15 and r < 0:
        flags.append(f"запасы выросли на {pct(i)} при падении выручки — затоваривание или задержки отгрузок")
    if m["ebit"] is not None and m["ebit"] < 0:
        flags.append("убыток от продаж — риск экономии на закупках комплектующих (колёса, литьё)")
    return flags


def run(a):
    data = checko.years(checko.cached("finances", a.id))
    if not data:
        sys.exit("Отчётность не получена (лимит Checko или формат) — попробуй 1С (onec.py) или позже.")
    m = metrics(data)
    cls, cover, months = grade(m)
    cases = checko.cases_summary(checko.cached("legal-cases", a.id))
    if m["debt"] and m["rev"]:
        debt_note = "⚠ больше выручки" if m["debt"] > m["rev"] else f"{m['debt'] / m['rev']:.1f} годовой выручки".replace(".", ",")
    else:
        debt_note = "нет данных"
    L = [f"# {a.name} — денежный поток и запас прочности", "",
         f"{{{{класс:{cls}}}}} **{ {'A': 'Низкий', 'B': 'Умеренный', 'C': 'Повышенный', 'D': 'Высокий', 'E': 'Критический'}[cls]} риск:** "
         + (f"поток покрывает платежи по долгу в {cover:.1f} раза".replace(".", ",") if cover is not None else "поток не рассчитан — нет отчёта о движении денег")
         + (f", денег хватит на {months:.0f} мес. без новых поступлений." if months and months <= 24 else
            ", запаса денег хватит больше чем на 2 года." if months else "."), "",
         f"<small>ИНН/ОГРН {a.id} · последняя доступная отчётность: РСБУ юрлица на 31.12.{m['year']} (к {m['prev']} г.) · тыс. ₽ · Подготовлено по открытым источникам</small>", "",
         "## Главное за минуту", "", "```cards",
         f"Выручка, {m['year']} | {t(m['rev'])} | {'⚠ ▼' if (ch(m['rev'], m['rev_p']) or 0) < 0 else '✓ ▲'} {pct(ch(m['rev'], m['rev_p']))} к {m['prev']}",
         f"Поток от операций | {t(m['cfo'])} | {'⚠ отрицательный' if (m['cfo'] or 0) < 0 else '✓ положительный'}",
         f"Долг (кредиты и займы) | {t(m['debt'])} | {debt_note}",
         f"Деньги на счетах | {t(m['cash'])} | {'⚠ меньше долга на 12 мес.' if (m['cash'] or 0) < (m['debt_s'] or 0) else '✓ покрывают долг на 12 мес.'}",
         f"Покрытие платежей потоком | {f'{cover:.1f} раза'.replace('.', ',') if cover is not None else 'нет данных'} | {'⚠ меньше 1' if cover is not None and cover < 1 else '✓'}",
         f"Капитал | {t(m['eq'])} | {'⚠ отрицательный' if (m['eq'] or 0) < 0 else '✓'}", "```", ""]
    L += ["## Сколько выдержит при росте нагрузки", "", "| Сценарий | Покрытие платежей потоком | Денег хватит |", "|---|---|---|"]
    for name, rk, dk, rp in TH["stress"]:
        c, mo = runway(m, rk, dk, rp)
        cs = "нет данных" if c is None else "поток отрицательный" if c < 0 else f"{c:.1f}".replace(".", ",")
        ms = ("поток покрывает платежи" if c is not None and mo is None else "больше 2 лет" if mo and mo > 24
              else f"{mo:.0f} мес." if mo else "нет данных")
        L.append(f"| {name} | {cs} | {ms} |")
    L += ["", "<small>Покрытие = поток от операций до процентов / (возврат кредитов + проценты). Меньше 1 — платежи "
          "идут из денег на счетах или новых займов. «Денег хватит» = деньги / месячный недостаток потока.</small>", ""]
    if a.zavod:
        rows, lim, share, by_deal, final, flags = advance_block(m, cls, a.deal)
        L += ["## Сколько аванса можно перечислить заводу", ""] + rows + [""]
        if not final:
            L += ["> **Аванс без банковской гарантии не перечислять:** свободных денег у завода нет или класс риска высокий. "
                  "Оплата — только под банковскую гарантию возврата аванса, аккредитив или по готовности вагонов "
                  "(оценка эксперта).", ""]
        else:
            L += [f"> **Допустимый аванс без банковской гарантии: {t(final)}**" +
              (f" — {final / a.deal * 100:.0f}% от сделки {t(a.deal)}" if final is not None and a.deal else "") +
              f". По классу {cls} — не больше {share * 100:.0f}% сделки. Сверх этого — только под банковскую гарантию "
              "возврата аванса, аккредитив или поэтапную оплату по готовности вагонов (оценка эксперта).", ""]
        L += ["**Не уйдёт ли аванс на долги, а не в производство:**", ""]
        L += [f"- ⚠ Риск (высокий): {f}" for f in flags] or ["- ✓ явных признаков в отчётности нет"]
        dl = delay_block(m)
        if cases and cases.get("n"):
            dl.append(f"судебных дел: {cases['n']}, сумма требований {checko.money(cases['sum'])} — проверить споры "
                      "с покупателями о сроках поставки")
        L += ["", "**Риск задержки поставки:**", ""] + ([f"- ⚠ Риск: {f}" for f in dl] or ["- ✓ явных признаков в отчётности нет"])
        L += ["", "<small>Проверить отдельно (в отчётности не видно): портфель заказов против выпуска, простои и неполная "
              "неделя, поставщики колёсных пар и литья, санкции — раздел новостей.</small>", ""]
    L += ["## Отчётность", "", f"| Показатель | {m['prev']} | {m['year']} | Изменение |", "|---|---|---|---|"]
    for n_, k in (("Выручка", "rev"), ("Прибыль от продаж", "ebit"), ("Чистая прибыль", "net"), ("Поток от операций", "cfo"),
                  ("Возврат кредитов", "repay"), ("Проценты", "int"), ("Запасы", "inv"), ("Дебиторка", "ar"),
                  ("Кредиторка (в т. ч. авансы полученные)", "ap"), ("Деньги", "cash"), ("Кредиты краткосрочные", "debt_s"),
                  ("Кредиты долгосрочные", "debt_l"), ("Капитал", "eq")):
        L.append(f"| {n_} | {t(m[k + '_p'])} | {t(m[k])} | {pct(ch(m[k], m[k + '_p']))} |")
    L += ["", "> **Как читать:** оценка по открытой годовой отчётности юрлица; квартальных данных и договоров нет. "
          "Для решения об авансе запросить у завода: портфель заказов, график выпуска, кредитный договор "
          "(ковенанты), расшифровку авансов полученных и банковскую гарантию."]
    md = "\n".join(L) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Файл: {a.out}")
    else:
        print(md)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("id")
    ap.add_argument("--name", default="Компания")
    ap.add_argument("--deal", type=float, help="сумма сделки, тыс. ₽")
    ap.add_argument("--zavod", action="store_true")
    ap.add_argument("--guest", action="store_true")
    ap.add_argument("--out")
    run(ap.parse_args())
