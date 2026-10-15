#!/usr/bin/env bash
# Ночной перезапуск OpenClaw в 04:00 МСК (очистка памяти). Данные не трогает: разговоры, память агентов, справки,
# архив новостей и настройки лежат на диске и остаются. Перед каждым перезапуском — копия openclaw.json
# (7 штук по дням недели, ~/.openclaw/backups/). Меню ботов ставится само после перезапуска.
#   bash ~/railway-monitor/nightly.sh          включить        bash ~/railway-monitor/nightly.sh off   выключить
set -eu
U=~/.config/systemd/user
if [ "${1:-}" = off ]; then
  systemctl --user disable --now openclaw-nightly.timer && echo "ночной перезапуск выключен"; exit 0
fi
mkdir -p "$U" ~/.openclaw/backups
cat > "$U/openclaw-nightly.service" <<'S'
[Unit]
Description=Ночной перезапуск OpenClaw (очистка памяти)

[Service]
Type=oneshot
ExecStartPre=/bin/sh -c 'cp %h/.openclaw/openclaw.json %h/.openclaw/backups/openclaw.json.$(date +%%a)'
ExecStart=/usr/bin/systemctl --user restart openclaw-gateway.service
ExecStartPost=/bin/sh -c 'echo "$(date "+%%F %%T") перезапуск" >> %h/.openclaw/backups/nightly.log'
S
cat > "$U/openclaw-nightly.timer" <<'S'
[Unit]
Description=Каждый день в 04:00 по Москве

[Timer]
OnCalendar=*-*-* 04:00:00 Europe/Moscow
Persistent=false

[Install]
WantedBy=timers.target
S
systemctl --user daemon-reload
systemctl --user enable --now openclaw-nightly.timer
echo "== Включено. Следующий запуск:"
systemctl --user list-timers openclaw-nightly.timer --no-pager | head -2
