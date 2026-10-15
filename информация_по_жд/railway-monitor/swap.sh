#!/usr/bin/env bash
# Анастасия: «Ави» → «ЖДуша» (гостем, без Argus); Владислав: доступ к «Ави» (отдельный агент).
#   bash ~/railway-monitor/swap.sh
set -u
A=207215298; V=328083444
cd ~/railway-monitor || exit 1
echo "== 1. Анастасия: отключить от Ави"
(cd ~/aviation-monitor && python3 tester/connect.py $A --off)
echo "== 2. Её рассылки «Тест: …» в Ави — выключить (не удаляются; включить обратно: openclaw automations enable <id>)"
for id in $(openclaw automations list 2>/dev/null | grep "Тест" | awk '{print $1}'); do
  openclaw automations disable "$id" >/dev/null && echo "выключено: $id"
done
echo "== 3. Владислав → Ави"
python3 guest.py apply $V vladislav | tail -2
echo "== 4. Анастасия → ЖДуша (гость)"
python3 zguest.py apply $A zguest
echo "== 5. Перезапуск OpenClaw (меню обоих ботов поставится само через 1–2 минуты)"
systemctl --user restart openclaw-gateway && sleep 30 && echo "перезапущено"
openclaw agents list --bindings 2>/dev/null | grep -E "^- |peer=|accountId" 
echo "== Готово. Владислав: /start в @marketMi_bot. Анастасия: /start в @zhdusha_bot."
