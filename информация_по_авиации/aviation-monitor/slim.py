#!/usr/bin/env python3
"""Укоротить инструкцию агента: AGENTS.md читается при КАЖДОМ ответе и каждом запуске по расписанию.

  python3 slim.py <путь к AGENTS.md>                   показать, что изменится (файлы не трогает)
  python3 slim.py <путь к AGENTS.md> --apply           применить: копия в bak/, затем запись
  python3 slim.py <путь к AGENTS.md> --relay --apply   плюс правило «справку и сигнал — дословно в out/» (только Ави)

Что делает (работает с текущим файлом на сервере, а не заменяет его целиком — серверные правки сохраняются):
1. Порядок справки по компании, пороги нагрузки и «как показывать цифры» — нужны только при справке по компании —
   переносит в guides/company-report.md, а в AGENTS.md оставляет указание прочитать этот файл перед справкой.
   Правила безопасности («Правила анализа») остаются в AGENTS.md.
2. --relay: правило сохранять готовую утреннюю справку и сигнал в out/ — их без модели получат подписчики (relay.py).
Повторный запуск ничего не ломает: сделанное пропускается.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
GUIDE = BASE / "guides" / "company-report.md"
START, STOP = "### Порядок справки", "### Правила анализа"
POINTER = """### Порядок справки, пороги нагрузки, как показывать цифры
Перед любой справкой по компании (/profile, /finance, /courts, /assets, /compare) **сначала прочитай целиком**
`~/aviation-monitor/guides/company-report.md`: порядок разделов, пороги нагрузки, оформление цифр.
Без него справку не начинай. В ответах этот файл не упоминай.
"""
AFTER = "| **Квартальная карточка** |"
RELAY = """
**Рассылка без модели.** Утренняя справка и дневной сигнал из расписания: готовый текст сообщения **дословно**
сохрани в `~/aviation-monitor/out/daily_ГГГГ-ММ-ДД.md` (утренняя) или `~/aviation-monitor/out/signal_ГГГГ-ММ-ДД_ЧЧММ.md`
(сигнал). Его без модели получат подписчики (`relay.py`). Нечего прислать — файл не создавай.
"""


def split_guide(lines):
    if any(ln.startswith("### Порядок справки, пороги") for ln in lines):
        return lines, None, "1. Справка уже вынесена — пропускаю."
    try:
        a = next(i for i, ln in enumerate(lines) if ln.startswith(START))
        b = next(i for i, ln in enumerate(lines) if i > a and ln.startswith(STOP))
    except StopIteration:
        return lines, None, f"1. Не нашёл разделы «{START}» … «{STOP}» — пропускаю, ничего не трогаю."
    block = lines[a:b]
    guide = "# Справка по компании: порядок, пороги, цифры\n\n" \
            "Читается перед каждой справкой по компании. Дополняет раздел «Справка по компании» в AGENTS.md.\n\n" + \
            "".join(ln.replace("### ", "## ", 1) if ln.startswith("### ") else ln for ln in block)
    new = lines[:a] + [POINTER, "\n"] + lines[b:]
    return new, guide, f"1. В guides/company-report.md переносится {len(block)} строк ({sum(map(len, block))} знаков)."


def add_relay(lines):
    if any("Рассылка без модели" in ln for ln in lines):
        return lines, "2. Правило рассылки уже есть — пропускаю."
    i = next((i for i, ln in enumerate(lines) if ln.startswith(AFTER)), None)
    if i is None:
        return lines, f"2. Не нашёл строку «{AFTER}» — правило рассылки не добавляю."
    return lines[:i + 1] + [RELAY] + lines[i + 1:], "2. Добавляется правило рассылки (после таблицы видов справок)."


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    path = Path(args[0]).expanduser()
    old = path.read_text(encoding="utf-8")
    lines = old.splitlines(keepends=True)
    lines, guide, msg = split_guide(lines)
    print(msg)
    if "--relay" in sys.argv:
        lines, msg = add_relay(lines)
        print(msg)
    new = "".join(lines)
    print(f"AGENTS.md: {len(old)} → {len(new)} знаков ({100 - round(100 * len(new) / max(len(old), 1))}% короче)")
    if new == old:
        return
    if "--apply" not in sys.argv:
        print("Это предпросмотр. Применить: добавь --apply")
        return
    bak = BASE / "bak"
    bak.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    shutil.copy2(path, bak / f"AGENTS-before-slim-{stamp}.md")
    if guide is not None:
        GUIDE.parent.mkdir(exist_ok=True)
        if GUIDE.exists() and GUIDE.read_text(encoding="utf-8") != guide:
            shutil.copy2(GUIDE, bak / f"company-report-{stamp}.md")
        GUIDE.write_text(guide, encoding="utf-8")
    path.write_text(new, encoding="utf-8")
    print(f"Готово. Копия прежнего файла: bak/AGENTS-before-slim-{stamp}.md")


if __name__ == "__main__":
    main()
