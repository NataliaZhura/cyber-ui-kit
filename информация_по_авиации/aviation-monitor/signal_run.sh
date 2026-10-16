#!/usr/bin/env bash
# Дневной сигнал без пустых запусков модели: сбор → проверка gate.py → задача-сигнал, только если есть новые 🔴.
#   bash signal_run.sh <ID задачи «сигналы» владельца>
# Запускается расписанием-командой OpenClaw вместо прежнего расписания самой задачи (см. STATUS.md, п. 14).
set -u
JOB="${1:?Укажи ID задачи-сигнала: bash signal_run.sh <ID>}"
cd ~/aviation-monitor || exit 1
python3 collector.py collect --days 2 >/dev/null 2>&1
if python3 gate.py signal.md; then
  openclaw automations run "$JOB"
fi
