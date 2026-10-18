#!/usr/bin/env python3
"""Старая переписка с ЖДушей → полки мини-приложения: каждая пара «вопрос — ответ» отдельным файлом в разделе меню.
Без нейросети (0 токенов). История OpenClaw только читается.

  python3 zhistory.py                     показать, что куда ляжет (ничего не пишет)
  python3 zhistory.py --show 5            то же + 5 примеров (проверить, что вопрос и ответ найдены верно)
  python3 zhistory.py --apply             разложить: saved/<раздел>/ГГГГ-ММ-ДД_ЧЧММ_<вопрос>.md (уже разложенное — пропуск)
  python3 zhistory.py --agent zguest      то же для гостя → saved_zguest/<раздел>/
  python3 zhistory.py --probe             устройство записей журнала (поля, роли, по 50 знаков текста) — для настройки

Раздел — по команде в вопросе (/vagon → «Стоимость вагона»), иначе по словам в вопросе, потом в ответе; не понятно — «Разное».
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import zapp

MSK = timezone(timedelta(hours=3))
# Слова для текста переписки (порядок важен: более узкие темы раньше)
TOPICS = [
    ("zavod", r"завод|аванс"), ("vagon", r"стоимость ваг|цен[аы] ваг|покупать или продавать|/vagon"),
    ("prognoz", r"2030|прогноз ставок"), ("forecast", r"прогноз на неделю|недельн\w* прогноз"),
    ("lease", r"оперировать|сдавать в аренду"), ("model", r"финмодел|финансов\w* модел|стресс-тест|excel"),
    ("compare", r"сравни|сравнен"), ("courts", r"суд|пристав|налогов\w* (долг|задолж)"),
    ("assets", r"имуществ|лизинг"), ("finance", r"финанс|выручк|прибыл|отчётност|рсбу"),
    ("company", r"новост\w* (по )?оператор"), ("profile", r"справк\w* по компани|инн|огрн|компани"),
    ("rates", r"ставк"), ("loading", r"погрузк"), ("balance", r"баланс парк|профицит|дефицит"),
    ("krytye", r"крыт"), ("poluvagony", r"полуваг"), ("market", r"новост|рынок|рынк"),
]
SKIP = re.compile(r"^\s*/(start|new)\b|^\s*$")


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(text_of(c) for c in content)
    if isinstance(content, dict):
        if content.get("type") in ("input_text", "output_text", "text"):
            return content.get("text", "")
        return text_of(content.get("content") or content.get("text") or "")
    return ""


def messages(path):
    """(время, роль, текст) из одного .jsonl. Внутренний журнал движка пишет ход дважды: событиями
    user_message/agent_message и записями response_item — берём события, а если их нет — response_item."""
    ev, ri = [], []
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        ts = o.get("timestamp") or o.get("ts") or ""
        p = o.get("payload") if isinstance(o.get("payload"), dict) else o
        if o.get("type") == "event_msg" and p.get("type") in ("user_message", "agent_message"):
            ev.append((ts, "user" if p["type"] == "user_message" else "assistant", p.get("message", "")))
            continue
        m = p.get("message") if isinstance(p.get("message"), dict) else p
        if m.get("role") in ("user", "assistant"):
            ri.append((ts, m["role"], text_of(m.get("content"))))
    out = []
    for ts, role, text in ev or ri:
        text = re.sub(r"^(\s*<([\w-]{1,40})[^>]{0,200}>.*?</\2>)+", "", text or "", flags=re.S).strip()
        if not text or (role == "user" and ("AGENTS.md instructions" in text[:300] or text.startswith("<"))):
            continue  # служебные вставки OpenClaw/движка: окружение, правила
        out.append((ts, role, text))
    return out


def pairs(files):
    """Вопрос + последний ответ ЖДуши до следующего вопроса; дубли (один ход в двух журналах) — один раз."""
    seen, res = set(), []
    for f in files:
        q = None
        for ts, role, text in messages(f) + [("", "user", "")]:
            if role == "user":
                if q and q[2] and not SKIP.match(q[1]) and len(q[2]) >= 40:
                    key = (q[1][:200], q[2][:200])
                    if key not in seen:
                        seen.add(key)
                        res.append(q)
                q = [ts, text, ""]
            elif q:
                q[2] = text  # последний ответ хода — итоговый
    return res


def question(text):
    """Из сообщения Telegram убрать служебную обёртку OpenClaw, оставить сам вопрос."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not re.match(r"^\s*[\[{(].*[\]})]\s*$", ln)]
    return "\n".join(lines).strip() or text.strip()


def topic(q, a):
    m = re.search(r"/([a-z]+)", q)
    if m and m.group(1) in zapp.KEYS:
        return m.group(1)
    for src in (q.lower(), a.lower()[:1500]):
        for key, rx in TOPICS:
            if re.search(rx, src):
                return key
    return "other"


def stamp(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(MSK)
    except (ValueError, AttributeError):
        return None


def probe(files):
    """Показать устройство записей: какие поля, где роль и текст. Текст — не больше 50 знаков."""
    def shape(v, depth=0):
        if isinstance(v, dict):
            return "{" + ", ".join(f"{k}: {shape(x, depth + 1)}" for k, x in list(v.items())[:12]) + "}" if depth < 4 else "{…}"
        if isinstance(v, list):
            return f"[{len(v)}× {shape(v[0], depth + 1)}]" if v else "[]"
        if isinstance(v, str):
            return repr(v[:50]) if len(v) < 40 or depth > 1 else f"str({len(v)})"
        return type(v).__name__
    f = max(files, key=lambda x: x.stat().st_mtime)
    print(f"Файл: {f}")
    kinds = {}
    for line in f.open(encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        k = str(o.get("type")) + "/" + str((o.get("payload") or {}).get("type") if isinstance(o.get("payload"), dict)
                                           else (o.get("message") or {}).get("role") if isinstance(o.get("message"), dict) else "")
        if kinds.get(k, 0) < 2:
            print(f"\n[{k}] {shape(o)}")
        kinds[k] = kinds.get(k, 0) + 1
    print("\nВиды записей:", kinds)


def main():
    a = sys.argv[1:]
    agent = a[a.index("--agent") + 1] if "--agent" in a else "zhdusha"
    show = int(a[a.index("--show") + 1]) if "--show" in a else 0
    root = zapp.SAVED if agent == "zhdusha" else zapp.BASE / f"saved_{agent}"
    base = zapp.OC / "agents" / agent
    sources = [sorted(base.glob("sessions/*.jsonl")), sorted(base.glob("agent/codex-home/sessions/**/*.jsonl"))]
    if not any(sources):
        sys.exit(f"Не нашёл историю агента {agent} в {base}")
    if "--probe" in a:
        for files in sources:
            if files:
                probe(files)
                print("=" * 60)
        return
    files, found = [], []
    for src in sources:  # сначала журнал OpenClaw, если в нём пар нет — журнал движка
        files, found = src, pairs(src) if src else []
        if found:
            break
    titles = {k: t for _, k, t, _ in zapp.SECTIONS}
    plan = []
    for ts, q, ans in found:
        q = question(q)
        when = stamp(ts) or datetime.now(MSK)
        sec = topic(q, ans)
        slug = re.sub(r"[^\w-]+", "_", q.lower())[:40].strip("_") or "вопрос"
        dest = root / sec / f"{when:%Y-%m-%d_%H%M}_{slug}.md"
        plan.append((dest, when, sec, q, ans))
    count = {}
    for d, *_ in plan:
        count[d.parent.name] = count.get(d.parent.name, 0) + 1
    print(f"История: {len(files)} файлов, пар «вопрос — ответ»: {len(plan)}")
    for k, n in sorted(count.items(), key=lambda x: -x[1]):
        print(f"  {titles.get(k, k)} → {root.name}/{k}/: {n}")
    for d, when, sec, q, ans in plan[:show]:
        print(f"\n--- {when:%d.%m %H:%M} · {titles.get(sec, sec)}\n  В: {q[:160]!r}\n  О: {ans[:160]!r}")
    if "--apply" not in a:
        return print("\nНичего не записано. Разложить: python3 zhistory.py --apply" + (f" --agent {agent}" if agent != "zhdusha" else ""))
    new = 0
    for d, when, sec, q, ans in plan:
        if d.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text(f"{when:%d.%m.%Y %H:%M} · {titles.get(sec, sec)}\n\n**Вопрос:** {q}\n\n**Ответ:**\n\n{ans}\n",
                     encoding="utf-8")
        new += 1
    print(f"\nЗаписано новых: {new}, уже были: {len(plan) - new}. Видно в приложении в своих разделах.")


if __name__ == "__main__":
    main()
