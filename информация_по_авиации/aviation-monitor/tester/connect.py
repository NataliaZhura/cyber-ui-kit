#!/usr/bin/env python3
"""Подключить тестового пользователя: отдельный агент `tester`, его сообщения — только в этого агента.

  python3 tester/connect.py <TELEGRAM_ID>          подключить (сначала bash tester/setup.sh <ID>)
  python3 tester/connect.py <TELEGRAM_ID> --off    отключить: убрать привязку и доступ (папка агента остаётся)

Что делает (существующие настройки дополняет, а не затирает):
  1. агент `tester` с рабочей папкой ~/.openclaw/workspace-tester и той же моделью, что у основного;
  2. запрет агенту служебных инструментов (настройки OpenClaw, расписания, управление другими сессиями);
  3. привязка: личные сообщения этого Telegram ID → агент `tester`;
  4. ID — в список разрешённых пользователей бота.
"""
import json
import subprocess
import sys
from pathlib import Path

AGENT = "tester"
WORKSPACE = str(Path.home() / ".openclaw" / "workspace-tester")
# инструменты, которые тестовому агенту не нужны и опасны: настройки шлюза, расписания, узлы, чужие сессии
DENY = ["gateway", "cron", "nodes", "sessions_send", "sessions_spawn", "sessions_list", "sessions_history", "canvas"]


def oc(*args, check=True):
    r = subprocess.run(["openclaw", *args], capture_output=True, text=True, timeout=120)
    if check and r.returncode != 0:
        sys.exit(f"openclaw {' '.join(args)} → ошибка:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r.stdout


def get(path):
    """Значение настройки как JSON; не задано — None. В выводе бывают служебные строки — берём JSON целиком."""
    out = oc("config", "get", path, check=False)
    if "unset" in out or "Unknown config path" in out:
        return None
    starts = [i for i in (out.find("{"), out.find("["), out.find('"')) if i >= 0]
    if not starts:
        return None
    i = min(starts)
    end = max(out.rfind("}"), out.rfind("]"), out.rfind('"')) + 1
    return json.loads(out[i:end])


def put(path, value):
    oc("config", "set", path, json.dumps(value, ensure_ascii=False))


def agent_path(entries):
    """Путь к записи агента: entries бывает словарём {id: {...}} или списком [{name: id, ...}]."""
    if isinstance(entries, dict) and AGENT in entries:
        return f"agents.entries.{AGENT}"
    if isinstance(entries, list):
        for i, e in enumerate(entries):
            if AGENT in (e.get("name"), e.get("id")):
                return f"agents.entries.{i}"
    return None


def main(tid, off=False):
    if not tid.isdigit():
        sys.exit("Telegram ID — только цифры.")
    binding = {"agentId": AGENT, "comment": "тестовый пользователь",
               "match": {"channel": "telegram", "peer": {"kind": "direct", "id": tid}}}
    bindings = get("bindings") or []
    allow = get("channels.telegram.allowFrom") or []
    style = next((a for a in allow if isinstance(a, str)), "")
    entry = (style.split(":")[0] + ":" + tid) if ":" in style else tid  # тот же формат, что у владельца

    if off:
        put("bindings", [b for b in bindings if (b.get("match", {}).get("peer") or {}).get("id") != tid])
        put("channels.telegram.allowFrom", [a for a in allow if str(a).split(":")[-1] != tid])
        print(f"Отключено: {tid} убран из привязок и разрешённых. Папка {WORKSPACE} сохранена.")
        return

    if not Path(WORKSPACE, "AGENTS.md").exists():
        sys.exit(f"Нет {WORKSPACE}/AGENTS.md — сначала: bash tester/setup.sh {tid}")
    entries = get("agents.entries")
    if not agent_path(entries):
        model = (get("agents.defaults.model") or {})
        model = model.get("primary") if isinstance(model, dict) else model
        args = ["agents", "add", AGENT, "--workspace", WORKSPACE, "--non-interactive"]
        if isinstance(model, str) and model:
            args += ["--model", model]
        oc(*args)
        entries = get("agents.entries")
    path = agent_path(entries)
    if not path:
        sys.exit("Агент добавлен, но не найден в agents.entries — пришли вывод: openclaw config get agents.entries")
    put(f"{path}.tools.deny", DENY)
    if not any((b.get("match", {}).get("peer") or {}).get("id") == tid for b in bindings):
        put("bindings", bindings + [binding])
    if entry not in allow and tid not in [str(a).split(":")[-1] for a in allow]:
        put("channels.telegram.allowFrom", allow + [entry])
    print(f"Готово: агент «{AGENT}» ({path}), запрещено: {', '.join(DENY)}; "
          f"сообщения {tid} → {AGENT}; {tid} в разрешённых.")
    print(oc("agents", "list", "--bindings", check=False)[-1200:])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], "--off" in sys.argv)
