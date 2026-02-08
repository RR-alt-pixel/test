# -*- coding: utf-8 -*-
import os
import time
import json
import random
import itertools
import traceback
import hashlib
from threading import Thread, Lock, Event
from typing import Optional, Dict, List, Any
from queue import Queue
from urllib.parse import urlencode, urljoin
from datetime import datetime

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright

# ================== 1. НАСТРОЙКИ ==================
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

pw_sessions: List[Dict[str, Any]] = []
pw_cycle = None
PW_SESSIONS_LOCK = Lock()

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
        self._pw = None
        self.ready = Event()

    def start(self):
        self._pw = sync_playwright().start()
        self.ready.set()
        print("[PW] Playwright started")

    def create_session(self, username: str, password: str) -> Optional[Dict]:
        browser = None
        try:
            browser = self._pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/145.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
            )

            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            page.goto(LOGIN_PAGE, wait_until="networkidle")
            time.sleep(1)

            page.fill(LOGIN_SELECTOR, username)
            time.sleep(0.3)
            page.fill(PASSWORD_SELECTOR, password)
            time.sleep(0.3)
            page.click(SIGN_IN_BUTTON_SELECTOR)

            page.wait_for_timeout(4000)
            page.goto(f"{BASE_URL}/dashboard/search", wait_until="networkidle")

            cookies = context.cookies()
            cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

            fingerprint = hashlib.sha256(
                f"{username}{time.time()}{random.random()}".encode()
            ).hexdigest()

            headers = {
                "accept": "application/json",
                "accept-language": "ru-RU,ru;q=0.9",
                "content-type": "application/json",
                "referer": f"{BASE_URL}/dashboard/search",
                "x-device-fingerprint": fingerprint,
                "cookie": cookie_header,
                "x-requested-with": "XMLHttpRequest"
            }

            print(f"[SESSION] OK {username}")

            return {
                "username": username,
                "browser": browser,
                "context": context,
                "headers": headers,
                "fingerprint": fingerprint,
                "created_at": int(time.time()),
            }

        except Exception as e:
            print("[SESSION ERROR]", e)
            traceback.print_exc()
            if browser:
                browser.close()
            return None

    def request(self, session: Dict, endpoint: str, params: dict = None):
        url = urljoin(BASE_URL, endpoint)
        if params:
            url += "?" + urlencode(params)

        r = session["context"].request.get(
            url,
            headers=session["headers"],
            timeout=30000
        )

        return {
            "status": r.status,
            "text": r.text(),
            "json": r.json() if r.status == 200 else None,
            "ok": r.status == 200
        }

pw_manager = PWManager()
pw_manager.start()
pw_manager.ready.wait(10)

# ================== ПУЛ ==================
def init_token_pool():
    global pw_sessions, pw_cycle
    sessions = []

    for acc in accounts:
        s = pw_manager.create_session(acc["username"], acc["password"])
        if s:
            sessions.append(s)

    with PW_SESSIONS_LOCK:
        pw_sessions = sessions
        pw_cycle = itertools.cycle(pw_sessions)

    print(f"[POOL] sessions={len(pw_sessions)}")
    return bool(pw_sessions)

def get_next_session():
    with PW_SESSIONS_LOCK:
        return next(pw_cycle)

# ================== CRM ==================
def crm_get(endpoint, params=None):
    session = get_next_session()
    r = pw_manager.request(session, endpoint, params)
    return ResponseLike(r["status"], r["text"], r["json"])

# ================== QUEUE ==================
crm_queue = Queue()

def crm_worker():
    while True:
        func, args, box = crm_queue.get()
        try:
            box["result"] = func(*args)
        except Exception as e:
            box["error"] = str(e)
        crm_queue.task_done()

Thread(target=crm_worker, daemon=True).start()

def enqueue(endpoint, params=None):
    box = {}
    crm_queue.put((crm_get, (endpoint, params), box))
    while "result" not in box and "error" not in box:
        time.sleep(0.05)
    return box.get("result")

# ================== SEARCH ==================
def search_by_iin(iin):
    r = enqueue("/api/v3/search/iin", {"iin": iin})
    if r.status_code != 200:
        return r.text
    return json.dumps(r.json(), ensure_ascii=False, indent=2)

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
        ALLOWED_USER_IDS = []

@app.route("/api/session/start", methods=["POST"])
def start_session():
    load_allowed_users()
    uid = int(request.json.get("telegram_user_id", 0))
    if uid not in ALLOWED_USER_IDS:
        return jsonify({"error": "forbidden"}), 403
    token = f"{uid}-{int(time.time())}"
    active_sessions[uid] = {"token": token, "created": time.time()}
    return jsonify({"session_token": token})

@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.json
    uid = int(data["telegram_user_id"])
    token = data["session_token"]
    if uid not in active_sessions or active_sessions[uid]["token"] != token:
        return jsonify({"error": "bad session"}), 403
    query = data["query"]
    return jsonify({"result": search_by_iin(query)})

# ================== START ==================
print("BOOT")
load_allowed_users()
init_token_pool()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
