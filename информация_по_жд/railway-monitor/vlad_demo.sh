#!/usr/bin/env bash
# Демонстрация Ави для Владислава на 16–17.10 (как у первого тестировщика, сдвинуто под его два дня).
# Старые демо-рассылки «Тест: …» (экскурсия, возможности дня, напоминания, итоги) — выключаются, не удаляются.
# Утренняя справка и сигналы «Тест: …» остаются. Повторный запуск не создаёт дублей.
#   bash ~/railway-monitor/vlad_demo.sh
set -u
ID=328083444; AM=~/aviation-monitor
cd "$AM" || exit 1

echo "== 1. Выключаю старые демо-рассылки"
openclaw automations list --json 2>/dev/null | python3 -c '
import json, re, sys
t = sys.stdin.read(); s = [i for i in (t.find("{"), t.find("[")) if i >= 0]
def walk(o):
    if isinstance(o, dict):
        if "id" in o and "name" in o: yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
for j in walk(json.loads(t[min(s):]) if s else []):
    if j["name"].startswith("Тест:") and re.search("экскурс|возможност|напомин|итог", j["name"], re.I):
        print(j["id"] + "\t" + j["name"])' | while IFS=$'\t' read -r jid name; do
  openclaw automations disable "$jid" >/dev/null && echo "выключена: $name"
done

echo "== 2. Файлы для экскурсии"
mkdir -p excel_tester/in excel_tester/out saved_tester/copy
[ -f excel_tester/in/demo_model.xlsx ] || cp demo/demo_model.xlsx excel_tester/in/
if [ ! -f demo/Ави_что_умеет.pdf ]; then
  cp demo/guide.md demo/Ави_что_умеет.md && ~/pw/bin/python share.py convert demo/Ави_что_умеет.md >/dev/null
fi
ls -la demo/Ави_что_умеет.pdf excel_tester/in/demo_model.xlsx | awk '{print $5, $9}'

echo "== 3. Новые рассылки Владиславу"
LIST=$(openclaw automations list 2>/dev/null)
add() {  # add "<название>" "<мин> <час> <день> <мес> *" "<текст>"
  if grep -qF "$1" <<<"$LIST"; then echo "уже есть: $1"; return; fi
  openclaw automations create "$2" "$3" --name "$1" --tz Europe/Moscow --agent tester --session isolated \
    --announce --channel telegram --to "$ID" | grep -E '"name"|"nextRunAtMs"' | head -2
}
TOUR="Экскурсия по Ави: пользователь — потенциальный клиент, первый день теста. Одним сообщением, не длиннее 6 строк: коротко поздоровайся, скажи, что Ави — аналитик авиарынка по открытым источникам, что памятка со всеми возможностями — в PDF ниже, и предложи начать с /profile → Аэрофлот или «проверь демо-модель». Затем отправь файлы: python3 ~/aviation-monitor/share.py tg $ID ~/aviation-monitor/demo/Ави_что_умеет.pdf ~/aviation-monitor/excel_tester/in/demo_model.xlsx"
D1="Возможность дня 1 — покажи сам, без запроса. Сделай справку по Аэрофлоту (ИНН 7712040126) по правилам AGENTS.md, раздел «Как отдавать справку»: файл .md в ~/aviation-monitor/saved_tester/ с плашкой класса, карточками цифр и графиками, затем PDF: ~/pw/bin/python ~/aviation-monitor/share.py report <файл.md> $ID и копия владельцу: python3 ~/aviation-monitor/share.py tg owner <тот же .pdf>. В чате — до 5 строк, первая: «Возможность дня: справка по компании в PDF. Такую же можно получить по любой компании через /profile»."
D2="Возможность дня 2 — покажи сам, без запроса. 1) Сравни Аэрофлот (ИНН 7712040126) и ЮТэйр по правилам AGENTS.md (как /compare): PDF через ~/pw/bin/python ~/aviation-monitor/share.py report <файл.md> $ID — карточки и графики обеих компаний рядом, копия владельцу: python3 ~/aviation-monitor/share.py tg owner <тот же .pdf>. 2) Проверь демо-модель ~/aviation-monitor/excel_tester/in/demo_model.xlsx по навыкам excel и model-stress: ошибки в файле, поток для обслуживания долга, DSCR и DCR по годам, стресс-сценарии, где модель пробивает; Excel с расчётом — в ~/aviation-monitor/excel_tester/out/ и отправь: python3 ~/aviation-monitor/share.py tg $ID <файл> (и копию владельцу: share.py tg owner <файл>). В чате — до 8 строк, первая: «Возможность дня: сравнение компаний и стресс-тест модели. Свою модель в Excel можно прислать в любой момент»."
REM='Мягкое вечернее напоминание пользователю (он тестирует Ави, потенциальный клиент). Прочитай ~/aviation-monitor/saved_tester/activity.log — что он уже пробовал. Если сегодня запросов не было: 2–3 дружелюбные строки — Ави на связи, и ОДНА конкретная возможность, которую он ещё не пробовал, с готовым примером (например: /compare → Аэрофлот и ЮТэйр; «проверь демо-модель»; /finance → Победа; /market → за неделю). Если сегодня запросы были: одна строка благодарности и одна новая возможность. Без давления и восклицательных знаков, не длиннее 400 знаков, без списков.'
FB='Последний день теста Ави. Прочитай ~/aviation-monitor/saved_tester/activity.log — что пользователь пробовал. Одним сообщением, не длиннее 8 строк, без давления: поблагодари за два дня теста и задай три коротких вопроса для отзыва, пронумеруй их: 1) что оказалось самым полезным; 2) чего не хватило или что было неудобно; 3) пользовался бы он Ави в работе и для каких задач. Скажи, что можно ответить прямо здесь, в свободной форме. Его ответы сохрани дословно с датой в ~/aviation-monitor/saved_tester/feedback.md (дописывай, не перезаписывай).'
add "Влад: экскурсия 16.10"      "30 11 16 10 *" "$TOUR"
add "Влад: возможность дня 1"    "30 14 16 10 *" "$D1"
add "Влад: напоминание 16.10"    "30 18 16 10 *" "$REM"
add "Влад: возможность дня 2"    "30 14 17 10 *" "$D2"
add "Влад: вопросы для отзыва"   "30 18 17 10 *" "$FB"

echo "== 4. Что придёт Владиславу (включённые)"
openclaw automations list 2>/dev/null | grep -E "Тест:|Влад:" | grep -v -i disabled
echo "== Готово. После 17.10: выключить «Тест:» и «Влад:», отключить доступ — python3 tester/connect.py $ID --off"
