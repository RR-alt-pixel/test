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

# ⚙️ Максимум одновременно логинящихся учёток
MAX_PARALLEL_LOGINS = 2

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

# ================== 4. LOGIN через PLAYWRIGHT ==================
def login_crm_playwright(username: str, password: str, p, show_browser: bool = False) -> Optional[Dict]:
    """Авторизация через Playwright и сбор cookies"""
    browser: Optional[Browser] = None
    try:
        print(f"[PLW] 🔵 Вход под {username}...")
        browser = p.chromium.launch(
            headless=not show_browser,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
                "--disable-gpu", "--disable-features=site-per-process,Translate,BlinkGenPropertyTrees"
            ],
            timeout=60000
        )
        context = browser.new_context()
        page: Page = context.new_page()
        page.set_default_timeout(30000)

        page.goto(LOGIN_PAGE, wait_until="load", timeout=30000)
        time.sleep(0.5)
        page.fill(LOGIN_SELECTOR, username)
        time.sleep(0.4)
        page.fill(PASSWORD_SELECTOR, password)
        time.sleep(0.4)
        page.keyboard.press("Enter")  # имитируем Enter
        time.sleep(4)

        try:
            page.wait_for_url("**/dashboard**", timeout=8000)
        except Exception:
            pass

        cookies = context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        user_agent = page.evaluate("() => navigator.userAgent")

        if cookie_header:
            print(f"[PLW] ✅ {username}: авторизация успешна, куки получены.")
            return {
                "username": username,
                "cookie_header": cookie_header,
                "user_agent": user_agent,
                "time": int(time.time())
            }
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


# ================== 5. ПУЛ ЛОГИНОВ ==================
def init_token_pool_playwright(show_browser: bool = False):
    """Логинит все учётки через Playwright, по MAX_PARALLEL_LOGINS за раз."""
    global token_pool, token_cycle

    load_tokens_from_file()
    if token_pool:
        existing_usernames = {t["username"] for t in token_pool}
        need_login = [a for a in accounts if a["username"] not in existing_usernames]
        if not need_login:
            token_cycle = itertools.cycle(token_pool)
            print(f"[POOL] 🟢 Используем токены из {TOKENS_FILE}.")
            return
    else:
        need_login = accounts

    print(f"[POOL] 🔄 Инициализация токенов ({len(need_login)} учёток, по {MAX_PARALLEL_LOGINS} за раз)...")
    token_pool = []

    try:
        # Разбиваем по партиям
        for i in range(0, len(need_login), MAX_PARALLEL_LOGINS):
            batch = need_login[i:i + MAX_PARALLEL_LOGINS]
            threads = []
            results = []

            def login_and_store(acc):
                try:
                    with sync_playwright() as local_p:
                        tok = login_crm_playwright(acc["username"], acc["password"], local_p, show_browser=show_browser)
                        if tok:
                            results.append(tok)
                except Exception as e:
                    print(f"[THREAD ERROR] {acc['username']}: {e}")

            for acc in batch:
                t = Thread(target=login_and_store, args=(acc,))
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

            token_pool.extend(results)
            print(f"[POOL] ✅ Партия завершена ({i + len(batch)}/{len(need_login)}).")
            time.sleep(3)

    except Exception as e:
        print(f"[POOL ERROR] Ошибка: {e}")
        traceback.print_exc()

    if token_pool:
        token_cycle = itertools.cycle(token_pool)
        save_tokens_to_file()
        print(f"[POOL] 🟢 Успешно загружено {len(token_pool)} токенов.")
    else:
        token_cycle = None
        print("[POOL] ❌ Пул токенов пуст!")


# ================== 6. ОБНОВЛЕНИЕ ТОКЕНА ==================
def refresh_token_for_username(username: str, show_browser: bool = False) -> Optional[Dict]:
    global token_pool, token_cycle
    try:
        with sync_playwright() as p:
            new_t = login_crm_playwright(username, next(a["password"] for a in accounts if a["username"] == username), p, show_browser=show_browser)
        if new_t:
            for i, t in enumerate(token_pool):
                if t.get("username") == username:
                    token_pool[i] = new_t
                    break
            else:
                token_pool.append(new_t)
            token_cycle = itertools.cycle(token_pool)
            save_tokens_to_file()
            print(f"[AUTH] ✅ {username} token refreshed.")
            return new_t
    except Exception as e:
        print(f"[AUTH ERROR] refresh {username}: {e}")
    return None


# ================== 7. CRM GET ==================
def get_next_token() -> Optional[Dict]:
    global token_cycle
    if not token_cycle:
        print("[AUTH] token_cycle пуст, инициализация...")
        init_token_pool_playwright()
        if not token_cycle:
            return None
    try:
        return next(token_cycle)
    except Exception:
        return None


def crm_get(endpoint: str, params: dict = None):
    for _ in range(2):
        token = get_next_token()
        if not token:
            return "❌ Нет активных токенов."
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": token.get("user_agent", ""),
            "Cookie": token.get("cookie_header", "")
        }
        url = endpoint if endpoint.startswith("http") else API_BASE + endpoint
        r = requests.get(url, headers=headers, params=params, timeout=15)

        if r.status_code in (401, 403):
            print(f"[AUTH] {token['username']} → токен истёк, обновляем...")
            refresh_token_for_username(token["username"])
            continue
        return r
    return "❌ Не удалось получить данные после обновления токена."


# ================== 8. SEARCH ==================
def search_by_iin(iin: str):
    r = crm_get("/api/v2/person-search/by-iin", params={"iin": iin})
    if isinstance(r, str):
        return r
    if r.status_code == 404:
        return "⚠️ Не найдено."
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}"
    p = r.json()
    return f"👤 {p.get('snf','')} | ИИН {p.get('iin','')} | Телефон {p.get('phone_number','')}"


# ================== 9. FLASK API ==================
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    if query.isdigit() and len(query) == 12:
        result = search_by_iin(query)
    else:
        result = "⚠️ Только поиск по ИИН пока включён."

    return jsonify({"result": result})


# ================== 10. START ==================
print("🔐 Initializing token pool (Playwright logins)...")
Thread(target=init_token_pool_playwright, daemon=True).start()

print("🚀 API server ready.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
