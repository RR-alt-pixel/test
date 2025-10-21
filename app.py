# -*- coding: utf-8 -*-
import os
import time
import json
import itertools
import traceback
from threading import Thread, Lock
from typing import Optional, Dict, List
from queue import Queue

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# Playwright (синхронный)
from playwright.sync_api import sync_playwright, Browser, Page

# ================== 1. НАСТРОЙКИ ==================
BOT_TOKEN = "8240195944:AAEQFd2met5meCU1uwu5PvPejJoiKu94cms"
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]

BASE_URL = "https://crm431241.ru"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
API_BASE = BASE_URL
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = "#username"
PASSWORD_SELECTOR = "#password"
SIGN_IN_BUTTON_SELECTOR = "button[type='submit']"

TOKENS_FILE = "tokens.json"
TOKENS_LOCK = Lock()

# ================== 2. АККАУНТЫ ==================
accounts = [
    {"username": "pink5", "password": "ugsdf413"},
    {"username": "pink6", "password": "851hjk74"},
    {"username": "pink7", "password": "85tg24vd"},
    {"username": "pink8", "password": "14gh1223"},
    {"username": "pink9", "password": "845ghj65"},
]

# ================== 3. ПУЛ ТОКЕНОВ ==================
token_pool: List[Dict] = []
token_cycle = None

def load_tokens_from_file() -> List[Dict]:
    global token_pool, token_cycle
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    token_pool = data
                    token_cycle = itertools.cycle(token_pool) if token_pool else None
                    print(f"[TOKENS] 🔁 Загружено {len(token_pool)} токенов.")
                    return token_pool
    except Exception as e:
        print(f"[TOKENS ERROR] {e}")
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
            print(f"[TOKENS] 💾 Сохранено {len(token_pool)} токенов.")
    except Exception as e:
        print(f"[TOKENS ERROR] {e}")
        traceback.print_exc()

# ================== 4. PLAYWRIGHT LOGIN ==================
def login_crm_playwright(username: str, password: str, p, show_browser: bool = False) -> Optional[Dict]:
    browser = None
    try:
        print(f"[PLW] 🔵 Вход под {username}...")
        browser = p.chromium.launch(
            headless=not show_browser,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", "--disable-gpu"
            ],
            timeout=60000
        )
        context = browser.new_context()
        page: Page = context.new_page()
        page.goto(LOGIN_PAGE, wait_until="load", timeout=30000)
        page.fill(LOGIN_SELECTOR, username)
        time.sleep(0.4)
        page.fill(PASSWORD_SELECTOR, password)
        time.sleep(0.4)
        page.click(SIGN_IN_BUTTON_SELECTOR)
        page.wait_for_timeout(2000)

        cookies = context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        user_agent = page.evaluate("() => navigator.userAgent")

        if cookie_header:
            token = {
                "username": username,
                "cookie_header": cookie_header,
                "user_agent": user_agent,
                "time": int(time.time())
            }
            print(f"[PLW] ✅ {username} авторизован.")
            return token
        return None
    except Exception as e:
        print(f"[PLW ERROR] {username}: {e}")
        return None
    finally:
        if browser:
            browser.close()

# ================== 5. ПУЛ ТОКЕНОВ ИНИЦИАЛИЗАЦИЯ ==================
def init_token_pool_playwright(show_browser: bool = False):
    global token_pool, token_cycle
    load_tokens_from_file()
    if token_pool:
        token_cycle = itertools.cycle(token_pool)
        print(f"[POOL] 🟢 Используем сохранённые токены.")
        return

    print("[POOL] 🔄 Логин через Playwright...")
    token_pool = []
    try:
        with sync_playwright() as p:
            for acc in accounts:
                tok = login_crm_playwright(acc["username"], acc["password"], p, show_browser)
                if tok:
                    token_pool.append(tok)
    except Exception as e:
        print(f"[POOL ERROR] {e}")
    if token_pool:
        token_cycle = itertools.cycle(token_pool)
        save_tokens_to_file()
        print(f"[POOL] ✅ Загружено {len(token_pool)} токенов.")
    else:
        print("[POOL] ❌ Пустой пул токенов.")

# ================== 6. TOKEN GETTER ==================
def get_next_token() -> Optional[Dict]:
    global token_cycle
    if not token_cycle:
        init_token_pool_playwright()
        if not token_cycle:
            return None
    try:
        return next(token_cycle)
    except Exception:
        return None

# ================== 7. CRM GET ==================
def refresh_token_for_username(username: str) -> Optional[Dict]:
    global token_pool, token_cycle
    try:
        with sync_playwright() as p:
            acc = next(a for a in accounts if a["username"] == username)
            new_t = login_crm_playwright(acc["username"], acc["password"], p)
        if new_t:
            for i, t in enumerate(token_pool):
                if t["username"] == username:
                    token_pool[i] = new_t
                    break
            else:
                token_pool.append(new_t)
            token_cycle = itertools.cycle(token_pool)
            save_tokens_to_file()
            print(f"[AUTH] 🔁 {username} token refreshed.")
            return new_t
    except Exception as e:
        print(f"[AUTH ERROR] {e}")
    return None

def crm_get(endpoint: str, params: dict = None):
    token = get_next_token()
    if not token:
        return "❌ Нет токенов CRM."
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": token.get("user_agent", "python-requests"),
        "Cookie": token.get("cookie_header", "")
    }
    url = endpoint if endpoint.startswith("http") else API_BASE + endpoint
    try:
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code in (401, 403):
            uname = token["username"]
            print(f"[AUTH] {uname} → 401/403 → обновляем токен")
            new_t = refresh_token_for_username(uname)
            if new_t:
                headers["Cookie"] = new_t["cookie_header"]
                r = requests.get(url, headers=headers, params=params, timeout=20)
        return r
    except Exception as e:
        return f"❌ Ошибка CRM: {e}"

# ================== 7.1. ОЧЕРЕДЬ ЗАПРОСОВ ==================
crm_queue = Queue()
RESULT_TIMEOUT = 45

def crm_worker():
    """Фоновый поток, который выполняет CRM-запросы по очереди."""
    while True:
        try:
            task = crm_queue.get()
            if not task:
                continue
            func, args, kwargs, result_box = task
            pos = crm_queue.qsize()
            print(f"[QUEUE] ⚙️ Выполняю CRM-запрос (в очереди осталось {pos})")
            res = func(*args, **kwargs)
            result_box["result"] = res
            time.sleep(1.5)  # защита от 429
        except Exception as e:
            result_box["error"] = str(e)
        finally:
            crm_queue.task_done()

Thread(target=crm_worker, daemon=True).start()

def enqueue_crm_get(endpoint, params=None):
    """Отправляет CRM-запрос в очередь и ждёт результат."""
    result_box = {}
    position = crm_queue.qsize() + 1
    print(f"[QUEUE] 🕒 Новый запрос. Позиция: {position}")
    crm_queue.put((crm_get, (endpoint,), {"params": params}, result_box))

    t0 = time.time()
    while "result" not in result_box and "error" not in result_box:
        if time.time() - t0 > RESULT_TIMEOUT:
            return {"status": "timeout", "queue_position": position}
        time.sleep(0.1)

    if "error" in result_box:
        return {"status": "error", "error": result_box["error"], "queue_position": position}
    return {"status": "ok", "result": result_box["result"], "queue_position": position}

# ================== 8. ALLOWED USERS ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600

def fetch_allowed_users():
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        if r.status_code == 200:
            data = r.json()
            ids = [int(i) for i in data.get("allowed_users", [])]
            if ids:
                ALLOWED_USER_IDS = ids
                LAST_FETCH_TIME = int(time.time())
                print(f"[AUTH] ✅ {len(ALLOWED_USER_IDS)} пользователей разрешено.")
    except Exception as e:
        print(f"[AUTH ERROR] {e}")

def periodic_fetch():
    while True:
        try:
            if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
                fetch_allowed_users()
        except Exception:
            pass
        time.sleep(FETCH_INTERVAL)

# ================== 9. SEARCH ==================
def search_by_iin(iin: str):
    r = enqueue_crm_get("/api/v2/person-search/by-iin", params={"iin": iin})
    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос поставлен в очередь (позиция {pos}). Пожалуйста, подождите."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    p = resp.json()
    return (f"👤 <b>{p.get('snf','')}</b>\n"
            f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
            f"📱 Телефон: {p.get('phone_number','')}")

def search_by_phone(phone: str):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    r = enqueue_crm_get("/api/v2/person-search/by-phone", params={"phone": clean})
    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос в очереди (позиция {pos})."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not data:
        return f"⚠️ Ничего не найдено по номеру {phone}"
    p = data[0] if isinstance(data, list) else data
    return (f"👤 <b>{p.get('snf','')}</b>\n"
            f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
            f"📱 Телефон: {p.get('phone_number','')}")

def search_by_fio(text: str):
    parts = text.strip().split()
    params = {"smart_mode": "false", "limit": 10}
    if len(parts) >= 1:
        params["surname"] = parts[0]
    if len(parts) >= 2:
        params["name"] = parts[1]
    if len(parts) >= 3:
        params["father_name"] = parts[2]
    r = enqueue_crm_get("/api/v2/person-search/smart", params=params)
    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос в очереди (позиция {pos})."
    resp = r["result"]
    if isinstance(resp, str):
        return resp
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not data:
        return "⚠️ Ничего не найдено."
    if isinstance(data, dict):
        data = [data]
    results = []
    for i, p in enumerate(data[:10], 1):
        results.append(f"{i}. 👤 <b>{p.get('snf','')}</b>\n🧾 ИИН: <code>{p.get('iin','')}</code>")
    return "📌 Результаты поиска:\n\n" + "\n".join(results)

# ================== 10. FLASK ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    user_id = data.get('telegram_user_id')
    if user_id is None:
        return jsonify({"error": "Ошибка авторизации."}), 403
    if int(user_id) not in ALLOWED_USER_IDS:
        return jsonify({"error": "Нет доступа."}), 403

    query = data.get('query', '').strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith(("+", "8", "7")):
        reply = search_by_phone(query)
    else:
        reply = search_by_fio(query)

    return jsonify({"result": reply})

@app.route('/api/queue-size', methods=['GET'])
def queue_size():
    """Показывает текущий размер очереди."""
    return jsonify({"queue_size": crm_queue.qsize()})

@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    fetch_allowed_users()
    return jsonify({"ok": True, "count": len(ALLOWED_USER_IDS)})

# ================== 11. STARTUP ==================
print("🚀 Запуск API с очередью запросов...")
fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()
Thread(target=init_token_pool_playwright, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
