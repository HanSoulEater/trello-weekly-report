# trello_weekly_report_to_telegram.py
# Запускается еженедельно. Берёт из Trello выполненные чек-пункты за прошлую неделю и шлёт отчёт в Telegram.
# Читает настройки из переменных окружения (см. GitHub Actions Secrets).

import os
import requests
import datetime
import pytz
import textwrap
from collections import defaultdict

# === Обязательные переменные окружения ===
def need(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"ENV {name} is required")
    return v

TRELLO_KEY   = need("TRELLO_KEY")
TRELLO_TOKEN = need("TRELLO_TOKEN")
BOARD_ID     = need("BOARD_ID")          # Например: 4CCbpXkF (shortLink из URL борда)
TG_TOKEN     = need("TG_TOKEN")
TG_CHAT_ID   = need("TG_CHAT_ID")        # Числовой chat_id
TZ_NAME      = os.getenv("TZ_NAME", "Europe/Moscow")  # По умолчанию Москва

# === Даты прошедшей недели (понедельник-воскресенье) в указанном часовом поясе ===
tz = pytz.timezone(TZ_NAME)
now = datetime.datetime.now(tz)
monday_this_week = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
start = monday_this_week - datetime.timedelta(days=7)
end   = monday_this_week  # не включительно

def to_utc_iso(dt: datetime.datetime) -> str:
    return dt.astimezone(pytz.UTC).isoformat()

SINCE  = to_utc_iso(start)
BEFORE = to_utc_iso(end)

def fmt_local(iso_str: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z","+00:00")).astimezone(tz)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str

def get_actions():
    url = f"https://api.trello.com/1/boards/{BOARD_ID}/actions"
    params = {
        "key": TRELLO_KEY,
        "token": TRELLO_TOKEN,
        "filter": "updateCheckItemStateOnCard",
        "limit": 1000,
        "since": SINCE,
        "before": BEFORE
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def build_report(actions):
    # cardId -> list[(date, itemName)]
    by_card = defaultdict(list)
    card_meta = {}  # cardId -> (name, url)
    for a in actions:
        if not isinstance(a, dict):
            continue
        data = a.get("data", {})
        ci = data.get("checkItem", {})
        if ci.get("state") != "complete":
            continue
        item_name = ci.get("name", "")
        card      = data.get("card", {}) or {}
        card_id   = card.get("id")
        card_name = card.get("name", "Без названия")
        short     = card.get("shortLink", "")
        card_url  = f"https://trello.com/c/{short}" if short else ""
        by_card[card_id].append((a.get("date"), item_name))
        card_meta[card_id] = (card_name, card_url)

    title = f"Отчёт по выполненным чек-пунктам: {start.strftime('%Y-%m-%d')} — {(end - datetime.timedelta(days=1)).strftime('%Y-%m-%d')}"
    if not by_card:
        return title, "За указанную неделю выполненных пунктов не найдено."

    # Сборка текста
    lines = []
    # сортируем карточки по имени
    for card_id in sorted(by_card.keys(), key=lambda cid: (card_meta[cid][0] or "").lower()):
        card_name, card_url = card_meta[card_id]
        lines.append(f'🔹 <a href="{card_url}">{card_name}</a>')
        for dt_iso, item in sorted(by_card[card_id], key=lambda x: x[0] or ""):
            lines.append(f" — {fmt_local(dt_iso)} — {item}")
        lines.append("")  # разделитель

    body = "\n".join(lines).strip()
    return title, body

def tg_send_html(token: str, chat_id: str, text: str):
    # Telegram ограничение ~4096 символов; режем на блоки
    for chunk in textwrap.wrap(text, width=3500, replace_whitespace=False, drop_whitespace=False):
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=30
        )
        resp.raise_for_status()

def main():
    # sanity: бот должен быть запущен пользователем (/start), иначе сообщения не дойдут
    actions = get_actions()
    title, body = build_report(actions)
    tg_send_html(TG_TOKEN, TG_CHAT_ID, f"<b>{title}</b>")
    tg_send_html(TG_TOKEN, TG_CHAT_ID, body)
    print("OK")

if __name__ == "__main__":
    main()
