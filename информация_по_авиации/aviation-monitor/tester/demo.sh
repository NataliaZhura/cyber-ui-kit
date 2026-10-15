#!/usr/bin/env bash
# Перевести «возможность дня» тестового пользователя на справки в PDF (правило AGENTS.md «Как отдавать справку»).
#   bash tester/demo.sh <TELEGRAM_ID_тестировщика>
set -euo pipefail
ID="${1:?Укажи Telegram ID тестировщика}"
[[ "$ID" =~ ^[0-9]{5,15}$ ]] || { echo "ID должен быть числом"; exit 1; }
cd ~/aviation-monitor
D1="Возможность дня 1 — покажи сам, без запроса. Сделай справку по Аэрофлоту (ИНН 7712040126) по правилам AGENTS.md, раздел «Как отдавать справку»: файл .md в ~/aviation-monitor/saved_tester/ с плашкой класса, карточками цифр и графиками, затем PDF: ~/pw/bin/python ~/aviation-monitor/share.py report <файл.md> $ID и копия владельцу: python3 ~/aviation-monitor/share.py tg owner <тот же .pdf>. В чате — до 5 строк, первая: «Возможность дня: справка по компании в PDF. Такую же можно получить по любой компании через /profile»."
D2="Возможность дня 2 — покажи сам, без запроса. 1) Сравни Аэрофлот (ИНН 7712040126) и ЮТэйр по правилам AGENTS.md (как /compare): PDF через ~/pw/bin/python ~/aviation-monitor/share.py report <файл.md> $ID — карточки и графики обеих компаний рядом, копия владельцу: python3 ~/aviation-monitor/share.py tg owner <тот же .pdf>. 2) Проверь демо-модель ~/aviation-monitor/excel_tester/in/demo_model.xlsx по навыкам excel и model-stress: ошибки в файле, поток для обслуживания долга, DSCR и DCR по годам, стресс-сценарии, где модель пробивает; Excel с расчётом — в ~/aviation-monitor/excel_tester/out/ и отправь: python3 ~/aviation-monitor/share.py tg $ID <файл> (и копию владельцу: share.py tg owner <файл>). В чате — до 8 строк, первая: «Возможность дня: сравнение компаний и стресс-тест модели. Свою модель в Excel можно прислать в любой момент»."
for pair in "1|$D1" "2|$D2"; do
  n="Тест: возможность дня ${pair%%|*}"; m="${pair#*|}"
  JID=$(openclaw automations list --json | python3 automation_id.py "$n")
  openclaw automations edit "$JID" --message "$m" >/dev/null && echo "обновлено: $n"
done
