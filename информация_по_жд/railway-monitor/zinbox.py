#!/usr/bin/env python3
"""Приёмка загрузок без нейросети (0 токенов): файлы из «Мои загрузки» мини-приложения (saved/upload/) → по папкам.

  python3 zinbox.py            разложить: выпуски Argus → private/argus/ (имя по дате выпуска, повтор пропускается) и
                               сразу в базу наблюдений (zobs.py); прочее — private/materials/; итог — строкой владельцу
  python3 zinbox.py status     какие месяцы выпусков есть и каких не хватает (по private/argus/)
  python3 zinbox.py rescan     заново узнать все выпуски (private/argus/ и duplicates/), переименовать, в базу наблюдений
Мини-приложение запускает раскладку само через 30 секунд после загрузки PDF владельцем.

Выпуск узнаётся по первой странице («Argus … ДД месяца ГГГГ»), а не по имени файла. Уже лежащий выпуск того же номера
и даты не копируется второй раз. Файлы не удаляются: обработанные из saved/upload/ переносятся, дубликаты — в
private/duplicates/.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
UP, ARG, MAT, DUP = BASE / "saved" / "upload", BASE / "private" / "argus", BASE / "private" / "materials", BASE / "private" / "duplicates"
PROC = BASE / "private" / "procure"  # сохранённые страницы закупок ЕИС (zprocure.py)
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
    """('логистика' | 'нефтетранспорт' | 'прочее', 'ГГГГ-ММ-01') или None. Месяц — по номеру выпуска на обложке
    («2026, выпуск VIII, № 9» — № совпадает с месяцем), иначе по колонтитулу «Логистика сухих грузов ДД месяца ГГГГ»."""
    if "Argus" not in text:
        return None
    flat = " ".join(text.split())
    kind = "логистика" if "сухих грузов" in flat else "нефтетранспорт" if "Нефтетранспорт" in flat else "прочее"
    m = re.search(r"(20\d\d),\s*выпуск\s+[IVXLC]+,\s*№\s*(\d{1,2})\b", flat)
    if m and 1 <= int(m.group(2)) <= 12:
        return kind, f"{m.group(1)}-{int(m.group(2)):02d}-01"
    m = re.search(r"(?:сухих грузов|Нефтетранспорт)\s+(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|"
                  r"октября|ноября|декабря)\s+(20\d\d)", flat)
    if m:
        return kind, f"{m.group(3)}-{GEN[m.group(2)]:02d}-01"
    m = re.search(r"(Январь|Февраль|Март|Апрель|Май|Июнь|Июль|Август|Сентябрь|Октябрь|Ноябрь|Декабрь)\s+(20\d\d),\s*выпуск", flat)
    return (kind, f"{m.group(2)}-{RU.index(m.group(1).lower()) + 1:02d}-01") if m else None


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
    new_argus, mats, dups, proc = [], [], [], []
    for p in files:
        if p.suffix.lower() in (".html", ".htm"):  # сохранённая страница поиска закупок ЕИС → zprocure.py import
            PROC.mkdir(parents=True, exist_ok=True)
            dst = PROC / p.name
            shutil.move(p, dst)
            proc.append(dst)
            continue
        low = p.name.lower()
        if p.suffix.lower() == ".pdf" and any(k in low for k in ("как_ждуша", "методика", "проверка_модели")):
            dst = BASE / "saved" / "model" / p.name  # методика и проверка модели — в раздел мини-приложения
            dst.parent.mkdir(parents=True, exist_ok=True)
            if "как_ждуша" in low and "внутр" not in low:  # версия для клиентов и кредиторов — и гостям
                (BASE / "forecast" / "guest").mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, BASE / "forecast" / "guest" / p.name)
            shutil.move(p, dst)
            mats.append(p.name)
            continue
        fp = first_page(p) if p.suffix.lower() == ".pdf" else ""
        if p.suffix.lower() == ".pdf" and ("zakupki.gov.ru" in fp or "Начальная цена" in fp) and "Argus" not in fp:
            PROC.mkdir(parents=True, exist_ok=True)  # страница поиска закупок, сохранённая в PDF с телефона
            dst = PROC / p.name
            shutil.move(p, dst)
            proc.append(dst)
            continue
        i = argus_id(fp) if fp else None
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
        # новый месяц: сначала сверка с прошлым прогнозом и оповещения, потом новый прогноз — в журнал
        subprocess.run([sys.executable, str(BASE / "zrates.py"), "alerts", "--send"])
        subprocess.run([sys.executable, str(BASE / "zrates.py"), "snap"])
        subprocess.Popen([sys.executable, str(BASE / "zsecond.py"), "run"], start_new_session=True)  # второе мнение GPT
    pr = ""
    if proc:
        r = subprocess.run([sys.executable, str(BASE / "zprocure.py"), "import"] + [str(p) for p in proc],
                           capture_output=True, text=True)
        pr = " Закупки: " + (r.stdout.strip().splitlines() or ["нет"])[-1]
    msg = (f"Принято: выпусков Argus — {len(new_argus)} ({', '.join(p.name[:7] for p in new_argus) or '—'}), "
           f"повторов пропущено — {len(dups)}, материалов — {len(mats)}.{pr}")
    print(msg)
    subprocess.run([sys.executable, str(BASE / "send.py"), "--note", msg[:200]], capture_output=True)
    cmd_status()


def cmd_rescan():
    """Заново узнать все выпуски в private/argus/ и private/duplicates/: правильные имена, по одному на месяц (больший
    файл), остальное — в повторы; затем все «Логистика» — в базу наблюдений."""
    files = [p for d in (ARG, DUP) if d.is_dir() for p in sorted(d.glob("*.pdf"))]
    best, other = {}, []
    for p in files:
        i = argus_id(first_page(p))
        if not i:
            other.append(p)
            continue
        key = (i[0], i[1][:7])
        if key not in best or p.stat().st_size > best[key][0].stat().st_size:
            if key in best:
                other.append(best[key][0])
            best[key] = (p, i[1])
        else:
            other.append(p)
    ARG.mkdir(parents=True, exist_ok=True)
    DUP.mkdir(parents=True, exist_ok=True)
    tmp = []
    for (kind, _), (p, date) in best.items():  # через временные имена: два файла могли поменяться местами
        t_ = p.with_name(f"_rescan_{len(tmp)}.pdf")
        p.rename(t_)
        tmp.append((t_, ARG / f"{date}_argus_{kind}.pdf"))
    for t_, dst in tmp:
        t_.rename(dst)
    moved = 0
    for p in other:
        if p.exists() and p.parent != DUP:
            n, dst = 1, DUP / p.name
            while dst.exists():
                dst, n = DUP / f"{p.stem}_{n}{p.suffix}", n + 1
            p.rename(dst)
            moved += 1
    logi = sorted(dst for _, dst in tmp if "логистика" in dst.name)
    print(f"Выпусков: {len(best)}, в повторы и неопознанные: {moved}.")
    if logi:
        subprocess.run([sys.executable, str(BASE / "zobs.py"), "pdf"] + [str(p) for p in logi])
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


def ensure_pdf_reader():
    """Нет pdftotext и pdfplumber в этом Python — перезапуск через ~/pw/bin/python (там pdfplumber, как у zreport.py)."""
    if shutil.which("pdftotext"):
        return
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        pw = Path.home() / "pw" / "bin" / "python"
        if pw.exists() and not os.environ.get("ZINBOX_PW"):  # ~/pw/bin/python — ссылка на тот же python, но своё окружение
            os.environ["ZINBOX_PW"] = "1"
            os.execv(str(pw), [str(pw), str(Path(__file__).resolve())] + sys.argv[1:])
        sys.exit("Нечем читать PDF: нет pdftotext и pdfplumber (~/pw/bin/python).")


if __name__ == "__main__":
    ensure_pdf_reader()
    if sys.argv[1:2] == ["status"]:
        sys.exit(cmd_status())
    if sys.argv[1:2] == ["rescan"]:
        sys.exit(cmd_rescan())
    import fcntl
    import time
    if "--wait" in sys.argv:  # вызов из мини-приложения: подождать, пока догрузятся остальные файлы пачки
        time.sleep(30)
    lock = open(BASE / ".zinbox.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)  # идёт другая раскладка — дождаться её, потом забрать оставшееся
    cmd_sort()
