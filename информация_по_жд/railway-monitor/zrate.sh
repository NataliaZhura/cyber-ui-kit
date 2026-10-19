#!/usr/bin/env bash
# Модель ставки полувагона (zrate.py) на сервер: данные и документы — в forecast/, правила /prognoz, проверка.
# Файлы с компьютера (в репозиторий не кладутся) — заранее в ~/railway-monitor/:
#   rate_data.json, Модель_ставки_полувагона_2030.pdf, Модель_ставки_полувагона_2030.xlsx
#   bash ~/zhd-repo/информация_по_жд/railway-monitor/zrate.sh
set -u
REPO=~/zhd-repo; KIT=~/railway-monitor; F=$KIT/forecast
mkdir -p "$F"
echo "== 1. Файлы модели"
for x in rate_data.json Модель_ставки_полувагона_2030.pdf Модель_ставки_полувагона_2030.xlsx; do
  [ -f "$KIT/$x" ] && mv "$KIT/$x" "$F/"
  [ -f "$F/$x" ] && echo "есть: forecast/$x" || echo "!! нет: forecast/$x"
done
[ -f "$F/rate_data.json" ] || { echo "СТОП: загрузи rate_data.json (PowerShell): scp rate_data.json avia:~/railway-monitor/"; exit 1; }
echo "== 2. Обновление комплекта"
cd "$REPO" && git pull -q && cp информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/*.py \
  информация_по_жд/railway-monitor/*.sh "$KIT"/ && cp -r информация_по_жд/railway-monitor/miniapp "$KIT"/ && echo "ok"
cd "$KIT" || exit 1
echo "== 3. Правила владельца и гостя"
python3 openclaw_setup.py sync
python3 - <<'PY'
from pathlib import Path
import zguest
ws = Path.home() / ".openclaw" / "workspace-zguest"
if ws.is_dir():
    zguest.write_rules("207215298", "zguest")
    print("гость zguest: правила обновлены,", len((ws / "AGENTS.md").read_text(encoding="utf-8")), "знаков (лимит 20000)")
PY
echo "== 4. Проверка модели"
python3 zrate.py menu | head -5
python3 zrate.py run --pick "2 1 4" | sed -n 5,11p
python3 zrate.py track coal=2.9 load=1.2 stroy=-3.7 netoff=0.7 workcut=5.1 | tail -1
echo "== 5. Мини-приложение («Прогнозы» → «Построить прогноз»)"
systemctl restart zhdusha-app 2>/dev/null && sleep 2 && systemctl is-active zhdusha-app || echo "служба zhdusha-app не найдена — приложение ещё не включено (SETUP.md, п. 7)"
echo "== Готово. В чате ЖДуши: /new, затем «прогноз ставки инновационного полувагона до 2030»"
