#!/usr/bin/env python3
"""На что уходят токены ботов: расход по агентам и командам из журналов OpenClaw. Только читает, ничего не меняет.
Без нейросети (0 токенов).

  python3 tokens.py                 последние 28 дней, все агенты (Ави — main/tester, ЖДуша — zhdusha/zguest)
  python3 tokens.py --days 7        за 7 дней
  python3 tokens.py --agent zhdusha один агент
  python3 tokens.py --probe         где в журнале записан расход (поля, без текста переписки) — для настройки

Вызов модели = один запрос к нейросети; на один вопрос их бывает несколько (поиск, программа, ответ).
«Вход» — всё, что отправлено модели: правила, история разговора, результаты программ; «из кэша» — часть входа,
которую сервис нейросети взял из кэша (обычно дешевле). «Минимальный вход» — самый маленький запрос за период:
примерно столько стоит каждое сообщение ещё до вопроса (правила + служебное).
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zhistory  # noqa: E402  — разбор текста и раздел по вопросу (общий с мини-приложением)

OC = Path.home() / ".openclaw"
IN = ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens", "input")
OUT = ("output_tokens", "outputTokens", "completion_tokens", "completionTokens", "output")
CACHE = ("cached_input_tokens", "cachedInputTokens", "cache_read_input_tokens", "cacheRead", "cache_read")
CACHE_W = ("cache_creation_input_tokens", "cacheWrite", "cache_write")


def num(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return int(v)
    return None


def usages(o, path=""):
    """Все записи расхода в объекте журнала: (путь, вход, из кэша, выход). Накопительные итоги
    (total_token_usage) пропускаются — берём расход одного вызова, чтобы не считать дважды."""
    found = []
    if isinstance(o, dict):
        i, out = num(o, IN), num(o, OUT)
        if i is not None and out is not None:
            c = num(o, CACHE) or 0
            # у Anthropic «вход» не включает кэш — приводим к общему виду «вход вместе с кэшем»
            if "cache_read_input_tokens" in o or "cacheRead" in o:
                i += c + (num(o, CACHE_W) or 0)
            return [(path, i, c, out)]
        for k, v in o.items():
            if k in ("total_token_usage", "totalTokenUsage", "cumulative"):
                continue
            found += usages(v, f"{path}.{k}")
    elif isinstance(o, list):
        for v in o:
            found += usages(v, path + "[]")
    return found


def user_text(o):
    """Текст вопроса, если строка журнала — сообщение пользователя (те же правила, что в zhistory)."""
    p = o.get("payload") if isinstance(o.get("payload"), dict) else o
    if o.get("type") == "event_msg" and p.get("type") == "user_message":
        t = p.get("message", "")
    else:
        m = p.get("message") if isinstance(p.get("message"), dict) else p
        if m.get("role") != "user":
            return None
        t = zhistory.text_of(m.get("content"))
    t = re.sub(r"^(\s*<([\w-]{1,40})[^>]{0,200}>.*?</\2>)+", "", t or "", flags=re.S).strip()
    if not t or "AGENTS.md instructions" in t[:300] or t.startswith("<"):
        return None
    return zhistory.question(t)


def when(o):
    ts = o.get("timestamp") or o.get("ts") or ""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, timezone.utc)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def section(q):
    m = re.match(r"\s*/([a-z_]+)", q)
    if m:
        return "/" + m.group(1)
    key = zhistory.topic(q, "")
    return {kk: t for _, kk, t, _ in zhistory.zapp.SECTIONS}.get(key, "Разное" if key == "other" else key) + " (текстом)"


def scan(files, since):
    """Расход по вопросам: {вопрос-ключ: [раздел, дата, вызовов, вход, кэш, выход]} + вызовы без вопроса."""
    rows, calls = [], []
    for f in files:
        cur = None
        if f.stat().st_mtime < since.timestamp():
            continue
        for line in f.open(encoding="utf-8", errors="replace"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            t = when(o)
            q = user_text(o)
            if q is not None:
                cur = [section(q), t, 0, 0, 0, 0]
                rows.append(cur)
                continue
            for _, i, c, out in usages(o):
                if t and t < since:
                    continue
                calls.append(i)
                if cur is None:
                    cur = ["(без вопроса: запуск, расписание)", t, 0, 0, 0, 0]
                    rows.append(cur)
                cur[2] += 1
                cur[3] += i
                cur[4] += c
                cur[5] += out
    return [r for r in rows if r[2]], calls


def k(v):
    return f"{v / 1000:,.0f}".replace(",", " ") + " тыс."


def report(agent, src, rows, calls):
    tot = [sum(r[i] for r in rows) for i in (2, 3, 4, 5)]
    print(f"\n== {agent} ({src}): вопросов {len(rows)}, вызовов модели {tot[0]}, "
          f"вход {k(tot[1])} (из кэша {k(tot[2])}), выход {k(tot[3])}")
    if calls:
        s = sorted(calls)
        print(f"   вход на один вызов: минимальный {k(s[0])}, средний {k(sum(s) / len(s))}, "
              f"максимальный {k(s[-1])}")
    by = {}
    for r in rows:
        a = by.setdefault(r[0], [0, 0, 0, 0, 0])
        a[0] += 1
        for j in range(4):
            a[j + 1] += r[j + 2]
    full = tot[1] + tot[3] or 1
    print(f"   {'раздел / команда':34s} {'вопр.':>5s} {'выз.':>5s} {'вход':>12s} {'выход':>11s} {'доля':>5s} "
          f"{'на вопрос':>12s}")
    for name, a in sorted(by.items(), key=lambda x: -(x[1][2] + x[1][4])):
        share = (a[2] + a[4]) / full * 100
        print(f"   {name[:34]:34s} {a[0]:5d} {a[1]:5d} {k(a[2]):>12s} {k(a[4]):>11s} {share:4.0f}% "
              f"{k((a[2] + a[4]) / a[0]):>12s}")
    top = sorted(rows, key=lambda r: -(r[3] + r[5]))[:5]
    print("   Самые дорогие вопросы: " + "; ".join(
        f"{r[1].astimezone(zhistory.MSK):%d.%m %H:%M} {r[0]} — {k(r[3] + r[5])}, {r[2]} выз." if r[1] else
        f"{r[0]} — {k(r[3] + r[5])}" for r in top))


def probe(files):
    """Где лежит расход: пути полей и числа, без текста."""
    seen = {}
    for f in sorted(files, key=lambda x: -x.stat().st_mtime)[:3]:
        for line in f.open(encoding="utf-8", errors="replace"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            for p, i, c, out in usages(o):
                key = str(o.get("type")) + p
                if seen.get(key, 0) < 2:
                    print(f"  {f.name[:30]} {key}: вход {i}, кэш {c}, выход {out}")
                seen[key] = seen.get(key, 0) + 1
    print("  Записей расхода по видам:", seen or "нет — журнал расход не пишет")


def rules_size(agent):
    ws = {"main": "workspace", "tester": "workspace-tester"}.get(agent, f"workspace-{agent}")
    d = OC / ws
    sz = {p.name: len(p.read_text(encoding="utf-8", errors="replace")) for p in d.glob("*.md")} if d.exists() else {}
    return sum(sz.values()), sz


def main():
    a = sys.argv[1:]
    days = int(a[a.index("--days") + 1]) if "--days" in a else 28
    since = datetime.now(timezone.utc) - timedelta(days=days)
    agents = [a[a.index("--agent") + 1]] if "--agent" in a else sorted(p.name for p in (OC / "agents").iterdir()
                                                                      if p.is_dir())
    print(f"Расход токенов за {days} дн. (с {since.astimezone(zhistory.MSK):%d.%m.%Y}). Тысячи токенов.")
    for ag in agents:
        base = OC / "agents" / ag
        srcs = {"журнал OpenClaw": sorted(base.glob("sessions/*.jsonl")),
                "журнал движка": sorted(base.glob("agent/codex-home/sessions/**/*.jsonl"))}
        total, files = rules_size(ag)
        if total:
            print(f"\n## {ag}: файлы правил в папке агента — {total} знаков "
                  f"({', '.join(f'{n} {v}' for n, v in sorted(files.items(), key=lambda x: -x[1])[:5])})")
        for src, fl in srcs.items():
            if not fl:
                continue
            if "--probe" in a:
                print(f"\n## {ag} ({src}), {len(fl)} файлов")
                probe(fl)
                continue
            rows, calls = scan(fl, since)
            if rows:
                report(ag, src, rows, calls)
            else:
                print(f"\n== {ag} ({src}): {len(fl)} файлов, записей расхода за период нет")
    print("\nОба журнала могут описывать одни и те же вызовы — складывать их нельзя, смотреть по одному.")


if __name__ == "__main__":
    main()
