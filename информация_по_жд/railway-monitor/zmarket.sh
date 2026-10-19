#!/usr/bin/env bash
# Сводка рынка ЖДуши: программы на место, правила владельца и гостя, первая сборка, расписание «после каждого сбора».
# Можно запускать повторно: расписание не дублируется. «Ави» не трогает.
#   bash ~/zhd-repo/информация_по_жд/railway-monitor/zmarket.sh
set -u
REPO=~/zhd-repo; KIT=~/railway-monitor; GID=207215298
echo "== 1. Обновление комплекта"
cd "$REPO" && git pull -q && cp информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/*.py \
  информация_по_жд/railway-monitor/*.sh "$KIT"/ && echo "ok"
cd "$KIT" || exit 1

echo "== 2. Правила владельца и гостя"
python3 openclaw_setup.py sync
python3 - <<'PY'
from pathlib import Path
import zguest
ws = Path.home() / ".openclaw" / "workspace-zguest"
if ws.is_dir():
    zguest.write_rules("207215298", "zguest")
    n = len((ws / "AGENTS.md").read_text(encoding="utf-8"))
    print(f"гость zguest: правила обновлены, {n} знаков (лимит 20000)" + ("  ⚠ БОЛЬШЕ ЛИМИТА" if n > 20000 else ""))
else:
    print("гостевого агента zguest нет — пропускаю")
PY

echo "== 3. Первая сборка сводок"
python3 zmarket.py build && python3 zmarket.py build --guest
head -4 "saved/market/сводка_полувагоны.md"

echo "== 4. Расписание: сводка через 20 минут после каждого сбора новостей (0 токенов)"
NAME="ЖД: сводка рынка"
if openclaw automations list 2>/dev/null | grep -qF "$NAME"; then echo "уже есть: $NAME"
else openclaw automations create "40 */3 * * *" --command "python3 zmarket.py build && python3 zmarket.py build --guest" \
       --command-cwd "$KIT" --no-deliver --name "$NAME" --tz "Europe/Moscow" >/dev/null && echo "создано: $NAME" \
       || echo "!! не создано: $NAME — пришли этот вывод"
fi
openclaw automations list 2>/dev/null | grep -F "ЖД:" || true

echo "== 5. Перезапуск робота (правила читаются заново)"
systemctl --user restart openclaw-gateway && sleep 20 && systemctl --user is-active openclaw-gateway
echo "== Готово. Проверь: /poluvagony — в ответе цифры с датами из сводки; через 1–2 недели — python3 tokens.py"
