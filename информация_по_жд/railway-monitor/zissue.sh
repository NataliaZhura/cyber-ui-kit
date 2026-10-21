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
# выпуски читаются при загрузке (zinbox.py); перечитать все заново (5–10 минут) — FULL=1 bash zissue.sh
[ "${FULL:-0}" = 1 ] && ~/pw/bin/python zobs.py pdf private/argus/*.pdf
~/pw/bin/python zinbox.py >/dev/null 2>&1   # то, что лежит в «Мои загрузки», — разложить
python3 zobs.py months
echo "== 3. Выпуск"
M=${1:+--month $1}
D=$(date +%F)
python3 zissue.py $M --out saved/market/${D}_обзор_рынка_вагонов.md && ~/pw/bin/python zreport.py saved/market/${D}_обзор_рынка_вагонов.md
python3 zissue.py $M --demo --out saved/market/${D}_обзор_рынка_вагонов_демо.md && ~/pw/bin/python zreport.py saved/market/${D}_обзор_рынка_вагонов_демо.md
echo "== 4. Отчёты по типам вагонов: ставка, факторы, стоимость, сделка и выход (полки «Рынок» в мини-приложении)"
[ -f forecast/types_data.json ] || echo "!! нет forecast/types_data.json — зерновоз и платформа без рядов (команда cat > … из чата)"
for w in inno gon kr158 kr138 hop_grain hop_grain_inno fit80 fit40 fit60; do
  out=$(python3 zreports.py $w all 2>&1 | sed -n 's/^Файл: //p')
  if [ -n "$out" ]; then for f in $out; do ~/pw/bin/python zreport.py $f >/dev/null; done; echo "готово: $w (отчётов: $(echo $out | wc -w))"
  else echo "!! $w — отчёты не собрались: python3 zreports.py $w all"; fi
done
python3 zevents.py --days 30 --out saved/market/${D}_события_рынка.md && ~/pw/bin/python zreport.py saved/market/${D}_события_рынка.md >/dev/null
echo "== 4б. Журнал «прогноз — факт», сверка рядов, оповещения"
python3 zrates.py snap
python3 ztypes.py check
python3 zretro.py test all
python3 zrates.py score | sed -n '1,4p;/^| Тип/,/^$/p'
python3 zrates.py alerts --send
echo "== 5. Отправка владельцу"
for f in saved/market/${D}_обзор_рынка_вагонов.pdf saved/market/${D}_обзор_рынка_вагонов_демо.pdf saved/market/${D}_события_рынка.pdf; do
  [ -f "$f" ] && python3 send.py "$f" || echo "!! нет $f — выпуск не собрался, пришли вывод выше"
done
systemctl restart zhdusha-app 2>/dev/null && echo "мини-приложение перезапущено"
echo "== Готово. Пульт с кнопками (один раз): python3 zmenu.py panel — прогнозы, ставки, сделка без нейросети"
