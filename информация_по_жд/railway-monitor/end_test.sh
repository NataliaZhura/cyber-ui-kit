#!/usr/bin/env bash
# Конец теста (вечер 17.10 или позже): отзывы на экран, тестовые рассылки выключить (не удалить), доступ отключить.
#   bash ~/railway-monitor/end_test.sh
set -u
echo "== Отзывы"
for f in ~/aviation-monitor/saved_tester/feedback.md ~/railway-monitor/saved_zguest/feedback.md; do
  echo "--- $f"; cat "$f" 2>/dev/null || echo "(пусто)"
done
echo "== Что пробовали (журнал Ави)"; tail -20 ~/aviation-monitor/saved_tester/activity.log 2>/dev/null
echo "== Выключаю рассылки «Тест:», «Влад:», «Гость ЖД:»"
openclaw automations list 2>/dev/null | grep -E "Тест:|Влад:|Гость ЖД:" | awk '{print $1}' |
while read -r jid; do openclaw automations disable "$jid" >/dev/null && echo "выключена: $jid"; done
echo "== Отключаю доступ (папки и архивы остаются)"
(cd ~/aviation-monitor && python3 tester/connect.py 328083444 --off)
(cd ~/railway-monitor && python3 zguest.py off 207215298 zguest)
systemctl --user restart openclaw-gateway && sleep 30 && echo "перезапущено"
openclaw agents list --bindings 2>/dev/null | grep -E "peer="
echo "== Готово: в привязках выше не должно быть 328083444 и 207215298."
