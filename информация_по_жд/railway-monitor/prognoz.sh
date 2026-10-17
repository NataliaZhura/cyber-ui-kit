#!/usr/bin/env bash
# Прогноз ставок до 2030 (PDF) в меню ЖДуши: файлы на место, правила, меню, показ гостю.
# Файлы прогноза в репозиторий не кладутся (внутренние расчёты) — их загружают с компьютера в ~/railway-monitor/:
#   prognoz_2030.pdf (владельцу), prognoz_2030_prilozhenie.pdf (приложение), prognoz_2030_guest.pdf (гостям).
#   git -C ~/zhd-repo pull && bash ~/zhd-repo/информация_по_жд/railway-monitor/prognoz.sh          всё по шагам
#   … prognoz.sh nodemo     без отправки гостю. Повторный запуск не создаёт дублей.
set -u
REPO=~/zhd-repo; KIT=~/railway-monitor; F=$KIT/forecast; GID=207215298
mkdir -p "$F/guest"

echo "== 1. Файлы прогноза"
for x in prognoz_2030.pdf prognoz_2030_prilozhenie.pdf prognoz_2030_guest.pdf model_data.json; do [ -f "$KIT/$x" ] && mv "$KIT/$x" "$F/"; done
[ -f "$F/prognoz_2030.pdf" ] && mv "$F/prognoz_2030.pdf" "$F/Прогноз_ставок_вагонов_2030.pdf"
[ -f "$F/prognoz_2030_prilozhenie.pdf" ] && mv "$F/prognoz_2030_prilozhenie.pdf" "$F/Приложение_факторы_и_источники.pdf"
[ -f "$F/prognoz_2030_guest.pdf" ] && mv "$F/prognoz_2030_guest.pdf" "$F/guest/Прогноз_ставок_вагонов_2030.pdf"
ok=1
for f in "$F/Прогноз_ставок_вагонов_2030.pdf" "$F/Приложение_факторы_и_источники.pdf" "$F/guest/Прогноз_ставок_вагонов_2030.pdf" "$F/model_data.json"; do
  if [ -f "$f" ]; then echo "есть: ${f#$KIT/}"; else echo "!! нет: ${f#$KIT/}"; ok=0; fi
done
if [ $ok = 0 ]; then
  echo "СТОП: загрузи файлы с компьютера (PowerShell; папка — куда сохранились, например «Загрузки\Telegram Desktop»):"
  echo '  cd "$HOME\Downloads\Telegram Desktop"; scp prognoz_2030.pdf prognoz_2030_prilozhenie.pdf prognoz_2030_guest.pdf model_data.json avia:~/railway-monitor/'
  exit 1
fi

echo "== 2. Обновление комплекта"
cd "$REPO" && git pull -q && cp информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/*.py \
  информация_по_жд/railway-monitor/*.sh "$KIT"/ && echo "ok"
cd "$KIT" || exit 1

echo "== 3. Правила владельца и гостя"
python3 openclaw_setup.py sync
python3 - <<'PY'
from pathlib import Path
import zguest
ws = Path.home() / ".openclaw" / "workspace-zguest"
if ws.is_dir():
    text = zguest.HEADER.replace("GUEST_ID", "207215298").replace("AGENT", "zguest") + (zguest.KIT / "AGENTS.md").read_text(encoding="utf-8")
    (ws / "AGENTS.md").write_text(text, encoding="utf-8")
    print(f"гость zguest: правила обновлены, {len(text)} знаков (лимит 20000)")
else:
    print("гостевого агента zguest нет — пропускаю")
PY

echo "== 3б. Проверка модели"
python3 zmodel.py run --wagon all --out /tmp/zmodel_test.md && grep -A6 "^| Тип вагона" /tmp/zmodel_test.md && grep -o "Надёжность набора: [^—]*" /tmp/zmodel_test.md

echo "== 4. Меню @zhdusha_bot"
python3 zmenu.py && python3 zmenu.py show | grep prognoz

echo "== 5. Перезапуск робота"
systemctl --user restart openclaw-gateway && sleep 20 && systemctl --user is-active openclaw-gateway

[ "${1:-}" = "nodemo" ] && { echo "== Готово (без показа гостю)"; exit 0; }
echo "== 6. Показ гостю (через 3 минуты, как в демонстрации)"
NAME="Гость ЖД: прогноз до 2030"
if openclaw automations list 2>/dev/null | grep -qF "$NAME"; then echo "уже есть: $NAME"
else
  T=$(date -d '+3 min' '+%M %H %d %m'); read -r MI HO DA MO <<<"$T"
  openclaw automations create "$((10#$MI)) $((10#$HO)) $((10#$DA)) $((10#$MO)) *" \
    "Демонстрация ЖДуши гостю. Покажи сам, без запроса. Раздел /prognoz — строго по PROGNOZ.md и гостевому правилу «/prognoz у гостя»: 1) отправь готовую гостевую презентацию python3 ~/railway-monitor/send.py --to $GID ~/railway-monitor/forecast/guest/Прогноз_ставок_вагонов_2030.pdf; 2) рассчитай общий прогноз рекомендуемыми показателями (zmodel.py run --wagon all --guest), сделай PDF и отправь гостю. В чат: первая строка «Новый раздел меню: /prognoz — прогноз ставок до 2030», затем 3 строки итогов из файла, последняя строка — «Можно выбрать свой тип вагона, год и показатели: кнопка «Меню» → /prognoz». Ссылок и названий источников не добавляй. Копию владельцу — по гостевым правилам, молча." \
    --name "$NAME" --tz Europe/Moscow --agent zguest --session isolated --announce --channel telegram --account zhdusha \
    --to "$GID" | grep -E '"name"|"nextRunAtMs"' | head -2
fi
echo "== Готово. Проверь у себя: кнопка «Меню» → /prognoz"
