#!/usr/bin/env bash
# Донастройка ЖДуши одной командой: обновление, правила, меню, автоустановка меню, расписания.
# Можно запускать повторно: уже созданные расписания не дублируются. «Ави» не трогает.
#   bash ~/zhd-repo/информация_по_жд/railway-monitor/finish.sh
set -u
REPO=~/zhd-repo; KIT=~/railway-monitor
echo "== 1. Обновление комплекта"
cd "$REPO" && git pull -q && cp информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/*.py \
  информация_по_жд/railway-monitor/*.sh информация_по_жд/railway-monitor/sources.json "$KIT"/ && echo "ok"
cd "$KIT" || exit 1
mkdir -p saved private/argus

echo "== 2. Правила и навыки в папке агента"
python3 openclaw_setup.py sync

echo "== 3. Меню @zhdusha_bot сейчас"
python3 zmenu.py

echo "== 4. Меню — само после каждого перезапуска OpenClaw"
python3 openclaw_setup.py menu || echo "!! автоустановка меню не включена — пришли этот вывод"

echo "== 5. Расписания"
OWNER=$(cat ~/.secrets/zhdusha_owner)
LIST=$(openclaw automations list 2>/dev/null)
add() {  # add "<название>" <аргументы openclaw automations create>
  local name="$1"; shift
  if grep -qF "$name" <<<"$LIST"; then echo "уже есть: $name"
  else openclaw automations create "$@" --name "$name" --tz "Europe/Moscow" >/dev/null && echo "создано: $name" \
       || echo "!! не создано: $name"; fi
}
AGENT=(--agent zhdusha --session isolated --announce --channel telegram --account zhdusha --to "$OWNER")
add "ЖД: сбор" "20 */3 * * *" --command "python3 collector.py collect --days 3" --command-cwd "$KIT"
add "ЖД: утренние новости" "45 8 * * *" \
  "Подготовь утренние новости за вчера строго по TEMPLATE.md и правилам AGENTS.md (каждое событие — один раз). Сначала запусти: python3 ~/railway-monitor/collector.py collect --days 2" "${AGENT[@]}"
add "ЖД: прогноз на неделю" "0 17 * * 5" \
  "Подготовь прогноз на следующую неделю по полувагонам и крытым по разделу «Прогноз» в AGENTS.md: ставки, грузопоток, баланс парка, микро- и макрориски. Каждое событие — один раз. Сохрани в saved/ и пришли PDF." "${AGENT[@]}"
add "ЖД: сверка прогноза" "0 9 * * 1" \
  "Сверь пятничный прогноз из saved/ с фактом: что сбылось, что нет и почему. До 10 строк." "${AGENT[@]}"

echo "== 6. Проверка"
[ -f watchlist.csv ] && echo "watchlist.csv: $(($(wc -l < watchlist.csv)-1)) компаний" || echo "!! нет watchlist.csv"
echo "выпусков Argus: $(ls private/argus/*.pdf 2>/dev/null | wc -l)"
ls private/argus/*.pdf >/dev/null 2>&1 && ~/pw/bin/python argus.py | tail -3
python3 collector.py stats 2>/dev/null | tail -3
openclaw automations list 2>/dev/null | grep -F "ЖД:" || true
echo "== Готово. В @zhdusha_bot: /new, затем /start — должна появиться кнопка «Меню»."
