#!/usr/bin/env bash
# «Обзор рынка вагонов ЖДуши»: база наблюдений из выпусков партнёра (private/argus/*.pdf) → выпуск PDF владельцу.
#   bash ~/zhd-repo/информация_по_жд/railway-monitor/zissue.sh [ГГГГ-ММ]
# Новый выпуск партнёра: положить PDF в ~/railway-monitor/private/argus/ и запустить снова (повтор не дублирует).
set -u
REPO=~/zhd-repo; KIT=~/railway-monitor
echo "== 1. Обновление комплекта"
cd "$REPO" && git pull -q && cp информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/*.py \
  информация_по_жд/railway-monitor/*.sh "$KIT"/ && echo "ok"
cd "$KIT" || exit 1
python3 openclaw_setup.py sync >/dev/null && echo "правила ЖДуши обновлены"
echo "== 2. База наблюдений из выпусков партнёра"
ls private/argus/*.pdf >/dev/null 2>&1 || { echo "СТОП: нет PDF в ~/railway-monitor/private/argus/"; exit 1; }
~/pw/bin/python zobs.py pdf private/argus/*.pdf
python3 zobs.py months
echo "== 3. Выпуск"
M=${1:+--month $1}
D=$(date +%F)
python3 zissue.py $M --out saved/market/${D}_обзор_рынка_вагонов.md && ~/pw/bin/python zreport.py saved/market/${D}_обзор_рынка_вагонов.md
python3 zissue.py $M --demo --out saved/market/${D}_обзор_рынка_вагонов_демо.md && ~/pw/bin/python zreport.py saved/market/${D}_обзор_рынка_вагонов_демо.md
echo "== 4. Отправка владельцу"
python3 send.py saved/market/${D}_обзор_рынка_вагонов.pdf saved/market/${D}_обзор_рынка_вагонов_демо.pdf
echo "== Готово. В ЖДуше: /new, затем «обзор рынка вагонов»"
