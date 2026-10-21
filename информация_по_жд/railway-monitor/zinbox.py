#!/usr/bin/env python3
"""Приёмка загрузок без нейросети (0 токенов): файлы из «Мои загрузки» мини-приложения (saved/upload/) → по папкам.

  python3 zinbox.py            разложить: выпуски Argus → private/argus/ (имя по дате выпуска, повтор пропускается) и
                               сразу в базу наблюдений (zobs.py); прочее — private/materials/; итог — строкой владельцу
  python3 zinbox.py status     какие месяцы выпусков есть и каких не хватает (по private/argus/)
Мини-приложение запускает раскладку само через 30 секунд после загрузки PDF владельцем.

Выпуск узнаётся по первой странице («Argus … ДД месяца ГГГГ»), а не по имени файла. Уже лежащий выпуск того же номера
и даты не копируется второй раз. Файлы не удаляются: обработанные из saved/upload/ переносятся, дубликаты — в
private/duplicates/.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
UP, ARG, MAT, DUP = BASE / "saved" / "upload", BASE / "private" / "argus", BASE / "private" / "materials", BASE / "private" / "duplicates"
GEN = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7, "августа": 8,
       "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def first_page(p):
    try:
        out = subprocess.run(["pdftotext", "-l", "2", str(p), "-"], capture_output=True, text=True, timeout=60).stdout
        if out.strip():
            return out
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        import logging
        import pdfplumber
        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        with pdfplumber.open(p) as pdf:
            return "\n".join((pg.extract_text() or "") for pg in pdf.pages[:2])
    except Exception:  # noqa: BLE001 — не PDF или битый файл: в «материалы»
        return ""


def argus_id(text):
    """('logistics' | 'oil' | …, 'ГГГГ-ММ-ДД') или None."""
    if "Argus" not in text:
        return None
    kind = "логистика" if "Логистика сухих грузов" in text else "нефтетранспорт" if "Нефтетранспорт" in text else "прочее"
    m = re.search(r"(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})", text)
    if not m:
        m2 = re.search(r"(Январь|Февраль|Март|Апрель|Май|Июнь|Июль|Август|Сентябрь|Октябрь|Ноябрь|Декабрь)\s+(\d{4})", text)
        if not m2:
            return None
        return kind, f"{m2.group(2)}-{RU.index(m2.group(1).lower()) + 1:02d}-01"
    return kind, f"{m.group(3)}-{GEN[m.group(2)]:02d}-{int(m.group(1)):02d}"


def have():
    """Выпуски в private/argus/: {(вид, ГГГГ-ММ): файл}."""
    out = {}
    for p in sorted(ARG.glob("*.pdf")) if ARG.is_dir() else []:
        m = re.match(r"(\d{4}-\d{2})-\d{2}_argus_(\w+)\.pdf$", p.name)
        if m:
            out[(m.group(2), m.group(1))] = p
            continue
        i = argus_id(first_page(p))
        if i:
            out[(i[0], i[1][:7])] = p
    return out


def cmd_sort():
    files = [p for p in sorted(UP.glob("*")) if p.is_file()] if UP.is_dir() else []
    if not files:
        return print("В «Мои загрузки» новых файлов нет.")
    ARG.mkdir(parents=True, exist_ok=True)
    known = have()
    new_argus, mats, dups = [], [], []
    for p in files:
        i = argus_id(first_page(p)) if p.suffix.lower() == ".pdf" else None
        if i:
            key = (i[0], i[1][:7])
            if key in known:
                DUP.mkdir(parents=True, exist_ok=True)
                shutil.move(p, DUP / p.name)
                dups.append(f"{i[0]} {i[1][:7]}")
                continue
            dst = ARG / f"{i[1]}_argus_{i[0]}.pdf"
            shutil.move(p, dst)
            known[key] = dst
            new_argus.append(dst)
        else:
            MAT.mkdir(parents=True, exist_ok=True)
            shutil.move(p, MAT / p.name)
            mats.append(p.name)
    logi = [p for p in new_argus if "логистика" in p.name]
    if logi:
        subprocess.run([sys.executable, str(BASE / "zobs.py"), "pdf"] + [str(p) for p in logi])
    msg = (f"Принято: выпусков Argus — {len(new_argus)} ({', '.join(p.name[:7] for p in new_argus) or '—'}), "
           f"повторов пропущено — {len(dups)}, материалов — {len(mats)}.")
    print(msg)
    subprocess.run([sys.executable, str(BASE / "send.py"), "--note", msg[:200]], capture_output=True)
    cmd_status()


def cmd_status():
    known = have()
    for kind in ("логистика", "нефтетранспорт"):
        ms = sorted(m for k, m in known if k == kind)
        if not ms:
            continue
        print(f"Argus {kind}: есть {len(ms)} — {', '.join(ms)}")
        for y in sorted({m[:4] for m in ms}):
            last = 12 if y < max(ms)[:4] else int(max(ms)[5:])
            miss = [f"{y}-{k:02d}" for k in range(1, last + 1) if f"{y}-{k:02d}" not in ms]
            print(f"  {y}: не хватает — {', '.join(miss) if miss else 'нет пропусков'}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["status"]:
        sys.exit(cmd_status())
    import fcntl
    import time
    if "--wait" in sys.argv:  # вызов из мини-приложения: подождать, пока догрузятся остальные файлы пачки
        time.sleep(30)
    lock = open(BASE / ".zinbox.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)  # идёт другая раскладка — дождаться её, потом забрать оставшееся
    cmd_sort()
