# -*- coding: utf-8 -*-
import os
import time
import json
import itertools
import traceback
from threading import Thread, Lock
from typing import Optional, Dict, List

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# Playwright (синхронный)
from playwright.sync_api import sync_playwright, Browser, Page

# ================== 1. НАСТРОЙКИ И АВТОРИЗАЦИЯ ==================
BOT_TOKEN = "8240195944:AAEQFd2met5meCU1uwu5PvPejJoiKu94cms"

ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]

BASE_URL = "https://crm431241.ru"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
API_BASE = "https://crm431241.ru"
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = "#username"
PASSWORD_SELECTOR = "#password"
SIGN_IN_BUTTON_SELECTOR = "button[type='submit']"

TOKENS_FILE = "tokens.json"
TOKENS_LOCK = Lock()

# ================== 2. АККАУНТЫ ==================
accounts = [
    {"username": "blue6", "password": "33dff63d"},
    {"username": "blue7", "password": "842dfghm"},
    {"username": "blue8", "password": "89df45bg"},
    {"username": "blue9", "password": "3363f44d"},
    {"username": "pink5", "password": "ugsdf413"},
    {"username": "pink6", "password": "851hjk74"},
    {"username": "pink7", "password": "85tg24vd"},
    {"username": "pink8", "password": "14gh1223"},
    {"username": "pink9", "password": "845ghj65"},
]

# ================== 3. ПУЛ ТОКЕНОВ ==================
# Каждый элемент:
# {
#   "username": "...",
#   "cookie_header": "name=val; name2=val2",
#   "user_agent": "...",
#   "time": 1234567890  # last refreshed timestamp
# }
token_pool: List[Dict] = []
token_cycle = None

# Helper to read/write tokens.json atomically
def load_tokens_from_file() -> List[Dict]:
    global token_pool, token_cycle
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    token_pool = data
                    token_cycle = itertools.cycle(token_pool) if token_pool else None
                    print(f"[TOKENS] 🔁 Загружено {len(token_pool)} токенов из {TOKENS_FILE}.")
                    return token_pool
    except Exception as e:
        print(f"[TOKENS ERROR] Не удалось загрузить {TOKENS_FILE}: {e}")
        traceback.print_exc()
    token_pool = []
    token_cycle = None
    return []

def save_tokens_to_file():
    global token_pool
    try:
        with TOKENS_LOCK:
            tmp = TOKENS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(token_pool, f, ensure_ascii=False, indent=2)
            os.replace(tmp, TOKENS_FILE)
            print(f"[TOKENS] 💾 Сохранено {len(token_pool)} токенов в {TOKENS_FILE}.")
    except Exception as e:
        print(f"[TOKENS ERROR] Ошибка сохранения токенов: {e}")
        traceback.print_exc()

# ================== 4. PLAYWRIGHT LOGIN (extract cookies) ==================
def login_crm_playwright(username: str, password: str, p, show_browser: bool = False) -> Optional[Dict]:
    """
    Авторизация через Playwright, возвращает словарь токена или None.
    show_browser=True — используйте локально для отладки, в Render оставлять False.
    """
    browser: Optional[Browser] = None
    try:
        print(f"[PLW] 🔵 Вход через браузер под {username}...")
        browser = p.chromium.launch(
            headless=not show_browser,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-features=site-per-process,Translate,BlinkGenPropertyTrees"
            ],
            timeout=60000
        )
        context = browser.new_context()
        page: Page = context.new_page()
        page.set_default_timeout(30000)

        page.goto(LOGIN_PAGE, wait_until="load", timeout=30000)

        # Имитируем ввод, как человек
        page.fill(LOGIN_SELECTOR, username)
        time.sleep(0.4)
        page.fill(PASSWORD_SELECTOR, password)
        time.sleep(0.4)
        page.click(SIGN_IN_BUTTON_SELECTOR)

        # Немного подождём редиректа
        try:
            page.wait_for_url("**/dashboard**", timeout=10000)
        except Exception:
            time.sleep(2)

        # Собираем cookies и UA
        cookies = context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        user_agent = page.evaluate("() => navigator.userAgent")

        # Попытка по ключевым именам cookie найти access/csrf
        access_cookie = next((c["value"] for c in cookies if "access" in c["name"].lower() and "token" in c["name"].lower()), None)
        csrf_cookie = next((c["value"] for c in cookies if "csrf" in c["name"].lower()), None)

        # fallback: localStorage/sessionStorage
        if not access_cookie or not csrf_cookie:
            try:
                ls = page.evaluate("() => Object.assign({}, window.localStorage)")
                for k, v in ls.items():
                    kl = k.lower()
                    if ("access" in kl and "token" in kl) and not access_cookie:
                        access_cookie = v
                    if ("csrf" in kl) and not csrf_cookie:
                        csrf_cookie = v
            except Exception:
                pass

            try:
                ss = page.evaluate("() => Object.assign({}, window.sessionStorage)")
                for k, v in ss.items():
                    kl = k.lower()
                    if ("access" in kl and "token" in kl) and not access_cookie:
                        access_cookie = v
                    if ("csrf" in kl) and not csrf_cookie:
                        csrf_cookie = v
            except Exception:
                pass

        # Если cookie есть — формируем объект токена и возвращаем
        if cookie_header:
            token = {
                "username": username,
                "cookie_header": cookie_header,
                "user_agent": user_agent,
                "time": int(time.time())
            }
            print(f"[PLW] ✅ {username} успешно авторизован, куки получены.")
            return token
        else:
            print(f"[PLW] ⚠️ {username}: не удалось получить куки.")
            return None

    except Exception as e:
        print(f"[PLW ERROR] {username}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None
    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass

# ================== 5. ИНИЦИАЛИЗАЦИЯ ПУЛА (playwright-driven) ==================
def init_token_pool_playwright(show_browser: bool = False):
    """
    Логин по всем учёткам и заполнение token_pool.
    Если есть tokens.json — сначала загрузим его (чтобы не делать логин каждый старт).
    """
    global token_pool, token_cycle
    # Попытка загрузить с диска
    load_tokens_from_file()
    if token_pool:
        # Если уже есть — убедимся, что все указанные учётки присутствуют, иначе дополним
        existing_usernames = {t["username"] for t in token_pool}
        need_login = [a for a in accounts if a["username"] not in existing_usernames]
        if not need_login:
            token_cycle = itertools.cycle(token_pool)
            print(f"[POOL] 🟢 Используем токены из {TOKENS_FILE}.")
            return

    print("[POOL] 🔄 Инициализация пула токенов через Playwright...")
    token_pool = []
    try:
        with sync_playwright() as p:
            for acc in accounts:
                tok = login_crm_playwright(acc["username"], acc["password"], p, show_browser=show_browser)
                if tok:
                    token_pool.append(tok)
                    print(f"[POOL] ✅ {acc['username']} добавлен.")
                else:
                    print(f"[POOL] ⚠️ {acc['username']} не дал токены.")
    except Exception as e:
        print(f"[POOL ERROR] during init: {e}")
        traceback.print_exc()

    if token_pool:
        token_cycle = itertools.cycle(token_pool)
        save_tokens_to_file()
        print(f"[POOL] 🟢 Успешно загружено {len(token_pool)} токенов.")
    else:
        token_cycle = None
        print("[POOL] ❌ Пул токенов пуст! Проверь логин-флоу.")

# ================== 6. ПОЛУЧЕНИЕ СЛЕДУЮЩЕГО ТОКЕНА (ROUND-ROBIN) ==================
def get_next_token() -> Optional[Dict]:
    global token_cycle, token_pool
    # Если нет токенов — инициализируем пул (попытка)
    if not token_cycle:
        print("[AUTH] token_cycle пуст, инициализируем пул...")
        init_token_pool_playwright()
        if not token_cycle:
            return None
    try:
        current_token = next(token_cycle)
        print(f"[POOL] 🔁 Переключение на аккаунт: {current_token.get('username')}")
        return current_token
    except Exception as e:
        print(f"[POOL ERROR] next(token_cycle): {e}")
        return None

# ================== 7. CRM GET (использует куки и обновляет при 401/403) ==================
def refresh_token_for_username(username: str, show_browser: bool = False) -> Optional[Dict]:
    """Обновляет токен для конкретной учётки и сохраняет файл."""
    global token_pool, token_cycle
    try:
        with sync_playwright() as p:
            new_t = login_crm_playwright(username, next(a["password"] for a in accounts if a["username"] == username), p, show_browser=show_browser)
        if new_t:
            replaced = False
            for i, t in enumerate(token_pool):
                if t.get("username") == username:
                    token_pool[i] = new_t
                    replaced = True
                    break
            if not replaced:
                token_pool.append(new_t)
            token_cycle = itertools.cycle(token_pool)
            save_tokens_to_file()
            print(f"[AUTH] ✅ {username} token refreshed and saved.")
            return new_t
        else:
            print(f"[AUTH] ❌ Не удалось обновить токен для {username}.")
            return None
    except Exception as e:
        print(f"[AUTH ERROR] refresh {username}: {e}")
        traceback.print_exc()
        return None

def crm_get(endpoint: str, params: dict = None):
    """
    Выполняет GET запрос в CRM, используя следующий токен из пула.
    Если получаем 401/403 — пробуем обновить токен (Playwright) и повторяем.
    """
    global token_pool, token_cycle

    for attempt in range(2):  # попытка: текущий токен, затем после возможного обновления
        token = get_next_token()
        if not token:
            return "❌ Нет активных токенов CRM."

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": token.get("user_agent", "python-requests"),
            "Cookie": token.get("cookie_header", ""),
        }
        url = endpoint if endpoint.startswith("http") else API_BASE + endpoint

        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
        except Exception as e:
            return f"❌ Ошибка соединения: {e}"

        # Если авторизация упала — обновим токен для этого пользователя и попробуем ещё раз
        if r.status_code in (401, 403):
            uname = token.get("username")
            print(f"[AUTH] {uname} token invalid (status {r.status_code}) → обновляем через Playwright...")
            new_t = refresh_token_for_username(uname)
            if new_t:
                print(f"[AUTH] {uname} token обновлён, повторяем запрос.")
                continue
            else:
                print(f"[AUTH] {uname} не удалось обновить токен, переключаемся на следующий.")
                continue

        return r

    return "❌ Не удалось получить данные после попытки обновления токенов."

# ================== 8. DYNAMIC ALLOWED IDS (github) ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600

def fetch_allowed_users():
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    print("[AUTH-LOG] 🔄 Загрузка списка разрешённых ID...")
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        print(f"[AUTH-LOG] GitHub status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            new_ids = [int(i) for i in data.get("allowed_users", []) if str(i).isdigit()]
            if new_ids:
                ALLOWED_USER_IDS = new_ids
                LAST_FETCH_TIME = int(time.time())
                print(f"[AUTH-LOG] ✅ Загружено {len(ALLOWED_USER_IDS)} ID.")
            else:
                print("[AUTH-LOG] ⚠️ Пустой список на удалённом ресурсе.")
        else:
            print(f"[AUTH-LOG] ❌ Ошибка загрузки списка: {r.status_code}")
    except Exception as e:
        print(f"[AUTH-LOG ERROR] {e}")

def periodic_fetch():
    while True:
        try:
            if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
                fetch_allowed_users()
        except Exception:
            pass
        time.sleep(FETCH_INTERVAL)

# ================== 9. SEARCH HELPERS ==================
def search_by_iin(iin: str):
    r = crm_get("/api/v2/person-search/by-iin", params={"iin": iin})
    if isinstance(r, str):
        return r
    if r.status_code == 404:
        return "⚠️ Ничего не найдено по ИИН."
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    p = r.json()
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📅 Дата рождения: {p.get('birthday','')}\n"
        f"🚻 Пол: {p.get('sex','')}\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_phone(phone: str):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    r = crm_get("/api/v2/person-search/by-phone", params={"phone": clean})
    if isinstance(r, str):
        return r
    if r.status_code == 404:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    data = r.json()
    if not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    p = data[0] if isinstance(data, list) else data
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📅 Дата рождения: {p.get('birthday','')}\n"
        f"🚻 Пол: {p.get('sex','')}\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_fio(text: str):
    if text.startswith(",,"):
        parts = text[2:].strip().split()
        if len(parts) < 2:
            return "⚠️ Укажите имя и отчество после ',,'"
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "false", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "":
            params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "":
            params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "":
            params["father_name"] = parts[2]
        q = {**params, "smart_mode": "false", "limit": 10}

    r = crm_get("/api/v2/person-search/smart", params=q)
    if isinstance(r, str):
        return r
    if r.status_code == 404:
        return "⚠️ Ничего не найдено."
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    data = r.json()
    if not data:
        return "⚠️ Ничего не найдено."
    if isinstance(data, dict):
        data = [data]
    results = []
    for i, p in enumerate(data[:10], start=1):
        results.append(
            f"{i}. 👤 <b>{p.get('snf','')}</b>\n"
            f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
            f"📅 Дата рождения: {p.get('birthday','')}\n"
            f"🚻 Пол: {p.get('sex','')}\n"
            f"🌍 Национальность: {p.get('nationality','')}"
        )
    return "📌 Результаты поиска по ФИО:\n\n" + "\n".join(results)

# ================== 10. FLASK API ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    user_id = data.get('telegram_user_id')
    if user_id is None:
        return jsonify({"error": "Ошибка авторизации: ID пользователя не найден."}), 403

    try:
        if int(user_id) not in ALLOWED_USER_IDS:
            print(f"❌ Доступ запрещен для ID: {user_id}")
            return jsonify({"error": "У вас нет доступа к этому приложению."}), 403
    except Exception:
        return jsonify({"error": "Неверный формат ID пользователя."}), 403

    query = data.get('query', '').strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith("+") or query.startswith("8") or query.startswith("7"):
        reply = search_by_phone(query)
    else:
        reply = search_by_fio(query)

    if isinstance(reply, str) and (reply.startswith("❌") or reply.startswith("⚠️")):
        return jsonify({"error": reply.replace("❌ ", "").replace("⚠️ ", "")}), 400

    return jsonify({"result": reply})

@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Неверный секретный токен. Доступ запрещен."}), 403
    print("[AUTH-LOG] manual refresh requested")
    fetch_allowed_users()
    return jsonify({
        "status": "success",
        "message": "Список разрешённых пользователей обновлён.",
        "loaded_count": len(ALLOWED_USER_IDS)
    }), 200

@app.route('/api/refresh-token', methods=['POST'])
def refresh_token_endpoint():
    """
    POST {"username": "blue7"} — принудительное обновление токена для указанной учётки.
    Требует секрета в заголовке Authorization: Bearer <SECRET_TOKEN>
    """
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Неверный секретный токен."}), 403
    data = request.json or {}
    uname = data.get("username")
    if not uname:
        return jsonify({"error": "username не указан."}), 400
    new_t = refresh_token_for_username(uname)
    if new_t:
        return jsonify({"status": "ok", "username": uname}), 200
    return jsonify({"status": "fail", "username": uname}), 500

# ================== 11. STARTUP ==================
print("--- 🔴 DEBUG: STARTING API (Playwright-driven tokens) 🔴 ---")

print("🔐 Initial fetch allowed users...")
fetch_allowed_users()

print("🔄 Start periodic allowed-users fetcher...")
Thread(target=periodic_fetch, daemon=True).start()

print("🔐 Initializing token pool (Playwright logins)...")
# Инициализация в фоновой ветке, чтобы Gunicorn не зависал на старте
Thread(target=init_token_pool_playwright, daemon=True).start()

print("🚀 API server ready to receive requests.")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
