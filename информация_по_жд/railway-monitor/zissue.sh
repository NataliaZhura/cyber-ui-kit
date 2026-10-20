#!/usr/bin/env bash
# «Обзор рынка вагонов ЖДуши»: база наблюдений из выпусков партнёра (private/argus/*.pdf) → выпуск PDF владельцу.
#   bash ~/zhd-repo/информация_по_жд/railway-monitor/zissue.sh [ГГГГ-ММ]
# Новый выпуск партнёра: положить PDF в ~/railway-monitor/private/argus/ и запустить снова (повтор не дублирует).
set -u
REPO=~/zhd-repo; KIT=~/railway-monitor
echo "== 1. Обновление комплекта"
cd "$REPO" && git pull -q && cp информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/*.py \
  информация_по_жд/railway-monitor/*.sh информация_по_жд/railway-monitor/sources.json "$KIT"/ && \
  cp -r информация_по_жд/railway-monitor/miniapp "$KIT"/ && echo "ok"
cd "$KIT" || exit 1
python3 openclaw_setup.py sync >/dev/null && echo "правила ЖДуши обновлены"
python3 collector.py rescore >/dev/null 2>&1 && echo "архив новостей переразмечен (зерновозы, фитинги, море и порты)"
echo "== 2. База наблюдений из выпусков партнёра"
ls private/argus/*.pdf >/dev/null 2>&1 || { echo "СТОП: нет PDF в ~/railway-monitor/private/argus/"; exit 1; }
~/pw/bin/python zobs.py pdf private/argus/*.pdf
python3 zobs.py months
echo "== 3. Выпуск"
M=${1:+--month $1}
D=$(date +%F)
python3 zissue.py $M --out saved/market/${D}_обзор_рынка_вагонов.md && ~/pw/bin/python zreport.py saved/market/${D}_обзор_рынка_вагонов.md
python3 zissue.py $M --demo --out saved/market/${D}_обзор_рынка_вагонов_демо.md && ~/pw/bin/python zreport.py saved/market/${D}_обзор_рынка_вагонов_демо.md
echo "== 4. Прогнозы по типам вагонов (плитки «Рынок» и «Прогнозы» в мини-приложении)"
[ -f forecast/types_data.json ] || echo "!! нет forecast/types_data.json — зерновоз и платформа без рядов (команда cat > … из чата)"
for pair in kr158:krytye:крытый_158 kr138:krytye:крытый_138 hop_grain:zerno:зерновоз hop_grain_inno:zerno:зерновоз_инновационный \
            fit80:fiting:фитинговая_платформа_80 fit40:fiting:фитинговая_платформа_40 fit60:fiting:фитинговая_платформа_60; do
  w=${pair%%:*}; rest=${pair#*:}; sec=${rest%%:*}; nm=${rest#*:}
  mkdir -p saved/$sec
  f=saved/$sec/${D}_прогноз_ставки_$nm.md
  python3 ztypes.py run --wagon $w --out $f >/dev/null && ~/pw/bin/python zreport.py $f >/dev/null && echo "готово: $f" || echo "!! $w — не посчитано"
done
python3 zevents.py --days 30 --out saved/market/${D}_события_рынка.md && ~/pw/bin/python zreport.py saved/market/${D}_события_рынка.md >/dev/null
echo "== 5. Отправка владельцу"
for f in saved/market/${D}_обзор_рынка_вагонов.pdf saved/market/${D}_обзор_рынка_вагонов_демо.pdf saved/market/${D}_события_рынка.pdf; do
  [ -f "$f" ] && python3 send.py "$f" || echo "!! нет $f — выпуск не собрался, пришли вывод выше"
done
systemctl restart zhdusha-app 2>/dev/null && echo "мини-приложение перезапущено"
echo "== Готово. В ЖДуше: /new, затем «обзор рынка вагонов» или /prognoz (вагоны 1–10)"
