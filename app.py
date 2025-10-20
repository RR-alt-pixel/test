# -*- coding: utf-8 -*-
import os
import time
import json
import itertools
import traceback
from threading import Thread
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
current_token = None  # 🔸 активный токен, используется в crm_get()

# ================== 4. PLAYWRIGHT LOGIN ==================
def login_crm_playwright(username: str, password: str, p) -> Optional[Dict]:
    browser: Optional[Browser] = None
    try:
        print(f"[PLW] starting browser for {username}...")
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", "--single-process",
                "--no-zygote", "--disable-gpu",
                "--disable-features=site-per-process,Translate,BlinkGenPropertyTrees"
            ],
            timeout=30000
        )
        context = browser.new_context()
        page: Page = context.new_page()
        page.set_default_timeout(30000)

        print(f"[PLW] goto login page for {username}: {LOGIN_PAGE}")
        page.goto(LOGIN_PAGE, wait_until="load", timeout=30000)
        page.fill(LOGIN_SELECTOR, username)
        time.sleep(0.5)
        page.fill(PASSWORD_SELECTOR, password)
        time.sleep(0.5)
        page.click(SIGN_IN_BUTTON_SELECTOR)

        try:
            page.wait_for_url("**/dashboard**", timeout=10000)
        except Exception:
            time.sleep(2)

        cookies = context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        user_agent = page.evaluate("() => navigator.userAgent")

        access_cookie = next((c["value"] for c in cookies if "access" in c["name"]), None)
        csrf_cookie = next((c["value"] for c in cookies if "csrf" in c["name"].lower()), None)

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

        if access_cookie:
            token = {
                "username": username,
                "access": access_cookie,
                "csrf": csrf_cookie or "",
                "time": int(time.time()),
                "cookie_header": cookie_header,
                "user_agent": user_agent
            }
            print(f"[PLW] {username} login OK, tokens found.")
            return token
        else:
            print(f"[PLW] {username} login failed or tokens not found.")
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

# ================== 5. ИНИЦИАЛИЗАЦИЯ ПУЛА ==================
def init_token_pool_playwright():
    global token_pool, token_cycle
    token_pool = []
    print("[POOL] init_token_pool_playwright: starting login for accounts...")
    try:
        with sync_playwright() as p:
            for acc in accounts:
                tok = login_crm_playwright(acc["username"], acc["password"], p)
                if tok:
                    token_pool.append(tok)
                else:
                    print(f"[POOL] warning: account {acc['username']} did not return tokens.")
    except Exception as e:
        print(f"[POOL ERROR] during init: {e}")
        traceback.print_exc()

    if token_pool:
        token_cycle = itertools.cycle(token_pool)
        print(f"[POOL] loaded {len(token_pool)} tokens.")
    else:
        token_cycle = None
        print("[POOL] no tokens loaded!")

# ================== 6. РОТАЦИЯ АККАУНТОВ КАЖДЫЙ ЧАС ==================
def rotate_accounts_hourly():
    global current_token
    while True:
        if not token_pool:
            print("[ROTATE] ⚠️ Token pool empty, waiting 60s...")
            time.sleep(60)
            continue
        current_token = next(token_cycle)
        print(f"[ROTATE] 🔁 Active account switched to: {current_token['username']}")
        time.sleep(3600)  # 🔸 менять аккаунт каждый час

# ================== 7. CRM GET ==================
def crm_get(endpoint: str, params: dict = None):
    global current_token, token_pool, token_cycle

    if not current_token:
        print("[AUTH] No active token yet, picking initial one...")
        current_token = next(token_cycle)

    for attempt in range(2):
        token = current_token
        if not token:
            return "❌ Нет активных токенов CRM."

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": token.get("user_agent", "python-requests"),
            "Cookie": token.get("cookie_header", "")
        }
        if token.get("csrf"):
            headers["X-CSRF-Token"] = token["csrf"]

        url = endpoint if endpoint.startswith("http") else API_BASE + endpoint

        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
        except Exception as e:
            return f"❌ Ошибка соединения: {e}"

        if r.status_code in (401, 403):
            uname = token.get("username")
            print(f"[AUTH] {uname} token invalid ({r.status_code}), refreshing...")
            try:
                with sync_playwright() as p:
                    new_t = login_crm_playwright(
                        uname,
                        next(a["password"] for a in accounts if a["username"] == uname),
                        p
                    )
                if new_t:
                    for i, t in enumerate(token_pool):
                        if t.get("username") == uname:
                            token_pool[i] = new_t
                            print(f"[AUTH] {uname} token refreshed.")
                            break
                    token_cycle = itertools.cycle(token_pool)
                    current_token = new_t
                    continue
            except Exception as e:
                print(f"[AUTH REFRESH ERROR] {e}")
                traceback.print_exc()
                continue
        return r
    return "❌ Не удалось получить данные после обновления токенов."

# ================== 8. DYNAMIC ALLOWED IDS ==================
LAST_FETCH_TIME = 0
FETCH_INTERVAL = 3600

def fetch_allowed_users():
    global ALLOWED_USER_IDS, LAST_FETCH_TIME
    print("[AUTH-LOG] fetching allowed users from GitHub...")
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        print(f"[AUTH-LOG] github status {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            new_ids = [int(i) for i in data.get("allowed_users", []) if str(i).isdigit()]
            if new_ids:
                ALLOWED_USER_IDS = new_ids
                LAST_FETCH_TIME = int(time.time())
                print(f"[AUTH-LOG] loaded allowed ids: {len(ALLOWED_USER_IDS)} users")
    except Exception as e:
        print(f"[AUTH-LOG] error fetching allowed ids: {e}")

def periodic_fetch():
    while True:
        if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
            fetch_allowed_users()
        time.sleep(FETCH_INTERVAL)

# ================== 9. SEARCH HELPERS ==================
# 🔹 (твой оригинальный блок — без изменений)
def search_by_iin(iin: str):
    r = crm_get("/api/v2/person-search/by-iin", params={"iin": iin})
    if isinstance(r, str): return r
    if r.status_code == 404: return "⚠️ Ничего не найдено по ИИН."
    if r.status_code != 200: return f"❌ Ошибка {r.status_code}: {r.text}"
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
    if isinstance(r, str): return r
    if r.status_code == 404: return f"⚠️ Ничего не найдено по номеру {phone}"
    if r.status_code != 200: return f"❌ Ошибка {r.status_code}: {r.text}"
    data = r.json()
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
        if len(parts) < 2:
            return "⚠️ Укажите имя и отчество после ',,'"
        q = {"name": parts[0], "father_name": " ".join(parts[1:]), "smart_mode": "false", "limit": 10}
    else:
        parts = text.split(" ")
        params = {}
        if len(parts) >= 1 and parts[0] != "": params["surname"] = parts[0]
        if len(parts) >= 2 and parts[1] != "": params["name"] = parts[1]
        if len(parts) >= 3 and parts[2] != "": params["father_name"] = parts[2]
        q = {**params, "smart_mode": "false", "limit": 10}

    r = crm_get("/api/v2/person-search/smart", params=q)
    if isinstance(r, str): return r
    if r.status_code == 404: return "⚠️ Ничего не найдено."
    if r.status_code != 200: return f"❌ Ошибка {r.status_code}: {r.text}"
    data = r.json()
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

# ================== 11. STARTUP ==================
print("--- 🔴 DEBUG: STARTING API (Playwright-driven tokens + hourly rotation) 🔴 ---")
print("🔐 Initial fetch allowed users...")
fetch_allowed_users()

Thread(target=periodic_fetch, daemon=True).start()
Thread(target=init_token_pool_playwright, daemon=True).start()
Thread(target=rotate_accounts_hourly, daemon=True).start()

print("🚀 API server ready to receive requests.")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
