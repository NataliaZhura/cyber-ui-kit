#!/usr/bin/env python3
"""Методика прогноза — только владельцу. Гостю, респонденту и любому внешнему читателю — результат без «как считаем».

  zclosed.strip(md)   убрать из отчёта разделы и строки о методике (факторы и их вклад, цена фактора, точность и
                      проверка модели, «как считается», допущения сценариев, способы расчёта)
  zclosed.public(r)   то же для ответа мини-приложения «Построить прогноз» (словарь)
  python3 zclosed.py <файл.md>   показать, что останется гостю

Вызывают: zrate/ztypes/zmodel/zvagon/zdeal с --guest, zpdf и zapp для не-владельца.
"""
import re
import sys

NOTE = "Оценка ЖДуши по открытым данным рынка. Не инвестиционная рекомендация."
# заголовки разделов, которые гостю не показываем целиком (подстрока, без учёта регистра)
HEADS = ("из чего складывается", "цена фактора", "все факторы", "точност", "как считается", "что нужно, чтобы",
         "за чем следить", "что двигает", "допущения сценари", "откуда значения", "методик", "проверка модели",
         "на что смотреть каждый месяц", "подсказка к выбору сценария", "как строится", "как устроен")
# строки о способе расчёта — убираем, где бы ни стояли
WORDS = re.compile(r"модел|способ|β|γ|эластичн|регресс|точнее всего|ошибк[аи] ±|направление угадано|по истории|"
                   r"проверк[аи] (модели|допущений)|фактор|темп (сентября|ставки)|сумма 12 месяцев|середина между",
                   re.I)


def strip(md):
    out, skip = [], 0
    for line in md.splitlines():
        h = re.match(r"^(#{1,6})\s+(.*)", line)
        if h:
            lvl = len(h.group(1))
            if skip and lvl > skip:
                continue
            skip = lvl if any(x in h.group(2).lower() for x in HEADS) else 0
            if skip:
                continue
        elif skip:
            continue
        if not h and WORDS.search(line):
            continue
        out.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).rstrip() + "\n"
    return text if NOTE in text else text + f"\n<small>{NOTE}</small>\n"


# ключи ответа /api/forecast, раскрывающие устройство модели
DROP = ("parts", "end", "parts_scenario", "price", "need", "defaults", "factors", "fields", "help", "accuracy")


def public(r):
    if not isinstance(r, dict) or r.get("error"):
        return r
    r = {k: v for k, v in r.items() if k not in DROP}
    r["cap"], r["pace_label"], r["closed"] = [], "", True
    for q in (r.get("q4") or {}).values():
        q.pop("pace", None)
    return r


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    print(strip(open(sys.argv[1], encoding="utf-8").read()))
