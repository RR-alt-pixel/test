# -*- coding: utf-8 -*-
import os
import time
import json
import random
import itertools
import traceback
import hashlib
from typing import Optional, Dict, List, Any
from urllib.parse import urlencode, urljoin
from datetime import datetime

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8545598161:AAGM6HtppAjUOuSAYH0mX5oNcPU0SuO59N4"
ALLOWED_USERS_URL = "https://raw.githubusercontent.com/RR-alt-pixel/test/refs/heads/main/allowed_ids.json"
ALLOWED_USER_IDS: List[int] = [0]

BASE_URL = "https://pena.rest"
LOGIN_PAGE = f"{BASE_URL}/auth/login"
SECRET_TOKEN = "Refresh-Server-Key-2025-Oct-VK44"

LOGIN_SELECTOR = 'input[placeholder="Логин"]'
PASSWORD_SELECTOR = 'input[placeholder="Пароль"]'
SIGN_IN_BUTTON_SELECTOR = 'button[type="submit"]'

accounts = [
    {"username": "klon9", "password": "7755SSaa"},
]

# ================== RESPONSE WRAPPER ==================
class ResponseLike:
    def __init__(self, status_code: int, text: str, json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        return self._json_data

# ================== PLAYWRIGHT ==================
class PWManager:
    def __init__(self):
        self.pw = sync_playwright().start()

    def create_session(self, username: str, password: str) -> Dict:
        browser = self.pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="ru-RU",
            ignore_https_errors=True
        )

        page = context.new_page()

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        page.goto(LOGIN_PAGE, wait_until="networkidle")
        time.sleep(1)

        page.fill(LOGIN_SELECTOR, username)
        page.fill(PASSWORD_SELECTOR, password)
        page.click(SIGN_IN_BUTTON_SELECTOR)

        page.wait_for_timeout(3000)
        page.goto(f"{BASE_URL}/dashboard/search", wait_until="networkidle")
        time.sleep(2)

        cookies = context.cookies()
        cookies_dict = {c["name"]: c["value"] for c in cookies}
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        fingerprint = hashlib.sha256(
            (username + str(time.time())).encode()
        ).hexdigest()

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            "x-device-fingerprint": fingerprint,
            "cookie": cookie_header,
            "referer": f"{BASE_URL}/dashboard/search",
        }

        return {
            "username": username,
            "browser": browser,
            "context": context,
            "headers": headers,
            "created_at": time.time(),
        }

    def request(self, session: Dict, endpoint: str, params: dict = None):
        url = urljoin(BASE_URL, endpoint)
        if params:
            url += "?" + urlencode(params)

        resp = session["context"].request.get(url, headers=session["headers"])
        try:
            data = resp.json()
        except:
            data = None

        return ResponseLike(resp.status, resp.text(), data)

pw_manager = PWManager()
sessions: List[Dict] = []

def init_sessions():
    global sessions
    sessions = []
    for acc in accounts:
        sessions.append(
            pw_manager.create_session(acc["username"], acc["password"])
        )

def get_session():
    if not sessions:
        init_sessions()
    return sessions[0]

# ================== CRM ==================
def crm_get(endpoint: str, params: dict = None):
    session = get_session()
    return pw_manager.request(session, endpoint, params)

# ================== SEARCH ==================
def search_by_iin(iin: str):
    resp = crm_get("/api/v3/search/iin", {"iin": iin})

    if resp.status_code != 200:
        return f"Ошибка {resp.status_code}: {resp.text}"

    return json.dumps(resp.json(), ensure_ascii=False, indent=2)

def search_by_phone(phone: str):
    resp = crm_get("/api/v3/search/phone", {"phone": phone})
    return json.dumps(resp.json(), ensure_ascii=False, indent=2)

def search_by_fio(fio: str):
    parts = fio.split()
    params = {}
    if len(parts) > 0: params["surname"] = parts[0]
    if len(parts) > 1: params["name"] = parts[1]
    if len(parts) > 2: params["father_name"] = parts[2]
    resp = crm_get("/api/v3/search/fio", params)
    return json.dumps(resp.json(), ensure_ascii=False, indent=2)

# ================== FLASK ==================
app = Flask(__name__)
CORS(app)

active_sessions = {}
SESSION_TTL = 3600

def load_allowed_users():
    global ALLOWED_USER_IDS
    try:
        r = requests.get(ALLOWED_USERS_URL, timeout=10)
        ALLOWED_USER_IDS = r.json().get("allowed_users", [])
    except:
        ALLOWED_USER_IDS = [0]

@app.route("/api/session/start", methods=["POST"])
def start_session():
    load_allowed_users()
    uid = int(request.json.get("telegram_user_id"))
    if uid not in ALLOWED_USER_IDS:
        return jsonify({"error": "Нет доступа"}), 403
    token = f"{uid}-{int(time.time())}"
    active_sessions[uid] = {"token": token, "created": time.time()}
    return jsonify({"session_token": token})

@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.json
    query = data.get("query", "").strip()

    if query.isdigit() and len(query) == 12:
        result = search_by_iin(query)
    elif query.startswith(("+", "7", "8")):
        result = search_by_phone(query)
    else:
        result = search_by_fio(query)

    return jsonify({"result": result})

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "sessions": len(sessions),
        "time": datetime.now().isoformat()
    })

# ================== START ==================
if __name__ == "__main__":
    init_sessions()
    app.run(host="0.0.0.0", port=5000, debug=False)
