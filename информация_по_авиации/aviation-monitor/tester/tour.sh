#!/usr/bin/env bash
# Экскурсия тестовому пользователю в PDF: памятка «Ави — что умеет» + короткое приветствие + демо-модель.
#   bash tester/tour.sh <TELEGRAM_ID_тестировщика> [ЧЧ:ММ]   (по умолчанию 11:30 сегодня по Москве)
# Старая текстовая экскурсия «Тест: экскурсия» выключается (не удаляется).
set -euo pipefail
ID="${1:?Укажи Telegram ID тестировщика}"
[[ "$ID" =~ ^[0-9]{5,15}$ ]] || { echo "ID должен быть числом"; exit 1; }
AT="${2:-11:30}"; HH="${AT%%:*}"; MM="${AT##*:}"
cd ~/aviation-monitor
cp demo/guide.md demo/Ави_что_умеет.md
~/pw/bin/python share.py report demo/Ави_что_умеет.md owner   # собрать PDF и показать владельцу
OLD=$(openclaw automations list --json | python3 automation_id.py "Тест: экскурсия" 2>/dev/null || true)
[ -n "$OLD" ] && openclaw automations disable "$OLD" >/dev/null && echo "выключена: Тест: экскурсия (11:00)"
MSG="Экскурсия по Ави: пользователь — потенциальный клиент, первый день теста. Одним сообщением, не длиннее 6 строк: коротко поздоровайся, скажи, что Ави — аналитик авиарынка по открытым источникам, что памятка со всеми возможностями — в PDF ниже, и предложи начать с /profile → Аэрофлот или «проверь демо-модель». Затем отправь файлы: python3 ~/aviation-monitor/share.py tg $ID ~/aviation-monitor/demo/Ави_что_умеет.pdf ~/aviation-monitor/excel_tester/in/demo_model.xlsx"
openclaw automations create "$((10#$MM)) $((10#$HH)) $(date +%-d) $(date +%-m) *" "$MSG" --name "Тест: экскурсия PDF" \
  --tz Europe/Moscow --agent tester --session isolated --announce --channel telegram --to "$ID" \
  | grep -E '"name"|"nextRunAtMs"' | head -2
