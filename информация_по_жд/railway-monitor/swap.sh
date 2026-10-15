#!/usr/bin/env bash
# Владислав занимает место Анастасии в «Ави» (тот же агент tester и его рассылки «Тест: …»);
# Анастасия — гостем в «ЖДушу» (без Argus, копии владельцу). Личное Анастасии из «Ави» — в архив, не удаляется.
#   bash ~/railway-monitor/swap.sh
set -u
A=207215298; V=328083444; D=$(date +%Y%m%d)
AM=~/aviation-monitor; WS=~/.openclaw/workspace-tester
cp ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak-swap-$D-$(date +%H%M%S) && echo "копия настроек сделана"

echo "== 1. Анастасия: отключить от Ави"
(cd "$AM" && python3 tester/connect.py $A --off)

echo "== 2. Личное Анастасии — в архив (память, журнал, отзыв, справки)"
ARC="$AM/saved_tester_anastasia_$D"
[ -d "$AM/saved_tester" ] && mv "$AM/saved_tester" "$ARC" && echo "справки, журнал, отзыв → $ARC"
mkdir -p "$ARC" "$AM/saved_tester/copy"
[ -f "$WS/MEMORY.md" ] && mv "$WS/MEMORY.md" "$ARC/MEMORY_tester.md" && echo "память агента → $ARC/MEMORY_tester.md"
[ -d "$AM/excel_tester/out" ] && mv "$AM/excel_tester/out" "$ARC/excel_out" && mkdir -p "$AM/excel_tester/out"

echo "== 3. Агент tester — правила на Владислава, подключение"
(cd "$AM" && bash tester/setup.sh $V && python3 tester/connect.py $V | head -1)

echo "== 4. Рассылки «Тест: …» — адресат Владислав"
for id in $(openclaw automations list 2>/dev/null | grep "Тест" | awk '{print $1}'); do
  openclaw automations edit "$id" --to "$V" >/dev/null && echo "перенаправлено: $id"
done

echo "== 5. Анастасия → ЖДуша (гость)"
cd ~/railway-monitor && python3 zguest.py apply $A zguest

echo "== 6. Перезапуск OpenClaw (меню обоих ботов поставится само через 1–2 минуты)"
systemctl --user restart openclaw-gateway && sleep 30 && echo "перезапущено"
openclaw agents list --bindings 2>/dev/null | grep -E "^- |peer=|accountId"
echo "== Готово. Владислав: /start в @marketMi_bot. Анастасия: /start в @zhdusha_bot."
