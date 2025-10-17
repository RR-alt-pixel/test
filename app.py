# -*- coding: utf-8 -*-
import requests
import json
import os
import time
import itertools
from flask import Flask, request, jsonify
from flask_cors import CORS
from threading import Thread
from playwright.sync_api import sync_playwright
from typing import Optional, Dict

# ================== 1. НАСТРОЙКИ И АВТОРИЗАЦИЯ ==================
BOT_TOKEN = "8240195944:AAEQFd2met5meCU1uwu5PvPejJoiKu94cms"

# 🔗 Загружаем список разрешённых пользователей с GitHub
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS = [0]  # временно, перезапишется после первой загрузки

BASE_URL = "https://crm431241.ru"
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

# ================== 2. НАСТРОЙКИ PLAYWRIGHT ==================
LOGIN_URL_PLW = f"{BASE_URL}/auth/login"
DASHBOARD_URL = f"{BASE_URL}/dashboard"
LOGIN_SELECTOR = '#username'
PASSWORD_SELECTOR = '#password'
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]'

# ================== 3. АККАУНТЫ ==================
accounts = [
    {"username": "blue1", "password": "852dfghm"},
]

# ================== 4. ПУЛ ТОКЕНОВ ==================
token_pool = []
token_cycle = None

# ================== 5. LOGIN_CRM через Playwright ==================
def login_crm(username, password, p) -> Optional[Dict]:
    browser = None
    try:
        print(f"[PLW] Попытка запуска браузера для {username}...")
        browser = p.chromium.launch(
            headless=True,
            timeout=15000,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-video-decode',
                '--disable-accelerated-video-encode',
                '--disable-gpu-memory-buffer-video-frames',
                '--single-process',
                '--no-zygote',
                '--disable-features=site-per-process,Translate,BlinkGenPropertyTrees'
            ]
        )

        page = browser.new_page()
        page.set_default_timeout(25000)

        page.goto(LOGIN_URL_PLW, wait_until='load', timeout=15000)
        page.type(LOGIN_SELECTOR, username, delay=50)
        time.sleep(1)
        page.type(PASSWORD_SELECTOR, password, delay=50)
        time.sleep(1)
        page.click(SIGN_IN_BUTTON_SELECTOR)
        time.sleep(4)

        page.goto(DASHBOARD_URL, wait_until='domcontentloaded', timeout=10000)
        time.sleep(1)

        if "dashboard" in page.url:
            print(f"[LOGIN OK] {username} вошёл успешно ✅")
            cookies = page.context.cookies()
            cookies_for_requests = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
            user_agent = page.evaluate('navigator.userAgent')
            csrf_token_sec = next((c['value'] for c in cookies if c['name'] == '__Secure-csrf_token'), None)
            csrf_value = csrf_token_sec.split('.')[0] if csrf_token_sec else None

            return {
                "username": username,
                "csrf": csrf_value,
                "time": int(time.time()),
                "user_agent": user_agent,
                "cookie_header": cookies_for_requests
            }

        print(f"[LOGIN FAIL] {username}: Не удалось войти ({page.url})")
        return None

    except Exception as e:
        print(f"[LOGIN ERR] {username}: {type(e).__name__}: {e}")
        return None
    finally:
        if browser:
            browser.close()

# ================== 6. АВТОРИЗАЦИЯ АККАУНТОВ ==================
def init_token_pool():
    global token_pool, token_cycle
    print("🔐 Загрузка токенов CRM...")
    try:
        with sync_playwright() as p:
            new_pool = []
            for acc in accounts:
                token_data = login_crm(acc["username"], acc["password"], p)
                if token_data:
                    new_pool.append(token_data)
            token_pool = new_pool
            token_cycle = itertools.cycle(token_pool) if token_pool else None
            print(f"✅ Загружено {len(token_pool)} токенов CRM.")
    except Exception as e:
        print(f"❌ Ошибка инициализации токенов: {type(e).__name__}: {e}")
    print("🚀 Сервис готов принимать запросы.")

def get_next_token() -> Optional[Dict]:
    global token_cycle, token_pool
    if not token_cycle:
        init_token_pool()
        if not token_cycle:
            return None
    try:
        return next(token_cycle)
    except StopIteration:
        return None

# ================== 7. CRM GET ==================
def crm_get(endpoint, params=None):
    for _ in range(2):
        token = get_next_token()
        if not token:
            return "❌ Нет активных токенов CRM."

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": token["user_agent"],
            "Cookie": token["cookie_header"]
        }
        if token["csrf"]:
            headers["X-CSRF-Token"] = token["csrf"]

        url = f"{BASE_URL}{endpoint}"
        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
        except Exception as e:
            return f"❌ Ошибка соединения: {e}"

        if r.status_code in (401, 403):
            print(f"[AUTH] {token['username']} → токен устарел, перелогин...")
            with sync_playwright() as p:
                new_t = login_crm(token["username"], next(a["password"] for a in accounts if a["username"] == token["username"]), p)
            if new_t:
                token_pool = [t if t["username"] != new_t["username"] else new_t for t in token_pool]
                token_cycle = itertools.cycle(token_pool)
                continue
        return r
    return "❌ Ошибка авторизации."

# ================== 8. ДИНАМИЧЕСКАЯ ЗАГРУЗКА ID (GitHub) ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600  # 1 час

def fetch_allowed_users():
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    print("[AUTH-LOG] Попытка загрузить разрешённые ID...")
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        print(f"[AUTH-LOG] HTTP {r.status_code} от GitHub")
        if r.status_code == 200:
            data = r.json()
            new_ids = [int(i) for i in data.get("allowed_users", []) if str(i).isdigit()]
            if new_ids:
                ALLOWED_USER_IDS = new_ids
                LAST_FETCH_TIME = int(time.time())
                print(f"[AUTH-LOG] ✅ Загружено {len(ALLOWED_USER_IDS)} ID: {ALLOWED_USER_IDS}")
            else:
                print("[AUTH-LOG] ⚠️ Список пуст.")
        else:
            print(f"[AUTH-LOG] ❌ Ошибка {r.status_code}: {r.text[:100]}")
    except Exception as e:
        print(f"[AUTH-LOG] 💥 Ошибка загрузки ID: {e}")

def periodic_fetch():
    while True:
        fetch_allowed_users()
        time.sleep(FETCH_INTERVAL)

# ================== 9. ФУНКЦИИ ПОИСКА ==================
def search_by_iin(iin):
    r = crm_get("/api/v2/person-search/by-iin", {"iin": iin})
    if isinstance(r, str): return r
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    p = r.json()
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_phone(phone):
    clean = ''.join(filter(str.isdigit, phone))
    if clean.startswith("8"): clean = "7" + clean[1:]
    r = crm_get("/api/v2/person-search/by-phone", {"phone": clean})
    if isinstance(r, str): return r
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    data = r.json()
    if not data: return "⚠️ Не найдено"
    p = data[0] if isinstance(data, list) else data
    return (
        f"👤 <b>{p.get('snf','')}</b>\n"
        f"🧾 ИИН: <code>{p.get('iin','')}</code>\n"
        f"📱 Телефон: {p.get('phone_number','')}\n"
        f"🏠 Адрес: {p.get('address','')}"
    )

def search_by_fio(text):
    parts = text.split(" ")
    q = {"limit": 10, "smart_mode": "false"}
    if len(parts) >= 1: q["surname"] = parts[0]
    if len(parts) >= 2: q["name"] = parts[1]
    if len(parts) >= 3: q["father_name"] = parts[2]
    r = crm_get("/api/v2/person-search/smart", q)
    if isinstance(r, str): return r
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    data = r.json()
    if not data: return "⚠️ Ничего не найдено."
    if isinstance(data, dict): data = [data]
    results = []
    for i, p in enumerate(data[:10], start=1):
        results.append(f"{i}. 👤 <b>{p.get('snf','')}</b>\n🧾 ИИН: <code>{p.get('iin','')}</code>")
    return "📌 Результаты:\n\n" + "\n".join(results)

# ================== 10. FLASK API ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    user_id = data.get('telegram_user_id')
    if user_id is None:
        return jsonify({"error": "ID пользователя не найден."}), 403

    try:
        user_id_int = int(user_id)
    except ValueError:
        return jsonify({"error": "Неверный формат ID."}), 403

    if user_id_int not in ALLOWED_USER_IDS:
        print(f"[ACCESS DENIED] user_id={user_id_int}, allowed={ALLOWED_USER_IDS}")
        return jsonify({"error": "Нет доступа"}), 403

    query = data.get('query', '').strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith("+") or query.startswith("8") or query.startswith("7"):
        reply = search_by_phone(query)
    else:
        reply = search_by_fio(query)

    if reply.startswith("❌") or reply.startswith("⚠️"):
        return jsonify({"error": reply}), 400
    return jsonify({"result": reply})

@app.route('/api/refresh-users', methods=['POST'])
def refresh_users():
    auth_header = request.headers.get('Authorization')
    if auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Неверный секретный токен"}), 403
    print("[AUTH-LOG] Принудительное обновление списка ID...")
    fetch_allowed_users()
    return jsonify({
        "status": "success",
        "message": "Список разрешённых пользователей обновлён.",
        "loaded_count": len(ALLOWED_USER_IDS)
    }), 200

# ================== 11. СТАРТ ==================
print("--- 🔴 ЗАПУСК API 🔴 ---")
print("🔐 Первая загрузка списка ID с GitHub...")
fetch_allowed_users()
print("🔄 Фоновое обновление ID...")
Thread(target=periodic_fetch, daemon=True).start()
print("🔐 Авторизация аккаунтов CRM...")
Thread(target=init_token_pool, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
