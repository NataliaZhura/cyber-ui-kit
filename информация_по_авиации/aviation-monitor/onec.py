#!/usr/bin/env python3
"""Чтение страниц 1С:Контрагент (fd.1cont.ru) под твоей учётной записью через браузер без экрана.

  ~/pw/bin/python onec.py probe                      что показывает сайт без входа: адрес, поля формы, кнопки
  ~/pw/bin/python onec.py login                      вход; сессия сохраняется, пароль больше не нужен до её истечения
  ~/pw/bin/python onec.py report 1025007509768       все разделы (скоринг, финансы, суды, приставы, лизинги…) → 1cont/<ОГРН>_отчёт_1С.txt
  ~/pw/bin/python onec.py fetch 1025007509768        страница скоринга компании по ОГРН → текст в 1cont/
  ~/pw/bin/python onec.py fetch 1025007509768 main/finance   другой раздел той же компании

Логин и пароль — в ~/.secrets/1cont (строка 1 — логин, строка 2 — пароль, права 600). В чат их не присылай.
"""
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
OUT = BASE / "1cont"
SECRETS = Path.home() / ".secrets"
CREDS = SECRETS / "1cont"
STATE = SECRETS / "1cont_state.json"
START = "https://fd.1cont.ru/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")


def browser(p, with_state=True):
    b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    st = str(STATE) if with_state and STATE.exists() else None
    ctx = b.new_context(storage_state=st, user_agent=UA, locale="ru-RU", viewport={"width": 1366, "height": 900})
    return b, ctx


def describe(page):
    """Что на странице: адрес, заголовок, поля ввода и кнопки — без значений полей."""
    print(f"Адрес: {page.url}\nЗаголовок: {page.title()}")
    for el in page.query_selector_all("input"):
        a = {k: el.get_attribute(k) for k in ("type", "name", "id", "placeholder")}
        if a["type"] != "hidden":
            print(f"  поле: {a}")
    for el in page.query_selector_all("button, input[type=submit], a[role=button]"):
        t = " ".join((el.inner_text() or el.get_attribute("value") or "").split())
        if t:
            print(f"  кнопка: {t[:60]}")
    for f in page.frames[1:]:
        print(f"  встроенное окно: {f.url}")


def open_login(page):
    """Стартовая страница — публичный поиск. Сначала закрываем плашку cookie («ОК»), потом жмём
    «Вход и регистрация». Форма может открыться в этой же вкладке, в новой вкладке или на сайте входа 1С."""
    page.goto(START, wait_until="networkidle", timeout=60000)
    if page.query_selector("input[type=password]"):
        return page
    ok = page.get_by_role("button", name="ОК")
    if ok.count():
        ok.first.click()
        page.wait_for_timeout(500)
    ctx = page.context
    before = len(ctx.pages)
    btn = page.get_by_role("button", name="Вход и регистрация")
    if not btn.count():
        btn = page.get_by_text("Вход и регистрация", exact=False)
    btn.first.click()
    for _ in range(20):  # до 10 секунд ждём форму, новую вкладку или переход на другой адрес
        page.wait_for_timeout(500)
        if len(ctx.pages) > before or page.url.rstrip("/") != START.rstrip("/") or page.query_selector("input[type=password]"):
            break
    page = ctx.pages[-1]
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(1500)
    return page


def cmd_probe():
    with sync_playwright() as p:
        b, ctx = browser(p, with_state=False)
        page = ctx.new_page()
        page.goto(START, wait_until="networkidle", timeout=60000)
        print("— стартовая страница —")
        describe(page)
        page = open_login(page)
        print("\n— после «Вход и регистрация» —")
        describe(page)
        text = " ".join(page.inner_text("body").split())
        print(f"Текст страницы: {text[:400]}")
        OUT.mkdir(exist_ok=True)
        page.screenshot(path=str(OUT / "probe.png"), full_page=True)
        print(f"Снимок экрана: {OUT / 'probe.png'}")
        b.close()


def cmd_login():
    """Вход через окно «Вход в продукты Актион» (id2.action-media.ru): логин (почта/телефон) + пароль.
    Окно входа может закрыться само после успеха — тогда проверяем главную страницу сайта."""
    if not CREDS.exists():
        sys.exit(f"Нет файла {CREDS}: сначала создай его (логин и пароль).")
    login, password = CREDS.read_text(encoding="utf-8").splitlines()[:2]
    with sync_playwright() as p:
        b, ctx = browser(p, with_state=False)
        page = open_login(ctx.new_page())
        pwd = page.wait_for_selector("input[type=password]", timeout=30000)
        user = page.query_selector("input[name=login], input[type=email], input[name*=user i], "
                                   "input[name*=mail i], input[type=text], input:not([type])")
        if not user:
            sys.exit("Не нашёл поле логина — запусти probe и пришли вывод.")
        user.fill(login)
        pwd.fill(password)
        btn = page.get_by_role("button", name="Войти")
        (btn.first.click() if btn.count() else pwd.press("Enter"))
        for _ in range(30):  # до 15 секунд: окно закрылось или ушло со страницы входа
            ctx.pages[0].wait_for_timeout(500)
            if page.is_closed() or "logon" not in page.url:
                break
        if not page.is_closed() and page.query_selector("input[type=password]"):
            OUT.mkdir(exist_ok=True)
            page.screenshot(path=str(OUT / "login_fail.png"), full_page=True)
            err = " ".join(page.inner_text("body").split())[:300]
            sys.exit(f"Вход не прошёл. Текст на странице: {err}\nСнимок: 1cont/login_fail.png")
        main = ctx.new_page()
        main.goto(START, wait_until="networkidle", timeout=60000)
        logged = "Вход и регистрация" not in main.inner_text("body")[:3000]
        SECRETS.mkdir(mode=0o700, exist_ok=True)
        ctx.storage_state(path=str(STATE))
        STATE.chmod(0o600)
        print("Вход выполнен, сессия сохранена." if logged else
              "Форма входа принята, но на главной всё ещё кнопка «Вход и регистрация» — проверим fetch.")
        b.close()


def cmd_fetch(ogrn, section="main/scoring"):
    url = f"https://fd.1cont.ru/contragent/{ogrn}/{section.strip('/')}"
    with sync_playwright() as p:
        b, ctx = browser(p)
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(3000)  # дорисовка таблиц и графиков после загрузки
        if page.query_selector("input[type=password]") or "Вход и регистрация" in page.inner_text("body")[:3000]:
            print("Внимание: вход не выполнен — сохраняю то, что видно без входа.")
        OUT.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        name = f"{ogrn}_{section.strip('/').replace('/', '_')}_{stamp}"
        text = page.inner_text("body")
        (OUT / f"{name}.txt").write_text(f"Источник: {url}\nВыгружено: {stamp} МСК\n\n{text}", encoding="utf-8")
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        links = sorted({h for h in (a.get_attribute("href") for a in page.query_selector_all("a"))
                        if h and f"/contragent/{ogrn}/" in h})
        print(f"Сохранено: 1cont/{name}.txt ({len(text)} символов) и .png")
        if links:
            print("Разделы этой компании на сайте:\n  " + "\n  ".join(links))
        b.close()


# Разделы для справки кредитному комитету: подпись ссылки в меню сайта → заголовок в отчёте
REPORT = [("Скоринг", "Скоринг"), ("Руководители и учредители", "Руководители и учредители"),
          ("Баланс и финрезультаты", "Баланс и финансовые результаты"), ("Финансовый анализ", "Финансовый анализ"),
          ("Арбитраж", "Арбитражные суды"), ("Приставы", "Исполнительные производства"),
          ("Налоги и взносы", "Налоги и взносы"), ("Залоги", "Залоги"), ("Лизинги", "Лизинги"),
          ("Связи", "Связанные компании"), ("Госконтракты", "Госконтракты")]
MENU_END = ("Дополнительные проверки", "Товарные знаки")


def content(text):
    """Текст страницы без левого меню сайта (оно одинаковое на всех страницах компании)."""
    lines = text.splitlines()
    for marker in MENU_END:
        idx = [i for i, l in enumerate(lines) if l.strip().startswith(marker)]
        if idx:
            return "\n".join(l for l in lines[idx[0] + 1:] if l.strip())
    return "\n".join(l for l in lines if l.strip())


def cmd_report(ogrn, limit="4000"):
    """Все разделы из REPORT одним проходом → 1cont/<ОГРН>_отчёт_1С.txt (по каждому — до limit знаков)."""
    limit = int(limit)
    start = f"https://fd.1cont.ru/contragent/{ogrn}/main/scoring"
    with sync_playwright() as p:
        b, ctx = browser(p)
        page = ctx.new_page()
        page.goto(start, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(3000)
        if "Вход и регистрация" in page.inner_text("body")[:3000]:
            sys.exit("Вход не выполнен или сессия истекла — запусти: onec.py login")
        menu = {}
        for a in page.query_selector_all("a"):
            h, t = a.get_attribute("href"), " ".join((a.inner_text() or "").split())
            if h and f"/contragent/{ogrn}/" in h and t:
                menu.setdefault(t, h)  # подпись может быть с числом: «Приставы 63»
        stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        out = [f"1С:Контрагент — {ogrn}", f"Выгружено: {stamp} МСК", ""]
        for label, title in REPORT:
            href = next((h for t, h in menu.items() if t.startswith(label)), None)
            if label == "Скоринг":
                href = start
            if not href:
                out += [f"=== {title} ===", "раздел не найден в меню", ""]
                continue
            url = href if href.startswith("http") else "https://fd.1cont.ru" + href
            try:
                page.goto(url, wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(2500)
                txt = content(page.inner_text("body"))
            except Exception as ex:  # noqa: BLE001 — один раздел не должен ронять весь отчёт
                txt = f"не загрузился: {type(ex).__name__}"
            cut = " … (обрезано)" if len(txt) > limit else ""
            out += [f"=== {title} ===", f"Источник: {url}", txt[:limit] + cut, ""]
            print(f"  {title}: {len(txt)} знаков")
        b.close()
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{ogrn}_отчёт_1С.txt"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"Отчёт: {path}")


if __name__ == "__main__":
    cmds = {"probe": cmd_probe, "login": cmd_login, "fetch": cmd_fetch, "report": cmd_report}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(1)
    cmds[sys.argv[1]](*sys.argv[2:])
