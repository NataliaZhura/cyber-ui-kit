#!/usr/bin/env python3
"""Оценка модели (NPV, IRR, окупаемость на горизонте) и сценарии по допущениям — правка ТЕКУЩЕГО AGENTS.md по меткам.

  python3 patch_eval.py                 показать, что изменится (Ави)
  python3 patch_eval.py --apply         применить (копия прежнего файла — в bak/)
  python3 patch_eval.py --agents ~/.openclaw/workspace-tester/AGENTS.md [--apply]   то же для тестера
  python3 patch_eval.py --zhd --agents ~/.openclaw/workspace-zhdusha/AGENTS.md [--apply]   ЖДуша (и её гость zguest):
        отдельный раздел «Оценка финмодели» с полными путями — программы общие, в ~/aviation-monitor
Повторный запуск ничего не ломает.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
AGENTS = Path(sys.argv[sys.argv.index("--agents") + 1]).expanduser() if "--agents" in sys.argv \
    else Path.home() / ".openclaw" / "workspace" / "AGENTS.md"
MARK = "Оценка на горизонте."
AFTER = "(паспорт: `skills/model-stress/SKILL.md`), расчёт только программой `cf.py`, не «в уме».\n"
ADD = ("\n**Оценка на горизонте.** Прислали модель — тот же навык: свободный поток проекта и акционера, NPV, IRR,\n"
       "рентабельность, окупаемость (простая и дисконтированная) — только на горизонте, который выбрал пользователь.\n"
       "Ставку дисконтирования **всегда спрашивай**, не угадывай. Сценарии выбирает тот, кто прислал модель: есть\n"
       "допущения — меняем их и пересчитываем модель её формулами (`assume.py`, системный python3); нет — доходы,\n"
       "расходы, ставка по кредитам, процентные платежи. Excel с расчётом — тому, кто прислал модель.\n")
ZHD_MARK = "## Оценка финмодели (любая модель)"
ZHD_ADD = """
## Оценка финмодели (любая модель)

Прислали Excel-модель (любой отрасли: железная дорога, авиация, другое) и просят оценить, посчитать NPV, IRR,
окупаемость, свободный поток или стресс-тест — **сначала прочитай целиком** `~/aviation-monitor/skills/model-stress/SKILL.md`
и действуй по разделу «Оценка на горизонте и сценарии на выбор». Команды запускай из каталога `~/aviation-monitor`
(`cd ~/aviation-monitor && …`), свои файлы клади в `excel/out/` с приставкой `zhd_`. Расчёт — только программами
`cf.py` и `assume.py`, не «в уме». Горизонт и ставку дисконтирования **всегда спрашивай**, ставку не угадывай;
сценарии выбирает тот, кто прислал модель. Excel с расчётом отправь тому, кто прислал модель, **своим обычным способом
отправки файлов** (не через `share.py` — он отправляет от имени другого бота). Это анализ модели, а не решение банка.
"""
MENU_MARK = "**Меню `/model`.**"
MODEL_MENU = """
**Меню `/model`.** На команду `/model` — и когда прислали Excel-файл без вопроса — ответь сразу, ничего не запуская, так:
«Анализ финансовой модели — что сделать?
1 — полная оценка: свободный поток, NPV, IRR, окупаемость, рентабельность + стресс-тест
2 — только оценка проекта: NPV, IRR, окупаемость, рентабельность на выбранном горизонте
3 — стресс-тест по допущениям модели: покажу допущения, вы выберете, что и на сколько изменить
4 — стандартные стресс-сценарии: доходы −10% и расходы +10%; доходы +5% и расходы +10%; ставка по кредитам
    +3 п. п.; процентные платежи +20%; всё вместе (можно свои числа)
5 — покрытие долга: DSCR, DCR и где модель «пробивает» порог банка
6 — проверка модели: ошибки, «зашитые» числа, скрытые листы
Ответьте цифрой и пришлите файл Excel, если ещё не прислали.»
Дальше — по навыку `model-stress` (раздел «Оценка на горизонте и сценарии на выбор»): 1 — шаги 1–8; 2 — без
шага 6; 3 — шаг 6, ветка «допущения есть» (их нет — скажи и предложи пункт 4); 4 — шаг 6, ветка «допущений нет»;
5 — раздел «Стресс покрытия долга»; 6 — только `xl.py info` и `xl.py check`. Горизонт и ставку дисконтирования
спрашивай всегда (для 2–4), по одному вопросу.
"""
ROW_PREFIXES = ("| `/bpla` |", "| `/compare` |")
ROW_ADD = "| `/model` | пункт подменю (ниже, «Меню /model») и файл Excel | оценка модели: NPV, IRR, окупаемость, стресс-тест |\n"
GREET_OLD = "• пришлите Excel-модель — проверю её и сделаю стресс-тест\n"
GREET_NEW = "• пришлите Excel-модель — проверю её, посчитаю NPV, IRR, окупаемость и стресс-тест по вашим сценариям\n"


def main():
    if not AGENTS.exists():
        sys.exit(f"Нет {AGENTS}")
    t = AGENTS.read_text(encoding="utf-8")
    new = t
    if "--zhd" in sys.argv:
        if ZHD_MARK in new:
            print("AGENTS.md: раздел оценки модели уже есть — пропускаю")
        else:
            new = new.rstrip("\n") + "\n" + ZHD_ADD
    elif MARK in new:
        print("AGENTS.md: правило оценки уже есть — пропускаю")
    elif AFTER in new:
        new = new.replace(AFTER, AFTER + ADD, 1)
    elif "## Длина сообщений в Telegram" in new:
        new = new.replace("## Длина сообщений в Telegram", ADD.lstrip("\n") + "\n## Длина сообщений в Telegram", 1)
    else:
        new = new.rstrip("\n") + "\n" + ADD
    if MENU_MARK in new:
        print("AGENTS.md: меню /model уже есть — пропускаю")
    else:
        if "--zhd" in sys.argv:
            new = new.rstrip("\n") + "\n" + MODEL_MENU
        else:
            row = next((l for p in ROW_PREFIXES for l in new.splitlines(keepends=True) if l.startswith(p)), None)
            if row:
                new = new.replace(row, row + ROW_ADD, 1)
            k = new.find(MARK)
            end = new.find("\n\n", k) if k >= 0 else -1
            new = new[:end + 1] + MODEL_MENU + new[end + 1:] if end >= 0 else new.rstrip("\n") + "\n" + MODEL_MENU
    if "--zhd" in sys.argv:
        pass
    elif GREET_OLD in new:
        new = new.replace(GREET_OLD, GREET_NEW, 1)
    elif GREET_NEW not in new:
        print("AGENTS.md: строка про Excel-модель в приветствии не найдена — приветствие не меняю")
    if new == t:
        print("Менять нечего.")
        return
    print(f"• {AGENTS}: " + ("раздел «Оценка финмодели (любая модель)» и меню /model" if "--zhd" in sys.argv
                              else "правило «Оценка на горизонте», меню /model, строка в приветствии"))
    if "--apply" not in sys.argv:
        print("Это предпросмотр. Применить: добавь --apply")
        return
    (BASE / "bak").mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    shutil.copy2(AGENTS, BASE / "bak" / f"{AGENTS.parent.name}-AGENTS-before-eval-{stamp}.md")
    AGENTS.write_text(new, encoding="utf-8")
    print(f"Готово. Копия: bak/{AGENTS.parent.name}-AGENTS-before-eval-{stamp}.md")


if __name__ == "__main__":
    main()
