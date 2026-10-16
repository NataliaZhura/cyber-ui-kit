#!/usr/bin/env python3
"""Новостной блок «БПЛА и низковысотная авиация» — правка ТЕКУЩИХ файлов на сервере, без замены целиком.

  python3 patch_uav.py            показать, что изменится
  python3 patch_uav.py --apply    применить (копии прежних файлов — в bak/)

Что меняет: раздел «Вертолёты и БПЛА» делится на «БПЛА и низковысотная авиация» и «Вертолёты»; новые поисковые
запросы по БАС и малой авиации; запреты полётов для гражданских дронов не теряются в фильтре военных сводок;
правило раздела в AGENTS.md и порядок разделов в TEMPLATE.md. Повторный запуск ничего не ломает.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
WS = Path.home() / ".openclaw" / "workspace"
OLD, HEL, UAV = "Вертолёты и БПЛА", "Вертолёты", "БПЛА и низковысотная авиация"
UAV_WORDS = ["беспилотн авиационн", "беспилотные авиационн", "беспилотных авиационн", "низковысотн", "малой авиац",
             "малая авиац", "малую авиац", "местной авиац", "местные авиалин", "авиахимработ", "авиационно-химическ",
             "аэрофотосъем", "аэрофотосъём", "внешн пилот", "внешнего пилот", "внешних пилот", "экспериментальн правов",
             "цифровое небо", "лмс-901", "«байкал»", "самолет байкал", "самолета байкал", "самолетов байкал", "л-410",
             "ан-2 ", "квадрокоптер", "мультикоптер", "агродрон"]
TOPICS = ["низковысотная авиация", "малая авиация Россия развитие", "экспериментальный правовой режим беспилотники",
          "учет беспилотных воздушных судов", "ограничение полетов беспилотников гражданские",
          "дроны авиахимработы поля", "доставка грузов беспилотниками", "беспилотники мониторинг ЛЭП трубопроводов",
          "внешний пилот БАС обучение", "лизинг беспилотников субсидия", "производство гражданских беспилотников объем",
          "ЛМС-901 Байкал поставки", "вертолетная компания беспилотники"]
UAV_CIVIL = ["запрет полет", "запрет на полет", "ограничени полет", "ограничения на полет", "сельхоз", "агро", "лэп",
             "доставк", "эксплуатант", "производител", "рынок", "рынк"]
AGENTS_OLD = "- БПЛА: кто производит, где планируют применять, есть ли спрос или техника лежит на складе.\n"
AGENTS_NEW = ("- БПЛА и низковысотная авиация — отдельный раздел: кто производит, где применяют, есть ли спрос или техника лежит\n"
              "  на складе; правила полётов и ограничения по регионам; **что это меняет для вертолётных компаний** (дрон заменяет\n"
              "  вертолёт на авиахимработах, облёте ЛЭП, съёмке — риск выручки; дополняет — новая услуга). Военные сводки\n"
              "  не включай; запреты полётов, которые бьют по гражданским эксплуатантам, — включай.\n")
TEMPLATE_OLD = "4. Вертолёты и БПЛА "
TEMPLATE_NEW = ("4. БПЛА и низковысотная авиация            ← правила полётов, производство, спрос; что меняется для вертолётчиков\n"
                "5. Вертолёты                                ← имущественный риск по вертолётам\n")


def add(lst, items):
    n = 0
    for x in items:
        if x not in lst:
            lst.append(x)
            n += 1
    return n


def patch_sources(d):
    log = []
    secs = d["sections"]
    i = next((k for k, s in enumerate(secs) if s["name"] == OLD), None)
    if i is not None:
        words = secs[i]["words"]
        uav = [w for w in words if any(x in w for x in ("бпла", "беспилот", "дрон", "бвс"))]
        secs[i:i + 1] = [{"name": UAV, "words": uav + [w for w in UAV_WORDS if w not in uav]},
                         {"name": HEL, "words": [w for w in words if w not in uav]}]
        disp = d["sections_display"]
        j = next((k for k, s in enumerate(disp) if s["name"] == OLD), None)
        if j is not None:
            disp[j:j + 1] = [{"name": UAV}, {"name": HEL}]
        for th in d.get("threads", []):
            if th.get("section") == OLD:
                th["section"] = UAV if "БПЛА" in th["name"] else HEL
        log.append(f"раздел «{OLD}» → «{UAV}» + «{HEL}»")
    n = add(d["search_topics"], TOPICS)
    n and log.append(f"поисковых запросов добавлено: {n}")
    n = add(d["assets"]["БПЛА"], ["квадрокоптер", "мультикоптер", "агродрон"])
    n += add(d["aviation_words"], ["низковысот", "малой авиац", "малая авиац", "местной авиац", "авиахимработ"])
    n += add(d["risks"]["допуск к полётам"], ["запрет полетов беспилот", "запрет на полеты беспилот",
                                             "запрет использования беспилот", "ограничени полетов беспилот"])
    n += add(d["civil_override"], ["запрет полет", "запрет на полет", "сельхоз", "агро", "лэп", "доставк", "эксплуатант"])
    if "uav_civil_words" not in d:
        d["_uav_civil_note"] = ("Заголовок со словами военных сводок («удар», «атак») всё же идёт в раздел БПЛА, если речь "
                                "о гражданском рынке: запрет полётов, сельхоз, ЛЭП, доставка")
        d["uav_civil_words"] = UAV_CIVIL
        n += 1
    n and log.append(f"слов для отбора и раздела добавлено: {n}")
    return log


def main():
    apply = "--apply" in sys.argv
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    (BASE / "bak").mkdir(exist_ok=True)
    changes = []
    src = BASE / "sources.json"
    d = json.loads(src.read_text(encoding="utf-8"))
    log = patch_sources(d)
    if log:
        changes.append((src, json.dumps(d, ensure_ascii=False, indent=1) + "\n", "sources.json: " + "; ".join(log)))
    for path, old, new in ((WS / "AGENTS.md", AGENTS_OLD, AGENTS_NEW), (WS / "TEMPLATE.md", TEMPLATE_OLD, TEMPLATE_NEW)):
        if not path.exists():
            print(f"{path.name}: нет файла — пропускаю")
            continue
        t = path.read_text(encoding="utf-8")
        if UAV in t:
            print(f"{path.name}: уже обновлён — пропускаю")
            continue
        if path.name == "TEMPLATE.md":
            lines = t.splitlines(keepends=True)
            k = next((i for i, ln in enumerate(lines) if ln.startswith(TEMPLATE_OLD)), None)
            if k is None:
                print("TEMPLATE.md: строка «4. Вертолёты и БПЛА» не найдена — пропускаю")
                continue
            tail = [ln for ln in lines[k + 1:]]
            # нумерация разделов после вставки сдвигается на один
            for i, ln in enumerate(tail):
                if ln[:1].isdigit() and ". " in ln[:4]:
                    tail[i] = f"{int(ln.split('.')[0]) + 1}{ln[ln.index('.'):]}"
                elif ln.startswith("```"):
                    break
            new_t = "".join(lines[:k]) + TEMPLATE_NEW + "".join(tail)
        else:
            if old not in t:
                print("AGENTS.md: строка про БПЛА не найдена — пропускаю (пришли вывод, поправлю вручную)")
                continue
            new_t = t.replace(old, new)
        changes.append((path, new_t, f"{path.name}: раздел БПЛА"))
    if not changes:
        print("Всё уже обновлено.")
        return
    for path, _, msg in changes:
        print("•", msg)
    if not apply:
        print("Это предпросмотр. Применить: python3 patch_uav.py --apply")
        return
    for path, text, _ in changes:
        shutil.copy2(path, BASE / "bak" / f"{path.stem}-before-uav-{stamp}{path.suffix}")
        path.write_text(text, encoding="utf-8")
    print(f"Готово. Копии прежних файлов: bak/*-before-uav-{stamp}.*")


if __name__ == "__main__":
    main()
