#!/usr/bin/env bash
# Рабочая папка отдельного агента для тестового пользователя: свои правила, память и навыки, без данных владельца.
#   bash tester/setup.sh <TELEGRAM_ID_тестировщика>
# Настройки OpenClaw (агент, маршрут сообщений этого человека к нему, доступ) — отдельными командами после проверки
# схемы конфигурации: формат зависит от версии OpenClaw.
set -euo pipefail
ID="${1:?Укажи Telegram ID тестировщика: bash tester/setup.sh 123456789}"
[[ "$ID" =~ ^[0-9]{5,15}$ ]] || { echo "ID должен быть числом"; exit 1; }
SRC=~/.openclaw/workspace
DST=~/.openclaw/workspace-tester
AM=~/aviation-monitor
mkdir -p "$DST/skills" "$AM/excel_tester/in" "$AM/excel_tester/out" "$AM/saved_tester"
# правила: ограничения тестировщика + общие правила; ID подставляется вместо TESTER_ID
sed "s/TESTER_ID/$ID/g" "$AM/tester/HEADER.md" > "$DST/AGENTS.md"
cat "$SRC/AGENTS.md" >> "$DST/AGENTS.md"
[ -f "$SRC/SOUL.md" ] && cp "$SRC/SOUL.md" "$DST/"
# навыки, нужные для справок и моделей (методика — для расчёта класса; текст наружу не выдаётся по правилам)
for s in fin-assessment company-picker excel model-stress pdf-read; do
  [ -d "$SRC/skills/$s" ] && cp -r "$SRC/skills/$s" "$DST/skills/"
done
# память не затираем при повторном запуске
[ -f "$DST/MEMORY.md" ] || printf '# Память тестового пользователя\n\n## Предпочтения\n\n## Факты\n' > "$DST/MEMORY.md"
echo "Готово: $DST (правила $(wc -l < "$DST/AGENTS.md") строк, навыки: $(ls "$DST/skills" | tr '\n' ' '))"
