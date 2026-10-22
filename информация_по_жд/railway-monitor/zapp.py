#!/usr/bin/env python3
"""Мини-приложение ЖДуши: отчёты и загрузки по разделам меню. Просмотр — без нейросети (0 токенов).

  python3 zapp.py serve [--port 8787]     запустить (слушает только 127.0.0.1; снаружи — через Caddy с HTTPS)
  python3 zapp.py sort                    показать, какие старые файлы saved/ в какой раздел лягут (ничего не меняет)
  python3 zapp.py sort --apply            разложить (только после «да» владельца; файлы переносятся, не удаляются)
  python3 zapp.py hide prognoz [--date 2026-10-19] [--keep <часть имени>]... [--only <часть имени>]... [--apply]
                                          убрать из раздела файлы за день (дата в имени, иначе дата файла; по умолчанию —
                                          сегодня): сначала список, с --apply — перенос в archive/<дата>/ (не удаляются);
                                          файлы модели и сводки рынка остаются
  python3 zapp.py check                   что умеет `openclaw agent` (для кнопки «Поставить задачу»), только чтение

Кто что видит (проверяется подпись Telegram, подделать нельзя):
  владелец (~/.secrets/zhdusha_owner) — saved/, forecast/*.pdf и полки гостей saved_<агент>/ (пометка «гость»);
  гость (Telegram ID из ~/.openclaw/workspace-<агент>/AGENTS.md) — только saved_<агент>/ и forecast/guest/;
  остальные — отказ. private/ (Argus, rates.csv) не показывается никому.

Токен бота — ~/.secrets/zhdusha_bot; в страницу и ответы не попадает.
«Построить прогноз» (вкладка «Прогнозы»): ставка полувагона по факторам из формы — считает zrate.py, без нейросети;
гостю — только результат модели, без помесячных ставок рынка.
Кнопка «Поставить задачу»: если в miniapp.json задан task_cmd — команда уходит агенту сразу; иначе текст копируется,
и его вставляют в чат.
"""
import hashlib
import hmac
import json
import math
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import send as S  # тот же sendDocument, что у send.py

BASE = Path(__file__).resolve().parent
SAVED, FORECAST = BASE / "saved", BASE / "forecast"
PAGE = BASE / "miniapp" / "index.html"
CONFIG = BASE / "miniapp.json"
OC = Path.home() / ".openclaw"
MAX_UPLOAD = 20 * 1024 * 1024
SHOW = {".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".csv", ".png", ".jpg", ".jpeg", ".md"}

# Разделы = пункты меню (zmenu.py) без /start, /new; /find, /remember, /save — во вкладке «Задача».
# Ключевые слова — только для раскладки старых файлов (sort) и файлов без папки; порядок важен.
SECTIONS = [
    ("Рынок", "poluvagony", "Полувагоны", ["полуваг"]),
    ("Рынок", "krytye", "Крытые вагоны", ["крыт"]),
    ("Рынок", "zerno", "Зерновозы", ["зерновоз"]),
    ("Рынок", "fiting", "Фитинговые платформы", ["фитинг"]),
    ("Рынок", "market", "Новости рынка", ["новост", "рынок", "market"]),
    ("Рынок", "rates", "Ставки", ["ставки_аренд", "_ставки"]),
    ("Рынок", "loading", "Погрузка", ["погрузк"]),
    ("Рынок", "balance", "Баланс парка", ["баланс"]),
    ("Прогнозы", "method", "Методика и проверка модели", ["проверка_модели", "методика", "как_ждуша"]),
    ("Прогнозы", "prognoz", "Ставки до 2030", ["прогноз_ставок", "2030", "прогноз_3м"]),
    ("Прогнозы", "forecast", "Прогноз на неделю", ["прогноз"]),
    ("Прогнозы", "vagon", "Стоимость вагона", ["стоимость_вагона"]),
    ("Компании", "company", "Новости оператора", ["новости_оператор"]),
    ("Компании", "profile", "Справка по компании", ["справка", "профиль"]),
    ("Компании", "finance", "Финансы", ["финанс"]),
    ("Компании", "courts", "Суды и приставы", ["суд", "пристав"]),
    ("Компании", "assets", "Имущество и лизинг", ["имуществ", "лизинг"]),
    ("Компании", "compare", "Сравнение компаний", ["сравнен", "_vs_"]),
    ("Прогнозы", "lease", "Оперировать или сдавать", ["оперировать", "аренд"]),
    ("Прогнозы", "model", "Финмодели и стресс-тест", ["модел", "стресс"]),
    ("Прогнозы", "zavod", "Заводы и аванс", ["завод"]),
    ("Задача", "upload", "Мои загрузки", []),
    ("Задача", "other", "Разное", []),
]
KEYS = [s[1] for s in SECTIONS]


def secret(name):
    p = Path.home() / ".secrets" / name
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def guests():
    """Telegram ID → имя агента гостя: zguest.py пишет ID в первые строки AGENTS.md агента."""
    out = {}
    for ws in OC.glob("workspace-*"):
        try:
            head = (ws / "AGENTS.md").read_text(encoding="utf-8")[:600]
        except OSError:
            continue
        m = re.search(r"\*\*гостем\*\* \(Telegram ID (\d+)\)", head)
        if m:
            out[m.group(1)] = ws.name.removeprefix("workspace-")
    return out


def who(uid):
    """(роль, имя агента, папки для чтения, папка для записи) или None."""
    if uid and uid == secret("zhdusha_owner"):  # владелец видит и полки гостей (с пометкой «гость»)
        return "owner", "zhdusha", [SAVED, FORECAST] + [BASE / f"saved_{a}" for a in sorted(set(guests().values()))], SAVED
    agent = guests().get(uid)
    if agent:
        own = BASE / f"saved_{agent}"
        return "guest", agent, [own, FORECAST / "guest"], own
    import zsurvey
    if uid in zsurvey.respondents():  # респондент анкеты: видит только анкету, файлов нет
        return "respondent", None, [], None
    return None


def check_init(init_data, token):
    """Проверка подписи Telegram: core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app."""
    pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    got = pairs.pop("hash", "")
    data = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    if not got or not hmac.compare_digest(hmac.new(key, data.encode(), hashlib.sha256).hexdigest(), got):
        return None
    if time.time() - int(pairs.get("auth_date", "0")) > 86400:
        return None
    return str(json.loads(pairs.get("user", "{}")).get("id", ""))


def company_list():
    """Компании для справки в приложении: первая колонка watchlist.csv (как в файле, без синонимов)."""
    try:
        lines = (BASE / "watchlist.csv").read_text(encoding="utf-8-sig").splitlines()[1:]
    except OSError:
        return []
    return sorted({x.split(";")[0].strip() for x in lines if x.split(";")[0].strip()}, key=str.lower)


def companies():
    """Названия и синонимы из watchlist.csv (только на сервере), в нижнем регистре, пробелы → «_»."""
    try:
        lines = (BASE / "watchlist.csv").read_text(encoding="utf-8-sig").splitlines()[1:]
    except OSError:
        return []
    names = set()
    for line in lines:
        cols = line.split(";")
        for n in [cols[0]] + (cols[1].split(",") if len(cols) > 1 else []):
            n = n.strip().lower().replace(" ", "_")
            if len(n) >= 3:
                names.add(n)
    return names


def section_of(path, root):
    rel = path.relative_to(root).parts
    if len(rel) > 1 and rel[0] in KEYS:
        return rel[0]
    if root.name == "forecast" or root.parent.name == "forecast":
        return "prognoz"
    name = path.name.lower()
    if "завод" in name:
        return "zavod"
    if "стоимость" in name:  # «стоимость_инновационного_полувагона» — это /vagon, а не справка по полувагонам
        return "vagon"
    if "lease" in name or "оперировать" in name:  # «lease_крытые» — это /lease, а не справка по крытым
        return "lease"
    if "новост" in name and any(c in name for c in companies()):  # «ПГК_новости» — новости оператора
        return "company"
    for _, key, _, words in SECTIONS:
        if any(w in name for w in words):
            return key
    if any(c in name for c in companies()):  # файл назван по компании из watchlist.csv — справка по компании
        return "profile"
    return "other"


def files(roots):
    """Все показываемые файлы: .md — только если рядом нет PDF с тем же именем."""
    seen = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            rel = p.relative_to(root).parts
            if not p.is_file() or p.suffix.lower() not in SHOW or "copy" in rel[:-1] or "_tmp" in p.stem:
                continue
            if root == FORECAST and rel[0] == "guest":
                continue
            if p.suffix.lower() == ".md" and p.with_suffix(".pdf").exists():
                continue
            seen.append((root, p))
    return seen


def listing(roots):
    out = {k: [] for k in KEYS}
    for root, p in files(roots):
        st = p.stat()
        item = {"id": f"{roots.index(root)}/{p.relative_to(root).as_posix()}",
                "name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)}
        if root.name.startswith("saved_"):
            item["guest"] = root.name.removeprefix("saved_")
        if p.suffix.lower() == ".md" or p.with_suffix(".md").exists():  # есть текст — читается прямо в приложении
            item["read"] = True
        out[section_of(p, root)].append(item)
    for v in out.values():
        v.sort(key=lambda f: -f["mtime"])
    return out


def resolve(roots, fid):
    idx, _, rel = fid.partition("/")
    if not idx.isdigit() or int(idx) >= len(roots) or not rel:
        return None
    root = roots[int(idx)].resolve()
    p = (root / rel).resolve()
    if not p.is_file() or not p.is_relative_to(root) or p.suffix.lower() not in SHOW:
        return None
    return p


def read_id(uid, path):
    """id файла для кнопки «Читать в приложении» под документом в чате (send.py) — в папках этого человека; нет — None."""
    acc = who(str(uid))
    path = Path(path).resolve()
    if not acc or not (path.suffix.lower() == ".md" or path.with_suffix(".md").exists()):
        return None
    for i, root in enumerate(acc[2]):
        r = root.resolve()
        if path.is_relative_to(r):
            return f"{i}/{path.relative_to(r).as_posix()}"
    return None


def link_sig(token, uid, fid, exp):
    key = hmac.new(token.encode(), b"zapp-link", hashlib.sha256).digest()
    return hmac.new(key, f"{uid}|{fid}|{exp}".encode(), hashlib.sha256).hexdigest()


def run_task(agent, uid, text):
    cmd = config().get("task_cmd")
    if not cmd:
        return {"ok": False, "fallback": text}
    sid = f"zapp-{uid}-{time.strftime('%Y%m%d%H%M%S')}"  # {session} в task_cmd — каждая задача в новом разговоре
    args = [a.replace("{agent}", agent).replace("{to}", uid).replace("{text}", text).replace("{session}", sid)
            for a in cmd]
    # ЖДуша отвечает минутами — запускаем отдельно и не ждём; ответ придёт в чат, журнал — saved/task.log
    try:
        log = (SAVED / "task.log").open("a", encoding="utf-8")
        log.write(f"\n{time.strftime('%Y-%m-%d %H:%M')} {agent} {uid}: {text[:200]}\n")
        log.flush()
        subprocess.Popen(args, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return {"ok": False, "fallback": text, "error": str(e)[:200]}
    return {"ok": True, "fallback": None}


LIMITS = {"coal": (-20, 20), "load": (-20, 20), "stroy": (-30, 30), "buy": (0, 80), "off": (0, 80), "pace": (-5, 5)}


TLIMITS = {"stroy": (-30, 30), "mortgage": (-60, 60), "export": (-40, 40), "park": (-10, 30), "balance": (-20, 20),
           "pace": (-5, 5)}


def vagon_value(t, lvl):
    """Стоимость вагона по модели zvagon.py для ставок выбранного сценария: новый, б/у 14 лет, доход к цене."""
    try:
        import zvagon
        V = zvagon.load()
        p, _ = zvagon.price_path(V, t, {y: lvl[y] for y in range(2027, 2031)})
    except (SystemExit, KeyError):
        return None
    k = zvagon.age_factor(V, 14)
    return {"new": {str(y): round(v, 1) for y, v in p.items()}, "used": {str(y): round(v * k, 1) for y, v in p.items()},
            "cap": {str(y): round(lvl[y] * 365 / (v * 1e6) * 100, 1) for y, v in p.items()}}


import zhelp  # noqa: E402  — пояснения к факторам («Изменить допущения»)


def monthly(q4, lvl):
    """Помесячный путь ставки до декабря 2030 г.: октябрь–декабрь 2026 — прогноз модели по месяцам; дальше — плавный
    путь через среднюю за каждый год (точка в середине года), без сезонности. Для выбора «с … по …» в приложении."""
    lm = 12 - len(q4)
    pts = [(lm + 1 + i, v) for i, v in enumerate(q4)] + [((y - 2026) * 12 + 7, lvl[y]) for y in range(2027, 2031) if y in lvl]
    out = {}
    for t in range(lm + 1, 61):
        if t <= 12:
            v = q4[t - lm - 1]
        else:
            a = max((x for x in pts if x[0] <= t), key=lambda x: x[0])
            nx = [x for x in pts if x[0] > t]
            if nx:
                b = nx[0]
                v = a[1] * (b[1] / a[1]) ** ((t - a[0]) / (b[0] - a[0]))
            else:  # после середины 2030 г. — тем же темпом, что последний отрезок
                p0, p1 = pts[-2], pts[-1]
                v = p1[1] * (p1[1] / p0[1]) ** ((t - p1[0]) / (p1[0] - p0[0]))
        out[f"{2026 + (t - 1) // 12}-{(t - 1) % 12 + 1:02d}"] = round(v)
    return out


def forecast_type(w, sc, body):
    """«Построить прогноз» для крытых, зерновоза, платформ — ztypes.py (та же схема, что у полувагона)."""
    import ztypes as T
    ov = {}
    for k, v in (body.get("set") or {}).items():
        if k in TLIMITS and v not in (None, ""):
            try:
                lo, hi = TLIMITS[k]
                ov[k] = str(min(hi, max(lo, float(str(v).replace(",", ".")))))
            except ValueError:
                return {"error": "Не число в поле фактора"}
    try:
        res = {s_: T.forecast(w, s_, ov if s_ == sc else None) for s_ in T.SCN}
    except SystemExit as e:
        return {"error": str(e) or "Данных по этому типу ещё нет на сервере."}
    TY, r = T.TYPES[w], res[sc]
    fk = T.fkeys(TY)
    units = {"pace": "% в месяц"}
    factors = {k: (T.fname(TY, k), "% за год") for k in fk}
    factors["pace"] = ("Темп ставки в IV кв.", units["pace"])
    defaults = {T.SCN[s_]: {**{k: res[s_]["scen"][k][0] for k in fk}, "pace": res[s_]["pace"]} for s_ in T.SCN}
    lm = r["last_m"]
    lvl = r["months"][lm]
    price = {f"{T.fname(TY, k)} +1%": lvl * (math.exp(r["fit"]["b"][k] * T.xval(TY, k, 1) / 100) - 1) for k in fk}
    v = T.value(w, sc)
    out = {"wagon": TY["name"], "scenario": T.SCN[sc], "as_of": f"{T.MNAME[lm - 1]} 2026", "now": round(lvl),
           "q4": {T.SCN[k]: {"months": [round(x) for x in x_["q4"]],
                             "delta": [round(a - b) for a, b in zip(x_["q4"], [x_["months"][lm]] + x_["q4"][:-1])],
                             "avg": round(x_["lvl"][2026]), "pace": x_["pace"]} for k, x_ in res.items()},
           "years": {T.SCN[k]: {str(y): round(x_["lvl"][y]) for y in [2026] + T.YEARS} for k, x_ in res.items()},
           "monthly": {T.SCN[k]: monthly(list(x_["q4"]), x_["lvl"]) for k, x_ in res.items()},
           "parts": {str(y): {k: round(x) for k, x in r["parts"][y].items()} for y in T.YEARS},
           "end": {str(y): round(r["end"][y]) for y in T.YEARS}, "parts_scenario": T.SCN[sc],
           "price": {k: round(x) for k, x in price.items()}, "need": [], "factors": factors, "cap": [],
           "defaults": defaults, "pace_label": "темп", "fields": fk + ["pace"],
           "accuracy": r["fit"]["bt"] or {}, "help": zhelp.for_wagon(w, fk + ["pace"])}
    if v:
        out["value"] = {"new": {str(y): round(x, 1) for y, x in v["new"].items()},
                        "used": {str(y): round(x, 1) for y, x in v["used"].items()},
                        "cap": {str(y): round(x, 1) for y, x in v["cap"].items()}}
    elif w == "kr158":
        out["value"] = vagon_value("kr158", r["lvl"])
    return out


def forecast(body):
    """«Построить прогноз»: полувагоны — zrate.py, остальные типы — ztypes.py; факторы из формы. Без нейросети."""
    import ztypes
    if body.get("wagon") in ztypes.TYPES:
        sc = body.get("scenario") if body.get("scenario") in ztypes.SCN else "base"
        return forecast_type(body["wagon"], sc, body)
    import zrate as Z
    try:
        D = Z.load()
    except SystemExit:
        return {"error": "Модель ещё не загружена на сервер."}
    w = body.get("wagon") if body.get("wagon") in Z.WAGONS else "inno"
    sc = body.get("scenario") if body.get("scenario") in Z.SCN else "base"
    ov = {}
    for k, v in (body.get("set") or {}).items():
        if k in LIMITS and v not in (None, ""):
            try:
                lo, hi = LIMITS[k]
                ov[k] = str(min(hi, max(lo, float(str(v).replace(",", ".")))))
            except ValueError:
                return {"error": f"Не число: {Z.FACTORS[k][0]}"}
    res = {s_: Z.forecast(D, w, s_, ov if s_ == sc else {}) for s_ in Z.SCN}
    r = res[sc if sc != "pess" else "base"]
    defaults = {s_: {k: (v if k == "pace" else v[1]) for k, v in D["scenarios"][s_].items() if k in LIMITS} for s_ in Z.SCN}
    L, up = Z.unit_price(D, w)
    return {"wagon": Z.WAGONS[w], "scenario": Z.SCN[sc], "as_of": D["as_of"], "now": round(res["base"]["months"][-1]),
            "q4": {Z.SCN[k]: {"months": [round(x) for x in v["q4"]], "delta": [round(x) for x in v["q4_rub"]],
                              "avg": round(v["lvl"][2026]), "pace": v["scen"]["pace"]} for k, v in res.items()},
            "years": {Z.SCN[k]: {str(y): round(v["lvl"][y]) for y in [2026] + Z.YEARS} for k, v in res.items()},
            "monthly": {Z.SCN[k]: monthly(list(v["q4"]), v["lvl"]) for k, v in res.items()},
            "parts": {str(y): {k: round(v) for k, v in r["parts"][y].items()} for y in Z.YEARS},
            "end": {str(y): round(r["end"][y]) for y in Z.YEARS}, "parts_scenario": Z.SCN[sc if sc != "pess" else "base"],
            "price": {k: round(v) for k, v in up.items()},
            "need": [{"target": t, "pct": round(Z.need(D, w, t)[0], 1), "k": round(Z.need(D, w, t)[1], 1)} for t in D["targets"]],
            "defaults": {Z.SCN[k]: v for k, v in defaults.items()}, "factors": {k: Z.FACTORS[k] for k in LIMITS}, "cap": r["cap"],
            "pace_label": "парк", "fields": ["pace", "coal", "load", "stroy", "buy", "off"], "value": vagon_value(w, r["lvl"]),
            "help": zhelp.for_wagon(w, ["pace", "coal", "load", "stroy", "buy", "off"])}


class App(BaseHTTPRequestHandler):
    server_version = "zapp"

    def log_message(self, fmt, *args):  # без адресов и подписей в журнале
        sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M')} {self.command} {self.path.split('?')[0]}\n")

    def reply(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):  # окно закрыли раньше, чем дошёл ответ — не ошибка
            pass

    def user(self):
        token = secret("zhdusha_bot")
        uid = check_init(self.headers.get("X-Init-Data", ""), token) if token else None
        return (uid, who(uid), token) if uid else (None, None, token)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path in ("/", "/index.html"):
            return self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if url.path == "/api/list":
            uid, acc, _ = self.user()
            if not acc:
                return self.reply(403, {"error": "Нет доступа. Попроси владельца добавить тебя в ЖДушу."})
            sections = [{"group": g, "key": k, "title": t} for g, k, t, _ in SECTIONS]
            return self.reply(200, {"role": acc[0], "sections": sections, "files": listing(acc[2]), "companies": company_list(),
                                    "direct": bool(config().get("task_cmd"))})
        if url.path == "/file":  # ссылка из /api/link: открывается во внешнем браузере, живёт 10 минут
            token, uid, fid, exp = secret("zhdusha_bot"), q.get("u", ""), q.get("f", ""), q.get("e", "0")
            if not exp.isdigit() or int(exp) < time.time() or not hmac.compare_digest(
                    link_sig(token, uid, fid, exp), q.get("s", "")):
                return self.reply(403, {"error": "Ссылка устарела — открой файл из приложения ещё раз."})
            acc = who(uid)
            p = resolve(acc[2], fid) if acc else None
            if not p:
                return self.reply(404, {"error": "Файл не найден"})
            ext = p.suffix.lower()
            ctype = {".pdf": "application/pdf", ".md": "text/plain; charset=utf-8", ".csv": "text/plain; charset=utf-8",
                     ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "application/octet-stream")
            disp = "attachment" if ctype == "application/octet-stream" else "inline"
            return self.reply(200, p.read_bytes(), ctype,
                              {"Content-Disposition": f"{disp}; filename*=UTF-8''{urllib.parse.quote(p.name)}"})
        self.reply(404, {"error": "Нет такой страницы"})

    def do_POST(self):
        uid, acc, token = self.user()
        if not acc:
            return self.reply(403, {"error": "Нет доступа"})
        role, agent, roots, own = acc
        path0 = urllib.parse.urlparse(self.path).path
        if role == "respondent" and path0 != "/api/survey":
            return self.reply(403, {"error": "Вам доступна только анкета ставок"})
        size = int(self.headers.get("Content-Length", "0"))
        if size > MAX_UPLOAD:
            return self.reply(413, {"error": "Файл больше 20 МБ — пришли его боту в чат."})
        raw = self.rfile.read(size)
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/upload":
            name = Path(urllib.parse.unquote(self.headers.get("X-File-Name", ""))).name
            if not name or Path(name).suffix.lower() not in SHOW | {".html", ".htm"}:  # html — страницы закупок (zprocure)
                return self.reply(400, {"error": "Такой тип файла не принимаю: PDF, Word, Excel, картинки, CSV, HTML."})
            dest = own / "upload" / f"{time.strftime('%Y-%m-%d')}_{name}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            n = 1
            while dest.exists():
                dest, n = dest.with_name(f"{time.strftime('%Y-%m-%d')}_{n}_{name}"), n + 1
            dest.write_bytes(raw)
            if own == SAVED and dest.suffix.lower() in (".pdf", ".html", ".htm"):  # владелец: выпуски Argus и материалы — по папкам (zinbox.py)
                subprocess.Popen([sys.executable, str(BASE / "zinbox.py"), "--wait"], cwd=BASE, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return self.reply(200, {"ok": True, "name": dest.name})
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self.reply(400, {"error": "Плохой запрос"})
        if path == "/api/send":
            p = resolve(roots, body.get("id", ""))
            if not p:
                return self.reply(404, {"error": "Файл не найден"})
            try:
                ok = S.send(uid, p, token)
            except SystemExit as e:  # send.py сообщает об ошибке Telegram через sys.exit
                return self.reply(502, {"error": str(e)[:300]})
            return self.reply(200, {"ok": bool(ok)})
        if path == "/api/link":
            fid = body.get("id", "")
            if not resolve(roots, fid):
                return self.reply(404, {"error": "Файл не найден"})
            exp = str(int(time.time()) + 600)
            q = urllib.parse.urlencode({"u": uid, "f": fid, "e": exp, "s": link_sig(token, uid, fid, exp)})
            return self.reply(200, {"url": f"/file?{q}"})
        if path == "/api/forecast":
            try:
                out = forecast(body)
            except Exception as e:  # noqa: BLE001 — ошибка расчёта не должна ронять приложение
                out = {"error": f"Расчёт не удался: {type(e).__name__}"}
            return self.reply(400 if "error" in out else 200, out)
        if path == "/api/rates":  # ставки и парк по месяцам — данные партнёра, только владельцу
            if role != "owner":
                return self.reply(403, {"error": "Ставки по месяцам доступны владельцу."})
            try:
                import zrates
                return self.reply(200, zrates.table())
            except Exception as e:  # noqa: BLE001
                return self.reply(400, {"error": f"Нет базы наблюдений: {type(e).__name__}"})
        if path == "/api/retro":  # анализ ставки по месяцам — данные партнёра, только владельцу
            if role != "owner":
                return self.reply(403, {"error": "Анализ по месяцам доступен владельцу."})
            import zretro
            w = body.get("wagon") or "inno"
            if w not in zretro.RATE:
                return self.reply(400, {"error": "Нет такого типа вагона"})
            try:
                return self.reply(200, zretro.api(w))
            except Exception as e:  # noqa: BLE001
                return self.reply(400, {"error": f"Нет данных для анализа: {type(e).__name__}"})
        if path == "/api/deal":  # расчёт сделки: лизинг 20 лет, без аванса, ключевая + 3,5 п.п.
            import zdeal
            if body.get("wagon", "inno") not in zdeal.NAMES or body.get("scenario", "base") not in zdeal.SCN:
                return self.reply(400, {"error": "Нет такого типа вагона или сценария"})
            argv = ["run", "--wagon", str(body.get("wagon") or "inno"), "--scenario", str(body.get("scenario") or "base")]
            for k, lim in (("price", (0.5, 30)), ("spread", (0, 15)), ("util", (30, 100)), ("opex", (0, 60)), ("term", (3, 25))):
                v = str(body.get(k) or "").replace(",", ".").strip()
                if v:
                    try:
                        x = min(lim[1], max(lim[0], float(v)))
                        argv += [f"--{k}", str(int(x) if k == "term" else x)]
                    except ValueError:
                        return self.reply(400, {"error": f"Не число: {k}"})
            try:
                a = zdeal.args(argv)
                D, _ = zdeal.report(a)
                return self.reply(200, zdeal.as_json(D, a))
            except SystemExit as e:
                return self.reply(400, {"error": str(e) or "Нет данных модели"})
            except Exception as e:  # noqa: BLE001
                return self.reply(400, {"error": f"Расчёт не удался: {type(e).__name__}"})
        if path == "/api/second":  # второе мнение GPT по прогнозам — только владельцу
            if role != "owner":
                return self.reply(403, {"error": "Второе мнение доступно владельцу."})
            subprocess.Popen([sys.executable, str(BASE / "zsecond.py"), "run"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return self.reply(200, {"msg": "Задача ушла ЖДуше (GPT) — PDF придёт в чат через 5–15 минут"})
        if path == "/api/read":  # отчёт текстом — читать прямо в приложении (PDF на компьютере Telegram не показывает)
            p = resolve(roots, body.get("id", ""))
            md = p if p and p.suffix.lower() == ".md" else p.with_suffix(".md") if p else None
            if not md or not md.exists():
                return self.reply(404, {"error": "У этого файла нет текстовой версии — нажмите «Открыть»."})
            return self.reply(200, {"name": p.name, "md": md.read_text(encoding="utf-8")[:400000]})
        if path == "/api/pdf":  # расчёт из приложения → PDF в чат (zpdf.py), без нейросети
            if body.get("kind") in ("rates", "retro") and role != "owner":
                return self.reply(403, {"error": "Этот расчёт доступен владельцу."})
            log = (SAVED / "task.log").open("a", encoding="utf-8")
            subprocess.Popen([sys.executable, str(BASE / "zpdf.py"), uid, json.dumps(body, ensure_ascii=False)], cwd=BASE,
                             stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
            return self.reply(200, {"ok": True, "msg": "PDF придёт в чат через 10–30 секунд"})
        if path == "/api/survey":  # анкета ставок: ответ → forecast/survey.csv (zsurvey.py)
            import zsurvey
            try:
                return self.reply(200, zsurvey.save(uid, role, body))
            except ValueError as e:
                return self.reply(400, {"error": str(e)})
        if path == "/api/task":
            text = " ".join(str(body.get("text", "")).split())[:1500]
            if not text:
                return self.reply(400, {"error": "Пустая задача"})
            return self.reply(200, run_task(agent, uid, text))
        self.reply(404, {"error": "Нет такой команды"})


def cmd_sort(apply):
    moves = []
    for p in sorted(SAVED.glob("*")) if SAVED.is_dir() else []:
        if p.is_file() and p.suffix.lower() in SHOW | {".html"}:
            moves.append((p, SAVED / section_of(p, SAVED) / p.name))
    if not moves:
        return print("В saved/ нет файлов без раздела — раскладывать нечего.")
    by = {}
    for src, dst in moves:
        by.setdefault(dst.parent.name, []).append(src.name)
    titles = {k: t for _, k, t, _ in SECTIONS}
    for key, names in by.items():
        print(f"\n{titles[key]} → saved/{key}/ ({len(names)})")
        for n in names:
            print("   ", n)
    if not apply:
        return print(f"\nВсего {len(moves)}. Ничего не перенесено. Разложить: python3 zapp.py sort --apply")
    for src, dst in moves:
        if dst.exists():
            print(f"Пропуск: {dst} уже есть")
            continue
        dst.parent.mkdir(exist_ok=True)
        shutil.move(src, dst)
    print(f"\nПеренесено: {len(moves)}. Журнал отправок saved/sent.log остаётся на месте.")


KEEP = {"Модель_ставки_полувагона_2030.pdf", "Модель_ставки_полувагона_2030.xlsx"}  # рабочая модель, не запросы


def cmd_hide(key, day, apply, keep=(), only=()):
    """Убрать из раздела приложения файлы, сохранённые за день: перенос в archive/<дата>/, без удаления."""
    roots = [SAVED, FORECAST, FORECAST / "guest"] + sorted(BASE.glob("saved_*"))
    found = []
    for root, p in files(roots):
        if root == FORECAST and p.relative_to(root).parts[0] == "guest":
            continue
        dated = re.match(r"\d{4}-\d{2}-\d{2}", p.name)  # дата в имени важнее даты файла (файлы могли переложить)
        when = dated.group() if dated else time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
        if (section_of(p, root) == key and p.name not in KEEP and not p.name.startswith("сводка_") and when == day
                and not any(k in p.name for k in keep) and (not only or any(o in p.name for o in only))):
            for x in (p, p.with_suffix(".md")):
                if x.is_file() and (root, x) not in found:
                    found.append((root, x))
    if not found:
        return print(f"В разделе «{key}» нет файлов за {day} — убирать нечего.")
    for root, p in found:
        print(f"   {root.name}/{p.relative_to(root).as_posix()}")
    if not apply:
        return print(f"\nВсего {len(found)}. Ничего не перенесено. Убрать: python3 zapp.py hide {key} --date {day}"
                     + "".join(f" --keep {k}" for k in keep) + "".join(f" --only {o}" for o in only) + " --apply")
    arch = BASE / "archive" / day
    for root, p in found:
        dst = arch / root.relative_to(BASE) / p.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(p, dst)
    print(f"\nПеренесено: {len(found)} → {arch} (из приложения убраны, не удалены).")


def cmd_check():
    r = subprocess.run(["openclaw", "agent", "--help"], capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    flags = [f for f in ("--agent", "--message", "--deliver", "--reply-channel", "--reply-account", "--reply-to")
             if f in out]
    print(out[-2500:])
    print("Есть флаги:", ", ".join(flags) or "нет")
    print("Подходит для прямой отправки задач." if len(flags) == 6 else
          "Прямой отправки нет — кнопка «Поставить задачу» будет копировать текст для вставки в чат.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["serve"]:
        port = int(a[a.index("--port") + 1]) if "--port" in a else 8787
        if not secret("zhdusha_bot") or not secret("zhdusha_owner"):
            sys.exit("Нет ~/.secrets/zhdusha_bot или ~/.secrets/zhdusha_owner — см. SETUP.md, шаг 2.")
        print(f"Мини-приложение ЖДуши: http://127.0.0.1:{port} (снаружи — через Caddy)")
        ThreadingHTTPServer(("127.0.0.1", port), App).serve_forever()
    elif a[:1] == ["sort"]:
        cmd_sort("--apply" in a)
    elif a[:1] == ["hide"] and len(a) > 1 and a[1] in KEYS:
        cmd_hide(a[1], a[a.index("--date") + 1] if "--date" in a else time.strftime("%Y-%m-%d"), "--apply" in a,
                 [a[i + 1] for i, x in enumerate(a[:-1]) if x == "--keep"],
                 [a[i + 1] for i, x in enumerate(a[:-1]) if x == "--only"])
    elif a[:1] == ["check"]:
        cmd_check()
    else:
        sys.exit(__doc__)
