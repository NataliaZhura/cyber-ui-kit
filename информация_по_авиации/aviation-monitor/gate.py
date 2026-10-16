#!/usr/bin/env python3
"""Есть ли новые 🔴 для дневного сигнала — проверка без модели, чтобы не тратить лимит впустую.

  python3 gate.py [signal.md]      код выхода 0 — есть новые важные (балл ≥7), 1 — нет

Считает так же, как `collector.py export --from <вчера> --to <сегодня> --new --min-score 7 --out signal.md`:
публикации со вчерашнего дня, собранные после прошлого сигнала. Отметку не сдвигает — её сдвинет сам сигнал.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
MSK = timezone(timedelta(hours=3))
MIN_SCORE = 7


def mark_for(key):
    """Отметка прошлой выгрузки. Агент мог указать путь по-разному («signal.md», «~/aviation-monitor/signal.md») —
    берём самую позднюю из отметок с тем же именем файла."""
    path = BASE / "state.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    marks = [v for k, v in state.items() if k == key or Path(k).name == Path(key).name]
    return max(marks, default="")


def main():
    sys.path.insert(0, str(BASE))
    import collector
    key = sys.argv[1] if len(sys.argv) > 1 else "signal.md"
    today = datetime.now(MSK).date()
    n = collector.db().execute(
        "SELECT count(*) FROM news WHERE published >= ? AND published < ? AND score >= ? AND collected > ?",
        ((today - timedelta(days=1)).isoformat(), (today + timedelta(days=1)).isoformat(), MIN_SCORE,
         mark_for(key))).fetchone()[0]
    print(f"Новых важных (🔴) для сигнала: {n}")
    sys.exit(0 if n else 1)


if __name__ == "__main__":
    main()
