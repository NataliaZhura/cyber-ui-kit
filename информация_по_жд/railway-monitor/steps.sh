#!/usr/bin/env bash
# Экономия токенов: выключить «проверку связи» (heartbeat) всех агентов и вписать блок «Экономия шагов»
# в правила ЖДуши, гостя, Ави и тестировщика. Перед изменениями — копии. Можно запускать повторно.
#   bash ~/zhd-repo/информация_по_жд/railway-monitor/steps.sh
set -u
REPO=~/zhd-repo; KIT=~/railway-monitor
echo "== 1. Обновление комплекта"
cd "$REPO" && git pull -q && cp информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/*.py \
  информация_по_жд/railway-monitor/*.sh "$KIT"/ && echo "ok"
cd "$KIT" || exit 1

echo "== 2. Проверка связи (heartbeat): что говорит справочник настроек"
openclaw config schema 2>/dev/null > /tmp/schema.json
EVERY=$(python3 - <<'PY'
import json
t = open("/tmp/schema.json", encoding="utf-8").read()
try:
    node = json.loads(t[t.find("{"):])
    for part in ("agents", "defaults", "heartbeat"):
        node = node["properties"][part]
    props = node.get("properties") or {}
except (ValueError, KeyError, TypeError):
    props = {}
for k, v in props.items():
    print(f"   {k}: {(v.get('description') or '')[:150]}", file=__import__("sys").stderr)
print("yes" if "every" in props else "no")
PY
)
if [ "$EVERY" = "yes" ]; then
  mkdir -p ~/.openclaw/backups && cp ~/.openclaw/openclaw.json ~/.openclaw/backups/openclaw.json.before-heartbeat-$(date +%F)
  openclaw config set agents.defaults.heartbeat.every 0m && echo "проверка связи выключена (копия настроек — ~/.openclaw/backups/)" \
    || echo "!! не получилось — настройки не менялись, пришли этот вывод"
  openclaw config get agents.defaults.heartbeat 2>&1 | head -8
else
  echo "!! в справочнике нет agents.defaults.heartbeat.every — проверку связи не трогаю, пришли этот вывод"
fi

echo "== 3. Правила ЖДуши и гостя"
python3 openclaw_setup.py sync
python3 - <<'PY'
from pathlib import Path
import zguest
ws = Path.home() / ".openclaw" / "workspace-zguest"
if ws.is_dir():
    zguest.write_rules("207215298", "zguest")
    n = len((ws / "AGENTS.md").read_text(encoding="utf-8"))
    print(f"гость zguest: правила обновлены, {n} знаков (лимит 20000)" + ("  ⚠ БОЛЬШЕ ЛИМИТА" if n > 20000 else ""))
PY

echo "== 4. Правила Ави и тестировщика"
python3 steps_rules.py --apply

echo "== 5. Перезапуск робота"
systemctl --user restart openclaw-gateway && sleep 20 && systemctl --user is-active openclaw-gateway
echo "== Готово. Через неделю: python3 ~/railway-monitor/tokens.py --steps > saved/tokens_steps.txt и прислать файл"
