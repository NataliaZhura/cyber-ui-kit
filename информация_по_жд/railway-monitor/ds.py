#!/usr/bin/env python3
"""DeepSeek для тестовых агентов — экономия подписки ChatGPT. Владелец (main, zhdusha) остаётся на GPT.

  python3 ds.py check                         только смотрит: версия, модуль DeepSeek, ключ, модели агентов
  python3 ds.py on  [агент ...]               перевести на DeepSeek (по умолчанию tester и zguest), GPT — запасной
  python3 ds.py off [агент ...]               вернуть GPT (DeepSeek — запасной)
  python3 ds.py on  --owner main tester zhdusha zguest    все агенты, включая владельца (когда кончился лимит GPT)
  python3 ds.py off --owner main tester zhdusha zguest    вернуть всех на GPT

Ключ: файл ~/.secrets/deepseek_key (одна строка, sk-…). Программа сама кладёт его в ~/.openclaw/.env
(DEEPSEEK_API_KEY) — так его видит робот. Ключ на экран не выводится.
Перед изменением — копия ~/.openclaw/openclaw.json.bak-ds-<дата>. После — перезапуск робота.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guest  # noqa: E402  — те же oc/get/put, что у гостевых агентов

DS = os.environ.get("DS_MODEL", "deepseek/deepseek-flash")
DS_PRO = "deepseek/deepseek-v4-pro"
GPT = "openai/gpt-5.6-sol"
DEFAULT = ["tester", "zguest"]
OWNER = ("main", "zhdusha")
KEYFILE = Path.home() / ".secrets" / "deepseek_key"
ENV = guest.OC_DIR / ".env"


def models():
    entries = guest.get("agents.entries") or []
    names = list(entries) if isinstance(entries, dict) else [e.get("id") or e.get("name") for e in entries]
    return entries, {n: guest.entry(entries, n).get("model") for n in names}


def key_in_env():
    return ENV.exists() and re.search(r"^DEEPSEEK_API_KEY=\S+", ENV.read_text(encoding="utf-8"), re.M)


def check():
    print("== OpenClaw:", guest.oc("--version", check=False).strip())
    print("== Модуль DeepSeek:")
    out = guest.oc("plugins", "list", check=False)
    print("  ", "\n   ".join(l for l in out.splitlines() if "deepseek" in l.lower()) or "не установлен")
    print("== Модели DeepSeek:")
    print("  ", guest.oc("models", "list", "--provider", "deepseek", check=False).strip()[-800:] or "нет")
    print("== Ключ:", "есть в ~/.secrets" if KEYFILE.exists() else "НЕТ ~/.secrets/deepseek_key",
          "| в .env робота:", "есть" if key_in_env() else "нет")
    print("== Модели агентов:")
    for n, m in models()[1].items():
        print(f"   {n}: {m or 'по умолчанию — ' + str(guest.get('agents.defaults.model'))}")


def put_key():
    if key_in_env():
        return
    if re.search(r"^deepseek/\S+.*\byes\b", guest.oc("models", "list", "--provider", "deepseek", check=False), re.M):
        return  # доступ к DeepSeek уже настроен в OpenClaw (Auth: yes)
    if not KEYFILE.exists():
        sys.exit(f"СТОП: нет {KEYFILE} — положи туда ключ DeepSeek одной строкой и запусти снова. Ничего не изменено.")
    key = KEYFILE.read_text(encoding="utf-8").strip()
    with ENV.open("a", encoding="utf-8") as f:
        f.write(f"\nDEEPSEEK_API_KEY={key}\n")
    ENV.chmod(0o600)
    print("Ключ добавлен в ~/.openclaw/.env")


def switch(on, agents):
    owner = "--owner" in agents
    agents = [a for a in agents if a != "--owner"]
    if not owner and (bad := [a for a in agents if a in OWNER]):
        sys.exit(f"СТОП: {', '.join(bad)} — агенты владельца; переключать их — только с --owner.")
    if on:
        if "deepseek" not in guest.oc("plugins", "list", check=False).lower():
            print(guest.oc("plugins", "install", "@openclaw/deepseek-provider", check=False)[-600:])
        put_key()
    entries, cur = models()
    cfg = guest.OC_DIR / "openclaw.json"
    shutil.copy2(cfg, cfg.with_name(f"openclaw.json.bak-ds-{datetime.now():%Y%m%d-%H%M%S}"))
    for a in agents:
        path = guest.entry_path(entries, a)
        if not path:
            print(f"{a}: такого агента нет — пропускаю")
            continue
        if on:
            guest.put(f"{path}.model", {"primary": DS, "fallbacks": [DS_PRO, GPT]})
        else:
            guest.put(f"{path}.model", {"primary": GPT, "fallbacks": [DS, DS_PRO]})
        print(f"{a}: было {cur.get(a)} → стало {models()[1].get(a)}")
    subprocess.run(["systemctl", "--user", "restart", "openclaw-gateway"], check=False)
    print("Робот перезапущен. Проверка: напиши тестовому боту «привет» и посмотри журнал:\n"
          "  journalctl --user -u openclaw-gateway -n 40 --no-pager | grep -i -E 'deepseek|error'")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        check()
    elif cmd in ("on", "off"):
        switch(cmd == "on", sys.argv[2:] or DEFAULT)
    else:
        sys.exit(__doc__)
