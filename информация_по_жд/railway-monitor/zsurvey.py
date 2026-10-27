#!/usr/bin/env python3
"""Анкета ставок рынка: свой ряд ставок от участников рынка (клиенты, партнёры — с их согласия). Без нейросети.

  python3 zsurvey.py add <TELEGRAM_ID> [имя]   добавить респондента (видит в приложении только анкету)
  python3 zsurvey.py remove <TELEGRAM_ID>       убрать респондента
  python3 zsurvey.py list                       респонденты и сколько ответов от каждого
  python3 zsurvey.py invite <TELEGRAM_ID>       отправить кнопку анкеты (человек должен один раз нажать Start у @zhdusha_bot)
  python3 zsurvey.py show [ГГГГ-ММ]             ответы за месяц — сводно, без имён
  python3 zsurvey.py build                      ставки, по которым ≥ 3 ответов → база наблюдений (источник survey)

Ответы — forecast/survey.csv (только на сервере). Ставка месяца по типу = медиана нижних и верхних границ ответов;
при 5 и более ответах крайние (самый низкий и самый высокий) отбрасываются. Меньше 3 ответов — в базу не идёт.
"""
import csv
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
FILE = BASE / "forecast" / "survey.csv"
RESP = Path.home() / ".secrets" / "zhdusha_respondents"
URL = "https://zhdusha.duckdns.org"
MIN_ANSWERS = 3
COLS = ["ts", "month", "uid", "role", "wagon", "low", "high", "contract", "term", "age", "repair", "outlook",
        "outlook_pct", "surplus", "reason"]
# тип вагона в анкете → показатель базы наблюдений (zobs.ITEMS); долгосрочные договоры — свой показатель у полувагонов
WAGONS = {"gon69": ("Полувагон типовой", "gon69_spot", "gon69_long"),
          "gon75": ("Полувагон инновационный", "gon75_spot", "gon75_long"),
          "kr158": ("Крытый 158 м³", "kr158", None), "kr138": ("Крытый 138 м³", "kr138", None),
          "hop_grain": ("Хоппер-зерновоз", "hop_grain", None),
          "fit80": ("Фитинговая платформа 80'", "fit80", None), "fit40": ("Фитинговая платформа 40'", "fit40", None),
          "fit60": ("Фитинговая платформа 60'", "fit60", None)}
CHOICE = {"contract": {"spot", "long"}, "age": {"0-5", "5-15", "15+"}, "repair": {"owner", "lessee"},
          "outlook": {"up", "flat", "down"}}


def respondents():
    """{Telegram ID: имя}."""
    if not RESP.exists():
        return {}
    out = {}
    for line in RESP.read_text(encoding="utf-8").splitlines():
        p = line.strip().split(maxsplit=1)
        if p and p[0].isdigit():
            out[p[0]] = p[1] if len(p) > 1 else ""
    return out


def prev_month():
    t = time.localtime()
    y, m = (t.tm_year, t.tm_mon - 1) if t.tm_mon > 1 else (t.tm_year - 1, 12)
    return f"{y}-{m:02d}"


def num(v):
    try:
        x = float(str(v).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None
    return x if x >= 0 else None


def read():
    if not FILE.exists():
        return []
    with FILE.open(encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def save(uid, role, body):
    """Ответ из мини-приложения → проверка → forecast/survey.csv. Один ответ на человека, тип и месяц (повтор заменяет)."""
    w = str(body.get("wagon", ""))
    if w not in WAGONS:
        raise ValueError("Выберите тип вагона")
    lo, hi = num(body.get("low")), num(body.get("high") or body.get("low"))
    if not lo or not hi or not 100 <= lo <= hi <= 20000:
        raise ValueError("Ставка — числа от 100 до 20 000 ₽/сут, «от» не больше «до»")
    row = {"ts": time.strftime("%Y-%m-%d %H:%M"), "month": prev_month(), "uid": uid, "role": role, "wagon": w,
           "low": round(lo), "high": round(hi)}
    for k, ok in CHOICE.items():
        v = str(body.get(k, ""))
        row[k] = v if v in ok else ""
    t = num(body.get("term"))
    row["term"] = round(t) if t and row["contract"] == "long" else ""
    p = num(str(body.get("outlook_pct", "")).lstrip("+-−"))
    row["outlook_pct"] = round(p, 1) if p is not None and row["outlook"] in ("up", "down") else ""
    for k in ("surplus", "reason"):
        row[k] = " ".join(str(body.get(k, "")).split())[:300].replace(";", ",")
    rows = [r for r in read() if not (r["uid"] == uid and r["wagon"] == w and r["month"] == row["month"])] + [row]
    FILE.parent.mkdir(parents=True, exist_ok=True)
    with FILE.open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, COLS, delimiter=";")
        wr.writeheader()
        wr.writerows(rows)
    n = sum(1 for r in rows if r["month"] == row["month"] and r["wagon"] == w)
    return {"ok": True, "month": row["month"], "n": n,
            "msg": f"Спасибо! Ставка за {row['month']} записана. Ответов по этому типу за месяц: {n}."}


def summary(month=None):
    """{(месяц, показатель): [(low, high), …]} — ответы, сгруппированные для базы наблюдений."""
    out = {}
    for r in read():
        if month and r["month"] != month:
            continue
        nm, spot, long_ = WAGONS[r["wagon"]]
        item = long_ if r["contract"] == "long" and long_ else spot
        out.setdefault((r["month"], item), []).append((float(r["low"]), float(r["high"])))
    return out


def rate(ans):
    """Медиана нижних и верхних границ; при 5+ ответах — без самого низкого и самого высокого."""
    a = sorted(ans, key=lambda x: (x[0] + x[1]) / 2)
    if len(a) >= 5:
        a = a[1:-1]
    return statistics.median(x[0] for x in a), statistics.median(x[1] for x in a)


def cmd_build():
    import zobs
    new, skip = [], []
    for (m, item), ans in sorted(summary().items()):
        if len(ans) < MIN_ANSWERS:
            skip.append(f"{m} {zobs.ITEMS[item][1]}: {len(ans)} отв.")
            continue
        lo, hi = rate(ans)
        new.append((m, item, round(lo), round(hi), "survey", f"анкета: {len(ans)} ответов, медиана"))
    if new:
        added, total = zobs.merge(new)
        print(f"В базу наблюдений записано ставок из анкеты: {len(new)} (источник survey); всего в базе {total}")
    else:
        print("Ставок с 3 и более ответами пока нет — в базу ничего не записано.")
    if skip:
        print("Мало ответов (нужно ≥ 3): " + "; ".join(skip))


def cmd_show(month):
    month = month or prev_month()
    s = summary(month)
    if not s:
        return print(f"Ответов за {month} нет.")
    import zobs
    print(f"Анкета за {month}:")
    for (m, item), ans in sorted(s.items()):
        lo, hi = rate(ans)
        print(f"  {zobs.ITEMS[item][1]:50s} ответов {len(ans)}  ставка {round(lo)}–{round(hi)} ₽/сут"
              + ("" if len(ans) >= MIN_ANSWERS else "  (мало — в базу не идёт)"))


def write_resp(d):
    RESP.parent.mkdir(parents=True, exist_ok=True)
    RESP.write_text("".join(f"{k} {v}".strip() + "\n" for k, v in d.items()), encoding="utf-8")
    RESP.chmod(0o600)


def cmd_invite(uid):
    token = (Path.home() / ".secrets" / "zhdusha_bot").read_text(encoding="utf-8").strip()
    kb = json.dumps({"inline_keyboard": [[{"text": "📝 Анкета ставок (5 минут)", "web_app": {"url": URL + "?go=survey"}}]]},
                    ensure_ascii=False)
    text = ("Здравствуйте! Раз в месяц собираем обезличенную оценку ставок аренды вагонов от участников рынка. "
            "8 вопросов, около 5 минут. Ответы используются только в сводной оценке "
            "рынка, без названия компании. Взамен — сводный обзор ставок и прогноз по вашему типу вагона.")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=urllib.parse.urlencode({"chat_id": uid, "text": text, "reply_markup": kb}).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ok = json.loads(r.read().decode()).get("ok")
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Telegram не принял ({e}). Попросите человека открыть @zhdusha_bot и нажать Start, затем повторите.")
    mb = json.dumps({"type": "web_app", "text": "Анкета", "web_app": {"url": URL + "?go=survey"}}, ensure_ascii=False)
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/setChatMenuButton",  # кнопка у поля ввода
                                 data=urllib.parse.urlencode({"chat_id": uid, "menu_button": mb}).encode())
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:  # noqa: BLE001 — не критично: кнопка анкеты уже в сообщении
        pass
    print("Кнопка анкеты отправлена." if ok else "Telegram не принял сообщение.")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else ""
    if cmd == "add" and len(a) >= 2 and a[1].isdigit():
        d = respondents()
        d[a[1]] = " ".join(a[2:])
        write_resp(d)
        print(f"Респондент {a[1]} добавлен. Дальше: python3 zsurvey.py invite {a[1]}")
    elif cmd == "remove" and len(a) >= 2:
        d = respondents()
        d.pop(a[1], None)
        write_resp(d)
        print(f"Респондент {a[1]} убран.")
    elif cmd == "list":
        cnt = {}
        for r in read():
            cnt[r["uid"]] = cnt.get(r["uid"], 0) + 1
        for k, v in respondents().items():
            print(f"{k} {v or ''} — ответов {cnt.get(k, 0)}")
    elif cmd == "invite" and len(a) >= 2:
        cmd_invite(a[1])
    elif cmd == "show":
        cmd_show(a[1] if len(a) > 1 else None)
    elif cmd == "build":
        cmd_build()
    else:
        sys.exit(__doc__)
