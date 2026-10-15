# Запуск ЖДуши на сервере рядом с «Ави»

Все команды — на сервере (PowerShell → `ssh avia`). «Ави» (`~/aviation-monitor`) не трогаем.

## 1. Забрать комплект из репозитория

```bash
cd ~ && git clone --depth 1 --branch claude/zhdusha-railway --filter=blob:none --sparse \
  https://github.com/NataliaZhura/cyber-ui-kit.git zhd-repo \
  && cd zhd-repo && git sparse-checkout set информация_по_жд \
  && cp -r информация_по_жд/railway-monitor ~/railway-monitor && ls ~/railway-monitor
```
Обновление позже: `cd ~/zhd-repo && git pull && cp информация_по_жд/railway-monitor/*.py информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/sources.json ~/railway-monitor/`

## 2. Секреты (в репозиторий не попадают)

- Токен бота: `~/.secrets/zhdusha_bot` — уже сохранён.
- Telegram ID владельца — тот же, что у «Ави»:
  ```bash
  openclaw config get channels.telegram.allowFrom
  ```
  Первое число из ответа (без `tg:`) записать: `echo <число> > ~/.secrets/zhdusha_owner && chmod 600 ~/.secrets/zhdusha_owner`

## 3. Закрытые файлы

- `~/railway-monitor/watchlist.csv` — список операторов (присылается в чате, формат — `watchlist_template.csv`).
- Выпуски Argus — в `~/railway-monitor/private/argus/`. С компьютера (PowerShell, не на сервере):
  ```powershell
  ssh avia "mkdir -p ~/railway-monitor/private/argus"
  scp "C:\путь\к\выпуску.pdf" avia:~/railway-monitor/private/argus/
  ```

## 4. Проверить источники и собрать первые новости

```bash
cd ~/railway-monitor
python3 collector.py check          # что открывается с сервера; нерабочее — убрать из sources.json
python3 collector.py collect --days 3 --all
python3 collector.py stats
```

## 5. Второй агент и второй бот в OpenClaw

```bash
cd ~/railway-monitor
python3 openclaw_setup.py plan     # только показывает изменения
python3 openclaw_setup.py apply    # копия настроек → агент zhdusha → бот → правило; в конце — команда перезапуска
# выполнить подсказанную команду перезапуска, подождать 30 секунд
python3 openclaw_setup.py check    # агенты, правила, состояние ботов
```
Проверка: `/start` в @zhdusha_bot → отвечает ЖДуша; `/start` в @marketMi_bot → по-прежнему Ави.
Если что-то не так: `python3 openclaw_setup.py undo` и перезапуск — всё как было.

## 6. Расписания (агент ЖДуши, доставка через @zhdusha_bot)

- 08:45 ежедневно — утренняя справка
- после сбора — сигналы 🔴
- понедельник 09:00 — итоги недели

## Проверка готовности

- [ ] `collector.py check` — работает большинство источников
- [ ] `collector.py stats` показывает новости
- [ ] `/start` в @zhdusha_bot → приветствие ЖДуши; `/start` в @marketMi_bot → по-прежнему Ави
- [ ] `python3 send.py SOUL.md` → файл пришёл от @zhdusha_bot
- [ ] утром в 08:45 справка пришла сама; `free -h` — памяти хватает
