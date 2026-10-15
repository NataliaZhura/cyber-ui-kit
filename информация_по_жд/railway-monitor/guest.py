#!/usr/bin/env python3
"""Ещё один тестовый пользователь «Ави» — так же, как первый (агент tester), но со своим агентом и своими папками.

  python3 guest.py plan  <TELEGRAM_ID> [имя_агента]    показать, что будет сделано (ничего не меняет)
  python3 guest.py apply <TELEGRAM_ID> [имя_агента]    копия настроек → папка агента → агент → маршрут → доступ
  python3 guest.py jobs                                расписания первого тестировщика (чтобы решить, какие повторить)
  python3 guest.py off   <TELEGRAM_ID> [имя_агента]    отключить: убрать маршрут и доступ (папки остаются)

Имя агента по умолчанию — tester2. Что получает пользователь (как первый тестировщик):
  - правила tester/HEADER.md «Ави»: ограничения, копии всех сообщений владельцу, журнал запросов, отзыв;
  - свои папки: ~/.openclaw/workspace-<агент> (правила, навыки, память), ~/aviation-monitor/saved_<агент>,
    ~/aviation-monitor/excel_<агент> — справки и файлы разных тестировщиков не смешиваются;
  - запрет служебных инструментов — тот же список, что у агента tester;
  - доступ только к @marketMi_bot («Ави»); к @zhdusha_bot доступа нет (у неё свой список разрешённых).
Файлы «Ави» и его агента tester не меняются.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()
AM = HOME / "aviation-monitor"
OC_DIR = HOME / ".openclaw"
DENY_DEFAULT = ["gateway", "cron", "nodes", "sessions_send", "sessions_spawn", "sessions_list", "sessions_history", "canvas"]


def oc(*args, check=True):
    r = subprocess.run(["openclaw", *args], capture_output=True, text=True, timeout=300)
    if check and r.returncode != 0:
        sys.exit(f"openclaw {' '.join(args)} → ошибка:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r.stdout


def get(path):
    out = oc("config", "get", path, check=False)
    if "unset" in out or "Unknown config path" in out:
        return None
    starts = [i for i in (out.find("{"), out.find("["), out.find('"')) if i >= 0]
    if not starts:
        return None
    i = min(starts)
    return json.loads(out[i:max(out.rfind("}"), out.rfind("]"), out.rfind('"')) + 1])


def put(path, value):
    oc("config", "set", path, json.dumps(value, ensure_ascii=False))


def entry_path(entries, name):
    if isinstance(entries, dict) and name in entries:
        return f"agents.entries.{name}"
    if isinstance(entries, list):
        for i, e in enumerate(entries):
            if name in (e.get("name"), e.get("id")):
                return f"agents.entries.{i}"
    return None


def entry(entries, name):
    p = entry_path(entries, name)
    if not p:
        return {}
    return entries[name] if isinstance(entries, dict) else entries[int(p.rsplit(".", 1)[1])]


def header(tid, agent):
    h = (AM / "tester" / "HEADER.md").read_text(encoding="utf-8")
    return (h.replace("TESTER_ID", tid).replace("saved_tester", f"saved_{agent}")
             .replace("excel_tester", f"excel_{agent}"))


def check_args():
    if len(sys.argv) < 3 or not sys.argv[2].isdigit():
        sys.exit(__doc__)
    tid, agent = sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "tester2")
    if agent in ("main", "tester", "zhdusha"):
        sys.exit(f"Имя «{agent}» уже занято — выбери другое, например tester2.")
    return tid, agent


def cmd_plan(tid, agent):
    ws = OC_DIR / f"workspace-{agent}"
    bindings = get("bindings") or []
    allow = get("channels.telegram.allowFrom") or []
    entries = get("agents.entries")
    deny = (entry(entries, "tester").get("tools") or {}).get("deny") or DENY_DEFAULT
    print(f"Пользователь {tid} → агент «{agent}»")
    print(f"  папка агента: {ws} ({'есть' if ws.exists() else 'будет создана'}); правила = tester/HEADER.md + AGENTS.md Ави")
    print(f"  папки файлов: {AM}/saved_{agent}, {AM}/excel_{agent}")
    print(f"  агент: {'уже есть' if entry_path(entries, agent) else 'будет создан'}; запрет инструментов: {', '.join(deny)}")
    print(f"  маршрут: {'уже есть' if any((b.get('match', {}).get('peer') or {}).get('id') == tid for b in bindings) else 'будет добавлен'}")
    print(f"  доступ к Ави: {'уже есть' if tid in [str(a).split(':')[-1] for a in allow] else 'будет добавлен'}")
    for need in (AM / "tester" / "HEADER.md", OC_DIR / "workspace" / "AGENTS.md"):
        if not need.exists():
            sys.exit(f"СТОП: нет {need}")
    return deny, bindings, allow, entries


def cmd_apply(tid, agent):
    deny, bindings, allow, entries = cmd_plan(tid, agent)
    cfg = OC_DIR / "openclaw.json"
    if cfg.exists():
        bak = cfg.with_name(f"openclaw.json.bak-{agent}-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(cfg, bak)
        print("Копия настроек:", bak)
    # папка агента — как tester/setup.sh, но со своими путями
    src, ws = OC_DIR / "workspace", OC_DIR / f"workspace-{agent}"
    (ws / "skills").mkdir(parents=True, exist_ok=True)
    (ws / "AGENTS.md").write_text(header(tid, agent) + (src / "AGENTS.md").read_text(encoding="utf-8"), encoding="utf-8")
    if (src / "SOUL.md").exists():
        shutil.copy2(src / "SOUL.md", ws / "SOUL.md")
    for s in ("fin-assessment", "company-picker", "excel", "model-stress", "pdf-read"):
        if (src / "skills" / s).is_dir():
            shutil.copytree(src / "skills" / s, ws / "skills" / s, dirs_exist_ok=True)
    if not (ws / "MEMORY.md").exists():
        (ws / "MEMORY.md").write_text("# Память тестового пользователя\n\n## Предпочтения\n\n## Факты\n", encoding="utf-8")
    for d in (f"saved_{agent}/copy", f"excel_{agent}/in", f"excel_{agent}/out"):
        (AM / d).mkdir(parents=True, exist_ok=True)
    demo = AM / "excel_tester" / "in" / "demo_model.xlsx"
    if demo.exists():
        shutil.copy2(demo, AM / f"excel_{agent}" / "in" / "demo_model.xlsx")
    # агент, запреты, маршрут, доступ — как tester/connect.py
    if not entry_path(entries, agent):
        model = entry(entries, "tester").get("model") or (get("agents.defaults.model") or {})
        model = model.get("primary") if isinstance(model, dict) else model
        args = ["agents", "add", agent, "--workspace", str(ws), "--non-interactive"]
        if isinstance(model, str) and model:
            args += ["--model", model]
        print(oc(*args)[-600:])
        entries = get("agents.entries")
    path = entry_path(entries, agent)
    if not path:
        sys.exit("Агент добавлен, но не найден в agents.entries — пришли вывод: openclaw config get agents.entries")
    put(f"{path}.tools.deny", deny)
    if not any((b.get("match", {}).get("peer") or {}).get("id") == tid for b in bindings):
        put("bindings", bindings + [{"agentId": agent, "comment": f"тестовый пользователь {tid}",
                                     "match": {"channel": "telegram", "peer": {"kind": "direct", "id": tid}}}])
    if tid not in [str(a).split(":")[-1] for a in allow]:
        style = next((a for a in allow if isinstance(a, str)), "")
        put("channels.telegram.allowFrom", allow + [(style.split(":")[0] + ":" + tid) if ":" in style else tid])
    print(f"Готово: {tid} → агент «{agent}». Пусть напишет /start боту @marketMi_bot.")
    print(oc("agents", "list", "--bindings", check=False)[-1500:])


def cmd_off(tid, agent):
    bindings = get("bindings") or []
    allow = get("channels.telegram.allowFrom") or []
    put("bindings", [b for b in bindings if (b.get("match", {}).get("peer") or {}).get("id") != tid])
    put("channels.telegram.allowFrom", [a for a in allow if str(a).split(":")[-1] != tid])
    print(f"Отключено: {tid}. Папки агента «{agent}» сохранены.")


def cmd_jobs():
    for line in oc("automations", "list", check=False).splitlines():
        if "Тест" in line or "tester" in line:
            print(line)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "jobs":
        cmd_jobs()
    elif cmd in ("plan", "apply", "off"):
        {"plan": lambda t, a: cmd_plan(t, a) and None, "apply": cmd_apply, "off": cmd_off}[cmd](*check_args())
    else:
        sys.exit(__doc__)
