#!/usr/bin/env bash
# Проверка всей цепочки ЖДуши и мини-приложения — ТОЛЬКО ЧТЕНИЕ, ничего не меняет, токены не выводит.
#   bash ~/railway-monitor/zcheck.sh [адрес]      (адрес по умолчанию — zhdusha.duckdns.org)
set -u
HOST=${1:-zhdusha.duckdns.org}; KIT=~/railway-monitor; S=~/.secrets; GID=207215298
ok() { echo "  ОК        $*"; }; bad() { echo "  ПРОБЛЕМА  $*"; }
chk() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }

echo "== 1. Секреты (только наличие)"
for f in zhdusha_bot zhdusha_owner; do chk "~/.secrets/$f" "[ -s $S/$f ]"; done

echo "== 2. OpenClaw"
chk "шлюз openclaw-gateway работает" "systemctl --user is-active openclaw-gateway || pgrep -f openclaw-gateway"
AG=$(openclaw agents list --bindings 2>/dev/null)
chk "агент zhdusha есть" "grep -q zhdusha <<<\"\$AG\""
chk "агент zguest (Анастасия) есть" "grep -q zguest <<<\"\$AG\""
chk "маршрут Анастасии $GID → zguest" "grep -q $GID <<<\"\$AG\""
ALLOW=$(openclaw config get channels.telegram.accounts.zhdusha.allowFrom 2>/dev/null)
chk "Анастасии разрешён @zhdusha_bot" "grep -q $GID <<<\"\$ALLOW\""
chk "openclaw agent умеет --reply-account" "openclaw agent --help 2>&1 | grep -q -- --reply-account"
echo "  расписания ЖДуши:"; openclaw automations list 2>/dev/null | grep -E '"name"|"enabled"|"schedule"|ЖД' | grep -E "ЖД|Гость" | sed 's/^/    /' | head -20

echo "== 3. Мини-приложение"
chk "служба zhdusha-app работает" "systemctl is-active zhdusha-app"
chk "Caddy работает" "systemctl is-active caddy"
chk "страница изнутри (127.0.0.1:8787)" "[ \$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/) = 200 ]"
chk "страница снаружи https://$HOST" "[ \$(curl -s -o /dev/null -w '%{http_code}' https://$HOST/) = 200 ]"
END=$(echo | openssl s_client -connect "$HOST:443" -servername "$HOST" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
[ -n "$END" ] && ok "сертификат HTTPS до $END" || bad "сертификат HTTPS не прочитан"
chk "без подписи Telegram — отказ (403)" "[ \$(curl -s -o /dev/null -w '%{http_code}' https://$HOST/api/list) = 403 ]"
chk "miniapp.json (прямая отправка задач)" "[ -s $KIT/miniapp.json ]"
chk "файлы приложения совпадают с репозиторием" "diff -q ~/zhd-repo/информация_по_жд/railway-monitor/zapp.py $KIT/zapp.py && diff -q ~/zhd-repo/информация_по_жд/railway-monitor/miniapp/index.html $KIT/miniapp/index.html"
cd "$KIT" && python3 - "$GID" <<'PY'
import sys, zapp
gid = sys.argv[1]
r = zapp.who(gid)
print(f"  {'ОК        ' if r and r[0] == 'guest' else 'ПРОБЛЕМА  '}приложение узнаёт Анастасию как гостя"
      + (f" (агент {r[1]}, папка {r[3].name})" if r else ""))
o = zapp.who(zapp.secret("zhdusha_owner"))
print(f"  {'ОК        ' if o and o[0] == 'owner' else 'ПРОБЛЕМА  '}приложение узнаёт владельца")
for who, acc in (("владелец", o), ("Анастасия", r)):
    if acc:
        n = {k: len(v) for k, v in zapp.listing(acc[2]).items() if v}
        print(f"    {who}: отчётов {sum(n.values())} — " + ", ".join(f"{k} {v}" for k, v in n.items()))
PY

echo "== 4. Telegram (кнопка «Меню»)"
python3 - "$GID" <<'PY'
import json, sys, urllib.parse, urllib.request
from pathlib import Path
tok = (Path.home() / ".secrets" / "zhdusha_bot").read_text().strip()
own = (Path.home() / ".secrets" / "zhdusha_owner").read_text().strip()
def api(m, **p):
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{m}", data=urllib.parse.urlencode(p).encode())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())
me = api("getMe")["result"]
print(f"  ОК        бот @{me['username']}")
for who, cid in (("общая", None), ("владелец", own), ("Анастасия", sys.argv[1])):
    b = api("getChatMenuButton", **({"chat_id": cid} if cid else {}))["result"]
    url = b.get("web_app", {}).get("url", "")
    print(f"  {'ОК        ' if b.get('type') == 'web_app' else 'ПРОБЛЕМА  '}кнопка «Меню» ({who}): {b.get('type')} {url}")
PY

echo "== 5. Журналы (последние строки)"
echo "  задачи из приложения (saved/task.log):"; tail -n 6 "$KIT/saved/task.log" 2>/dev/null | sed 's/^/    /' || echo "    пусто"
echo "  ошибки приложения за сутки:"; journalctl -u zhdusha-app --since "-24h" --no-pager 2>/dev/null | grep -i -E "error|traceback|exception" | tail -5 | sed 's/^/    /'
echo "== Готово. Строки «ПРОБЛЕМА» — пришли в разговор «Мини-приложение»."
