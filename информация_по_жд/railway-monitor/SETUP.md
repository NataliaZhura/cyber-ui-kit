# Запуск ЖДуши на сервере рядом с «Ави»

Все команды — на сервере (PowerShell → `ssh avia`). «Ави» (`~/aviation-monitor`) не трогаем.

## 1. Забрать комплект из репозитория

```bash
cd ~ && git clone --depth 1 --branch claude/zhdusha-railway --filter=blob:none --sparse \
  https://github.com/NataliaZhura/cyber-ui-kit.git zhd-repo \
  && cd zhd-repo && git sparse-checkout set информация_по_жд \
  && cp -r информация_по_жд/railway-monitor ~/railway-monitor && ls ~/railway-monitor
```
Обновление позже: `cd ~/zhd-repo && git pull && cp информация_по_жд/railway-monitor/*.py информация_по_жд/railway-monitor/*.md информация_по_жд/railway-monitor/sources.json ~/railway-monitor/ && cp -r информация_по_жд/railway-monitor/miniapp ~/railway-monitor/`

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

Сначала проверить, какие параметры есть у команды в этой версии OpenClaw:
```bash
openclaw automations create --help | grep -i -E "agent|account|channel|command"
```
Затем (параметры `--agent` и `--account` — по выводу выше):
```bash
# сбор новостей каждые 3 часа
openclaw automations create "20 */3 * * *" --name "ЖД: сбор" --tz "Europe/Moscow" \
  --command "python3 collector.py collect --days 3" --command-cwd "$HOME/railway-monitor"
# утренние новости 08:45
openclaw automations create "45 8 * * *" \
  "Подготовь утренние новости за вчера по AGENTS.md и TEMPLATE.md. Сначала: python3 ~/railway-monitor/collector.py collect --days 2" \
  --name "ЖД: утренние новости" --tz "Europe/Moscow" --agent zhdusha \
  --session isolated --announce --channel telegram --account zhdusha --to "<ID владельца>"
# прогноз на неделю — пятница 17:00; сверка — понедельник 09:00 (тот же вид команды, свой текст задания)
```

## 7. Мини-приложение (отчёты по разделам)

Что это: кнопка «Меню» в @zhdusha_bot открывает окно с разделами (как пункты меню), в каждом — готовые отчёты.
Просмотр — без нейросети. Команды бота остаются: их список появляется, если набрать «/». Описание — `MINIAPP.md`.

**7.1. Адрес (один раз, в браузере).** duckdns.org → войти (Google/GitHub) → придумать имя, например `zhdusha` →
в поле «current ip» — IP сервера (`curl -4 ifconfig.me` на сервере) → «update ip». Адрес: `https://zhdusha.duckdns.org`.
Свой домен вместо этого: A-запись поддомена (например, `zhd.твойдомен.ru`) → IP сервера; дальше всё так же.

**7.2. Проверить, что порты 80, 443 и 8787 свободны и Caddy ещё не стоит** (только чтение):
```bash
cat /etc/os-release | head -2; sudo ss -ltnp | grep -E ':(80|443|8787) '; which caddy
```
Если порты кем-то заняты или Caddy уже есть — остановиться и прислать вывод, Caddyfile не трогать.

**7.3. Caddy — HTTPS-сертификат сам** (Ubuntu/Debian, официальная инструкция caddyserver.com/docs/install):
```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak      # копия приветственной страницы Caddy
printf 'zhdusha.duckdns.org {\n\treverse_proxy 127.0.0.1:8787\n}\n' | sudo tee /etc/caddy/Caddyfile
sudo systemctl reload caddy
```
Если включён ufw: `sudo ufw allow 80,443/tcp`.

**7.4. Программа приложения — постоянно, с автозапуском:**
```bash
sudo tee /etc/systemd/system/zhdusha-app.service >/dev/null <<UNIT
[Unit]
Description=ZhDusha mini app
After=network.target
[Service]
User=$USER
WorkingDirectory=$HOME/railway-monitor
ExecStart=/usr/bin/python3 $HOME/railway-monitor/zapp.py serve
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now zhdusha-app
systemctl status zhdusha-app --no-pager | head -5
```
Проверка: `https://zhdusha.duckdns.org` в браузере → «Открой приложение кнопкой «Меню»…» — значит, работает
(вне Telegram отчёты не показываются).

**7.5. Кнопка «Меню» → приложение:** `python3 ~/railway-monitor/zmenu.py webapp https://zhdusha.duckdns.org`.
Вернуть как было (кнопка со списком команд): `python3 ~/railway-monitor/zmenu.py`.

**7.6. Разложить старые отчёты по разделам:** `python3 zapp.py sort` — только показывает, что куда ляжет.
Если всё верно — `python3 zapp.py sort --apply` (файлы переносятся в подпапки `saved/`, ничего не удаляется).

**7.7. Кнопка «Поставить задачу»** (только чтение): `python3 zapp.py check`. Пока не настроено — кнопка копирует
текст, его вставляют в чат. Если `check` пишет «Подходит» — прислать вывод в разговор «Мини-приложение»,
там соберём `miniapp.json` для отправки задач напрямую.

## Проверка готовности

- [ ] `collector.py check` — работает большинство источников
- [ ] `collector.py stats` показывает новости
- [ ] `/start` в @zhdusha_bot → приветствие ЖДуши; `/start` в @marketMi_bot → по-прежнему Ави
- [ ] `python3 send.py SOUL.md` → файл пришёл от @zhdusha_bot
- [ ] утром в 08:45 справка пришла сама; `free -h` — памяти хватает
- [ ] «Меню» в @zhdusha_bot открывает разделы; «В чат» присылает PDF; гость видит только свои отчёты
