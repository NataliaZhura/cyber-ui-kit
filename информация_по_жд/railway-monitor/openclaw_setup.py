#!/usr/bin/env python3
"""Подключить ЖДушу вторым агентом и вторым ботом к OpenClaw, не ломая «Ави».

  python3 openclaw_setup.py plan     показать, что изменится (ничего не меняет)
  python3 openclaw_setup.py apply    копия настроек → агент zhdusha → бот @zhdusha_bot → правило маршрута
  python3 openclaw_setup.py check    проверить результат (агенты, правила, каналы)
  python3 openclaw_setup.py undo     вернуть настройки из последней копии

Что меняется в ~/.openclaw/openclaw.json:
  - channels.telegram.tokenFile, allowFrom, меню «Ави» — НЕ трогаем (их читают menu.py и share.py «Ави»);
  - channels.telegram.accounts.default  → тот же файл токена «Ави» (явный бот по умолчанию);
  - channels.telegram.accounts.zhdusha  → токен ~/.secrets/zhdusha_bot, писать может только владелец;
  - channels.telegram.defaultAccount    → "default";
  - bindings: + {agentId: zhdusha, match: telegram, accountId: zhdusha}; правило тестировщика остаётся.
Агент создаётся командой `openclaw agents add` с отдельной папкой ~/.openclaw/workspace-zhdusha.
После apply нужен перезапуск OpenClaw — команду скрипт подскажет.
"""
import copy
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CFG = HOME / ".openclaw" / "openclaw.json"
WS = HOME / ".openclaw" / "workspace-zhdusha"
KIT = Path(__file__).resolve().parent
TOKEN = HOME / ".secrets" / "zhdusha_bot"
OWNER = HOME / ".secrets" / "zhdusha_owner"
AGENT, ACCOUNT, MODEL = "zhdusha", "zhdusha", "openai/gpt-5.6-sol"


def load():
    return json.loads(CFG.read_text(encoding="utf-8"))


def owner_id(cfg):
    if OWNER.exists():
        return OWNER.read_text().strip()
    ids = cfg["channels"]["telegram"].get("allowFrom") or []
    return str(ids[0]) if ids else None


def changed(cfg):
    new = copy.deepcopy(cfg)
    tg = new["channels"]["telegram"]
    accounts = tg.setdefault("accounts", {})
    accounts.setdefault("default", {"tokenFile": tg["tokenFile"]})
    accounts[ACCOUNT] = {"tokenFile": str(TOKEN), "dmPolicy": "allowlist", "allowFrom": [owner_id(cfg)]}
    tg.setdefault("defaultAccount", "default")
    binds = new.setdefault("bindings", [])
    if not any(b.get("agentId") == AGENT for b in binds):
        binds.append({"agentId": AGENT, "comment": "ЖДуша — свой бот",
                      "match": {"channel": "telegram", "accountId": ACCOUNT}})
    return new


def show(old, new):
    o, n = old["channels"]["telegram"], new["channels"]["telegram"]
    print("channels.telegram.accounts:", json.dumps(n.get("accounts"), ensure_ascii=False, indent=1))
    print("channels.telegram.defaultAccount:", n.get("defaultAccount"))
    print("tokenFile «Ави» без изменений:", o["tokenFile"] == n["tokenFile"])
    print("bindings:", json.dumps(new.get("bindings"), ensure_ascii=False))


def agents():
    out = subprocess.run(["openclaw", "agents", "list"], capture_output=True, text=True, timeout=120).stdout
    return out


def cmd_plan():
    problems = []
    if not TOKEN.exists() or TOKEN.stat().st_size < 30:
        problems.append(f"нет токена {TOKEN}")
    cfg = load()
    if not owner_id(cfg):
        problems.append("не найден Telegram ID владельца")
    show(cfg, changed(cfg))
    print("агент zhdusha уже есть:", f"- {AGENT}" in agents())
    print("папка агента:", WS, "(будет создана)" if not WS.exists() else "(есть)")
    if problems:
        sys.exit("СТОП: " + "; ".join(problems))
    print("\nВсё готово к apply.")


def restart_hint():
    units = subprocess.run("systemctl list-units --type=service --all --no-legend | grep -i claw; "
                           "systemctl --user list-units --type=service --all --no-legend 2>/dev/null | grep -i claw",
                           shell=True, capture_output=True, text=True).stdout.split()
    names = [u for u in units if u.endswith(".service")]
    print("\nПерезапусти OpenClaw:", " / ".join(f"systemctl restart {u}" for u in names) or
          "служба не найдена — пришли вывод `systemctl list-units | grep -i claw`")


def cmd_apply():
    cmd_plan()
    backup = CFG.with_name(f"openclaw.json.bak-zhdusha-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(CFG, backup)
    print("\nКопия настроек:", backup)
    if f"- {AGENT}" not in agents():
        r = subprocess.run(["openclaw", "agents", "add", AGENT, "--workspace", str(WS), "--model", MODEL,
                            "--non-interactive"], capture_output=True, text=True, timeout=300)
        print(r.stdout[-1500:], r.stderr[-1500:])
        if r.returncode:
            sys.exit("Агент не создан — настройки не менялись. Пришли этот вывод.")
    WS.mkdir(parents=True, exist_ok=True)
    for f in ("AGENTS.md", "SOUL.md", "TEMPLATE.md"):
        shutil.copy2(KIT / f, WS / f)
    cfg = load()  # перечитываем: agents add мог дописать агента в файл
    CFG.write_text(json.dumps(changed(cfg), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Настройки записаны. Откат: python3 openclaw_setup.py undo")
    restart_hint()


def cmd_check():
    for c in (["openclaw", "agents", "list", "--bindings"], ["openclaw", "channels", "status", "--probe"],
              ["openclaw", "doctor"]):
        r = subprocess.run(c, capture_output=True, text=True, timeout=300)
        print("$", " ".join(c), "\n", (r.stdout + r.stderr)[-3000:])


def cmd_undo():
    backups = sorted(CFG.parent.glob("openclaw.json.bak-zhdusha-*"))
    if not backups:
        sys.exit("Копий нет — нечего возвращать.")
    shutil.copy2(backups[-1], CFG)
    print("Настройки возвращены из", backups[-1])
    restart_hint()


if __name__ == "__main__":
    cmds = {"plan": cmd_plan, "apply": cmd_apply, "check": cmd_check, "undo": cmd_undo}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
