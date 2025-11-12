# -*- coding: utf-8 -*-
import os
import time
import json
import random
import itertools
import traceback
from threading import Thread, Lock
from typing import Optional, Dict, List
from queue import Queue

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright, Browser, Page

# ================== 1. НАСТРОЙКИ ==================
BOT_TOKEN = "8205898720:AAFP5EU1MKIM9q9SKflrq7aNXMq82M0tv5s"
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
    {"username": "bear1", "password": "79Cx78Qg"},
    {"username": "bear2", "password": "66pQ77aZ"},
    {"username": "bear3", "password": "68Es77Cx"},
    {"username": "bear4", "password": "67xC90qC"},
    {"username": "bear5", "password": "80Sh69Op"},
    {"username": "Gray4", "password": "70Tk77Hk"},
    {"username": "Gray5", "password": "71oB65fF"},
    {"username": "Gray6", "password": "78Hk83Ga"},
    {"username": "Gray7", "password": "67wR76xT"},
    {"username": "Gray8", "password": "68Bg68Uk"},
    {"username": "Gray9", "password": "89fO85jO"},
    {"username": "gold6", "password": "79Lj65Uz"},
    {"username": "gold7", "password": "78bJ87fI"},
    {"username": "gold8", "password": "73Za81Fx"},
    {"username": "gold9", "password": "68rK66rZ"},
]

# ================== 3. ПУЛ ТОКЕНОВ ==================
token_pool: List[Dict] = []
token_cycle = None

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

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
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            timeout=60000
        )
        context = browser.new_context(user_agent=random.choice(USER_AGENTS))
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
# ================== 6. TOKEN GETTER ==================
def get_next_token() -> Optional[Dict]:
    global token_pool, token_cycle
    if not token_pool:
        init_token_pool_playwright()
        if not token_pool:
            return None

    # Если цикл не создан — создаём его
    if token_cycle is None:
        token_cycle = itertools.cycle(token_pool)

    # Берём следующий токен по очереди
    try:
        token = next(token_cycle)
        print(f"[POOL] 🔁 Используется токен {token['username']}")
        return token
    except StopIteration:
        # Если цикл почему-то прервался — пересоздаём
        token_cycle = itertools.cycle(token_pool)
        token = next(token_cycle)
        print(f"[POOL] ♻️ Перезапуск цикла, выбран {token['username']}")
        return token


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
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Connection": "keep-alive",
        "Referer": f"{BASE_URL}/search",
        "User-Agent": token.get("user_agent", random.choice(USER_AGENTS)),
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
            time.sleep(random.uniform(1.2, 1.8))  # 🕒 Анти-бот задержка
        except Exception as e:
            result_box["error"] = str(e)
        finally:
            crm_queue.task_done()

Thread(target=crm_worker, daemon=True).start()

def enqueue_crm_get(endpoint, params=None):
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
        return f"⌛ Ваш запрос в очереди (позиция {pos})."
    resp = r["result"]
    if isinstance(resp, str): return resp
    if resp.status_code == 404: return "⚠️ Ничего не найдено по ИИН."
    if resp.status_code != 200: return f"❌ Ошибка {resp.status_code}: {resp.text}"
    p = resp.json()
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
    if clean.startswith("8"): clean = "7" + clean[1:]
    r = enqueue_crm_get("/api/v2/person-search/by-phone", params={"phone": clean})
    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос в очереди (позиция {pos})."
    resp = r["result"]
    if isinstance(resp, str): return resp
    if resp.status_code == 404: return f"⚠️ Ничего не найдено по номеру {phone}"
    if resp.status_code != 200: return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not data: return f"⚠️ Ничего не найдено по номеру {phone}"
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
        if len(parts) < 2: return "⚠️ Укажите имя и отчество после ',,'"
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "false", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "": params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "": params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "": params["father_name"] = parts[2]
        q = {**params, "smart_mode": "false", "limit": 10}
    r = enqueue_crm_get("/api/v2/person-search/smart", params=q)
    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос в очереди (позиция {pos})."
    resp = r["result"]
    if isinstance(resp, str): return resp
    if resp.status_code == 404: return "⚠️ Ничего не найдено."
    if resp.status_code != 200: return f"❌ Ошибка {resp.status_code}: {resp.text}"
    data = resp.json()
    if not data: return "⚠️ Ничего не найдено."
    if isinstance(data, dict): data = [data]
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
    return jsonify({"queue_size": crm_queue.qsize()})

@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Forbidden"}), 403
    fetch_allowed_users()
    return jsonify({"ok": True, "count": len(ALLOWED_USER_IDS)})

def search_by_address(address: str):
    print(f"[SEARCH] 🔍 Поиск по адресу: {address}")

    r = enqueue_crm_get("/api/v2/person-search/by-address", params={
        "address": address,
        "exact_match": "false",
        "limit": 100
    })

    if r["status"] != "ok":
        pos = r.get("queue_position", "?")
        return f"⌛ Ваш запрос в очереди (позиция {pos})."

    resp = r["result"]
    if isinstance(resp, str):
        return resp

    if resp.status_code == 404:
        return f"⚠️ Ничего не найдено по адресу: {address}"
    if resp.status_code != 200:
        return f"❌ Ошибка {resp.status_code}: {resp.text}"

    try:
        data = resp.json()
    except Exception:
        return f"❌ Ошибка разбора ответа от CRM."

    if not data:
        return f"⚠️ Ничего не найдено по адресу: {address}"

    if isinstance(data, dict):
        data = [data]

    results = []
    for i, p in enumerate(data[:10], start=1):
        addr = p.get("address", "")
        if len(addr) > 120:
            addr = addr[:120] + "..."
        results.append(
            f"{i}. 👤 <b>{p.get('snf','')}</b>\n"
            f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
            f"📅 {p.get('birthday','')}\n"
            f"🚻 {p.get('sex','')}\n"
            f"🌍 {p.get('nationality','')}\n"
            f"🏠 {addr}"
        )

    return "📍 Результаты поиска по адресу:\n\n" + "\n\n".join(results)

# ================== 11. STARTUP ==================
print("🚀 Запуск API с очередью запросов...")
fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()
Thread(target=init_token_pool_playwright, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
