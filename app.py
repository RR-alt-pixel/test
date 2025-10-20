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
from playwright.sync_api import sync_playwright, Browser, Page

# ================== НАСТРОЙКИ ==================
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

# ================== УЧЁТКИ ==================
accounts = [
    {"username": "pink5", "password": "ugsdf413"},
    {"username": "pink6", "password": "851hjk74"},
    {"username": "pink7", "password": "85tg24vd"},
    {"username": "pink8", "password": "14gh1223"},
    {"username": "pink9", "password": "845ghj65"},
]

token_pool: List[Dict] = []
token_cycle = None
playwright_lock = Lock()
last_refresh_times: Dict[str, float] = {}

# ================== PLAYWRIGHT LOGIN ==================
def login_crm_playwright(username: str, password: str, p) -> Optional[Dict]:
    browser: Optional[Browser] = None
    try:
        print(f"[PLW] 🔵 Вход через браузер под {username}...")
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", "--single-process",
                "--no-zygote", "--disable-gpu"
            ],
        )
        context = browser.new_context()
        page: Page = context.new_page()
        page.set_default_timeout(30000)
        page.goto(LOGIN_PAGE, wait_until="load")
        page.fill(LOGIN_SELECTOR, username)
        time.sleep(0.4)
        page.fill(PASSWORD_SELECTOR, password)
        time.sleep(0.4)
        page.click(SIGN_IN_BUTTON_SELECTOR)
        time.sleep(2)

        cookies = context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        user_agent = page.evaluate("() => navigator.userAgent")
        access_cookie = next((c["value"] for c in cookies if "access" in c["name"]), None)
        csrf_cookie = next((c["value"] for c in cookies if "csrf" in c["name"].lower()), None)

        if access_cookie:
            print(f"[PLW] ✅ {username} успешно авторизован.")
            return {
                "username": username,
                "access": access_cookie,
                "csrf": csrf_cookie or "",
                "time": int(time.time()),
                "cookie_header": cookie_header,
                "user_agent": user_agent
            }
        else:
            print(f"[PLW] ⚠️ Не удалось извлечь токены для {username}")
            return None
    except Exception as e:
        print(f"[PLW ERROR] {username}: {e}")
        traceback.print_exc()
        return None
    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass

# ================== ПУЛ ТОКЕНОВ ==================
def init_token_pool_playwright():
    global token_pool, token_cycle
    token_pool = []
    print("[POOL] 🔄 Инициализация пула токенов...")
    try:
        with playwright_lock:
            with sync_playwright() as p:
                for acc in accounts:
                    tok = login_crm_playwright(acc["username"], acc["password"], p)
                    if tok:
                        token_pool.append(tok)
                        print(f"[POOL] ✅ {acc['username']} добавлен.")
                        time.sleep(0.8)
    except Exception as e:
        print(f"[POOL ERROR] {e}")
        traceback.print_exc()
    if token_pool:
        token_cycle = itertools.cycle(token_pool)
        print(f"[POOL] 🟢 Успешно загружено {len(token_pool)} токенов.")
    else:
        print("[POOL] ❌ Пул токенов пуст!")

def get_next_token() -> Optional[Dict]:
    global token_cycle
    if not token_cycle:
        init_token_pool_playwright()
        if not token_cycle:
            return None
    try:
        token = next(token_cycle)
        print(f"[POOL] 🔁 Аккаунт: {token['username']}")
        return token
    except Exception:
        return None

# ================== CRM ЗАПРОС ==================
def crm_get(endpoint: str, params: dict = None):
    for _ in range(2):
        token = get_next_token()
        if not token:
            return "❌ Нет активных токенов CRM."
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": token.get("user_agent", "python-requests"),
            "Cookie": token.get("cookie_header", ""),
            "Referer": BASE_URL,
            "Origin": BASE_URL,
        }
        if token.get("csrf"):
            headers["X-CSRF-Token"] = token["csrf"]
        url = endpoint if endpoint.startswith("http") else API_BASE + endpoint
        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
        except Exception as e:
            return f"❌ Ошибка соединения: {e}"
        if r.status_code in (401, 403):
            uname = token["username"]
            now = time.time()
            # антифлуд: не чаще 180 секунд на одного пользователя
            if uname in last_refresh_times and now - last_refresh_times[uname] < 180:
                print(f"[AUTH] ⏳ {uname}: недавно обновлялся, пропуск.")
                continue
            last_refresh_times[uname] = now
            print(f"[AUTH] 🔄 Токен устарел: {uname}, обновляем...")
            try:
                with playwright_lock:
                    with sync_playwright() as p:
                        new_t = login_crm_playwright(
                            uname,
                            next(a["password"] for a in accounts if a["username"] == uname),
                            p
                        )
                if new_t:
                    for i, t in enumerate(token_pool):
                        if t["username"] == uname:
                            token_pool[i] = new_t
                            break
                    token_cycle = itertools.cycle(token_pool)
                    print(f"[AUTH] ✅ {uname} токен обновлён.")
                    time.sleep(1)
                    continue
                else:
                    print(f"[AUTH] ❌ Не удалось обновить токен {uname}.")
                    continue
            except Exception as e:
                print(f"[AUTH ERROR] {e}")
                traceback.print_exc()
                continue
        return r
    return "❌ Не удалось получить данные."

# ================== СПИСОК ДОПУСКА ==================
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
                print(f"[AUTH-LOG] ✅ Загружено {len(ids)} ID.")
    except Exception as e:
        print(f"[AUTH-LOG ERROR] {e}")

def periodic_fetch():
    while True:
        if int(time.time()) - LAST_FETCH_TIME >= FETCH_INTERVAL:
            fetch_allowed_users()
        time.sleep(FETCH_INTERVAL)

# ================== ПОИСК ==================
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
# ================== FLASK ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
# твои /api/search и /api/refresh-users остаются теми же

print("🔐 Загрузка разрешённых ID...")
fetch_allowed_users()
Thread(target=periodic_fetch, daemon=True).start()
print("🔐 Авторизация через Playwright...")
Thread(target=init_token_pool_playwright, daemon=True).start()
print("🚀 API готов к работе.")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
