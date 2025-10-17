# -*- coding: utf-8 -*-
import os
import json
import time
import itertools
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from playwright.sync_api import sync_playwright

# ================== 1. НАСТРОЙКИ ==================
BOT_TOKEN = "8240195944:AAEQFd2met5meCU1uwu5PvPejJoiKu94cms"
BASE_URL = "https://crm431241.ru"
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"
ALLOWED_IDS_PATH = "allowed_ids.json"  # локальный путь
CRM_USER = "blue1"
CRM_PASS = "852dfghm"

# ================== 2. FLASK ==================
app = Flask(__name__, static_folder="public", static_url_path="")
CORS(app, resources={r"/*": {"origins": "*"}})

# ================== 3. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ==================
token_pool = []
token_cycle = None
allowed_user_ids = []

# ================== 4. ЗАГРУЗКА ДОПУСТИМЫХ ID ==================
def load_allowed_users():
    global allowed_user_ids
    try:
        with open(ALLOWED_IDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            allowed_user_ids = data.get("allowed_users", [])
            print(f"[AUTH] Загружено {len(allowed_user_ids)} разрешённых ID.")
    except Exception as e:
        print(f"[AUTH ERROR] Не удалось загрузить allowed_ids.json: {e}")
        allowed_user_ids = []

# ================== 5. PLAYWRIGHT ЛОГИН ==================
def login_crm(username, password, p):
    browser = None
    try:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--single-process",
                "--no-zygote"
            ],
            timeout=30000
        )
        page = browser.new_page()
        page.goto(f"{BASE_URL}/auth/login", wait_until="load")
        page.fill("#username", username)
        page.fill("#password", password)
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        page.goto(f"{BASE_URL}/dashboard", wait_until="domcontentloaded")

        if "dashboard" not in page.url:
            print(f"[LOGIN FAIL] {username}")
            return None

        cookies = page.context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
        user_agent = page.evaluate("navigator.userAgent")
        csrf_token = next((c["value"] for c in cookies if c["name"] == "__Secure-csrf_token"), None)
        print(f"[LOGIN OK] {username}")
        return {"username": username, "csrf": csrf_token, "user_agent": user_agent, "cookie_header": cookie_header}
    except Exception as e:
        print(f"[LOGIN ERROR] {username}: {e}")
        return None
    finally:
        if browser:
            browser.close()

def init_token_pool():
    global token_pool, token_cycle
    with sync_playwright() as p:
        print("[INIT] Авторизация CRM...")
        token = login_crm(CRM_USER, CRM_PASS, p)
        if token:
            token_pool = [token]
            token_cycle = itertools.cycle(token_pool)
            print("[INIT OK] Токен успешно получен.")
        else:
            print("[INIT FAIL] Ошибка входа в CRM.")

def get_next_token():
    global token_cycle
    if not token_cycle:
        init_token_pool()
    if token_cycle:
        return next(token_cycle)
    return None

def crm_get(endpoint, params=None):
    token = get_next_token()
    if not token:
        return None
    headers = {
        "Accept": "application/json",
        "User-Agent": token["user_agent"],
        "Cookie": token["cookie_header"]
    }
    if token.get("csrf"):
        headers["X-CSRF-Token"] = token["csrf"]

    return requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=20)

# ================== 6. ПОИСКОВЫЕ ФУНКЦИИ ==================
def search_by_iin(iin):
    r = crm_get("/api/v2/person-search/by-iin", {"iin": iin})
    if not r:
        return "❌ Ошибка связи с CRM"
    if r.status_code == 404:
        return "⚠️ Не найдено"
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    p = r.json()
    return f"👤 {p.get('snf','')}\n🧾 {p.get('iin','')}\n📅 {p.get('birthday','')}\n📱 {p.get('phone_number','')}"

def search_by_phone(phone):
    clean = "".join(filter(str.isdigit, phone))
    if clean.startswith("8"):
        clean = "7" + clean[1:]
    r = crm_get("/api/v2/person-search/by-phone", {"phone": clean})
    if not r:
        return "❌ Ошибка связи с CRM"
    if r.status_code == 404:
        return "⚠️ Не найдено"
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    p = r.json()[0] if isinstance(r.json(), list) else r.json()
    return f"👤 {p.get('snf','')}\n🧾 {p.get('iin','')}\n📅 {p.get('birthday','')}\n📱 {p.get('phone_number','')}"

def search_by_fio(text):
    parts = text.split()
    params = {"smart_mode": "false", "limit": 10}
    if len(parts) >= 1: params["surname"] = parts[0]
    if len(parts) >= 2: params["name"] = parts[1]
    if len(parts) >= 3: params["father_name"] = parts[2]
    r = crm_get("/api/v2/person-search/smart", params)
    if not r:
        return "❌ Ошибка связи с CRM"
    if r.status_code == 404:
        return "⚠️ Не найдено"
    if r.status_code != 200:
        return f"❌ Ошибка {r.status_code}: {r.text}"
    data = r.json()
    if isinstance(data, dict):
        data = [data]
    results = [f"{p.get('snf','')} — {p.get('iin','')} — {p.get('birthday','')}" for p in data[:10]]
    return "\n".join(results)

# ================== 7. API ==================
@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.json
    user_id = data.get("telegram_user_id")
    if not user_id:
        return jsonify({"error": "ID пользователя не передан"}), 403
    if int(user_id) not in allowed_user_ids:
        return jsonify({"error": "Нет доступа"}), 403

    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Пустой запрос"}), 400

    if query.isdigit() and len(query) == 12:
        reply = search_by_iin(query)
    elif query.startswith("+") or query.startswith("8") or query.startswith("7"):
        reply = search_by_phone(query)
    else:
        reply = search_by_fio(query)

    return jsonify({"result": reply})

# ================== 8. ВЕБ-СТРАНИЦА ==================
@app.route("/")
def serve_index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(app.static_folder, path)

# ================== 9. ЗАПУСК ==================
if __name__ == "__main__":
    load_allowed_users()
    init_token_pool()
    app.run(host="0.0.0.0", port=8000)
